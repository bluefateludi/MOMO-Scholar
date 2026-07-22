from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace

import pytest
from pydantic import ValidationError

from paper_agent.config import Settings
from paper_agent.evidence.models import RetrievalDiagnostics, RetrievalOutcome
from paper_agent.evidence.packs import EvidencePack, EvidencePackBuilder
from paper_agent.observability.models import RetrievalRecord
from paper_agent.schemas import Chunk, Evidence


def _chunk(
    chunk_id: str,
    *,
    paper_id: str = "paper-1",
    text: str | None = None,
    section: str | None = "Methods",
    page: int | None = 3,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        section=section,
        page=page,
        text=text or f"text for {chunk_id}",
        token_count=4,
    )


def _evidence(
    chunk: Chunk,
    *,
    evidence_id: str | None = None,
    paper_id: str | None = None,
    quote: str | None = None,
    section: str | None = None,
    page: int | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id or f"run-1:paper:{chunk.paper_id}:ev_001",
        paper_id=paper_id or chunk.paper_id,
        chunk_id=chunk.chunk_id,
        section=chunk.section if section is None else section,
        page=chunk.page if page is None else page,
        claim_type="retrieved",
        quote=chunk.text if quote is None else quote,
        relevance_score=0.8,
    )


def _outcome(evidence: Sequence[Evidence]) -> RetrievalOutcome:
    return RetrievalOutcome(
        evidence=tuple(evidence),
        diagnostics=RetrievalDiagnostics(
            lexical_candidate_count=len(evidence),
            vector_candidate_count=0,
            fused_candidate_count=len(evidence),
            returned_evidence_count=len(evidence),
            requested_mode="lexical",
            actual_mode="lexical",
            vector_attempted=False,
            degraded=False,
        ),
    )


class FakeService:
    def __init__(self, outcome: RetrievalOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, list[Chunk], str, object]] = []

    def retrieve(self, question, chunks, run_id, event_sink=None):
        self.calls.append((question, list(chunks), run_id, event_sink))
        return self.outcome


class FakeServiceFactory:
    def __init__(self, outcome: RetrievalOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[Settings, object]] = []
        self.services: list[FakeService] = []
        self.exits = 0

    @contextmanager
    def __call__(self, settings, *, transport=None) -> Iterator[FakeService]:
        self.calls.append((settings, transport))
        service = FakeService(self.outcome)
        self.services.append(service)
        try:
            yield service
        finally:
            self.exits += 1


def _builder(outcome: RetrievalOutcome, *, cap: int = 2):
    transport = object()
    factory = FakeServiceFactory(outcome)
    settings = replace(
        Settings(), retrieval_mode="lexical", analysis_evidence_per_paper=cap
    )
    return (
        EvidencePackBuilder(
            settings=settings,
            embedding_transport=transport,
            service_factory=factory,
        ),
        factory,
        transport,
    )


def test_evidence_pack_is_strict() -> None:
    record = RetrievalRecord(
        paper_id="paper-1",
        requested_mode="lexical",
        actual_mode="lexical",
        degraded=False,
    )

    with pytest.raises(ValidationError):
        EvidencePack(
            paper_id="paper-1", evidence=[], retrieval=record, unexpected=True
        )


def test_builder_scopes_run_deduplicates_by_rank_and_caps() -> None:
    first = _chunk("chunk-1")
    second = _chunk("chunk-2")
    third = _chunk("chunk-3")
    outcome = _outcome(
        [
            _evidence(first, evidence_id="run-1:paper:paper-1:ev_001"),
            _evidence(first, evidence_id="run-1:paper:paper-1:ev_002"),
            _evidence(second, evidence_id="run-1:paper:paper-1:ev_003"),
            _evidence(third, evidence_id="run-1:paper:paper-1:ev_004"),
        ]
    )
    builder, factory, transport = _builder(outcome, cap=2)
    sink = object()

    pack = builder.build(
        question="research question",
        paper_id="paper-1",
        chunks=[first, second, third],
        run_id="run-1",
        event_sink=sink,
    )

    assert [item.chunk_id for item in pack.evidence] == ["chunk-1", "chunk-2"]
    assert all(
        item.evidence_id.startswith("run-1:paper:paper-1:ev_")
        for item in pack.evidence
    )
    assert pack.retrieval.paper_id == "paper-1"
    assert factory.calls == [(builder.settings, transport)]
    assert factory.services[0].calls == [
        ("research question", [first, second, third], "run-1:paper:paper-1", sink)
    ]
    assert factory.exits == 1


@pytest.mark.parametrize(
    "bad_evidence",
    [
        lambda chunk: _evidence(
            chunk, evidence_id="other-run:paper:paper-1:ev_001"
        ),
        lambda chunk: _evidence(chunk, paper_id="paper-2"),
        lambda chunk: _evidence(chunk).model_copy(update={"chunk_id": "missing"}),
        lambda chunk: _evidence(chunk, quote="different quote"),
        lambda chunk: _evidence(chunk, section="Results"),
        lambda chunk: _evidence(chunk, page=4),
    ],
    ids=["foreign-run", "foreign-paper", "foreign-chunk", "quote", "section", "page"],
)
def test_builder_rejects_evidence_outside_scoped_chunk_contract(bad_evidence) -> None:
    chunk = _chunk("chunk-1")
    builder, factory, _ = _builder(_outcome([bad_evidence(chunk)]))

    with pytest.raises(ValueError):
        builder.build(
            question="question",
            paper_id="paper-1",
            chunks=[chunk],
            run_id="run-1",
        )

    assert factory.exits == 1


def test_builder_rejects_foreign_input_chunks_before_creating_service() -> None:
    chunk = _chunk("chunk-1", paper_id="paper-2")
    builder, factory, _ = _builder(_outcome([]))

    with pytest.raises(ValueError, match="paper_id"):
        builder.build(
            question="question",
            paper_id="paper-1",
            chunks=[chunk],
            run_id="run-1",
        )

    assert factory.calls == []


def test_builder_validates_all_returned_evidence_before_applying_cap() -> None:
    first = _chunk("chunk-1")
    second = _chunk("chunk-2")
    outcome = _outcome(
        [
            _evidence(first),
            _evidence(second, quote="invalid after cap"),
        ]
    )
    builder, _, _ = _builder(outcome, cap=1)

    with pytest.raises(ValueError, match="quote"):
        builder.build(
            question="question",
            paper_id="paper-1",
            chunks=[first, second],
            run_id="run-1",
        )
