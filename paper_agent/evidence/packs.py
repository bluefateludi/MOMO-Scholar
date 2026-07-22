from collections.abc import Sequence
from typing import ContextManager, Protocol

from paper_agent.config import Settings
from paper_agent.modeling import StrictModel
from paper_agent.observability.models import RetrievalRecord
from paper_agent.schemas import Chunk, Evidence
from paper_agent.vector.bailian import EmbeddingTransport

from .contracts import EvidenceRetrievalService, RetrievalEventSink
from .factory import build_retrieval_service


class EvidencePack(StrictModel):
    paper_id: str
    evidence: list[Evidence]
    retrieval: RetrievalRecord


class RetrievalServiceFactory(Protocol):
    def __call__(
        self,
        settings: Settings,
        *,
        transport: EmbeddingTransport | None = None,
    ) -> ContextManager[EvidenceRetrievalService]: ...


class EvidencePackBuilder:
    def __init__(
        self,
        *,
        settings: Settings,
        embedding_transport: EmbeddingTransport | None,
        service_factory: RetrievalServiceFactory = build_retrieval_service,
    ) -> None:
        self.settings = settings
        self._embedding_transport = embedding_transport
        self._service_factory = service_factory

    def build(
        self,
        *,
        question: str,
        paper_id: str,
        chunks: Sequence[Chunk],
        run_id: str,
        event_sink: RetrievalEventSink | None = None,
    ) -> EvidencePack:
        if any(chunk.paper_id != paper_id for chunk in chunks):
            raise ValueError("all chunks must match paper_id")

        chunk_index = {chunk.chunk_id: chunk for chunk in chunks}
        scoped_run_id = f"{run_id}:paper:{paper_id}"
        with self._service_factory(
            self.settings, transport=self._embedding_transport
        ) as service:
            outcome = service.retrieve(
                question, chunks, scoped_run_id, event_sink
            )

            selected: list[Evidence] = []
            seen_chunks: set[str] = set()
            for item in outcome.evidence:
                self._validate_evidence(
                    item,
                    paper_id=paper_id,
                    scoped_run_id=scoped_run_id,
                    chunk_index=chunk_index,
                )
                if item.chunk_id in seen_chunks:
                    continue
                seen_chunks.add(item.chunk_id)
                if len(selected) < self.settings.analysis_evidence_per_paper:
                    selected.append(item)

        diagnostics = outcome.diagnostics
        return EvidencePack(
            paper_id=paper_id,
            evidence=selected,
            retrieval=RetrievalRecord(
                paper_id=paper_id,
                requested_mode=diagnostics.requested_mode,
                actual_mode=diagnostics.actual_mode,
                degraded=diagnostics.degraded,
                degradation_code=diagnostics.degradation_code,
            ),
        )

    @staticmethod
    def _validate_evidence(
        item: Evidence,
        *,
        paper_id: str,
        scoped_run_id: str,
        chunk_index: dict[str, Chunk],
    ) -> None:
        if not item.evidence_id.startswith(f"{scoped_run_id}:ev_"):
            raise ValueError("evidence belongs to a foreign run")
        if item.paper_id != paper_id:
            raise ValueError("evidence belongs to a foreign paper")
        chunk = chunk_index.get(item.chunk_id)
        if chunk is None:
            raise ValueError("evidence references a foreign chunk")
        if item.quote != chunk.text:
            raise ValueError("evidence quote does not match its chunk")
        if item.section != chunk.section:
            raise ValueError("evidence section does not match its chunk")
        if item.page != chunk.page:
            raise ValueError("evidence page does not match its chunk")
