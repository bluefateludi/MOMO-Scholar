# MOMO TechScout delivery documentation

This directory is the candidate-facing and interview-facing delivery layer for MOMO TechScout. It records what is reproducible at `origin/master@b7516a7b478834614f6ce2ccf1ae63a5c73c3140` without rewriting historical MOMO Scholar claims.

## Status vocabulary

Every capability is labeled with one of these meanings:

- **Implemented** — present in the current code path and supported by repository contracts/tests.
- **Explicitly limited** — callable or visible, but designed to return a limitation instead of pretending the missing boundary worked.
- **Future integration** — a module, interface, or plan exists, but it is not connected to the default product path.
- **Pending authority** — the measurement must come from a supplied, sealed final artifact. Its value is `PENDING_FINAL_AUTHORITY`; planning targets and fixture observations cannot fill it.

## Reading order

1. [Architecture and authority](architecture.md) — component boundaries, data flow, and the source of truth.
2. [Running the product](running.md) — exact Fast, Verified/Live, and Offline semantics.
3. [Support and safety](support-and-safety.md) — supported candidates, research-only behavior, sandbox limits, approvals, and known limitations.
4. [Final delivery](final-delivery.md) — final Eval and Browser fill-in sites plus the required authority checks.
5. [Interview and resume](interview-and-resume.md) — project narrative and four STAR-format drafts whose measurements remain pending.

## Current release boundary

The current coherent vertical slice includes strict domain/state contracts, a bounded LangGraph graph, fixed runtime Skills, a fail-closed local MCP policy, frozen evidence/context flow, reviewed recipe contracts, deterministic validation, typed single-stage recovery, SQLite projections/checkpoints, a React/FastAPI surface, sanitized sealed tracing, and evaluation-package infrastructure.

The default Fast Demo still substitutes frozen synthetic evidence and deterministic synthetic PoC responses behind the real orchestration seams. The Live adapters and real Docker runner are implemented modules but are not connected to that Web executor. The `verified` request therefore returns an explicit limitation. This distinction is a product fact, not an evaluation result.

Historical Scholar closeout documents under `docs/` remain Scholar authority. Their retrieval, citation, and browser numbers must never be copied into TechScout results.
