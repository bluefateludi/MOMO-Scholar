import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from paper_agent.eval.runner import evaluate_case, evaluate_fixture
from paper_agent.schemas import Evidence, ReportClaim


def _evidence(evidence_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id="paper-1",
        chunk_id="paper-1:chunk:001",
        claim_type="retrieved",
        quote="Source text",
        relevance_score=0.9,
    )


def _write_fixture(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "eval.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _raw_case() -> dict[str, object]:
    return {
        "case_id": "case-1",
        "expected_paper_ids": ["paper-1"],
        "actual_paper_ids": ["paper-1"],
        "claims": [],
        "evidence": [],
    }


def test_evaluate_case_returns_exact_metric_dictionary() -> None:
    claims = [
        ReportClaim(
            claim="Supported claim",
            evidence_ids=["ev-1", "missing"],
            support_status="supported",
        ),
        ReportClaim(
            claim="Unsupported claim",
            evidence_ids=[],
            support_status="unsupported",
        ),
    ]

    result = evaluate_case(
        expected_paper_ids=["paper-1", "paper-2"],
        actual_paper_ids=["paper-1", "paper-3"],
        claims=claims,
        evidence=[_evidence("ev-1")],
    )

    assert result == {
        "retrieval_hit_rate": 0.5,
        "evidence_coverage": 0.5,
        "unsupported_claim_rate": 0.5,
        "citation_validity": 0.5,
    }


def test_evaluate_case_rejects_duplicate_evidence_ids() -> None:
    duplicate = _evidence("ev-1")

    with pytest.raises(ValueError, match="duplicate evidence_id: ev-1"):
        evaluate_case(
            expected_paper_ids=[],
            actual_paper_ids=[],
            claims=[],
            evidence=[duplicate, duplicate.model_copy()],
        )


def test_evaluate_fixture_returns_per_case_metrics() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "eval_cases.json"

    result = evaluate_fixture(fixture_path)

    assert result["cases"] == [
        {
            "case_id": "partial-match",
            "metrics": {
                "retrieval_hit_rate": 0.5,
                "evidence_coverage": 0.5,
                "unsupported_claim_rate": 0.5,
                "citation_validity": 0.5,
            },
        }
    ]
    assert result["summary"] == {
        "case_count": 1,
        "retrieval_hit_rate": 0.5,
        "evidence_coverage": 0.5,
        "unsupported_claim_rate": 0.5,
        "citation_validity": 0.5,
    }


def test_evaluate_fixture_returns_zero_summary_for_empty_fixture(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "empty.json"
    fixture_path.write_text("[]", encoding="utf-8")

    assert evaluate_fixture(fixture_path) == {
        "cases": [],
        "summary": {
            "case_count": 0,
            "retrieval_hit_rate": 0.0,
            "evidence_coverage": 0.0,
            "unsupported_claim_rate": 0.0,
            "citation_validity": 0.0,
        },
    }


def test_evaluate_fixture_is_deterministic_and_accepts_string_path() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "eval_cases.json"

    first = evaluate_fixture(fixture_path)
    second = evaluate_fixture(str(fixture_path))

    assert first == second


def test_evaluate_fixture_rejects_non_list_top_level(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path, {"case_id": "case-1"})

    with pytest.raises(ValueError, match="fixture top level must be a list"):
        evaluate_fixture(path)


@pytest.mark.parametrize(
    "missing_field",
    ["case_id", "expected_paper_ids", "actual_paper_ids", "claims", "evidence"],
)
def test_evaluate_fixture_rejects_missing_required_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    raw_case = _raw_case()
    raw_case.pop(missing_field)

    with pytest.raises(ValueError, match=rf"case 0.*{missing_field}"):
        evaluate_fixture(_write_fixture(tmp_path, [raw_case]))


@pytest.mark.parametrize("case_id", ["", "   ", 7, None])
def test_evaluate_fixture_rejects_invalid_case_id(
    tmp_path: Path,
    case_id: object,
) -> None:
    raw_case = _raw_case()
    raw_case["case_id"] = case_id

    with pytest.raises(ValueError, match=r"case 0.*case_id"):
        evaluate_fixture(_write_fixture(tmp_path, [raw_case]))


@pytest.mark.parametrize("field", ["expected_paper_ids", "actual_paper_ids"])
@pytest.mark.parametrize("invalid_value", ["paper-1", ["paper-1", 2]])
def test_evaluate_fixture_requires_lists_of_paper_id_strings(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    raw_case = _raw_case()
    raw_case[field] = invalid_value

    with pytest.raises(ValueError, match=rf"case case-1.*{field}"):
        evaluate_fixture(_write_fixture(tmp_path, [raw_case]))


@pytest.mark.parametrize("field", ["claims", "evidence"])
def test_evaluate_fixture_requires_claims_and_evidence_lists(
    tmp_path: Path,
    field: str,
) -> None:
    raw_case = _raw_case()
    raw_case[field] = {}

    with pytest.raises(ValueError, match=rf"case case-1.*{field}"):
        evaluate_fixture(_write_fixture(tmp_path, [raw_case]))


def test_evaluate_fixture_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    first = _raw_case()
    second = _raw_case()

    with pytest.raises(ValueError, match=r"duplicate case_id: case-1"):
        evaluate_fixture(_write_fixture(tmp_path, [first, second]))


def test_evaluate_fixture_reports_claim_validation_path_and_preserves_cause(
    tmp_path: Path,
) -> None:
    raw_case = _raw_case()
    raw_case["claims"] = [
        {
            "claim": "Invalid status",
            "evidence_ids": [],
            "support_status": "unknown",
        }
    ]

    with pytest.raises(
        ValueError,
        match=r"case case-1: claims\[0\]\.support_status",
    ) as exc_info:
        evaluate_fixture(_write_fixture(tmp_path, [raw_case]))

    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_evaluate_fixture_reports_evidence_validation_path_and_preserves_cause(
    tmp_path: Path,
) -> None:
    raw_case = _raw_case()
    raw_case["evidence"] = [
        {
            "evidence_id": "ev-1",
            "paper_id": "paper-1",
            "chunk_id": "paper-1:chunk:001",
            "claim_type": "retrieved",
            "quote": "Source text",
            "relevance_score": 2.0,
        }
    ]

    with pytest.raises(
        ValueError,
        match=r"case case-1: evidence\[0\]\.relevance_score",
    ) as exc_info:
        evaluate_fixture(_write_fixture(tmp_path, [raw_case]))

    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_evaluate_fixture_reports_duplicate_evidence_with_case_path(
    tmp_path: Path,
) -> None:
    raw_case = _raw_case()
    evidence = {
        "evidence_id": "ev-1",
        "paper_id": "paper-1",
        "chunk_id": "paper-1:chunk:001",
        "claim_type": "retrieved",
        "quote": "Source text",
        "relevance_score": 0.9,
    }
    raw_case["evidence"] = [evidence, evidence.copy()]

    with pytest.raises(
        ValueError,
        match=r"case case-1: evidence.*duplicate evidence_id: ev-1",
    ):
        evaluate_fixture(_write_fixture(tmp_path, [raw_case]))


def test_evaluate_fixture_allows_optional_query(tmp_path: Path) -> None:
    without_query = _raw_case()
    with_query = _raw_case()
    with_query["query"] = "An optional descriptive query"

    first = evaluate_fixture(_write_fixture(tmp_path, [without_query]))
    second_path = tmp_path / "with-query.json"
    second_path.write_text(json.dumps([with_query]), encoding="utf-8")
    second = evaluate_fixture(second_path)

    assert first == second


def test_evaluate_fixture_propagates_malformed_json_error(tmp_path: Path) -> None:
    path = tmp_path / "malformed.json"
    path.write_text("[{", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        evaluate_fixture(path)


def test_evaluate_fixture_macro_averages_two_cases_exactly(tmp_path: Path) -> None:
    high_scores = _raw_case()
    high_scores["case_id"] = "high"
    high_scores["claims"] = [
        {
            "claim": "Supported claim",
            "evidence_ids": ["ev-1"],
            "support_status": "supported",
        }
    ]
    high_scores["evidence"] = [
        {
            "evidence_id": "ev-1",
            "paper_id": "paper-1",
            "chunk_id": "paper-1:chunk:001",
            "claim_type": "retrieved",
            "quote": "Source text",
            "relevance_score": 0.9,
        }
    ]

    low_scores = _raw_case()
    low_scores["case_id"] = "low"
    low_scores["actual_paper_ids"] = []
    low_scores["claims"] = [
        {
            "claim": "Unsupported claim",
            "evidence_ids": [],
            "support_status": "unsupported",
        }
    ]

    result = evaluate_fixture(
        _write_fixture(tmp_path, [high_scores, low_scores])
    )

    assert result["summary"] == {
        "case_count": 2,
        "retrieval_hit_rate": 0.5,
        "evidence_coverage": 0.5,
        "unsupported_claim_rate": 0.5,
        "citation_validity": 0.5,
    }


def test_evaluate_fixture_rejects_non_object_case(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path, [42])

    with pytest.raises(ValueError, match=r"case 0: case must be an object"):
        evaluate_fixture(path)
