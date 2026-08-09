# MOMO TechScout final browser acceptance

- Date: 2026-08-09 (Asia/Hong_Kong)
- Baseline: `origin/master@b7516a7b478834614f6ce2ccf1ae63a5c73c3140`
- Assembly: local FastAPI serving the React production build at `http://127.0.0.1:8765`
- Browser: headed Chromium controlled by Playwright CLI
- Network boundary: frozen Fast Demo only; no live provider, paid API, research network, or real Docker claim
- Result: pass after fixing the Windows-only fixture-integrity test described below

## Acceptance runs

The first run used separate CLI snapshots around the same browser session, so its
browser-observed wall time includes snapshot and screenshot startup overhead. The
application's persisted elapsed time is included to make the distinction explicit.

| Scenario | Run ID | Browser wall-clock | Persisted elapsed | Terminal result |
|---|---|---:|---:|---|
| Hero Fast Demo 1 | `68d4aa09-29fc-4870-a9b1-9ae7ecff2eef` | 45.081 s | 15.1 s | `completed` |
| Hero Fast Demo 2 | `40bede61-5d3a-4b41-b4f4-37f942e43588` | 15.360 s | 14.1 s | `completed` |
| Hero Fast Demo 3 | `013c0b50-8406-408e-9c0a-7826b3bd6638` | 12.879 s | 10.6 s | `completed` |
| Cached evidence fallback | `07f4c009-efa2-427a-9e72-ed71f348ee70` | not separately sampled | 9.9 s | `completed_with_limitations` |
| Single recovery | `dcfc42cf-5f67-419a-8ff3-ac20575e0b3f` | 14.959 s | 13.0 s | `completed` |
| Unknown candidate | `40729c3b-5715-4da3-a9e0-c30d10b0e324` | 5.810 s | 2.5 s | `completed_with_limitations` |
| Injected executor exception | `00000000-0000-4000-8000-000000000909` | immediate injected boundary | 0.0 s | `failed` |

All three consecutive Hero runs reached a terminal state within the 120-second
acceptance budget. Every other submitted scenario also terminalized; no unbounded
spinner was observed.

## User-visible checks

- The home page accepted a Hero Python 3.11 local-RAG vector-store task through
  the Fast Demo form and navigated to the durable run URL.
- Normal results showed the recommendation, deterministic tie-break reason,
  synthetic/frozen evidence boundary, supported candidates, and pgvector as
  `research only` with insufficient evidence.
- The cached path returned `completed_with_limitations`, `no safe winner`, a
  visible `tool_unavailable` issue, unknown gates, and
  `cached_provider_degradation` in the report.
- The recovery path showed `recovered · 1/1`. Its Trace preserved the dependency
  conflict, checkpoint, `pin_version_and_rerun_poc` action, repeated only
  `execute_poc`, and recorded the recovered outcome.
- An unknown `MysteryDB` candidate remained `research only`; the report said
  `No trusted recipe — research only`, returned `no safe winner`, and the Trace
  contained no `sandbox.run_smoke_test` event for that candidate.
- Refreshing a completed recovery run restored its terminal result, recommendation,
  candidate matrix, and `recovered · 1/1` state.
- The injected executor exception produced a durable `failed` page with the stable
  `execution_initialization_failed` code and no report link. The raw exception and
  `secret-canary` were absent from the rendered DOM and persisted projection, and
  the failed page remained failed after refresh.
- Report first screens exposed the recommendation or `no safe winner`, the reason,
  and the synthetic frozen/cache boundary. Existing `decision-report.md` and
  `decision-report.json` files were non-empty/parseable for all seven runs.
- Browser smoke finished with zero console errors and zero console warnings. All
  observed API requests returned expected `200 OK` or `202 Accepted` responses.

## Local smoke artifacts

The Playwright convention keeps generated evidence under the ignored
`output/playwright/` tree. This run produced the following local artifacts under
`output/playwright/final-acceptance/`:

- `fast-demo-run-2.png`, `fast-demo-run-3.png`
- `single-recovery-trace-loaded.png`, `single-recovery-report.png`
- `unknown-research-only-trace.png`, `unknown-research-only-report.png`
- `failed-safe-refreshed.png`
- `.playwright-cli/traces/trace-1786276795162.trace`
- `.playwright-cli/traces/trace-1786276795162.network`
- `.playwright-cli/traces/trace-1786276795162.stacks`

Run artifacts were retained below
`output/playwright/final-acceptance/runs/techscout/<run-id>/`, including sealed
`traces.jsonl`, Markdown/JSON decision reports, evidence, PoC, manifest, and
checkpoint artifacts where applicable.

## Stability finding and fix

The full local gate initially failed only
`test_frozen_eval_fixtures_have_expected_hashes_and_no_observations` on Windows.
Git stored the frozen JSON fixtures with LF, while `core.autocrlf=true` checked
them out with CRLF. Hashing the worktree bytes therefore disagreed with the
repository-authoritative hashes even though `git status` reported no fixture
change. Normalizing CRLF to LF at the hash boundary makes the integrity assertion
platform-independent without changing any fixture or expected digest.

## Verification

- `.venv/Scripts/python.exe -m pytest tests/web tests/techscout -q`:
  `118 passed, 2 skipped`
- `npm test`: `22 passed`
- `npm run contracts:check`: passed
- `npm run build`: passed
- `.venv/Scripts/ruff.exe check .`: passed
- JSON/Markdown and sealed-Trace verification: seven artifact pairs parsed,
  seven `traces.jsonl` files verified sealed
- `git diff --check`: passed
