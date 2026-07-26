from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence

from paper_agent.eval.metrics import mrr_at_k, ndcg_at_k, precision_at_k, recall_at_k

from .contracts import CANONICAL_KS, CANONICAL_MODES, CaseRetrievalResult


_METRICS = {
    "recall_at_k": recall_at_k,
    "precision_at_k": precision_at_k,
    "mrr_at_k": mrr_at_k,
    "ndcg_at_k": ndcg_at_k,
}


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bootstrap_mean_ci(
    values: Sequence[float], *, resamples: int, rng: random.Random
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap requires at least one value")
    sampled_means = [
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(resamples)
    ]
    return _percentile(sampled_means, 0.025), _percentile(sampled_means, 0.975)


def _latency_summary(success: list[float], *, attempted: int) -> dict[str, int | float | None]:
    completed = len(success)
    failed = attempted - completed
    return {
        "attempted": attempted,
        "completed": completed,
        "failed": failed,
        "failure_rate": failed / attempted if attempted else 0.0,
        "latency_ms_p50": statistics.median(success) if success else None,
        "latency_ms_p95": _percentile(success, 0.95) if success else None,
    }


def score_benchmark(
    *,
    cases: Sequence[CaseRetrievalResult],
    relevance_by_case: dict[str, dict[str, int]],
    ks: tuple[int, ...] = CANONICAL_KS,
    primary_k: int = 8,
    bootstrap_resamples: int = 10_000,
    seed: int = 20_260_726,
) -> dict[str, object]:
    if ks != CANONICAL_KS or primary_k != 8:
        raise ValueError("benchmark statistics require canonical K values and primary K=8")
    if type(bootstrap_resamples) is not int or bootstrap_resamples < 1:
        raise ValueError("bootstrap_resamples must be a positive integer")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")
    if set(case_ids) != set(relevance_by_case):
        raise ValueError("relevance judgments must exactly match benchmark cases")

    case_metrics: list[dict[str, object]] = []
    values: dict[str, dict[str, dict[str, list[float]]]] = {
        mode: {str(k): {name: [] for name in _METRICS} for k in ks}
        for mode in CANONICAL_MODES
    }
    latencies: dict[str, list[float]] = {mode: [] for mode in CANONICAL_MODES}

    for case in cases:
        rankings = {ranking.mode: ranking for ranking in case.rankings}
        failures = {failure.mode: failure for failure in case.failures}
        modes: dict[str, object] = {}
        relevance = relevance_by_case[case.case_id]
        for mode in CANONICAL_MODES:
            if mode in failures:
                failure = failures[mode]
                modes[mode] = {
                    "status": "error",
                    "stage": failure.stage,
                    "reason_code": failure.reason_code,
                }
                continue
            ranking = rankings[mode]
            ranked_ids = [candidate.chunk_id for candidate in ranking.candidates]
            by_k: dict[str, dict[str, float]] = {}
            for k in ks:
                metrics = {
                    name: function(ranked_ids, relevance, k)
                    for name, function in _METRICS.items()
                }
                by_k[str(k)] = metrics
                for name, value in metrics.items():
                    values[mode][str(k)][name].append(value)
            modes[mode] = by_k
            latencies[mode].append(ranking.duration_ms)
        case_metrics.append({"case_id": case.case_id, "modes": modes})

    rng = random.Random(seed)
    aggregate: dict[str, object] = {}
    aggregate_ci: dict[str, object] = {}
    for mode in CANONICAL_MODES:
        aggregate[mode] = {}
        aggregate_ci[mode] = {}
        for k in ks:
            key = str(k)
            aggregate[mode][key] = {}
            aggregate_ci[mode][key] = {}
            for metric_name in _METRICS:
                metric_values = values[mode][key][metric_name]
                aggregate[mode][key][metric_name] = (
                    statistics.fmean(metric_values) if metric_values else None
                )
                aggregate_ci[mode][key][metric_name] = (
                    dict(zip(("ci_95_low", "ci_95_high"), _bootstrap_mean_ci(
                        metric_values, resamples=bootstrap_resamples, rng=rng
                    )))
                    if metric_values
                    else {"ci_95_low": None, "ci_95_high": None}
                )

    case_metric_index = {
        item["case_id"]: item["modes"] for item in case_metrics
    }
    paired: dict[str, object] = {}
    for source_mode in ("keyword", "vector"):
        comparison_name = f"hybrid_rrf_minus_{source_mode}"
        paired[comparison_name] = {}
        for k in ks:
            key = str(k)
            paired[comparison_name][key] = {}
            for metric_name in _METRICS:
                deltas = []
                for case_id in case_ids:
                    modes = case_metric_index[case_id]
                    source = modes[source_mode]
                    hybrid = modes["hybrid_rrf"]
                    if "status" in source or "status" in hybrid:
                        continue
                    deltas.append(hybrid[key][metric_name] - source[key][metric_name])
                if deltas:
                    low, high = _bootstrap_mean_ci(
                        deltas, resamples=bootstrap_resamples, rng=rng
                    )
                    paired[comparison_name][key][metric_name] = {
                        "mean_delta": statistics.fmean(deltas),
                        "paired_case_count": len(deltas),
                        "ci_95_low": low,
                        "ci_95_high": high,
                    }
                else:
                    paired[comparison_name][key][metric_name] = {
                        "mean_delta": None,
                        "paired_case_count": 0,
                        "ci_95_low": None,
                        "ci_95_high": None,
                    }

    return {
        "ks": list(ks),
        "primary_k": primary_k,
        "bootstrap": {
            "method": "case_percentile",
            "confidence_level": 0.95,
            "resamples": bootstrap_resamples,
            "seed": seed,
        },
        "case_metrics": case_metrics,
        "aggregate": aggregate,
        "aggregate_ci_95": aggregate_ci,
        "paired_deltas": paired,
        "operations": {
            mode: _latency_summary(latencies[mode], attempted=len(cases))
            for mode in CANONICAL_MODES
        },
    }


__all__ = ["score_benchmark"]
