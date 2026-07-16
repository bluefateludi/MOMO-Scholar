from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from paper_agent.schemas import Chunk

from .models import DegradationCode, RetrievalCandidate, RetrievalEvent, RetrievalOutcome


RetrievalEventSink = Callable[[RetrievalEvent], None]


class CandidateSource(Protocol):
    def retrieve(
        self, question: str, chunks: Sequence[Chunk], limit: int
    ) -> list[RetrievalCandidate]:
        raise NotImplementedError


class EvidenceRetrievalService(Protocol):
    def retrieve(
        self,
        question: str,
        chunks: Sequence[Chunk],
        run_id: str,
        event_sink: RetrievalEventSink | None = None,
    ) -> RetrievalOutcome:
        raise NotImplementedError


VectorFailureStage = Literal["vector_index", "vector_query"]


@dataclass(frozen=True, slots=True)
class RetrievalSourceUnavailable(RuntimeError):
    degradation_code: DegradationCode
    failure_stage: VectorFailureStage

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.degradation_code)
