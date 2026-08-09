"""Strict domain and state contracts for MOMO TechScout."""

from paper_agent.techscout.errors import (
    Failure,
    FailureCode,
    FailureStage,
    RecoveryAction,
)
from paper_agent.techscout.models import (
    Candidate,
    CandidateEvidence,
    DecisionReport,
    GateDecision,
    GateOutcome,
    ResearchPlan,
    ResearchRequest,
    RunManifest,
    RunMode,
    TerminalStatus,
)
from paper_agent.techscout.state import (
    CheckpointMetadata,
    ResearchStage,
    ResearchState,
    RunBudget,
)

__all__ = [
    "Candidate",
    "CandidateEvidence",
    "CheckpointMetadata",
    "DecisionReport",
    "Failure",
    "FailureCode",
    "FailureStage",
    "GateDecision",
    "GateOutcome",
    "RecoveryAction",
    "ResearchPlan",
    "ResearchRequest",
    "ResearchStage",
    "ResearchState",
    "RunBudget",
    "RunManifest",
    "RunMode",
    "TerminalStatus",
]
