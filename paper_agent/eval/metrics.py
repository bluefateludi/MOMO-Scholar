"""Pure, deterministic evaluation metrics."""

import math

from paper_agent.schemas import Evidence, ReportClaim


def _validate_ranking_inputs(
    ranked_ids: list[str],
    relevance_by_id: dict[str, int],
    k: int,
) -> None:
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if any(not isinstance(item_id, str) for item_id in ranked_ids):
        raise ValueError("ranked IDs must be strings")
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError("ranked IDs must be unique")
    if any(not isinstance(item_id, str) for item_id in relevance_by_id):
        raise ValueError("relevance IDs must be strings")
    if any(
        type(grade) is not int or grade < 0
        for grade in relevance_by_id.values()
    ):
        raise ValueError("grades must be non-negative integers")


def recall_at_k(
    ranked_ids: list[str],
    relevance_by_id: dict[str, int],
    k: int,
) -> float:
    """Return the fraction of relevant IDs retrieved within the Top-K."""
    _validate_ranking_inputs(ranked_ids, relevance_by_id, k)
    relevant_ids = {
        item_id for item_id, grade in relevance_by_id.items() if grade > 0
    }
    if not relevant_ids:
        return 0.0

    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def precision_at_k(
    ranked_ids: list[str],
    relevance_by_id: dict[str, int],
    k: int,
) -> float:
    """Return the relevant fraction of the results actually returned in Top-K."""
    _validate_ranking_inputs(ranked_ids, relevance_by_id, k)
    top_k_ids = ranked_ids[:k]
    if not top_k_ids:
        return 0.0

    relevant_count = sum(
        relevance_by_id.get(item_id, 0) > 0 for item_id in top_k_ids
    )
    return relevant_count / len(top_k_ids)


def mrr_at_k(
    ranked_ids: list[str],
    relevance_by_id: dict[str, int],
    k: int,
) -> float:
    """Return the reciprocal rank of the first relevant result within Top-K."""
    _validate_ranking_inputs(ranked_ids, relevance_by_id, k)
    for rank, item_id in enumerate(ranked_ids[:k], start=1):
        if relevance_by_id.get(item_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked_ids: list[str],
    relevance_by_id: dict[str, int],
    k: int,
) -> float:
    """Return graded normalized discounted cumulative gain within Top-K."""
    _validate_ranking_inputs(ranked_ids, relevance_by_id, k)

    def discounted_gain(grade: int, rank: int) -> float:
        return (2**grade - 1) / math.log2(rank + 1)

    actual_dcg = sum(
        discounted_gain(relevance_by_id.get(item_id, 0), rank)
        for rank, item_id in enumerate(ranked_ids[:k], start=1)
    )
    ideal_dcg = sum(
        discounted_gain(grade, rank)
        for rank, grade in enumerate(
            sorted(relevance_by_id.values(), reverse=True)[:k],
            start=1,
        )
    )
    if ideal_dcg == 0.0:
        return 0.0
    return actual_dcg / ideal_dcg


def retrieval_hit_rate(
    actual_paper_ids: list[str],
    expected_paper_ids: list[str],
) -> float:
    """Return the fraction of unique expected paper IDs that were retrieved."""
    expected = set(expected_paper_ids)
    if not expected:
        return 0.0

    actual = set(actual_paper_ids)
    return len(actual & expected) / len(expected)


def evidence_coverage(claims: list[ReportClaim]) -> float:
    """Return the fraction of claims that cite at least one evidence ID."""
    if not claims:
        return 0.0

    covered_count = sum(bool(claim.evidence_ids) for claim in claims)
    return covered_count / len(claims)


def unsupported_claim_rate(claims: list[ReportClaim]) -> float:
    """Return the fraction of claims explicitly marked as unsupported."""
    if not claims:
        return 0.0

    unsupported_count = sum(
        claim.support_status == "unsupported" for claim in claims
    )
    return unsupported_count / len(claims)


def citation_validity(
    claims: list[ReportClaim],
    evidence: list[Evidence],
) -> float:
    """Return the fraction of citation occurrences present in the evidence set."""
    citation_ids = [
        evidence_id
        for claim in claims
        for evidence_id in claim.evidence_ids
    ]
    if not citation_ids:
        return 0.0

    valid_evidence_ids = {item.evidence_id for item in evidence}
    valid_count = sum(
        evidence_id in valid_evidence_ids for evidence_id in citation_ids
    )
    return valid_count / len(citation_ids)
