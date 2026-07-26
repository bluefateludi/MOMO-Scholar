# Agent Trace and Observability Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist sealed, sanitized Pipeline and Evaluation traces with exactly two span names, explicit execution/scoring identities, fresh-child or reuse-link correlation, deterministic cross-file validation, and optional OTLP export.

**Architecture:** `TraceFileWriter` owns schema-1.0 JSONL append/seal/hash mechanics. `PipelineRunTrace` owns the single `paper_agent.pipeline.run` span and allowlisted Pipeline events; `EvaluationCaseTrace` owns the single `paper_agent.evaluation.case` span and either a fresh child relationship or a standard OTel Span Link to a sealed reused execution. `RunRecorder` finalizes children, root, sealed trace, hash, terminal manifest, then optional exporter in that order; manifest remains Pipeline terminal authority.

**Tech Stack:** Python 3.10+, Pydantic v2, JSONL, SHA-256, pytest, optional OpenTelemetry Python SDK/OTLP HTTP exporter.

**Specification:** `docs/superpowers/specs/2026-07-23-agent-trace-observability-design.md`, especially authoritative section 0.

---

## Delivery guardrails

- Work only in `.worktrees/agent-trace-observability` on `codex/agent-trace-observability`.
- Do not modify the main workspace or RAG Evaluation worktree.
- Do not commit, push, merge, stage, or open a PR without new explicit authorization.
- Implement Chunks in order using RED-GREEN-REFACTOR. Run focused tests before broader suites.
- Preserve existing manifest/log behavior unless this plan explicitly extends a strict contract.
- Final 60-case integration belongs to the Evaluation project. This worktree freezes the reusable contract and passes synthetic integration tests only.

## Locked contracts

1. Trace schema version is `1.0`; the only span names are `paper_agent.pipeline.run` and `paper_agent.evaluation.case`.
2. Pipeline stages and Evaluation metrics are strict allowlisted `span_event` records, not spans.
3. `run_id` identifies the existing run directory; `execution_id` identifies one Pipeline execution; `scoring_attempt_id` identifies one scoring attempt.
4. A fresh execution uses W3C parent-child correlation: evaluation case parent, pipeline run child.
5. Reuse recovery creates a new evaluation case with an OTel Span Link to the sealed historical pipeline root and records `reused_execution_id`.
6. Every execution owns `traces.jsonl`; every scoring attempt owns `evaluation-traces.jsonl`. A `trace_seal` is the final record and later append is forbidden.
7. `trace_seal.pre_seal_sha256` hashes the exact bytes before the seal. After appending and flushing the seal, the writer returns the SHA-256 of the complete sealed file for the terminal manifest/result.
8. Pipeline terminal order is events/children, root end, trace seal+flush, full-file hash, atomic terminal manifest, optional exporter flush.
9. Exporter failures write only backward-compatible `logs.jsonl` warnings or a separate exporter-health artifact. They never mutate a sealed trace or terminal manifest.
10. Validator modes are `standalone`, `fresh_child`, and `declared_reuse_link`. `trace-index.json` is a rebuildable projection.
11. Without a terminal manifest, Pipeline success is `unknown`; root span status can never promote it to success.

## File map

**Create:**

- `paper_agent/observability/tracing_models.py` — strict IDs, links, lifecycle/event/seal records, identities, and validation results.
- `paper_agent/observability/trace_store.py` — append, flush, seal, full-file hash, immutable-after-seal behavior.
- `paper_agent/observability/run_trace.py` — one Pipeline root plus allowlisted Pipeline events.
- `paper_agent/observability/evaluation_trace.py` — one Evaluation root, scoring identity, fresh parent or reuse link.
- `paper_agent/observability/trace_validation.py` — per-file and cross-file validation plus index rebuild.
- `paper_agent/observability/openinference.py` — pure two-span/event semantic mapping.
- `paper_agent/observability/otlp.py` — lazy optional OTel replay preserving IDs, parent, links, events, and timestamps.
- `tests/observability/test_tracing_models.py`
- `tests/observability/test_trace_store.py`
- `tests/observability/test_run_trace.py`
- `tests/observability/test_evaluation_trace.py`
- `tests/observability/test_trace_validation.py`
- `tests/observability/test_openinference.py`
- `tests/observability/test_otlp.py`
- `tests/test_pipeline_tracing.py`
- `docs/observability.md`

**Modify:**

- `paper_agent/observability/models.py` — execution ID and terminal trace metadata in `RunManifest`.
- `paper_agent/observability/recorder.py` — run trace ownership and terminal ordering.
- `paper_agent/observability/sanitize.py` — trace denylist and artifact scanner helpers.
- `paper_agent/observability/__init__.py` — caller-facing contracts only.
- `paper_agent/pipeline.py` — correlation input and Pipeline span events.
- `paper_agent/config.py` — local trace and optional OTLP settings.
- `pyproject.toml` — optional `observability` extra.
- `README.md`
- focused existing observability, pipeline, config, and packaging tests.

## Chunk 1: Schema, sealed storage, and Pipeline lifecycle

### Task 1: Strict schema-1.0 records and identities

**Files:**
- Create: `paper_agent/observability/tracing_models.py`
- Create: `tests/observability/test_tracing_models.py`
- Modify: `paper_agent/observability/__init__.py`

- [ ] **Step 1: Write failing identity and record tests**

```python
def test_execution_and_scoring_ids_are_distinct_contracts() -> None:
    execution = PipelineCorrelationInput(execution_id='exec-1')
    scoring = ScoringCorrelation(
        scoring_attempt_id='score-1',
        execution_id='exec-1',
        case_id='case-1',
    )
    assert execution.execution_id != scoring.scoring_attempt_id


def test_only_two_span_names_are_allowed() -> None:
    SpanStartRecord(name='paper_agent.pipeline.run', **START_FIELDS)
    SpanStartRecord(name='paper_agent.evaluation.case', **START_FIELDS)
    with pytest.raises(ValidationError):
        SpanStartRecord(name='paper_agent.retrieval', **START_FIELDS)


def test_reuse_link_requires_matching_reused_execution_id() -> None:
    link = SpanLink(
        trace_id='1' * 32,
        span_id='2' * 16,
        attributes={'link.type': 'reused_execution', 'execution_id': 'exec-old'},
    )
    with pytest.raises(ValidationError, match='reused_execution_id'):
        SpanStartRecord(
            correlation_mode='declared_reuse_link',
            scoring_attempt_id='score-2',
            reused_execution_id='exec-other',
            links=[link],
            **START_FIELDS,
        )


def test_trace_seal_requires_pre_seal_hash_and_record_count() -> None:
    seal = TraceSealRecord(
        timestamp=NOW,
        artifact_kind='pipeline_execution',
        owner_id='exec-1',
        record_count=3,
        pre_seal_sha256='a' * 64,
    )
    assert seal.record_type == 'trace_seal'
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_tracing_models.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'paper_agent.observability.tracing_models'`.

- [ ] **Step 3: Implement strict value objects**

Implement `W3CSpanContext`, `SpanLink`, `PipelineCorrelationInput`, `RunCorrelation`, `ScoringCorrelation`, `SpanStartRecord`, `SpanEventRecord`, `SpanEndRecord`, and `TraceSealRecord` using repository `StrictModel`.

Validation must enforce lowercase non-zero 32/16-hex IDs, UTC timestamps, nonblank owner IDs, exact schema `1.0`, exactly two span names, event-name allowlists by owning span, no extra fields, and these correlation modes:

```python
CorrelationMode = Literal['standalone', 'fresh_child', 'declared_reuse_link']
SpanName = Literal['paper_agent.pipeline.run', 'paper_agent.evaluation.case']
RecordType = Literal['span_start', 'span_event', 'span_end', 'trace_seal']
```

`SpanLink` uses standard context fields plus safe scalar attributes. `declared_reuse_link` requires exactly one link whose `execution_id` equals `reused_execution_id`; fresh mode forbids reuse fields.

Required fields are fixed as follows:

| Record | Required payload | Invariants |
|---|---|---|
| `span_start` | timestamp, trace/span/parent IDs, name, owner IDs, mode, attributes, links | pipeline start forbids scoring ID/reuse link; evaluation start requires scoring ID; fresh has parent/no reuse link; reuse has one matching link |
| `span_event` | timestamp, trace/span IDs, event name, status, attributes | owning span exists; name is in that span's allowlist; degraded/error requires stable code |
| `span_end` | timestamp, trace/span IDs, status, duration, attributes | exactly one per span; `ok` forbids code; degraded/error requires code |
| `trace_seal` | timestamp, artifact kind, owner ID, record count, pre-seal SHA-256 | final record; `record_count` equals every preceding start/event/end record; no later bytes/records |

Pipeline event allowlist is the ten names in Task 4. Evaluation allowlist initially contains only `paper_agent.evaluation.metrics`; unknown names are rejected.

- [ ] **Step 4: Verify GREEN and regression**

Run: `pytest tests/observability/test_tracing_models.py tests/observability/test_models.py -q`

Expected: exit code 0; all selected tests PASS with no failures.

### Task 2: Append-only sealed trace store

**Files:**
- Create: `paper_agent/observability/trace_store.py`
- Create: `tests/observability/test_trace_store.py`

- [ ] **Step 1: Write failing append/seal tests**

```python
def test_seal_is_final_record_and_returns_full_file_hash(tmp_path) -> None:
    store = TraceFileWriter.create(
        tmp_path / 'traces.jsonl',
        artifact_kind='pipeline_execution',
        owner_id='exec-1',
    )
    store.append(_start())
    store.append(_end())
    digest = store.seal(timestamp=NOW)
    lines = (tmp_path / 'traces.jsonl').read_bytes().splitlines()
    seal = json.loads(lines[-1])
    assert seal['record_type'] == 'trace_seal'
    assert seal['record_count'] == 2
    assert digest == hashlib.sha256((tmp_path / 'traces.jsonl').read_bytes()).hexdigest()
    with pytest.raises(TraceSealedError):
        store.append(_event())


def test_seal_hashes_exact_pre_seal_bytes(tmp_path) -> None:
    store = _store(tmp_path)
    store.append(_start())
    before = (tmp_path / 'traces.jsonl').read_bytes()
    store.seal(timestamp=NOW)
    seal = json.loads((tmp_path / 'traces.jsonl').read_text().splitlines()[-1])
    assert seal['record_count'] == 1
    assert seal['pre_seal_sha256'] == hashlib.sha256(before).hexdigest()


def test_append_or_flush_failure_is_integrity_error(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(store, '_flush', _raise_oserror)
    with pytest.raises(TracePersistenceError):
        store.seal(timestamp=NOW)
```

Add executable tests asserting: a second `seal()` raises `TraceSealedError`; reopening a file whose final record is a seal returns read-only/sealed state; an externally appended record after the seal is rejected by `inspect_trace_file`; input model dumps remain equal before/after append; and compact UTF-8 lines contain no indentation/newline inside a record.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_trace_store.py -q`

Expected: collection fails with `ImportError` for `TraceFileWriter` from `paper_agent.observability.trace_store`.

- [ ] **Step 3: Implement storage mechanics**

Use `append_json_line` semantics for records. `seal()` computes the pre-seal digest, appends and flushes a validated seal, closes the writable handle, then streams the complete file through SHA-256. No exporter callback lives in this module.

- [ ] **Step 4: Verify GREEN and I/O compatibility**

Run: `pytest tests/observability/test_trace_store.py tests/test_io.py -q`

Expected: exit code 0; all selected tests PASS with no failures.

### Task 3A: Pipeline root lifecycle

**Files:**
- Create: `paper_agent/observability/run_trace.py`
- Create: `tests/observability/test_run_trace.py`

- [ ] **Step 1: Write failing Pipeline root tests**

```python
def test_synthetic_external_parent_is_preserved(tmp_path) -> None:
    parent = W3CSpanContext(trace_id='1' * 32, span_id='2' * 16)
    trace = PipelineRunTrace.start(
        path=tmp_path / 'traces.jsonl',
        correlation=RunCorrelation(run_id='run-1', execution_id='exec-1', parent=parent),
        root_attributes={},
    )
    assert trace.context.trace_id == parent.trace_id
    assert trace.context.span_id != parent.span_id
    assert trace.context.span_id != '0' * 16
    assert _records(trace.path)[0]['parent_span_id'] == parent.span_id


def test_pipeline_trace_emits_events_but_no_child_spans(tmp_path) -> None:
    trace = _run_trace(tmp_path)
    trace.event('paper_agent.pipeline.search', {'result_count': 2})
    digest = trace.finish(status='ok')
    records = _records(trace.path)
    assert [r['record_type'] for r in records] == [
        'span_start', 'span_event', 'span_end', 'trace_seal'
    ]
    assert {r.get('name') for r in records if r['record_type'] == 'span_start'} == {
        'paper_agent.pipeline.run'
    }
    assert len(digest) == 64
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_run_trace.py -q`

Expected: collection fails with `ImportError` for `PipelineRunTrace`.

- [ ] **Step 3: Implement PipelineRunTrace**

`PipelineRunTrace` has only `context`, `event(name, attributes)`, and `finish(status, code=None) -> str`. It owns one start, many events, one end, and one seal. It sanitizes then validates every record.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/observability/test_run_trace.py tests/observability/test_trace_store.py tests/observability/test_tracing_models.py -q`

Expected: exit code 0; all selected tests PASS with no failures.
### Task 3B: RunManifest trace metadata contract

**Files:**
- Modify: `paper_agent/observability/models.py`
- Modify: `tests/observability/test_models.py`

- [ ] **Step 1: Write failing terminal metadata tests**

Test exact model dictionaries for: running manifest with `execution_id` and null trace terminal fields; completed manifest requiring schema version, root trace/span IDs, and 64-hex full-file hash; `trace_persistence_failed` failed manifest allowing null hash; and every other terminal state rejecting missing trace metadata.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_models.py -q`

Expected: new assertions fail because `RunManifest` has no `execution_id` or trace metadata fields.

- [ ] **Step 3: Implement manifest invariants**

Add `execution_id`, `trace_schema_version`, `trace_root_trace_id`, `trace_root_span_id`, and `trace_sha256`. Preserve existing `run_id`. Running manifests require null terminal trace fields. Completed/degraded/ordinary failed manifests require schema `1.0`, valid root IDs, and full-file hash. Only `trace_persistence_failed` may omit terminal trace metadata.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/observability/test_models.py -q`

Expected: exit code 0; all model tests PASS.

### Task 3C: RunRecorder terminal ordering and recovery

**Files:**
- Modify: `paper_agent/observability/recorder.py`
- Modify: `tests/observability/test_recorder.py`

- [ ] **Step 1: Write failing terminal ordering test**

```python
def test_terminal_order_is_root_seal_hash_manifest_then_exporter(tmp_path) -> None:
    calls = []
    recorder = _start_with_recording_trace(tmp_path, calls)
    recorder.complete(
        status='completed',
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={},
        usage=USAGE,
    )
    assert calls == [
        'root_end', 'trace_seal', 'trace_hash',
        'manifest_replace', 'exporter_close',
    ]
    manifest = _read_json(recorder.run_dir / 'run_manifest.json')
    assert manifest['trace_sha256'] == _sha256(recorder.run_dir / 'traces.jsonl')
```

- [ ] **Step 2: Write failing integrity-path tests**

Add exact tests proving: trace append/seal failure raises `TracePersistenceError` and best-effort writes failed manifest code `trace_persistence_failed`; terminal manifest replacement failure never produces a second root end and validator outcome remains unknown; exporter close failure leaves sealed trace/manifest byte-identical and appends one sanitized `otlp_export_failed` log warning; degraded and failed runs map to degraded/error root ends.

- [ ] **Step 3: Verify RED**

Run: `pytest tests/observability/test_recorder.py -q`

Expected: ordering assertion fails because current recorder writes only manifest/log artifacts.

- [ ] **Step 4: Implement lifecycle ownership**

`RunRecorder.start()` creates `execution_id` when absent, starts `PipelineRunTrace` after manifest/log creation, and exposes `trace_event`. `complete()`/`fail()` finish root, seal/flush, obtain full-file hash, atomically replace terminal manifest, then close exporter. Root terminal intent is immutable; no failure path writes a second end/seal.

- [ ] **Step 5: Verify GREEN and Chunk 1**

Run: `pytest tests/observability/test_tracing_models.py tests/observability/test_trace_store.py tests/observability/test_run_trace.py tests/observability/test_recorder.py tests/observability/test_models.py tests/test_io.py -q`

Expected: exit code 0; all selected tests PASS with no failures.

- [ ] **Step 6: Review Chunk 1 diff without staging**

Run: `git diff --check`

Expected: no whitespace errors. Do not stage or commit.

## Chunk 2: Pipeline events, Evaluation handoff, and cross-file integrity

### Task 4: Instrument Pipeline events without adding spans

**Files:**
- Modify: `paper_agent/pipeline.py`
- Create: `tests/test_pipeline_tracing.py`
- Modify: `tests/test_pipeline_fulltext_integration.py`
- Modify: `tests/test_pipeline_terminal_states.py`

- [ ] **Step 1: Write failing event-topology tests**

```python
def test_success_pipeline_has_one_span_and_required_events(tmp_path) -> None:
    result = _run_success(tmp_path)
    records = _records(result.run_dir / 'traces.jsonl')
    starts = [r for r in records if r['record_type'] == 'span_start']
    assert [r['name'] for r in starts] == ['paper_agent.pipeline.run']
    assert _event_names(records) == {
        'paper_agent.pipeline.search',
        'paper_agent.pipeline.document_acquire',
        'paper_agent.pipeline.document_chunk',
        'paper_agent.pipeline.retrieval',
        'paper_agent.pipeline.analysis',
        'paper_agent.pipeline.citation_validate_paper',
        'paper_agent.pipeline.synthesis',
        'paper_agent.pipeline.citation_validate_report',
        'paper_agent.pipeline.report_render',
        'paper_agent.pipeline.artifacts_publish',
    }
    assert records[-1]['record_type'] == 'trace_seal'


def test_fallback_and_skipped_analysis_are_degraded_events(tmp_path) -> None:
    result = _run_fallback_and_skipped_analysis(tmp_path)
    events = _events(result.run_dir)
    assert _one(events, 'paper_agent.pipeline.document_acquire', paper_id='p1')['status'] == 'degraded'
    assert _one(events, 'paper_agent.pipeline.analysis', paper_id='p2')['status'] == 'degraded'
    assert _root_end(result.run_dir)['status'] == 'degraded'


def test_terminal_failure_seals_error_trace_before_failed_manifest(tmp_path) -> None:
    with pytest.raises(PipelineRunFailed) as caught:
        _run_failing_synthesis(tmp_path)
    assert _root_end(caught.value.run_dir)['status'] == 'error'
    assert _records(caught.value.run_dir / 'traces.jsonl')[-1]['record_type'] == 'trace_seal'
    assert _manifest(caught.value.run_dir).status == 'failed'
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_pipeline_tracing.py -q`

Expected: `FileNotFoundError` for `traces.jsonl` or the first required-event assertion fails.

- [ ] **Step 3: Add correlation input and allowlisted event emission**

Add `correlation: PipelineCorrelationInput | None = None` to `run_pipeline` and pass it through the existing recorder factory seam. Replace the existing generic `timed()` helper with `recorded_operation(event_name, safe_initial_attributes, operation)` that preserves `stage_elapsed_seconds` while emitting one completed event.

In `tests/test_pipeline_tracing.py`, implement `_run_success`, `_run_fallback_and_skipped_analysis`, and `_run_failing_synthesis` from the deterministic `Settings`, `Provider`, and dependency fakes already defined in `tests/test_pipeline_fulltext_integration.py` and `tests/test_pipeline_terminal_states.py`; no ellipsis or network call remains.

Populate only normalized identifiers, hashes, counts, modes, model names, attempts, usage, durations, and stable error/degradation codes. Never copy provider payload dictionaries, text chunks, prompts, responses, abstracts, quotes, stack traces, exception objects, or arbitrary exception messages.

Keep current retrieval `RunEvent` emission backward compatible. Keep the legacy `retrieval_service` branch behavior unchanged and explicitly outside the traced production path.

- [ ] **Step 4: Verify focused Pipeline GREEN**

Run: `pytest tests/test_pipeline_tracing.py tests/test_pipeline_fulltext_integration.py tests/test_pipeline_terminal_states.py tests/test_pipeline_hybrid_retrieval.py tests/test_pipeline_vertical_slice.py -q`

Expected: exit code 0; all selected tests PASS and existing expected artifact sets add only `traces.jsonl`.

### Task 5: Evaluation scoring trace and reuse-link contract

**Files:**
- Create: `paper_agent/observability/evaluation_trace.py`
- Create: `tests/observability/test_evaluation_trace.py`
- Modify: `paper_agent/observability/__init__.py`

- [ ] **Step 1: Write failing fresh and reuse tests**

```python
def test_fresh_scoring_trace_supplies_parent_for_pipeline(tmp_path) -> None:
    external = W3CSpanContext(trace_id='9' * 32, span_id='8' * 16)
    trace = EvaluationCaseTrace.start(
        path=tmp_path / 'evaluation-traces.jsonl',
        correlation=ScoringCorrelation(
            scoring_attempt_id='score-1', execution_id='exec-1', case_id='case-1'
        ),
        parent=external,
    )
    child_input = trace.fresh_pipeline_parent()
    start = _records(trace.path)[0]
    assert trace.context.trace_id == external.trace_id
    assert start['parent_span_id'] == external.span_id
    assert child_input.execution_id == 'exec-1'
    assert child_input.parent.trace_id == trace.context.trace_id
    assert child_input.parent.span_id == trace.context.span_id


def test_recovery_links_sealed_historical_pipeline_root(tmp_path) -> None:
    historical = SealedExecutionReference(
        execution_id='exec-old',
        trace_id='1' * 32,
        span_id='2' * 16,
        trace_sha256='a' * 64,
    )
    trace = EvaluationCaseTrace.start_reuse(
        path=tmp_path / 'evaluation-traces.jsonl',
        scoring_attempt_id='score-2',
        case_id='case-1',
        reused=historical,
    )
    start = _records(trace.path)[0]
    assert start['reused_execution_id'] == 'exec-old'
    assert start['links'][0]['trace_id'] == historical.trace_id
    assert start['links'][0]['attributes']['link.type'] == 'reused_execution'


def test_each_scoring_attempt_owns_independent_sealed_file(tmp_path) -> None:
    first = _finish_score(tmp_path / 'score-1' / 'evaluation-traces.jsonl', 'score-1')
    second = _finish_score(tmp_path / 'score-2' / 'evaluation-traces.jsonl', 'score-2')
    assert first.path != second.path
    assert _seal(first.path)['owner_id'] == 'score-1'
    assert _seal(second.path)['owner_id'] == 'score-2'


def test_metric_events_are_owned_by_single_evaluation_span(tmp_path) -> None:
    trace = _fresh_trace(tmp_path)
    trace.metric_event('paper_agent.evaluation.metrics', {'metric_count': 4})
    trace.finish(status='ok')
    records = _records(trace.path)
    assert [r['name'] for r in records if r['record_type'] == 'span_start'] == [
        'paper_agent.evaluation.case'
    ]
    assert [r['name'] for r in records if r['record_type'] == 'span_event'] == [
        'paper_agent.evaluation.metrics'
    ]
    with pytest.raises(TraceDataPolicyError):
        _fresh_trace(tmp_path / 'other').metric_event('unknown.metric', {})
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_evaluation_trace.py -q`

Expected: collection fails with `ImportError` for `EvaluationCaseTrace`.

- [ ] **Step 3: Implement the Evaluation-owned adapter module**

`EvaluationCaseTrace` exposes `context`, `metric_event`, `fresh_pipeline_parent`, and `finish`. It always owns one evaluation span and one scoring attempt file. `start(path, correlation, parent=None)` accepts an optional synthetic/remote W3C parent; the evaluation span preserves its trace ID and records its parent span ID. Fresh mode may provide the resulting evaluation context as a Pipeline parent; reuse mode forbids starting/reparenting a historical Pipeline run and exposes only the declared link.

This task does not modify `paper_agent.eval.runner` or the RAG Evaluation worktree. It freezes the handoff interface used by the later Integration Task.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/observability/test_evaluation_trace.py tests/observability/test_trace_store.py tests/observability/test_tracing_models.py -q`

Expected: exit code 0; all selected tests PASS with no failures.

### Task 6: Security policy and serialized-artifact scan

**Files:**
- Modify: `paper_agent/observability/sanitize.py`
- Modify: `paper_agent/observability/run_trace.py`
- Modify: `paper_agent/observability/evaluation_trace.py`
- Modify: `tests/observability/test_sanitize.py`
- Modify: `tests/observability/test_run_trace.py`
- Modify: `tests/observability/test_evaluation_trace.py`
- Modify: `tests/test_pipeline_tracing.py`

- [ ] **Step 1: Add failing denylist and secret tests**

```python
@pytest.mark.parametrize('key', [
    'prompt', 'prompt_text', 'response', 'response_text', 'abstract',
    'pdf_text', 'evidence_quote', 'authorization', 'cookie',
    'stack_trace', 'exception_message', 'endpoint_url',
])
def test_trace_events_reject_prohibited_keys(key: str) -> None:
    with pytest.raises(TraceDataPolicyError):
        validate_event_attributes('paper_agent.pipeline.analysis', {key: 'private'})


def test_pipeline_and_evaluation_trace_files_contain_no_runtime_secret(tmp_path) -> None:
    secret = 'runtime-secret-value'
    paths = _produce_pipeline_and_evaluation_traces(tmp_path, secret=secret)
    for path in paths:
        assert secret not in path.read_text(encoding='utf-8')
```

Also cover nested credential keys, malicious objects whose `str`/`repr` raise, URLs with credentials/query/fragment, raw provider request/response keys, non-mutation, and scans after failure paths.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_sanitize.py tests/observability/test_run_trace.py tests/observability/test_evaluation_trace.py tests/test_pipeline_tracing.py -q`

Expected: the first unsupported key is accepted or the serialized secret assertion fails.

- [ ] **Step 3: Implement defense in depth**

Centralize exact event allowlists and prohibited key/value scanning. Sanitize known runtime secret substrings before strict record validation. Questions/templates use content hash, character count, and version ID. Endpoints reduce to hostname. Event adapters construct explicit dictionaries rather than filtering arbitrary provider dictionaries.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/observability tests/test_pipeline_tracing.py tests/test_pipeline_terminal_states.py -q`

Expected: exit code 0; all selected tests PASS with zero sensitive findings.

### Task 7: Cross-file validator and rebuildable trace index

**Files:**
- Create: `paper_agent/observability/trace_validation.py`
- Create: `tests/observability/test_trace_validation.py`
- Modify: `paper_agent/observability/__init__.py`

- [ ] **Step 1: Write failing validator tests**

```python
def test_fresh_child_validation_matches_cross_file_context(tmp_path) -> None:
    evaluation_path, run_dir = _fresh_pair(tmp_path)
    result = validate_trace_pair(evaluation_path=evaluation_path, run_dir=run_dir)
    assert result.correlation_mode == 'fresh_child'
    assert result.valid


def test_declared_reuse_link_validates_sealed_historical_execution(tmp_path) -> None:
    evaluation_path, run_dir = _reuse_pair(tmp_path)
    result = validate_trace_pair(evaluation_path=evaluation_path, run_dir=run_dir)
    assert result.correlation_mode == 'declared_reuse_link'
    assert result.valid


def test_root_ok_without_terminal_manifest_is_unknown_not_success(tmp_path) -> None:
    run_dir = _sealed_ok_trace_without_terminal_manifest(tmp_path)
    result = validate_pipeline_trace(run_dir)
    assert result.pipeline_outcome == 'unknown'
    assert 'terminal_manifest_missing' in result.finding_codes


def test_index_is_rebuilt_from_authoritative_artifacts(tmp_path) -> None:
    sources = _fresh_and_reuse_sources(tmp_path)
    secret = 'runtime-secret-value'
    sources[0]['untrusted_label'] = secret
    rebuilt = rebuild_trace_index(sources)
    index_path = tmp_path / 'trace-index.json'
    assert rebuilt == json.loads(index_path.read_text(encoding='utf-8'))
    assert rebuilt['projection_version'] == '1.0'
    assert secret not in index_path.read_text(encoding='utf-8')


def test_missing_applicable_event_is_reported(tmp_path) -> None:
    run_dir = _successful_execution_without_synthesis_event(tmp_path)
    assert 'required_event_missing' in validate_pipeline_trace(run_dir).finding_codes


def test_early_search_failure_does_not_require_later_events(tmp_path) -> None:
    run_dir = _failed_search_execution(tmp_path)
    result = validate_pipeline_trace(run_dir)
    assert 'required_event_missing' not in result.finding_codes
    assert result.required_event_coverage == 1.0
```

Parameterize corruptions for missing/duplicate lifecycle records, post-seal append, pre-seal hash mismatch, full-file hash mismatch, identity mismatch, wrong fresh parent, missing/wrong reuse link, missing applicable event, valid early-failure applicability, and missing terminal manifest.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_trace_validation.py -q`

Expected: collection fails with `ImportError` for `validate_trace_pair`.

- [ ] **Step 3: Implement deterministic validation**

Parse each record through strict models. Verify final seal position, pre-seal bytes hash, terminal manifest full-file hash, owner IDs, one allowed root, event applicability, and terminal authority. `validate_trace_pair` explicitly branches fresh-child versus declared-reuse-link; it must never accept a historical span as a fresh child.

`rebuild_trace_index` writes an atomic projection containing paths, IDs, contexts, modes, hashes, and validation state only. Deleting it loses no authoritative data.

- [ ] **Step 4: Verify GREEN and Chunk 2**

Run: `pytest tests/observability tests/test_pipeline_tracing.py tests/test_pipeline_fulltext_integration.py tests/test_pipeline_terminal_states.py -q`

Expected: exit code 0; all selected tests PASS, including Task 6 security tests.

- [ ] **Step 5: Review Chunk 2 diff without staging**

Run: `pytest tests/observability tests/test_pipeline_tracing.py tests/test_pipeline_fulltext_integration.py tests/test_pipeline_terminal_states.py -q`

Expected: exit code 0; all Chunk 2 security, correlation, applicability, and Pipeline tests PASS.

Run: `git diff --check`

Expected: no whitespace errors. Do not stage or commit.

## Chunk 3: Optional export, configuration, and delivery

### Task 8: Pure OpenInference mapping for two spans and events

**Files:**
- Create: `paper_agent/observability/openinference.py`
- Create: `tests/observability/test_openinference.py`

- [ ] **Step 1: Write failing mapping tests**

```python
@pytest.mark.parametrize(
    ('name', 'kind'),
    [
        ('paper_agent.pipeline.run', 'CHAIN'),
        ('paper_agent.evaluation.case', 'EVALUATOR'),
    ],
)
def test_only_final_span_names_map(name: str, kind: str) -> None:
    assert map_span_kind(name) == kind


def test_pipeline_events_map_without_becoming_spans() -> None:
    mapped = map_event(
        'paper_agent.pipeline.retrieval',
        {'execution_id': 'exec-1', 'returned_evidence_count': 3},
    )
    assert mapped.name == 'paper_agent.pipeline.retrieval'
    assert mapped.attributes['paper_agent.execution.id'] == 'exec-1'


def test_reuse_link_preserves_standard_context_and_safe_attributes() -> None:
    mapped = map_link(_reuse_link())
    assert mapped.trace_id == '1' * 32
    assert mapped.span_id == '2' * 16
    assert mapped.attributes['paper_agent.reused_execution.id'] == 'exec-old'
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/observability/test_openinference.py -q`

Expected: collection fails with `ImportError` for `map_span_kind`.

- [ ] **Step 3: Implement pure deterministic mapping**

Use local string constants and pure value objects; import no optional OTel/OpenInference packages. Unknown span/event/attribute names raise rather than pass through. Preserve execution/scoring/run/case IDs under central semantic names and map local error state separately.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/observability/test_openinference.py -q`

Expected: exit code 0; all mapping tests PASS.

### Task 9: Optional ID/link-preserving OTLP adapter and configuration

**Files:**
- Create: `paper_agent/observability/otlp.py`
- Create: `tests/observability/test_otlp.py`
- Modify: `paper_agent/config.py`
- Modify: `paper_agent/observability/models.py`
- Modify: `paper_agent/observability/recorder.py`
- Modify: `paper_agent/pipeline.py`
- Modify: `tests/test_config.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Write failing configuration and disabled-import tests**

Test that enabled export rejects endpoint credentials/query/fragment, secret headers never enter safe settings, and a missing optional extra raises `ObservabilityConfigurationError` before any run directory is created. In a subprocess/import-blocking test, make every `opentelemetry*` import raise, then prove `import paper_agent.observability`, local tracing, and a run with OTLP disabled still succeed without network calls.

- [ ] **Step 2: Write failing replay and sealed-artifact tests**

Capture replayed spans for standalone, external-parent/fresh-child, and declared-reuse-link modes. Assert exact local trace/span/parent IDs, OTel Span Links, event names/attributes/timestamps, and span start/end timestamps independently. Snapshot sealed `traces.jsonl` and terminal manifest bytes before every exporter callback, force exporter failure, then assert both snapshots are unchanged and only `logs.jsonl` contains sanitized `otlp_export_failed`.

Define the failure threshold as per `OtlpTraceExporter` instance, which is owned by one run/scoring attempt. Test that two failures at threshold `2` disable that adapter, a third completed span makes no transport call, and exactly one sanitized post-seal health warning is emitted.

- [ ] **Step 3: Verify RED**

Run: `pytest tests/test_config.py tests/observability/test_otlp.py tests/test_packaging.py -q`

Expected: the first new setting assertion fails or collection raises `ImportError` for `paper_agent.observability.otlp`.

- [ ] **Step 4: Implement safe settings**

Add frozen settings for local trace enablement, deployment environment, OTLP enablement, safe HTTPS endpoint, positive timeout, bounded failure threshold, and secret header mapping with `repr=False`. Parse booleans strictly and headers only from a secret JSON environment setting. Never include header values in safe settings, manifests, logs, traces, or exceptions.

`TRACE_ENABLED=false` is an emergency/test opt-out: no trace file is created, terminal manifest trace fields are null, and validator returns `enabled=false`; default acceptance runs enabled.

- [ ] **Step 5: Implement lazy OTel replay**

Keep optional imports inside `_load_otel()`. Use a private `TracerProvider` and one-shot `IdGenerator` loaded with local IDs before `start_span`; construct explicit parent contexts and standard Links; replay original events and timestamps; never set the global provider. Assert replayed IDs match before export.

Official contracts: `https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.id_generator.html`, `https://opentelemetry-python.readthedocs.io/en/stable/api/trace.html`, and `https://opentelemetry.io/docs/languages/python/exporters/`.

Disable each run-owned exporter instance after its failure threshold; no process-global counter is used. Health callbacks may append one rate-limited sanitized `logs.jsonl` warning only and cannot access `TraceFileWriter` after seal.

- [ ] **Step 6: Add optional dependency extra**

Add `opentelemetry-api`, `opentelemetry-sdk`, and `opentelemetry-exporter-otlp-proto-http` constrained to compatible `>=1.38,<2` releases under `[project.optional-dependencies].observability`.

- [ ] **Step 7: Verify GREEN**

Run: `pytest tests/test_config.py tests/observability/test_otlp.py tests/test_packaging.py -q`

Expected: exit code 0; all selected tests PASS with no network calls. Absence behavior uses the lazy loader; replay tests use a capturing exporter.

### Task 10: Documentation and independent trace acceptance

**Files:**
- Create: `docs/observability.md`
- Modify: `README.md`
- Modify: `tests/observability/test_trace_validation.py`
- Modify: `tests/observability/test_otlp.py`

- [ ] **Step 1: Add the independent acceptance scenario**

Create one synthetic offline flow using only capturing exporters and no live backend. It starts an evaluation case from an external parent; starts and seals a fresh Pipeline child; seals the scoring trace; verifies both pre-seal and full-file hashes; starts a recovery scoring attempt linked to the historical root; validates fresh and reuse modes separately; rebuilds `trace-index.json`; snapshots artifacts before exporter callbacks; proves post-seal append is rejected and tampering with either hash fails validation; and proves missing terminal manifest never yields Pipeline success.

- [ ] **Step 2: Run independent acceptance**

Run: `pytest tests/observability/test_trace_validation.py tests/observability/test_otlp.py -q`

Expected: synthetic external-parent, Span Link, seal/hash, immutability, and cross-file validation tests pass.

- [ ] **Step 3: Document authority and integration boundary**

Document manifest/log/run-trace/evaluation-trace/index authority; execution versus scoring identities; fresh versus reused topology; seal/hash format; finalization order; local and OTLP configuration; exporter failure isolation; validator usage; Phoenix as optional only; and the Evaluation-owned 60-case Integration Task.

- [ ] **Step 4: Run focused observability and Pipeline suites**

Run: `pytest tests/observability tests/test_pipeline_tracing.py tests/test_pipeline_fulltext_integration.py tests/test_pipeline_terminal_states.py tests/test_config.py tests/test_packaging.py -q`

Expected: all tests pass offline.

- [ ] **Step 5: Run complete offline suite**

Run: `pytest -q`

Expected: all tests pass without Phoenix, Redis, an OTel collector, or live network access.

- [ ] **Step 6: Final integrity and scope review**

Run: `rg -n '^(<<<<<<<|=======|>>>>>>>)' . -g '!__pycache__/**'`

Expected: no conflict markers.

Run: `git diff --check`

Expected: no whitespace errors.

Run: `git status --short --untracked-files=all`

Expected: only the design, plan, and files named in this plan are changed. Do not stage or commit.

## Execution checkpoints

- **Chunk 1:** report focused test output for schema, sealing/hash, synthetic external parent, and terminal ordering.
- **Chunk 2:** report successful, degraded, and failed Pipeline traces; fresh/reuse validation; and security scans.
- **Chunk 3:** report ID/link-preserving replay, absent-extra behavior, independent trace acceptance, and full offline suite.
- **Integration Task:** RAG Evaluation runs final 60-case acceptance after consuming this contract. It is outside this worktree.
