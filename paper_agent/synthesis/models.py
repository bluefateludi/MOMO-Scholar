from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from paper_agent.modeling import StrictModel
from paper_agent.schemas import SupportStatus


class GroundedFinding(StrictModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class PaperAnalysis(StrictModel):
    paper_id: str
    contributions: list[GroundedFinding] = Field(default_factory=list)
    methods: list[GroundedFinding] = Field(default_factory=list)
    experiments: list[GroundedFinding] = Field(default_factory=list)
    results: list[GroundedFinding] = Field(default_factory=list)
    limitations: list[GroundedFinding] = Field(default_factory=list)


class GroundedClaim(StrictModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class SurveyDraft(StrictModel):
    tldr_claims: list[GroundedClaim]
    method_taxonomy: list[GroundedClaim]
    comparisons: list[GroundedClaim]
    key_findings: list[GroundedClaim]
    limitations: list[GroundedClaim]
    open_questions: list[GroundedClaim]


class CheckedFinding(StrictModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    support_status: SupportStatus


class CheckedPaperAnalysis(StrictModel):
    paper_id: str
    contributions: list[CheckedFinding] = Field(default_factory=list)
    methods: list[CheckedFinding] = Field(default_factory=list)
    experiments: list[CheckedFinding] = Field(default_factory=list)
    results: list[CheckedFinding] = Field(default_factory=list)
    limitations: list[CheckedFinding] = Field(default_factory=list)


class CheckedClaim(StrictModel):
    text: str
    evidence_ids: list[str]
    support_status: SupportStatus

    @model_validator(mode="after")
    def non_unsupported_claim_requires_evidence(self) -> CheckedClaim:
        if self.support_status != "unsupported" and not self.evidence_ids:
            raise ValueError("non-unsupported claim requires evidence")
        return self


class RejectedCriticalClaim(CheckedClaim):
    source_section: Literal["tldr_claims", "key_findings"]

    @model_validator(mode="after")
    def status_must_not_be_supported(self) -> RejectedCriticalClaim:
        if self.support_status == "supported":
            raise ValueError("rejected critical claims must not be supported")
        return self


class CheckedSurveyReport(StrictModel):
    question: str
    tldr_claims: list[CheckedClaim] = Field(default_factory=list)
    method_taxonomy: list[CheckedClaim] = Field(default_factory=list)
    comparisons: list[CheckedClaim] = Field(default_factory=list)
    key_findings: list[CheckedClaim] = Field(default_factory=list)
    limitations: list[CheckedClaim] = Field(default_factory=list)
    open_questions: list[CheckedClaim] = Field(default_factory=list)
    rejected_critical_claims: list[RejectedCriticalClaim] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def critical_claims_must_be_supported(self) -> CheckedSurveyReport:
        critical_claims = [*self.tldr_claims, *self.key_findings]
        if any(claim.support_status != "supported" for claim in critical_claims):
            raise ValueError("critical claims must be supported")
        return self
