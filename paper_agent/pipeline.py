from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

from paper_agent.config import Settings, load_settings
from paper_agent.evidence import (
    EvidenceRetrievalService,
    RetrievalConfigurationError,
    RetrievalDiagnostics,
    RetrievalEvent,
    RetrievalOutcome,
    build_retrieval_service,
)
from paper_agent.evidence.citation_checker import check_claims
from paper_agent.io import append_json_line, create_run_dir, write_json, write_text
from paper_agent.rendering.markdown import render_evidence_review
from paper_agent.retrieval.arxiv import search_arxiv
from paper_agent.retrieval.normalize import dedupe_papers
from paper_agent.schemas import Paper
from paper_agent.synthesis.paper_reader import analyze_paper
from paper_agent.synthesis.survey import synthesize_claims
from paper_agent.text.chunker import chunk_text
from paper_agent.text.loader import load_paper_text

SearchFn = Callable[[str, int], list[Paper]]


def _empty_outcome(settings: Settings, event_sink) -> RetrievalOutcome:
    values = dict(
        requested_mode=settings.retrieval_mode,
        actual_mode="lexical",
        lexical_candidate_count=0,
        vector_candidate_count=0,
        fused_candidate_count=0,
        returned_evidence_count=0,
        vector_attempted=False,
        degraded=False,
        degradation_code=None,
    )
    diagnostics = RetrievalDiagnostics.model_validate(values)
    event_sink(
        RetrievalEvent.model_validate(
            {
                **values,
                "status": "ok",
                "failure_stage": None,
                "error_code": None,
            }
        )
    )
    return RetrievalOutcome(evidence=(), diagnostics=diagnostics)


def _assembly_error_event(settings: Settings) -> RetrievalEvent:
    return RetrievalEvent(
        status="error",
        requested_mode=settings.retrieval_mode,
        actual_mode=None,
        lexical_candidate_count=0,
        vector_candidate_count=0,
        fused_candidate_count=0,
        returned_evidence_count=0,
        vector_attempted=False,
        degraded=False,
        degradation_code=None,
        failure_stage="assembly",
        error_code="retrieval_configuration_error",
    )


def run_pipeline(
    question: str,
    output_base: Path = Path("outputs"),
    limit: int = 5,
    no_pdf: bool = False,
    search_fn: SearchFn = search_arxiv,
    *,
    settings: Settings | None = None,
    retrieval_service: EvidenceRetrievalService | None = None,
) -> Path:
    papers = dedupe_papers(search_fn(question, limit))[:limit]
    run_dir = create_run_dir(output_base, question)
    run_id = run_dir.name
    log_path = run_dir / "logs.jsonl"
    write_text(log_path, "")
    write_json(run_dir / "papers.json", [paper.model_dump() for paper in papers])

    chunks = []
    for paper in papers:
        text = load_paper_text(paper, no_pdf=no_pdf)
        chunks.extend(chunk_text(paper.paper_id, text))

    def event_sink(event: RetrievalEvent) -> None:
        append_json_line(log_path, event.model_dump(mode="json"))

    if retrieval_service is not None:
        outcome = retrieval_service.retrieve(question, chunks, run_id, event_sink)
    else:
        active_settings = settings if settings is not None else load_settings()
        if not chunks:
            outcome = _empty_outcome(active_settings, event_sink)
        else:
            with ExitStack() as stack:
                try:
                    service = stack.enter_context(
                        build_retrieval_service(active_settings)
                    )
                except RetrievalConfigurationError:
                    event_sink(_assembly_error_event(active_settings))
                    raise
                outcome = service.retrieve(question, chunks, run_id, event_sink)

    evidence = outcome.evidence
    analyses = [analyze_paper(paper, evidence) for paper in papers]
    claims = synthesize_claims(question, papers, analyses, evidence)
    checked_claims = check_claims(claims, evidence, run_id=run_id)

    write_json(run_dir / "evidence.json", [item.model_dump() for item in evidence])
    report_md = render_evidence_review(question, papers, evidence, checked_claims)
    write_text(run_dir / "report.md", report_md)
    return run_dir
