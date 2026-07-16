import pytest

from paper_agent.evidence.retriever import retrieve_evidence
from paper_agent.schemas import Chunk


def _chunk(chunk_id: str, text: str, paper_id: str = "p1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        section="Method",
        text=text,
        token_count=len(text.split()),
    )


def test_retrieve_evidence_ranks_matching_chunks_with_run_scoped_id():
    chunks = [
        _chunk("p1:chunk:001", "Paper agents use retrieval and source grounding."),
        _chunk("p2:chunk:001", "This chunk discusses unrelated biology.", "p2"),
    ]

    evidence = retrieve_evidence(
        "retrieval grounding for paper agents", chunks, run_id="run-a", top_k=1
    )

    assert len(evidence) == 1
    assert evidence[0].evidence_id == "run-a:ev_001"
    assert evidence[0].chunk_id == "p1:chunk:001"
    assert evidence[0].quote == chunks[0].text
    assert evidence[0].relevance_score > 0


def test_retrieve_evidence_returns_empty_for_non_matching_chunks():
    chunks = [_chunk("p1:chunk:001", "Unrelated biology material")]
    assert retrieve_evidence("paper agents", chunks, run_id="run-a") == []


def test_retrieve_evidence_returns_empty_for_no_chunks():
    assert retrieve_evidence("paper agents", [], run_id="run-a") == []


def test_retrieve_evidence_returns_empty_for_question_without_terms():
    chunks = [_chunk("p1:chunk:001", "Paper agents")]
    assert retrieve_evidence("... !!!", chunks, run_id="run-a") == []


def test_retrieve_evidence_rejects_non_positive_top_k():
    with pytest.raises(ValueError, match="top_k must be at least 1"):
        retrieve_evidence("paper", [], run_id="run-a", top_k=0)


def test_retrieve_evidence_sorts_equal_scores_by_chunk_id():
    chunks = [
        _chunk("p2:chunk:001", "paper", "p2"),
        _chunk("p1:chunk:001", "paper"),
    ]
    evidence = retrieve_evidence("paper", chunks, run_id="run-a")
    assert [item.chunk_id for item in evidence] == [
        "p1:chunk:001",
        "p2:chunk:001",
    ]


def test_retrieve_evidence_rejects_blank_run_id():
    with pytest.raises(ValueError, match="run_id must not be empty"):
        retrieve_evidence("paper", [], run_id="  ")


def test_retrieve_evidence_preserves_four_decimal_lexical_score() -> None:
    evidence = retrieve_evidence(
        "alpha beta gamma",
        [_chunk("p1:chunk:001", "alpha beta")],
        run_id="run-a",
        top_k=1,
    )
    assert len(evidence) == 1
    assert evidence[0].relevance_score == 0.6667
