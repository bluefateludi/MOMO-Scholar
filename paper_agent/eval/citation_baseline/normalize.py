from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from paper_agent.eval.citation_baseline.contracts import (
    AtomicAssertion,
    CitationOccurrence,
)
from paper_agent.schemas import Evidence, ReportClaim
from paper_agent.synthesis.models import CheckedClaim, CheckedSurveyReport


_REPORT_SECTIONS = (
    "tldr_claims",
    "method_taxonomy",
    "comparisons",
    "key_findings",
    "limitations",
    "open_questions",
)


@dataclass(frozen=True)
class NormalizedCitationOutput:
    assertions: tuple[AtomicAssertion, ...]
    citation_occurrences: tuple[CitationOccurrence, ...]


def _evidence_index(evidence: Sequence[Evidence]) -> dict[str, Evidence]:
    indexed: dict[str, Evidence] = {}
    for item in evidence:
        if item.evidence_id in indexed:
            raise ValueError("duplicate evidence_id")
        indexed[item.evidence_id] = item
    return indexed


def _structured_sections(
    output: object,
) -> tuple[tuple[str, tuple[CheckedClaim | ReportClaim, ...]], ...]:
    if isinstance(output, CheckedSurveyReport):
        rejected_by_section: dict[str, list[CheckedClaim]] = {
            section: [] for section in _REPORT_SECTIONS
        }
        for claim in output.rejected_critical_claims:
            rejected_by_section[claim.source_section].append(claim)
        return tuple(
            (
                section,
                tuple(getattr(output, section))
                + tuple(rejected_by_section[section]),
            )
            for section in _REPORT_SECTIONS
        )

    if isinstance(output, Sequence) and not isinstance(
        output, (str, bytes, bytearray)
    ):
        claims = tuple(output)
        if all(isinstance(claim, ReportClaim) for claim in claims):
            return (("claims", claims),)

    raise ValueError("unsupported_output_shape")


def _citation_state(
    evidence_id: str,
    *,
    run_id: str,
    evidence_by_id: dict[str, Evidence],
) -> tuple[bool, str | None]:
    prefix = f"{run_id}:"
    if ":" not in evidence_id or evidence_id.endswith(":"):
        return False, "malformed_evidence_id"
    if not evidence_id.startswith(prefix):
        return False, "foreign_run_evidence_id"
    if evidence_id not in evidence_by_id:
        return False, "unknown_evidence_id"
    return True, None


def normalize_checked_output(
    output: object,
    evidence: Sequence[Evidence],
    *,
    case_id: str,
    run_id: str,
) -> NormalizedCitationOutput:
    """Normalize checked structured claims into stable, source-relative spans."""

    if not case_id.strip() or not run_id.strip():
        raise ValueError("case_id and run_id must be non-empty")

    evidence_by_id = _evidence_index(evidence)
    sections = _structured_sections(output)
    assertions: list[AtomicAssertion] = []
    citations: list[CitationOccurrence] = []

    for source_section, claims in sections:
        section_cursor = 0
        for claim in claims:
            text = claim.text if isinstance(claim, CheckedClaim) else claim.claim
            evidence_ids = claim.evidence_ids
            assertion_id = f"{case_id}:assertion:{len(assertions) + 1:04d}"
            assertion_end = section_cursor + len(text)
            assertions.append(
                AtomicAssertion(
                    schema_version="1.0",
                    assertion_id=assertion_id,
                    case_id=case_id,
                    run_id=run_id,
                    text=text,
                    paper_id=None,
                    source_section=source_section,
                    start_char=section_cursor,
                    end_char=assertion_end,
                )
            )

            rendered_cursor = assertion_end
            for evidence_id in evidence_ids:
                citation_start = rendered_cursor + 2
                citation_end = citation_start + len(evidence_id)
                structurally_valid, reason = _citation_state(
                    evidence_id,
                    run_id=run_id,
                    evidence_by_id=evidence_by_id,
                )
                citations.append(
                    CitationOccurrence(
                        schema_version="1.0",
                        occurrence_id=(
                            f"{case_id}:citation:{len(citations) + 1:04d}"
                        ),
                        assertion_id=assertion_id,
                        evidence_id=evidence_id,
                        source_section=source_section,
                        start_char=citation_start,
                        end_char=citation_end,
                        structurally_valid=structurally_valid,
                        structural_reason_code=reason,
                    )
                )
                rendered_cursor = citation_end + 1

            section_cursor = rendered_cursor + 1

    return NormalizedCitationOutput(
        assertions=tuple(assertions),
        citation_occurrences=tuple(citations),
    )


__all__ = ["NormalizedCitationOutput", "normalize_checked_output"]
