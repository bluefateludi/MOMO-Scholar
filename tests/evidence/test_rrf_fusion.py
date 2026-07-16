import pytest

from paper_agent.evidence.fusion import fuse_candidates
from paper_agent.evidence.models import RetrievalCandidate


def _candidate(
    source: str,
    chunk_id: str,
    rank: int,
    score: float,
    text: str | None = None,
) -> RetrievalCandidate:
    values: dict[str, object] = {
        "chunk_id": chunk_id,
        "paper_id": "p1",
        "text": text or f"text-{chunk_id}",
        "section": "Methods",
        "page": 1,
        "retrieval_sources": (source,),
        "lexical_score": score if source == "lexical" else None,
        "lexical_rank": rank if source == "lexical" else None,
        "vector_score": score if source == "vector" else None,
        "vector_rank": rank if source == "vector" else None,
    }
    return RetrievalCandidate.model_validate(values)


def test_rrf_merges_duplicate_identity_and_normalizes_by_active_sources() -> None:
    lexical = [_candidate("lexical", "shared", 1, 0.8)]
    vector = [
        _candidate("vector", "vector-only", 1, 0.9),
        _candidate("vector", "shared", 2, 0.7),
    ]
    result = fuse_candidates(
        lexical,
        vector,
        rrf_k=60,
        active_sources=("lexical", "vector"),
    )
    shared = next(item for item in result if item.chunk_id == "shared")
    vector_only = next(item for item in result if item.chunk_id == "vector-only")
    assert shared.retrieval_sources == ("lexical", "vector")
    assert shared.lexical_rank == 1
    assert shared.vector_rank == 2
    assert shared.fusion_score == pytest.approx(
        ((1 / 61) + (1 / 62)) / (2 / 61)
    )
    assert vector_only.fusion_score == pytest.approx(0.5)
    assert result[0].chunk_id == "shared"


def test_successful_empty_vector_source_stays_in_normalization_denominator() -> None:
    result = fuse_candidates(
        [_candidate("lexical", "a", 1, 1.0)],
        [],
        rrf_k=60,
        active_sources=("lexical", "vector"),
    )
    assert result[0].fusion_score == pytest.approx(0.5)


def test_rrf_uses_chunk_id_for_exact_tie() -> None:
    lexical = [
        _candidate("lexical", "b", 1, 1.0),
        _candidate("lexical", "a", 1, 1.0),
    ]
    assert [
        item.chunk_id
        for item in fuse_candidates(
            lexical, [], rrf_k=60, active_sources=("lexical",)
        )
    ] == ["a", "b"]


def test_rrf_rejects_identity_conflict_for_same_chunk_id() -> None:
    with pytest.raises(ValueError, match="identity"):
        fuse_candidates(
            [_candidate("lexical", "same", 1, 1.0, text="first")],
            [_candidate("vector", "same", 1, 1.0, text="second")],
            rrf_k=60,
            active_sources=("lexical", "vector"),
        )


@pytest.mark.parametrize("rrf_k", [0, -1, True])
def test_rrf_rejects_invalid_k(rrf_k: object) -> None:
    with pytest.raises(ValueError, match="rrf_k"):
        fuse_candidates([], [], rrf_k=rrf_k, active_sources=("lexical",))


def test_rrf_rejects_candidate_in_wrong_source_list() -> None:
    with pytest.raises(ValueError, match="lexical input"):
        fuse_candidates(
            [_candidate("vector", "a", 1, 1.0)],
            [],
            rrf_k=60,
            active_sources=("lexical",),
        )


def test_rrf_rejects_candidates_for_inactive_source() -> None:
    with pytest.raises(ValueError, match="inactive vector"):
        fuse_candidates(
            [],
            [_candidate("vector", "a", 1, 1.0)],
            rrf_k=60,
            active_sources=("lexical",),
        )


@pytest.mark.parametrize("sources", [(), ("vector", "lexical")])
def test_rrf_rejects_invalid_active_sources(sources: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="active_sources"):
        fuse_candidates([], [], rrf_k=60, active_sources=sources)


def test_rrf_rejects_duplicate_id_inside_one_source() -> None:
    duplicate = _candidate("lexical", "same", 1, 1.0)
    with pytest.raises(ValueError, match="duplicate.*same"):
        fuse_candidates(
            [duplicate, duplicate.model_copy(update={"lexical_rank": 2})],
            [],
            rrf_k=60,
            active_sources=("lexical",),
        )


def test_rrf_does_not_mutate_input_candidates_or_sequences() -> None:
    lexical = [_candidate("lexical", "shared", 1, 0.8)]
    vector = [_candidate("vector", "shared", 1, 0.9)]
    lexical_before = list(lexical)
    vector_before = list(vector)

    result = fuse_candidates(
        lexical,
        vector,
        rrf_k=60,
        active_sources=("lexical", "vector"),
    )

    assert lexical == lexical_before
    assert vector == vector_before
    assert lexical[0].retrieval_sources == ("lexical",)
    assert vector[0].retrieval_sources == ("vector",)
    assert result[0] is not lexical[0]
    assert result[0] is not vector[0]
