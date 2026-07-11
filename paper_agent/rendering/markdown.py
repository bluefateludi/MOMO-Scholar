from __future__ import annotations

from paper_agent.schemas import Evidence, Paper, ReportClaim


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
