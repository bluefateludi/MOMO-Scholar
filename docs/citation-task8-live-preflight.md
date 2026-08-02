# Citation Task 8: 20-Case Live-Generation Preflight

This runbook is the launch authority for the 20-case Citation generation only.
It does not authorize provider calls or spend. Run every command from a clean
worktree at the latest `origin/master` containing the merged preflight changes.

## Frozen local inputs

The ignored preflight directory is:

```text
evaluations/preflight/citation-task8-20case/
```

It contains the five prepared authorities and the one cumulative campaign
ledger. The ledger was created from all three historical smoke ledgers and
accounts for 9 sends, 8,137 prompt tokens, 9,468 completion tokens, and
USD 0.03450675 before a new transmission is permitted. That legacy estimate
is retained as USD authority and is never added to the CNY launch budget.

The prepared-authority SHA-256 values are:

| Authority | SHA-256 |
|---|---|
| `dataset-manifest.json` | `e7bd8c5a77e6711f13d71a6cd28f4310d67bb26667ca8c11bd702ef9c68b86e8` |
| `corpus-manifest.json` | `57eb568e691e5fe046df8370aa0b8b421cc8ad1afc885c623e1380a268c78d94` |
| `gold-judgments.jsonl` | `d0634916de72a91cf6857a1a769d9ee878f8b000bb32225d86901de28d2cdc74` |
| `prepared-cases.jsonl` | `65bc40701aefa485e2106c74caaa8a7c7b5c19e02fdfd57d6fc0a4f7efb3aa96` |
| `resolved-config.json` | `2b60ba007b757a95725015f5d73b2ceaca4f227e47a0836eb517b5202de03bba` |
| `campaign-ledger.jsonl` (initial 9-send state) | `e1863d127b0371aeae5fd9b51976f6f39c2cdfd9bf24c3e548660ddf38fcbcf3` |

The dataset has exactly 20 ordered, unique, real Validation cases: 10 SciFact
and 10 QASPER. Every case has a non-empty question and chunk, and the Gold file
has exactly one row for each selected case.

## Required provider authority

The frozen request and expected response model is
`qwen3.7-plus-2026-05-26`. Official Alibaba Cloud documentation records the
mutable `qwen3.7-plus` alias as currently equivalent to that snapshot.

Before launch, an approver must place `provider-model-authority.json` and its
two captured provider documents beside the prepared authorities. The JSON must
match this exact contract; placeholders must be replaced with facts supported
by the captured official provider documents:

```json
{
  "schema_version": "1.0",
  "provider": "dashscope",
  "request_model": "qwen3.7-plus-2026-05-26",
  "expected_response_model": "qwen3.7-plus-2026-05-26",
  "identifier_kind": "dated_immutable",
  "deployment_scope": "China (Beijing)",
  "generation_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "deployment_authority_file": "beijing-endpoint-attestation.json",
  "deployment_authority_sha256": "<lowercase SHA-256>",
  "model_document_url": "<official HTTPS provider URL without query or fragment>",
  "model_document_retrieved_at_utc": "<YYYY-MM-DDTHH:MM:SSZ>",
  "model_document_file": "<adjacent captured model document filename>",
  "model_document_sha256": "<lowercase SHA-256>",
  "pricing_document_url": "<official HTTPS provider URL without query or fragment>",
  "pricing_document_retrieved_at_utc": "<YYYY-MM-DDTHH:MM:SSZ>",
  "pricing_document_file": "<adjacent captured pricing document filename>",
  "pricing_document_sha256": "<lowercase SHA-256>",
  "pricing_currency": "CNY",
  "input_cost_per_million_tokens": 2.0,
  "output_cost_per_million_tokens": 8.0,
  "approved_by": "<stable reviewer pseudonym>",
  "approved_at_utc": "<YYYY-MM-DDTHH:MM:SSZ>"
}
```

The rates are the standard China (Beijing), up-to-256K rates; promotional
pricing is excluded. The preflight rejects mutable aliases,
changed snapshot bytes, unsafe URLs or paths, secret-like material, and any
model or pricing mismatch.

## Proposed authorization ceilings

Subject to confirmation of the rates above, the conservative proposal is:

- 31 cumulative campaign sends: 9 already used plus 20 primary sends and only
  2 retry-or-repair sends across the batch;
- at most 2 sends for any case in this execution;
- 60 seconds per provider attempt and 1,024 maximum completion tokens;
- 32,768 prompt-token upper bound per send;
- 729,033 cumulative prompt tokens and 31,996 cumulative completion tokens,
  both including the prior 9 sends;
- CNY 0.073728 maximum authorized cost per new send;
- CNY 1.622016 maximum for 22 new sends. The prior USD 0.03450675 remains a
  separate legacy estimate and is not converted or added.

These are hard ceilings, not estimates. A reservation is written before the
provider transport is called. Unknown or interrupted usage remains charged at
its authorized ceiling. The campaign ledger counts transport retries and JSON
repair requests as sends.

## Launch checklist

1. Update to the latest `origin/master`; verify `git status --short` is empty.
2. Verify the five authority hashes and initial campaign-ledger hash above.
3. Verify the provider authority and both captured document hashes; confirm the
   request and expected response IDs are dated and documented as immutable.
4. Confirm the standard Beijing CNY rates and the separate legacy USD record.
5. Confirm the user explicitly approves: provider/model, exact 20 cases,
   60-second timeout, 31 cumulative sends, 2 sends per case, token ceilings,
   and CNY 1.622016 new-send cost.
6. Set `DASHSCOPE_API_KEY` only in the process environment. Do not put it under
   `evaluations/` or in command-line arguments.
7. Choose one new execution ID and matching output directory using the clean
   Git SHA, then run the offline preflight command below.
8. Inspect the PASS line. Do not launch if preflight exits nonzero or if any
   authority, Git SHA, path, ledger, token, or cost value differs.
9. Only after all approvals, repeat the command as `run-live-generation` and
   append `--acknowledge-provider-costs`.

## Exact offline preflight and launch commands

Replace `<git-short>` once, using the short SHA of the clean merged
`origin/master`. This command does not read credentials or construct a provider.

```powershell
python -m paper_agent.cli citation-baseline preflight-live-generation `
  --prepared evaluations/preflight/citation-task8-20case `
  --output evaluations/experiments/citation-task8-20case-<git-short>-live `
  --model-authority evaluations/preflight/citation-task8-20case/provider-model-authority.json `
  --campaign-ledger evaluations/preflight/citation-task8-20case/campaign-ledger.jsonl `
  --campaign-id citation-task8-2026-08 `
  --execution-id citation-task8-20case-<git-short>-live `
  --case-limit 20 `
  --max-tokens 1024 `
  --attempt-timeout-seconds 60 `
  --max-sends-per-case 2 `
  --max-total-sends 31 `
  --max-prompt-tokens-per-send 32768 `
  --max-total-prompt-tokens 729033 `
  --max-total-completion-tokens 31996 `
  --max-cost 1.622016
```

The paid launch uses the identical arguments, changes only the command name to
`run-live-generation`, and adds `--acknowledge-provider-costs`. Any other
argument change invalidates the approval and requires a new offline preflight.

## Artifacts, interruption, and resume

The output directory contains copied prepared/model authorities plus:

```text
generation-config.json
run-state.json
provider-sends.jsonl
generation-drafts.jsonl
case-results.jsonl
pipeline-outputs.jsonl
evidence.jsonl
failures.jsonl
logs.jsonl
traces.jsonl
generation-manifest.json
```

`campaign-ledger.jsonl` remains the sole cumulative budget authority; the
output `provider-sends.jsonl` is the execution-only projection.

On timeout, interruption, or failure, preserve both directories. Resume with
the byte-identical command, execution ID, output path, Git SHA, authorities,
and campaign ledger. Completed cases are skipped, and a persisted validated
generation draft is post-processed without another send. A reserved send with
unknown outcome remains fully accounted. Never delete or edit ledger rows to
recover budget.

If Git, model authority, pricing, prepared authorities, or generation config
must change, do not reuse the output. Obtain a new approval, select a new
execution ID/output directory, and keep using the same cumulative campaign
ledger so prior sends and spend remain counted.

After generation completes, freeze and review the output before using the
existing offline `export-review`, `import-review`, `score`, `recompute`, and
`verify` commands. No generated result is resume-ready evidence until the
complete review and sealing workflow succeeds.
