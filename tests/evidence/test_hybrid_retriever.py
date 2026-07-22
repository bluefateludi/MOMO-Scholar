import pytest

from paper_agent.evidence.models import RetrievalCandidate
from paper_agent.evidence.models import RetrievalEvent
from tests.evidence.hybrid_fakes import (
    FakeSource,
    _chunk,
    _lexical_candidate,
    _recording_sink,
    _service,
    _vector_candidate,
)


def test_lexical_mode_bypasses_vector_and_preserves_legacy_score() -> None:
    lexical = FakeSource([_lexical_candidate(score=2 / 3, rank=1)])
    vector = FakeSource([_vector_candidate(score=1.0, rank=1)])
    events, sink = _recording_sink()
    outcome = _service("lexical", lexical, vector).retrieve(
        "question", [_chunk()], "run-a", sink
    )
    assert vector.calls == []
    assert outcome.evidence[0].relevance_score == 0.6667
    assert outcome.evidence[0].evidence_id == "run-a:ev_001"
    assert outcome.diagnostics.actual_mode == "lexical"
    assert len(events) == 1 and events[0].status == "ok"


def test_auto_hybrid_calls_each_source_once_and_fuses_before_top_k() -> None:
    lexical = FakeSource([_lexical_candidate(chunk_id="shared", rank=1)])
    vector = FakeSource(
        [
            _vector_candidate(chunk_id="vector-only", rank=1),
            _vector_candidate(chunk_id="shared", rank=2),
        ]
    )
    outcome = _service("auto", lexical, vector, top_k=1).retrieve(
        "question", [_chunk()], "run-a"
    )
    assert lexical.calls[0][2] == 30
    assert vector.calls[0][2] == 30
    assert [item.chunk_id for item in outcome.evidence] == ["shared"]
    assert outcome.diagnostics.fused_candidate_count == 2
    assert outcome.diagnostics.returned_evidence_count == 1
    assert outcome.diagnostics.actual_mode == "hybrid"


def test_empty_chunks_emit_one_success_event_without_source_calls() -> None:
    lexical, vector = FakeSource([]), FakeSource([])
    events, sink = _recording_sink()
    outcome = _service("hybrid", lexical, vector).retrieve(
        "question", [], "run-a", sink
    )
    assert outcome.evidence == ()
    assert lexical.calls == vector.calls == []
    assert outcome.diagnostics.actual_mode == "lexical"
    assert events == [
        RetrievalEvent.model_validate(
            {
                **outcome.diagnostics.model_dump(),
                "status": "ok",
                "failure_stage": None,
                "error_code": None,
            }
        )
    ]


def test_evidence_ids_are_assigned_after_final_top_k() -> None:
    lexical = FakeSource(
        [_lexical_candidate("a", rank=1), _lexical_candidate("b", rank=2)]
    )
    outcome = _service("lexical", lexical, None, top_k=1).retrieve(
        "question", [_chunk()], "run-z"
    )
    assert [(item.evidence_id, item.chunk_id) for item in outcome.evidence] == [
        ("run-z:ev_001", "a")
    ]


def test_evidence_copies_candidate_section_and_page_provenance() -> None:
    candidate = RetrievalCandidate(
        chunk_id="methods-1",
        paper_id="p1",
        text="method details",
        section="Methods",
        page=3,
        retrieval_sources=("lexical",),
        lexical_score=0.9,
        lexical_rank=1,
    )

    outcome = _service("lexical", FakeSource([candidate]), None).retrieve(
        "question", [_chunk("methods-1")], "run-provenance"
    )

    assert outcome.evidence[0].section == "Methods"
    assert outcome.evidence[0].page == 3


def test_auto_without_vector_source_is_lexical() -> None:
    outcome = _service("auto", FakeSource([_lexical_candidate()]), None).retrieve(
        "question", [_chunk()], "run-a"
    )
    assert outcome.diagnostics.actual_mode == "lexical"
    assert outcome.diagnostics.vector_attempted is False


def test_empty_vector_result_is_hybrid_not_degradation() -> None:
    outcome = _service(
        "auto", FakeSource([_lexical_candidate()]), FakeSource([])
    ).retrieve("question", [_chunk()], "run-a")
    assert outcome.diagnostics.actual_mode == "hybrid"
    assert outcome.diagnostics.degraded is False
    assert outcome.evidence[0].relevance_score == pytest.approx(0.5)
