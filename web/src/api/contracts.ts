// Runtime API schemas are generated from openapi/web-v1.json. This file only
// adds client conveniences and marks defaulted response fields as always present,
// matching FastAPI's serialized response_model behavior.
import type { components } from "./openapi.generated";

type Schemas = components["schemas"];
type RequiredDeep<T> = T extends readonly (infer Item)[]
  ? RequiredDeep<Item>[]
  : T extends object
    ? { [Key in keyof T]-?: RequiredDeep<Exclude<T[Key], undefined>> }
    : T;

export type RetrievalSettings = RequiredDeep<Schemas["RetrievalRequest"]>;
export type CreateRunRequest = RequiredDeep<Schemas["CreateRunRequest"]>;
export type RunProgress = RequiredDeep<Schemas["RunProgress"]>;
export type RunIssue = RequiredDeep<Schemas["RunIssue"]>;
export type ManifestProjection = RequiredDeep<Schemas["ManifestProjection"]>;
export type RunSummary = RequiredDeep<Schemas["RunSummary"]>;
export type RunDetail = RequiredDeep<Schemas["RunDetail"]>;
export type RunList = RequiredDeep<Schemas["RunList"]>;
export type ApiErrorBody = RequiredDeep<Schemas["ErrorResponse"]>;
export type CheckedClaim = RequiredDeep<Schemas["CheckedClaim"]>;
export type RejectedCriticalClaim = RequiredDeep<Schemas["RejectedCriticalClaim"]>;
export type CheckedSurveyReport = RequiredDeep<Schemas["CheckedSurveyReport"]>;
export type ReportResponse = RequiredDeep<Schemas["ReportResponse"]>;
export type Paper = RequiredDeep<Schemas["Paper"]>;
export type DocumentRecord = RequiredDeep<Schemas["DocumentRecord"]>;
export type PaperSummary = RequiredDeep<Schemas["PaperSummary"]>;
export type CheckedPaperAnalysis = RequiredDeep<Schemas["CheckedPaperAnalysis"]>;
export type PaperAnalysisResponse = RequiredDeep<Schemas["PaperAnalysisResponse"]>;
export type EvidenceView = RequiredDeep<Schemas["EvidenceView"]>;

export type RunStatus = RunSummary["status"];
export type RunPhase = RunSummary["phase"];
export type SupportStatus = CheckedClaim["support_status"];
export type ContentMode = CreateRunRequest["content_mode"];
export type RetrievalMode = RetrievalSettings["mode"];
export type ArtifactName = RunDetail["available_artifacts"][number];

export interface ApiResponse<T> {
  data: T;
  retryAfterSeconds?: number;
  location?: string;
}

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
