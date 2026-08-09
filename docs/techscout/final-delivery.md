# Final evaluation and browser acceptance skeleton

This file is the single fill-in site for MOMO TechScout final measurements. At baseline `b7516a7b478834614f6ce2ccf1ae63a5c73c3140`, the evaluation runner and package contracts exist, but no supplied final Eval or Browser authority has been verified in this worktree.

Planning targets, synthetic fixtures, unit-test counts, historical Scholar results, and manual impressions are not substitutes for final authority.

## Evaluation authority

| Claim | Final value | Required evidence |
|---|---|---|
| Suite identity, profile, resolved configuration, environment, and case-set fingerprint | `PENDING_FINAL_AUTHORITY` | Verified sealed manifest and referenced artifacts |
| V0/V1 Task Success | `PENDING_FINAL_AUTHORITY` | Case-level records plus generated summary; same TechScout tasks/tools/model/frozen inputs |
| V0/V1 First-pass Success | `PENDING_FINAL_AUTHORITY` | Case-level recovery flags and summary |
| Retrieval Recall@5 and version-filter accuracy | `PENDING_FINAL_AUTHORITY` | Offline retrieval records and summary |
| Fault Recovery Success and average recovery stages | `PENDING_FINAL_AUTHORITY` | Injected-fault records with checkpoint-linked outcomes |
| Cold-live latency p50/p95 | `PENDING_FINAL_AUTHORITY` | Cold-live observations only |
| Warm-cache latency p50/p95 | `PENDING_FINAL_AUTHORITY` | Warm-cache observations only; never pooled with cold-live |
| Tool schema/execution success | `PENDING_FINAL_AUTHORITY` | Case-level tool observations |
| Tokens and estimated cost per successful task | `PENDING_FINAL_AUTHORITY` | Provider usage records and pricing/method authority |
| Final package path, manifest SHA-256, and verification result | `PENDING_FINAL_AUTHORITY` | Offline package verification output |

V0 must be the TechScout baseline with the same core model/tools and frozen inputs but without the explicitly named V1 Harness capabilities. MOMO Scholar is not V0. If infrastructure partially fails, preserve the original failure and partial records; do not tune or rerun merely to improve headline values.

## Browser and product acceptance authority

| Claim | Final value | Required evidence |
|---|---|---|
| Browser authority baseline commit/build | `PENDING_FINAL_AUTHORITY` | Exact commit and production build artifact |
| Fast Demo terminal acceptance | `PENDING_FINAL_AUTHORITY` | Timestamped run records and terminal artifacts with synthetic/live boundary stated |
| Verified/Live terminal or limited behavior | `PENDING_FINAL_AUTHORITY` | Authorized run records; missing credentials must remain a limitation |
| Desktop browser smoke | `PENDING_FINAL_AUTHORITY` | Browser authority, viewport, console/network observations, and screenshots if supplied |
| Narrow browser smoke | `PENDING_FINAL_AUTHORITY` | Browser authority, viewport, overflow/accessibility observations, and screenshots if supplied |
| Report/candidate/evidence/recovery/Trace navigation | `PENDING_FINAL_AUTHORITY` | Browser flow record tied to the same build |
| Artifact downloads and content types | `PENDING_FINAL_AUTHORITY` | API/browser observations and allowlisted artifact inventory |
| Final browser authority path/hash | `PENDING_FINAL_AUTHORITY` | Immutable record plus verifier/checksum |

## Required two-axis fact check before filling

### Axis A — implementation and standards

- Confirm every README command exists and runs from a clean checkout.
- Confirm Fast, Verified/Live, and Offline labels match the actual executor and UI.
- Confirm Chroma/Qdrant are the only reviewed V1 recipes and pgvector remains research-only.
- Confirm the deterministic gate, terminal statuses, recovery bound, security controls, and artifact/Trace authority match code.
- Confirm no secret, absolute host path, raw provider body, unbounded output, or ignored local evaluation content entered tracked docs.

### Axis B — specification and claim provenance

- Verify the final package seal and every referenced hash before copying a number.
- Trace every headline value back to generated summary and case-level records.
- Keep cold-live and warm-cache latency separate.
- Keep synthetic fixture acceptance separate from live evaluation.
- Keep Scholar metrics separate from TechScout metrics.
- Publish missed targets and limitations unchanged; do not estimate or backfill missing denominators.
- Update the four resume drafts only with values projected from the same verified final authority.

## Fill procedure

1. Receive the exact Eval and Browser authority paths/hashes from the integration owner.
2. Verify them offline and record the verification commands/results.
3. Replace each applicable `PENDING_FINAL_AUTHORITY` with an exact value, denominator, method label, authority path, and hash. Leave unavailable claims pending or explicitly unavailable.
4. Perform both fact-check axes against the final diff.
5. Confirm no accidental placeholders remain outside deliberately unavailable claims:

```powershell
rg -n "PENDING_FINAL_AUTHORITY" README.md docs/techscout
```

6. Only then prepare the scoped documentation commit and Draft PR requested by the integration owner.
