from __future__ import annotations

import pytest

from paper_agent.eval.citation_baseline.contracts import (
    AtomicAssertion,
    CitationOccurrence,
)
from paper_agent.eval.citation_baseline.matching import (
    ActualEvidenceRecord,
    match_gold_evidence,
    resolve_citation_occurrences,
)
from paper_agent.eval.contracts import ReferenceEvidence
from paper_agent.schemas import Evidence


CONTENT_HASH = "a" * 64
OTHER_CONTENT_HASH = "b" * 64


def _assertion(*, paper_id: str | None = "paper-1") -> AtomicAssertion:
    return AtomicAssertion(
        schema_version="1.0",
        assertion_id="assertion-1",
        case_id="case-1",
        run_id="run-1",
        text="The intervention improved the measured outcome.",
        paper_id=paper_id,
        source_section="findings",
        start_char=0,
        end_char=47,
    )


def _occurrence(
    *,
    occurrence_id: str = "citation-1",
    evidence_id: str = "run-1:evidence-1",
    structurally_valid: bool = True,
) -> CitationOccurrence:
    return CitationOccurrence(
        schema_version="1.0",
        occurrence_id=occurrence_id,
        assertion_id="assertion-1",
        evidence_id=evidence_id,
        source_section="findings",
        start_char=48,
        end_char=72,
        structurally_valid=structurally_valid,
        structural_reason_code=None if structurally_valid else "not_resolved",
    )


def _evidence(
    *,
    evidence_id: str = "run-1:evidence-1",
    paper_id: str = "paper-1",
    quote: str = "The intervention improved the measured outcome.",
    page: int | None = 3,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id=paper_id,
        chunk_id=f"chunk:{evidence_id}",
        section="Results",
        page=page,
        claim_type="finding",
        quote=quote,
        relevance_score=1.0,
    )


def _actual(
    *,
    evidence: Evidence | None = None,
    content_sha256: str = CONTENT_HASH,
    upstream_locator: str | None = "claim-17/rationale-0",
) -> ActualEvidenceRecord:
    return ActualEvidenceRecord(
        evidence=evidence or _evidence(),
        content_sha256=content_sha256,
        upstream_locator=upstream_locator,
    )


def _gold(
    *,
    evidence_id: str = "gold-1",
    quote: str = "The intervention improved the measured outcome.",
    upstream_locator: str | None = "claim-17/rationale-0",
    page: int | None = 3,
    source_type: str = "rationale",
) -> ReferenceEvidence:
    return ReferenceEvidence(
        evidence_id=evidence_id,
        paper_id="paper-1",
        content_sha256=CONTENT_HASH,
        source_type=source_type,
        upstream_locator=upstream_locator,
        page=page,
        section="Results",
        quote=quote,
        relevance_grade=3,
        required=True,
    )


def test_structural_resolution_is_unique_run_owned_and_semantically_undecided() -> None:
    citation = _occurrence(structurally_valid=False)
    resolved = resolve_citation_occurrences(
        assertions=(_assertion(),),
        citation_occurrences=(citation,),
        actual_evidence=(
            _evidence(quote="This passage is real but irrelevant."),
        ),
    )

    assert resolved == (
        citation.model_copy(
            update={"structurally_valid": True, "structural_reason_code": None}
        ),
    )
    assert not hasattr(resolved[0], "supports_assertion")


@pytest.mark.parametrize(
    ("citation", "evidence", "reason"),
    [
        (
            _occurrence(evidence_id="other-run:evidence-1"),
            (_evidence(evidence_id="other-run:evidence-1"),),
            "foreign_run_evidence",
        ),
        (
            _occurrence(),
            (_evidence(), _evidence()),
            "non_unique_evidence",
        ),
        (
            _occurrence(),
            (_evidence(paper_id="paper-2"),),
            "paper_scope_mismatch",
        ),
    ],
)
def test_structural_resolution_rejects_invalid_references(
    citation: CitationOccurrence,
    evidence: tuple[Evidence, ...],
    reason: str,
) -> None:
    resolved = resolve_citation_occurrences(
        assertions=(_assertion(),),
        citation_occurrences=(citation,),
        actual_evidence=evidence,
    )

    assert resolved[0].structurally_valid is False
    assert resolved[0].structural_reason_code == reason


def test_unscoped_assertion_allows_run_owned_evidence_from_any_paper() -> None:
    resolved = resolve_citation_occurrences(
        assertions=(_assertion(paper_id=None),),
        citation_occurrences=(_occurrence(),),
        actual_evidence=(_evidence(paper_id="paper-2"),),
    )

    assert resolved[0].structurally_valid is True


@pytest.mark.parametrize(
    ("actual", "gold", "strategy", "score"),
    [
        (
            _actual(evidence=_evidence(quote="Irrelevant text.")),
            _gold(quote="Different text."),
            "exact_locator",
            1.0,
        ),
        (
            _actual(
                evidence=_evidence(
                    quote="THE\u00a0INTERVENTION   improved the measured outcome."
                ),
                upstream_locator=None,
            ),
            _gold(upstream_locator=None),
            "exact_normalized_quote",
            1.0,
        ),
        (
            _actual(
                evidence=_evidence(
                    quote="zero one two three four five six seven eight extra"
                ),
                upstream_locator=None,
            ),
            _gold(
                quote="zero one two three four five six seven eight",
                upstream_locator=None,
            ),
            "containment",
            0.9,
        ),
        (
            _actual(
                evidence=_evidence(quote="alpha beta gamma delta epsilon"),
                upstream_locator=None,
            ),
            _gold(
                quote="alpha beta gamma delta zeta",
                upstream_locator=None,
            ),
            "token_span_f1",
            0.8,
        ),
    ],
)
def test_gold_matching_uses_deterministic_strategy_order(
    actual: ActualEvidenceRecord,
    gold: ReferenceEvidence,
    strategy: str,
    score: float,
) -> None:
    result = match_gold_evidence(
        assertion=_assertion(),
        citation_occurrences=(_occurrence(),),
        actual_evidence=(actual,),
        reference_evidence=(gold,),
    )

    assert result.status == "matched"
    assert len(result.matches) == 1
    assert result.matches[0].strategy == strategy
    assert result.matches[0].score == pytest.approx(score)
    assert result.matches[0].supports_assertion is True
    assert result.matches[0].actual_evidence_sha256 == CONTENT_HASH
    assert result.matches[0].gold_evidence_sha256 == CONTENT_HASH


@pytest.mark.parametrize(
    ("actual_page", "gold_page", "source_type", "expected_status"),
    [
        (2, 3, "rationale", "review_required"),
        (None, 3, "pdf_span", "review_required"),
        (None, None, "pdf_span", "review_required"),
        (None, 3, "upstream_paragraph", "matched"),
        (None, 1, "abstract", "matched"),
    ],
)
def test_gold_matching_applies_page_constraints(
    actual_page: int | None,
    gold_page: int | None,
    source_type: str,
    expected_status: str,
) -> None:
    result = match_gold_evidence(
        assertion=_assertion(),
        citation_occurrences=(_occurrence(),),
        actual_evidence=(
            _actual(
                evidence=_evidence(page=actual_page),
                upstream_locator=None,
            ),
        ),
        reference_evidence=(
            _gold(
                page=gold_page,
                source_type=source_type,
                upstream_locator=None,
            ),
        ),
    )

    assert result.status == expected_status


def test_content_hash_mismatch_is_unscorable_not_no_match() -> None:
    result = match_gold_evidence(
        assertion=_assertion(),
        citation_occurrences=(_occurrence(),),
        actual_evidence=(
            _actual(content_sha256=OTHER_CONTENT_HASH),
        ),
        reference_evidence=(_gold(),),
    )

    assert result.status == "unscorable_content"
    assert result.matches == ()
    assert result.review_occurrence_ids == ()


def test_one_actual_passage_matches_at_most_one_duplicate_gold_passage() -> None:
    result = match_gold_evidence(
        assertion=_assertion(),
        citation_occurrences=(_occurrence(),),
        actual_evidence=(_actual(upstream_locator=None),),
        reference_evidence=(
            _gold(evidence_id="gold-1", upstream_locator=None),
            _gold(evidence_id="gold-2", upstream_locator=None),
        ),
    )

    assert len(result.matches) == 1
    assert result.matches[0].gold_evidence_id == "gold-1"
    assert result.unmatched_gold_evidence_ids == ("gold-2",)


def test_one_to_one_assignment_maximizes_total_match_weight() -> None:
    result = match_gold_evidence(
        assertion=_assertion(),
        citation_occurrences=(
            _occurrence(
                occurrence_id="citation-1",
                evidence_id="run-1:evidence-1",
            ),
            _occurrence(
                occurrence_id="citation-2",
                evidence_id="run-1:evidence-2",
            ),
        ),
        actual_evidence=(
            _actual(
                evidence=_evidence(
                    evidence_id="run-1:evidence-1",
                    quote="a b c d e f g h i j",
                ),
                upstream_locator=None,
            ),
            _actual(
                evidence=_evidence(
                    evidence_id="run-1:evidence-2",
                    quote="a b c d e f j",
                ),
                upstream_locator=None,
            ),
        ),
        reference_evidence=(
            _gold(
                evidence_id="gold-1",
                quote="a b c d e f g h i j",
                upstream_locator=None,
            ),
            _gold(
                evidence_id="gold-2",
                quote="a b c d e f g h i",
                upstream_locator=None,
            ),
        ),
    )

    assert [
        (match.actual_evidence_id, match.gold_evidence_id, match.strategy)
        for match in result.matches
    ] == [
        ("run-1:evidence-1", "gold-2", "containment"),
        ("run-1:evidence-2", "gold-1", "token_span_f1"),
    ]
    assert result.unmatched_gold_evidence_ids == ()


def test_containment_does_not_match_inside_a_token() -> None:
    result = match_gold_evidence(
        assertion=_assertion(),
        citation_occurrences=(_occurrence(),),
        actual_evidence=(
            _actual(
                evidence=_evidence(quote="alpha beta"),
                upstream_locator=None,
            ),
        ),
        reference_evidence=(
            _gold(quote="xalpha beta", upstream_locator=None),
        ),
    )

    assert result.matches[0].strategy == "no_match"
    assert result.status == "review_required"


def test_no_match_is_recorded_and_handed_off_to_review() -> None:
    actual = _actual(
        evidence=_evidence(quote="alpha beta gamma delta"),
        upstream_locator=None,
    )
    result = match_gold_evidence(
        assertion=_assertion(),
        citation_occurrences=(_occurrence(),),
        actual_evidence=(actual,),
        reference_evidence=(
            _gold(
                quote="one two three four",
                upstream_locator=None,
            ),
        ),
    )

    assert result.status == "review_required"
    assert len(result.matches) == 1
    assert result.matches[0].strategy == "no_match"
    assert result.matches[0].score == 0.0
    assert result.matches[0].supports_assertion is False
    assert result.review_occurrence_ids == ("citation-1",)
    assert result.unmatched_gold_evidence_ids == ("gold-1",)
