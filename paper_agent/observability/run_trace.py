from __future__ import annotations

import secrets as secure_random
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_agent.observability.sanitize import (
    validate_event_attributes,
    validate_trace_attributes,
)
from paper_agent.observability.trace_store import TraceFileWriter
from paper_agent.observability.tracing_models import (
    RunCorrelation,
    SpanEndRecord,
    SpanEventRecord,
    SpanStartRecord,
    SpanStatus,
    W3CSpanContext,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineRunTrace:
    def __init__(
        self,
        *,
        writer: TraceFileWriter,
        context: W3CSpanContext,
        started_monotonic: float,
        secrets: tuple[str, ...],
    ) -> None:
        self.path = writer.path
        self.context = context
        self._writer = writer
        self._started_monotonic = started_monotonic
        self._secrets = secrets
        self._finished = False

    @classmethod
    def start(
        cls,
        *,
        path: Path,
        correlation: RunCorrelation,
        root_attributes: Mapping[str, Any],
        secrets: tuple[str, ...] = (),
    ) -> PipelineRunTrace:
        trace_id = (
            correlation.parent.trace_id
            if correlation.parent is not None
            else secure_random.token_hex(16)
        )
        context = W3CSpanContext(
            trace_id=trace_id,
            span_id=secure_random.token_hex(8),
        )
        writer = TraceFileWriter.create(
            path,
            artifact_kind='pipeline_execution',
            owner_id=correlation.execution_id,
        )
        if writer.sealed:
            raise RuntimeError('pipeline trace is already sealed')
        attributes = validate_trace_attributes(
            root_attributes,
            secrets=secrets,
        )
        start = SpanStartRecord(
            timestamp=_utc_now(),
            trace_id=context.trace_id,
            span_id=context.span_id,
            parent_span_id=(
                correlation.parent.span_id
                if correlation.parent is not None
                else None
            ),
            name='paper_agent.pipeline.run',
            run_id=correlation.run_id,
            execution_id=correlation.execution_id,
            experiment_id=correlation.experiment_id,
            case_id=correlation.case_id,
            correlation_mode=(
                'fresh_child' if correlation.parent is not None else 'standalone'
            ),
            attributes=attributes,
            links=[],
        )
        writer.append(start)
        return cls(
            writer=writer,
            context=context,
            started_monotonic=time.monotonic(),
            secrets=secrets,
        )

    def event(
        self,
        name: str,
        attributes: Mapping[str, Any],
        *,
        status: SpanStatus = 'ok',
        code: str | None = None,
    ) -> None:
        self._require_active()
        sanitized = validate_event_attributes(
            name,
            attributes,
            secrets=self._secrets,
        )
        record = SpanEventRecord(
            timestamp=_utc_now(),
            trace_id=self.context.trace_id,
            span_id=self.context.span_id,
            span_name='paper_agent.pipeline.run',
            name=name,
            status=status,
            code=code,
            attributes=sanitized,
        )
        self._writer.append(record)

    def finish(self, status: SpanStatus, code: str | None = None) -> str:
        self._require_active()
        end = SpanEndRecord(
            timestamp=_utc_now(),
            trace_id=self.context.trace_id,
            span_id=self.context.span_id,
            name='paper_agent.pipeline.run',
            status=status,
            code=code,
            duration_ms=(time.monotonic() - self._started_monotonic) * 1000,
            attributes={},
        )
        self._writer.append(end)
        self._finished = True
        return self._writer.seal(timestamp=_utc_now())

    def _require_active(self) -> None:
        if self._finished:
            raise RuntimeError('pipeline trace is already finished')
