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
from .citation_checker import (
    CheckedAnalysisOutcome,
    check_paper_analysis,
    check_survey_draft,
    require_publishable_report,
)

__all__ = [
    "CandidateSource",
    "CheckedAnalysisOutcome",
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
    "check_paper_analysis",
    "check_survey_draft",
    "require_publishable_report",
    "retrieve_lexical_candidates",
]
