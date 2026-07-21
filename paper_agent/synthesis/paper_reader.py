from __future__ import annotations

from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import GroundedFinding, PaperAnalysis


def analyze_paper(paper: Paper, evidence: list[Evidence]) -> PaperAnalysis:
    related = [item for item in evidence if item.paper_id == paper.paper_id]
    if not related:
        return PaperAnalysis(paper_id=paper.paper_id)

    evidence_ids = [item.evidence_id for item in related]
    contribution_text = paper.abstract[:280] or related[0].quote[:280]
    return PaperAnalysis(
        paper_id=paper.paper_id,
        contributions=[
            GroundedFinding(text=contribution_text, evidence_ids=evidence_ids)
        ],
        methods=[
            GroundedFinding(text=item.quote[:280], evidence_ids=[item.evidence_id])
            for item in related[:2]
        ],
    )
