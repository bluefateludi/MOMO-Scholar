from collections.abc import Sequence

from paper_agent.schemas import Chunk
from paper_agent.vector.contracts import Embedder, VectorStore
from paper_agent.vector.embedding import _validate_embedding_batch
from paper_agent.vector.models import VectorCandidate, VectorFilter


class VectorRetriever:
    def __init__(self, *, embedder: Embedder, store: VectorStore) -> None:
        self._embedder = embedder
        self._store = store

    def index_chunks(self, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        if self._embedder.model_name != self._store.embedding_model:
            raise ValueError("embedder and store embedding model identities must match")

        texts = [chunk.text for chunk in chunks]
        embeddings = _validate_embedding_batch(texts, self._embedder.embed(texts))
        vector_size = len(embeddings[0])

        self._store.ensure_collection(vector_size)
        self._store.upsert(chunks, embeddings)

    def retrieve(
        self,
        question: str,
        limit: int,
        filters: VectorFilter | None = None,
    ) -> list[VectorCandidate]:
        if not question.strip():
            raise ValueError("question must not be blank")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if self._embedder.model_name != self._store.embedding_model:
            raise ValueError("embedder and store embedding model identities must match")

        embeddings = _validate_embedding_batch(
            [question], self._embedder.embed([question])
        )
        results = self._store.search(embeddings[0], limit, filters)
        return [
            VectorCandidate(
                chunk_id=result.chunk_id,
                paper_id=result.metadata.paper_id,
                text=result.text,
                score=result.score,
                metadata=result.metadata,
            )
            for result in results
        ]