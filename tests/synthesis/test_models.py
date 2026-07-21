import pytest
from pydantic import ValidationError

from paper_agent.synthesis.models import (
    CheckedClaim,
    CheckedFinding,
    CheckedPaperAnalysis,
    CheckedSurveyReport,
    GroundedClaim,
    GroundedFinding,
    PaperAnalysis,
    RejectedCriticalClaim,
    SurveyDraft,
)


def _claim(status: str = "supported", evidence_ids: list[str] | None = None) -> CheckedClaim:
    return CheckedClaim(
        text="claim",
        evidence_ids=["run:ev_001"] if evidence_ids is None else evidence_ids,
        support_status=status,
    )


def test_grounded_items_require_evidence() -> None:
    for model in (GroundedFinding, GroundedClaim):
        with pytest.raises(ValidationError):
            model(text="claim", evidence_ids=[])


def test_paper_analysis_category_defaults_are_isolated() -> None:
    first = PaperAnalysis(paper_id="p1")
    second = PaperAnalysis(paper_id="p2")

    first.contributions.append(
        GroundedFinding(text="finding", evidence_ids=["run:ev_001"])
    )

    assert second.contributions == []
    assert first.methods == []
    assert first.experiments == []
    assert first.results == []
    assert first.limitations == []


def test_survey_draft_requires_all_categories() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        SurveyDraft(tldr_claims=[])


def test_checked_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        CheckedFinding(text="finding", evidence_ids=[], support_status="unsupported")


def test_checked_paper_analysis_defaults_are_isolated() -> None:
    first = CheckedPaperAnalysis(paper_id="p1")
    second = CheckedPaperAnalysis(paper_id="p2")

    first.methods.append(
        CheckedFinding(
            text="method", evidence_ids=["run:ev_001"], support_status="supported"
        )
    )

    assert second.methods == []


def test_checked_claim_allows_empty_evidence_only_when_unsupported() -> None:
    unsupported = _claim(status="unsupported", evidence_ids=[])
    assert unsupported.evidence_ids == []

    for status in ("supported", "weakly_supported"):
        with pytest.raises(ValidationError, match="requires evidence"):
            _claim(status=status, evidence_ids=[])


def test_checked_report_rejects_unsupported_critical_claim() -> None:
    with pytest.raises(ValidationError, match="critical claims must be supported"):
        CheckedSurveyReport(
            question="q",
            tldr_claims=[_claim(status="unsupported", evidence_ids=[])],
        )


def test_checked_report_rejects_weak_key_finding() -> None:
    with pytest.raises(ValidationError, match="critical claims must be supported"):
        CheckedSurveyReport(
            question="q",
            key_findings=[_claim(status="weakly_supported")],
        )


@pytest.mark.parametrize("status", ["weakly_supported", "unsupported"])
def test_rejected_critical_claim_accepts_non_supported_status(status: str) -> None:
    evidence_ids = [] if status == "unsupported" else ["run:ev_001"]
    rejected = RejectedCriticalClaim(
        text="claim",
        evidence_ids=evidence_ids,
        support_status=status,
        source_section="tldr_claims",
    )
    assert rejected.support_status == status


def test_rejected_critical_claim_rejects_supported_status() -> None:
    with pytest.raises(ValidationError, match="rejected critical claims must not be supported"):
        RejectedCriticalClaim(
            text="claim",
            evidence_ids=["run:ev_001"],
            support_status="supported",
            source_section="key_findings",
        )


def test_checked_report_defaults_are_isolated() -> None:
    first = CheckedSurveyReport(question="q1")
    second = CheckedSurveyReport(question="q2")

    first.comparisons.append(_claim())

    assert second.comparisons == []


def test_synthesis_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        GroundedFinding(
            text="finding", evidence_ids=["run:ev_001"], unexpected=True
        )
