import { Link, useParams } from "react-router-dom";
import { techScoutApi } from "../api";
import { syntheticNotice } from "../api/techscoutFixtures";
import { useResource } from "./useResource";

export function EvidencePage() {
  const { id = "", evidenceId = "" } = useParams(); const evidence = useResource(() => techScoutApi.getEvidenceItem(id, evidenceId).then((response) => response.data), [id, evidenceId]);
  if (evidence.error) return <div className="page-state" role="alert">{evidence.error.message}</div>; if (!evidence.data) return <div className="page-state">Loading evidence…</div>; const item = evidence.data;
  const authority = item.acquisition_state === "live" ? "Live" : item.acquisition_state === "cache" ? "Cached" : item.acquisition_state === "synthetic" ? "Synthetic" : "Unavailable";
  return <article className="tech-evidence"><div className="synthetic-ribbon" role="note">{item.acquisition_state === "synthetic" ? syntheticNotice : `${authority} evidence`}</div><header><div><p className="eyebrow">{item.kind.replaceAll("_", " ")} · {item.candidate_id}</p><h1>Evidence<br/><em>record</em></h1></div><Link to={`/runs/${id}/report`}>← Decision report</Link></header><blockquote>{item.claim}</blockquote><dl><div><dt>Authority</dt><dd>{authority}</dd></div><div><dt>Evidence ID</dt><dd>{item.evidence_id}</dd></div><div><dt>Source type</dt><dd>{item.source_type.replaceAll("_", " ")}</dd></div><div><dt>Source title</dt><dd>{item.source_title}</dd></div><div><dt>Source hash</dt><dd><code>{item.snapshot_sha256}</code></dd></div><div><dt>Snapshot time</dt><dd>{new Date(item.as_of).toLocaleString()}</dd></div></dl>{item.source_url ? <a className="primary-action inline" href={item.source_url} target="_blank" rel="noopener noreferrer">Open source</a> : item.acquisition_state === "synthetic" ? <p className="offline-source">Frozen synthetic source: no external URL is exposed.</p> : null}</article>;
}
