from __future__ import annotations

from paper_agent.schemas import Evidence, Paper, ReportClaim
from paper_agent.synthesis.models import PaperAnalysis


def synthesize_claims(
    question: str,
    papers: list[Paper],
    analyses: list[PaperAnalysis],
    evidence: list[Evidence],
) -> list[ReportClaim]:
    del question, evidence
    analysis_by_paper = {analysis.paper_id: analysis for analysis in analyses}
    claims: list[ReportClaim] = []
    for paper in papers:
        analysis = analysis_by_paper.get(paper.paper_id)
        if not analysis or not analysis.contributions:
            continue
        contribution = analysis.contributions[0]
        claims.append(
            ReportClaim(
                claim=f"{paper.title}: {contribution.text}",
                evidence_ids=list(contribution.evidence_ids),
            )
        )
    return claims
