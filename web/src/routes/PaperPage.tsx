import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { CheckedClaim } from "../api/contracts";
import { EvidenceLinks } from "../components/EvidenceLinks";
import { ErrorPanel, Loading, RunBanner, SupportBadge } from "../components/Feedback";
import { useResource } from "./useResource";

export function PaperPage() {
  const { id = "", paperId = "" } = useParams();
  const { data, error } = useResource(async () => { const [run, analysis, evidence] = await Promise.all([api.getRun(id), api.getPaperAnalysis(id, paperId), api.getEvidence(id, paperId)]); return { run: run.data, analysis: analysis.data, evidence: evidence.data.items }; }, [id, paperId]);
  if (error) return <ErrorPanel code={error.code} message={error.message}/>; if (!data) return <Loading/>;
  const { paper, document, analysis } = data.analysis; const sections: Array<[string, CheckedClaim[]]> = [["Contributions", analysis.contributions], ["Methods", analysis.methods], ["Experiments", analysis.experiments], ["Results", analysis.results], ["Limitations", analysis.limitations]];
  return <div className="content-page paper-page page-enter"><RunBanner run={data.run}/><Link className="back-link" to={`/runs/${encodeURIComponent(id)}/report`}>← Checked report</Link><header className="paper-header"><div><p className="eyebrow">Paper analysis · {paper.paper_id}</p><h1>{paper.title}</h1><p>{paper.authors.join(", ") || "Authors unknown"} · {paper.year ?? "Year unknown"}</p></div><a className="source-button" href={paper.url} target="_blank" rel="noopener noreferrer">Open source ↗</a></header>
    {document?.content_source === "abstract" && <aside className="abstract-warning"><strong>Abstract-backed analysis</strong><span>{document.fallback_code ? `PDF fallback: ${document.fallback_code}.` : "Abstract-only mode was selected intentionally."} Findings do not claim full-text coverage.</span></aside>}
    {document?.warnings.map((warning) => <p className="document-warning" key={warning}>{warning}</p>)}
    <div className="paper-layout"><article className="analysis-sections">{sections.map(([title, findings], index) => <section key={title}><header><span>{String(index + 1).padStart(2, "0")}</span><h2>{title}</h2></header>{findings.length === 0 ? <p className="section-empty">No checked findings.</p> : findings.map((finding, findingIndex) => <div className="finding" key={findingIndex}><p>{finding.text}</p><footer><SupportBadge status={finding.support_status}/><EvidenceLinks runId={id} ids={finding.evidence_ids}/></footer></div>)}</section>)}</article><aside className="evidence-rail"><p className="eyebrow">Paper Evidence</p>{data.evidence.map((item, index) => <Link key={item.evidence_id} to={`/runs/${encodeURIComponent(id)}/evidence/${encodeURIComponent(item.evidence_id)}`}><span>E{String(index + 1).padStart(2, "0")}</span><blockquote>{item.quote}</blockquote><small>{item.section ?? "Unknown section"} · {item.page === null ? "Unknown page" : `Page ${item.page}`}</small></Link>)}</aside></div>
  </div>;
}
