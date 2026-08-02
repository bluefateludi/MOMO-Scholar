import type { CheckedPaperAnalysis, CheckedClaim, EvidenceView, PaperSummary, ReportResponse, RunDetail, RunIssue } from "./contracts";

export const DEMO_ID = "00000000-0000-4000-8000-000000000001";
const artifactId = "20260802-120000-000001-synthetic-demo";
export const EV1 = `${artifactId}:paper:arxiv:2401.00001:ev_001`;
export const EV2 = `${artifactId}:paper:arxiv:2401.00002:ev_001`;
const degradation: RunIssue = { stage: "retrieval", code: "vector_network_unavailable", paper_id: "arxiv:2401.00002" };

export const evidence: EvidenceView[] = [
  { evidence_id: EV1, paper_id: "arxiv:2401.00001", chunk_id: "arxiv:2401.00001:chunk:0004", section: "Methods", page: 4, claim_type: "method", quote: "Reciprocal-rank fusion combines independently ranked lexical and semantic candidates without requiring score calibration.", relevance_score: 0.94, source: { title: "Synthetic Hybrid Retrieval Study", url: "https://arxiv.org/abs/2401.00001", pdf_url: "https://arxiv.org/pdf/2401.00001", content_source: "pdf", fallback_code: null } },
  { evidence_id: EV2, paper_id: "arxiv:2401.00002", chunk_id: "arxiv:2401.00002:chunk:0002", section: null, page: null, claim_type: "limitation", quote: "Lexical fallback preserves availability when vector infrastructure is transiently unavailable, but may reduce semantic recall.", relevance_score: 0.82, source: { title: "Synthetic Resilient Review Pipelines", url: "https://arxiv.org/abs/2401.00002", pdf_url: null, content_source: "abstract", fallback_code: "vector_network_unavailable" } },
];

export const papers: PaperSummary[] = evidence.map((item, index) => ({
  paper_id: item.paper_id, title: item.source.title, authors: index === 0 ? ["Ada Example", "Lin Fixture"] : ["Noor Sample"], year: 2024,
  abstract: "Synthetic content prepared only for the bundled offline UI demonstration.", url: item.source.url, pdf_url: item.source.pdf_url,
  source: "arxiv", citation_count: null, document: { paper_id: item.paper_id, content_source: item.source.content_source, content_sha256: "a".repeat(64), page_count: index === 0 ? 8 : 1, warnings: index ? ["Abstract fallback used in this synthetic fixture."] : [], fallback_code: item.source.fallback_code },
  analysis_available: true, evidence_count: 1,
}));

const claim = (text: string, evidence_ids: string[], support_status: CheckedClaim["support_status"] = "supported"): CheckedClaim => ({ text, evidence_ids, support_status });
export const report: ReportResponse = {
  run_id: DEMO_ID, status: "completed_with_degradation", degradations: [degradation],
  report: {
    question: "How can hybrid retrieval support resilient scientific literature review?",
    tldr_claims: [claim("Hybrid retrieval can combine complementary lexical and semantic rankings.", [EV1])],
    method_taxonomy: [claim("Reciprocal-rank fusion avoids direct score calibration.", [EV1])], comparisons: [],
    key_findings: [claim("Fallback behavior must remain explicit in research provenance.", [EV2])],
    limitations: [claim("Lexical fallback may reduce semantic recall.", [EV2], "weakly_supported")],
    open_questions: [claim("How should fusion parameters adapt across scientific fields?", [], "unsupported")],
    rejected_critical_claims: [{ ...claim("The fixture proves production retrieval quality.", [], "unsupported"), source_section: "key_findings" }],
  },
  markdown: `# Formal Survey: Hybrid retrieval\n\n## TL;DR\n\nHybrid retrieval can combine complementary rankings. [${EV1}]\n\n<script>alert('blocked')</script>\n\n## Limitations\n\nLexical fallback may reduce semantic recall. [${EV2}]\n`,
};

export const analyses: Record<string, CheckedPaperAnalysis> = Object.fromEntries(papers.map((paper, index) => [paper.paper_id, {
  paper_id: paper.paper_id,
  contributions: [claim(index ? "The pipeline specifies an explicit degraded state." : "The study combines two retrieval signals.", [evidence[index].evidence_id])],
  methods: index ? [] : [claim("Ranked lists are fused by reciprocal rank.", [EV1])], experiments: [], results: [],
  limitations: index ? [claim("Only abstract content was available.", [EV2], "weakly_supported")] : [],
}]));

const retrieval = { mode: "auto" as const, candidate_k: 30, top_k: 8, rrf_k: 60, analysis_evidence_per_paper: 6 };
export const demoRun: RunDetail = {
  id: DEMO_ID, artifact_run_id: artifactId, origin: "bundled_demo", demo: true, status: "completed_with_degradation", phase: "terminal",
  question: report.report.question, paper_limit: 2, content_mode: "pdf_preferred", retrieval,
  progress: { completed_units: 2, total_units: 2, paper_id: null }, created_at: "2026-08-02T04:00:00Z", started_at: "2026-08-02T04:00:01Z", finished_at: "2026-08-02T04:00:12Z", has_report: true,
  manifest: { counts: { selected_papers: 2, pdf_documents: 1, abstract_documents: 1, successful_analyses: 2, evidence_items: 2 }, retrieval_outcomes: [], degradations: [degradation], errors: [], stage_elapsed_seconds: { search: 1.2, retrieval: 2.4, synthesis: 1.8 }, usage: {}, settings: {}, component_versions: {} },
  available_artifacts: ["papers.json", "documents.json", "evidence.json", "analyses.json", "report.json", "report.md", "run_manifest.json", "logs.jsonl"],
};
