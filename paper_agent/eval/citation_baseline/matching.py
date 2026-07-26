from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from paper_agent.eval.contracts import ReferenceEvidence
from paper_agent.schemas import Evidence

from .contracts import AtomicAssertion, CitationOccurrence, EvidenceMatch, MatchStrategy


MatchingStatus = Literal["matched", "review_required", "unscorable_content"]
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ActualEvidenceRecord:
    evidence: Evidence
    content_sha256: str
    upstream_locator: str | None = None

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 value")
        if self.upstream_locator is not None and not self.upstream_locator.strip():
            raise ValueError("upstream_locator must not be blank")


@dataclass(frozen=True, slots=True)
class EvidenceMatchingResult:
    status: MatchingStatus
    matches: tuple[EvidenceMatch, ...]
    review_occurrence_ids: tuple[str, ...]
    unmatched_gold_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PairMatch:
    strategy: MatchStrategy
    score: float


def resolve_citation_occurrences(
    *,
    assertions: Sequence[AtomicAssertion],
    citation_occurrences: Sequence[CitationOccurrence],
    actual_evidence: Sequence[Evidence],
) -> tuple[CitationOccurrence, ...]:
    assertions_by_id = {assertion.assertion_id: assertion for assertion in assertions}
    evidence_by_id: dict[str, list[Evidence]] = {}
    for evidence in actual_evidence:
        evidence_by_id.setdefault(evidence.evidence_id, []).append(evidence)

    resolved: list[CitationOccurrence] = []
    for occurrence in citation_occurrences:
        assertion = assertions_by_id.get(occurrence.assertion_id)
        candidates = evidence_by_id.get(occurrence.evidence_id, [])
        reason: str | None
        if assertion is None:
            reason = "unknown_assertion"
        elif not occurrence.evidence_id.startswith(f"{assertion.run_id}:"):
            reason = "foreign_run_evidence"
        elif len(candidates) == 0:
            reason = "missing_evidence"
        elif len(candidates) != 1:
            reason = "non_unique_evidence"
        elif (
            assertion.paper_id is not None
            and candidates[0].paper_id != assertion.paper_id
        ):
            reason = "paper_scope_mismatch"
        else:
            reason = None
        resolved.append(
            occurrence.model_copy(
                update={
                    "structurally_valid": reason is None,
                    "structural_reason_code": reason,
                }
            )
        )
    return tuple(resolved)


def match_gold_evidence(
    *,
    assertion: AtomicAssertion,
    citation_occurrences: Sequence[CitationOccurrence],
    actual_evidence: Sequence[ActualEvidenceRecord],
    reference_evidence: Sequence[ReferenceEvidence],
) -> EvidenceMatchingResult:
    actual_by_id = _unique_actual_by_id(actual_evidence)
    cited: list[tuple[CitationOccurrence, ActualEvidenceRecord]] = []
    seen_actual_ids: set[str] = set()
    for occurrence in citation_occurrences:
        if (
            occurrence.assertion_id != assertion.assertion_id
            or not occurrence.structurally_valid
        ):
            continue
        actual = actual_by_id.get(occurrence.evidence_id)
        if actual is None or occurrence.evidence_id in seen_actual_ids:
            continue
        seen_actual_ids.add(occurrence.evidence_id)
        cited.append((occurrence, actual))

    gold = tuple(
        item
        for item in reference_evidence
        if assertion.paper_id is None or item.paper_id == assertion.paper_id
    )
    if _has_content_hash_mismatch(cited, gold):
        return EvidenceMatchingResult(
            status="unscorable_content",
            matches=(),
            review_occurrence_ids=(),
            unmatched_gold_evidence_ids=tuple(item.evidence_id for item in gold),
        )

    pair_matches = [
        [_match_pair(actual, expected) for expected in gold]
        for _, actual in cited
    ]
    assignment = _maximum_weight_assignment(pair_matches)
    assigned_gold: set[int] = set()
    matches: list[EvidenceMatch] = []
    review_occurrence_ids: list[str] = []

    for actual_index, (occurrence, actual) in enumerate(cited):
        gold_index = assignment[actual_index]
        pair = (
            pair_matches[actual_index][gold_index]
            if gold_index is not None
            else None
        )
        if pair is None:
            matches.append(_no_match(assertion, occurrence, actual))
            review_occurrence_ids.append(occurrence.occurrence_id)
            continue
        expected = gold[gold_index]
        assigned_gold.add(gold_index)
        matches.append(
            EvidenceMatch(
                schema_version="1.0",
                match_id=f"match:{occurrence.occurrence_id}",
                assertion_id=assertion.assertion_id,
                citation_occurrence_id=occurrence.occurrence_id,
                actual_evidence_id=actual.evidence.evidence_id,
                gold_evidence_id=expected.evidence_id,
                strategy=pair.strategy,
                score=float(pair.score),
                supports_assertion=True,
                actual_evidence_sha256=actual.content_sha256,
                gold_evidence_sha256=expected.content_sha256,
            )
        )

    unmatched_gold = tuple(
        expected.evidence_id
        for index, expected in enumerate(gold)
        if index not in assigned_gold
    )
    return EvidenceMatchingResult(
        status="review_required" if review_occurrence_ids else "matched",
        matches=tuple(matches),
        review_occurrence_ids=tuple(review_occurrence_ids),
        unmatched_gold_evidence_ids=unmatched_gold,
    )


def _unique_actual_by_id(
    records: Sequence[ActualEvidenceRecord],
) -> dict[str, ActualEvidenceRecord]:
    result: dict[str, ActualEvidenceRecord] = {}
    for record in records:
        evidence_id = record.evidence.evidence_id
        if evidence_id in result:
            raise ValueError("actual evidence IDs must be unique")
        result[evidence_id] = record
    return result


def _has_content_hash_mismatch(
    cited: Sequence[tuple[CitationOccurrence, ActualEvidenceRecord]],
    gold: Sequence[ReferenceEvidence],
) -> bool:
    expected_hashes_by_paper: dict[str, set[str]] = {}
    for expected in gold:
        expected_hashes_by_paper.setdefault(expected.paper_id, set()).add(
            expected.content_sha256
        )
    return any(
        expected_hashes
        and actual.content_sha256 not in expected_hashes
        for _, actual in cited
        if (expected_hashes := expected_hashes_by_paper.get(actual.evidence.paper_id))
    )


def _match_pair(
    actual: ActualEvidenceRecord,
    expected: ReferenceEvidence,
) -> _PairMatch | None:
    if actual.evidence.paper_id != expected.paper_id:
        return None
    if not _page_matches(actual.evidence.page, expected):
        return None
    if (
        actual.upstream_locator is not None
        and expected.upstream_locator is not None
        and actual.upstream_locator == expected.upstream_locator
    ):
        return _PairMatch("exact_locator", 1.0)

    actual_quote = _normalize_quote(actual.evidence.quote)
    expected_quote = _normalize_quote(expected.quote)
    if actual_quote == expected_quote:
        return _PairMatch("exact_normalized_quote", 1.0)

    actual_tokens = actual_quote.split()
    expected_tokens = expected_quote.split()
    shorter_count = min(len(actual_tokens), len(expected_tokens))
    longer_count = max(len(actual_tokens), len(expected_tokens))
    containment_score = shorter_count / longer_count if longer_count else 0.0
    if _has_contiguous_containment(actual_tokens, expected_tokens) and (
        containment_score >= 0.90
    ):
        return _PairMatch("containment", containment_score)

    token_f1 = _token_f1(actual_tokens, expected_tokens)
    if token_f1 >= 0.80:
        return _PairMatch("token_span_f1", token_f1)
    return None


def _page_matches(actual_page: int | None, expected: ReferenceEvidence) -> bool:
    if actual_page is not None and expected.page is not None:
        return actual_page == expected.page
    source_type = expected.source_type.casefold().replace("-", "_").replace(" ", "_")
    return (
        "abstract" in source_type
        or "paragraph" in source_type
        or "rationale" in source_type
    )


def _normalize_quote(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _token_f1(actual_tokens: Sequence[str], expected_tokens: Sequence[str]) -> float:
    if not actual_tokens or not expected_tokens:
        return 0.0
    overlap = sum((Counter(actual_tokens) & Counter(expected_tokens)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(actual_tokens)
    recall = overlap / len(expected_tokens)
    return 2 * precision * recall / (precision + recall)


def _has_contiguous_containment(
    actual_tokens: Sequence[str],
    expected_tokens: Sequence[str],
) -> bool:
    shorter, longer = (
        (actual_tokens, expected_tokens)
        if len(actual_tokens) <= len(expected_tokens)
        else (expected_tokens, actual_tokens)
    )
    if not shorter:
        return False
    width = len(shorter)
    return any(
        list(longer[start : start + width]) == list(shorter)
        for start in range(len(longer) - width + 1)
    )


def _maximum_weight_assignment(
    pair_matches: Sequence[Sequence[_PairMatch | None]],
) -> tuple[int | None, ...]:
    row_count = len(pair_matches)
    if row_count == 0:
        return ()
    gold_count = len(pair_matches[0])
    column_count = gold_count + row_count
    costs = [
        [
            -(pair.score if pair is not None else 0.0)
            for pair in row
        ]
        + [0.0] * row_count
        for row in pair_matches
    ]

    # Rectangular Hungarian assignment; dummy columns represent no match.
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    assigned_row = [0] * (column_count + 1)
    previous_column = [0] * (column_count + 1)
    for row in range(1, row_count + 1):
        assigned_row[0] = row
        minimum = [float("inf")] * (column_count + 1)
        used = [False] * (column_count + 1)
        column = 0
        while True:
            used[column] = True
            current_row = assigned_row[column]
            delta = float("inf")
            next_column = 0
            for candidate_column in range(1, column_count + 1):
                if used[candidate_column]:
                    continue
                reduced_cost = (
                    costs[current_row - 1][candidate_column - 1]
                    - u[current_row]
                    - v[candidate_column]
                )
                if reduced_cost < minimum[candidate_column]:
                    minimum[candidate_column] = reduced_cost
                    previous_column[candidate_column] = column
                if minimum[candidate_column] < delta:
                    delta = minimum[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(column_count + 1):
                if used[candidate_column]:
                    u[assigned_row[candidate_column]] += delta
                    v[candidate_column] -= delta
                else:
                    minimum[candidate_column] -= delta
            column = next_column
            if assigned_row[column] == 0:
                break
        while True:
            previous = previous_column[column]
            assigned_row[column] = assigned_row[previous]
            column = previous
            if column == 0:
                break

    result: list[int | None] = [None] * row_count
    for column in range(1, column_count + 1):
        row = assigned_row[column]
        if row == 0:
            continue
        gold_index = column - 1
        if (
            gold_index < gold_count
            and pair_matches[row - 1][gold_index] is not None
        ):
            result[row - 1] = gold_index
    return tuple(result)


def _no_match(
    assertion: AtomicAssertion,
    occurrence: CitationOccurrence,
    actual: ActualEvidenceRecord,
) -> EvidenceMatch:
    return EvidenceMatch(
        schema_version="1.0",
        match_id=f"match:{occurrence.occurrence_id}",
        assertion_id=assertion.assertion_id,
        citation_occurrence_id=occurrence.occurrence_id,
        actual_evidence_id=actual.evidence.evidence_id,
        gold_evidence_id=None,
        strategy="no_match",
        score=0.0,
        supports_assertion=False,
        actual_evidence_sha256=actual.content_sha256,
        gold_evidence_sha256=None,
    )


__all__ = [
    "ActualEvidenceRecord",
    "EvidenceMatchingResult",
    "MatchingStatus",
    "match_gold_evidence",
    "resolve_citation_occurrences",
]
