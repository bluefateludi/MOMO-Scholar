# Live Eval V1 preregistration

Live Eval V1 is a bounded 12-case pilot for MOMO TechScout's current vector
store selection scope. Phase 0 freezes the case contract, oracle, rubric, and
authority requirements. It does not run a provider, access the network, start
Docker, or authorize spend.

The existing `final` evaluation remains a sealed synthetic infrastructure
acceptance. Live V1 uses separate contracts and local-only artifacts; it must
not overwrite or reinterpret the synthetic `12/40/8` authority.

## Current blocker discovered during Phase 0

The current Verified composition connects live/cache research and reviewed
Docker PoCs, but planning, reporting, and gate decisions are deterministic
Python stage services. The terminal trace records zero completion tokens. A
Verified run therefore does not yet establish model-backed reasoning authority.

Formal Live V1 execution is blocked until one preflight can independently prove:

1. live research authority and captured source timestamps/hashes;
2. real Docker PoC authority for the reviewed Chroma/Qdrant Local recipes;
3. a real model provider and exact model revision for decision/report stages;
4. provider-reported token usage and a frozen pricing snapshot;
5. a clean baseline commit and an explicit non-zero cost authorization.

Until all five pass, model Task Success, model Token, and model Cost remain
`N/A`. Live-source or Docker-only checks may be reported separately, but cannot
be described as a real-model Live Eval.

## Frozen case composition

The populated registration contains exactly 12 cases and stays under ignored
`evaluations/techscout-live-v1/` storage so the Agent cannot read private
oracles during execution.

| Cases | Category | Required behavior |
|---:|---|---|
| 1-6 | supported recommendation | Recommend only reviewed Chroma/Qdrant Local candidates after required evidence and PoC authority. Mixed pgvector/unknown candidates remain ineligible. |
| 7-10 | safe boundary | Return a limited, insufficient-evidence result for research-only, unknown, production-HA, or forced-evidence-unavailable conditions. |
| 11 | controlled recovery | Recover once from an injected dependency conflict, rerun only the failed PoC stage, and publish only after verification. |
| 12 | recovery exhaustion | Stop after one injected PoC timeout recovery attempt and publish a limited no-safe-winner result without fabricating success. |

Expected business limitations are not expected process crashes. An unhandled
exception, missing final report, or lost trace is a product failure. Evaluator
infrastructure failures are marked invalid and may use at most the separately
declared infrastructure rerun.

## Rubric and hard gates

The preregistered rubric weights outcome/verdict correctness (30%), hard
constraints (25%), claim/evidence support (20%), PoC authority (15%), and
bounded recovery/honest limitations (10%).

Any of the following is a critical failure regardless of weighted score:

- recommending pgvector or an unknown candidate;
- recommending after a required PoC did not pass;
- violating an explicit hard constraint;
- fabricating evidence, execution, trace, or artifacts;
- extrapolating Local-mode verification to Server, Cloud, cluster, or HA.

Report raw counts alongside percentages: terminal/verdict accuracy, critical
eligibility violations, safe-refusal recall, recommendation precision,
hard-constraint safe-decision rate, atomic claim support, verified PoC coverage,
bounded recovery compliance, and per-run latency/token/cost. The planned sample
is 12 cases times two repetitions; it is not statistically generalizable.

## Phase 0 validation

The populated registration is local-only at
`evaluations/techscout-live-v1/registration.json`. Validate it with:

```console
python scripts/validate_techscout_live_eval.py
```

The command only parses strict contracts and prints the registration hash, case
counts, authority requirements, and deny-by-default execution/cost state. It
has no run subcommand and creates no trace or experiment directory.

Before Phase 1, freeze the registration SHA-256, baseline commit, exact
model/provider revision, pricing snapshot, case order seed, timeout, and private
oracle. Product or prompt changes after the first formal run require a new
evaluation version; previous failures remain immutable.

Safe external wording is: “a bounded 12-case Live Eval pilot covering the
current Chroma/Qdrant Local scope and safety behavior for research-only or
unknown candidates.” Do not call it a general component benchmark, production
reliability proof, or evidence that one vector store is universally better.
