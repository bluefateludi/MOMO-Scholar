from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from paper_agent.config import Settings
from paper_agent.eval.evidence_package import EvidencePackageBuilder
from paper_agent.eval.retrieval_benchmark.contracts import (
    CaseRetrievalResult,
    ModeFailure,
    RankedCandidate,
    RawRanking,
    RetrievalBenchmarkConfig,
)
from paper_agent.eval.retrieval_benchmark.statistics import score_benchmark


runner = CliRunner()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _ranking(mode: str, *, case_id: str = "case-1") -> RawRanking:
    sources = {
        "keyword": ("lexical",),
        "vector": ("vector",),
        "hybrid_rrf": ("lexical", "vector"),
    }[mode]
    return RawRanking(
        schema_version="1.0",
        case_id=case_id,
        mode=mode,
        candidates=(
            RankedCandidate(
                chunk_id="chunk-r",
                rank=1,
                score=1.0,
                retrieval_sources=sources,
            ),
        ),
        started_at="2026-07-26T08:00:00Z",
        finished_at="2026-07-26T08:00:01Z",
        duration_ms=1.0,
    )


def _sealed_package(
    root: Path,
    *,
    corrupt_aggregate: bool = False,
    data_kind: str = "synthetic",
    case_count: int = 1,
    bootstrap_resamples: int = 10_000,
) -> Path:
    package = root / "experiment"
    builder = EvidencePackageBuilder(package)
    case_ids = tuple(f"case-{index + 1}" for index in range(case_count))
    config = RetrievalBenchmarkConfig(
        schema_version="1.0",
        dataset_fingerprint_sha256="a" * 64,
        ordered_case_ids=case_ids,
        corpus_sha256="b" * 64,
        ordered_chunk_sha256=("c" * 64,),
        candidate_limit=10,
        timeout_seconds=5.0,
        rrf_k=60,
        embedding_model="text-embedding-v4",
        embedding_model_version="text-embedding-v4@test",
        chunking_config_sha256="d" * 64,
        metric_versions=("retrieval-metrics/1.0",),
        ks=(1, 3, 5, 8, 10),
        primary_k=8,
        modes=("keyword", "vector", "hybrid_rrf"),
    )
    cases = tuple(
        CaseRetrievalResult(
            case_id=case_id,
            rankings=tuple(
                _ranking(mode, case_id=case_id)
                for mode in ("keyword", "vector", "hybrid_rrf")
            ),
            failures=(),
        )
        for case_id in case_ids
    )
    statistics = score_benchmark(
        cases=cases,
        relevance_by_case={case_id: {"chunk-r": 3} for case_id in case_ids},
        bootstrap_resamples=bootstrap_resamples,
    )
    aggregate = {
        "ks": statistics["ks"],
        "primary_k": statistics["primary_k"],
        "aggregate": statistics["aggregate"],
        "operations": statistics["operations"],
    }
    if corrupt_aggregate:
        aggregate["primary_k"] = 5
    confidence = {
        "bootstrap": statistics["bootstrap"],
        "aggregate_ci_95": statistics["aggregate_ci_95"],
        "paired_deltas": statistics["paired_deltas"],
    }
    builder.write_json("dataset-manifest.json", {"data_kind": data_kind})
    builder.write_json("corpus-manifest.json", {"corpus_sha256": "b" * 64})
    builder.write_text(
        "gold-judgments.jsonl",
        "".join(
            _canonical_json({"case_id": case_id, "relevance": {"chunk-r": 3}})
            for case_id in case_ids
        ),
    )
    builder.write_json("resolved-config.json", config.model_dump(mode="json"))
    builder.write_json(
        "environment.json",
        {
            "git_sha": "e" * 40,
            "git_dirty": False,
            "models": {"embedding": "text-embedding-v4@test"},
        },
    )
    builder.write_text(
        "raw-rankings.jsonl",
        "".join(
            _canonical_json(item.model_dump(mode="json"))
            for case in cases
            for item in case.rankings
        ),
    )
    builder.write_text(
        "case-metrics.jsonl",
        "".join(_canonical_json(item) for item in statistics["case_metrics"]),
    )
    builder.write_json("aggregate.json", aggregate)
    builder.write_json("confidence-intervals.json", confidence)
    builder.write_text("failures.jsonl", "")
    builder.write_text("logs.jsonl", "")
    builder.write_text("traces.jsonl", "")
    builder.write_text("report.md", "# Retrieval Benchmark Report\n")
    builder.write_text("resume-evidence.md", "# Resume Evidence\n")
    # Citation track artifacts are empty for retrieval-only packages.
    builder.write_text("assertions.jsonl", "")
    builder.write_text("citation-occurrences.jsonl", "")
    builder.write_text("evidence-matches.jsonl", "")
    builder.write_json("review-rubric.json", {})
    builder.write_text("calibration.jsonl", "")
    builder.write_text("judgments.jsonl", "")
    builder.write_text("adjudications.jsonl", "")
    builder.seal(package_kind="retrieval_benchmark")
    return package


def test_prepare_is_offline_and_writes_frozen_inputs(tmp_path, monkeypatch) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    def credentials_are_forbidden() -> Settings:
        raise AssertionError("offline prepare must not load credentials")

    monkeypatch.setattr(cli, "load_settings", credentials_are_forbidden)
    output = tmp_path / "prepared"

    result = runner.invoke(
        cli.app,
        [
            "prepare",
            "--dataset",
            "tests/fixtures/evaluation/minimal-dataset",
            "--split",
            "validation",
            "--output",
            str(output),
            "--embedding-model-version",
            "text-embedding-v4@test",
        ],
    )

    assert result.exit_code == 0, result.output
    config = RetrievalBenchmarkConfig.model_validate_json(
        (output / "resolved-config.json").read_text(encoding="utf-8")
    )
    assert config.ordered_case_ids == (
        "scifact-validation-001",
        "qasper-validation-001",
    )
    assert config.timeout_seconds == 30.0
    assert (output / "gold-judgments.jsonl").is_file()
    assert (output / "corpus-manifest.json").is_file()
    dataset_manifest = json.loads(
        (output / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert dataset_manifest["data_kind"] == "synthetic"


def test_run_live_requires_ack_and_preflights_before_creating_output(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    prepared = tmp_path / "prepared"
    cli._write_prepared(
        dataset_path=Path("tests/fixtures/evaluation/minimal-dataset"),
        split="validation",
        output=prepared,
        candidate_limit=30,
        timeout_seconds=30.0,
        rrf_k=60,
        embedding_model="text-embedding-v4",
        embedding_model_version="text-embedding-v4@test",
    )
    output = tmp_path / "experiment"

    missing_ack = runner.invoke(
        cli.app,
        ["run-live", "--prepared", str(prepared), "--output", str(output)],
    )
    assert missing_ack.exit_code == 2
    assert not output.exists()

    monkeypatch.setattr(cli, "load_settings", lambda: Settings(dashscope_api_key=None))
    missing_credentials = runner.invoke(
        cli.app,
        [
            "run-live",
            "--prepared",
            str(prepared),
            "--output",
            str(output),
            "--acknowledge-provider-costs",
        ],
    )
    assert missing_credentials.exit_code == 1
    assert "DASHSCOPE_API_KEY" in missing_credentials.output
    assert not output.exists()


def test_run_live_rejects_dirty_git_before_provider_access(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    prepared = tmp_path / "prepared"
    cli._write_prepared(
        dataset_path=Path("tests/fixtures/evaluation/minimal-dataset"),
        split="validation",
        output=prepared,
        candidate_limit=30,
        timeout_seconds=7.5,
        rrf_k=60,
        embedding_model="text-embedding-v4",
        embedding_model_version="text-embedding-v4@test",
    )

    class ProviderMustNotStart:
        def __init__(self, **_kwargs: object) -> None:
            raise AssertionError("dirty Git must fail before provider access")

    monkeypatch.setattr(cli, "BailianTextEmbedder", ProviderMustNotStart)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(dashscope_api_key="test-key"),
    )
    monkeypatch.setattr(
        cli,
        "_git_environment",
        lambda model: {
            "git_sha": "e" * 40,
            "git_dirty": True,
            "python_version": "3.12",
            "models": {"embedding": model},
        },
    )
    output = tmp_path / "experiment"

    result = runner.invoke(
        cli.app,
        [
            "run-live",
            "--prepared",
            str(prepared),
            "--output",
            str(output),
            "--acknowledge-provider-costs",
        ],
    )

    assert result.exit_code == 1
    assert "clean Git worktree" in result.output
    assert not output.exists()


def test_run_live_applies_timeout_and_seals_sanitized_mode_failures(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    prepared = tmp_path / "prepared"
    cli._write_prepared(
        dataset_path=Path("tests/fixtures/evaluation/minimal-dataset"),
        split="validation",
        output=prepared,
        candidate_limit=30,
        timeout_seconds=7.5,
        rrf_k=60,
        embedding_model="text-embedding-v4",
        embedding_model_version="text-embedding-v4@test",
    )
    captured: dict[str, float] = {}

    class FakeEmbedder:
        def __init__(self, **kwargs: object) -> None:
            captured["timeout"] = float(kwargs["timeout"])

    class FailingBenchmark:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run_case(
            self, *, case_id: str, **_kwargs: object
        ) -> CaseRetrievalResult:
            return CaseRetrievalResult(
                case_id=case_id,
                rankings=(),
                failures=(
                    ModeFailure(
                        case_id=case_id,
                        mode="keyword",
                        stage="lexical",
                        reason_code="retrieval_source_error",
                        duration_ms=1.0,
                    ),
                    ModeFailure(
                        case_id=case_id,
                        mode="vector",
                        stage="vector_query",
                        reason_code="embedding_authentication_error",
                        duration_ms=2.0,
                    ),
                    ModeFailure(
                        case_id=case_id,
                        mode="hybrid_rrf",
                        stage="fusion",
                        reason_code="dependent_vector_failure",
                        duration_ms=0.1,
                    ),
                ),
            )

    monkeypatch.setattr(cli, "BailianTextEmbedder", FakeEmbedder)
    monkeypatch.setattr(cli, "RetrievalBenchmarkRunner", FailingBenchmark)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(dashscope_api_key="test-key"),
    )
    monkeypatch.setattr(
        cli,
        "_git_environment",
        lambda model: {
            "git_sha": "e" * 40,
            "git_dirty": False,
            "python_version": "3.12",
            "models": {"embedding": model},
        },
    )
    output = tmp_path / "experiment"

    result = runner.invoke(
        cli.app,
        [
            "run-live",
            "--prepared",
            str(prepared),
            "--output",
            str(output),
            "--acknowledge-provider-costs",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["timeout"] == 7.5
    failures = [
        json.loads(line)
        for line in (output / "failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {item["reason_code"] for item in failures} == {
        "retrieval_source_error",
        "embedding_authentication_error",
        "dependent_vector_failure",
    }
    assert "test-key" not in (output / "failures.jsonl").read_text(encoding="utf-8")
    assert (output / "artifact-manifest.json").is_file()


def test_run_live_isolates_vector_index_between_cases(tmp_path, monkeypatch) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    prepared = tmp_path / "prepared"
    cli._write_prepared(
        dataset_path=Path("tests/fixtures/evaluation/minimal-dataset"),
        split="validation",
        output=prepared,
        candidate_limit=30,
        timeout_seconds=7.5,
        rrf_k=60,
        embedding_model="text-embedding-v4",
        embedding_model_version="text-embedding-v4@test",
    )

    class FakeEmbedder:
        model_name = "text-embedding-v4"

        def __init__(self, **_kwargs: object) -> None:
            pass

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] for _text in texts]

    monkeypatch.setattr(cli, "BailianTextEmbedder", FakeEmbedder)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(dashscope_api_key="test-key"),
    )
    monkeypatch.setattr(
        cli,
        "_git_environment",
        lambda model: {
            "git_sha": "e" * 40,
            "git_dirty": False,
            "python_version": "3.12",
            "models": {"embedding": model},
        },
    )
    output = tmp_path / "experiment"

    result = runner.invoke(
        cli.app,
        [
            "run-live",
            "--prepared",
            str(prepared),
            "--output",
            str(output),
            "--acknowledge-provider-costs",
        ],
    )

    assert result.exit_code == 0, result.output
    rankings = [
        json.loads(line)
        for line in (output / "raw-rankings.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    vector_rankings = [item for item in rankings if item["mode"] == "vector"]
    assert [len(item["candidates"]) for item in vector_rankings] == [1, 1]
    assert all(
        candidate["chunk_id"].startswith(f"{ranking['case_id']}:")
        for ranking in vector_rankings
        for candidate in ranking["candidates"]
    )


def test_recompute_writes_verification_copy_and_detects_projection_mismatch(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: (_ for _ in ()).throw(
            AssertionError("offline recompute must not load credentials")
        ),
    )
    valid = _sealed_package(tmp_path / "valid")
    verification = tmp_path / "verification"

    result = runner.invoke(
        cli.app,
        ["recompute", "--package", str(valid), "--output", str(verification)],
    )

    assert result.exit_code == 0, result.output
    assert (verification / "aggregate.json").read_bytes() == (
        valid / "aggregate.json"
    ).read_bytes()
    assert (verification / "confidence-intervals.json").read_bytes() == (
        valid / "confidence-intervals.json"
    ).read_bytes()
    assert (verification / "report.md").is_file()
    assert (verification / "resume-evidence.md").is_file()

    corrupt = _sealed_package(tmp_path / "corrupt", corrupt_aggregate=True)
    mismatch = runner.invoke(
        cli.app,
        [
            "recompute",
            "--package",
            str(corrupt),
            "--output",
            str(tmp_path / "mismatch"),
        ],
    )
    assert mismatch.exit_code == 3
    assert "aggregate.json" in mismatch.output


def test_recompute_seals_publishable_authority_without_mutating_real_source(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    monkeypatch.setattr(
        cli,
        "score_benchmark",
        lambda **kwargs: score_benchmark(**kwargs, bootstrap_resamples=1),
    )
    source = _sealed_package(
        tmp_path / "real",
        data_kind="real",
        case_count=40,
        bootstrap_resamples=1,
    )
    source_manifest = (source / "artifact-manifest.json").read_bytes()
    authority = tmp_path / "authority"

    result = runner.invoke(
        cli.app,
        ["recompute", "--package", str(source), "--output", str(authority)],
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads(
        (authority / "recompute-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["sealed"] is True
    assert manifest["recomputed"] is True
    assert manifest["publishable"] is True
    assert manifest["source"]["artifact_manifest_sha256"] == hashlib.sha256(
        source_manifest
    ).hexdigest()
    resume = (authority / "resume-evidence.md").read_text(encoding="utf-8")
    assert "On 40 real cases" in resume
    assert "No resume-ready numeric claims" not in resume
    assert (source / "artifact-manifest.json").read_bytes() == source_manifest
    verified = runner.invoke(cli.app, ["verify", str(authority)])
    assert verified.exit_code == 0, verified.output


def test_recomputed_authority_rejects_tampering_and_invalid_chain_state(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    monkeypatch.setattr(
        cli,
        "score_benchmark",
        lambda **kwargs: score_benchmark(**kwargs, bootstrap_resamples=1),
    )
    source = _sealed_package(
        tmp_path / "source",
        data_kind="real",
        case_count=40,
        bootstrap_resamples=1,
    )

    projection_authority = tmp_path / "projection-tamper"
    assert runner.invoke(
        cli.app,
        ["recompute", "--package", str(source), "--output", str(projection_authority)],
    ).exit_code == 0
    with (projection_authority / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    projection_manifest_path = projection_authority / "recompute-manifest.json"
    projection_manifest = json.loads(
        projection_manifest_path.read_text(encoding="utf-8")
    )
    report_entry = next(
        entry
        for entry in projection_manifest["artifacts"]
        if entry["path"] == "report.md"
    )
    report_bytes = (projection_authority / "report.md").read_bytes()
    report_entry["byte_length"] = len(report_bytes)
    report_entry["sha256"] = hashlib.sha256(report_bytes).hexdigest()
    projection_manifest_path.write_text(
        _canonical_json(projection_manifest), encoding="utf-8"
    )
    assert runner.invoke(cli.app, ["verify", str(projection_authority)]).exit_code == 3

    for directory, mutation in (
        ("source-hash", lambda value: value["source"].update(
            {"artifact_manifest_sha256": "0" * 64}
        )),
        ("recomputed-state", lambda value: value.update({"recomputed": False})),
    ):
        authority = tmp_path / directory
        assert runner.invoke(
            cli.app,
            ["recompute", "--package", str(source), "--output", str(authority)],
        ).exit_code == 0
        path = authority / "recompute-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        mutation(manifest)
        path.write_text(_canonical_json(manifest), encoding="utf-8")
        assert runner.invoke(cli.app, ["verify", str(authority)]).exit_code == 3


def test_synthetic_recomputed_authority_remains_non_publishable(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli

    monkeypatch.setattr(
        cli,
        "score_benchmark",
        lambda **kwargs: score_benchmark(**kwargs, bootstrap_resamples=1),
    )
    source = _sealed_package(
        tmp_path / "synthetic", case_count=40, bootstrap_resamples=1
    )
    authority = tmp_path / "authority"
    result = runner.invoke(
        cli.app,
        ["recompute", "--package", str(source), "--output", str(authority)],
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads(
        (authority / "recompute-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publishable"] is False
    resume = (authority / "resume-evidence.md").read_text(encoding="utf-8")
    assert "No resume-ready numeric claims" in resume
    assert "Recall@8 was" not in resume
    verified = runner.invoke(cli.app, ["verify", str(authority)])
    assert verified.exit_code == 0, verified.output


def test_recompute_rejects_a_corrupt_seal_with_integrity_exit_code(tmp_path) -> None:
    from paper_agent.eval.retrieval_benchmark.cli import app

    package = _sealed_package(tmp_path)
    with (package / "logs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")

    result = runner.invoke(
        app,
        [
            "recompute",
            "--package",
            str(package),
            "--output",
            str(tmp_path / "verification"),
        ],
    )

    assert result.exit_code == 3
    assert "mismatch" in result.output
    assert not (tmp_path / "verification").exists()


def test_verify_uses_integrity_exit_code_and_group_is_registered(
    tmp_path, monkeypatch
) -> None:
    from paper_agent.eval.retrieval_benchmark import cli
    from paper_agent.cli import app as root_app

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: (_ for _ in ()).throw(
            AssertionError("offline verify must not load credentials")
        ),
    )
    package = _sealed_package(tmp_path)
    valid = runner.invoke(root_app, ["retrieval-benchmark", "verify", str(package)])
    assert valid.exit_code == 0, valid.output

    with (package / "logs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    invalid = runner.invoke(root_app, ["retrieval-benchmark", "verify", str(package)])
    assert invalid.exit_code == 3
    assert "mismatch" in invalid.output
