import json

import pytest

from paper_agent.evidence import RetrievalEvent
from paper_agent.pipeline import run_pipeline
from paper_agent.schemas import Paper


def _fake_search(query, limit):
    return [Paper(paper_id="p1", title="Grounded Retrieval", abstract="Retrieval evidence is available.", url="https://example.test/p1", source="test")]


class ErroringRetrievalService:
    def __init__(self, error):
        self.error = error
        self.close_calls = 0

    def retrieve(self, question, chunks, run_id, event_sink=None):
        event = RetrievalEvent(status="error", requested_mode="hybrid", actual_mode="hybrid", lexical_candidate_count=1, vector_candidate_count=0, fused_candidate_count=0, returned_evidence_count=0, vector_attempted=True, degraded=False, degradation_code=None, failure_stage="vector_query", error_code="vector_failure")
        if event_sink:
            event_sink(event)
        raise self.error

    def close(self):
        self.close_calls += 1


def test_service_error_is_rethrown_without_duplicate_event(tmp_path):
    sentinel = RuntimeError("sentinel-service-error")
    service = ErroringRetrievalService(sentinel)
    with pytest.raises(RuntimeError) as exc_info:
        run_pipeline(question="question", output_base=tmp_path, no_pdf=True, search_fn=_fake_search, retrieval_service=service)
    assert exc_info.value is sentinel
    run_dir = next(tmp_path.iterdir())
    lines = (run_dir / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["status"] == "error"
    assert event["failure_stage"] == "vector_query"
    assert event["error_code"] == "vector_failure"
    assert event["degradation_code"] is None
    assert service.close_calls == 0
