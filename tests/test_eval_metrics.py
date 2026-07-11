import pytest

from paper_agent import schemas
from paper_agent.eval import metrics
from paper_agent.eval.metrics import retrieval_hit_rate


def make_evidence(evidence_id: str) -> schemas.Evidence:
    return schemas.Evidence(
        evidence_id=evidence_id,
        paper_id=f"paper-for-{evidence_id}",
        chunk_id=f"chunk-for-{evidence_id}",
        claim_type="finding",
        quote=f"Quote for {evidence_id}",
        relevance_score=1.0,
    )


@pytest.mark.parametrize(
    ("actual_paper_ids", "expected_paper_ids", "expected_rate"),
    [
        (["paper-1", "paper-2"], ["paper-1", "paper-2"], 1.0),
        (["paper-1", "paper-3"], ["paper-1", "paper-2"], 0.5),
        (["paper-3"], ["paper-1", "paper-2"], 0.0),
        ([], ["paper-1"], 0.0),
        (["paper-1"], [], 0.0),
    ],
)
def test_retrieval_hit_rate(
    actual_paper_ids: list[str],
    expected_paper_ids: list[str],
    expected_rate: float,
) -> None:
    assert retrieval_hit_rate(actual_paper_ids, expected_paper_ids) == expected_rate


def test_retrieval_hit_rate_deduplicates_actual_and_expected_ids() -> None:
    assert retrieval_hit_rate(
        ["paper-1", "paper-1"],
        ["paper-1", "paper-1", "paper-2"],
    ) == 0.5


def test_retrieval_hit_rate_uses_exact_string_matching() -> None:
    assert retrieval_hit_rate(["ARXIV:paper-1"], ["arxiv:paper-1"]) == 0.0


def test_retrieval_hit_rate_stays_within_unit_interval() -> None:
    result = retrieval_hit_rate(
        ["paper-1", "paper-1", "paper-2", "paper-3"],
        ["paper-1", "paper-1", "paper-2"],
    )

    assert 0.0 <= result <= 1.0


def test_evidence_coverage_counts_claims_with_evidence_ids() -> None:
    claims = [
        schemas.ReportClaim(claim="Covered", evidence_ids=["ev-1"]),
        schemas.ReportClaim(claim="Also covered", evidence_ids=["ev-2"]),
        schemas.ReportClaim(claim="Not covered", evidence_ids=[]),
        schemas.ReportClaim(claim="Still not covered", evidence_ids=[]),
    ]

    assert metrics.evidence_coverage(claims) == 0.5


def test_evidence_coverage_returns_zero_for_empty_claims() -> None:
    assert metrics.evidence_coverage([]) == 0.0


def test_evidence_coverage_returns_one_when_all_claims_have_evidence() -> None:
    claims = [
        schemas.ReportClaim(claim="First", evidence_ids=["ev-1"]),
        schemas.ReportClaim(claim="Second", evidence_ids=["ev-2", "ev-3"]),
    ]

    assert metrics.evidence_coverage(claims) == 1.0


def test_unsupported_claim_rate_counts_only_unsupported_claims() -> None:
    claims = [
        schemas.ReportClaim(claim="Supported", support_status="supported"),
        schemas.ReportClaim(
            claim="Weakly supported",
            support_status="weakly_supported",
        ),
        schemas.ReportClaim(claim="Unsupported", support_status="unsupported"),
        schemas.ReportClaim(claim="Also unsupported", support_status="unsupported"),
    ]

    assert metrics.unsupported_claim_rate(claims) == 0.5


def test_unsupported_claim_rate_returns_zero_for_empty_claims() -> None:
    assert metrics.unsupported_claim_rate([]) == 0.0


def test_citation_validity_returns_one_when_all_citations_exist() -> None:
    claims = [schemas.ReportClaim(claim="Claim", evidence_ids=["ev-1", "ev-2"])]
    evidence = [make_evidence("ev-1"), make_evidence("ev-2")]

    assert metrics.citation_validity(claims, evidence) == 1.0


def test_citation_validity_returns_fraction_of_citations_that_exist() -> None:
    claims = [
        schemas.ReportClaim(
            claim="Claim",
            evidence_ids=["ev-1", "missing", "ev-2"],
        )
    ]
    evidence = [make_evidence("ev-1"), make_evidence("ev-2")]

    assert metrics.citation_validity(claims, evidence) == pytest.approx(2 / 3)


def test_citation_validity_returns_zero_when_all_citations_are_invalid() -> None:
    claims = [schemas.ReportClaim(claim="Claim", evidence_ids=["missing-1", "missing-2"])]

    assert metrics.citation_validity(claims, [make_evidence("ev-1")]) == 0.0


def test_citation_validity_returns_zero_when_there_are_no_citations() -> None:
    claims = [schemas.ReportClaim(claim="Claim", evidence_ids=[])]

    assert metrics.citation_validity(claims, [make_evidence("ev-1")]) == 0.0


def test_citation_validity_returns_zero_when_evidence_is_empty() -> None:
    claims = [schemas.ReportClaim(claim="Claim", evidence_ids=["ev-1"])]

    assert metrics.citation_validity(claims, []) == 0.0


def test_citation_validity_counts_duplicate_citations_within_claim_by_occurrence() -> None:
    claims = [
        schemas.ReportClaim(
            claim="Claim",
            evidence_ids=["ev-1", "ev-1", "missing"],
        )
    ]

    assert metrics.citation_validity(claims, [make_evidence("ev-1")]) == pytest.approx(2 / 3)


def test_citation_validity_counts_same_citation_in_different_claims_separately() -> None:
    claims = [
        schemas.ReportClaim(claim="First", evidence_ids=["ev-1"]),
        schemas.ReportClaim(claim="Second", evidence_ids=["ev-1", "missing"]),
    ]

    assert metrics.citation_validity(claims, [make_evidence("ev-1")]) == pytest.approx(2 / 3)


def test_evaluation_metrics_stay_within_unit_interval() -> None:
    claims = [
        schemas.ReportClaim(
            claim="Supported",
            evidence_ids=["ev-1", "missing"],
            support_status="supported",
        ),
        schemas.ReportClaim(
            claim="Unsupported",
            evidence_ids=[],
            support_status="unsupported",
        ),
    ]
    evidence = [make_evidence("ev-1")]
    results = [
        metrics.retrieval_hit_rate(["paper-1"], ["paper-1", "paper-2"]),
        metrics.evidence_coverage(claims),
        metrics.unsupported_claim_rate(claims),
        metrics.citation_validity(claims, evidence),
    ]

    assert all(0.0 <= result <= 1.0 for result in results)
