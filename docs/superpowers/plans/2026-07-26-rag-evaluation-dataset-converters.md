# RAG Evaluation Dataset Converters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Status:** Review gate. Do not execute this plan until the decisions in
"Decisions Required Before Implementation" are approved.

**Goal:** Add deterministic, offline SciFact and QASPER conversion boundaries
that emit frozen `EvalCase` records and a hash-bound, asset-specific conversion
receipt without downloading or committing real upstream data.

**Architecture:** Keep frozen evaluation contracts and the public Loader
unchanged. A small common conversion module validates provenance, hashes raw
inputs, serializes outputs canonically, and returns a receipt; dataset-specific
modules strictly parse pinned upstream shapes and map them to existing
`EvalCase` models. Tests use hand-authored synthetic records in upstream format
with an explicit fixture license notice.

**Tech Stack:** Python 3.10+, Pydantic 2, pytest, standard-library `datetime`,
`hashlib`, `json`, `pathlib`, and `typing`.

## Global Constraints

- Start from `origin/master@3a614b5` in an isolated worktree.
- Do not change `paper_agent.eval.contracts.EvalCase`, related frozen gold
  contracts, `paper_agent.eval.dataset`, or Loader behavior.
- Do not download real SciFact or QASPER assets and do not access providers or
  credentials.
- Do not treat fixture counts, IDs, hashes, or outputs as a baseline.
- Reject unknown fields at every supported upstream and receipt model boundary.
- Hash raw upstream files as bytes before parsing; reject every supplied hash
  mismatch.
- Produce UTF-8, LF-terminated, canonical JSON/JSONL with sorted object keys,
  compact separators, and `ensure_ascii=False`.
- Require caller-supplied conversion time; converter code must not read the
  system clock.
- Keep filesystem I/O at the common boundary and dataset transformations pure.
- Do not push, open a PR, merge, rebase, or modify branches.

---

## Decisions Required Before Implementation

The current engineering design fixes the target contract and high-level data
flow, but it does not fix the following API-significant behavior. The
recommendations below form one coherent minimal V1. Approval of this plan means
approval of these choices; changing one requires updating the interfaces and
literal snapshots below before implementation.

### D1. Public Boundary and Output Ownership

**Recommended:** Expose one common request/result API, with dataset-specific
pure parsers selected by an explicit dataset literal. The converter returns
bytes and validated models; a separate atomic writer owns paths.

```python
DatasetName = Literal["scifact", "qasper"]

class ConversionRequest(FrozenEvalModel):
    dataset: DatasetName
    split: SplitName
    upstream_version: str
    adapter_version: str
    converted_at: datetime
    assets: tuple[ConversionAssetInput, ...]

class ConversionResult(NamedTuple):
    cases: tuple[EvalCase, ...]
    cases_jsonl: bytes
    receipt: ConversionReceipt
    receipt_json: bytes

def convert_dataset(request: ConversionRequest) -> ConversionResult: ...

def write_conversion(
    result: ConversionResult,
    *,
    output_root: Path,
    cases_path: Path,
    receipt_path: Path,
) -> None: ...
```

This avoids two drifting orchestration APIs while keeping SciFact and QASPER
mapping isolated. Alternative A is two unrelated public converter functions;
it duplicates provenance and serialization logic. Alternative B is a plugin
registry; it adds extension machinery with no current consumer.

### D2. Case Granularity

**Recommended:** Emit only content-dependent cases in this chunk:

- SciFact: one `claim_verification` case per
  `(claim_id, cited_doc_id, evidence_set_index)`.
- QASPER: one `single_paper_qa` case per
  `(paper_id, question_id, annotation_id)`.

This preserves alternative rationales and annotator answers without widening
the frozen `EvalCase` schema. It deliberately defers SciFact
`paper_retrieval` and both datasets' `evidence_retrieval` projections: the
existing contract requires a complete allowed corpus per retrieval case, and
the design does not decide whether that corpus is the full upstream collection
or a curated candidate pool. Emitting retrieval cases now would guess a gold
retrieval universe.

Rejected alternative A merges alternatives into one case, which incorrectly
makes every alternative evidence span required and cannot represent conflicting
QASPER answers. Rejected alternative B chooses the first annotation/rationale,
which silently discards provenance.

### D3. QASPER Answer Projection

**Recommended:** For each annotation, map answer fields in this precedence:

1. `unanswerable == true` -> `answer=None`, `unanswerable=True`;
2. non-blank `free_form_answer` -> that exact string;
3. non-empty `extractive_spans` -> join exact spans with `"\n"`;
4. non-null `yes_no` -> lowercase `"yes"` or `"no"`;
5. otherwise reject the annotation.

Evidence paragraphs remain separate `ReferenceEvidence` entries. This is a
lossless per-annotation projection except that multiple extractive spans use a
documented newline representation.

### D4. Content Hash Materialization

**Recommended:** Define the content verified by `CorpusPaper.content_sha256`
as the exact UTF-8 bytes returned by these pure functions:

```python
def materialize_scifact_content(record: SciFactCorpusRecord) -> bytes:
    return ("\n".join(record.abstract) + "\n").encode("utf-8")

def materialize_qasper_content(record: QasperPaperRecord) -> bytes:
    paragraphs = [
        paragraph
        for section in record.full_text
        for paragraph in section.paragraphs
    ]
    return ("\n".join(paragraphs) + "\n").encode("utf-8")
```

Section names are locators, not content. No whitespace normalization is
performed. This makes hashes reproducible from upstream JSON while matching
the quote-bearing text. A later acquisition component must use the same
materializers or explicitly migrate the hash contract.

### D5. Receipt Timestamp and Deterministic Bytes

**Recommended:** `converted_at` is mandatory input, timezone-aware, normalized
to UTC, and serialized with seconds precision as `YYYY-MM-DDTHH:MM:SSZ`.
Repeated conversion means identical request values, including this timestamp.
The converter never reads wall-clock time. This reconciles the design's
timestamp requirement with byte stability.

### D6. License and Fixture Policy

**Recommended:** A conversion asset carries both facts and a reviewed decision:

```python
class ConversionAssetInput(FrozenEvalModel):
    asset_type: str
    path: Path
    expected_sha256: str
    source_url: str
    license_id: str
    redistribution: Literal["allowed", "disallowed", "metadata-only"]
    reviewer: str
    review_date: date
```

- SciFact requires exactly `claims-evidence` and `abstracts` assets.
- QASPER requires exactly one `questions-answers-and-corpus` asset.
- Every non-blank field and lowercase SHA-256 is mandatory.
- Conversion may run for all three decisions, but `may_commit_transformed`
  is true only when every asset is `allowed`.
- No code-license inference or dataset-wide fallback is permitted.
- The receipt repeats every asset independently and records its actual hash.
- The tests use synthetic upstream-format data authored for this repository,
  covered by `tests/fixtures/evaluation/upstream-format/LICENSE.md`. The fixture
  registry uses `source_url=https://example.test/...` and `license_id=CC0-1.0`;
  it must not claim that synthetic bytes came from SciFact or QASPER.
- Dataset-name-specific production license expectations are documented in
  `evaluations/DATASETS.md`: SciFact claims/evidence `CC-BY-4.0`, SciFact
  abstracts `ODC-By-1.0`; QASPER remains "review required" until an
  asset/version-specific decision is supplied. The converter enforces
  completeness and consistency, not legal conclusions.

This separates mechanical validation from legal review. Hard-coding a QASPER
license would contradict the current engineering design and safety template.

---

## Proposed File Structure

- Create `paper_agent/eval/datasets/__init__.py`: narrow public conversion
  exports.
- Create `paper_agent/eval/datasets/conversion.py`: request/receipt models,
  canonical serialization, hashing, orchestration, and atomic writer.
- Create `paper_agent/eval/datasets/scifact.py`: strict upstream models,
  materialization, and pure SciFact mapping.
- Create `paper_agent/eval/datasets/qasper.py`: strict upstream models,
  materialization, and pure QASPER mapping.
- Create `tests/eval/datasets/test_conversion.py`: common boundary, receipt,
  hash, serialization, and write-failure tests.
- Create `tests/eval/datasets/test_scifact.py`: upstream validation and mapping.
- Create `tests/eval/datasets/test_qasper.py`: upstream validation and mapping.
- Create `tests/fixtures/evaluation/upstream-format/LICENSE.md`: explicit
  synthetic fixture origin and redistribution terms.
- Create `tests/fixtures/evaluation/upstream-format/scifact/claims.jsonl` and
  `corpus.jsonl`: two tiny synthetic records covering support/refute and
  alternative rationale behavior.
- Create `tests/fixtures/evaluation/upstream-format/qasper/qasper.json`: one
  tiny synthetic paper with answerable and unanswerable annotations.
- Create `tests/fixtures/evaluation/upstream-format/registry.json`: test-only,
  asset-specific provenance and license decisions for the synthetic bytes.
- Create `evaluations/DATASETS.md`: human registry rules and unresolved real
  asset decisions; no real records, hashes, reviewer identities, or approval.
- Modify `paper_agent/eval/__init__.py`: no change. Conversion stays under the
  explicit `paper_agent.eval.datasets` namespace.

## Receipt Contract

The proposed receipt is strict and frozen:

```python
class ConversionAssetReceipt(FrozenEvalModel):
    asset_type: str
    source_url: str
    license_id: str
    redistribution: Literal["allowed", "disallowed", "metadata-only"]
    reviewer: str
    review_date: date
    upstream_sha256: str
    byte_length: StrictInt

class ConversionReceipt(FrozenEvalModel):
    schema_version: Literal["1.0"]
    dataset: DatasetName
    split: SplitName
    upstream_version: str
    adapter_version: str
    converted_at: datetime
    assets: tuple[ConversionAssetReceipt, ...]
    case_ids: tuple[str, ...]
    case_count: StrictInt
    cases_sha256: str
    may_commit_transformed: StrictBool
```

Assets are sorted by `asset_type`; cases are sorted by `case_id`. The
`cases_sha256` hashes the exact emitted `cases_jsonl` bytes. Receipt JSON is a
single canonical object plus LF. Paths are intentionally excluded so moving a
conversion does not change its receipt.

---

### Task 1: Common Provenance, Receipt, and Canonical Bytes

**Files:**
- Create: `paper_agent/eval/datasets/__init__.py`
- Create: `paper_agent/eval/datasets/conversion.py`
- Create: `tests/eval/datasets/__init__.py`
- Create: `tests/eval/datasets/test_conversion.py`

**Interfaces:**
- Produces: `ConversionAssetInput`, `ConversionAssetReceipt`,
  `ConversionRequest`, `ConversionReceipt`, `ConversionResult`,
  `ConversionValidationError`, `canonical_json_bytes`,
  `canonical_jsonl_bytes`, `convert_dataset`, and `write_conversion`.
- Consumes: existing `FrozenEvalModel`, `EvalCase`, and `SplitName` without
  modifying them.

- [ ] **Step 1: Write strict model RED tests**

Add literal tests proving unknown fields, blank provenance, naive timestamps,
invalid review dates, uppercase/short hashes, booleans used as byte lengths,
duplicate asset types, duplicate case IDs, and inconsistent `case_count` are
rejected. Assert Pydantic error locations, not complete error strings.

- [ ] **Step 2: Run the model tests and verify RED**

Run:

```powershell
python -m pytest tests/eval/datasets/test_conversion.py -k "model or unknown or blank or timestamp or hash or duplicate or count" -q
```

Expected: collection fails because `paper_agent.eval.datasets.conversion` does
not exist.

- [ ] **Step 3: Implement the minimal strict models**

Use `FrozenEvalModel`, `StrictInt`, `StrictBool`, exact literals, non-blank
validators, lowercase `^[0-9a-f]{64}$` hashes, unique asset/case identities,
and cross-field count validation. Do not add a generic registry framework.

- [ ] **Step 4: Run the focused model tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Write canonical serialization and receipt RED tests**

Use hand-derived byte literals. Prove:

- object key order and input JSON formatting do not affect output;
- Unicode is UTF-8, not ASCII escaped;
- JSON and JSONL have exactly one final LF and no CR;
- cases are ordered by `case_id`;
- assets are ordered by `asset_type`;
- `cases_sha256` equals SHA-256 of the exact JSONL bytes;
- identical requests produce byte-identical cases and receipt;
- changing `converted_at`, an input byte, or a provenance field changes the
  appropriate receipt bytes/hash.

- [ ] **Step 6: Run serialization tests and verify RED**

Run:

```powershell
python -m pytest tests/eval/datasets/test_conversion.py -k "canonical or byte or receipt or deterministic" -q
```

Expected: fails because serializers and receipt builder are absent.

- [ ] **Step 7: Implement canonical serialization and receipt construction**

Serialize `model_dump(mode="json")` with:

```python
json.dumps(
    payload,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
).encode("utf-8") + b"\n"
```

Normalize the supplied timestamp to UTC seconds before model construction.
Never call `datetime.now`, `datetime.utcnow`, or `time.time`.

- [ ] **Step 8: Run all common conversion tests and verify GREEN**

Run:

```powershell
python -m pytest tests/eval/datasets/test_conversion.py -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit the independently verified boundary**

```powershell
git add paper_agent/eval/datasets tests/eval/datasets
git commit -m "feat: add deterministic evaluation conversion boundary"
```

### Task 2: SciFact Strict Converter

**Files:**
- Create: `paper_agent/eval/datasets/scifact.py`
- Create: `tests/eval/datasets/test_scifact.py`
- Create: `tests/fixtures/evaluation/upstream-format/LICENSE.md`
- Create: `tests/fixtures/evaluation/upstream-format/scifact/claims.jsonl`
- Create: `tests/fixtures/evaluation/upstream-format/scifact/corpus.jsonl`
- Create: `tests/fixtures/evaluation/upstream-format/registry.json`
- Modify: `paper_agent/eval/datasets/conversion.py`

**Interfaces:**
- Consumes: `ConversionRequest` with exact asset types `claims-evidence` and
  `abstracts`.
- Produces:

```python
def convert_scifact(
    *,
    split: SplitName,
    claims_bytes: bytes,
    corpus_bytes: bytes,
) -> tuple[EvalCase, ...]: ...

def materialize_scifact_content(record: SciFactCorpusRecord) -> bytes: ...
```

- [ ] **Step 1: Add explicitly licensed synthetic upstream-format fixtures**

The notice states that all records are fictional, were authored for MOMO
Scholar tests, contain no upstream dataset text or identifiers, are available
under CC0-1.0, and cannot establish upstream license review. Fixture records
mirror the complete supported SciFact shapes:

```json
{"doc_id":101,"title":"Synthetic study","abstract":["First sentence.","Second sentence."],"structured":false}
{"id":201,"claim":"The synthetic result is supported.","evidence":{"101":[{"label":"SUPPORT","sentences":[1]}]},"cited_doc_ids":[101]}
```

Include a second `REFUTE` claim and one claim with two evidence sets so
cardinality and ordering are observable.

- [ ] **Step 2: Write upstream shape and linkage RED tests**

Prove rejection of unknown fields at every nested level, duplicate IDs,
missing cited corpus documents, evidence documents absent from
`cited_doc_ids`, unsupported labels, empty sentence lists, negative/out-of-range
sentence indexes, duplicate indexes, malformed JSONL with physical line
context, and invalid UTF-8 without leaking source content into errors.

- [ ] **Step 3: Run strict parsing tests and verify RED**

Run:

```powershell
python -m pytest tests/eval/datasets/test_scifact.py -k "reject or invalid or unknown or duplicate or missing or range or utf" -q
```

Expected: fails because the SciFact parser does not exist.

- [ ] **Step 4: Implement strict SciFact upstream models and linkage checks**

Model only the fields shown in the approved fixture shape with
`extra="forbid"`. Parse JSONL line-by-line, preserve physical line numbers in
sanitized errors, and validate cross-file identities before mapping.

- [ ] **Step 5: Run strict parsing tests and verify GREEN**

Run the Step 3 command. Expected: all selected tests pass.

- [ ] **Step 6: Write mapping and literal snapshot RED tests**

Assert complete literal `EvalCase.model_dump(mode="json")` dictionaries for
SUPPORT and REFUTE. Prove:

- canonical IDs include claim, document, and evidence-set identities;
- `stance` maps to `supported` or `refuted`;
- rationale sentences become ordered evidence with stable upstream locators;
- each quote is the exact indexed sentence;
- content hash is over the D4 materialized bytes;
- alternatives emit separate cases;
- case metadata source/split/domain/difficulty are exact approved literals;
- every output passes `EvalCase.model_validate`;
- repeated conversion yields identical model dumps and JSONL bytes.

- [ ] **Step 7: Run mapping tests and verify RED**

Run:

```powershell
python -m pytest tests/eval/datasets/test_scifact.py -k "map or case or content or deterministic" -q
```

Expected: fails because mapping is absent.

- [ ] **Step 8: Implement the minimal SciFact mapping**

Map only `claim_verification`. Use one corpus paper per emitted case, one
reference claim, and one `ReferenceEvidence` per rationale sentence. Set all
rationale evidence `required=True`, relevance grade `3`, section `"Abstract"`,
and source type `"rationale"`.

- [ ] **Step 9: Route SciFact through the common boundary**

Before parsing, verify raw asset byte lengths and hashes against
`ConversionAssetInput`. Reject missing, extra, duplicated, or mislabeled asset
types. Build the receipt only after every emitted case validates.

- [ ] **Step 10: Run SciFact and common tests and verify GREEN**

Run:

```powershell
python -m pytest tests/eval/datasets/test_scifact.py tests/eval/datasets/test_conversion.py -q
```

Expected: all tests pass.

- [ ] **Step 11: Commit the independently verified converter**

```powershell
git add paper_agent/eval/datasets tests/eval/datasets tests/fixtures/evaluation/upstream-format
git commit -m "feat: add deterministic SciFact converter"
```

### Task 3: QASPER Strict Converter

**Files:**
- Create: `paper_agent/eval/datasets/qasper.py`
- Create: `tests/eval/datasets/test_qasper.py`
- Create: `tests/fixtures/evaluation/upstream-format/qasper/qasper.json`
- Modify: `tests/fixtures/evaluation/upstream-format/registry.json`
- Modify: `paper_agent/eval/datasets/conversion.py`

**Interfaces:**
- Consumes: `ConversionRequest` with exact asset type
  `questions-answers-and-corpus`.
- Produces:

```python
def convert_qasper(
    *,
    split: SplitName,
    dataset_bytes: bytes,
) -> tuple[EvalCase, ...]: ...

def materialize_qasper_content(record: QasperPaperRecord) -> bytes: ...
```

- [ ] **Step 1: Add one fully synthetic QASPER-format paper**

Mirror the complete supported record shape: paper title, abstract, sectioned
full text, one question, stable question ID, and complete annotation objects
with annotation/worker IDs plus `unanswerable`, `extractive_spans`, `yes_no`,
`free_form_answer`, and `evidence`. Include answerable and unanswerable
annotations and evidence text that occurs exactly once in full text.

- [ ] **Step 2: Write upstream shape and linkage RED tests**

Prove rejection of unknown fields at every nested level, duplicate paper,
question, or annotation IDs, blank IDs/question/evidence, invalid answer field
combinations under D3, evidence absent from full text, evidence occurring more
than once without a stable locator, empty full text, malformed JSON, and
invalid UTF-8 with sanitized errors.

- [ ] **Step 3: Run strict parsing tests and verify RED**

Run:

```powershell
python -m pytest tests/eval/datasets/test_qasper.py -k "reject or invalid or unknown or duplicate or evidence or utf" -q
```

Expected: fails because the QASPER parser does not exist.

- [ ] **Step 4: Implement strict QASPER upstream models and linkage checks**

Model the complete approved fixture shape with unknown fields forbidden.
Resolve each evidence string to exactly one `(section_index, paragraph_index)`;
reject ambiguous or missing matches rather than selecting one.

- [ ] **Step 5: Run strict parsing tests and verify GREEN**

Run the Step 3 command. Expected: all selected tests pass.

- [ ] **Step 6: Write mapping and literal snapshot RED tests**

Assert complete literal `EvalCase.model_dump(mode="json")` dictionaries for
free-form, extractive, yes/no, and unanswerable branches. Prove:

- canonical IDs include paper, question, and annotation identities;
- alternative annotations emit separate cases;
- D3 precedence and exact newline joining are followed;
- evidence order follows the annotation, with stable section/paragraph
  locators and exact quotes;
- content hash is over D4 materialized bytes;
- all output passes `EvalCase.model_validate`;
- repeated conversion yields identical model dumps and JSONL bytes.

- [ ] **Step 7: Run mapping tests and verify RED**

Run:

```powershell
python -m pytest tests/eval/datasets/test_qasper.py -k "map or case or answer or content or deterministic" -q
```

Expected: fails because mapping is absent.

- [ ] **Step 8: Implement the minimal QASPER mapping**

Map only `single_paper_qa`. Create one corpus paper and one case per
annotation. Use source type `"annotation"`, relevance grade `3`,
`required=True`, and section/paragraph upstream locators. Apply D3 without
cross-annotator voting or answer synthesis.

- [ ] **Step 9: Route QASPER through the common boundary**

Verify the raw asset hash and length before parsing, reject asset-set errors,
and build the receipt only from validated cases and reviewed input metadata.

- [ ] **Step 10: Run QASPER and all converter tests and verify GREEN**

Run:

```powershell
python -m pytest tests/eval/datasets -q
```

Expected: all tests pass.

- [ ] **Step 11: Commit the independently verified converter**

```powershell
git add paper_agent/eval/datasets tests/eval/datasets tests/fixtures/evaluation/upstream-format
git commit -m "feat: add deterministic QASPER converter"
```

### Task 4: Atomic Writes, Failure Safety, and Registry Documentation

**Files:**
- Modify: `paper_agent/eval/datasets/conversion.py`
- Modify: `tests/eval/datasets/test_conversion.py`
- Create: `evaluations/DATASETS.md`

**Interfaces:**
- Consumes: a complete `ConversionResult` and two distinct destination paths.
- Produces: `write_conversion(...) -> None`; neither destination is considered
  published until both temporary files have been flushed and replaced.

- [ ] **Step 1: Write path and write-failure RED tests**

Prove rejection of identical/resolved-alias destinations, existing
destinations, directories, nonexistent parent directories, and writes outside
the explicitly supplied `output_root`. Inject a narrow replace operation to
prove a failed second replace leaves the newly written cases file without a
receipt, so no receipt can claim an unpublished or different cases file. Error
messages name only destination basenames and do not contain input records.

- [ ] **Step 2: Run writer tests and verify RED**

Run:

```powershell
python -m pytest tests/eval/datasets/test_conversion.py -k "write or path or replace or publish" -q
```

Expected: fails because the atomic writer is absent.

- [ ] **Step 3: Implement the minimal guarded writer**

Resolve and validate both absent destinations under `output_root`; write sibling
temporary files with exclusive creation, flush and `os.fsync`, replace cases
first and receipt last, and clean only temporary files owned by this call.
Never delete or overwrite unrelated paths. Document that replacing two files is
not a filesystem transaction; receipt-last publication is the recovery marker,
and an interrupted receipt-less cases file must be moved aside explicitly
before retrying.

- [ ] **Step 4: Write the human-readable registry**

Document required per-asset fields, receipt/hash relationships, safe local
workflow, fixture-only restrictions, the two known SciFact license identifiers,
and the unresolved QASPER version/URL/license/redistribution reviewer gate. Do
not insert placeholder approvals, hashes, identities, or real source data.

- [ ] **Step 5: Run writer tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit the independently verified writer and documentation**

```powershell
git add paper_agent/eval/datasets/conversion.py tests/eval/datasets/test_conversion.py evaluations/DATASETS.md
git commit -m "feat: publish converter receipts safely"
```

### Task 5: Full Verification and Scope Audit

**Files:**
- Review only.

**Interfaces:**
- Produces: verification evidence and a scoped handoff; no new behavior.

- [ ] **Step 1: Run focused converter tests**

```powershell
python -m pytest tests/eval/datasets -q
```

Expected: all tests pass with no warnings.

- [ ] **Step 2: Re-run frozen contract and Loader tests**

```powershell
python -m pytest tests/eval/test_contracts.py tests/eval/test_dataset.py -q
```

Expected: all tests pass, proving converter additions did not reopen contracts
or Loader behavior.

- [ ] **Step 3: Run the full offline suite**

```powershell
python -m pytest -q
```

Expected: all tests pass. Do not run live-provider or network commands.

- [ ] **Step 4: Verify deterministic artifacts independently**

Run the fixture conversion twice into two temporary directories with the same
explicit timestamp, then compare SHA-256 and bytes for cases and receipts.
Change one source byte and assert conversion fails against the pinned expected
hash. Record exact hashes only in test assertions or test output, never as
baseline evidence.

- [ ] **Step 5: Audit scope and repository safety**

```powershell
git status --short
git diff --check
git diff --stat origin/master...HEAD
git diff --name-only origin/master...HEAD
rg -n "api[_-]?key|authorization:|bearer |provider" paper_agent/eval/datasets tests/eval/datasets tests/fixtures/evaluation/upstream-format evaluations/DATASETS.md
```

Confirm:

- no changes to `paper_agent/eval/contracts.py`,
  `paper_agent/eval/dataset.py`, existing fixture baselines, Pipeline, CLI,
  providers, or credentials;
- no real dataset text, real reviewer identity, placeholder approval, or
  provider configuration;
- fixture documentation clearly forbids baseline interpretation;
- every unknown-field, license/provenance, raw-hash, content-hash, and
  reference-integrity rejection has a RED/GREEN test.

- [ ] **Step 6: Commit only if verification changed scoped files**

Stage explicit paths only. Do not push, open a PR, merge, rebase, or manipulate
branches/worktrees.

## Review Gate

Implementation remains blocked until the reviewer either approves D1-D6 or
supplies replacements for:

1. retrieval-case candidate-corpus semantics;
2. SciFact evidence-set and QASPER annotation cardinality;
3. QASPER answer projection;
4. exact content materialization used by `content_sha256`;
5. caller-supplied timestamp semantics;
6. the mechanical/legal boundary for license decisions and fixture licensing.

Real-data use remains separately blocked after implementation by exact upstream
versions and URLs, asset-specific QASPER terms, redistribution review, reviewer
identity/date, locally verified raw hashes, and approved Gold curation. None of
those decisions are inferred or satisfied by synthetic fixtures.
