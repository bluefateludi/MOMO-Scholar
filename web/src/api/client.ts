import type { ApiErrorBody, ApiResponse, ArtifactName, CreateRunRequest, EvidenceView, PaperAnalysisResponse, PaperSummary, ReportResponse, RunApi, RunDetail, RunList, RunSummary } from "./contracts";

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string, public readonly details: Record<string, unknown> = {}) { super(message); }
}

const errorMessages: Record<string, string> = {
  validation_error: "Review the highlighted settings and try again.", queue_full: "The local research queue is full. Try again after another run finishes.",
  execution_unavailable: "The local research executor is unavailable.", run_not_found: "This run could not be found.", paper_not_found: "This paper is not part of the run.",
  evidence_not_found: "This Evidence item could not be found.", artifact_not_found: "This artifact is not available.", artifact_not_ready: "The requested content is still being prepared.",
  report_unavailable: "This run did not publish a report.", artifact_corrupt: "A saved artifact could not be safely read.", internal_error: "The local service hit an unexpected error.",
  run_busy: "The local research runner is busy. Try again shortly.", origin_not_allowed: "This browser origin is not allowed to use the local API.",
  techscout_execution_unavailable: "TechScout execution is unavailable.", candidate_not_found: "This candidate is not part of the run.",
};
export const messageForCode = (code: string) => errorMessages[code] ?? "The request could not be completed safely.";

async function request<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  const response = await fetch(`/api/v1${path}`, { ...init, headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers } });
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try { body = await response.json() as ApiErrorBody; } catch { /* sanitized fallback */ }
    const code = body?.error.code ?? "internal_error";
    throw new ApiError(response.status, code, messageForCode(code), body?.error.details);
  }
  const retry = Number(response.headers.get("Retry-After"));
  return { data: await response.json() as T, retryAfterSeconds: Number.isFinite(retry) && retry > 0 ? retry : undefined, location: response.headers.get("Location") ?? undefined };
}

export const httpApi: RunApi = {
  listRuns: () => request<RunList>("/runs"),
  createRun: (body: CreateRunRequest) => request<RunSummary>("/runs", { method: "POST", body: JSON.stringify(body) }),
  getRun: (id) => request<RunDetail>(`/runs/${encodeURIComponent(id)}`),
  getReport: (id) => request<ReportResponse>(`/runs/${encodeURIComponent(id)}/report`),
  getPapers: (id) => request<{ items: PaperSummary[] }>(`/runs/${encodeURIComponent(id)}/papers`),
  getPaperAnalysis: (id, paperId) => request<PaperAnalysisResponse>(`/runs/${encodeURIComponent(id)}/papers/${encodeURIComponent(paperId)}/analysis`),
  getEvidence: (id, paperId) => request<{ items: EvidenceView[] }>(`/runs/${encodeURIComponent(id)}/evidence${paperId ? `?paper_id=${encodeURIComponent(paperId)}` : ""}`),
  getEvidenceItem: (id, evidenceId) => request<EvidenceView>(`/runs/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`),
  artifactUrl: (id: string, name: ArtifactName) => `/api/v1/runs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(name)}`,
};
