# Citation Gold-Grounded LLM-as-Judge Runbook

This is a separate automated semantic-evaluation method. It does not replace,
rename, or populate the Citation human-review contracts. Every automated
authority and projection uses `evaluation_method=llm_as_judge_single_pass`.

## Frozen generation authority

The current real generation input is local-only:

```text
C:\Users\86150\.codex\worktrees\870c\MOMO-Scholar\evaluations\experiments\citation-task8-20case-49e342b-generation-authority
```

Its read-only compatibility facts are:

- 20 ordered unique real Validation cases, all completed;
- generation model `qwen3.7-plus-2026-05-26`;
- `pipeline-outputs.jsonl` SHA-256
  `05ad82a7ad2dcb27900bb82877f07f09ed556a1092128cbeab7744f3275a0541`;
- generation-authority package-manifest SHA-256
  `72683899d8db7eadd57c29e462b5c32e3e9e9bc1690361803038ca6df9a8a21d`;
- 20 execution sends, no execution retries, no failed cases; and
- estimated generation usage cost CNY 0.054478 (historical generation cost,
  not automated-judge authorization).

Inspection is read-only. It creates no score:

```powershell
python -c "from pathlib import Path; from paper_agent.eval.citation_baseline.automated_judge import inspect_frozen_generation; print(inspect_frozen_generation(Path(r'<generation-directory>')))"
```

## Required automated judge authority

Do not choose a judge alias by convenience. Before any paid judge command, freeze
one JSON authority accepted by `AutomatedJudgeAuthority`. It must include:

- exact dated judge model/version, different from
  `qwen3.7-plus-2026-05-26`;
- official model authority URL and captured-document SHA-256;
- exact HTTPS endpoint;
- official pricing authority, currency, and input/output rates;
- frozen rubric and prompt versions/hashes;
- the frozen Gold and generation-output hashes;
- temperature zero, timeout, one-or-zero retry per pass, per-send token ceilings;
- cumulative send, prompt-token, completion-token, and cost caps; and
- `data_kind=real` for the real package.

Authority is injectable and mandatory. The repository does not select a judge,
claim a current price, or authorize spend.

## Inputs and deterministic work

Normalize frozen checked outputs into stable atomic assertions and citation
occurrences. Resolve citation links and run deterministic Gold Evidence matching
first. Each `AutomatedJudgeInput` binds stable IDs, blinded case ID, exact
assertion text, cited and Gold passages, output/Evidence/Gold/config hashes, and
any deterministic supporting match IDs.

A deterministic supporting Gold match produces a supported decision without a
judge call. Each unresolved assertion receives one blinded semantic judge pass.
The provider payload does not include private case/run IDs.

For `U` unresolved assertions:

```text
judge passes = U
provider sends <= U * (1 + retries_per_pass)
```

With one permitted retry the maximum is `2U`. Approval must state lower hard
caps when appropriate. Budget exhaustion preserves progress and blocks further
sends.

## Offline preflight and bounded future live command

The preflight reads no credential and makes zero provider calls:

```powershell
python -m paper_agent.cli citation-baseline preflight-automated-judge `
  --generation <frozen-generation-directory> `
  --authority <judge-authority.json> `
  --inputs <automated-judge-inputs.jsonl>
```

Only after an approver accepts the exact authority and printed send/token/cost
caps may the same inputs run with the paid command:

```powershell
python -m paper_agent.cli citation-baseline run-automated-judge `
  --generation <frozen-generation-directory> `
  --authority <judge-authority.json> `
  --inputs <automated-judge-inputs.jsonl> `
  --output <automated-judge-run-directory> `
  --acknowledge-provider-costs
```

The output persists state, inputs, sends, passes, decisions, and sanitized
failures after every operation. Resume uses the byte-identical authority, inputs,
and output directory. Completed passes and decisions are not purchased again;
reserved or unknown sends remain budgeted.

## Score, seal, recompute, verify

After completion, combine the automated files with normalized assertions,
citation occurrences, deterministic matches, dataset/corpus/Gold/config/
environment authorities, and sanitized operation files. Then run offline:

```powershell
python -m paper_agent.cli citation-baseline score-automated --prepared <prepared-automated-directory> --output <sealed-package>
python -m paper_agent.cli citation-baseline recompute-automated --package <sealed-package> --output <verification-directory>
python -m paper_agent.cli citation-baseline verify-automated <sealed-package>
```

The package reports Citation Coverage, Citation Validity, Unsupported Assertion
Rate, denominators, failures, judge latency, and deterministic case-level
bootstrap intervals. Reports label Gold-grounded single-pass LLM-as-Judge.
There is no human review, independent second judge, inter-rater reliability, or
adjudication. Semantic errors and model bias from the single judge remain an
explicit limitation.

Verification rejects method relabeling, missing pass provenance, judge/generator
model collision, changed rubric/prompt/Gold/output hashes, tampering, nonempty
automated failures, synthetic/real relabeling, and wording that represents
automated results as human evaluation.
