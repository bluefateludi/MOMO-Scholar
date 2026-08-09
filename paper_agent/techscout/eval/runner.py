from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from paper_agent.techscout.eval.contracts import (
    CaseKind,
    EvaluationEnvironment,
    EvaluationSummary,
    FaultExecutionResult,
    HarnessVariant,
    RetrievalExecutionResult,
    TaskRunObservation,
)
from paper_agent.techscout.eval.executor import EvaluationExecutor, InfrastructureFailure
from paper_agent.techscout.eval.faults import DeterministicFaultInjector
from paper_agent.techscout.eval.metrics import summarize
from paper_agent.techscout.eval.package import publish_package
from paper_agent.techscout.eval.suite import load_suite
from paper_agent.techscout.observability import TechScoutTraceRecorder, TraceEventName


T = TypeVar("T")


def _with_infrastructure_retry(
    operation: Callable[[], T],
    *,
    max_reruns: int,
    trace: TechScoutTraceRecorder,
    case_id: str,
) -> T:
    try:
        return operation()
    except InfrastructureFailure:
        trace.record(
            TraceEventName.ERROR_CLASSIFIED,
            status="error",
            attributes={
                "case_id": case_id,
                "failure_id": f"failure:{case_id}:infrastructure",
                "failure_code": "infrastructure_failure",
                "failure_stage": "orchestration",
                "recoverable": max_reruns == 1,
                "attempt": 1,
            },
        )
        if max_reruns != 1:
            raise
        trace.record(
            TraceEventName.RETRY_SCHEDULED,
            status="started",
            attributes={
                "case_id": case_id,
                "failure_id": f"failure:{case_id}:infrastructure",
                "stage": "orchestration",
                "attempt": 2,
            },
        )
        return operation()


def run_evaluation_suite(
    suite_path: Path,
    output_dir: Path,
    *,
    environment: EvaluationEnvironment,
    executor: EvaluationExecutor,
    monotonic: Callable[[], float] = time.monotonic,
) -> EvaluationSummary:
    """Execute a frozen suite once, then seal objective observations and Trace."""
    suite, cases = load_suite(suite_path)
    if environment.executor_version != suite.executor_version or executor.version != suite.executor_version:
        raise ValueError("executor version does not match frozen suite")
    trace = TechScoutTraceRecorder(output_dir / "traces.jsonl", run_id=suite.suite_id)
    variants = (HarnessVariant.V1,) if suite.profile.value == "smoke" else tuple(HarnessVariant)
    jobs: list[Callable[[], tuple[str, object]]] = []
    for case in cases:
        if case.kind is CaseKind.END_TO_END:
            for variant in variants:
                def run_task(case=case, variant=variant):
                    started = monotonic()
                    result = _with_infrastructure_retry(
                        lambda: executor.run_e2e(
                            case,
                            variant,
                            timeout_seconds=suite.execution_policy.timeout_seconds,
                            trace=trace,
                        ),
                        max_reruns=suite.execution_policy.max_infrastructure_reruns,
                        trace=trace,
                        case_id=case.case_id,
                    )
                    elapsed = max(0, round((monotonic() - started) * 1_000))
                    return "task", TaskRunObservation(
                        case_id=case.case_id,
                        harness_variant=variant,
                        cache_mode=case.cache_mode,
                        latency_ms=elapsed,
                        supports_poc=case.supports_poc,
                        result=result,
                    )
                jobs.append(run_task)
        elif case.kind is CaseKind.RETRIEVAL:
            jobs.append(
                lambda case=case: (
                    "retrieval",
                    executor.run_retrieval(
                        case,
                        timeout_seconds=suite.execution_policy.timeout_seconds,
                        trace=trace,
                    ),
                )
            )
        else:
            assert case.fault_plan is not None
            jobs.append(
                lambda case=case: (
                    "fault",
                    executor.run_fault(
                        case,
                        DeterministicFaultInjector(case.fault_plan),
                        timeout_seconds=suite.execution_policy.timeout_seconds,
                        trace=trace,
                    ),
                )
            )
    try:
        with ThreadPoolExecutor(max_workers=suite.execution_policy.workers) as pool:
            observations = tuple(pool.map(lambda job: job(), jobs))
    except BaseException:
        trace.seal()
        raise
    task_runs = tuple(value for kind, value in observations if kind == "task")
    retrieval = tuple(value for kind, value in observations if kind == "retrieval")
    faults = tuple(value for kind, value in observations if kind == "fault")
    assert all(isinstance(item, TaskRunObservation) for item in task_runs)
    assert all(isinstance(item, RetrievalExecutionResult) for item in retrieval)
    assert all(isinstance(item, FaultExecutionResult) for item in faults)
    trace.seal()
    summary = summarize(
        suite,
        task_runs=task_runs,
        retrieval_results=retrieval,
        fault_results=faults,
        e2e_case_count=sum(case.kind is CaseKind.END_TO_END for case in cases),
    )
    publish_package(
        output_dir,
        suite=suite,
        environment=environment,
        summary=summary,
        task_runs=task_runs,
        retrieval_results=retrieval,
        fault_results=faults,
    )
    return summary
