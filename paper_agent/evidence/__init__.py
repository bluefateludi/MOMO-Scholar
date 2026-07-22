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
from .hybrid import HybridEvidenceRetriever
from .factory import RetrievalConfigurationError, build_retrieval_service
from .packs import EvidencePack, EvidencePackBuilder, RetrievalServiceFactory
from .retriever import LexicalCandidateSource, retrieve_lexical_candidates
from .vector_source import VectorCandidateSource, VectorSourceExecutionError

__all__ = [
    "CandidateSource",
    "DegradationCode",
    "ErrorCode",
    "EventStatus",
    "EvidenceRetrievalService",
    "EvidencePack",
    "EvidencePackBuilder",
    "FailureStage",
    "HybridEvidenceRetriever",
    "LexicalCandidateSource",
    "RetrievalCandidate",
    "RetrievalConfigurationError",
    "RetrievalCounts",
    "RetrievalDiagnostics",
    "RetrievalEvent",
    "RetrievalEventSink",
    "RetrievalOutcome",
    "RetrievalSource",
    "RetrievalSourceUnavailable",
    "RetrievalServiceFactory",
    "VectorCandidateSource",
    "VectorSourceExecutionError",
    "VectorFailureStage",
    "build_retrieval_service",
    "retrieve_lexical_candidates",
]
