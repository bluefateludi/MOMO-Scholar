from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.models import RetrievalCandidate, RetrievalDiagnostics, RetrievalEvent


def _candidate(**overrides: object) -> RetrievalCandidate:
    values: dict[str, object] = {
        "chunk_id": "p1:chunk:001",
        "paper_id": "p1",
        "text": "retrieval grounding",
        "section": "Methods",
        "page": 2,
        "retrieval_sources": ("lexical",),
        "lexical_score": 0.8,
        "lexical_rank": 1,
    }
    values.update(overrides)
    return RetrievalCandidate.model_validate(values)


def _diagnostics(**overrides: object) -> RetrievalDiagnostics:
    values: dict[str, object] = {
        "requested_mode": "lexical",
        "actual_mode": "lexical",
        "lexical_candidate_count": 1,
        "vector_candidate_count": 0,
        "fused_candidate_count": 1,
        "returned_evidence_count": 1,
        "vector_attempted": False,
        "degraded": False,
    }
    values.update(overrides)
    return RetrievalDiagnostics.model_validate(values)


def _event(**overrides: object) -> RetrievalEvent:
    values = _diagnostics().model_dump()
    values.update({"status": "ok", "failure_stage": None, "error_code": None})
    values.update(overrides)
    return RetrievalEvent.model_validate(values)


def test_candidate_rejects_noncanonical_source_order() -> None:
    with pytest.raises(ValueError, match="canonical"):
        _candidate(
            retrieval_sources=("vector", "lexical"),
            lexical_score=0.8,
            lexical_rank=2,
            vector_score=0.9,
            vector_rank=1,
        )


def test_candidate_requires_score_and_rank_pair() -> None:
    with pytest.raises(ValueError, match="lexical score and rank"):
        _candidate(lexical_score=0.8, lexical_rank=None)


def test_diagnostics_rejects_returned_count_above_fused_count() -> None:
    with pytest.raises(ValueError, match="returned_evidence_count"):
        _diagnostics(fused_candidate_count=1, returned_evidence_count=2)


def test_hybrid_diagnostics_require_vector_attempt() -> None:
    with pytest.raises(ValueError, match="hybrid.*vector"):
        _diagnostics(actual_mode="hybrid", vector_attempted=False)


def test_degraded_diagnostics_require_auto_lexical_fallback() -> None:
    with pytest.raises(ValueError, match="degraded"):
        _diagnostics(
            requested_mode="hybrid",
            actual_mode="lexical",
            vector_attempted=True,
            degraded=True,
            degradation_code="embedding_timeout",
        )


def test_assembly_error_event_allows_no_actual_mode() -> None:
    event = _event(
        status="error",
        actual_mode=None,
        failure_stage="assembly",
        error_code="retrieval_configuration_error",
    )
    assert event.actual_mode is None


def test_success_event_requires_actual_mode_and_no_error_fields() -> None:
    with pytest.raises(ValueError, match="successful event"):
        _event(status="ok", actual_mode=None)


def test_event_rejects_unknown_degradation_code() -> None:
    with pytest.raises(ValidationError):
        _event(degraded=True, degradation_code="unknown")


def test_source_unavailable_exposes_frozen_typed_metadata() -> None:
    error = RetrievalSourceUnavailable("embedding_timeout", "vector_query")
    assert error.degradation_code == "embedding_timeout"
    assert error.failure_stage == "vector_query"
    with pytest.raises(FrozenInstanceError):
        error.failure_stage = "vector_index"
    assert "sentinel-secret" not in repr(error)


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError, match="frozen"):
        candidate.chunk_id = "changed"
    values = candidate.model_dump()
    values["database_filter"] = "unsafe"
    with pytest.raises(ValidationError, match="extra"):
        RetrievalCandidate.model_validate(values)


def test_candidate_rejects_rank_below_one() -> None:
    with pytest.raises(ValidationError):
        _candidate(lexical_rank=0)


def test_candidate_rejects_fields_for_absent_source() -> None:
    with pytest.raises(ValueError, match="absent vector"):
        _candidate(vector_score=0.9, vector_rank=1)


def test_diagnostics_reject_vector_count_without_attempt() -> None:
    with pytest.raises(ValueError, match="vector_candidate_count"):
        _diagnostics(vector_candidate_count=1, vector_attempted=False)


def test_error_event_requires_stage_and_code() -> None:
    with pytest.raises(ValueError, match="error event"):
        _event(
            status="error",
            actual_mode="lexical",
            failure_stage=None,
            error_code=None,
        )


def test_nonassembly_error_requires_actual_mode() -> None:
    with pytest.raises(ValueError, match="actual_mode"):
        _event(
            status="error",
            actual_mode=None,
            failure_stage="vector_query",
            error_code="vector_failure",
        )
