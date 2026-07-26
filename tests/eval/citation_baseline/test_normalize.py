import pytest

from paper_agent.eval.citation_baseline.normalize import normalize_checked_output
from paper_agent.schemas import Evidence, ReportClaim
from paper_agent.synthesis.models import CheckedClaim, CheckedSurveyReport


def _evidence(evidence_id: str, *, paper_id: str = "p1") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id=paper_id,
        chunk_id=f"{paper_id}:chunk:001",
        section="Results",
        page=2,
        claim_type="retrieved",
        quote="Source text",
        relevance_score=0.9,
    )


def _claim(text: str, *evidence_ids: str) -> CheckedClaim:
    return CheckedClaim(
        text=text,
        evidence_ids=list(evidence_ids),
        support_status="supported" if evidence_ids else "unsupported",
    )


def _report(**overrides: list[CheckedClaim]) -> CheckedSurveyReport:
    values = {
        "question": "A heading, not an assertion",
        "tldr_claims": [],
        "method_taxonomy": [],
        "comparisons": [],
        "key_findings": [],
        "limitations": [],
        "open_questions": [],
    }
    values.update(overrides)
    return CheckedSurveyReport(**values)


def test_normalizes_one_claim_and_citation_without_changing_text():
    result = normalize_checked_output(
        _report(tldr_claims=[_claim("Exact assertion.", "run-1:ev-1")]),
        [_evidence("run-1:ev-1")],
        case_id="case-1",
        run_id="run-1",
    )

    assert [item.model_dump() for item in result.assertions] == [
        {
            "schema_version": "1.0",
            "assertion_id": "case-1:assertion:0001",
            "case_id": "case-1",
            "run_id": "run-1",
            "text": "Exact assertion.",
            "paper_id": None,
            "source_section": "tldr_claims",
            "start_char": 0,
            "end_char": 16,
        }
    ]
    assert [item.model_dump() for item in result.citation_occurrences] == [
        {
            "schema_version": "1.0",
            "occurrence_id": "case-1:citation:0001",
            "assertion_id": "case-1:assertion:0001",
            "evidence_id": "run-1:ev-1",
            "source_section": "tldr_claims",
            "start_char": 18,
            "end_char": 28,
            "structurally_valid": True,
            "structural_reason_code": None,
        }
    ]


def test_preserves_order_repeated_citations_and_uncited_assertions():
    report = _report(
        method_taxonomy=[
            _claim("First", "run-1:ev-2", "run-1:ev-1", "run-1:ev-2"),
            _claim("Uncited"),
            _claim("Third", "run-1:ev-1"),
        ]
    )

    first = normalize_checked_output(
        report,
        [_evidence("run-1:ev-1"), _evidence("run-1:ev-2")],
        case_id="case-1",
        run_id="run-1",
    )
    second = normalize_checked_output(
        report,
        [_evidence("run-1:ev-1"), _evidence("run-1:ev-2")],
        case_id="case-1",
        run_id="run-1",
    )

    assert first == second
    assert [item.text for item in first.assertions] == ["First", "Uncited", "Third"]
    assert [item.start_char for item in first.assertions] == [0, 45, 53]
    assert [item.evidence_id for item in first.citation_occurrences] == [
        "run-1:ev-2",
        "run-1:ev-1",
        "run-1:ev-2",
        "run-1:ev-1",
    ]
    assert [item.start_char for item in first.citation_occurrences] == [7, 20, 33, 60]


def test_uses_section_order_and_does_not_turn_headings_into_assertions():
    result = normalize_checked_output(
        _report(
            method_taxonomy=[_claim("- Literal list item")],
            comparisons=[_claim("Comparison")],
            limitations=[_claim("Limitation")],
        ),
        [],
        case_id="case-1",
        run_id="run-1",
    )

    assert [item.text for item in result.assertions] == [
        "- Literal list item",
        "Comparison",
        "Limitation",
    ]
    assert [item.source_section for item in result.assertions] == [
        "method_taxonomy",
        "comparisons",
        "limitations",
    ]


def test_normalizes_checked_legacy_claims_as_one_ordered_section():
    result = normalize_checked_output(
        [
            ReportClaim(
                claim="Legacy one",
                evidence_ids=["run-1:ev-1"],
                support_status="supported",
            ),
            ReportClaim(
                claim="Legacy two",
                evidence_ids=[],
                support_status="unsupported",
            ),
        ],
        [_evidence("run-1:ev-1")],
        case_id="case-1",
        run_id="run-1",
    )

    assert [item.text for item in result.assertions] == ["Legacy one", "Legacy two"]
    assert {item.source_section for item in result.assertions} == {"claims"}


def test_rejects_duplicate_evidence_ids():
    duplicate = _evidence("run-1:ev-1")

    with pytest.raises(ValueError, match="duplicate evidence_id"):
        normalize_checked_output(
            _report(),
            [duplicate, duplicate.model_copy()],
            case_id="case-1",
            run_id="run-1",
        )


def test_marks_malformed_foreign_and_unknown_citations_invalid():
    result = normalize_checked_output(
        _report(
            open_questions=[
                _claim(
                    "Question",
                    "malformed",
                    "run-2:ev-1",
                    "run-1:missing",
                )
            ]
        ),
        [_evidence("run-1:ev-1")],
        case_id="case-1",
        run_id="run-1",
    )

    assert [
        (item.structurally_valid, item.structural_reason_code)
        for item in result.citation_occurrences
    ] == [
        (False, "malformed_evidence_id"),
        (False, "foreign_run_evidence_id"),
        (False, "unknown_evidence_id"),
    ]


@pytest.mark.parametrize(
    "output",
    [
        "# Heading\n\n- An unstructured assertion [run-1:ev-1]",
        {"claims": [{"text": "An assertion"}]},
        [object()],
    ],
)
def test_rejects_unstructured_output_shapes(output: object):
    with pytest.raises(ValueError, match="unsupported_output_shape"):
        normalize_checked_output(
            output,
            [_evidence("run-1:ev-1")],
            case_id="case-1",
            run_id="run-1",
        )
