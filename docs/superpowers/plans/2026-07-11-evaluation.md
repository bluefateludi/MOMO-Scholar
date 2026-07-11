# MOMO Scholar Evaluation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent, deterministic, offline Evaluation module for paper retrieval recall, evidence attachment, unsupported claims, and citation integrity.

**Architecture:** Keep all metric calculations as pure functions in `paper_agent/eval/metrics.py`. Put JSON loading, fixture validation, existing-schema construction, per-case evaluation, and macro aggregation in `paper_agent/eval/runner.py`. Do not connect Evaluation to the pipeline or introduce storage, network, model, or database dependencies.

**Tech Stack:** Python 3.11+, Pydantic models already defined in `paper_agent.schemas`, pytest, standard-library `json` and `pathlib`.

**Specification:** `docs/superpowers/specs/2026-07-11-evaluation-design.md`

**Git constraint:** The user authorized the design-spec commit and push only. During implementation, do not stage, commit, push, or create a PR unless the user gives new explicit authorization. Use status and diff checks at task checkpoints instead of commits.

---

## File Structure

- Create `paper_agent/eval/__init__.py`: package description only.
- Create `paper_agent/eval/metrics.py`: four pure metric functions.
- Create `paper_agent/eval/runner.py`: case evaluation, JSON validation, model construction, and macro summary.
- Create `tests/test_eval_metrics.py`: focused behavioral coverage for all metric contracts.
- Create `tests/test_eval_runner.py`: runner, validation, aggregation, and determinism coverage.
- Create `tests/fixtures/eval_cases.json`: deterministic, human-reviewable contract cases.
- Create `docs/evaluation.md`: formulas, usage, directionality, limitations, and future layers.

Do not modify shared schemas or pipeline files.

## Chunk 1: Pure Evaluation Metrics

### Task 1: Retrieval hit rate

**Files:**

- Create: `paper_agent/eval/__init__.py`
- Create: `paper_agent/eval/metrics.py`
- Create: `tests/test_eval_metrics.py`

- [ ] **Step 1: Create the empty Evaluation package and write retrieval tests**

Create `paper_agent/eval/__init__.py` with only:

```python
"""Deterministic offline evaluation."""
```

Create `tests/test_eval_metrics.py` with parametrized coverage:

```python
import pytest

from paper_agent.eval.metrics import retrieval_hit_rate


@pytest.mark.parametrize(
    ("actual", "expected", "score"),
    [
        (["p1", "p2"], ["p1", "p2"], 1.0),
        (["p1", "other"], ["p1", "p2"], 0.5),
        (["other"], ["p1", "p2"], 0.0),
        ([], ["p1"], 0.0),
        (["p1"], [], 0.0),
        (["p1", "p1"], ["p1", "p1", "p2"], 0.5),
    ],
)
def test_retrieval_hit_rate(actual, expected, score):
    assert retrieval_hit_rate(actual, expected) == score
```

- [ ] **Step 2: Run the retrieval test and confirm RED**

Run:

```powershell
python -m pytest tests/test_eval_metrics.py::test_retrieval_hit_rate -q
```

Expected: collection fails because `paper_agent.eval.metrics` or
`retrieval_hit_rate` does not exist. Record the actual failure text.

- [ ] **Step 3: Implement the minimal retrieval metric**

Create `paper_agent/eval/metrics.py`:

```python
from __future__ import annotations


def retrieval_hit_rate(
    actual_paper_ids: list[str],
    expected_paper_ids: list[str],
) -> float:
    expected = set(expected_paper_ids)
    if not expected:
        return 0.0
    return len(set(actual_paper_ids) & expected) / len(expected)
```

- [ ] **Step 4: Run the retrieval test and confirm GREEN**

Run the command from Step 2.

Expected: all retrieval cases pass.

- [ ] **Step 5: Check the task diff**

Run:

```powershell
git diff -- paper_agent/eval tests/test_eval_metrics.py
git status --short
```

Confirm only the intended Evaluation package and metric test are new.

### Task 2: Claim-level rates

**Files:**

- Modify: `paper_agent/eval/metrics.py`
- Modify: `tests/test_eval_metrics.py`

- [ ] **Step 1: Add failing tests for evidence coverage and unsupported rate**

Add imports and tests using the existing `ReportClaim` model:

```python
from paper_agent.eval.metrics import evidence_coverage, unsupported_claim_rate
from paper_agent.schemas import ReportClaim


def test_evidence_coverage_counts_non_empty_evidence_lists():
    claims = [
        ReportClaim(claim="A", evidence_ids=["ev-1"]),
        ReportClaim(claim="B", evidence_ids=[]),
    ]
    assert evidence_coverage(claims) == 0.5


def test_evidence_coverage_returns_zero_for_no_claims():
    assert evidence_coverage([]) == 0.0


def test_evidence_coverage_returns_one_when_all_claims_have_evidence():
    claims = [
        ReportClaim(claim="A", evidence_ids=["ev-1"]),
        ReportClaim(claim="B", evidence_ids=["ev-2"]),
    ]
    assert evidence_coverage(claims) == 1.0


def test_unsupported_claim_rate_counts_only_unsupported():
    claims = [
        ReportClaim(claim="A", evidence_ids=["ev-1"], support_status="supported"),
        ReportClaim(claim="B", evidence_ids=["ev-2"], support_status="weakly_supported"),
        ReportClaim(claim="C", evidence_ids=[], support_status="unsupported"),
    ]
    assert unsupported_claim_rate(claims) == pytest.approx(1 / 3)


def test_unsupported_claim_rate_returns_zero_for_no_claims():
    assert unsupported_claim_rate([]) == 0.0
```

- [ ] **Step 2: Run every new behavior test and confirm RED**

Run:

```powershell
python -m pytest tests/test_eval_metrics.py::test_evidence_coverage_counts_non_empty_evidence_lists -q
python -m pytest tests/test_eval_metrics.py::test_evidence_coverage_returns_zero_for_no_claims -q
python -m pytest tests/test_eval_metrics.py::test_evidence_coverage_returns_one_when_all_claims_have_evidence -q
python -m pytest tests/test_eval_metrics.py::test_unsupported_claim_rate_counts_only_unsupported -q
python -m pytest tests/test_eval_metrics.py::test_unsupported_claim_rate_returns_zero_for_no_claims -q
```

Expected: each focused node fails because its metric is not implemented. Record each
RED result rather than treating one collection failure as evidence for every
behavior.

- [ ] **Step 3: Implement the two minimal claim metrics**

Add:

```python
from paper_agent.schemas import ReportClaim


def evidence_coverage(claims: list[ReportClaim]) -> float:
    if not claims:
        return 0.0
    return sum(bool(claim.evidence_ids) for claim in claims) / len(claims)


def unsupported_claim_rate(claims: list[ReportClaim]) -> float:
    if not claims:
        return 0.0
    return sum(claim.support_status == "unsupported" for claim in claims) / len(claims)
```

- [ ] **Step 4: Run metric tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_eval_metrics.py -q
```

Expected: all tests written through Task 2 pass.

### Task 3: Citation validity and range invariants

**Files:**

- Modify: `paper_agent/eval/metrics.py`
- Modify: `tests/test_eval_metrics.py`

- [ ] **Step 1: Add an Evidence factory and failing citation tests**

Add:

```python
from paper_agent.eval.metrics import citation_validity
from paper_agent.schemas import Evidence


def _evidence(evidence_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id="p1",
        chunk_id="p1:chunk:001",
        claim_type="retrieved",
        quote="Source text.",
        relevance_score=0.9,
    )


@pytest.mark.parametrize(
    ("citation_ids", "valid_ids", "score"),
    [
        (["ev-1", "ev-2"], ["ev-1", "ev-2"], 1.0),
        (["ev-1", "missing"], ["ev-1"], 0.5),
        (["missing"], ["ev-1"], 0.0),
        ([], ["ev-1"], 0.0),
        (["missing"], [], 0.0),
        (["ev-1", "ev-1", "missing"], ["ev-1"], 2 / 3),
    ],
)
def test_citation_validity_counts_reference_occurrences(
    citation_ids, valid_ids, score
):
    claims = [ReportClaim(claim="A", evidence_ids=citation_ids)]
    evidence = [_evidence(evidence_id) for evidence_id in valid_ids]
    assert citation_validity(claims, evidence) == pytest.approx(score)


def test_citation_validity_counts_duplicates_across_claims():
    claims = [
        ReportClaim(claim="A", evidence_ids=["ev-1"]),
        ReportClaim(claim="B", evidence_ids=["ev-1", "missing"]),
    ]
    assert citation_validity(claims, [_evidence("ev-1")]) == pytest.approx(2 / 3)
```

Add a range-invariant test that calls all four metrics with representative inputs
and asserts `0.0 <= value <= 1.0` for every result.

- [ ] **Step 2: Run every citation behavior test and confirm RED**

Run:

```powershell
python -m pytest tests/test_eval_metrics.py::test_citation_validity_counts_reference_occurrences -q
python -m pytest tests/test_eval_metrics.py::test_citation_validity_counts_duplicates_across_claims -q
python -m pytest tests/test_eval_metrics.py::test_metric_results_stay_in_unit_interval -q
```

Expected: both focused nodes fail because the citation metric is not implemented.
The parametrized node reports every listed boundary case as failed. Record the RED
output before implementation.

- [ ] **Step 3: Implement occurrence-based citation validity**

Add:

```python
from paper_agent.schemas import Evidence, ReportClaim


def citation_validity(
    claims: list[ReportClaim],
    evidence: list[Evidence],
) -> float:
    citations = [
        evidence_id
        for claim in claims
        for evidence_id in claim.evidence_ids
    ]
    if not citations:
        return 0.0
    valid_ids = {item.evidence_id for item in evidence}
    return sum(evidence_id in valid_ids for evidence_id in citations) / len(citations)
```

- [ ] **Step 4: Run all metric tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_eval_metrics.py -q
```

Expected: all metric cases and range assertions pass.

- [ ] **Step 5: Run a chunk checkpoint**

Run:

```powershell
python -m pytest tests/test_eval_metrics.py -q
git diff --check
git status --short
```

Record the pass count and confirm no files outside the allowed list changed.

## Chunk 2: Fixture Runner

### Task 4: Typed per-case evaluation

**Files:**

- Create: `paper_agent/eval/runner.py`
- Create: `tests/test_eval_runner.py`

- [ ] **Step 1: Write failing `evaluate_case` tests**

Create `tests/test_eval_runner.py` with local `Evidence` and `ReportClaim` factories.
Test that `evaluate_case` returns exactly the four expected metric keys and known
values for one partial case.

Add a second test:

```python
def test_evaluate_case_rejects_duplicate_evidence_ids():
    evidence = [_evidence("ev-1"), _evidence("ev-1")]
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        evaluate_case(
            expected_paper_ids=[],
            actual_paper_ids=[],
            claims=[],
            evidence=evidence,
        )
```

- [ ] **Step 2: Run runner tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_eval_runner.py::test_evaluate_case_returns_all_metrics -q
python -m pytest tests/test_eval_runner.py::test_evaluate_case_rejects_duplicate_evidence_ids -q
```

Expected: each node independently fails because the runner module or function does
not exist. Record both RED results.

- [ ] **Step 3: Implement `evaluate_case`**

Create `paper_agent/eval/runner.py` with metric imports and:

```python
def evaluate_case(
    *,
    expected_paper_ids: list[str],
    actual_paper_ids: list[str],
    claims: list[ReportClaim],
    evidence: list[Evidence],
) -> dict[str, float]:
    evidence_ids = [item.evidence_id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate evidence_id")
    return {
        "retrieval_hit_rate": retrieval_hit_rate(
            actual_paper_ids, expected_paper_ids
        ),
        "evidence_coverage": evidence_coverage(claims),
        "unsupported_claim_rate": unsupported_claim_rate(claims),
        "citation_validity": citation_validity(claims, evidence),
    }
```

- [ ] **Step 4: Run runner tests and confirm GREEN**

Run the Task 4 focused command and record the result.

### Task 5: Deterministic JSON fixture evaluation

**Files:**

- Create: `tests/fixtures/eval_cases.json`
- Modify: `paper_agent/eval/runner.py`
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: Create deterministic fixture cases**

Create at least two cases:

- a partial-retrieval case with mixed claim support and mixed citation validity;
- an empty-boundary case with no expected papers, claims, citations, or evidence.

Use complete `ReportClaim` and `Evidence` JSON objects accepted by existing schemas.
Keep all identifiers synthetic and stable.

- [ ] **Step 2: Add the basic fixture-entry test and confirm RED**

Write one test that passes the repository fixture as a `Path` and asserts the exact
ordered `cases` entries and their metric dictionaries. Run only that node:

```powershell
python -m pytest tests/test_eval_runner.py::test_evaluate_fixture_returns_case_metrics -q
```

Expected: FAIL because `evaluate_fixture` does not exist. Record RED.

- [ ] **Step 3: Implement minimal fixture loading and per-case evaluation**

Implement UTF-8 JSON loading with `fixture_path = Path(path)`, require a top-level list, read the five required
fields from each valid fixture case, construct `ReportClaim` and `Evidence`, call
`evaluate_case`, and return `{"cases": [...]}` only. Do not implement summary or
the full validation contract yet.

Run the Step 2 node and confirm GREEN.

- [ ] **Step 4: Add summary and empty-fixture tests and confirm RED**

Add separate tests for exact macro averages and for an empty list returning zero
metrics with `case_count == 0`. Run each node separately. Expected: both fail
because the minimal result has no `summary`.

- [ ] **Step 5: Implement macro aggregation and confirm GREEN**

Build:

```python
{
    "cases": [{"case_id": case_id, "metrics": metrics}, ...],
    "summary": {
        "case_count": len(case_results),
        **macro_metric_values,
    },
}
```

Use equal case weights, return `0.0` for every metric when there are no cases, and
do not round. Run both Step 4 nodes and confirm GREEN.

- [ ] **Step 6: Add determinism and path-type tests and record initial results**

Add separate tests asserting repeated calls are equal and that a `Path` and its
`str` representation return equal dictionaries. Because the minimal entry point
already normalizes with `Path(path)` and is pure, these tests may be initial GREEN.
Record the actual initial results as already-satisfied invariants rather than
manufacturing failures.

- [ ] **Step 7: Correct any determinism or path-type failure and confirm GREEN**

If either Step 6 invariant fails, make the smallest correction at the I/O boundary
or remove the identified nondeterministic state, then rerun both nodes. Do not add
clocks, randomness, caches, network, models, or database dependencies.

- [ ] **Step 8: Add required-structure and type-validation tests and confirm RED**

Using `tmp_path`, add and individually run tests for:

- non-list top level;
- non-dictionary case;
- every missing required field (`case_id`, `expected_paper_ids`,
  `actual_paper_ids`, `claims`, and `evidence`) in a parametrized test;
- blank or non-string `case_id`;
- paper-ID fields that are not `list[str]`;
- claims and evidence values that are not lists.

Expected: the non-list-top-level test should be initial GREEN because Step 3 already
implements that basic guard. The other focused tests should fail because the
minimal loader leaks `KeyError` or accepts/coerces invalid structure instead of
raising the specified `ValueError`. Record every actual result and do not weaken an
already-correct guard to manufacture RED.

- [ ] **Step 9: Implement explicit structure validation and confirm GREEN**

Add required-field and metric-name constants plus small helpers that validate the
structure without coercion. Raise `ValueError` messages containing the case ID
when available and the invalid field name. Run every Step 8 node and confirm GREEN.

- [ ] **Step 10: Add identity and schema-diagnostic tests and confirm RED**

Add and individually run tests for:

- duplicate case IDs;
- duplicate Evidence IDs delegated to `evaluate_case`;
- invalid `ReportClaim` data;
- invalid `Evidence` data;
- diagnostic messages containing both case ID and invalid field path when
  available.

Expected: duplicate Evidence rejection should be initial GREEN because the fixture
entry point already delegates to `evaluate_case`. Raw invalid schema data may also
already raise Pydantic `ValidationError`, a `ValueError` subclass. Duplicate case
IDs and the stronger diagnostic assertions for case ID plus field path should RED
because cross-case identity tracking and diagnostic wrapping have not been
implemented. Record the actual results separately.

- [ ] **Step 11: Implement identity and schema diagnostics and confirm GREEN**

Track seen case IDs. Let `evaluate_case` remain the single duplicate-Evidence
validator. Catch Pydantic `ValidationError`, extract the first error location with
`error["loc"]`, join its components into a field path, and raise a `ValueError`
whose message contains both the case ID and field path. Preserve the original
exception as the cause. Run all Step 10 nodes and confirm GREEN.

Do not introduce new Pydantic models or modify `paper_agent/schemas.py`.

- [ ] **Step 12: Add optional-query and malformed-JSON tests**

Add tests proving that a case without `query` evaluates successfully and that
adding or changing `query` does not change metrics. These may already pass because
the loader ignores unknown optional provenance; record their actual initial result
instead of manufacturing RED.

Add a malformed JSON syntax test and verify that `json.JSONDecodeError` propagates.
This is accepted because it is a standard-library `ValueError` subclass with line
and column diagnostics. If the current implementation already propagates it, record
the initial GREEN as an already-satisfied boundary contract.

- [ ] **Step 13: Run all runner tests and confirm GREEN**

```powershell
python -m pytest tests/test_eval_runner.py -q
```

Expected: all runner, validation, aggregation, determinism, path, provenance, and
diagnostic tests pass.

- [ ] **Step 14: Run the focused Evaluation suite**

Run:

```powershell
python -m pytest tests/test_eval_metrics.py tests/test_eval_runner.py -q
```

Record the exact result.

## Chunk 3: Documentation and Final Verification

### Task 6: Evaluation documentation

**Files:**

- Create: `docs/evaluation.md`

- [ ] **Step 1: Document formulas and directions**

Document all four formulas, `[0, 1]` ranges, empty-input behavior, duplicate paper
set semantics, duplicate citation occurrence semantics, and which direction is
better for each metric.

- [ ] **Step 2: Document fixture and runner usage**

Show a small JSON case and Python examples for `evaluate_case` and
`evaluate_fixture`. State that fixtures are versioned offline contract data rather
than a complete public benchmark.

- [ ] **Step 3: Document limitations and roadmap**

Explicitly state that v1 does not prove claim-evidence entailment, answer factual
correctness, completeness, or total RAG quality. Describe the future public
retrieval benchmark and human-calibrated semantic evaluation layers without
implementing them.

- [ ] **Step 4: Review documentation against the spec**

Search for stale terms and confirm the documentation does not claim pipeline
integration, database support, HTML output, LLM judging, vector retrieval, or
reranking.

### Task 7: Final verification and delivery audit

**Files:**

- Review all files listed in this plan.

- [ ] **Step 1: Run focused tests**

```powershell
python -m pytest tests/test_eval_metrics.py tests/test_eval_runner.py -q
```

- [ ] **Step 2: Run the full suite**

```powershell
python -m pytest -q
```

Compare the pass count to the baseline of 36 tests.

- [ ] **Step 3: Run repository checks**

```powershell
git diff --check
git status --short --branch
```

- [ ] **Step 4: Review the complete diff**

Confirm:

- only allowed Evaluation, test, fixture, plan, and documentation files changed;
- no debug output or stale package names remain;
- no shared forbidden files changed;
- no network, model, database, clock, or random dependency exists;
- no pipeline integration, HTML, vector retrieval, or reranking was added.

- [ ] **Step 5: Deliver without additional Git mutation**

Report formulas, changed files, every RED/GREEN command and result, focused and full
test results, test-count growth from 36, known limitations, shared-file overlap,
and actual commit/push/PR status. Do not stage, commit, push, or create a PR without
new explicit authorization.
