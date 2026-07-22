import pytest

from paper_agent.evidence.citation_checker import (
    CheckedAnalysisOutcome,
    check_claims,
    check_paper_analysis,
    check_survey_draft,
    require_publishable_report,
)
from paper_agent.schemas import Evidence, ReportClaim
from paper_agent.synthesis.models import (
    GroundedClaim,
    GroundedFinding,
    PaperAnalysis,
    SurveyDraft,
)


def _evidence(evidence_id: str = "run-b:ev_001") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id="p1",
        chunk_id="p1:chunk:001",
        section="Methods",
        page=3,
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


def _finding(text: str, *evidence_ids: str) -> GroundedFinding:
    return GroundedFinding(text=text, evidence_ids=list(evidence_ids))


def _claim(text: str, *evidence_ids: str) -> GroundedClaim:
    return GroundedClaim(text=text, evidence_ids=list(evidence_ids))


def _draft(**overrides: list[GroundedClaim]) -> SurveyDraft:
    values = {
        "tldr_claims": [],
        "method_taxonomy": [],
        "comparisons": [],
        "key_findings": [],
        "limitations": [],
        "open_questions": [],
    }
    values.update(overrides)
    return SurveyDraft(**values)


def test_check_paper_analysis_sanitizes_references_and_drops_ungrounded_findings():
    evidence = [
        _evidence("run-b:paper:p1:ev_001"),
        _evidence("run-b:paper:p1:ev_002"),
        _evidence("run-b:paper:p2:ev_001").model_copy(update={"paper_id": "p2"}),
        _evidence("run-a:paper:p1:ev_001"),
    ]
    analysis = PaperAnalysis(
        paper_id="p1",
        contributions=[
            _finding(
                "all valid",
                "run-b:paper:p1:ev_001",
                "run-b:paper:p1:ev_002",
            )
        ],
        methods=[
            _finding(
                "mixed",
                "run-b:paper:p1:ev_002",
                "run-b:paper:p1:ev_002",
                "run-b:paper:p1:missing",
                "run-b:paper:p2:ev_001",
                "run-a:paper:p1:ev_001",
                "run-b:paper:p1:ev_001",
            )
        ],
        results=[
            _finding(
                "drop me",
                "run-b:paper:p1:missing",
                "run-b:paper:p2:ev_001",
            )
        ],
    )

    outcome = check_paper_analysis(analysis, evidence, run_id="run-b")

    assert isinstance(outcome, CheckedAnalysisOutcome)
    assert outcome.analysis.contributions[0].support_status == "supported"
    assert outcome.analysis.methods[0].support_status == "weakly_supported"
    assert outcome.analysis.methods[0].evidence_ids == [
        "run-b:paper:p1:ev_002",
        "run-b:paper:p1:ev_001",
    ]
    assert outcome.analysis.results == []
    assert outcome.sanitized_reference_count == 6
    assert outcome.dropped_finding_count == 1
    assert outcome.has_supported_finding is True


def test_check_paper_analysis_requires_a_supported_finding_for_success():
    outcome = check_paper_analysis(
        PaperAnalysis(
            paper_id="p1",
            limitations=[_finding("mixed", "run-b:paper:p1:ev_001", "unknown")],
        ),
        [_evidence("run-b:paper:p1:ev_001")],
        run_id="run-b",
    )

    assert outcome.analysis.limitations[0].support_status == "weakly_supported"
    assert outcome.has_supported_finding is False


def test_check_paper_analysis_rejects_duplicate_evidence_index():
    duplicate = _evidence("run-b:paper:p1:ev_001")
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        check_paper_analysis(
            PaperAnalysis(paper_id="p1"),
            [duplicate, duplicate.model_copy()],
            run_id="run-b",
        )


def test_check_survey_draft_relocates_non_supported_critical_claims():
    report = check_survey_draft(
        "What works?",
        _draft(
            tldr_claims=[
                _claim("supported", "run-b:paper:p1:ev_001"),
                _claim("weak", "run-b:paper:p1:ev_001", "unknown"),
                _claim("unsupported", "unknown"),
            ],
            key_findings=[_claim("key", "run-b:paper:p1:ev_001")],
            limitations=[
                _claim("weak limitation", "run-b:paper:p1:ev_001", "unknown"),
                _claim("unsupported limitation", "unknown"),
            ],
        ),
        [_evidence("run-b:paper:p1:ev_001")],
        run_id="run-b",
    )

    assert report.question == "What works?"
    assert [claim.text for claim in report.tldr_claims] == ["supported"]
    assert [claim.support_status for claim in report.rejected_critical_claims] == [
        "weakly_supported",
        "unsupported",
    ]
    assert [claim.source_section for claim in report.rejected_critical_claims] == [
        "tldr_claims",
        "tldr_claims",
    ]
    assert [claim.support_status for claim in report.limitations] == [
        "weakly_supported",
        "unsupported",
    ]
    assert report.limitations[0].evidence_ids == ["run-b:paper:p1:ev_001"]
    assert report.limitations[1].evidence_ids == []


def test_check_survey_draft_rejects_empty_question_and_duplicate_evidence_index():
    duplicate = _evidence("run-b:paper:p1:ev_001")
    with pytest.raises(ValueError):
        check_survey_draft("", _draft(), [duplicate], run_id="run-b")
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        check_survey_draft(
            "Question",
            _draft(),
            [duplicate, duplicate.model_copy()],
            run_id="run-b",
        )


def test_require_publishable_report_enforces_both_critical_minimums():
    evidence = [_evidence("run-b:paper:p1:ev_001")]
    publishable = check_survey_draft(
        "Question",
        _draft(
            tldr_claims=[_claim("tldr", "run-b:paper:p1:ev_001")],
            key_findings=[_claim("key", "run-b:paper:p1:ev_001")],
        ),
        evidence,
        run_id="run-b",
    )
    require_publishable_report(publishable)

    for incomplete in (
        publishable.model_copy(update={"tldr_claims": []}),
        publishable.model_copy(update={"key_findings": []}),
        publishable.model_copy(
            update={
                "tldr_claims": [
                    publishable.tldr_claims[0].model_copy(
                        update={"support_status": "weakly_supported"}
                    )
                ]
            }
        ),
    ):
        with pytest.raises(ValueError, match="insufficient_supported_report"):
            require_publishable_report(incomplete)
