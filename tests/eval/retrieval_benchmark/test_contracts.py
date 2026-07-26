import hashlib
import json

import pytest
from pydantic import ValidationError

from paper_agent.eval.retrieval_benchmark.contracts import (
    BenchmarkFingerprint,
    CaseRetrievalResult,
    ModeFailure,
    RankedCandidate,
    RawRanking,
    RetrievalBenchmarkConfig,
    compute_benchmark_fingerprint,
)


def _config_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "dataset_fingerprint_sha256": "a" * 64,
        "ordered_case_ids": ["case-1", "case-2"],
        "corpus_sha256": "b" * 64,
        "ordered_chunk_sha256": ["c" * 64, "d" * 64],
        "candidate_limit": 30,
        "timeout_seconds": 30.0,
        "rrf_k": 60,
        "embedding_model": "text-embedding-v4",
        "embedding_model_version": "2026-07-01",
        "chunking_config_sha256": "e" * 64,
        "metric_versions": [
            "recall_at_k:v1",
            "precision_at_k:v1",
            "mrr_at_k:v1",
            "ndcg_at_k:v1",
        ],
        "ks": [1, 3, 5, 8, 10],
        "primary_k": 8,
        "modes": ["keyword", "vector", "hybrid_rrf"],
    }


def _config() -> RetrievalBenchmarkConfig:
    return RetrievalBenchmarkConfig.model_validate(_config_payload())


def _ranking(mode: str = "keyword") -> RawRanking:
    sources = {
        "keyword": ("lexical",),
        "vector": ("vector",),
        "hybrid_rrf": ("lexical", "vector"),
    }[mode]
    return RawRanking(
        schema_version="1.0",
        case_id="case-1",
        mode=mode,
        candidates=(
            RankedCandidate(
                chunk_id="chunk-1",
                rank=1,
                score=0.75,
                retrieval_sources=sources,
            ),
        ),
        started_at="2026-07-26T08:00:00Z",
        finished_at="2026-07-26T08:00:00.125000Z",
        duration_ms=125.0,
    )


def test_config_freezes_canonical_fairness_dimensions() -> None:
    config = _config()

    assert config.ks == (1, 3, 5, 8, 10)
    assert config.primary_k == 8
    assert config.modes == ("keyword", "vector", "hybrid_rrf")
    assert isinstance(config.ordered_case_ids, tuple)
    assert isinstance(config.ordered_chunk_sha256, tuple)
    with pytest.raises(ValidationError):
        config.primary_k = 5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ks", [1, 3, 8, 5, 10]),
        ("ks", [1, 3, 5, 8, 8]),
        ("ks", [1, 3, 5, 8]),
        ("primary_k", 5),
        ("modes", ["vector", "keyword", "hybrid_rrf"]),
        ("candidate_limit", True),
        ("candidate_limit", "30"),
        ("timeout_seconds", float("inf")),
        ("timeout_seconds", -1.0),
        ("rrf_k", True),
        ("embedding_model_version", " "),
        ("dataset_fingerprint_sha256", "not-a-hash"),
        ("ordered_case_ids", ["case-1", "case-1"]),
        ("ordered_chunk_sha256", ["c" * 64, "c" * 64]),
    ],
)
def test_config_rejects_unfair_or_ambiguous_values(field: str, value: object) -> None:
    payload = _config_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        RetrievalBenchmarkConfig.model_validate(payload)


def test_config_rejects_unknown_fields() -> None:
    payload = _config_payload()
    payload["provider_secret"] = "must-not-enter-contract"

    with pytest.raises(ValidationError):
        RetrievalBenchmarkConfig.model_validate(payload)


def test_fingerprint_matches_independent_canonical_payload() -> None:
    config = _config()
    canonical = json.dumps(
        _config_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()

    result = compute_benchmark_fingerprint(config)

    assert result == BenchmarkFingerprint(
        algorithm="sha256",
        value=expected,
    )


def test_each_fairness_input_changes_the_fingerprint() -> None:
    original = compute_benchmark_fingerprint(_config())
    mutations = {
        "dataset_fingerprint_sha256": "f" * 64,
        "ordered_case_ids": ["case-2", "case-1"],
        "corpus_sha256": "f" * 64,
        "ordered_chunk_sha256": ["d" * 64, "c" * 64],
        "candidate_limit": 31,
        "timeout_seconds": 31.0,
        "rrf_k": 61,
        "embedding_model": "other-model",
        "embedding_model_version": "2026-07-02",
        "chunking_config_sha256": "f" * 64,
        "metric_versions": [
            "recall_at_k:v2",
            "precision_at_k:v1",
            "mrr_at_k:v1",
            "ndcg_at_k:v1",
        ],
    }

    for field, value in mutations.items():
        payload = _config_payload()
        payload[field] = value
        assert compute_benchmark_fingerprint(
            RetrievalBenchmarkConfig.model_validate(payload)
        ) != original, field


@pytest.mark.parametrize(
    "mutation",
    [
        {"rank": True},
        {"rank": 0},
        {"score": float("nan")},
        {"retrieval_sources": []},
        {"retrieval_sources": ["vector", "lexical"]},
    ],
)
def test_ranked_candidate_rejects_invalid_values(mutation: dict[str, object]) -> None:
    payload = {
        "chunk_id": "chunk-1",
        "rank": 1,
        "score": 0.75,
        "retrieval_sources": ["lexical"],
    }
    payload.update(mutation)

    with pytest.raises(ValidationError):
        RankedCandidate.model_validate(payload)


def test_raw_ranking_rejects_duplicate_chunks_and_noncontiguous_ranks() -> None:
    base = _ranking().model_dump(mode="json")
    base["candidates"] = [base["candidates"][0], base["candidates"][0]]
    with pytest.raises(ValidationError):
        RawRanking.model_validate(base)

    second = dict(base["candidates"][0])
    second["chunk_id"] = "chunk-2"
    second["rank"] = 3
    base["candidates"] = [base["candidates"][0], second]
    with pytest.raises(ValidationError):
        RawRanking.model_validate(base)


@pytest.mark.parametrize("duration", [-0.1, float("nan"), float("inf")])
def test_raw_ranking_rejects_invalid_duration(duration: float) -> None:
    payload = _ranking().model_dump(mode="json")
    payload["duration_ms"] = duration

    with pytest.raises(ValidationError):
        RawRanking.model_validate(payload)


def test_case_result_requires_one_outcome_per_canonical_mode() -> None:
    rankings = (
        _ranking("keyword"),
        _ranking("vector"),
    )
    failure = ModeFailure(
        case_id="case-1",
        mode="hybrid_rrf",
        stage="fusion",
        reason_code="candidate_identity_conflict",
        duration_ms=5.0,
    )

    result = CaseRetrievalResult(
        case_id="case-1",
        rankings=rankings,
        failures=(failure,),
    )

    assert tuple(item.mode for item in result.rankings) == ("keyword", "vector")
    assert result.failures[0].mode == "hybrid_rrf"


def test_case_result_rejects_missing_duplicate_or_conflicting_modes() -> None:
    failure = ModeFailure(
        case_id="case-1",
        mode="vector",
        stage="vector_query",
        reason_code="embedding_timeout",
        duration_ms=5.0,
    )
    with pytest.raises(ValidationError):
        CaseRetrievalResult(case_id="case-1", rankings=(_ranking(),), failures=())
    with pytest.raises(ValidationError):
        CaseRetrievalResult(
            case_id="case-1",
            rankings=(_ranking(), _ranking()),
            failures=(failure,),
        )
    with pytest.raises(ValidationError):
        CaseRetrievalResult(
            case_id="case-1",
            rankings=(_ranking(),),
            failures=(failure, failure),
        )
    with pytest.raises(ValidationError):
        CaseRetrievalResult(
            case_id="case-1",
            rankings=(_ranking(),),
            failures=(
                failure.model_copy(update={"mode": "keyword"}),
                failure.model_copy(update={"mode": "hybrid_rrf"}),
            ),
        )


def test_nested_contracts_are_frozen() -> None:
    ranking = _ranking()
    with pytest.raises(ValidationError):
        ranking.duration_ms = 1.0
    with pytest.raises(AttributeError):
        ranking.candidates.append(ranking.candidates[0])
