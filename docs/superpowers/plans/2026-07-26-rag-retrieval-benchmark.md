# RAG Retrieval Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a sealed, recomputable 40-case retrieval baseline that fairly compares production Keyword, actual Vector-only, and production Hybrid+RRF retrieval.

**Architecture:** A benchmark adapter loads frozen evaluation cases and chunks, invokes the same production candidate sources under three explicit modes, and records raw rankings before deterministic scoring. A separate statistics and evidence-pack layer computes paired comparisons, bootstrap intervals, operational metrics, and sealed reports without changing the existing dataset Loader contracts.

**Tech Stack:** Python 3.10+, Pydantic 2, pytest, standard-library `hashlib`, `json`, `random`, `statistics`, production `paper_agent.evidence` and `paper_agent.vector` modules.

## Global Constraints

- Evaluate `K={1,3,5,8,10}` and declare `K=8` as primary before execution.
- Use equal ordered cases, queries, chunks, candidate budgets, timeout policy, and failure policy across all modes.
- Keyword uses `LexicalCandidateSource`; Vector-only uses `VectorCandidateSource` with an actual configured embedder/vector store; Hybrid uses `HybridRetriever` and production RRF.
- Fixture-provided vector rankings and synthetic fixture metrics are test evidence only and are forbidden in `resume-evidence.md`.
- Normal tests are offline with fakes; live evaluation is a separate explicit command with network timeouts.
- All resume numbers come from a clean-worktree sealed package and remain recomputable from raw rankings and case metrics.
- Do not modify the completed `EvalCase` or dataset Loader contracts unless a demonstrated incompatibility requires a separately reviewed migration.

---

## File Map

- Create `paper_agent/eval/retrieval_benchmark/contracts.py`: strict benchmark config, ranking, timing, failure, and aggregate models.
- Create `paper_agent/eval/retrieval_benchmark/runner.py`: fair three-mode case execution and raw authority writing.
- Create `paper_agent/eval/retrieval_benchmark/statistics.py`: multi-K metrics, paired deltas, and seeded bootstrap intervals.
- Create `paper_agent/eval/evidence_package.py`: common hash manifest, atomic writes, sealing, and verification.
- Create `paper_agent/eval/retrieval_benchmark/report.py`: engineering and resume evidence projections.
- Create `paper_agent/eval/retrieval_benchmark/cli.py`: explicit offline preparation, live execution, recompute, and verify entry points.
- Modify `paper_agent/cli.py`: register the benchmark command group only after its module tests pass.
- Create focused tests under `tests/eval/retrieval_benchmark/` and deterministic fixtures under `tests/fixtures/evaluation/retrieval-benchmark/`.
- Materialize the real 40-case dataset and generated experiment packages under ignored `evaluations/`; do not commit licensed or generated content unless its manifest permits redistribution.

### Task 1: Freeze Benchmark Contracts and Fairness Fingerprint

**Files:**
- Create: `paper_agent/eval/retrieval_benchmark/contracts.py`
- Test: `tests/eval/retrieval_benchmark/test_contracts.py`

**Interfaces:**
- Consumes: `EvaluationDataset.fingerprint_sha256`, ordered case IDs, resolved production retrieval settings.
- Produces: `RetrievalBenchmarkConfig`, `RawRanking`, `CaseRetrievalResult`, `ModeFailure`, and `BenchmarkFingerprint`.

- [ ] **Step 1: Write failing contract tests**

Assert strict rejection of unknown fields, booleans as integers, duplicate/unsorted K values, a primary K outside the K set, noncanonical modes, blank model versions, invalid hashes, duplicate ranking IDs, and non-finite or negative durations. Assert frozen tuple-backed collections.

- [ ] **Step 2: Run the contract tests and confirm RED**

Run: `python -m pytest tests/eval/retrieval_benchmark/test_contracts.py -q`

Expected: collection fails because the contract module does not exist.

- [ ] **Step 3: Implement the minimal strict models**

Use canonical modes `("keyword", "vector", "hybrid_rrf")`, K values `(1, 3, 5, 8, 10)`, primary K `8`, and a fairness fingerprint over dataset fingerprint, ordered case IDs, corpus/chunk hashes, candidate limit, timeout, RRF constant, embedding model/version, chunking config, and metric versions.

- [ ] **Step 4: Run the contract tests and confirm GREEN**

Run: `python -m pytest tests/eval/retrieval_benchmark/test_contracts.py -q`

### Task 2: Build a Fair Production Retrieval Adapter

**Files:**
- Create: `paper_agent/eval/retrieval_benchmark/runner.py`
- Test: `tests/eval/retrieval_benchmark/test_runner.py`

**Interfaces:**
- Consumes: `RetrievalBenchmarkConfig`, cases with frozen `Chunk` sequences, `LexicalCandidateSource`, `VectorCandidateSource`, and `HybridRetriever` dependencies.
- Produces: one `RawRanking` per case/mode plus structured `ModeFailure` records.

- [ ] **Step 1: Write RED tests for mode execution**

Use deterministic fakes to prove each mode receives identical query/chunk order and candidate limit; Vector-only calls `index_chunks` and `retrieve`; Hybrid output equals production RRF over the same captured Keyword and Vector rankings; raw rankings preserve scores, ranks, source provenance, start/end timestamps, and duration.

- [ ] **Step 2: Add RED tests for failure isolation**

Cover timeout, embedding authentication/configuration, rate-limit/network failure, malformed candidate identity, and an empty corpus. Assert no implicit hybrid degradation in a benchmark and that one mode failure does not erase successful paired-mode raw data.

- [ ] **Step 3: Implement the adapter and confirm GREEN**

Run: `python -m pytest tests/eval/retrieval_benchmark/test_runner.py -q`

- [ ] **Step 4: Run production retrieval regressions**

Run: `python -m pytest tests/evidence tests/vector tests/test_pipeline_hybrid_retrieval.py -q`

### Task 3: Compute Multi-K Metrics and Paired Confidence Intervals

**Files:**
- Create: `paper_agent/eval/retrieval_benchmark/statistics.py`
- Test: `tests/eval/retrieval_benchmark/test_statistics.py`

**Interfaces:**
- Consumes: successful raw rankings and graded gold judgments.
- Produces: per-case metrics, macro aggregates, paired deltas, percentile bootstrap 95% confidence intervals, latency summaries, and failure rates.

- [ ] **Step 1: Write RED metric matrix tests**

For every mode and K, assert exact Recall, Precision, MRR, and graded nDCG values using the existing metric functions. Verify primary metric labels always point to K=8 and a failed mode has status `error`, not numeric zero.

- [ ] **Step 2: Write RED paired-statistics tests**

Use a fixed four-case table and assert deltas are calculated case-by-case before averaging. Require Hybrid-minus-Keyword and Hybrid-minus-Vector comparisons, deterministic seed `20260726`, 10,000 resamples, percentile endpoints, and explicit paired case count.

- [ ] **Step 3: Write RED operational-metric tests**

Assert p50/p95 latency uses successful attempts, failure rate uses all attempted cases, and the output preserves failure counts by mode and sanitized reason code.

- [ ] **Step 4: Implement statistics and confirm GREEN**

Run: `python -m pytest tests/eval/retrieval_benchmark/test_statistics.py -q`

### Task 4: Write and Verify the Sealed Evidence Package

**Files:**
- Create: `paper_agent/eval/evidence_package.py`
- Test: `tests/eval/test_evidence_package.py`

**Interfaces:**
- Consumes: dataset/corpus manifests, gold judgments, resolved config, environment, rankings, metrics, failures, logs, and traces.
- Produces: atomically published files and a final `artifact-manifest.json` containing path, byte length, SHA-256, role, and seal timestamp.

- [ ] **Step 1: Write RED layout and hash tests**

Require `dataset-manifest.json`, `corpus-manifest.json`, `gold-judgments.jsonl`, `resolved-config.json`, `environment.json`, `raw-rankings.jsonl`, `case-metrics.jsonl`, `aggregate.json`, `confidence-intervals.json`, `failures.jsonl`, `logs.jsonl`, `traces.jsonl`, `report.md`, and `resume-evidence.md` before sealing.

- [ ] **Step 2: Write RED corruption and authority tests**

Reject missing artifacts, path traversal, duplicate paths, hash mismatch, post-seal append, a dirty Git state for publishable status, missing model version, and report numbers not derivable from aggregate authorities.

- [ ] **Step 3: Implement atomic writing, sealing, and verification**

Use temporary sibling files plus `Path.replace`; seal `artifact-manifest.json` last and refuse all package mutation afterward.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/eval/test_evidence_package.py -q`

### Task 5: Generate Reports Without Inventing Resume Claims

**Files:**
- Create: `paper_agent/eval/retrieval_benchmark/report.py`
- Test: `tests/eval/retrieval_benchmark/test_report.py`

**Interfaces:**
- Consumes: verified aggregate, confidence interval, failure, environment, and artifact hash records.
- Produces: `report.md` and `resume-evidence.md` projections.

- [ ] **Step 1: Write RED report tests**

Assert the engineering report includes dataset/corpus fingerprints, exact configuration, all K values, paired deltas/CI, latency/failure tables, exclusions, limitations, and source hashes. Assert resume evidence is empty with an explicit reason when the package is dirty, unsealed, synthetic, incomplete, or has fewer than 40 cases.

- [ ] **Step 2: Implement deterministic report rendering**

Every resume bullet must state case count, modes, metric and K, absolute values, paired delta, 95% CI, and package/artifact hash prefix. Never select a metric based on observed improvement.

- [ ] **Step 3: Confirm GREEN**

Run: `python -m pytest tests/eval/retrieval_benchmark/test_report.py -q`

### Task 6: Add Explicit Commands and Offline Recompute

**Files:**
- Create: `paper_agent/eval/retrieval_benchmark/cli.py`
- Modify: `paper_agent/cli.py`
- Test: `tests/eval/retrieval_benchmark/test_cli.py`

**Interfaces:**
- Consumes: dataset path, split, output path, provider-backed vector dependencies, and an existing sealed package.
- Produces: `prepare`, `run-live`, `recompute`, and `verify` commands with exit codes 0/1/2/3.

- [ ] **Step 1: Write RED CLI tests**

Prove `prepare`, `recompute`, and `verify` never access network or credentials; `run-live` requires explicit acknowledgement, validates credentials/dependencies before creating an experiment, applies request timeouts, and records sanitized failures.

- [ ] **Step 2: Implement commands and register the group**

The recompute command reads only sealed raw rankings/gold/config, regenerates metrics and reports in a new verification directory, and byte-compares canonical JSON projections.

- [ ] **Step 3: Run CLI and evaluation regressions**

Run: `python -m pytest tests/eval/retrieval_benchmark tests/eval tests/test_cli.py -q`

### Task 7: Curate and Run the 40-Case Real Quick Baseline

**Files:**
- Create locally: `evaluations/datasets/momo-eval-v1/` licensed manifests and 40 retrieval cases.
- Create locally: `evaluations/experiments/<retrieval-experiment-id>/` sealed evidence package.

**Interfaces:**
- Consumes: real licensed corpus, frozen Gold Evidence judgments, clean Git SHA, actual embedding model credentials/configuration, and the benchmark commands.
- Produces: a verified 40-case retrieval evidence package.

- [ ] **Step 1: Validate offline inputs before provider access**

Run dataset audit, corpus/chunk hash verification, duplicate/judgment checks, resolved-config review, cost estimate, and a secret scan. Confirm exactly 40 ordered retrieval cases and no synthetic source.

- [ ] **Step 2: Run a two-case live smoke with explicit timeout**

Record actual Vector-only calls and all three raw rankings. A failure becomes a sanitized blocker and offline regression case; it never becomes a fabricated metric.

- [ ] **Step 3: Run the clean 40-case experiment once**

Do not tune after looking at Validation results. Preserve all failures and seal the package only after projections and traces finish.

- [ ] **Step 4: Recompute and verify independently**

Run the offline recompute and package verifier. Require identical case metrics, aggregates, intervals, and report source values.

- [ ] **Step 5: Record the handoff**

Report exact path, Git SHA/dirty state, model versions, dataset/corpus hashes, case counts, failures, verification commands, and whether `resume-evidence.md` is publishable. If data, network, credentials, dependency, or cost blocks execution, list the blocker and completed offline artifacts without numeric claims.

## Plan Self-Review Gate

Before implementation, verify every design requirement maps to a task, scan for placeholders, check type/name consistency across tasks, and run `git diff --check`. Do not start live execution until this plan and the design diff have been reviewed.
