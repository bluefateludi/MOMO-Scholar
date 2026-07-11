from collections.abc import Sequence
import hashlib

from paper_agent.schemas import Chunk
from paper_agent.vector import (
    InMemoryVectorStore,
    VectorFilter,
    VectorRetriever,
)


class DeterministicEmbedder:
    model_name = "text-embedding-v4"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vectors[text] for text in texts]


def _chunk(
    chunk_id: str,
    paper_id: str,
    text: str,
    *,
    section: str,
    page: int,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        section=section,
        page=page,
        text=text,
        token_count=len(text.split()),
    )


def test_offline_vector_retrieval_lifecycle_across_multiple_papers() -> None:
    factual_a = _chunk(
        "chunk-a",
        "paper-a",
        "Grounding reduces hallucinations.",
        section="Methods",
        page=2,
    )
    factual_b = _chunk(
        "chunk-b",
        "paper-b",
        "Retrieved evidence improves factual reliability.",
        section="Results",
        page=7,
    )
    efficiency = _chunk(
        "chunk-c",
        "paper-a",
        "Caching improves throughput.",
        section="Experiments",
        page=5,
    )
    updated_a = _chunk(
        "chunk-a",
        "paper-a",
        "Caching now improves latency.",
        section="Results",
        page=9,
    )
    vectors = {
        factual_a.text: [1.0, 0.0],
        factual_b.text: [1.0, 0.0],
        efficiency.text: [0.0, 1.0],
        updated_a.text: [0.0, 1.0],
        "How is factual reliability improved?": [1.0, 0.0],
        "How is latency improved?": [0.0, 1.0],
    }
    embedder = DeterministicEmbedder(vectors)
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    retriever = VectorRetriever(embedder=embedder, store=store)

    retriever.index_chunks([factual_b, efficiency, factual_a])

    factual = retriever.retrieve("How is factual reliability improved?", 3)
    assert [candidate.chunk_id for candidate in factual] == [
        "chunk-a",
        "chunk-b",
        "chunk-c",
    ]
    assert factual[0].text == factual_a.text
    assert all(0.0 <= candidate.score <= 1.0 for candidate in factual)
    assert [candidate.score for candidate in factual] == sorted(
        (candidate.score for candidate in factual), reverse=True
    )
    assert factual[0].metadata.model_dump() == {
        "paper_id": "paper-a",
        "chunk_id": "chunk-a",
        "section": "Methods",
        "page": 2,
        "content_hash": hashlib.sha256(factual_a.text.encode("utf-8")).hexdigest(),
        "embedding_model": "text-embedding-v4",
    }

    filtered = retriever.retrieve(
        "How is factual reliability improved?",
        3,
        VectorFilter(paper_id="paper-b"),
    )
    assert [(candidate.paper_id, candidate.chunk_id) for candidate in filtered] == [
        ("paper-b", "chunk-b")
    ]

    old_hash = factual[0].metadata.content_hash
    retriever.index_chunks([updated_a])
    fresh_retriever = VectorRetriever(embedder=embedder, store=store)
    updated = fresh_retriever.retrieve(
        "How is latency improved?", 3, VectorFilter(paper_id="paper-a")
    )
    updated_candidate = next(
        candidate for candidate in updated if candidate.chunk_id == "chunk-a"
    )
    assert updated_candidate.text == updated_a.text
    assert updated_candidate.metadata.section == "Results"
    assert updated_candidate.metadata.page == 9
    assert updated_candidate.metadata.content_hash != old_hash
    assert updated_candidate.metadata.content_hash == hashlib.sha256(
        updated_a.text.encode("utf-8")
    ).hexdigest()
    assert updated[0].chunk_id == "chunk-a"

    store.delete_by_paper("paper-b")
    assert fresh_retriever.retrieve(
        "How is factual reliability improved?",
        3,
        VectorFilter(paper_id="paper-b"),
    ) == []

    remaining = fresh_retriever.retrieve(
        "How is latency improved?",
        3,
        VectorFilter(paper_id="paper-a"),
    )
    assert [candidate.chunk_id for candidate in remaining] == [
        "chunk-a",
        "chunk-c",
    ]
    assert remaining[0].text == updated_a.text
