const issueMessages: Record<string, string> = {
  poc_timeout: "The allowlisted verification timed out within its configured bound.",
  research_only_candidate: "One or more candidates had no trusted verification recipe.",
  dependency_version_conflict: "The verification environment found a dependency version conflict.",
  insufficient_evidence: "The available evidence did not cover every hard constraint.",
  approval_denied: "The requested operation was not approved.",
};

export function messageForTechScoutIssue(code: string): string {
  return issueMessages[code] ?? "The run reached a bounded condition recorded by this stable code.";
}
