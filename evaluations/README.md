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

## Real Validation Inputs

`DATASETS.md` pins the reviewed SciFact and QASPER versions, archive and inner
asset hashes, byte lengths, licenses, and redistribution decisions. When those
exact assets are available locally, converters can produce the source-balanced
40-case Retrieval and 20-case Citation inputs described there without provider
access.

No real records or generated manifests are committed. A clean clone therefore
still contains only deterministic synthetic fixtures; local materialization
must obtain and verify the registered public assets. Preparing inputs is not a
live smoke or baseline run and does not authorize model calls or provider cost.

The offline human-review workflow is documented in
`docs/citation-human-review.md`. The empty
`templates/citation-calibration-bundle.template.json` records the fields that
must be frozen after generation and before calibration; it contains no reviewer,
case, answer, judgment, or metric data.
