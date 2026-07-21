from typing import Literal

from pydantic import BaseModel, Field, field_validator

from paper_agent.modeling import StrictModel


class Paper(StrictModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    url: str
    pdf_url: str | None = None
    source: str
    citation_count: int | None = None


class Chunk(BaseModel):
    chunk_id: str
    paper_id: str
    section: str | None = None
    page: int | None = None
    text: str
    token_count: int

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk text must not be empty")
        return value


class Evidence(StrictModel):
    evidence_id: str
    paper_id: str
    chunk_id: str
    section: str | None = None
    page: int | None = None
    claim_type: str
    quote: str
    relevance_score: float = Field(ge=0.0, le=1.0)


SupportStatus = Literal["supported", "weakly_supported", "unsupported"]


class ReportClaim(BaseModel):
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    support_status: SupportStatus | None = None

    def model_post_init(self, __context: object) -> None:
        if self.support_status is None:
            self.support_status = "supported" if self.evidence_ids else "unsupported"


class EvalSummary(BaseModel):
    retrieval_hit_rate: float | None = None
    evidence_coverage: float | None = None
    unsupported_claim_rate: float | None = None
    citation_validity: float | None = None
    run_cost: float | None = None
