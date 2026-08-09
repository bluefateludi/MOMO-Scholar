"""Deterministic final validation for TechScout artifacts."""

from paper_agent.techscout.validation.gate import (
    REQUIRED_TERMINAL_ARTIFACTS,
    ValidationGate,
    ValidationInput,
    ValidationResult,
)

__all__ = [
    "REQUIRED_TERMINAL_ARTIFACTS",
    "ValidationGate",
    "ValidationInput",
    "ValidationResult",
]
