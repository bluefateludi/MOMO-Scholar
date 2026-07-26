from __future__ import annotations

import secrets as secure_random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from pydantic import Field, field_validator

from paper_agent.modeling import StrictModel
from paper_agent.observability.sanitize import (
    validate_event_attributes,
    validate_trace_attributes,
)
from paper_agent.observability.trace_store import TraceFileWriter
from paper_agent.observability.tracing_models import (
    PipelineCorrelationInput,
    ScoringCorrelation,
    SpanEndRecord,
    SpanEventRecord,
    SpanLink,
    SpanStartRecord,
    SpanStatus,
    W3CSpanContext,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SealedExecutionReference(W3CSpanContext):
    execution_id: str = Field(min_length=1)
    trace_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @field_validator('execution_id')
    @classmethod
    def execution_id_is_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('execution_id must not be blank')
        return value


class EvaluationCaseTrace:
    def __init__(
        self,
        *,
        writer: TraceFileWriter,
        context: W3CSpanContext,
        correlation: ScoringCorrelation,
        started_monotonic: float,
        fresh: bool,
        secrets: tuple[str, ...],
    ) -> None:
        self.path = writer.path
        self.context = context
        self._writer = writer
        self._correlation = correlation
        self._started_monotonic = started_monotonic
        self._fresh = fresh
        self._secrets = secrets
        self._finished = False

    @classmethod
    def start(
        cls,
        *,
        path: Path,
        correlation: ScoringCorrelation,
        parent: W3CSpanContext | None = None,
        secrets: tuple[str, ...] = (),
    ) -> EvaluationCaseTrace:
        context = W3CSpanContext(
            trace_id=(
                parent.trace_id
                if parent is not None
                else secure_random.token_hex(16)
            ),
            span_id=secure_random.token_hex(8),
        )
        writer = TraceFileWriter.create(
            path,
            artifact_kind='evaluation_scoring_attempt',
            owner_id=correlation.scoring_attempt_id,
        )
        writer.append(
            SpanStartRecord(
                timestamp=_utc_now(),
                trace_id=context.trace_id,
                span_id=context.span_id,
                parent_span_id=parent.span_id if parent is not None else None,
                name='paper_agent.evaluation.case',
                execution_id=correlation.execution_id,
                scoring_attempt_id=correlation.scoring_attempt_id,
                case_id=correlation.case_id,
                correlation_mode=(
                    'fresh_child' if parent is not None else 'standalone'
                ),
                attributes=validate_trace_attributes({}, secrets=secrets),
                links=[],
            )
        )
        return cls(
            writer=writer,
            context=context,
            correlation=correlation,
            started_monotonic=time.monotonic(),
            fresh=True,
            secrets=secrets,
        )

    @classmethod
    def start_reuse(
        cls,
        *,
        path: Path,
        scoring_attempt_id: str,
        case_id: str,
        reused: SealedExecutionReference,
        secrets: tuple[str, ...] = (),
    ) -> EvaluationCaseTrace:
        correlation = ScoringCorrelation(
            scoring_attempt_id=scoring_attempt_id,
            execution_id=reused.execution_id,
            case_id=case_id,
        )
        context = W3CSpanContext(
            trace_id=secure_random.token_hex(16),
            span_id=secure_random.token_hex(8),
        )
        writer = TraceFileWriter.create(
            path,
            artifact_kind='evaluation_scoring_attempt',
            owner_id=scoring_attempt_id,
        )
        writer.append(
            SpanStartRecord(
                timestamp=_utc_now(),
                trace_id=context.trace_id,
                span_id=context.span_id,
                parent_span_id=None,
                name='paper_agent.evaluation.case',
                execution_id=reused.execution_id,
                scoring_attempt_id=scoring_attempt_id,
                case_id=case_id,
                correlation_mode='declared_reuse_link',
                reused_execution_id=reused.execution_id,
                attributes=validate_trace_attributes({}, secrets=secrets),
                links=[
                    SpanLink(
                        trace_id=reused.trace_id,
                        span_id=reused.span_id,
                        attributes={
                            'link.type': 'reused_execution',
                            'execution_id': reused.execution_id,
                            'trace_sha256': reused.trace_sha256,
                        },
                    )
                ],
            )
        )
        return cls(
            writer=writer,
            context=context,
            correlation=correlation,
            started_monotonic=time.monotonic(),
            fresh=False,
            secrets=secrets,
        )

    def fresh_pipeline_parent(self) -> PipelineCorrelationInput:
        self._require_active()
        if not self._fresh:
            raise RuntimeError('reused execution cannot be reparented')
        return PipelineCorrelationInput(
            execution_id=self._correlation.execution_id,
            case_id=self._correlation.case_id,
            parent=self.context,
        )

    def metric_event(
        self,
        name: str,
        attributes: Mapping[str, Any],
        *,
        status: SpanStatus = 'ok',
        code: str | None = None,
    ) -> None:
        self._require_active()
        safe_attributes = validate_event_attributes(
            name,
            attributes,
            secrets=self._secrets,
        )
        self._writer.append(
            SpanEventRecord(
                timestamp=_utc_now(),
                trace_id=self.context.trace_id,
                span_id=self.context.span_id,
                span_name='paper_agent.evaluation.case',
                name=name,
                status=status,
                code=code,
                attributes=safe_attributes,
            )
        )

    def finish(self, status: SpanStatus, code: str | None = None) -> str:
        self._require_active()
        self._writer.append(
            SpanEndRecord(
                timestamp=_utc_now(),
                trace_id=self.context.trace_id,
                span_id=self.context.span_id,
                name='paper_agent.evaluation.case',
                status=status,
                code=code,
                duration_ms=(
                    time.monotonic() - self._started_monotonic
                ) * 1000,
                attributes={},
            )
        )
        self._finished = True
        return self._writer.seal(timestamp=_utc_now())

    def _require_active(self) -> None:
        if self._finished:
            raise RuntimeError('evaluation trace is already finished')
