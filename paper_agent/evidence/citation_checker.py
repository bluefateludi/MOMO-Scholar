from __future__ import annotations

from paper_agent.schemas import Evidence, ReportClaim


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
