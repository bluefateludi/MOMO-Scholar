from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from paper_agent.web.api_models import CreateRunRequest
from paper_agent.web.errors import WebError
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

    first = registry.trace(run_id, limit=1)
    assert len(first.items) == 1
    assert first.next_cursor is not None
    second = registry.trace(run_id, limit=1, cursor=first.next_cursor)
    assert second.items[0].label == "Fetched allowlisted metadata"
    assert second.items[0].tool == "github.read"
    assert second.next_cursor is None


def test_trace_rejects_invalid_cursor_and_unbounded_text(tmp_path):
    registry = RunRegistry(tmp_path / "registry.sqlite3")
    run_id = "00000000-0000-4000-8000-000000000001"
    registry.admit(run_id, REQUEST, 4)
    with pytest.raises(WebError) as error:
        registry.trace(run_id, limit=10, cursor="not-a-cursor")
    assert error.value.code == "validation_error"

    registry.append_event(
        run_id, event_type="stage", stage="research", status="running",
        label="x" * 500,
    )
    assert len(registry.trace(run_id, 10).items[-1].label) == 240
