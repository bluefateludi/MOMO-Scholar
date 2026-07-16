import pytest

import paper_agent.evidence.hybrid as hybrid_module
from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.models import RetrievalEvent
from paper_agent.evidence.vector_source import VectorSourceExecutionError
from tests.evidence.hybrid_fakes import (
    FakeSource,
    _chunk,
    _lexical_candidate,
    _recording_sink,
    _service,
    _vector_candidate,
)


def test_auto_degrades_only_typed_unavailable_error() -> None:
    lexical = FakeSource([_lexical_candidate(score=0.75, rank=1)])
    vector = FakeSource([])
    vector.error = RetrievalSourceUnavailable("embedding_timeout", "vector_query")
    events, sink = _recording_sink()
    outcome = _service("auto", lexical, vector).retrieve(
        "question", [_chunk()], "run-a", sink
    )
    assert outcome.evidence[0].relevance_score == 0.75
    assert outcome.diagnostics.degraded is True
    assert outcome.diagnostics.degradation_code == "embedding_timeout"
    assert events[0].status == "ok"


def test_forced_hybrid_emits_error_then_rethrows_unavailable() -> None:
    lexical, vector = FakeSource([]), FakeSource([])
    error = RetrievalSourceUnavailable("embedding_timeout", "vector_index")
    vector.error = error
    events, sink = _recording_sink()
    with pytest.raises(RetrievalSourceUnavailable) as exc_info:
        _service("hybrid", lexical, vector).retrieve(
            "question", [_chunk()], "run-a", sink
        )
    assert exc_info.value is error
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].failure_stage == "vector_index"


@pytest.mark.parametrize(
    ("question", "run_id", "candidate_k", "top_k", "rrf_k"),
    [
        (" ", "run-a", 30, 8, 60),
        ("q", " ", 30, 8, 60),
        ("q", "run-a", 0, 8, 60),
        ("q", "run-a", 30, 0, 60),
        ("q", "run-a", 30, 8, 0),
    ],
)
def test_validation_error_emits_one_terminal_event(
    question: str, run_id: str, candidate_k: int, top_k: int, rrf_k: int
) -> None:
    events, sink = _recording_sink()
    service = HybridEvidenceRetriever(
        lexical_source=FakeSource([]),
        vector_source=None,
        requested_mode="lexical",
        candidate_k=candidate_k,
        top_k=top_k,
        rrf_k=rrf_k,
    )
    with pytest.raises(ValueError):
        service.retrieve(question, [_chunk()], run_id, sink)
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].failure_stage == "validation"


def test_vector_contract_failure_uses_exact_stage_and_rethrows_cause() -> None:
    lexical, vector = FakeSource([_lexical_candidate()]), FakeSource([])
    cause = ValueError("dimension mismatch")
    vector.error = VectorSourceExecutionError(cause, "vector_index")
    events, sink = _recording_sink()
    with pytest.raises(ValueError) as exc_info:
        _service("hybrid", lexical, vector).retrieve(
            "q", [_chunk()], "run-a", sink
        )
    assert exc_info.value is cause
    assert exc_info.value.__suppress_context__ is True
    assert [
        (item.failure_stage, item.error_code, item.lexical_candidate_count)
        for item in events
    ] == [("vector_index", "vector_failure", 1)]


def test_fusion_failure_emits_counts_once_and_rethrows_same_error() -> None:
    lexical = FakeSource([_lexical_candidate("same")])
    conflicting = _vector_candidate("same").model_copy(update={"text": "different"})
    vector = FakeSource([conflicting])
    events, sink = _recording_sink()
    with pytest.raises(ValueError, match="identity") as exc_info:
        _service("hybrid", lexical, vector).retrieve(
            "q", [_chunk()], "run-a", sink
        )
    assert len(events) == 1
    event = events[0]
    assert (event.failure_stage, event.error_code) == ("fusion", "fusion_failure")
    assert (
        event.lexical_candidate_count,
        event.vector_candidate_count,
        event.fused_candidate_count,
        event.returned_evidence_count,
    ) == (1, 1, 0, 0)
    assert exc_info.value is not None


def test_evidence_conversion_failure_emits_fused_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ValueError("conversion failed")

    def fail_conversion(*args: object, **kwargs: object) -> tuple[()]:
        raise error

    monkeypatch.setattr(hybrid_module, "_candidates_to_evidence", fail_conversion)
    events, sink = _recording_sink()
    with pytest.raises(ValueError) as exc_info:
        _service("lexical", FakeSource([_lexical_candidate()]), None).retrieve(
            "q", [_chunk()], "run-a", sink
        )
    assert exc_info.value is error
    assert len(events) == 1
    event = events[0]
    assert (event.failure_stage, event.error_code) == (
        "evidence_conversion",
        "evidence_conversion_failure",
    )
    assert (event.fused_candidate_count, event.returned_evidence_count) == (1, 0)


def test_lexical_failure_emits_once_and_rethrows_same_error() -> None:
    lexical = FakeSource([])
    error = ValueError("lexical-contract")
    lexical.error = error
    events, sink = _recording_sink()
    with pytest.raises(ValueError) as exc_info:
        _service("lexical", lexical, None).retrieve("q", [_chunk()], "run-a", sink)
    assert exc_info.value is error
    assert [
        (item.status, item.failure_stage, item.error_code) for item in events
    ] == [("error", "lexical", "lexical_failure")]


def test_sink_failure_propagates_without_second_delivery() -> None:
    calls = 0

    def failing_sink(event: RetrievalEvent) -> None:
        nonlocal calls
        calls += 1
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        _service("lexical", FakeSource([]), None).retrieve(
            "q", [_chunk()], "run-a", failing_sink
        )
    assert calls == 1
