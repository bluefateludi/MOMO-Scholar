from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from paper_agent.observability.tracing_models import (
    EVALUATION_EVENT_NAMES,
    PIPELINE_EVENT_NAMES,
    SafeScalar,
    SpanLink,
)


_SPAN_KINDS = {
    'paper_agent.pipeline.run': 'CHAIN',
    'paper_agent.evaluation.case': 'EVALUATOR',
}
_SEMANTIC_NAMES = {
    'run_id': 'paper_agent.run.id',
    'execution_id': 'paper_agent.execution.id',
    'scoring_attempt_id': 'paper_agent.scoring_attempt.id',
    'reused_execution_id': 'paper_agent.reused_execution.id',
    'experiment_id': 'paper_agent.experiment.id',
    'case_id': 'paper_agent.case.id',
}
_EVENT_ATTRIBUTE_NAMES = frozenset(
    {
        *_SEMANTIC_NAMES,
        'requested_limit',
        'no_pdf',
        'operation',
        'returned_paper_count',
        'paper_id',
        'document_available',
        'chunk_count',
        'warning_count',
        'requested_mode',
        'actual_mode',
        'evidence_count',
        'returned_evidence_count',
        'attempts',
        'scope',
        'sanitized_reference_count',
        'dropped_finding_count',
        'analysis_count',
        'sanitized_claim_count',
        'published',
        'paper_count',
        'document_count',
        'degradation_count',
        'selected_paper_count',
        'failure_stage',
        'metric_count',
        'model_name',
        'duration_ms',
        'prompt_tokens',
        'completion_tokens',
        'total_tokens',
    }
)


@dataclass(frozen=True)
class MappedEvent:
    name: str
    attributes: dict[str, SafeScalar]


@dataclass(frozen=True)
class MappedLink:
    trace_id: str
    span_id: str
    attributes: dict[str, SafeScalar]


def map_span_kind(name: str) -> str:
    try:
        return _SPAN_KINDS[name]
    except KeyError as error:
        raise ValueError('unknown trace span name') from error


def map_event(
    name: str,
    attributes: Mapping[str, SafeScalar],
) -> MappedEvent:
    if name not in PIPELINE_EVENT_NAMES | EVALUATION_EVENT_NAMES:
        raise ValueError('unknown trace event name')
    if not set(attributes) <= _EVENT_ATTRIBUTE_NAMES:
        raise ValueError('unknown trace event attribute')
    return MappedEvent(
        name=name,
        attributes={
            _SEMANTIC_NAMES.get(key, f'paper_agent.event.{key}'): value
            for key, value in attributes.items()
        },
    )


def map_link(link: SpanLink) -> MappedLink:
    allowed = {'execution_id', 'trace_sha256', 'link.type'}
    if not set(link.attributes) <= allowed:
        raise ValueError('unknown trace link attribute')
    mapped = {
        _SEMANTIC_NAMES.get(key, f'paper_agent.link.{key}'): value
        for key, value in link.attributes.items()
    }
    return MappedLink(
        trace_id=link.trace_id,
        span_id=link.span_id,
        attributes=mapped,
    )
