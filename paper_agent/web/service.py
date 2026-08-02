from __future__ import annotations

from uuid import uuid4

from paper_agent.observability.models import RunManifest
from paper_agent.web.api_models import (
    CreateRunRequest, EvidenceList, EvidenceView, PaperAnalysisResponse, PaperList,
    ReportResponse, RunDetail, RunList, RunSummary,
)
from paper_agent.web.artifacts import ArtifactReader
from paper_agent.web.errors import WebError
from paper_agent.web.registry import RegistryRun, RunRegistry


TERMINAL = {"completed", "completed_with_degradation", "failed", "interrupted"}
SUCCESS = {"completed", "completed_with_degradation"}


class RunService:
    def __init__(self, registry: RunRegistry, artifacts: ArtifactReader, executor: object, capacity: int = 4) -> None:
        self.registry = registry
        self.artifacts = artifacts
        self.executor = executor
        self.capacity = capacity

    def create(self, request: CreateRunRequest) -> RunSummary:
        if not getattr(self.executor, "available", False):
            raise WebError(503, "execution_unavailable")
        row = self.registry.admit(str(uuid4()), request, self.capacity)
        self.executor.notify()
        return self._summary(row, None)

    def list(self, limit: int, cursor: str | None = None) -> RunList:
        rows, next_cursor = self.registry.list(limit, cursor)
        items: list[RunSummary] = []
        for row in rows:
            manifest = self._manifest_and_reconcile(row)
            items.append(self._summary(self.registry.get(row.id), manifest))
        return RunList(items=items, next_cursor=next_cursor)

    def detail(self, run_id: str) -> RunDetail:
        row = self.registry.get(run_id)
        manifest = self._manifest_and_reconcile(row)
        row = self.registry.get(run_id)
        available = self.artifacts.available(row.origin, row.artifact_run_id) if row.artifact_run_id else []
        summary = self._summary(row, manifest)
        return RunDetail(
            **summary.model_dump(),
            manifest=self.artifacts.projection(manifest) if manifest else None,
            available_artifacts=available,
        )

    def report(self, run_id: str) -> ReportResponse:
        detail = self.detail(run_id)
        if detail.status not in SUCCESS:
            raise WebError(409, "artifact_not_ready" if detail.status in {"queued", "running"} else "report_unavailable")
        assert detail.artifact_run_id and detail.manifest
        report, markdown = self.artifacts.report(detail.origin, detail.artifact_run_id)
        return ReportResponse(run_id=run_id, status=detail.status, report=report, markdown=markdown, degradations=detail.manifest.degradations)

    def evidence(self, run_id: str, paper_id: str | None = None) -> EvidenceList:
        detail = self.detail(run_id)
        if not detail.artifact_run_id:
            raise WebError(409, "artifact_not_ready")
        try:
            items = self.artifacts.evidence(detail.origin, detail.artifact_run_id)
        except WebError as error:
            if error.code == "artifact_not_found" and detail.status not in TERMINAL:
                raise WebError(409, "artifact_not_ready") from error
            raise
        return EvidenceList(items=[item for item in items if paper_id is None or item.paper_id == paper_id])

    def evidence_one(self, run_id: str, evidence_id: str) -> EvidenceView:
        for item in self.evidence(run_id).items:
            if item.evidence_id == evidence_id:
                return item
        raise WebError(404, "evidence_not_found")

    def papers(self, run_id: str) -> PaperList:
        detail = self.detail(run_id)
        if not detail.artifact_run_id:
            raise WebError(409, "artifact_not_ready")
        try:
            items = self.artifacts.papers(detail.origin, detail.artifact_run_id)
        except WebError as error:
            if error.code == "artifact_not_found" and detail.status not in TERMINAL:
                raise WebError(409, "artifact_not_ready") from error
            raise
        return PaperList(items=items)

    def paper_analysis(self, run_id: str, paper_id: str) -> PaperAnalysisResponse:
        detail = self.detail(run_id)
        if not detail.artifact_run_id:
            raise WebError(409, "artifact_not_ready")
        try:
            return self.artifacts.paper_analysis(
                detail.origin, detail.artifact_run_id, paper_id, run_id,
            )
        except WebError as error:
            if error.code == "artifact_not_found" and detail.status not in TERMINAL:
                raise WebError(409, "artifact_not_ready") from error
            raise

    def artifact(self, run_id: str, name: str):
        detail = self.detail(run_id)
        if not detail.artifact_run_id:
            raise WebError(409, "artifact_not_ready")
        return self.artifacts.validate_download(
            detail.origin, detail.artifact_run_id, name,
            terminal=detail.status in TERMINAL,
        )

    def _manifest_and_reconcile(self, row: RegistryRun) -> RunManifest | None:
        if not row.artifact_run_id:
            return None
        try:
            manifest = self.artifacts.manifest(row.origin, row.artifact_run_id)
        except WebError as error:
            if error.code == "artifact_not_found" and row.status not in TERMINAL:
                return None
            raise
        if manifest.run_id != row.artifact_run_id:
            raise WebError(409, "artifact_corrupt")
        if manifest.status != "running" and (row.status != manifest.status or row.phase != "terminal"):
            self.registry.terminal(row.id, manifest.status, finished_at=manifest.finished_at)
        return manifest

    def _summary(self, row: RegistryRun, manifest: RunManifest | None) -> RunSummary:
        successful = manifest is not None and manifest.status in SUCCESS
        has_report = bool(successful and row.artifact_run_id and all(
            name in self.artifacts.available(row.origin, row.artifact_run_id)
            for name in ("report.json", "report.md")
        ))
        return RunSummary(
            id=row.id, artifact_run_id=row.artifact_run_id, origin=row.origin,
            status=row.status, phase=row.phase, question=row.request.question,
            paper_limit=row.request.paper_limit, content_mode=row.request.content_mode,
            retrieval=row.request.retrieval, progress=row.progress,
            created_at=row.created_at, started_at=row.started_at,
            finished_at=row.finished_at, has_report=has_report,
            demo=row.origin == "bundled_demo",
        )
