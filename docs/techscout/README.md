# MOMO TechScout delivery documentation

This directory is the candidate-facing and interview-facing delivery layer for MOMO TechScout. The sealed evaluation authority remains `ca7e65a3c1bcaa8e5da2e9b2776c615bceb74aab` (PR #93), including PR #92 browser acceptance; later product changes, including the bounded Verified Web wiring in PR #98, do not retroactively expand that evaluation authority or rewrite historical MOMO Scholar claims.

## Status vocabulary

Every capability is labeled with one of these meanings:

- **Implemented** — present in the current code path and supported by repository contracts/tests.
- **Environment-dependent** — connected for the bounded product path, but external provider/cache, Docker, or network capacity may produce an honest limitation.
- **Research-only** — evidence may be collected, but no reviewed recipe authorizes a recommendation.
- **Synthetic diagnostic** — useful for checking evaluation infrastructure, but forbidden as a model/product-effect or resume result.

## Reading order

1. [Architecture and authority](architecture.md) — component boundaries, data flow, and the source of truth.
2. [Running the product](running.md) — exact Fast, Verified/Live, and Offline semantics.
3. [Support and safety](support-and-safety.md) — supported candidates, research-only behavior, sandbox limits, approvals, and known limitations.
4. [Final delivery](final-delivery.md) — browser, test/CI, and sealed synthetic-runner authorities plus the final fact-check invariants.
5. [Interview and resume](interview-and-resume.md) — project narrative and four Chinese STAR drafts using only authorized claims.

## Current release boundary

The current coherent vertical slice includes strict domain/state contracts, a bounded LangGraph graph, fixed runtime Skills, a fail-closed local MCP policy, frozen evidence/context flow, reviewed recipe contracts, deterministic validation, typed single-stage recovery, SQLite projections/checkpoints, a React/FastAPI surface, sanitized sealed tracing, and evaluation-package infrastructure.

The default Fast Demo still substitutes frozen synthetic evidence and deterministic synthetic PoC responses behind the real orchestration seams. The `verified` Web path is now separately composed from bounded live/cache research, candidate-scoped context, and the reviewed real Docker PoC service. Chroma and Qdrant Local may complete under real authority; provider/cache/Docker gaps produce explicit limitations, while pgvector and unknown candidates remain research-only. This distinction is a product fact, not an evaluation result.

Historical Scholar closeout documents under `docs/` remain Scholar authority. Their retrieval, citation, and browser numbers must never be copied into TechScout results.

## Demo media policy

No screenshot or GIF is currently committed as v0.1.0 execution authority. A future capture must be reproducible from a recorded commit, keep the Fast synthetic or Verified authority label visible in-frame, document its capture steps, and avoid provider secrets or local artifacts. Until then, use the running Fast UI rather than a mock or fabricated image.
