from collections.abc import Sequence

import pytest

from paper_agent.schemas import Chunk
from paper_agent.vector.embedding import EmbeddingResponseError
from paper_agent.vector.retriever import VectorRetriever


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id="paper-1",
        text=text,
        token_count=len(text.split()),
    )


class FakeEmbedder:
    def __init__(
        self,
        *,
        model_name: str = "text-embedding-v4",
        embeddings: list[list[float]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.model_name = model_name
        self.embeddings = embeddings if embeddings is not None else [[1.0, 0.0]]
        self.error = error
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return self.embeddings


class FakeStore:
    def __init__(
        self,
        *,
        embedding_model: str = "text-embedding-v4",
        upsert_error: Exception | None = None,
    ) -> None:
        self.embedding_model = embedding_model
        self.upsert_error = upsert_error
        self.calls: list[tuple[object, ...]] = []

    def ensure_collection(self, vector_size: int) -> None:
        self.calls.append(("ensure_collection", vector_size))

    def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        self.calls.append(
            ("upsert", [chunk.chunk_id for chunk in chunks], [list(row) for row in embeddings])
        )
        if self.upsert_error is not None:
            raise self.upsert_error


def test_empty_chunks_are_a_noop() -> None:
    embedder = FakeEmbedder()
    store = FakeStore()

    VectorRetriever(embedder=embedder, store=store).index_chunks([])

    assert embedder.calls == []
    assert store.calls == []


def test_index_chunks_embeds_all_texts_once_in_input_order() -> None:
    embedder = FakeEmbedder(embeddings=[[1.0, 0.0], [0.0, 1.0]])
    store = FakeStore()
    chunks = [_chunk("chunk-b", "second text"), _chunk("chunk-a", "first text")]

    VectorRetriever(embedder=embedder, store=store).index_chunks(chunks)

    assert embedder.calls == [["second text", "first text"]]


def test_index_chunks_infers_dimension_and_ensures_before_upsert() -> None:
    embedder = FakeEmbedder(embeddings=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    store = FakeStore()
    chunks = [_chunk("chunk-1", "one"), _chunk("chunk-2", "two")]

    VectorRetriever(embedder=embedder, store=store).index_chunks(chunks)

    assert store.calls == [
        ("ensure_collection", 3),
        ("upsert", ["chunk-1", "chunk-2"], [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
    ]


def test_model_mismatch_fails_before_embedding_or_store_mutation() -> None:
    embedder = FakeEmbedder(model_name="model-a")
    store = FakeStore(embedding_model="model-b")

    with pytest.raises(ValueError, match="embedding model"):
        VectorRetriever(embedder=embedder, store=store).index_chunks(
            [_chunk("chunk-1", "text")]
        )

    assert embedder.calls == []
    assert store.calls == []


def test_embedding_failure_does_not_call_store() -> None:
    embedder = FakeEmbedder(error=RuntimeError("embedding failed"))
    store = FakeStore()

    with pytest.raises(RuntimeError, match="embedding failed"):
        VectorRetriever(embedder=embedder, store=store).index_chunks(
            [_chunk("chunk-1", "text")]
        )

    assert store.calls == []


def test_empty_embedding_batch_is_rejected_before_store_calls() -> None:
    embedder = FakeEmbedder(embeddings=[])
    store = FakeStore()

    with pytest.raises(EmbeddingResponseError, match="count"):
        VectorRetriever(embedder=embedder, store=store).index_chunks(
            [_chunk("chunk-1", "text")]
        )

    assert store.calls == []


def test_upsert_failure_is_propagated() -> None:
    embedder = FakeEmbedder()
    store = FakeStore(upsert_error=RuntimeError("upsert failed"))

    with pytest.raises(RuntimeError, match="upsert failed"):
        VectorRetriever(embedder=embedder, store=store).index_chunks(
            [_chunk("chunk-1", "text")]
        )
