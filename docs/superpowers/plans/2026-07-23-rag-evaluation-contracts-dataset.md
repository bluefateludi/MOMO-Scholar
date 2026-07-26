# RAG Evaluation Contracts and Dataset Loader Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build immutable, versioned evaluation gold contracts and a strict offline dataset loader without touching Pipeline execution, scoring, CLI integration, or external providers.

**Architecture:** Gold models live in `paper_agent/eval/contracts.py` behind frozen tuple-backed interfaces. `load_evaluation_dataset` validates and returns one selected split without opening unselected test labels; `audit_evaluation_dataset` performs explicitly authorized multi-split checks. Both are deterministic and perform no writes or network I/O.

**Tech Stack:** Python 3.10+, Pydantic 2, pytest, standard-library `json`, `pathlib`, `hashlib`.

**Specification:** `docs/superpowers/specs/2026-07-23-rag-evaluation-engineering-design.md`

**Baseline:** `origin/master@3f75bfb89574fab1e0379f90b9b96affd7682af1`; `766 passed`.

**Scope:** Delivery Chunk 1 only. Converter, matching, metric, Pipeline adapter, experiment, resume/comparison, semantic, CLI, and curated-baseline work use later plans.

**Git constraint:** Do not stage, commit, push, merge, or create a PR without new explicit user authorization.

---

## Confirmed Seams

Tests exercise only these public interfaces:

1. `DatasetManifest.model_validate` and `EvalCase.model_validate` for immutable gold contracts.
2. `load_evaluation_dataset(root, split=..., allow_test_labels=False)` for selected-split loading.
3. `audit_evaluation_dataset(root, include_test_labels=False)` for explicitly authorized cross-split auditing.

No test reaches private helpers or mocks internal parsing.

## Locked Cross-Plan Decisions

- Internal execution identity is `execution_id`; each evaluation attempt has a distinct `scoring_attempt_id`.
- The external correlation chain remains `experiment_id -> case_id -> run_id -> trace_id -> span_id`.
- Later `EvaluationSystem.run` accepts `EvaluationCorrelation`.
- Fresh execution: `evaluation.case` is the parent span of `pipeline.run`.
- Reused sealed execution: the new `evaluation.case` links to the old Pipeline root with an OTel Span Link and records `reused_execution_id`.
- Every scoring attempt owns a sealed `evaluation-traces.jsonl`; every execution owns a sealed run-level `traces.jsonl`. Sealed files reject appends.
- One `case-result.json` describes one scoring attempt. `cases/<case-id>/canonical.json` atomically selects the baseline result. `trace-index.json` is a projection.
- Resume/rerun tests must cover non-terminal Pipeline state, corrupt run trace, interrupted scoring, failed case-result publication, and explicit `--rerun-corrupt`.
- Every canonical scored case in the final 60-case baseline passes fresh-child or declared-reuse-link structural checks.
- `content_sha256` may be absent only for pure `paper_retrieval`; content-dependent tasks require it.
- Paper retrieval remains a gold task type, but no frozen headline result is implemented until a real paper-ranking SUT exists.
- Cost remains `unscorable` until a versioned currency and pricing contract exists.

## File Map

- Modify `docs/superpowers/specs/2026-07-23-rag-evaluation-engineering-design.md`: manifest matrix, licensing, applicability, correlation, trace authority, recovery, and cost corrections.
- Create `paper_agent/eval/contracts.py`: frozen manifest, provenance, corpus, reference, case, and dataset models.
- Create `paper_agent/eval/dataset.py`: selected-split loader, authorized audit, I/O diagnostics, path safety, and fingerprints.
- Modify `paper_agent/eval/__init__.py`: export stable dataset entry points only.
- Create `tests/eval/__init__.py`.
- Create `tests/eval/test_contracts.py`.
- Create `tests/eval/test_dataset.py`.
- Create `tests/fixtures/evaluation/minimal-dataset/{dataset.json,development.jsonl,validation.jsonl,test.jsonl}`.

Do not modify `paper_agent/pipeline.py`, `paper_agent/cli.py`, `paper_agent/schemas.py`, or existing evaluation fixture formats.

## Phase 1: Design Corrections

### Task 1: Correct the design source of truth

**Files:**
- Modify: `docs/superpowers/specs/2026-07-23-rag-evaluation-engineering-design.md`

- [ ] **Step 1: Correct manifest counts and licensing**

Replace source totals with a source x split matrix:

```json
"source_split_counts": [
  {"source": "SciFact", "development": 5, "validation": 20, "test": 5},
  {"source": "QASPER", "development": 5, "validation": 20, "test": 5},
  {"source": "MOMO", "development": 2, "validation": 10, "test": 2},
  {"source": "ScholarQABench", "development": 3, "validation": 10, "test": 3}
]
```

Record source assets separately: SciFact claims/evidence are `CC-BY-4.0`; SciFact abstracts are `ODC-By-1.0`; code licenses do not stand in for dataset licenses. QASPER and ScholarQABench assets require their own recorded terms.

- [ ] **Step 2: Add execution gates and applicability**

Document that `FrozenCorpusSearchAdapter` freezes `Paper` records, not PDF bytes; later execution must inject or verify frozen `PaperDocument`. Allow missing corpus hash only for `paper_retrieval`. Record the missing offline paper-ranker SUT as a blocker for frozen Paper Recall.

- [ ] **Step 3: Add unified correlation, authority, and recovery rules**

Copy every item from "Locked Cross-Plan Decisions" into the relevant specification sections. Do not introduce implementation in this task.

- [ ] **Step 4: Correct cost semantics**

Latency and token usage are observable. Cost is `unscorable` until a versioned pricing policy exists.

- [ ] **Step 5: Review the design diff**

```powershell
git diff -- docs/superpowers/specs/2026-07-23-rag-evaluation-engineering-design.md
git diff --check
```

Expected: design-only corrections, no production code.

## Phase 2: Immutable Gold Contracts

### Task 2: Manifest, provenance, and audit-result models

**Files:**
- Create: `paper_agent/eval/contracts.py`
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/test_contracts.py`

- [ ] **Step 1: Write the complete manifest-contract RED matrix**

Before any implementation, create a two-source manifest fixture and tests for:

- valid asset-specific provenance and source x split counts;
- numeric strings and booleans rejected for every count;
- unknown fields and blank identifiers/provenance rejected;
- model attribute reassignment rejected;
- nested collections are tuples and cannot be appended;
- duplicate source names and duplicate asset types rejected;
- split paths unique under `os.path.normcase`;
- matrix sources exactly equal declared sources;
- matrix column sums exactly equal declared split totals.

Use the matrix:

```python
"source_split_counts": [
    {"source": "SciFact", "development": 1, "validation": 1, "test": 1},
    {"source": "QASPER", "development": 1, "validation": 1, "test": 1},
]
```

Also write RED tests for the public audit result contract:

```python
audit = EvaluationDatasetAudit(
    root="C:/dataset",
    manifest=manifest,
    audited_splits=("development", "validation"),
    splits=(
        AuditedSplit(
            split="development",
            case_ids=("dev-1", "dev-2"),
            fingerprint_sha256="a" * 64,
        ),
        AuditedSplit(
            split="validation",
            case_ids=("val-1",),
            fingerprint_sha256="b" * 64,
        ),
    ),
    fingerprint_sha256="c" * 64,
)
assert audit.audited_splits == ("development", "validation")
```

Reject duplicate/out-of-canonical-order `audited_splits`, disagreement between `audited_splits` and `splits`, duplicate case IDs within an audited split, invalid hashes, and all mutation attempts.

- [ ] **Step 2: Confirm the complete contract suite is RED**

```powershell
python -m pytest tests/eval/test_contracts.py -k "manifest or audit" -q
```

Expected: collection fails because `paper_agent.eval.contracts` does not exist. Record this RED before implementation.

- [ ] **Step 3: Implement only the tested frozen contracts**

Use `FrozenEvalModel(StrictModel)` with `ConfigDict(extra="forbid", frozen=True)`, tuple-backed collections, `StrictInt`, and these public types:

- `SourceAsset`
- `DatasetSource`
- `SplitDeclaration`
- `SplitDeclarations`
- `SourceSplitCount`
- `DatasetManifest`
- `AuditedSplit`
- `EvaluationDatasetAudit`

`EvaluationDatasetAudit` fields are exactly:

```python
class AuditedSplit(FrozenEvalModel):
    split: SplitName
    case_ids: tuple[str, ...]
    fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

class EvaluationDatasetAudit(FrozenEvalModel):
    root: str
    manifest: DatasetManifest
    audited_splits: tuple[SplitName, ...]
    splits: tuple[AuditedSplit, ...]
    fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

Put source/asset/matrix invariants on manifest-owned models and audit ordering/membership invariants on `EvaluationDatasetAudit`. Lock fingerprint semantics in the contract tests:

- `AuditedSplit.fingerprint_sha256` equals `EvaluationDataset.fingerprint_sha256` for the same manifest, split name, and ordered cases.
- The split fingerprint payload is canonical manifest JSON + split name + ordered cases.
- The audit fingerprint payload is canonical manifest JSON + ordered `audited_splits` + the corresponding ordered split fingerprints.
- Audited splits always use canonical order `development, validation, test` filtered to the authorized set. Split content and the authorized split set affect the audit fingerprint; callers cannot reorder splits.
- Dataset root, timestamps, JSON whitespace, and JSON key order affect neither fingerprint.

Do not implement filesystem behavior.

- [ ] **Step 4: Confirm the complete contract suite is GREEN**

```powershell
python -m pytest tests/eval/test_contracts.py -k "manifest or audit" -q
```

Expected: every Task 2 case passes.
### Task 3: EvalCase applicability and reference integrity

**Files:**
- Modify: `paper_agent/eval/contracts.py`
- Modify: `tests/eval/test_contracts.py`

- [ ] **Step 1: Write the complete EvalCase RED matrix before case implementation**

Add:

1. One valid claim-verification case with relevant paper IDs, one corpus paper, one evidence record, one critical claim, and matching hashes.
2. Strict scalar cases rejecting numeric strings/bools for year, page, relevance grade, `required`, and `unanswerable`.
3. Integrity cases for blank IDs/question, invalid hashes, duplicate paper/evidence/claim/rubric IDs, references outside corpus, mismatched content hashes, dangling supporting evidence, and unanswerable with non-blank answer.
4. A parameterized five-task applicability matrix:

| Task | relevant IDs | evidence | claims | answer | corpus | hashes |
|---|---|---|---|---|---|---|
| paper_retrieval | required | forbidden | forbidden | forbidden | >=1 | optional |
| evidence_retrieval | optional diagnostic | required | forbidden | forbidden | >=1 | required |
| single_paper_qa | optional diagnostic | required | forbidden | answer or unanswerable | exactly 1 | required |
| claim_verification | required | required | required | optional | >=1 | required |
| multi_paper_synthesis | required | required | required | required | >=2 | required |

For every optional gold section, empty tuple/string is invalid; unavailable is absent/`None`. Include a parameterized test proving every non-`paper_retrieval` case is rejected when any corpus content hash is missing.

- [ ] **Step 2: Confirm all case behavior is RED**

```powershell
python -m pytest tests/eval/test_contracts.py -k "case or paper_retrieval or evidence_retrieval or single_paper or claim_verification or synthesis or scalar or hash" -q
```

Expected: failures because case contract types do not exist. Record RED before implementation.

- [ ] **Step 3: Implement only the tested frozen case contracts**

Add frozen tuple-backed models for:

- `CorpusPaper`, with `content_sha256: str | None`;
- `CorpusConstraint`;
- `ReferenceEvidence`;
- `ReferenceClaim`;
- `CaseReference`;
- `RubricItem`;
- `CaseMetadata`;
- `EvalCase`;
- `EvaluationDataset`.

Use `StrictInt` and `StrictBool`; validate hashes with `^[0-9a-f]{64}$`. Implement local identity/reference validators and exactly the applicability table from Step 1. Do not add execution or metric models.

- [ ] **Step 4: Confirm the complete case suite is GREEN**

```powershell
python -m pytest tests/eval/test_contracts.py -q
```

Expected: all manifest, audit-result, strict-scalar, integrity, immutability, and applicability cases pass.

- [ ] **Step 5: Contract checkpoint**

```powershell
python -m pytest tests/eval/test_contracts.py -q
python -m pytest tests/test_eval_metrics.py tests/test_eval_runner.py tests/test_retrieval_eval_runner.py -q
git diff --check
```
## Phase 3: Dataset Loader and Audit

### Task 4: Minimal licensed fixture, selected-split load, and fingerprint

**Files:**
- Create: `tests/fixtures/evaluation/minimal-dataset/dataset.json`
- Create: `tests/fixtures/evaluation/minimal-dataset/development.jsonl`
- Create: `tests/fixtures/evaluation/minimal-dataset/validation.jsonl`
- Create: `tests/fixtures/evaluation/minimal-dataset/test.jsonl`
- Create: `tests/eval/test_dataset.py`
- Create: `paper_agent/eval/dataset.py`

The fixture contains SciFact and QASPER, with one case from each source in every split. This catches source x split swaps while preserving equal row/column totals.

- [ ] **Step 1: Write all selected-load and fingerprint RED tests**

Before creating `dataset.py`, assert:

- selected development loads ordered case IDs and declared counts;
- repeated loads return the same literal SHA-256;
- changing selected case order changes the fingerprint;
- changing a selected gold label changes the fingerprint;
- moving the same dataset to another root does not change the fingerprint;
- whitespace/key-order-only JSON reformatting does not change the fingerprint;
- development and validation loads succeed when `test.jsonl` is missing or malformed;
- a spy/guard proves development and validation loads never open `test.jsonl`;
- a test load is rejected unless `allow_test_labels=True`.

Expected fingerprint literals come from one independently canonicalized fixture payload stored in the test, not by calling production helpers.

- [ ] **Step 2: Confirm the group is RED**

```powershell
python -m pytest tests/eval/test_dataset.py -k "selected or fingerprint" -q
```

Expected: import fails because `paper_agent.eval.dataset` does not exist.

- [ ] **Step 3: Implement only selected happy-path loading and canonical fingerprinting**

`load_evaluation_dataset` reads `dataset.json` and only the selected split, validates public models, and fingerprints canonical manifest + split name + ordered selected cases. It must not resolve or open unselected split files. Test selection requires `allow_test_labels=True`. Root path, timestamps, and source JSON formatting are excluded.

- [ ] **Step 4: Confirm the group is GREEN**

Run Step 2. Expected: every selected-load and fingerprint case passes.
### Task 5: Parsing diagnostics, path safety, and test-label isolation

**Files:**
- Modify: `tests/eval/test_dataset.py`
- Modify: `paper_agent/eval/dataset.py`

- [ ] **Step 1: Add schema-major RED, implement, confirm GREEN**
- [ ] **Step 2: Add malformed JSON/JSONL RED with file and line, implement, confirm GREEN**
- [ ] **Step 3: Add invalid UTF-8, directory-instead-of-file, missing file, and generic `OSError` RED; wrap as `DatasetValidationError` without raw corpus text; confirm GREEN**
- [ ] **Step 4: Add selected-path absolute path, parent traversal, sibling-prefix, and supported-platform symlink/junction escape RED**
- [ ] **Step 5: Implement path containment with resolved `Path.relative_to()`, never string `startswith`; confirm GREEN**
- [ ] **Step 6: Run the complete parsing/path group and confirm GREEN**

```powershell
python -m pytest tests/eval/test_dataset.py -k "schema or json or utf8 or os_error or path or symlink" -q
```

### Task 6: Selected-split validation and explicit multi-split audit

**Files:**
- Modify: `tests/eval/test_dataset.py`
- Modify: `paper_agent/eval/dataset.py`

- [ ] **Step 1: Add selected-split RED tests**

Test selected split count, metadata split, duplicate IDs within selected split, source membership, license-asset membership, and selected source-count column.

- [ ] **Step 2: Implement selected-split validation and confirm GREEN**

- [ ] **Step 3: Add default audit cross-validation and fingerprint RED**

Before implementing audit, test that `audit_evaluation_dataset(root)`:

- opens development and validation only and reports `audited_splits=("development", "validation")`;
- ignores missing/malformed/forbidden test data;
- rejects duplicate case IDs between development and validation;
- validates the development and validation source-matrix columns independently;
- resolves only development/validation paths, rejects when those two resolve to the same target, and a guard proves it never resolves the test path;
- returns each `AuditedSplit.fingerprint_sha256` equal to the selected-load fingerprint for that split;
- returns a deterministic aggregate fingerprint from canonical manifest + ordered audited split names + ordered split fingerprints;
- changes aggregate fingerprint when audited split content changes;
- ignores root relocation, timestamps, whitespace, and key ordering.

- [ ] **Step 4: Confirm default audit behavior is RED**

```powershell
python -m pytest tests/eval/test_dataset.py -k "default_audit or audit_fingerprint" -q
```

Expected: failures because `audit_evaluation_dataset` does not exist.

- [ ] **Step 5: Implement one development+validation audit pass and confirm GREEN**

Implement only the default audited pair and the exact canonical fingerprints from Step 3. Run the Step 4 command.

- [ ] **Step 6: Add authorized-test audit RED**

With `include_test_labels=True`, require all three split files, validate all three source-matrix columns, reject duplicates involving test, reject any resolved-path alias among all three audited files, and report canonical `("development", "validation", "test")`. Without authorization, test-only defects and test-path resolution remain outside the audited result. Assert the authorized three-split aggregate fingerprint differs from the default two-split fingerprint.

- [ ] **Step 7: Confirm RED, extend the audit minimally, and confirm GREEN**

```powershell
python -m pytest tests/eval/test_dataset.py -k "authorized_test_audit" -q
```

- [ ] **Step 8: Run the full dataset suite**

```powershell
python -m pytest tests/eval/test_dataset.py -q
```


```powershell
python -m pytest tests/eval/test_dataset.py -q
```

### Task 7: Stable exports

**Files:**
- Modify: `paper_agent/eval/__init__.py`
- Modify: `tests/eval/test_dataset.py`

- [ ] **Step 1: Add public import RED**

Import `DatasetValidationError`, `load_evaluation_dataset`, and `audit_evaluation_dataset` from `paper_agent.eval`.

- [ ] **Step 2: Confirm RED, export only these symbols, confirm GREEN**

## Phase 4: Verification

### Task 8: Verify and hand off

- [ ] **Step 1: New focused suite**

```powershell
python -m pytest tests/eval/test_contracts.py tests/eval/test_dataset.py -q
```

- [ ] **Step 2: Evaluation regression suite**

```powershell
python -m pytest tests/test_eval_metrics.py tests/test_eval_runner.py tests/test_eval_retrieval_metrics.py tests/test_retrieval_eval_runner.py tests/eval -q
```

- [ ] **Step 3: Full offline suite**

```powershell
python -m pytest -q
```

Expected: more than 766 tests, zero failures, no network/provider/Ragas access.

- [ ] **Step 4: Integrity and diff review**

```powershell
git diff --check
git status --short --branch
```

Confirm only design, plan, contracts, loader, exports, tests, and fixtures changed. Confirm no Pipeline/CLI/shared-schema edits, no secrets, no debug code, and no speculative later-plan implementation.

- [ ] **Step 5: Deliver without Git mutation**

Report RED/GREEN evidence, focused/full counts, changed files, remaining execution gates, and exact commit/push status.

## Deferred Plans

1. SciFact/QASPER converters and provenance registry.
2. Evidence matching and task-aware metrics.
3. Frozen acquisition, `EvaluationCorrelation`, `EvaluationSystem`, and Pipeline adapter.
4. Experiment attempts, sealed traces, canonical selection, resume/recovery, and projections.
5. Compatible baseline comparison and structural trace checks.
6. Optional Ragas adapter.
7. Curated 90-case materialization and 60-case validation baseline.

No deferred plan may treat a gold-ordered paper list as retrieval output or collapse `execution_id` into `scoring_attempt_id`.

## Post-Merge Baseline Addendum (2026-07-26)

Tasks 1-8 above are complete on `origin/master` and remain authoritative. Do not
reopen their frozen contract, selected-split isolation, path-safety, or loader
tests merely to support benchmark execution.

The retrieval and citation baseline plans may make only these additive changes:

- add benchmark-specific manifests that reference an
  `EvaluationDataset.fingerprint_sha256` and the ordered selected case IDs;
- add optional benchmark annotation models in new modules rather than widening
  the existing five-task `EvalCase` contract without a migration;
- load `development` and `validation` through the existing public Loader and
  preserve explicit authorization for test labels;
- store corpus/chunk hashes, Gold Evidence judgments, resolved runtime config,
  and model versions in experiment artifacts, not in Loader-owned gold models;
- keep the minimal licensed fixture and fixture-generated values restricted to
  offline contract/regression tests. They are never resume evidence.

The follow-on implementation sources are:

1. `docs/superpowers/plans/2026-07-26-rag-retrieval-benchmark.md` for the 40-case
   real retrieval quick baseline.
2. `docs/superpowers/plans/2026-07-26-rag-citation-quality-baseline.md` for the
   20-case citation quick baseline and the combined 60-case Validation seal.
