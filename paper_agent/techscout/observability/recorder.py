from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from paper_agent.observability.sanitize import sanitize_bounded_event_data
from paper_agent.observability.sealed_jsonl import SealedJsonlWriter
from paper_agent.techscout.observability.schema import TraceEvent, TraceEventName, validate_event


class TechScoutTraceRecorder:
    """Small interface for sanitized, append-only TechScout lifecycle events."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        secrets: tuple[str, ...] = (),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._run_id = run_id
        self._secrets = secrets
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sequence = 0
        self._lock = Lock()
        self._writer = SealedJsonlWriter(
            path,
            owner_id=run_id,
            artifact_kind="techscout_run_trace",
        )

    def record(
        self,
        name: TraceEventName,
        *,
        status: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> TraceEvent:
        with self._lock:
            safe_attributes = sanitize_bounded_event_data(
                dict(attributes or {}),
                secrets=self._secrets,
            )
            self._sequence += 1
            event = validate_event(
                sequence=self._sequence,
                timestamp=self._now(),
                run_id=self._run_id,
                name=name,
                status=status,
                attributes=safe_attributes,
            )
            self._writer.append(event.model_dump(mode="json"))
        return event

    def seal(self) -> dict[str, Any]:
        with self._lock:
            return self._writer.seal(
                timestamp=self._now(),
                metadata={"schema_family": "momo-techscout-trace-v1"},
            )

    def record_terminal(
        self,
        *,
        terminal_status: str,
        gate_outcome: str,
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        retry_count: int,
        recovery_count: int,
        report_sha256: str,
        manifest_sha256: str,
        status: str = "ok",
        context: Mapping[str, Any] | None = None,
    ) -> TraceEvent:
        return self.record(
            TraceEventName.TERMINAL_COMPLETED,
            status=status,
            attributes={
                **dict(context or {}),
                "terminal_status": terminal_status,
                "gate_outcome": gate_outcome,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "retry_count": retry_count,
                "recovery_count": recovery_count,
                "report_sha256": report_sha256,
                "manifest_sha256": manifest_sha256,
            },
        )
