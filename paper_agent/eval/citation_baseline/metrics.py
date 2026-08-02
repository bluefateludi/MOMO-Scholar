from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    AtomicAssertion,
    CitationOccurrence,
    EvidenceMatch,
)


class SemanticJudgment(Protocol):
    @property
    def judgment_id(self) -> str: ...

    case_id: str
    assertion_id: str
    semantic_verdict: str


BOOTSTRAP_SEED = 20_260_726
BOOTSTRAP_RESAMPLES = 10_000
_METRIC_NAMES = (
    "citation_coverage",
    "citation_validity",
    "unsupported_assertion_rate",
)


@dataclass(frozen=True, slots=True)
class CitationCaseInput:
    case_id: str
    assertions: tuple[AtomicAssertion, ...] = ()
    citation_occurrences: tuple[CitationOccurrence, ...] = ()
    evidence_matches: tuple[EvidenceMatch, ...] = ()
    judgments: tuple[SemanticJudgment, ...] = ()
    unscorable_assertion_ids: tuple[str, ...] = ()
    duration_ms: float | None = None
    failure_reason_code: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if self.duration_ms is None or (
            not math.isfinite(self.duration_ms) or self.duration_ms < 0
        ):
            raise ValueError("duration_ms must be finite and non-negative")
        if self.failure_reason_code is not None:
            if not self.failure_reason_code.strip():
                raise ValueError("failure_reason_code must not be blank")
            if any(
                (
                    self.assertions,
                    self.citation_occurrences,
                    self.evidence_matches,
                    self.judgments,
                    self.unscorable_assertion_ids,
                )
            ):
                raise ValueError("failed case must not include scoring records")


def _unique_index(items: Sequence[object], field: str, label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in items:
        value = getattr(item, field)
        if value in result:
            raise ValueError(f"{label} must be unique")
        result[value] = item
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metric(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": _ratio(numerator, denominator),
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
    values: Sequence[float], *, rng: random.Random
) -> tuple[float, float]:
    sampled_means = [
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(BOOTSTRAP_RESAMPLES)
    ]
    return _percentile(sampled_means, 0.025), _percentile(sampled_means, 0.975)


def _score_case(case: CitationCaseInput) -> dict[str, object]:
    assertions = _unique_index(case.assertions, "assertion_id", "assertion IDs")
    occurrences = _unique_index(
        case.citation_occurrences, "occurrence_id", "citation occurrence IDs"
    )
    matches = _unique_index(case.evidence_matches, "match_id", "evidence match IDs")
    judgments = _unique_index(case.judgments, "judgment_id", "judgment IDs")

    if any(
        assertion.case_id != case.case_id for assertion in case.assertions
    ):
        raise ValueError("assertion case IDs must match their metrics case")
    if any(
        occurrence.assertion_id not in assertions
        for occurrence in case.citation_occurrences
    ):
        raise ValueError("citation occurrence assertion reference is dangling")
    if any(
        match.assertion_id not in assertions
        or match.citation_occurrence_id not in occurrences
        for match in case.evidence_matches
    ):
        raise ValueError("evidence match reference is dangling")
    if any(
        judgment.case_id != case.case_id
        or judgment.assertion_id not in assertions
        for judgment in case.judgments
    ):
        raise ValueError("judgment case or assertion reference is invalid")

    judgment_by_assertion: dict[str, SemanticJudgment] = {}
    for judgment in judgments.values():
        if judgment.assertion_id in judgment_by_assertion:
            raise ValueError("assertions must have at most one final judgment")
        judgment_by_assertion[judgment.assertion_id] = judgment

    unscorable = set(case.unscorable_assertion_ids)
    if len(unscorable) != len(case.unscorable_assertion_ids):
        raise ValueError("unscorable assertion IDs must be unique")
    if not unscorable <= assertions.keys():
        raise ValueError("unscorable assertion reference is dangling")

    matched_supported = {
        match.assertion_id
        for match in matches.values()
        if isinstance(match, EvidenceMatch) and match.supports_assertion
    }
    supported = {
        assertion_id
        for assertion_id, judgment in judgment_by_assertion.items()
        if judgment.semantic_verdict == "supported"
    } | matched_supported
    unsupported = {
        assertion_id
        for assertion_id, judgment in judgment_by_assertion.items()
        if judgment.semantic_verdict == "unsupported"
    }
    ambiguous = {
        assertion_id
        for assertion_id, judgment in judgment_by_assertion.items()
        if judgment.semantic_verdict == "ambiguous"
    }
    statuses = (supported, unsupported, ambiguous, unscorable)
    if set.union(*statuses) != assertions.keys() or sum(map(len, statuses)) != len(
        assertions
    ):
        raise ValueError("each assertion must have exactly one semantic status")

    cited_assertions = {
        occurrence.assertion_id for occurrence in case.citation_occurrences
    }
    structurally_valid = sum(
        occurrence.structurally_valid for occurrence in case.citation_occurrences
    )
    scorable_count = len(supported) + len(unsupported)
    return {
        "case_id": case.case_id,
        "status": "completed",
        "duration_ms": case.duration_ms,
        "metrics": {
            "citation_coverage": _metric(len(cited_assertions), len(assertions)),
            "citation_validity": _metric(
                structurally_valid, len(case.citation_occurrences)
            ),
            "unsupported_assertion_rate": _metric(
                len(unsupported), scorable_count
            ),
        },
        "assertion_status_counts": {
            "supported": len(supported),
            "unsupported": len(unsupported),
            "ambiguous": len(ambiguous),
            "unscorable": len(unscorable),
        },
    }


def score_citation_baseline(*, cases: Sequence[CitationCaseInput]) -> dict[str, object]:
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")

    case_metrics: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    latencies: list[float] = []
    for case in cases:
        if case.failure_reason_code is not None:
            case_metrics.append(
                {
                    "case_id": case.case_id,
                    "status": "error",
                    "reason_code": case.failure_reason_code,
                    "duration_ms": case.duration_ms,
                }
            )
            continue
        scored = _score_case(case)
        case_metrics.append(scored)
        completed.append(scored)
        assert case.duration_ms is not None
        latencies.append(case.duration_ms)

    rng = random.Random(BOOTSTRAP_SEED)
    aggregate: dict[str, dict[str, float | int | None]] = {}
    for metric_name in _METRIC_NAMES:
        values = [
            metric["value"]
            for item in completed
            for metric in (item["metrics"][metric_name],)
            if metric["value"] is not None
        ]
        if values:
            low, high = _bootstrap_mean_ci(values, rng=rng)
            aggregate[metric_name] = {
                "macro_mean": statistics.fmean(values),
                "case_denominator": len(values),
                "ci_95_low": low,
                "ci_95_high": high,
            }
        else:
            aggregate[metric_name] = {
                "macro_mean": None,
                "case_denominator": 0,
                "ci_95_low": None,
                "ci_95_high": None,
            }

    status_counts = {
        status: sum(item["assertion_status_counts"][status] for item in completed)
        for status in ("supported", "unsupported", "ambiguous", "unscorable")
    }
    attempted = len(cases)
    completed_count = len(completed)
    failed = attempted - completed_count
    return {
        "bootstrap": {
            "method": "case_percentile",
            "confidence_level": 0.95,
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "case_metrics": case_metrics,
        "aggregate": aggregate,
        "assertion_status_counts": status_counts,
        "denominators": {
            "attempted_cases": attempted,
            "completed_cases": completed_count,
            "assertions": sum(
                item["metrics"]["citation_coverage"]["denominator"]
                for item in completed
            ),
            "citations": sum(
                item["metrics"]["citation_validity"]["denominator"]
                for item in completed
            ),
            "scorable_assertions": status_counts["supported"]
            + status_counts["unsupported"],
        },
        "operations": {
            "attempted": attempted,
            "completed": completed_count,
            "failed": failed,
            "failure_rate": failed / attempted if attempted else 0.0,
            "completed_latency_ms_p50": (
                statistics.median(latencies) if latencies else None
            ),
            "completed_latency_ms_p95": (
                _percentile(latencies, 0.95) if latencies else None
            ),
        },
    }


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CitationCaseInput",
    "score_citation_baseline",
]
