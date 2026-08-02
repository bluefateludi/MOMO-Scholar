from __future__ import annotations

import json
import secrets
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
from paper_agent.observability.run_trace import PipelineRunTrace
from paper_agent.observability.trace_store import TracePersistenceError
from paper_agent.observability.tracing_models import (
    PipelineCorrelationInput,
    RunCorrelation,
    SpanStatus,
)
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
        trace: PipelineRunTrace | None = None,
        exporter_close: Callable[[], None] | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.run_id = manifest.run_id
        self._manifest = manifest
        self._clock = clock
        self._trace = trace
        self._exporter_close = exporter_close
        self._terminal_intent: ManifestStatus | None = None

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
        execution_id: str | None = None,
        trace_factory: Callable[..., PipelineRunTrace] = PipelineRunTrace.start,
        exporter_close: Callable[[], None] | None = None,
        correlation: PipelineCorrelationInput | None = None,
        trace_secrets: tuple[str, ...] = (),
        trace_enabled: bool = True,
        artifact_created_sink: Callable[[str], None] | None = None,
    ) -> RunRecorder:
        started_at = clock()
        run_dir = create_run_dir(output_base, question)
        manifest = RunManifest(
            run_id=run_dir.name,
            execution_id=(
                correlation.execution_id
                if correlation is not None
                else execution_id or secrets.token_hex(16)
            ),
            trace_enabled=trace_enabled,
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
        if artifact_created_sink is not None:
            artifact_created_sink(run_dir.name)
        if trace_enabled:
            recorder._trace = trace_factory(
                path=run_dir / 'traces.jsonl',
                correlation=RunCorrelation(
                    run_id=run_dir.name,
                    execution_id=manifest.execution_id,
                    experiment_id=(
                        correlation.experiment_id
                        if correlation is not None
                        else None
                    ),
                    case_id=(
                        correlation.case_id
                        if correlation is not None
                        else None
                    ),
                    parent=(
                        correlation.parent
                        if correlation is not None
                        else None
                    ),
                ),
                root_attributes={},
                secrets=trace_secrets,
            )
        recorder._exporter_close = exporter_close
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

    def set_exporter_close(
        self,
        callback: Callable[[], None] | None,
    ) -> None:
        self._require_running()
        self._exporter_close = callback

    def trace_event(
        self,
        name: str,
        attributes: Mapping[str, object],
        *,
        status: SpanStatus = 'ok',
        code: str | None = None,
    ) -> None:
        self._require_running()
        if self._trace is None:
            if not self._manifest.trace_enabled:
                return
            raise RuntimeError('pipeline trace is unavailable')
        self._trace.event(name, attributes, status=status, code=code)

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
        self._transition_with_trace(
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
        self._transition_with_trace(
            status="failed",
            counts=counts,
            retrieval_outcomes=retrieval_outcomes,
            stage_elapsed_seconds=stage_elapsed_seconds,
            usage=usage,
            degradations=degradations,
            errors=(safe_issue,),
        )

    def _transition_with_trace(
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
        if self._manifest.status != 'running':
            if self._manifest.status == status:
                return
            raise RuntimeError(
                f'run is already terminal as {self._manifest.status}'
            )
        if self._terminal_intent is not None:
            raise RuntimeError(
                f'run trace is already terminalized as {self._terminal_intent}'
            )
        self._terminal_intent = status
        if self._trace is None:
            if self._manifest.trace_enabled:
                raise RuntimeError('pipeline trace is unavailable')
            manifest_values = self._manifest.model_dump()
            manifest_values.update(
                {
                    'status': status,
                    'finished_at': self._clock(),
                    'counts': counts,
                    'retrieval_outcomes': list(retrieval_outcomes),
                    'stage_elapsed_seconds': dict(stage_elapsed_seconds),
                    'usage': usage,
                    'degradations': list(degradations),
                    'errors': list(errors),
                }
            )
            terminal_manifest = RunManifest.model_validate(manifest_values)
            self._write_manifest(terminal_manifest)
            self._manifest = terminal_manifest
            self._close_exporter()
            return

        span_status = {
            'completed': 'ok',
            'completed_with_degradation': 'degraded',
            'failed': 'error',
            'running': 'error',
        }[status]
        span_code = None
        if status == 'completed_with_degradation':
            span_code = 'pipeline_degraded'
        elif status == 'failed':
            span_code = errors[0].code if errors else 'pipeline_failed'

        try:
            trace_sha256 = self._trace.finish(span_status, span_code)
        except TracePersistenceError:
            persistence_issue = RunIssue(
                stage='observability',
                code='trace_persistence_failed',
            )
            manifest_values = self._manifest.model_dump()
            manifest_values.update(
                {
                    'status': 'failed',
                    'finished_at': self._clock(),
                    'counts': counts,
                    'retrieval_outcomes': list(retrieval_outcomes),
                    'stage_elapsed_seconds': dict(stage_elapsed_seconds),
                    'usage': usage,
                    'degradations': list(degradations),
                    'errors': [*errors, persistence_issue],
                    'trace_schema_version': None,
                    'trace_root_trace_id': None,
                    'trace_root_span_id': None,
                    'trace_sha256': None,
                }
            )
            failed_manifest = RunManifest.model_validate(manifest_values)
            try:
                self._write_manifest(failed_manifest)
                self._manifest = failed_manifest
            except OSError:
                pass
            raise

        manifest_values = self._manifest.model_dump()
        manifest_values.update(
            {
                'status': status,
                'finished_at': self._clock(),
                'counts': counts,
                'retrieval_outcomes': list(retrieval_outcomes),
                'stage_elapsed_seconds': dict(stage_elapsed_seconds),
                'usage': usage,
                'degradations': list(degradations),
                'errors': list(errors),
                'trace_schema_version': '1.0',
                'trace_root_trace_id': self._trace.context.trace_id,
                'trace_root_span_id': self._trace.context.span_id,
                'trace_sha256': trace_sha256,
            }
        )
        terminal_manifest = RunManifest.model_validate(manifest_values)
        self._write_manifest(terminal_manifest)
        self._manifest = terminal_manifest
        self._close_exporter()

    def _close_exporter(self) -> None:
        if self._exporter_close is None:
            return
        try:
            self._exporter_close()
        except Exception:
            warning = RunEvent(
                timestamp=self._clock(),
                run_id=self.run_id,
                stage='observability',
                operation='export_trace',
                status='error',
                code='otlp_export_failed',
                attributes={},
            )
            try:
                append_json_line(
                    self.run_dir / 'logs.jsonl',
                    warning.model_dump(mode='json'),
                )
            except OSError:
                pass

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
