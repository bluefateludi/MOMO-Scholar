# Local Evaluation Workspace

This directory is the local workspace for real evaluation inputs and generated
experiment packages. Git ignores everything here except this file,
`DATASETS.md`, and the four empty templates explicitly allowlisted in
`.gitignore`.

Do not commit dataset records, source documents, chunks, Gold judgments,
provider credentials, downloaded archives, caches, model outputs, logs, traces,
or experiment artifacts. Keep real material under ignored paths such as:

```text
evaluations/
|-- datasets/
|-- downloads/
|-- credentials/
|-- cache/
`-- experiments/
```

The templates are curation checklists, not runnable data. They deliberately
contain no source content, URLs, licenses, hashes, judgments, reviewer
identities, provider configuration, or approved spend.

## Required Offline Gate

Before preparing a Development smoke input:

1. Follow `DATASETS.md` and record each upstream asset separately in the
   local license/provenance registry.
2. Obtain a reviewer decision for license compatibility and redistribution.
3. Verify the downloaded asset locally and record its SHA-256.
4. Convert source records through the existing `DatasetManifest`, `EvalCase`,
   `CorpusPaper`, and `Chunk` contracts.
5. Freeze Gold judgments from the authorized source annotations.
6. Generate `corpus-manifest.json`, `gold-judgments.jsonl`, and
   `resolved-config.json` with the existing retrieval benchmark preparation
   command.
7. Review the two-case limit, explicit timeout, model version, and maximum
   provider budget before any separately authorized live command.

## Current Two-Case Status

No real two-case input is present. The repository contains only deterministic
SciFact and QASPER test fixtures with example domains, placeholder content, and
placeholder hashes. They are synthetic test evidence and cannot satisfy the
real-data, provenance, license-review, content-hash, or Gold requirements.

Preparing one SciFact and one QASPER Development case remains blocked until the
source versions and asset URLs are selected, license and redistribution
decisions are reviewed, an authorized offline download is supplied, asset and
content hashes are verified, Gold annotations are approved, and provider
model/timeout/budget choices are authorized. Do not substitute fixture content
for any of these inputs.
