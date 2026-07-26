import json

import pytest

from paper_agent.observability.evaluation_trace import (
    EvaluationCaseTrace,
    SealedExecutionReference,
)
from paper_agent.observability.sanitize import TraceDataPolicyError
from paper_agent.observability.tracing_models import (
    ScoringCorrelation,
    W3CSpanContext,
)


def _records(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding='utf-8').splitlines()
    ]


def test_fresh_scoring_supplies_pipeline_parent(tmp_path) -> None:
    external = W3CSpanContext(trace_id='9' * 32, span_id='8' * 16)
    trace = EvaluationCaseTrace.start(
        path=tmp_path / 'evaluation-traces.jsonl',
        correlation=ScoringCorrelation(
            scoring_attempt_id='score-1',
            execution_id='exec-1',
            case_id='case-1',
        ),
        parent=external,
    )

    child = trace.fresh_pipeline_parent()
    start = _records(trace.path)[0]
    assert trace.context.trace_id == external.trace_id
    assert start['parent_span_id'] == external.span_id
    assert child.execution_id == 'exec-1'
    assert child.parent == trace.context


def test_recovery_links_sealed_historical_pipeline_root(tmp_path) -> None:
    historical = SealedExecutionReference(
        execution_id='exec-old',
        trace_id='1' * 32,
        span_id='2' * 16,
        trace_sha256='a' * 64,
    )
    trace = EvaluationCaseTrace.start_reuse(
        path=tmp_path / 'evaluation-traces.jsonl',
        scoring_attempt_id='score-2',
        case_id='case-1',
        reused=historical,
    )

    start = _records(trace.path)[0]
    assert start['reused_execution_id'] == 'exec-old'
    assert start['links'][0]['trace_id'] == historical.trace_id
    assert start['links'][0]['attributes']['link.type'] == 'reused_execution'
    with pytest.raises(RuntimeError, match='cannot be reparented'):
        trace.fresh_pipeline_parent()


def test_each_scoring_attempt_owns_an_independent_sealed_file(tmp_path) -> None:
    paths = []
    for score_id in ('score-1', 'score-2'):
        trace = EvaluationCaseTrace.start(
            path=tmp_path / score_id / 'evaluation-traces.jsonl',
            correlation=ScoringCorrelation(
                scoring_attempt_id=score_id,
                execution_id='exec-1',
                case_id='case-1',
            ),
        )
        trace.finish('ok')
        paths.append(trace.path)

    assert paths[0] != paths[1]
    assert _records(paths[0])[-1]['owner_id'] == 'score-1'
    assert _records(paths[1])[-1]['owner_id'] == 'score-2'


def test_metric_events_are_allowlisted_sanitized_and_not_spans(tmp_path) -> None:
    secret = 'runtime-secret-value'
    trace = EvaluationCaseTrace.start(
        path=tmp_path / 'evaluation-traces.jsonl',
        correlation=ScoringCorrelation(
            scoring_attempt_id='score-1',
            execution_id='exec-1',
            case_id='case-1',
        ),
        secrets=(secret,),
    )
    trace.metric_event(
        'paper_agent.evaluation.metrics',
        {'metric_count': 4, 'model_name': f'model-{secret}'},
    )
    with pytest.raises(TraceDataPolicyError):
        trace.metric_event('unknown.metric', {})
    trace.finish('ok')

    records = _records(trace.path)
    assert [
        record['name']
        for record in records
        if record['record_type'] == 'span_start'
    ] == ['paper_agent.evaluation.case']
    assert secret not in trace.path.read_text(encoding='utf-8')
