from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Lock
from typing import TypeVar

from paper_agent.techscout.eval.contracts import (
    CaseKind,
    EvaluationEnvironment,
    EvaluationSummary,
    FaultExecutionResult,
    HarnessVariant,
    RetrievalExecutionResult,
    TaskRunObservation,
    validate_expected_contract,
    validate_fault_contract,
    validate_retrieval_contract,
)
from paper_agent.techscout.eval.executor import EvaluationExecutor, InfrastructureFailure
from paper_agent.techscout.eval.faults import DeterministicFaultInjector
from paper_agent.techscout.eval.metrics import summarize
from paper_agent.techscout.eval.package import publish_package, publish_partial_results
from paper_agent.techscout.eval.suite import load_suite
from paper_agent.techscout.observability import TechScoutTraceRecorder, TraceEventName


T = TypeVar("T")


class EvaluationCaseTimeout(TimeoutError):
    pass


def _run_bounded_jobs(
    jobs: list[tuple[str, Callable[[], tuple[str, object]]]],
    *,
    workers: int,
    timeout_seconds: int,
    output_dir: Path,
    cancel: Callable[[str], None],
) -> tuple[tuple[str, object], ...]:
    pool = ThreadPoolExecutor(max_workers=workers)
    starts: dict[int, float] = {}
    lock = Lock()

    def invoke(index: int, job: Callable[[], tuple[str, object]]):
        with lock:
            starts[index] = time.monotonic()
        return job()

    futures: dict[Future[tuple[str, object]], tuple[int, str]] = {
        pool.submit(invoke, index, job): (index, case_id)
        for index, (case_id, job) in enumerate(jobs)
    }
    remaining = set(futures)
    completed: dict[int, tuple[str, object]] = {}
    try:
        while remaining:
            done, _ = wait(remaining, timeout=0.05, return_when=FIRST_COMPLETED)
            for future in done:
                remaining.remove(future)
                completed[futures[future][0]] = future.result()
            now = time.monotonic()
            overdue = [
                futures[future][0]
                for future in remaining
                if futures[future][0] in starts
                and now - starts[futures[future][0]] >= timeout_seconds
            ]
            if overdue:
                for future in remaining:
                    index, case_id = futures[future]
                    if index in overdue:
                        cancel(case_id)
                raise EvaluationCaseTimeout(
                    f"evaluation cases exceeded hard timeout: {sorted(overdue)}"
                )
    except BaseException as error:
        for future in remaining:
            future.cancel()
        publish_partial_results(
            output_dir,
            observations=tuple(completed[index] for index in sorted(completed)),
            failure_code=(
                "case_timeout"
                if isinstance(error, EvaluationCaseTimeout)
                else "runner_failure"
            ),
        )
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return tuple(completed[index] for index in sorted(completed))


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
    jobs: list[tuple[str, Callable[[], tuple[str, object]]]] = []
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
                    observation = TaskRunObservation(
                        case_id=case.case_id,
                        harness_variant=variant,
                        cache_mode=case.cache_mode,
                        latency_ms=elapsed,
                        supports_poc=case.supports_poc,
                        result=result,
                    )
                    validate_expected_contract(case, observation)
                    return "task", observation
                jobs.append((case.case_id, run_task))
        elif case.kind is CaseKind.RETRIEVAL:
            def run_retrieval(case=case):
                result = executor.run_retrieval(
                        case,
                        timeout_seconds=suite.execution_policy.timeout_seconds,
                        trace=trace,
                    )
                validate_retrieval_contract(case, result)
                return "retrieval", result
            jobs.append((case.case_id, run_retrieval))
        else:
            assert case.fault_plan is not None
            def run_fault(case=case):
                injector = DeterministicFaultInjector(case.fault_plan)
                result = executor.run_fault(
                        case,
                        injector,
                        timeout_seconds=suite.execution_policy.timeout_seconds,
                        trace=trace,
                    )
                if injector.triggered_count != 1 or result.injected_failure_code != case.fault_plan.failure_code:
                    raise ValueError("fault executor did not trigger the frozen failure plan")
                validate_fault_contract(case, result)
                return "fault", result
            jobs.append((case.case_id, run_fault))
    try:
        observations = _run_bounded_jobs(
            jobs,
            workers=suite.execution_policy.workers,
            timeout_seconds=suite.execution_policy.timeout_seconds,
            output_dir=output_dir,
            cancel=executor.cancel,
        )
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
