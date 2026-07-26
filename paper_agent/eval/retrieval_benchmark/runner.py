from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timezone

from paper_agent.evidence.contracts import CandidateSource, RetrievalSourceUnavailable
from paper_agent.evidence.fusion import fuse_candidates
from paper_agent.evidence.models import RetrievalCandidate
from paper_agent.evidence.vector_source import VectorSourceExecutionError
from paper_agent.schemas import Chunk
from paper_agent.vector.bailian import (
    EmbeddingAuthenticationError,
    EmbeddingConfigurationError,
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingRequestError,
    EmbeddingServerError,
    EmbeddingTimeoutError,
)

from .contracts import (
    BenchmarkMode,
    CaseRetrievalResult,
    ModeFailure,
    RankedCandidate,
    RawRanking,
)


def _utc_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reason(error: Exception) -> str:
    if isinstance(error, RetrievalSourceUnavailable):
        return error.degradation_code
    if isinstance(error, EmbeddingTimeoutError | TimeoutError):
        return "embedding_timeout"
    if isinstance(error, EmbeddingAuthenticationError):
        return "embedding_authentication_error"
    if isinstance(error, EmbeddingConfigurationError):
        return "embedding_configuration_error"
    if isinstance(error, EmbeddingRateLimitError):
        return "embedding_rate_limited"
    if isinstance(error, EmbeddingNetworkError):
        return "embedding_network_error"
    if isinstance(error, EmbeddingServerError):
        return "embedding_server_error"
    if isinstance(error, EmbeddingRequestError):
        return "embedding_request_error"
    return "retrieval_source_error"


def _stage(error: Exception, default: str) -> str:
    if isinstance(error, RetrievalSourceUnavailable):
        return error.failure_stage
    if isinstance(error, VectorSourceExecutionError):
        return error.failure_stage
    return default


def _ranking(
    *,
    case_id: str,
    mode: BenchmarkMode,
    candidates: Sequence[RetrievalCandidate],
    started_at: str,
    started_monotonic: float,
) -> RawRanking:
    ranked: list[RankedCandidate] = []
    for rank, candidate in enumerate(candidates, start=1):
        score = {
            "keyword": candidate.lexical_score,
            "vector": candidate.vector_score,
            "hybrid_rrf": candidate.fusion_score,
        }[mode]
        if score is None:
            raise ValueError(f"candidate lacks score for {mode}")
        ranked.append(
            RankedCandidate(
                chunk_id=candidate.chunk_id,
                rank=rank,
                score=float(score),
                retrieval_sources=candidate.retrieval_sources,
            )
        )
    return RawRanking(
        schema_version="1.0",
        case_id=case_id,
        mode=mode,
        candidates=tuple(ranked),
        started_at=started_at,
        finished_at=_utc_text(),
        duration_ms=(time.perf_counter() - started_monotonic) * 1000,
    )


class RetrievalBenchmarkRunner:
    def __init__(
        self,
        *,
        lexical_source: CandidateSource,
        vector_source: CandidateSource,
    ) -> None:
        self._lexical_source = lexical_source
        self._vector_source = vector_source

    def run_case(
        self,
        *,
        case_id: str,
        query: str,
        chunks: Sequence[Chunk],
        candidate_limit: int,
        rrf_k: int,
    ) -> CaseRetrievalResult:
        rankings: dict[BenchmarkMode, RawRanking] = {}
        failures: dict[BenchmarkMode, ModeFailure] = {}
        source_candidates: dict[BenchmarkMode, list[RetrievalCandidate]] = {}

        for mode, source, default_stage in (
            ("keyword", self._lexical_source, "lexical"),
            ("vector", self._vector_source, "vector_query"),
        ):
            started_at = _utc_text()
            started_monotonic = time.perf_counter()
            try:
                candidates = source.retrieve(query, chunks, candidate_limit)
                source_candidates[mode] = candidates
                rankings[mode] = _ranking(
                    case_id=case_id,
                    mode=mode,
                    candidates=candidates,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                )
            except Exception as error:
                cause = error.cause if isinstance(error, VectorSourceExecutionError) else error
                failures[mode] = ModeFailure(
                    case_id=case_id,
                    mode=mode,
                    stage=_stage(error, default_stage),
                    reason_code=_reason(cause),
                    duration_ms=(time.perf_counter() - started_monotonic) * 1000,
                )

        hybrid_started_at = _utc_text()
        hybrid_started_monotonic = time.perf_counter()
        if "keyword" not in source_candidates or "vector" not in source_candidates:
            missing = "keyword" if "keyword" not in source_candidates else "vector"
            failures["hybrid_rrf"] = ModeFailure(
                case_id=case_id,
                mode="hybrid_rrf",
                stage="fusion",
                reason_code=f"dependent_{missing}_failure",
                duration_ms=(time.perf_counter() - hybrid_started_monotonic) * 1000,
            )
        else:
            try:
                fused = fuse_candidates(
                    source_candidates["keyword"],
                    source_candidates["vector"],
                    rrf_k=rrf_k,
                    active_sources=("lexical", "vector"),
                )
                rankings["hybrid_rrf"] = _ranking(
                    case_id=case_id,
                    mode="hybrid_rrf",
                    candidates=fused,
                    started_at=hybrid_started_at,
                    started_monotonic=hybrid_started_monotonic,
                )
            except Exception as error:
                reason = (
                    "candidate_identity_conflict"
                    if "identity conflict" in str(error)
                    else "fusion_error"
                )
                failures["hybrid_rrf"] = ModeFailure(
                    case_id=case_id,
                    mode="hybrid_rrf",
                    stage="fusion",
                    reason_code=reason,
                    duration_ms=(time.perf_counter() - hybrid_started_monotonic) * 1000,
                )

        canonical_modes: tuple[BenchmarkMode, ...] = (
            "keyword",
            "vector",
            "hybrid_rrf",
        )
        return CaseRetrievalResult(
            case_id=case_id,
            rankings=tuple(rankings[mode] for mode in canonical_modes if mode in rankings),
            failures=tuple(failures[mode] for mode in canonical_modes if mode in failures),
        )


__all__ = ["RetrievalBenchmarkRunner"]
