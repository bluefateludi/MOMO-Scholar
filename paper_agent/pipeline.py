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
from paper_agent.generation import (
    GenerationProviderError,
    GenerationRateLimitError,
    GenerationResponseError,
    GenerationServerError,
    GenerationTimeoutError,
)
from paper_agent.observability import (
    PipelineCorrelationInput,
    RunCounts,
    RunEvent,
    RunIssue,
    RunRecorder,
    SafeRunSettings,
    UsageTotals,
)
from paper_agent.observability.recorder import utc_now
from paper_agent.observability.otlp import OtlpTraceExporter, preflight_otlp
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


class PipelineRunFailed(RuntimeError):
    def __init__(self, run_dir: Path, code: str) -> None:
        self.run_dir = run_dir
        self.code = code
        super().__init__(code)


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


def _add_failure_usage(total: UsageTotals, error: GenerationProviderError) -> UsageTotals:
    metadata = error.metadata
    values = total.model_dump()
    values["operations"] += 1
    values["http_attempts"] += metadata.attempts
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        supplied = getattr(metadata, field)
        if supplied is not None:
            values[field] = supplied if values[field] is None else values[field] + supplied
    return UsageTotals.model_validate(values)


_SKIPPABLE_ANALYSIS_ERRORS = (
    GenerationTimeoutError,
    GenerationRateLimitError,
    GenerationServerError,
    GenerationResponseError,
)
_FAILURE_TRACE_EVENTS = {
    'search': 'paper_agent.pipeline.retrieval',
    'acquisition': 'paper_agent.pipeline.fulltext',
    'chunking': 'paper_agent.pipeline.fulltext',
    'retrieval': 'paper_agent.pipeline.retrieval',
    'analysis': 'paper_agent.pipeline.analysis',
    'synthesis': 'paper_agent.pipeline.synthesis',
}


def _emit_failure_trace_event(
    recorder: RunRecorder,
    *,
    stage: str,
    code: str,
) -> None:
    event_name = _FAILURE_TRACE_EVENTS.get(stage)
    if event_name is None:
        return
    recorder.trace_event(
        event_name,
        {'failure_stage': stage},
        status='error',
        code=code,
    )

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
    correlation: PipelineCorrelationInput | None = None,
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
    if active_settings.otlp_enabled:
        preflight_otlp()

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
            correlation=correlation,
            trace_secrets=(active_settings.dashscope_api_key,),
            trace_enabled=active_settings.trace_enabled,
        )
        if active_settings.otlp_enabled:
            assert active_settings.otlp_endpoint is not None
            trace_exporter = OtlpTraceExporter(
                endpoint=active_settings.otlp_endpoint,
                headers=active_settings.otlp_headers,
                timeout_seconds=active_settings.otlp_timeout_seconds,
                failure_threshold=active_settings.otlp_failure_threshold,
                deployment_environment=(
                    active_settings.deployment_environment
                ),
            )
            recorder.set_exporter_close(
                lambda: trace_exporter.export_file(
                    recorder.run_dir / 'traces.jsonl'
                )
            )
        recorder.trace_event(
            'paper_agent.pipeline.run.started',
            {
                'requested_limit': limit,
                'no_pdf': no_pdf,
            },
        )
        timings: dict[str, float] = {}
        papers: list[Paper] = []
        records: list[DocumentRecord] = []
        evidence: list[Evidence] = []
        analyses: list[CheckedPaperAnalysis] = []
        retrievals = []
        degradations: list[RunIssue] = []
        usage = UsageTotals(operations=0, http_attempts=0)
        failure_stage = "pipeline"

        def timed(stage: str, operation: Callable[[], object]) -> object:
            nonlocal failure_stage
            started = time.monotonic()
            try:
                return operation()
            except Exception:
                failure_stage = stage
                raise
            finally:
                timings[stage] = timings.get(stage, 0.0) + max(0.0, time.monotonic() - started)

        try:
            papers = timed(
                "search", lambda: dedupe_papers(deps.search(question, limit))[:limit]
            )
            recorder.trace_event(
                'paper_agent.pipeline.retrieval',
                {
                    'operation': 'search',
                    'returned_paper_count': len(papers),
                },
            )
            recorder.write_papers(papers)
            acquirer = DocumentAcquirer(downloader=deps.downloader, parser=deps.parser)

            for paper in papers:
                outcome = timed(
                    "acquisition",
                    lambda paper=paper: acquire_paper_document(
                        acquirer, paper, no_pdf=no_pdf
                    ),
                )
                degradations.extend(outcome.degradations)
                acquisition_code = (
                    (
                        outcome.record.fallback_code
                        if outcome.record is not None
                        else None
                    )
                    or (
                        outcome.degradations[0].code
                        if outcome.degradations
                        else None
                    )
                    or 'fulltext_degraded'
                )
                acquisition_degraded = bool(outcome.degradations)
                recorder.trace_event(
                    'paper_agent.pipeline.fulltext',
                    {
                        'operation': 'document_acquire',
                        'paper_id': paper.paper_id,
                        'document_available': outcome.document is not None,
                    },
                    status='degraded' if acquisition_degraded else 'ok',
                    code=acquisition_code if acquisition_degraded else None,
                )
                if outcome.document is None or outcome.record is None:
                    continue
                chunked = timed("chunking", lambda document=outcome.document: chunk_document(document))
                record = outcome.record.model_copy(
                    update={"warnings": list(dict.fromkeys([*outcome.record.warnings, *chunked.warnings]))}
                )
                recorder.trace_event(
                    'paper_agent.pipeline.fulltext',
                    {
                        'operation': 'document_chunk',
                        'paper_id': paper.paper_id,
                        'chunk_count': len(chunked.chunks),
                        'warning_count': len(chunked.warnings),
                    },
                )
                records.append(record)

                def retrieval_event(event: object, paper_id: str = paper.paper_id) -> None:
                    recorder.emit(RunEvent(timestamp=utc_now(), run_id=recorder.run_id, stage="retrieval", operation="retrieve_evidence", status=event.status, paper_id=paper_id, code=event.degradation_code or event.error_code, attributes=event.model_dump(mode="json")))

                pack = timed("retrieval", lambda paper=paper, chunked=chunked: deps.evidence_packs.build(question=question, paper_id=paper.paper_id, chunks=chunked.chunks, run_id=recorder.run_id, event_sink=retrieval_event))
                retrieval_code = (
                    pack.retrieval.degradation_code
                    if pack.retrieval.degraded
                    else None
                )
                retrieval_attributes = {
                    'paper_id': paper.paper_id,
                    'requested_mode': pack.retrieval.requested_mode,
                    'actual_mode': pack.retrieval.actual_mode,
                    'evidence_count': len(pack.evidence),
                }
                recorder.trace_event(
                    'paper_agent.pipeline.retrieval',
                    retrieval_attributes,
                    status='degraded' if pack.retrieval.degraded else 'ok',
                    code=retrieval_code,
                )
                recorder.trace_event(
                    'paper_agent.pipeline.rerank',
                    {
                        'paper_id': paper.paper_id,
                        'actual_mode': pack.retrieval.actual_mode,
                        'returned_evidence_count': len(pack.evidence),
                    },
                    status='degraded' if pack.retrieval.degraded else 'ok',
                    code=retrieval_code,
                )
                evidence.extend(pack.evidence)
                retrievals.append(pack.retrieval)
                if pack.retrieval.degraded:
                    degradations.append(RunIssue(stage="retrieval", code=pack.retrieval.degradation_code or "retrieval_degraded", paper_id=paper.paper_id))
                try:
                    generated = timed("analysis", lambda paper=paper, pack=pack: deps.analyzer.analyze(paper=paper, evidence_pack=pack, timeout=active_settings.dashscope_generation_timeout_seconds))
                except _SKIPPABLE_ANALYSIS_ERRORS as error:
                    usage = _add_failure_usage(usage, error)
                    degradations.append(RunIssue(stage="analysis", code=error.code, paper_id=paper.paper_id))
                    recorder.trace_event(
                        'paper_agent.pipeline.analysis',
                        {
                            'paper_id': paper.paper_id,
                            'attempts': error.metadata.attempts,
                        },
                        status='degraded',
                        code=error.code,
                    )
                    continue
                usage = _add_usage(usage, generated)
                checked = check_paper_analysis(generated.result, pack.evidence, run_id=recorder.run_id)
                recorder.trace_event(
                    'paper_agent.pipeline.analysis',
                    {
                        'paper_id': paper.paper_id,
                        'attempts': generated.attempts,
                        'evidence_count': len(pack.evidence),
                    },
                )
                citation_degraded = bool(
                    checked.sanitized_reference_count
                    or checked.dropped_finding_count
                )
                recorder.trace_event(
                    'paper_agent.pipeline.citation_validation',
                    {
                        'scope': 'paper',
                        'paper_id': paper.paper_id,
                        'sanitized_reference_count': (
                            checked.sanitized_reference_count
                        ),
                        'dropped_finding_count': checked.dropped_finding_count,
                    },
                    status='degraded' if citation_degraded else 'ok',
                    code=(
                        'citation_references_sanitized'
                        if citation_degraded
                        else None
                    ),
                )
                if checked.sanitized_reference_count or checked.dropped_finding_count:
                    degradations.append(RunIssue(stage="citation_check", code="citation_references_sanitized", paper_id=paper.paper_id, message=f"sanitized={checked.sanitized_reference_count};dropped={checked.dropped_finding_count}"))
                if checked.has_supported_finding:
                    analyses.append(checked.analysis)
                else:
                    degradations.append(RunIssue(stage="analysis", code="analysis_without_supported_finding", paper_id=paper.paper_id))

            recorder.write_documents(records)
            recorder.write_evidence(evidence)
            recorder.write_analyses(analyses)
            minimum = 2 if len(papers) >= 2 else 1
            if len(analyses) < minimum:
                raise ValueError("insufficient_successful_analyses")
            survey = timed("synthesis", lambda: deps.synthesizer.synthesize(question=question, analyses=analyses, evidence=evidence, timeout=active_settings.dashscope_generation_timeout_seconds))
            usage = _add_usage(usage, survey)
            recorder.trace_event(
                'paper_agent.pipeline.synthesis',
                {
                    'analysis_count': len(analyses),
                    'evidence_count': len(evidence),
                    'attempts': survey.attempts,
                },
            )
            report = check_survey_draft(question, survey.result, evidence, run_id=recorder.run_id)
            sanitized = sum(claim.support_status != "supported" for claim in [*report.method_taxonomy, *report.comparisons, *report.limitations, *report.open_questions, *report.rejected_critical_claims])
            recorder.trace_event(
                'paper_agent.pipeline.citation_validation',
                {
                    'scope': 'report',
                    'sanitized_claim_count': sanitized,
                },
                status='degraded' if sanitized else 'ok',
                code='citation_references_sanitized' if sanitized else None,
            )
            if sanitized:
                degradations.append(RunIssue(stage="citation_check", code="citation_references_sanitized", message=f"sanitized_claims={sanitized}"))
            require_publishable_report(report)
            status: Literal["completed", "completed_with_degradation"] = "completed_with_degradation" if degradations else "completed"
            markdown = render_formal_report(status=status, papers=[paper for paper in papers if any(record.paper_id == paper.paper_id for record in records)], documents=records, evidence=evidence, report=report)
            recorder.publish_report(report, markdown)
            recorder.trace_event(
                'paper_agent.pipeline.output',
                {
                    'published': True,
                    'paper_count': len(papers),
                    'document_count': len(records),
                },
            )
            if degradations:
                recorder.trace_event(
                    'paper_agent.pipeline.degradation',
                    {'degradation_count': len(degradations)},
                    status='degraded',
                    code='pipeline_degraded',
                )
            recorder.trace_event(
                'paper_agent.pipeline.run.finished',
                {
                    'selected_paper_count': len(papers),
                    'analysis_count': len(analyses),
                    'evidence_count': len(evidence),
                },
                status='degraded' if degradations else 'ok',
                code='pipeline_degraded' if degradations else None,
            )
            recorder.complete(status=status, counts=_counts(papers, records, analyses, evidence), retrieval_outcomes=retrievals, stage_elapsed_seconds=timings, usage=usage, degradations=degradations)
            return PipelineResult(run_dir=recorder.run_dir, status=status)
        except (KeyboardInterrupt, SystemExit):
            raise
        except GenerationProviderError as error:
            usage = _add_failure_usage(usage, error)
            code = error.code
            _emit_failure_trace_event(
                recorder,
                stage=failure_stage,
                code=code,
            )
            recorder.trace_event(
                'paper_agent.pipeline.run.finished',
                {'failure_stage': 'generation'},
                status='error',
                code=code,
            )
            recorder.fail(stage="generation", code=code, counts=_counts(papers, records, analyses, evidence), retrieval_outcomes=retrievals, stage_elapsed_seconds=timings, usage=usage, degradations=degradations)
            raise PipelineRunFailed(recorder.run_dir, code) from error
        except ValueError as error:
            message = str(error)
            if failure_stage == "retrieval":
                code = getattr(error, "error_code", "retrieval_failure")
            else:
                code = message if message in {"insufficient_successful_analyses", "insufficient_supported_report"} else "pipeline_validation_error"
            _emit_failure_trace_event(
                recorder,
                stage=failure_stage,
                code=code,
            )
            recorder.trace_event(
                'paper_agent.pipeline.run.finished',
                {'failure_stage': failure_stage},
                status='error',
                code=code,
            )
            recorder.fail(stage=failure_stage, code=code, counts=_counts(papers, records, analyses, evidence), retrieval_outcomes=retrievals, stage_elapsed_seconds=timings, usage=usage, degradations=degradations)
            raise PipelineRunFailed(recorder.run_dir, code) from error
        except Exception as error:
            code = "retrieval_failure" if failure_stage == "retrieval" else "unexpected_pipeline_error"
            _emit_failure_trace_event(
                recorder,
                stage=failure_stage,
                code=code,
            )
            recorder.trace_event(
                'paper_agent.pipeline.run.finished',
                {'failure_stage': failure_stage},
                status='error',
                code=code,
            )
            recorder.fail(stage=failure_stage, code=code, counts=_counts(papers, records, analyses, evidence), retrieval_outcomes=retrievals, stage_elapsed_seconds=timings, usage=usage, degradations=degradations)
            raise PipelineRunFailed(recorder.run_dir, code) from error
