# RAG Validation Task 9 Offline Assembly Preflight

This preflight implements only the deterministic assembly boundary for the
final Validation package. It does not run providers, read credentials,
materialize datasets, or create either source baseline.

## Required source inputs

Assembly requires both of these exact inputs once the real runs exist:

1. `evaluations/experiments/<retrieval-experiment-id>/` containing a sealed
   `retrieval_benchmark` package with exactly 40 ordered real Validation cases.
   The handoff must include the absolute package path and the full SHA-256 of
   its `artifact-manifest.json`.
2. `evaluations/experiments/<citation-experiment-id>/` containing a sealed
   `citation_baseline` package with exactly 20 ordered real Validation cases.
   The handoff must include the absolute package path and the full SHA-256 of
   its `artifact-manifest.json`.

The Citation source may use the preserved `human_review` method or the separate
`llm_as_judge_single_pass` method. An automated source must explicitly declare
`evaluation_method=llm_as_judge_single_pass`, pass its automated authority verifier, and
retain that method in the combined manifest, report, and resume evidence. Task 9
never relabels an automated source as human-reviewed.

The source packages must pass their ordinary seal/hash verifier and a new
offline recomputation. The recomputed `case-metrics.jsonl`, `aggregate.json`,
and `confidence-intervals.json` must be byte-identical to the sealed canonical
data projections. The combined package uses the newly recomputed `report.md`
and `resume-evidence.md`, so it never treats copied source prose as authority.
A package that merely has a valid seal is not enough.

## Compatibility contract

The assembler requires:

- 40 retrieval and 20 citation case IDs, ordered and unique within each track,
  with no cross-track overlap;
- matching dataset ID, dataset version, selected `validation` split, clean Git
  state, and Git SHA;
- a track dataset fingerprint, corpus hash, resolved-config hash, chunk-hash
  authority, non-empty metric versions, and exact model versions;
- failures represented by sanitized stable `reason_code` values;
- an explicit Citation evaluation method preserved through recomputation and
  assembly;
- `data_kind=real` for both inputs before a publishable package can be created.

Corpus, config, metric, interval, latency, and failure authorities stay
track-specific. The final report never averages retrieval and citation metrics
into a composite score. Each track report is copied only after offline
recomputation proves that it matches its sealed source. Each combined resume
claim records the source package manifest hash prefix.

For `llm_as_judge_single_pass`, recomputation also requires a judge snapshot distinct from
the generation snapshot, complete single-pass provenance, frozen
rubric/prompt/Gold/output hashes, zero unresolved automated failures, and
prominent same-model repeatability and Gold Evidence limitations. Automated
prose that implies human review is an integrity failure.

## Outputs and commands

`python -m paper_agent.cli validation-package preflight` validates both inputs
and prints their exact manifest paths and hashes. `validation-package assemble`
creates `artifact-manifest.json`, `report.md`, and `resume-evidence.md` and
seals the manifest last. `validation-package verify` checks the combined
projection lengths and hashes.

`--fixture-dry-run` is restricted to synthetic inputs and produces an
explicitly non-publishable `validation_fixture_dry_run` package whose resume
file contains no numeric claims. It cannot be used with real inputs.

## Current blocker

This worktree contains no `evaluations/experiments/` directory, so neither real
source path nor source manifest hash is available. No final Validation seal or
resume metric has been created. Once the two handoffs above are available, the
preflight and assembly commands require no provider or credential access.
