from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from paper_agent.config import Settings
from paper_agent.observability.models import (
    RunCounts,
    RunEvent,
    RunIssue,
    RunManifest,
    SafeRunSettings,
    UsageTotals,
)


def _counts(**overrides: int) -> RunCounts:
    values = {
        "selected_papers": 3,
        "pdf_documents": 1,
        "abstract_documents": 1,
        "explicit_abstract_documents": 0,
        "pdf_fallback_documents": 1,
        "excluded_papers": 1,
        "successful_analyses": 2,
        "evidence_items": 4,
    }
    values.update(overrides)
    return RunCounts(**values)


def _safe_settings() -> SafeRunSettings:
    return SafeRunSettings.from_settings(
        Settings(dashscope_api_key="do-not-persist"),
        chunk_max_words=180,
        chunk_overlap_words=30,
    )


def _manifest_values() -> dict[str, object]:
    return {
        'run_id': 'run-1',
        'execution_id': 'exec-1',
        'status': 'running',
        'question': 'grounded review',
        'requested_limit': 3,
        'no_pdf': False,
        'started_at': datetime(2026, 7, 21, tzinfo=timezone.utc),
        'finished_at': None,
        'settings': _safe_settings(),
        'counts': _counts(),
        'stage_elapsed_seconds': {},
        'usage': UsageTotals(operations=0, http_attempts=0),
        'component_versions': {},
    }


def test_manifest_trace_metadata_follows_terminal_authority() -> None:
    running = RunManifest.model_validate(_manifest_values())
    assert running.execution_id == 'exec-1'
    assert running.trace_sha256 is None

    completed_values = _manifest_values()
    completed_values.update(
        status='completed',
        finished_at=datetime(2026, 7, 21, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValidationError, match='trace metadata'):
        RunManifest.model_validate(completed_values)

    completed_values.update(
        trace_schema_version='1.0',
        trace_root_trace_id='1' * 32,
        trace_root_span_id='2' * 16,
        trace_sha256='a' * 64,
    )
    assert RunManifest.model_validate(completed_values).status == 'completed'


def test_trace_persistence_failure_allows_null_trace_metadata() -> None:
    values = _manifest_values()
    values.update(
        status='failed',
        finished_at=datetime(2026, 7, 21, 1, tzinfo=timezone.utc),
        errors=[
            RunIssue(stage='observability', code='trace_persistence_failed')
        ],
    )
    assert RunManifest.model_validate(values).trace_sha256 is None


def test_run_counts_require_consistent_document_partition() -> None:
    with pytest.raises(ValidationError, match="selected papers"):
        _counts(excluded_papers=0)


def test_run_counts_require_consistent_abstract_partition() -> None:
    with pytest.raises(ValidationError, match="abstract documents"):
        _counts(explicit_abstract_documents=1)


def test_run_counts_bound_successful_analyses_by_documents() -> None:
    with pytest.raises(ValidationError, match="successful analyses"):
        _counts(successful_analyses=3)


def test_run_counts_reject_negative_values() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        _counts(evidence_items=-1)


def test_safe_settings_copy_only_approved_non_secret_values() -> None:
    safe = _safe_settings()

    assert safe.generation_endpoint_host == "dashscope.aliyuncs.com"
    assert safe.chunk_max_words == 180
    assert safe.chunk_overlap_words == 30
    assert "dashscope_api_key" not in safe.model_dump()


def test_safe_settings_reject_endpoint_without_host() -> None:
    with pytest.raises(ValueError, match="generation endpoint host is required"):
        SafeRunSettings.from_settings(
            Settings(dashscope_generation_base_url="relative/path"),
            chunk_max_words=180,
            chunk_overlap_words=30,
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 7, 21, 12, 0),
        datetime(2026, 7, 21, 12, 0, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_run_event_requires_utc_aware_timestamp(timestamp: datetime) -> None:
    with pytest.raises(ValidationError, match="UTC-aware"):
        RunEvent(
            timestamp=timestamp,
            run_id="run-1",
            stage="test",
            operation="validate",
            status="ok",
        )


def test_run_manifest_requires_utc_finished_at_and_rejects_extra_fields() -> None:
    values = {
        'execution_id': 'exec-1',
        'trace_schema_version': '1.0',
        'trace_root_trace_id': '1' * 32,
        'trace_root_span_id': '2' * 16,
        'trace_sha256': 'a' * 64,
        "run_id": "run-1",
        "status": "completed",
        "question": "grounded review",
        "requested_limit": 3,
        "no_pdf": False,
        "started_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
        "finished_at": datetime(2026, 7, 21, 1),
        "settings": _safe_settings(),
        "counts": _counts(),
        "stage_elapsed_seconds": {},
        "usage": UsageTotals(operations=0, http_attempts=0),
        "component_versions": {},
    }
    with pytest.raises(ValidationError, match="UTC-aware"):
        RunManifest(**values)

    values["finished_at"] = datetime(2026, 7, 21, 1, tzinfo=timezone.utc)
    values["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RunManifest(**values)


def test_manifest_status_and_finished_at_are_consistent() -> None:
    values = {
        'execution_id': 'exec-1',
        "run_id": "run-1",
        "status": "running",
        "question": "grounded review",
        "requested_limit": 3,
        "no_pdf": False,
        "started_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
        "finished_at": datetime(2026, 7, 21, 1, tzinfo=timezone.utc),
        "settings": _safe_settings(),
        "counts": _counts(),
        "stage_elapsed_seconds": {},
        "usage": UsageTotals(operations=0, http_attempts=0),
        "component_versions": {},
    }
    with pytest.raises(ValidationError, match="running manifest"):
        RunManifest(**values)

    values.update(status="failed", finished_at=None)
    with pytest.raises(ValidationError, match="terminal manifest"):
        RunManifest(**values)
