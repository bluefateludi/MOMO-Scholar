from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from paper_agent.techscout.errors import Failure, RecoveryAction, StableId
from paper_agent.techscout.models import (
    NonEmptyStr,
    PocStatus,
    SkillSpec,
    TechScoutModel,
)


class ResearchSkillInput(TechScoutModel):
    candidate_id: StableId
    query: NonEmptyStr
    constraints: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=5)


class ResearchSkillOutput(TechScoutModel):
    candidate_id: StableId
    source_ids: tuple[StableId, ...] = Field(max_length=5)
    evidence_ids: tuple[StableId, ...] = Field(max_length=12)
    completion_notes: tuple[NonEmptyStr, ...] = Field(min_length=1)


class SmokeTestSkillInput(TechScoutModel):
    candidate_id: StableId
    recipe_id: StableId
    checks: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=8)


class SmokeTestSkillOutput(TechScoutModel):
    candidate_id: StableId
    poc_result_id: StableId
    status: PocStatus
    artifact_ids: tuple[StableId, ...]


class FailureDiagnosisInput(TechScoutModel):
    failure: Failure
    candidate_id: StableId | None = None
    available_actions: tuple[RecoveryAction, ...] = Field(min_length=1)


class FailureDiagnosisOutput(TechScoutModel):
    selected_action: RecoveryAction
    rationale: NonEmptyStr
    retry_stage_only: bool = True


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    spec: SkillSpec
    input_model: type[BaseModel]
    output_model: type[BaseModel]
