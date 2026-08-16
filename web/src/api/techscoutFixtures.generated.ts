// Generated from paper_agent.web.techscout_fixtures; do not edit.
export const generatedTechScoutFixture = {
  "detail": {
    "id": "10000000-0000-4000-8000-000000000001",
    "status": "completed",
    "synthetic": true,
    "fixture_name": "happy-path",
    "question": "Choose a local vector store for a Python 3.11 RAG service.",
    "mode": "fast",
    "progress": {
      "stage": "terminal",
      "completed_stages": [
        "plan",
        "research",
        "verify",
        "decide"
      ],
      "current_skill": null,
      "current_tool": null,
      "elapsed_seconds": 18.4
    },
    "created_at": "2026-08-09T04:00:00Z",
    "finished_at": "2026-08-09T04:00:18.400000Z",
    "project_context": "A single-node local service with no separately managed database.",
    "environment": {
      "python_version": "3.11",
      "operating_system": "linux-container",
      "deployment": "single-node-local"
    },
    "hard_constraints": [
      "local persistence",
      "metadata equality filtering",
      "no separately managed database"
    ],
    "candidates": [
      {
        "candidate_id": "chroma",
        "name": "Chroma",
        "support_level": "v1_supported",
        "requested_version": null,
        "resolved_version": "fixture-pinned",
        "compatibility": "compatible",
        "verdict": "recommended",
        "evidence_ids": [
          "ev-chroma-persistence",
          "ev-chroma-poc"
        ]
      },
      {
        "candidate_id": "qdrant-local",
        "name": "Qdrant Local",
        "support_level": "v1_supported",
        "requested_version": null,
        "resolved_version": "fixture-pinned",
        "compatibility": "compatible",
        "verdict": "not_recommended",
        "evidence_ids": [
          "ev-qdrant-local"
        ]
      },
      {
        "candidate_id": "pgvector",
        "name": "pgvector",
        "support_level": "research_only",
        "requested_version": null,
        "resolved_version": null,
        "compatibility": "unknown",
        "verdict": "insufficient_evidence",
        "evidence_ids": [
          "ev-pgvector-research-only"
        ]
      }
    ],
    "recovery": {
      "attempted": false,
      "failed_stage": null,
      "action": null,
      "outcome": "not_needed",
      "attempts_used": 0
    },
    "approval": {
      "required": false,
      "status": "not_required",
      "reason": null
    },
    "issues": []
  },
  "evidence": [
    {
      "evidence_id": "ev-chroma-persistence",
      "candidate_id": "chroma",
      "kind": "retrieved_fact",
      "claim": "Chroma documents local persistent storage.",
      "source_title": "Synthetic Chroma persistence snapshot",
      "source_type": "official_documentation",
      "source_url": null,
      "as_of": "2026-08-09T04:00:00Z",
      "acquisition_state": "synthetic",
      "snapshot_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    },
    {
      "evidence_id": "ev-chroma-poc",
      "candidate_id": "chroma",
      "kind": "local_measurement",
      "claim": "The frozen allowlisted fixture passes persistence and metadata filtering checks.",
      "source_title": "Synthetic allowlisted PoC result",
      "source_type": "poc",
      "source_url": null,
      "as_of": "2026-08-09T04:00:00Z",
      "acquisition_state": "synthetic",
      "snapshot_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    },
    {
      "evidence_id": "ev-qdrant-local",
      "candidate_id": "qdrant-local",
      "kind": "retrieved_fact",
      "claim": "Qdrant documents an embedded local mode.",
      "source_title": "Synthetic Qdrant Local snapshot",
      "source_type": "official_documentation",
      "source_url": null,
      "as_of": "2026-08-09T04:00:00Z",
      "acquisition_state": "synthetic",
      "snapshot_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    },
    {
      "evidence_id": "ev-pgvector-research-only",
      "candidate_id": "pgvector",
      "kind": "retrieved_fact",
      "claim": "pgvector requires PostgreSQL; this fixture has no trusted PostgreSQL recipe.",
      "source_title": "Synthetic pgvector package snapshot",
      "source_type": "package_metadata",
      "source_url": null,
      "as_of": "2026-08-09T04:00:00Z",
      "acquisition_state": "synthetic",
      "snapshot_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    }
  ],
  "report": {
    "run_id": "10000000-0000-4000-8000-000000000001",
    "verdict": "recommended",
    "recommendation": "chroma",
    "summary": "The synthetic fixture selects Chroma because the frozen evidence and allowlisted PoC cover every hard constraint.",
    "constraints": [
      {
        "constraint": "local persistence",
        "candidate_id": "chroma",
        "status": "satisfied",
        "evidence_ids": [
          "ev-chroma-persistence",
          "ev-chroma-poc"
        ],
        "reason": null
      },
      {
        "constraint": "metadata equality filtering",
        "candidate_id": "chroma",
        "status": "satisfied",
        "evidence_ids": [
          "ev-chroma-persistence",
          "ev-chroma-poc"
        ],
        "reason": null
      },
      {
        "constraint": "no separately managed database",
        "candidate_id": "chroma",
        "status": "satisfied",
        "evidence_ids": [
          "ev-chroma-persistence",
          "ev-chroma-poc"
        ],
        "reason": null
      }
    ],
    "poc_results": [
      {
        "candidate_id": "chroma",
        "recipe_id": "fixture:chroma-local-contract-v1",
        "status": "passed",
        "checks": [
          "import",
          "persistence",
          "upsert",
          "query",
          "filter"
        ],
        "duration_ms": 640,
        "synthetic": true,
        "verified": false
      },
      {
        "candidate_id": "qdrant-local",
        "recipe_id": "fixture:qdrant-local-contract-v1",
        "status": "passed",
        "checks": [
          "import",
          "persistence",
          "upsert",
          "query",
          "filter"
        ],
        "duration_ms": 710,
        "synthetic": true,
        "verified": false
      },
      {
        "candidate_id": "pgvector",
        "recipe_id": null,
        "status": "research_only",
        "checks": [],
        "duration_ms": 0,
        "synthetic": true,
        "verified": false
      }
    ],
    "limitations": [
      "Synthetic Wave 1 contract fixture — not live research or evaluation evidence.",
      "Small contract checks do not establish production-scale performance.",
      "pgvector remains research-only without a reviewed PostgreSQL fixture."
    ],
    "evidence_ids": [
      "ev-chroma-persistence",
      "ev-chroma-poc",
      "ev-qdrant-local",
      "ev-pgvector-research-only"
    ],
    "synthetic": true
  },
  "trace": {
    "items": [
      {
        "cursor": "ZXZlbnQ6MQ==",
        "event_type": "stage",
        "stage": "plan",
        "status": "completed",
        "label": "Investigation plan frozen from the synthetic request.",
        "skill": null,
        "tool": null,
        "duration_ms": 900,
        "created_at": "2026-08-09T04:00:01Z"
      },
      {
        "cursor": "ZXZlbnQ6Mg==",
        "event_type": "skill",
        "stage": "research",
        "status": "completed",
        "label": "Official-source fixture selected.",
        "skill": "official-source-research",
        "tool": null,
        "duration_ms": 4200,
        "created_at": "2026-08-09T04:00:02Z"
      },
      {
        "cursor": "ZXZlbnQ6Mw==",
        "event_type": "tool",
        "stage": "verify",
        "status": "completed",
        "label": "Allowlisted fixture recipe completed.",
        "skill": "vector-store-verification",
        "tool": "poc.run_allowlisted",
        "duration_ms": 710,
        "created_at": "2026-08-09T04:00:03Z"
      },
      {
        "cursor": "ZXZlbnQ6NA==",
        "event_type": "stage",
        "stage": "decide",
        "status": "completed",
        "label": "Deterministic gate published the fixture decision.",
        "skill": null,
        "tool": null,
        "duration_ms": 1300,
        "created_at": "2026-08-09T04:00:04Z"
      }
    ],
    "next_cursor": null
  }
} as const;
