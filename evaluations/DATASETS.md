# Evaluation Dataset Provenance Registry

This document defines the review boundary for evaluation dataset conversion.
It is not a registry of approved real assets and contains no source records,
download locations, verified real-data hashes, or reviewer approvals.

## Required asset record

Before converting a real asset, record all of these values independently for
each file:

- dataset source and asset type;
- pinned upstream version and exact source URL;
- asset-specific license identifier;
- redistribution decision: `allowed`, `disallowed`, or `metadata-only`;
- locally verified lowercase SHA-256;
- reviewer identity and review date.

The converter mechanically checks required fields, exact asset types, raw file
hashes, strict upstream shapes, references, and deterministic output hashes. It
does not infer licenses, replace human license review, or decide whether a
license is compatible with a particular distribution.

## Dataset status

### SciFact

The engineering design records claims/evidence separately as `CC-BY-4.0` and
abstracts separately as `ODC-By-1.0`. A real conversion still requires pinned
versions, exact asset URLs, locally verified hashes, and a documented
redistribution review. The repository code license is not a substitute for
either dataset asset license.

### QASPER

License and redistribution review required. Do not convert or commit a real
QASPER asset until its exact version, URL, asset-specific terms, decision,
reviewer, review date, and locally verified SHA-256 have been recorded.

## Synthetic fixtures

Files under `tests/fixtures/evaluation/upstream-format/` are fictional,
repository-authored shape fixtures covered by their own CC0 notice. They
contain no real SciFact or QASPER content. Their cases, counts, hashes,
licenses, receipts, and metric values are not baseline evidence and must not be
used to claim real-data readiness or evaluation quality.
