from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from paper_agent.web.api_models import CreateRunRequest
from paper_agent.web.errors import WebError
from paper_agent.web.event_cursor import decode_event_cursor, encode_event_cursor
from paper_agent.web.registry import RunRegistry


REQUEST = CreateRunRequest.model_validate({
    "question": "grounded literature review",
    "paper_limit": 1,
    "content_mode": "abstract_only",
    "retrieval": {
        "mode": "lexical", "candidate_k": 4, "top_k": 2, "rrf_k": 60,
        "analysis_evidence_per_paper": 1,
    },
})


def test_concurrent_admission_never_exceeds_capacity(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")

    def admit(index: int) -> bool:
        try:
            registry.admit(f"00000000-0000-4000-8000-{index:012d}", REQUEST, 2)
            return True
        except WebError as error:
            assert error.code == "queue_full"
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(admit, range(8)))
    assert sum(accepted) == 2


def test_claim_is_atomic_and_oldest_only(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")
    registry.admit("00000000-0000-4000-8000-000000000001", REQUEST, 4)
    registry.admit("00000000-0000-4000-8000-000000000002", REQUEST, 4)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: registry.claim_oldest(), range(2)))
    assert sum(item is not None for item in claims) == 1
    assert registry.get("00000000-0000-4000-8000-000000000001").status == "running"
    assert registry.get("00000000-0000-4000-8000-000000000002").status == "queued"


def test_artifact_id_rejects_paths(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")
    registry.admit("00000000-0000-4000-8000-000000000001", REQUEST, 4)
    with pytest.raises(ValueError):
        registry.set_artifact_id("00000000-0000-4000-8000-000000000001", "../secret")


def test_run_events_migrate_and_page_with_opaque_cursor(tmp_path):
    path = tmp_path / "registry.sqlite3"
    registry = RunRegistry(path)
    run_id = "00000000-0000-4000-8000-000000000001"
    registry.admit(run_id, REQUEST, 4)
    registry.append_event(
        run_id, event_type="tool", stage="research", status="completed",
        label="Fetched\nallowlisted metadata", skill="official-docs", tool="github.read",
        duration_ms=12,
    )

    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM run_events").fetchone()[0] == 2

    first, has_more = registry.list_events(run_id, after_sequence=0, limit=1)
    assert len(first) == 1 and has_more is True
    cursor = encode_event_cursor(first[-1].sequence)
    second, has_more = registry.list_events(
        run_id, after_sequence=decode_event_cursor(cursor), limit=1,
    )
    assert second[0].label == "Fetched allowlisted metadata"
    assert second[0].tool == "github.read"
    assert has_more is False


def test_trace_rejects_invalid_cursor_and_unbounded_text(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")
    run_id = "00000000-0000-4000-8000-000000000001"
    registry.admit(run_id, REQUEST, 4)
    with pytest.raises(WebError) as error:
        decode_event_cursor("not-a-cursor")
    assert error.value.code == "validation_error"

    registry.append_event(
        run_id, event_type="stage", stage="research", status="running",
        label="x" * 500,
    )
    events, _ = registry.list_events(run_id, after_sequence=0, limit=10)
    assert len(events[-1].label) == 240


def test_trace_redacts_common_credential_shapes_before_persistence(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")
    run_id = "00000000-0000-4000-8000-000000000001"
    registry.admit(run_id, REQUEST, 4)
    registry.append_event(
        run_id, event_type="tool", stage="research", status="failed",
        label=(
            "Authorization: Bearer secret-canary "
            "https://example.test/path?api_key=also-secret&safe=1 password=hunter2 "
            "provider-body-canary"
        ),
        tool="token=tool-secret",
        secrets=("provider-body-canary",),
    )
    events, _ = registry.list_events(run_id, after_sequence=0, limit=10)
    persisted = events[-1].model_dump_json()
    assert "secret-canary" not in persisted
    assert "also-secret" not in persisted
    assert "hunter2" not in persisted
    assert "tool-secret" not in persisted
    assert "provider-body-canary" not in persisted
    assert persisted.count("[REDACTED]") >= 5


def test_progress_and_event_append_are_one_transaction(tmp_path):
    path = tmp_path / "registry.sqlite3"
    registry = RunRegistry(path)
    run_id = "00000000-0000-4000-8000-000000000001"
    registry.admit(run_id, REQUEST, 4)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE run_events")

    with pytest.raises(sqlite3.OperationalError):
        registry.update_progress(run_id, "search", registry.get(run_id).progress)
    assert registry.get(run_id).phase == "queued"


def test_terminal_state_and_event_append_are_one_transaction(tmp_path):
    path = tmp_path / "registry.sqlite3"
    registry = RunRegistry(path)
    run_id = "00000000-0000-4000-8000-000000000001"
    registry.admit(run_id, REQUEST, 4)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE run_events")

    with pytest.raises(sqlite3.OperationalError):
        registry.terminal(run_id, "failed")
    assert registry.get(run_id).status == "queued"
