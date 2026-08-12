from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator
from typing_extensions import Self

from paper_agent.techscout.context import ContextPacket
from paper_agent.techscout.errors import FailureCode, StableId
from paper_agent.techscout.models import (
    CandidateEvidence,
    HttpsUrl,
    NonEmptyStr,
    Sha256,
    SourceChunk,
    SourceDocument,
    SourceType,
    TechScoutModel,
)


class AcquisitionState(str, Enum):
    LIVE = "live"
    CACHE = "cache"
    UNAVAILABLE = "unavailable"


class CandidateSourcePolicy(TechScoutModel):
    candidate_id: StableId
    version: NonEmptyStr | None = None
    official_domains: tuple[NonEmptyStr, ...] = Field(max_length=5)
    official_queries: tuple[NonEmptyStr, ...] = Field(max_length=2)
    repository_url: HttpsUrl | None = None
    research_only: bool = False

    @model_validator(mode="after")
    def require_a_source(self) -> Self:
        if not self.official_queries and self.repository_url is None:
            raise ValueError("candidate policy requires an official or GitHub source")
        if self.official_queries and not self.official_domains:
            raise ValueError("official queries require an allowed domain")
        return self


class SourceAttempt(TechScoutModel):
    operation: NonEmptyStr
    reference: NonEmptyStr
    source_type: SourceType | None = None
    state: AcquisitionState
    provider: NonEmptyStr | None = None
    fetched_at: datetime | None = None
    content_sha256: Sha256 | None = None
    cache_fallback: bool = False
    failure_code: FailureCode | None = None

    @property
    def available(self) -> bool:
        return self.state is not AcquisitionState.UNAVAILABLE

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.available:
            if (
                self.source_type is None
                or self.provider is None
                or self.fetched_at is None
                or self.content_sha256 is None
                or self.failure_code is not None
            ):
                raise ValueError("available source requires complete provenance")
        elif self.failure_code is None:
            raise ValueError("unavailable source requires a failure code")
        return self


class CandidateResearchResult(TechScoutModel):
    candidate_id: StableId
    version: NonEmptyStr | None = None
    state: AcquisitionState
    research_only: bool
    documents: tuple[SourceDocument, ...] = Field(max_length=5)
    chunks: tuple[SourceChunk, ...] = Field(max_length=200)
    evidence: tuple[CandidateEvidence, ...] = Field(max_length=200)
    attempts: tuple[SourceAttempt, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        if any(item.candidate_id != self.candidate_id for item in self.documents):
            raise ValueError("research result contains an unrelated candidate source")
        source_ids = {item.source_id for item in self.documents}
        chunk_ids = {item.chunk_id for item in self.chunks}
        if any(item.source_id not in source_ids for item in self.chunks):
            raise ValueError("research chunk references an unknown source")
        if any(item.candidate_id != self.candidate_id for item in self.evidence):
            raise ValueError("research result contains unrelated candidate evidence")
        if any(not set(item.source_ids).issubset(source_ids) for item in self.evidence):
            raise ValueError("research evidence references an unknown source")
        if any(not set(item.chunk_ids).issubset(chunk_ids) for item in self.evidence):
            raise ValueError("research evidence references an unknown chunk")
        if self.state is AcquisitionState.UNAVAILABLE and self.documents:
            raise ValueError("unavailable research cannot contain documents")
        if self.state is not AcquisitionState.UNAVAILABLE and not self.documents:
            raise ValueError("available research requires at least one document")
        return self


class ResearchDelivery(TechScoutModel):
    research: CandidateResearchResult
    context: ContextPacket
