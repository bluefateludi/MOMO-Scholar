from collections.abc import Sequence

import pytest

from paper_agent.eval.retrieval_benchmark.runner import RetrievalBenchmarkRunner
from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.fusion import fuse_candidates
from paper_agent.evidence.models import RetrievalCandidate
from paper_agent.schemas import Chunk


def _chunks() -> tuple[Chunk, ...]:
    return (
        Chunk(
            chunk_id="chunk-1",
            paper_id="paper-1",
            section="Methods",
            page=1,
            text="alpha retrieval",
            token_count=2,
        ),
        Chunk(
            chunk_id="chunk-2",
            paper_id="paper-1",
            section="Results",
            page=2,
            text="beta retrieval",
            token_count=2,
        ),
    )


class RecordingSource:
    def __init__(self, candidates: list[RetrievalCandidate]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, tuple[str, ...], int]] = []

    def retrieve(
        self, question: str, chunks: Sequence[Chunk], limit: int
    ) -> list[RetrievalCandidate]:
        self.calls.append((question, tuple(chunk.chunk_id for chunk in chunks), limit))
        return self.candidates[:limit]


class FailingSource:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def retrieve(
        self, question: str, chunks: Sequence[Chunk], limit: int
    ) -> list[RetrievalCandidate]:
        raise self.error


def _lexical() -> list[RetrievalCandidate]:
    return [
        RetrievalCandidate(
            chunk_id="chunk-1",
            paper_id="paper-1",
            text="alpha retrieval",
            section="Methods",
            page=1,
            retrieval_sources=("lexical",),
            lexical_score=0.8,
            lexical_rank=1,
        ),
        RetrievalCandidate(
            chunk_id="chunk-2",
            paper_id="paper-1",
            text="beta retrieval",
            section="Results",
            page=2,
            retrieval_sources=("lexical",),
            lexical_score=0.4,
            lexical_rank=2,
        ),
    ]


def _vector() -> list[RetrievalCandidate]:
    return [
        RetrievalCandidate(
            chunk_id="chunk-2",
            paper_id="paper-1",
            text="beta retrieval",
            section="Results",
            page=2,
            retrieval_sources=("vector",),
            vector_score=0.9,
            vector_rank=1,
        ),
        RetrievalCandidate(
            chunk_id="chunk-1",
            paper_id="paper-1",
            text="alpha retrieval",
            section="Methods",
            page=1,
            retrieval_sources=("vector",),
            vector_score=0.7,
            vector_rank=2,
        ),
    ]


def test_runner_gives_both_sources_identical_case_inputs() -> None:
    lexical = RecordingSource(_lexical())
    vector = RecordingSource(_vector())
    runner = RetrievalBenchmarkRunner(lexical_source=lexical, vector_source=vector)

    result = runner.run_case(
        case_id="case-1",
        query="alpha question",
        chunks=_chunks(),
        candidate_limit=30,
        rrf_k=60,
    )

    expected_call = ("alpha question", ("chunk-1", "chunk-2"), 30)
    assert lexical.calls == [expected_call]
    assert vector.calls == [expected_call]
    assert tuple(item.mode for item in result.rankings) == (
        "keyword",
        "vector",
        "hybrid_rrf",
    )
    assert result.failures == ()


def test_hybrid_raw_ranking_is_the_production_rrf_of_captured_sources() -> None:
    runner = RetrievalBenchmarkRunner(
        lexical_source=RecordingSource(_lexical()),
        vector_source=RecordingSource(_vector()),
    )

    result = runner.run_case(
        case_id="case-1",
        query="alpha question",
        chunks=_chunks(),
        candidate_limit=30,
        rrf_k=60,
    )

    expected = fuse_candidates(
        _lexical(),
        _vector(),
        rrf_k=60,
        active_sources=("lexical", "vector"),
    )
    hybrid = result.rankings[2]
    assert tuple(item.chunk_id for item in hybrid.candidates) == tuple(
        item.chunk_id for item in expected
    )
    assert tuple(item.score for item in hybrid.candidates) == pytest.approx(
        tuple(item.fusion_score for item in expected)
    )
    assert hybrid.started_at.endswith("Z")
    assert hybrid.finished_at.endswith("Z")
    assert hybrid.duration_ms >= 0.0


def test_vector_timeout_preserves_keyword_and_marks_hybrid_failed() -> None:
    runner = RetrievalBenchmarkRunner(
        lexical_source=RecordingSource(_lexical()),
        vector_source=FailingSource(
            RetrievalSourceUnavailable("embedding_timeout", "vector_query")
        ),
    )

    result = runner.run_case(
        case_id="case-1",
        query="alpha question",
        chunks=_chunks(),
        candidate_limit=30,
        rrf_k=60,
    )

    assert tuple(item.mode for item in result.rankings) == ("keyword",)
    assert [(item.mode, item.stage, item.reason_code) for item in result.failures] == [
        ("vector", "vector_query", "embedding_timeout"),
        ("hybrid_rrf", "fusion", "dependent_vector_failure"),
    ]


def test_fusion_identity_failure_keeps_both_source_rankings() -> None:
    conflicting = _vector()
    conflicting[1] = conflicting[1].model_copy(update={"text": "different identity"})
    runner = RetrievalBenchmarkRunner(
        lexical_source=RecordingSource(_lexical()),
        vector_source=RecordingSource(conflicting),
    )

    result = runner.run_case(
        case_id="case-1",
        query="alpha question",
        chunks=_chunks(),
        candidate_limit=30,
        rrf_k=60,
    )

    assert tuple(item.mode for item in result.rankings) == ("keyword", "vector")
    assert [(item.mode, item.stage, item.reason_code) for item in result.failures] == [
        ("hybrid_rrf", "fusion", "candidate_identity_conflict")
    ]


def test_empty_corpus_produces_three_empty_successful_rankings() -> None:
    lexical = RecordingSource([])
    vector = RecordingSource([])
    runner = RetrievalBenchmarkRunner(lexical_source=lexical, vector_source=vector)

    result = runner.run_case(
        case_id="case-1",
        query="alpha question",
        chunks=(),
        candidate_limit=30,
        rrf_k=60,
    )

    assert all(not ranking.candidates for ranking in result.rankings)
    assert result.failures == ()
