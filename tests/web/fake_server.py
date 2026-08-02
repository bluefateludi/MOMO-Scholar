"""Explicitly synthetic FastAPI assembly for offline browser integration only."""

from __future__ import annotations

import os
from pathlib import Path

from paper_agent.config import Settings
from paper_agent.fulltext.models import DocumentRecord
from paper_agent.observability.models import (
    RunCounts, RunIssue, SafeRunSettings, UsageTotals,
)
from paper_agent.observability.recorder import RunRecorder
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import (
    CheckedClaim, CheckedFinding, CheckedPaperAnalysis, CheckedSurveyReport,
)
from paper_agent.web.app import create_app


class SyntheticBrowserRunner:
    def __call__(self, question: str, **kwargs: object) -> object:
        settings = kwargs["settings"]
        recorder = RunRecorder.start(
            output_base=kwargs["output_base"], question=question,
            requested_limit=kwargs["limit"], no_pdf=kwargs["no_pdf"],
            safe_settings=SafeRunSettings.from_settings(
                settings, chunk_max_words=180, chunk_overlap_words=30,
            ),
            component_versions={"paper-agent": "synthetic-browser-runner"},
            trace_enabled=False,
            artifact_created_sink=kwargs["artifact_created_sink"],
        )
        paper = Paper(
            paper_id="arxiv:synthetic.browser/0001", title="Synthetic Browser Integration Paper",
            authors=["MOMO Fixture"], year=2026,
            abstract="Synthetic offline browser-integration material.",
            url="https://example.invalid/synthetic-browser-paper",
            source="synthetic",
        )
        document = DocumentRecord(
            paper_id=paper.paper_id, content_source="abstract",
            content_sha256="c" * 64, page_count=1,
            warnings=["Synthetic browser fixture; no provider or network was used."],
        )
        evidence = Evidence(
            evidence_id=f"{recorder.run_id}:paper:{paper.paper_id}:ev_001",
            paper_id=paper.paper_id,
            chunk_id=f"{paper.paper_id}:chunk:0001",
            section=None, page=None, claim_type="method",
            quote="This persisted quote was produced by the deterministic synthetic browser runner.",
            relevance_score=0.9,
        )
        finding = CheckedFinding(
            text="The offline vertical slice preserves exact Evidence links.",
            evidence_ids=[evidence.evidence_id], support_status="supported",
        )
        report_claim = CheckedClaim(
            text=finding.text, evidence_ids=finding.evidence_ids,
            support_status="supported",
        )
        report = CheckedSurveyReport(
            question=question, tldr_claims=[report_claim],
            key_findings=[report_claim],
        )
        recorder.write_papers([paper])
        recorder.write_documents([document])
        recorder.write_evidence([evidence])
        recorder.write_analyses([CheckedPaperAnalysis(
            paper_id=paper.paper_id, methods=[finding],
        )])
        recorder.publish_report(
            report,
            f"# Synthetic browser report\n\n{report_claim.text} [{evidence.evidence_id}]\n",
        )
        recorder.complete(
            status="completed_with_degradation",
            counts=RunCounts(
                selected_papers=1, pdf_documents=0, abstract_documents=1,
                explicit_abstract_documents=1, pdf_fallback_documents=0,
                excluded_papers=0, successful_analyses=1, evidence_items=1,
            ),
            retrieval_outcomes=[], stage_elapsed_seconds={},
            usage=UsageTotals(operations=0, http_attempts=0),
            degradations=[RunIssue(stage="retrieval", code="synthetic_offline_runner")],
        )
        return object()


root = Path(os.environ.get("MOMO_WEB_E2E_ROOT", "output/playwright/fake-server")).resolve()
app = create_app(
    state_root=root / "state",
    output_root=root / "outputs",
    runner=SyntheticBrowserRunner(),
    settings_loader=lambda: Settings(
        dashscope_api_key="synthetic-browser-value", trace_enabled=False,
    ),
    allowed_origins=("http://127.0.0.1:5173",),
)
