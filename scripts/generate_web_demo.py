from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from paper_agent.fulltext.models import DocumentRecord
from paper_agent.observability.models import (
    RetrievalRecord, RunCounts, RunEvent, RunIssue, RunManifest, SafeRunSettings,
    UsageTotals,
)
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import (
    CheckedClaim, CheckedFinding, CheckedPaperAnalysis, CheckedSurveyReport,
    RejectedCriticalClaim,
)
from paper_agent.web.demo import DEMO_ARTIFACT_RUN_ID, DEMO_REQUEST


STARTED = datetime(2026, 8, 2, 4, 0, 1, tzinfo=timezone.utc)
FINISHED = datetime(2026, 8, 2, 4, 0, 12, tzinfo=timezone.utc)


def bundle() -> dict[str, str]:
    paper_a = Paper(
        paper_id="arxiv:synthetic.0001", title="Synthetic Hybrid Retrieval Study",
        authors=["Ada Example", "Lin Fixture"], year=2026,
        abstract="Synthetic content for the bundled offline demonstration.",
        url="https://example.invalid/synthetic-hybrid-retrieval",
        pdf_url="https://example.invalid/synthetic-hybrid-retrieval.pdf",
        source="synthetic",
    )
    paper_b = Paper(
        paper_id="arxiv:synthetic.0002", title="Synthetic Resilient Review Pipelines",
        authors=["Noor Sample"], year=2026,
        abstract="Synthetic content for the bundled offline demonstration.",
        url="https://example.invalid/synthetic-resilient-review",
        source="synthetic",
    )
    ev_a = f"{DEMO_ARTIFACT_RUN_ID}:paper:{paper_a.paper_id}:ev_001"
    ev_b = f"{DEMO_ARTIFACT_RUN_ID}:paper:{paper_b.paper_id}:ev_001"
    evidence = [
        Evidence(
            evidence_id=ev_a, paper_id=paper_a.paper_id,
            chunk_id=f"{paper_a.paper_id}:chunk:0004", section="Methods", page=4,
            claim_type="method",
            quote="Reciprocal-rank fusion combines independently ranked lexical and semantic candidates without requiring score calibration.",
            relevance_score=0.94,
        ),
        Evidence(
            evidence_id=ev_b, paper_id=paper_b.paper_id,
            chunk_id=f"{paper_b.paper_id}:chunk:0002", section=None, page=None,
            claim_type="limitation",
            quote="Lexical fallback preserves availability when vector infrastructure is transiently unavailable, but may reduce semantic recall.",
            relevance_score=0.82,
        ),
    ]
    documents = [
        DocumentRecord(
            paper_id=paper_a.paper_id, content_source="pdf",
            content_sha256="a" * 64, page_count=8,
        ),
        DocumentRecord(
            paper_id=paper_b.paper_id, content_source="abstract",
            content_sha256="b" * 64, page_count=1,
            warnings=["Abstract fallback used in this synthetic fixture."],
            fallback_code="pdf_download_timeout",
        ),
    ]
    analyses = [
        CheckedPaperAnalysis(
            paper_id=paper_a.paper_id,
            contributions=[CheckedFinding(text="The study combines two retrieval signals.", evidence_ids=[ev_a], support_status="supported")],
            methods=[CheckedFinding(text="Ranked lists are fused by reciprocal rank.", evidence_ids=[ev_a], support_status="supported")],
        ),
        CheckedPaperAnalysis(
            paper_id=paper_b.paper_id,
            contributions=[CheckedFinding(text="The pipeline specifies an explicit degraded state.", evidence_ids=[ev_b], support_status="supported")],
            limitations=[CheckedFinding(text="Only abstract content was available.", evidence_ids=[ev_b], support_status="weakly_supported")],
        ),
    ]
    report = CheckedSurveyReport(
        question=DEMO_REQUEST.question,
        tldr_claims=[CheckedClaim(text="Hybrid retrieval can combine complementary lexical and semantic rankings.", evidence_ids=[ev_a], support_status="supported")],
        method_taxonomy=[CheckedClaim(text="Reciprocal-rank fusion avoids direct score calibration.", evidence_ids=[ev_a], support_status="supported")],
        key_findings=[CheckedClaim(text="Fallback behavior must remain explicit in research provenance.", evidence_ids=[ev_b], support_status="supported")],
        limitations=[CheckedClaim(text="Lexical fallback may reduce semantic recall.", evidence_ids=[ev_b], support_status="weakly_supported")],
        open_questions=[CheckedClaim(text="How should fusion parameters adapt across scientific fields?", evidence_ids=[], support_status="unsupported")],
        rejected_critical_claims=[RejectedCriticalClaim(text="The fixture proves production retrieval quality.", evidence_ids=[], support_status="unsupported", source_section="key_findings")],
    )
    degradation = RunIssue(
        stage="retrieval", code="vector_network_unavailable",
        paper_id=paper_b.paper_id,
    )
    manifest = RunManifest(
        run_id=DEMO_ARTIFACT_RUN_ID, execution_id="synthetic-demo-execution",
        trace_enabled=False, status="completed_with_degradation",
        question=DEMO_REQUEST.question, requested_limit=2, no_pdf=False,
        started_at=STARTED, finished_at=FINISHED,
        settings=SafeRunSettings(
            retrieval_mode="auto", embedding_model="synthetic-embedding",
            generation_provider="dashscope", generation_endpoint_host="example.invalid",
            generation_model="synthetic-generation", generation_timeout_seconds=1,
            pdf_download_timeout_seconds=1, pdf_max_bytes=1_000_000,
            pdf_max_pages=20, analysis_evidence_per_paper=6,
            chunk_max_words=180, chunk_overlap_words=30,
        ),
        counts=RunCounts(
            selected_papers=2, pdf_documents=1, abstract_documents=1,
            explicit_abstract_documents=0, pdf_fallback_documents=1,
            excluded_papers=0, successful_analyses=2, evidence_items=2,
        ),
        stage_elapsed_seconds={"search": 1.2, "retrieval": 2.4, "synthesis": 1.8},
        usage=UsageTotals(operations=0, http_attempts=0),
        component_versions={"paper-agent": "synthetic-demo-v1"},
        retrieval_outcomes=[
            RetrievalRecord(paper_id=paper_a.paper_id, requested_mode="auto", actual_mode="hybrid", degraded=False),
            RetrievalRecord(paper_id=paper_b.paper_id, requested_mode="auto", actual_mode="lexical", degraded=True, degradation_code=degradation.code),
        ],
        degradations=[degradation],
    )
    log = RunEvent(
        timestamp=FINISHED, run_id=DEMO_ARTIFACT_RUN_ID, stage="pipeline",
        operation="synthetic_demo", status="degraded", code="synthetic_demo",
        attributes={"synthetic": True},
    )
    markdown = (
        "# Formal Survey: Hybrid retrieval\n\n"
        f"Hybrid retrieval can combine complementary rankings. [{ev_a}]\n\n"
        "<script>alert('blocked')</script>\n\n"
        f"Lexical fallback may reduce semantic recall. [{ev_b}]\n"
    )
    objects = {
        "papers.json": [paper_a.model_dump(mode="json"), paper_b.model_dump(mode="json")],
        "documents.json": [item.model_dump(mode="json") for item in documents],
        "evidence.json": [item.model_dump(mode="json") for item in evidence],
        "analyses.json": [item.model_dump(mode="json") for item in analyses],
        "report.json": report.model_dump(mode="json"),
        "run_manifest.json": manifest.model_dump(mode="json"),
    }
    rendered = {
        name: json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        for name, value in objects.items()
    }
    rendered["report.md"] = markdown
    rendered["logs.jsonl"] = json.dumps(log.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n"
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("paper_agent/web/demo_data") / DEMO_ARTIFACT_RUN_ID)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = bundle()
    if args.check:
        mismatches = [name for name, text in expected.items() if not (args.output / name).is_file() or (args.output / name).read_text(encoding="utf-8") != text]
        if mismatches:
            raise SystemExit(f"bundled demo drift: {', '.join(mismatches)}")
        return
    args.output.mkdir(parents=True, exist_ok=True)
    for name, text in expected.items():
        (args.output / name).write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
