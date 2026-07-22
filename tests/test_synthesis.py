from paper_agent.fulltext.models import DocumentRecord
from paper_agent.rendering.markdown import render_formal_report
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import CheckedClaim, CheckedSurveyReport
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
    assert analysis.contributions[0].text in claims[0].claim
    assert claims[0].evidence_ids == analysis.contributions[0].evidence_ids


def test_analysis_does_not_create_abstract_finding_without_evidence():
    analysis = analyze_paper(_paper(), [])

    assert analysis.contributions == []


def test_synthesis_skips_paper_without_evidence():
    paper = _paper()
    analysis = analyze_paper(paper, [])
    assert synthesize_claims("grounded agents", [paper], [analysis], []) == []


def test_checked_synthesis_inputs_render_deterministically():
    paper = _paper()
    evidence = _evidence()
    report = CheckedSurveyReport(
        question="grounded agents",
        tldr_claims=[
            CheckedClaim(
                text="Agents remain grounded.",
                evidence_ids=[evidence[0].evidence_id],
                support_status="supported",
            )
        ],
        key_findings=[
            CheckedClaim(
                text="Evidence tracing supports auditability.",
                evidence_ids=[evidence[0].evidence_id],
                support_status="supported",
            )
        ],
    )
    document = DocumentRecord(
        paper_id=paper.paper_id,
        content_source="abstract",
        content_sha256="a" * 64,
        page_count=1,
    )
    inputs = dict(
        status="completed",
        papers=[paper],
        documents=[document],
        evidence=evidence,
        report=report,
    )

    assert render_formal_report(**inputs) == render_formal_report(**inputs)
