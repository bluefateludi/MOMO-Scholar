# MOMO TechScout final evaluation authority

The original run is permanently retained as `FAILED_PRECHECK_AUTHORITY`. It
produced zero authoritative observations because a frozen-data authoring defect
duplicated one hard constraint. This was not a model or infrastructure result.

One transparent amended run was authorized after deleting only that duplicate.
No model, threshold, expected outcome, runner behavior, or other fixture changed.

- Amended N: `12 E2E tasks / 24 V0+V1 observations, 40 retrieval, 8 fault`
- V0 Task Success / First-pass: `12/12 / 12/12`
- V1 Task Success / First-pass: `12/12 / 12/12`
- Fault Recovery Success: `6/8`
- Retrieval Recall@5 / version-filter accuracy: `0.9 / 0.925`
- V0 warm-cache p50/p95 ms: `235/265`
- V1 warm-cache p50/p95 ms: `250/296`
- Cold-live latency: `N/A (N=0; live network prohibited)`
- V0/V1 prompt tokens per successful task: `900.0/900.0`
- Estimated cost per successful task: `N/A`

No further full rerun is authorized.
