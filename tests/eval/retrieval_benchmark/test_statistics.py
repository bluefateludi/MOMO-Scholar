import pytest

from paper_agent.eval.retrieval_benchmark.contracts import (
    CaseRetrievalResult,
    ModeFailure,
    RankedCandidate,
    RawRanking,
)
from paper_agent.eval.retrieval_benchmark.statistics import score_benchmark


def _ranking(case_id: str, mode: str, ids: list[str], duration: float) -> RawRanking:
    source = {
        "keyword": ("lexical",),
        "vector": ("vector",),
        "hybrid_rrf": ("lexical", "vector"),
    }[mode]
    return RawRanking(
        schema_version="1.0",
        case_id=case_id,
        mode=mode,
        candidates=tuple(
            RankedCandidate(
                chunk_id=chunk_id,
                rank=rank,
                score=1.0 / rank,
                retrieval_sources=source,
            )
            for rank, chunk_id in enumerate(ids, start=1)
        ),
        started_at="2026-07-26T08:00:00Z",
        finished_at="2026-07-26T08:00:01Z",
        duration_ms=duration,
    )


def _case(case_id: str, keyword: list[str], vector: list[str], hybrid: list[str]):
    return CaseRetrievalResult(
        case_id=case_id,
        rankings=(
            _ranking(case_id, "keyword", keyword, 10.0),
            _ranking(case_id, "vector", vector, 20.0),
            _ranking(case_id, "hybrid_rrf", hybrid, 30.0),
        ),
        failures=(),
    )


def test_scores_every_metric_at_every_k_and_labels_k8_primary() -> None:
    result = score_benchmark(
        cases=(_case("case-1", ["x", "r1"], ["r1", "x"], ["r2", "r1"]),),
        relevance_by_case={"case-1": {"r1": 2, "r2": 1}},
        ks=(1, 3, 5, 8, 10),
        primary_k=8,
        bootstrap_resamples=100,
        seed=20260726,
    )

    keyword = result["case_metrics"][0]["modes"]["keyword"]
    assert set(keyword) == {"1", "3", "5", "8", "10"}
    assert keyword["1"] == {
        "recall_at_k": 0.0,
        "precision_at_k": 0.0,
        "mrr_at_k": 0.0,
        "ndcg_at_k": 0.0,
    }
    assert result["primary_k"] == 8


def test_paired_delta_is_mean_of_case_level_hybrid_minus_source() -> None:
    cases = (
        _case("case-1", ["x"], ["r"], ["r"]),
        _case("case-2", ["r"], ["x"], ["r"]),
        _case("case-3", ["x"], ["x"], ["x"]),
        _case("case-4", ["r"], ["r"], ["x"]),
    )
    relevance = {case.case_id: {"r": 1} for case in cases}

    result = score_benchmark(
        cases=cases,
        relevance_by_case=relevance,
        ks=(1, 3, 5, 8, 10),
        primary_k=8,
        bootstrap_resamples=1000,
        seed=20260726,
    )

    recall = result["paired_deltas"]["hybrid_rrf_minus_keyword"]["8"]["recall_at_k"]
    assert recall["mean_delta"] == pytest.approx(0.0)
    assert recall["paired_case_count"] == 4
    assert recall["ci_95_low"] <= recall["mean_delta"] <= recall["ci_95_high"]
    vector = result["paired_deltas"]["hybrid_rrf_minus_vector"]["8"]["recall_at_k"]
    assert vector["mean_delta"] == pytest.approx(0.0)


def test_failures_are_status_not_zero_and_use_attempted_denominator() -> None:
    keyword = _ranking("case-1", "keyword", ["r"], 10.0)
    result_case = CaseRetrievalResult(
        case_id="case-1",
        rankings=(keyword,),
        failures=(
            ModeFailure(
                case_id="case-1",
                mode="vector",
                stage="vector_query",
                reason_code="embedding_timeout",
                duration_ms=20.0,
            ),
            ModeFailure(
                case_id="case-1",
                mode="hybrid_rrf",
                stage="fusion",
                reason_code="dependent_vector_failure",
                duration_ms=0.1,
            ),
        ),
    )

    result = score_benchmark(
        cases=(result_case,),
        relevance_by_case={"case-1": {"r": 1}},
        ks=(1, 3, 5, 8, 10),
        primary_k=8,
        bootstrap_resamples=100,
        seed=20260726,
    )

    modes = result["case_metrics"][0]["modes"]
    assert modes["vector"] == {
        "status": "error",
        "stage": "vector_query",
        "reason_code": "embedding_timeout",
    }
    assert result["operations"]["vector"]["failure_rate"] == 1.0
    assert result["operations"]["keyword"] == {
        "attempted": 1,
        "completed": 1,
        "failed": 0,
        "failure_rate": 0.0,
        "latency_ms_p50": 10.0,
        "latency_ms_p95": 10.0,
    }


def test_seeded_bootstrap_is_repeatable() -> None:
    cases = (
        _case("case-1", ["x"], ["x"], ["r"]),
        _case("case-2", ["r"], ["r"], ["x"]),
    )
    relevance = {case.case_id: {"r": 1} for case in cases}
    kwargs = dict(
        cases=cases,
        relevance_by_case=relevance,
        ks=(1, 3, 5, 8, 10),
        primary_k=8,
        bootstrap_resamples=1000,
        seed=20260726,
    )

    assert score_benchmark(**kwargs) == score_benchmark(**kwargs)
