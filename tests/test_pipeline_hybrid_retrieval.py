import json

import pytest

from paper_agent.config import Settings
from paper_agent.evidence import RetrievalDiagnostics, RetrievalEvent, RetrievalOutcome
from paper_agent.evidence.factory import RetrievalConfigurationError
from paper_agent.pipeline import run_pipeline
from paper_agent.schemas import Evidence, Paper


def _paper(abstract="Hybrid retrieval grounds scholarly evidence."):
    return Paper(paper_id="p1", title="Grounded Retrieval", abstract=abstract, url="https://example.test/p1", source="test")


def _fake_search(query, limit):
    return [_paper()]


def _empty_search(query, limit):
    return []


class FakeRetrievalService:
    def __init__(self):
        self.calls = []
        self.close_calls = 0

    def retrieve(self, question, chunks, run_id, event_sink=None):
        self.calls.append((question, chunks, run_id))
        evidence = (Evidence(evidence_id=f"{run_id}:ev_001", paper_id=chunks[0].paper_id, chunk_id=chunks[0].chunk_id, claim_type="retrieved", quote=chunks[0].text, relevance_score=0.75),)
        values = dict(requested_mode="hybrid", actual_mode="hybrid", lexical_candidate_count=1, vector_candidate_count=1, fused_candidate_count=1, returned_evidence_count=1, vector_attempted=True, degraded=False, degradation_code=None)
        diagnostics = RetrievalDiagnostics.model_validate(values)
        if event_sink:
            event_sink(RetrievalEvent.model_validate({**values, "status": "ok", "failure_stage": None, "error_code": None}))
        return RetrievalOutcome(evidence=evidence, diagnostics=diagnostics)

    def close(self):
        self.close_calls += 1


def test_pipeline_uses_injected_service_and_writes_terminal_event(tmp_path):
    service = FakeRetrievalService()
    run_dir = run_pipeline(question="retrieval grounding", output_base=tmp_path, limit=1, no_pdf=True, search_fn=_fake_search, retrieval_service=service)
    assert len(service.calls) == 1
    lines = (run_dir / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert (event["status"], event["actual_mode"]) == ("ok", "hybrid")
    evidence = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    assert evidence[0]["evidence_id"].startswith(f"{run_dir.name}:")
    assert service.close_calls == 0


def test_pipeline_defaults_to_offline_lexical_retrieval_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    run_dir = run_pipeline(question="retrieval grounding", output_base=tmp_path, no_pdf=True, search_fn=_fake_search)
    event = json.loads((run_dir / "logs.jsonl").read_text(encoding="utf-8"))
    assert (event["status"], event["requested_mode"], event["actual_mode"]) == ("ok", "auto", "lexical")


def _expected_event(status, actual_mode, failure_stage=None, error_code=None):
    return dict(status=status, requested_mode="hybrid", actual_mode=actual_mode, lexical_candidate_count=0, vector_candidate_count=0, fused_candidate_count=0, returned_evidence_count=0, vector_attempted=False, degraded=False, degradation_code=None, failure_stage=failure_stage, error_code=error_code)


@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_empty_chunks_bypass_forced_hybrid_assembly(tmp_path, monkeypatch, api_key):
    def fail_factory(settings):
        raise AssertionError("factory must not be called")
    monkeypatch.setattr("paper_agent.pipeline.build_retrieval_service", fail_factory)
    run_dir = run_pipeline(question="question", output_base=tmp_path, no_pdf=True, search_fn=_empty_search, settings=Settings(retrieval_mode="hybrid", dashscope_api_key=api_key))
    assert json.loads((run_dir / "evidence.json").read_text(encoding="utf-8")) == []
    lines = (run_dir / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == _expected_event("ok", "lexical")


@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_nonempty_forced_hybrid_writes_assembly_error(tmp_path, api_key):
    with pytest.raises(RetrievalConfigurationError):
        run_pipeline(question="question", output_base=tmp_path, no_pdf=True, search_fn=_fake_search, settings=Settings(retrieval_mode="hybrid", dashscope_api_key=api_key))
    run_dir = next(tmp_path.iterdir())
    lines = (run_dir / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == _expected_event("error", None, "assembly", "retrieval_configuration_error")
