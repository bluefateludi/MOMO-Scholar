from collections.abc import Sequence

from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.retriever import LexicalCandidateSource
from paper_agent.evidence.vector_source import VectorCandidateSource
from paper_agent.schemas import Chunk
from paper_agent.vector import InMemoryVectorStore, VectorRetriever


class DeterministicEmbedder:
    model_name = "test-hybrid-v1"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vectors[text] for text in texts]


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
