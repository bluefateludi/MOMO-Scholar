from datetime import datetime
from typing import Protocol

from pydantic import Field, field_validator

from paper_agent.techscout.models import (
    DecisionReport,
    RunManifest,
    TechScoutModel,
)
from paper_agent.techscout.state import ResearchStage, ResearchState


class StageArtifacts(TechScoutModel):
    """Validated report artifacts carried between isolated graph stages."""

    report: DecisionReport | None = None
    manifest: RunManifest | None = None


class StageDeadline(TechScoutModel):
    """Deadline contract that every external stage adapter must enforce."""

    deadline_at: datetime
    timeout_seconds: float = Field(gt=0)

    @field_validator("deadline_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline_at must include a timezone")
        return value


class StageDeadlineExceeded(TimeoutError):
    """Raised when a stage adapter reaches its enforced I/O deadline."""


class StageResult(TechScoutModel):
    """A stage's deterministic state update and metered resource usage."""

    state: ResearchState
    artifacts: StageArtifacts = Field(default_factory=StageArtifacts)
    tool_calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)


class HarnessRunResult(TechScoutModel):
    """Terminal or interrupted graph state together with produced artifacts."""

    state: ResearchState
    report: DecisionReport | None = None
    manifest: RunManifest | None = None


class StageServices(Protocol):
    """Single injectable boundary for all work performed by graph stages."""

    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
        artifacts: StageArtifacts,
        deadline: StageDeadline,
    ) -> StageResult: ...
