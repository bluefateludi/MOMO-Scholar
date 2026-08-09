import json
from pathlib import Path
from threading import Event

import pytest

from paper_agent.eval.evidence_package import verify_evidence_package
from paper_agent.observability.sealed_jsonl import verify_sealed_jsonl
from paper_agent.techscout.eval.contracts import EvaluationEnvironment
from paper_agent.techscout.eval.runner import (
    EvaluationSuiteTimeout,
    _run_bounded_jobs,
    run_evaluation_suite,
)
from paper_agent.techscout.eval.smoke import FrozenSmokeExecutor


FIXTURES = Path("tests/fixtures/techscout/eval")


class StepClock:
    def __init__(self) -> None:
        self._values = iter((0.0, 7.2, 10.0, 11.8, 20.0, 24.1))

    def __call__(self) -> float:
        return next(self._values)


def _environment() -> EvaluationEnvironment:
    return EvaluationEnvironment(
        git_dirty=False,
        models={"fixture_executor": "frozen-synthetic-v1"},
        executor_version="frozen-synthetic-v1",
    )


def _run(tmp_path, output):
    return run_evaluation_suite(
        FIXTURES / "smoke-suite.json",
        output,
        environment=_environment(),
        executor=FrozenSmokeExecutor(tmp_path / "checkpoints"),
        monotonic=StepClock(),
    )


def test_three_smoke_runner_crosses_real_harness_and_seals_evidence(tmp_path):
    output = tmp_path / "smoke-evidence"
    summary = _run(tmp_path, output)

    metrics = summary.task_metrics["v1"]
    assert (summary.e2e_case_count, summary.e2e_run_count) == (3, 3)
    assert (metrics.task_success_count, metrics.first_pass_success_count) == (3, 2)
    assert (metrics.recovery_success_count, metrics.recovery_attempt_count) == (1, 1)
    assert metrics.average_recovery_stages == 1.0
    assert metrics.average_retries == pytest.approx(1 / 3)
    assert (summary.fault_recovery_success_count, summary.fault_recovery_attempt_count) == (0, 0)
    assert metrics.prompt_tokens_per_successful_task is not None
    assert metrics.tool_call_schema_success_count == metrics.tool_call_count == 3
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
    assert "Prompt/total tokens" in projection


def test_suite_cannot_be_rerun_into_same_output(tmp_path):
    output = tmp_path / "one-shot"
    _run(tmp_path, output)
    with pytest.raises(ValueError, match="already exists"):
        _run(tmp_path, output)


def test_final_profile_enforces_exact_12_40_8_counts(tmp_path):
    suite = json.loads((FIXTURES / "smoke-suite.json").read_text(encoding="utf-8"))
    suite["profile"] = "final"
    invalid_suite = tmp_path / "final-suite.json"
    invalid_suite.write_text(json.dumps(suite), encoding="utf-8")
    for case_file in suite["case_files"]:
        (tmp_path / case_file).write_bytes((FIXTURES / case_file).read_bytes())
    with pytest.raises(ValueError, match=r"requires counts \(12, 40, 8\)"):
        run_evaluation_suite(
            invalid_suite,
            tmp_path / "output",
            environment=_environment(),
            executor=FrozenSmokeExecutor(tmp_path / "checkpoints"),
        )


def test_job_scheduler_enforces_total_suite_timeout(tmp_path):
    cancelled = Event()

    def blocked_job():
        cancelled.wait(timeout=1)
        return "task", object()

    with pytest.raises(EvaluationSuiteTimeout, match="total hard timeout"):
        _run_bounded_jobs(
            [("case:blocked", blocked_job)],
            workers=1,
            timeout_seconds=1,
            total_timeout_seconds=0.01,
            output_dir=tmp_path / "partial",
            cancel=lambda _: cancelled.set(),
        )
    assert json.loads((tmp_path / "partial" / "failures.jsonl").read_text())["failure_code"] == (
        "suite_timeout"
    )
