from __future__ import annotations

import json

import pytest

from paper_agent.eval.citation_baseline.contracts import CalibrationRecord
from paper_agent.eval.citation_baseline.review import (
    CitedPassage,
    ReviewIntegrityError,
    ReviewItem,
    adjudicate,
    assign_reviews,
    calibration_statistics,
    export_response_template_jsonl,
    export_review_jsonl,
    freeze_rubric,
    import_review_jsonl,
    judgments_for_scoring,
    merge_review_judgments,
    require_scoring_ready,
    stable_reviewer_pseudonym,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _item(
    assertion_id: str = "assertion-1",
    *,
    calibration: bool = False,
) -> ReviewItem:
    return ReviewItem(
        schema_version="1.0",
        case_id="private-case-1",
        run_id="run-1",
        blinded_case_id="blind-001",
        assertion_id=assertion_id,
        assertion_text="The method improves retrieval quality.",
        citation_occurrence_ids=("citation-1",),
        cited_passages=(
            CitedPassage(
                evidence_id="run-1:evidence-1",
                text="Retrieval quality improved by five points.",
                paper_id="paper-1",
                locator="page 3",
            ),
        ),
        output_sha256=SHA_A,
        evidence_sha256=SHA_B,
        config_sha256=SHA_C,
        is_calibration=calibration,
    )


def _response(assignment: object, **updates: object) -> dict[str, object]:
    response: dict[str, object] = {
        "schema_version": "1.0",
        "assignment_id": assignment.assignment_id,
        "assignment_sha256": assignment.assignment_sha256,
        "reviewer_pseudonym": assignment.reviewer_pseudonym,
        "rubric_version": assignment.rubric_version,
        "calibration_set_version": assignment.calibration_set_version,
        "output_sha256": assignment.item.output_sha256,
        "evidence_sha256": assignment.item.evidence_sha256,
        "config_sha256": assignment.item.config_sha256,
        "semantic_verdict": "unsupported",
        "reason_code": "insufficient_evidence",
        "support_match_ids": [],
        "notes": None,
        "reviewed_at": "2026-07-26T09:00:00Z",
    }
    response.update(updates)
    return response


def _jsonl(*rows: dict[str, object]) -> str:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def _calibration(
    assertion_id: str,
    reviewer: str,
    observed: str,
    *,
    adjudicated: str | None = None,
) -> CalibrationRecord:
    return CalibrationRecord(
        schema_version="1.0",
        calibration_id=f"{assertion_id}-{reviewer}",
        calibration_set_version="calibration-v1",
        rubric_version="citation-support-v1",
        assertion_id=assertion_id,
        reviewer_pseudonym=reviewer,
        expected_verdict="supported",
        observed_verdict=observed,
        adjudicated_verdict=adjudicated,
    )


def test_rubric_is_frozen_and_assignments_enforce_double_calibration() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")

    assert rubric.definitions["ambiguous"].startswith("The cited evidence")
    assert rubric.reason_codes["supported"] == (
        "gold_evidence_match",
        "human_entailment",
    )
    with pytest.raises(TypeError):
        rubric.definitions["supported"] = "changed"

    calibration = _item(calibration=True)
    reported = _item("assertion-2")
    alpha = stable_reviewer_pseudonym("reviewer-a", namespace="study-1")
    beta = stable_reviewer_pseudonym("reviewer-b", namespace="study-1")
    assignments = assign_reviews(
        (calibration, reported),
        {
            "assertion-1": (alpha, beta),
            "assertion-2": (alpha,),
        },
        rubric,
    )

    assert len(assignments) == 3
    assert len({item.assignment_id for item in assignments}) == 3
    with pytest.raises(ReviewIntegrityError, match="exactly two"):
        assign_reviews(
            (calibration,),
            {"assertion-1": (alpha,)},
            rubric,
        )
    with pytest.raises(ReviewIntegrityError, match="duplicate"):
        assign_reviews(
            (calibration,),
            {"assertion-1": (alpha, alpha)},
            rubric,
        )


def test_calibration_reports_agreement_kappa_and_blocks_unresolved_scoring() -> None:
    records = (
        _calibration("a-1", "reviewer-alpha", "supported"),
        _calibration("a-1", "reviewer-beta", "supported"),
        _calibration(
            "a-2",
            "reviewer-alpha",
            "supported",
            adjudicated="supported",
        ),
        _calibration(
            "a-2",
            "reviewer-beta",
            "unsupported",
            adjudicated="supported",
        ),
        _calibration("a-3", "reviewer-alpha", "unsupported"),
        _calibration("a-3", "reviewer-beta", "unsupported"),
        _calibration("a-4", "reviewer-alpha", "unsupported"),
        _calibration("a-4", "reviewer-beta", "supported"),
    )

    unresolved = calibration_statistics(
        records,
        expected_assertion_ids=("a-1", "a-2", "a-3", "a-4"),
    )
    assert unresolved.raw_agreement == 0.5
    assert unresolved.cohens_kappa == 0.0
    assert unresolved.disagreement_assertion_ids == ("a-2", "a-4")
    assert unresolved.unresolved_assertion_ids == ("a-4",)
    with pytest.raises(ReviewIntegrityError, match="adjudicated"):
        require_scoring_ready(unresolved)

    completed_records = tuple(
        record.model_copy(update={"adjudicated_verdict": "supported"})
        if record.assertion_id == "a-4"
        else record
        for record in records
    )
    complete = calibration_statistics(
        completed_records,
        expected_assertion_ids=("a-1", "a-2", "a-3", "a-4"),
    )
    require_scoring_ready(complete)
    assert complete.complete is True


def test_calibration_requires_fixed_complete_two_reviewer_sample() -> None:
    records = (
        _calibration("a-1", "reviewer-alpha", "supported"),
        _calibration("a-1", "reviewer-beta", "supported"),
    )

    with pytest.raises(ReviewIntegrityError, match="fixed calibration sample"):
        calibration_statistics(
            records,
            expected_assertion_ids=("a-1", "a-2"),
        )
    with pytest.raises(ReviewIntegrityError, match="exactly two stable reviewers"):
        calibration_statistics(
            records
            + (
                _calibration("a-2", "reviewer-alpha", "supported"),
                _calibration("a-2", "reviewer-gamma", "supported"),
            ),
            expected_assertion_ids=("a-1", "a-2"),
        )


def test_scoring_projection_excludes_calibration_judgments() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    alpha = stable_reviewer_pseudonym("reviewer-a", namespace="study-1")
    beta = stable_reviewer_pseudonym("reviewer-b", namespace="study-1")
    assignments = assign_reviews(
        (_item(calibration=True), _item("assertion-2")),
        {
            "assertion-1": (alpha, beta),
            "assertion-2": (alpha,),
        },
        rubric,
    )
    judgments = import_review_jsonl(
        _jsonl(*(_response(assignment) for assignment in assignments)),
        assignments,
    )
    incomplete = calibration_statistics(
        (
            _calibration("assertion-1", alpha, "supported"),
            _calibration("assertion-1", beta, "unsupported"),
        ),
        expected_assertion_ids=("assertion-1",),
    )
    with pytest.raises(ReviewIntegrityError, match="adjudicated"):
        judgments_for_scoring(judgments, assignments, incomplete)

    complete_records = (
        _calibration(
            "assertion-1",
            alpha,
            "supported",
            adjudicated="supported",
        ),
        _calibration(
            "assertion-1",
            beta,
            "unsupported",
            adjudicated="supported",
        ),
    )
    complete = calibration_statistics(
        complete_records,
        expected_assertion_ids=("assertion-1",),
    )

    projected = judgments_for_scoring(judgments, assignments, complete)

    assert tuple(item.assertion_id for item in projected) == ("assertion-2",)


def test_kappa_is_undefined_when_expected_agreement_is_one() -> None:
    statistics = calibration_statistics(
        (
            _calibration("a-1", "reviewer-alpha", "supported"),
            _calibration("a-1", "reviewer-beta", "supported"),
            _calibration("a-2", "reviewer-alpha", "supported"),
            _calibration("a-2", "reviewer-beta", "supported"),
        ),
        expected_assertion_ids=("a-1", "a-2"),
    )

    assert statistics.raw_agreement == 1.0
    assert statistics.cohens_kappa is None


def test_export_is_blinded_deterministic_and_bound_to_frozen_payload() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    pseudonym = stable_reviewer_pseudonym(
        "alice@example.com",
        namespace="study-1",
    )
    assignment = assign_reviews(
        (_item(),),
        {"assertion-1": (pseudonym,)},
        rubric,
    )[0]

    first = export_review_jsonl((assignment,))
    second = export_review_jsonl((assignment,))
    row = json.loads(first)

    assert first == second
    assert row["blinded_case_id"] == "blind-001"
    assert row["assertion"] == "The method improves retrieval quality."
    assert row["cited_passages"][0]["evidence_id"] == "run-1:evidence-1"
    assert row["cited_passages"][0]["text"].startswith("Retrieval quality")
    assert row["assignment_sha256"] == assignment.assignment_sha256
    assert "private-case-1" not in first
    assert "alice@example.com" not in first


def test_response_template_is_deterministic_blinded_and_import_shaped() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    pseudonym = stable_reviewer_pseudonym("reviewer-a", namespace="study-1")
    assignment = assign_reviews(
        (_item(),),
        {"assertion-1": (pseudonym,)},
        rubric,
    )[0]

    first = export_response_template_jsonl((assignment,))
    second = export_response_template_jsonl((assignment,))
    row = json.loads(first)

    assert first == second
    assert set(row) == {
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
    assert row["semantic_verdict"] == "__REQUIRED__"
    assert "private-case-1" not in first
    with pytest.raises(ReviewIntegrityError, match="invalid"):
        import_review_jsonl(first, (assignment,))


def test_merge_review_judgments_resumes_without_replacement() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    pseudonym = stable_reviewer_pseudonym("reviewer-a", namespace="study-1")
    assignments = assign_reviews(
        (_item("assertion-1"), _item("assertion-2")),
        {
            "assertion-1": (pseudonym,),
            "assertion-2": (pseudonym,),
        },
        rubric,
    )
    first = import_review_jsonl(_jsonl(_response(assignments[0])), assignments)
    second = import_review_jsonl(_jsonl(_response(assignments[1])), assignments)

    merged = merge_review_judgments(first, second, assignments)

    assert tuple(item.assertion_id for item in merged) == (
        "assertion-1",
        "assertion-2",
    )
    with pytest.raises(ReviewIntegrityError, match="duplicate"):
        merge_review_judgments(first, first, assignments)


def test_import_accepts_only_assigned_hash_bound_blinded_reviews() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    pseudonym = stable_reviewer_pseudonym("reviewer-a", namespace="study-1")
    assignment = assign_reviews(
        (_item(),),
        {"assertion-1": (pseudonym,)},
        rubric,
    )[0]

    judgment = import_review_jsonl(
        _jsonl(_response(assignment)),
        (assignment,),
    )[0]

    assert judgment.case_id == "private-case-1"
    assert judgment.reviewer_pseudonym == pseudonym
    assert judgment.output_sha256 == SHA_A
    assert judgment.evidence_sha256 == SHA_B
    assert judgment.config_sha256 == SHA_C

    with pytest.raises(ReviewIntegrityError, match="assignment hash"):
        import_review_jsonl(
            _jsonl(_response(assignment, assignment_sha256="f" * 64)),
            (assignment,),
        )
    with pytest.raises(ReviewIntegrityError, match="evidence hash"):
        import_review_jsonl(
            _jsonl(_response(assignment, evidence_sha256="f" * 64)),
            (assignment,),
        )
    with pytest.raises(ReviewIntegrityError, match="unassigned"):
        import_review_jsonl(
            _jsonl(_response(assignment, assignment_id="unknown")),
            (assignment,),
        )
    with pytest.raises(ReviewIntegrityError, match="identity leakage"):
        import_review_jsonl(
            _jsonl(
                _response(
                    assignment,
                    reviewer_email="alice@example.com",
                )
            ),
            (assignment,),
        )
    with pytest.raises(ReviewIntegrityError, match="schema_version"):
        import_review_jsonl(
            _jsonl(_response(assignment, schema_version="2.0")),
            (assignment,),
        )


def test_import_rejects_duplicate_missing_version_and_post_freeze_changes() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    pseudonym = stable_reviewer_pseudonym("reviewer-a", namespace="study-1")
    assignment = assign_reviews(
        (_item(),),
        {"assertion-1": (pseudonym,)},
        rubric,
    )[0]
    row = _response(assignment)

    with pytest.raises(ReviewIntegrityError, match="duplicate"):
        import_review_jsonl(_jsonl(row, row), (assignment,))

    missing_version = dict(row)
    del missing_version["rubric_version"]
    with pytest.raises(ReviewIntegrityError, match="rubric_version"):
        import_review_jsonl(_jsonl(missing_version), (assignment,))

    changed = assignment.model_copy(
        update={"item": assignment.item.model_copy(update={"assertion_text": "edited"})}
    )
    with pytest.raises(ReviewIntegrityError, match="post-freeze"):
        export_review_jsonl((changed,))


def test_adjudication_preserves_original_judgments_and_gates_agreement() -> None:
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    alpha = stable_reviewer_pseudonym("reviewer-a", namespace="study-1")
    beta = stable_reviewer_pseudonym("reviewer-b", namespace="study-1")
    assignments = assign_reviews(
        (_item(calibration=True),),
        {"assertion-1": (alpha, beta)},
        rubric,
    )
    judgments = import_review_jsonl(
        _jsonl(
            _response(
                assignments[0],
                semantic_verdict="supported",
                reason_code="human_entailment",
            ),
            _response(assignments[1]),
        ),
        assignments,
    )

    record = adjudicate(
        judgments,
        adjudicator_pseudonym=stable_reviewer_pseudonym(
            "adjudicator",
            namespace="study-1",
        ),
        semantic_verdict="supported",
        reason_code="human_entailment",
        notes="The passage directly entails the assertion.",
        adjudicated_at="2026-07-26T10:00:00Z",
    )

    assert record.original_judgments == judgments
    assert record.semantic_verdict == "supported"
    assert record.original_judgments[1].semantic_verdict == "unsupported"
    with pytest.raises(ReviewIntegrityError, match="disagreement"):
        adjudicate(
            (
                judgments[0],
                judgments[1].model_copy(
                    update={
                        "semantic_verdict": "supported",
                        "reason_code": "human_entailment",
                    }
                ),
            ),
            adjudicator_pseudonym="reviewer-adjudicator",
            semantic_verdict="supported",
            reason_code="human_entailment",
            notes=None,
            adjudicated_at="2026-07-26T10:00:00Z",
        )
