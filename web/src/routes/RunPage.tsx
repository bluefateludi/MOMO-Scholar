import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Artifacts } from "../components/Artifacts";
import { ConnectionBanner, ErrorPanel, Loading, RunBanner, StatusBadge } from "../components/Feedback";
import { useRunPolling } from "../polling/useRunPolling";

const phases = ["queued", "initializing", "search", "acquisition", "chunking", "retrieval", "analysis", "synthesis", "citation_check", "publishing", "terminal"];
export function RunPage() {
  const { id = "" } = useParams(); const { run, error, connectionLost, loading } = useRunPolling(id, api);
  if (loading && !run) return <Loading/>;
  if (!run) return <ErrorPanel code={error?.code} message={error?.message ?? "The run could not be loaded."}/>;
  const phaseIndex = phases.indexOf(run.phase); const active = run.status === "queued" || run.status === "running";
  return <div className="content-page page-enter">{connectionLost && <ConnectionBanner/>}<RunBanner run={run}/>
    <header className="run-header"><div><p className="eyebrow">Research file <span>{run.id.slice(0, 8)}</span></p><h1>{run.question}</h1></div><StatusBadge status={run.status}/></header>
    <section className="progress-panel" aria-live="polite"><div className="progress-lead"><span>{active ? "Pipeline in progress" : "Pipeline record"}</span><strong>{run.phase.replaceAll("_", " ")}</strong>{run.progress.total_units !== null && <p>{run.progress.completed_units ?? 0} of {run.progress.total_units} papers in this phase</p>}{run.progress.paper_id && <code>{run.progress.paper_id}</code>}</div><ol>{phases.map((phase, index) => <li key={phase} className={index < phaseIndex ? "done" : index === phaseIndex ? "current" : ""}><span>{String(index + 1).padStart(2, "0")}</span>{phase.replaceAll("_", " ")}</li>)}</ol></section>
    {(run.status === "failed" || run.status === "interrupted") && <div className="retry-note"><h2>No report was published.</h2><p>The pipeline does not invent a substitute report after a terminal failure. Review the safe issue code above, then create a new run.</p><Link className="text-link" to="/">Start a new run →</Link></div>}
    {run.has_report && <nav className="run-actions" aria-label="Run content"><Link to={`/runs/${encodeURIComponent(run.id)}/report`}><span>01</span><strong>Read checked report</strong><small>Claims, support and Evidence</small></Link><Link to={`/runs/${encodeURIComponent(run.id)}/report#papers`}><span>02</span><strong>Browse paper analysis</strong><small>Choose a source from the report</small></Link></nav>}
    <dl className="run-meta"><div><dt>API run ID</dt><dd>{run.id}</dd></div><div><dt>Artifact run ID</dt><dd>{run.artifact_run_id ?? "Not created yet"}</dd></div><div><dt>Source mode</dt><dd>{run.content_mode.replaceAll("_", " ")}</dd></div><div><dt>Retrieval</dt><dd>{run.retrieval.mode} · top {run.retrieval.top_k}</dd></div></dl>
    <Artifacts run={run}/>
  </div>;
}
