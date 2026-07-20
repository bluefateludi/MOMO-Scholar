# Production Full-Text Survey Design

**Date:** 2026-07-20
**Status:** Approved in conversation; pending written-spec review
**Scope:** Production-oriented local CLI vertical slice for public arXiv papers

## 1. Context

MOMO Scholar currently has a working arXiv search and hybrid evidence-retrieval
stack. It can produce a citation-traceable mini report, but the normal pipeline
still analyzes abstract text, uses deterministic placeholder synthesis, and
writes only a subset of the artifacts needed to explain or audit a run.

This phase turns that technical MVP into a useful local product:

```text
research question
  -> arXiv search
  -> public PDF download
  -> page-aware PDF parsing
  -> section-aware chunks
  -> balanced hybrid evidence retrieval
  -> Qwen structured paper analyses
  -> Qwen cross-paper synthesis
  -> deterministic citation validation
  -> formal Markdown report
```

The target is a production-oriented CLI, not a hosted multi-user service. The
first version intentionally supports only publicly accessible arXiv PDFs and
text-native documents. OCR, arbitrary websites, user-uploaded files, and durable
databases are later phases.

## 2. Goals and Non-Goals

### Goals

- Make PDF-backed analysis the default behavior of `paper-agent run`.
- Retain `--no-pdf` as an explicit, user-selected abstract-only mode.
- Download only public arXiv PDFs through a constrained HTTP boundary.
- Preserve paper, page, section, chunk, and evidence provenance.
- Use DashScope for both embeddings and generation with one
  `DASHSCOPE_API_KEY`.
- Use `text-embedding-v4` for embeddings and exactly `qwen3.7-plus` for
  generation by default.
- Produce schema-validated per-paper analyses and a cross-paper survey.
- Prevent unsupported model claims from entering critical report sections.
- Record terminal status, degradations, attempts, latency, and token usage.
- Keep the normal test suite deterministic and offline.
- Preserve the current retrieval behavior and regression suite.

### Non-Goals

- OCR or scanned-PDF support.
- Non-arXiv websites, Semantic Scholar, OpenAlex, or local PDF uploads.
- Persistent embeddings, SQLite, cross-run caches, or resumable jobs.
- Reranking or learned relevance models.
- Web UI, multi-user isolation, background queues, or CI/CD deployment.
- Exhaustive table, figure, equation, or reference-list reconstruction.
- Guaranteed support for malformed or heavily customized PDF layouts.

## 3. Decisions

### 3.1 Product and provider

- The product remains a local CLI.
- DashScope is the only provider implementation in this phase.
- Generation remains behind a provider interface so another implementation can
  be added without changing analysis or synthesis logic.
- Embeddings and generation share `DASHSCOPE_API_KEY`, but retain separate model,
  endpoint, timeout, and diagnostics settings.
- A missing or invalid key is a terminal configuration/authentication failure
  for the default PDF-plus-Qwen run. The pipeline must not silently present the
  existing deterministic template as an AI-generated formal report.

### 3.2 PDF engine and licensing

The parser uses PyMuPDF. PyMuPDF and MuPDF are dual-licensed under AGPL and a
commercial license. This project chooses the AGPL path because MOMO Scholar is
intended to remain open source.

Before a release that distributes the PyMuPDF-backed application:

- the repository must contain an AGPL-3.0 project license;
- source recipients must receive the complete corresponding source required by
  that license;
- PyMuPDF/MuPDF copyright and license notices must be preserved;
- modifications and build/install instructions must remain available;
- dependency/license documentation must identify PyMuPDF and link to its terms;
- release packaging must not include a proprietary-only component that conflicts
  with AGPL obligations.

Merely making a repository publicly readable is not treated as sufficient
license compliance. If the project later needs proprietary distribution, the
team must obtain an appropriate commercial license or replace PyMuPDF. This is
an engineering compliance decision, not legal advice.

References:

- <https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright>
- <https://www.gnu.org/licenses/agpl-3.0.html>

PyMuPDF becomes a base dependency because PDF analysis is the default product
path. The current optional `pdf` extra is retired. The design uses the
`pymupdf` import name and does not introduce PyMuPDF4LLM or OCR in this phase.

## 4. Architecture

### 4.1 Boundary modules

The system is split into narrow components with explicit inputs and outputs:

| Component | Responsibility | External I/O |
| --- | --- | --- |
| `ArxivSearch` | Retrieve and normalize candidate paper metadata | arXiv HTTP |
| `FullTextDownloader` | Validate and download an arXiv PDF with hard limits | arXiv HTTPS |
| `PdfParser` | Convert PDF bytes into page-aware normalized text | none |
| `SectionAwareChunker` | Produce stable page/section-aware chunks | none |
| `EvidencePackBuilder` | Retrieve and cap evidence independently per paper | embedding API through existing retriever |
| `GenerationProvider` | Generate and validate structured responses | DashScope HTTP |
| `PaperAnalyzer` | Produce evidence-bound findings for one paper | provider interface |
| `SurveySynthesizer` | Produce cross-paper evidence-bound claims | provider interface |
| `CitationChecker` | Validate every referenced Evidence ID | none |
| `ReportRenderer` | Render checked data into Markdown | none |
| `RunRecorder` | Write artifacts, events, usage, and terminal status | local filesystem |

External I/O is kept out of transformation modules. The downloader receives an
injectable `httpx` transport/client, and generation receives a provider
interface. Parser, chunker, citation validation, and rendering are deterministic.

### 4.2 Pipeline orchestration

For each normalized paper:

1. If `--no-pdf` is set, construct an abstract-backed `PaperDocument`.
2. Otherwise validate and download the paper's public arXiv PDF.
3. Parse the PDF into ordered pages and normalize text.
4. If PDF acquisition or parsing fails with an allowed per-paper failure, create
   an abstract-backed document and record a degradation.
5. Create section-aware chunks, retaining page provenance.
6. Retrieve evidence against only that paper's chunks.
7. Build a bounded evidence pack.
8. Ask `qwen3.7-plus` for a schema-valid paper analysis whose findings reference
   only that evidence pack.

After the minimum number of paper analyses succeeds:

1. Ask `qwen3.7-plus` for a schema-valid cross-paper survey.
2. Resolve every model-produced Evidence ID against the run evidence index.
3. Remove unknown references and mark the affected claims unsupported.
4. Exclude unsupported and weak claims from TL;DR and key findings.
5. Persist structured artifacts and render the formal report.
6. Write the terminal run status last.

The pipeline creates the run directory and manifest before external work begins.
Safe intermediate artifacts and structured error events remain available after a
failure. `report.json` and `report.md` are published only after synthesis and
citation validation succeed.

The pipeline creates a fresh retrieval service and therefore a fresh
`InMemoryVectorStore` for each paper. A shared HTTP embedding transport may live
for the whole run, but no vector store or indexed chunks may cross the per-paper
service boundary. The pipeline owns the shared transport and closes it once;
each per-paper service owns and releases only its local retrieval resources.
This prevents a later paper query from returning chunks indexed for an earlier
paper.

## 5. Domain Contracts

All new or migrated persisted, generated, and terminal contracts inherit:

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

This includes `Paper`, `DocumentPage`, `PaperDocument`, `DocumentRecord`,
`Evidence`, `GroundedFinding`, `PaperAnalysis`, `SurveyDraft`,
`CheckedFinding`, `CheckedPaperAnalysis`, `CheckedClaim`,
`RejectedCriticalClaim`, `RetrievalRecord`,
`CheckedSurveyReport`, and `RunManifest`. `Chunk` remains an internal retrieval
contract in this phase. Persisted JSON uses stable UTF-8 serialization.

### 5.1 Documents

```python
ContentSource = Literal["pdf", "abstract"]

class DocumentPage(StrictModel):
    page_number: int
    text: str

class PaperDocument(StrictModel):
    paper_id: str
    content_source: ContentSource
    pages: list[DocumentPage]
    content_sha256: str
    warnings: list[str] = Field(default_factory=list)

class DocumentRecord(StrictModel):
    paper_id: str
    content_source: ContentSource
    content_sha256: str
    page_count: int
    warnings: list[str] = Field(default_factory=list)
    fallback_code: str | None = None
```

Rules:

- `page_number` is one-based for PDFs.
- Abstract-backed documents use a single logical page numbered `1`.
- `content_sha256` hashes the original PDF bytes for PDF documents and the
  normalized UTF-8 abstract for abstract documents.
- An empty `pages` list or pages containing no meaningful text is invalid.
- Raw PDF bytes and full extracted page text are internal transient data.
  `documents.json` is exactly `list[DocumentRecord]`; it contains provenance,
  page counts, hashes, content source, warnings, and fallback code, but not the
  `pages[*].text` payload.
- Chunks and evidence are the persisted textual audit surface.

### 5.2 Chunks and evidence

The existing `Chunk` contract remains the retrieval boundary:

- `chunk_id` is deterministic for the normalized document content;
- `paper_id` identifies the source paper;
- `section` is the nearest recognized section, if any;
- `page` is the one-based starting page;
- `text` is normalized non-empty text;
- `token_count` is the project's deterministic estimate, not provider billing
  tokens.

Chunk IDs follow:

```text
{paper_id}:chunk:{sequence:03d}
```

Identical normalized input and chunking settings must produce identical IDs and
content. The first version does not promise ID stability after the source
content or chunking configuration changes.

Evidence retrieval is performed independently for each paper using the existing
retrieval service:

```text
scoped_run_id = "{run_id}:paper:{paper_id}"
```

This yields globally unique IDs such as:

```text
{run_id}:paper:{paper_id}:ev_001
```

The existing citation check's `{run_id}:` prefix invariant remains valid.
Per-paper retrieval prevents a globally dominant paper from consuming all
evidence positions. `EvidencePackBuilder` preserves retrieval order, removes
duplicate chunk references, and caps the result at
`ANALYSIS_EVIDENCE_PER_PAPER`.

The implementation migrates `Evidence` to retain the provenance already present
on `RetrievalCandidate`:

```python
class Evidence(StrictModel):
    evidence_id: str
    paper_id: str
    chunk_id: str
    section: str | None = None
    page: int | None = None
    claim_type: str
    quote: str
    relevance_score: float = Field(ge=0.0, le=1.0)
```

`evidence.json` is exactly `list[Evidence]`. Chunks are not separately persisted
because each evidence record contains the selected chunk ID, quote, section, and
page needed for the report trace.

An evidence item is valid for a paper analysis only when:

- its `paper_id` matches the analysis paper;
- its `chunk_id` resolves against the in-memory per-paper chunk index before
  artifact publication; the selected quote and provenance are then persisted in
  `evidence.json`;
- its quote equals the normalized chunk text or an explicitly defined,
  deterministic excerpt of that text;
- its ID belongs to the current run.

### 5.3 Grounded analyses

```python
class GroundedFinding(StrictModel):
    text: str
    evidence_ids: list[str]

class PaperAnalysis(StrictModel):
    paper_id: str
    contributions: list[GroundedFinding] = Field(default_factory=list)
    methods: list[GroundedFinding] = Field(default_factory=list)
    experiments: list[GroundedFinding] = Field(default_factory=list)
    results: list[GroundedFinding] = Field(default_factory=list)
    limitations: list[GroundedFinding] = Field(default_factory=list)

class CheckedFinding(StrictModel):
    text: str
    evidence_ids: list[str]
    support_status: SupportStatus

class CheckedPaperAnalysis(StrictModel):
    paper_id: str
    contributions: list[CheckedFinding] = Field(default_factory=list)
    methods: list[CheckedFinding] = Field(default_factory=list)
    experiments: list[CheckedFinding] = Field(default_factory=list)
    results: list[CheckedFinding] = Field(default_factory=list)
    limitations: list[CheckedFinding] = Field(default_factory=list)
```

Every finding must contain at least one Evidence ID. IDs must belong to the
paper's evidence pack. Empty categories are allowed; fabricated filler is not.
The current singular field names (`contribution`, `method`, `experiment`,
`limitation`) are migrated deliberately rather than kept as ambiguous aliases.
Tests and renderers move to the new contract in the same change set.

The citation checker sanitizes every generated finding before persistence:

- valid same-paper IDs are retained;
- unknown, foreign-paper, foreign-run, and duplicate IDs are removed;
- a finding with only valid IDs is `supported`;
- a finding with at least one valid and at least one removed ID is
  `weakly_supported`;
- a finding with no valid ID after sanitization is removed entirely.

`analyses.json` is exactly `list[CheckedPaperAnalysis]`, so every persisted
finding retains at least one resolvable same-paper ID. A paper analysis counts as
successful only when it retains at least one `supported` finding. Only supported
findings are supplied to cross-paper synthesis; weak findings remain available
for audit but cannot ground survey claims.

### 5.4 Survey draft and checked report

```python
class GroundedClaim(StrictModel):
    text: str
    evidence_ids: list[str]

class SurveyDraft(StrictModel):
    tldr_claims: list[GroundedClaim]
    method_taxonomy: list[GroundedClaim]
    comparisons: list[GroundedClaim]
    key_findings: list[GroundedClaim]
    limitations: list[GroundedClaim]
    open_questions: list[GroundedClaim]

class CheckedClaim(StrictModel):
    text: str
    evidence_ids: list[str]
    support_status: SupportStatus

class RejectedCriticalClaim(CheckedClaim):
    source_section: Literal["tldr_claims", "key_findings"]

class CheckedSurveyReport(StrictModel):
    question: str
    tldr_claims: list[CheckedClaim] = Field(default_factory=list)
    method_taxonomy: list[CheckedClaim] = Field(default_factory=list)
    comparisons: list[CheckedClaim] = Field(default_factory=list)
    key_findings: list[CheckedClaim] = Field(default_factory=list)
    limitations: list[CheckedClaim] = Field(default_factory=list)
    open_questions: list[CheckedClaim] = Field(default_factory=list)
    rejected_critical_claims: list[RejectedCriticalClaim] = Field(
        default_factory=list
    )
```

The deterministic citation checker converts draft claims into checked claims
with `supported`, `weakly_supported`, or `unsupported` status.

- `supported`: every reference resolves and the claim has at least one reference.
- `unsupported`: the claim has no valid reference after sanitization.
- `weakly_supported`: reserved for a deterministic, documented rule that finds
  at least one valid and at least one invalid reference. It is never treated as
  fully supported in critical sections.

Unknown IDs are removed. Citation checking relocates every weakly supported or
unsupported TL;DR/key-finding claim into `rejected_critical_claims`, preserving
its original section, and leaves only `supported` claims in `tldr_claims` and
`key_findings`. Other category arrays may retain checked statuses for explicit
rendering in limitations/audit content. Both `report.json` and `report.md` consume
these already-sanitized arrays; the renderer does not independently filter them.
`report.json` is exactly one `CheckedSurveyReport`. A model-level validator
requires every item in the two critical arrays to be `supported` and every
rejected critical claim to be weak or unsupported.

A report is publishable only if, after citation checking, it contains at least
one supported TL;DR claim and at least one supported key finding. Failure to meet
either minimum is `insufficient_supported_report` and makes the run `failed`;
the pipeline does not publish `report.json` or `report.md`. The first version has
no separate generated conclusion field.

## 6. PDF Acquisition and Parsing

### 6.1 URL and network policy

`FullTextDownloader` accepts only HTTPS arXiv PDF URLs derived from normalized
arXiv metadata. It does not accept an arbitrary user URL.

- The downloader extracts the canonical, optionally versioned arXiv identifier
  from normalized metadata and constructs
  `https://arxiv.org/pdf/{arxiv_id}` itself; it never fetches the raw feed URL.
- The exact allowed hosts are `arxiv.org` and `export.arxiv.org`.
- The path must remain under `/pdf/`, contain the same canonical arXiv ID, and
  have no query string. An optional `.pdf` suffix is accepted.
- Every redirect hop is revalidated for scheme, host, path, and arXiv ID.
- Userinfo, fragments, localhost names, private/link-local IP targets, and
  non-HTTPS schemes are rejected.
- Connect/read/write/pool timeouts are explicit.
- Redirect count is bounded.
- Response streaming stops as soon as `PDF_MAX_BYTES` would be exceeded.
- A PDF-compatible content type is required, and bytes must begin with the PDF
  magic signature.
- Partial, corrupt, encrypted, empty, and over-page-limit documents fail at the
  parser boundary with structured codes.

The downloader never includes the API key because arXiv PDF retrieval is public.

### 6.2 Parser behavior

`PdfParser` accepts bytes and returns a `PaperDocument`; it does not perform
network calls or chunking.

Using PyMuPDF, it:

- opens the document from bytes;
- rejects password-protected/encrypted documents that cannot be opened without a
  password;
- enforces `PDF_MAX_PAGES` before extracting all pages;
- extracts text in page order;
- normalizes line endings, whitespace, repeated blank lines, and obvious control
  characters;
- preserves page boundaries;
- treats the first and last three non-empty lines as page-edge candidates and
  removes one only when the same normalized line occurs on more than half of all
  pages;
- records warnings for pages with no extractable text;
- rejects documents whose normalized text has fewer than 200 non-whitespace
  characters; this fixed v1 threshold is not user-configurable.

Complex reading-order reconstruction and OCR are out of scope. Text-native arXiv
PDFs are the supported input class.

### 6.3 Section-aware chunking

The chunker operates on ordered page text. It recognizes conservative section
headings from line structure and common scholarly patterns such as numbered
headings and canonical names (`Abstract`, `Introduction`, `Methods`, `Results`,
`Discussion`, `Limitations`, `Conclusion`, `References`).

- A recognized heading applies until the next heading.
- Chunk windows do not intentionally cross section boundaries.
- Long sections use fixed v1 windows of 180 words with 30 words of overlap.
- Page boundaries and the starting page are retained.
- If no reliable section is recognized, chunking falls back to page-aware fixed
  windows and records `section_detection_failed`.
- Reference-list chunks are excluded from analysis retrieval by default after a
  reliable `References` heading. The corresponding `DocumentRecord.warnings`
  contains the stable code `reference_section_excluded`.

No LLM is used for parsing, heading detection, or chunking.

## 7. Generation Provider

### 7.1 Interface

```python
class GenerationProvider(Protocol):
    def generate_structured(
        self,
        operation: str,
        messages: Sequence[GenerationMessage],
        response_schema: type[ModelT],
        timeout: float,
    ) -> StructuredGeneration[ModelT]:
        ...
```

```python
class StructuredGeneration(StrictModel, Generic[ModelT]):
    result: ModelT
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    attempts: int
    elapsed_seconds: float
```

The caller supplies a schema type; the provider returns only a validated model.
Analyzer and synthesizer do not know DashScope URLs, headers, response envelopes,
retry rules, or JSON decoding details.

### 7.2 DashScope implementation

The implementation uses `httpx` against DashScope's OpenAI-compatible endpoint,
without adding the OpenAI SDK. It sends the shared `DASHSCOPE_API_KEY` as a
bearer credential and uses the configured generation model.

Default settings:

```text
DASHSCOPE_GENERATION_MODEL=qwen3.7-plus
DASHSCOPE_GENERATION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_GENERATION_TIMEOUT_SECONDS=60
```

The base URL must be HTTPS. Error messages, event payloads, exceptions, and
`repr(Settings)` must never expose the key.

### 7.3 Structured response and retry rules

- Successful content is decoded as JSON and validated with the supplied Pydantic
  schema.
- HTTP 401/403 and invalid model/configuration errors fail immediately.
- One logical generation operation starts with one original HTTP request.
- Timeout, HTTP 429, and HTTP 5xx permit one transport retry, so an original or
  repair request has at most two HTTP attempts.
- `Retry-After` is capped at 10 seconds. Missing, invalid, negative, or larger
  values use a one-second delay or the 10-second cap as applicable.
- Invalid JSON or schema failure after a successful original response permits
  exactly one repair request using `qwen3.7-plus` and a safe validation-error
  summary. The repair request has the same one-transport-retry rule.
- If both original HTTP attempts fail, no repair request is made.
- Therefore one logical generation operation sends at most four HTTP attempts:
  two for the original request and two for the optional repair request.
- `StructuredGeneration.attempts` is the total number of HTTP sends, including
  transport failures and repair sends. `elapsed_seconds` covers sends, retry
  waits, validation, and repair.
- Usage fields aggregate every HTTP response that supplies usage, including an
  invalid-content original response followed by repair. Missing usage remains
  `None`; available counts are summed once and never inferred.
- The configured timeout applies per HTTP attempt. With the defaults, the hard
  design upper bound is four 60-second attempts plus two 10-second waits.
- The original prompt, raw model response, and API key are not persisted in
  normal logs. Safe operation names, counts, latency, attempts, model, and usage
  are persisted.

## 8. Failure and Degradation Contract

### 8.1 Terminal states

```python
RunStatus = Literal["completed", "completed_with_degradation", "failed"]
```

- `completed`: all selected papers used their requested source mode, required
  generation succeeded, every retained generated reference was valid, and the
  minimum supported critical content passed citation validation.
- `completed_with_degradation`: a permitted per-paper fallback, retrieval
  degradation, skipped paper analysis, or citation-reference sanitization
  occurred, but the minimum analysis threshold and report integrity rules still
  passed.
- `failed`: the pipeline cannot truthfully produce the formal report.

The manifest is created with an internal `running` lifecycle value and finalized
to exactly one terminal state in a `finally`-safe orchestration boundary.

### 8.2 Per-paper PDF fallback

The following failures fall back to the paper abstract and mark the run degraded:

| Code | Meaning |
| --- | --- |
| `pdf_url_missing` | arXiv metadata has no usable PDF URL |
| `pdf_download_timeout` | bounded download timed out |
| `pdf_not_found` | PDF returned 404/410 |
| `pdf_http_error` | other non-success response |
| `pdf_redirect_rejected` | redirect violated URL policy |
| `pdf_too_large` | body exceeded `PDF_MAX_BYTES` |
| `pdf_content_invalid` | content type or magic signature was invalid |
| `pdf_corrupt` | PyMuPDF could not parse the bytes |
| `pdf_encrypted` | password was required |
| `pdf_too_many_pages` | page count exceeded `PDF_MAX_PAGES` |
| `pdf_text_empty` | no useful text could be extracted |

Fallback is permitted only when the paper has a non-empty abstract. If neither
usable PDF text nor abstract exists, the paper is excluded and the reason is
recorded.

`--no-pdf` creates abstract-backed documents by explicit user choice and is not
itself a degradation.

### 8.3 Retrieval and generation failures

Existing retrieval semantics remain:

- `auto` may degrade from vector to lexical for defined transient vector
  failures;
- explicitly requested `hybrid` fails rather than silently changing modes;
- assembly/configuration and lexical failures remain terminal for the affected
  paper operation.

A failed paper analysis may be skipped if the number of successful analyses is:

- at least two when two or more papers were retrieved; or
- one when exactly one paper was retrieved.

If the minimum is not met, the run fails. A survey synthesis failure, exhausted
repair, or authentication failure is terminal. A citation-checked result below the
minimum defined in Section 5.4 fails with `insufficient_supported_report`.

## 9. Artifacts and Observability

A successful run writes:

```text
outputs/<run-id>/
  papers.json
  documents.json
  evidence.json
  analyses.json
  report.json
  report.md
  run_manifest.json
  logs.jsonl
```

### Persisted manifest and event contracts

```python
ManifestStatus = Literal[
    "running", "completed", "completed_with_degradation", "failed"
]

class SafeRunSettings(StrictModel):
    retrieval_mode: RetrievalMode
    embedding_model: str
    generation_provider: Literal["dashscope"]
    generation_endpoint_host: str
    generation_model: str
    generation_timeout_seconds: float
    pdf_download_timeout_seconds: float
    pdf_max_bytes: int
    pdf_max_pages: int
    analysis_evidence_per_paper: int
    chunk_max_words: int
    chunk_overlap_words: int

class RunCounts(StrictModel):
    selected_papers: int
    pdf_documents: int
    abstract_documents: int
    explicit_abstract_documents: int
    pdf_fallback_documents: int
    excluded_papers: int
    successful_analyses: int
    evidence_items: int

`RunCounts` validates that
`abstract_documents == explicit_abstract_documents + pdf_fallback_documents`.

class RetrievalRecord(StrictModel):
    paper_id: str
    requested_mode: RetrievalMode
    actual_mode: Literal["lexical", "hybrid"]
    degraded: bool
    degradation_code: str | None = None

class UsageTotals(StrictModel):
    operations: int
    http_attempts: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

class RunIssue(StrictModel):
    stage: str
    code: str
    paper_id: str | None = None
    message: str | None = None

class RunManifest(StrictModel):
    run_id: str
    status: ManifestStatus
    question: str
    requested_limit: int
    no_pdf: bool
    started_at: datetime
    finished_at: datetime | None = None
    settings: SafeRunSettings
    counts: RunCounts
    stage_elapsed_seconds: dict[str, float]
    usage: UsageTotals
    component_versions: dict[str, str]
    retrieval_outcomes: list[RetrievalRecord] = Field(default_factory=list)
    degradations: list[RunIssue] = Field(default_factory=list)
    errors: list[RunIssue] = Field(default_factory=list)

class RunEvent(StrictModel):
    timestamp: datetime
    run_id: str
    stage: str
    operation: str
    status: Literal["started", "ok", "degraded", "error"]
    paper_id: str | None = None
    code: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
```

Before constructing `RunIssue` or `RunEvent`, one centralized sanitizer rejects
credential-like keys and raw provider request/response bodies, and redacts known
secret values from messages and attributes. Flexible message/attribute fields
may contain only the sanitized result.

Timestamps are UTC ISO-8601 values. `run_manifest.json` is exactly one
`RunManifest`; it is first written with `running` and atomically replaced with a
terminal value. Every line of `logs.jsonl` is exactly one `RunEvent`. Existing
`RetrievalEvent` fields are nested into safe event `attributes` together with the
paper operation context.

### Artifact meanings

- `papers.json`: exactly `list[Paper]` of normalized search metadata.
- `documents.json`: content source, hash, page count, warnings, and fallback
  reason; no raw page text.
- `evidence.json`: evidence plus paper/chunk/section/page provenance.
- `analyses.json`: checked per-paper structured analyses.
- `report.json`: checked structured survey used by the renderer.
- `report.md`: human-facing formal literature review.
- `run_manifest.json`: the exact `RunManifest` contract above.
- `logs.jsonl`: append-only `RunEvent` records for stages and attempts.

On failure, the manifest, log, and any already completed safe intermediate
artifacts remain. A failed run must not contain a newly published `report.md`
that could be mistaken for a completed formal result.

Writes use temporary sibling files followed by replacement so readers do not
observe partially serialized JSON or Markdown.

The manifest records configuration values that affect reproducibility, but
redacts all secrets. At minimum it includes:

- query, requested limit, and `no_pdf`;
- retrieval requested/actual modes and model;
- generation provider, endpoint host, and model;
- PDF byte/page limits and chunk settings;
- selected, PDF, explicit/fallback abstract, excluded, and analyzed paper counts;
- one `RetrievalRecord` per successful paper retrieval, including requested and
  actual mode; failed retrievals are represented by `RunIssue` errors;
- per-stage elapsed time;
- generation attempts and token usage when supplied by DashScope;
- terminal status and structured degradation/error codes;
- `paper-agent`, PyMuPDF, and embedded MuPDF versions.

## 10. Formal Report

The renderer consumes only citation-checked models and emits:

1. title and run status;
2. TL;DR;
3. selected papers and content source (`PDF` or `abstract fallback`);
4. method taxonomy;
5. cross-paper comparison;
6. key findings;
7. limitations;
8. open questions;
9. evidence trace.

Each displayed critical claim includes resolvable evidence markers. The evidence
trace maps each marker to paper title, section when known, page, chunk, and quote.
The renderer performs no model calls and invents no prose beyond fixed labels and
run metadata.

## 11. Configuration

The existing environment-over-`.env` precedence remains. New settings are
strictly parsed at startup:

```text
DASHSCOPE_API_KEY=<shared secret>
BAILIAN_EMBEDDING_MODEL=text-embedding-v4
DASHSCOPE_GENERATION_MODEL=qwen3.7-plus
DASHSCOPE_GENERATION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_GENERATION_TIMEOUT_SECONDS=60
PDF_DOWNLOAD_TIMEOUT_SECONDS=30
PDF_MAX_BYTES=25000000
PDF_MAX_PAGES=200
ANALYSIS_EVIDENCE_PER_PAPER=6
```

Positive numeric values must be strictly positive integers/floats as applicable.
The generation URL must be valid HTTPS. The retry count is fixed at one rather
than exposed as additional configuration in this phase.

Legacy OpenAI configuration fields are not used by the new path. Their removal
may be handled as a focused compatibility task in the implementation plan rather
than mixed into unrelated component work.

## 12. Testing Strategy

The default suite remains fully offline. External behavior is tested with
injectable transports and deterministic fakes.

### Downloader

Using `httpx.MockTransport`:

- successful bounded PDF response;
- allowed and rejected redirects;
- timeout;
- 404 and other HTTP error;
- wrong content type and wrong magic;
- maximum-size boundary and streamed overflow;
- truncated response/parse handoff;
- no arbitrary host or non-HTTPS access.

### Parser

Using small synthetic PDFs:

- multi-page text and one-based page provenance;
- common headings;
- blank pages;
- empty/garbage text;
- corrupted bytes;
- encrypted/password-protected PDF;
- exact and exceeded page limits;
- stable content hashing;
- no OCR fallback.

### Chunker

- section recognition and fallback;
- page attribution and cross-page windows;
- maximum size and overlap;
- deterministic IDs;
- reference-section exclusion;
- empty/malformed input.

### Provider

Using a fake transport:

- valid structured JSON and usage;
- 401/403 without retry;
- 429, timeout, and 5xx with at most one retry;
- `Retry-After`;
- invalid JSON/schema followed by successful repair;
- exhausted repair;
- configured model and timeout propagation;
- API key absent from exceptions, logs, and representations.

### Analyzer and survey

Using a deterministic fake `GenerationProvider`:

- complete valid results;
- empty optional categories;
- rejection/sanitization of foreign and unknown Evidence IDs;
- paper-to-evidence containment;
- minimum successful-analysis threshold;
- unsupported claims excluded from critical report sections.

### Offline vertical integration

One integration test fakes only arXiv HTTP, PDF HTTP, embedding transport, and
generation provider. It exercises real normalization, parsing, chunking,
retrieval/fusion, evidence packing, validation, artifact persistence, and
rendering. A two-paper case asserts the second paper's vector outcome cannot
contain any chunk indexed for the first paper.

Live tests are separate manual smoke checks and are not part of normal `pytest`.

## 13. Acceptance Criteria

The phase is complete when:

- all existing 440 tests still pass, with intentional schema migrations updated;
- a default run attempts public arXiv PDF download and uses `qwen3.7-plus`;
- `--no-pdf` remains explicit abstract-only operation;
- every per-paper finding has at least one valid same-paper Evidence ID;
- every critical report claim resolves to paper, section if known, page, chunk,
  and quote;
- unsupported/weak claims cannot enter TL;DR or key findings;
- failures and fallbacks produce the documented terminal status and codes;
- network calls have explicit timeouts, bounded retries, and byte/page limits;
- logs and artifacts contain no secret;
- an offline end-to-end test produces all eight successful-run artifacts;
- a manual live run with `--limit 3` produces all eight artifacts, at least the
  required number of analyses, a formal citation-checked report, and usage
  metrics in the manifest;
- release documentation satisfies the PyMuPDF/AGPL compliance gate.

## 14. Delivery Sequence

The implementation plan should split this design into small test-driven tasks:

1. Day 1: schemas, configuration, provider contracts, manifest lifecycle.
2. Day 2: secure arXiv downloader and PyMuPDF parser.
3. Day 3: section/page chunking and per-paper evidence packs.
4. Day 4: DashScope structured provider and per-paper analyzer.
5. Day 5: cross-paper synthesis, citation validation, formal renderer.
6. Day 6: pipeline integration, atomic artifacts, regression verification.
7. Day 7: live smoke test, fixes, usage documentation, and AGPL release
   compliance files.

Later phases add caching/persistence, broader sources, CI/CD, and operational
hardening only after this vertical slice works end to end.
