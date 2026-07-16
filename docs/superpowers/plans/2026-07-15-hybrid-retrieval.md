# Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic lexical + vector candidate fusion with RRF, safe lexical fallback, structured retrieval diagnostics, and offline ranking evaluation without introducing Rerank or a persistent vector database.

**Architecture:** Introduce a unified retrieval-candidate contract between existing lexical and vector paths. Keep RRF as a pure transformation, put source orchestration and terminal events in a focused service, and assemble external resources in a context-managed factory outside the pipeline. Preserve the lexical Evidence Trace wrapper and only use normalized fusion scores when actual mode is hybrid.

**Tech Stack:** Python 3.10+, Pydantic 2, httpx, pytest, standard-library dataclasses/contextlib/json/math/typing.

**Design spec:** `docs/superpowers/specs/2026-07-15-hybrid-retrieval-design.md`

**Scope constraints:** No Bailian Rerank, generation model, persistent vector database, learned fusion weights, retry policy, CLI flag expansion, or changes to synthesis/citation/rendering behavior.

---

## Chunk 1: Contracts, configuration, and lexical compatibility

### Task 1: Add retrieval configuration with strict parsing

**Files:**
- Modify: `paper_agent/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add failing configuration tests**

Add the three new environment names to `ENVIRONMENT_VARIABLES`, then add these complete cases:

```python
def _clear_settings_environment(monkeypatch) -> None:
    for variable in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_load_settings_uses_hybrid_retrieval_defaults(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)
    settings = load_settings()
    assert settings.retrieval_mode == "auto"
    assert settings.retrieval_candidate_k == 30
    assert settings.retrieval_top_k == 8
    assert settings.retrieval_rrf_k == 60


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("AUTO", "auto"), (" lexical ", "lexical"), ("Hybrid", "hybrid")],
)
def test_load_settings_normalizes_retrieval_mode(
    monkeypatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("RETRIEVAL_MODE", raw)
    assert load_settings().retrieval_mode == expected


@pytest.mark.parametrize("raw", ["unknown", "", "vector"])
def test_load_settings_rejects_unknown_retrieval_mode(
    monkeypatch, raw: str
) -> None:
    monkeypatch.setenv("RETRIEVAL_MODE", raw)
    with pytest.raises(ValueError, match="RETRIEVAL_MODE"):
        load_settings()


@pytest.mark.parametrize(
    ("name", "raw", "message"),
    [
        ("RETRIEVAL_TOP_K", "0", "must be at least 1"),
        ("RETRIEVAL_RRF_K", "-1", "must be at least 1"),
        ("RETRIEVAL_TOP_K", "1.5", "must be an integer"),
        ("RETRIEVAL_RRF_K", "not-an-int", "must be an integer"),
    ],
)
def test_load_settings_rejects_invalid_retrieval_k(
    monkeypatch, name: str, raw: str, message: str
) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(ValueError, match=rf"{name} {message}"):
        load_settings()
```

Update the existing environment-reading assertion with:

```python
"RETRIEVAL_MODE": " hybrid ",
"RETRIEVAL_TOP_K": " 9 ",
"RETRIEVAL_RRF_K": " 61 ",
```

and expect `retrieval_mode="hybrid"`, `retrieval_top_k=9`, `retrieval_rrf_k=61`.

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/test_config.py -q`

Expected failures:

- `AttributeError: 'Settings' object has no attribute 'retrieval_mode'` in the defaults test.
- Environment-reading equality fails because the new fields are absent.
- Invalid mode/K tests fail because those variables are not parsed.

- [ ] **Step 3: Implement the settings fields and parsers**

Add `Literal` to imports and define:

```python
RetrievalMode = Literal["auto", "lexical", "hybrid"]

_VALID_RETRIEVAL_MODES: tuple[RetrievalMode, ...] = (
    "auto",
    "lexical",
    "hybrid",
)
```

The ellipsis in `tuple[RetrievalMode, ...]` is Python variable-length tuple syntax, not an implementation placeholder.

Append these fields to the existing `Settings` dataclass:

```python
retrieval_mode: RetrievalMode = "auto"
retrieval_top_k: int = 8
retrieval_rrf_k: int = 60
```

Keep `retrieval_candidate_k`. Replace its dedicated parser with:

```python
def _positive_int(name: str, value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1")
    return parsed


def _retrieval_mode(value: str | None) -> RetrievalMode:
    normalized = "auto" if value is None else value.strip().lower()
    if normalized not in _VALID_RETRIEVAL_MODES:
        raise ValueError("RETRIEVAL_MODE must be auto, lexical, or hybrid")
    return normalized  # type: ignore[return-value]
```

Use `_positive_int` for candidate/top/RRF K in `load_settings()` and preserve the existing candidate-K error wording.

- [ ] **Step 4: Run focused tests and record GREEN**

Run: `python -m pytest tests/test_config.py -q`

Expected: all configuration tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add paper_agent/config.py tests/test_config.py
git commit -m "feat: add hybrid retrieval settings"
```

### Task 2: Define candidates, diagnostics, events, outcomes, and protocols

**Files:**
- Create: `paper_agent/evidence/models.py`
- Create: `paper_agent/evidence/contracts.py`
- Modify: `paper_agent/evidence/__init__.py`
- Create: `tests/evidence/test_retrieval_models.py`

- [ ] **Step 1: Write failing model tests with exact invariants**

Start the test file with these executable imports and helpers:

```python
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.models import RetrievalCandidate, RetrievalDiagnostics, RetrievalEvent


def _candidate(**overrides: object) -> RetrievalCandidate:
    values: dict[str, object] = {"chunk_id": "p1:chunk:001", "paper_id": "p1", "text": "retrieval grounding", "section": "Methods", "page": 2, "retrieval_sources": ("lexical",), "lexical_score": 0.8, "lexical_rank": 1}
    values.update(overrides)
    return RetrievalCandidate.model_validate(values)


def _diagnostics(**overrides: object) -> RetrievalDiagnostics:
    values: dict[str, object] = {"requested_mode": "lexical", "actual_mode": "lexical", "lexical_candidate_count": 1, "vector_candidate_count": 0, "fused_candidate_count": 1, "returned_evidence_count": 1, "vector_attempted": False, "degraded": False}
    values.update(overrides)
    return RetrievalDiagnostics.model_validate(values)


def _event(**overrides: object) -> RetrievalEvent:
    values = _diagnostics().model_dump()
    values.update({"status": "ok", "failure_stage": None, "error_code": None})
    values.update(overrides)
    return RetrievalEvent.model_validate(values)
```

Add the following explicit tests:

```python
def test_candidate_rejects_noncanonical_source_order() -> None:
    with pytest.raises(ValueError, match="canonical"):
        _candidate(
            retrieval_sources=("vector", "lexical"),
            lexical_score=0.8,
            lexical_rank=2,
            vector_score=0.9,
            vector_rank=1,
        )


def test_candidate_requires_score_and_rank_pair() -> None:
    with pytest.raises(ValueError, match="lexical score and rank"):
        _candidate(lexical_score=0.8, lexical_rank=None)


def test_diagnostics_rejects_returned_count_above_fused_count() -> None:
    with pytest.raises(ValueError, match="returned_evidence_count"):
        _diagnostics(fused_candidate_count=1, returned_evidence_count=2)


def test_hybrid_diagnostics_require_vector_attempt() -> None:
    with pytest.raises(ValueError, match="hybrid.*vector"):
        _diagnostics(actual_mode="hybrid", vector_attempted=False)


def test_degraded_diagnostics_require_auto_lexical_fallback() -> None:
    with pytest.raises(ValueError, match="degraded"):
        _diagnostics(
            requested_mode="hybrid",
            actual_mode="lexical",
            vector_attempted=True,
            degraded=True,
            degradation_code="embedding_timeout",
        )


def test_assembly_error_event_allows_no_actual_mode() -> None:
    event = _event(
        status="error",
        actual_mode=None,
        failure_stage="assembly",
        error_code="retrieval_configuration_error",
    )
    assert event.actual_mode is None


def test_success_event_requires_actual_mode_and_no_error_fields() -> None:
    with pytest.raises(ValueError, match="successful event"):
        _event(status="ok", actual_mode=None)


def test_event_rejects_unknown_degradation_code() -> None:
    with pytest.raises(ValidationError):
        _event(degraded=True, degradation_code="unknown")


def test_source_unavailable_exposes_frozen_typed_metadata() -> None:
    error = RetrievalSourceUnavailable("embedding_timeout", "vector_query")
    assert error.degradation_code == "embedding_timeout"
    assert error.failure_stage == "vector_query"
    with pytest.raises(FrozenInstanceError):
        error.failure_stage = "vector_index"
    assert "sentinel-secret" not in repr(error)
```

Add these remaining executable invariant tests:

```python
def test_models_are_frozen_and_forbid_extra_fields() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError, match="frozen"):
        candidate.chunk_id = "changed"
    values = candidate.model_dump()
    values["database_filter"] = "unsafe"
    with pytest.raises(ValidationError, match="extra"):
        RetrievalCandidate.model_validate(values)


def test_candidate_rejects_rank_below_one() -> None:
    with pytest.raises(ValidationError):
        _candidate(lexical_rank=0)


def test_candidate_rejects_fields_for_absent_source() -> None:
    with pytest.raises(ValueError, match="absent vector"):
        _candidate(vector_score=0.9, vector_rank=1)


def test_diagnostics_reject_vector_count_without_attempt() -> None:
    with pytest.raises(ValueError, match="vector_candidate_count"):
        _diagnostics(vector_candidate_count=1, vector_attempted=False)


def test_error_event_requires_stage_and_code() -> None:
    with pytest.raises(ValueError, match="error event"):
        _event(
            status="error",
            actual_mode="lexical",
            failure_stage=None,
            error_code=None,
        )


def test_nonassembly_error_requires_actual_mode() -> None:
    with pytest.raises(ValueError, match="actual_mode"):
        _event(
            status="error",
            actual_mode=None,
            failure_stage="vector_query",
            error_code="vector_failure",
        )
```

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/evidence/test_retrieval_models.py -q`

Expected: collection error `ModuleNotFoundError: No module named 'paper_agent.evidence.models'`.

- [ ] **Step 3: Implement exact immutable model surface**

Use `ConfigDict(frozen=True, extra="forbid")`. Define:

```python
RetrievalSource = Literal["lexical", "vector"]
DegradationCode = Literal[
    "embedding_timeout",
    "vector_network_unavailable",
    "vector_rate_limited",
    "vector_server_unavailable",
]
FailureStage = Literal[
    "validation", "assembly", "lexical", "vector_index",
    "vector_query", "fusion", "evidence_conversion",
]
ErrorCode = Literal[
    "invalid_request", "retrieval_configuration_error", "lexical_failure",
    "vector_failure", "fusion_failure", "evidence_conversion_failure",
]
EventStatus = Literal["ok", "error"]

class RetrievalCandidate(FrozenRetrievalModel):
    chunk_id: str
    paper_id: str
    text: str
    section: str | None = None
    page: int | None = None
    retrieval_sources: tuple[RetrievalSource, ...]
    lexical_score: float | None = Field(default=None, ge=0.0, le=1.0)
    lexical_rank: int | None = Field(default=None, ge=1)
    vector_score: float | None = Field(default=None, ge=0.0, le=1.0)
    vector_rank: int | None = Field(default=None, ge=1)
    fusion_score: float | None = Field(default=None, ge=0.0, le=1.0)

class RetrievalCounts(FrozenRetrievalModel):
    lexical_candidate_count: int = Field(ge=0)
    vector_candidate_count: int = Field(ge=0)
    fused_candidate_count: int = Field(ge=0)
    returned_evidence_count: int = Field(ge=0)

class RetrievalDiagnostics(RetrievalCounts):
    requested_mode: RetrievalMode
    actual_mode: Literal["lexical", "hybrid"]
    vector_attempted: bool
    degraded: bool
    degradation_code: DegradationCode | None = None

class RetrievalEvent(RetrievalCounts):
    status: EventStatus
    requested_mode: RetrievalMode
    actual_mode: Literal["lexical", "hybrid"] | None
    vector_attempted: bool
    degraded: bool
    degradation_code: DegradationCode | None = None
    failure_stage: FailureStage | None = None
    error_code: ErrorCode | None = None

class RetrievalOutcome(FrozenRetrievalModel):
    evidence: tuple[Evidence, ...]
    diagnostics: RetrievalDiagnostics
```

The ellipsis in tuple annotations is Python syntax. Validators enforce:

- sources equal one of `("lexical",)`, `("vector",)`, `("lexical", "vector")`;
- present source has score+rank and absent source has neither;
- `returned_evidence_count <= fused_candidate_count`;
- no vector attempt implies zero vector candidates;
- hybrid actual mode requires a vector attempt;
- degraded means requested auto + actual lexical + attempted vector + typed code;
- non-degraded means code is absent;
- successful event has actual mode and no failure fields;
- error event has stage+error code; `assembly` requires `actual_mode=None`, while every other error stage requires a non-None actual mode chosen before validation begins.

- [ ] **Step 4: Implement protocols and typed source-unavailable error**

In `contracts.py`, import `dataclass` from `dataclasses` and `Literal`/`Protocol` from `typing`, then define:

```python
RetrievalEventSink = Callable[[RetrievalEvent], None]

class CandidateSource(Protocol):
    def retrieve(
        self, question: str, chunks: Sequence[Chunk], limit: int
    ) -> list[RetrievalCandidate]:
        raise NotImplementedError

class EvidenceRetrievalService(Protocol):
    def retrieve(
        self,
        question: str,
        chunks: Sequence[Chunk],
        run_id: str,
        event_sink: RetrievalEventSink | None = None,
    ) -> RetrievalOutcome:
        raise NotImplementedError

VectorFailureStage = Literal["vector_index", "vector_query"]

@dataclass(frozen=True, slots=True)
class RetrievalSourceUnavailable(RuntimeError):
    degradation_code: DegradationCode
    failure_stage: VectorFailureStage

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.degradation_code)
```

Do not accept arbitrary messages or provider exceptions in its constructor. Export the public types from `paper_agent.evidence`.

- [ ] **Step 5: Run focused tests and record GREEN**

Run: `python -m pytest tests/evidence/test_retrieval_models.py -q`

Expected: all model/contract tests PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add paper_agent/evidence tests/evidence/test_retrieval_models.py
git commit -m "feat: add hybrid retrieval contracts"
```

### Task 3: Extract lexical candidates without changing Evidence Trace

**Files:**
- Modify: `paper_agent/evidence/retriever.py`
- Modify: `paper_agent/evidence/__init__.py`
- Modify: `tests/test_evidence_retriever.py`
- Create: `tests/evidence/test_lexical_candidates.py`

- [ ] **Step 1: Add complete failing candidate tests**

Start the file with:

```python
import pytest

from paper_agent.evidence.retriever import retrieve_lexical_candidates
from paper_agent.schemas import Chunk


def _chunk(
    chunk_id: str,
    text: str,
    *,
    section: str | None = "Methods",
    page: int | None = 1,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id="p1",
        section=section,
        page=page,
        text=text,
        token_count=len(text.split()),
    )
```

Then add:
```python
def test_lexical_candidates_preserve_score_rank_and_provenance() -> None:
    chunks = [
        _chunk("b", "retrieval grounding", section="Methods", page=2),
        _chunk("a", "retrieval", section="Abstract", page=None),
    ]
    candidates = retrieve_lexical_candidates(
        "retrieval grounding", chunks, limit=8
    )
    assert [item.chunk_id for item in candidates] == ["b", "a"]
    assert candidates[0].model_dump() == {
        "chunk_id": "b", "paper_id": "p1", "text": "retrieval grounding",
        "section": "Methods", "page": 2,
        "retrieval_sources": ("lexical",),
        "lexical_score": 1.0, "lexical_rank": 1,
        "vector_score": None, "vector_rank": None, "fusion_score": None,
    }
    assert candidates[1].lexical_score == 0.5
    assert candidates[1].lexical_rank == 2


def test_lexical_candidates_use_chunk_id_tie_break() -> None:
    chunks = [_chunk("b", "retrieval"), _chunk("a", "retrieval")]
    assert [item.chunk_id for item in retrieve_lexical_candidates(
        "retrieval", chunks, limit=8
    )] == ["a", "b"]


def test_lexical_candidates_reject_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit must be at least 1"):
        retrieve_lexical_candidates("retrieval", [], limit=0)


def test_lexical_candidates_return_empty_for_empty_or_termless_input() -> None:
    assert retrieve_lexical_candidates("retrieval", [], limit=8) == []
    assert retrieve_lexical_candidates("... !!!", [_chunk("a", "retrieval")], 8) == []
```

Add this compatibility test to `tests/test_evidence_retriever.py`:

```python
def test_retrieve_evidence_preserves_four_decimal_lexical_score() -> None:
    evidence = retrieve_evidence(
        "alpha beta gamma",
        [_chunk("p1:chunk:001", "alpha beta")],
        run_id="run-a",
        top_k=1,
    )
    assert len(evidence) == 1
    assert evidence[0].relevance_score == 0.6667
```

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/test_evidence_retriever.py tests/evidence/test_lexical_candidates.py -q`

Expected: collection/import failure because `retrieve_lexical_candidates` is absent.

- [ ] **Step 3: Implement the candidate function**

Add these imports in `paper_agent/evidence/retriever.py`:

```python
from collections.abc import Sequence

from paper_agent.evidence.models import RetrievalCandidate
```
Keep `_terms()` unchanged and implement:

```python
def retrieve_lexical_candidates(
    question: str,
    chunks: Sequence[Chunk],
    limit: int,
) -> list[RetrievalCandidate]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    query_terms = _terms(question)
    if not query_terms or not chunks:
        return []
    scored: list[tuple[float, str, Chunk]] = []
    for chunk in chunks:
        score = len(query_terms & _terms(chunk.text)) / len(query_terms)
        if score > 0:
            scored.append((score, chunk.chunk_id, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        RetrievalCandidate(
            chunk_id=chunk.chunk_id,
            paper_id=chunk.paper_id,
            text=chunk.text,
            section=chunk.section,
            page=chunk.page,
            retrieval_sources=("lexical",),
            lexical_score=score,
            lexical_rank=rank,
        )
        for rank, (score, _chunk_id, chunk) in enumerate(
            scored[:limit], start=1
        )
    ]
```

Refactor `retrieve_evidence()` after its existing validation:

```python
candidates = retrieve_lexical_candidates(question, chunks, limit=top_k)
return [
    Evidence(
        evidence_id=f"{run_id}:ev_{index:03d}",
        paper_id=item.paper_id,
        chunk_id=item.chunk_id,
        claim_type="retrieved",
        quote=item.text,
        relevance_score=round(min(item.lexical_score or 0.0, 1.0), 4),
    )
    for index, item in enumerate(candidates, start=1)
]
```

Preserve validation order: invalid `top_k`, blank `run_id`, then empty/no-term behavior.

- [ ] **Step 4: Run focused tests and regressions**

Run: `python -m pytest tests/test_evidence_retriever.py tests/evidence/test_lexical_candidates.py -q`

Expected: PASS, including exact `0.6667` compatibility.

Run: `python -m pytest tests/test_pipeline_evidence_trace.py tests/test_synthesis.py tests/test_citation_checker.py -q`

Expected: PASS with unchanged lexical Evidence Trace.

- [ ] **Step 5: Commit Task 3**

```bash
git add paper_agent/evidence/retriever.py paper_agent/evidence/__init__.py tests/test_evidence_retriever.py tests/evidence/test_lexical_candidates.py
git commit -m "refactor: expose lexical retrieval candidates"
```

### Chunk 1 verification checkpoint

- [ ] Run: `python -m pytest tests/test_config.py tests/test_evidence_retriever.py tests/evidence -q`; expected PASS.
- [ ] Run: `python -m pytest -q`; expected all tests PASS and record the actual count.
- [ ] Run: `git diff --check`; expected exit code 0 with no output.
- [ ] Confirm `git diff HEAD^ -- paper_agent/pipeline.py paper_agent/vector paper_agent/synthesis paper_agent/rendering` is empty for this chunk.

## Chunk 2: Bailian error taxonomy and vector candidate boundary

### Task 4: Split embedding failures into actionable domain errors

**Files:**
- Modify: `paper_agent/vector/bailian.py`
- Modify: `paper_agent/vector/__init__.py`
- Modify: `tests/vector/test_bailian_http_transport.py`
- Modify: `tests/vector/test_bailian_embedder.py`

- [ ] **Step 1: Replace generic HTTP-error tests with exact typed cases**

Update test imports and add:

```python
from paper_agent.vector.bailian import (
    EmbeddingAuthenticationError,
    EmbeddingConfigurationError,
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingRequestError,
    EmbeddingResponseError,
    EmbeddingServerError,
    EmbeddingTimeoutError,
)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, EmbeddingRequestError),
        (401, EmbeddingAuthenticationError),
        (403, EmbeddingAuthenticationError),
        (429, EmbeddingRateLimitError),
        (500, EmbeddingServerError),
        (503, EmbeddingServerError),
    ],
)
def test_http_status_maps_to_typed_sanitized_error(
    status: int, error_type: type[Exception]
) -> None:
    transport = _transport(
        lambda _: httpx.Response(status, json={"message": "sentinel-key"})
    )
    with pytest.raises(error_type) as exc_info:
        _embed(transport)
    assert "sentinel-key" not in str(exc_info.value)


def test_network_failure_maps_to_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sentinel-key", request=request)
    with pytest.raises(EmbeddingNetworkError) as exc_info:
        _embed(_transport(handler))
    assert "sentinel-key" not in str(exc_info.value)


def test_unsupported_region_is_configuration_error() -> None:
    transport = _transport(lambda _: pytest.fail("request must not run"))
    with pytest.raises(EmbeddingConfigurationError, match="region"):
        transport.embed(
            texts=["text"], model="text-embedding-v4", api_key="key",
            region="hangzhou", timeout=30.0,
        )


def test_malformed_success_payload_is_response_error() -> None:
    transport = _transport(lambda _: httpx.Response(200, content=b"not-json"))
    with pytest.raises(EmbeddingResponseError, match="response"):
        _embed(transport)
```

Keep the timeout test and add these exact compatibility/response cases:

```python
def test_new_transport_errors_keep_compatibility_base() -> None:
    error_types = [
        EmbeddingNetworkError, EmbeddingRateLimitError, EmbeddingServerError,
        EmbeddingAuthenticationError, EmbeddingRequestError,
        EmbeddingConfigurationError,
    ]
    assert all(issubclass(item, EmbeddingTransportError) for item in error_types)


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": None}, {"data": [{}]}, {"data": [{"index": 0}]}],
)
def test_invalid_success_payload_is_response_error(payload: object) -> None:
    with pytest.raises(EmbeddingResponseError, match="response"):
        _embed(_transport(lambda _: httpx.Response(200, json=payload)))


def test_api_error_payload_is_response_error() -> None:
    response = {"code": "InvalidParameter", "message": "sentinel-key"}
    with pytest.raises(EmbeddingResponseError) as exc_info:
        _embed(_transport(lambda _: httpx.Response(200, json=response)))
    assert "sentinel-key" not in str(exc_info.value)
```

`EmbeddingResponseError` is imported from `paper_agent.vector.embedding` (or its public re-export), not newly defined in `bailian.py`.

- [ ] **Step 2: Run transport tests and record RED**

Run: `python -m pytest tests/vector/test_bailian_http_transport.py tests/vector/test_bailian_embedder.py -q`

Expected: import/expectation failures because the typed subclasses do not exist and all HTTP failures currently map to `EmbeddingTransportError`.

- [ ] **Step 3: Implement the exception hierarchy and status mapping**

Keep `EmbeddingTransportError` as the public base. Add:

```python
class EmbeddingNetworkError(EmbeddingTransportError):
    pass

class EmbeddingRateLimitError(EmbeddingTransportError):
    pass

class EmbeddingServerError(EmbeddingTransportError):
    pass

class EmbeddingAuthenticationError(EmbeddingTransportError):
    pass

class EmbeddingRequestError(EmbeddingTransportError):
    pass

class EmbeddingConfigurationError(EmbeddingTransportError):
    pass

# Reuse and re-export paper_agent.vector.embedding.EmbeddingResponseError.
```

In `HttpxEmbeddingTransport.embed()`:

1. Reject unsupported region with `EmbeddingConfigurationError` before I/O.
2. Map `httpx.TimeoutException` to existing `EmbeddingTimeoutError`.
3. Map other `httpx.RequestError` to `EmbeddingNetworkError`.
4. Inspect status explicitly: 401/403 auth, 429 rate limit, 500–599 server, remaining 400–499 request.
5. Parse only a successful response; malformed JSON/data/row/index raises the existing `paper_agent.vector.embedding.EmbeddingResponseError`. Import it into `bailian.py` beside `_validate_embedding_batch` and re-export that same class from `paper_agent.vector`.
6. Never include response body, request text, URL query, or API key in messages/repr.

Export the hierarchy from `paper_agent.vector`.

- [ ] **Step 4: Run focused tests and full vector regression**

Run: `python -m pytest tests/vector/test_bailian_http_transport.py tests/vector/test_bailian_embedder.py -q`

Expected: PASS.

Run: `python -m pytest tests/vector -q`

Expected: all vector tests PASS; record actual count.

- [ ] **Step 5: Commit Task 4**

```bash
git add paper_agent/vector tests/vector/test_bailian_http_transport.py tests/vector/test_bailian_embedder.py
git commit -m "refactor: classify embedding failures"
```

### Task 5: Adapt VectorRetriever results to unified candidates

**Files:**
- Create: `paper_agent/evidence/vector_source.py`
- Modify: `paper_agent/evidence/__init__.py`
- Create: `tests/evidence/test_vector_candidate_source.py`

- [ ] **Step 1: Write an executable fake and mapping tests**

Start the test file with:

```python
from collections.abc import Sequence

import pytest

from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.vector_source import VectorCandidateSource
from paper_agent.schemas import Chunk
from paper_agent.vector import VectorCandidate, VectorRecordMetadata
from paper_agent.vector.bailian import (
    EmbeddingAuthenticationError,
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingServerError,
    EmbeddingTimeoutError,
)


class FakeVectorRetriever:
    def __init__(self) -> None:
        self.indexed: list[Chunk] = []
        self.question: str | None = None
        self.limit: int | None = None
        self.index_error: Exception | None = None
        self.query_error: Exception | None = None
        self.results: list[VectorCandidate] = []

    def index_chunks(self, chunks: Sequence[Chunk]) -> None:
        if self.index_error is not None:
            raise self.index_error
        self.indexed = list(chunks)

    def retrieve(self, question: str, limit: int) -> list[VectorCandidate]:
        if self.query_error is not None:
            raise self.query_error
        self.question = question
        self.limit = limit
        return self.results
```

Add this complete helper, then the tests below:

```python
def _chunk_and_vector() -> tuple[Chunk, VectorCandidate]:
    chunk = Chunk(
        chunk_id="p1:chunk:001", paper_id="p1", section="Methods", page=2,
        text="semantic grounding", token_count=2,
    )
    metadata = VectorRecordMetadata(
        paper_id=chunk.paper_id, chunk_id=chunk.chunk_id,
        section=chunk.section, page=chunk.page,
        content_hash="sha256-test", embedding_model="text-embedding-v4",
    )
    candidate = VectorCandidate(
        chunk_id=chunk.chunk_id, paper_id=chunk.paper_id,
        text=chunk.text, score=0.9, metadata=metadata,
    )
    return chunk, candidate
```

Add:

```python
def test_vector_source_indexes_queries_and_maps_ranked_candidate() -> None:
    chunk, vector = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    retriever.results = [vector]
    result = VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert retriever.indexed == [chunk]
    assert (retriever.question, retriever.limit) == ("question", 3)
    assert result[0].model_dump() == {
        "chunk_id": chunk.chunk_id, "paper_id": chunk.paper_id,
        "text": chunk.text, "section": chunk.section, "page": chunk.page,
        "retrieval_sources": ("vector",),
        "lexical_score": None, "lexical_rank": None,
        "vector_score": vector.score, "vector_rank": 1,
        "fusion_score": None,
    }


def test_vector_source_short_circuits_empty_chunks() -> None:
    retriever = FakeVectorRetriever()
    assert VectorCandidateSource(retriever).retrieve("question", [], 3) == []
    assert retriever.indexed == []
    assert retriever.question is None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (EmbeddingTimeoutError("timeout"), "embedding_timeout"),
        (EmbeddingNetworkError("network"), "vector_network_unavailable"),
        (EmbeddingRateLimitError("rate"), "vector_rate_limited"),
        (EmbeddingServerError("server"), "vector_server_unavailable"),
    ],
)
def test_vector_source_maps_query_availability_error(
    error: Exception, code: str
) -> None:
    chunk, _ = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    retriever.query_error = error
    with pytest.raises(RetrievalSourceUnavailable) as exc_info:
        VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert exc_info.value.degradation_code == code
    assert exc_info.value.failure_stage == "vector_query"


@pytest.mark.parametrize(
    "error",
    [EmbeddingAuthenticationError("auth"), EmbeddingResponseError("response")],
)
def test_vector_source_does_not_downgrade_nonavailability_errors(
    error: Exception,
) -> None:
    chunk, _ = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    retriever.index_error = error
    with pytest.raises(type(error)):
        VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
```

Add the remaining executable boundary tests:

```python
def test_vector_source_marks_index_availability_stage() -> None:
    chunk, _ = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    retriever.index_error = EmbeddingTimeoutError("timeout")
    with pytest.raises(RetrievalSourceUnavailable) as exc_info:
        VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert exc_info.value.degradation_code == "embedding_timeout"
    assert exc_info.value.failure_stage == "vector_index"


@pytest.mark.parametrize(("question", "limit"), [("   ", 3), ("question", 0)])
def test_vector_source_rejects_invalid_query_without_downgrade(
    question: str, limit: int
) -> None:
    chunk, _ = _chunk_and_vector()
    with pytest.raises(ValueError):
        VectorCandidateSource(FakeVectorRetriever()).retrieve(question, [chunk], limit)


def test_unavailable_error_metadata_is_frozen() -> None:
    error = RetrievalSourceUnavailable("embedding_timeout", "vector_query")
    with pytest.raises(FrozenInstanceError):
        error.failure_stage = "vector_index"
```

Import `FrozenInstanceError` from `dataclasses` in this test file.

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/evidence/test_vector_candidate_source.py -q`

Expected: collection error because `paper_agent.evidence.vector_source` is absent.

- [ ] **Step 3: Reconfirm the final unavailable-error contract from Chunk 1**

Run: `python -m pytest tests/evidence/test_retrieval_models.py -q`

Expected: PASS with the already-frozen two-argument `RetrievalSourceUnavailable(code, stage)` contract. Do not modify that contract in this task.

- [ ] **Step 4: Implement the adapter and exact availability mapping**

Implement `vector_source.py` with this complete structure:

```python
from collections.abc import Sequence
from typing import Protocol

from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.models import DegradationCode, RetrievalCandidate
from paper_agent.schemas import Chunk
from paper_agent.vector import VectorCandidate
from paper_agent.vector.bailian import (
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingServerError,
    EmbeddingTimeoutError,
)


class VectorRetrieverLike(Protocol):
    def index_chunks(self, chunks: Sequence[Chunk]) -> None:
        raise NotImplementedError

    def retrieve(self, question: str, limit: int) -> list[VectorCandidate]:
        raise NotImplementedError


_AVAILABILITY_ERRORS = (
    EmbeddingTimeoutError,
    EmbeddingNetworkError,
    EmbeddingRateLimitError,
    EmbeddingServerError,
)


def _degradation_code(error: Exception) -> DegradationCode:
    if isinstance(error, EmbeddingTimeoutError):
        return "embedding_timeout"
    if isinstance(error, EmbeddingNetworkError):
        return "vector_network_unavailable"
    if isinstance(error, EmbeddingRateLimitError):
        return "vector_rate_limited"
    if isinstance(error, EmbeddingServerError):
        return "vector_server_unavailable"
    raise TypeError("error is not an availability failure")


class VectorCandidateSource:
    def __init__(self, retriever: VectorRetrieverLike) -> None:
        self._retriever = retriever

    def retrieve(
        self,
        question: str,
        chunks: Sequence[Chunk],
        limit: int,
    ) -> list[RetrievalCandidate]:
        if not question.strip():
            raise ValueError("question must not be blank")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not chunks:
            return []
        try:
            self._retriever.index_chunks(chunks)
        except _AVAILABILITY_ERRORS as error:
            raise RetrievalSourceUnavailable(
                _degradation_code(error), "vector_index"
            ) from None
        try:
            candidates = self._retriever.retrieve(question, limit)
        except _AVAILABILITY_ERRORS as error:
            raise RetrievalSourceUnavailable(
                _degradation_code(error), "vector_query"
            ) from None
        return [
            RetrievalCandidate(
                chunk_id=item.chunk_id,
                paper_id=item.paper_id,
                text=item.text,
                section=item.metadata.section,
                page=item.metadata.page,
                retrieval_sources=("vector",),
                vector_score=item.score,
                vector_rank=rank,
            )
            for rank, item in enumerate(candidates, start=1)
        ]
```

Only the four availability classes are caught. Authentication, request, configuration, response, metadata, model-identity, dimension, and other contract errors propagate unchanged. The adapter does not look up chunks in an in-process dictionary and does not create Evidence.

- [ ] **Step 5: Run focused tests and regressions**

Run: `python -m pytest tests/evidence/test_vector_candidate_source.py tests/evidence/test_retrieval_models.py -q`

Expected: PASS.

Run: `python -m pytest tests/vector tests/test_evidence_retriever.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add paper_agent/evidence tests/evidence/test_vector_candidate_source.py
git commit -m "feat: adapt vector retrieval candidates"
```

### Chunk 2 verification checkpoint

- [ ] Run: `python -m pytest tests/vector tests/evidence -q`; expected PASS.
- [ ] Run: `python -m pytest -q`; expected all tests PASS and record actual count.
- [ ] Run: `git diff --check`; expected exit code 0 with no output.
- [ ] Confirm no RRF, pipeline wiring, Rerank, generation, or database adapter was added.
## Chunk 3: Deterministic RRF and HybridEvidenceRetriever

### Task 6: Implement pure RRF merge and stable ranking

**Files:**
- Create: `paper_agent/evidence/fusion.py`
- Create: `tests/evidence/test_rrf_fusion.py`

- [ ] **Step 1: Write complete failing RRF tests**

Start `test_rrf_fusion.py` with:

```python
import pytest

from paper_agent.evidence.fusion import fuse_candidates
from paper_agent.evidence.models import RetrievalCandidate
```

Then add this executable helper:

```python
def _candidate(
    source: str,
    chunk_id: str,
    rank: int,
    score: float,
    text: str | None = None,
) -> RetrievalCandidate:
    values: dict[str, object] = {
        "chunk_id": chunk_id, "paper_id": "p1",
        "text": text or f"text-{chunk_id}", "section": "Methods", "page": 1,
        "retrieval_sources": (source,),
        "lexical_score": score if source == "lexical" else None,
        "lexical_rank": rank if source == "lexical" else None,
        "vector_score": score if source == "vector" else None,
        "vector_rank": rank if source == "vector" else None,
    }
    return RetrievalCandidate.model_validate(values)
```

Then add:

```python
def test_rrf_merges_duplicate_identity_and_normalizes_by_active_sources() -> None:
    lexical = [_candidate("lexical", "shared", 1, 0.8)]
    vector = [
        _candidate("vector", "vector-only", 1, 0.9),
        _candidate("vector", "shared", 2, 0.7),
    ]
    result = fuse_candidates(
        lexical, vector, rrf_k=60,
        active_sources=("lexical", "vector"),
    )
    shared = next(item for item in result if item.chunk_id == "shared")
    vector_only = next(item for item in result if item.chunk_id == "vector-only")
    assert shared.retrieval_sources == ("lexical", "vector")
    assert shared.lexical_rank == 1
    assert shared.vector_rank == 2
    assert shared.fusion_score == pytest.approx(
        ((1 / 61) + (1 / 62)) / (2 / 61)
    )
    assert vector_only.fusion_score == pytest.approx(0.5)
    assert result[0].chunk_id == "shared"


def test_successful_empty_vector_source_stays_in_normalization_denominator() -> None:
    result = fuse_candidates(
        [_candidate("lexical", "a", 1, 1.0)], [], rrf_k=60,
        active_sources=("lexical", "vector"),
    )
    assert result[0].fusion_score == pytest.approx(0.5)


def test_rrf_uses_chunk_id_for_exact_tie() -> None:
    lexical = [
        _candidate("lexical", "b", 1, 1.0),
        _candidate("lexical", "a", 1, 1.0),
    ]
    assert [item.chunk_id for item in fuse_candidates(
        lexical, [], rrf_k=60, active_sources=("lexical",)
    )] == ["a", "b"]


def test_rrf_rejects_identity_conflict_for_same_chunk_id() -> None:
    with pytest.raises(ValueError, match="identity"):
        fuse_candidates(
            [_candidate("lexical", "same", 1, 1.0, text="first")],
            [_candidate("vector", "same", 1, 1.0, text="second")],
            rrf_k=60, active_sources=("lexical", "vector"),
        )


@pytest.mark.parametrize("rrf_k", [0, -1, True])
def test_rrf_rejects_invalid_k(rrf_k: object) -> None:
    with pytest.raises(ValueError, match="rrf_k"):
        fuse_candidates([], [], rrf_k=rrf_k, active_sources=("lexical",))
```

Add these exact validation tests:

```python
def test_rrf_rejects_candidate_in_wrong_source_list() -> None:
    with pytest.raises(ValueError, match="lexical input"):
        fuse_candidates(
            [_candidate("vector", "a", 1, 1.0)], [], rrf_k=60,
            active_sources=("lexical",),
        )


def test_rrf_rejects_candidates_for_inactive_source() -> None:
    with pytest.raises(ValueError, match="inactive vector"):
        fuse_candidates(
            [], [_candidate("vector", "a", 1, 1.0)], rrf_k=60,
            active_sources=("lexical",),
        )
```

Then add the active-source shape cases:

```python
@pytest.mark.parametrize("sources", [(), ("vector", "lexical")])
def test_rrf_rejects_invalid_active_sources(sources: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="active_sources"):
        fuse_candidates([], [], rrf_k=60, active_sources=sources)


def test_rrf_rejects_duplicate_id_inside_one_source() -> None:
    duplicate = _candidate("lexical", "same", 1, 1.0)
    with pytest.raises(ValueError, match="duplicate.*same"):
        fuse_candidates(
            [duplicate, duplicate.model_copy(update={"lexical_rank": 2})], [],
            rrf_k=60, active_sources=("lexical",),
        )
```

The ellipsis in `tuple[str, ...]` is Python tuple typing syntax.

- [ ] **Step 2: Run focused tests and record RED**

Run: `python -m pytest tests/evidence/test_rrf_fusion.py -q`

Expected: collection error because `paper_agent.evidence.fusion` is absent.

- [ ] **Step 3: Implement the pure fusion function**

Implement:

```python
def fuse_candidates(
    lexical: Sequence[RetrievalCandidate],
    vector: Sequence[RetrievalCandidate],
    *,
    rrf_k: int,
    active_sources: tuple[RetrievalSource, ...],
) -> list[RetrievalCandidate]:
```

Validation and transformation order:

1. Require `type(rrf_k) is int and rrf_k >= 1`.
2. Require active sources to equal `("lexical",)`, `("vector",)`, or `("lexical", "vector")`.
3. Require every lexical-list candidate to have exactly `("lexical",)` and every vector-list candidate exactly `("vector",)`; require an inactive source list to be empty.
4. Reject duplicate IDs inside each source list.
5. Merge by chunk ID and require exact equality of `paper_id`, `text`, `section`, and `page`.
6. Preserve raw source scores/ranks and canonical source order.
7. Compute raw contribution from present source ranks.
8. Normalize by `sum(1 / (rrf_k + 1) for each active source)`, including a successful source with zero candidates.
9. Clamp numerical drift to `[0, 1]`, construct new immutable candidates, and sort by `(-fusion_score, chunk_id)`.

Do not mutate inputs, truncate, generate Evidence IDs, or inspect environment configuration.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/evidence/test_rrf_fusion.py -q`

Expected: PASS.

```bash
git add paper_agent/evidence/fusion.py tests/evidence/test_rrf_fusion.py
git commit -m "feat: add deterministic RRF fusion"
```

### Task 7: Implement retrieval orchestration, fallback, and terminal events

**Files:**
- Modify: `paper_agent/evidence/retriever.py`
- Create: `paper_agent/evidence/hybrid.py`
- Modify: `paper_agent/evidence/vector_source.py`
- Modify: `tests/evidence/test_vector_candidate_source.py`
- Modify: `paper_agent/evidence/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/evidence/__init__.py`
- Create: `tests/evidence/hybrid_fakes.py`
- Create: `tests/evidence/test_hybrid_retriever.py`
- Create: `tests/evidence/test_hybrid_failures.py`

- [ ] **Step 1: Define executable fake sources for service tests**

```python
class FakeSource:
    def __init__(self, results: list[RetrievalCandidate]) -> None:
        self.results = results
        self.calls: list[tuple[str, list[Chunk], int]] = []
        self.error: Exception | None = None

    def retrieve(
        self, question: str, chunks: Sequence[Chunk], limit: int
    ) -> list[RetrievalCandidate]:
        self.calls.append((question, list(chunks), limit))
        if self.error is not None:
            raise self.error
        return self.results


def _recording_sink() -> tuple[list[RetrievalEvent], RetrievalEventSink]:
    events: list[RetrievalEvent] = []
    return events, events.append
```

Create empty `tests/__init__.py` and `tests/evidence/__init__.py` up front. Start `hybrid_fakes.py` with:

```python
from collections.abc import Sequence

from paper_agent.evidence.contracts import RetrievalEventSink
from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.models import RetrievalCandidate, RetrievalEvent
from paper_agent.schemas import Chunk


def _candidate(
    source: str, chunk_id: str, rank: int, score: float
) -> RetrievalCandidate:
    values: dict[str, object] = {
        "chunk_id": chunk_id, "paper_id": "p1",
        "text": f"text-{chunk_id}", "section": "Methods", "page": 1,
        "retrieval_sources": (source,),
        "lexical_score": score if source == "lexical" else None,
        "lexical_rank": rank if source == "lexical" else None,
        "vector_score": score if source == "vector" else None,
        "vector_rank": rank if source == "vector" else None,
    }
    return RetrievalCandidate.model_validate(values)
```

Place `FakeSource`, `_recording_sink`, `_chunk`, `_lexical_candidate`, `_vector_candidate`, and `_service` below that helper.

Start `test_hybrid_retriever.py` with:

```python
import pytest
from paper_agent.evidence.models import RetrievalEvent
from tests.evidence.hybrid_fakes import (
    FakeSource, _chunk, _lexical_candidate, _recording_sink,
    _service, _vector_candidate,
)
```

Start `test_hybrid_failures.py` with:

```python
import pytest
from paper_agent.evidence.contracts import RetrievalSourceUnavailable
from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.models import RetrievalEvent
from tests.evidence.hybrid_fakes import (
    FakeSource, _chunk, _lexical_candidate, _recording_sink, _service,
)
```

Use these executable helpers with stable provenance:

```python
def _chunk(chunk_id: str = "shared") -> Chunk:
    return Chunk(chunk_id=chunk_id, paper_id="p1", section="Methods", page=1,
                 text=f"text-{chunk_id}", token_count=1)


def _lexical_candidate(
    chunk_id: str = "shared", score: float = 0.8, rank: int = 1
) -> RetrievalCandidate:
    return _candidate("lexical", chunk_id, rank, score)


def _vector_candidate(
    chunk_id: str = "shared", score: float = 0.9, rank: int = 1
) -> RetrievalCandidate:
    return _candidate("vector", chunk_id, rank, score)


def _service(
    mode: str,
    lexical: FakeSource,
    vector: FakeSource | None,
    *,
    candidate_k: int = 30,
    top_k: int = 8,
    rrf_k: int = 60,
) -> HybridEvidenceRetriever:
    return HybridEvidenceRetriever(
        lexical_source=lexical, vector_source=vector, requested_mode=mode,
        candidate_k=candidate_k, top_k=top_k, rrf_k=rrf_k,
    )
```

The service constructor used by tests is:

```python
HybridEvidenceRetriever(
    lexical_source=lexical,
    vector_source=vector_or_none,
    requested_mode="auto",
    candidate_k=30,
    top_k=8,
    rrf_k=60,
)
```

- [ ] **Step 2: Write failing success and compatibility tests**

Add exact assertions for:

```python
def test_lexical_mode_bypasses_vector_and_preserves_legacy_score() -> None:
    lexical = FakeSource([_lexical_candidate(score=2 / 3, rank=1)])
    vector = FakeSource([_vector_candidate(score=1.0, rank=1)])
    events, sink = _recording_sink()
    outcome = _service("lexical", lexical, vector).retrieve(
        "question", [_chunk()], "run-a", sink
    )
    assert vector.calls == []
    assert outcome.evidence[0].relevance_score == 0.6667
    assert outcome.evidence[0].evidence_id == "run-a:ev_001"
    assert outcome.diagnostics.actual_mode == "lexical"
    assert len(events) == 1 and events[0].status == "ok"


def test_auto_hybrid_calls_each_source_once_and_fuses_before_top_k() -> None:
    lexical = FakeSource([_lexical_candidate(chunk_id="shared", rank=1)])
    vector = FakeSource([
        _vector_candidate(chunk_id="vector-only", rank=1),
        _vector_candidate(chunk_id="shared", rank=2),
    ])
    outcome = _service("auto", lexical, vector, top_k=1).retrieve(
        "question", [_chunk()], "run-a"
    )
    assert lexical.calls[0][2] == 30
    assert vector.calls[0][2] == 30
    assert [item.chunk_id for item in outcome.evidence] == ["shared"]
    assert outcome.diagnostics.fused_candidate_count == 2
    assert outcome.diagnostics.returned_evidence_count == 1
    assert outcome.diagnostics.actual_mode == "hybrid"


def test_empty_chunks_emit_one_success_event_without_source_calls() -> None:
    lexical, vector = FakeSource([]), FakeSource([])
    events, sink = _recording_sink()
    outcome = _service("hybrid", lexical, vector).retrieve(
        "question", [], "run-a", sink
    )
    assert outcome.evidence == ()
    assert lexical.calls == vector.calls == []
    assert outcome.diagnostics.actual_mode == "lexical"
    assert events == [RetrievalEvent.model_validate({
        **outcome.diagnostics.model_dump(), "status": "ok",
        "failure_stage": None, "error_code": None,
    })]
```

Add the remaining success cases:

```python
def test_evidence_ids_are_assigned_after_final_top_k() -> None:
    lexical = FakeSource([_lexical_candidate("a", rank=1), _lexical_candidate("b", rank=2)])
    outcome = _service("lexical", lexical, None, top_k=1).retrieve(
        "question", [_chunk()], "run-z"
    )
    assert [(item.evidence_id, item.chunk_id) for item in outcome.evidence] == [("run-z:ev_001", "a")]


def test_auto_without_vector_source_is_lexical() -> None:
    outcome = _service("auto", FakeSource([_lexical_candidate()]), None).retrieve(
        "question", [_chunk()], "run-a"
    )
    assert outcome.diagnostics.actual_mode == "lexical"
    assert outcome.diagnostics.vector_attempted is False


def test_empty_vector_result_is_hybrid_not_degradation() -> None:
    outcome = _service("auto", FakeSource([_lexical_candidate()]), FakeSource([])).retrieve(
        "question", [_chunk()], "run-a"
    )
    assert outcome.diagnostics.actual_mode == "hybrid"
    assert outcome.diagnostics.degraded is False
    assert outcome.evidence[0].relevance_score == pytest.approx(0.5)
```

- [ ] **Step 3: Write failing validation, degradation, and error-event tests**

```python
def test_auto_degrades_only_typed_unavailable_error() -> None:
    lexical = FakeSource([_lexical_candidate(score=0.75, rank=1)])
    vector = FakeSource([])
    vector.error = RetrievalSourceUnavailable(
        "embedding_timeout", "vector_query"
    )
    events, sink = _recording_sink()
    outcome = _service("auto", lexical, vector).retrieve(
        "question", [_chunk()], "run-a", sink
    )
    assert outcome.evidence[0].relevance_score == 0.75
    assert outcome.diagnostics.degraded is True
    assert outcome.diagnostics.degradation_code == "embedding_timeout"
    assert events[0].status == "ok"


def test_forced_hybrid_emits_error_then_rethrows_unavailable() -> None:
    lexical, vector = FakeSource([]), FakeSource([])
    error = RetrievalSourceUnavailable("embedding_timeout", "vector_index")
    vector.error = error
    events, sink = _recording_sink()
    with pytest.raises(RetrievalSourceUnavailable) as exc_info:
        _service("hybrid", lexical, vector).retrieve(
            "question", [_chunk()], "run-a", sink
        )
    assert exc_info.value is error
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].failure_stage == "vector_index"


@pytest.mark.parametrize(
    ("question", "run_id", "candidate_k", "top_k", "rrf_k"),
    [(" ", "run-a", 30, 8, 60), ("q", " ", 30, 8, 60),
     ("q", "run-a", 0, 8, 60), ("q", "run-a", 30, 0, 60),
     ("q", "run-a", 30, 8, 0)],
)
def test_validation_error_emits_one_terminal_event(
    question: str, run_id: str, candidate_k: int, top_k: int, rrf_k: int
) -> None:
    events, sink = _recording_sink()
    service = HybridEvidenceRetriever(
        lexical_source=FakeSource([]), vector_source=None,
        requested_mode="lexical", candidate_k=candidate_k,
        top_k=top_k, rrf_k=rrf_k,
    )
    with pytest.raises(ValueError):
        service.retrieve(question, [_chunk()], run_id, sink)
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].failure_stage == "validation"
```

Add exact vector-wrapper, fusion, conversion, lexical, and sink failures:

```python
def test_vector_contract_failure_uses_exact_stage_and_rethrows_cause() -> None:
    lexical, vector = FakeSource([_lexical_candidate()]), FakeSource([])
    cause = ValueError("dimension mismatch")
    vector.error = VectorSourceExecutionError(cause, "vector_index")
    events, sink = _recording_sink()
    with pytest.raises(ValueError) as exc_info:
        _service("hybrid", lexical, vector).retrieve("q", [_chunk()], "run-a", sink)
    assert exc_info.value is cause
    assert exc_info.value.__suppress_context__ is True
    assert [(item.failure_stage, item.error_code, item.lexical_candidate_count) for item in events] == [("vector_index", "vector_failure", 1)]


def test_fusion_failure_emits_counts_once_and_rethrows_same_error() -> None:
    lexical = FakeSource([_lexical_candidate("same")])
    conflicting = _vector_candidate("same").model_copy(update={"text": "different"})
    vector = FakeSource([conflicting])
    events, sink = _recording_sink()
    with pytest.raises(ValueError, match="identity") as exc_info:
        _service("hybrid", lexical, vector).retrieve("q", [_chunk()], "run-a", sink)
    assert len(events) == 1
    event = events[0]
    assert (event.failure_stage, event.error_code) == ("fusion", "fusion_failure")
    assert (event.lexical_candidate_count, event.vector_candidate_count, event.fused_candidate_count, event.returned_evidence_count) == (1, 1, 0, 0)
    assert exc_info.value is not None


def test_evidence_conversion_failure_emits_fused_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ValueError("conversion failed")
    def fail_conversion(*args: object, **kwargs: object) -> tuple[()]:
        raise error
    monkeypatch.setattr(hybrid_module, "_candidates_to_evidence", fail_conversion)
    events, sink = _recording_sink()
    with pytest.raises(ValueError) as exc_info:
        _service("lexical", FakeSource([_lexical_candidate()]), None).retrieve(
            "q", [_chunk()], "run-a", sink
        )
    assert exc_info.value is error
    assert len(events) == 1
    event = events[0]
    assert (event.failure_stage, event.error_code) == ("evidence_conversion", "evidence_conversion_failure")
    assert (event.fused_candidate_count, event.returned_evidence_count) == (1, 0)
```

In `test_hybrid_failures.py`, also import:

```python
import paper_agent.evidence.hybrid as hybrid_module
from paper_agent.evidence.vector_source import VectorSourceExecutionError
```

Then add the lexical and sink tests:

```python
def test_lexical_failure_emits_once_and_rethrows_same_error() -> None:
    lexical = FakeSource([])
    error = ValueError("lexical-contract")
    lexical.error = error
    events, sink = _recording_sink()
    with pytest.raises(ValueError) as exc_info:
        _service("lexical", lexical, None).retrieve("q", [_chunk()], "run-a", sink)
    assert exc_info.value is error
    assert [(item.status, item.failure_stage, item.error_code) for item in events] == [("error", "lexical", "lexical_failure")]


def test_sink_failure_propagates_without_second_delivery() -> None:
    calls = 0
    def failing_sink(event: RetrievalEvent) -> None:
        nonlocal calls
        calls += 1
        raise OSError("disk full")
    with pytest.raises(OSError, match="disk full"):
        _service("lexical", FakeSource([]), None).retrieve("q", [_chunk()], "run-a", failing_sink)
    assert calls == 1
```

- [ ] **Step 4: Run focused tests and record RED**

Run: `python -m pytest tests/evidence/test_hybrid_retriever.py tests/evidence/test_hybrid_failures.py -q`

Expected: collection error because `paper_agent.evidence.hybrid` is absent.

- [ ] **Step 5: Add the lexical source adapter and HybridEvidenceRetriever**

Add `LexicalCandidateSource.retrieve()` in `retriever.py` as a one-line delegation to `retrieve_lexical_candidates(question, chunks, limit)`.

In `hybrid.py`, implement constructor validation storage and one `retrieve()` method with this order:

1. Store constructor values without validating K so a sink is available for validation events.
2. In `retrieve()`, check empty chunks first. Return lexical empty success even when question/run/K are invalid; do not call sources.
3. For non-empty chunks, determine planned actual mode, then validate question/run ID/K; deliver one `validation` event before rethrow.
4. Call lexical once. On failure emit `lexical` error and rethrow the identical exception.
5. For planned lexical mode, convert lexical candidates directly to Evidence using `round(min(score, 1), 4)` and emit success.
6. Call vector once. On `RetrievalSourceUnavailable`: auto returns lexical fallback success/degradation; forced hybrid emits the exception stage and rethrows the same object.
7. Before service integration, add this exact wrapper to `vector_source.py` (reuse `VectorFailureStage` from contracts):

```python
@dataclass(frozen=True, slots=True)
class VectorSourceExecutionError(RuntimeError):
    cause: Exception
    failure_stage: VectorFailureStage

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, "vector source execution failed")
```

Import `dataclass`. Around index and query, keep availability handlers first, then add:

```python
except Exception as cause:
    raise VectorSourceExecutionError(cause, "vector_index") from cause
```

and the corresponding `"vector_query"` block. In `tests/evidence/test_vector_candidate_source.py`, replace the old single import with:

```python
from paper_agent.evidence.vector_source import (
    VectorCandidateSource,
    VectorSourceExecutionError,
)
```

Then replace the Chunk 2 nonavailability adapter test with:

```python
def test_vector_source_wraps_nonavailability_error_with_stage() -> None:
    chunk, _ = _chunk_and_vector()
    retriever = FakeVectorRetriever()
    cause = EmbeddingAuthenticationError("auth")
    retriever.index_error = cause
    with pytest.raises(VectorSourceExecutionError) as exc_info:
        VectorCandidateSource(retriever).retrieve("question", [chunk], 3)
    assert exc_info.value.cause is cause
    assert exc_info.value.failure_stage == "vector_index"
```

The service catches this wrapper, emits its stage with `vector_failure`, then executes `raise wrapper.cause from None`. This preserves the caller-visible original exception without retaining the wrapper as context. Never default an unknown index error to query.
8. Fuse with active sources `("lexical", "vector")`, truncate after fusion, convert using fusion scores, and emit one success event.
9. Fusion/conversion failures emit their exact stage and rethrow.

Implement this exact module-level conversion boundary and private event helpers:

```python
ScoreMode = Literal["lexical", "fusion"]


def _candidates_to_evidence(
    candidates: Sequence[RetrievalCandidate],
    *,
    run_id: str,
    top_k: int,
    score_mode: ScoreMode,
) -> tuple[Evidence, ...]:
    evidence: list[Evidence] = []
    for index, item in enumerate(candidates[:top_k], start=1):
        raw_score = (
            item.lexical_score if score_mode == "lexical"
            else item.fusion_score
        )
        if raw_score is None:
            raise ValueError(f"candidate lacks {score_mode} score")
        evidence.append(Evidence(
            evidence_id=f"{run_id}:ev_{index:03d}",
            paper_id=item.paper_id,
            chunk_id=item.chunk_id,
            claim_type="retrieved",
            quote=item.text,
            relevance_score=round(min(raw_score, 1.0), 4),
        ))
    return tuple(evidence)
```

Import `Literal`, `Sequence`, `Evidence`, and `RetrievalCandidate`. Lexical-only and degraded paths pass `score_mode="lexical"`; fused hybrid passes `"fusion"`. Inputs are already deterministically sorted; Top-K truncation occurs only inside this function, immediately before Evidence ID assignment. Event construction/delivery helpers use the counts table below. Delivery occurs before success return or failure rethrow; sink errors propagate immediately.

Use this exact error-event state table:

| stage | error_code | lexical count | vector count | fused count | returned | actual mode |
|---|---|---:|---:|---:|---:|---|
| validation | invalid_request | 0 | 0 | 0 | 0 | planned mode |
| lexical | lexical_failure | 0 | 0 | 0 | 0 | planned mode |
| vector_index/query | vector_failure | completed lexical count | 0 | 0 | 0 | hybrid |
| fusion | fusion_failure | completed lexical | completed vector | 0 | 0 | hybrid |
| evidence_conversion | evidence_conversion_failure | completed lexical | completed vector | fused count | 0 | actual mode |

Every failure emits exactly once. Forced-hybrid availability uses the vector stage from `RetrievalSourceUnavailable`. Auto availability is a successful degraded lexical event, not an error event.

- [ ] **Step 6: Run focused tests and regressions**

Run: `python -m pytest tests/evidence/test_hybrid_retriever.py tests/evidence/test_hybrid_failures.py tests/evidence/test_rrf_fusion.py -q`

Expected: PASS.

Run: `python -m pytest tests/test_evidence_retriever.py tests/test_pipeline_evidence_trace.py tests/evidence -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```bash
git add paper_agent/evidence tests/__init__.py tests/evidence/__init__.py tests/evidence/hybrid_fakes.py tests/evidence/test_vector_candidate_source.py tests/evidence/test_hybrid_retriever.py tests/evidence/test_hybrid_failures.py
git commit -m "feat: orchestrate hybrid evidence retrieval"
```

### Chunk 3 verification checkpoint

- [ ] Run: `python -m pytest tests/evidence tests/test_evidence_retriever.py -q`; expected PASS.
- [ ] Run: `python -m pytest -q`; expected all tests PASS and record actual count.
- [ ] Run: `git diff --check`; expected no output.
- [ ] Confirm pipeline, factory, evaluation runner, Rerank, generation, and database adapters remain unchanged.
## Chunk 4: Retrieval factory, pipeline integration, and JSONL events

### Task 8: Assemble retrieval services with explicit resource ownership

**Files:**
- Create: `paper_agent/evidence/factory.py`
- Modify: `paper_agent/evidence/__init__.py`
- Create: `tests/evidence/test_retrieval_factory.py`

- [ ] **Step 1: Write complete ownership and key-boundary tests**

Start with `pytest`, `Settings`, factory imports, and `FakeTransport` implementing `embed()`, `__enter__`, `__exit__`, and `closed`. The public factory accepts an optional borrowed transport; only the default production path constructs and owns a transport.

```python
@pytest.mark.parametrize("key", [None, "", "   "])
def test_auto_without_nonblank_key_is_lexical_and_constructs_no_transport(
    key, monkeypatch
) -> None:
    monkeypatch.setattr(
        factory_module, "HttpxEmbeddingTransport",
        lambda: pytest.fail("transport constructed"),
    )
    with build_retrieval_service(
        Settings(retrieval_mode="auto", dashscope_api_key=key)
    ) as service:
        assert service.requested_mode == "auto"
        assert service.vector_source is None



def test_lexical_with_key_never_touches_any_transport(monkeypatch) -> None:
    borrowed = FakeTransport()
    monkeypatch.setattr(
        factory_module, "HttpxEmbeddingTransport",
        lambda: pytest.fail("production transport constructed"),
    )
    with build_retrieval_service(
        Settings(retrieval_mode="lexical", dashscope_api_key="key"),
        transport=borrowed,
    ) as service:
        assert service.requested_mode == "lexical"
        assert service.vector_source is None
    assert borrowed.enter_calls == 0
    assert borrowed.closed is False


@pytest.mark.parametrize("key", [None, "", "   "])
def test_forced_hybrid_without_nonblank_key_is_configuration_error(key) -> None:
    with pytest.raises(
        RetrievalConfigurationError, match="DASHSCOPE_API_KEY"
    ) as exc_info:
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key=key)
        ):
            pytest.fail("factory must not yield")
    assert exc_info.value.error_code == "retrieval_configuration_error"


def test_default_path_closes_owned_transport_on_success(monkeypatch) -> None:
    transport = FakeTransport()
    monkeypatch.setattr(factory_module, "HttpxEmbeddingTransport", lambda: transport)
    with build_retrieval_service(
        Settings(retrieval_mode="auto", dashscope_api_key="key")
    ) as service:
        assert service.vector_source is not None
        assert transport.closed is False
    assert transport.closed is True


def test_default_path_closes_owned_transport_when_consumer_raises(monkeypatch) -> None:
    transport = FakeTransport()
    monkeypatch.setattr(factory_module, "HttpxEmbeddingTransport", lambda: transport)
    with pytest.raises(RuntimeError, match="consumer"):
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key="key")
        ):
            raise RuntimeError("consumer")
    assert transport.closed is True


def test_borrowed_transport_is_never_entered_or_closed() -> None:
    transport = FakeTransport()
    with build_retrieval_service(
        Settings(retrieval_mode="hybrid", dashscope_api_key="key"),
        transport=transport,
    ) as service:
        assert service.vector_source is not None
    assert transport.enter_calls == 0
    assert transport.closed is False
```

Add both assembly-error cleanup tests as executable bodies:

```python
def test_assembly_error_closes_owned_transport(monkeypatch) -> None:
    sentinel = RuntimeError("assembly")
    transport = FakeTransport()
    monkeypatch.setattr(factory_module, "HttpxEmbeddingTransport", lambda: transport)
    monkeypatch.setattr(
        factory_module, "BailianTextEmbedder",
        lambda **kwargs: (_ for _ in ()).throw(sentinel),
    )
    with pytest.raises(RuntimeError) as exc_info:
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key="key")
        ):
            pytest.fail("factory must not yield")
    assert exc_info.value is sentinel
    assert transport.enter_calls == 1
    assert transport.closed is True


def test_assembly_error_does_not_close_borrowed_transport(monkeypatch) -> None:
    sentinel = RuntimeError("assembly")
    transport = FakeTransport()
    monkeypatch.setattr(
        factory_module, "BailianTextEmbedder",
        lambda **kwargs: (_ for _ in ()).throw(sentinel),
    )
    with pytest.raises(RuntimeError) as exc_info:
        with build_retrieval_service(
            Settings(retrieval_mode="hybrid", dashscope_api_key="key"),
            transport=transport,
        ):
            pytest.fail("factory must not yield")
    assert exc_info.value is sentinel
    assert transport.enter_calls == 0
    assert transport.closed is False
```

- [ ] **Step 2: Add a complete dependency-forwarding test**

Use recording fakes with constructor signatures matching the production classes:

```python
def test_factory_forwards_settings_and_dependencies(monkeypatch) -> None:
    recorded = {}
    transport = FakeTransport()

    class RecordingEmbedder:
        def __init__(self, *, api_key, model, region, transport):
            recorded["embedder"] = (api_key, model, region, transport)
            recorded["embedder_instance"] = self

    class RecordingStore:
        def __init__(self, *, embedding_model):
            recorded["store_model"] = embedding_model
            recorded["store_instance"] = self

    class RecordingRetriever:
        def __init__(self, *, embedder, store):
            recorded["retriever"] = (embedder, store)
            recorded["retriever_instance"] = self

    class RecordingVectorSource:
        def __init__(self, retriever):
            recorded["vector_retriever"] = retriever
            recorded["vector_source_instance"] = self

    class RecordingLexicalSource:
        pass

    class RecordingService:
        def __init__(
            self, *, lexical_source, vector_source, requested_mode,
            candidate_k, top_k, rrf_k
        ):
            recorded["service_instance"] = self
            recorded["service"] = (
                lexical_source, vector_source, requested_mode,
                candidate_k, top_k, rrf_k,
            )

    monkeypatch.setattr(factory_module, "LexicalCandidateSource", RecordingLexicalSource)
    monkeypatch.setattr(factory_module, "BailianTextEmbedder", RecordingEmbedder)
    monkeypatch.setattr(factory_module, "InMemoryVectorStore", RecordingStore)
    monkeypatch.setattr(factory_module, "VectorRetriever", RecordingRetriever)
    monkeypatch.setattr(factory_module, "VectorCandidateSource", RecordingVectorSource)
    monkeypatch.setattr(factory_module, "HybridEvidenceRetriever", RecordingService)
    settings = Settings(
        retrieval_mode="hybrid", dashscope_api_key="secret",
        bailian_embedding_model="text-embedding-v4", bailian_region="beijing",
        retrieval_candidate_k=21, retrieval_top_k=7, retrieval_rrf_k=42,
    )
    with build_retrieval_service(settings, transport=transport):
        pass
    assert recorded["embedder"] == (
        "secret", "text-embedding-v4", "beijing", transport
    )
    assert recorded["store_model"] == "text-embedding-v4"
    assert recorded["retriever"] == (
        recorded["embedder_instance"], recorded["store_instance"]
    )
    assert recorded["vector_retriever"] is recorded["retriever_instance"]
    lexical, vector, mode, candidate_k, top_k, rrf_k = recorded["service"]
    assert lexical.__class__ is RecordingLexicalSource
    assert vector is recorded["vector_source_instance"]
    assert (mode, candidate_k, top_k, rrf_k) == ("hybrid", 21, 7, 42)
```

Add identity assertions linking `embedder` and `store` to the instances passed into `RecordingRetriever`, and that retriever to `RecordingVectorSource`. `vector_collection` is intentionally not forwarded: this stage uses `InMemoryVectorStore`, whose constructor has no collection parameter.

Run: `python -m pytest tests/evidence/test_retrieval_factory.py -q`

Expected: collection error because `paper_agent.evidence.factory` is absent.

- [ ] **Step 3: Implement the context-managed factory**

Define frozen `RetrievalConfigurationError` with stable `error_code="retrieval_configuration_error"`. Implement:

```python
@contextmanager
def build_retrieval_service(
    settings: Settings,
    *,
    transport: EmbeddingTransport | None = None,
) -> Iterator[HybridEvidenceRetriever]:
```

Assembly rules:

1. Create `LexicalCandidateSource` for every mode.
2. `lexical`, or `auto` with no nonblank key: yield a service with `vector_source=None`; never construct or touch a transport.
3. Forced hybrid without a nonblank key raises the typed configuration error.
4. If `transport` is supplied, treat it as borrowed: do not call `__enter__`, `__exit__`, or `close`.
5. Otherwise construct `HttpxEmbeddingTransport`, enter it with `ExitStack`, and guarantee cleanup on assembly failure, consumer failure, and success.
6. Build `BailianTextEmbedder`, same-model `InMemoryVectorStore`, `VectorRetriever`, `VectorCandidateSource`, then the service; pass candidate/top/RRF K exactly.
7. The factory never accepts or closes a caller-owned retrieval service.

Export factory and configuration error from `paper_agent.evidence`.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/evidence/test_retrieval_factory.py -q`

Expected: PASS without network access.

```bash
git add paper_agent/evidence tests/evidence/test_retrieval_factory.py
git commit -m "feat: assemble hybrid retrieval services"
```

### Task 9: Integrate retrieval outcomes and terminal events into pipeline

**Files:**
- Modify: `paper_agent/io.py`
- Modify: `paper_agent/pipeline.py`
- Modify: `tests/test_io.py`
- Modify: `tests/test_pipeline_evidence_trace.py`
- Create: `tests/test_pipeline_hybrid_retrieval.py`
- Create: `tests/test_pipeline_retrieval_failures.py`

- [ ] **Step 1: Add failing append-only JSONL tests**

```python
def test_append_json_line_writes_one_compact_utf8_object_per_line(tmp_path) -> None:
    path = tmp_path / "logs.jsonl"
    append_json_line(path, {"event": "retrieval", "message": "中文"})
    append_json_line(path, {"event": "second"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"event": "retrieval", "message": "中文"}, {"event": "second"}
    ]
```

Run: `python -m pytest tests/test_io.py -q`

Expected: import failure because `append_json_line` is absent.

- [ ] **Step 2: Implement append_json_line minimally**

Create parent directories; open with `encoding="utf-8", mode="a"`; write `json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"`. Never truncate existing events.

Run: `python -m pytest tests/test_io.py -q`

Expected: PASS.

- [ ] **Step 3: Define an executable injected service and success tests**

In `tests/test_pipeline_hybrid_retrieval.py`, define `FakeRetrievalService`. Its `retrieve(question, chunks, run_id, event_sink=None)` records arguments, constructs `Evidence` and `RetrievalOutcome` from the received `run_id`, constructs the matching success `RetrievalEvent`, sends it once, and returns the outcome. It must not store a prebuilt outcome. Give it `close()` only to count accidental ownership.

```python
def test_pipeline_uses_injected_service_and_writes_terminal_event(tmp_path) -> None:
    service = FakeRetrievalService()
    run_dir = run_pipeline(
        question="retrieval grounding", output_base=tmp_path, limit=1,
        no_pdf=True, search_fn=_fake_search, retrieval_service=service,
    )
    assert len(service.calls) == 1
    lines = (run_dir / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert (event["status"], event["actual_mode"]) == ("ok", "hybrid")
    evidence = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    assert evidence[0]["evidence_id"].startswith(f"{run_dir.name}:")
    assert service.close_calls == 0
```

Also retain the default no-key regression: unset `DASHSCOPE_API_KEY`, run with no injected service, and assert one event with requested `auto`, actual `lexical`.

- [ ] **Step 4: Add exact empty, assembly-error, and service-error tests**

Parameterize the direct empty path over forced-hybrid keys `[None, "", "   "]`. Patch `build_retrieval_service` to fail if called. Assert empty evidence and exactly one event equal to the complete expected mapping: `status="ok"`, requested `hybrid`, actual `lexical`, lexical/vector/fused/evidence counts all zero, `vector_attempted=False`, `degraded=False`, and `degradation_code`, `failure_stage`, `error_code` all `None`.

For nonempty forced hybrid, parameterize the same key values; assert `RetrievalConfigurationError`, exactly one assembly error event, requested `hybrid`, actual mode `None`, every count zero, vector not attempted, and `error_code="retrieval_configuration_error"` without an exception message.

In `tests/test_pipeline_retrieval_failures.py`, add:

```python
def test_service_error_is_rethrown_without_duplicate_event(tmp_path) -> None:
    sentinel = RuntimeError("sentinel-service-error")
    service = ErroringRetrievalService(sentinel)
    with pytest.raises(RuntimeError) as exc_info:
        run_pipeline(
            question="question", output_base=tmp_path, no_pdf=True,
            search_fn=_fake_search, retrieval_service=service,
        )
    assert exc_info.value is sentinel
    run_dir = next(tmp_path.iterdir())
    lines = (run_dir / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["status"] == "error"
    assert event["failure_stage"] == "vector_query"
    assert event["error_code"] == "vector_failure"
    assert event["degradation_code"] is None
```

`ErroringRetrievalService.retrieve()` emits that one complete valid event with `actual_mode="hybrid"`, `vector_attempted=True`, `degraded=False`, `degradation_code=None`, all known counts, `failure_stage="vector_query"`, and `error_code="vector_failure"`, then raises the exact sentinel. Pipeline must neither catch it nor add an assembly event. Assert its `close_calls` remains zero.

- [ ] **Step 5: Implement the pipeline flow with an exact exception boundary**

Extend the current signature without changing existing positional parameters:

```python
def run_pipeline(
    question: str,
    output_base: Path = Path("outputs"),
    limit: int = 5,
    no_pdf: bool = False,
    search_fn: SearchFn = search_arxiv,
    *,
    settings: Settings | None = None,
    retrieval_service: EvidenceRetrievalService | None = None,
) -> Path:
```

After run-directory creation, initialize empty `logs.jsonl`; load and chunk papers before factory assembly. Create a sink that calls `append_json_line(log_path, event.model_dump(mode="json"))`.

1. Injected service: call it for all inputs including empty chunks; caller owns it.
2. Otherwise load settings exactly once unless explicit settings were passed.
3. Empty chunks: directly create the lexical empty outcome and complete success event; never call the factory.
4. Nonempty chunks: use `ExitStack`. Catch `RetrievalConfigurationError` only around `stack.enter_context(build_retrieval_service(settings))`; write the single assembly event and rethrow. Call `service.retrieve(...)` after that `except` block but inside the `with ExitStack()` lifetime.
5. Never catch service exceptions; the service emitted its terminal event. Do not write a second event.
6. Pass only `outcome.evidence` to analysis, synthesis, citation checking, and rendering.

Do not add CLI flags in this Task.

- [ ] **Step 6: Run focused tests and regressions**

Run: `python -m pytest tests/test_io.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_hybrid_retrieval.py tests/test_pipeline_retrieval_failures.py -q`

Expected: PASS.

Run: `python -m pytest tests/test_cli.py tests/test_pipeline_vertical_slice.py -q`

Expected: PASS with unchanged CLI calls.

- [ ] **Step 7: Commit Task 9**

```bash
git add paper_agent/io.py paper_agent/pipeline.py tests/test_io.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_hybrid_retrieval.py tests/test_pipeline_retrieval_failures.py
git commit -m "feat: integrate hybrid retrieval pipeline"
```

### Chunk 4 verification checkpoint

- [ ] Run: `python -m pytest tests/evidence tests/test_io.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_hybrid_retrieval.py tests/test_pipeline_retrieval_failures.py -q`; expected PASS.
- [ ] Run: `python -m pytest -q`; expected all tests PASS and record actual count.
- [ ] Run: `git diff --check`; expected no output.
- [ ] Confirm production-owned transports close on every exit, borrowed transports and injected services remain caller-owned, and tests make no network calls.
## Chunk 5: Offline ranking metrics and three-mode evaluation

### Task 10: Add strict Top-K ranking metrics

**Files:**
- Modify: `paper_agent/eval/metrics.py`
- Modify: `paper_agent/eval/__init__.py`
- Create: `tests/test_eval_retrieval_metrics.py`

- [ ] **Step 1: Add shared validation and failing metric tests**

Import the four new functions from `paper_agent.eval.metrics`. Add exact-value tests:

```python
def test_binary_ranking_metrics_use_only_top_k() -> None:
    ranked = ["c0", "c2", "c1"]
    grades = {"c1": 2, "c2": 1}
    assert recall_at_k(ranked, grades, 2) == 0.5
    assert precision_at_k(ranked, grades, 2) == 0.5
    assert mrr_at_k(ranked, grades, 2) == 0.5


def test_precision_uses_actual_returned_length() -> None:
    assert precision_at_k(["c1"], {"c1": 1}, 5) == 1.0


def test_ndcg_uses_graded_gain_and_log_discount() -> None:
    result = ndcg_at_k(["c2", "c1"], {"c1": 2, "c2": 1}, 2)
    actual = 1.0 + 3.0 / math.log2(3)
    ideal = 3.0 + 1.0 / math.log2(3)
    assert result == pytest.approx(actual / ideal)


@pytest.mark.parametrize("k", [0, -1, True, 1.5, "2"])
@pytest.mark.parametrize(
    "metric", [recall_at_k, precision_at_k, mrr_at_k, ndcg_at_k]
)
def test_ranking_metrics_require_positive_plain_integer_k(metric, k) -> None:
    with pytest.raises(ValueError, match="k must be a positive integer"):
        metric([], {}, k)
```

Also parameterize every public function to reject duplicate ranked IDs, non-string ranked IDs, non-string relevance keys, boolean grades, negative grades, and non-integer grades with `ValueError`. Test empty ranking, no relevant items, K truncation, and an empty relevance mapping returning `0.0`.

Run: `python -m pytest tests/test_eval_retrieval_metrics.py -q`

Expected: import failure because the ranking metrics do not exist.

- [ ] **Step 2: Implement the exact public metric contract**

```python
def recall_at_k(
    ranked_ids: list[str], relevance_by_id: dict[str, int], k: int
) -> float:

def precision_at_k(
    ranked_ids: list[str], relevance_by_id: dict[str, int], k: int
) -> float:

def mrr_at_k(
    ranked_ids: list[str], relevance_by_id: dict[str, int], k: int
) -> float:

def ndcg_at_k(
    ranked_ids: list[str], relevance_by_id: dict[str, int], k: int
) -> float:
```

Use one private validator called by all four; require `type(k) is int and k >= 1`. Grade `> 0` is relevant. Recall divides unique relevant IDs in `ranked_ids[:k]` by all relevant IDs in the mapping. Precision divides relevant results by `len(ranked_ids[:k])`, returning zero for empty output. MRR@K returns the first relevant reciprocal rank in that slice. nDCG uses gain `2**grade - 1`, discount `log2(rank + 1)`, and all mapping grades sorted descending then truncated to K for ideal DCG; zero ideal returns zero. Export all four without changing existing metrics.

- [ ] **Step 3: Run focused and legacy tests**

Run: `python -m pytest tests/test_eval_retrieval_metrics.py tests/test_eval_metrics.py -q`

Expected: PASS.

- [ ] **Step 4: Commit Task 10**

```bash
git add paper_agent/eval/metrics.py paper_agent/eval/__init__.py tests/test_eval_retrieval_metrics.py
git commit -m "feat: add top-k retrieval metrics"
```

### Task 11: Compare lexical, vector, and hybrid retrieval offline

**Files:**
- Create: `paper_agent/eval/retrieval_runner.py`
- Modify: `paper_agent/eval/__init__.py`
- Create: `tests/fixtures/retrieval_eval_cases.json`
- Create: `tests/test_retrieval_eval_runner.py`

- [ ] **Step 1: Create the complete deterministic fixture**

Write this complete JSON array. It separately covers complementary source-only hits, lexical-only, vector-only, duplicate hits, no relevant result, graded relevance, and lexical tie ordering:

```json
[
  {
    "case_id": "complementary-results",
    "query": "exact kinase",
    "chunks": [
      {"chunk_id":"c-lex","paper_id":"p-1","section":null,"page":1,"text":"exact kinase marker","token_count":3},
      {"chunk_id":"c-vec","paper_id":"p-2","section":null,"page":2,"text":"semantic pathway neighbor","token_count":3}
    ],
    "relevance_by_chunk_id": {"c-lex":2,"c-vec":1},
    "vector_ranked_chunk_ids": ["c-vec"]
  },
  {
    "case_id": "lexical-only-hit",
    "query": "rare acronym xyz",
    "chunks": [
      {"chunk_id":"c-lex-only","paper_id":"p-3","section":null,"page":1,"text":"rare acronym xyz","token_count":3},
      {"chunk_id":"c-noise-a","paper_id":"p-4","section":null,"page":1,"text":"unrelated passage","token_count":2}
    ],
    "relevance_by_chunk_id": {"c-lex-only":1},
    "vector_ranked_chunk_ids": []
  },
  {
    "case_id": "vector-only-hit",
    "query": "surface words",
    "chunks": [
      {"chunk_id":"c-false-lex","paper_id":"p-5","section":null,"page":1,"text":"surface words","token_count":2},
      {"chunk_id":"c-vec-only","paper_id":"p-6","section":null,"page":1,"text":"semantic meaning","token_count":2}
    ],
    "relevance_by_chunk_id": {"c-false-lex":0,"c-vec-only":1},
    "vector_ranked_chunk_ids": ["c-vec-only"]
  },
  {
    "case_id": "duplicate-hit",
    "query": "shared retrieval",
    "chunks": [
      {"chunk_id":"c-shared","paper_id":"p-7","section":null,"page":1,"text":"shared retrieval","token_count":2}
    ],
    "relevance_by_chunk_id": {"c-shared":1},
    "vector_ranked_chunk_ids": ["c-shared"]
  },
  {
    "case_id": "no-relevant-result",
    "query": "alpha query",
    "chunks": [
      {"chunk_id":"c-alpha","paper_id":"p-8","section":null,"page":1,"text":"alpha query","token_count":2},
      {"chunk_id":"c-zero","paper_id":"p-9","section":null,"page":1,"text":"other text","token_count":2}
    ],
    "relevance_by_chunk_id": {"c-alpha":0,"c-zero":0},
    "vector_ranked_chunk_ids": ["c-zero"]
  },
  {
    "case_id": "graded-relevance",
    "query": "ranking evidence",
    "chunks": [
      {"chunk_id":"c-grade-high","paper_id":"p-10","section":null,"page":1,"text":"ranking evidence strong","token_count":3},
      {"chunk_id":"c-grade-low","paper_id":"p-11","section":null,"page":1,"text":"ranking evidence weak","token_count":3}
    ],
    "relevance_by_chunk_id": {"c-grade-high":3,"c-grade-low":1},
    "vector_ranked_chunk_ids": ["c-grade-low","c-grade-high"]
  },
  {
    "case_id": "lexical-tie",
    "query": "tie token",
    "chunks": [
      {"chunk_id":"c-tie-b","paper_id":"p-12","section":null,"page":1,"text":"tie token beta","token_count":3},
      {"chunk_id":"c-tie-a","paper_id":"p-13","section":null,"page":1,"text":"tie token alpha","token_count":3}
    ],
    "relevance_by_chunk_id": {"c-tie-a":1,"c-tie-b":1},
    "vector_ranked_chunk_ids": []
  }
]
```

Do not add expected fused rankings or tune weights from this fixture.

- [ ] **Step 2: Add executable output, default, complementarity, and aggregate tests**

Start with helpers:

```python
FIXTURE_PATH = Path("tests/fixtures/retrieval_eval_cases.json")
METRIC_NAMES = {"recall_at_k", "precision_at_k", "mrr_at_k", "ndcg_at_k"}


def _write_fixture(tmp_path: Path, cases: object) -> Path:
    path = tmp_path / "retrieval.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def _base_case() -> dict[str, object]:
    return {
        "case_id": "base", "query": "alpha",
        "chunks": [{"chunk_id":"c1","paper_id":"p1","section":None,
                    "page":1,"text":"alpha text","token_count":2}],
        "relevance_by_chunk_id": {"c1": 1},
        "vector_ranked_chunk_ids": ["c1"],
    }
```

Then add:

```python
def test_runner_defaults_to_eight_without_loading_environment(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_TOP_K", "99")
    result = evaluate_retrieval_fixture(FIXTURE_PATH)
    assert result["k"] == 8


def test_runner_freezes_case_and_mode_output_shape() -> None:
    result = evaluate_retrieval_fixture(FIXTURE_PATH, k=2)
    assert set(result) == {"k", "cases", "summary"}
    assert set(result["cases"][0]) == {"case_id", "modes"}
    assert set(result["cases"][0]["modes"]) == {"lexical", "vector", "hybrid"}
    for mode in result["cases"][0]["modes"].values():
        assert set(mode) == {"ranked_chunk_ids", "metrics"}
        assert set(mode["metrics"]) == METRIC_NAMES


def test_complementary_case_keeps_each_unique_hit_once() -> None:
    result = evaluate_retrieval_fixture(FIXTURE_PATH, k=2)
    case = next(item for item in result["cases"]
                if item["case_id"] == "complementary-results")
    assert case["modes"]["lexical"]["ranked_chunk_ids"] == ["c-lex"]
    assert case["modes"]["vector"]["ranked_chunk_ids"] == ["c-vec"]
    assert set(case["modes"]["hybrid"]["ranked_chunk_ids"]) == {"c-lex", "c-vec"}
    assert len(case["modes"]["hybrid"]["ranked_chunk_ids"]) == 2


def test_summary_is_macro_average() -> None:
    result = evaluate_retrieval_fixture(FIXTURE_PATH, k=2)
    for mode in ("lexical", "vector", "hybrid"):
        for metric in METRIC_NAMES:
            expected = sum(c["modes"][mode]["metrics"][metric]
                           for c in result["cases"]) / len(result["cases"])
            assert result["summary"][mode][metric] == pytest.approx(expected)


def test_empty_fixture_returns_zero_summaries(tmp_path) -> None:
    result = evaluate_retrieval_fixture(_write_fixture(tmp_path, []), k=2)
    assert result == {
        "k": 2, "cases": [],
        "summary": {mode: {metric: 0.0 for metric in METRIC_NAMES}
                    for mode in ("lexical", "vector", "hybrid")},
    }
```

Per-case output intentionally excludes query; fixture order is preserved.

- [ ] **Step 3: Add complete validation tests**

```python
@pytest.mark.parametrize("k", [0, -1, True, 1.5, "2"])
def test_runner_requires_positive_plain_integer_k(tmp_path, k) -> None:
    with pytest.raises(ValueError, match="k must be a positive integer"):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, []), k=k)


@pytest.mark.parametrize(
    "field",
    ["case_id", "query", "chunks", "relevance_by_chunk_id",
     "vector_ranked_chunk_ids"],
)
def test_runner_requires_every_case_field(tmp_path, field) -> None:
    case = _base_case()
    del case[field]
    with pytest.raises(ValueError, match=field):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, [case]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_id", " "), ("query", " "), ("chunks", "not-a-list"),
        ("relevance_by_chunk_id", []), ("vector_ranked_chunk_ids", {}),
        ("vector_ranked_chunk_ids", ["unknown"]),
        ("vector_ranked_chunk_ids", ["c1", "c1"]),
        ("relevance_by_chunk_id", {"unknown": 1}),
        ("relevance_by_chunk_id", {"c1": True}),
        ("relevance_by_chunk_id", {"c1": -1}),
        ("relevance_by_chunk_id", {"c1": 1.5}),
    ],
)
def test_runner_rejects_malformed_case_fields(tmp_path, field, value) -> None:
    case = _base_case()
    case[field] = value
    with pytest.raises(ValueError, match=field):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, [case]))
```

Add separate executable tests for non-list top level; duplicate case IDs; duplicate chunk IDs by appending a copy of `_base_case()["chunks"][0]`; and a malformed Chunk such as `token_count="two"`. Each assertion matches the case ID and affected field. Run: `python -m pytest tests/test_retrieval_eval_runner.py -q`; expected import failure because the runner is absent.

- [ ] **Step 4: Implement parsing, fake-vector adaptation, and real fusion**

Define a fixed offline default; never read settings or environment:

```python
def evaluate_retrieval_fixture(
    path: str | Path, *, k: int = 8
) -> dict[str, object]:
```

Validate every field before evaluation. Convert chunks with `Chunk.model_validate`, wrapping Pydantic errors as case/field `ValueError`. Unknown qrel/vector IDs and duplicates fail. Omitted relevance entries have grade zero.

For each case call real `LexicalCandidateSource.retrieve(query, chunks, max(k, len(chunks)))`. Convert each fixture vector ID with the exact fields:

```python
chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
vector = [
    RetrievalCandidate(
        chunk_id=chunk_id,
        paper_id=chunk_by_id[chunk_id].paper_id,
        text=chunk_by_id[chunk_id].text,
        section=chunk_by_id[chunk_id].section,
        page=chunk_by_id[chunk_id].page,
        retrieval_sources=("vector",),
        lexical_score=None,
        lexical_rank=None,
        vector_score=1.0 / rank,
        vector_rank=rank,
        fusion_score=None,
    )
    for rank, chunk_id in enumerate(vector_ranked_chunk_ids, start=1)
]
```

Call real `fuse_candidates(lexical, vector, rrf_k=60, active_sources=("lexical", "vector"))`. Truncate each mode to K for output and metrics. Return:

```python
{
    "k": k,
    "cases": [
        {
            "case_id": "case-id",
            "modes": {
                "lexical": {"ranked_chunk_ids": [], "metrics": {}},
                "vector": {"ranked_chunk_ids": [], "metrics": {}},
                "hybrid": {"ranked_chunk_ids": [], "metrics": {}},
            },
        }
    ],
    "summary": {
        "lexical": {}, "vector": {}, "hybrid": {}
    },
}
```

Every metrics mapping has exactly `recall_at_k`, `precision_at_k`, `mrr_at_k`, `ndcg_at_k`; every summary mapping is their macro average, or four zeros for no cases. Export `evaluate_retrieval_fixture`; leave existing report runner unchanged.

- [ ] **Step 5: Run and commit**

Run: `python -m pytest tests/test_retrieval_eval_runner.py -q`

Expected: PASS without network access.

Run: `python -m pytest tests/test_eval_metrics.py tests/test_eval_runner.py tests/test_eval_retrieval_metrics.py tests/test_retrieval_eval_runner.py -q`

Expected: PASS with unchanged report fixture output.

```bash
git add paper_agent/eval/retrieval_runner.py paper_agent/eval/__init__.py tests/fixtures/retrieval_eval_cases.json tests/test_retrieval_eval_runner.py
git commit -m "feat: compare retrieval modes offline"
```

### Chunk 5 verification checkpoint

- [ ] Run both evaluation suites from Step 5; expected PASS.
- [ ] Confirm the complementary hybrid ranking contains both source-specific relevant IDs once and duplicate case contains `c-shared` once.
- [ ] Confirm evaluation never loads settings or constructs an HTTP transport.
- [ ] Run `git diff --check`; expected no output.
## Chunk 6: Offline vertical integration, operator documentation, and final acceptance

### Task 12: Prove lexical and vector complementarity through the real service stack

**Files:**
- Create: `tests/evidence/test_hybrid_retrieval_integration.py`

- [ ] **Step 1: Add a deterministic embedder and complete offline integration test**

Use real `LexicalCandidateSource`, `VectorCandidateSource`, `VectorRetriever`, `InMemoryVectorStore`, `fuse_candidates` through `HybridEvidenceRetriever`, and real Evidence conversion. Only embedding is faked:

```python
from collections.abc import Sequence

from paper_agent.evidence.hybrid import HybridEvidenceRetriever
from paper_agent.evidence.retriever import LexicalCandidateSource
from paper_agent.evidence.vector_source import VectorCandidateSource
from paper_agent.schemas import Chunk
from paper_agent.vector import InMemoryVectorStore, VectorRetriever


class DeterministicEmbedder:
    model_name = "test-hybrid-v1"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vectors[text] for text in texts]


def _chunk(chunk_id: str, paper_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, paper_id=paper_id, section="Results", page=1,
        text=text, token_count=len(text.split()),
    )
```

Then add this exact scenario:

```python
def test_real_hybrid_stack_keeps_complementary_results_once() -> None:
    question = "exact kinase"
    lexical_chunk = _chunk("chunk-lex", "paper-lex", "exact kinase marker")
    vector_chunk = _chunk("chunk-vec", "paper-vec", "semantic pathway neighbor")
    embedder = DeterministicEmbedder({
        lexical_chunk.text: [0.0, 1.0],
        vector_chunk.text: [1.0, 0.0],
        question: [1.0, 0.0],
    })
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    vector_retriever = VectorRetriever(embedder=embedder, store=store)
    service = HybridEvidenceRetriever(
        lexical_source=LexicalCandidateSource(),
        vector_source=VectorCandidateSource(vector_retriever),
        requested_mode="hybrid", candidate_k=1, top_k=2, rrf_k=60,
    )

    outcome = service.retrieve(
        question, [vector_chunk, lexical_chunk], "run-integration"
    )

    assert {item.chunk_id for item in outcome.evidence} == {
        "chunk-lex", "chunk-vec"
    }
    assert len({item.chunk_id for item in outcome.evidence}) == 2
    assert [item.evidence_id for item in outcome.evidence] == [
        "run-integration:ev_001", "run-integration:ev_002"
    ]
    assert [item.relevance_score for item in outcome.evidence] == [0.5, 0.5]
    assert outcome.diagnostics.model_dump() == {
        "lexical_candidate_count": 1,
        "vector_candidate_count": 1,
        "fused_candidate_count": 2,
        "returned_evidence_count": 2,
        "requested_mode": "hybrid",
        "actual_mode": "hybrid",
        "vector_attempted": True,
        "degraded": False,
        "degradation_code": None,
    }
    assert embedder.calls == [
        [vector_chunk.text, lexical_chunk.text], [question]
    ]
```

The equal fused scores intentionally exercise the stable `chunk_id` tie-break; assert the Evidence chunk order is `['chunk-lex', 'chunk-vec']` in addition to the set assertion. This test must not patch fusion, candidate conversion, the in-memory store, or either source adapter.

- [ ] **Step 2: Create and run the complete integration test**

Create the test exactly as specified, including the ordered chunk assertion. Because Tasks 1–11 already supply the behavior and this Task adds only vertical coverage, do not manufacture a RED result with an intentionally wrong assertion.

Run: `python -m pytest tests/evidence/test_hybrid_retrieval_integration.py -q`

Expected: PASS; any genuine failure is diagnosed and fixed in the owning earlier Task before continuing.

- [ ] **Step 3: Run integration and adjacent real-store regressions**

Run: `python -m pytest tests/evidence/test_hybrid_retrieval_integration.py tests/vector/test_vector_retrieval_integration.py tests/evidence/test_rrf_fusion.py -q`

Expected: PASS without API keys or network access.

- [ ] **Step 4: Commit Task 12**

```bash
git add tests/evidence/test_hybrid_retrieval_integration.py
git commit -m "test: cover offline hybrid retrieval stack"
```

### Task 13: Document operation and complete release-grade verification

**Files:**
- Create: `docs/hybrid-retrieval.md`
- Modify: `docs/evaluation.md`

- [ ] **Step 1: Write the operator-facing retrieval guide**

Document only implemented behavior:

- modes `auto`, `lexical`, `hybrid` and default `auto`;
- `DASHSCOPE_API_KEY`, `BAILIAN_REGION`, `BAILIAN_EMBEDDING_MODEL`, `RETRIEVAL_MODE`, `RETRIEVAL_CANDIDATE_K`, `RETRIEVAL_TOP_K`, and `RETRIEVAL_RRF_K` with defaults but no example secret;
- `auto` without a key is lexical; timeout, network, rate-limit, and server failures may degrade to lexical; authentication, request/configuration, response-shape, dimension/model, metadata, and other contract failures never degrade; forced `hybrid` fails for every vector failure;
- empty chunks succeed without vector configuration;
- one sanitized retrieval event per call in `logs.jsonl` and the meaning of requested/actual mode, counts, degradation, failure stage, and error code;
- current `InMemoryVectorStore` is per-process and may re-embed each run;
- no reranking, persistent vector database, weight tuning, retries, or CLI mode flags in this stage.

Include exact environment examples with `DASHSCOPE_API_KEY` omitted for offline mode and with the value shown only as `<set-in-shell>` for configured hybrid.

- [ ] **Step 2: Extend evaluation documentation without rewriting Evaluation v1**

Append a “Retrieval ranking evaluation” section to `docs/evaluation.md`. Document Recall@K, Precision@K with actual returned-length denominator, MRR@K, graded nDCG@K, fixture fields, validation rules, three compared modes, macro averaging, empty-fixture zeros, and offline-only behavior. Replace the stale Future Evaluation statement that ranking metrics are not implemented, while retaining all report-evaluation v1 contracts and limitations.

Include this executable usage:

```python
from pathlib import Path

from paper_agent.eval.retrieval_runner import evaluate_retrieval_fixture

result = evaluate_retrieval_fixture(
    Path("tests/fixtures/retrieval_eval_cases.json"), k=8
)
```

- [ ] **Step 3: Run all focused Hybrid Retrieval suites**

Run:

```bash
python -m pytest tests/test_config.py tests/evidence tests/vector tests/test_io.py tests/test_pipeline_evidence_trace.py tests/test_pipeline_hybrid_retrieval.py tests/test_pipeline_retrieval_failures.py tests/test_eval_metrics.py tests/test_eval_runner.py tests/test_eval_retrieval_metrics.py tests/test_retrieval_eval_runner.py -q
```

Expected: PASS and no network access.

- [ ] **Step 4: Run the complete repository suite**

Run: `python -m pytest -q`

Expected: all tests PASS; record the actual test count in the execution handoff rather than hard-coding the pre-implementation count.

- [ ] **Step 5: Commit documentation**

```bash
git add docs/hybrid-retrieval.md docs/evaluation.md
git commit -m "docs: explain hybrid retrieval operation"
```

- [ ] **Step 6: Audit the committed full branch for contracts, secrets, and scope**

Run: `git diff --check master...HEAD`

Expected: no output across the complete committed branch range.

Run: `rg -n "TODO|TBD|NotImplementedError|pytest\.skip|@pytest\.mark\.skip" paper_agent tests docs/hybrid-retrieval.md docs/evaluation.md`

Expected: no skipped Hybrid tests and no implementation placeholders. The sole allowed new `NotImplementedError` matches are the Protocol method bodies in `paper_agent/evidence/contracts.py` created by Chunk 1 Task 2; inspect each match and confirm it is inside `CandidateSource` or `EvidenceRetrievalService`, not executable production logic. Existing unrelated matches must be listed with file and reason.

Now that every Task commit exists, inspect both `git diff master...HEAD --stat` and the complete `git diff master...HEAD`. Confirm:

1. Documentation changes are included in the reviewed range.
2. No secrets, authorization values, provider-produced or real embeddings, real/copyrighted source-paper text, or provider response bodies are logged or committed. Minimal deterministic synthetic vectors and synthetic fixture text in tests are allowed.
3. No Rerank, persistent vector database, retry loop, learned weighting, generation-model, or CLI flag implementation entered the diff.
4. Existing report-evaluation APIs and lexical behavior remain covered by regression tests.
5. Every implementation commit corresponds to one Task above and contains its focused tests.

Run `git status --short --branch`; expected clean working tree on the Hybrid implementation branch.
### Chunk 6 and plan completion checkpoint

- [ ] Run the complete focused command from Task 13 Step 3; expected PASS.
- [ ] Run `python -m pytest -q`; expected all tests PASS.
- [ ] Run `git diff --check master...HEAD`; expected no output across the complete committed range.
- [ ] Inspect `git status --short --branch`; expected only intentional commits and no uncommitted files.
- [ ] Record actual test counts, offline/network status, mode/fallback coverage, and known in-memory-store limitation in the handoff.
- [ ] Stop after Hybrid Retrieval acceptance. Do not begin the separate Bailian Rerank specification or implementation.
