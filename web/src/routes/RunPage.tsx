import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { techScoutApi } from "../api";
import { syntheticNotice } from "../api/techscoutFixtures";
import { useTechScoutRunPolling } from "../polling/useTechScoutRunPolling";
import { useResource } from "./useResource";

const stages = [{ id: "plan", label: "Plan", note: "freeze the question" }, { id: "research", label: "Research", note: "collect official evidence" }, { id: "verify", label: "Verify", note: "run trusted recipes" }, { id: "decide", label: "Decide", note: "apply deterministic gates" }] as const;
export function RunPage() {
  const { id = "" } = useParams(); const { run, error, connectionLost, loading } = useTechScoutRunPolling(id, techScoutApi); const [traceOpen, setTraceOpen] = useState(false); const trace = useResource(() => techScoutApi.getTrace(id, undefined, 50).then((response) => response.data), [id, traceOpen]);
  if (loading) return <div className="page-state">Loading run projection…</div>; if (error || !run) return <div className="page-state" role="alert">{error?.message ?? "Run not found."}</div>;
  return <article className="tech-run">{run.synthetic && <div className="synthetic-ribbon" role="note">{syntheticNotice}</div>}{connectionLost && <div className="connection-banner" role="alert">Connection lost — retaining the last known state and retrying with backoff.</div>}
    <header className="run-title"><div><p className="eyebrow">{run.mode} mode · {run.status.replaceAll("_", " ")}</p><h1>{run.question}</h1></div><div className="elapsed"><strong>{run.progress.elapsed_seconds.toFixed(1)}s</strong><span>fixture elapsed</span></div></header>
    <ol className="stage-track">{stages.map((stage, index) => { const complete = run.progress.completed_stages.includes(stage.id); const current = run.progress.stage === stage.id; return <li key={stage.id} className={complete ? "complete" : current ? "current" : ""}><span>{String(index + 1).padStart(2, "0")}</span><strong>{stage.label}</strong><small>{stage.note}</small></li>; })}</ol>
    <section className="now-panel"><div><span>Current skill</span><strong>{run.progress.current_skill ?? "—"}</strong></div><div><span>Current tool</span><strong>{run.progress.current_tool ?? "—"}</strong></div><div><span>Approval</span><strong>{run.approval.status.replaceAll("_", " ")}</strong></div><div><span>Recovery</span><strong>{run.recovery.outcome.replaceAll("_", " ")} · {run.recovery.attempts_used}/1</strong></div></section>
    <section className="candidate-board"><header><p className="eyebrow">Candidate matrix</p><h2>{run.candidates.length ? `${run.candidates.length} components` : "Awaiting candidate projection"}</h2></header><div>{run.candidates.map((candidate) => <Link key={candidate.candidate_id} to={`/runs/${id}/candidates/${encodeURIComponent(candidate.candidate_id)}`}><span className="candidate-index">{candidate.candidate_id}</span><strong>{candidate.name}</strong><small>{candidate.support_level.replaceAll("_", " ")}</small><b>{candidate.verdict.replaceAll("_", " ")}</b></Link>)}</div></section>
    <div className="run-links"><Link to={`/runs/${id}/report`}>Open decision report →</Link></div>
    <section className="trace-drawer"><button aria-expanded={traceOpen} onClick={() => setTraceOpen(!traceOpen)}>Trace feed <span>{traceOpen ? "Collapse" : "Expand"}</span></button>{traceOpen && <ol>{trace.data?.items.map((event) => <li key={event.cursor}><time>{event.stage ?? event.event_type}</time><div><strong>{event.label}</strong><small>{[event.skill, event.tool, event.duration_ms == null ? null : `${event.duration_ms} ms`].filter(Boolean).join(" · ")}</small></div></li>)}</ol>}</section>
  </article>;
}
