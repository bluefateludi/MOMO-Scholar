from __future__ import annotations

import math
from collections.abc import Sequence

from paper_agent.techscout.eval.contracts import (
    CacheMode,
    EvaluationSummary,
    FaultExecutionResult,
    HarnessVariant,
    LatencySummary,
    RetrievalExecutionResult,
    SuiteDefinition,
    TaskMetricSummary,
    TaskRunObservation,
)


def _percentile(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(percentile * len(ordered))) - 1]


def _latency(runs: Sequence[TaskRunObservation], mode: CacheMode) -> LatencySummary:
    values = [run.latency_ms for run in runs if run.cache_mode is mode]
    return LatencySummary(
        count=len(values),
        p50_ms=_percentile(values, 0.50),
        p95_ms=_percentile(values, 0.95),
    )


def _task_metrics(runs: Sequence[TaskRunObservation]) -> TaskMetricSummary:
    successful = [run for run in runs if run.task_success]
    recovery = [run for run in runs if run.result.recovery_attempted]
    costs = [run.result.estimated_cost for run in successful]
    known_costs = [cost for cost in costs if cost is not None]
    return TaskMetricSummary(
        task_count=len(runs),
        task_success_count=len(successful),
        first_pass_success_count=sum(run.first_pass_success for run in runs),
        recovery_success_count=sum(run.result.recovery_succeeded is True for run in recovery),
        recovery_attempt_count=len(recovery),
        tool_call_schema_success_count=sum(run.result.tool_call_schema_valid_count for run in runs),
        tool_call_execution_success_count=sum(
            run.result.tool_call_execution_success_count for run in runs
        ),
        tool_call_count=sum(run.result.tool_call_count for run in runs),
        average_recovery_stages=(
            sum(run.result.recovery_stages for run in recovery) / len(recovery)
            if recovery
            else None
        ),
        average_retries=(sum(run.result.retry_count for run in runs) / len(runs) if runs else 0),
        prompt_tokens_per_successful_task=(
            sum(run.result.prompt_tokens for run in successful) / len(successful)
            if successful
            else None
        ),
        total_tokens_per_successful_task=(
            sum(run.result.prompt_tokens + run.result.completion_tokens for run in successful)
            / len(successful)
            if successful
            else None
        ),
        estimated_cost_per_successful_task=(
            sum(known_costs) / len(successful)
            if successful and len(known_costs) == len(successful)
            else None
        ),
        latency={
            "cold_live": _latency(runs, CacheMode.COLD_LIVE),
            "warm_cache": _latency(runs, CacheMode.WARM_CACHE),
        },
    )


def summarize(
    suite: SuiteDefinition,
    *,
    task_runs: Sequence[TaskRunObservation],
    retrieval_results: Sequence[RetrievalExecutionResult],
    fault_results: Sequence[FaultExecutionResult],
    e2e_case_count: int,
) -> EvaluationSummary:
    recalls = []
    for result in retrieval_results:
        relevant = set(result.relevant_source_ids)
        recalls.append(len(set(result.retrieved_source_ids[:5]) & relevant) / len(relevant))
    return EvaluationSummary(
        suite_id=suite.suite_id,
        profile=suite.profile,
        e2e_case_count=e2e_case_count,
        e2e_run_count=len(task_runs),
        retrieval_case_count=len(retrieval_results),
        fault_case_count=len(fault_results),
        fault_recovery_success_count=sum(result.recovery_succeeded for result in fault_results),
        fault_recovery_attempt_count=len(fault_results),
        retrieval_recall_at_5=(sum(recalls) / len(recalls) if recalls else None),
        version_filter_accuracy=(
            sum(result.expected_version_match == result.actual_version_match for result in retrieval_results)
            / len(retrieval_results)
            if retrieval_results
            else None
        ),
        average_fault_recovery_stages=(
            sum(result.recovery_stages for result in fault_results) / len(fault_results)
            if fault_results
            else None
        ),
        average_fault_retries=(
            sum(result.retry_count for result in fault_results) / len(fault_results)
            if fault_results
            else None
        ),
        task_metrics={
            variant: _task_metrics(
                [run for run in task_runs if run.harness_variant is variant]
            )
            for variant in HarnessVariant
            if any(run.harness_variant is variant for run in task_runs)
        },
    )
