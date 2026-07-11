"""Deterministic evaluation runner entry points."""

import json
from pathlib import Path

from pydantic import ValidationError

from paper_agent.eval.metrics import (
    citation_validity,
    evidence_coverage,
    retrieval_hit_rate,
    unsupported_claim_rate,
)
from paper_agent.schemas import Evidence, ReportClaim


_REQUIRED_CASE_FIELDS = (
    "case_id",
    "expected_paper_ids",
    "actual_paper_ids",
    "claims",
    "evidence",
)


def _require_list(case_label: str, field: str, value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"case {case_label}: {field} must be a list")
    return value


def _require_string_list(case_label: str, field: str, value: object) -> list[str]:
    items = _require_list(case_label, field, value)
    if any(not isinstance(item, str) for item in items):
        raise ValueError(f"case {case_label}: {field} must contain only strings")
    return items


def _validation_path(error: ValidationError) -> str:
    location = error.errors()[0]["loc"]
    return ".".join(str(part) for part in location)


def evaluate_case(
    *,
    expected_paper_ids: list[str],
    actual_paper_ids: list[str],
    claims: list[ReportClaim],
    evidence: list[Evidence],
) -> dict[str, float]:
    """Evaluate one in-memory case with the deterministic v1 metrics."""
    seen_evidence_ids: set[str] = set()
    for item in evidence:
        if item.evidence_id in seen_evidence_ids:
            raise ValueError(f"duplicate evidence_id: {item.evidence_id}")
        seen_evidence_ids.add(item.evidence_id)

    return {
        "retrieval_hit_rate": retrieval_hit_rate(
            actual_paper_ids,
            expected_paper_ids,
        ),
        "evidence_coverage": evidence_coverage(claims),
        "unsupported_claim_rate": unsupported_claim_rate(claims),
        "citation_validity": citation_validity(claims, evidence),
    }


def evaluate_fixture(path: str | Path) -> dict[str, object]:
    """Read a JSON fixture and evaluate each case deterministically."""
    raw_cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("fixture top level must be a list")

    cases = []
    seen_case_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise ValueError(f"case {index}: case must be an object")
        for field in _REQUIRED_CASE_FIELDS:
            if field not in raw_case:
                raise ValueError(f"case {index}: missing required field {field}")

        case_id = raw_case["case_id"]
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"case {index}: case_id must be a non-blank string")
        if case_id in seen_case_ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen_case_ids.add(case_id)

        expected_paper_ids = _require_string_list(
            case_id, "expected_paper_ids", raw_case["expected_paper_ids"]
        )
        actual_paper_ids = _require_string_list(
            case_id, "actual_paper_ids", raw_case["actual_paper_ids"]
        )
        raw_claims = _require_list(case_id, "claims", raw_case["claims"])
        raw_evidence = _require_list(case_id, "evidence", raw_case["evidence"])
        claims = []
        for item_index, item in enumerate(raw_claims):
            try:
                claims.append(ReportClaim.model_validate(item))
            except ValidationError as error:
                path = _validation_path(error)
                raise ValueError(
                    f"case {case_id}: claims[{item_index}].{path} is invalid"
                ) from error

        evidence = []
        for item_index, item in enumerate(raw_evidence):
            try:
                evidence.append(Evidence.model_validate(item))
            except ValidationError as error:
                path = _validation_path(error)
                raise ValueError(
                    f"case {case_id}: evidence[{item_index}].{path} is invalid"
                ) from error

        try:
            metrics = evaluate_case(
                expected_paper_ids=expected_paper_ids,
                actual_paper_ids=actual_paper_ids,
                claims=claims,
                evidence=evidence,
            )
        except ValueError as error:
            raise ValueError(f"case {case_id}: evidence: {error}") from error
        cases.append({"case_id": case_id, "metrics": metrics})

    metric_names = (
        "retrieval_hit_rate",
        "evidence_coverage",
        "unsupported_claim_rate",
        "citation_validity",
    )
    case_count = len(cases)
    summary: dict[str, int | float] = {"case_count": case_count}
    for metric_name in metric_names:
        summary[metric_name] = (
            sum(case["metrics"][metric_name] for case in cases) / case_count
            if case_count
            else 0.0
        )

    return {"cases": cases, "summary": summary}
