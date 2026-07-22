from collections.abc import Sequence
from typing import Literal

from paper_agent.config import RetrievalMode
from paper_agent.schemas import Chunk, Evidence

from .contracts import (
    CandidateSource,
    RetrievalEventSink,
    RetrievalSourceUnavailable,
)
from .fusion import fuse_candidates
from .models import (
    ErrorCode,
    FailureStage,
    RetrievalCandidate,
    RetrievalDiagnostics,
    RetrievalEvent,
    RetrievalOutcome,
)
from .vector_source import VectorSourceExecutionError


ScoreMode = Literal["lexical", "fusion"]


def _candidates_to_evidence(
    candidates: Sequence[RetrievalCandidate],
    *,
    run_id: str,
    top_k: int,
    score_mode: ScoreMode,
) -> tuple[Evidence, ...]:
    evidence: list[Evidence] = []
    for index, item in enumerate(candidates[:top_k], start=1):
        raw_score = (
            item.lexical_score if score_mode == "lexical" else item.fusion_score
        )
        if raw_score is None:
            raise ValueError(f"candidate lacks {score_mode} score")
        evidence.append(
            Evidence(
                evidence_id=f"{run_id}:ev_{index:03d}",
                paper_id=item.paper_id,
                chunk_id=item.chunk_id,
                section=item.section,
                page=item.page,
                claim_type="retrieved",
                quote=item.text,
                relevance_score=round(min(raw_score, 1.0), 4),
            )
        )
    return tuple(evidence)


class HybridEvidenceRetriever:
    def __init__(
        self,
        *,
        lexical_source: CandidateSource,
        vector_source: CandidateSource | None,
        requested_mode: RetrievalMode,
        candidate_k: int,
        top_k: int,
        rrf_k: int,
    ) -> None:
        self._lexical_source = lexical_source
        self._vector_source = vector_source
        self._requested_mode = requested_mode
        self._candidate_k = candidate_k
        self._top_k = top_k
        self._rrf_k = rrf_k

    @property
    def requested_mode(self) -> RetrievalMode:
        return self._requested_mode

    @property
    def vector_source(self) -> CandidateSource | None:
        return self._vector_source

    def retrieve(
        self,
        question: str,
        chunks: Sequence[Chunk],
        run_id: str,
        event_sink: RetrievalEventSink | None = None,
    ) -> RetrievalOutcome:
        if not chunks:
            return self._success(
                (), actual_mode="lexical", vector_attempted=False,
                lexical_count=0, vector_count=0, fused_count=0,
                event_sink=event_sink,
            )

        planned_mode: Literal["lexical", "hybrid"] = (
            "lexical"
            if self._requested_mode == "lexical" or self._vector_source is None
            else "hybrid"
        )
        try:
            self._validate(question, run_id)
        except Exception:
            self._emit_error(
                event_sink, planned_mode, False, "validation", "invalid_request"
            )
            raise

        try:
            lexical = self._lexical_source.retrieve(
                question, chunks, self._candidate_k
            )
        except Exception:
            self._emit_error(
                event_sink, planned_mode, False, "lexical", "lexical_failure"
            )
            raise

        if planned_mode == "lexical":
            return self._convert_and_succeed(
                lexical, run_id, "lexical", False, len(lexical), 0,
                event_sink=event_sink,
            )

        assert self._vector_source is not None
        try:
            vector = self._vector_source.retrieve(
                question, chunks, self._candidate_k
            )
        except RetrievalSourceUnavailable as error:
            if self._requested_mode == "auto":
                return self._convert_and_succeed(
                    lexical, run_id, "lexical", True, len(lexical), 0,
                    degraded=True, degradation_code=error.degradation_code,
                    event_sink=event_sink,
                )
            self._emit_error(
                event_sink, "hybrid", True, error.failure_stage,
                "vector_failure", lexical_count=len(lexical),
            )
            raise
        except VectorSourceExecutionError as wrapper:
            self._emit_error(
                event_sink, "hybrid", True, wrapper.failure_stage,
                "vector_failure", lexical_count=len(lexical),
            )
            raise wrapper.cause from None

        try:
            fused = fuse_candidates(
                lexical, vector, rrf_k=self._rrf_k,
                active_sources=("lexical", "vector"),
            )
        except Exception:
            self._emit_error(
                event_sink, "hybrid", True, "fusion", "fusion_failure",
                lexical_count=len(lexical), vector_count=len(vector),
            )
            raise
        return self._convert_and_succeed(
            fused, run_id, "hybrid", True, len(lexical), len(vector),
            event_sink=event_sink,
        )

    def _validate(self, question: str, run_id: str) -> None:
        if not question.strip():
            raise ValueError("question must not be empty")
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        for name, value in (
            ("candidate_k", self._candidate_k),
            ("top_k", self._top_k),
            ("rrf_k", self._rrf_k),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    def _convert_and_succeed(
        self,
        candidates: Sequence[RetrievalCandidate],
        run_id: str,
        actual_mode: Literal["lexical", "hybrid"],
        vector_attempted: bool,
        lexical_count: int,
        vector_count: int,
        *,
        degraded: bool = False,
        degradation_code: str | None = None,
        event_sink: RetrievalEventSink | None,
    ) -> RetrievalOutcome:
        score_mode: ScoreMode = "lexical" if actual_mode == "lexical" else "fusion"
        try:
            evidence = _candidates_to_evidence(
                candidates, run_id=run_id, top_k=self._top_k,
                score_mode=score_mode,
            )
        except Exception:
            self._emit_error(
                event_sink, actual_mode, vector_attempted,
                "evidence_conversion", "evidence_conversion_failure",
                lexical_count=lexical_count, vector_count=vector_count,
                fused_count=len(candidates), degraded=degraded,
                degradation_code=degradation_code,
            )
            raise
        return self._success(
            evidence, actual_mode=actual_mode, vector_attempted=vector_attempted,
            lexical_count=lexical_count, vector_count=vector_count,
            fused_count=len(candidates), degraded=degraded,
            degradation_code=degradation_code, event_sink=event_sink,
        )

    def _success(
        self,
        evidence: tuple[Evidence, ...],
        *,
        actual_mode: Literal["lexical", "hybrid"],
        vector_attempted: bool,
        lexical_count: int,
        vector_count: int,
        fused_count: int,
        event_sink: RetrievalEventSink | None,
        degraded: bool = False,
        degradation_code: str | None = None,
    ) -> RetrievalOutcome:
        values = dict(
            requested_mode=self._requested_mode,
            actual_mode=actual_mode,
            lexical_candidate_count=lexical_count,
            vector_candidate_count=vector_count,
            fused_candidate_count=fused_count,
            returned_evidence_count=len(evidence),
            vector_attempted=vector_attempted,
            degraded=degraded,
            degradation_code=degradation_code,
        )
        diagnostics = RetrievalDiagnostics.model_validate(values)
        self._deliver(
            event_sink,
            RetrievalEvent.model_validate(
                {**values, "status": "ok", "failure_stage": None, "error_code": None}
            ),
        )
        return RetrievalOutcome(evidence=evidence, diagnostics=diagnostics)

    def _emit_error(
        self,
        event_sink: RetrievalEventSink | None,
        actual_mode: Literal["lexical", "hybrid"],
        vector_attempted: bool,
        failure_stage: FailureStage,
        error_code: ErrorCode,
        *,
        lexical_count: int = 0,
        vector_count: int = 0,
        fused_count: int = 0,
        degraded: bool = False,
        degradation_code: str | None = None,
    ) -> None:
        self._deliver(
            event_sink,
            RetrievalEvent.model_validate(
                {
                    "status": "error",
                    "requested_mode": self._requested_mode,
                    "actual_mode": actual_mode,
                    "lexical_candidate_count": lexical_count,
                    "vector_candidate_count": vector_count,
                    "fused_candidate_count": fused_count,
                    "returned_evidence_count": 0,
                    "vector_attempted": vector_attempted,
                    "degraded": degraded,
                    "degradation_code": degradation_code,
                    "failure_stage": failure_stage,
                    "error_code": error_code,
                }
            ),
        )

    @staticmethod
    def _deliver(
        event_sink: RetrievalEventSink | None, event: RetrievalEvent
    ) -> None:
        if event_sink is not None:
            event_sink(event)
