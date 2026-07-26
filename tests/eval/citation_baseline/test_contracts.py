from __future__ import annotations

import pytest
from pydantic import ValidationError

from paper_agent.eval.citation_baseline.contracts import (
    AtomicAssertion,
    CalibrationRecord,
    CitationCaseResult,
    CitationOccurrence,
    EvidenceMatch,
    SupportJudgment,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _assertion() -> AtomicAssertion:
    return AtomicAssertion(
        schema_version="1.0",
        assertion_id="assertion-1",
        case_id="case-1",
        run_id="run-1",
        text="The method improves retrieval quality.",
        paper_id="paper-1",
        source_section="findings",
        start_char=0,
        end_char=38,
    )


def _occurrence() -> CitationOccurrence:
    return CitationOccurrence(
        schema_version="1.0",
        occurrence_id="citation-1",
        assertion_id="assertion-1",
        evidence_id="run-1:evidence-1",
        source_section="findings",
        start_char=39,
        end_char=63,
        structurally_valid=True,
    )


def _match() -> EvidenceMatch:
    return EvidenceMatch(
        schema_version="1.0",
        match_id="match-1",
        assertion_id="assertion-1",
        citation_occurrence_id="citation-1",
        actual_evidence_id="run-1:evidence-1",
        gold_evidence_id="gold-1",
        strategy="exact_locator",
        score=1.0,
        supports_assertion=True,
        actual_evidence_sha256=SHA_B,
        gold_evidence_sha256=SHA_C,
    )


def _judgment(**updates: object) -> SupportJudgment:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "judgment_id": "judgment-1",
        "case_id": "case-1",
        "run_id": "run-1",
        "assertion_id": "assertion-1",
        "citation_occurrence_ids": ["citation-1"],
        "support_match_ids": ["match-1"],
        "semantic_verdict": "supported",
        "reason_code": "gold_evidence_match",
        "notes": None,
        "reviewer_pseudonym": "reviewer-alpha",
        "rubric_version": "citation-support-v1",
        "calibration_set_version": "calibration-v1",
        "reviewed_at": "2026-07-26T09:00:00Z",
        "output_sha256": SHA_A,
        "evidence_sha256": SHA_B,
        "config_sha256": SHA_C,
    }
    payload.update(updates)
    return SupportJudgment.model_validate(payload)


def _calibration() -> CalibrationRecord:
    return CalibrationRecord(
        schema_version="1.0",
        calibration_id="calibration-1",
        calibration_set_version="calibration-v1",
        rubric_version="citation-support-v1",
        assertion_id="assertion-1",
        reviewer_pseudonym="reviewer-alpha",
        expected_verdict="supported",
        observed_verdict="supported",
        adjudicated_verdict=None,
    )


def _case_result(**updates: object) -> CitationCaseResult:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "case_id": "case-1",
        "run_id": "run-1",
        "output_sha256": SHA_A,
        "evidence_sha256": SHA_B,
        "config_sha256": SHA_C,
        "assertions": [_assertion()],
        "citation_occurrences": [_occurrence()],
        "evidence_matches": [_match()],
        "judgments": [_judgment()],
        "calibration_records": [_calibration()],
    }
    payload.update(updates)
    return CitationCaseResult.model_validate(payload)


def test_contracts_are_strict_immutable_and_preserve_judgment_authorities() -> None:
    result = _case_result()

    assert isinstance(result.assertions, tuple)
    assert (
        result.judgments[0].output_sha256,
        result.judgments[0].evidence_sha256,
        result.judgments[0].config_sha256,
    ) == (SHA_A, SHA_B, SHA_C)
    with pytest.raises(ValidationError):
        result.case_id = "changed"
    with pytest.raises(ValidationError):
        result.judgments[0].semantic_verdict = "unsupported"
    with pytest.raises(AttributeError):
        result.assertions.append(_assertion())
    with pytest.raises(ValidationError):
        SupportJudgment.model_validate(
            {
                **_judgment().model_dump(),
                "reviewer_email": "person@example.com",
            }
        )


@pytest.mark.parametrize(
    ("model", "payload", "field"),
    [
        (AtomicAssertion, _assertion().model_dump(), "assertion_id"),
        (CitationOccurrence, _occurrence().model_dump(), "occurrence_id"),
        (EvidenceMatch, _match().model_dump(), "match_id"),
        (SupportJudgment, _judgment().model_dump(), "judgment_id"),
        (CalibrationRecord, _calibration().model_dump(), "calibration_set_version"),
        (CitationCaseResult, _case_result().model_dump(), "run_id"),
    ],
)
def test_contracts_reject_blank_identifiers(
    model: type, payload: dict[str, object], field: str
) -> None:
    payload[field] = " "

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    ["output_sha256", "evidence_sha256", "config_sha256"],
)
def test_judgments_reject_missing_or_invalid_authority_hashes(field: str) -> None:
    payload = _judgment().model_dump()
    payload[field] = "not-a-sha256"
    with pytest.raises(ValidationError):
        SupportJudgment.model_validate(payload)

    del payload[field]
    with pytest.raises(ValidationError):
        SupportJudgment.model_validate(payload)


def test_case_result_rejects_duplicate_and_dangling_references() -> None:
    duplicate = _assertion().model_copy(update={"text": "Different text"})
    with pytest.raises(ValidationError, match="assertion IDs must be unique"):
        _case_result(assertions=[_assertion(), duplicate])

    dangling = _occurrence().model_copy(update={"assertion_id": "missing"})
    with pytest.raises(ValidationError, match="citation occurrence assertion"):
        _case_result(citation_occurrences=[dangling])

    dangling_match = _match().model_copy(
        update={"citation_occurrence_id": "missing"}
    )
    with pytest.raises(ValidationError, match="evidence match citation occurrence"):
        _case_result(evidence_matches=[dangling_match])


def test_case_result_rejects_cross_assertion_support_references() -> None:
    other_assertion = _assertion().model_copy(
        update={
            "assertion_id": "assertion-2",
            "text": "A second assertion.",
            "start_char": 64,
            "end_char": 83,
        }
    )
    cross_assertion_match = _match().model_copy(
        update={"assertion_id": "assertion-2"}
    )
    with pytest.raises(ValidationError, match="same assertion"):
        _case_result(
            assertions=[_assertion(), other_assertion],
            evidence_matches=[cross_assertion_match],
        )

    non_supporting_match = _match().model_copy(update={"supports_assertion": False})
    with pytest.raises(ValidationError, match="supporting match"):
        _case_result(evidence_matches=[non_supporting_match])


@pytest.mark.parametrize(
    ("verdict", "reason_code", "support_match_ids", "notes"),
    [
        ("unknown", "human_entailment", [], None),
        ("supported", "irrelevant_evidence", [], None),
        ("unsupported", "gold_evidence_match", [], None),
        ("unsupported", "insufficient_evidence", ["match-1"], None),
        ("ambiguous", "partial_support", [], None),
        ("ambiguous", "insufficient_context", [], " "),
    ],
)
def test_judgment_rejects_invalid_verdict_states(
    verdict: str,
    reason_code: str,
    support_match_ids: list[str],
    notes: str | None,
) -> None:
    with pytest.raises(ValidationError):
        _judgment(
            semantic_verdict=verdict,
            reason_code=reason_code,
            support_match_ids=support_match_ids,
            notes=notes,
        )


def test_case_result_keeps_structure_separate_from_semantic_support() -> None:
    occurrence = _occurrence().model_copy(
        update={
            "structurally_valid": False,
            "structural_reason_code": "foreign_run_evidence",
        }
    )
    judgment = _judgment(
        semantic_verdict="ambiguous",
        reason_code="insufficient_context",
        support_match_ids=[],
        notes="The cited passage cannot be resolved for semantic review.",
    )

    result = _case_result(
        citation_occurrences=[occurrence],
        evidence_matches=[],
        judgments=[judgment],
    )

    assert result.citation_occurrences[0].structurally_valid is False
    assert result.judgments[0].semantic_verdict == "ambiguous"
