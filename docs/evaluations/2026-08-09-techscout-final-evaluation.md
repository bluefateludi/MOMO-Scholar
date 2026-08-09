# MOMO TechScout Final Bounded Evaluation

## Authority chain

- Required baseline: `b7516a7b478834614f6ce2ccf1ae63a5c73c3140`.
- Frozen-input commit: `6be979ab13ddaae0e16408cedbb179ffd379f996`.
- Original run: `FAILED_PRECHECK_AUTHORITY`, sealed manifest SHA-256
  `cca1449dbad6827c89b818be58e76768e2a8106f78e194310977bb51d7939c68`.
- Data-only amendment: `659bc76aefdfd7cb062af02fc7b866217ff0a6fc`, which deleted one exact duplicate
  `metadata equality filtering` constraint and changed no model, threshold,
  expected outcome, runner behavior, or other fixture.
- Amended run: `AMENDED_AUTHORITY`, sealed manifest SHA-256
  `662cfcffc81e95763296bf9598ff9bda529ebd1f5c2c6720a39d64c853516641`.
- Final audit: `FINAL_AUDIT_AUTHORITY`; it preserves both runs but authorizes no
  numeric resume metric.

The failed run, amended run, initial index, final audit authority, and a sealed
post-run preflight attestation are committed under `docs/evaluations/artifacts/`.
The preflight result was captured in the task console before the amended run but
was only sealed afterward; that timing limitation is explicit in the artifact.

The original run produced zero authoritative observations because the frozen
input failed `ResearchRequest` construction. Its sealed trace is retained as
diagnostic evidence only. The error was a fixture authoring defect, not a model
or infrastructure result.

Before the single amended run, all 12 E2E request constructors, 40 retrieval
contracts, and eight fault injectors passed static preflight. The amended source
tree SHA-256 is
`9e16042c061d0ecc6b1074c7e7c1453c9c5dbd8c5eca64b16e35f52e95cdf6c0`;
the unchanged case tree SHA-256 is
`e8b90f5e7025155d0a114be1cfade705a8c7be2dafa9d6fdf589ad140243ed0d`.

## Recorded amended synthetic diagnostics

The runner completed 12 E2E tasks (24 V0/V1 observations), 40 retrieval cases,
and eight injected fault cases. Audit found that rankings, fault outcomes, token
counts, and E2E services were authored in the synthetic fixtures. The following
values are preserved diagnostics, not independent product/model measurements.

| Metric | V0 | V1 |
|---|---:|---:|
| Task Success | 12/12 | 12/12 |
| First-pass Success | 12/12 | 12/12 |
| E2E Recovery Success | 0/0 | 0/0 |
| Average E2E retries | 0.0 | 0.0 |
| Tool schema success | 12/12 | 12/12 |
| Tool execution success | 12/12 | 12/12 |
| Prompt tokens per successful task | 900.0 | 900.0 |
| Total tokens per successful task | 900.0 | 900.0 |
| Warm-cache latency p50/p95 | 235/265 ms | 250/296 ms |
| Cold-live latency | N/A (N=0) | N/A (N=0) |
| Estimated cost per successful task | N/A | N/A |

- Fault Recovery Success: 6/8.
- Average fault recovery stages: 1.0.
- Average fault retries: 0.75.
- Retrieval Recall@5: 0.90 (36/40 single-relevant-source cases).
- Version-filter accuracy: 0.925 (37/40).

All cases used frozen offline synthetic inputs with network policy `offline` and
no paid calls. Resume-authoritative Task Success, First-pass, Recovery,
Recall@5, retries, tokens, latency, and cost are all **N/A**. No further complete
run is authorized.
