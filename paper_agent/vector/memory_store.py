from dataclasses import dataclass
import hashlib
import math
from typing import Sequence

from paper_agent.schemas import Chunk
from paper_agent.vector.models import (
    VectorFilter,
    VectorRecordMetadata,
    VectorSearchResult,
)


@dataclass(frozen=True)
class _StoredVectorRecord:
    text: str
    embedding: tuple[float, ...]
    metadata: VectorRecordMetadata




def _cosine_similarity(
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float:
    left_scale = max(abs(value) for value in left)
    right_scale = max(abs(value) for value in right)
    scaled_left = tuple(value / left_scale for value in left)
    scaled_right = tuple(value / right_scale for value in right)
    dot_product = math.fsum(
        left_value * right_value
        for left_value, right_value in zip(scaled_left, scaled_right)
    )
    left_norm = math.sqrt(math.fsum(value * value for value in scaled_left))
    right_norm = math.sqrt(math.fsum(value * value for value in scaled_right))
    return dot_product / (left_norm * right_norm)

class InMemoryVectorStore:
    """Process-local reference storage for vector-store contract tests."""

    def __init__(self, *, embedding_model: str) -> None:
        if not embedding_model.strip():
            raise ValueError("embedding_model must not be empty")
        self._embedding_model = embedding_model
        self._vector_size: int | None = None
        self._records: dict[str, _StoredVectorRecord] = {}

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    def ensure_collection(self, vector_size: int) -> None:
        if type(vector_size) is not int:
            raise ValueError("vector_size must be an integer")
        if vector_size < 1:
            raise ValueError("vector_size must be positive")
        if self._vector_size is None:
            self._vector_size = vector_size
            return
        if self._vector_size != vector_size:
            raise ValueError("collection dimension does not match vector_size")

    def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if self._vector_size is None:
            raise RuntimeError("collection has not been initialized")
        if len(chunks) != len(embeddings):
            raise ValueError("chunk and embedding count must match")

        pending: list[tuple[str, _StoredVectorRecord]] = []
        for chunk, embedding in zip(chunks, embeddings):
            vector = tuple(float(value) for value in embedding)
            if len(vector) != self._vector_size:
                raise ValueError("embedding dimension does not match collection")
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("embedding values must be finite")
            if not any(value != 0.0 for value in vector):
                raise ValueError("zero embedding vectors are not allowed")

            metadata = VectorRecordMetadata(
                paper_id=chunk.paper_id,
                chunk_id=chunk.chunk_id,
                section=chunk.section,
                page=chunk.page,
                content_hash=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                embedding_model=self.embedding_model,
            )
            pending.append(
                (
                    chunk.chunk_id,
                    _StoredVectorRecord(
                        text=chunk.text,
                        embedding=vector,
                        metadata=metadata,
                    ),
                )
            )

        for chunk_id, record in pending:
            self._records[chunk_id] = record

    def search(
        self,
        query_embedding: Sequence[float],
        limit: int,
        filters: VectorFilter | None = None,
    ) -> list[VectorSearchResult]:
        if self._vector_size is None:
            raise RuntimeError("collection has not been initialized")
        if type(limit) is not int:
            raise ValueError("limit must be an integer")
        if limit < 1:
            raise ValueError("limit must be positive")

        query = tuple(float(value) for value in query_embedding)
        if len(query) != self._vector_size:
            raise ValueError("query embedding dimension does not match collection")
        if not all(math.isfinite(value) for value in query):
            raise ValueError("query embedding values must be finite")

        if max(abs(value) for value in query) == 0.0:
            raise ValueError("zero query embedding vectors are not allowed")

        results: list[VectorSearchResult] = []
        for record in self._records.values():
            if (
                filters is not None
                and filters.paper_id is not None
                and record.metadata.paper_id != filters.paper_id
            ):
                continue

            cosine = _cosine_similarity(query, record.embedding)
            cosine = max(-1.0, min(1.0, cosine))
            score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
            results.append(
                VectorSearchResult(
                    chunk_id=record.metadata.chunk_id,
                    text=record.text,
                    score=score,
                    metadata=record.metadata,
                )
            )

        results.sort(key=lambda result: (-result.score, result.chunk_id))
        return results[:limit]

    def delete_by_paper(self, paper_id: str) -> None:
        self._records = {
            chunk_id: record
            for chunk_id, record in self._records.items()
            if record.metadata.paper_id != paper_id
        }