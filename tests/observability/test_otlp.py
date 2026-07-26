import builtins
from types import SimpleNamespace

import pytest

from paper_agent.config import ObservabilityConfigurationError
from paper_agent.observability.otlp import (
    OtlpTraceExporter,
    TraceExportError,
    _load_otel,
    _validate_replayed_span,
)
from paper_agent.observability.trace_store import inspect_trace_file
from paper_agent.observability.run_trace import PipelineRunTrace
from paper_agent.observability.tracing_models import RunCorrelation


def _sealed_trace(tmp_path):
    trace = PipelineRunTrace.start(
        path=tmp_path / 'traces.jsonl',
        correlation=RunCorrelation(run_id='run-1', execution_id='exec-1'),
        root_attributes={},
    )
    trace.finish('ok')
    return trace.path


def test_optional_imports_are_lazy(tmp_path, monkeypatch) -> None:
    path = _sealed_trace(tmp_path)
    real_import = builtins.__import__

    def block_otel(name, *args, **kwargs):
        if name.startswith('opentelemetry'):
            raise ImportError('blocked')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', block_otel)
    assert path.exists()
    with pytest.raises(ObservabilityConfigurationError):
        _load_otel()


def test_failure_threshold_is_per_exporter_instance(tmp_path) -> None:
    path = _sealed_trace(tmp_path)
    calls = []
    warnings = []

    def fail_replay(*args, **kwargs) -> None:
        calls.append('transport')
        raise RuntimeError('private transport detail')

    exporter = OtlpTraceExporter(
        endpoint='https://collector.example.test/v1/traces',
        headers={'Authorization': 'secret'},
        timeout_seconds=5,
        failure_threshold=2,
        replay=fail_replay,
        health_warning=warnings.append,
    )
    for _ in range(2):
        with pytest.raises(TraceExportError) as caught:
            exporter.export_file(path)
        assert 'private transport detail' not in str(caught.value)
    assert exporter.disabled
    assert not exporter.export_file(path)
    assert calls == ['transport', 'transport']
    assert warnings == ['otlp_export_failed']


def test_replay_receives_sealed_records_without_mutation(tmp_path) -> None:
    path = _sealed_trace(tmp_path)
    before = path.read_bytes()
    captured = []

    def capture(inspection, **kwargs) -> None:
        captured.extend(inspection.records)

    exporter = OtlpTraceExporter(
        endpoint='https://collector.example.test/v1/traces',
        headers={},
        timeout_seconds=5,
        failure_threshold=2,
        replay=capture,
    )
    assert exporter.export_file(path)
    assert path.read_bytes() == before
    assert captured[0].trace_id == captured[-2].trace_id


def test_replayed_span_identity_is_checked_before_export(tmp_path) -> None:
    start = inspect_trace_file(_sealed_trace(tmp_path)).records[0]
    context = SimpleNamespace(
        trace_id=int(start.trace_id, 16),
        span_id=int(start.span_id, 16),
    )
    span = SimpleNamespace(
        get_span_context=lambda: context,
        parent=None,
        links=[],
    )

    _validate_replayed_span(span, start)
    context.span_id += 1

    with pytest.raises(TraceExportError, match='changed span identity'):
        _validate_replayed_span(span, start)
