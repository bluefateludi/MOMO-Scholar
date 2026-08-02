import { Link } from "react-router-dom";

export function EvidenceLinks({ runId, ids }: { runId: string; ids: string[] }) {
  if (!ids.length) return <span className="unresolved">No supporting Evidence</span>;
  return <span className="evidence-links">{ids.map((id, index) => <Link key={id} to={`/runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(id)}`} title={id}>E{String(index + 1).padStart(2, "0")}</Link>)}</span>;
}
