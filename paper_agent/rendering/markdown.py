from __future__ import annotations

from paper_agent.schemas import Paper


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
