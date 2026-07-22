from __future__ import annotations

import inspect

import pytest

from paper_agent.fulltext.models import DocumentRecord
from paper_agent.rendering.markdown import render_formal_report
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import (
    CheckedClaim,
    CheckedSurveyReport,
    RejectedCriticalClaim,
)


def _paper(paper_id: str = "p1", title: str = "Grounded Agents") -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        authors=["Ada Author"],
        year=2025,
        abstract="Raw abstract text must not be copied into the formal report.",
        url=f"https://example.test/{paper_id}",
        source="test",
    )


def _document(
    paper_id: str = "p1",
    *,
    content_source: str = "pdf",
    fallback_code: str | None = None,
) -> DocumentRecord:
    return DocumentRecord(
        paper_id=paper_id,
        content_source=content_source,
        content_sha256="a" * 64,
        page_count=3,
        fallback_code=fallback_code,
    )


def _evidence(
    evidence_id: str = "run-1:paper:p1:ev_001",
    *,
    paper_id: str = "p1",
    section: str | None = "Methods",
    page: int | None = 2,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id=paper_id,
        chunk_id=f"{paper_id}:chunk:001",
        section=section,
        page=page,
        claim_type="method",
        quote="Exact selected evidence quote.",
        relevance_score=0.9,
    )


def _claim(
    text: str,
    *,
    evidence_ids: list[str] | None = None,
    support_status: str = "supported",
) -> CheckedClaim:
    return CheckedClaim(
        text=text,
        evidence_ids=(
            ["run-1:paper:p1:ev_001"]
            if evidence_ids is None
            else evidence_ids
        ),
        support_status=support_status,
    )


def _complete_report() -> CheckedSurveyReport:
    return CheckedSurveyReport(
        question="How do agents stay grounded?",
        tldr_claims=[_claim("TLDR supported claim")],
        method_taxonomy=[_claim("Method claim")],
        comparisons=[_claim("Comparison claim")],
        key_findings=[_claim("Key supported claim")],
        limitations=[_claim("Limitation claim")],
        open_questions=[_claim("Open question claim")],
    )


def _render(
    *,
    papers: list[Paper] | None = None,
    documents: list[DocumentRecord] | None = None,
    evidence: list[Evidence] | None = None,
    report: CheckedSurveyReport | None = None,
    status: str = "completed_with_degradation",
) -> str:
    return render_formal_report(
        status=status,
        papers=[_paper()] if papers is None else papers,
        documents=[_document()] if documents is None else documents,
        evidence=[_evidence()] if evidence is None else evidence,
        report=_complete_report() if report is None else report,
    )


def test_renders_formal_sections_in_order_with_complete_provenance() -> None:
    markdown = _render()

    expected = [
        "# Formal Survey: How do agents stay grounded?",
        "Status: completed_with_degradation",
        "## TL;DR",
        "## Selected Papers",
        "## Method Taxonomy",
        "## Cross-Paper Comparison",
        "## Key Findings",
        "## Limitations",
        "## Open Questions",
        "## Evidence Trace",
    ]
    positions = [markdown.index(item) for item in expected]
    assert positions == sorted(positions)
    assert "Grounded Agents" in markdown
    assert "Content source: PDF" in markdown
    assert "[run-1:paper:p1:ev_001]" in markdown
    assert "Paper: Grounded Agents" in markdown
    assert "Section: Methods" in markdown
    assert "Page: 2" in markdown
    assert "Chunk: p1:chunk:001" in markdown
    assert "Quote: Exact selected evidence quote." in markdown


def test_renders_pdf_abstract_and_fallback_source_labels() -> None:
    papers = [
        _paper("p1", "PDF Paper"),
        _paper("p2", "Abstract Paper"),
        _paper("p3", "Fallback Paper"),
    ]
    documents = [
        _document("p1"),
        _document("p2", content_source="abstract"),
        _document("p3", content_source="abstract", fallback_code="pdf_text_empty"),
    ]
    evidence = [
        _evidence(),
        _evidence("run-1:paper:p2:ev_001", paper_id="p2"),
        _evidence("run-1:paper:p3:ev_001", paper_id="p3"),
    ]

    markdown = _render(papers=papers, documents=documents, evidence=evidence)

    assert "PDF Paper — Content source: PDF" in markdown
    assert "Abstract Paper — Content source: abstract" in markdown
    assert (
        "Fallback Paper — Content source: abstract fallback (pdf_text_empty)"
        in markdown
    )


def test_unknown_section_and_page_are_explicit() -> None:
    markdown = _render(evidence=[_evidence(section=None, page=None)])

    assert "Section: Unknown section" in markdown
    assert "Page: Unknown page" in markdown


def test_rejected_critical_claims_are_not_rendered_and_noncritical_statuses_are_labeled(
) -> None:
    report = CheckedSurveyReport(
        question="Checked only",
        tldr_claims=[_claim("Safe TLDR")],
        method_taxonomy=[
            _claim("Weak method", support_status="weakly_supported"),
            _claim("Unsupported method", evidence_ids=[], support_status="unsupported"),
        ],
        key_findings=[_claim("Safe finding")],
        rejected_critical_claims=[
            RejectedCriticalClaim(
                text="Rejected critical text",
                evidence_ids=[],
                support_status="unsupported",
                source_section="tldr_claims",
            )
        ],
    )

    markdown = _render(report=report)

    assert "Rejected critical text" not in markdown
    assert "Weak method [weakly supported]" in markdown
    assert "Unsupported method [unsupported]" in markdown


def test_empty_categories_do_not_invent_claims() -> None:
    report = CheckedSurveyReport(question="Empty categories")

    markdown = _render(report=report, evidence=[])

    for heading in (
        "## TL;DR",
        "## Method Taxonomy",
        "## Cross-Paper Comparison",
        "## Key Findings",
        "## Limitations",
        "## Open Questions",
    ):
        assert heading in markdown
    assert "No claims" not in markdown
    assert "No evidence" not in markdown
    assert "Raw abstract text" not in markdown


def test_identical_checked_inputs_produce_identical_markdown() -> None:
    assert _render() == _render()


def test_renderer_accepts_only_checked_artifact_inputs() -> None:
    assert list(inspect.signature(render_formal_report).parameters) == [
        "status",
        "papers",
        "documents",
        "evidence",
        "report",
    ]


@pytest.mark.parametrize(
    ("field", "values", "message"),
    [
        ("papers", [_paper(), _paper()], "duplicate paper ID"),
        ("documents", [_document(), _document()], "duplicate document paper ID"),
        ("evidence", [_evidence(), _evidence()], "duplicate evidence ID"),
    ],
)
def test_rejects_duplicate_artifact_ids(
    field: str, values: list[object], message: str
) -> None:
    kwargs = {field: values}
    with pytest.raises(ValueError, match=message):
        _render(**kwargs)


def test_rejects_missing_document_for_retained_paper() -> None:
    with pytest.raises(ValueError, match="missing document for paper ID: p1"):
        _render(documents=[])


def test_rejects_evidence_for_unknown_paper() -> None:
    with pytest.raises(ValueError, match="evidence references unknown paper ID: p2"):
        _render(evidence=[_evidence(paper_id="p2")])


def test_rejects_unknown_claim_evidence_reference() -> None:
    report = CheckedSurveyReport(
        question="Bad reference",
        tldr_claims=[_claim("Bad claim", evidence_ids=["missing-evidence"])],
    )

    with pytest.raises(ValueError, match="unknown evidence ID: missing-evidence"):
        _render(report=report)
