# Evaluation Dataset Provenance Registry

This document is the human-readable registry of real evaluation dataset
provenance. It records source, version, license, redistribution decision,
locally verified SHA-256, reviewer identity, and review date for every
upstream asset used by MOMO Scholar evaluation.

The converter mechanically checks required fields, exact asset types, raw file
hashes, strict upstream shapes, references, and deterministic output hashes.
It does not infer licenses, replace human license review, or decide whether a
license is compatible with a particular distribution.

Review required: any upstream version, URL, hash, license, or redistribution
change must receive a new human provenance review before materialization.

## Required asset record

Before converting a real asset, record all of these values independently for
each file:

- dataset source and asset type;
- pinned upstream version and exact source URL;
- asset-specific license identifier;
- redistribution decision: `allowed`, `disallowed`, or `metadata-only`;
- locally verified lowercase SHA-256;
- byte length of the raw upstream file;
- reviewer identity (stable pseudonym) and review date.

## SciFact

| Field | Value |
|---|---|
| Source | allenai/scifact |
| GitHub URL | https://github.com/allenai/scifact |
| Pinned version | commit `68b98a56d93e0f9da0d2aab4e6c3294699a0f72e` (2023-10-15) |
| Data URL | https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz |
| Archive SHA-256 | `11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be` |
| Archive byte length | 3115079 |
| Paper | arXiv:2004.14974 (EMNLP 2020) |

### Asset: claims-evidence

| Field | Value |
|---|---|
| Asset type | claims-evidence |
| Upstream file | `claims_dev.jsonl` (from `data.tar.gz`) |
| License | CC-BY-4.0 |
| Redistribution | allowed |
| SHA-256 | `86f0435d08fdb65d1aa41d1472684f57e6e71930626497bdf4d7a9ec1a632217` |
| Byte length | 65007 |
| Reviewer | codex-reviewer |
| Review date | 2026-07-28 |

### Asset: abstracts

| Field | Value |
|---|---|
| Asset type | abstracts |
| Upstream file | `corpus.jsonl` (from `data.tar.gz`) |
| License | ODC-By-1.0 |
| Redistribution | attribution-required |
| SHA-256 | `b8d6c89624cb2ed74dee8938effc4f5d8bd2086887880af8110d64be4ceade62` |
| Byte length | 8307875 |
| Reviewer | codex-reviewer |
| Review date | 2026-07-28 |

The SciFact claims/evidence annotations are released under CC-BY-4.0. The
corpus abstracts are sourced from S2ORC and carry the ODC-By-1.0 license.
These are separate, asset-specific licenses; the repository code license
(Apache-2.0) is not a substitute for either dataset asset license.

The S3 URL uses the `release/latest` path. The pinned GitHub commit
`68b98a56d93e0f9da0d2aab4e6c3294699a0f72e` identifies the repository state
at the time of this review. If the S3 `latest` tarball is updated, the
SHA-256 values above will not match and conversion must be blocked until a
new review is completed.

## QASPER

| Field | Value |
|---|---|
| Source | allenai/qasper |
| HuggingFace URL | https://huggingface.co/datasets/allenai/qasper |
| Pinned version | 0.3.0 |
| Data URL | https://qasper-dataset.s3.us-west-2.amazonaws.com/qasper-train-dev-v0.3.tgz |
| Archive SHA-256 | `a28fdf966db827bcee3d873107d6b6669864fb7ca8fbf73a192f5e39191bdb5a` |
| Archive byte length | 10835856 |
| Homepage | https://allenai.org/data/qasper |
| Paper | arXiv:2105.03011 (NAACL 2021) |

### Asset: questions-answers-and-corpus

| Field | Value |
|---|---|
| Asset type | questions-answers-and-corpus |
| Upstream file | `qasper-dev-v0.3.json` (from `qasper-train-dev-v0.3.tgz`) |
| License | CC-BY-4.0 |
| Redistribution | allowed |
| SHA-256 | `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93` |
| Byte length | 11398686 |
| Reviewer | codex-reviewer |
| Review date | 2026-07-28 |

The QASPER dataset license is CC-BY-4.0, confirmed from the HuggingFace
loading script (`qasper.py`) which declares `_LICENSE = "CC BY 4.0"` and
version `_VERSION = "0.3.0"`. The full paper text is extracted from S2ORC
(Lo et al., 2020). The dev split contains 281 papers with 1005 questions.

## Validation materialization policy

The frozen 60-case Validation input is selected only from converter-emitted
cases whose Gold Evidence can be represented without inventing a locator.
QASPER annotations with no evidence, table/figure placeholders, section-title
evidence, or evidence that does not uniquely match one full-text paragraph are
not emitted as `EvalCase` records. Their upstream annotations remain unchanged
in the ignored raw asset.

Eligible case IDs are ranked independently for SciFact and QASPER by lowercase
SHA-256 of the UTF-8 case ID. The first 20 cases per source form the 40-case
Retrieval track; the next 10 cases per source form the disjoint 20-case Citation
track. This produces exactly 60 unique case IDs with 30 cases per source while
leaving all answers, claims, evidence quotes, locators, and relevance grades
unchanged from converter output.

Downloaded archives, extracted source files, converted JSONL, receipts,
manifests, Gold judgments, and prepared experiment inputs stay under ignored
`evaluations/` paths. This policy and converter code are committable; the
licensed and generated records are not.

## Synthetic fixtures

Files under `tests/fixtures/evaluation/upstream-format/` are fictional,
repository-authored shape fixtures covered by their own CC0 notice. They
contain no real SciFact or QASPER content. Their cases, counts, hashes,
licenses, receipts, and metric values are not baseline evidence and must not
be used to claim real-data readiness or evaluation quality.
