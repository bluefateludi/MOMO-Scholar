import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { CheckedClaim } from "../api/contracts";
import { EvidenceLinks } from "../components/EvidenceLinks";
import { ErrorPanel, Loading, RunBanner, SupportBadge } from "../components/Feedback";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { useResource } from "./useResource";

export function ReportPage() {
  const { id = "" } = useParams(); const [view, setView] = useState<"checked" | "markdown">("checked");
  const { data, error } = useResource(async () => { const [run, report, evidence, papers] = await Promise.all([api.getRun(id), api.getReport(id), api.getEvidence(id), api.getPapers(id)]); return { run: run.data, report: report.data, evidence: evidence.data.items, papers: papers.data.items }; }, [id]);
  if (error) return <ErrorPanel code={error.code} message={error.message}/>; if (!data) return <Loading/>;
  const evidenceIds = data.evidence.map((item) => item.evidence_id); const sections: Array<[string, CheckedClaim[]]> = [["TL;DR", data.report.report.tldr_claims], ["Method taxonomy", data.report.report.method_taxonomy], ["Cross-paper comparison", data.report.report.comparisons], ["Key findings", data.report.report.key_findings], ["Limitations", data.report.report.limitations], ["Open questions", data.report.report.open_questions]];
  return <div className="content-page report-page page-enter"><RunBanner run={data.run}/><header className="report-header"><div><Link className="back-link" to={`/runs/${encodeURIComponent(id)}`}>← Research file</Link><p className="eyebrow">Checked survey report</p><h1>{data.report.report.question}</h1></div><div className="view-toggle" aria-label="Report view"><button className={view === "checked" ? "active" : ""} onClick={() => setView("checked")}>Checked view</button><button className={view === "markdown" ? "active" : ""} onClick={() => setView("markdown")}>Markdown</button></div></header>
    {view === "markdown" ? <SafeMarkdown markdown={data.report.markdown} runId={id} evidenceIds={evidenceIds}/> : <div className="report-layout"><article className="checked-report">{sections.map(([title, claims], sectionIndex) => <section key={title}><header><span>{String(sectionIndex + 1).padStart(2, "0")}</span><h2>{title}</h2><small>{claims.length} {claims.length === 1 ? "claim" : "claims"}</small></header>{claims.length === 0 ? <p className="section-empty">No checked claims in this section.</p> : <ol>{claims.map((claim, index) => <li key={`${title}-${index}`}><p>{claim.text}</p><footer><SupportBadge status={claim.support_status}/><EvidenceLinks runId={id} ids={claim.evidence_ids}/></footer></li>)}</ol>}</section>)}
      <section className="audit"><header><span>A</span><h2>Rejected critical claims</h2><small>Audit trail</small></header>{data.report.report.rejected_critical_claims.length === 0 ? <p className="section-empty">No critical claims were rejected.</p> : <ol>{data.report.report.rejected_critical_claims.map((claim, index) => <li key={index}><p>{claim.text}</p><footer><SupportBadge status={claim.support_status}/><span>Removed from {claim.source_section.replaceAll("_", " ")}</span><EvidenceLinks runId={id} ids={claim.evidence_ids}/></footer></li>)}</ol>}</section></article>
      <aside className="report-sidebar" id="papers"><p className="eyebrow">Selected papers</p>{data.papers.map((paper, index) => <Link key={paper.paper_id} to={`/runs/${encodeURIComponent(id)}/papers/${encodeURIComponent(paper.paper_id)}`}><span>{String(index + 1).padStart(2, "0")}</span><strong>{paper.title}</strong><small>{paper.year ?? "Year unknown"} · {paper.evidence_count} Evidence</small></Link>)}</aside></div>}
    <div className="report-downloads"><a href={api.artifactUrl(id, "report.md")} download>Download Markdown ↓</a><a href={api.artifactUrl(id, "report.json")} download>Download JSON ↓</a></div>
  </div>;
}
