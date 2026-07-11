from __future__ import annotations

from paper_agent.schemas import Evidence, Paper, PaperAnalysis


def analyze_paper(paper: Paper, evidence: list[Evidence]) -> PaperAnalysis:
    related = [item for item in evidence if item.paper_id == paper.paper_id]
    return PaperAnalysis(
        paper_id=paper.paper_id,
        contribution=[paper.abstract[:280]] if paper.abstract else [],
        method=[item.quote[:280] for item in related[:2]],
        experiment=[],
        limitation=[],
        evidence_ids=[item.evidence_id for item in related],
    )
