from typing import Protocol

from pydantic import Field

from paper_agent.techscout.models import TechScoutModel
from paper_agent.techscout.state import ResearchStage, ResearchState


class StageResult(TechScoutModel):
    """A stage's deterministic state update and metered resource usage."""

    state: ResearchState
    tool_calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)


class StageServices(Protocol):
    """Single injectable boundary for all work performed by graph stages."""

    def execute(
        self,
        stage: ResearchStage,
        state: ResearchState,
    ) -> StageResult: ...
