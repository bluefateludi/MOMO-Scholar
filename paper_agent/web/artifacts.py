from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import TypeAdapter, ValidationError

from paper_agent.fulltext.models import DocumentRecord
from paper_agent.observability.models import RunEvent, RunManifest
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import CheckedPaperAnalysis, CheckedSurveyReport
from paper_agent.web.api_models import (
    EvidenceSource, EvidenceView, ManifestProjection, PaperAnalysisResponse,
    PaperSummary,
)
from paper_agent.web.errors import WebError


ARTIFACT_NAMES = (
    "papers.json", "documents.json", "evidence.json", "analyses.json",
    "report.json", "report.md", "run_manifest.json", "logs.jsonl",
)
CONTENT_TYPES = {
    "report.md": "text/markdown; charset=utf-8",
    "logs.jsonl": "application/x-ndjson",
}
T = TypeVar("T")


class ArtifactReader:
    def __init__(self, output_root: Path, demo_root: Path | None = None, max_bytes: int = 25_000_000) -> None:
        self.output_root = output_root.resolve()
        self.demo_root = demo_root.resolve() if demo_root else None
        self.max_bytes = max_bytes

    def run_dir(self, origin: str, artifact_run_id: str) -> Path:
        root = self.output_root if origin == "live" else self.demo_root
        if root is None or not artifact_run_id or Path(artifact_run_id).name != artifact_run_id or any(c in artifact_run_id for c in ("/", "\\")):
            raise WebError(409, "artifact_corrupt")
        candidate = root / artifact_run_id
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise WebError(409, "artifact_corrupt") from exc
        if candidate.is_symlink() or resolved.parent != root or not resolved.is_dir():
            raise WebError(409, "artifact_corrupt")
        return resolved

    def path(self, origin: str, artifact_run_id: str, name: str, *, terminal: bool = True) -> Path:
        if name not in ARTIFACT_NAMES:
            raise WebError(404, "artifact_not_found")
        run_dir = self.run_dir(origin, artifact_run_id)
        candidate = run_dir / name
        if not candidate.exists():
            raise WebError(404 if terminal else 409, "artifact_not_found" if terminal else "artifact_not_ready")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise WebError(409, "artifact_corrupt") from exc
        if candidate.is_symlink() or resolved.parent != run_dir or not resolved.is_file():
            raise WebError(404, "artifact_not_found")
        if resolved.stat().st_size > self.max_bytes:
            raise WebError(409, "artifact_corrupt")
        return resolved

    def text(self, origin: str, artifact_run_id: str, name: str, *, terminal: bool = True) -> str:
        try:
            return self.path(origin, artifact_run_id, name, terminal=terminal).read_bytes().decode("utf-8")
        except UnicodeError as exc:
            raise WebError(409, "artifact_corrupt") from exc

    def model(self, origin: str, artifact_run_id: str, name: str, model_type: type[T], *, terminal: bool = True) -> T:
        try:
            return TypeAdapter(model_type).validate_json(self.text(origin, artifact_run_id, name, terminal=terminal))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise WebError(409, "artifact_corrupt") from exc

    def manifest(self, origin: str, artifact_run_id: str) -> RunManifest:
        return self.model(origin, artifact_run_id, "run_manifest.json", RunManifest)

    def projection(self, manifest: RunManifest) -> ManifestProjection:
        return ManifestProjection(
            counts=manifest.counts, retrieval_outcomes=manifest.retrieval_outcomes,
            degradations=manifest.degradations, errors=manifest.errors,
            stage_elapsed_seconds=manifest.stage_elapsed_seconds, usage=manifest.usage,
            settings=manifest.settings, component_versions=manifest.component_versions,
        )

    def available(self, origin: str, artifact_run_id: str) -> list[str]:
        run_dir = self.run_dir(origin, artifact_run_id)
        return [name for name in ARTIFACT_NAMES if (run_dir / name).is_file() and not (run_dir / name).is_symlink()]

    def report(self, origin: str, artifact_run_id: str) -> tuple[CheckedSurveyReport, str]:
        return (
            self.model(origin, artifact_run_id, "report.json", CheckedSurveyReport),
            self.text(origin, artifact_run_id, "report.md"),
        )

    def evidence(self, origin: str, artifact_run_id: str) -> list[EvidenceView]:
        evidence = self.model(origin, artifact_run_id, "evidence.json", list[Evidence])
        papers = self.model(origin, artifact_run_id, "papers.json", list[Paper])
        documents = self.model(origin, artifact_run_id, "documents.json", list[DocumentRecord])
        paper_by_id = {item.paper_id: item for item in papers}
        document_by_id = {item.paper_id: item for item in documents}
        items: list[EvidenceView] = []
        for item in evidence:
            paper = paper_by_id.get(item.paper_id)
            document = document_by_id.get(item.paper_id)
            items.append(EvidenceView(
                **item.model_dump(),
                source=EvidenceSource(
                    title=paper.title if paper else None, url=paper.url if paper else None,
                    pdf_url=paper.pdf_url if paper else None,
                    content_source=document.content_source if document else None,
                    fallback_code=document.fallback_code if document else None,
                ),
            ))
        return items

    def papers(self, origin: str, artifact_run_id: str) -> list[PaperSummary]:
        papers = self.model(origin, artifact_run_id, "papers.json", list[Paper])
        documents = self.model(origin, artifact_run_id, "documents.json", list[DocumentRecord])
        analyses = self.model(origin, artifact_run_id, "analyses.json", list[CheckedPaperAnalysis])
        evidence = self.model(origin, artifact_run_id, "evidence.json", list[Evidence])
        document_by_id = {item.paper_id: item for item in documents}
        analysis_ids = {item.paper_id for item in analyses}
        evidence_counts: dict[str, int] = {}
        for item in evidence:
            evidence_counts[item.paper_id] = evidence_counts.get(item.paper_id, 0) + 1
        return [
            PaperSummary(
                **paper.model_dump(),
                document=document_by_id.get(paper.paper_id),
                analysis_available=paper.paper_id in analysis_ids,
                evidence_count=evidence_counts.get(paper.paper_id, 0),
            )
            for paper in papers
        ]

    def paper_analysis(
        self, origin: str, artifact_run_id: str, paper_id: str, run_id: str,
    ) -> PaperAnalysisResponse:
        papers = self.model(origin, artifact_run_id, "papers.json", list[Paper])
        documents = self.model(origin, artifact_run_id, "documents.json", list[DocumentRecord])
        analyses = self.model(origin, artifact_run_id, "analyses.json", list[CheckedPaperAnalysis])
        paper = next((item for item in papers if item.paper_id == paper_id), None)
        analysis = next((item for item in analyses if item.paper_id == paper_id), None)
        if paper is None or analysis is None:
            raise WebError(404, "paper_not_found")
        document = next((item for item in documents if item.paper_id == paper_id), None)
        return PaperAnalysisResponse(
            run_id=run_id, paper=paper, document=document, analysis=analysis,
        )

    def validate_download(self, origin: str, artifact_run_id: str, name: str, *, terminal: bool) -> Path:
        path = self.path(origin, artifact_run_id, name, terminal=terminal)
        if name == "papers.json": self.model(origin, artifact_run_id, name, list[Paper], terminal=terminal)
        elif name == "documents.json": self.model(origin, artifact_run_id, name, list[DocumentRecord], terminal=terminal)
        elif name == "evidence.json": self.model(origin, artifact_run_id, name, list[Evidence], terminal=terminal)
        elif name == "analyses.json": self.model(origin, artifact_run_id, name, list[CheckedPaperAnalysis], terminal=terminal)
        elif name == "report.json": self.model(origin, artifact_run_id, name, CheckedSurveyReport, terminal=terminal)
        elif name == "run_manifest.json": self.model(origin, artifact_run_id, name, RunManifest, terminal=terminal)
        elif name == "logs.jsonl":
            try:
                for line in self.text(origin, artifact_run_id, name, terminal=terminal).splitlines():
                    RunEvent.model_validate_json(line)
            except (ValidationError, ValueError) as exc:
                raise WebError(409, "artifact_corrupt") from exc
        else:
            self.text(origin, artifact_run_id, name, terminal=terminal)
        return path

    @staticmethod
    def content_type(name: str) -> str:
        return CONTENT_TYPES.get(name, "application/json")
