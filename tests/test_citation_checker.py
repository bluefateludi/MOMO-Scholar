import pytest

from paper_agent.evidence.citation_checker import check_claims
from paper_agent.schemas import Evidence, ReportClaim


def _evidence(evidence_id: str = "run-b:ev_001") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id="p1",
        chunk_id="p1:chunk:001",
        claim_type="retrieved",
        quote="Source text",
        relevance_score=0.9,
    )


def test_check_claims_supports_current_run_reference():
    checked = check_claims(
        [ReportClaim(claim="Supported", evidence_ids=["run-b:ev_001"])],
        [_evidence()],
        run_id="run-b",
    )
    assert checked[0].support_status == "supported"


def test_check_claims_rejects_cross_run_reference():
    checked = check_claims(
        [ReportClaim(claim="Wrong run", evidence_ids=["run-a:ev_001"])],
        [_evidence()],
        run_id="run-b",
    )
    assert checked[0].support_status == "unsupported"


def test_check_claims_rejects_empty_evidence_ids():
    checked = check_claims(
        [ReportClaim(claim="Empty", evidence_ids=[])],
        [_evidence()],
        run_id="run-b",
    )
    assert checked[0].support_status == "unsupported"


def test_check_claims_rejects_duplicate_evidence_ids():
    duplicate = _evidence()
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        check_claims([], [duplicate, duplicate.model_copy()], run_id="run-b")
