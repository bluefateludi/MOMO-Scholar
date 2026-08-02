import { api } from "../api";
import type { ArtifactName, RunDetail } from "../api/contracts";

const labels: Partial<Record<ArtifactName, string>> = { "report.md": "Markdown report", "report.json": "Report JSON", "evidence.json": "Evidence JSON", "analyses.json": "Analyses JSON", "papers.json": "Papers JSON", "documents.json": "Documents JSON", "run_manifest.json": "Run manifest", "logs.jsonl": "Run log" };
export function Artifacts({ run }: { run: RunDetail }) {
  if (!run.available_artifacts.length) return null;
  return <section className="artifacts"><div><p className="eyebrow">Artifacts</p><h2>Take the research file with you.</h2>{run.demo && <p className="small-warning">Synthetic demo downloads remain fixture data—not research output.</p>}</div><div className="download-grid">{run.available_artifacts.map((name) => <a key={name} href={api.artifactUrl(run.id, name)} download>{labels[name] ?? name}<span>{name.split(".").pop()?.toUpperCase()} ↓</span></a>)}</div></section>;
}
