from __future__ import annotations

import json

import pytest

from paper_agent.observability.run_trace import PipelineRunTrace
from paper_agent.observability.sanitize import TraceDataPolicyError
from paper_agent.observability.trace_store import inspect_trace_file
from paper_agent.observability.tracing_models import RunCorrelation, W3CSpanContext


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_synthetic_external_parent_is_preserved(tmp_path) -> None:
    parent = W3CSpanContext(trace_id='1' * 32, span_id='2' * 16)

    trace = PipelineRunTrace.start(
        path=tmp_path / 'traces.jsonl',
        correlation=RunCorrelation(
            run_id='run-1', execution_id='exec-1', parent=parent
        ),
        root_attributes={},
    )

    assert trace.context.trace_id == parent.trace_id
    assert trace.context.span_id != parent.span_id
    assert trace.context.span_id != '0' * 16
    assert _records(trace.path)[0]['parent_span_id'] == parent.span_id


def test_pipeline_trace_emits_events_but_no_child_spans(tmp_path) -> None:
    trace = PipelineRunTrace.start(
        path=tmp_path / 'traces.jsonl',
        correlation=RunCorrelation(run_id='run-1', execution_id='exec-1'),
        root_attributes={'requested_limit': 3},
    )

    trace.event(
        'paper_agent.pipeline.retrieval',
        {'returned_paper_count': 2},
    )
    digest = trace.finish(status='ok')

    records = _records(trace.path)
    assert [record['record_type'] for record in records] == [
        'span_start',
        'span_event',
        'span_end',
        'trace_seal',
    ]
    assert {
        record.get('name')
        for record in records
        if record['record_type'] == 'span_start'
    } == {'paper_agent.pipeline.run'}
    assert digest == inspect_trace_file(trace.path).sha256


def test_pipeline_trace_sanitizes_and_validates_events(tmp_path) -> None:
    trace = PipelineRunTrace.start(
        path=tmp_path / 'traces.jsonl',
        correlation=RunCorrelation(run_id='run-1', execution_id='exec-1'),
        root_attributes={},
    )

    with pytest.raises(TraceDataPolicyError):
        trace.event(
            'paper_agent.pipeline.output',
            {'authorization': 'private', 'paper_count': 2},
        )
    trace.event('paper_agent.pipeline.output', {'paper_count': 2})
    with pytest.raises(TraceDataPolicyError, match='allowlisted'):
        trace.event('paper_agent.pipeline.search', {})
    trace.finish(status='ok')

    event = _records(trace.path)[1]
    assert event['attributes'] == {'paper_count': 2}


def test_pipeline_trace_cannot_be_used_after_finish(tmp_path) -> None:
    trace = PipelineRunTrace.start(
        path=tmp_path / 'traces.jsonl',
        correlation=RunCorrelation(run_id='run-1', execution_id='exec-1'),
        root_attributes={},
    )
    trace.finish(status='error', code='run_failed')

    with pytest.raises(RuntimeError, match='already finished'):
        trace.event('paper_agent.pipeline.output', {})
    with pytest.raises(RuntimeError, match='already finished'):
        trace.finish(status='error', code='run_failed')
