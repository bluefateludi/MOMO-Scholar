from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_agent.config import RetrievalMode
from paper_agent.schemas import Evidence


RetrievalSource = Literal["lexical", "vector"]
DegradationCode = Literal[
    "embedding_timeout",
    "vector_network_unavailable",
    "vector_rate_limited",
    "vector_server_unavailable",
]
FailureStage = Literal[
    "validation",
    "assembly",
    "lexical",
    "vector_index",
    "vector_query",
    "fusion",
    "evidence_conversion",
]
ErrorCode = Literal[
    "invalid_request",
    "retrieval_configuration_error",
    "lexical_failure",
    "vector_failure",
    "fusion_failure",
    "evidence_conversion_failure",
]
EventStatus = Literal["ok", "error"]


class FrozenRetrievalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RetrievalCandidate(FrozenRetrievalModel):
    chunk_id: str
    paper_id: str
    text: str
    section: str | None = None
    page: int | None = None
    retrieval_sources: tuple[RetrievalSource, ...]
    lexical_score: float | None = Field(default=None, ge=0.0, le=1.0)
    lexical_rank: int | None = Field(default=None, ge=1)
    vector_score: float | None = Field(default=None, ge=0.0, le=1.0)
    vector_rank: int | None = Field(default=None, ge=1)
    fusion_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_sources(self) -> "RetrievalCandidate":
        canonical_sources = {
            ("lexical",),
            ("vector",),
            ("lexical", "vector"),
        }
        if self.retrieval_sources not in canonical_sources:
            raise ValueError("retrieval sources must use canonical order")

        for source in ("lexical", "vector"):
            score = getattr(self, f"{source}_score")
            rank = getattr(self, f"{source}_rank")
            if source in self.retrieval_sources:
                if score is None or rank is None:
                    raise ValueError(f"{source} score and rank must both be present")
            elif score is not None or rank is not None:
                raise ValueError(f"fields for absent {source} source are not allowed")
        return self


class RetrievalCounts(FrozenRetrievalModel):
    lexical_candidate_count: int = Field(ge=0)
    vector_candidate_count: int = Field(ge=0)
    fused_candidate_count: int = Field(ge=0)
    returned_evidence_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "RetrievalCounts":
        if self.returned_evidence_count > self.fused_candidate_count:
            raise ValueError("returned_evidence_count cannot exceed fused_candidate_count")
        return self


class RetrievalDiagnostics(RetrievalCounts):
    requested_mode: RetrievalMode
    actual_mode: Literal["lexical", "hybrid"]
    vector_attempted: bool
    degraded: bool
    degradation_code: DegradationCode | None = None

    @model_validator(mode="after")
    def validate_diagnostics(self) -> "RetrievalDiagnostics":
        _validate_retrieval_state(self)
        return self


class RetrievalEvent(RetrievalCounts):
    status: EventStatus
    requested_mode: RetrievalMode
    actual_mode: Literal["lexical", "hybrid"] | None
    vector_attempted: bool
    degraded: bool
    degradation_code: DegradationCode | None = None
    failure_stage: FailureStage | None = None
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_event(self) -> "RetrievalEvent":
        _validate_retrieval_state(self)
        if self.status == "ok":
            if self.actual_mode is None or self.failure_stage is not None or self.error_code is not None:
                raise ValueError("successful event requires actual mode and no error fields")
        else:
            if self.failure_stage is None or self.error_code is None:
                raise ValueError("error event requires failure stage and error code")
            if self.failure_stage == "assembly":
                if self.actual_mode is not None:
                    raise ValueError("assembly error event cannot have actual_mode")
            elif self.actual_mode is None:
                raise ValueError("non-assembly error event requires actual_mode")
        return self


class RetrievalOutcome(FrozenRetrievalModel):
    evidence: tuple[Evidence, ...]
    diagnostics: RetrievalDiagnostics


def _validate_retrieval_state(
    value: RetrievalDiagnostics | RetrievalEvent,
) -> None:
    if not value.vector_attempted and value.vector_candidate_count != 0:
        raise ValueError("vector_candidate_count requires a vector attempt")
    if value.actual_mode == "hybrid" and not value.vector_attempted:
        raise ValueError("hybrid actual mode requires a vector attempt")
    if value.degraded:
        if not (
            value.requested_mode == "auto"
            and value.actual_mode == "lexical"
            and value.vector_attempted
            and value.degradation_code is not None
        ):
            raise ValueError("degraded retrieval must be an auto lexical fallback")
    elif value.degradation_code is not None:
        raise ValueError("non-degraded retrieval cannot have a degradation code")
