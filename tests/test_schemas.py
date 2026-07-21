import pytest
from pydantic import ValidationError

from paper_agent.schemas import Chunk, Evidence, Paper, ReportClaim


PAPER_VALUES = {
    "paper_id": "arxiv:2401.00001",
    "title": "Example Paper",
    "authors": ["Alice Researcher"],
    "year": 2024,
    "abstract": "An example abstract.",
    "url": "https://arxiv.org/abs/2401.00001",
    "pdf_url": "https://arxiv.org/pdf/2401.00001",
    "source": "arxiv",
}


def test_paper_requires_normalized_identity():
    paper = Paper(**PAPER_VALUES)

    assert paper.paper_id == "arxiv:2401.00001"
    assert paper.citation_count is None


def test_persisted_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Paper.model_validate({**PAPER_VALUES, "unexpected": True})


def test_evidence_references_a_chunk():
    chunk = Chunk(
        chunk_id="chunk-1",
        paper_id="arxiv:2401.00001",
        section="Introduction",
        page=None,
        text="This paper introduces a paper research agent.",
        token_count=8,
    )
    evidence = Evidence(
        evidence_id="evidence-1",
        paper_id="arxiv:2401.00001",
        chunk_id=chunk.chunk_id,
        section="Methods",
        page=3,
        claim_type="contribution",
        quote="This paper introduces a paper research agent.",
        relevance_score=0.9,
    )

    assert evidence.chunk_id == chunk.chunk_id
    assert evidence.section == "Methods"
    assert evidence.page == 3


def test_report_claim_without_evidence_is_unsupported():
    claim = ReportClaim(claim="A claim without evidence.", evidence_ids=[])

    assert claim.support_status == "unsupported"
