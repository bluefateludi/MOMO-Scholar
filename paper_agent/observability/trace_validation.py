from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal
from collections.abc import Mapping, Sequence

from pydantic import Field

from paper_agent.io import write_json
from paper_agent.modeling import StrictModel
from paper_agent.observability.models import RunManifest
from paper_agent.observability.trace_store import (
    TraceFileInspection,
    TraceIntegrityError,
    TracePersistenceError,
    inspect_trace_file,
)
from paper_agent.observability.tracing_models import (
    SpanEndRecord,
    SpanEventRecord,
    SpanStartRecord,
)


PipelineOutcome = Literal['success', 'degraded', 'failed', 'unknown']
ValidationCorrelationMode = Literal[
    'standalone',
    'fresh_child',
    'declared_reuse_link',
]


class TraceValidationResult(StrictModel):
    enabled: bool = True
    valid: bool
    correlation_mode: ValidationCorrelationMode
    pipeline_outcome: PipelineOutcome
    finding_codes: tuple[str, ...] = ()
    required_event_coverage: float = Field(ge=0, le=1)


_SUCCESS_EVENTS = frozenset(
    {
        'paper_agent.pipeline.run.started',
        'paper_agent.pipeline.retrieval',
        'paper_agent.pipeline.fulltext',
        'paper_agent.pipeline.rerank',
        'paper_agent.pipeline.analysis',
        'paper_agent.pipeline.citation_validation',
        'paper_agent.pipeline.synthesis',
        'paper_agent.pipeline.output',
        'paper_agent.pipeline.run.finished',
    }
)
_STAGE_EVENTS = {
    'search': 'paper_agent.pipeline.retrieval',
    'acquisition': 'paper_agent.pipeline.fulltext',
    'chunking': 'paper_agent.pipeline.fulltext',
    'retrieval': 'paper_agent.pipeline.retrieval',
    'analysis': 'paper_agent.pipeline.analysis',
    'synthesis': 'paper_agent.pipeline.synthesis',
}


def validate_pipeline_trace(run_dir: Path) -> TraceValidationResult:
    findings: list[str] = []
    disabled_manifest = _read_manifest(run_dir)
    if disabled_manifest is not None and not disabled_manifest.trace_enabled:
        return _result(
            mode='standalone',
            outcome=_manifest_outcome(disabled_manifest),
            findings=[],
            coverage=1,
            enabled=False,
        )
    try:
        inspection = inspect_trace_file(run_dir / 'traces.jsonl')
    except (TraceIntegrityError, TracePersistenceError):
        return _result(
            mode='standalone',
            outcome='unknown',
            findings=['trace_integrity_invalid'],
            coverage=0,
        )

    lifecycle_findings = _validate_lifecycle(inspection)
    findings.extend(lifecycle_findings)
    manifest_path = run_dir / 'run_manifest.json'
    if not manifest_path.exists():
        findings.append('terminal_manifest_missing')
        return _result(
            mode='standalone',
            outcome='unknown',
            findings=findings,
            coverage=_event_coverage(inspection, required=set()),
        )
    try:
        manifest = RunManifest.model_validate_json(
            manifest_path.read_text(encoding='utf-8')
        )
    except (OSError, ValueError):
        findings.append('terminal_manifest_invalid')
        return _result(
            mode='standalone',
            outcome='unknown',
            findings=findings,
            coverage=0,
        )

    outcome = _manifest_outcome(manifest)
    if outcome != 'unknown' and manifest.trace_sha256 != inspection.sha256:
        findings.append('full_file_hash_mismatch')
    start = _single_start(inspection)
    if start is not None and start.execution_id != manifest.execution_id:
        findings.append('execution_identity_mismatch')
    end = _single_end(inspection)
    expected_end_status = {
        'completed': 'ok',
        'completed_with_degradation': 'degraded',
        'failed': 'error',
        'running': None,
    }[manifest.status]
    if (
        end is not None
        and expected_end_status is not None
        and end.status != expected_end_status
    ):
        findings.append('terminal_status_mismatch')

    required = {
        'paper_agent.pipeline.run.started',
        'paper_agent.pipeline.run.finished',
    }
    for stage in manifest.stage_elapsed_seconds:
        event_name = _STAGE_EVENTS.get(stage)
        if event_name is not None:
            required.add(event_name)
    if outcome in ('success', 'degraded'):
        required.update(_SUCCESS_EVENTS)
    elif manifest.counts.successful_analyses:
        required.add('paper_agent.pipeline.citation_validation')
    if outcome == 'degraded':
        required.add('paper_agent.pipeline.degradation')
    coverage = _event_coverage(inspection, required=required)
    if coverage < 1:
        findings.append('required_event_missing')
    return _result(
        mode='standalone',
        outcome=outcome,
        findings=findings,
        coverage=coverage,
    )


def validate_trace_pair(
    *,
    evaluation_path: Path,
    run_dir: Path,
) -> TraceValidationResult:
    pipeline = validate_pipeline_trace(run_dir)
    findings = list(pipeline.finding_codes)
    try:
        evaluation = inspect_trace_file(evaluation_path)
        pipeline_inspection = inspect_trace_file(run_dir / 'traces.jsonl')
    except (TraceIntegrityError, TracePersistenceError):
        return _result(
            mode='fresh_child',
            outcome=pipeline.pipeline_outcome,
            findings=[*findings, 'trace_pair_integrity_invalid'],
            coverage=pipeline.required_event_coverage,
        )

    findings.extend(_validate_lifecycle(evaluation))
    evaluation_start = _single_start(evaluation)
    pipeline_start = _single_start(pipeline_inspection)
    if evaluation_start is None or pipeline_start is None:
        findings.append('trace_pair_root_missing')
        return _result(
            mode='fresh_child',
            outcome=pipeline.pipeline_outcome,
            findings=findings,
            coverage=pipeline.required_event_coverage,
        )

    if evaluation_start.correlation_mode == 'declared_reuse_link':
        mode: ValidationCorrelationMode = 'declared_reuse_link'
        link = evaluation_start.links[0] if evaluation_start.links else None
        if (
            link is None
            or link.trace_id != pipeline_start.trace_id
            or link.span_id != pipeline_start.span_id
            or evaluation_start.reused_execution_id
            != pipeline_start.execution_id
            or link.attributes.get('trace_sha256')
            != pipeline_inspection.sha256
        ):
            findings.append('reuse_link_mismatch')
    else:
        mode = 'fresh_child'
        if (
            pipeline_start.trace_id != evaluation_start.trace_id
            or pipeline_start.parent_span_id != evaluation_start.span_id
            or pipeline_start.execution_id != evaluation_start.execution_id
        ):
            findings.append('fresh_parent_mismatch')
    if evaluation_start.case_id != pipeline_start.case_id:
        findings.append('case_identity_mismatch')

    return _result(
        mode=mode,
        outcome=pipeline.pipeline_outcome,
        findings=findings,
        coverage=pipeline.required_event_coverage,
    )


def rebuild_trace_index(
    sources: Sequence[Mapping[str, object]],
    *,
    path: Path | None = None,
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    source_paths: list[Path] = []
    for source in sources:
        run_dir = Path(str(source['run_dir']))
        evaluation_value = source.get('evaluation_path')
        evaluation_path = (
            Path(str(evaluation_value))
            if evaluation_value is not None
            else None
        )
        result = (
            validate_trace_pair(
                evaluation_path=evaluation_path,
                run_dir=run_dir,
            )
            if evaluation_path is not None
            else validate_pipeline_trace(run_dir)
        )
        manifest = _read_manifest(run_dir)
        entries.append(
            {
                'run_dir': str(run_dir),
                'evaluation_path': (
                    str(evaluation_path)
                    if evaluation_path is not None
                    else None
                ),
                'execution_id': (
                    manifest.execution_id if manifest is not None else None
                ),
                'trace_sha256': (
                    manifest.trace_sha256 if manifest is not None else None
                ),
                'correlation_mode': result.correlation_mode,
                'valid': result.valid,
                'pipeline_outcome': result.pipeline_outcome,
                'finding_codes': list(result.finding_codes),
            }
        )
        source_paths.append(run_dir)
    if path is None:
        if not source_paths:
            raise ValueError('trace index requires at least one source')
        common = Path(os.path.commonpath([str(item) for item in source_paths]))
        path = common / 'trace-index.json'
    projection: dict[str, object] = {
        'projection_version': '1.0',
        'entries': entries,
    }
    write_json(path, projection)
    return projection


def _validate_lifecycle(inspection: TraceFileInspection) -> list[str]:
    starts = [
        record
        for record in inspection.records
        if isinstance(record, SpanStartRecord)
    ]
    ends = [
        record
        for record in inspection.records
        if isinstance(record, SpanEndRecord)
    ]
    findings: list[str] = []
    if len(starts) != 1:
        findings.append('span_start_count_invalid')
    if len(ends) != 1:
        findings.append('span_end_count_invalid')
    if starts and ends and (
        starts[0].trace_id != ends[0].trace_id
        or starts[0].span_id != ends[0].span_id
        or starts[0].name != ends[0].name
    ):
        findings.append('span_lifecycle_mismatch')
    if starts:
        for record in inspection.records:
            if isinstance(record, SpanEventRecord) and (
                record.trace_id != starts[0].trace_id
                or record.span_id != starts[0].span_id
            ):
                findings.append('span_event_owner_mismatch')
                break
    if not inspection.sealed:
        findings.append('trace_not_sealed')
    return findings


def _single_start(
    inspection: TraceFileInspection,
) -> SpanStartRecord | None:
    starts = [
        record
        for record in inspection.records
        if isinstance(record, SpanStartRecord)
    ]
    return starts[0] if len(starts) == 1 else None


def _single_end(
    inspection: TraceFileInspection,
) -> SpanEndRecord | None:
    ends = [
        record
        for record in inspection.records
        if isinstance(record, SpanEndRecord)
    ]
    return ends[0] if len(ends) == 1 else None


def _event_coverage(
    inspection: TraceFileInspection,
    *,
    required: set[str],
) -> float:
    if not required:
        return 1.0
    present = {
        record.name
        for record in inspection.records
        if isinstance(record, SpanEventRecord)
    }
    return len(required & present) / len(required)


def _manifest_outcome(manifest: RunManifest) -> PipelineOutcome:
    return {
        'completed': 'success',
        'completed_with_degradation': 'degraded',
        'failed': 'failed',
        'running': 'unknown',
    }[manifest.status]


def _read_manifest(run_dir: Path) -> RunManifest | None:
    try:
        return RunManifest.model_validate_json(
            (run_dir / 'run_manifest.json').read_text(encoding='utf-8')
        )
    except (OSError, ValueError):
        return None


def _result(
    *,
    mode: ValidationCorrelationMode,
    outcome: PipelineOutcome,
    findings: Sequence[str],
    coverage: float,
    enabled: bool = True,
) -> TraceValidationResult:
    unique_findings = tuple(dict.fromkeys(findings))
    return TraceValidationResult(
        enabled=enabled,
        valid=not unique_findings,
        correlation_mode=mode,
        pipeline_outcome=outcome,
        finding_codes=unique_findings,
        required_event_coverage=coverage,
    )
