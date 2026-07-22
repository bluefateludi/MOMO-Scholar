from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from paper_agent.modeling import StrictModel
from paper_agent.schemas import Evidence, ReportClaim
from paper_agent.synthesis.models import (
    CheckedClaim,
    CheckedFinding,
    CheckedPaperAnalysis,
    CheckedSurveyReport,
    GroundedClaim,
    PaperAnalysis,
    RejectedCriticalClaim,
    SurveyDraft,
)


class CheckedAnalysisOutcome(StrictModel):
    analysis: CheckedPaperAnalysis
    sanitized_reference_count: int = Field(ge=0)
    dropped_finding_count: int = Field(ge=0)
    has_supported_finding: bool


def _evidence_index(evidence: Sequence[Evidence]) -> dict[str, Evidence]:
    index: dict[str, Evidence] = {}
    for item in evidence:
        if item.evidence_id in index:
            raise ValueError("duplicate evidence_id")
        index[item.evidence_id] = item
    return index


def _sanitize_references(
    evidence_ids: Sequence[str],
    index: dict[str, Evidence],
    *,
    run_id: str,
    paper_id: str | None = None,
) -> tuple[list[str], str, int]:
    prefix = f"{run_id}:"
    retained: list[str] = []
    seen: set[str] = set()
    removed = 0
    for evidence_id in evidence_ids:
        item = index.get(evidence_id)
        valid = (
            evidence_id.startswith(prefix)
            and item is not None
            and (paper_id is None or item.paper_id == paper_id)
            and evidence_id not in seen
        )
        if valid:
            retained.append(evidence_id)
            seen.add(evidence_id)
        else:
            removed += 1

    if not retained:
        status = "unsupported"
    elif removed:
        status = "weakly_supported"
    else:
        status = "supported"
    return retained, status, removed


def check_paper_analysis(
    analysis: PaperAnalysis,
    evidence: Sequence[Evidence],
    *,
    run_id: str,
) -> CheckedAnalysisOutcome:
    index = _evidence_index(evidence)
    checked_categories: dict[str, list[CheckedFinding]] = {}
    sanitized_reference_count = 0
    dropped_finding_count = 0
    has_supported_finding = False

    for category in (
        "contributions",
        "methods",
        "experiments",
        "results",
        "limitations",
    ):
        checked_findings: list[CheckedFinding] = []
        for finding in getattr(analysis, category):
            retained, status, removed = _sanitize_references(
                finding.evidence_ids,
                index,
                run_id=run_id,
                paper_id=analysis.paper_id,
            )
            sanitized_reference_count += removed
            if not retained:
                dropped_finding_count += 1
                continue
            checked_findings.append(
                CheckedFinding(
                    text=finding.text,
                    evidence_ids=retained,
                    support_status=status,
                )
            )
            has_supported_finding |= status == "supported"
        checked_categories[category] = checked_findings

    return CheckedAnalysisOutcome(
        analysis=CheckedPaperAnalysis(paper_id=analysis.paper_id, **checked_categories),
        sanitized_reference_count=sanitized_reference_count,
        dropped_finding_count=dropped_finding_count,
        has_supported_finding=has_supported_finding,
    )


def _check_claim(
    claim: GroundedClaim,
    index: dict[str, Evidence],
    *,
    run_id: str,
) -> CheckedClaim:
    retained, status, _ = _sanitize_references(
        claim.evidence_ids,
        index,
        run_id=run_id,
    )
    return CheckedClaim(
        text=claim.text,
        evidence_ids=retained,
        support_status=status,
    )


def check_survey_draft(
    question: str,
    draft: SurveyDraft,
    evidence: Sequence[Evidence],
    *,
    run_id: str,
) -> CheckedSurveyReport:
    if not question.strip():
        raise ValueError("question must be non-empty")
    index = _evidence_index(evidence)
    checked_categories: dict[str, list[CheckedClaim]] = {}
    rejected: list[RejectedCriticalClaim] = []

    for category in (
        "tldr_claims",
        "method_taxonomy",
        "comparisons",
        "key_findings",
        "limitations",
        "open_questions",
    ):
        checked_claims: list[CheckedClaim] = []
        for claim in getattr(draft, category):
            checked = _check_claim(claim, index, run_id=run_id)
            if (
                category in {"tldr_claims", "key_findings"}
                and checked.support_status != "supported"
            ):
                rejected.append(
                    RejectedCriticalClaim(
                        **checked.model_dump(),
                        source_section=category,
                    )
                )
            else:
                checked_claims.append(checked)
        checked_categories[category] = checked_claims

    return CheckedSurveyReport(
        question=question,
        **checked_categories,
        rejected_critical_claims=rejected,
    )


def require_publishable_report(report: CheckedSurveyReport) -> None:
    has_supported_tldr = any(
        claim.support_status == "supported" for claim in report.tldr_claims
    )
    has_supported_key_finding = any(
        claim.support_status == "supported" for claim in report.key_findings
    )
    if not has_supported_tldr or not has_supported_key_finding:
        raise ValueError("insufficient_supported_report")


def check_claims(
    claims: list[ReportClaim],
    evidence: list[Evidence],
    run_id: str,
) -> list[ReportClaim]:
    evidence_ids = [item.evidence_id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate evidence_id")

    valid_ids = set(evidence_ids)
    prefix = f"{run_id}:"
    checked: list[ReportClaim] = []
    for claim in claims:
        supported = bool(claim.evidence_ids) and all(
            evidence_id.startswith(prefix) and evidence_id in valid_ids
            for evidence_id in claim.evidence_ids
        )
        checked.append(
            claim.model_copy(
                update={"support_status": "supported" if supported else "unsupported"}
            )
        )
    return checked
