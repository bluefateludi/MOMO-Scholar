from collections.abc import Sequence
from typing import Protocol

from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.models import DegradationCode, RetrievalCandidate
from paper_agent.schemas import Chunk
from paper_agent.vector import VectorCandidate
from paper_agent.vector.bailian import (
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingServerError,
    EmbeddingTimeoutError,
)


class VectorRetrieverLike(Protocol):
    def index_chunks(self, chunks: Sequence[Chunk]) -> None:
        raise NotImplementedError

    def retrieve(self, question: str, limit: int) -> list[VectorCandidate]:
        raise NotImplementedError


_AVAILABILITY_ERRORS = (
    EmbeddingTimeoutError,
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingServerError,
)


def _degradation_code(error: Exception) -> DegradationCode:
    if isinstance(error, EmbeddingTimeoutError):
        return "embedding_timeout"
    if isinstance(error, EmbeddingNetworkError):
        return "vector_network_unavailable"
    if isinstance(error, EmbeddingRateLimitError):
        return "vector_rate_limited"
    if isinstance(error, EmbeddingServerError):
        return "vector_server_unavailable"
    raise TypeError("error is not an availability failure")


class VectorCandidateSource:
    def __init__(self, retriever: VectorRetrieverLike) -> None:
        self._retriever = retriever

    def retrieve(
        self,
        question: str,
        chunks: Sequence[Chunk],
        limit: int,
    ) -> list[RetrievalCandidate]:
        if not question.strip():
            raise ValueError("question must not be blank")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not chunks:
            return []
        try:
            self._retriever.index_chunks(chunks)
        except _AVAILABILITY_ERRORS as error:
            raise RetrievalSourceUnavailable(
                _degradation_code(error), "vector_index"
            ) from None
        try:
            candidates = self._retriever.retrieve(question, limit)
        except _AVAILABILITY_ERRORS as error:
            raise RetrievalSourceUnavailable(
                _degradation_code(error), "vector_query"
            ) from None
        return [
            RetrievalCandidate(
                chunk_id=item.chunk_id,
                paper_id=item.paper_id,
                text=item.text,
                section=item.metadata.section,
                page=item.metadata.page,
                retrieval_sources=("vector",),
                vector_score=item.score,
                vector_rank=rank,
            )
            for rank, item in enumerate(candidates, start=1)
        ]
