const issueMessages: Record<string, string> = {
  poc_timeout: "The allowlisted verification timed out within its configured bound.",
  research_only_candidate: "One or more candidates had no trusted verification recipe.",
  dependency_version_conflict: "The verification environment found a dependency version conflict.",
  insufficient_evidence: "The available evidence did not cover every hard constraint.",
  approval_denied: "The requested operation was not approved.",
  dependency_conflict: "The deterministic local PoC found a dependency conflict and preserved the bounded recovery trace.",
  tool_unavailable: "Live provider or real Docker verification is unavailable; the run published an explicit limited result.",
  execution_initialization_failed: "The local TechScout executor failed before it could publish a report.",
  poc_recipe_unsupported: "No reviewed local PoC recipe exists for this candidate, so it remains research-only.",
};

export function messageForTechScoutIssue(code: string): string {
  return issueMessages[code] ?? "The run reached a bounded condition recorded by this stable code.";
}
