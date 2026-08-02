import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { RunDetail, RunIssue, RunStatus, SupportStatus } from "../api/contracts";

export function Loading({ label = "Reading the research file…" }: { label?: string }) { return <div className="loading" role="status"><span className="spinner" />{label}</div>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><span aria-hidden="true">∅</span><h2>{title}</h2>{children}</div>; }
export function ErrorPanel({ code, message }: { code?: string; message: string }) { return <section className="error-panel" role="alert"><p className="eyebrow">Unable to open file</p><h2>{message}</h2>{code && <code>{code}</code>}<p><Link to="/">Return to the research desk</Link></p></section>; }
export function DemoBanner() { return <aside className="demo-banner" role="note"><strong>Synthetic offline demo</strong><span>Not research output or evaluation evidence. No provider or network call is made.</span></aside>; }
export function ConnectionBanner() { return <div className="connection-banner" role="alert"><strong>Connection lost.</strong> Showing the last known run state; reconnecting automatically.</div>; }
export function StatusBadge({ status }: { status: RunStatus }) { return <span className={`status status-${status}`}>{status.replaceAll("_", " ")}</span>; }
export function SupportBadge({ status }: { status: SupportStatus }) { return <span className={`support support-${status}`}>{status.replaceAll("_", " ")}</span>; }
export function friendlyIssue(code: string) {
  const messages: Record<string, string> = { vector_network_unavailable: "Vector retrieval was unavailable; approved lexical fallback was used.", vector_rate_limited: "Vector retrieval was rate-limited; approved lexical fallback was used.", embedding_timeout: "Embedding timed out; approved lexical fallback was used.", provider_configuration_missing: "The generation provider is not configured for this local service.", pipeline_terminated_without_manifest: "The process stopped before a terminal manifest was published." };
  return messages[code] ?? `Run issue: ${code.replaceAll("_", " ")}`;
}
export function IssueList({ title, issues, tone = "warning" }: { title: string; issues: RunIssue[]; tone?: "warning" | "error" }) {
  if (!issues.length) return null;
  return <section className={`issue-list ${tone}`} role={tone === "error" ? "alert" : "note"}><p className="eyebrow">{title}</p><ul>{issues.map((issue, index) => <li key={`${issue.code}-${index}`}><strong>{friendlyIssue(issue.code)}</strong><span>{issue.stage}{issue.paper_id ? ` · ${issue.paper_id}` : ""}</span></li>)}</ul></section>;
}
export function RunBanner({ run }: { run: RunDetail }) { return <>{run.demo && <DemoBanner />}{run.status === "completed_with_degradation" && <IssueList title="Completed with degradation" issues={run.manifest?.degradations ?? []} />}{(run.status === "failed" || run.status === "interrupted") && <IssueList title={run.status === "failed" ? "Research run failed" : "Research run interrupted"} issues={run.manifest?.errors ?? []} tone="error" />}</>; }
