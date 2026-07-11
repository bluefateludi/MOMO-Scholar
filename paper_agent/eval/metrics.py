"""Pure, deterministic evaluation metrics."""

from paper_agent.schemas import Evidence, ReportClaim


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
