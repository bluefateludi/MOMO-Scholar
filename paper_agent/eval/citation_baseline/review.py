from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping, Sequence

from pydantic import (
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from paper_agent.eval.citation_baseline.contracts import (
    CalibrationRecord,
    FrozenCitationModel,
    SemanticVerdict,
    SupportJudgment,
    SupportReasonCode,
)


_VERDICTS: tuple[SemanticVerdict, ...] = (
    "supported",
    "unsupported",
    "ambiguous",
)
_DEFINITIONS: dict[SemanticVerdict, str] = {
    "supported": (
        "The cited evidence directly entails the complete atomic assertion."
    ),
    "unsupported": (
        "No cited evidence entails the complete atomic assertion, including when "
        "the evidence is irrelevant, contradictory, or insufficient."
    ),
    "ambiguous": (
        "The cited evidence partially supports the atomic assertion or cannot be "
        "decided because context is insufficient or conflicting."
    ),
}
_REASON_CODES: dict[SemanticVerdict, tuple[SupportReasonCode, ...]] = {
    "supported": ("gold_evidence_match", "human_entailment"),
    "unsupported": (
        "irrelevant_evidence",
        "contradicted_by_evidence",
        "insufficient_evidence",
        "no_supporting_citation",
    ),
    "ambiguous": (
        "partial_support",
        "insufficient_context",
        "conflicting_evidence",
    ),
}
_PSEUDONYM = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)
_RESPONSE_FIELDS = frozenset(
    {
        "schema_version",
        "assignment_id",
        "assignment_sha256",
        "reviewer_pseudonym",
        "rubric_version",
        "calibration_set_version",
        "output_sha256",
        "evidence_sha256",
        "config_sha256",
        "semantic_verdict",
        "reason_code",
        "support_match_ids",
        "notes",
        "reviewed_at",
    }
)


class ReviewIntegrityError(ValueError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


@dataclass(frozen=True)
class FrozenRubric:
    rubric_version: str
    calibration_set_version: str
    definitions: Mapping[SemanticVerdict, str]
    reason_codes: Mapping[SemanticVerdict, tuple[SupportReasonCode, ...]]
    rubric_sha256: str


class CitedPassage(FrozenCitationModel):
    evidence_id: str
    text: str
    paper_id: str | None = None
    locator: str | None = None

    _required_non_blank = field_validator("evidence_id", "text")(_non_blank)

    @field_validator("paper_id", "locator")
    @classmethod
    def _optional_non_blank(cls, value: str | None) -> str | None:
        return _non_blank(value) if value is not None else None


class ReviewItem(FrozenCitationModel):
    schema_version: Literal["1.0"]
    case_id: str
    run_id: str
    blinded_case_id: str
    assertion_id: str
    assertion_text: str
    citation_occurrence_ids: tuple[str, ...]
    cited_passages: tuple[CitedPassage, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_calibration: StrictBool

    _required_non_blank = field_validator(
        "case_id",
        "run_id",
        "blinded_case_id",
        "assertion_id",
        "assertion_text",
    )(_non_blank)

    @field_validator("citation_occurrence_ids")
    @classmethod
    def _unique_citation_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("citation occurrence IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("citation occurrence IDs must be unique")
        return values

    @model_validator(mode="after")
    def _has_review_evidence(self) -> ReviewItem:
        if not self.cited_passages:
            raise ValueError("review item requires at least one cited passage")
        return self


class ReviewAssignment(FrozenCitationModel):
    schema_version: Literal["1.0"]
    assignment_id: str
    assignment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_pseudonym: str = Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    rubric_version: str
    calibration_set_version: str
    rubric_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_definitions: tuple[tuple[SemanticVerdict, str], ...]
    rubric_reason_codes: tuple[
        tuple[SemanticVerdict, tuple[SupportReasonCode, ...]], ...
    ]
    item: ReviewItem

    _required_non_blank = field_validator(
        "assignment_id",
        "reviewer_pseudonym",
        "rubric_version",
        "calibration_set_version",
    )(_non_blank)


class AdjudicationRecord(FrozenCitationModel):
    schema_version: Literal["1.0"]
    adjudication_id: str
    assertion_id: str
    adjudicator_pseudonym: str = Field(
        pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$"
    )
    semantic_verdict: SemanticVerdict
    reason_code: SupportReasonCode
    notes: str | None = None
    adjudicated_at: str
    original_judgments: tuple[SupportJudgment, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _required_non_blank = field_validator(
        "adjudication_id",
        "assertion_id",
        "adjudicator_pseudonym",
        "adjudicated_at",
    )(_non_blank)

    @field_validator("notes")
    @classmethod
    def _notes_non_blank(cls, value: str | None) -> str | None:
        return _non_blank(value) if value is not None else None


@dataclass(frozen=True)
class CalibrationStatistics:
    calibration_set_version: str
    rubric_version: str
    assertion_ids: tuple[str, ...]
    item_count: int
    raw_agreement: float
    cohens_kappa: float | None
    disagreement_assertion_ids: tuple[str, ...]
    unresolved_assertion_ids: tuple[str, ...]
    complete: bool


def freeze_rubric(
    rubric_version: str,
    calibration_set_version: str,
) -> FrozenRubric:
    _non_blank(rubric_version)
    _non_blank(calibration_set_version)
    payload = {
        "rubric_version": rubric_version,
        "calibration_set_version": calibration_set_version,
        "definitions": _DEFINITIONS,
        "reason_codes": _REASON_CODES,
    }
    return FrozenRubric(
        rubric_version=rubric_version,
        calibration_set_version=calibration_set_version,
        definitions=MappingProxyType(dict(_DEFINITIONS)),
        reason_codes=MappingProxyType(dict(_REASON_CODES)),
        rubric_sha256=_digest(payload),
    )


def stable_reviewer_pseudonym(reviewer_key: str, *, namespace: str) -> str:
    _non_blank(reviewer_key)
    _non_blank(namespace)
    digest = hashlib.sha256(
        f"{namespace}\0{reviewer_key}".encode("utf-8")
    ).hexdigest()
    return f"reviewer-{digest[:16]}"


def _private_assignment_payload(
    item: ReviewItem,
    reviewer_pseudonym: str,
    rubric: FrozenRubric,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "reviewer_pseudonym": reviewer_pseudonym,
        "rubric_version": rubric.rubric_version,
        "calibration_set_version": rubric.calibration_set_version,
        "rubric_sha256": rubric.rubric_sha256,
        "rubric_definitions": tuple(
            (verdict, rubric.definitions[verdict]) for verdict in _VERDICTS
        ),
        "rubric_reason_codes": tuple(
            (verdict, rubric.reason_codes[verdict]) for verdict in _VERDICTS
        ),
        "item": item.model_dump(mode="json"),
    }


def _assignment_payload_from_record(
    assignment: ReviewAssignment,
) -> dict[str, object]:
    return {
        "schema_version": assignment.schema_version,
        "reviewer_pseudonym": assignment.reviewer_pseudonym,
        "rubric_version": assignment.rubric_version,
        "calibration_set_version": assignment.calibration_set_version,
        "rubric_sha256": assignment.rubric_sha256,
        "rubric_definitions": assignment.rubric_definitions,
        "rubric_reason_codes": assignment.rubric_reason_codes,
        "item": assignment.item.model_dump(mode="json"),
    }


def _expected_assignment_hash(assignment: ReviewAssignment) -> str:
    return _digest(_assignment_payload_from_record(assignment))


def _validate_frozen_assignment(assignment: ReviewAssignment) -> None:
    expected_hash = _expected_assignment_hash(assignment)
    if assignment.assignment_sha256 != expected_hash:
        raise ReviewIntegrityError("assignment changed after freeze (post-freeze edit)")
    if assignment.assignment_id != f"assignment-{expected_hash[:20]}":
        raise ReviewIntegrityError(
            "assignment ID changed after freeze (post-freeze edit)"
        )
    rubric_payload = {
        "rubric_version": assignment.rubric_version,
        "calibration_set_version": assignment.calibration_set_version,
        "definitions": dict(assignment.rubric_definitions),
        "reason_codes": dict(assignment.rubric_reason_codes),
    }
    if assignment.rubric_sha256 != _digest(rubric_payload):
        raise ReviewIntegrityError("rubric changed after freeze (post-freeze edit)")


def assign_reviews(
    items: Sequence[ReviewItem],
    reviewers_by_assertion: Mapping[str, Sequence[str]],
    rubric: FrozenRubric,
) -> tuple[ReviewAssignment, ...]:
    item_by_id = {item.assertion_id: item for item in items}
    if len(item_by_id) != len(items):
        raise ReviewIntegrityError("review items contain duplicate assertion IDs")
    if set(reviewers_by_assertion) != set(item_by_id):
        raise ReviewIntegrityError(
            "every frozen review item must have one assignment rule"
        )

    assignments: list[ReviewAssignment] = []
    for assertion_id in sorted(item_by_id):
        item = item_by_id[assertion_id]
        reviewers = tuple(reviewers_by_assertion[assertion_id])
        if len(reviewers) != len(set(reviewers)):
            raise ReviewIntegrityError("duplicate reviewer assignment")
        expected_count = 2 if item.is_calibration else 1
        if len(reviewers) != expected_count:
            label = "calibration item" if item.is_calibration else "reported item"
            count = "two" if expected_count == 2 else "one"
            raise ReviewIntegrityError(
                f"{label} requires exactly {count} reviewer"
                f"{'s' if expected_count != 1 else ''}"
            )
        for reviewer in sorted(reviewers):
            if not _PSEUDONYM.fullmatch(reviewer):
                raise ReviewIntegrityError("reviewer must use a stable pseudonym")
            payload = _private_assignment_payload(item, reviewer, rubric)
            assignment_sha256 = _digest(payload)
            assignment_id = f"assignment-{assignment_sha256[:20]}"
            assignments.append(
                ReviewAssignment(
                    schema_version="1.0",
                    assignment_id=assignment_id,
                    assignment_sha256=assignment_sha256,
                    reviewer_pseudonym=reviewer,
                    rubric_version=rubric.rubric_version,
                    calibration_set_version=rubric.calibration_set_version,
                    rubric_sha256=rubric.rubric_sha256,
                    rubric_definitions=tuple(
                        (verdict, rubric.definitions[verdict])
                        for verdict in _VERDICTS
                    ),
                    rubric_reason_codes=tuple(
                        (verdict, rubric.reason_codes[verdict])
                        for verdict in _VERDICTS
                    ),
                    item=item,
                )
            )
    return tuple(assignments)


def _public_assignment_row(assignment: ReviewAssignment) -> dict[str, object]:
    item = assignment.item
    return {
        "schema_version": "1.0",
        "assignment_id": assignment.assignment_id,
        "assignment_sha256": assignment.assignment_sha256,
        "reviewer_pseudonym": assignment.reviewer_pseudonym,
        "rubric_version": assignment.rubric_version,
        "calibration_set_version": assignment.calibration_set_version,
        "rubric_sha256": assignment.rubric_sha256,
        "rubric": {
            "definitions": dict(assignment.rubric_definitions),
            "reason_codes": dict(assignment.rubric_reason_codes),
        },
        "blinded_case_id": item.blinded_case_id,
        "assertion_id": item.assertion_id,
        "assertion": item.assertion_text,
        "cited_passages": [
            {
                "evidence_id": passage.evidence_id,
                "text": passage.text,
                "paper_id": passage.paper_id,
                "locator": passage.locator,
            }
            for passage in item.cited_passages
        ],
        "citation_occurrence_ids": list(item.citation_occurrence_ids),
        "output_sha256": item.output_sha256,
        "evidence_sha256": item.evidence_sha256,
        "config_sha256": item.config_sha256,
        "is_calibration": item.is_calibration,
    }


def export_review_jsonl(assignments: Sequence[ReviewAssignment]) -> str:
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    for assignment in assignments:
        if assignment.assignment_id in seen:
            raise ReviewIntegrityError("duplicate review assignment")
        seen.add(assignment.assignment_id)
        _validate_frozen_assignment(assignment)
        rows.append(_public_assignment_row(assignment))
    return "".join(
        _canonical_json(row) + "\n"
        for row in sorted(rows, key=lambda row: str(row["assignment_id"]))
    )


def _contains_identity_leak(value: object, *, key: str | None = None) -> bool:
    if key is not None:
        lowered = key.lower()
        if (
            "email" in lowered
            or "identity" in lowered
            or lowered in {"name", "real_name", "reviewer_name", "username", "user_id"}
        ):
            return True
    if isinstance(value, str):
        return _EMAIL.search(value) is not None
    if isinstance(value, dict):
        return any(
            _contains_identity_leak(child, key=str(child_key))
            for child_key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_identity_leak(child) for child in value)
    return False


def _load_response_rows(content: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReviewIntegrityError(
                f"review import line {line_number} is invalid JSON"
            ) from error
        if not isinstance(value, dict):
            raise ReviewIntegrityError(
                f"review import line {line_number} must be an object"
            )
        if _contains_identity_leak(value):
            raise ReviewIntegrityError("review import contains identity leakage")
        unexpected = set(value) - _RESPONSE_FIELDS
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ReviewIntegrityError(
                f"review import contains unexpected fields: {names}"
            )
        missing = _RESPONSE_FIELDS - set(value)
        if missing:
            raise ReviewIntegrityError(
                f"review import is missing {', '.join(sorted(missing))}"
            )
        rows.append(value)
    return rows


def import_review_jsonl(
    content: str,
    assignments: Sequence[ReviewAssignment],
) -> tuple[SupportJudgment, ...]:
    assignment_by_id = {
        assignment.assignment_id: assignment for assignment in assignments
    }
    if len(assignment_by_id) != len(assignments):
        raise ReviewIntegrityError("assignment registry contains duplicate IDs")
    for assignment in assignments:
        _validate_frozen_assignment(assignment)

    judgments: list[SupportJudgment] = []
    seen: set[str] = set()
    for row in _load_response_rows(content):
        assignment_id = row["assignment_id"]
        if not isinstance(assignment_id, str) or assignment_id not in assignment_by_id:
            raise ReviewIntegrityError("review judgment is for an unassigned item")
        if assignment_id in seen:
            raise ReviewIntegrityError("review import contains duplicate assignments")
        seen.add(assignment_id)
        assignment = assignment_by_id[assignment_id]
        item = assignment.item
        if row["schema_version"] != "1.0":
            raise ReviewIntegrityError("review schema_version is not supported")
        if row["assignment_sha256"] != assignment.assignment_sha256:
            raise ReviewIntegrityError("review assignment hash changed")
        if row["reviewer_pseudonym"] != assignment.reviewer_pseudonym:
            raise ReviewIntegrityError("reviewer is not assigned to this item")
        if row["rubric_version"] != assignment.rubric_version:
            raise ReviewIntegrityError("review rubric_version changed after freeze")
        if (
            row["calibration_set_version"]
            != assignment.calibration_set_version
        ):
            raise ReviewIntegrityError(
                "review calibration_set_version changed after freeze"
            )
        for label in ("output", "evidence", "config"):
            field = f"{label}_sha256"
            if row[field] != getattr(item, field):
                raise ReviewIntegrityError(f"review {label} hash changed")
        try:
            judgment = SupportJudgment(
                schema_version="1.0",
                judgment_id=f"judgment-{_digest(row)[:20]}",
                case_id=item.case_id,
                run_id=item.run_id,
                assertion_id=item.assertion_id,
                citation_occurrence_ids=item.citation_occurrence_ids,
                support_match_ids=row["support_match_ids"],
                semantic_verdict=row["semantic_verdict"],
                reason_code=row["reason_code"],
                notes=row["notes"],
                reviewer_pseudonym=assignment.reviewer_pseudonym,
                rubric_version=assignment.rubric_version,
                calibration_set_version=assignment.calibration_set_version,
                reviewed_at=row["reviewed_at"],
                output_sha256=item.output_sha256,
                evidence_sha256=item.evidence_sha256,
                config_sha256=item.config_sha256,
            )
        except ValidationError as error:
            raise ReviewIntegrityError("review judgment is invalid") from error
        judgments.append(judgment)
    return tuple(judgments)


def calibration_statistics(
    records: Sequence[CalibrationRecord],
    *,
    expected_assertion_ids: Sequence[str],
) -> CalibrationStatistics:
    expected = tuple(expected_assertion_ids)
    if not expected or len(expected) != len(set(expected)):
        raise ReviewIntegrityError(
            "fixed calibration sample must be non-empty and unique"
        )
    by_assertion: dict[str, list[CalibrationRecord]] = {}
    for record in records:
        by_assertion.setdefault(record.assertion_id, []).append(record)
    if set(by_assertion) != set(expected):
        raise ReviewIntegrityError("records do not match the fixed calibration sample")

    rubric_versions = {record.rubric_version for record in records}
    calibration_versions = {record.calibration_set_version for record in records}
    reviewers = {record.reviewer_pseudonym for record in records}
    if len(rubric_versions) != 1 or len(calibration_versions) != 1:
        raise ReviewIntegrityError("calibration records changed frozen versions")
    if len(reviewers) != 2:
        raise ReviewIntegrityError("calibration requires exactly two stable reviewers")
    reviewer_a, reviewer_b = sorted(reviewers)

    pairs: list[tuple[SemanticVerdict, SemanticVerdict]] = []
    disagreements: list[str] = []
    unresolved: list[str] = []
    for assertion_id in expected:
        group = by_assertion[assertion_id]
        if (
            len(group) != 2
            or {record.reviewer_pseudonym for record in group}
            != {reviewer_a, reviewer_b}
        ):
            raise ReviewIntegrityError(
                "each calibration item requires exactly two stable reviewers"
            )
        if len({record.expected_verdict for record in group}) != 1:
            raise ReviewIntegrityError("frozen calibration answer changed")
        by_reviewer = {record.reviewer_pseudonym: record for record in group}
        first = by_reviewer[reviewer_a].observed_verdict
        second = by_reviewer[reviewer_b].observed_verdict
        pairs.append((first, second))
        if first != second:
            disagreements.append(assertion_id)
            decisions = {record.adjudicated_verdict for record in group}
            if None in decisions or len(decisions) != 1:
                unresolved.append(assertion_id)

    agreements = sum(first == second for first, second in pairs)
    raw_agreement = agreements / len(pairs)
    expected_agreement = sum(
        (
            sum(first == verdict for first, _ in pairs) / len(pairs)
        )
        * (
            sum(second == verdict for _, second in pairs) / len(pairs)
        )
        for verdict in _VERDICTS
    )
    kappa = (
        None
        if expected_agreement == 1.0
        else (raw_agreement - expected_agreement) / (1.0 - expected_agreement)
    )
    return CalibrationStatistics(
        calibration_set_version=next(iter(calibration_versions)),
        rubric_version=next(iter(rubric_versions)),
        assertion_ids=expected,
        item_count=len(pairs),
        raw_agreement=raw_agreement,
        cohens_kappa=kappa,
        disagreement_assertion_ids=tuple(disagreements),
        unresolved_assertion_ids=tuple(unresolved),
        complete=not unresolved,
    )


def require_scoring_ready(statistics: CalibrationStatistics) -> None:
    if not statistics.complete:
        raise ReviewIntegrityError(
            "scoring is blocked until calibration disagreements are adjudicated"
        )


def judgments_for_scoring(
    judgments: Sequence[SupportJudgment],
    assignments: Sequence[ReviewAssignment],
    statistics: CalibrationStatistics,
) -> tuple[SupportJudgment, ...]:
    require_scoring_ready(statistics)
    assignment_by_key: dict[tuple[str, str], ReviewAssignment] = {}
    for assignment in assignments:
        _validate_frozen_assignment(assignment)
        key = (assignment.item.assertion_id, assignment.reviewer_pseudonym)
        if key in assignment_by_key:
            raise ReviewIntegrityError(
                "assignment registry contains duplicate assignments"
            )
        assignment_by_key[key] = assignment

    calibration_ids = tuple(
        sorted(
            {
                assignment.item.assertion_id
                for assignment in assignments
                if assignment.item.is_calibration
            }
        )
    )
    if (
        statistics.assertion_ids != calibration_ids
        or any(
            assignment.rubric_version != statistics.rubric_version
            or assignment.calibration_set_version
            != statistics.calibration_set_version
            for assignment in assignments
        )
    ):
        raise ReviewIntegrityError(
            "calibration statistics do not match the frozen assignment set"
        )

    reported: list[SupportJudgment] = []
    seen: set[tuple[str, str]] = set()
    for judgment in judgments:
        key = (judgment.assertion_id, judgment.reviewer_pseudonym)
        assignment = assignment_by_key.get(key)
        if assignment is None:
            raise ReviewIntegrityError("judgment is for an unassigned item")
        if key in seen:
            raise ReviewIntegrityError("judgments contain duplicate assignments")
        seen.add(key)
        item = assignment.item
        if (
            judgment.case_id != item.case_id
            or judgment.run_id != item.run_id
            or judgment.rubric_version != assignment.rubric_version
            or judgment.calibration_set_version
            != assignment.calibration_set_version
            or judgment.output_sha256 != item.output_sha256
            or judgment.evidence_sha256 != item.evidence_sha256
            or judgment.config_sha256 != item.config_sha256
        ):
            raise ReviewIntegrityError("judgment changed frozen assignment authorities")
        if not item.is_calibration:
            reported.append(judgment)
    return tuple(reported)


def adjudicate(
    judgments: Sequence[SupportJudgment],
    *,
    adjudicator_pseudonym: str,
    semantic_verdict: SemanticVerdict,
    reason_code: SupportReasonCode,
    notes: str | None,
    adjudicated_at: str,
) -> AdjudicationRecord:
    if len(judgments) != 2:
        raise ReviewIntegrityError("adjudication requires two original judgments")
    if len({judgment.reviewer_pseudonym for judgment in judgments}) != 2:
        raise ReviewIntegrityError("adjudication requires distinct reviewers")
    if len({judgment.semantic_verdict for judgment in judgments}) == 1:
        raise ReviewIntegrityError("adjudication requires an actual disagreement")
    authority = {
        (
            judgment.case_id,
            judgment.run_id,
            judgment.assertion_id,
            judgment.rubric_version,
            judgment.calibration_set_version,
            judgment.output_sha256,
            judgment.evidence_sha256,
            judgment.config_sha256,
        )
        for judgment in judgments
    }
    if len(authority) != 1:
        raise ReviewIntegrityError("original judgments do not share frozen authorities")
    if not _PSEUDONYM.fullmatch(adjudicator_pseudonym):
        raise ReviewIntegrityError("adjudicator must use a stable pseudonym")

    originals = tuple(judgments)
    first = originals[0]
    payload = {
        "original_judgment_ids": sorted(
            item.judgment_id for item in originals
        ),
        "adjudicator_pseudonym": adjudicator_pseudonym,
        "semantic_verdict": semantic_verdict,
        "reason_code": reason_code,
        "notes": notes,
        "adjudicated_at": adjudicated_at,
    }
    try:
        candidate = SupportJudgment(
            **{
                **first.model_dump(),
                "judgment_id": "adjudication-validation",
                "semantic_verdict": semantic_verdict,
                "reason_code": reason_code,
                "notes": notes,
                "reviewer_pseudonym": adjudicator_pseudonym,
                "reviewed_at": adjudicated_at,
                "support_match_ids": (),
            }
        )
    except ValidationError as error:
        raise ReviewIntegrityError("adjudication verdict is invalid") from error
    return AdjudicationRecord(
        schema_version="1.0",
        adjudication_id=f"adjudication-{_digest(payload)[:20]}",
        assertion_id=first.assertion_id,
        adjudicator_pseudonym=adjudicator_pseudonym,
        semantic_verdict=candidate.semantic_verdict,
        reason_code=candidate.reason_code,
        notes=candidate.notes,
        adjudicated_at=adjudicated_at,
        original_judgments=originals,
        output_sha256=first.output_sha256,
        evidence_sha256=first.evidence_sha256,
        config_sha256=first.config_sha256,
    )


__all__ = [
    "AdjudicationRecord",
    "CalibrationStatistics",
    "CitedPassage",
    "FrozenRubric",
    "ReviewAssignment",
    "ReviewIntegrityError",
    "ReviewItem",
    "adjudicate",
    "assign_reviews",
    "calibration_statistics",
    "export_review_jsonl",
    "freeze_rubric",
    "import_review_jsonl",
    "judgments_for_scoring",
    "require_scoring_ready",
    "stable_reviewer_pseudonym",
]
