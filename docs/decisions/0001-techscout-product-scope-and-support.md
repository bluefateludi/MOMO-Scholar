# ADR 0001: MOMO TechScout product scope and V1 support matrix

- Status: Accepted
- Date: 2026-08-09
- Decision owners: MOMO TechScout maintainers
- Supersedes: nothing
- Related plan: `docs/superpowers/plans/2026-08-09-momo-techscout-production-refactor.md`

## Context

MOMO Scholar remains attributable to its historical implementation and results. The TechScout refactor needs a new product authority without rewriting that history, deleting paper features early, or moving the work to a second repository.

MOMO TechScout helps Python AI application developers compare open-source components using frozen or live official/GitHub evidence, trusted local verification recipes, deterministic gates, and bounded recovery. A recommendation is valid only when the available evidence and verification cover the request's hard constraints. Otherwise the product returns an explicit limited result or `no safe winner`.

## Decision

We will evolve this repository into MOMO TechScout while preserving the Scholar closeout baseline identified by commit `4b1cdf5d46a4977c1963b765023b489f3104c178`. Recording the identifier here does not assert that a release tag has already been created; the tag remains a migration precondition before the default product is replaced.

V1 fully supports exactly one component family: Python vector stores used by a local RAG application. “Fully supports” means that TechScout may research the candidate, run only a reviewed allowlisted PoC recipe, apply deterministic gates, and recommend or reject the candidate. It does not mean production-scale performance certification.

Unknown installation commands are never generated or executed. A candidate without a trusted recipe remains research-only. Research-only candidates can appear in the evidence matrix, but cannot become a critical recommendation on the strength of an unverified inference.

## V1 support matrix

| Component family or candidate | Research | Allowlisted PoC | Recommendation eligibility | V1 disposition |
|---|---|---|---|---|
| Python vector stores for local RAG | Official/GitHub frozen or bounded live sources | Only reviewed candidate recipes | Yes, when every hard constraint and gate is satisfied | Fully supported family |
| Chroma | Yes | Yes: local persistence, create/upsert/query/filter contract checks | Yes | Supported |
| Qdrant Local | Yes | Yes: local persistence, create/upsert/query/filter contract checks | Yes | Supported |
| pgvector without a trusted PostgreSQL fixture | Yes | No | No | Research-only |
| pgvector with a future trusted PostgreSQL fixture | Yes | Not part of this decision | Not part of this decision | Requires a later ADR and fixture review |
| Other component families or candidates without a trusted recipe | Evidence may be collected when safe | No | No | Research-only or out of V1 scope |

The PoCs verify small contract behavior: installation/import, resolved version, create/upsert/query/filter, and persistence where supported. They are not throughput or production-readiness benchmarks.

## Terminal and recovery policy

A run ends as `completed`, `completed_with_limitations`, or `failed`. Insufficient evidence produces `no safe winner`; it never causes a fabricated recommendation. Docker unavailability and unsupported recipes produce a bounded research-only result.

Recovery is a contract bound, not a measured success claim: at most one recovery attempt may repeat only the failed stage. The original failed trace remains immutable and the recovery trace links to its checkpoint. Exhausted recovery publishes an honest limited result or fails safely.

## Frozen fixture policy

Ordinary development uses exactly three synthetic, deterministic, offline vertical fixtures:

1. a happy path with supported local-RAG vector stores;
2. a research-only comparison that must return `no safe winner`;
3. a typed PoC failure followed by one local recovery attempt.

These fixtures contain expected contract outcomes, not observations from a live provider, Docker benchmark, user study, production deployment, or final evaluation. Their `observed_metrics` objects remain empty. Fixture integrity is checked outside `tests/techscout/` so later domain-contract tests retain a separate ownership boundary.

## Planning targets, not results

Every quantity below is a **planning target**, not a measured result and not a resume claim:

| Planning target | Intended use |
|---|---|
| Fast mode terminal artifact within 120 seconds on a prewarmed benchmark case | Acceptance planning target |
| Live mode terminal or limited artifact within 300 seconds | Runtime budget planning target |
| Three frozen vertical smoke tasks during ordinary development | Release-gate planning target |
| Twelve end-to-end tasks, forty offline retrieval/version-filter cases, and eight injected recovery scenarios | One-time final evaluation planning targets after the vertical slice is stable |

Resume or portfolio statements may use only automatically projected measurements from a sealed final evaluation package. Scholar metrics remain Scholar metrics and must not be relabeled as TechScout results.

## Consequences

- Existing Scholar code, imports, artifacts, and history stay intact until the TechScout vertical slice passes its gates.
- Chroma and Qdrant Local may cross the PoC boundary; pgvector cannot do so without a reviewed PostgreSQL fixture.
- The three frozen tasks provide stable inputs for future contracts and Agent smoke tests without introducing live network, provider, or Docker dependencies into ordinary tests.
- Adding a fully supported family, promoting a research-only candidate, or changing the recovery bound requires an explicit decision update and fixture review.
