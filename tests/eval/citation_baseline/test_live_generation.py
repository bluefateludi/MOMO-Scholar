from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from paper_agent.eval.citation_baseline.live_generation import (
    GenerationBudgetLedger,
    LiveGenerationConfig,
    run_live_generation,
)
from paper_agent.generation import (
    GenerationFailureMetadata,
    GenerationTimeoutError,
    StructuredGeneration,
)
from paper_agent.generation.dashscope_transport import (
    GenerationHttpResponse,
    GenerationUsage,
)
from paper_agent.synthesis.models import GroundedClaim, SurveyDraft


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _prepared(root: Path) -> Path:
    prepared = root / "prepared"
    prepared.mkdir()
    case_ids = ["case-a", "case-b"]
    (prepared / "dataset-manifest.json").write_text(
        _canonical_json({"data_kind": "real", "dataset_fingerprint_sha256": "a" * 64}),
        encoding="utf-8",
    )
    (prepared / "corpus-manifest.json").write_text(
        _canonical_json({"schema_version": "1.0", "corpus_sha256": "b" * 64}),
        encoding="utf-8",
    )
    (prepared / "gold-judgments.jsonl").write_text("", encoding="utf-8")
    (prepared / "resolved-config.json").write_text(
        _canonical_json({"schema_version": "1.0", "ordered_case_ids": case_ids}),
        encoding="utf-8",
    )
    rows = []
    for index, case_id in enumerate(case_ids, start=1):
        rows.append(
            {
                "case_id": case_id,
                "question": f"Question {index}?",
                "chunks": [
                    {
                        "chunk_id": f"chunk-{index}",
                        "paper_id": f"paper-{index}",
                        "section": "Abstract",
                        "page": None,
                        "text": f"Frozen evidence {index}.",
                        "token_count": 3,
                    }
                ],
            }
        )
    (prepared / "prepared-cases.jsonl").write_text(
        "".join(_canonical_json(row) for row in rows), encoding="utf-8"
    )
    return prepared


def _config(**updates: object) -> LiveGenerationConfig:
    values: dict[str, object] = {
        "request_model": "qwen3.7-plus",
        "temperature": 0.0,
        "max_tokens": 512,
        "attempt_timeout_seconds": 60.0,
        "max_sends_per_case": 4,
        "max_total_sends": 8,
        "case_limit": 2,
        "max_prompt_tokens_per_send": 20_000,
        "pricing_authority": "https://pricing.example/model",
        "input_usd_per_million_tokens": 1.0,
        "output_usd_per_million_tokens": 3.0,
        "max_cost_usd": 0.25,
    }
    values.update(updates)
    return LiveGenerationConfig.model_validate(values)


def _environment() -> dict[str, object]:
    return {
        "git_sha": "d" * 40,
        "git_dirty": False,
        "python_version": "3.test",
    }


class LedgerFakeProvider:
    def __init__(self, case_id, ledger, config, outcome, calls):
        self.case_id = case_id
        self.ledger = ledger
        self.config = config
        self.outcome = outcome
        self.calls = calls

    def generate_structured(self, *, operation, messages, response_schema, timeout):
        self.calls.append(self.case_id)
        sequence = self.ledger.reserve(
            case_id=self.case_id,
            messages=messages,
            model=self.config.request_model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            timeout=timeout,
        )
        if isinstance(self.outcome, Exception):
            self.ledger.complete(sequence, failure_reason_code="generation_timeout_error")
            raise self.outcome
        payload = json.loads(messages[1].content)
        evidence_id = payload["evidence"][0]["evidence_id"]
        claim = GroundedClaim(text=f"Answer for {self.case_id}.", evidence_ids=[evidence_id])
        draft = SurveyDraft(
            tldr_claims=[claim],
            method_taxonomy=[],
            comparisons=[],
            key_findings=[claim],
            limitations=[],
            open_questions=[],
        )
        response = GenerationHttpResponse(
            content="{}",
            model="qwen3.7-plus-2026-08-01",
            usage=GenerationUsage(prompt_tokens=40, completion_tokens=20, total_tokens=60),
        )
        self.ledger.complete(sequence, response=response)
        return StructuredGeneration(
            result=draft,
            model=response.model,
            prompt_tokens=40,
            completion_tokens=20,
            total_tokens=60,
            attempts=1,
            elapsed_seconds=0.01,
        )


def _factory(config, outcomes, calls):
    def create(case_id, ledger):
        outcome = outcomes[case_id].pop(0)
        return LedgerFakeProvider(case_id, ledger, config, outcome, calls)

    return create


def _forbid_network(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline fake-provider test attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)


def test_runner_is_offline_records_frozen_request_and_stable_outputs(tmp_path, monkeypatch):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-read")
    prepared = _prepared(tmp_path)
    output = tmp_path / "experiment"
    config = _config()
    calls = []
    outcomes = {"case-a": [None], "case-b": [None]}

    manifest = run_live_generation(
        prepared=prepared,
        output=output,
        config=config,
        environment=_environment(),
        provider_factory=_factory(config, outcomes, calls),
    )

    assert manifest["status"] == "completed"
    assert manifest["output_sha256"] is not None
    assert manifest["provider_send_count"] == 2
    assert manifest["resolved_response_models"] == ["qwen3.7-plus-2026-08-01"]
    assert calls == ["case-a", "case-b"]
    sends = [
        json.loads(line)
        for line in (output / "provider-sends.jsonl").read_text().splitlines()
    ]
    assert {(row["temperature"], row["max_tokens"], row["timeout_seconds"]) for row in sends} == {
        (0.0, 512, 60.0)
    }
    assert all(
        row["authorized_cost_ceiling_usd"] == config.max_cost_per_send_usd
        for row in sends
    )
    results = [
        json.loads(line)
        for line in (output / "case-results.jsonl").read_text().splitlines()
    ]
    assert all(row["output_sha256"] and row["evidence_sha256"] for row in results)
    assert all(row["prompt_tokens"] == 40 and row["completion_tokens"] == 20 for row in results)
    persisted = "".join(
        path.read_text() for path in output.iterdir() if path.is_file()
    )
    assert "must-not-be-read" not in persisted


def test_resume_keeps_successful_case_and_only_retries_failed_case(tmp_path, monkeypatch):
    _forbid_network(monkeypatch)
    prepared = _prepared(tmp_path)
    output = tmp_path / "experiment"
    config = _config()
    calls = []
    timeout = GenerationTimeoutError(
        metadata=GenerationFailureMetadata(attempts=1, elapsed_seconds=60.0)
    )
    first_outcomes = {"case-a": [None], "case-b": [timeout]}

    first = run_live_generation(
        prepared=prepared,
        output=output,
        config=config,
        environment=_environment(),
        provider_factory=_factory(config, first_outcomes, calls),
    )
    assert first["completed_case_ids"] == ["case-a"]
    assert first["failed_case_ids"] == ["case-b"]

    second_outcomes = {"case-a": [], "case-b": [None]}
    second = run_live_generation(
        prepared=prepared,
        output=output,
        config=config,
        environment=_environment(),
        provider_factory=_factory(config, second_outcomes, calls),
    )

    assert second["status"] == "completed"
    assert calls == ["case-a", "case-b", "case-b"]
    assert second["provider_send_count"] == 3
    assert len((output / "pipeline-outputs.jsonl").read_text().splitlines()) == 2
    assert len((output / "failures.jsonl").read_text().splitlines()) == 1


def test_validated_draft_prevents_rebilling_after_post_generation_failure(
    tmp_path, monkeypatch
):
    from paper_agent.eval.citation_baseline import live_generation

    prepared = _prepared(tmp_path)
    output = tmp_path / "experiment"
    config = _config(case_limit=1, max_total_sends=4)
    calls = []
    outcomes = {"case-a": [None], "case-b": []}
    real_checker = live_generation.check_survey_draft
    monkeypatch.setattr(
        live_generation,
        "check_survey_draft",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("postprocess")),
    )
    first = run_live_generation(
        prepared=prepared,
        output=output,
        config=config,
        environment=_environment(),
        provider_factory=_factory(config, outcomes, calls),
    )
    assert first["status"] == "incomplete"
    assert calls == ["case-a"]
    assert len((output / "generation-drafts.jsonl").read_text().splitlines()) == 1

    monkeypatch.setattr(live_generation, "check_survey_draft", real_checker)
    second = run_live_generation(
        prepared=prepared,
        output=output,
        config=config,
        environment=_environment(),
        provider_factory=lambda *_args: pytest.fail("draft resume must not call provider"),
    )
    assert second["status"] == "completed"
    assert second["provider_send_count"] == 1


def test_errors_are_reason_codes_only_and_never_persist_exception_text(tmp_path):
    prepared = _prepared(tmp_path)
    output = tmp_path / "experiment"
    config = _config()
    calls = []
    secret = "sk-should-never-be-persisted"
    outcomes = {"case-a": [ValueError(secret)], "case-b": [None]}

    run_live_generation(
        prepared=prepared,
        output=output,
        config=config,
        environment=_environment(),
        provider_factory=_factory(config, outcomes, calls),
    )

    persisted = "".join(path.read_text() for path in output.iterdir() if path.is_file())
    assert secret not in persisted
    assert "citation_output_validation_error" in persisted


def test_budget_is_reserved_before_send_and_enforces_case_and_batch_caps(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    config = _config(max_total_sends=2, case_limit=2, max_sends_per_case=1)
    ledger = GenerationBudgetLedger(root, config)
    messages = ()
    for case_id in ("case-a", "case-b"):
        ledger.reserve(
            case_id=case_id,
            messages=messages,
            model=config.request_model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.attempt_timeout_seconds,
        )
    with pytest.raises(Exception, match="generation_budget_exceeded"):
        ledger.reserve(
            case_id="case-b",
            messages=messages,
            model=config.request_model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.attempt_timeout_seconds,
        )
    assert len((root / "provider-sends.jsonl").read_text().splitlines()) == 2


def test_resume_rejects_changed_config_git_or_nested_output(tmp_path):
    prepared = _prepared(tmp_path)
    output = tmp_path / "experiment"
    config = _config()
    outcomes = {"case-a": [None], "case-b": [None]}
    run_live_generation(
        prepared=prepared,
        output=output,
        config=config,
        environment=_environment(),
        provider_factory=_factory(config, outcomes, []),
    )
    with pytest.raises(ValueError, match="changed"):
        run_live_generation(
            prepared=prepared,
            output=output,
            config=_config(max_tokens=256),
            environment=_environment(),
            provider_factory=_factory(config, {"case-a": [], "case-b": []}, []),
        )
    changed_environment = _environment()
    changed_environment["git_sha"] = "e" * 40
    with pytest.raises(ValueError, match="changed"):
        run_live_generation(
            prepared=prepared,
            output=output,
            config=config,
            environment=changed_environment,
            provider_factory=_factory(config, {"case-a": [], "case-b": []}, []),
        )
    with pytest.raises(ValueError, match="outside"):
        run_live_generation(
            prepared=prepared,
            output=prepared / "nested",
            config=config,
            environment=_environment(),
            provider_factory=_factory(config, {"case-a": [], "case-b": []}, []),
        )


def test_config_rejects_a_non_executable_cost_ceiling() -> None:
    with pytest.raises(ValueError, match="exceeds max_cost_usd"):
        _config(
            input_usd_per_million_tokens=100.0,
            output_usd_per_million_tokens=100.0,
            max_cost_usd=0.01,
        )


def test_cli_requires_cost_ack_and_checks_offline_gates_before_credentials(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.cli import app
    from paper_agent.eval.citation_baseline import cli as citation_cli

    prepared = _prepared(tmp_path)
    output = tmp_path / "experiment"
    arguments = [
        "citation-baseline",
        "run-live-generation",
        "--prepared",
        str(prepared),
        "--output",
        str(output),
        "--max-tokens",
        "512",
        "--max-total-sends",
        "8",
        "--max-prompt-tokens-per-send",
        "20000",
        "--input-usd-per-million-tokens",
        "1",
        "--output-usd-per-million-tokens",
        "3",
        "--pricing-authority",
        "https://pricing.example/model",
    ]
    runner = CliRunner()
    monkeypatch.setattr(
        citation_cli,
        "load_settings",
        lambda: pytest.fail("credentials must not be read before offline gates pass"),
    )

    missing_ack = runner.invoke(app, arguments)
    assert missing_ack.exit_code == 2
    assert not output.exists()

    monkeypatch.setattr(
        citation_cli,
        "_git_environment",
        lambda: {"git_sha": "d" * 40, "git_dirty": True},
    )
    dirty = runner.invoke(app, [*arguments, "--acknowledge-provider-costs"])
    assert dirty.exit_code == 2
    assert "dirty" in dirty.output.lower()
    assert not output.exists()
