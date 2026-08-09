from enum import Enum

from pydantic import Field, model_validator
from typing_extensions import Self

from paper_agent.techscout.errors import Failure, StableId
from paper_agent.techscout.models import (
    GateOutcome,
    ResearchPlan,
    TechScoutModel,
    TerminalStatus,
)


class ResearchStage(str, Enum):
    NORMALIZE_REQUEST = "normalize_request"
    PLAN_RESEARCH = "plan_research"
    RESEARCH_CANDIDATES = "research_candidates"
    SELECT_CONTEXT = "select_context"
    PLAN_POC = "plan_poc"
    EXECUTE_POC = "execute_poc"
    VALIDATE = "validate"
    RECOVER_ONCE = "recover_once"
    REVIEW_REPORT = "review_report"
    PUBLISH = "publish"
    TERMINAL = "terminal"


class CheckpointMetadata(TechScoutModel):
    checkpoint_id: StableId
    run_id: StableId
    stage: ResearchStage
    sequence: int = Field(ge=0)
    parent_checkpoint_id: StableId | None = None
    completed_stages: tuple[ResearchStage, ...]


class ResearchState(TechScoutModel):
    run_id: StableId
    stage: ResearchStage
    step_count: int = Field(ge=0, le=16)
    recovery_count: int = Field(ge=0, le=1)
    plan: ResearchPlan | None = None
    checkpoint: CheckpointMetadata | None = None
    candidate_ids: tuple[StableId, ...]
    source_ids: tuple[StableId, ...]
    evidence_ids: tuple[StableId, ...]
    poc_result_ids: tuple[StableId, ...]
    failures: tuple[Failure, ...]
    gate_outcome: GateOutcome | None = None
    terminal_status: TerminalStatus | None = None

    @model_validator(mode="after")
    def validate_terminal_state(self) -> Self:
        if self.terminal_status is not None and self.stage is not ResearchStage.TERMINAL:
            raise ValueError("terminal status requires terminal stage")
        if self.stage is ResearchStage.TERMINAL and (
            self.terminal_status is None or self.gate_outcome is None
        ):
            raise ValueError("terminal stage requires terminal status and gate outcome")
        if self.stage is not ResearchStage.TERMINAL and self.terminal_status is not None:
            raise ValueError("non-terminal stage cannot have terminal status")
        if self.checkpoint is not None and self.checkpoint.run_id != self.run_id:
            raise ValueError("checkpoint run identifier must match state")
        return self
