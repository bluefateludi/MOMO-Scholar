import pytest

from paper_agent.eval.citation_baseline.contracts import (
    AtomicAssertion,
    CitationOccurrence,
    EvidenceMatch,
    SupportJudgment,
)
from paper_agent.eval.citation_baseline.metrics import (
    CitationCaseInput,
    score_citation_baseline,
)


_SHA = "a" * 64


def _assertion(case_id: str, index: int) -> AtomicAssertion:
    assertion_id = f"{case_id}:assertion:{index}"
    return AtomicAssertion(
        schema_version="1.0",
        assertion_id=assertion_id,
        case_id=case_id,
        run_id=f"run-{case_id}",
        text=f"Assertion {index}.",
        source_section="summary",
        start_char=index * 20,
        end_char=index * 20 + 12,
    )


def _citation(
    assertion: AtomicAssertion,
    index: int,
    *,
    structurally_valid: bool = True,
) -> CitationOccurrence:
    return CitationOccurrence(
        schema_version="1.0",
        occurrence_id=f"{assertion.assertion_id}:citation:{index}",
        assertion_id=assertion.assertion_id,
        evidence_id=f"{assertion.run_id}:evidence:{index}",
        source_section=assertion.source_section,
        start_char=assertion.start_char,
        end_char=assertion.start_char + 1,
        structurally_valid=structurally_valid,
        structural_reason_code=None if structurally_valid else "missing_evidence",
    )


def _match(
    assertion: AtomicAssertion,
    occurrence: CitationOccurrence,
) -> EvidenceMatch:
    return EvidenceMatch(
        schema_version="1.0",
        match_id=f"match:{occurrence.occurrence_id}",
        assertion_id=assertion.assertion_id,
        citation_occurrence_id=occurrence.occurrence_id,
        actual_evidence_id=occurrence.evidence_id,
        gold_evidence_id=f"gold:{assertion.assertion_id}",
        strategy="exact_locator",
        score=1.0,
        supports_assertion=True,
        actual_evidence_sha256=_SHA,
        gold_evidence_sha256="b" * 64,
    )


def _judgment(
    assertion: AtomicAssertion,
    verdict: str,
    *,
    citation_ids: tuple[str, ...] = (),
) -> SupportJudgment:
    reason = {
        "supported": "human_entailment",
        "unsupported": "no_supporting_citation",
        "ambiguous": "insufficient_context",
    }[verdict]
    return SupportJudgment(
        schema_version="1.0",
        judgment_id=f"judgment:{assertion.assertion_id}",
        case_id=assertion.case_id,
        run_id=assertion.run_id,
        assertion_id=assertion.assertion_id,
        citation_occurrence_ids=citation_ids,
        support_match_ids=(),
        semantic_verdict=verdict,
        reason_code=reason,
        notes="Needs more context." if verdict == "ambiguous" else None,
        reviewer_pseudonym="reviewer-1",
        rubric_version="citation-support-v1",
        calibration_set_version="calibration-v1",
        reviewed_at="2026-07-26T08:00:00Z",
        output_sha256=_SHA,
        evidence_sha256=_SHA,
        config_sha256=_SHA,
    )


def _supported_case(
    case_id: str,
    *,
    assertion_count: int,
    cited_assertion_count: int,
    latency_ms: float,
) -> CitationCaseInput:
    assertions = tuple(_assertion(case_id, index) for index in range(assertion_count))
    citations = tuple(
        _citation(assertion, 1) for assertion in assertions[:cited_assertion_count]
    )
    judgments = tuple(_judgment(assertion, "supported") for assertion in assertions)
    return CitationCaseInput(
        case_id=case_id,
        assertions=assertions,
        citation_occurrences=citations,
        evidence_matches=(),
        judgments=judgments,
        unscorable_assertion_ids=(),
        duration_ms=latency_ms,
    )


def test_metric_denominators_keep_ambiguous_and_unscorable_separate() -> None:
    case_id = "case-denominators"
    assertions = tuple(_assertion(case_id, index) for index in range(5))
    citations = (
        _citation(assertions[0], 1),
        _citation(assertions[0], 2, structurally_valid=False),
        _citation(assertions[2], 1),
        _citation(assertions[3], 1),
    )
    result = score_citation_baseline(
        cases=(
            CitationCaseInput(
                case_id=case_id,
                assertions=assertions,
                citation_occurrences=citations,
                evidence_matches=(_match(assertions[0], citations[0]),),
                judgments=(
                    _judgment(assertions[1], "unsupported"),
                    _judgment(
                        assertions[2],
                        "ambiguous",
                        citation_ids=(citations[2].occurrence_id,),
                    ),
                    _judgment(assertions[4], "supported"),
                ),
                unscorable_assertion_ids=(assertions[3].assertion_id,),
                duration_ms=12.0,
            ),
        )
    )

    case = result["case_metrics"][0]
    assert case["metrics"] == {
        "citation_coverage": {"numerator": 3, "denominator": 5, "value": 0.6},
        "citation_validity": {"numerator": 3, "denominator": 4, "value": 0.75},
        "unsupported_assertion_rate": {
            "numerator": 1,
            "denominator": 3,
            "value": pytest.approx(1 / 3),
        },
    }
    assert case["assertion_status_counts"] == {
        "supported": 2,
        "unsupported": 1,
        "ambiguous": 1,
        "unscorable": 1,
    }


def test_aggregation_is_case_macro_with_fixed_case_bootstrap_and_attempted_failures() -> None:
    result = score_citation_baseline(
        cases=(
            _supported_case(
                "case-small",
                assertion_count=1,
                cited_assertion_count=1,
                latency_ms=10.0,
            ),
            _supported_case(
                "case-large",
                assertion_count=3,
                cited_assertion_count=1,
                latency_ms=20.0,
            ),
            CitationCaseInput(
                case_id="case-failed",
                failure_reason_code="generation_timeout",
                duration_ms=30.0,
            ),
        )
    )

    coverage = result["aggregate"]["citation_coverage"]
    assert coverage["macro_mean"] == pytest.approx(2 / 3)
    assert coverage["case_denominator"] == 2
    assert coverage["ci_95_low"] == pytest.approx(1 / 3)
    assert coverage["ci_95_high"] == pytest.approx(1.0)
    assert result["bootstrap"] == {
        "method": "case_percentile",
        "confidence_level": 0.95,
        "resamples": 10_000,
        "seed": 20_260_726,
    }
    assert result["denominators"] == {
        "attempted_cases": 3,
        "completed_cases": 2,
        "assertions": 4,
        "citations": 2,
        "scorable_assertions": 4,
    }
    assert result["operations"] == {
        "attempted": 3,
        "completed": 2,
        "failed": 1,
        "failure_rate": pytest.approx(1 / 3),
        "completed_latency_ms_p50": 15.0,
        "completed_latency_ms_p95": 19.5,
    }
    assert result == score_citation_baseline(
        cases=(
            _supported_case(
                "case-small",
                assertion_count=1,
                cited_assertion_count=1,
                latency_ms=10.0,
            ),
            _supported_case(
                "case-large",
                assertion_count=3,
                cited_assertion_count=1,
                latency_ms=20.0,
            ),
            CitationCaseInput(
                case_id="case-failed",
                failure_reason_code="generation_timeout",
                duration_ms=30.0,
            ),
        )
    )


def test_completed_case_rejects_missing_or_overlapping_semantic_statuses() -> None:
    assertion = _assertion("case-incomplete", 0)
    with pytest.raises(ValueError, match="exactly one semantic status"):
        score_citation_baseline(
            cases=(
                CitationCaseInput(
                    case_id=assertion.case_id,
                    assertions=(assertion,),
                    unscorable_assertion_ids=(assertion.assertion_id,),
                    judgments=(_judgment(assertion, "unsupported"),),
                    duration_ms=1.0,
                ),
            )
        )
