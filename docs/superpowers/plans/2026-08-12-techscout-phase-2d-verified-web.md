# TechScout Phase 2D Verified Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect existing live evidence/context and reviewed real Docker PoC services to the verified Web path without changing Fast fixture authority.

**Architecture:** Keep `DeterministicStageServices` exclusively for `fast`. Add an injected verified service factory at the Web composition root; the verified service reuses `LiveEvidenceResearchService`, candidate-scoped `ContextEngine`, and `RealPocService`, then publishes through the existing Harness, gate, projection, artifact, checkpoint, and trace boundaries.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, LangGraph harness, SQLite checkpoints, httpx, Docker CLI, React 19, TypeScript, Vitest.

## Global Constraints

- Fast remains frozen synthetic and never invokes live research or Docker.
- Verified supports only the Python 3.11 Chroma/Qdrant Local hero case; pgvector and unknown candidates remain research-only.
- Live/cache/unavailable provenance and real/not-run PoC authority must never be inferred or conflated.
- Only the failed PoC stage may recover once; completed research is reused from checkpoint.
- Verified reaches a terminal status inside the configured 300-second whole-run deadline.
- Trace and artifacts contain bounded sanitized data only: no secrets, raw provider bodies, or absolute host paths.

---

### Task 1: Verified orchestration contract

**Files:**
- Test: `tests/web/test_techscout_verified_integration.py`
- Modify: `paper_agent/web/techscout_execution.py`
- Modify: `paper_agent/web/app.py`

**Interfaces:**
- Consumes: existing `LiveEvidenceResearchService.research`, `ContextEngine.build`, `RealPocService.execute`, and `RealPocService.rerun_stage`.
- Produces: an injectable verified dependency/factory accepted by `create_app` and `TechScoutSingleRunExecutor`.

- [ ] Write offline fake integration tests for happy path, cache fallback, Docker unavailable, unsupported candidates, single-stage recovery, deadline terminalization, safe provenance/trace, and Fast/Verified isolation.
- [ ] Run `python -m pytest tests/web/test_techscout_verified_integration.py -q` and confirm failures identify the missing verified composition boundary.
- [ ] Implement the smallest verified service and engine mode dispatch that satisfy those tests.
- [ ] Re-run the focused tests until green.

### Task 2: Honest API and UI authority labels

**Files:**
- Modify: `paper_agent/web/techscout_api_models.py`
- Modify: `paper_agent/web/techscout_execution.py`
- Modify: `web/src/routes/HomePage.tsx`
- Modify: `web/src/routes/RunPage.tsx`
- Modify: `web/src/routes/ReportPage.tsx`
- Modify: generated OpenAPI/TypeScript projections through repository scripts.
- Test: `tests/web/test_techscout_verified_integration.py`
- Test: `web/src/test/frontend.test.tsx`

**Interfaces:**
- Consumes: persisted evidence acquisition states and PoC statuses/recipe IDs.
- Produces: explicit Live, Cached, unavailable, PoC verified, research-only, limited, and synthetic labels.

- [ ] Add failing API/frontend behavior tests that mutate authority fields and assert the corresponding labels.
- [ ] Run focused Python and Vitest tests and confirm expected failures.
- [ ] Add minimal schema projections and presentation copy; regenerate checked contracts.
- [ ] Re-run focused tests and production build.

### Task 3: Verification and delivery

**Files:** all scoped Phase 2D changes.

**Interfaces:**
- Consumes: completed Tasks 1 and 2.
- Produces: reviewed Draft PR targeting `master`.

- [ ] Run focused Python/Web tests, full pytest/Vitest, OpenAPI snapshot, production build, Ruff, and `git diff --check`.
- [ ] Review `git diff origin/master...HEAD` on Standards and Spec axes in parallel and fix every Critical/Important finding.
- [ ] Re-run the complete gate, stage only scoped files, commit, push `codex/phase-2d-verified-web`, and create a Draft PR.

## Self-review

All eight requested offline boundaries map to Task 1; truthful API/UI states map to Task 2; full verification, dual review, and Draft delivery map to Task 3. No provider credential or real Docker success is required for deterministic completion, and no later family/recipe is introduced.
