import pytest

from paper_agent.evidence.retriever import retrieve_lexical_candidates
from paper_agent.schemas import Chunk


def _chunk(
    chunk_id: str,
    text: str,
    *,
    section: str | None = "Methods",
    page: int | None = 1,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id="p1",
        section=section,
        page=page,
        text=text,
        token_count=len(text.split()),
    )


def test_lexical_candidates_preserve_score_rank_and_provenance() -> None:
    chunks = [
        _chunk("b", "retrieval grounding", section="Methods", page=2),
        _chunk("a", "retrieval", section="Abstract", page=None),
    ]
    candidates = retrieve_lexical_candidates(
        "retrieval grounding", chunks, limit=8
    )
    assert [item.chunk_id for item in candidates] == ["b", "a"]
    assert candidates[0].model_dump() == {
        "chunk_id": "b",
        "paper_id": "p1",
        "text": "retrieval grounding",
        "section": "Methods",
        "page": 2,
        "retrieval_sources": ("lexical",),
        "lexical_score": 1.0,
        "lexical_rank": 1,
        "vector_score": None,
        "vector_rank": None,
        "fusion_score": None,
    }
    assert candidates[1].lexical_score == 0.5
    assert candidates[1].lexical_rank == 2


def test_lexical_candidates_use_chunk_id_tie_break() -> None:
    chunks = [_chunk("b", "retrieval"), _chunk("a", "retrieval")]
    assert [
        item.chunk_id
        for item in retrieve_lexical_candidates("retrieval", chunks, limit=8)
    ] == ["a", "b"]


def test_lexical_candidates_reject_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit must be at least 1"):
        retrieve_lexical_candidates("retrieval", [], limit=0)


def test_lexical_candidates_return_empty_for_empty_or_termless_input() -> None:
    assert retrieve_lexical_candidates("retrieval", [], limit=8) == []
    assert (
        retrieve_lexical_candidates("... !!!", [_chunk("a", "retrieval")], 8)
        == []
    )
