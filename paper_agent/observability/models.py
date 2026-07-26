from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic.types import JsonValue

from paper_agent.config import RetrievalMode, Settings
from paper_agent.modeling import StrictModel


ManifestStatus = Literal[
    "running", "completed", "completed_with_degradation", "failed"
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC-aware")
    return value


class SafeRunSettings(StrictModel):
    retrieval_mode: RetrievalMode
    embedding_model: str
    generation_provider: Literal["dashscope"]
    generation_endpoint_host: str
    generation_model: str
    generation_timeout_seconds: float
    pdf_download_timeout_seconds: float
    pdf_max_bytes: int
    pdf_max_pages: int
    analysis_evidence_per_paper: int
    chunk_max_words: int
    chunk_overlap_words: int

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        chunk_max_words: int,
        chunk_overlap_words: int,
    ) -> SafeRunSettings:
        endpoint_host = urlsplit(settings.dashscope_generation_base_url).hostname
        if endpoint_host is None:
            raise ValueError("generation endpoint host is required")
        return cls(
            retrieval_mode=settings.retrieval_mode,
            embedding_model=settings.bailian_embedding_model,
            generation_provider="dashscope",
            generation_endpoint_host=endpoint_host,
            generation_model=settings.dashscope_generation_model,
            generation_timeout_seconds=settings.dashscope_generation_timeout_seconds,
            pdf_download_timeout_seconds=settings.pdf_download_timeout_seconds,
            pdf_max_bytes=settings.pdf_max_bytes,
            pdf_max_pages=settings.pdf_max_pages,
            analysis_evidence_per_paper=settings.analysis_evidence_per_paper,
            chunk_max_words=chunk_max_words,
            chunk_overlap_words=chunk_overlap_words,
        )


class RunCounts(StrictModel):
    selected_papers: int = Field(ge=0)
    pdf_documents: int = Field(ge=0)
    abstract_documents: int = Field(ge=0)
    explicit_abstract_documents: int = Field(ge=0)
    pdf_fallback_documents: int = Field(ge=0)
    excluded_papers: int = Field(ge=0)
    successful_analyses: int = Field(ge=0)
    evidence_items: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_partitions(self) -> RunCounts:
        if self.abstract_documents != (
            self.explicit_abstract_documents + self.pdf_fallback_documents
        ):
            raise ValueError(
                "abstract documents must equal explicit and fallback documents"
            )
        if self.selected_papers != (
            self.pdf_documents + self.abstract_documents + self.excluded_papers
        ):
            raise ValueError("selected papers must equal documents and excluded papers")
        if self.successful_analyses > self.pdf_documents + self.abstract_documents:
            raise ValueError("successful analyses cannot exceed available documents")
        return self


class RetrievalRecord(StrictModel):
    paper_id: str
    requested_mode: RetrievalMode
    actual_mode: Literal["lexical", "hybrid"]
    degraded: bool
    degradation_code: str | None = None


class UsageTotals(StrictModel):
    operations: int = Field(ge=0)
    http_attempts: int = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class RunIssue(StrictModel):
    stage: str
    code: str
    paper_id: str | None = None
    message: str | None = None


class RunManifest(StrictModel):
    run_id: str
    execution_id: str = Field(min_length=1)
    trace_enabled: bool = True
    status: ManifestStatus
    question: str
    requested_limit: int
    no_pdf: bool
    started_at: datetime
    finished_at: datetime | None = None
    settings: SafeRunSettings
    counts: RunCounts
    stage_elapsed_seconds: dict[str, float]
    usage: UsageTotals
    component_versions: dict[str, str]
    retrieval_outcomes: list[RetrievalRecord] = Field(default_factory=list)
    degradations: list[RunIssue] = Field(default_factory=list)
    errors: list[RunIssue] = Field(default_factory=list)
    trace_schema_version: Literal['1.0'] | None = None
    trace_root_trace_id: str | None = Field(
        default=None, pattern=r'^[0-9a-f]{32}$'
    )
    trace_root_span_id: str | None = Field(
        default=None, pattern=r'^[0-9a-f]{16}$'
    )
    trace_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    _started_at_utc = field_validator("started_at")(_require_utc)
    _finished_at_utc = field_validator("finished_at")(_require_utc)

    @model_validator(mode="after")
    def validate_lifecycle_timestamps(self) -> RunManifest:
        if self.status == "running" and self.finished_at is not None:
            raise ValueError("running manifest must not have a finished timestamp")
        if self.status != "running" and self.finished_at is None:
            raise ValueError("terminal manifest requires a finished timestamp")
        return self


    @model_validator(mode='after')
    def validate_trace_metadata(self) -> RunManifest:
        trace_values = (
            self.trace_schema_version,
            self.trace_root_trace_id,
            self.trace_root_span_id,
            self.trace_sha256,
        )
        if self.status == 'running':
            if any(value is not None for value in trace_values):
                raise ValueError('running manifest forbids terminal trace metadata')
            return self
        if not self.trace_enabled:
            if any(value is not None for value in trace_values):
                raise ValueError('disabled trace requires null trace metadata')
            return self
        persistence_failed = self.status == 'failed' and any(
            issue.code == 'trace_persistence_failed' for issue in self.errors
        )
        if persistence_failed:
            if any(value is not None for value in trace_values):
                raise ValueError(
                    'trace persistence failure requires null trace metadata'
                )
            return self
        if any(value is None for value in trace_values):
            raise ValueError('terminal manifest requires trace metadata')
        if self.trace_root_trace_id == '0' * 32:
            raise ValueError('trace root trace ID must be non-zero')
        if self.trace_root_span_id == '0' * 16:
            raise ValueError('trace root span ID must be non-zero')
        return self


class RunEvent(StrictModel):
    timestamp: datetime
    run_id: str
    stage: str
    operation: str
    status: Literal["started", "ok", "degraded", "error"]
    paper_id: str | None = None
    code: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    _timestamp_utc = field_validator("timestamp")(_require_utc)
