import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, isMockMode } from "../api";
import { ApiError } from "../api/client";
import type { ContentMode, CreateRunRequest, RetrievalMode, RunSummary } from "../api/contracts";
import { DEMO_ID } from "../api/fixtures";
import { Empty, Loading, StatusBadge } from "../components/Feedback";

const defaults: CreateRunRequest = { question: "", paper_limit: 3, content_mode: "pdf_preferred", retrieval: { mode: "auto", candidate_k: 30, top_k: 8, rrf_k: 60, analysis_evidence_per_paper: 6 } };
export function HomePage() {
  const [form, setForm] = useState(defaults); const [runs, setRuns] = useState<RunSummary[] | null>(null); const [available, setAvailable] = useState<boolean | null>(null); const [pending, setPending] = useState(false); const [error, setError] = useState(""); const navigate = useNavigate();
  useEffect(() => { api.listRuns().then(({ data }) => { setRuns(data.items); setAvailable(true); }).catch(() => { setRuns([]); setAvailable(false); }); }, []);
  const setRetrieval = (key: keyof CreateRunRequest["retrieval"], value: string | number) => setForm((current) => ({ ...current, retrieval: { ...current.retrieval, [key]: value } }));
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    const question = form.question.trim();
    if (question.length < 3) { setError("Enter a research question of at least three characters."); return; }
    const bounded: Array<[number, number, number, string]> = [[form.paper_limit, 1, 10, "Paper count"], [form.retrieval.candidate_k, 1, 100, "Candidate K"], [form.retrieval.top_k, 1, 20, "Top K"], [form.retrieval.rrf_k, 1, 1000, "RRF K"], [form.retrieval.analysis_evidence_per_paper, 1, 20, "Evidence per paper"]];
    const invalid = bounded.find(([value, min, max]) => !Number.isInteger(value) || value < min || value > max);
    if (invalid) { setError(`${invalid[3]} must be a whole number from ${invalid[1]} to ${invalid[2]}.`); return; }
    if (form.retrieval.top_k > form.retrieval.candidate_k) { setError("Top K cannot exceed candidate K."); return; }
    if (form.retrieval.analysis_evidence_per_paper > form.retrieval.top_k) { setError("Evidence per paper cannot exceed top K."); return; }
    setPending(true);
    try { const { data } = await api.createRun({ ...form, question }); navigate(`/runs/${encodeURIComponent(data.id)}`); }
    catch (caught) { setError(caught instanceof ApiError ? caught.message : "The local API could not be reached."); setPending(false); }
  }
  return <div className="home-page page-enter">
    <section className="hero"><div className="hero-copy"><p className="eyebrow">Stage 4 · local research workspace</p><h1>Ask precisely.<br/><em>Trace everything.</em></h1><p className="dek">Build a checked literature survey whose claims remain attached to exact paper Evidence—not a persuasive black box.</p></div><aside className="folio" aria-label="Workflow summary"><span>01</span><p>Question</p><span>02</span><p>Retrieve</p><span>03</span><p>Check</p><span>04</span><p>Read</p></aside></section>
    <section className="desk-grid">
      <form className="run-form" onSubmit={submit} noValidate><div className="section-heading"><span>New research file</span><small>All fields are recorded with the run.</small></div><div className={`availability ${available === false ? "unavailable" : ""}`} role="status"><i/>{available === null ? "Checking local service…" : available ? (isMockMode ? "Fixture API ready · offline" : "Local API reachable") : "Local API unavailable"}</div>
        <label className="question-label">Research question<textarea value={form.question} onChange={(event) => setForm({ ...form, question: event.target.value })} minLength={3} maxLength={1000} rows={4} placeholder="How is hybrid retrieval used in scientific literature review?" required/><span>{form.question.length} / 1000</span></label>
        <div className="form-row"><label>Paper count<input type="number" min="1" max="10" value={form.paper_limit} onChange={(event) => setForm({ ...form, paper_limit: Number(event.target.value) })}/></label><fieldset><legend>Source material</legend><label><input type="radio" name="content" checked={form.content_mode === "pdf_preferred"} onChange={() => setForm({ ...form, content_mode: "pdf_preferred" as ContentMode })}/> PDF preferred</label><label><input type="radio" name="content" checked={form.content_mode === "abstract_only"} onChange={() => setForm({ ...form, content_mode: "abstract_only" as ContentMode })}/> Abstract only</label></fieldset></div>
        <div className="mode-row"><span>Retrieval mode</span>{(["auto", "lexical", "hybrid"] as RetrievalMode[]).map((mode) => <label key={mode}><input type="radio" name="retrieval" checked={form.retrieval.mode === mode} onChange={() => setRetrieval("mode", mode)}/><b>{mode}</b></label>)}</div>
        <details><summary>Retrieval settings <span>Advanced</span></summary><div className="advanced-grid"><NumberField label="Candidate K" value={form.retrieval.candidate_k} min={1} max={100} onChange={(value) => setRetrieval("candidate_k", value)}/><NumberField label="Top K" value={form.retrieval.top_k} min={1} max={20} onChange={(value) => setRetrieval("top_k", value)}/><NumberField label="RRF K" value={form.retrieval.rrf_k} min={1} max={1000} onChange={(value) => setRetrieval("rrf_k", value)}/><NumberField label="Evidence / paper" value={form.retrieval.analysis_evidence_per_paper} min={1} max={20} onChange={(value) => setRetrieval("analysis_evidence_per_paper", value)}/></div></details>
        {error && <p className="form-error" role="alert">{error}</p>}<button className="primary-button" disabled={pending}>{pending ? "Opening file…" : "Create research run"}<span aria-hidden="true">↗</span></button>
      </form>
      <aside className="demo-card"><p className="eyebrow">No network? Start here.</p><h2>A complete research file, already on the desk.</h2><p>Explore report, paper analysis, Evidence provenance and downloads using deterministic synthetic data.</p><Link className="text-link" to={`/runs/${DEMO_ID}`}>Open offline demo <span>→</span></Link><small>Synthetic demo · never presented as live output</small></aside>
    </section>
    <section className="recent"><div className="section-heading"><span>Recent files</span><small>Newest first</small></div>{runs === null ? <Loading label="Checking the local registry…"/> : runs.length === 0 ? <Empty title="No research files yet."/> : <div className="run-list">{runs.map((run, index) => <Link key={run.id} to={`/runs/${encodeURIComponent(run.id)}`}><span className="run-index">{String(index + 1).padStart(2, "0")}</span><div><strong>{run.question}</strong><small>{run.demo ? "Synthetic offline demo" : new Date(run.created_at).toLocaleString()}</small></div><StatusBadge status={run.status}/><span aria-hidden="true">↗</span></Link>)}</div>}</section>
  </div>;
}
function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) { return <label>{label}<input type="number" value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value))}/></label>; }
