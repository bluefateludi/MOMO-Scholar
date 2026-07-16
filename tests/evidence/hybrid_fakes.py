from collections.abc import Sequence

from paper_agent.evidence.contracts import RetrievalEventSink
from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.models import RetrievalCandidate, RetrievalEvent
from paper_agent.schemas import Chunk


def _candidate(
    source: str, chunk_id: str, rank: int, score: float
) -> RetrievalCandidate:
    values: dict[str, object] = {
        "chunk_id": chunk_id,
        "paper_id": "p1",
        "text": f"text-{chunk_id}",
        "section": "Methods",
        "page": 1,
        "retrieval_sources": (source,),
        "lexical_score": score if source == "lexical" else None,
        "lexical_rank": rank if source == "lexical" else None,
        "vector_score": score if source == "vector" else None,
        "vector_rank": rank if source == "vector" else None,
    }
    return RetrievalCandidate.model_validate(values)


class FakeSource:
    def __init__(self, results: list[RetrievalCandidate]) -> None:
        self.results = results
        self.calls: list[tuple[str, list[Chunk], int]] = []
        self.error: Exception | None = None

    def retrieve(
        self, question: str, chunks: Sequence[Chunk], limit: int
    ) -> list[RetrievalCandidate]:
        self.calls.append((question, list(chunks), limit))
        if self.error is not None:
            raise self.error
        return self.results


def _recording_sink() -> tuple[list[RetrievalEvent], RetrievalEventSink]:
    events: list[RetrievalEvent] = []
    return events, events.append


def _chunk(chunk_id: str = "shared") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id="p1",
        section="Methods",
        page=1,
        text=f"text-{chunk_id}",
        token_count=1,
    )


def _lexical_candidate(
    chunk_id: str = "shared", score: float = 0.8, rank: int = 1
) -> RetrievalCandidate:
    return _candidate("lexical", chunk_id, rank, score)


def _vector_candidate(
    chunk_id: str = "shared", score: float = 0.9, rank: int = 1
) -> RetrievalCandidate:
    return _candidate("vector", chunk_id, rank, score)


def _service(
    mode: str,
    lexical: FakeSource,
    vector: FakeSource | None,
    *,
    candidate_k: int = 30,
    top_k: int = 8,
    rrf_k: int = 60,
) -> HybridEvidenceRetriever:
    return HybridEvidenceRetriever(
        lexical_source=lexical,
        vector_source=vector,
        requested_mode=mode,
        candidate_k=candidate_k,
        top_k=top_k,
        rrf_k=rrf_k,
    )
