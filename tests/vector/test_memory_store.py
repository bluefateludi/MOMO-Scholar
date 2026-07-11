import hashlib
import math

import pytest

from paper_agent.schemas import Chunk
from paper_agent.vector.memory_store import InMemoryVectorStore
from paper_agent.vector.models import VectorFilter


def _chunk(
    chunk_id: str,
    *,
    paper_id: str = "paper-1",
    text: str = "Original text",
    section: str | None = "Methods",
    page: int | None = 3,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        section=section,
        page=page,
        text=text,
        token_count=len(text.split()),
    )


def test_embedding_model_is_required_and_nonempty() -> None:
    with pytest.raises(ValueError, match="embedding_model"):
        InMemoryVectorStore(embedding_model="")
    with pytest.raises(ValueError, match="embedding_model"):
        InMemoryVectorStore(embedding_model="   ")

    store = InMemoryVectorStore(embedding_model="text-embedding-v4")

    assert store.embedding_model == "text-embedding-v4"


def test_ensure_collection_requires_positive_vector_size() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")

    for vector_size in (0, -1):
        with pytest.raises(ValueError, match="vector_size"):
            store.ensure_collection(vector_size)


def test_ensure_collection_is_idempotent_for_same_dimension() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")

    store.ensure_collection(2)
    store.ensure_collection(2)


def test_ensure_collection_rejects_different_dimension() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    with pytest.raises(ValueError, match="dimension"):
        store.ensure_collection(3)


def test_upsert_requires_collection_and_equal_batch_counts() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    chunk = _chunk("chunk-1")

    with pytest.raises(RuntimeError, match="collection"):
        store.upsert([chunk], [[1.0, 0.0]])

    store.ensure_collection(2)
    with pytest.raises(ValueError, match="count"):
        store.upsert([chunk], [])


def test_upsert_rejects_wrong_dimension_and_zero_vectors() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    chunk = _chunk("chunk-1")

    with pytest.raises(ValueError, match="dimension"):
        store.upsert([chunk], [[1.0]])
    with pytest.raises(ValueError, match="zero"):
        store.upsert([chunk], [[0.0, 0.0]])


def test_upsert_overwrites_record_by_stable_chunk_id() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert([_chunk("chunk-1", text="Old text")], [[1.0, 0.0]])

    store.upsert([_chunk("chunk-1", text="New text", page=4)], [[0.0, 1.0]])

    results = store.search([0.0, 1.0], limit=2)

    assert len(results) == 1
    assert results[0].text == "New text"
    assert results[0].score == pytest.approx(1.0)
    assert results[0].metadata.page == 4


def test_upsert_persists_text_and_complete_provenance_metadata() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    chunk = _chunk("chunk-1", text="Exact source text")

    store.upsert([chunk], [[0.6, 0.8]])

    result = store.search([0.6, 0.8], limit=1)[0]
    assert result.text == "Exact source text"
    assert result.metadata.model_dump() == {
        "paper_id": "paper-1",
        "chunk_id": "chunk-1",
        "section": "Methods",
        "page": 3,
        "content_hash": hashlib.sha256(b"Exact source text").hexdigest(),
        "embedding_model": "text-embedding-v4",
    }


def test_invalid_batch_does_not_partially_mutate_records() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert([_chunk("existing")], [[1.0, 0.0]])
    before = store.search([1.0, 0.0], limit=10)

    with pytest.raises(ValueError, match="zero"):
        store.upsert(
            [_chunk("valid-new"), _chunk("invalid-new")],
            [[0.0, 1.0], [0.0, 0.0]],
        )

    assert store.search([1.0, 0.0], limit=10) == before


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_upsert_rejects_nonfinite_document_vectors(invalid_value: float) -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    with pytest.raises(ValueError, match="finite"):
        store.upsert([_chunk("chunk-nonfinite")], [[invalid_value, 1.0]])


def test_search_requires_initialized_collection() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")

    with pytest.raises(RuntimeError, match="collection"):
        store.search([1.0, 0.0], limit=1)


def test_search_returns_empty_list_for_initialized_empty_collection() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    assert store.search([1.0, 0.0], limit=1) == []


@pytest.mark.parametrize("limit", [0, -1])
def test_search_requires_positive_limit(limit: int) -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    with pytest.raises(ValueError, match="limit"):
        store.search([1.0, 0.0], limit=limit)


def test_search_rejects_wrong_query_dimension() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    with pytest.raises(ValueError, match="dimension"):
        store.search([1.0], limit=1)


def test_search_rejects_zero_query_vector() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    with pytest.raises(ValueError, match="zero"):
        store.search([0.0, 0.0], limit=1)


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_search_rejects_nonfinite_query_vectors(invalid_value: float) -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    with pytest.raises(ValueError, match="finite"):
        store.search([invalid_value, 1.0], limit=1)


def test_search_normalizes_cosine_scores_and_orders_descending() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert(
        [_chunk("same"), _chunk("orthogonal"), _chunk("opposite")],
        [[1.0, 0.0], [0.0, 2.0], [-3.0, 0.0]],
    )

    results = store.search([4.0, 0.0], limit=3)

    assert [result.chunk_id for result in results] == [
        "same",
        "orthogonal",
        "opposite",
    ]
    assert [result.score for result in results] == pytest.approx([1.0, 0.5, 0.0])
    assert all(0.0 <= result.score <= 1.0 for result in results)


def test_search_breaks_equal_score_ties_by_chunk_id() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert(
        [_chunk("chunk-b"), _chunk("chunk-a")],
        [[0.0, 1.0], [0.0, -1.0]],
    )

    results = store.search([1.0, 0.0], limit=2)

    assert [result.chunk_id for result in results] == ["chunk-a", "chunk-b"]


def test_search_applies_typed_paper_filter_before_limit() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert(
        [
            _chunk("other-best", paper_id="paper-2"),
            _chunk("target", paper_id="paper-1"),
        ],
        [[1.0, 0.0], [0.8, 0.2]],
    )

    results = store.search(
        [1.0, 0.0],
        limit=1,
        filters=VectorFilter(paper_id="paper-1"),
    )

    assert [result.chunk_id for result in results] == ["target"]


def test_search_result_contains_text_and_metadata_but_not_internal_vector() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert([_chunk("chunk-1", text="Exact source text")], [[1.0, 0.0]])

    result = store.search([1.0, 0.0], limit=1)[0]

    assert result.text == "Exact source text"
    assert result.metadata.chunk_id == "chunk-1"
    assert result.metadata.paper_id == "paper-1"
    assert set(result.model_dump()) == {"chunk_id", "text", "score", "metadata"}


def test_delete_by_paper_only_removes_target_and_is_idempotent() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert(
        [
            _chunk("paper-1-a", paper_id="paper-1"),
            _chunk("paper-1-b", paper_id="paper-1"),
            _chunk("paper-2-a", paper_id="paper-2"),
        ],
        [[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]],
    )

    store.delete_by_paper("paper-1")
    store.delete_by_paper("paper-1")

    results = store.search([0.0, 1.0], limit=3)

    assert [result.chunk_id for result in results] == ["paper-2-a"]

@pytest.mark.parametrize("vector_size", [True, False, 2.0, "2"])
def test_ensure_collection_requires_exact_integer_vector_size(
    vector_size: object,
) -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")

    with pytest.raises(ValueError, match="integer"):
        store.ensure_collection(vector_size)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [True, False, 1.0, "1"])
def test_search_requires_exact_integer_limit(limit: object) -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)

    with pytest.raises(ValueError, match="integer"):
        store.search([1.0, 0.0], limit=limit)  # type: ignore[arg-type]


def test_search_handles_huge_finite_vectors_without_overflow() -> None:
    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert(
        [_chunk("same"), _chunk("opposite")],
        [[1e308, 1e308], [-1e308, -1e308]],
    )

    results = store.search([1e308, 1e308], limit=2)

    assert [result.chunk_id for result in results] == ["same", "opposite"]
    assert [result.score for result in results] == pytest.approx([1.0, 0.0])
    assert all(math.isfinite(result.score) for result in results)