import { Link, useParams } from "react-router-dom";
import { techScoutApi } from "../api";
import { syntheticNotice } from "../api/techscoutFixtures";
import { useResource } from "./useResource";

export function ReportPage() {
  const { id = "" } = useParams(); const report = useResource(() => techScoutApi.getReport(id).then((response) => response.data), [id]); const evidence = useResource(() => techScoutApi.getEvidence(id).then((response) => response.data.items), [id]);
  if (report.error) return <div className="page-state" role="alert">{report.error.message}</div>; if (!report.data) return <div className="page-state">Loading decision report…</div>; const data = report.data;
  return <article className="decision-report">{data.synthetic && <div className="synthetic-ribbon" role="note">{syntheticNotice}</div>}<header><div><p className="eyebrow">Decision report · {data.verdict.replaceAll("_", " ")}</p><h1>{data.recommendation ? <>Recommend <em>{data.recommendation}</em></> : "No safe winner"}</h1><p>{data.summary}</p></div><Link to={`/runs/${id}`}>← Run timeline</Link></header>
    <section className="constraint-table"><div className="section-number">01</div><div><p className="eyebrow">Hard constraints</p><h2>Gate record</h2>{data.constraints.map((item) => <article key={`${item.candidate_id}-${item.constraint}`}><span data-status={item.status}>{item.status.replaceAll("_", " ")}</span><strong>{item.constraint}</strong><small>{item.candidate_id}</small><div>{item.evidence_ids.map((evidenceId) => <Link key={evidenceId} to={`/runs/${id}/evidence/${encodeURIComponent(evidenceId)}`}>{evidenceId}</Link>)}</div></article>)}</div></section>
    <section className="poc-grid"><header><span className="section-number">02</span><div><p className="eyebrow">Proof of concept</p><h2>Allowlisted checks</h2></div></header><div>{data.poc_results.map((poc) => <article key={poc.candidate_id}><span>{poc.status.replaceAll("_", " ")}</span><h3>{poc.candidate_id}</h3><p>{poc.recipe_id ?? "No trusted recipe — research only"}</p><ul>{poc.checks.map((check) => <li key={check}>{check}</li>)}</ul><small>{poc.synthetic ? "synthetic fixture" : "local run"} · {poc.duration_ms} ms</small></article>)}</div></section>
    <section className="evidence-index"><header><span className="section-number">03</span><div><p className="eyebrow">Evidence</p><h2>Claim ledger</h2></div></header>{evidence.data?.map((item) => <Link key={item.evidence_id} to={`/runs/${id}/evidence/${encodeURIComponent(item.evidence_id)}`}><span>{item.kind.replaceAll("_", " ")}</span><strong>{item.claim}</strong><small>{item.source_title}</small></Link>)}</section>
    <section className="limitations"><span className="section-number">04</span><div><p className="eyebrow">Limits</p><h2>What this does not prove</h2><ul>{data.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></div></section>
  </article>;
}
