from __future__ import annotations

from typing import Literal

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from paper_agent.modeling import StrictModel


SemanticVerdict = Literal["supported", "unsupported", "ambiguous"]
SupportReasonCode = Literal[
    "gold_evidence_match",
    "human_entailment",
    "irrelevant_evidence",
    "contradicted_by_evidence",
    "insufficient_evidence",
    "no_supporting_citation",
    "partial_support",
    "insufficient_context",
    "conflicting_evidence",
]
MatchStrategy = Literal[
    "exact_locator",
    "exact_normalized_quote",
    "containment",
    "token_span_f1",
    "no_match",
]

_REASON_CODES: dict[SemanticVerdict, frozenset[str]] = {
    "supported": frozenset({"gold_evidence_match", "human_entailment"}),
    "unsupported": frozenset(
        {
            "irrelevant_evidence",
            "contradicted_by_evidence",
            "insufficient_evidence",
            "no_supporting_citation",
        }
    ),
    "ambiguous": frozenset(
        {"partial_support", "insufficient_context", "conflicting_evidence"}
    ),
}


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _optional_non_blank(value: str | None) -> str | None:
    return _non_blank(value) if value is not None else None


def _unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{label} must not contain blank values")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


class FrozenCitationModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AtomicAssertion(FrozenCitationModel):
    schema_version: Literal["1.0"]
    assertion_id: str
    case_id: str
    run_id: str
    text: str
    paper_id: str | None = None
    source_section: str
    start_char: StrictInt = Field(ge=0)
    end_char: StrictInt = Field(gt=0)

    _required_text_is_non_blank = field_validator(
        "assertion_id", "case_id", "run_id", "text", "source_section"
    )(_non_blank)
    _paper_id_is_non_blank = field_validator("paper_id")(_optional_non_blank)

    @model_validator(mode="after")
    def _offsets_are_ordered(self) -> AtomicAssertion:
        if self.end_char <= self.start_char:
            raise ValueError("assertion end offset must follow its start offset")
        return self


class CitationOccurrence(FrozenCitationModel):
    schema_version: Literal["1.0"]
    occurrence_id: str
    assertion_id: str
    evidence_id: str
    source_section: str
    start_char: StrictInt = Field(ge=0)
    end_char: StrictInt = Field(gt=0)
    structurally_valid: StrictBool
    structural_reason_code: str | None = None

    _required_text_is_non_blank = field_validator(
        "occurrence_id",
        "assertion_id",
        "evidence_id",
        "source_section",
    )(_non_blank)
    _reason_is_non_blank = field_validator("structural_reason_code")(
        _optional_non_blank
    )

    @model_validator(mode="after")
    def _structural_state_is_consistent(self) -> CitationOccurrence:
        if self.end_char <= self.start_char:
            raise ValueError("citation end offset must follow its start offset")
        if self.structurally_valid and self.structural_reason_code is not None:
            raise ValueError("valid citation must not include a structural failure reason")
        if not self.structurally_valid and self.structural_reason_code is None:
            raise ValueError("invalid citation requires a structural failure reason")
        return self


class EvidenceMatch(FrozenCitationModel):
    schema_version: Literal["1.0"]
    match_id: str
    assertion_id: str
    citation_occurrence_id: str
    actual_evidence_id: str
    gold_evidence_id: str | None = None
    strategy: MatchStrategy
    score: StrictFloat = Field(ge=0.0, le=1.0)
    supports_assertion: StrictBool
    actual_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gold_evidence_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    _required_text_is_non_blank = field_validator(
        "match_id",
        "assertion_id",
        "citation_occurrence_id",
        "actual_evidence_id",
    )(_non_blank)
    _gold_id_is_non_blank = field_validator("gold_evidence_id")(_optional_non_blank)

    @model_validator(mode="after")
    def _match_state_is_consistent(self) -> EvidenceMatch:
        if self.strategy == "no_match":
            if (
                self.gold_evidence_id is not None
                or self.gold_evidence_sha256 is not None
                or self.supports_assertion
                or self.score != 0.0
            ):
                raise ValueError("no-match record cannot claim matched support")
        elif self.gold_evidence_id is None or self.gold_evidence_sha256 is None:
            raise ValueError("matched evidence requires a gold ID and content hash")
        return self


class SupportJudgment(FrozenCitationModel):
    schema_version: Literal["1.0"]
    judgment_id: str
    case_id: str
    run_id: str
    assertion_id: str
    citation_occurrence_ids: tuple[str, ...]
    support_match_ids: tuple[str, ...]
    semantic_verdict: SemanticVerdict
    reason_code: SupportReasonCode
    notes: str | None = None
    reviewer_pseudonym: str = Field(
        pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$"
    )
    rubric_version: str
    calibration_set_version: str
    reviewed_at: str
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _required_text_is_non_blank = field_validator(
        "judgment_id",
        "case_id",
        "run_id",
        "assertion_id",
        "reviewer_pseudonym",
        "rubric_version",
        "calibration_set_version",
        "reviewed_at",
    )(_non_blank)
    _notes_are_non_blank = field_validator("notes")(_optional_non_blank)

    @field_validator("citation_occurrence_ids")
    @classmethod
    def _citation_ids_are_unique(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        return _unique(values, "citation occurrence IDs")

    @field_validator("support_match_ids")
    @classmethod
    def _support_match_ids_are_unique(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        return _unique(values, "support match IDs")

    @model_validator(mode="after")
    def _verdict_state_is_consistent(self) -> SupportJudgment:
        if self.reason_code not in _REASON_CODES[self.semantic_verdict]:
            raise ValueError("reason code is not allowed for semantic verdict")
        if self.semantic_verdict == "unsupported" and self.support_match_ids:
            raise ValueError("unsupported verdict cannot claim matched support")
        if self.semantic_verdict == "ambiguous" and self.notes is None:
            raise ValueError("ambiguous verdict requires notes")
        return self


class CalibrationRecord(FrozenCitationModel):
    schema_version: Literal["1.0"]
    calibration_id: str
    calibration_set_version: str
    rubric_version: str
    assertion_id: str
    reviewer_pseudonym: str = Field(
        pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$"
    )
    expected_verdict: SemanticVerdict
    observed_verdict: SemanticVerdict
    adjudicated_verdict: SemanticVerdict | None = None

    _required_text_is_non_blank = field_validator(
        "calibration_id",
        "calibration_set_version",
        "rubric_version",
        "assertion_id",
        "reviewer_pseudonym",
    )(_non_blank)


class CitationCaseResult(FrozenCitationModel):
    schema_version: Literal["1.0"]
    case_id: str
    run_id: str
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertions: tuple[AtomicAssertion, ...]
    citation_occurrences: tuple[CitationOccurrence, ...]
    evidence_matches: tuple[EvidenceMatch, ...]
    judgments: tuple[SupportJudgment, ...]
    calibration_records: tuple[CalibrationRecord, ...]

    _required_text_is_non_blank = field_validator("case_id", "run_id")(_non_blank)

    @model_validator(mode="after")
    def _references_are_complete_and_consistent(self) -> CitationCaseResult:
        assertion_ids = self._unique_ids(
            self.assertions, "assertion_id", "assertion IDs"
        )
        occurrence_ids = self._unique_ids(
            self.citation_occurrences,
            "occurrence_id",
            "citation occurrence IDs",
        )
        match_ids = self._unique_ids(
            self.evidence_matches, "match_id", "evidence match IDs"
        )
        occurrences_by_id = {
            item.occurrence_id: item for item in self.citation_occurrences
        }
        matches_by_id = {item.match_id: item for item in self.evidence_matches}
        self._unique_ids(self.judgments, "judgment_id", "judgment IDs")
        self._unique_ids(
            self.calibration_records, "calibration_id", "calibration IDs"
        )

        if any(
            item.case_id != self.case_id or item.run_id != self.run_id
            for item in self.assertions
        ):
            raise ValueError("assertion case and run IDs must match case result")
        if any(
            item.assertion_id not in assertion_ids
            for item in self.citation_occurrences
        ):
            raise ValueError("citation occurrence assertion reference is dangling")
        if any(
            item.assertion_id not in assertion_ids
            for item in self.evidence_matches
        ):
            raise ValueError("evidence match assertion reference is dangling")
        if any(
            item.citation_occurrence_id not in occurrence_ids
            for item in self.evidence_matches
        ):
            raise ValueError(
                "evidence match citation occurrence reference is dangling"
            )
        if any(
            occurrences_by_id[item.citation_occurrence_id].assertion_id
            != item.assertion_id
            for item in self.evidence_matches
        ):
            raise ValueError(
                "evidence match and citation occurrence must reference the same assertion"
            )
        for judgment in self.judgments:
            if (
                judgment.case_id != self.case_id
                or judgment.run_id != self.run_id
                or judgment.assertion_id not in assertion_ids
            ):
                raise ValueError("judgment case, run, or assertion reference is invalid")
            if not set(judgment.citation_occurrence_ids) <= occurrence_ids:
                raise ValueError("judgment citation occurrence reference is dangling")
            if not set(judgment.support_match_ids) <= match_ids:
                raise ValueError("judgment support match reference is dangling")
            if any(
                occurrences_by_id[occurrence_id].assertion_id
                != judgment.assertion_id
                for occurrence_id in judgment.citation_occurrence_ids
            ):
                raise ValueError(
                    "judgment and citation occurrence must reference the same assertion"
                )
            if any(
                matches_by_id[match_id].assertion_id != judgment.assertion_id
                for match_id in judgment.support_match_ids
            ):
                raise ValueError(
                    "judgment and support match must reference the same assertion"
                )
            if any(
                not matches_by_id[match_id].supports_assertion
                for match_id in judgment.support_match_ids
            ):
                raise ValueError(
                    "judgment support match IDs must reference a supporting match"
                )
            if (
                judgment.output_sha256 != self.output_sha256
                or judgment.evidence_sha256 != self.evidence_sha256
                or judgment.config_sha256 != self.config_sha256
            ):
                raise ValueError("judgment authority hashes must match case result")
        if any(
            record.assertion_id not in assertion_ids
            for record in self.calibration_records
        ):
            raise ValueError("calibration assertion reference is dangling")
        return self

    @staticmethod
    def _unique_ids(
        items: tuple[FrozenCitationModel, ...],
        field: str,
        label: str,
    ) -> set[str]:
        values = [getattr(item, field) for item in items]
        if len(values) != len(set(values)):
            raise ValueError(f"{label} must be unique")
        return set(values)


__all__ = [
    "AtomicAssertion",
    "CalibrationRecord",
    "CitationCaseResult",
    "CitationOccurrence",
    "EvidenceMatch",
    "FrozenCitationModel",
    "MatchStrategy",
    "SemanticVerdict",
    "SupportJudgment",
    "SupportReasonCode",
]
