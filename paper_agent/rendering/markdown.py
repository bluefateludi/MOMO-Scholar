from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from paper_agent.fulltext.models import DocumentRecord
from paper_agent.schemas import Evidence, Paper, ReportClaim
from paper_agent.synthesis.models import CheckedClaim, CheckedSurveyReport


FormalReportStatus = Literal["completed", "completed_with_degradation"]


def _index_unique(
    items: Sequence[object], attribute: str, label: str
) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for item in items:
        identifier = getattr(item, attribute)
        if identifier in indexed:
            raise ValueError(f"duplicate {label}: {identifier}")
        indexed[identifier] = item
    return indexed


def _iter_report_claims(report: CheckedSurveyReport) -> list[CheckedClaim]:
    return [
        *report.tldr_claims,
        *report.method_taxonomy,
        *report.comparisons,
        *report.key_findings,
        *report.limitations,
        *report.open_questions,
        *report.rejected_critical_claims,
    ]


def _validate_formal_report_inputs(
    *,
    status: FormalReportStatus,
    papers: Sequence[Paper],
    documents: Sequence[DocumentRecord],
    evidence: Sequence[Evidence],
    report: CheckedSurveyReport,
) -> tuple[dict[str, Paper], dict[str, DocumentRecord], dict[str, Evidence]]:
    if status not in ("completed", "completed_with_degradation"):
        raise ValueError(f"invalid formal report status: {status}")

    paper_by_id = _index_unique(papers, "paper_id", "paper ID")
    document_by_id = _index_unique(documents, "paper_id", "document paper ID")
    evidence_by_id = _index_unique(evidence, "evidence_id", "evidence ID")

    for paper_id in paper_by_id:
        if paper_id not in document_by_id:
            raise ValueError(f"missing document for paper ID: {paper_id}")
    for paper_id in document_by_id:
        if paper_id not in paper_by_id:
            raise ValueError(f"document references unknown paper ID: {paper_id}")
    for item in evidence:
        if item.paper_id not in paper_by_id:
            raise ValueError(
                f"evidence references unknown paper ID: {item.paper_id}"
            )
    for claim in _iter_report_claims(report):
        for evidence_id in claim.evidence_ids:
            if evidence_id not in evidence_by_id:
                raise ValueError(f"unknown evidence ID: {evidence_id}")

    return paper_by_id, document_by_id, evidence_by_id


def _content_source_label(document: DocumentRecord) -> str:
    if document.content_source == "pdf":
        return "PDF"
    if document.fallback_code:
        return f"abstract fallback ({document.fallback_code})"
    return "abstract"


def _evidence_markers(claim: CheckedClaim) -> str:
    return " ".join(f"[{evidence_id}]" for evidence_id in claim.evidence_ids)


def _render_claim(claim: CheckedClaim, *, critical: bool) -> str:
    status_label = ""
    if not critical and claim.support_status != "supported":
        status_label = f" [{claim.support_status.replace('_', ' ')}]"
    markers = _evidence_markers(claim)
    marker_suffix = f" {markers}" if markers else ""
    return f"- {claim.text}{status_label}{marker_suffix}"


def _append_claim_section(
    lines: list[str],
    heading: str,
    claims: Sequence[CheckedClaim],
    *,
    critical: bool = False,
) -> None:
    lines.extend([f"## {heading}", ""])
    lines.extend(_render_claim(claim, critical=critical) for claim in claims)
    if claims:
        lines.append("")


def render_formal_report(
    *,
    status: FormalReportStatus,
    papers: Sequence[Paper],
    documents: Sequence[DocumentRecord],
    evidence: Sequence[Evidence],
    report: CheckedSurveyReport,
) -> str:
    paper_by_id, document_by_id, _ = _validate_formal_report_inputs(
        status=status,
        papers=papers,
        documents=documents,
        evidence=evidence,
        report=report,
    )

    lines = [
        f"# Formal Survey: {report.question}",
        "",
        f"Status: {status}",
        "",
    ]
    _append_claim_section(lines, "TL;DR", report.tldr_claims, critical=True)

    lines.extend(["## Selected Papers", ""])
    for paper in papers:
        source = _content_source_label(document_by_id[paper.paper_id])
        lines.append(f"- {paper.title} — Content source: {source}")
    if papers:
        lines.append("")

    _append_claim_section(lines, "Method Taxonomy", report.method_taxonomy)
    _append_claim_section(lines, "Cross-Paper Comparison", report.comparisons)
    _append_claim_section(
        lines, "Key Findings", report.key_findings, critical=True
    )
    _append_claim_section(lines, "Limitations", report.limitations)
    _append_claim_section(lines, "Open Questions", report.open_questions)

    lines.extend(["## Evidence Trace", ""])
    for item in evidence:
        paper = paper_by_id[item.paper_id]
        section = item.section or "Unknown section"
        page = str(item.page) if item.page is not None else "Unknown page"
        lines.extend(
            [
                f"### [{item.evidence_id}]",
                "",
                f"- Paper: {paper.title}",
                f"- Section: {section}",
                f"- Page: {page}",
                f"- Chunk: {item.chunk_id}",
                f"- Quote: {item.quote}",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def render_initial_review(question: str, papers: list[Paper]) -> str:
    lines = [
        f"# Mini Survey: {question}",
        "",
        "## TL;DR",
        "",
        f"This initial review retrieved {len(papers)} candidate papers. Evidence tracing will be added in the next milestone.",
        "",
        "## Selected Papers",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        authors = ", ".join(paper.authors[:3]) or "Unknown authors"
        year = paper.year or "n.d."
        lines.extend(
            [
                f"### {index}. {paper.title}",
                "",
                f"- Year: {year}",
                f"- Authors: {authors}",
                f"- URL: {paper.url}",
                f"- Abstract: {paper.abstract}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_evidence_review(
    question: str,
    papers: list[Paper],
    evidence: list[Evidence],
    claims: list[ReportClaim],
) -> str:
    lines = [
        f"# Mini Survey: {question}",
        "",
        "## TL;DR",
        "",
        f"Retrieved {len(papers)} papers and attached {len(evidence)} evidence spans.",
        "",
        "## Selected Papers",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        lines.extend(
            [
                f"### {index}. {paper.title}",
                "",
                f"- Year: {paper.year or 'n.d.'}",
                f"- URL: {paper.url}",
                f"- Abstract: {paper.abstract}",
                "",
            ]
        )
    lines.extend(["## Key Claims with Evidence", ""])
    for claim in claims:
        references = ", ".join(claim.evidence_ids) or "no evidence"
        lines.append(f"- {claim.claim} [{references}] ({claim.support_status})")
    lines.extend(["", "## Evidence Trace", ""])
    for item in evidence:
        lines.append(f"- **{item.evidence_id}** `{item.paper_id}`: {item.quote}")
    return "\n".join(lines).strip() + "\n"
