from datetime import datetime, timezone

from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.retriever import LexicalCandidateSource
import pytest

from paper_agent.techscout.context import (
    CandidateContextData,
    ContextEngine,
    ContextStage,
    HybridContextRetriever,
)
from paper_agent.techscout.models import (
    Candidate,
    CandidateEvidence,
    EnvironmentSpec,
    EvidenceKind,
    PocResult,
    PocStatus,
    ResearchRequest,
    SourceChunk,
    SourceDocument,
    SourceType,
)
from paper_agent.techscout.runtime_skills import fixed_skill_registry


def _request() -> ResearchRequest:
    return ResearchRequest(
        run_id="run:context-test",
        question="Which vector store supports filtering?",
        project_context="Local RAG",
        environment=EnvironmentSpec(
            python_version="3.11", operating_system="linux", deployment="local"
        ),
        hard_constraints=("metadata filtering", "persistence"),
        candidates=(
            Candidate(candidate_id="candidate:a", name="Alpha"),
            Candidate(candidate_id="candidate:b", name="Beta"),
        ),
    )


def _source(
    candidate: str,
    suffix: str,
    *,
    version: str | None = None,
    as_of: datetime = datetime(2026, 8, 9, tzinfo=timezone.utc),
) -> SourceDocument:
    return SourceDocument(
        source_id=f"source:{suffix}",
        candidate_id=candidate,
        source_type=SourceType.OFFICIAL_DOCUMENTATION,
        url=f"https://docs.example.com/{suffix}",
        title=f"Docs {suffix}",
        version=version,
        as_of=as_of,
        content_sha256="a" * 64,
    )


def _engine() -> ContextEngine:
    service = HybridEvidenceRetriever(
        lexical_source=LexicalCandidateSource(),
        vector_source=None,
        requested_mode="lexical",
        candidate_k=8,
        top_k=8,
        rrf_k=60,
    )
    return ContextEngine(HybridContextRetriever(service))


def test_planning_packet_contains_summaries_but_loads_no_research_data() -> None:
    packet = _engine().build(
        packet_id="context:planning",
        stage=ContextStage.INTAKE_PLANNING,
        request=_request(),
        skills=fixed_skill_registry().all(),
    )

    assert len(packet.skill_summaries) == 4
    assert packet.sources == ()
    assert packet.chunks == ()
    assert packet.evidence == ()


def test_research_packet_excludes_other_candidates_and_unrelated_full_content() -> None:
    source_a = _source("candidate:a", "a")
    source_b = _source("candidate:b", "b")
    relevant = SourceChunk(
        chunk_id="chunk:a:filtering",
        source_id=source_a.source_id,
        text="Alpha supports metadata filtering and persistence.",
        ordinal=0,
        content_sha256="b" * 64,
    )
    unrelated = SourceChunk(
        chunk_id="chunk:b:full-page",
        source_id=source_b.source_id,
        text="UNRELATED_FULL_PAGE " * 500,
        ordinal=0,
        content_sha256="c" * 64,
    )

    packet = _engine().build(
        packet_id="context:research:a",
        stage=ContextStage.RESEARCH,
        request=_request(),
        candidate_context=CandidateContextData(
            candidate_id="candidate:a",
            documents=(source_a,),
            chunks=(relevant,),
        ),
        as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    assert packet.candidate_id == "candidate:a"
    assert packet.sources == (source_a,)
    assert packet.chunks == (relevant,)
    assert "UNRELATED_FULL_PAGE" not in packet.model_dump_json()
    with pytest.raises(ValueError, match="unrelated source"):
        CandidateContextData(
            candidate_id="candidate:a",
            documents=(source_a, source_b),
            chunks=(relevant, unrelated),
        )


def test_validation_packet_uses_structured_evidence_not_raw_chunks() -> None:
    source = _source("candidate:a", "a")
    chunk = SourceChunk(
        chunk_id="chunk:a:filtering",
        source_id=source.source_id,
        text="Raw source excerpt",
        ordinal=0,
        content_sha256="b" * 64,
    )
    evidence = CandidateEvidence(
        evidence_id="evidence:a:filtering",
        candidate_id="candidate:a",
        constraint="metadata filtering",
        claim="Alpha supports filtering.",
        source_ids=(source.source_id,),
        chunk_ids=(chunk.chunk_id,),
        kind=EvidenceKind.RETRIEVED_FACT,
    )

    packet = _engine().build(
        packet_id="context:validation:a",
        stage=ContextStage.VALIDATION,
        request=_request(),
        candidate_context=CandidateContextData(
            candidate_id="candidate:a",
            documents=(source,),
            chunks=(chunk,),
            evidence=(evidence,),
        ),
        as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
        poc_result=PocResult(
            poc_result_id="poc-result:a",
            poc_plan_id="poc-plan:a",
            candidate_id="candidate:a",
            status=PocStatus.PASSED,
            exit_code=0,
            timed_out=False,
            duration_ms=10,
        ),
        gate_rules=("cover every hard constraint",),
    )

    assert packet.evidence == (evidence,)
    assert packet.chunks == ()
    assert packet.poc_result is not None
    assert packet.poc_result.candidate_id == "candidate:a"


def test_context_rejects_cross_candidate_poc_and_filters_version_and_date() -> None:
    matching = _source("candidate:a", "matching", version="2.0")
    wrong_version = _source("candidate:a", "old", version="1.0")
    future = _source(
        "candidate:a",
        "future",
        version="2.0",
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    context = CandidateContextData(
        candidate_id="candidate:a",
        documents=(matching, wrong_version, future),
        chunks=tuple(
            SourceChunk(
                chunk_id=f"chunk:{source.source_id}",
                source_id=source.source_id,
                text="metadata filtering persistence",
                ordinal=0,
                content_sha256="d" * 64,
            )
            for source in (matching, wrong_version, future)
        ),
    )
    packet = _engine().build(
        packet_id="context:research:filtered",
        stage=ContextStage.RESEARCH,
        request=_request(),
        candidate_context=context,
        candidate_version="2.0",
        as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )
    assert packet.sources == (matching,)
    assert packet.candidate_version == "2.0"

    wrong_poc = PocResult(
        poc_result_id="poc-result:b",
        poc_plan_id="poc-plan:b",
        candidate_id="candidate:b",
        status=PocStatus.PASSED,
        exit_code=0,
        timed_out=False,
        duration_ms=10,
    )
    with pytest.raises(ValueError, match="unrelated candidate PoC"):
        _engine().build(
            packet_id="context:validation:cross-candidate",
            stage=ContextStage.VALIDATION,
            request=_request(),
            candidate_context=context,
            as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
            poc_result=wrong_poc,
        )
