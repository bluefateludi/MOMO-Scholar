from collections.abc import Sequence

import pytest

from paper_agent.schemas import Evidence
from paper_agent.vector.embedding import EmbeddingResponseError
from paper_agent.vector.memory_store import InMemoryVectorStore
from paper_agent.vector.models import (
    VectorCandidate,
    VectorFilter,
    VectorRecordMetadata,
    VectorSearchResult,
)
from paper_agent.vector.retriever import VectorRetriever


def _metadata(
    chunk_id: str,
    *,
    paper_id: str = "paper-1",
    text_hash: str = "hash",
) -> VectorRecordMetadata:
    return VectorRecordMetadata(
        paper_id=paper_id,
        chunk_id=chunk_id,
        section="Methods",
        page=3,
        content_hash=text_hash,
        embedding_model="text-embedding-v4",
    )


class FakeEmbedder:
    def __init__(
        self,
        vectors: list[list[object]],
        *,
        model_name: str = "text-embedding-v4",
    ) -> None:
        self.model_name = model_name
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return self.vectors  # type: ignore[return-value]


class SearchStore:
    def __init__(
        self,
        results: list[VectorSearchResult] | None = None,
        *,
        embedding_model: str = "text-embedding-v4",
        error: Exception | None = None,
    ) -> None:
        self.embedding_model = embedding_model
        self.results = results or []
        self.error = error
        self.search_calls: list[tuple[list[float], int, VectorFilter | None]] = []

    def search(
        self,
        query_embedding: Sequence[float],
        limit: int,
        filters: VectorFilter | None = None,
    ) -> list[VectorSearchResult]:
        self.search_calls.append((list(query_embedding), limit, filters))
        if self.error is not None:
            raise self.error
        return self.results


@pytest.mark.parametrize("question", ["", " ", "\t\n"])
def test_retrieve_rejects_blank_question_before_embedding(question: str) -> None:
    embedder = FakeEmbedder([[1.0, 0.0]])
    store = SearchStore()

    with pytest.raises(ValueError, match="question"):
        VectorRetriever(embedder=embedder, store=store).retrieve(question, 3)

    assert embedder.calls == []
    assert store.search_calls == []


@pytest.mark.parametrize("limit", [0, -1, True, 1.0, "1"])
def test_retrieve_requires_a_strictly_positive_integer_limit(limit: object) -> None:
    embedder = FakeEmbedder([[1.0, 0.0]])
    store = SearchStore()

    with pytest.raises(ValueError, match="limit"):
        VectorRetriever(embedder=embedder, store=store).retrieve(
            "question", limit  # type: ignore[arg-type]
        )

    assert embedder.calls == []
    assert store.search_calls == []


def test_retrieve_embeds_exactly_the_question_once_and_forwards_typed_filter() -> None:
    embedder = FakeEmbedder([[1, 2]])
    store = SearchStore()
    filters = VectorFilter(paper_id="paper-2")

    VectorRetriever(embedder=embedder, store=store).retrieve(
        "What is the method?", 7, filters
    )

    assert embedder.calls == [["What is the method?"]]
    assert store.search_calls == [([1.0, 2.0], 7, filters)]
    assert store.search_calls[0][2] is filters


@pytest.mark.parametrize(
    "vectors, message",
    [
        ([], "count"),
        ([[1.0], [2.0]], "count"),
        ([[]], "empty vector"),
        ([[True]], "numeric"),
        ([["bad"]], "numeric"),
        ([[float("nan")]], "finite"),
        ([[float("inf")]], "finite"),
    ],
)
def test_invalid_query_embedding_never_searches_store(
    vectors: list[list[object]], message: str
) -> None:
    embedder = FakeEmbedder(vectors)
    store = SearchStore()

    with pytest.raises(EmbeddingResponseError, match=message):
        VectorRetriever(embedder=embedder, store=store).retrieve("question", 3)

    assert embedder.calls == [["question"]]
    assert store.search_calls == []


def test_retrieve_preserves_result_order_and_maps_persisted_fields() -> None:
    second = VectorSearchResult(
        chunk_id="chunk-2",
        text="persisted second text",
        score=0.91,
        metadata=_metadata("chunk-2", paper_id="paper-2", text_hash="hash-2"),
    )
    first = VectorSearchResult(
        chunk_id="chunk-1",
        text="persisted first text",
        score=0.73,
        metadata=_metadata("chunk-1", text_hash="hash-1"),
    )
    retriever = VectorRetriever(
        embedder=FakeEmbedder([[1.0, 0.0]]),
        store=SearchStore([second, first]),
    )

    candidates = retriever.retrieve("question", 2)

    assert candidates == [
        VectorCandidate(
            chunk_id="chunk-2",
            paper_id="paper-2",
            text="persisted second text",
            score=0.91,
            metadata=second.metadata,
        ),
        VectorCandidate(
            chunk_id="chunk-1",
            paper_id="paper-1",
            text="persisted first text",
            score=0.73,
            metadata=first.metadata,
        ),
    ]
    assert all(not isinstance(candidate, Evidence) for candidate in candidates)


def test_new_retriever_can_search_a_prepopulated_memory_store() -> None:
    from paper_agent.schemas import Chunk

    store = InMemoryVectorStore(embedding_model="text-embedding-v4")
    store.ensure_collection(2)
    store.upsert(
        [Chunk(chunk_id="stable-id", paper_id="paper-1", text="stored", token_count=1)],
        [[1.0, 0.0]],
    )

    candidates = VectorRetriever(
        embedder=FakeEmbedder([[1.0, 0.0]]), store=store
    ).retrieve("question", 1)

    assert [(candidate.chunk_id, candidate.text) for candidate in candidates] == [
        ("stable-id", "stored")
    ]


def test_retrieve_model_mismatch_fails_before_embedding_and_search() -> None:
    embedder = FakeEmbedder([[1.0]], model_name="model-a")
    store = SearchStore(embedding_model="model-b")

    with pytest.raises(ValueError, match="embedding model"):
        VectorRetriever(embedder=embedder, store=store).retrieve("question", 1)

    assert embedder.calls == []
    assert store.search_calls == []


def test_search_exception_propagates_unchanged() -> None:
    failure = RuntimeError("search failed")
    retriever = VectorRetriever(
        embedder=FakeEmbedder([[1.0]]), store=SearchStore(error=failure)
    )

    with pytest.raises(RuntimeError, match="search failed") as caught:
        retriever.retrieve("question", 1)

    assert caught.value is failure
