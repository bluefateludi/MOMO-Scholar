from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import httpx
import pymupdf

from paper_agent.config import Settings, load_settings
from paper_agent.evidence import EvidencePackBuilder
from paper_agent.evidence.citation_checker import (
    check_paper_analysis,
    check_survey_draft,
    require_publishable_report,
)
from paper_agent.fulltext import DocumentAcquirer, FullTextDownloader, PdfParser
from paper_agent.fulltext.models import DocumentRecord
from paper_agent.generation.dashscope import DashScopeGenerationProvider
from paper_agent.generation.dashscope_transport import DashScopeChatTransport
from paper_agent.observability import (
    RunCounts,
    RunEvent,
    RunIssue,
    RunRecorder,
    SafeRunSettings,
    UsageTotals,
)
from paper_agent.observability.recorder import utc_now
from paper_agent.rendering.markdown import render_formal_report
from paper_agent.retrieval.arxiv import search_arxiv
from paper_agent.retrieval.normalize import dedupe_papers
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import CheckedPaperAnalysis
from paper_agent.synthesis.paper_reader import PaperAnalyzer
from paper_agent.synthesis.survey import SurveySynthesizer
from paper_agent.text.chunker import chunk_document
from paper_agent.text.loader import acquire_paper_document
from paper_agent.vector.bailian import EmbeddingTransport, HttpxEmbeddingTransport
from paper_agent.evidence.contracts import EvidenceRetrievalService
from paper_agent.io import append_json_line, create_run_dir
from paper_agent.text.chunker import chunk_text
from paper_agent.text.loader import load_paper_text


SearchFn = Callable[[str, int], list[Paper]]


class RecorderFactory(Protocol):
    def __call__(self, **kwargs: object) -> RunRecorder: ...


@dataclass(frozen=True, slots=True)
class PipelineDependencies:
    search: SearchFn
    downloader: FullTextDownloader
    parser: PdfParser
    evidence_packs: EvidencePackBuilder
    analyzer: PaperAnalyzer
    synthesizer: SurveySynthesizer
    recorder_factory: RecorderFactory = RunRecorder.start
    embedding_transport: EmbeddingTransport | None = None


@dataclass(frozen=True, slots=True)
class PipelineResult:
    run_dir: Path
    status: Literal["completed", "completed_with_degradation"]


def _versions() -> dict[str, str]:
    return {
        "paper-agent": "0.1.0",
        "pymupdf": str(pymupdf.VersionBind),
        "mupdf": str(pymupdf.mupdf_version_tuple),
    }


def _add_usage(total: UsageTotals, generation: object) -> UsageTotals:
    values = total.model_dump()
    values["operations"] += 1
    values["http_attempts"] += generation.attempts
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        supplied = getattr(generation, field)
        if supplied is not None:
            values[field] = supplied if values[field] is None else values[field] + supplied
    return UsageTotals.model_validate(values)


def _counts(
    papers: Sequence[Paper],
    records: Sequence[DocumentRecord],
    analyses: Sequence[CheckedPaperAnalysis],
    evidence: Sequence[Evidence],
) -> RunCounts:
    return RunCounts(
        selected_papers=len(papers),
        pdf_documents=sum(record.content_source == "pdf" for record in records),
        abstract_documents=sum(
            record.content_source == "abstract" for record in records
        ),
        explicit_abstract_documents=sum(
            record.content_source == "abstract" and record.fallback_code is None
            for record in records
        ),
        pdf_fallback_documents=sum(
            record.content_source == "abstract" and record.fallback_code is not None
            for record in records
        ),
        excluded_papers=len(papers) - len(records),
        successful_analyses=len(analyses),
        evidence_items=len(evidence),
    )


def _production_dependencies(
    settings: Settings, stack: ExitStack
) -> PipelineDependencies:
    api_key = settings.dashscope_api_key
    if not api_key or not api_key.strip():
        raise ValueError("DASHSCOPE_API_KEY is required for generation")
    pdf_client = stack.enter_context(httpx.Client())
    embedding_transport = stack.enter_context(HttpxEmbeddingTransport())
    generation_client = stack.enter_context(httpx.Client())
    provider = DashScopeGenerationProvider(
        api_key=api_key,
        model=settings.dashscope_generation_model,
        base_url=settings.dashscope_generation_base_url,
        transport=DashScopeChatTransport(generation_client),
    )
    return PipelineDependencies(
        search=search_arxiv,
        downloader=FullTextDownloader(
            client=pdf_client,
            timeout_seconds=settings.pdf_download_timeout_seconds,
            max_bytes=settings.pdf_max_bytes,
        ),
        parser=PdfParser(max_pages=settings.pdf_max_pages),
        evidence_packs=EvidencePackBuilder(
            settings=settings, embedding_transport=embedding_transport
        ),
        analyzer=PaperAnalyzer(provider),
        synthesizer=SurveySynthesizer(provider),
        embedding_transport=embedding_transport,
    )


def run_pipeline(
    question: str,
    output_base: Path = Path("outputs"),
    limit: int = 5,
    no_pdf: bool = False,
    search_fn: SearchFn | None = None,
    *,
    settings: Settings | None = None,
    dependencies: PipelineDependencies | None = None,
    retrieval_service: EvidenceRetrievalService | None = None,
) -> PipelineResult:
    if retrieval_service is not None:
        papers = dedupe_papers((search_fn or search_arxiv)(question, limit))[:limit]
        run_dir = create_run_dir(output_base, question)
        log_path = run_dir / "logs.jsonl"
        log_path.touch()
        chunks = [
            chunk
            for paper in papers
            for chunk in chunk_text(
                paper.paper_id, load_paper_text(paper, no_pdf=no_pdf)
            )
        ]

        def legacy_sink(event: object) -> None:
            append_json_line(log_path, event.model_dump(mode="json"))

        retrieval_service.retrieve(question, chunks, run_dir.name, legacy_sink)
        raise AssertionError("legacy retrieval service unexpectedly returned")
    active_settings = settings if settings is not None else load_settings()
    if (
        not active_settings.dashscope_api_key
        or not active_settings.dashscope_api_key.strip()
    ):
        raise ValueError("DASHSCOPE_API_KEY is required for generation")

    with ExitStack() as stack:
        deps = dependencies or _production_dependencies(active_settings, stack)
        if search_fn is not None:
            deps = PipelineDependencies(
                search=search_fn, downloader=deps.downloader, parser=deps.parser,
                evidence_packs=deps.evidence_packs, analyzer=deps.analyzer,
                synthesizer=deps.synthesizer, recorder_factory=deps.recorder_factory,
                embedding_transport=deps.embedding_transport,
            )
        safe_settings = SafeRunSettings.from_settings(
            active_settings, chunk_max_words=180, chunk_overlap_words=30
        )
        recorder = deps.recorder_factory(
            output_base=output_base, question=question, requested_limit=limit,
            no_pdf=no_pdf,
            safe_settings=safe_settings,
            component_versions=_versions(),
        )
        timings: dict[str, float] = {}

        def timed(stage: str, operation: Callable[[], object]) -> object:
            started = time.monotonic()
            try:
                return operation()
            finally:
                timings[stage] = timings.get(stage, 0.0) + max(0.0, time.monotonic() - started)

        papers = timed(
            "search", lambda: dedupe_papers(deps.search(question, limit))[:limit]
        )
        recorder.write_papers(papers)
        acquirer = DocumentAcquirer(downloader=deps.downloader, parser=deps.parser)
        records: list[DocumentRecord] = []
        evidence: list[Evidence] = []
        analyses: list[CheckedPaperAnalysis] = []
        retrievals = []
        degradations = []
        usage = UsageTotals(operations=0, http_attempts=0)

        for paper in papers:
            outcome = timed(
                "acquisition",
                lambda paper=paper: acquire_paper_document(
                    acquirer, paper, no_pdf=no_pdf
                ),
            )
            degradations.extend(outcome.degradations)
            if outcome.document is None or outcome.record is None:
                continue
            chunked = timed("chunking", lambda document=outcome.document: chunk_document(document))
            record = outcome.record.model_copy(
                update={
                    "warnings": list(
                        dict.fromkeys([*outcome.record.warnings, *chunked.warnings])
                    )
                }
            )
            records.append(record)

            def retrieval_event(event: object, paper_id: str = paper.paper_id) -> None:
                recorder.emit(
                    RunEvent(
                        timestamp=utc_now(),
                        run_id=recorder.run_id,
                        stage="retrieval",
                        operation="retrieve_evidence",
                        status=event.status,
                        paper_id=paper_id,
                        code=event.degradation_code or event.error_code,
                        attributes=event.model_dump(mode="json"),
                    )
                )

            pack = timed("retrieval", lambda paper=paper, chunked=chunked: deps.evidence_packs.build(question=question, paper_id=paper.paper_id, chunks=chunked.chunks, run_id=recorder.run_id, event_sink=retrieval_event))
            evidence.extend(pack.evidence)
            retrievals.append(pack.retrieval)
            if pack.retrieval.degraded:
                degradations.append(
                    RunIssue(
                        stage="retrieval",
                        code=pack.retrieval.degradation_code or "retrieval_degraded",
                        paper_id=paper.paper_id,
                    )
                )
            generated = timed("analysis", lambda paper=paper, pack=pack: deps.analyzer.analyze(paper=paper, evidence_pack=pack, timeout=active_settings.dashscope_generation_timeout_seconds))
            usage = _add_usage(usage, generated)
            checked = check_paper_analysis(generated.result, pack.evidence, run_id=recorder.run_id)
            if checked.has_supported_finding:
                analyses.append(checked.analysis)

        minimum = 2 if len(papers) >= 2 else 1
        if len(analyses) < minimum:
            raise ValueError("insufficient_successful_analyses")
        survey = timed("synthesis", lambda: deps.synthesizer.synthesize(question=question, analyses=analyses, evidence=evidence, timeout=active_settings.dashscope_generation_timeout_seconds))
        usage = _add_usage(usage, survey)
        report = check_survey_draft(question, survey.result, evidence, run_id=recorder.run_id)
        require_publishable_report(report)
        status: Literal["completed", "completed_with_degradation"] = "completed_with_degradation" if degradations else "completed"
        markdown = render_formal_report(status=status, papers=[paper for paper in papers if any(record.paper_id == paper.paper_id for record in records)], documents=records, evidence=evidence, report=report)
        recorder.write_documents(records)
        recorder.write_evidence(evidence)
        recorder.write_analyses(analyses)
        recorder.publish_report(report, markdown)
        recorder.complete(status=status, counts=_counts(papers, records, analyses, evidence), retrieval_outcomes=retrievals, stage_elapsed_seconds=timings, usage=usage, degradations=degradations)
        return PipelineResult(run_dir=recorder.run_dir, status=status)
