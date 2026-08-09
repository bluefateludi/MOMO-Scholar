"""Typed failure classification, bounded recovery, and approval policy."""

from paper_agent.techscout.recovery.approval import (
    ApprovalDecision,
    ApprovalOutcome,
    ApprovalPolicy,
    OperationKind,
    OperationRequest,
)
from paper_agent.techscout.recovery.classifier import FailureClassifier
from paper_agent.techscout.recovery.policy import RecoveryDecision, RecoveryPolicy

__all__ = [
    "ApprovalDecision",
    "ApprovalOutcome",
    "ApprovalPolicy",
    "FailureClassifier",
    "OperationKind",
    "OperationRequest",
    "RecoveryDecision",
    "RecoveryPolicy",
]
