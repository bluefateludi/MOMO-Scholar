// Typed projection of docs/superpowers/specs/2026-08-02-web-mvp-scope-api-ui-contract.md.
// Replace generation source with openapi/web-v1.json when the backend snapshot lands.
export type RunStatus = "queued" | "running" | "completed" | "completed_with_degradation" | "failed" | "interrupted";
export type RunPhase = "queued" | "initializing" | "search" | "acquisition" | "chunking" | "retrieval" | "analysis" | "synthesis" | "citation_check" | "publishing" | "terminal";
export type SupportStatus = "supported" | "weakly_supported" | "unsupported";
export type ContentMode = "pdf_preferred" | "abstract_only";
export type RetrievalMode = "auto" | "lexical" | "hybrid";

export interface RetrievalSettings { mode: RetrievalMode; candidate_k: number; top_k: number; rrf_k: number; analysis_evidence_per_paper: number }
export interface CreateRunRequest { question: string; paper_limit: number; content_mode: ContentMode; retrieval: RetrievalSettings }
export interface RunProgress { completed_units: number | null; total_units: number | null; paper_id: string | null }
export interface RunIssue { stage: string; code: string; paper_id?: string | null; message?: string | null }
export interface ManifestProjection {
  counts: Record<string, number>;
  retrieval_outcomes: Array<Record<string, unknown>>;
  degradations: RunIssue[];
  errors: RunIssue[];
  stage_elapsed_seconds: Record<string, number>;
  usage: Record<string, number | null>;
  settings: Record<string, unknown>;
  component_versions: Record<string, string>;
}
export interface RunSummary extends CreateRunRequest {
  id: string; artifact_run_id: string | null; origin: "live" | "bundled_demo"; status: RunStatus; phase: RunPhase;
  progress: RunProgress; created_at: string; started_at: string | null; finished_at: string | null; has_report: boolean; demo: boolean;
}
export interface RunDetail extends RunSummary { manifest: ManifestProjection | null; available_artifacts: ArtifactName[] }
export interface RunList { items: RunSummary[]; next_cursor: string | null }
export interface ApiErrorBody { error: { code: string; message: string; details: Record<string, unknown> } }

export interface CheckedClaim { text: string; evidence_ids: string[]; support_status: SupportStatus }
export interface RejectedCriticalClaim extends CheckedClaim { source_section: "tldr_claims" | "key_findings" }
export interface CheckedSurveyReport {
  question: string; tldr_claims: CheckedClaim[]; method_taxonomy: CheckedClaim[]; comparisons: CheckedClaim[];
  key_findings: CheckedClaim[]; limitations: CheckedClaim[]; open_questions: CheckedClaim[]; rejected_critical_claims: RejectedCriticalClaim[];
}
export interface ReportResponse { run_id: string; status: "completed" | "completed_with_degradation"; report: CheckedSurveyReport; markdown: string; degradations: RunIssue[] }
export interface Paper { paper_id: string; title: string; authors: string[]; year: number | null; abstract: string; url: string; pdf_url: string | null; source: string; citation_count: number | null }
export interface DocumentRecord { paper_id: string; content_source: "pdf" | "abstract"; content_sha256: string; page_count: number; warnings: string[]; fallback_code: string | null }
export interface PaperSummary extends Paper { document: DocumentRecord | null; analysis_available: boolean; evidence_count: number }
export interface CheckedPaperAnalysis { paper_id: string; contributions: CheckedClaim[]; methods: CheckedClaim[]; experiments: CheckedClaim[]; results: CheckedClaim[]; limitations: CheckedClaim[] }
export interface PaperAnalysisResponse { run_id: string; paper: Paper; document: DocumentRecord | null; analysis: CheckedPaperAnalysis }
export interface EvidenceView { evidence_id: string; paper_id: string; chunk_id: string; section: string | null; page: number | null; claim_type: string; quote: string; relevance_score: number; source: { title: string; url: string; pdf_url: string | null; content_source: "pdf" | "abstract"; fallback_code: string | null } }
export type ArtifactName = "papers.json" | "documents.json" | "evidence.json" | "analyses.json" | "report.json" | "report.md" | "run_manifest.json" | "logs.jsonl";

export interface ApiResponse<T> { data: T; retryAfterSeconds?: number }
export interface RunApi {
  listRuns(): Promise<ApiResponse<RunList>>;
  createRun(request: CreateRunRequest): Promise<ApiResponse<RunSummary>>;
  getRun(id: string): Promise<ApiResponse<RunDetail>>;
  getReport(id: string): Promise<ApiResponse<ReportResponse>>;
  getPapers(id: string): Promise<ApiResponse<{ items: PaperSummary[] }>>;
  getPaperAnalysis(id: string, paperId: string): Promise<ApiResponse<PaperAnalysisResponse>>;
  getEvidence(id: string, paperId?: string): Promise<ApiResponse<{ items: EvidenceView[] }>>;
  getEvidenceItem(id: string, evidenceId: string): Promise<ApiResponse<EvidenceView>>;
  artifactUrl(id: string, name: ArtifactName): string;
}
