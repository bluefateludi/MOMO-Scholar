import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorPanel, Loading, RunBanner } from "../components/Feedback";
import { useResource } from "./useResource";

export function EvidencePage() {
  const { id = "", evidenceId = "" } = useParams(); const { data, error } = useResource(async () => { const [run, evidence] = await Promise.all([api.getRun(id), api.getEvidenceItem(id, evidenceId)]); return { run: run.data, evidence: evidence.data }; }, [id, evidenceId]);
  if (error) return <ErrorPanel code={error.code} message={error.message}/>; if (!data) return <Loading/>; const item = data.evidence;
  return <div className="content-page evidence-page page-enter"><RunBanner run={data.run}/><Link className="back-link" to={`/runs/${encodeURIComponent(id)}/papers/${encodeURIComponent(item.paper_id)}`}>← Paper analysis</Link>
    <header className="evidence-header"><div><p className="eyebrow">Persisted Evidence</p><h1>One claim.<br/><em>Exact provenance.</em></h1></div><span className="score"><strong>{item.relevance_score.toFixed(2)}</strong><small>retrieval score</small></span></header>
    <figure className="evidence-quote"><span aria-hidden="true">“</span><blockquote>{item.quote}</blockquote><figcaption>This quote is persisted research data. It is never fetched from the source URL at view time.</figcaption></figure>
    <dl className="provenance"><div><dt>Paper</dt><dd><Link to={`/runs/${encodeURIComponent(id)}/papers/${encodeURIComponent(item.paper_id)}`}>{item.source.title}</Link><code>{item.paper_id}</code></dd></div><div><dt>Location</dt><dd>{item.section ?? "Unknown section"}<span>{item.page === null ? "Unknown page" : `Page ${item.page}`}</span></dd></div><div><dt>Chunk</dt><dd><code>{item.chunk_id}</code></dd></div><div><dt>Claim type</dt><dd>{item.claim_type}</dd></div><div><dt>Evidence ID</dt><dd><code>{item.evidence_id}</code></dd></div><div><dt>Content source</dt><dd>{item.source.content_source.toUpperCase()}{item.source.fallback_code && <span>Fallback: {item.source.fallback_code}</span>}</dd></div></dl>
    <a className="source-button" href={item.source.url} target="_blank" rel="noopener noreferrer">Open paper source ↗</a>
  </div>;
}
