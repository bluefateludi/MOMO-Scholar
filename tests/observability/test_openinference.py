import pytest

from paper_agent.observability.openinference import (
    map_event,
    map_link,
    map_span_kind,
)
from paper_agent.observability.tracing_models import SpanLink


@pytest.mark.parametrize(
    ('name', 'kind'),
    [
        ('paper_agent.pipeline.run', 'CHAIN'),
        ('paper_agent.evaluation.case', 'EVALUATOR'),
    ],
)
def test_only_final_span_names_map(name: str, kind: str) -> None:
    assert map_span_kind(name) == kind


def test_pipeline_events_map_without_becoming_spans() -> None:
    mapped = map_event(
        'paper_agent.pipeline.retrieval',
        {'execution_id': 'exec-1', 'returned_evidence_count': 3},
    )
    assert mapped.name == 'paper_agent.pipeline.retrieval'
    assert mapped.attributes['paper_agent.execution.id'] == 'exec-1'


def test_reuse_link_preserves_context_and_safe_attributes() -> None:
    mapped = map_link(
        SpanLink(
            trace_id='1' * 32,
            span_id='2' * 16,
            attributes={
                'execution_id': 'exec-old',
                'link.type': 'reused_execution',
            },
        )
    )
    assert mapped.trace_id == '1' * 32
    assert mapped.span_id == '2' * 16
    assert mapped.attributes['paper_agent.execution.id'] == 'exec-old'


def test_unknown_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        map_span_kind('paper_agent.pipeline.search')
    with pytest.raises(ValueError):
        map_event('paper_agent.pipeline.search', {})
    with pytest.raises(ValueError):
        map_event('paper_agent.pipeline.analysis', {'private_payload': 'x'})
