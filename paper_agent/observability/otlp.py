from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
import platform
from typing import Any

from paper_agent import __version__
from paper_agent.config import ObservabilityConfigurationError
from paper_agent.observability.openinference import (
    map_event,
    map_link,
    map_span_kind,
)
from paper_agent.observability.trace_store import (
    TraceFileInspection,
    inspect_trace_file,
)
from paper_agent.observability.tracing_models import (
    SpanEndRecord,
    SpanEventRecord,
    SpanStartRecord,
)


class TraceExportError(RuntimeError):
    pass


class OtlpTraceExporter:
    def __init__(
        self,
        *,
        endpoint: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        failure_threshold: int,
        deployment_environment: str = 'local',
        replay: Callable[..., None] | None = None,
        health_warning: Callable[[str], None] | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._headers = dict(headers)
        self._timeout_seconds = timeout_seconds
        self._failure_threshold = failure_threshold
        self._deployment_environment = deployment_environment
        self._replay = replay or _replay_with_otel
        self._health_warning = health_warning
        self._failures = 0
        self._disabled = False
        self._warning_emitted = False

    @property
    def disabled(self) -> bool:
        return self._disabled

    def export_file(self, path: Path) -> bool:
        if self._disabled:
            return False
        inspection = inspect_trace_file(path)
        if not inspection.sealed:
            raise TraceExportError('only sealed trace files can be exported')
        try:
            self._replay(
                inspection,
                endpoint=self._endpoint,
                headers=self._headers,
                timeout_seconds=self._timeout_seconds,
                deployment_environment=self._deployment_environment,
            )
        except Exception as error:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._disabled = True
                if (
                    not self._warning_emitted
                    and self._health_warning is not None
                ):
                    self._health_warning('otlp_export_failed')
                    self._warning_emitted = True
            raise TraceExportError('OTLP trace export failed') from error
        return True


def _load_otel() -> dict[str, Any]:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            SpanExportResult,
            SpanProcessor,
        )
        from opentelemetry.sdk.trace.id_generator import IdGenerator
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError as error:
        raise ObservabilityConfigurationError(
            'OTLP export requires the observability extra'
        ) from error
    return {
        'trace': trace,
        'TracerProvider': TracerProvider,
        'SpanExportResult': SpanExportResult,
        'SpanProcessor': SpanProcessor,
        'IdGenerator': IdGenerator,
        'Resource': Resource,
        'OTLPSpanExporter': OTLPSpanExporter,
    }


def _replay_with_otel(
    inspection: TraceFileInspection,
    *,
    endpoint: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    deployment_environment: str,
) -> None:
    otel = _load_otel()
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
    if len(starts) != 1 or len(ends) != 1:
        raise TraceExportError('trace lifecycle is invalid')
    start = starts[0]
    end = ends[0]
    trace_api = otel['trace']
    fixed_trace_id = int(start.trace_id, 16)
    fixed_span_id = int(start.span_id, 16)
    id_generator_base = otel['IdGenerator']

    class FixedIdGenerator(id_generator_base):
        def generate_trace_id(self) -> int:
            return fixed_trace_id

        def generate_span_id(self) -> int:
            return fixed_span_id

    provider = otel['TracerProvider'](
        id_generator=FixedIdGenerator(),
        resource=otel['Resource'].create(
            {
                'service.name': 'paper-agent',
                'service.version': __version__,
                'python.version': platform.python_version(),
                'deployment.environment': deployment_environment,
                'paper_agent.trace.schema.version': '1.0',
            }
        ),
    )
    exporter = otel['OTLPSpanExporter'](
        endpoint=endpoint,
        headers=dict(headers),
        timeout=timeout_seconds,
    )
    span_processor_base = otel['SpanProcessor']

    class CapturingSpanProcessor(span_processor_base):
        def __init__(self) -> None:
            self.spans: list[Any] = []

        def on_start(self, span: Any, parent_context: Any = None) -> None:
            return None

        def on_end(self, span: Any) -> None:
            self.spans.append(span)

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    processor = CapturingSpanProcessor()
    try:
        provider.add_span_processor(processor)
        tracer = provider.get_tracer('paper_agent.observability', '1.0')
        _replay_span(
            inspection=inspection,
            start=start,
            end=end,
            trace_api=trace_api,
            tracer=tracer,
            fixed_trace_id=fixed_trace_id,
        )
        if not provider.force_flush(
            timeout_millis=int(timeout_seconds * 1000)
        ):
            raise TraceExportError('OTLP trace processor flush failed')
        if len(processor.spans) != 1:
            raise TraceExportError('OTLP replay produced invalid span count')
        _validate_replayed_span(processor.spans[0], start)
        export_result = exporter.export(tuple(processor.spans))
        if export_result != otel['SpanExportResult'].SUCCESS:
            raise TraceExportError('OTLP transport returned failure')
    finally:
        provider.shutdown()
        exporter.shutdown()


def _replay_span(
    *,
    inspection: TraceFileInspection,
    start: SpanStartRecord,
    end: SpanEndRecord,
    trace_api: Any,
    tracer: Any,
    fixed_trace_id: int,
) -> None:

    parent_context = None
    if start.parent_span_id is not None:
        parent = trace_api.SpanContext(
            trace_id=fixed_trace_id,
            span_id=int(start.parent_span_id, 16),
            is_remote=True,
            trace_flags=trace_api.TraceFlags(1),
            trace_state=trace_api.TraceState(),
        )
        parent_context = trace_api.set_span_in_context(
            trace_api.NonRecordingSpan(parent)
        )
    links = [
        trace_api.Link(
            trace_api.SpanContext(
                trace_id=int(link.trace_id, 16),
                span_id=int(link.span_id, 16),
                is_remote=True,
                trace_flags=trace_api.TraceFlags(1),
                trace_state=trace_api.TraceState(),
            ),
            attributes=map_link(link).attributes,
        )
        for link in start.links
    ]
    span = tracer.start_span(
        start.name,
        context=parent_context,
        attributes={
            'openinference.span.kind': map_span_kind(start.name),
            'paper_agent.run.id': start.run_id,
            'paper_agent.execution.id': start.execution_id,
            'paper_agent.scoring_attempt.id': start.scoring_attempt_id,
            'paper_agent.experiment.id': start.experiment_id,
            'paper_agent.case.id': start.case_id,
            'paper_agent.reused_execution.id': start.reused_execution_id,
            'paper_agent.correlation.mode': start.correlation_mode,
            **{
                f'paper_agent.start.{key}': value
                for key, value in start.attributes.items()
            },
        },
        links=links,
        start_time=_timestamp_ns(start.timestamp),
    )
    for event in inspection.records:
        if isinstance(event, SpanEventRecord):
            mapped = map_event(event.name, event.attributes)
            span.add_event(
                mapped.name,
                attributes=mapped.attributes,
                timestamp=_timestamp_ns(event.timestamp),
            )
    if end.status == 'error':
        span.set_status(
            trace_api.Status(
                trace_api.StatusCode.ERROR,
                end.code or 'trace_error',
            )
        )
    else:
        span.set_status(trace_api.Status(trace_api.StatusCode.OK))
    span.set_attribute('paper_agent.trace.status', end.status)
    span.end(end_time=_timestamp_ns(end.timestamp))


def _validate_replayed_span(span: Any, start: SpanStartRecord) -> None:
    context = span.get_span_context()
    if (
        context.trace_id != int(start.trace_id, 16)
        or context.span_id != int(start.span_id, 16)
    ):
        raise TraceExportError('OTLP replay changed span identity')
    actual_parent_id = None if span.parent is None else span.parent.span_id
    expected_parent_id = (
        None
        if start.parent_span_id is None
        else int(start.parent_span_id, 16)
    )
    if actual_parent_id != expected_parent_id:
        raise TraceExportError('OTLP replay changed parent identity')
    actual_links = [
        (link.context.trace_id, link.context.span_id)
        for link in span.links
    ]
    expected_links = [
        (int(link.trace_id, 16), int(link.span_id, 16))
        for link in start.links
    ]
    if actual_links != expected_links:
        raise TraceExportError('OTLP replay changed span links')


def preflight_otlp() -> None:
    _load_otel()


def _timestamp_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)
