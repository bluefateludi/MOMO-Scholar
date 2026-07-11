from typing import Protocol, Sequence, runtime_checkable

from paper_agent.schemas import Chunk
from paper_agent.vector.models import VectorFilter, VectorSearchResult


@runtime_checkable
class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorStore(Protocol):
    @property
    def embedding_model(self) -> str: ...

    def ensure_collection(self, vector_size: int) -> None: ...

    def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...

    def search(
        self,
        query_embedding: Sequence[float],
        limit: int,
        filters: VectorFilter | None = None,
    ) -> list[VectorSearchResult]: ...

    def delete_by_paper(self, paper_id: str) -> None: ...
