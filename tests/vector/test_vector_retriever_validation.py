from collections.abc import Sequence

import pytest

from paper_agent.schemas import Chunk
from paper_agent.vector.embedding import EmbeddingResponseError
from paper_agent.vector.retriever import VectorRetriever


def _chunks(count: int = 2) -> list[Chunk]:
    return [
        Chunk(
            chunk_id=f"chunk-{index}",
            paper_id="paper-1",
            text=f"text {index}",
            token_count=2,
        )
        for index in range(count)
    ]


class FakeEmbedder:
    model_name = "text-embedding-v4"

    def __init__(self, embeddings: list[list[object]], call_log: list[str]) -> None:
        self.embeddings = embeddings
        self.call_log = call_log

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.call_log.append("embed")
        return self.embeddings  # type: ignore[return-value]


class FakeStore:
    embedding_model = "text-embedding-v4"

    def __init__(
        self,
        call_log: list[str],
        *,
        ensure_error: Exception | None = None,
        upsert_error: Exception | None = None,
    ) -> None:
        self.call_log = call_log
        self.ensure_error = ensure_error
        self.upsert_error = upsert_error

    def ensure_collection(self, vector_size: int) -> None:
        self.call_log.append("ensure")
        if self.ensure_error is not None:
            raise self.ensure_error

    def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        self.call_log.append("upsert")
        if self.upsert_error is not None:
            raise self.upsert_error


@pytest.mark.parametrize(
    "embeddings, expected_message",
    [
        ([[1.0, 0.0]], "count"),
        ([[1.0, 0.0], []], "empty vector"),
        ([[1.0, 0.0], [1.0]], "dimensions"),
        ([[True, 0.0], [1.0, 0.0]], "numeric"),
        ([["bad", 0.0], [1.0, 0.0]], "numeric"),
        ([[float("nan"), 0.0], [1.0, 0.0]], "finite"),
        ([[float("inf"), 0.0], [1.0, 0.0]], "finite"),
    ],
)
def test_invalid_embedding_response_fails_before_store_calls(
    embeddings: list[list[object]],
    expected_message: str,
) -> None:
    call_log: list[str] = []
    retriever = VectorRetriever(
        embedder=FakeEmbedder(embeddings, call_log),
        store=FakeStore(call_log),
    )

    with pytest.raises(EmbeddingResponseError, match=expected_message):
        retriever.index_chunks(_chunks())

    assert call_log == ["embed"]


def test_ensure_collection_failure_propagates_without_upsert() -> None:
    call_log: list[str] = []
    retriever = VectorRetriever(
        embedder=FakeEmbedder([[1.0, 0.0]], call_log),
        store=FakeStore(
            call_log, ensure_error=RuntimeError("ensure failed")
        ),
    )

    with pytest.raises(RuntimeError, match="ensure failed"):
        retriever.index_chunks(_chunks(1))

    assert call_log == ["embed", "ensure"]


def test_upsert_failure_has_no_calls_after_upsert() -> None:
    call_log: list[str] = []
    retriever = VectorRetriever(
        embedder=FakeEmbedder([[1.0, 0.0]], call_log),
        store=FakeStore(call_log, upsert_error=RuntimeError("upsert failed")),
    )

    with pytest.raises(RuntimeError, match="upsert failed"):
        retriever.index_chunks(_chunks(1))

    assert call_log == ["embed", "ensure", "upsert"]
