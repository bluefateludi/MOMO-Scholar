from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from paper_agent.evidence.contracts import EvidenceRetrievalService
from paper_agent.schemas import Chunk
from paper_agent.techscout.errors import Failure
from paper_agent.techscout.models import (
    CandidateEvidence,
    JsonObject,
    PocResult,
    ResearchRequest,
    SkillSpec,
    SourceChunk,
    SourceDocument,
)

from .models import CandidateContextData, ContextPacket, ContextStage, SkillSummary


class HybridContextRetriever:
    """Candidate-scoped adapter around the existing lexical/vector/RRF service."""

    def __init__(
        self,
        service: EvidenceRetrievalService,
        *,
        max_chunks: int = 8,
    ) -> None:
        if max_chunks < 1 or max_chunks > 8:
            raise ValueError("context max_chunks must be between 1 and 8")
        self._service = service
        self._max_chunks = max_chunks

    def retrieve(
        self,
        *,
        candidate_id: str,
        question: str,
        documents: Sequence[SourceDocument],
        chunks: Sequence[SourceChunk],
        run_id: str,
        top_k: int | None = None,
    ) -> tuple[SourceChunk, ...]:
        limit = self._max_chunks if top_k is None else top_k
        if limit < 1 or limit > self._max_chunks:
            raise ValueError(
                f"context top_k must be between 1 and {self._max_chunks}"
            )
        source_ids = [document.source_id for document in documents]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source identifiers must be unique")
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunk identifiers must be unique")
        known_source_ids = set(source_ids)
        if any(chunk.source_id not in known_source_ids for chunk in chunks):
            raise ValueError("source chunk references an unknown document")
        selected_source_ids = {
            document.source_id
            for document in documents
            if document.candidate_id == candidate_id
        }
        scoped = [chunk for chunk in chunks if chunk.source_id in selected_source_ids]
        legacy = [
            Chunk(
                chunk_id=chunk.chunk_id,
                paper_id=candidate_id,
                text=chunk.text,
                token_count=max(1, len(chunk.text.split())),
            )
            for chunk in scoped
        ]
        outcome = self._service.retrieve(question, legacy, run_id)
        by_id = {chunk.chunk_id: chunk for chunk in scoped}
        return tuple(
            by_id[item.chunk_id]
            for item in outcome.evidence[:limit]
            if item.chunk_id in by_id
        )


class ContextEngine:
    def __init__(
        self,
        retriever: HybridContextRetriever,
        *,
        max_sources: int = 5,
        max_evidence: int = 12,
    ) -> None:
        if not 1 <= max_sources <= 5:
            raise ValueError("context max_sources must be between 1 and 5")
        if not 1 <= max_evidence <= 12:
            raise ValueError("context max_evidence must be between 1 and 12")
        self._retriever = retriever
        self._max_sources = max_sources
        self._max_evidence = max_evidence

    def build(
        self,
        *,
        packet_id: str,
        stage: ContextStage,
        request: ResearchRequest,
        skills: Sequence[SkillSpec] = (),
        candidate_context: CandidateContextData | None = None,
        as_of: datetime | None = None,
        candidate_version: str | None = None,
        trusted_recipe_schema: JsonObject | None = None,
        poc_result: PocResult | None = None,
        gate_rules: Sequence[str] = (),
        prior_failure: Failure | None = None,
        risks: Sequence[str] = (),
        limitations: Sequence[str] = (),
        top_k: int | None = None,
    ) -> ContextPacket:
        summary = f"{request.question} Project: {request.project_context}"
        if stage is ContextStage.INTAKE_PLANNING:
            return ContextPacket(
                packet_id=packet_id,
                stage=stage,
                request_summary=summary,
                constraints=request.hard_constraints,
                candidate_names=tuple(item.name for item in request.candidates),
                skill_summaries=tuple(self._skill_summary(skill) for skill in skills),
                search_history=(),
                sources=(),
                chunks=(),
                evidence=(),
                gate_rules=(),
                risks=(),
                limitations=(),
            )
        if candidate_context is None:
            raise ValueError("stage context requires candidate-partitioned input")
        if as_of is None or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("stage context requires a timezone-aware as_of cutoff")
        candidate = self._candidate(request, candidate_context.candidate_id)
        target_version = (
            candidate_version or candidate.resolved_version or candidate.requested_version
        )
        scoped_documents = tuple(
            document
            for document in candidate_context.documents
            if document.as_of <= as_of
            and (target_version is None or document.version in {None, target_version})
        )
        scoped_source_ids = {document.source_id for document in scoped_documents}
        scoped_chunks = tuple(
            chunk
            for chunk in candidate_context.chunks
            if chunk.source_id in scoped_source_ids
        )
        scoped_evidence = tuple(
            item
            for item in candidate_context.evidence
        )[: self._max_evidence]
        scoped_history = tuple(
            record
            for record in candidate_context.search_history
        )[:8]

        selected_chunks: tuple[SourceChunk, ...] = ()
        selected_documents: tuple[SourceDocument, ...] = ()
        if stage in {ContextStage.RESEARCH, ContextStage.POC_PLANNING}:
            query = " ".join((request.question, *request.hard_constraints, stage.value))
            selected_chunks = self._retriever.retrieve(
                candidate_id=candidate.candidate_id,
                question=query,
                documents=scoped_documents,
                chunks=scoped_chunks,
                run_id=f"{request.run_id}:context:{stage.value}",
                top_k=top_k,
            )
            selected_source_ids = {chunk.source_id for chunk in selected_chunks}
            if stage is ContextStage.POC_PLANNING:
                selected_source_ids.update(
                    source_id
                    for item in scoped_evidence
                    for source_id in item.source_ids
                )
            selected_documents = tuple(
                document
                for document in scoped_documents
                if document.source_id in selected_source_ids
            )[: self._max_sources]
            allowed_source_ids = {item.source_id for item in selected_documents}
            selected_chunks = tuple(
                chunk for chunk in selected_chunks if chunk.source_id in allowed_source_ids
            )
        if stage is ContextStage.RESEARCH:
            scoped_evidence = ()
        elif stage in {ContextStage.VALIDATION, ContextStage.REPORTING}:
            selected_chunks = ()
            selected_documents = tuple(
                document
                for document in scoped_documents
                if any(document.source_id in item.source_ids for item in scoped_evidence)
            )[: self._max_sources]
        allowed_source_ids = {item.source_id for item in selected_documents}
        scoped_evidence = tuple(
            item
            for item in scoped_evidence
            if not item.source_ids or set(item.source_ids).issubset(allowed_source_ids)
        )

        return ContextPacket(
            packet_id=packet_id,
            stage=stage,
            candidate_id=candidate.candidate_id,
            request_summary=summary,
            constraints=request.hard_constraints,
            candidate_names=(candidate.name,),
            skill_summaries=(),
            search_history=(
                scoped_history if stage is ContextStage.RESEARCH else ()
            ),
            sources=selected_documents,
            chunks=selected_chunks,
            evidence=(
                scoped_evidence
                if stage
                in {
                    ContextStage.POC_PLANNING,
                    ContextStage.VALIDATION,
                    ContextStage.REPORTING,
                }
                else ()
            ),
            candidate_version=target_version,
            as_of=as_of,
            trusted_recipe_schema=(
                trusted_recipe_schema if stage is ContextStage.POC_PLANNING else None
            ),
            poc_result=(
                poc_result
                if stage in {ContextStage.VALIDATION, ContextStage.REPORTING}
                else None
            ),
            gate_rules=(
                tuple(gate_rules) if stage is ContextStage.VALIDATION else ()
            ),
            prior_failure=(
                prior_failure if stage is ContextStage.VALIDATION else None
            ),
            risks=tuple(risks) if stage is ContextStage.REPORTING else (),
            limitations=(
                tuple(limitations) if stage is ContextStage.REPORTING else ()
            ),
        )

    @staticmethod
    def _candidate(request: ResearchRequest, candidate_id: str | None):
        if candidate_id is None:
            raise ValueError("stage context requires candidate_id")
        for candidate in request.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        raise ValueError(f"candidate is not part of request: {candidate_id}")

    @staticmethod
    def _skill_summary(skill: SkillSpec) -> SkillSummary:
        return SkillSummary(
            skill_id=skill.skill_id,
            name=skill.name,
            stage=skill.stage,
            completion_criteria=skill.completion_criteria,
        )
