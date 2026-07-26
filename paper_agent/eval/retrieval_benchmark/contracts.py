from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator

from paper_agent.modeling import StrictModel


BenchmarkMode = Literal["keyword", "vector", "hybrid_rrf"]
RetrievalSourceName = Literal["lexical", "vector"]
CANONICAL_MODES: tuple[BenchmarkMode, ...] = ("keyword", "vector", "hybrid_rrf")
CANONICAL_KS = (1, 3, 5, 8, 10)


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _unique_non_blank(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if not values or any(not value.strip() for value in values):
        raise ValueError(f"{label} must contain non-blank values")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


def _finite_non_negative(value: float) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError("must be finite and non-negative")
    return value


class FrozenBenchmarkModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetrievalBenchmarkConfig(FrozenBenchmarkModel):
    schema_version: Literal["1.0"]
    dataset_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_case_ids: tuple[str, ...]
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_chunk_sha256: tuple[str, ...]
    candidate_limit: StrictInt = Field(gt=0)
    timeout_seconds: StrictFloat
    rrf_k: StrictInt = Field(gt=0)
    embedding_model: str
    embedding_model_version: str
    chunking_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metric_versions: tuple[str, ...]
    ks: tuple[StrictInt, ...]
    primary_k: StrictInt
    modes: tuple[BenchmarkMode, ...]

    _model_is_non_blank = field_validator(
        "embedding_model", "embedding_model_version"
    )(_non_blank)
    _timeout_is_valid = field_validator("timeout_seconds")(_finite_non_negative)

    @field_validator("ordered_case_ids")
    @classmethod
    def _case_ids_are_valid(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_non_blank(values, "ordered case IDs")

    @field_validator("ordered_chunk_sha256")
    @classmethod
    def _chunk_hashes_are_valid(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _unique_non_blank(values, "ordered chunk hashes")
        if any(len(value) != 64 or set(value) - set("0123456789abcdef") for value in values):
            raise ValueError("ordered chunk hashes must be lowercase SHA-256 values")
        return values

    @field_validator("metric_versions")
    @classmethod
    def _metric_versions_are_valid(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_non_blank(values, "metric versions")

    @model_validator(mode="after")
    def _fairness_dimensions_are_canonical(self) -> RetrievalBenchmarkConfig:
        if self.ks != CANONICAL_KS:
            raise ValueError("ks must equal the canonical ordered K values")
        if self.primary_k != 8:
            raise ValueError("primary_k must be 8")
        if self.modes != CANONICAL_MODES:
            raise ValueError("modes must use canonical order")
        return self


class BenchmarkFingerprint(FrozenBenchmarkModel):
    algorithm: Literal["sha256"]
    value: str = Field(pattern=r"^[0-9a-f]{64}$")


def compute_benchmark_fingerprint(
    config: RetrievalBenchmarkConfig,
) -> BenchmarkFingerprint:
    payload = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return BenchmarkFingerprint(
        algorithm="sha256",
        value=hashlib.sha256(payload).hexdigest(),
    )


class RankedCandidate(FrozenBenchmarkModel):
    chunk_id: str
    rank: StrictInt = Field(gt=0)
    score: StrictFloat
    retrieval_sources: tuple[RetrievalSourceName, ...]

    _chunk_id_is_non_blank = field_validator("chunk_id")(_non_blank)

    @field_validator("score")
    @classmethod
    def _score_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value

    @field_validator("retrieval_sources")
    @classmethod
    def _sources_are_canonical(
        cls, values: tuple[RetrievalSourceName, ...]
    ) -> tuple[RetrievalSourceName, ...]:
        if values not in (("lexical",), ("vector",), ("lexical", "vector")):
            raise ValueError("retrieval sources must use a canonical shape")
        return values


class RawRanking(FrozenBenchmarkModel):
    schema_version: Literal["1.0"]
    case_id: str
    mode: BenchmarkMode
    candidates: tuple[RankedCandidate, ...]
    started_at: str
    finished_at: str
    duration_ms: StrictFloat

    _text_is_non_blank = field_validator("case_id", "started_at", "finished_at")(
        _non_blank
    )
    _duration_is_valid = field_validator("duration_ms")(_finite_non_negative)

    @model_validator(mode="after")
    def _ranking_is_consistent(self) -> RawRanking:
        chunk_ids = [candidate.chunk_id for candidate in self.candidates]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("ranking chunk IDs must be unique")
        if [candidate.rank for candidate in self.candidates] != list(
            range(1, len(self.candidates) + 1)
        ):
            raise ValueError("candidate ranks must be contiguous and ordered")
        allowed_sources = {
            "keyword": {("lexical",)},
            "vector": {("vector",)},
            "hybrid_rrf": {("lexical",), ("vector",), ("lexical", "vector")},
        }
        if any(
            candidate.retrieval_sources not in allowed_sources[self.mode]
            for candidate in self.candidates
        ):
            raise ValueError("candidate retrieval sources do not match ranking mode")
        return self


class ModeFailure(FrozenBenchmarkModel):
    case_id: str
    mode: BenchmarkMode
    stage: str
    reason_code: str
    duration_ms: StrictFloat

    _text_is_non_blank = field_validator("case_id", "stage", "reason_code")(_non_blank)
    _duration_is_valid = field_validator("duration_ms")(_finite_non_negative)


class CaseRetrievalResult(FrozenBenchmarkModel):
    case_id: str
    rankings: tuple[RawRanking, ...]
    failures: tuple[ModeFailure, ...]

    _case_id_is_non_blank = field_validator("case_id")(_non_blank)

    @model_validator(mode="after")
    def _outcomes_cover_each_mode_once(self) -> CaseRetrievalResult:
        ranking_modes = tuple(ranking.mode for ranking in self.rankings)
        failure_modes = tuple(failure.mode for failure in self.failures)
        all_modes = ranking_modes + failure_modes
        if len(all_modes) != len(set(all_modes)) or set(all_modes) != set(CANONICAL_MODES):
            raise ValueError("each canonical mode must have exactly one outcome")
        if ranking_modes != tuple(mode for mode in CANONICAL_MODES if mode in ranking_modes):
            raise ValueError("rankings must use canonical mode order")
        if failure_modes != tuple(mode for mode in CANONICAL_MODES if mode in failure_modes):
            raise ValueError("failures must use canonical mode order")
        if any(item.case_id != self.case_id for item in (*self.rankings, *self.failures)):
            raise ValueError("nested outcome case IDs must match the result case ID")
        return self


__all__ = [
    "BenchmarkFingerprint",
    "BenchmarkMode",
    "CANONICAL_KS",
    "CANONICAL_MODES",
    "CaseRetrievalResult",
    "ModeFailure",
    "RankedCandidate",
    "RawRanking",
    "RetrievalBenchmarkConfig",
    "compute_benchmark_fingerprint",
]
