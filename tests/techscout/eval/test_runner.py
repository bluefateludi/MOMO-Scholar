import json
from pathlib import Path

import pytest

from paper_agent.eval.evidence_package import verify_evidence_package
from paper_agent.observability.sealed_jsonl import verify_sealed_jsonl
from paper_agent.techscout.eval.contracts import (
    EvaluationEnvironment,
    FaultExecutionResult,
    RetrievalExecutionResult,
    TaskExecutionResult,
)
from paper_agent.techscout.eval.runner import run_evaluation_suite
from paper_agent.techscout.observability import TraceEventName


FIXTURES = Path("tests/fixtures/techscout/eval")


class StepClock:
    def __init__(self) -> None:
        self._values = iter((0.0, 7.2, 10.0, 11.8, 20.0, 24.1))

    def __call__(self) -> float:
        return next(self._values)


class SmokeExecutor:
    version = "frozen-synthetic-v1"

    def run_e2e(self, case, variant, *, timeout_seconds, trace):
        assert timeout_seconds == 10
        source = json.loads(Path(case.source_fixture).read_text(encoding="utf-8"))
        assert source["task_id"] == case.case_id
        trace.record(
            TraceEventName.PLAN_CREATED,
            status="ok",
            attributes={
                "case_id": case.case_id,
                "harness_variant": variant.value,
                "plan_id": f"plan:{case.case_id}",
                "dimension_count": 3,
                "decision_code": "frozen_smoke",
            },
        )
        trace.record(
            TraceEventName.SKILL_SELECTED,
            status="ok",
            attributes={
                "case_id": case.case_id,
                "skill_id": "skill:smoke@1",
                "stage": "execute_poc",
                "reason_code": "frozen_smoke",
            },
        )
        trace.record(
            TraceEventName.CHECKPOINT_CREATED,
            status="ok",
            attributes={
                "case_id": case.case_id,
                "checkpoint_id": f"checkpoint:{case.case_id}",
                "parent_checkpoint_id": None,
                "stage": "execute_poc",
                "sequence": 1,
            },
        )
        recovered = case.case_id.endswith("003")
        if recovered:
            trace.record(
                TraceEventName.ERROR_CLASSIFIED,
                status="error",
                attributes={
                    "case_id": case.case_id,
                    "failure_id": f"failure:{case.case_id}:dependency",
                    "failure_code": "dependency_conflict",
                    "failure_stage": "poc_execution",
                    "recoverable": True,
                    "attempt": 1,
                },
            )
            trace.record(
                TraceEventName.RECOVERY_STARTED,
                status="started",
                attributes={
                    "case_id": case.case_id,
                    "failure_id": f"failure:{case.case_id}:dependency",
                    "checkpoint_id": f"checkpoint:{case.case_id}",
                    "stage": "execute_poc",
                    "recovery_action": "pin_version_and_rerun_poc",
                },
            )
            trace.record(
                TraceEventName.RECOVERY_FINISHED,
                status="ok",
                attributes={
                    "case_id": case.case_id,
                    "failure_id": f"failure:{case.case_id}:dependency",
                    "checkpoint_id": f"checkpoint:{case.case_id}",
                    "stage": "execute_poc",
                    "succeeded": True,
                },
            )
        trace.record(
            TraceEventName.VALIDATION_COMPLETED,
            status="ok",
            attributes={
                "case_id": case.case_id,
                "gate_outcome": "passed",
                "checked_constraint_count": 3,
                "failure_count": 0,
            },
        )
        token_counts = {
            "techscout-smoke-001": (820, 310),
            "techscout-smoke-002": (560, 230),
            "techscout-smoke-003": (910, 350),
        }
        prompt, completion = token_counts[case.case_id]
        trace.record_terminal(
            terminal_status="completed",
            gate_outcome="passed",
            latency_ms=0,
            prompt_tokens=prompt,
            completion_tokens=completion,
            retry_count=1 if recovered else 0,
            recovery_count=1 if recovered else 0,
            report_sha256="a" * 64,
            manifest_sha256="b" * 64,
            context={"case_id": case.case_id, "harness_variant": variant.value},
        )
        return TaskExecutionResult(
            report_schema_valid=True,
            hard_constraints_addressed=True,
            required_evidence_available=True,
            poc_result_present=case.supports_poc,
            validation_gate_passed=True,
            artifacts_and_trace_complete=True,
            prompt_tokens=prompt,
            completion_tokens=completion,
            estimated_cost=0.001,
            tool_call_schema_valid_count=2,
            tool_call_execution_success_count=2,
            tool_call_count=2,
            recovery_attempted=recovered,
            recovery_succeeded=True if recovered else None,
            recovery_stages=1 if recovered else 0,
            retry_count=1 if recovered else 0,
        )

    def run_retrieval(self, case, *, timeout_seconds, trace):
        return RetrievalExecutionResult(
            retrieved_source_ids=("source:one",),
            relevant_source_ids=("source:one",),
            expected_version_match=True,
            actual_version_match=True,
        )

    def run_fault(self, case, injector, *, timeout_seconds, trace):
        return FaultExecutionResult(
            injected_failure_code="dependency_conflict",
            recovery_succeeded=True,
            recovery_stages=1,
            retry_count=1,
        )


def _environment() -> EvaluationEnvironment:
    return EvaluationEnvironment(
        git_dirty=False,
        models={"fixture_executor": "frozen-synthetic-v1"},
        executor_version="frozen-synthetic-v1",
    )


def test_three_smoke_runner_executes_and_seals_objective_evidence(tmp_path):
    output = tmp_path / "smoke-evidence"
    summary = run_evaluation_suite(
        FIXTURES / "smoke-suite.json",
        output,
        environment=_environment(),
        executor=SmokeExecutor(),
        monotonic=StepClock(),
    )

    metrics = summary.task_metrics["v1"]
    assert (summary.e2e_case_count, summary.e2e_run_count) == (3, 3)
    assert (metrics.task_success_count, metrics.first_pass_success_count) == (3, 2)
    assert (metrics.recovery_success_count, metrics.recovery_attempt_count) == (1, 1)
    assert (summary.fault_recovery_success_count, summary.fault_recovery_attempt_count) == (0, 0)
    assert metrics.prompt_tokens_per_successful_task == pytest.approx(2290 / 3)
    assert metrics.tool_call_schema_success_count == metrics.tool_call_count == 6
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


def test_suite_cannot_be_rerun_into_same_output(tmp_path):
    output = tmp_path / "one-shot"
    run_evaluation_suite(
        FIXTURES / "smoke-suite.json",
        output,
        environment=_environment(),
        executor=SmokeExecutor(),
        monotonic=StepClock(),
    )
    with pytest.raises(ValueError, match="already exists"):
        run_evaluation_suite(
            FIXTURES / "smoke-suite.json",
            output,
            environment=_environment(),
            executor=SmokeExecutor(),
            monotonic=StepClock(),
        )


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
            executor=SmokeExecutor(),
        )
