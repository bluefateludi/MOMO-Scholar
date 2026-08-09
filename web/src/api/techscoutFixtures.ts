import type { TechScoutCandidate, TechScoutEvidence, TechScoutReport, TechScoutRunDetail, TracePage } from "./contracts";

export const TECHSCOUT_FIXTURE_ID = "10000000-0000-4000-8000-000000000001";
export const syntheticNotice = "Synthetic Wave 1 contract fixture — not live research or evaluation evidence.";
const at = "2026-08-09T04:00:00Z";

export const techScoutEvidence: TechScoutEvidence[] = [
  { evidence_id: "ev-chroma-persistence", candidate_id: "chroma", kind: "retrieved_fact", claim: "Chroma documents local persistent storage.", source_title: "Synthetic Chroma persistence snapshot", source_type: "official_documentation", source_url: null, as_of: at },
  { evidence_id: "ev-chroma-poc", candidate_id: "chroma", kind: "local_measurement", claim: "The frozen allowlisted fixture passes persistence and metadata filtering checks.", source_title: "Synthetic allowlisted PoC result", source_type: "poc", source_url: null, as_of: at },
  { evidence_id: "ev-qdrant-local", candidate_id: "qdrant-local", kind: "retrieved_fact", claim: "Qdrant documents an embedded local mode.", source_title: "Synthetic Qdrant Local snapshot", source_type: "official_documentation", source_url: null, as_of: at },
  { evidence_id: "ev-pgvector-research-only", candidate_id: "pgvector", kind: "retrieved_fact", claim: "pgvector requires PostgreSQL; this fixture has no trusted PostgreSQL recipe.", source_title: "Synthetic pgvector package snapshot", source_type: "package_metadata", source_url: null, as_of: at },
];

export const techScoutCandidates: TechScoutCandidate[] = [
  { candidate_id: "chroma", name: "Chroma", support_level: "v1_supported", requested_version: null, resolved_version: "fixture-pinned", compatibility: "compatible", verdict: "recommended", evidence_ids: ["ev-chroma-persistence", "ev-chroma-poc"] },
  { candidate_id: "qdrant-local", name: "Qdrant Local", support_level: "v1_supported", requested_version: null, resolved_version: "fixture-pinned", compatibility: "compatible", verdict: "not_recommended", evidence_ids: ["ev-qdrant-local"] },
  { candidate_id: "pgvector", name: "pgvector", support_level: "research_only", requested_version: null, resolved_version: null, compatibility: "unknown", verdict: "insufficient_evidence", evidence_ids: ["ev-pgvector-research-only"] },
];

export const techScoutRun: TechScoutRunDetail = {
  id: TECHSCOUT_FIXTURE_ID, status: "completed", synthetic: true, fixture_name: "happy-path", question: "Choose a local vector store for a Python 3.11 RAG service.", mode: "fast",
  progress: { stage: "terminal", completed_stages: ["plan", "research", "verify", "decide"], current_skill: null, current_tool: null, elapsed_seconds: 18.4 },
  created_at: at, finished_at: "2026-08-09T04:00:18.400Z", project_context: "A single-node local service with no separately managed database.",
  environment: { python_version: "3.11", operating_system: "linux-container", deployment: "single-node-local" },
  hard_constraints: ["local persistence", "metadata equality filtering", "no separately managed database"], candidates: techScoutCandidates,
  recovery: { attempted: false, failed_stage: null, action: null, outcome: "not_needed", attempts_used: 0 },
  approval: { required: false, status: "not_required", reason: null },
};

export const techScoutReport: TechScoutReport = {
  run_id: TECHSCOUT_FIXTURE_ID, verdict: "recommended", recommendation: "chroma", summary: "The synthetic fixture selects Chroma because the frozen evidence and allowlisted PoC cover every hard constraint.",
  constraints: techScoutRun.hard_constraints.map((constraint) => ({ constraint, candidate_id: "chroma", status: "satisfied", evidence_ids: ["ev-chroma-persistence", "ev-chroma-poc"], reason: null })),
  poc_results: [
    { candidate_id: "chroma", recipe_id: "fixture:chroma-local-contract-v1", status: "passed", checks: ["import", "persistence", "upsert", "query", "filter"], duration_ms: 640, synthetic: true },
    { candidate_id: "qdrant-local", recipe_id: "fixture:qdrant-local-contract-v1", status: "passed", checks: ["import", "persistence", "upsert", "query", "filter"], duration_ms: 710, synthetic: true },
    { candidate_id: "pgvector", recipe_id: null, status: "research_only", checks: [], duration_ms: 0, synthetic: true },
  ], limitations: [syntheticNotice, "Small contract checks do not establish production-scale performance.", "pgvector remains research-only without a reviewed PostgreSQL fixture."],
  evidence_ids: techScoutEvidence.map((item) => item.evidence_id), synthetic: true,
};

export const fixtureTrace: TracePage = { items: [
  { cursor: "ZXZlbnQ6MQ==", event_type: "stage", stage: "plan", status: "completed", label: "Investigation plan frozen from the synthetic request.", skill: null, tool: null, duration_ms: 900, created_at: at },
  { cursor: "ZXZlbnQ6Mg==", event_type: "skill", stage: "research", status: "completed", label: "Official-source fixture selected.", skill: "official-source-research", tool: null, duration_ms: 4200, created_at: at },
  { cursor: "ZXZlbnQ6Mw==", event_type: "tool", stage: "verify", status: "completed", label: "Allowlisted fixture recipe completed.", skill: "vector-store-verification", tool: "poc.run_allowlisted", duration_ms: 710, created_at: at },
  { cursor: "ZXZlbnQ6NA==", event_type: "stage", stage: "decide", status: "completed", label: "Deterministic gate published the fixture decision.", skill: null, tool: null, duration_ms: 1300, created_at: at },
], next_cursor: null };
