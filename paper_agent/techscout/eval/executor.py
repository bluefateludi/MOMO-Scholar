from __future__ import annotations

from typing import Protocol

from paper_agent.techscout.eval.contracts import (
    EvaluationCase,
    FaultExecutionResult,
    HarnessVariant,
    RetrievalExecutionResult,
    TaskExecutionResult,
)
from paper_agent.techscout.eval.faults import DeterministicFaultInjector
from paper_agent.techscout.observability import TechScoutTraceRecorder


class InfrastructureFailure(RuntimeError):
    """A proven executor/infrastructure failure eligible for one preserved rerun."""


class EvaluationExecutor(Protocol):
    """Execution seam; final-suite methods may be called by four worker threads."""

    version: str

    def run_e2e(
        self,
        case: EvaluationCase,
        variant: HarnessVariant,
        *,
        timeout_seconds: int,
        trace: TechScoutTraceRecorder,
    ) -> TaskExecutionResult: ...

    def run_retrieval(
        self,
        case: EvaluationCase,
        *,
        timeout_seconds: int,
        trace: TechScoutTraceRecorder,
    ) -> RetrievalExecutionResult: ...

    def run_fault(
        self,
        case: EvaluationCase,
        injector: DeterministicFaultInjector,
        *,
        timeout_seconds: int,
        trace: TechScoutTraceRecorder,
    ) -> FaultExecutionResult: ...
