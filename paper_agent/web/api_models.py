from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from paper_agent.modeling import StrictModel
from paper_agent.observability.models import (
    RetrievalRecord, RunCounts, RunIssue, SafeRunSettings, UsageTotals,
)
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import CheckedSurveyReport


ApiStatus = Literal[
    "queued", "running", "completed", "completed_with_degradation", "failed",
    "interrupted",
]
Phase = Literal[
    "queued", "initializing", "search", "acquisition", "chunking", "retrieval",
    "analysis", "synthesis", "citation_check", "publishing", "terminal",
]


class RetrievalRequest(StrictModel):
    mode: Literal["auto", "lexical", "hybrid"]
    candidate_k: int = Field(strict=True, ge=1, le=100)
    top_k: int = Field(strict=True, ge=1, le=20)
    rrf_k: int = Field(strict=True, ge=1, le=1000)
    analysis_evidence_per_paper: int = Field(strict=True, ge=1, le=20)

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "RetrievalRequest":
        if self.top_k > self.candidate_k:
            raise ValueError("top_k must not exceed candidate_k")
        if self.analysis_evidence_per_paper > self.top_k:
            raise ValueError("analysis_evidence_per_paper must not exceed top_k")
        return self


class CreateRunRequest(StrictModel):
    question: str = Field(min_length=3, max_length=1000)
    paper_limit: int = Field(strict=True, ge=1, le=10)
    content_mode: Literal["pdf_preferred", "abstract_only"]
    retrieval: RetrievalRequest

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RunProgress(StrictModel):
    completed_units: int | None = Field(default=None, ge=0)
    total_units: int | None = Field(default=None, ge=0)
    paper_id: str | None = None


class RunSummary(StrictModel):
    id: str
    artifact_run_id: str | None
    origin: Literal["live", "bundled_demo"]
    status: ApiStatus
    phase: Phase
    question: str
    paper_limit: int
    content_mode: Literal["pdf_preferred", "abstract_only"]
    retrieval: RetrievalRequest
    progress: RunProgress
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    has_report: bool
    demo: bool


class ManifestProjection(StrictModel):
    counts: RunCounts
    retrieval_outcomes: list[RetrievalRecord]
    degradations: list[RunIssue]
    errors: list[RunIssue]
    stage_elapsed_seconds: dict[str, float]
    usage: UsageTotals
    settings: SafeRunSettings
    component_versions: dict[str, str]


class RunDetail(RunSummary):
    manifest: ManifestProjection | None
    available_artifacts: list[str]


class ReportResponse(StrictModel):
    run_id: str
    status: Literal["completed", "completed_with_degradation"]
    report: CheckedSurveyReport
    markdown: str
    degradations: list[RunIssue]


class EvidenceSource(StrictModel):
    title: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    content_source: Literal["pdf", "abstract"] | None = None
    fallback_code: str | None = None


class EvidenceView(Evidence):
    source: EvidenceSource


class EvidenceList(StrictModel):
    items: list[EvidenceView]


class ErrorBody(StrictModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(StrictModel):
    error: ErrorBody
