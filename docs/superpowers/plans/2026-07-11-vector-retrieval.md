# Text Vector Retrieval Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independently testable text-vector indexing and retrieval path using Bailian `text-embedding-v4`, a replaceable vector-store contract, and an in-memory reference store without changing lexical Evidence Trace behavior.

**Architecture:** Add a focused `paper_agent/vector/` package. `VectorRetriever` orchestrates an injected `Embedder` and `VectorStore`; Bailian HTTP details remain behind an injectable transport, while the in-memory store supplies deterministic contract tests and offline development.

**Tech Stack:** Python 3.10+, Pydantic 2, httpx, pytest, standard-library protocols/dataclasses/hashlib/math.

**Scope constraints:** Text embedding only. Do not add multimodal embedding, pgvector/Qdrant, hybrid fusion, rerank, generation, retries, or changes to `paper_agent.evidence.retriever` and its offline fallback.

---

## Chunk 1: Contracts and configuration

### Task 1: Add vector-domain models and protocols

**Files:**
- Create: `paper_agent/vector/__init__.py`
- Create: `paper_agent/vector/models.py`
- Create: `paper_agent/vector/contracts.py`
- Test: `tests/vector/test_contracts.py`

- [ ] **Step 1: Write failing model-validation tests**

Cover:

```python
def test_vector_metadata_contains_required_provenance(): ...
def test_vector_search_result_rejects_score_outside_unit_interval(): ...
def test_vector_filter_accepts_only_typed_paper_id(): ...
def test_vector_candidate_preserves_stable_chunk_identity_and_text(): ...
```

Define expected immutable domain objects:

```python
class VectorFilter(BaseModel):
    paper_id: str | None = None

class VectorRecordMetadata(BaseModel):
    paper_id: str
    chunk_id: str
    section: str | None
    page: int | None
    content_hash: str
    embedding_model: str

class VectorSearchResult(BaseModel):
    chunk_id: str
    text: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: VectorRecordMetadata

class VectorCandidate(BaseModel):
    chunk_id: str
    paper_id: str
    text: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: VectorRecordMetadata
```

- [ ] **Step 2: Run the focused tests and record RED**

Run: `python -m pytest tests/vector/test_contracts.py -q`

Expected: collection fails because `paper_agent.vector` models do not exist.

- [ ] **Step 3: Implement minimal models and structural protocols**

Use `typing.Protocol`:

```python
class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

class VectorStore(Protocol):
    @property
    def embedding_model(self) -> str: ...
    def ensure_collection(self, vector_size: int) -> None: ...
    def upsert(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None: ...
    def search(self, query_embedding: Sequence[float], limit: int, filters: VectorFilter | None = None) -> list[VectorSearchResult]: ...
    def delete_by_paper(self, paper_id: str) -> None: ...
```

All contract models are frozen. `VectorFilter` additionally uses `extra="forbid"` so callers cannot pass database expressions through unknown fields. The store is configured for one `embedding_model` when instantiated and creates `content_hash = sha256(chunk.text.encode("utf-8")).hexdigest()` at its persistence boundary. This preserves the requested `upsert(chunks, embeddings)` signature while ensuring model provenance. `VectorSearchResult.text` is persisted record data, allowing a future database-backed retriever to work in a fresh process. Do not add vector fields to the existing `Chunk` schema.

- [ ] **Step 4: Run focused tests and record GREEN**

Run: `python -m pytest tests/vector/test_contracts.py -q`

Expected: PASS.

### Task 2: Extend safe environment configuration

**Files:**
- Modify: `paper_agent/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add failing configuration tests**

Test defaults and environment normalization for:

```text
DASHSCOPE_API_KEY=None              # repr-hidden
BAILIAN_REGION=beijing
BAILIAN_EMBEDDING_MODEL=text-embedding-v4
VECTOR_COLLECTION=momo_scholar_chunks_v1
RETRIEVAL_CANDIDATE_K=30
```

Reject non-integer or `< 1` candidate counts with a clear `ValueError`. Preserve all existing settings and tests.

- [ ] **Step 2: Run configuration tests and record RED**

Run: `python -m pytest tests/test_config.py -q`

Expected: FAIL because vector settings are absent.

- [ ] **Step 3: Add minimal settings fields and parsing**

Keep `dashscope_api_key` declared as `field(default=None, repr=False)`. Normalize optional strings consistently with existing configuration code.

- [ ] **Step 4: Run configuration tests and record GREEN**

Run: `python -m pytest tests/test_config.py -q`

Expected: PASS.

## Chunk 2: Bailian text embedding boundary

### Task 3: Validate embedding batches independently of HTTP

**Files:**
- Create: `paper_agent/vector/embedding.py`
- Test: `tests/vector/test_embedding.py`

- [ ] **Step 1: Write failing validation tests**

Cover empty input returning `[]`, input/output count mismatch, empty vectors, inconsistent dimensions, booleans/non-numeric values, NaN, and infinity. A valid batch returns `list[list[float]]` without changing row order.

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/vector/test_embedding.py -q`

Expected: FAIL because validation does not exist.

- [ ] **Step 3: Implement `_validate_embedding_batch`**

The function receives original texts and transport vectors, validates count and dimension, converts finite numeric values to floats, and raises a vector-specific `EmbeddingResponseError` with no input text or API key in the message.

- [ ] **Step 4: Run focused tests and record GREEN**

Run: `python -m pytest tests/vector/test_embedding.py -q`

Expected: PASS.

### Task 4: Add injectable Bailian transport and adapter

**Files:**
- Create: `paper_agent/vector/bailian.py`
- Test: `tests/vector/test_bailian_embedder.py`
- Test: `tests/vector/test_bailian_http_transport.py`

- [ ] **Step 1: Verify the current official Bailian Beijing text-embedding HTTP documentation**

Confirm the Beijing endpoint, authorization header, synchronous request body for batch strings, and ordered embedding response fields for `text-embedding-v4`. Record the official documentation URL in a module comment or plan execution note. Do not infer a response shape from third-party examples.

- [ ] **Step 2: Write failing adapter tests with a fake transport**

Define a narrow transport contract similar to:

```python
class EmbeddingTransport(Protocol):
    def embed(self, *, texts: Sequence[str], model: str, api_key: str, region: str, timeout: float) -> list[list[float]]: ...
```

Test default model/region, batch order, empty input without a transport call, missing API key, explicit timeout forwarding, timeout propagation as `EmbeddingTimeoutError`, HTTP/API failure as `EmbeddingTransportError`, count mismatch, and dimension mismatch. Assert exception/repr text never contains the sentinel API key.

- [ ] **Step 3: Run adapter tests and record RED**

Run: `python -m pytest tests/vector/test_bailian_embedder.py -q`

Expected: FAIL because the adapter is absent.

- [ ] **Step 4: Implement `BailianTextEmbedder`**

Defaults:

```python
model_name = "text-embedding-v4"
region = "beijing"
timeout = 30.0
```

Require a non-empty API key only for non-empty embedding calls. Delegate I/O to the injected transport and validate the returned batch centrally.

- [ ] **Step 5: Write failing HTTP transport tests**

Use `httpx.MockTransport`; never contact the network. Assert the verified Beijing URL, bearer authorization header without logging it, JSON model/input fields, request order, explicit timeout request extension, ordered response parsing, and no SDK use. Cover `httpx.TimeoutException`, HTTP 4xx/5xx, API-level error payload, non-JSON response, missing fields, invalid embedding rows, and response indices returned out of order.

- [ ] **Step 6: Run HTTP transport tests and record RED**

Run: `python -m pytest tests/vector/test_bailian_http_transport.py -q`

Expected: FAIL because the HTTP transport is absent.

- [ ] **Step 7: Implement `HttpxEmbeddingTransport` against the verified official contract**

Use the existing `httpx` dependency, explicit timeout, `raise_for_status`, bounded response parsing, and sanitized domain exceptions. The transport alone maps `httpx.TimeoutException` to `EmbeddingTimeoutError` and HTTP/API/parse failures to `EmbeddingTransportError`; `BailianTextEmbedder` propagates those domain errors and only validates batch count/dimensions. Do not use the Bailian SDK and do not add online tests to the normal suite.

- [ ] **Step 8: Run focused tests and record GREEN**

Run: `python -m pytest tests/vector/test_bailian_embedder.py tests/vector/test_bailian_http_transport.py tests/vector/test_embedding.py -q`

Expected: PASS with no network calls.

## Chunk 3: In-memory VectorStore reference implementation

### Task 5: Establish collection and upsert behavior

**Files:**
- Create: `paper_agent/vector/memory_store.py`
- Test: `tests/vector/test_memory_store.py`

- [ ] **Step 1: Write failing collection/upsert tests**

Cover a required non-empty store `embedding_model`, positive `vector_size`, idempotent repeated `ensure_collection`, rejection of a different dimension, equal chunk/embedding counts, embedding dimension checks, zero document vectors, stable `chunk_id` overwrite, and complete metadata including SHA-256 hash/model and original text.

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/vector/test_memory_store.py -q`

Expected: FAIL because the store is absent.

- [ ] **Step 3: Implement minimal collection and record storage**

Keep process-local records keyed by `chunk_id`. Validate the complete incoming batch before mutating state so failed upserts cannot partially write records.

- [ ] **Step 4: Run focused tests and record GREEN**

Run: `python -m pytest tests/vector/test_memory_store.py -q`

Expected: PASS for collection/upsert cases.

### Task 6: Add cosine search, filtering, and deletion

**Files:**
- Modify: `paper_agent/vector/memory_store.py`
- Modify: `tests/vector/test_memory_store.py`

- [ ] **Step 1: Write failing search/delete tests**

Cover query dimension mismatch, zero query vectors, `limit < 1`, search before `ensure_collection` as a clear initialization error, an initialized store with no records returning `[]`, descending relevance, deterministic chunk-ID tie-breaking, `paper_id` filtering, score bounds, and `delete_by_paper` idempotence.

- [ ] **Step 2: Run new focused cases and record RED**

Run: `python -m pytest tests/vector/test_memory_store.py -q`

Expected: FAIL only for unimplemented search/delete behavior.

- [ ] **Step 3: Implement cosine behavior**

Compute cosine similarity and normalize with `(cosine + 1.0) / 2.0`, clamp numerical drift to `[0.0, 1.0]`, sort by `(-score, chunk_id)`, apply the typed filter before truncation, and never expose internal vectors in results.

- [ ] **Step 4: Run focused tests and record GREEN**

Run: `python -m pytest tests/vector/test_memory_store.py -q`

Expected: PASS.

## Chunk 4: VectorRetriever orchestration

### Task 7: Index chunks through injected boundaries

**Files:**
- Create: `paper_agent/vector/retriever.py`
- Test: `tests/vector/test_vector_retriever.py`

- [ ] **Step 1: Write failing indexing tests with fakes**

Test empty chunks as a no-op, batch document embedding in input order, inferred vector dimension, `ensure_collection` before upsert, rejection when embedder/store model identities differ, and failure without partial store calls.

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/vector/test_vector_retriever.py -q`

Expected: FAIL because `VectorRetriever` is absent.

- [ ] **Step 3: Implement `index_chunks` minimally**

Inject `Embedder` and `VectorStore` in the constructor. Do not read environment variables, instantiate HTTP clients, or call lexical retrieval inside this class.

- [ ] **Step 4: Run focused tests and record GREEN**

Run: `python -m pytest tests/vector/test_vector_retriever.py -q`

Expected: PASS for indexing cases.

### Task 8: Retrieve vector candidates and map stable chunk IDs

**Files:**
- Modify: `paper_agent/vector/retriever.py`
- Modify: `tests/vector/test_vector_retriever.py`

- [ ] **Step 1: Write failing retrieval tests**

Cover blank question rejection, `limit < 1`, exactly one query embedding, typed filter forwarding, result ordering, stable chunk mapping, stale/unknown store IDs as a clear contract error, and no conversion into `Evidence`.

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/vector/test_vector_retriever.py -q`

Expected: FAIL for retrieval behavior.

- [ ] **Step 3: Implement `retrieve` minimally**

Query with `embed([question])`, require exactly one vector through shared validation, search the store, and map each result's persisted `text` and stable metadata directly to `VectorCandidate`. Retrieval must work with a newly constructed retriever over an already populated store; do not depend on an in-process chunk lookup.

- [ ] **Step 4: Run focused tests and record GREEN**

Run: `python -m pytest tests/vector/test_vector_retriever.py -q`

Expected: PASS.

## Chunk 5: Contract integration and final verification

### Task 9: Add an offline end-to-end vector retrieval test

**Files:**
- Create: `tests/vector/test_vector_retrieval_integration.py`
- Modify: `paper_agent/vector/__init__.py`

- [ ] **Step 1: Write a failing offline integration test**

Use a deterministic fake embedder plus `InMemoryVectorStore` to index multiple papers, retrieve a semantically selected chunk, filter by paper, re-upsert a changed chunk, and delete a paper. Assert returned IDs, text, metadata, score bounds, and deterministic order.

- [ ] **Step 2: Run the test and record RED**

Run: `python -m pytest tests/vector/test_vector_retrieval_integration.py -q`

Expected: FAIL if public exports or integration behavior are incomplete.

- [ ] **Step 3: Add only the public exports/integration fixes required**

Do not wire vector retrieval into `paper_agent.pipeline`, CLI, EvidenceRetriever, report rendering, or automatic fallback in this stage.

- [ ] **Step 4: Run all vector tests and record GREEN**

Run: `python -m pytest tests/vector -q`

Expected: PASS.

### Task 10: Preserve Evidence Trace and verify delivery

**Files:**
- Review only: all changed files

- [ ] **Step 1: Run existing Evidence Trace regression tests**

Run: `python -m pytest tests/test_chunker.py tests/test_chunker_sections.py tests/test_evidence_retriever.py tests/test_pipeline_evidence_trace.py tests/test_citation_checker.py tests/test_synthesis.py -q`

Expected: PASS with no changes to lexical fallback behavior. Also run `git diff --exit-code origin/master -- paper_agent/evidence/retriever.py paper_agent/pipeline.py` and expect no output for these protected paths.

- [ ] **Step 2: Run the complete suite**

Run: `python -m pytest -q`

Expected: all original 36 tests plus new vector tests pass; record the actual count.

- [ ] **Step 3: Run repository hygiene checks**

Run: `git diff --check`

Expected: no output and exit code 0.

Run: `git status --short --branch`

Expected: branch is `codex/vector-retrieval`; only planned files are modified/untracked.

- [ ] **Step 4: Review the diff**

Check for API keys, network-dependent tests, stale names, debug output, unrequested database SDKs, hybrid/rerank/generation code, and edits to unrelated user files.

- [ ] **Step 5: Prepare delivery report**

Report new interfaces/files, per-task RED/GREEN commands and outcomes, final test count, environment configuration, in-memory-store limitations, the concrete `VectorStore` adapter boundary required for a production database, and that no commit/push/PR was performed unless separately requested.
