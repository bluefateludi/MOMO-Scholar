# MOMO TechScout delivery documentation

This directory is the candidate-facing and interview-facing delivery layer for MOMO TechScout. It records what is reproducible at `origin/master@7c6a9ed25b50f790d3a0b39a541e46258da71f5a` without rewriting historical MOMO Scholar claims.

This documentation is intentionally still a Draft: #93 must merge first, then this branch must normally merge the resulting latest `master` and repeat the two-axis fact check before final sealing.

## Status vocabulary

Every capability is labeled with one of these meanings:

- **Implemented** — present in the current code path and supported by repository contracts/tests.
- **Explicitly limited** — callable or visible, but designed to return a limitation instead of pretending the missing boundary worked.
- **Future integration** — a module, interface, or plan exists, but it is not connected to the default product path.
- **Synthetic diagnostic** — useful for checking evaluation infrastructure, but forbidden as a model/product-effect or resume result.

## Reading order

1. [Architecture and authority](architecture.md) — component boundaries, data flow, and the source of truth.
2. [Running the product](running.md) — exact Fast, Verified/Live, and Offline semantics.
3. [Support and safety](support-and-safety.md) — supported candidates, research-only behavior, sandbox limits, approvals, and known limitations.
4. [Final delivery](final-delivery.md) — browser, test/CI, and synthetic runner authorities plus the completed fact check.
5. [Interview and resume](interview-and-resume.md) — project narrative and four Chinese STAR drafts using only authorized claims.

## Current release boundary

The current coherent vertical slice includes strict domain/state contracts, a bounded LangGraph graph, fixed runtime Skills, a fail-closed local MCP policy, frozen evidence/context flow, reviewed recipe contracts, deterministic validation, typed single-stage recovery, SQLite projections/checkpoints, a React/FastAPI surface, sanitized sealed tracing, and evaluation-package infrastructure.

The default Fast Demo still substitutes frozen synthetic evidence and deterministic synthetic PoC responses behind the real orchestration seams. The Live adapters and real Docker runner are implemented modules but are not connected to that Web executor. The `verified` request therefore returns an explicit limitation. This distinction is a product fact, not an evaluation result.

Historical Scholar closeout documents under `docs/` remain Scholar authority. Their retrieval, citation, and browser numbers must never be copied into TechScout results.
