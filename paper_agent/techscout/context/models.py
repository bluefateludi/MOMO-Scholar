from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator
from typing_extensions import Self

from paper_agent.techscout.errors import Failure, StableId
from paper_agent.techscout.models import (
    CandidateEvidence,
    EvidenceKind,
    HttpsUrl,
    JsonObject,
    NonEmptyStr,
    PocResult,
    SourceChunk,
    SourceDocument,
    TechScoutModel,
)


class ContextStage(str, Enum):
    INTAKE_PLANNING = "intake_planning"
    RESEARCH = "research"
    POC_PLANNING = "poc_planning"
    VALIDATION = "validation"
    REPORTING = "reporting"


class SkillSummary(TechScoutModel):
    skill_id: StableId
    name: NonEmptyStr
    stage: NonEmptyStr
    completion_criteria: tuple[NonEmptyStr, ...]


class SearchRecord(TechScoutModel):
    candidate_id: StableId
    query: NonEmptyStr
    source_urls: tuple[HttpsUrl, ...] = Field(max_length=5)


class CandidateContextData(TechScoutModel):
    """Candidate-partitioned context input; cross-candidate load-all is invalid."""

    candidate_id: StableId
    documents: tuple[SourceDocument, ...] = Field(default=(), max_length=50)
    chunks: tuple[SourceChunk, ...] = Field(default=(), max_length=200)
    evidence: tuple[CandidateEvidence, ...] = Field(default=(), max_length=50)
    search_history: tuple[SearchRecord, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def enforce_candidate_partition(self) -> Self:
        if any(item.candidate_id != self.candidate_id for item in self.documents):
            raise ValueError("candidate context contains an unrelated source")
        source_ids = {item.source_id for item in self.documents}
        if len(source_ids) != len(self.documents):
            raise ValueError("candidate context contains duplicate source identifiers")
        if any(item.source_id not in source_ids for item in self.chunks):
            raise ValueError("candidate context chunk references an unknown source")
        if any(item.candidate_id != self.candidate_id for item in self.evidence):
            raise ValueError("candidate context contains unrelated evidence")
        if any(item.candidate_id != self.candidate_id for item in self.search_history):
            raise ValueError("candidate context contains unrelated search history")
        return self


class ContextPacket(TechScoutModel):
    """Bounded prompt context; deliberately has no raw-page/repository field."""

    packet_id: StableId
    stage: ContextStage
    candidate_id: StableId | None = None
    request_summary: NonEmptyStr
    constraints: tuple[NonEmptyStr, ...] = Field(max_length=5)
    candidate_names: tuple[NonEmptyStr, ...] = Field(max_length=3)
    skill_summaries: tuple[SkillSummary, ...] = Field(max_length=4)
    search_history: tuple[SearchRecord, ...] = Field(max_length=8)
    sources: tuple[SourceDocument, ...] = Field(max_length=5)
    chunks: tuple[SourceChunk, ...] = Field(max_length=8)
    evidence: tuple[CandidateEvidence, ...] = Field(max_length=12)
    candidate_version: NonEmptyStr | None = None
    as_of: datetime | None = None
    trusted_recipe_schema: JsonObject | None = None
    poc_result: PocResult | None = None
    gate_rules: tuple[NonEmptyStr, ...] = Field(max_length=12)
    prior_failure: Failure | None = None
    risks: tuple[NonEmptyStr, ...] = Field(max_length=8)
    limitations: tuple[NonEmptyStr, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def enforce_stage_partition(self) -> Self:
        if self.stage is ContextStage.INTAKE_PLANNING:
            if self.candidate_id is not None:
                raise ValueError("planning context cannot select one candidate")
            if any(
                (
                    self.search_history,
                    self.sources,
                    self.chunks,
                    self.evidence,
                    self.poc_result,
                    self.prior_failure,
                )
            ):
                raise ValueError("planning context cannot load research or execution data")
            if self.as_of is not None:
                raise ValueError("planning context cannot set an as_of cutoff")
        elif self.candidate_id is None:
            raise ValueError("stage context requires one candidate")
        elif self.as_of is None:
            raise ValueError("stage context requires an as_of cutoff")
        elif self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("context as_of must include a timezone")
        if self.stage is not ContextStage.INTAKE_PLANNING and self.skill_summaries:
            raise ValueError("only planning context may contain skill summaries")
        for source in self.sources:
            if source.candidate_id != self.candidate_id:
                raise ValueError("context contains an unrelated candidate source")
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("context contains duplicate source identifiers")
        chunk_ids = {chunk.chunk_id for chunk in self.chunks}
        if len(chunk_ids) != len(self.chunks):
            raise ValueError("context contains duplicate chunk identifiers")
        for chunk in self.chunks:
            if chunk.source_id not in source_ids:
                raise ValueError("context chunk lacks selected source metadata")
        for item in self.evidence:
            if item.candidate_id != self.candidate_id:
                raise ValueError("context contains unrelated candidate evidence")
            if item.kind is EvidenceKind.RETRIEVED_FACT and not set(
                item.source_ids
            ).issubset(source_ids):
                raise ValueError("retrieved evidence lacks source metadata in context")
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("context contains duplicate evidence identifiers")
        for record in self.search_history:
            if record.candidate_id != self.candidate_id:
                raise ValueError("context contains unrelated search history")
        if self.poc_result is not None and self.poc_result.candidate_id != self.candidate_id:
            raise ValueError("context contains an unrelated candidate PoC result")
        return self
