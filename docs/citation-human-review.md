# Citation 20-Case Human Review Runbook

This runbook makes the human calibration and assertion-level Citation review
repeatable offline. It does not authorize generation, perform a judgment, or
permit scoring before the real 20-case generation authorities are complete and
frozen.

## Current repository state

A clean clone does not contain the real 20 selected Citation cases, their Gold
Evidence, or a frozen 20-case generation directory. Those files are intentionally
ignored under `evaluations/`. Consequently, repository tests can validate the
contracts and workflow, but cannot audit the content of the actual 20 cases or
produce real metrics.

The minimum human input needed after generation freezes is exactly:

1. two distinct stable reviewer pseudonyms; and
2. one stable adjudicator pseudonym.

Use lowercase letters and digits separated only by `-` or `_`. Do not put names,
emails, usernames, or other real identity fields in any review artifact. The
adjudicator may be one of the reviewers only if the study owner explicitly accepts
that independence limitation; a third pseudonym is still required as the recorded
adjudicator role.

## Frozen inputs and 20-case audit

Before creating assignments, verify all of the following without a provider:

- `generation-manifest.json` says `completed`, has exactly 20 ordered, unique
  `selected_case_ids`, and has no failed case IDs;
- `case-results.jsonl`, `pipeline-outputs.jsonl`, and `evidence.jsonl` each cover
  the same 20 IDs in the frozen order, with non-null per-case output and Evidence
  hashes;
- `dataset-manifest.json` says `data_kind=real`, and the 20 IDs are the disjoint
  Citation selection defined in `evaluations/DATASETS.md`;
- every Gold Evidence record is copied from the authorized `EvalCase.reference`,
  retains upstream source/provenance and locator, and resolves to the same case and
  paper as the evaluated assertion;
- normalization produces stable, globally unique assertion and citation-occurrence
  IDs, preserves assertion text and offsets, and rejects duplicate or dangling IDs;
- every review item binds the assertion, cited passages, rubric/config version, and
  output/Evidence/config hashes; and
- the calibration assertion IDs and answer key are fixed before either reviewer
  receives a packet. Calibration items are double-reviewed and excluded from
  reported semantic metrics.

Do not use `score`, `recompute`, or `verify` during this gate. A missing, partial,
unfrozen, synthetic, or failed generation is a blocker, never a zero score.

## Rubric and assertion-level response

The frozen `citation-support-v1` rubric has three verdicts:

- `supported`: cited Evidence entails the complete atomic assertion;
- `unsupported`: no cited Evidence entails the complete assertion; and
- `ambiguous`: support is partial or cannot be decided from available context.

Reason codes are frozen in `paper_agent.eval.citation_baseline.review`. Ambiguous
responses require notes. Unsupported responses cannot claim supporting match IDs.
Every imported response must retain its assignment ID/hash, reviewer pseudonym,
rubric and calibration versions, three authority hashes, and review timestamp.

The committed empty calibration template is
`evaluations/templates/citation-calibration-bundle.template.json`. Copy it only
into the ignored experiment workspace after generation freezes. Populate the
authority hashes, the two reviewer pseudonyms, adjudicator pseudonym, fixed
calibration assertion IDs, and independently frozen expected answers. Do not put
expected answers in reviewer packets.

## Blind export and resumable import

Prepare the Pipeline-derived review authorities first. `prepare` validates the
frozen assignment registry and creates an empty `judgments.jsonl`; it does not
score anything.

For each reviewer, export a separate context packet and import-shaped response
template:

```text
python -m paper_agent.cli citation-baseline export-review --prepared <prepared> --output <reviewer-packet.jsonl> --reviewer-pseudonym <reviewer-pseudonym>
python -m paper_agent.cli citation-baseline export-review-template --prepared <prepared> --output <reviewer-responses.jsonl> --reviewer-pseudonym <reviewer-pseudonym>
```

The packet exposes only blinded case IDs, stable assertion/citation IDs, cited
passages and necessary provenance, rubric, calibration flag, and frozen hashes.
It omits private case and run IDs. Do not distribute an unfiltered aggregate
packet when reviewer separation is intended.

In the response template, replace every `__REQUIRED__` marker with an allowed
verdict/reason and every `__REQUIRED_ISO_8601_UTC__` marker with the actual review
time. Leave unfinished rows out of the import batch; placeholder rows are
intentionally rejected.

Import a completed partial batch offline:

```text
python -m paper_agent.cli citation-baseline import-review --prepared <prepared> --review <completed-batch.jsonl> --output <judgments-001.jsonl>
```

Resume by merging a later batch into the prior canonical judgments:

```text
python -m paper_agent.cli citation-baseline import-review --prepared <prepared> --review <next-completed-batch.jsonl> --existing <judgments-001.jsonl> --output <judgments-002.jsonl>
```

Imports reject malformed JSON, unexpected or missing fields, identity leakage,
unknown assignments, duplicate assignments, changed rubric/version/hash values,
invalid verdict/reason combinations, and attempts to replace an already imported
assignment. Keep each prior file until the next output is verified so progress is
recoverable.

## Calibration and adjudication gates

Both reviewers independently judge every fixed calibration assertion. Build one
`CalibrationRecord` per reviewer and calibration assertion using the frozen
expected verdict and the imported observed verdict. The set must contain exactly
the same two reviewer pseudonyms for every calibration assertion.

Compute raw agreement and Cohen's kappa from original reviewer verdicts. Kappa is
reported as undefined when expected agreement is one. Any reviewer disagreement
must be adjudicated before reported-case review can be scored. Adjudication must:

- use the adjudicator pseudonym;
- reference exactly two distinct original judgments for the same frozen assertion;
- apply only to a real disagreement;
- preserve both original judgments and all authority hashes; and
- use a valid verdict/reason pair, with notes where the verdict requires them.

Never overwrite original judgments with an adjudicated result. Duplicate or
missing calibration records, inconsistent expected answers, changed versions,
unresolved disagreements, or missing reported judgments block scoring.

## Final offline path

Only after calibration is complete, all assigned judgments are imported, and all
disagreements are resolved may the package run:

```text
python -m paper_agent.cli citation-baseline score --prepared <prepared> --judgments <complete-judgments.jsonl> --output <sealed-package>
python -m paper_agent.cli citation-baseline recompute --package <sealed-package> --output <verification-directory>
python -m paper_agent.cli citation-baseline verify <sealed-package>
```

Recompute reads only sealed authorities. Verification requires byte-identical
case metrics, aggregates, confidence intervals, report, and resume projection.
Real results remain unpublished unless the package is real, clean, exactly 20
cases, complete, sealed, and independently recomputed.
