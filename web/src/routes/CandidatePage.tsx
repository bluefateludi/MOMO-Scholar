import { Link, useParams } from "react-router-dom";
import { techScoutApi } from "../api";
import { syntheticNotice } from "../api/techscoutFixtures";
import { useResource } from "./useResource";

export function CandidatePage() {
  const { id = "", candidateId = "" } = useParams(); const candidate = useResource(() => techScoutApi.getCandidate(id, candidateId).then((response) => response.data), [id, candidateId]); const evidence = useResource(() => techScoutApi.getEvidence(id).then((response) => response.data.items.filter((item) => item.candidate_id === candidateId)), [id, candidateId]);
  if (candidate.error) return <div className="page-state" role="alert">{candidate.error.message}</div>; if (!candidate.data) return <div className="page-state">Loading candidate…</div>; const item = candidate.data;
  return <article className="candidate-page"><div className="synthetic-ribbon" role="note">{syntheticNotice}</div><header><div><p className="eyebrow">Candidate · {item.support_level.replaceAll("_", " ")}</p><h1>{item.name}</h1></div><Link to={`/runs/${id}`}>← Candidate matrix</Link></header><dl><div><dt>Verdict</dt><dd>{item.verdict.replaceAll("_", " ")}</dd></div><div><dt>Compatibility</dt><dd>{item.compatibility}</dd></div><div><dt>Requested version</dt><dd>{item.requested_version ?? "not pinned"}</dd></div><div><dt>Resolved version</dt><dd>{item.resolved_version ?? "not verified"}</dd></div></dl><section><p className="eyebrow">Evidence &amp; PoC record</p><h2>{evidence.data?.length ?? 0} linked items</h2>{evidence.data?.map((entry) => <Link key={entry.evidence_id} to={`/runs/${id}/evidence/${encodeURIComponent(entry.evidence_id)}`}><strong>{entry.claim}</strong><small>{entry.kind.replaceAll("_", " ")} · {entry.source_title}</small></Link>)}</section></article>;
}
