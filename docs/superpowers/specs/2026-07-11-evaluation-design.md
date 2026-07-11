# MOMO Scholar Evaluation Design

## Purpose

MOMO Scholar needs an independent evaluation module that can detect regressions in
paper retrieval, evidence attachment, unsupported claims, and citation integrity.
The first version must be deterministic, offline, and isolated from the pipeline.

This design uses a layered evaluation strategy:

1. deterministic offline regression metrics;
2. a future public scientific-retrieval benchmark;
3. a future semantic trustworthiness evaluation based primarily on human labels,
   with LLM judges used only as auxiliary evaluators.

Only the first layer is implemented in this task. The JSON case format and module
boundaries leave room for the later layers without introducing their dependencies.

## Scope

### In scope

- Four deterministic metrics:
  - `retrieval_hit_rate`
  - `evidence_coverage`
  - `unsupported_claim_rate`
  - `citation_validity`
- Pure metric functions with no external I/O.
- A runner that evaluates typed run artifacts and versioned JSON fixtures.
- Per-case results and macro-averaged summaries returned as ordinary dictionaries.
- Deterministic fixtures and focused offline tests.
- User-facing metric and limitation documentation.

### Out of scope

- Pipeline integration.
- Database persistence or repository abstractions.
- Online dataset downloads.
- LLM-as-a-judge evaluation.
- Human annotation tooling.
- HTML reports.
- Vector retrieval, reranking, or retrieval changes.
- A combined overall quality score.

The implementation must not modify `paper_agent/pipeline.py`,
`paper_agent/config.py`, `paper_agent/schemas.py`,
`paper_agent/evidence/retriever.py`, `pyproject.toml`, or `README.md`.

## Evaluation Architecture

The three evaluation layers have separate purposes.

### Layer 1: deterministic offline regression

Layer 1 runs on fixed JSON cases and current run artifacts. It evaluates structural
and referential contracts without network access, models, databases, clocks, or
randomness. It is suitable for unit tests, CI, and local regression checks.

This layer does not establish that evidence semantically entails a claim. It only
measures reference-paper recall, evidence attachment, unsupported-status frequency,
and whether cited evidence identifiers exist in the current evidence collection.

### Layer 2: public retrieval benchmark

A later task may convert a licensed subset of a public scientific retrieval dataset
into MOMO Scholar's JSON format. Converted cases will be pinned and stored locally;
normal tests will never download benchmark data at runtime.

Potential future metrics include Precision@K, Recall@K, MRR, and nDCG@K. Dataset
selection, licensing review, conversion, and those additional metrics are not part
of this task.

### Layer 3: semantic trustworthiness

A later task may add human-labeled reference claims and supporting passages to
measure claim-evidence entailment, answer correctness, completeness, relevance, and
overstatement. Human labels are the primary reference. LLM judges may assist, but
must be calibrated against human-labeled examples and kept out of the deterministic
default test suite.

## Components

### `paper_agent/eval/metrics.py`

Contains four side-effect-free metric functions. The functions accept ordinary
collections and existing `ReportClaim` or `Evidence` models. They do not read files,
perform validation unrelated to their metric, round results, or know how their
inputs were stored.

### `paper_agent/eval/runner.py`

Provides two entry points:

```python
evaluate_case(
    *,
    expected_paper_ids: list[str],
    actual_paper_ids: list[str],
    claims: list[ReportClaim],
    evidence: list[Evidence],
) -> dict[str, float]
```

```python
evaluate_fixture(path: str | Path) -> dict[str, object]
```

`evaluate_case` contains no file I/O. `evaluate_fixture` reads JSON, validates the
case structure, constructs existing Pydantic models, invokes `evaluate_case`, and
returns per-case and summary results.

The runner returns ordinary dictionaries rather than `EvalSummary`. This avoids
modifying or expanding the shared schema module and keeps the evaluation result
format local to the evaluation package.

### `tests/fixtures/eval_cases.json`

Contains a small, human-reviewable contract dataset. Each case includes both the
expected retrieval target and deterministic simulated run artifacts. It is not
presented as a complete public benchmark.

## JSON Case Contract

The fixture top level is a list of cases. Each case has the following shape:

```json
{
  "case_id": "partial-retrieval",
  "query": "retrieval augmented generation evaluation",
  "expected_paper_ids": [
    "arxiv:paper-001",
    "arxiv:paper-002"
  ],
  "actual_paper_ids": [
    "arxiv:paper-001",
    "arxiv:paper-999"
  ],
  "claims": [
    {
      "claim": "RAG evaluation should assess retrieval and generation separately.",
      "evidence_ids": ["run-a:ev_001"],
      "support_status": "supported"
    }
  ],
  "evidence": [
    {
      "evidence_id": "run-a:ev_001",
      "paper_id": "arxiv:paper-001",
      "chunk_id": "arxiv:paper-001:chunk:001",
      "claim_type": "retrieved",
      "quote": "Retrieval and generation require separate evaluation.",
      "relevance_score": 0.95
    }
  ]
}
```

`case_id`, `expected_paper_ids`, `actual_paper_ids`, `claims`, and `evidence` are
required. `query` is optional, is retained only as case provenance and
human-readable context when present, and is ignored by the first four metrics.

Before constructing Pydantic models, the fixture reader verifies that `case_id` is
a non-empty string; `expected_paper_ids` and `actual_paper_ids` are lists containing
only strings; and `claims` and `evidence` are lists. It does not silently coerce
these non-Pydantic fixture fields into the required types.

The fixture reader raises `ValueError` for a non-list top level, missing required
fields, invalid non-Pydantic field types, duplicate case IDs, or data that cannot be
constructed as the existing `ReportClaim` and `Evidence` models. Error messages
identify the case and invalid field when that information is available.

## Metric Definitions

All metric functions return a `float` in the inclusive range `[0.0, 1.0]`.

### `retrieval_hit_rate`

Let `A` be the set of actual paper IDs and `E` the set of expected paper IDs:

```text
retrieval_hit_rate = |A intersection E| / |E|
```

Rules:

- Return `0.0` when `E` is empty.
- Return `0.0` when actual IDs are empty and expected IDs are not empty.
- Deduplicate both actual and expected IDs before calculation.
- Match IDs as exact strings; do not normalize case or source prefixes.
- Unrelated retrieved papers do not reduce this metric.

This is reference-paper recall, not precision. It must not be described as a
complete retrieval-quality score.

### `evidence_coverage`

```text
evidence_coverage =
    claims with non-empty evidence_ids / total claims
```

Rules:

- Return `0.0` when there are no claims.
- Count a claim as covered when its `evidence_ids` list is non-empty.
- Do not check whether those IDs exist; that is the responsibility of
  `citation_validity`.

### `unsupported_claim_rate`

```text
unsupported_claim_rate =
    claims whose support_status is "unsupported" / total claims
```

Rules:

- Return `0.0` when there are no claims.
- Count only the exact status `unsupported`.
- Do not count `supported` or `weakly_supported`.
- This is a negative-direction metric: lower is better.

### `citation_validity`

Let `V` be the set of evidence IDs in the current evidence collection. Let `C` be
the ordered multiset formed by concatenating every claim's `evidence_ids` list:

```text
citation_validity =
    citation occurrences in C whose ID belongs to V / total occurrences in C
```

Rules:

- Return `0.0` when there are no citation occurrences.
- Return `0.0` when citations exist but the evidence collection is empty.
- Count duplicate citations by occurrence, including repeated IDs in one claim or
  across multiple claims.
- Determine validity only by membership in the current evidence-ID set.
- Do not infer semantic support from identifier validity.
- `evaluate_case` rejects duplicate `Evidence.evidence_id` values to match the
  existing citation-checker contract. Because `evaluate_fixture` delegates every
  case to `evaluate_case`, direct and fixture-based evaluation have identical
  duplicate-ID behavior.

## Result Contract

`evaluate_case` returns:

```json
{
  "retrieval_hit_rate": 0.5,
  "evidence_coverage": 1.0,
  "unsupported_claim_rate": 0.5,
  "citation_validity": 0.5
}
```

Metric functions and `evaluate_case` do not round results.

`evaluate_fixture` returns:

```json
{
  "cases": [
    {
      "case_id": "partial-retrieval",
      "metrics": {
        "retrieval_hit_rate": 0.5,
        "evidence_coverage": 1.0,
        "unsupported_claim_rate": 0.5,
        "citation_validity": 0.5
      }
    }
  ],
  "summary": {
    "case_count": 1,
    "retrieval_hit_rate": 0.5,
    "evidence_coverage": 1.0,
    "unsupported_claim_rate": 0.5,
    "citation_validity": 0.5
  }
}
```

Each summary metric is the macro average of that metric across cases. Every case
therefore has equal weight regardless of its number of claims or citations. No
single combined quality score is produced because `unsupported_claim_rate` has the
opposite direction from the other metrics and because the metrics measure different
contracts.

For an empty fixture, the result contains an empty `cases` list and a summary with
`case_count` equal to zero and every metric equal to `0.0`.

## Testing Strategy

Implementation follows strict test-driven development. Each behavior receives a
focused failing test that fails for the expected missing behavior before the
smallest implementation is added.

### Metric tests

Tests cover:

- complete, partial, and zero retrieval hits;
- empty expected paper IDs;
- duplicate actual and expected paper IDs;
- empty claims;
- all claims with evidence;
- partially unsupported claims;
- `weakly_supported` claims not counted as unsupported;
- all-valid, partially valid, and all-invalid citations;
- no citations;
- duplicate citations counted by occurrence;
- every result remaining in `[0.0, 1.0]`.

### Runner tests

Tests cover:

- deterministic fixture loading;
- per-case metrics and macro averages;
- empty fixture behavior;
- identical results on repeated execution;
- duplicate case IDs;
- duplicate evidence IDs;
- malformed top-level JSON structure;
- missing or invalid fields and existing-schema validation failures.

Normal tests must not access the network, a model API, a database, the clock, or
randomness.

## Documentation

`docs/evaluation.md` documents the formulas, metric directions, empty-input rules,
duplicate semantics, JSON usage, and limitations. It explicitly states that v1
does not measure semantic entailment, answer correctness, or overall RAG quality.
It also records the Layer 2 and Layer 3 roadmap.

## Files

The task may create or modify only:

- `paper_agent/eval/__init__.py`
- `paper_agent/eval/metrics.py`
- `paper_agent/eval/runner.py`
- `tests/fixtures/eval_cases.json`
- `tests/test_eval_metrics.py`
- `tests/test_eval_runner.py`
- `docs/evaluation.md`
- `docs/superpowers/specs/2026-07-11-evaluation-design.md`
- `docs/superpowers/plans/2026-07-11-evaluation.md`

## Verification

The implementation is complete only after checking the output of:

```powershell
python -m pytest tests/test_eval_metrics.py tests/test_eval_runner.py -q
python -m pytest -q
git diff --check
git status --short --branch
```

The baseline before this work is `36 passed in 0.81s` on branch
`codex/evaluation-control` in the independent `evaluation-control` worktree.

No files are staged, committed, pushed, merged, or submitted as a pull request
without explicit user authorization.
