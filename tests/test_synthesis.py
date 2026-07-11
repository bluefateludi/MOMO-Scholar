from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.paper_reader import analyze_paper
from paper_agent.synthesis.survey import synthesize_claims


def _paper() -> Paper:
    return Paper(
        paper_id="p1",
        title="Grounded Agents",
        authors=[],
        year=2024,
        abstract="Agents link claims to source evidence.",
        url="https://example.test/p1",
        source="test",
    )


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            evidence_id="run-a:ev_001",
            paper_id="p1",
            chunk_id="p1:chunk:001",
            claim_type="retrieved",
            quote="Agents link claims to source evidence.",
            relevance_score=1.0,
        )
    ]


def test_analysis_and_synthesis_are_deterministic_for_ordered_inputs():
    paper = _paper()
    evidence = _evidence()
    first_analysis = analyze_paper(paper, evidence)
    second_analysis = analyze_paper(paper, evidence)
    first_claims = synthesize_claims(
        "grounded agents", [paper], [first_analysis], evidence
    )
    second_claims = synthesize_claims(
        "grounded agents", [paper], [second_analysis], evidence
    )
    assert first_analysis == second_analysis
    assert first_claims == second_claims


def test_synthesis_uses_analysis_contribution_and_evidence_ids():
    paper = _paper()
    evidence = _evidence()
    analysis = analyze_paper(paper, evidence)
    claims = synthesize_claims("grounded agents", [paper], [analysis], evidence)
    assert len(claims) == 1
    assert analysis.contribution[0] in claims[0].claim
    assert claims[0].evidence_ids == analysis.evidence_ids


def test_synthesis_skips_paper_without_evidence():
    paper = _paper()
    analysis = analyze_paper(paper, [])
    assert synthesize_claims("grounded agents", [paper], [analysis], []) == []
