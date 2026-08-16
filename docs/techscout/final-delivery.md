# Final delivery authority

This record separates browser product acceptance, automated verification, and synthetic evaluation-runner diagnostics. The final bounded-evaluation audit authority is `ca7e65a3c1bcaa8e5da2e9b2776c615bceb74aab`, which includes PR #92 browser acceptance and PR #93. Later implementation commits do not retroactively authorize broader evaluation claims.

Planning targets, historical MOMO Scholar metrics, synthetic runner outputs, and unit-test observations are not interchangeable with real-model TechScout results.

## Browser product acceptance

Primary authority: [`docs/acceptance/2026-08-09-techscout-browser-acceptance.md`](../acceptance/2026-08-09-techscout-browser-acceptance.md), merged at `7c6a9ed25b50f790d3a0b39a541e46258da71f5a`.

The headed-Chromium run used the React production build served by local FastAPI at the actual run baseline `b7516a7b478834614f6ce2ccf1ae63a5c73c3140`. Its acceptance record and bounded stability fixes were merged by PR #92 at `7c6a9ed25b50f790d3a0b39a541e46258da71f5a`. Its network boundary was the frozen synthetic Fast Demo: no live provider, paid API, research network, or real-Docker execution was claimed.

| Scenario | Browser wall-clock | Terminal/UI result |
|---|---:|---|
| Hero Fast Demo, consecutive run 1 | 45.081 s | `completed` |
| Hero Fast Demo, consecutive run 2 | 15.360 s | `completed` |
| Hero Fast Demo, consecutive run 3 | 12.879 s | `completed` |
| Cached evidence fallback | 16.139 s | `completed_with_limitations`; visible cache degradation and `no safe winner` |
| Injected executor exception | 2.725 s injection + 0.377 s UI load | durable `failed`; no report substitute or secret leakage |

All three consecutive Hero runs terminalized within the 120-second acceptance budget. Normal, cached/limited, single-recovery, unknown-candidate, reload, injected-failure, and 390 px viewport flows passed. The browser session recorded **zero console errors and zero console warnings**.

The single-recovery scenario preserved the dependency conflict and checkpoint, applied `pin_version_and_rerun_poc`, repeated only `execute_poc`, reached `recovered`, and restored that state after reload. This is one path acceptance, not a Recovery Success percentage.

## Test and CI authority

| Scope | Commit / authority | Result | Interpretation |
|---|---|---|---|
| Product full-integration run | pre-PR #92 product baseline `b7516a7b478834614f6ce2ccf1ae63a5c73c3140`, integration-owner authority | 1462 passed, 3 skipped | Historical full-repository integration result; not the PR #92 focused count |
| PR #92 focused Python | `7c6a9ed25b50f790d3a0b39a541e46258da71f5a`; `tests/web tests/techscout` | 118 passed, 2 skipped | Focused TechScout/Web regression scope, not the whole repository |
| PR #92 Web | `7c6a9ed25b50f790d3a0b39a541e46258da71f5a`; `npm test` | 22 passed | Frontend test scope |
| PR #92 build/contracts/lint | same commit | OpenAPI contract check, production build, and Ruff passed | Build and static verification |
| PR #92 CI | same commit | Python quality/package smoke, Web quality, and sandbox build/no-network smoke green | Three distinct CI jobs; no live provider secret or paid call |

The browser authority additionally verified parseable/non-empty successful or limited reports, report-free failed execution, sealed traces, desktop/narrow rendering, expected API statuses, and absence of raw exception/secret-canary data from rendered and persisted projections.

## Synthetic evaluation-runner diagnostics

Primary authorities:

- [`docs/evaluations/2026-08-09-techscout-final-evaluation.md`](../evaluations/2026-08-09-techscout-final-evaluation.md)
- [sealed final audit summary](../evaluations/artifacts/techscout-final-2026-08-09-FINAL_AUDIT_AUTHORITY/audit-summary.md)
- [final resume authority](../evaluations/artifacts/techscout-final-2026-08-09-FINAL_AUDIT_AUTHORITY/resume-evidence.md)

The runner's `12/40/8` task/retrieval/fault shape was exercised with frozen synthetic fixtures. It emitted V0/V1 `12/12`, Recall@5 `0.90`, fault recovery `6/8`, `900` tokens, and roughly `235–296 ms` diagnostic latency. The amended package manifest SHA-256 is `662cfcffc81e95763296bf9598ff9bda529ebd1f5c2c6720a39d64c853516641`; the retained failed-precheck manifest SHA-256 is `cca1449dbad6827c89b818be58e76768e2a8106f78e194310977bb51d7939c68`.

These values verify loading, execution, aggregation, failure injection, partial-result handling, and package projection. They do **not** measure a real LLM, live retrieval, Docker-backed product effectiveness, or user outcome.

| Resume/product claim | Authority |
|---|---|
| V0/V1 Task Success | N/A — synthetic fixture diagnostic only |
| Recall@5 / version-filter product quality | N/A — synthetic fixture diagnostic only |
| Recovery Success rate | N/A — synthetic fixture diagnostic only |
| Tokens or cost per successful real task | N/A — synthetic fixture diagnostic only |
| Cold-live or warm-cache product latency | N/A — synthetic fixture diagnostic only |

The synthetic numbers must not appear as resume achievements or README headline product metrics. The authorized latency claim is the headed-browser Fast Demo acceptance above, with its synthetic boundary stated.

## Permanent evaluation limitations

1. The original full-run attempt is permanently retained as `FAILED_PRECHECK_AUTHORITY` with zero authoritative observations; a duplicated frozen hard constraint was a fixture-authoring defect, not a model or infrastructure result.
2. Exactly one amended run followed a data-only deletion of that exact duplicate. No model, threshold, expected outcome, runner behavior, or other fixture changed, and no further complete run is authorized.
3. Static preflight ran before the amendment, but its attestation was sealed only afterward from captured console output; it was not independently sealed at execution time.
4. Rankings, fault outcomes, token counts, and E2E services were authored synthetic fixture behavior. Consequently Task Success, First-pass, Recovery, Recall@5, retries, tokens, cold-live/warm-cache latency, and cost are permanently **N/A** for resume/model/product-effect claims.

## Final fact-check invariants

These invariants define the state that implementation/Standards and specification/provenance review must preserve. Review execution and CI status belong to the pull-request record rather than a self-certifying documentation claim.

### Axis A — implementation and standards

- README commands map to the current install/build/server entry points; no nonexistent Compose or TechScout CLI command is advertised.
- Fast, Verified/Live, and Offline wording matches the Web executor and UI.
- Chroma and Qdrant Local are the only reviewed V1 recipes; pgvector and unknown candidates remain research-only.
- Terminal statuses, deterministic gate, failed-stage-only recovery, sandbox/network constraints, and artifact/Trace authority match current contracts.
- Documentation changes contain no secret, raw provider body, absolute authority path, unbounded output, or ignored evaluation artifact.

### Axis B — specification and claim provenance

- Browser timings and scenario results trace to the tracked acceptance record at PR #92.
- Full-repository and focused test counts are labeled separately with scope and commit.
- The original failure, single data-only amendment, late-sealed preflight limitation, no-rerun rule, and synthetic-only Resume N/A audit remain visible.
- Synthetic `12/40/8` diagnostics are labeled non-publishable for product effect and N/A for resume use.
- Browser wall-clock is not relabeled as cold-live/warm-cache evaluation latency.
- MOMO Scholar metrics remain legacy Scholar authority and do not appear as TechScout results.
- The four resume drafts use only browser acceptance, the single recovery-path observation, test scope, and CI evidence authorized here.
