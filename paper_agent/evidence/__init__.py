"""Evidence retrieval and citation checking."""

from .contracts import (
    CandidateSource,
    EvidenceRetrievalService,
    RetrievalEventSink,
    RetrievalSourceUnavailable,
    VectorFailureStage,
)
from .models import (
    DegradationCode,
    ErrorCode,
    EventStatus,
    FailureStage,
    RetrievalCandidate,
    RetrievalCounts,
    RetrievalDiagnostics,
    RetrievalEvent,
    RetrievalOutcome,
    RetrievalSource,
)
from .vector_source import VectorCandidateSource

__all__ = [
    "CandidateSource",
    "DegradationCode",
    "ErrorCode",
    "EventStatus",
    "EvidenceRetrievalService",
    "FailureStage",
    "RetrievalCandidate",
    "RetrievalCounts",
    "RetrievalDiagnostics",
    "RetrievalEvent",
    "RetrievalEventSink",
    "RetrievalOutcome",
    "RetrievalSource",
    "RetrievalSourceUnavailable",
    "VectorCandidateSource",
    "VectorFailureStage",
]
