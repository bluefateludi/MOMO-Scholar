from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace

from paper_agent.config import Settings
from paper_agent.evidence.packs import EvidencePackBuilder
from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.retriever import LexicalCandidateSource
from paper_agent.evidence.vector_source import VectorCandidateSource
from paper_agent.schemas import Chunk
from paper_agent.vector import InMemoryVectorStore, VectorRetriever
from paper_agent.vector.bailian import BailianTextEmbedder


class DeterministicEmbedder:
    model_name = "test-hybrid-v1"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vectors[text] for text in texts]


class DeterministicTransport:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.close_count = 0

    def embed(self, *, texts, model, api_key, region, timeout):
        return [self.vectors[text] for text in texts]

    def close(self) -> None:
        self.close_count += 1


class CountingHybridServiceFactory:
    def __init__(self) -> None:
        self.created_store_count = 0
        self.released_store_count = 0

    @contextmanager
    def __call__(self, settings, *, transport=None) -> Iterator[HybridEvidenceRetriever]:
        self.created_store_count += 1
        embedder = BailianTextEmbedder(
            api_key=settings.dashscope_api_key,
            transport=transport,
            model=settings.bailian_embedding_model,
        )
        store = InMemoryVectorStore(embedding_model=embedder.model_name)
        retriever = VectorRetriever(embedder=embedder, store=store)
        try:
            yield HybridEvidenceRetriever(
                lexical_source=LexicalCandidateSource(),
                vector_source=VectorCandidateSource(retriever),
                requested_mode=settings.retrieval_mode,
                candidate_k=settings.retrieval_candidate_k,
                top_k=settings.retrieval_top_k,
                rrf_k=settings.retrieval_rrf_k,
            )
        finally:
            self.released_store_count += 1


def _chunk(chunk_id: str, paper_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        section="Results",
        page=1,
        text=text,
        token_count=len(text.split()),
    )


def test_real_hybrid_stack_keeps_complementary_results_once() -> None:
    question = "exact kinase"
    lexical_chunk = _chunk(
        "chunk-lex", "paper-lex", "exact kinase marker"
    )
    vector_chunk = _chunk(
        "chunk-vec", "paper-vec", "semantic pathway neighbor"
    )
    embedder = DeterministicEmbedder(
        {
            lexical_chunk.text: [0.0, 1.0],
            vector_chunk.text: [1.0, 0.0],
            question: [1.0, 0.0],
        }
    )
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    vector_retriever = VectorRetriever(embedder=embedder, store=store)
    service = HybridEvidenceRetriever(
        lexical_source=LexicalCandidateSource(),
        vector_source=VectorCandidateSource(vector_retriever),
        requested_mode="hybrid",
        candidate_k=1,
        top_k=2,
        rrf_k=60,
    )

    outcome = service.retrieve(
        question,
        [vector_chunk, lexical_chunk],
        "run-integration",
    )

    assert {item.chunk_id for item in outcome.evidence} == {
        "chunk-lex",
        "chunk-vec",
    }
    assert len({item.chunk_id for item in outcome.evidence}) == 2
    assert [item.chunk_id for item in outcome.evidence] == [
        "chunk-lex",
        "chunk-vec",
    ]
    assert [item.evidence_id for item in outcome.evidence] == [
        "run-integration:ev_001",
        "run-integration:ev_002",
    ]
    assert [item.relevance_score for item in outcome.evidence] == [0.5, 0.5]
    assert outcome.diagnostics.model_dump() == {
        "lexical_candidate_count": 1,
        "vector_candidate_count": 1,
        "fused_candidate_count": 2,
        "returned_evidence_count": 2,
        "requested_mode": "hybrid",
        "actual_mode": "hybrid",
        "vector_attempted": True,
        "degraded": False,
        "degradation_code": None,
    }
    assert embedder.calls == [
        [vector_chunk.text, lexical_chunk.text],
        [question],
    ]


def test_evidence_pack_builder_isolates_real_hybrid_store_per_paper() -> None:
    question = "semantic target"
    paper_1 = _chunk("paper-1:chunk:001", "paper-1", "first document")
    paper_2 = _chunk("paper-2:chunk:001", "paper-2", "second document")
    transport = DeterministicTransport(
        {
            paper_1.text: [1.0, 0.0],
            paper_2.text: [0.0, 1.0],
            question: [0.0, 1.0],
        }
    )
    factory = CountingHybridServiceFactory()
    settings = replace(
        Settings(),
        dashscope_api_key="fake-key",
        retrieval_mode="hybrid",
        retrieval_candidate_k=1,
        retrieval_top_k=1,
        analysis_evidence_per_paper=1,
    )
    builder = EvidencePackBuilder(
        settings=settings,
        embedding_transport=transport,
        service_factory=factory,
    )

    first = builder.build(
        question=question,
        paper_id="paper-1",
        chunks=[paper_1],
        run_id="run-isolation",
    )
    second = builder.build(
        question=question,
        paper_id="paper-2",
        chunks=[paper_2],
        run_id="run-isolation",
    )

    assert all(item.paper_id == "paper-2" for item in second.evidence)
    assert not (
        {item.chunk_id for item in first.evidence}
        & {item.chunk_id for item in second.evidence}
    )
    assert factory.created_store_count == 2
    assert factory.released_store_count == 2
    assert transport.close_count == 0
