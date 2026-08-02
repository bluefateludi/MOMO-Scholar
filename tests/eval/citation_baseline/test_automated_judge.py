from __future__ import annotations

import json
import hashlib
import socket
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from paper_agent.eval.citation_baseline.automated_judge import (
    AUTOMATED_JUDGE_PROMPT_SHA256,
    AUTOMATED_JUDGE_RUBRIC_SHA256,
    AutomatedJudgeAuthority,
    AutomatedJudgeError,
    AutomatedJudgeInput,
    DashScopeAutomatedJudgeProvider,
    JudgePassage,
    JudgeProviderResult,
    run_automated_judge,
    seal_automated_citation_package,
    validate_automated_judge_authorities,
    verify_automated_citation_package,
)
from paper_agent.eval.citation_baseline.contracts import AtomicAssertion, CitationOccurrence
from paper_agent.generation.dashscope_transport import DashScopeChatTransport


OUTPUT_SHA = "a" * 64
GOLD_SHA = "b" * 64


def _authority(**updates: object) -> AutomatedJudgeAuthority:
    payload: dict[str, object] = {
        "data_kind": "synthetic",
        "provider": "fake-provider",
        "judge_model_version": "judge-fixture-2026-08-02",
        "generation_model_version": "qwen3.7-plus-2026-05-26",
        "model_authority": "https://provider.example/models/judge-fixture-2026-08-02",
        "authority_sha256": "c" * 64,
        "judge_base_url": "https://provider.example/v1",
        "pricing_authority": "https://provider.example/pricing/2026-08-02",
        "pricing_currency": "TEST",
        "input_cost_per_million_tokens": 1.0,
        "output_cost_per_million_tokens": 2.0,
        "rubric_version": "citation-llm-judge-v1",
        "rubric_sha256": AUTOMATED_JUDGE_RUBRIC_SHA256,
        "prompt_version": "citation-llm-judge-prompt-v1",
        "prompt_sha256": AUTOMATED_JUDGE_PROMPT_SHA256,
        "gold_evidence_sha256": GOLD_SHA,
        "generation_output_sha256": OUTPUT_SHA,
        "timeout_seconds": 5.0,
        "max_retries_per_pass": 1,
        "max_completion_tokens_per_send": 100,
        "max_prompt_tokens_per_send": 500,
        "max_total_sends": 20,
        "max_total_prompt_tokens": 10_000,
        "max_total_completion_tokens": 2_000,
        "max_total_cost": 1.0,
    }
    payload.update(updates)
    return AutomatedJudgeAuthority.model_validate(payload)


def _input(assertion_id: str, *, deterministic: bool = False) -> AutomatedJudgeInput:
    return AutomatedJudgeInput(
        case_id=f"private-{assertion_id}",
        run_id=f"run-{assertion_id}",
        blinded_case_id=f"blind-{assertion_id}",
        assertion_id=assertion_id,
        assertion_text=f"Assertion {assertion_id}.",
        citation_occurrence_ids=(f"citation-{assertion_id}",),
        cited_passages=(
            JudgePassage(evidence_id=f"actual-{assertion_id}", text="Actual evidence."),
        ),
        gold_passages=(
            JudgePassage(evidence_id=f"gold-{assertion_id}", text="Gold evidence."),
        ),
        deterministic_support_match_ids=(f"match-{assertion_id}",) if deterministic else (),
        output_sha256=OUTPUT_SHA,
        evidence_sha256="d" * 64,
        gold_evidence_sha256=GOLD_SHA,
        config_sha256="e" * 64,
    )


class FakeProvider:
    def __init__(self, results: dict[tuple[str, int], str]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def judge(self, *, payload, pass_index, timeout_seconds):
        assert "case_id" not in payload
        assert "run_id" not in payload
        assert timeout_seconds == 5.0
        assertion_id = payload["assertion_id"]
        self.calls.append((assertion_id, pass_index))
        return JudgeProviderResult(
            result=self.results[(assertion_id, pass_index)],
            rationale="Grounded fixture rationale.",
            evidence_references=(f"actual-{assertion_id}", f"gold-{assertion_id}"),
            prompt_tokens=40,
            completion_tokens=10,
            model_version="judge-fixture-2026-08-02",
        )


class InvalidSemanticResponseTransport:
    def send(self, **_kwargs):
        return SimpleNamespace(
            content="not-json",
            model="judge-fixture-2026-08-02",
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )


class CapturingSemanticResponseTransport:
    def __init__(self) -> None:
        self.kwargs = None

    def send(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=json.dumps(
                {"result": "supported", "rationale": "fixture", "evidence_references": []}
            ),
            model="judge-fixture-2026-08-02",
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )


def _forbid_network(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline automated judge test attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)


def test_authority_requires_distinct_models_and_frozen_prompt_rubric() -> None:
    with pytest.raises(ValidationError, match="differ"):
        _authority(judge_model_version="qwen3.7-plus-2026-05-26")
    with pytest.raises(ValidationError, match="prompt hash"):
        _authority(prompt_sha256="f" * 64)
    with pytest.raises(ValidationError, match="rubric hash"):
        _authority(rubric_sha256="f" * 64)


def test_single_blinded_pass_and_deterministic_match_are_resumable(
    tmp_path,
    monkeypatch,
) -> None:
    _forbid_network(monkeypatch)
    provider = FakeProvider(
        {
            ("agree", 1): "supported",
            ("disagree", 1): "unsupported",
        }
    )
    inputs = (_input("deterministic", deterministic=True), _input("agree"), _input("disagree"))

    decisions = run_automated_judge(
        output=tmp_path,
        authority=_authority(),
        inputs=inputs,
        provider=provider,
    )

    assert provider.calls == [
        ("agree", 1),
        ("disagree", 1),
    ]
    by_id = {item.assertion_id: item for item in decisions}
    assert by_id["deterministic"].decision_source == "deterministic_gold_match"
    assert by_id["deterministic"].pass_ids == ()
    assert by_id["agree"].decision_source == "single_pass"
    assert len(by_id["agree"].pass_ids) == 1
    assert by_id["disagree"].decision_source == "single_pass"
    assert by_id["disagree"].semantic_verdict == "unsupported"
    assert len(by_id["disagree"].pass_ids) == 1
    assert validate_automated_judge_authorities(tmp_path) == decisions

    resumed = run_automated_judge(
        output=tmp_path,
        authority=_authority(),
        inputs=inputs,
        provider=provider,
    )
    assert resumed == decisions
    assert len(provider.calls) == 2
    persisted = "".join(path.read_text() for path in tmp_path.iterdir())
    assert "private-agree" in persisted
    assert "private-agree" not in json.dumps(
        {
            "instruction": "provider payloads are not persisted",
        }
    )


def test_budget_gate_blocks_before_provider_call(tmp_path) -> None:
    provider = FakeProvider({("a", 1): "supported", ("a", 2): "supported"})
    with pytest.raises(AutomatedJudgeError, match="budget exhausted"):
        run_automated_judge(
            output=tmp_path,
            authority=_authority(max_total_sends=2, max_total_prompt_tokens=499),
            inputs=(_input("a"),),
            provider=provider,
        )
    assert provider.calls == []


def test_local_semantic_schema_failure_is_not_mislabeled_as_provider_error(
    tmp_path,
) -> None:
    authority = _authority(max_retries_per_pass=0)
    provider = DashScopeAutomatedJudgeProvider(
        api_key="fixture-key",
        base_url=authority.judge_base_url,
        authority=authority,
        transport=InvalidSemanticResponseTransport(),
    )

    with pytest.raises(AutomatedJudgeError):
        run_automated_judge(
            output=tmp_path,
            authority=authority,
            inputs=(_input("invalid-semantic-response"),),
            provider=provider,
        )

    failure = json.loads((tmp_path / "automated-judge-failures.jsonl").read_text())
    assert failure["reason_code"] == "judge_contract_error"


def test_provider_failure_persists_only_safe_http_diagnostics(tmp_path) -> None:
    authority = _authority(max_retries_per_pass=0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "code": "InvalidParameter",
                "type": "invalid_request_error",
                "param": "response_format",
                "request_id": "req-safe-123",
                "message": "must-never-persist sk-secret prompt-body",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = DashScopeAutomatedJudgeProvider(
            api_key="must-never-persist-key",
            base_url=authority.judge_base_url,
            authority=authority,
            transport=DashScopeChatTransport(client),
        )
        with pytest.raises(AutomatedJudgeError):
            run_automated_judge(
                output=tmp_path,
                authority=authority,
                inputs=(_input("safe-http-diagnostics"),),
                provider=provider,
            )

    failure_text = (tmp_path / "automated-judge-failures.jsonl").read_text()
    failure = json.loads(failure_text)
    assert failure["http_status"] == 400
    assert failure["provider_error_code"] == "InvalidParameter"
    assert failure["provider_error_type"] == "invalid_request_error"
    assert failure["provider_error_parameter"] == "response_format"
    assert failure["provider_request_id"] == "req-safe-123"
    assert "must-never-persist" not in failure_text
    assert "prompt-body" not in failure_text
    assert "secret" not in failure_text


def test_judge_json_mode_prompt_contains_required_json_keyword() -> None:
    authority = _authority(max_retries_per_pass=0)
    transport = CapturingSemanticResponseTransport()
    provider = DashScopeAutomatedJudgeProvider(
        api_key="fixture-key",
        base_url=authority.judge_base_url,
        authority=authority,
        transport=transport,
    )

    result = provider.judge(
        payload={
            "assertion_id": "a",
            "assertion": "A.",
            "cited_passages": [],
            "gold_passages": [],
        },
        pass_index=1,
        timeout_seconds=5.0,
    )

    assert result.result == "supported"
    assert "JSON" in transport.kwargs["messages"][0].content


def test_retry_accounting_survives_process_restart(tmp_path) -> None:
    class SimulatedCrash(BaseException):
        pass

    class CrashProvider:
        def judge(self, **_kwargs):
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        run_automated_judge(
            output=tmp_path,
            authority=_authority(),
            inputs=(_input("a"),),
            provider=CrashProvider(),
        )

    class FailingProvider:
        def __init__(self) -> None:
            self.calls = 0

        def judge(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("do-not-persist")

    second = FailingProvider()
    with pytest.raises(AutomatedJudgeError, match="pass failed"):
        run_automated_judge(
            output=tmp_path,
            authority=_authority(),
            inputs=(_input("a"),),
            provider=second,
        )
    assert second.calls == 1

    third = FailingProvider()
    with pytest.raises(AutomatedJudgeError, match="retry budget exhausted"):
        run_automated_judge(
            output=tmp_path,
            authority=_authority(),
            inputs=(_input("a"),),
            provider=third,
        )
    assert third.calls == 0
    sends = [
        json.loads(line)
        for line in (tmp_path / "automated-judge-sends.jsonl").read_text().splitlines()
    ]
    assert [row["attempt_index"] for row in sends] == [1, 2]


def test_failures_are_sanitized_and_tampering_is_rejected(tmp_path) -> None:
    class FailingProvider:
        def judge(self, **_kwargs):
            raise RuntimeError("secret-provider-message")

    with pytest.raises(AutomatedJudgeError, match="pass failed"):
        run_automated_judge(
            output=tmp_path,
            authority=_authority(),
            inputs=(_input("a"),),
            provider=FailingProvider(),
        )
    persisted = "".join(path.read_text() for path in tmp_path.iterdir())
    assert "secret-provider-message" not in persisted
    assert "judge_provider_error" in persisted
    failure = json.loads((tmp_path / "automated-judge-failures.jsonl").read_text())
    assert failure["case_id"] == "private-a"
    assert failure["judge_model_version"] == "judge-fixture-2026-08-02"
    assert failure["rubric_sha256"] == AUTOMATED_JUDGE_RUBRIC_SHA256
    assert failure["prompt_sha256"] == AUTOMATED_JUDGE_PROMPT_SHA256
    assert failure["gold_evidence_sha256"] == GOLD_SHA
    assert failure["output_sha256"] == OUTPUT_SHA
    assert failure["send_indices"] == [1, 2]
    assert failure["prompt_tokens_accounted"] == 1000
    assert failure["completion_tokens_accounted"] == 200
    assert failure["cost_accounted"] > 0


def test_validator_rejects_method_relabel_and_missing_pass(tmp_path) -> None:
    provider = FakeProvider(
        {
            ("a", 1): "supported",
        }
    )
    run_automated_judge(
        output=tmp_path,
        authority=_authority(),
        inputs=(_input("a"),),
        provider=provider,
    )
    decisions_path = tmp_path / "automated-judge-decisions.jsonl"
    decision = json.loads(decisions_path.read_text())
    decision["evaluation_method"] = "human_review"
    decisions_path.write_text(json.dumps(decision) + "\n")
    with pytest.raises((ValidationError, AutomatedJudgeError)):
        validate_automated_judge_authorities(tmp_path)

    # Restore the decision but remove its only semantic pass.
    decision["evaluation_method"] = "llm_as_judge_single_pass"
    decisions_path.write_text(json.dumps(decision) + "\n")
    passes_path = tmp_path / "automated-judge-passes.jsonl"
    rows = [json.loads(line) for line in passes_path.read_text().splitlines()]
    passes_path.write_text(
        ""
    )
    with pytest.raises(AutomatedJudgeError, match="missing"):
        validate_automated_judge_authorities(tmp_path)


def _write_json(path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _write_jsonl(path, values) -> None:
    path.write_text(
        "".join(
            json.dumps(
                value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for value in values
        )
    )


def test_automated_package_seal_recompute_verify_and_method_label(tmp_path) -> None:
    prepared = tmp_path / "prepared"
    provider = FakeProvider(
        {
            ("assertion-a", 1): "supported",
            ("assertion-a", 2): "supported",
            ("assertion-b", 1): "unsupported",
            ("assertion-b", 2): "unsupported",
        }
    )
    inputs = (_input("assertion-a"), _input("assertion-b"))
    run_automated_judge(
        output=prepared,
        authority=_authority(),
        inputs=inputs,
        provider=provider,
    )
    assertions = tuple(
        AtomicAssertion(
            schema_version="1.0",
            assertion_id=item.assertion_id,
            case_id=item.case_id,
            run_id=item.run_id,
            text=item.assertion_text,
            source_section="summary",
            start_char=0,
            end_char=len(item.assertion_text),
        )
        for item in inputs
    )
    occurrences = tuple(
        CitationOccurrence(
            schema_version="1.0",
            occurrence_id=item.citation_occurrence_ids[0],
            assertion_id=item.assertion_id,
            evidence_id=item.cited_passages[0].evidence_id,
            source_section="summary",
            start_char=1,
            end_char=2,
            structurally_valid=True,
        )
        for item in inputs
    )
    _write_json(
        prepared / "dataset-manifest.json",
        {
            "dataset_id": "fixture",
            "dataset_version": "1",
            "selected_split": "validation",
            "data_kind": "synthetic",
            "dataset_fingerprint_sha256": "f" * 64,
        },
    )
    _write_json(prepared / "corpus-manifest.json", {"corpus_sha256": "1" * 64})
    _write_jsonl(prepared / "gold-judgments.jsonl", ({"case_id": item.case_id} for item in inputs))
    _write_json(
        prepared / "resolved-config.json",
        {
            "schema_version": "1.0",
            "metric_versions": ["citation-llm-as-judge/1.0"],
            "ordered_chunk_sha256": ["2" * 64],
            "cases": [
                {
                    "case_id": item.case_id,
                    "duration_ms": 0.0,
                    "unscorable_assertion_ids": [],
                    "failure_reason_code": None,
                }
                for item in inputs
            ],
        },
    )
    _write_json(
        prepared / "environment.json",
        {
            "git_sha": "3" * 40,
            "git_dirty": False,
            "models": {
                "generation": "qwen3.7-plus-2026-05-26",
                "judge": "judge-fixture-2026-08-02",
            },
        },
    )
    _write_jsonl(prepared / "assertions.jsonl", assertions)
    _write_jsonl(prepared / "citation-occurrences.jsonl", occurrences)
    _write_jsonl(prepared / "evidence-matches.jsonl", ())
    for name in ("failures.jsonl", "logs.jsonl", "traces.jsonl"):
        (prepared / name).write_text("")

    package = tmp_path / "package"
    manifest = seal_automated_citation_package(prepared, package)

    assert manifest["evaluation_method"] == "llm_as_judge_single_pass"
    assert verify_automated_citation_package(package) == manifest
    assert json.loads((package / "aggregate.json").read_text())[
        "evaluation_method"
    ] == "llm_as_judge_single_pass"
    report = (package / "report.md").read_text()
    resume = (package / "resume-evidence.md").read_text()
    assert "Gold-grounded single-pass LLM-as-Judge" in report
    assert "No resume-ready numeric claims" in resume
    assert "Cohen" not in report

    manifest_path = package / "artifact-manifest.json"
    changed = json.loads(manifest_path.read_text())
    changed["evaluation_method"] = "human_review"
    _write_json(manifest_path, changed)
    with pytest.raises(AutomatedJudgeError, match="method"):
        verify_automated_citation_package(package)


def test_cli_automated_preflight_is_offline_and_paid_run_requires_ack(
    tmp_path,
    monkeypatch,
) -> None:
    from paper_agent.eval.citation_baseline.cli import app

    _forbid_network(monkeypatch)
    generation = tmp_path / "generation"
    generation.mkdir()
    case_ids = [f"case-{index:02d}" for index in range(20)]
    output_rows = [
        {"case_id": case_id, "checked_output": {"claims": []}}
        for case_id in case_ids
    ]
    _write_jsonl(generation / "pipeline-outputs.jsonl", output_rows)
    output_sha = hashlib.sha256((generation / "pipeline-outputs.jsonl").read_bytes()).hexdigest()
    gold_rows = [{"case_id": case_id} for case_id in case_ids]
    _write_jsonl(generation / "gold-judgments.jsonl", gold_rows)
    gold_sha = hashlib.sha256((generation / "gold-judgments.jsonl").read_bytes()).hexdigest()
    _write_jsonl(
        generation / "case-results.jsonl",
        ({"case_id": case_id, "status": "completed"} for case_id in case_ids),
    )
    _write_jsonl(
        generation / "evidence.jsonl",
        ({"case_id": case_id, "evidence": []} for case_id in case_ids),
    )
    _write_json(
        generation / "generation-manifest.json",
        {
            "status": "completed",
            "request_model": "qwen3.7-plus-2026-05-26",
            "resolved_response_models": ["qwen3.7-plus-2026-05-26"],
            "output_sha256": output_sha,
            "selected_case_ids": case_ids,
            "failed_case_ids": [],
            "provider_send_count": 20,
        },
    )
    authority = _authority(
        generation_output_sha256=output_sha,
        gold_evidence_sha256=gold_sha,
    )
    authority_path = tmp_path / "authority.json"
    _write_json(authority_path, authority.model_dump(mode="json"))
    item = _input("a").model_copy(
        update={"output_sha256": output_sha, "gold_evidence_sha256": gold_sha}
    )
    inputs_path = tmp_path / "inputs.jsonl"
    _write_jsonl(inputs_path, (item,))

    runner = CliRunner()
    preflight = runner.invoke(
        app,
        [
            "preflight-automated-judge",
            "--generation",
            str(generation),
            "--authority",
            str(authority_path),
            "--inputs",
            str(inputs_path),
        ],
    )
    assert preflight.exit_code == 0, preflight.output
    assert '"provider_calls":0' in preflight.output
    assert '"minimum_judge_passes":1' in preflight.output
    paid = runner.invoke(
        app,
        [
            "run-automated-judge",
            "--generation",
            str(generation),
            "--authority",
            str(authority_path),
            "--inputs",
            str(inputs_path),
            "--output",
            str(tmp_path / "paid-output"),
        ],
    )
    assert paid.exit_code == 2
    assert "acknowledge-provider-costs" in paid.output
    assert not (tmp_path / "paid-output").exists()
