"""Typed failure classification, bounded recovery, and approval policy."""

from paper_agent.techscout.recovery.approval import (
    ApprovalDecision,
    ApprovalOutcome,
    ApprovalPolicy,
    OperationKind,
    OperationRequest,
)
from paper_agent.techscout.recovery.classifier import FailureClassifier
from paper_agent.techscout.recovery.policy import (
    FAILURE_STAGE_BY_RESEARCH_STAGE,
    RESEARCH_STAGE_BY_FAILURE_STAGE,
    RecoveryDecision,
    RecoveryPolicy,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalOutcome",
    "ApprovalPolicy",
    "FailureClassifier",
    "FAILURE_STAGE_BY_RESEARCH_STAGE",
    "OperationKind",
    "OperationRequest",
    "RecoveryDecision",
    "RecoveryPolicy",
    "RESEARCH_STAGE_BY_FAILURE_STAGE",
]
