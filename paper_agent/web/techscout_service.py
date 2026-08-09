from __future__ import annotations

from base64 import urlsafe_b64encode
from datetime import timedelta

from paper_agent.web.errors import WebError
from paper_agent.web.registry import RunRegistry
from paper_agent.web.techscout_api_models import (
    TechScoutCandidateList,
    TechScoutCandidateProjection,
    TechScoutEvidenceList,
    TechScoutEvidenceProjection,
    TechScoutReportProjection,
    TechScoutRunDetail,
    TechScoutRunList,
    TechScoutRunSummary,
    TraceEvent,
    TracePage,
)
from paper_agent.web.techscout_fixtures import DETAIL, EVIDENCE, REPORT, SYNTHETIC_RUN_ID


class TechScoutProjectionService:
    """Wave 1 read projections over an explicit frozen synthetic fixture.

    The TechScout Harness is intentionally not connected in this stream. POST is
    therefore unavailable instead of inventing execution state.
    """

    def __init__(self, registry: RunRegistry) -> None:
        self.registry = registry

    def create(self) -> None:
        raise WebError(503, "techscout_execution_unavailable")

    def list(self) -> TechScoutRunList:
        return TechScoutRunList(items=[TechScoutRunSummary(**DETAIL.model_dump(exclude={
            "project_context", "environment", "hard_constraints", "candidates", "recovery", "approval",
        }))])

    def detail(self, run_id: str) -> TechScoutRunDetail:
        if run_id != SYNTHETIC_RUN_ID:
            raise WebError(404, "run_not_found")
        return DETAIL

    def report(self, run_id: str) -> TechScoutReportProjection:
        self.detail(run_id)
        return REPORT

    def candidates(self, run_id: str) -> TechScoutCandidateList:
        return TechScoutCandidateList(items=self.detail(run_id).candidates)

    def candidate(self, run_id: str, candidate_id: str) -> TechScoutCandidateProjection:
        item = next(
            (candidate for candidate in self.detail(run_id).candidates if candidate.candidate_id == candidate_id),
            None,
        )
        if item is None:
            raise WebError(404, "candidate_not_found")
        return item

    def evidence(self, run_id: str) -> TechScoutEvidenceList:
        self.detail(run_id)
        return TechScoutEvidenceList(items=EVIDENCE)

    def evidence_one(self, run_id: str, evidence_id: str) -> TechScoutEvidenceProjection:
        item = next(
            (evidence for evidence in self.evidence(run_id).items if evidence.evidence_id == evidence_id),
            None,
        )
        if item is None:
            raise WebError(404, "evidence_not_found")
        return item

    def trace(self, run_id: str, limit: int, cursor: str | None) -> TracePage:
        if run_id != SYNTHETIC_RUN_ID:
            return self.registry.trace(run_id, limit, cursor)
        events = self._fixture_events()
        after = self.registry._decode_event_cursor(cursor) if cursor else 0
        remaining = events[after:]
        page = remaining[:limit]
        next_cursor = page[-1].cursor if len(remaining) > limit and page else None
        return TracePage(items=page, next_cursor=next_cursor)

    @staticmethod
    def _fixture_events() -> list[TraceEvent]:
        definitions = [
            ("stage", "plan", "completed", "Investigation plan frozen from the synthetic request.", None, None, 900),
            ("skill", "research", "completed", "Official-source fixture selected.", "official-source-research", None, 4200),
            ("tool", "verify", "completed", "Allowlisted fixture recipe completed.", "vector-store-verification", "poc.run_allowlisted", 710),
            ("stage", "decide", "completed", "Deterministic gate published the fixture decision.", None, None, 1300),
        ]
        return [
            TraceEvent(
                cursor=urlsafe_b64encode(f"event:{index}".encode("ascii")).decode("ascii"),
                event_type=event_type, stage=stage, status=status, label=label,
                skill=skill, tool=tool, duration_ms=duration,
                created_at=DETAIL.created_at + timedelta(seconds=index),
            )
            for index, (event_type, stage, status, label, skill, tool, duration) in enumerate(definitions, 1)
        ]
