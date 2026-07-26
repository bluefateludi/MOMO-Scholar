# RAG Citation Quality Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a sealed, recomputable 20-case citation-quality baseline and combine it with the retrieval track into the final 60-case Validation evidence package.

**Architecture:** Citation outputs are normalized into atomic assertions and citation occurrences, then evaluated by two intentionally separate layers: deterministic structural validity and Gold Evidence/human-reviewed semantic support. A frozen calibration protocol controls reviewer drift, while the shared evidence-package layer preserves authorities, projections, hashes, traces, and resume-safe claims.

**Tech Stack:** Python 3.10+, Pydantic 2, pytest, standard-library JSON/hash/statistics utilities, existing evaluation contracts, Evidence schemas, citation checker, and evidence matching rules.

## Global Constraints

- Report Citation Coverage, Citation Validity, and Unsupported Assertion Rate as separate metrics.
- Citation Validity measures resolvable, run-owned references; it never implies semantic support.
- Unsupported Assertion Rate is based on atomic assertions and cited evidence semantics; lower is better.
- Match Gold Evidence deterministically before human review and preserve every match decision.
- Freeze the human-review rubric and calibration answers before scoring reported cases.
- Use exactly 20 citation cases for the quick baseline and combine them with 40 retrieval cases for the final 60-case Validation baseline.
- Synthetic fixture numbers are forbidden in resume evidence; normal tests remain offline.
- A publishable package requires sealed authorities, clean Git state, exact model versions, and recomputation success.

---

## File Map

- Create `paper_agent/eval/citation_baseline/contracts.py`: atomic assertion, citation occurrence, match, review, and metric contracts.
- Create `paper_agent/eval/citation_baseline/normalize.py`: deterministic output normalization and assertion boundaries.
- Create `paper_agent/eval/citation_baseline/matching.py`: Gold Evidence matching and support-decision preparation.
- Create `paper_agent/eval/citation_baseline/metrics.py`: structural and semantic metrics plus bootstrap intervals.
- Create `paper_agent/eval/citation_baseline/review.py`: frozen rubric, calibration, assignment, adjudication, and review import/export.
- Create `paper_agent/eval/citation_baseline/report.py`: complete and resume-safe report projections.
- Create `paper_agent/eval/citation_baseline/cli.py`: prepare, export-review, import-review, score, recompute, and verify commands.
- Modify `paper_agent/cli.py`: register commands after focused tests pass.
- Reuse `paper_agent/eval/evidence_package.py` created by the retrieval plan.
- Create focused tests under `tests/eval/citation_baseline/` and non-resume fixtures under `tests/fixtures/evaluation/citation-baseline/`.

### Task 1: Freeze Citation and Human-Judgment Contracts

**Files:**
- Create: `paper_agent/eval/citation_baseline/contracts.py`
- Test: `tests/eval/citation_baseline/test_contracts.py`

**Interfaces:**
- Consumes: case/run IDs, generated output, Evidence records, Gold Evidence, and rubric metadata.
- Produces: `AtomicAssertion`, `CitationOccurrence`, `EvidenceMatch`, `SupportJudgment`, `CalibrationRecord`, and `CitationCaseResult`.

- [ ] **Step 1: Write failing strict-contract tests**

Reject blank/duplicate IDs, dangling citation occurrence references, invalid hashes, unknown verdicts, verdicts without allowed reason codes, unsupported verdicts that claim matched support, ambiguous verdicts lacking notes, and mutation. Preserve output/evidence/config hashes on every judgment.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/eval/citation_baseline/test_contracts.py -q`

- [ ] **Step 3: Implement immutable contracts and confirm GREEN**

Use verdicts `supported`, `unsupported`, and `ambiguous`; separate `structurally_valid` from `semantic_verdict`; identify reviewers only by stable pseudonym; version every rubric and calibration set.

### Task 2: Normalize Outputs into Stable Atomic Assertions

**Files:**
- Create: `paper_agent/eval/citation_baseline/normalize.py`
- Test: `tests/eval/citation_baseline/test_normalize.py`

**Interfaces:**
- Consumes: checked Pipeline report/claims and run-owned Evidence records.
- Produces: ordered atomic assertions and citation occurrences with source section and character offsets.

- [ ] **Step 1: Write RED normalization tests**

Cover one claim/one citation, several citations, repeated citation occurrences, uncited assertions, list items, headings without assertions, duplicate Evidence IDs, and malformed/foreign-run IDs. Assert normalization is deterministic and never changes assertion text.

- [ ] **Step 2: Implement the narrow normalizer**

Prefer existing structured claims over sentence splitting. If an output section is unstructured, fail with `unsupported_output_shape` rather than silently applying a lossy parser.

- [ ] **Step 3: Confirm GREEN and run citation checker regressions**

Run: `python -m pytest tests/eval/citation_baseline/test_normalize.py tests/test_citation_checker.py -q`

### Task 3: Separate Structural Citation Validity from Semantic Support

**Files:**
- Create: `paper_agent/eval/citation_baseline/matching.py`
- Test: `tests/eval/citation_baseline/test_matching.py`

**Interfaces:**
- Consumes: normalized assertions, citation occurrences, actual Evidence, and reference `ReferenceEvidence`.
- Produces: structural resolution and deterministic Gold Evidence match records.

- [ ] **Step 1: Write RED structural tests**

Require a citation ID to resolve uniquely, use the evaluated run prefix, and match an assertion's paper where the assertion is paper-scoped. Prove a structurally valid but irrelevant citation remains semantically undecided.

- [ ] **Step 2: Write RED Gold Evidence tests**

Cover exact locator, exact normalized quote, 0.90 containment, 0.80 token-span F1, page constraints, content-hash mismatch as `unscorable_content`, one-to-one matching, and no-match handoff to review.

- [ ] **Step 3: Implement matching and confirm GREEN**

Reuse the specification's deterministic match order and record strategy, score, actual evidence ID, gold evidence ID, and hash inputs.

### Task 4: Implement the Frozen Human-Review Calibration Workflow

**Files:**
- Create: `paper_agent/eval/citation_baseline/review.py`
- Test: `tests/eval/citation_baseline/test_review.py`

**Interfaces:**
- Consumes: unresolved assertion/evidence pairs, frozen rubric, calibration set, and signed review imports.
- Produces: validated calibration statistics, assignments, judgments, and adjudication records.

- [ ] **Step 1: Write RED rubric and calibration tests**

Freeze supported/unsupported/ambiguous definitions and reason codes. Require a fixed double-reviewed calibration sample selected before scoring, exclude calibration items from reported metrics, compute raw agreement and Cohen's kappa when defined, and block scoring until calibration is complete and disagreements are adjudicated.

- [ ] **Step 2: Write RED review integrity tests**

Reject changed assertion/evidence/config hashes, reviewer identity leakage, missing rubric versions, duplicated assignments, post-freeze edits, and judgments for unassigned items. Preserve original judgments beside adjudication.

- [ ] **Step 3: Implement export/import and calibration gates**

Emit review JSONL with only the assertion, cited passages, necessary provenance, and blinded case ID. Import validates all hashes before accepting a verdict.

- [ ] **Step 4: Confirm GREEN**

Run: `python -m pytest tests/eval/citation_baseline/test_review.py -q`

### Task 5: Compute Citation Metrics and Confidence Intervals

**Files:**
- Create: `paper_agent/eval/citation_baseline/metrics.py`
- Test: `tests/eval/citation_baseline/test_metrics.py`

**Interfaces:**
- Consumes: normalized assertions, structural resolutions, Gold matches, and final semantic judgments.
- Produces: per-case/aggregate Citation Coverage, Citation Validity, Unsupported Assertion Rate, status counts, latency, failure rate, and bootstrap 95% intervals.

- [ ] **Step 1: Write RED denominator tests**

Citation Coverage denominator is all atomic assertions. Citation Validity denominator is all citation occurrences. Unsupported Assertion Rate denominator is all scorable atomic assertions; ambiguous and unscorable counts are reported separately and never coerced to supported or unsupported.

- [ ] **Step 2: Write RED aggregation tests**

Assert equal-weight case macro means, deterministic seed `20260726`, 10,000 case-level bootstrap resamples, percentile 95% intervals, explicit case/assertion/citation denominators, and failure rate over all attempted cases.

- [ ] **Step 3: Implement metrics and confirm GREEN**

Run: `python -m pytest tests/eval/citation_baseline/test_metrics.py -q`

### Task 6: Add Citation Reports and Evidence-Package Checks

**Files:**
- Create: `paper_agent/eval/citation_baseline/report.py`
- Modify: `paper_agent/eval/evidence_package.py`
- Test: `tests/eval/citation_baseline/test_report.py`
- Test: `tests/eval/test_evidence_package.py`

**Interfaces:**
- Consumes: verified case metrics, aggregate/CI, calibration/adjudication, environment, failures, logs, and traces.
- Produces: citation `report.md`, guarded `resume-evidence.md`, and sealed package entries for review authorities.

- [ ] **Step 1: Extend the package RED matrix**

Require `assertions.jsonl`, `citation-occurrences.jsonl`, `evidence-matches.jsonl`, `review-rubric.json`, `calibration.jsonl`, `judgments.jsonl`, and `adjudications.jsonl`. Hash all review authorities before metric projections.

- [ ] **Step 2: Write RED report tests**

Show structure and semantics in separate tables, include all denominators/intervals/failures/calibration statistics, and explain ambiguous/unscorable cases. Suppress resume numbers for synthetic, dirty, unsealed, unrecomputed, under-20-case, or incomplete-review packages.

- [ ] **Step 3: Implement reports and confirm GREEN**

Run: `python -m pytest tests/eval/citation_baseline/test_report.py tests/eval/test_evidence_package.py -q`

### Task 7: Add Review, Score, Recompute, and Verify Commands

**Files:**
- Create: `paper_agent/eval/citation_baseline/cli.py`
- Modify: `paper_agent/cli.py`
- Test: `tests/eval/citation_baseline/test_cli.py`

**Interfaces:**
- Consumes: a prepared experiment, review JSONL, and sealed authorities.
- Produces: `prepare`, `export-review`, `import-review`, `score`, `recompute`, and `verify` commands.

- [ ] **Step 1: Write RED command tests**

Prove all commands are offline except the separately invoked Pipeline generation step; imports fail on hash/rubric mismatch; scoring blocks on incomplete calibration or judgments; recompute derives projections only from sealed authorities.

- [ ] **Step 2: Implement and register commands**

Use exit code 0 for verified completion, 1 for case/review failures, 2 for input/configuration issues, and 3 for package corruption.

- [ ] **Step 3: Confirm GREEN**

Run: `python -m pytest tests/eval/citation_baseline tests/eval tests/test_cli.py -q`

### Task 8: Curate and Run the 20-Case Citation Quick Baseline

**Files:**
- Create locally: 20 licensed citation cases and Gold Evidence judgments in `evaluations/datasets/momo-eval-v1/`.
- Create locally: `evaluations/experiments/<citation-experiment-id>/` sealed evidence package.

**Interfaces:**
- Consumes: real Pipeline outputs, frozen Evidence, clean Git state, generation model version, Gold Evidence, and calibrated human reviews.
- Produces: a verified 20-case citation-quality package.

- [ ] **Step 1: Complete offline preflight**

Validate exactly 20 ordered non-synthetic cases, corpus/chunk/output hashes, Gold Evidence, resolved configuration, model versions, expected provider cost, secret policy, reviewer availability, rubric, and calibration assignments.

- [ ] **Step 2: Run a two-case live generation smoke with timeout**

Preserve outputs, Evidence, logs, traces, token usage, latency, and failures. Provider or credential failure is a blocker, not a score.

- [ ] **Step 3: Freeze outputs and perform calibration/review**

Seal generation authorities before review export. Complete and adjudicate the fixed calibration sample, then review remaining unresolved assertions without changing outputs or gold.

- [ ] **Step 4: Score, seal, recompute, and verify**

Require identical per-case metrics, aggregate values, intervals, and reports from offline recomputation.

### Task 9: Assemble the Final 60-Case Validation Baseline

**Files:**
- Create locally: `evaluations/experiments/<validation-experiment-id>/` combined sealed manifest and reports.

**Interfaces:**
- Consumes: verified 40-case retrieval and 20-case citation packages with compatible dataset/config/Git/corpus fingerprints.
- Produces: the authoritative 60-case Validation `artifact-manifest.json`, `report.md`, and `resume-evidence.md`.

- [ ] **Step 1: Verify compatibility without copying projections as authority**

Require 60 unique ordered case IDs, matching dataset version/split, Git SHA and clean state, applicable corpus/chunk hashes, metric versions, and source package seals. Reject overlap, missing cases, dirty packages, or incompatible fingerprints.

- [ ] **Step 2: Build the combined manifest and report**

Reference the two source packages and hashes. Do not average unrelated retrieval and citation metrics into one score. Preserve track-specific case counts, metrics, intervals, latency, failures, and limitations.

- [ ] **Step 3: Verify every resume statement**

For each numeric statement, recompute the numerator, denominator, comparison, and interval from sealed authorities and record source hash prefixes. Remove statements that fail verification.

- [ ] **Step 4: Record blockers honestly**

If dataset download, model dependency, network, API credential, reviewer availability, or cost prevents a real run, deliver validated offline schemas/tools and a precise blocker list. Do not create a final baseline seal or resume metrics.

## Plan Self-Review Gate

Before implementation, map every citation-design requirement to a task, scan for placeholders and contradictory denominators, verify contract names across tasks, and run `git diff --check`. Implementation begins only after this plan and the revised design are reviewed.
