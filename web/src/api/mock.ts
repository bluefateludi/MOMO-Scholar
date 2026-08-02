import type { ArtifactName, CreateRunRequest, RunApi, RunDetail } from "./contracts";
import { analyses, demoRun, DEMO_ID, evidence, papers, report } from "./fixtures";
import { ApiError } from "./client";

const delay = (ms = 30) => new Promise((resolve) => setTimeout(resolve, ms));
const runs = new Map<string, RunDetail>([[DEMO_ID, demoRun]]);
const phases = ["queued", "search", "retrieval", "analysis", "synthesis", "terminal"] as const;
const pollCount = new Map<string, number>();
function find(id: string) { const run = runs.get(id); if (!run) throw new ApiError(404, "run_not_found", "This run could not be found."); return run; }

export const mockApi: RunApi = {
  async listRuns() { await delay(); return { data: { items: [...runs.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)), next_cursor: null } }; },
  async createRun(request: CreateRunRequest) {
    await delay(); const id = crypto.randomUUID(); const now = new Date().toISOString();
    const run: RunDetail = { ...request, id, artifact_run_id: null, origin: "live", demo: false, status: "queued", phase: "queued", progress: { completed_units: null, total_units: null, paper_id: null }, created_at: now, started_at: null, finished_at: null, has_report: false, manifest: null, available_artifacts: [] };
    runs.set(id, run); pollCount.set(id, 0); return { data: run };
  },
  async getRun(id) {
    await delay(); const current = find(id); if (current.demo || current.status === "completed") return { data: current };
    const count = (pollCount.get(id) ?? 0) + 1; pollCount.set(id, count); const phase = phases[Math.min(count, phases.length - 1)]; const terminal = phase === "terminal";
    const updated: RunDetail = { ...current, artifact_run_id: count > 1 ? `fixture-${id.slice(0, 8)}` : null, status: terminal ? "completed" : "running", phase, started_at: current.started_at ?? new Date().toISOString(), finished_at: terminal ? new Date().toISOString() : null, has_report: terminal, progress: count >= 2 ? { completed_units: Math.min(count - 1, current.paper_limit), total_units: current.paper_limit, paper_id: count < 4 ? papers[0].paper_id : null } : current.progress, manifest: terminal ? { ...demoRun.manifest!, degradations: [] } : null, available_artifacts: terminal ? demoRun.available_artifacts : [] };
    runs.set(id, updated); return { data: updated, retryAfterSeconds: 2 };
  },
  async getReport(id) { await delay(); const run = find(id); if (!run.has_report) throw new ApiError(409, "artifact_not_ready", "The requested content is still being prepared."); return { data: { ...report, run_id: id, status: run.status === "completed" ? "completed" : "completed_with_degradation", degradations: run.manifest?.degradations ?? [] } }; },
  async getPapers(id) { await delay(); find(id); return { data: { items: papers } }; },
  async getPaperAnalysis(id, paperId) { await delay(); find(id); const analysis = analyses[paperId]; const paper = papers.find((item) => item.paper_id === paperId); if (!analysis || !paper) throw new ApiError(404, "paper_not_found", "This paper is not part of the run."); return { data: { run_id: id, paper, document: paper.document, analysis } }; },
  async getEvidence(id, paperId) { await delay(); find(id); return { data: { items: paperId ? evidence.filter((item) => item.paper_id === paperId) : evidence } }; },
  async getEvidenceItem(id, evidenceId) { await delay(); find(id); const item = evidence.find((entry) => entry.evidence_id === evidenceId); if (!item) throw new ApiError(404, "evidence_not_found", "This Evidence item could not be found."); return { data: item }; },
  artifactUrl(id: string, name: ArtifactName) {
    const fixture = name === "report.md" ? report.markdown : JSON.stringify({ synthetic_demo: true, run_id: id, artifact: name }, null, 2);
    const mime = name.endsWith(".md") ? "text/markdown" : name.endsWith(".jsonl") ? "application/x-ndjson" : "application/json";
    return `data:${mime};charset=utf-8,${encodeURIComponent(fixture)}`;
  },
};
