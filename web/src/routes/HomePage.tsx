import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { techScoutApi } from "../api";
import type { TechScoutCreateRunRequest, TechScoutRunSummary } from "../api/contracts";
import { ApiError } from "../api/client";
import { TECHSCOUT_FIXTURE_ID } from "../api/techscoutFixtures";

const initial: TechScoutCreateRunRequest = {
  question: "", project_context: "Local RAG service choosing a Python vector store.",
  environment: { python_version: "3.11", operating_system: "Linux", deployment: "single-node local" },
  hard_constraints: ["local persistence", "metadata equality filtering"], candidates: [], mode: "fast",
};

export function HomePage() {
  const navigate = useNavigate(); const [form, setForm] = useState(initial); const [constraints, setConstraints] = useState(initial.hard_constraints.join("\n")); const [candidates, setCandidates] = useState("Chroma, Qdrant Local, pgvector");
  const [runs, setRuns] = useState<TechScoutRunSummary[]>([]); const [pending, setPending] = useState(false); const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => { void techScoutApi.listRuns().then((response) => setRuns(response.data.items)).catch(() => setRuns([])); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(null);
    try {
      const body: TechScoutCreateRunRequest = { ...form, hard_constraints: constraints.split("\n").map((item) => item.trim()).filter(Boolean), candidates: candidates.split(",").map((name) => name.trim()).filter(Boolean).map((name) => ({ name })) };
      const response = await techScoutApi.createRun(body); navigate(`/runs/${response.data.id}`);
    } catch (caught) { setError(caught instanceof ApiError ? caught : new ApiError(0, "connection_lost", "The local API could not be reached.")); } finally { setPending(false); }
  }
  return <>
    <section className="tech-hero"><div><p className="eyebrow">Wave 2 · Harness-backed component research</p><h1>Choose with<br/><em>receipts.</em></h1><p className="dek">Compare Python AI components against hard constraints, frozen evidence over local MCP, and deterministic allowlisted checks.</p></div><aside className="scope-card"><b>Fast Demo boundary</b><strong>Local RAG vector stores</strong><p>Fast Demo is synthetic and offline. Verified mode remains explicitly limited until live providers and real Docker are connected.</p></aside></section>
    <section className="tech-desk"><form className="tech-form" onSubmit={submit}><header><span>01</span><div><p className="eyebrow">New task</p><h2>Frame the decision</h2></div></header>
      <label>Decision question<textarea aria-label="Decision question" required minLength={3} value={form.question} onChange={(event) => setForm({ ...form, question: event.target.value })} placeholder="Which local vector store fits this service?"/></label>
      <label>Project context<textarea aria-label="Project context" required value={form.project_context} onChange={(event) => setForm({ ...form, project_context: event.target.value })}/></label>
      <div className="env-grid"><label>Python<input aria-label="Python version" value={form.environment.python_version} onChange={(event) => setForm({ ...form, environment: { ...form.environment, python_version: event.target.value } })}/></label><label>Operating system<input aria-label="Operating system" value={form.environment.operating_system} onChange={(event) => setForm({ ...form, environment: { ...form.environment, operating_system: event.target.value } })}/></label><label>Deployment<input aria-label="Deployment" value={form.environment.deployment} onChange={(event) => setForm({ ...form, environment: { ...form.environment, deployment: event.target.value } })}/></label></div>
      <label>Hard constraints <small>one per line, maximum five</small><textarea aria-label="Hard constraints" value={constraints} onChange={(event) => setConstraints(event.target.value)}/></label>
      <label>Candidate shortlist <small>optional, comma-separated, maximum three</small><input aria-label="Candidate shortlist" value={candidates} onChange={(event) => setCandidates(event.target.value)}/></label>
      <fieldset className="mode-field"><legend>Mode</legend><label><input type="radio" name="mode" checked={(form.mode ?? "fast") === "fast"} onChange={() => setForm({ ...form, mode: "fast" })}/> Fast Demo</label><label><input type="radio" name="mode" checked={form.mode === "verified"} onChange={() => setForm({ ...form, mode: "verified" })}/> Verified (Live + reviewed Docker)</label></fieldset>
      {error && <div className="api-warning" role="alert"><strong>{error.code}</strong><span>{error.message}</span></div>}
      <button className="primary-action" disabled={pending}>{pending ? "Submitting…" : "Start TechScout task"}</button>
    </form><aside className="recent-runs"><header><span>02</span><div><p className="eyebrow">Recent runs</p><h2>Decision ledger</h2></div></header><Link className="offline-callout" to={`/runs/${TECHSCOUT_FIXTURE_ID}`}><b>Synthetic offline fixture</b><span>No live evidence, provider, Docker, or evaluation claims.</span></Link>{runs.map((run) => <Link key={run.id} to={`/runs/${run.id}`}><span className="run-dot" data-status={run.status}/><strong>{run.question}</strong><small>{run.status.replaceAll("_", " ")}</small></Link>)}</aside></section>
  </>;
}
