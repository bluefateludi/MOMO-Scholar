from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from paper_agent.techscout.errors import FailureCode, StableId
from paper_agent.techscout.models import (
    CacheStatus,
    HttpsUrl,
    NonEmptyStr,
    Sha256,
    TechScoutModel,
)


class SourceProvenance(TechScoutModel):
    provider: NonEmptyStr
    retrieved_at: datetime
    snapshot_sha256: Sha256
    cache_status: CacheStatus
    cache_fallback: bool = False

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value


class SearchInput(TechScoutModel):
    query: NonEmptyStr
    candidate_id: StableId
    domains: tuple[NonEmptyStr, ...] = Field(default=(), max_length=10)
    max_results: int = Field(default=5, ge=1, le=5)


class SearchHit(TechScoutModel):
    title: NonEmptyStr
    url: HttpsUrl
    snippet: NonEmptyStr
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class SearchOutput(TechScoutModel):
    query: NonEmptyStr
    candidate_id: StableId
    results: tuple[SearchHit, ...] = Field(max_length=5)
    provenance: SourceProvenance


class FetchInput(TechScoutModel):
    url: HttpsUrl
    candidate_id: StableId


class FetchOutput(TechScoutModel):
    url: HttpsUrl
    candidate_id: StableId
    media_type: NonEmptyStr
    content: NonEmptyStr
    size_bytes: int = Field(ge=1)
    provenance: SourceProvenance


class GitHubInspectInput(TechScoutModel):
    repository_url: HttpsUrl
    candidate_id: StableId
    release_limit: int = Field(default=3, ge=0, le=5)
    issue_limit: int = Field(default=3, ge=0, le=5)


class GitHubRelease(TechScoutModel):
    tag: NonEmptyStr
    url: HttpsUrl
    published_at: datetime | None = None


class GitHubIssue(TechScoutModel):
    number: int = Field(ge=1)
    title: NonEmptyStr
    state: Literal["open", "closed"]
    url: HttpsUrl


class GitHubInspectOutput(TechScoutModel):
    candidate_id: StableId
    repository_url: HttpsUrl
    default_branch: NonEmptyStr
    description: str
    stars: int = Field(ge=0)
    archived: bool
    readme_excerpt: str
    releases: tuple[GitHubRelease, ...] = Field(max_length=5)
    issues: tuple[GitHubIssue, ...] = Field(max_length=5)
    provenance: SourceProvenance


class SmokeTestInput(TechScoutModel):
    candidate_id: StableId
    recipe_id: StableId
    checks: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=8)
    requested_version: NonEmptyStr | None = None


class SmokeTestOutput(TechScoutModel):
    candidate_id: StableId
    recipe_id: StableId
    status: Literal["passed", "failed", "timed_out", "research_only"]
    resolved_version: NonEmptyStr | None = None
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    artifact_sha256: Sha256 | None = None
    failure_code: FailureCode | None = None


TOOL_INPUT_MODELS = {
    "web.search": SearchInput,
    "web.fetch": FetchInput,
    "github.inspect_repository": GitHubInspectInput,
    "sandbox.run_smoke_test": SmokeTestInput,
}

TOOL_OUTPUT_MODELS = {
    "web.search": SearchOutput,
    "web.fetch": FetchOutput,
    "github.inspect_repository": GitHubInspectOutput,
    "sandbox.run_smoke_test": SmokeTestOutput,
}
