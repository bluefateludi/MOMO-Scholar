# Evaluation

MOMO Scholar Evaluation v1 is a deterministic, offline regression layer for
paper retrieval recall, evidence attachment, unsupported-claim frequency, and
citation integrity. Given the same inputs, it always produces the same result.
It does not access the pipeline, a database, the network, a model API, the
clock, or randomness.

## Metrics

Every metric returns a floating-point value in the inclusive range `[0.0, 1.0]`.
Metric functions do not round their results.

### `retrieval_hit_rate`

Let `A` be the set of actual paper IDs and `E` the set of expected paper IDs:

```text
retrieval_hit_rate = |A intersection E| / |E|
```

- Higher is better.
- If `E` is empty, the result is `0.0`.
- If actual IDs are empty while `E` is non-empty, the result is `0.0`.
- Actual and expected IDs are deduplicated before calculation, so repeated paper
  IDs do not change the score.
- IDs use exact string matching. Case and source prefixes are not normalized.
- Unrelated retrieved papers do not reduce this value.

This metric is reference-paper recall, not precision and not a complete measure
of retrieval quality.

### `evidence_coverage`

```text
evidence_coverage =
    claims with non-empty evidence_ids / total claims
```

- Higher is better.
- If there are no claims, the result is `0.0`.
- A claim is covered whenever `evidence_ids` is non-empty.
- This metric does not check whether cited IDs exist. That is measured by
  `citation_validity`.

### `unsupported_claim_rate`

```text
unsupported_claim_rate =
    claims whose support_status is "unsupported" / total claims
```

- Lower is better; this is the only negative-direction v1 metric.
- If there are no claims, the result is `0.0`.
- Only the exact `unsupported` status is counted. `supported` and
  `weakly_supported` are not counted.

### `citation_validity`

Let `V` be the set of evidence IDs in the current run's Evidence collection. Let
`C` be the ordered multiset produced by concatenating every claim's
`evidence_ids`:

```text
citation_validity =
    citation occurrences in C whose ID belongs to V / total occurrences in C
```

- Higher is better.
- If there are no citation occurrences, the result is `0.0`.
- If citations exist but the Evidence collection is empty, the result is `0.0`.
- Duplicate citations are counted by occurrence. Repeating an ID within one
  claim or across claims adds another item to both the numerator (when valid)
  and denominator.
- Validity means only that the cited ID exists in the current Evidence set. It
  does not mean that the Evidence semantically supports the claim.
- A case containing duplicate `Evidence.evidence_id` values is invalid and the
  runner raises `ValueError`.

The four metrics are reported separately. Evaluation v1 intentionally does not
combine metrics with different meanings and directions into an overall score.

## JSON fixture contract

Fixtures are versioned, offline contract data used for repeatable local tests and
CI. They are small and human-reviewable; they are not presented as a complete
public benchmark. The JSON top level is a list of cases. Each case requires
`case_id`, `expected_paper_ids`, `actual_paper_ids`, `claims`, and `evidence`.
An optional `query` records provenance and readable context but does not affect
v1 metrics.

```json
[
  {
    "case_id": "partial-match",
    "query": "How should scholarly RAG systems be evaluated?",
    "expected_paper_ids": ["paper-1", "paper-2"],
    "actual_paper_ids": ["paper-1", "paper-3"],
    "claims": [
      {
        "claim": "Retrieval and generation should be evaluated separately.",
        "evidence_ids": ["ev-1", "missing"],
        "support_status": "supported"
      }
    ],
    "evidence": [
      {
        "evidence_id": "ev-1",
        "paper_id": "paper-1",
        "chunk_id": "paper-1:chunk:001",
        "claim_type": "retrieved",
        "quote": "Retrieval and generation should be evaluated separately.",
        "relevance_score": 0.9
      }
    ]
  }
]
```

The fixture reader rejects invalid top-level structure, missing or incorrectly
typed required fields, duplicate case IDs, duplicate Evidence IDs, and claims or
Evidence that do not satisfy the existing schemas. Malformed JSON syntax is
reported by the standard JSON decoder.

## Runner usage

Use `evaluate_case` when `ReportClaim` and `Evidence` objects are already in
memory:

```python
from paper_agent.eval.runner import evaluate_case
from paper_agent.schemas import Evidence, ReportClaim

claims = [
    ReportClaim(
        claim="Retrieval and generation should be evaluated separately.",
        evidence_ids=["ev-1"],
        support_status="supported",
    )
]
evidence = [
    Evidence(
        evidence_id="ev-1",
        paper_id="paper-1",
        chunk_id="paper-1:chunk:001",
        claim_type="retrieved",
        quote="Retrieval and generation should be evaluated separately.",
        relevance_score=0.9,
    )
]

metrics = evaluate_case(
    expected_paper_ids=["paper-1", "paper-2"],
    actual_paper_ids=["paper-1", "paper-3"],
    claims=claims,
    evidence=evidence,
)
```

`metrics` is an ordinary dictionary containing exactly the four v1 metric
values. Use `evaluate_fixture` for a versioned JSON file:

```python
from pathlib import Path

from paper_agent.eval.runner import evaluate_fixture

result = evaluate_fixture(Path("tests/fixtures/eval_cases.json"))
```

The returned dictionary contains ordered per-case results and a `summary`. Each
summary metric is the macro average across cases:

```text
summary metric = sum(per-case metric) / number of cases
```

Each case therefore has equal weight, regardless of how many claims or citations
it contains. For an empty fixture, `cases` is empty, `summary.case_count` is `0`,
and all four summary metrics are `0.0`.

## Scope and limitations

Evaluation v1 checks deterministic structural and referential contracts. It does
not establish:

- semantic entailment between a claim and its cited Evidence;
- factual correctness of the generated answer;
- completeness or relevance of the answer;
- retrieval precision or ranking quality;
- an overall RAG quality or trustworthiness score.

In particular, a citation can be valid because its ID exists while its passage is
irrelevant to the claim. Likewise, a non-empty evidence list can yield full
coverage even when the attached Evidence is not useful.

This version has no pipeline integration, database persistence, runtime network
downloads, model or LLM-judge calls, HTML reporting, vector-retrieval changes, or
reranking behavior.

## Future evaluation layers

A future public retrieval benchmark may convert a licensed subset of a scientific
retrieval dataset into the same local JSON format. Converted cases should be
version-pinned and stored locally so normal tests remain offline. That layer may
add Precision@K, Recall@K, MRR, and nDCG@K after dataset selection, licensing
review, and conversion are completed.

A later semantic layer may add human-labeled reference claims and supporting
passages to evaluate claim-Evidence entailment, answer correctness, completeness,
relevance, and overstatement. Human labels should remain the primary reference.
LLM judges may be auxiliary evaluators only after calibration against human-labeled
examples, and they should remain outside the deterministic default test suite.
