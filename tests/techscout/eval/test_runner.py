import json
from pathlib import Path

import pytest

from paper_agent.eval.evidence_package import verify_evidence_package
from paper_agent.observability.sealed_jsonl import verify_sealed_jsonl
from paper_agent.techscout.eval.contracts import EvaluationEnvironment
from paper_agent.techscout.eval.runner import run_evaluation_suite


FIXTURES = Path("tests/fixtures/techscout/eval")


def _environment() -> EvaluationEnvironment:
    return EvaluationEnvironment(
        git_dirty=False,
        models={"fixture_executor": "frozen-synthetic-v1"},
        executor_version="frozen-synthetic-v1",
    )


def test_three_smoke_runner_publishes_objective_sealed_evidence(tmp_path):
    output = tmp_path / "smoke-evidence"

    summary = run_evaluation_suite(
        FIXTURES / "smoke-suite.json",
        output,
        environment=_environment(),
    )

    metrics = summary.task_metrics["v1"]
    assert metrics.task_success_count == 3
    assert metrics.first_pass_success_count == 2
    assert summary.recovery_success_count == 1
    assert summary.recovery_attempt_count == 1
    assert metrics.prompt_tokens_per_successful_task == pytest.approx(2290 / 3)
    assert metrics.latency["cold_live"].model_dump() == {
        "count": 1,
        "p50_ms": 7200,
        "p95_ms": 7200,
    }
    assert metrics.latency["warm_cache"].model_dump() == {
        "count": 2,
        "p50_ms": 1800,
        "p95_ms": 4100,
    }
    assert verify_evidence_package(output)["profile"] == "smoke"
    verify_sealed_jsonl(output / "traces.jsonl")
    projection = (output / "resume-evidence.md").read_text(encoding="utf-8")
    assert "Synthetic smoke results" in projection
    assert "Cold-live" in projection and "Warm-cache" in projection


def test_suite_cannot_be_overwritten_or_rerun_into_same_output(tmp_path):
    output = tmp_path / "one-shot"
    run_evaluation_suite(FIXTURES / "smoke-suite.json", output, environment=_environment())

    with pytest.raises(ValueError, match="already exists"):
        run_evaluation_suite(FIXTURES / "smoke-suite.json", output, environment=_environment())


def test_final_profile_enforces_exact_12_40_8_counts(tmp_path):
    suite = json.loads((FIXTURES / "smoke-suite.json").read_text(encoding="utf-8"))
    suite["profile"] = "final"
    invalid_suite = tmp_path / "final-suite.json"
    invalid_suite.write_text(json.dumps(suite), encoding="utf-8")
    for case_file in suite["case_files"]:
        (tmp_path / case_file).write_bytes((FIXTURES / case_file).read_bytes())

    with pytest.raises(ValueError, match=r"requires counts \(12, 40, 8\)"):
        run_evaluation_suite(invalid_suite, tmp_path / "output", environment=_environment())
