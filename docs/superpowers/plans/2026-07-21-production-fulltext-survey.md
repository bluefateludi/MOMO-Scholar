# Production Full-Text Survey Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-oriented local CLI that downloads public arXiv PDFs, extracts page-aware evidence, uses DashScope `qwen3.7-plus` for grounded analysis and synthesis, validates citations, and emits auditable terminal artifacts.

**Architecture:** Keep `paper_agent.pipeline` as a thin orchestrator. Isolate public-PDF I/O in `paper_agent.fulltext`, structured generation in `paper_agent.generation`, run lifecycle and safe persistence in `paper_agent.observability`, and deterministic grounding in the existing evidence/synthesis/rendering boundaries. Reuse the current hybrid retriever with one fresh service and in-memory vector store per paper while sharing only the owned embedding HTTP transport.

**Tech Stack:** Python 3.10+, Pydantic 2, Typer, httpx, PyMuPDF, DashScope OpenAI-compatible HTTP API, pytest

**Approved spec:** `docs/superpowers/specs/2026-07-20-production-fulltext-survey-design.md`

---

## Target File Structure

### Shared contracts and configuration

- Modify `paper_agent/schemas.py`: keep shared `Paper`, `Chunk`, and `Evidence`; make persisted models strict and add evidence page/section provenance.
- Create `paper_agent/modeling.py`: shared `StrictModel` only.
- Modify `paper_agent/config.py`: validate generation, PDF, and evidence-pack settings.
- Modify `.env.example`: document safe defaults without a key value.
- Modify `pyproject.toml`: make PyMuPDF a base dependency and declare project licensing.
- Create `LICENSE`: canonical AGPL-3.0 license text.
- Create `THIRD_PARTY_NOTICES.md`: PyMuPDF/MuPDF license and copyright notice.

### Full text

- Create `paper_agent/fulltext/__init__.py`: public exports.
- Create `paper_agent/fulltext/models.py`: `DocumentPage`, transient `PaperDocument`, and persisted `DocumentRecord`.
- Create `paper_agent/fulltext/downloader.py`: canonical arXiv URL derivation and bounded HTTPS download.
- Create `paper_agent/fulltext/parser.py`: PyMuPDF byte parsing and deterministic page cleaning.
- Create `paper_agent/fulltext/service.py`: explicit PDF/abstract acquisition and permitted per-paper fallback.
- Modify `paper_agent/text/chunker.py`: page/section-aware deterministic chunking.
- Retire behavior in `paper_agent/text/loader.py` after callers migrate; remove it only when no import remains.

### Evidence and generation

- Create `paper_agent/evidence/packs.py`: per-paper retrieval resource ownership and evidence-pack validation/capping.
- Modify `paper_agent/evidence/hybrid.py`: copy candidate section/page into `Evidence`.
- Create `paper_agent/generation/__init__.py`: public exports.
- Create `paper_agent/generation/contracts.py`: provider protocol, messages, flattened result/failure metrics, and typed errors.
- Create `paper_agent/generation/dashscope_transport.py`: one-attempt HTTP/envelope boundary and internal transport response models.
- Create `paper_agent/generation/dashscope.py`: bounded HTTP attempts, JSON/schema validation, repair, and usage aggregation.

### Synthesis, checking, and rendering

- Create `paper_agent/synthesis/models.py`: generated and checked paper/survey contracts.
- Modify `paper_agent/synthesis/paper_reader.py`: provider-driven grounded per-paper analysis.
- Modify `paper_agent/synthesis/survey.py`: provider-driven cross-paper structured survey.
- Modify `paper_agent/evidence/citation_checker.py`: sanitize findings and survey claims against the run evidence index.
- Modify `paper_agent/rendering/markdown.py`: formal report from checked models only.

### Run lifecycle and integration

- Create `paper_agent/observability/__init__.py`: public exports.
- Create `paper_agent/observability/models.py`: manifest, counts, issues, usage, retrieval records, and log events.
- Create `paper_agent/observability/sanitize.py`: centralized secret/raw-payload sanitization.
- Create `paper_agent/observability/recorder.py`: atomic artifacts, JSONL events, and terminal manifest transition.
- Modify `paper_agent/io.py`: reusable atomic UTF-8 JSON/text writes.
- Modify `paper_agent/pipeline.py`: thin end-to-end orchestration and dependency injection.
- Modify `paper_agent/cli.py`: truthful success/degradation/failure output.
- Create `docs/fulltext-survey.md`: setup, run modes, artifacts, failure semantics, and live smoke procedure.

### Tests

- Extend focused existing tests where their public contract changes.
- Add `tests/fulltext/`, `tests/generation/`, `tests/observability/`, and `tests/synthesis/` packages for new boundaries.
- Add `tests/test_pipeline_fulltext_integration.py` for the offline vertical slice.
- Keep manual live smoke separate from normal pytest.

## Chunk 1: Contracts, Configuration, and Run Foundation

### Task 1: Adopt PyMuPDF and the AGPL release contract

**Files:**
- Modify: `pyproject.toml`
- Create: `LICENSE`
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Write failing packaging/license tests**

Add tests that parse `pyproject.toml` and assert:

```python
def test_pdf_runtime_and_agpl_metadata_are_declared() -> None:
    pyproject = _load_pyproject()
    assert "pymupdf>=1.24,<2" in pyproject["project"]["dependencies"]
    assert "pdf" not in pyproject["project"].get("optional-dependencies", {})
    assert pyproject["project"]["license"] == {"file": "LICENSE"}


def test_agpl_and_pymupdf_notices_are_present() -> None:
    root = Path(__file__).resolve().parents[1]
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (
        root / "LICENSE"
    ).read_text(encoding="utf-8")
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "PyMuPDF" in notices
    assert "MuPDF" in notices
    assert "AGPL" in notices
```

Refactor the repeated TOML-loading lines in this test file into a local
`_load_pyproject()` helper; do not change packaging behavior yet.

- [ ] **Step 2: Run the focused tests and confirm the expected failure**

Run:

```powershell
python -m pytest tests/test_packaging.py::test_pdf_runtime_and_agpl_metadata_are_declared tests/test_packaging.py::test_agpl_and_pymupdf_notices_are_present -q
```

Expected: FAIL because PyMuPDF is still optional and the license files do not
exist.

- [ ] **Step 3: Implement the dependency and license metadata**

Move `pymupdf>=1.24,<2` into `[project].dependencies`, remove the `pdf` optional
extra, and add:

```toml
license = {file = "LICENSE"}
```

Copy the unmodified canonical GNU AGPL version 3 text into `LICENSE`. Add
`THIRD_PARTY_NOTICES.md` naming PyMuPDF and MuPDF, their AGPL/commercial
dual-license status, the selected AGPL path, and links from the approved spec.
Do not claim that the notice replaces legal review.

- [ ] **Step 4: Verify packaging and the existing editable-build regression**

Run:

```powershell
python -m pytest tests/test_packaging.py -q
$root = (Resolve-Path '.').Path
$wheelDirCandidate = Join-Path $root '.tmp-wheels'
if (Test-Path -LiteralPath $wheelDirCandidate) {
    throw '.tmp-wheels already exists; inspect it instead of deleting it'
}
New-Item -ItemType Directory -Path $wheelDirCandidate | Out-Null
try {
    python -m pip wheel . --no-deps --no-build-isolation --wheel-dir $wheelDirCandidate
    if ($LASTEXITCODE -ne 0) { throw 'wheel build failed' }
    $wheels = @(Get-ChildItem -LiteralPath $wheelDirCandidate -Filter '*.whl')
    if ($wheels.Count -ne 1) { throw "expected one wheel, found $($wheels.Count)" }
    python -c "import zipfile; p=r'$($wheels[0].FullName)'; z=zipfile.ZipFile(p); xs=[n for n in z.namelist() if n.endswith('.dist-info/licenses/LICENSE') or n.endswith('.dist-info/LICENSE')]; assert len(xs)==1, xs; print('LICENSE_ENTRY='+xs[0])"
    if ($LASTEXITCODE -ne 0) { throw 'license metadata inspection failed' }
} finally {
    $resolvedWheelDir = (Resolve-Path -LiteralPath $wheelDirCandidate).Path
    if (-not $resolvedWheelDir.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'refusing to remove directory outside worktree'
    }
    Remove-Item -LiteralPath $resolvedWheelDir -Recurse -Force
}
```

Expected: packaging tests PASS, the build creates exactly one wheel, and the
inspection prints one `LICENSE_ENTRY=...LICENSE` line. A pre-existing
`.tmp-wheels` directory stops the step without deleting user data.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml LICENSE THIRD_PARTY_NOTICES.md tests/test_packaging.py
git commit -m "build: adopt pymupdf under agpl"
```

### Task 2: Introduce strict shared, full-text, and synthesis contracts

**Files:**
- Create: `paper_agent/modeling.py`
- Modify: `paper_agent/schemas.py`
- Create: `paper_agent/fulltext/__init__.py`
- Create: `paper_agent/fulltext/models.py`
- Create: `paper_agent/synthesis/models.py`
- Modify: `paper_agent/synthesis/paper_reader.py`
- Modify: `paper_agent/synthesis/survey.py`
- Modify: `tests/test_schemas.py`
- Create: `tests/fulltext/__init__.py`
- Create: `tests/fulltext/test_models.py`
- Create: `tests/synthesis/__init__.py`
- Create: `tests/synthesis/test_models.py`
- Modify: `tests/test_synthesis.py`
- Modify: `tests/test_citation_checker.py`

- [ ] **Step 1: Write failing strict-contract tests**

Cover:

```python
def test_persisted_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Paper.model_validate({**PAPER_VALUES, "unexpected": True})


def test_document_record_omits_page_text() -> None:
    document = PaperDocument(
        paper_id="arxiv:2401.00001",
        content_source="pdf",
        pages=[DocumentPage(page_number=1, text="Introduction\nBody")],
        content_sha256="a" * 64,
    )
    record = DocumentRecord.from_document(document)
    assert record.page_count == 1
    assert "pages" not in record.model_dump()


def test_checked_report_rejects_unsupported_critical_claim() -> None:
    with pytest.raises(ValidationError, match="critical claims must be supported"):
        CheckedSurveyReport(
            question="q",
            tldr_claims=[
                CheckedClaim(
                    text="claim",
                    evidence_ids=[],
                    support_status="unsupported",
                )
            ],
        )
```

Also test `Evidence(section="Methods", page=3)`, list default isolation,
positive one-based pages, 64-character lowercase SHA-256 validation, rejection
of blank `DocumentPage.text`, and the `RejectedCriticalClaim` status invariant.

- [ ] **Step 2: Run the contract tests and confirm they fail**

Run:

```powershell
python -m pytest tests/test_schemas.py tests/fulltext/test_models.py tests/synthesis/test_models.py -q
```

Expected: FAIL on missing modules/models and the current permissive `Paper`.

- [ ] **Step 3: Add the minimal shared and full-text models**

Implement:

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentPage(StrictModel):
    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)


class PaperDocument(StrictModel):
    paper_id: str
    content_source: Literal["pdf", "abstract"]
    pages: list[DocumentPage] = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    warnings: list[str] = Field(default_factory=list)


class DocumentRecord(StrictModel):
    paper_id: str
    content_source: Literal["pdf", "abstract"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)
    fallback_code: str | None = None
```

`PaperDocument` contains only non-empty retained pages. The parser omits blank
pages while preserving their original numbers in warnings; consequently,
`DocumentRecord.page_count` is the retained non-empty page count
(`len(document.pages)`), not the physical PDF page count.
`DocumentRecord.from_document()` accepts the optional fallback code and copies
only metadata. Make `Paper` and `Evidence` inherit `StrictModel`; add optional
`section` and `page` to `Evidence`. Leave internal `Chunk` on `BaseModel`.

- [ ] **Step 4: Add generated and checked synthesis models**

Implement the exact approved models in `paper_agent/synthesis/models.py`:
`GroundedFinding`, `PaperAnalysis`, `GroundedClaim`, `SurveyDraft`,
`CheckedFinding`, `CheckedPaperAnalysis`, `CheckedClaim`,
`RejectedCriticalClaim`, and `CheckedSurveyReport`.

Use these field rules exactly:

- `GroundedFinding.evidence_ids` and `GroundedClaim.evidence_ids` are required
  with `Field(min_length=1)`;
- all five `PaperAnalysis` category lists use `default_factory=list`;
- all six `SurveyDraft` category lists are required and have no defaults;
- `CheckedFinding.evidence_ids` is required with `Field(min_length=1)`;
- all five `CheckedPaperAnalysis` category lists use `default_factory=list`;
- `CheckedClaim.evidence_ids` is required but may be empty only when its status
  is `unsupported`;
- all six `CheckedSurveyReport` category lists and
  `rejected_critical_claims` use `default_factory=list`;
- validators allow only `supported` items in `tldr_claims`/`key_findings` and
  only `weakly_supported`/`unsupported` items in
  `rejected_critical_claims`.

Delete the obsolete `PaperAnalysis`/`SurveyReport` definitions from
`paper_agent.schemas`. In the same step, update `paper_reader.py` to build the
new plural `GroundedFinding` fields from related evidence and update `survey.py`
to read `analysis.contributions[0].text/evidence_ids`. This is a temporary
deterministic compatibility path until Chunk 3 replaces both functions with
provider-driven generation; it must not create a finding from an abstract
without evidence.

- [ ] **Step 5: Run focused and schema-dependent tests**

Run:

```powershell
python -m pytest tests/test_schemas.py tests/fulltext/test_models.py tests/synthesis/test_models.py tests/test_synthesis.py tests/test_citation_checker.py -q
```

Expected: PASS. Any old singular paper-analysis field assertion must be migrated
to the approved plural grounded model rather than supported through an alias.

- [ ] **Step 6: Commit**

```powershell
git add paper_agent/modeling.py paper_agent/schemas.py paper_agent/fulltext paper_agent/synthesis/models.py paper_agent/synthesis/paper_reader.py paper_agent/synthesis/survey.py tests/test_schemas.py tests/fulltext tests/synthesis tests/test_synthesis.py tests/test_citation_checker.py
git commit -m "feat: add strict full-text survey contracts"
```

### Task 3: Add strict production settings

**Files:**
- Modify: `paper_agent/config.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing settings tests**

Add cases for defaults, `.env` loading, process-environment precedence, secret
repr redaction, positive finite timeouts, positive integer limits, and HTTPS
generation URL validation:

```python
def test_fulltext_generation_defaults() -> None:
    settings = Settings()
    assert settings.bailian_embedding_model == "text-embedding-v4"
    assert settings.dashscope_generation_model == "qwen3.7-plus"
    assert settings.dashscope_generation_base_url == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert settings.dashscope_generation_timeout_seconds == 60.0
    assert settings.pdf_download_timeout_seconds == 30.0
    assert settings.pdf_max_bytes == 25_000_000
    assert settings.pdf_max_pages == 200
    assert settings.analysis_evidence_per_paper == 6


@pytest.mark.parametrize("raw", ["0", "-1", "nan", "inf", "word"])
def test_generation_timeout_rejects_invalid_values(raw, monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_GENERATION_TIMEOUT_SECONDS", raw)
    with pytest.raises(ValueError, match="positive finite"):
        load_settings()
```

Also assert `http://...`, URL credentials, query, fragment, and a missing host
are rejected. A user-configured HTTPS host is allowed by the approved provider
abstraction; only the default value is pinned to DashScope.

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_config.py -q
```

Expected: FAIL on missing fields/parsers.

- [ ] **Step 3: Implement minimal settings parsing**

Add frozen, slotted fields:

```python
dashscope_generation_model: str = "qwen3.7-plus"
dashscope_generation_base_url: str = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
dashscope_generation_timeout_seconds: float = 60.0
pdf_download_timeout_seconds: float = 30.0
pdf_max_bytes: int = 25_000_000
pdf_max_pages: int = 200
analysis_evidence_per_paper: int = 6
```

Add `_positive_float()` using `math.isfinite`, reuse `_positive_int()`, and add a
URL parser that requires the `https` scheme, a non-empty host, and no
userinfo/query/fragment.
Continue environment-over-`.env` precedence. Keep the API key `repr=False`.

- [ ] **Step 4: Update `.env.example`**

Add the approved variable names and safe defaults. Leave
`DASHSCOPE_API_KEY=` empty. Do not add a real or syntactically realistic key.

- [ ] **Step 5: Run configuration and dotenv regression tests**

Run:

```powershell
python -m pytest tests/test_config.py -q
```

Expected: PASS, including existing parent-directory and precedence behavior.

- [ ] **Step 6: Commit**

```powershell
git add paper_agent/config.py .env.example tests/test_config.py
git commit -m "feat: configure full-text generation limits"
```

### Task 4: Add atomic I/O and centralized event sanitization

**Files:**
- Modify: `paper_agent/io.py`
- Create: `paper_agent/observability/__init__.py`
- Create: `paper_agent/observability/sanitize.py`
- Modify: `tests/test_io.py`
- Create: `tests/observability/__init__.py`
- Create: `tests/observability/test_sanitize.py`

- [ ] **Step 1: Write failing atomic-write tests**

Monkeypatch `Path.replace` to observe sibling temporary-file use and simulate a
replacement error:

```python
def test_write_json_atomically_replaces_complete_sibling(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    replacements: list[tuple[Path, Path]] = []
    real_replace = Path.replace

    def recording_replace(source: Path, destination: Path):
        replacements.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", recording_replace)
    write_json(target, {"status": "complete"})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "status": "complete"
    }
    assert replacements[0][1] == target
    assert replacements[0][0].parent == target.parent
```

Also test that a failed replacement leaves any pre-existing target unchanged and
cleans its own temporary file. Keep `append_json_line` append-only; do not make
JSONL replacement-based.

- [ ] **Step 2: Write failing sanitizer tests**

Cover nested mappings/sequences, case-insensitive credential-like keys, known
secret values embedded in strings, raw provider request/response keys, and
ordinary diagnostic values:

```python
def test_sanitize_event_data_removes_secrets_and_raw_payloads() -> None:
    result = sanitize_event_data(
        {
            "Authorization": "Bearer secret-value",
            "raw_response": {"choices": ["private"]},
            "stage": "generation",
            "message": "failed for secret-value",
        },
        secrets=("secret-value",),
    )
    assert result == {
        "Authorization": "[REDACTED]",
        "raw_response": "[REDACTED]",
        "stage": "generation",
        "message": "failed for [REDACTED]",
    }
```

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_io.py tests/observability/test_sanitize.py -q
```

Expected: FAIL on missing atomic behavior and sanitizer module.

- [ ] **Step 4: Implement atomic writers**

Use `tempfile.NamedTemporaryFile(delete=False, dir=path.parent, prefix=...)`,
flush and close it, then `Path.replace(path)`. On any error, delete only the
temporary sibling created by that invocation. Serialize Pydantic models before
calling the writer; keep `write_json(path, JSON-compatible data)` narrow.

- [ ] **Step 5: Implement the sanitizer**

Define a recursive `sanitize_event_data(value, *, secrets)` that:

- replaces values for credential-like and raw-payload keys with `[REDACTED]`;
- replaces each non-empty known secret substring in strings;
- preserves JSON-compatible scalar types;
- recursively copies mappings/lists without mutating caller data;
- replaces an unsupported object with
  `[UNSUPPORTED_TYPE:<module>.<qualified-class-name>]` using only `type(value)`;
  never call instance `str()` or `repr()`.

The recorder will be the only caller that converts flexible messages/attributes
into persisted events.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m pytest tests/test_io.py tests/observability/test_sanitize.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add paper_agent/io.py paper_agent/observability tests/test_io.py tests/observability
git commit -m "feat: add atomic output and event sanitization"
```

### Task 5: Implement the run manifest and recorder lifecycle

**Files:**
- Create: `paper_agent/observability/models.py`
- Create: `paper_agent/observability/recorder.py`
- Modify: `paper_agent/observability/__init__.py`
- Create: `tests/observability/test_models.py`
- Create: `tests/observability/test_recorder.py`

- [ ] **Step 1: Write failing manifest-invariant tests**

Implement tests directly from the approved equations:

```python
def test_run_counts_require_consistent_document_partition() -> None:
    with pytest.raises(ValidationError, match="selected papers"):
        RunCounts(
            selected_papers=3,
            pdf_documents=1,
            abstract_documents=1,
            explicit_abstract_documents=0,
            pdf_fallback_documents=1,
            excluded_papers=0,
            successful_analyses=1,
            evidence_items=2,
        )
```

Also test abstract partition equality, successful-analysis upper bound,
non-negative counts, UTC-aware timestamps, strict extra-field rejection, and:

```python
safe = SafeRunSettings.from_settings(
    Settings(),
    chunk_max_words=180,
    chunk_overlap_words=30,
)
assert safe.generation_endpoint_host == "dashscope.aliyuncs.com"
assert "dashscope_api_key" not in safe.model_dump()
```

- [ ] **Step 2: Write failing recorder lifecycle tests**

Use a fixed clock and temporary output directory:

```python
def test_recorder_writes_running_then_one_terminal_manifest(tmp_path) -> None:
    recorder = RunRecorder.start(
        output_base=tmp_path,
        question="grounded review",
        requested_limit=3,
        no_pdf=False,
        safe_settings=SAFE_SETTINGS,
        component_versions={
            "paper-agent": "0.1.0",
            "pymupdf": "1.28.0",
            "mupdf": "1.28.0",
        },
        clock=FIXED_CLOCK,
    )
    running = _read_json(recorder.run_dir / "run_manifest.json")
    assert running["status"] == "running"

    recorder.complete(
        status="completed",
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={},
        usage=USAGE,
    )
    terminal = _read_json(recorder.run_dir / "run_manifest.json")
    assert terminal["status"] == "completed"

    with pytest.raises(RuntimeError, match="already terminal"):
        recorder.fail(
            code="late_failure",
            stage="test",
            counts=COUNTS,
            retrieval_outcomes=(),
            stage_elapsed_seconds={},
            usage=USAGE,
        )
```

Test sanitized JSONL events, failure retention, forbidden publication after
`failed`, preparation of both temporary report files before replacement, and
per-file atomicity. Simulate failure on the second replacement and assert that a
complete `report.json` may remain, `report.md` is absent, and the recorder has
not transitioned to a completed status.

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
python -m pytest tests/observability/test_models.py tests/observability/test_recorder.py -q
```

Expected: FAIL because manifest and recorder do not exist.

- [ ] **Step 4: Implement exact observability models**

Implement the spec's `ManifestStatus`, `SafeRunSettings`, `RunCounts`,
`RetrievalRecord`, `UsageTotals`, `RunIssue`, `RunManifest`, and `RunEvent`.
Use `Field(ge=0)` on counts/usage and model validators for all three count
relationships. `RetrievalRecord.actual_mode` is only lexical/hybrid; failed
retrievals are `RunIssue` entries.

Add this exact conversion boundary:

```python
@classmethod
def from_settings(
    cls,
    settings: Settings,
    *,
    chunk_max_words: int,
    chunk_overlap_words: int,
) -> SafeRunSettings:
    endpoint_host = urlsplit(settings.dashscope_generation_base_url).hostname
    if endpoint_host is None:
        raise ValueError("generation endpoint host is required")
    return cls(
        retrieval_mode=settings.retrieval_mode,
        embedding_model=settings.bailian_embedding_model,
        generation_provider="dashscope",
        generation_endpoint_host=endpoint_host,
        generation_model=settings.dashscope_generation_model,
        generation_timeout_seconds=(
            settings.dashscope_generation_timeout_seconds
        ),
        pdf_download_timeout_seconds=settings.pdf_download_timeout_seconds,
        pdf_max_bytes=settings.pdf_max_bytes,
        pdf_max_pages=settings.pdf_max_pages,
        analysis_evidence_per_paper=settings.analysis_evidence_per_paper,
        chunk_max_words=chunk_max_words,
        chunk_overlap_words=chunk_overlap_words,
    )
```

It copies only safe approved settings, derives `generation_endpoint_host` with
`urlsplit(settings.dashscope_generation_base_url).hostname`, rejects missing
hosts defensively, and records the explicit chunk values supplied by the caller.
The section-aware chunker in Chunk 2 defines and uses the v1 values `180` and
`30`; the pipeline passes those same active values here. It never reflects over
`Settings` and never copies the API key.

- [ ] **Step 5: Implement `RunRecorder`**

Give the recorder one responsibility: own artifact writes and lifecycle state.
Required public methods:

```python
class RunRecorder:
    @classmethod
    def start(
        cls,
        *,
        output_base: Path,
        question: str,
        requested_limit: int,
        no_pdf: bool,
        safe_settings: SafeRunSettings,
        component_versions: Mapping[str, str],
        clock: Callable[[], datetime] = utc_now,
    ) -> RunRecorder: ...
    def write_papers(self, papers: Sequence[Paper]) -> None: ...
    def write_documents(self, records: Sequence[DocumentRecord]) -> None: ...
    def write_evidence(self, evidence: Sequence[Evidence]) -> None: ...
    def write_analyses(self, analyses: Sequence[CheckedPaperAnalysis]) -> None: ...
    def publish_report(
        self, report: CheckedSurveyReport, markdown: str
    ) -> None: ...
    def emit(self, event: RunEvent) -> None: ...
    def complete(
        self,
        *,
        status: Literal["completed", "completed_with_degradation"],
        counts: RunCounts,
        retrieval_outcomes: Sequence[RetrievalRecord],
        stage_elapsed_seconds: Mapping[str, float],
        usage: UsageTotals,
        degradations: Sequence[RunIssue] = (),
    ) -> None: ...
    def fail(
        self,
        *,
        stage: str,
        code: str,
        counts: RunCounts,
        retrieval_outcomes: Sequence[RetrievalRecord],
        stage_elapsed_seconds: Mapping[str, float],
        usage: UsageTotals,
        degradations: Sequence[RunIssue] = (),
        paper_id: str | None = None,
        message: str | None = None,
    ) -> None: ...
```

`start()` creates the directory and initial manifest/log before external work.
`publish_report()` fully serializes both outputs to temporary siblings before
replacing either target, then performs one atomic `Path.replace` per file. This
is per-file atomicity, not a two-file transaction. A failure before replacement
publishes neither file; a failure during the second replacement may leave a
complete `report.json` but no `report.md`, must propagate, and the orchestrator
must finalize the run as `failed`. Terminal methods are idempotent only for the
exact same terminal transition; conflicting second transitions raise.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m pytest tests/observability/test_models.py tests/observability/test_recorder.py tests/test_io.py -q
```

Expected: PASS.

- [ ] **Step 7: Run the complete Chunk 1 regression suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS with no failures. This catches strict-model migration effects in
evaluation, retrieval, and pipeline tests outside the focused lists.

- [ ] **Step 8: Commit**

```powershell
git add paper_agent/observability tests/observability
git commit -m "feat: record auditable run lifecycle"
```

## Chunk 2: PDF Acquisition, Parsing, and Evidence Preparation

### Task 6: Implement constrained public arXiv PDF download

**Files:**
- Create: `paper_agent/fulltext/downloader.py`
- Modify: `paper_agent/fulltext/__init__.py`
- Create: `tests/fulltext/test_downloader.py`

- [ ] **Step 1: Write failing canonical-URL and policy tests**

Use `httpx.MockTransport` and cover modern IDs, old category IDs, an optional
version suffix, missing/non-arXiv IDs, raw feed HTTP links, exact allowed hosts,
redirect revalidation, query/userinfo/fragment rejection, and redirect loops:

```python
@pytest.mark.parametrize(
    ("paper_id", "expected"),
    [
        ("arxiv:2401.00001", "https://arxiv.org/pdf/2401.00001"),
        ("arxiv:2401.00001v2", "https://arxiv.org/pdf/2401.00001v2"),
        ("arxiv:cs/9901001", "https://arxiv.org/pdf/cs/9901001"),
    ],
)
def test_canonical_pdf_url_is_derived_from_paper_id(paper_id, expected):
    assert canonical_pdf_url(_paper(paper_id=paper_id)) == expected
```

Assert the implementation never requests `Paper.pdf_url` directly. A redirect
is allowed only when it remains HTTPS on `arxiv.org` or `export.arxiv.org`, uses
no explicit port other than `443`, has no userinfo/query/fragment, and its raw
path equals exactly `/pdf/{canonical_id}` or `/pdf/{canonical_id}.pdf`. Paths
with suffix segments, encoded separators, a different ID, or a non-default port
are rejected as `pdf_redirect_rejected`.

- [ ] **Step 2: Write failing response-boundary tests**

Cover:

- success for `application/pdf` and `application/octet-stream` only when bytes
  start with `%PDF-`;
- 404/410 as `pdf_not_found` and other non-success as `pdf_http_error`;
- connect/read timeout as `pdf_download_timeout`;
- declared `Content-Length` above the cap and streamed overflow as
  `pdf_too_large`;
- a body exactly equal to `max_bytes` succeeds;
- wrong content type or magic as `pdf_content_invalid`;
- `httpx.RemoteProtocolError` during streaming maps to `pdf_http_error`;
- a completed short body that starts with `%PDF-` is handed to the parser, whose
  corrupt-PDF test maps it to `pdf_corrupt`;
- at most three redirects;
- caller-supplied client ownership (downloader must not close it).

Use a streaming test body that raises if the downloader reads beyond the first
chunk over the cap, proving early termination.

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
python -m pytest tests/fulltext/test_downloader.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 4: Implement the downloader contract**

Implement:

```python
@dataclass(frozen=True, slots=True)
class DownloadedPdf:
    content: bytes
    source_url: str
    content_type: str


@dataclass(frozen=True, slots=True)
class PdfDownloadError(RuntimeError):
    code: Literal[
        "pdf_url_missing",
        "pdf_download_timeout",
        "pdf_not_found",
        "pdf_http_error",
        "pdf_redirect_rejected",
        "pdf_too_large",
        "pdf_content_invalid",
    ]
    message: str


class FullTextDownloader:
    def __init__(
        self,
        *,
        client: httpx.Client,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int = 3,
    ) -> None: ...

    def download(self, paper: Paper) -> DownloadedPdf: ...
```

Derive the URL from `paper.paper_id`, request with `follow_redirects=False`, and
handle redirects manually so every hop is validated by exact scheme, host,
port, path, query, fragment, and canonical-ID equality. Use `client.stream()`
and stop before appending a chunk that would exceed `max_bytes`. Map an
`httpx.TimeoutException` to `pdf_download_timeout` and any other
`httpx.RequestError`, including mid-stream protocol failure, to
`pdf_http_error`. A completed `%PDF-` body is returned even if structurally
truncated so `PdfParser` owns structural validity. Never send the DashScope key
or persist PDF bytes.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest tests/fulltext/test_downloader.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add paper_agent/fulltext/downloader.py paper_agent/fulltext/__init__.py tests/fulltext/test_downloader.py
git commit -m "feat: download bounded arxiv pdfs"
```

### Task 7: Parse and normalize PDFs with PyMuPDF

**Files:**
- Create: `paper_agent/fulltext/parser.py`
- Modify: `paper_agent/fulltext/__init__.py`
- Create: `tests/fulltext/test_parser.py`

- [ ] **Step 1: Write synthetic-PDF helpers and failing happy-path tests**

Build PDFs in memory with PyMuPDF inside the test; do not add binary fixtures.
Cover ordered one-based pages, SHA-256 over original bytes, blank-page warnings,
line-ending/control-character normalization, and useful text:

```python
def test_parser_preserves_page_order_and_hash() -> None:
    pdf_bytes = _pdf_bytes([
        "Abstract\nThis paper studies grounded retrieval. " * 8,
        "1 Introduction\nThe method uses hybrid evidence. " * 8,
    ])
    document = PdfParser(max_pages=200).parse(
        paper_id="arxiv:2401.00001",
        pdf_bytes=pdf_bytes,
    )
    assert [page.page_number for page in document.pages] == [1, 2]
    assert document.content_source == "pdf"
    assert document.content_sha256 == hashlib.sha256(pdf_bytes).hexdigest()
```

- [ ] **Step 2: Write failing error and cleaning tests**

Cover exact error codes:

- corrupt/truncated bytes -> `pdf_corrupt`;
- a fake opened document whose `load_page()` or `page.get_text()` raises
  `pymupdf.FileDataError` -> `pdf_corrupt` without leaking the library error;
- encrypted PDF requiring a password -> `pdf_encrypted`;
- `max_pages` exact boundary succeeds and one over -> `pdf_too_many_pages`;
- fewer than 200 non-whitespace normalized characters -> `pdf_text_empty`;
- repeated first/last-three edge line on more than half the pages is removed;
- a line occurring on exactly half the pages is retained;
- an isolated blank page is omitted from `PaperDocument.pages`, records its
  original one-based number as `page_text_empty:<page>`, and does not fail when
  another page makes the document useful; retained pages keep their original
  numbers and `DocumentRecord.page_count` counts retained non-empty pages.

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
python -m pytest tests/fulltext/test_parser.py -q
```

Expected: FAIL because `PdfParser` is missing.

- [ ] **Step 4: Implement deterministic parsing**

Implement:

```python
@dataclass(frozen=True, slots=True)
class PdfParseError(RuntimeError):
    code: Literal[
        "pdf_corrupt",
        "pdf_encrypted",
        "pdf_too_many_pages",
        "pdf_text_empty",
    ]
    message: str


class PdfParser:
    def __init__(self, *, max_pages: int, min_useful_characters: int = 200): ...
    def parse(self, *, paper_id: str, pdf_bytes: bytes) -> PaperDocument: ...
```

Open with `pymupdf.open(stream=pdf_bytes, filetype="pdf")` inside a context
manager. Map only `pymupdf.EmptyFileError` and `pymupdf.FileDataError` raised by
open, page-count access, `load_page()`, or `page.get_text()` to `pdf_corrupt`.
After opening, check `document.needs_pass` and return `pdf_encrypted` before page
access; do not attempt an empty password. Enforce page count before extraction.
Normalize pages first, calculate repeated edge lines across all physical pages
second, then remove only qualifying edge lines. Do not catch the base
`RuntimeError`, `Exception`, or errors raised by the normalization code;
programmer/unrecognized failures propagate.

- [ ] **Step 5: Run focused tests and dependency import check**

Run:

```powershell
python -c "import pymupdf; print(pymupdf.__version__)"
python -m pytest tests/fulltext/test_parser.py -q
```

Expected: a PyMuPDF version is printed and all parser tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add paper_agent/fulltext/parser.py paper_agent/fulltext/__init__.py tests/fulltext/test_parser.py
git commit -m "feat: parse page-aware pdf text"
```

### Task 8: Replace flat text splitting with section/page-aware chunks

**Files:**
- Modify: `paper_agent/text/chunker.py`
- Modify: `tests/test_chunker.py`
- Modify: `tests/test_chunker_sections.py`

- [ ] **Step 1: Write failing section and page tests**

Change the public entry point to accept a `PaperDocument` and return diagnostics:

```python
@dataclass(frozen=True, slots=True)
class ChunkingOutcome:
    chunks: tuple[Chunk, ...]
    warnings: tuple[str, ...] = ()


def chunk_document(
    document: PaperDocument,
    *,
    max_words: int = 180,
    overlap_words: int = 30,
) -> ChunkingOutcome: ...
```

Test canonical and numbered headings, nearest-section propagation, one-based
starting page, deterministic IDs, and no intentional crossing of a recognized
section boundary.

- [ ] **Step 2: Write failing window, fallback, and reference tests**

Cover:

- a 181-word section creates two chunks with exactly 30 overlapping words;
- `max_words=180`, `overlap_words=30` are the active v1 values;
- `overlap_words < max_words` and positive values are enforced;
- a chunk spanning page text retains its starting page;
- no reliable heading uses page-aware windows and emits
  `section_detection_failed`;
- a reliable `References` heading excludes later text and emits
  `reference_section_excluded`;
- a word “references” inside body prose is not a heading;
- identical normalized input/settings produce identical IDs and text.

- [ ] **Step 3: Run chunk tests and confirm expected failure**

Run:

```powershell
python -m pytest tests/test_chunker.py tests/test_chunker_sections.py -q
```

Expected: FAIL because current `chunk_text()` has no page/document contract or
overlap.

- [ ] **Step 4: Implement the minimal deterministic chunker**

Recognize only line-isolated canonical names or numbered headings. Flatten pages
into `(word, page)` pairs within the active section, then create windows with
step `max_words - overlap_words`. Build IDs in final output order:

```python
chunk_id = f"{document.paper_id}:chunk:{sequence:03d}"
```

Do not use an LLM, tokenizer network call, or font/layout inference. Keep a
small deprecated `chunk_text()` wrapper only until all current callers migrate
in Task 16; tests for new behavior must call `chunk_document()`.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest tests/test_chunker.py tests/test_chunker_sections.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add paper_agent/text/chunker.py tests/test_chunker.py tests/test_chunker_sections.py
git commit -m "feat: chunk papers by section and page"
```

### Task 9: Add explicit PDF-to-abstract acquisition outcomes

**Files:**
- Create: `paper_agent/fulltext/service.py`
- Modify: `paper_agent/fulltext/__init__.py`
- Create: `tests/fulltext/test_service.py`

- [ ] **Step 1: Write failing explicit-mode and success tests**

Define the orchestration boundary:

```python
class AcquisitionOutcome(StrictModel):
    document: PaperDocument | None
    record: DocumentRecord | None
    degradations: list[RunIssue] = Field(default_factory=list)
    excluded_code: str | None = None
```

A model validator requires document/record together, forbids `excluded_code`
when they exist, and requires it when they are absent. Test:

- `no_pdf=True` with text never calls downloader/parser, creates one abstract
  page, hashes normalized UTF-8 abstract text, and has no degradation;
- PDF success records `content_source="pdf"` and no fallback;
- an empty abstract in explicit no-PDF mode produces an excluded outcome with
  `excluded_code="abstract_text_empty"` and one `RunIssue(stage="acquisition",
  code="abstract_text_empty", paper_id=...)` in `degradations`; exclusion makes
  an otherwise successful multi-paper run `completed_with_degradation`.

- [ ] **Step 2: Write failing typed-fallback tests**

Parameterize every downloader/parser code from the spec. With a non-empty
abstract, each produces:

```python
assert outcome.document.content_source == "abstract"
assert outcome.record.fallback_code == expected_code
assert outcome.degradations[0].code == expected_code
```

With an empty abstract, the same failure excludes the paper. Assert unexpected
`RuntimeError`/programmer errors propagate and are not mislabeled as PDF
fallback.

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
python -m pytest tests/fulltext/test_service.py -q
```

Expected: FAIL because acquisition service is missing.

- [ ] **Step 4: Implement document acquisition**

Implement:

```python
class DocumentAcquirer:
    def __init__(
        self,
        *,
        downloader: FullTextDownloader,
        parser: PdfParser,
    ) -> None: ...

    def acquire(self, paper: Paper, *, no_pdf: bool) -> AcquisitionOutcome: ...
```

Normalize abstract documents as `DocumentPage(page_number=1, text=...)` and hash
exactly the stored normalized text bytes. Catch only `PdfDownloadError` and
`PdfParseError`. Convert their safe `code/message` into a `RunIssue` without raw
URL response bodies. Raw PDF/page bytes remain only in local variables.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest tests/fulltext/test_service.py tests/fulltext/test_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add paper_agent/fulltext/service.py paper_agent/fulltext/__init__.py tests/fulltext/test_service.py
git commit -m "feat: acquire pdfs with explicit fallback"
```

### Task 10: Build isolated per-paper evidence packs

**Files:**
- Modify: `paper_agent/evidence/hybrid.py`
- Create: `paper_agent/evidence/packs.py`
- Modify: `paper_agent/evidence/__init__.py`
- Modify: `tests/evidence/test_hybrid_retriever.py`
- Create: `tests/evidence/test_evidence_packs.py`
- Modify: `tests/evidence/test_hybrid_retrieval_integration.py`

- [ ] **Step 1: Write failing evidence-provenance tests**

Extend the existing candidate-to-evidence tests:

```python
assert outcome.evidence[0].section == "Methods"
assert outcome.evidence[0].page == 3
```

This must copy provenance already present on `RetrievalCandidate`; do not
re-derive it from text.

- [ ] **Step 2: Write failing pack validation/capping tests**

Define:

```python
class EvidencePack(StrictModel):
    paper_id: str
    evidence: list[Evidence]
    retrieval: RetrievalRecord


class RetrievalServiceFactory(Protocol):
    def __call__(
        self,
        settings: Settings,
        *,
        transport: EmbeddingTransport | None = None,
    ) -> ContextManager[EvidenceRetrievalService]: ...


class EvidencePackBuilder:
    def __init__(
        self,
        *,
        settings: Settings,
        embedding_transport: EmbeddingTransport | None,
        service_factory: RetrievalServiceFactory = build_retrieval_service,
    ) -> None: ...

    def build(
        self,
        *,
        question: str,
        paper_id: str,
        chunks: Sequence[Chunk],
        run_id: str,
        event_sink: RetrievalEventSink | None = None,
    ) -> EvidencePack: ...
```

Test scoped IDs begin with
`{run_id}:paper:{paper_id}:ev_`, duplicate chunk references are removed in rank
order, and results are capped at `settings.analysis_evidence_per_paper`.
Reject evidence with a foreign run/paper/chunk, mismatched quote, or mismatched
section/page against the in-memory `chunk_id -> Chunk` index.

- [ ] **Step 3: Write the failing resource-isolation integration test**

Use the real hybrid retriever, deterministic fake embeddings, and two papers
whose vector-nearest chunks differ. Call `builder.build()` twice and assert:

```python
assert all(item.paper_id == "paper-2" for item in second.evidence)
assert not ({item.chunk_id for item in first.evidence} &
            {item.chunk_id for item in second.evidence})
assert service_factory.created_store_count == 2
assert shared_transport.close_count == 0
```

The builder borrows the embedding transport; it must not close it. Each service
context must create and release a fresh `InMemoryVectorStore`.

- [ ] **Step 4: Run focused tests and confirm failure**

Run:

```powershell
python -m pytest tests/evidence/test_hybrid_retriever.py tests/evidence/test_evidence_packs.py tests/evidence/test_hybrid_retrieval_integration.py -q
```

Expected: FAIL on missing provenance and pack builder.

- [ ] **Step 5: Implement provenance and pack construction**

Copy `candidate.section/page` in `_candidates_to_evidence()`. In `build()`:

1. validate all input chunks belong to `paper_id`;
2. construct `scoped_run_id = f"{run_id}:paper:{paper_id}"`;
3. enter a newly returned retrieval-service context using the borrowed transport;
4. call the existing service against only this paper's chunks;
5. validate returned evidence against the in-memory chunk index;
6. deduplicate by `chunk_id`, preserve rank order, and cap;
7. create `RetrievalRecord` from diagnostics.

Do not modify `HybridEvidenceRetriever` to retain a global index or add a clear
method; isolation comes from service/store lifetime. The production factory is
`build_retrieval_service`; the counting fake implements the same callable and
returns a new context manager on every invocation. The builder passes its
borrowed transport by the keyword-only `transport` argument and never enters or
closes the transport itself.

During Task 16 pipeline integration, merge each `ChunkingOutcome.warnings` tuple
into the matching `DocumentRecord.warnings` before writing `documents.json`,
including the stable `reference_section_excluded` code.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m pytest tests/evidence/test_hybrid_retriever.py tests/evidence/test_evidence_packs.py tests/evidence/test_hybrid_retrieval_integration.py -q
```

Expected: PASS.

- [ ] **Step 7: Run the complete Chunk 2 regression suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS with no failures.

- [ ] **Step 8: Commit**

```powershell
git add paper_agent/evidence/hybrid.py paper_agent/evidence/packs.py paper_agent/evidence/__init__.py tests/evidence
git commit -m "feat: build isolated paper evidence packs"
```

## Chunk 3: DashScope Generation and Grounding

### Task 11: Define structured generation contracts and deterministic fakes

**Files:**
- Create: `paper_agent/generation/__init__.py`
- Create: `paper_agent/generation/contracts.py`
- Create: `tests/generation/__init__.py`
- Create: `tests/generation/fakes.py`
- Create: `tests/generation/test_contracts.py`

- [ ] **Step 1: Write failing strict-contract tests**

Cover message roles/content, strict extra-field rejection, non-negative elapsed
time, `attempts >= 1`, safe exception repr, and the exact independently optional
flattened fields `prompt_tokens`, `completion_tokens`, and `total_tokens`. Assert
there is no nested public `.usage` field. Test queued Pydantic results and typed
exceptions through `FakeGenerationProvider`.

- [ ] **Step 2: Run focused tests and confirm failure**

```powershell
python -m pytest tests/generation/test_contracts.py -q
```

Expected: FAIL because generation contracts do not exist.

- [ ] **Step 3: Implement exact contracts**

Implement strict `GenerationMessage` and the exact public result:

```python
class StructuredGeneration(StrictModel, Generic[ModelT]):
    result: ModelT
    model: str = Field(min_length=1)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    attempts: int = Field(ge=1)
    elapsed_seconds: float = Field(ge=0.0)

class GenerationFailureMetadata(StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    attempts: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0.0)

class GenerationProvider(Protocol):
    def generate_structured(
        self,
        *,
        operation: str,
        messages: Sequence[GenerationMessage],
        response_schema: type[ModelT],
        timeout: float,
    ) -> StructuredGeneration[ModelT]: ...
```

Add typed safe exceptions with stable codes: configuration, authentication,
request, timeout, network, rate-limit with optional retry delay, server, and
response errors. Their common base exposes only `code` and
`GenerationFailureMetadata`; a provider re-raises terminal failures with all
attempts, elapsed time, and response-supplied token counts accumulated so far.
Store no API key, body, raw response, provider payload, or prompt data.

- [ ] **Step 4: Implement the deterministic test fake**

The fake belongs under `tests/`, validates queued models with the requested
schema, records operation/messages/schema/timeout, never sleeps, and raises a
clear assertion when the queue or schema is wrong.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/generation/test_contracts.py -q
git add paper_agent/generation tests/generation
git commit -m "feat: define structured generation contracts"
```

Expected: tests PASS before the commit.

### Task 12: Implement one-attempt DashScope chat transport

**Files:**
- Create: `paper_agent/generation/dashscope_transport.py`
- Modify: `paper_agent/generation/__init__.py`
- Create: `tests/generation/test_dashscope_transport.py`

- [ ] **Step 1: Write failing request/success tests**

Using `httpx.MockTransport`, assert POST to
`{base_url}/chat/completions`, bearer auth,
`response_format={"type":"json_object"}`, exact messages/model, and propagated
timeout. Parse first-choice message content, response model, and optional usage.

- [ ] **Step 2: Write failing error/envelope tests**

Map 401/403 to authentication; 400/404/422 to request; 429 to rate-limit with
parsed delta-seconds `Retry-After`; 500-599 to server; timeout to timeout; other
`httpx.RequestError` to network; invalid JSON/envelope/content to response error.
Missing usage remains `None`, partial integer usage is preserved, no key/raw body
appears in errors, and the transport sends once without sleeping.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/generation/test_dashscope_transport.py -q
```

Expected: FAIL because the transport is missing.

- [ ] **Step 4: Implement one-attempt transport**

Create strict immutable internal `GenerationUsage` and
`GenerationHttpResponse` for the transport boundary, plus
`DashScopeChatTransport.send(messages, model, api_key, base_url, timeout)`.
These internal models may group provider usage, but the public
`StructuredGeneration` and failure metadata must expose only the approved
flattened token fields. Strip one trailing slash, append `/chat/completions`,
validate positive finite timeout, map malformed HTTP envelopes to
`GenerationResponseError` without retry/repair, and parse only documented
fields. A valid envelope whose message content later fails JSON/schema validation
is returned normally so Task 13 may repair it. The caller owns the injected
`httpx.Client`.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/generation/test_dashscope_transport.py -q
git add paper_agent/generation/dashscope_transport.py paper_agent/generation/__init__.py tests/generation/test_dashscope_transport.py
git commit -m "feat: call dashscope chat transport"
```

Expected: tests PASS before the commit.

### Task 13: Add bounded retry, schema repair, and usage aggregation

**Files:**
- Create: `paper_agent/generation/dashscope.py`
- Modify: `paper_agent/generation/__init__.py`
- Create: `tests/generation/test_dashscope_provider.py`

- [ ] **Step 1: Write failing retry tests**

Inject scripted transport, fake sleep, and monotonic clock. Verify one-send
success; no retry for authentication/request/configuration/response/network;
one retry for timeout/rate-limit/server; `Retry-After` capped at 10; invalid,
negative, or missing delay defaults to 1; unchanged per-attempt timeout; and no
repair after two failed original sends.

- [ ] **Step 2: Write failing JSON/schema-repair tests**

Test valid JSON without repair and invalid JSON/schema with one repair. Repair
retains the original grounded system/user messages, appends the invalid assistant
content as untrusted data truncated to `MAX_REPAIR_CONTENT_CHARS = 20_000`, and
adds one repair instruction containing a sanitized validation summary capped at
2,000 characters and five errors. The summary contains only error location and
type; it excludes Pydantic `input`, `ctx`, raw exception text, prompt data, and
provider diagnostics. Test one transient repair retry, maximum four sends, no
third logical request, attempts/elapsed including waits, and each flattened token
field summed independently across responses that supply it. A field remains
`None` only when no response supplies that field; never infer `total_tokens`.

For every terminal failure after provider construction, assert the raised typed
generation exception carries `GenerationFailureMetadata` with all HTTP sends,
elapsed time, and token counts supplied before failure. Include the case where an
invalid original response supplies usage and the repaired response remains
invalid. Configuration failure before a send reports zero attempts and no usage.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/generation/test_dashscope_provider.py -q
```

Expected: FAIL because the provider is missing.

- [ ] **Step 4: Implement one logical operation**

`DashScopeGenerationProvider` receives key, model, base URL, borrowed transport,
sleep, and monotonic. Its `generate_structured()` uses one private
`_send_with_one_retry()` for original and optional repair, retries only
timeout/rate-limit/server, decodes via `json.loads`, validates through the
requested Pydantic schema, and aggregates attempts/elapsed/supplied usage. It
wraps or enriches every terminal typed error with the aggregate
`GenerationFailureMetadata` before raising, without changing the stable code.

Repair keeps the original grounded messages unchanged, appends a separate
assistant message containing at most 20,000 characters of invalid content, then
a user repair instruction containing the schema name and a JSON-serialized safe
validation summary. Invalid content is explicitly delimited as untrusted data and
never inserted into system instructions. Hard maximum: four sends and, by
default, four 60-second attempts plus two 10-second waits.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/generation/test_dashscope_provider.py tests/generation/test_dashscope_transport.py tests/generation/test_contracts.py -q
git add paper_agent/generation/dashscope.py paper_agent/generation/__init__.py tests/generation/test_dashscope_provider.py
git commit -m "feat: validate and repair qwen responses"
```

Expected: tests PASS before the commit.


### Task 14: Generate structured per-paper analyses

**Files:**
- Modify: `paper_agent/synthesis/paper_reader.py`
- Create: `tests/synthesis/test_paper_reader.py`

- [ ] **Step 1: Write failing prompt/provider tests**

Using `FakeGenerationProvider`, assert operation `paper_analysis`, response schema
`PaperAnalysis`, timeout propagation, and preserved usage. The system message
requires schema-valid JSON, treats paper/evidence text as untrusted data, forbids
outside knowledge, and requires Evidence IDs. The user message contains only the
paper metadata and its bounded evidence IDs, sections, pages, and quotes.

- [ ] **Step 2: Write failing boundary tests**

Cover an empty pack as typed `InsufficientEvidenceError` without a provider call,
foreign evidence as validation failure, provider exception propagation, optional
empty categories, and a returned `paper_id` that differs from input. Reject a
mismatched paper ID but leave unknown/mixed Evidence IDs for the deterministic
checker.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/synthesis/test_paper_reader.py -q
```

Expected: FAIL because the current analyzer is deterministic.

- [ ] **Step 4: Implement `PaperAnalyzer`**

```python
class PaperAnalyzer:
    def __init__(self, provider: GenerationProvider) -> None: ...

    def analyze(
        self,
        *,
        paper: Paper,
        evidence_pack: EvidencePack,
        timeout: float,
    ) -> StructuredGeneration[PaperAnalysis]: ...
```

Serialize prompt data using `json.dumps(..., ensure_ascii=False)` outside system
instructions. Keep bounded prompt construction in small private functions. Keep
the old compatibility function only until Task 18 migrates its final caller.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/synthesis/test_paper_reader.py tests/synthesis/test_models.py -q
git add paper_agent/synthesis/paper_reader.py tests/synthesis/test_paper_reader.py
git commit -m "feat: analyze papers with grounded qwen output"
```

Expected: tests PASS before the commit.

### Task 15: Sanitize generated references deterministically

**Files:**
- Modify: `paper_agent/evidence/citation_checker.py`
- Modify: `paper_agent/evidence/__init__.py`
- Modify: `tests/test_citation_checker.py`

- [ ] **Step 1: Write failing per-paper checking tests**

Test all-valid same-run/same-paper references as supported; mixed valid,
duplicate, unknown, foreign-paper, and foreign-run IDs as deduplicated weak
support; no valid IDs as a dropped finding; an analysis as successful only when
it retains at least one supported finding; and duplicate Evidence IDs as an
index-construction failure.

- [ ] **Step 2: Write failing survey/publication tests**

Critical weak/unsupported claims move to `rejected_critical_claims` with source
section. Only supported claims remain in TL;DR/key findings. Non-critical
categories retain checked statuses. `require_publishable_report()` requires one
supported TL;DR and one supported key finding or raises code
`insufficient_supported_report`.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/test_citation_checker.py -q
```

Expected: FAIL because the current checker handles flat claims only.

- [ ] **Step 4: Implement one evidence-index path**

Define `CheckedAnalysisOutcome` in
`paper_agent/evidence/citation_checker.py` as a strict Pydantic boundary and
export it from `paper_agent.evidence`:

```python
class CheckedAnalysisOutcome(StrictModel):
    analysis: CheckedPaperAnalysis
    sanitized_reference_count: int = Field(ge=0)
    dropped_finding_count: int = Field(ge=0)
    has_supported_finding: bool

def check_paper_analysis(
    analysis: PaperAnalysis,
    evidence: Sequence[Evidence],
    *,
    run_id: str,
) -> CheckedAnalysisOutcome: ...

def check_survey_draft(
    question: str,
    draft: SurveyDraft,
    evidence: Sequence[Evidence],
    *,
    run_id: str,
) -> CheckedSurveyReport: ...

def require_publishable_report(report: CheckedSurveyReport) -> None: ...
```

`check_survey_draft()` copies the explicit non-empty `question` into the checked
report. Paper validity additionally requires matching `paper_id`. Preserve
claim/finding and first-seen ID order. Do not perform semantic LLM checking or
fuzzy quote matching.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_citation_checker.py tests/synthesis/test_models.py -q
git add paper_agent/evidence/citation_checker.py paper_agent/evidence/__init__.py tests/test_citation_checker.py
git commit -m "feat: sanitize generated evidence references"
```

Expected: tests PASS before the commit.

### Task 16: Generate the grounded cross-paper survey

**Files:**
- Modify: `paper_agent/synthesis/survey.py`
- Create: `tests/synthesis/test_survey.py`

- [ ] **Step 1: Write failing synthesis-call tests**

Pass checked analyses containing supported and weak findings. Assert the provider
receives only supported findings and resolvable evidence, calls
`survey_synthesis`, requests `SurveyDraft`, propagates timeout, and preserves
usage. One-paper input is allowed.

- [ ] **Step 2: Write failing minimum/boundary tests**

Cover no successful analyses, an analysis with no supported finding, foreign
evidence IDs, provider errors, and a generated draft with invalid IDs. Invalid
draft IDs remain for Task 15 checking; the synthesizer must not alter them.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/synthesis/test_survey.py -q
```

Expected: FAIL because current synthesis is deterministic and flat.

- [ ] **Step 4: Implement `SurveySynthesizer`**

```python
class SurveySynthesizer:
    def __init__(self, provider: GenerationProvider) -> None: ...

    def synthesize(
        self,
        *,
        question: str,
        analyses: Sequence[CheckedPaperAnalysis],
        evidence: Sequence[Evidence],
        timeout: float,
    ) -> StructuredGeneration[SurveyDraft]: ...
```

Require at least one analysis with a supported finding before the provider call.
Serialize the question, supported analyses, and their referenced evidence as
untrusted JSON data outside system instructions. Require grounded taxonomy,
comparisons, key findings, limitations, and open questions without outside
claims.

- [ ] **Step 5: Run focused and complete Chunk 3 tests**

```powershell
python -m pytest tests/synthesis/test_survey.py tests/synthesis/test_paper_reader.py tests/test_citation_checker.py -q
python -m pytest -q
```

Expected: focused tests and complete suite PASS with no failures.

- [ ] **Step 6: Commit**

```powershell
git add paper_agent/synthesis/survey.py tests/synthesis/test_survey.py
git commit -m "feat: synthesize grounded cross-paper surveys"
```


## Chunk 4: Pipeline Integration, Formal Report, and Release Acceptance

### Task 17: Render the formal checked report

**Files:**
- Modify: `paper_agent/rendering/markdown.py`
- Modify: `tests/test_synthesis.py`
- Create: `tests/test_formal_report.py`

- [ ] **Step 1: Write failing section and provenance tests**

Build a `CheckedSurveyReport`, papers, document records, and evidence. Assert the
Markdown contains, in order: title/status, TL;DR, Selected Papers, Method
Taxonomy, Cross-Paper Comparison, Key Findings, Limitations, Open Questions, and
Evidence Trace. Each retained paper shows `PDF`, `abstract`, or its fallback code.

The renderer receives only retained papers that have a matching
`DocumentRecord`; initially selected but excluded papers remain in `papers.json`
and manifest issues, not the formal report. For every rendered evidence marker
assert paper title, section or `Unknown section`, one-based page or `Unknown
page`, chunk ID, and exact evidence quote. Critical claims must render resolvable
markers.

- [ ] **Step 2: Write failing safety/determinism tests**

Assert `rejected_critical_claims` never appears in TL;DR or Key Findings; weak or
unsupported non-critical claims are explicitly labeled; no claim is invented
when a category is empty; identical checked inputs produce identical Markdown;
and renderer input contains no raw PDF/page text or provider prompt/response.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/test_formal_report.py tests/test_synthesis.py -q
```

Expected: FAIL because the current renderer emits only the mini survey.

- [ ] **Step 4: Implement a pure checked-model renderer**

Implement:

```python
def render_formal_report(
    *,
    status: Literal["completed", "completed_with_degradation"],
    papers: Sequence[Paper],
    documents: Sequence[DocumentRecord],
    evidence: Sequence[Evidence],
    report: CheckedSurveyReport,
) -> str: ...
```

Use `report.question` as the only title/question source. Validate unique
paper/document/evidence IDs and all evidence references before rendering. Keep
fixed labels/provenance formatting in small helpers. Do not call a provider,
re-check semantics, or filter critical arrays independently; those arrays are
already sanitized model invariants.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/test_formal_report.py tests/test_synthesis.py -q
git add paper_agent/rendering/markdown.py tests/test_formal_report.py tests/test_synthesis.py
git commit -m "feat: render formal evidence-backed surveys"
```

Expected: tests PASS before the commit.

### Task 18: Integrate the successful offline vertical pipeline

**Files:**
- Modify: `paper_agent/pipeline.py`
- Modify: `paper_agent/text/loader.py`
- Modify: `tests/test_pipeline_vertical_slice.py`
- Modify: `tests/test_pipeline_evidence_trace.py`
- Modify: `tests/test_pipeline_hybrid_retrieval.py`
- Create: `tests/test_pipeline_fulltext_integration.py`

- [ ] **Step 1: Write the failing offline PDF-to-report integration test**

Fake only arXiv search, PDF HTTP, embedding HTTP, and generation provider. Use a
real synthetic multi-page PDF, parser, chunker, hybrid retriever/fusion,
evidence-pack validator, citation checker, recorder, and renderer. Run
`limit=3` and assert all eight artifacts:

```python
EXPECTED = {
    "papers.json",
    "documents.json",
    "evidence.json",
    "analyses.json",
    "report.json",
    "report.md",
    "run_manifest.json",
    "logs.jsonl",
}
assert {path.name for path in result.run_dir.iterdir()} == EXPECTED
assert result.status == "completed"
```

Validate every JSON file against its exact Pydantic contract, every Evidence ID
resolves to the correct paper/chunk/page/section/quote, each paper has a separate
retrieval record, and manifest usage equals all paper plus survey generation
usage.

- [ ] **Step 2: Write failing explicit no-PDF integration test**

With `no_pdf=True`, assert PDF transport/parser are never called, every
`DocumentRecord.content_source` is `abstract`, fallback count is zero, generation
still uses `qwen3.7-plus`, and the report is formal and citation checked.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/test_pipeline_fulltext_integration.py tests/test_pipeline_vertical_slice.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_hybrid_retrieval.py -q
```

Expected: FAIL because the current pipeline has abstract placeholders and two
artifacts only.

- [ ] **Step 4: Define exact orchestration dependencies and result**

In `paper_agent.pipeline`, add:

```python
@dataclass(frozen=True, slots=True)
class PipelineDependencies:
    search: SearchFn
    downloader: FullTextDownloader
    parser: PdfParser
    evidence_packs: EvidencePackBuilder
    analyzer: PaperAnalyzer
    synthesizer: SurveySynthesizer
    recorder_factory: RecorderFactory
    embedding_transport: EmbeddingTransport | None = None

@dataclass(frozen=True, slots=True)
class PipelineResult:
    run_dir: Path
    status: Literal["completed", "completed_with_degradation"]
```

Production assembly owns one PDF `httpx.Client`, one embedding transport, and one
generation `httpx.Client`/transport/provider in an `ExitStack`; injected
dependencies are borrowed and never closed. The evidence builder creates a fresh
service/store per paper while borrowing the one embedding transport.

- [ ] **Step 5: Implement the successful orchestration path**

Refactor `run_pipeline()` to:

1. load/validate settings and generation key before external calls;
2. start the recorder before arXiv search;
3. search/dedupe/limit and write `papers.json`;
4. acquire document, chunk it, merge chunk warnings into its document record;
5. build one isolated evidence pack per retained paper;
6. analyze and citation-check each paper;
7. enforce the successful-analysis minimum;
8. synthesize, citation-check, and require a publishable report;
9. write documents/evidence/analyses, publish report JSON/Markdown;
10. complete the manifest last and return `PipelineResult`.

Aggregate each generation token field independently, total HTTP attempts,
per-stage monotonic timings, retrieval outcomes, component versions, counts, and
degradations. Remove the old deterministic loader/analyzer/survey path only after
all callers migrate.

- [ ] **Step 6: Verify successful integration and existing retrieval contracts**

```powershell
python -m pytest tests/test_pipeline_fulltext_integration.py tests/test_pipeline_vertical_slice.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_hybrid_retrieval.py tests/test_pipeline_retrieval_failures.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add paper_agent/pipeline.py paper_agent/text/loader.py tests/test_pipeline_fulltext_integration.py tests/test_pipeline_vertical_slice.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_hybrid_retrieval.py
git commit -m "feat: integrate full-text survey pipeline"
```

### Task 19: Enforce terminal failure and degradation semantics

**Files:**
- Modify: `paper_agent/pipeline.py`
- Modify: `paper_agent/observability/recorder.py`
- Modify: `tests/test_pipeline_retrieval_failures.py`
- Create: `tests/test_pipeline_terminal_states.py`

- [ ] **Step 1: Write failing PDF/retrieval degradation tests**

Parameterize every approved PDF fallback code. With a usable abstract, assert
`completed_with_degradation`, fallback count, `DocumentRecord.fallback_code`,
safe `RunIssue`, and a formal report. With no abstract, assert exclusion and the
same degraded status only when the remaining papers still satisfy the analysis
minimum. Explicit `--no-pdf` alone remains `completed`.

Test `auto` vector transient failure as lexical degradation. Explicit `hybrid`
vector failure, retrieval assembly/configuration, lexical, or fusion failure
must fail the whole run rather than silently skipping that paper or changing
mode.

- [ ] **Step 2: Write failing generation/minimum tests**

Define the exact policy:

- authentication, configuration, request/model, and `GenerationNetworkError`
  fail the whole run because network errors are not an approved retry/fallback;
- exhausted timeout/rate-limit/server/valid-envelope-response failure for one
  paper may skip that analysis and mark degradation;
- when two or more papers were retrieved, at least two checked analyses with a
  supported finding are required;
- when exactly one paper was retrieved, one is required;
- survey generation/repair failure is always terminal;
- below-minimum checked TL;DR/key findings is terminal code
  `insufficient_supported_report`.

Add a publishable case where paper or survey citation checking removes duplicate,
unknown, foreign-paper, or foreign-run references but retains enough supported
content. Assert `completed_with_degradation` and a safe
`citation_references_sanitized` `RunIssue` with sanitized/dropped counts.

For each terminal case assert `run_manifest.status == "failed"`, safe failure
metadata/usage is retained, `logs.jsonl` ends with an error event, and no
`report.md` exists. Already completed safe intermediates remain.

- [ ] **Step 3: Write failing unexpected-exception finalization test**

Inject an unexpected exception after recorder start. Assert the manifest still
becomes `failed` with code `unexpected_pipeline_error`, the log/message contains
no secret or raw exception object, and the original exception remains the Python
cause for local debugging. Calling a conflicting terminal transition still
raises.

- [ ] **Step 4: Run and confirm failure**

```powershell
python -m pytest tests/test_pipeline_terminal_states.py tests/test_pipeline_retrieval_failures.py -q
```

Expected: FAIL because current orchestration has no terminal manifest contract.

- [ ] **Step 5: Implement one top-level finalization boundary**

Use one `try/except` around work after `RunRecorder.start()`. Catch typed
configuration/retrieval/generation/publication errors first and finalize with
their stable code and accumulated metrics. Catch unexpected exceptions last,
sanitize the persisted event, finalize once, then raise
`PipelineRunFailed(run_dir, code)` from the original exception.

Do not catch `KeyboardInterrupt` or `SystemExit`. A partial complete
`report.json` left by a second replacement failure is permitted as a safe
intermediate, but `report.md` and a completed terminal status are not.

- [ ] **Step 6: Verify terminal semantics and complete regression suite**

```powershell
python -m pytest tests/test_pipeline_terminal_states.py tests/test_pipeline_retrieval_failures.py tests/observability/test_recorder.py -q
python -m pytest -q
```

Expected: focused tests and complete suite PASS with no failures.

- [ ] **Step 7: Commit**

```powershell
git add paper_agent/pipeline.py paper_agent/observability/recorder.py tests/test_pipeline_terminal_states.py tests/test_pipeline_retrieval_failures.py
git commit -m "feat: enforce truthful pipeline terminal states"
```


### Task 20: Deliver truthful CLI, setup documentation, and release metadata

**Files:**
- Modify: `paper_agent/cli.py`
- Modify: `paper_agent/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Create: `README.md`
- Create: `docs/fulltext-survey.md`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Write failing CLI outcome tests**

Mock `run_pipeline()` and cover:

- `completed` exits 0 and prints status/run directory plus all eight artifact
  paths;
- `completed_with_degradation` exits 0 and prints a concise degradation warning;
- `PipelineRunFailed` exits 1, prints only safe code/run directory and points to
  manifest/log when present, never claims `report.md` was created, and shows no
  traceback or secret;
- missing `DASHSCOPE_API_KEY` for the default run exits 1 with a safe actionable
  message;
- `--no-pdf` remains explicit and does not disable Qwen generation.

- [ ] **Step 2: Write failing release/config cleanup tests**

Assert the project has no runtime OpenAI SDK dependency or unused OpenAI
settings, `.env.example` contains every approved safe default with an empty key,
wheel includes AGPL/third-party notices, and help text documents default PDF
behavior and explicit abstract mode.

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m pytest tests/test_cli.py tests/test_config.py tests/test_packaging.py -q
```

Expected: FAIL until CLI result handling and release documentation metadata are
migrated.

- [ ] **Step 4: Implement truthful CLI behavior**

Catch only typed configuration and `PipelineRunFailed` errors at the CLI
boundary. Use Typer stderr/error exits, never print secret-bearing settings, and
render success from `PipelineResult`. Do not catch unexpected programming errors
as a successful command.

Remove unused `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `PAPER_AGENT_MODEL`
settings plus the obsolete `llm` optional dependency only after `rg` confirms no
production caller. Keep DashScope embedding and generation on the shared key.

- [ ] **Step 5: Write user and operator documentation**

`README.md` provides installation, `.env` creation, one default command, one
`--no-pdf` command, output location, and links to detailed docs. The detailed
guide documents:

- public text-native arXiv-only scope and no OCR;
- DashScope shared-key variables and exact default models;
- default PDF versus explicit abstract behavior;
- all eight artifacts and three terminal states;
- fallback, retrieval, generation, and citation failure semantics;
- timeout/byte/page/evidence limits;
- token usage and evidence-trace interpretation;
- AGPL implications and third-party notice;
- offline tests and the manual live smoke command.

Examples use `DASHSCOPE_API_KEY=` or `your-key-here`, never a key-like fixture.

- [ ] **Step 6: Verify CLI, packaging, and docs**

```powershell
python -m pytest tests/test_cli.py tests/test_config.py tests/test_packaging.py -q
python -m paper_agent.cli --help
python -m paper_agent.cli run --help
```

Expected: tests PASS; help shows default PDF behavior and `--no-pdf`.

- [ ] **Step 7: Commit**

```powershell
git add paper_agent/cli.py paper_agent/config.py pyproject.toml .env.example README.md docs/fulltext-survey.md tests/test_cli.py tests/test_config.py tests/test_packaging.py
git commit -m "docs: ship production full-text cli workflow"
```

### Task 21: Run offline release verification and a separate live smoke

**Files:**
- Modify only if a failing verification first receives a deterministic regression
  test in the owning task's test file.
- Verify: all production, test, license, configuration, and documentation files
  changed by Tasks 1-20.

- [ ] **Step 1: Run static repository checks**

```powershell
rg -n "^(<<<<<<<|=======|>>>>>>>)" . -g '!outputs/**'
git diff --check
python -m compileall -q paper_agent
```

Expected: no conflict markers, no diff errors, and successful compilation.

- [ ] **Step 2: Run the complete offline suite**

```powershell
python -m pytest -q
```

Expected: PASS with no failures. Normal pytest must make no live arXiv or
DashScope request.

- [ ] **Step 3: Build and inspect the wheel in a safe temporary directory**

Use the same pre-existing-directory guard, resolved-path containment check, build,
and cleanup `try/finally` from Task 1. Inside its `try` block, after proving
`$wheels.Count -eq 1`, run:

```powershell
$env:WHEEL_PATH = $wheels[0].FullName
@'
import os
import zipfile
from pathlib import Path

wheel = Path(os.environ["WHEEL_PATH"])
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()

required = (
    "paper_agent/fulltext/__init__.py",
    "paper_agent/generation/__init__.py",
    "paper_agent/observability/__init__.py",
    "paper_agent/synthesis/__init__.py",
)
missing = [name for name in required if name not in names]
assert not missing, missing
licenses = [
    name for name in names
    if name.endswith(".dist-info/licenses/LICENSE")
    or name.endswith(".dist-info/LICENSE")
]
assert len(licenses) == 1, licenses
assert not any(name.startswith("outputs/") for name in names)
assert not any(name.startswith("tests/") for name in names)
assert not any(Path(name).name == ".env" for name in names)
print("WHEEL_CONTENT_OK")
'@ | python -
if ($LASTEXITCODE -ne 0) { throw 'wheel content inspection failed' }
```

Expected: exactly one wheel and license entry, all required package modules,
runtime/user/test files absent, and `WHEEL_CONTENT_OK`.

- [ ] **Step 4: Confirm live-smoke prerequisites without printing the key**

```powershell
python -c "from paper_agent.config import load_settings; s=load_settings(); assert s.dashscope_api_key; assert s.bailian_embedding_model == 'text-embedding-v4'; assert s.dashscope_generation_model == 'qwen3.7-plus'; print('LIVE_CONFIG_OK')"
```

Expected: `LIVE_CONFIG_OK`. If no key is configured, stop only the manual live
smoke and report that external prerequisite; do not weaken offline acceptance.

- [ ] **Step 5: Run the default live vertical smoke**

This is intentionally outside normal pytest:

```powershell
paper-agent run "hybrid retrieval for scientific literature review" --limit 3
```

Expected: exit 0 with `completed` or documented
`completed_with_degradation`, and one new run directory containing all eight
artifacts.

- [ ] **Step 6: Validate live artifacts without exposing secrets**

Set `$runDir` to the exact path printed by the command, then run:

```powershell
$expected = @('papers.json','documents.json','evidence.json','analyses.json','report.json','report.md','run_manifest.json','logs.jsonl')
$missing = $expected | Where-Object { -not (Test-Path -LiteralPath (Join-Path $runDir $_)) }
if ($missing) { throw "missing artifacts: $($missing -join ', ')" }
$env:PAPER_AGENT_RUN_DIR = $runDir
@'
import json
import os
from pathlib import Path

from paper_agent.config import load_settings
from paper_agent.schemas import Evidence
from paper_agent.synthesis.models import CheckedPaperAnalysis, CheckedSurveyReport

run_dir = Path(os.environ["PAPER_AGENT_RUN_DIR"])
manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
evidence = [
    Evidence.model_validate(item)
    for item in json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
]
analyses = [
    CheckedPaperAnalysis.model_validate(item)
    for item in json.loads((run_dir / "analyses.json").read_text(encoding="utf-8"))
]
report = CheckedSurveyReport.model_validate_json(
    (run_dir / "report.json").read_text(encoding="utf-8")
)

assert manifest["status"] in {"completed", "completed_with_degradation"}
assert manifest["settings"]["generation_model"] == "qwen3.7-plus"
assert manifest["settings"]["embedding_model"] == "text-embedding-v4"
assert manifest["counts"]["successful_analyses"] >= 2
assert len(analyses) >= 2
assert len(manifest["retrieval_outcomes"]) >= 2
assert manifest["usage"]["operations"] >= 3

finding_fields = ("contributions", "methods", "experiments", "results", "limitations")
for analysis in analyses:
    findings = [
        finding
        for field in finding_fields
        for finding in getattr(analysis, field)
    ]
    assert any(finding.support_status == "supported" for finding in findings)

critical = [*report.tldr_claims, *report.key_findings]
assert report.tldr_claims and report.key_findings
assert all(claim.support_status == "supported" for claim in critical)
valid_ids = {item.evidence_id for item in evidence}
assert all(claim.evidence_ids for claim in critical)
assert all(set(claim.evidence_ids) <= valid_ids for claim in critical)

key = load_settings().dashscope_api_key or ""
assert not key or all(
    key not in file.read_text(encoding="utf-8", errors="ignore")
    for file in run_dir.iterdir()
    if file.is_file()
)
print("LIVE_ARTIFACTS_OK")
'@ | python -
if ($LASTEXITCODE -ne 0) { throw 'live artifact validation failed' }
```

Expected: `LIVE_ARTIFACTS_OK`. Manually inspect `report.md` for supported TL;DR,
key findings, content-source labels, and page/section/chunk evidence trace.

- [ ] **Step 7: Run an explicit abstract-mode smoke**

```powershell
paper-agent run "hybrid retrieval for scientific literature review" --limit 1 --no-pdf
```

Expected: exit 0, `no_pdf=true`, `explicit_abstract_documents=1`,
`pdf_fallback_documents=0`, formal Qwen report, and no PDF download event.

- [ ] **Step 8: Fix live-only discoveries through TDD, then reverify**

For each defect, add a deterministic fake/fixture test that fails for the same
contract, implement the smallest fix, run focused plus complete offline tests,
and commit separately. Never make normal pytest depend on the live service.

- [ ] **Step 9: Final handoff verification**

```powershell
git status --short --branch
git log --oneline --decorate -20
git diff --check
python -m pytest -q
```

Expected: intended branch only, clean worktree, reviewed task commits, no diff
errors, and complete suite PASS. Record the live run directory/status, commands,
test result, and any remaining text-native-PDF limitation in the handoff.
