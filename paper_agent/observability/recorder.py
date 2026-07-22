from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from paper_agent.fulltext.models import DocumentRecord
from paper_agent.io import append_json_line, create_run_dir, write_json
from paper_agent.modeling import StrictModel
from paper_agent.observability.models import (
    ManifestStatus,
    RetrievalRecord,
    RunCounts,
    RunEvent,
    RunIssue,
    RunManifest,
    SafeRunSettings,
    UsageTotals,
)
from paper_agent.observability.sanitize import sanitize_event_data
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import CheckedPaperAnalysis, CheckedSurveyReport


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunRecorder:
    def __init__(
        self,
        *,
        run_dir: Path,
        manifest: RunManifest,
        clock: Callable[[], datetime],
    ) -> None:
        self.run_dir = run_dir
        self.run_id = manifest.run_id
        self._manifest = manifest
        self._clock = clock

    @classmethod
    def start(
        cls,
        *,
        output_base: Path,
        question: str,
        requested_limit: int,
        no_pdf: bool,
        safe_settings: SafeRunSettings,
        component_versions: Mapping[str, str],
        clock: Callable[[], datetime] = utc_now,
    ) -> RunRecorder:
        started_at = clock()
        run_dir = create_run_dir(output_base, question)
        manifest = RunManifest(
            run_id=run_dir.name,
            status="running",
            question=question,
            requested_limit=requested_limit,
            no_pdf=no_pdf,
            started_at=started_at,
            settings=safe_settings,
            counts=RunCounts(
                selected_papers=0,
                pdf_documents=0,
                abstract_documents=0,
                explicit_abstract_documents=0,
                pdf_fallback_documents=0,
                excluded_papers=0,
                successful_analyses=0,
                evidence_items=0,
            ),
            stage_elapsed_seconds={},
            usage=UsageTotals(operations=0, http_attempts=0),
            component_versions=dict(component_versions),
        )
        recorder = cls(run_dir=run_dir, manifest=manifest, clock=clock)
        recorder._write_manifest()
        (run_dir / "logs.jsonl").touch(exist_ok=False)
        return recorder

    def write_papers(self, papers: Sequence[Paper]) -> None:
        self._require_running()
        self._write_models("papers.json", papers)

    def write_documents(self, records: Sequence[DocumentRecord]) -> None:
        self._require_running()
        self._write_models("documents.json", records)

    def write_evidence(self, evidence: Sequence[Evidence]) -> None:
        self._require_running()
        self._write_models("evidence.json", evidence)

    def write_analyses(self, analyses: Sequence[CheckedPaperAnalysis]) -> None:
        self._require_running()
        self._write_models("analyses.json", analyses)

    def publish_report(self, report: CheckedSurveyReport, markdown: str) -> None:
        self._require_running()
        json_text = json.dumps(
            report.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        prepared: list[Path] = []
        try:
            prepared.append(
                self._prepare_temporary(self.run_dir / "report.json", json_text)
            )
            prepared.append(
                self._prepare_temporary(self.run_dir / "report.md", markdown)
            )
            prepared[0].replace(self.run_dir / "report.json")
            prepared[1].replace(self.run_dir / "report.md")
        finally:
            for temporary in prepared:
                temporary.unlink(missing_ok=True)

    def emit(self, event: RunEvent) -> None:
        self._require_running()
        sanitized = sanitize_event_data(event.model_dump(mode="json"), secrets=())
        safe_event = RunEvent.model_validate(sanitized)
        append_json_line(
            self.run_dir / "logs.jsonl", safe_event.model_dump(mode="json")
        )

    def complete(
        self,
        *,
        status: Literal["completed", "completed_with_degradation"],
        counts: RunCounts,
        retrieval_outcomes: Sequence[RetrievalRecord],
        stage_elapsed_seconds: Mapping[str, float],
        usage: UsageTotals,
        degradations: Sequence[RunIssue] = (),
    ) -> None:
        self._transition(
            status=status,
            counts=counts,
            retrieval_outcomes=retrieval_outcomes,
            stage_elapsed_seconds=stage_elapsed_seconds,
            usage=usage,
            degradations=degradations,
            errors=(),
        )

    def fail(
        self,
        *,
        stage: str,
        code: str,
        counts: RunCounts,
        retrieval_outcomes: Sequence[RetrievalRecord],
        stage_elapsed_seconds: Mapping[str, float],
        usage: UsageTotals,
        degradations: Sequence[RunIssue] = (),
        paper_id: str | None = None,
        message: str | None = None,
    ) -> None:
        safe_issue = RunIssue.model_validate(
            sanitize_event_data(
                {
                    "stage": stage,
                    "code": code,
                    "paper_id": paper_id,
                    "message": message,
                },
                secrets=(),
            )
        )
        self.emit(
            RunEvent(
                timestamp=self._clock(),
                run_id=self.run_id,
                stage=stage,
                operation="finalize_run",
                status="error",
                paper_id=paper_id,
                code=code,
                attributes={},
            )
        )
        self._transition(
            status="failed",
            counts=counts,
            retrieval_outcomes=retrieval_outcomes,
            stage_elapsed_seconds=stage_elapsed_seconds,
            usage=usage,
            degradations=degradations,
            errors=(safe_issue,),
        )

    def _transition(
        self,
        *,
        status: ManifestStatus,
        counts: RunCounts,
        retrieval_outcomes: Sequence[RetrievalRecord],
        stage_elapsed_seconds: Mapping[str, float],
        usage: UsageTotals,
        degradations: Sequence[RunIssue],
        errors: Sequence[RunIssue],
    ) -> None:
        if self._manifest.status != "running":
            if self._manifest.status == status:
                return
            raise RuntimeError(f"run is already terminal as {self._manifest.status}")
        manifest_values = self._manifest.model_dump()
        manifest_values.update(
            {
                "status": status,
                "finished_at": self._clock(),
                "counts": counts,
                "retrieval_outcomes": list(retrieval_outcomes),
                "stage_elapsed_seconds": dict(stage_elapsed_seconds),
                "usage": usage,
                "degradations": list(degradations),
                "errors": list(errors),
            }
        )
        terminal_manifest = RunManifest.model_validate(manifest_values)
        self._write_manifest(terminal_manifest)
        self._manifest = terminal_manifest

    def _require_running(self) -> None:
        if self._manifest.status != "running":
            raise RuntimeError(f"run is already terminal as {self._manifest.status}")

    def _write_manifest(self, manifest: RunManifest | None = None) -> None:
        write_json(
            self.run_dir / "run_manifest.json",
            (manifest or self._manifest).model_dump(mode="json"),
        )

    def _write_models(self, name: str, values: Sequence[StrictModel]) -> None:
        write_json(
            self.run_dir / name,
            [value.model_dump(mode="json") for value in values],
        )

    @staticmethod
    def _prepare_temporary(target: Path, text: str) -> Path:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(text)
                temporary_file.flush()
            return temporary_path
        except BaseException:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
