import json
from datetime import datetime, timezone

import pytest

from paper_agent.observability.sealed_jsonl import SealedJsonlError, verify_sealed_jsonl
from paper_agent.techscout.observability import TechScoutTraceRecorder, TraceEventName


FROZEN_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def test_records_sanitized_structured_events_and_seals_manifest(tmp_path):
    path = tmp_path / "traces.jsonl"
    recorder = TechScoutTraceRecorder(
        path,
        run_id="run:smoke-001",
        secrets=("super-secret",),
        now=lambda: FROZEN_NOW,
    )

    event = recorder.record(
        TraceEventName.TOOL_FINISHED,
        status="ok",
        attributes={
            "tool_call_id": "tool:001",
            "tool_name": "fetch C:\\private\\workspace\\source.json",
            "latency_ms": 12,
            "cache_status": "hit",
            "api_key": "super-secret",
            "prompt": "never persist this",
        },
    )
    manifest = recorder.seal()

    assert "api_key" not in event.attributes
    assert "prompt" not in event.attributes
    assert "private" not in event.attributes["tool_name"]
    assert manifest == verify_sealed_jsonl(path)
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["record_type"] == "trace_seal"


def test_event_allowlist_applies_after_sanitization(tmp_path):
    recorder = TechScoutTraceRecorder(
        tmp_path / "traces.jsonl",
        run_id="run:smoke-002",
        now=lambda: FROZEN_NOW,
    )

    with pytest.raises(ValueError, match="not allowlisted"):
        recorder.record(
            TraceEventName.SKILL_SELECTED,
            status="ok",
            attributes={"skill_id": "skill:research", "unexpected": "value"},
        )


def test_tampering_breaks_sealed_jsonl_verification(tmp_path):
    path = tmp_path / "traces.jsonl"
    recorder = TechScoutTraceRecorder(path, run_id="run:smoke-003", now=lambda: FROZEN_NOW)
    recorder.record(
        TraceEventName.PLAN_CREATED,
        status="ok",
        attributes={"plan_id": "plan:001", "dimension_count": 3},
    )
    recorder.seal()
    path.write_bytes(path.read_bytes().replace(b"plan:001", b"plan:999"))

    with pytest.raises(SealedJsonlError, match="integrity"):
        verify_sealed_jsonl(path)


def test_each_event_is_flushed_before_sealing(tmp_path):
    path = tmp_path / "traces.jsonl"
    recorder = TechScoutTraceRecorder(path, run_id="run:partial", now=lambda: FROZEN_NOW)
    recorder.record(
        TraceEventName.ERROR_CLASSIFIED,
        status="error",
        attributes={
            "failure_id": "failure:partial:001",
            "failure_code": "tool_timeout",
            "failure_stage": "research",
            "recoverable": True,
            "attempt": 1,
        },
    )

    assert "failure:partial:001" in path.read_text(encoding="utf-8")
    assert not path.with_name("traces-manifest.json").exists()
