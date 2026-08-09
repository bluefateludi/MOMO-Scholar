from __future__ import annotations

import math
from collections.abc import Sequence

from paper_agent.techscout.eval.contracts import (
    CacheMode,
    CaseKind,
    EvaluationCase,
    EvaluationSummary,
    HarnessVariant,
    LatencySummary,
    SuiteDefinition,
    TaskMetricSummary,
    TaskRunObservation,
)


def _percentile(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _latency(runs: Sequence[TaskRunObservation], mode: CacheMode) -> LatencySummary:
    values = [run.latency_ms for run in runs if run.cache_mode is mode]
    return LatencySummary(
        count=len(values),
        p50_ms=_percentile(values, 0.50),
        p95_ms=_percentile(values, 0.95),
    )


def _task_metrics(runs: Sequence[TaskRunObservation]) -> TaskMetricSummary:
    successful = [run for run in runs if run.task_checks.passed]
    recovery = [run for run in runs if run.recovery_attempted]
    return TaskMetricSummary(
        task_count=len(runs),
        task_success_count=len(successful),
        first_pass_success_count=sum(run.first_pass_success for run in runs),
        recovery_success_count=sum(run.recovery_succeeded is True for run in recovery),
        recovery_attempt_count=len(recovery),
        prompt_tokens_per_successful_task=(
            sum(run.prompt_tokens for run in successful) / len(successful)
            if successful
            else None
        ),
        total_tokens_per_successful_task=(
            sum(run.prompt_tokens + run.completion_tokens for run in successful)
            / len(successful)
            if successful
            else None
        ),
        latency={
            "cold_live": _latency(runs, CacheMode.COLD_LIVE),
            "warm_cache": _latency(runs, CacheMode.WARM_CACHE),
        },
    )


def summarize(suite: SuiteDefinition, cases: Sequence[EvaluationCase]) -> EvaluationSummary:
    e2e = [case for case in cases if case.kind is CaseKind.END_TO_END]
    retrieval = [case for case in cases if case.kind is CaseKind.RETRIEVAL]
    faults = [case for case in cases if case.kind is CaseKind.FAULT]
    runs = [run for case in e2e for run in case.runs]
    fault_recovery = [case for case in faults if case.recovery_attempted]
    run_recovery = [run for run in runs if run.recovery_attempted]
    recall_values = []
    for case in retrieval:
        relevant = set(case.relevant_source_ids)
        recall_values.append(len(set(case.retrieved_source_ids[:5]) & relevant) / len(relevant))
    return EvaluationSummary(
        suite_id=suite.suite_id,
        profile=suite.profile,
        e2e_case_count=len(e2e),
        retrieval_case_count=len(retrieval),
        fault_case_count=len(faults),
        e2e_run_count=len(runs),
        recovery_success_count=(
            sum(case.recovery_succeeded is True for case in fault_recovery)
            + sum(run.recovery_succeeded is True for run in run_recovery)
        ),
        recovery_attempt_count=len(fault_recovery) + len(run_recovery),
        retrieval_recall_at_5=(sum(recall_values) / len(recall_values) if recall_values else None),
        version_filter_accuracy=(
            sum(case.expected_version_match == case.actual_version_match for case in retrieval)
            / len(retrieval)
            if retrieval
            else None
        ),
        average_recovery_stages=(
            (
                sum(case.recovery_stages for case in fault_recovery)
                + sum(run.recovery_stages for run in run_recovery)
            )
            / (len(fault_recovery) + len(run_recovery))
            if fault_recovery or run_recovery
            else None
        ),
        average_retries=(
            (
                sum(case.retry_count for case in faults)
                + sum(run.retry_count for run in runs)
            )
            / (len(faults) + len(runs))
            if faults or runs
            else None
        ),
        task_metrics={
            variant: _task_metrics(
                [run for run in runs if run.harness_variant is variant]
            )
            for variant in HarnessVariant
            if any(run.harness_variant is variant for run in runs)
        },
    )
