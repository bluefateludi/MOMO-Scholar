from collections.abc import Sequence
from dataclasses import FrozenInstanceError

import pytest

from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.vector_source import (
    VectorCandidateSource,
    VectorSourceExecutionError,
)
from paper_agent.schemas import Chunk
from paper_agent.vector import VectorCandidate, VectorRecordMetadata
from paper_agent.vector.bailian import (
    EmbeddingAuthenticationError,
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingServerError,
    EmbeddingTimeoutError,
)


class FakeVectorRetriever:
    def __init__(self) -> None:
        self.indexed: list[Chunk] = []
        self.question: str | None = None
        self.limit: int | None = None
        self.index_error: Exception | None = None
        self.query_error: Exception | None = None
        self.results: list[VectorCandidate] = []

    def index_chunks(self, chunks: Sequence[Chunk]) -> None:
        if self.index_error is not None:
            raise self.index_error
        self.indexed = list(chunks)

    def retrieve(self, question: str, limit: int) -> list[VectorCandidate]:
        if self.query_error is not None:
            raise self.query_error
        self.question = question
        self.limit = limit
        return self.results


def _chunk_and_vector() -> tuple[Chunk, VectorCandidate]:
    chunk = Chunk(
        chunk_id="p1:chunk:001",
        paper_id="p1",
        section="Methods",
        page=2,
        text="semantic grounding",
        token_count=2,
    )
    metadata = VectorRecordMetadata(
        paper_id=chunk.paper_id,
        chunk_id=chunk.chunk_id,
        section=chunk.section,
        page=chunk.page,
        content_hash="sha256-test",
        embedding_model="text-embedding-v4",
    )
    candidate = VectorCandidate(
        chunk_id=chunk.chunk_id,
        paper_id=chunk.paper_id,
        text=chunk.text,
        score=0.9,
        metadata=metadata,
    )
    return chunk, candidate


def test_vector_source_indexes_queries_and_maps_ranked_candidate() -> None:
    chunk, vector = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    retriever.results = [vector]
    result = VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert retriever.indexed == [chunk]
    assert (retriever.question, retriever.limit) == ("question", 3)
    assert result[0].model_dump() == {
        "chunk_id": chunk.chunk_id,
        "paper_id": chunk.paper_id,
        "text": chunk.text,
        "section": chunk.section,
        "page": chunk.page,
        "retrieval_sources": ("vector",),
        "lexical_score": None,
        "lexical_rank": None,
        "vector_score": vector.score,
        "vector_rank": 1,
        "fusion_score": None,
    }


def test_vector_source_short_circuits_empty_chunks() -> None:
    retriever = FakeVectorRetriever()
    assert VectorCandidateSource(retriever).retrieve("question", [], 3) == []
    assert retriever.indexed == []
    assert retriever.question is None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (EmbeddingTimeoutError("timeout"), "embedding_timeout"),
        (EmbeddingNetworkError("network"), "vector_network_unavailable"),
        (EmbeddingRateLimitError("rate"), "vector_rate_limited"),
        (EmbeddingServerError("server"), "vector_server_unavailable"),
    ],
)
def test_vector_source_maps_query_availability_error(
    error: Exception, code: str
) -> None:
    chunk, _ = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    retriever.query_error = error
    with pytest.raises(RetrievalSourceUnavailable) as exc_info:
        VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert exc_info.value.degradation_code == code
    assert exc_info.value.failure_stage == "vector_query"


def test_vector_source_wraps_nonavailability_error_with_stage() -> None:
    chunk, _ = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    cause = EmbeddingAuthenticationError("auth")
    retriever.index_error = cause
    with pytest.raises(VectorSourceExecutionError) as exc_info:
        VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert exc_info.value.cause is cause
    assert exc_info.value.failure_stage == "vector_index"


def test_vector_source_marks_index_availability_stage() -> None:
    chunk, _ = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    retriever.index_error = EmbeddingTimeoutError("timeout")
    with pytest.raises(RetrievalSourceUnavailable) as exc_info:
        VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert exc_info.value.degradation_code == "embedding_timeout"
    assert exc_info.value.failure_stage == "vector_index"


@pytest.mark.parametrize(("question", "limit"), [("   ", 3), ("question", 0)])
def test_vector_source_rejects_invalid_query_without_downgrade(
    question: str, limit: int
) -> None:
    chunk, _ = _chunk_and_vector()
    with pytest.raises(ValueError):
        VectorCandidateSource(FakeVectorRetriever()).retrieve(question, [chunk], limit)


def test_unavailable_error_metadata_is_frozen() -> None:
    error = RetrievalSourceUnavailable("embedding_timeout", "vector_query")
    with pytest.raises(FrozenInstanceError):
        error.failure_stage = "vector_index"
