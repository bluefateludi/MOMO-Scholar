from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from paper_agent.modeling import StrictModel


SafeScalar: TypeAlias = str | bool | int | float | None
CorrelationMode = Literal['standalone', 'fresh_child', 'declared_reuse_link']
SpanName = Literal['paper_agent.pipeline.run', 'paper_agent.evaluation.case']
RecordType = Literal['span_start', 'span_event', 'span_end', 'trace_seal']
SpanStatus = Literal['ok', 'degraded', 'error']
TraceArtifactKind = Literal['pipeline_execution', 'evaluation_scoring_attempt']

PIPELINE_EVENT_NAMES = frozenset(
    {
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
    }
)
EVALUATION_EVENT_NAMES = frozenset({'paper_agent.evaluation.metrics'})


def _require_nonblank(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValueError("identifier must not be blank")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError('timestamp must be UTC-aware')
    return value


def _require_w3c_id(value: str, *, length: int, label: str) -> str:
    if re.fullmatch(f'[0-9a-f]{{{length}}}', value) is None or not any(
        character != '0' for character in value
    ):
        raise ValueError(f'{label} must be a non-zero lowercase {length}-hex value')
    return value


def _validate_safe_attributes(value: object) -> object:
    if not isinstance(value, dict):
        raise ValueError('attributes must be a mapping of safe scalar values')
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError('attribute keys must be nonblank strings')
        if type(item) not in (str, bool, int, float, type(None)):
            raise ValueError('attributes accept only safe scalar values')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('attributes accept only finite safe scalar values')
    return value


class W3CSpanContext(StrictModel):
    trace_id: str
    span_id: str

    @field_validator('trace_id')
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        return _require_w3c_id(value, length=32, label='trace_id')

    @field_validator('span_id')
    @classmethod
    def validate_span_id(cls, value: str) -> str:
        return _require_w3c_id(value, length=16, label='span_id')


class SpanLink(W3CSpanContext):
    attributes: dict[str, SafeScalar] = Field(default_factory=dict)

    _attributes_are_safe_scalars = field_validator(
        'attributes', mode='before'
    )(_validate_safe_attributes)


class SpanStartRecord(W3CSpanContext):
    schema_version: Literal['1.0'] = '1.0'
    record_type: Literal['span_start'] = 'span_start'
    timestamp: datetime
    parent_span_id: str | None
    name: SpanName
    run_id: str | None = None
    execution_id: str
    scoring_attempt_id: str | None = None
    experiment_id: str | None = None
    case_id: str | None = None
    correlation_mode: CorrelationMode
    reused_execution_id: str | None = None
    attributes: dict[str, SafeScalar]
    links: list[SpanLink]

    _timestamp_is_utc = field_validator('timestamp')(_require_utc)
    _owner_ids_nonblank = field_validator(
        'run_id',
        'execution_id',
        'scoring_attempt_id',
        'experiment_id',
        'case_id',
        'reused_execution_id',
    )(_require_nonblank)
    _attributes_are_safe_scalars = field_validator(
        'attributes', mode='before'
    )(_validate_safe_attributes)

    @field_validator('parent_span_id')
    @classmethod
    def validate_parent_span_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_w3c_id(value, length=16, label='parent_span_id')

    @model_validator(mode='after')
    def validate_topology(self) -> SpanStartRecord:
        if self.name == 'paper_agent.pipeline.run':
            if self.run_id is None:
                raise ValueError('pipeline start requires run_id')
            if self.scoring_attempt_id is not None:
                raise ValueError('pipeline start forbids scoring_attempt_id')
            if self.reused_execution_id is not None or self.links:
                raise ValueError('pipeline start forbids reuse fields and links')
            if self.correlation_mode == 'declared_reuse_link':
                raise ValueError('pipeline start cannot declare a reuse link')
        elif self.scoring_attempt_id is None:
            raise ValueError('evaluation start requires scoring_attempt_id')
        if self.correlation_mode == 'fresh_child':
            if self.parent_span_id is None:
                raise ValueError('fresh_child requires parent_span_id')
            if self.reused_execution_id is not None or self.links:
                raise ValueError('fresh_child forbids reuse fields and links')
            return self
        if self.correlation_mode != 'declared_reuse_link':
            if self.reused_execution_id is not None or self.links:
                raise ValueError('non-reuse start forbids reuse fields and links')
            return self
        if self.reused_execution_id is None:
            raise ValueError('declared reuse requires reused_execution_id')
        if len(self.links) != 1:
            raise ValueError('declared reuse requires exactly one link')
        linked_execution_id = self.links[0].attributes.get('execution_id')
        if linked_execution_id != self.reused_execution_id:
            raise ValueError(
                'link execution_id must match reused_execution_id'
            )
        return self


class SpanEventRecord(W3CSpanContext):
    schema_version: Literal['1.0'] = '1.0'
    record_type: Literal['span_event'] = 'span_event'
    timestamp: datetime
    span_name: SpanName
    name: str
    status: SpanStatus
    code: str | None = None
    attributes: dict[str, SafeScalar]

    _timestamp_is_utc = field_validator('timestamp')(_require_utc)
    _attributes_are_safe_scalars = field_validator(
        'attributes', mode='before'
    )(_validate_safe_attributes)

    @model_validator(mode='after')
    def validate_event_name(self) -> SpanEventRecord:
        allowlist = (
            PIPELINE_EVENT_NAMES
            if self.span_name == 'paper_agent.pipeline.run'
            else EVALUATION_EVENT_NAMES
        )
        if self.name not in allowlist:
            raise ValueError('event name is not in the owning span allowlist')
        if self.status in ('degraded', 'error') and (
            self.code is None
            or re.fullmatch(r'[a-z0-9]+(?:[._-][a-z0-9]+)*', self.code) is None
        ):
            raise ValueError('degraded or error event requires a stable code')
        return self


class SpanEndRecord(W3CSpanContext):
    schema_version: Literal['1.0'] = '1.0'
    record_type: Literal['span_end'] = 'span_end'
    timestamp: datetime
    name: SpanName
    status: SpanStatus
    code: str | None = None
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    attributes: dict[str, SafeScalar]

    _timestamp_is_utc = field_validator('timestamp')(_require_utc)
    _attributes_are_safe_scalars = field_validator(
        'attributes', mode='before'
    )(_validate_safe_attributes)

    @model_validator(mode='after')
    def validate_status_code(self) -> SpanEndRecord:
        if self.status == 'ok':
            if self.code is not None:
                raise ValueError('ok span end forbids code')
            return self
        if self.code is None or re.fullmatch(
            r'[a-z0-9]+(?:[._-][a-z0-9]+)*', self.code
        ) is None:
            raise ValueError('degraded or error span end requires a stable code')
        return self


class TraceSealRecord(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    record_type: Literal['trace_seal'] = 'trace_seal'
    timestamp: datetime
    artifact_kind: TraceArtifactKind
    owner_id: str
    record_count: int = Field(ge=0)
    pre_seal_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    _timestamp_is_utc = field_validator('timestamp')(_require_utc)
    _owner_id_nonblank = field_validator('owner_id')(_require_nonblank)


class PipelineCorrelationInput(StrictModel):
    execution_id: str
    experiment_id: str | None = None
    case_id: str | None = None
    parent: W3CSpanContext | None = None

    _execution_id_nonblank = field_validator("execution_id")(_require_nonblank)


    _optional_ids_nonblank = field_validator(
        'experiment_id', 'case_id'
    )(_require_nonblank)


class RunCorrelation(StrictModel):
    run_id: str
    execution_id: str
    experiment_id: str | None = None
    case_id: str | None = None
    parent: W3CSpanContext | None = None

    _ids_nonblank = field_validator(
        'run_id', 'execution_id', 'experiment_id', 'case_id'
    )(_require_nonblank)


class ScoringCorrelation(StrictModel):
    scoring_attempt_id: str
    execution_id: str
    case_id: str

    _ids_nonblank = field_validator(
        "scoring_attempt_id", "execution_id", "case_id"
    )(_require_nonblank)
