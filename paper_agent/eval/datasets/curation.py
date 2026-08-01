from __future__ import annotations

import hashlib
from collections import Counter
from typing import NamedTuple

from paper_agent.eval.contracts import EvalCase


class CuratedValidationCases(NamedTuple):
    retrieval: tuple[EvalCase, ...]
    citation: tuple[EvalCase, ...]

    @property
    def combined(self) -> tuple[EvalCase, ...]:
        return tuple(
            sorted(self.retrieval + self.citation, key=lambda case: case.case_id)
        )


def _rank(case: EvalCase) -> tuple[str, str]:
    digest = hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()
    return digest, case.case_id


def curate_validation_cases(
    cases: tuple[EvalCase, ...],
    *,
    retrieval_per_source: int = 20,
    citation_per_source: int = 10,
) -> CuratedValidationCases:
    """Select source-balanced, disjoint cases without changing upstream Gold."""
    if retrieval_per_source < 1 or citation_per_source < 1:
        raise ValueError("track counts per source must be positive")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("candidate case IDs must be unique")
    if any(case.metadata.split != "validation" for case in cases):
        raise ValueError("all candidate cases must belong to validation")

    by_source: dict[str, list[EvalCase]] = {"SciFact": [], "QASPER": []}
    for case in cases:
        try:
            by_source[case.metadata.source].append(case)
        except KeyError as error:
            raise ValueError("candidate case has an unsupported source") from error

    needed = retrieval_per_source + citation_per_source
    retrieval: list[EvalCase] = []
    citation: list[EvalCase] = []
    for source in ("SciFact", "QASPER"):
        ranked = sorted(by_source[source], key=_rank)
        if len(ranked) < needed:
            raise ValueError(f"{source} has fewer than {needed} eligible cases")
        retrieval.extend(ranked[:retrieval_per_source])
        citation.extend(ranked[retrieval_per_source:needed])

    result = CuratedValidationCases(
        retrieval=tuple(sorted(retrieval, key=lambda case: case.case_id)),
        citation=tuple(sorted(citation, key=lambda case: case.case_id)),
    )
    combined_ids = [case.case_id for case in result.combined]
    if len(combined_ids) != len(set(combined_ids)):
        raise AssertionError("curated tracks must be disjoint")
    expected_counts = {
        "SciFact": retrieval_per_source + citation_per_source,
        "QASPER": retrieval_per_source + citation_per_source,
    }
    if Counter(case.metadata.source for case in result.combined) != expected_counts:
        raise AssertionError("curated source counts are inconsistent")
    return result


__all__ = ["CuratedValidationCases", "curate_validation_cases"]
