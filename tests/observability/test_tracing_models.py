from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

import paper_agent.observability as observability
from paper_agent.observability.tracing_models import (
    PipelineCorrelationInput,
    RunCorrelation,
    ScoringCorrelation,
    SpanEndRecord,
    SpanEventRecord,
    SpanLink,
    SpanStartRecord,
    TraceSealRecord,
    W3CSpanContext,
)


NOW = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)


def test_tracing_models_are_available_from_observability_package() -> None:
    public_names = {
        'CorrelationMode',
        'PipelineCorrelationInput',
        'RecordType',
        'RunCorrelation',
        'ScoringCorrelation',
        'SpanEndRecord',
        'SpanEventRecord',
        'SpanLink',
        'SpanName',
        'SpanStartRecord',
        'TraceSealRecord',
        'W3CSpanContext',
    }

    assert public_names <= set(observability.__all__)


def test_pipeline_correlation_rejects_scoring_attempt_identity() -> None:
    with pytest.raises(ValidationError, match='extra_forbidden'):
        PipelineCorrelationInput(
            execution_id='exec-1',
            scoring_attempt_id='score-1',
        )


def test_scoring_correlation_requires_scoring_attempt_identity() -> None:
    with pytest.raises(ValidationError, match='scoring_attempt_id'):
        ScoringCorrelation(execution_id='exec-1', case_id='case-1')


def test_scoring_correlation_preserves_execution_identity_independently() -> None:
    correlation = ScoringCorrelation(
        scoring_attempt_id='score-1',
        execution_id='exec-1',
        case_id='case-1',
    )

    assert correlation.execution_id == 'exec-1'
    assert correlation.scoring_attempt_id == 'score-1'


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('trace_id', '0' * 32),
        ('trace_id', 'A' * 32),
        ('span_id', '0' * 16),
        ('span_id', 'B' * 16),
    ],
)
def test_w3c_context_rejects_zero_or_non_lowercase_hex_ids(
    field: str, value: str
) -> None:
    values = {'trace_id': '1' * 32, 'span_id': '2' * 16}
    values[field] = value

    with pytest.raises(ValidationError, match=field):
        W3CSpanContext(**values)


def test_run_correlation_carries_execution_and_optional_parent_context() -> None:
    parent = W3CSpanContext(trace_id='1' * 32, span_id='2' * 16)

    correlation = RunCorrelation(
        run_id='run-1',
        execution_id='exec-1',
        experiment_id='experiment-1',
        case_id='case-1',
        parent=parent,
    )

    assert correlation.execution_id == 'exec-1'
    assert correlation.parent == parent


@pytest.mark.parametrize('unsafe_value', [{'nested': 'value'}, ['value'], float('nan')])
def test_span_link_attributes_allow_only_finite_json_scalars(
    unsafe_value: object,
) -> None:
    safe = SpanLink(
        trace_id='1' * 32,
        span_id='2' * 16,
        attributes={
            'text': 'value',
            'count': 1,
            'ratio': 1.5,
            'flag': True,
            'empty': None,
        },
    )
    assert safe.attributes['count'] == 1

    with pytest.raises(ValidationError, match='safe scalar'):
        SpanLink(
            trace_id='1' * 32,
            span_id='2' * 16,
            attributes={'unsafe': unsafe_value},
        )


def test_only_two_span_names_are_allowed() -> None:
    common = {
        'timestamp': NOW,
        'trace_id': '1' * 32,
        'span_id': '2' * 16,
        'parent_span_id': None,
        'execution_id': 'exec-1',
        'correlation_mode': 'standalone',
        'attributes': {},
        'links': [],
    }
    SpanStartRecord(
        name='paper_agent.pipeline.run',
        run_id='run-1',
        **common,
    )
    SpanStartRecord(
        name='paper_agent.evaluation.case',
        scoring_attempt_id='score-1',
        case_id='case-1',
        **common,
    )

    with pytest.raises(ValidationError):
        SpanStartRecord(
            name='paper_agent.retrieval',
            run_id='run-1',
            **common,
        )


def test_reuse_link_requires_matching_reused_execution_id() -> None:
    link = SpanLink(
        trace_id='1' * 32,
        span_id='2' * 16,
        attributes={
            'link.type': 'reused_execution',
            'execution_id': 'exec-old',
        },
    )

    with pytest.raises(ValidationError, match='reused_execution_id'):
        SpanStartRecord(
            timestamp=NOW,
            trace_id='3' * 32,
            span_id='4' * 16,
            parent_span_id=None,
            name='paper_agent.evaluation.case',
            execution_id='exec-current',
            scoring_attempt_id='score-2',
            case_id='case-1',
            correlation_mode='declared_reuse_link',
            reused_execution_id='exec-other',
            attributes={},
            links=[link],
        )


def test_pipeline_start_forbids_scoring_attempt_identity() -> None:
    with pytest.raises(ValidationError, match='scoring_attempt_id'):
        SpanStartRecord(
            timestamp=NOW,
            trace_id='1' * 32,
            span_id='2' * 16,
            parent_span_id=None,
            name='paper_agent.pipeline.run',
            run_id='run-1',
            execution_id='exec-1',
            scoring_attempt_id='score-1',
            correlation_mode='standalone',
            attributes={},
            links=[],
        )


def test_fresh_child_requires_parent_and_forbids_reuse_fields() -> None:
    pipeline_fields = {
        'timestamp': NOW,
        'trace_id': '1' * 32,
        'span_id': '2' * 16,
        'name': 'paper_agent.pipeline.run',
        'run_id': 'run-1',
        'execution_id': 'exec-1',
        'correlation_mode': 'fresh_child',
        'attributes': {},
    }
    with pytest.raises(ValidationError, match='parent_span_id'):
        SpanStartRecord(parent_span_id=None, links=[], **pipeline_fields)

    evaluation_fields = {
        'timestamp': NOW,
        'trace_id': '1' * 32,
        'span_id': '2' * 16,
        'name': 'paper_agent.evaluation.case',
        'execution_id': 'exec-1',
        'scoring_attempt_id': 'score-1',
        'case_id': 'case-1',
        'correlation_mode': 'fresh_child',
        'attributes': {},
    }
    fresh = SpanStartRecord(
        parent_span_id='5' * 16,
        links=[],
        **evaluation_fields,
    )
    assert fresh.parent_span_id == '5' * 16

    link = SpanLink(
        trace_id='3' * 32,
        span_id='4' * 16,
        attributes={'execution_id': 'exec-old'},
    )
    with pytest.raises(ValidationError, match='reuse'):
        SpanStartRecord(
            parent_span_id='5' * 16,
            reused_execution_id='exec-old',
            links=[link],
            **evaluation_fields,
        )


def test_span_start_requires_owner_specific_identities() -> None:
    common = {
        'timestamp': NOW,
        'trace_id': '1' * 32,
        'span_id': '2' * 16,
        'parent_span_id': None,
        'execution_id': 'exec-1',
        'correlation_mode': 'standalone',
        'attributes': {},
        'links': [],
    }
    with pytest.raises(ValidationError, match='run_id'):
        SpanStartRecord(name='paper_agent.pipeline.run', **common)

    with pytest.raises(ValidationError, match='scoring_attempt_id'):
        SpanStartRecord(
            name='paper_agent.evaluation.case',
            case_id='case-1',
            **common,
        )


def test_event_names_are_allowlisted_by_owning_span() -> None:
    common = {
        'timestamp': NOW,
        'trace_id': '1' * 32,
        'span_id': '2' * 16,
        'status': 'ok',
        'attributes': {},
    }
    SpanEventRecord(
        span_name='paper_agent.pipeline.run',
        name='paper_agent.pipeline.retrieval',
        **common,
    )
    SpanEventRecord(
        span_name='paper_agent.evaluation.case',
        name='paper_agent.evaluation.metrics',
        **common,
    )

    with pytest.raises(ValidationError, match='allowlist'):
        SpanEventRecord(
            span_name='paper_agent.evaluation.case',
            name='paper_agent.pipeline.retrieval',
            **common,
        )


@pytest.mark.parametrize(
    ('status', 'code'),
    [('degraded', None), ('error', 'raw provider message')],
)
def test_degraded_or_error_event_requires_stable_code(
    status: str, code: str | None
) -> None:
    with pytest.raises(ValidationError, match='code'):
        SpanEventRecord(
            timestamp=NOW,
            trace_id='1' * 32,
            span_id='2' * 16,
            span_name='paper_agent.pipeline.run',
            name='paper_agent.pipeline.degradation',
            status=status,
            code=code,
            attributes={},
        )


@pytest.mark.parametrize(
    ('status', 'code'),
    [('ok', 'unexpected_code'), ('degraded', None), ('error', 'raw message')],
)
def test_span_end_status_and_code_are_consistent(
    status: str, code: str | None
) -> None:
    with pytest.raises(ValidationError, match='code'):
        SpanEndRecord(
            timestamp=NOW,
            trace_id='1' * 32,
            span_id='2' * 16,
            name='paper_agent.pipeline.run',
            status=status,
            code=code,
            duration_ms=10.5,
            attributes={},
        )


def test_trace_seal_requires_pre_seal_hash_and_record_count() -> None:
    seal = TraceSealRecord(
        timestamp=NOW,
        artifact_kind='pipeline_execution',
        owner_id='exec-1',
        record_count=3,
        pre_seal_sha256='a' * 64,
    )

    assert seal.record_type == 'trace_seal'


def test_pipeline_correlation_input_preserves_external_context() -> None:
    parent = W3CSpanContext(trace_id='1' * 32, span_id='2' * 16)

    correlation = PipelineCorrelationInput(
        execution_id='exec-1',
        experiment_id='experiment-1',
        case_id='case-1',
        parent=parent,
    )

    assert correlation.parent == parent
    assert correlation.case_id == 'case-1'


def test_declared_reuse_accepts_exactly_one_matching_link() -> None:
    link = SpanLink(
        trace_id='1' * 32,
        span_id='2' * 16,
        attributes={
            'link.type': 'reused_execution',
            'execution_id': 'exec-old',
        },
    )
    fields = {
        'timestamp': NOW,
        'trace_id': '3' * 32,
        'span_id': '4' * 16,
        'parent_span_id': None,
        'name': 'paper_agent.evaluation.case',
        'execution_id': 'exec-current',
        'scoring_attempt_id': 'score-1',
        'case_id': 'case-1',
        'correlation_mode': 'declared_reuse_link',
        'reused_execution_id': 'exec-old',
        'attributes': {},
    }

    record = SpanStartRecord(links=[link], **fields)
    assert record.links == [link]

    with pytest.raises(ValidationError, match='exactly one'):
        SpanStartRecord(links=[], **fields)
    with pytest.raises(ValidationError, match='exactly one'):
        SpanStartRecord(links=[link, link], **fields)


def test_declared_reuse_accepts_standard_link_without_adapter_metadata() -> None:
    link = SpanLink(
        trace_id='1' * 32,
        span_id='2' * 16,
        attributes={'execution_id': 'exec-old'},
    )

    record = SpanStartRecord(
        timestamp=NOW,
        trace_id='3' * 32,
        span_id='4' * 16,
        parent_span_id=None,
        name='paper_agent.evaluation.case',
        execution_id='exec-current',
        scoring_attempt_id='score-1',
        case_id='case-1',
        correlation_mode='declared_reuse_link',
        reused_execution_id='exec-old',
        attributes={},
        links=[link],
    )

    assert record.links == [link]


@pytest.mark.parametrize(
    ('overrides', 'message'),
    [
        ({'schema_version': '1.1'}, 'literal_error'),
        ({'timestamp': datetime(2026, 7, 23, 12)}, 'UTC-aware'),
        ({'unexpected': True}, 'extra_forbidden'),
    ],
)
def test_trace_records_require_exact_schema_utc_and_no_extra_fields(
    overrides: dict[str, object], message: str
) -> None:
    values = {
        'timestamp': NOW,
        'trace_id': '1' * 32,
        'span_id': '2' * 16,
        'name': 'paper_agent.pipeline.run',
        'status': 'ok',
        'duration_ms': 1.0,
        'attributes': {},
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        SpanEndRecord(**values)


@pytest.mark.parametrize(
    ('field', 'value'),
    [('owner_id', '  '), ('record_count', -1), ('pre_seal_sha256', 'A' * 64)],
)
def test_trace_seal_rejects_invalid_fields(field: str, value: object) -> None:
    values = {
        'timestamp': NOW,
        'artifact_kind': 'pipeline_execution',
        'owner_id': 'exec-1',
        'record_count': 3,
        'pre_seal_sha256': 'a' * 64,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        TraceSealRecord(**values)


@pytest.mark.parametrize(
    'event_name',
    [
        'paper_agent.pipeline.run.started',
        'paper_agent.pipeline.analysis',
        'paper_agent.pipeline.retrieval',
        'paper_agent.pipeline.fulltext',
        'paper_agent.pipeline.rerank',
        'paper_agent.pipeline.synthesis',
        'paper_agent.pipeline.citation_validation',
        'paper_agent.pipeline.output',
        'paper_agent.pipeline.degradation',
        'paper_agent.pipeline.run.finished',
    ],
)
def test_all_pipeline_event_names_are_allowed(event_name: str) -> None:
    SpanEventRecord(
        timestamp=NOW,
        trace_id='1' * 32,
        span_id='2' * 16,
        span_name='paper_agent.pipeline.run',
        name=event_name,
        status='ok',
        attributes={},
    )
