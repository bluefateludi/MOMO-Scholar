# Agent Trace and Observability Design

**Date:** 2026-07-23
**Status:** Implementation-ready draft
**Scope:** Local durable Agent Trace, OpenTelemetry/OpenInference mapping, optional
OTLP/Phoenix export, trace completeness, and future worker evolution.

## 0. Final architecture corrections

This section records the final cross-project design review and is authoritative
where later draft sections conflict with it.

### 0.1 Span vocabulary and schema

Trace schema remains version `1.0`. The only span names are:

- `paper_agent.evaluation.case`
- `paper_agent.pipeline.run`

Pipeline stages are allowlisted span events on `paper_agent.pipeline.run`, not
child spans. Evaluation metrics are allowlisted span events on
`paper_agent.evaluation.case`.

### 0.2 Execution and scoring identities

`execution_id` identifies one Pipeline execution and its run-level artifacts.
`scoring_attempt_id` identifies one Evaluation/metrics attempt. They are
independent: a fresh scoring attempt may create a new execution, while recovery
may score a previously sealed execution. Existing `run_id` remains the
run-directory/artifact identifier and is not a scoring-attempt identifier.

### 0.3 Fresh execution and sealed-execution reuse

For a fresh execution, `paper_agent.evaluation.case` is the parent and
`paper_agent.pipeline.run` is its W3C child.

For scoring recovery against a sealed Pipeline execution, the new evaluation
case does not become a parent of the historical span. It carries a standard
OpenTelemetry Span Link to the old pipeline root and records
`reused_execution_id`.

### 0.4 Artifact ownership and sealing

Each `execution_id` owns one run-level `traces.jsonl`. Each
`scoring_attempt_id` owns one `evaluation-traces.jsonl`. A trace file ends with
a strict `trace_seal` record and is immutable afterward.

`trace-index.json` is a rebuildable projection across those authoritative
files. It is never the source of truth.

### 0.5 Pipeline finalization

Pipeline terminal ordering is:

1. finish child work and append its final allowlisted events;
2. finish `paper_agent.pipeline.run`;
3. append the trace seal and flush the run-level trace;
4. hash the complete sealed trace file;
5. atomically replace the terminal manifest with the trace hash;
6. flush/shutdown the optional exporter.

Exporter failure after sealing may be written only to `logs.jsonl` or a
separate exporter-health artifact. It must never append to or rewrite a sealed
trace.

### 0.6 Cross-file validation

The validator accepts and distinguishes:

- `fresh_child`: the pipeline root is a W3C child of the evaluation case;
- `declared_reuse_link`: the evaluation case has a valid Span Link to a sealed
  historical pipeline root and its `reused_execution_id` matches.

It validates seals, hashes, identities, correlation, and topology across the
two trace files. A missing terminal manifest is never interpreted as Pipeline
success from span status.

### 0.7 Acceptance ownership

The Agent Trace project independently verifies synthetic external parent
propagation, Span Link serialization/export, sealing, hashing, immutability,
and cross-file validation. The Evaluation project owns final end-to-end
acceptance over 60 cases; that integration is not implemented in this worktree.

## 1. Context and goals

MOMO Scholar already persists two observability artifacts:

- `run_manifest.json` is the authoritative snapshot of run configuration,
  aggregate counts, usage, degradations, errors, and terminal status.
- `logs.jsonl` is an append-only sequence of sanitized `RunEvent` records,
  currently used most deeply by retrieval.

These artifacts describe what ultimately happened, but they do not preserve
parent-child operation structure or connect an evaluation experiment, case,
pipeline run, paper, retrieval, generation call, and citation check in one
navigable trace.

This design adds that structure without replacing current artifacts. It must:

1. produce a durable, sanitized local trace for every pipeline run;
2. use OpenTelemetry identifiers and map to OpenInference semantic attributes;
3. correlate `experiment_id`, `case_id`, `run_id`, and `trace_id`;
4. represent success, permitted degradation, and terminal failure honestly;
5. permit optional OTLP export to Phoenix without making it a runtime
   requirement;
6. measure trace completeness deterministically;
7. preserve a clean seam for a later Redis-backed worker system.

This phase does **not** introduce Redis, a worker queue, Prometheus, Grafana,
Phoenix as a required dependency, or storage of raw prompts/provider payloads.

## 2. Approaches considered

### Replace the current recorder with OpenTelemetry

This gives one observability system but makes core run correctness depend on an
optional SDK/export path and risks changing stable manifest/log contracts. It
is rejected.

### Instrument every low-level module directly

This exposes HTTP-attempt detail, but spreads tracing imports and attribute
policy across retrieval, PDF, generation, and rendering modules. It weakens
locality and makes sanitization difficult to audit. It is rejected for V1.

### Add a local-first trace module at orchestration seams

The selected approach adds a small tracing interface used by the pipeline
orchestrator. The implementation writes local JSONL first and optionally
mirrors completed spans through an OTLP adapter. Existing module return values
provide counts, usage, error codes, and degradation facts. This concentrates
policy, preserves current interfaces, and remains testable without external
services.

## 3. Artifact authority

The three local artifacts have deliberately different authority:

| Artifact | Authority |
|---|---|
| `run_manifest.json` | Final run status, settings, aggregate counts, usage, degradations, and errors |
| `logs.jsonl` | Backward-compatible operational events and retrieval diagnostics |
| `traces.jsonl` | Trace topology, span lifecycle, correlation, duration, and safe per-operation attributes |

No consumer may infer run success from the root span when the manifest exists.
The manifest wins during disagreement. Trace validation reports disagreement as
`terminal_status_mismatch`.

`traces.jsonl` is not generated later from `logs.jsonl`: it is written during
execution and is the durable authority for trace history. OTLP/Phoenix is only
a queryable copy and may be incomplete.

Existing `logs.jsonl` fields and semantics remain backward compatible. V1 does
not duplicate every span into `logs.jsonl`; only exporter health warnings may
be added there.

## 4. Module design and seams

Add the following focused modules:

```text
paper_agent/observability/
  tracing_models.py       # strict local span/event contracts
  tracing.py              # small interface and local-first implementation
  openinference.py        # local attribute names -> OpenInference mapping
  otlp.py                 # optional OTel SDK adapter, lazy imports only
  trace_validation.py     # completeness and reconciliation metrics
```

The main interface is intentionally small:

```python
class TraceRecorder(Protocol):
    @contextmanager
    def span(self, spec: SpanSpec) -> Iterator[ActiveSpan]: ...
    def close(self) -> None: ...

class ActiveSpan(Protocol):
    @property
    def context(self) -> SpanContext: ...
    def set_attributes(self, values: Mapping[str, JsonValue]) -> None: ...
    def mark_degraded(self, *, code: str) -> None: ...
```

The context manager owns timing and exception-to-error conversion. Callers do
not construct IDs, serialize records, sanitize values, map OpenInference
attributes, or call exporters.

`RunRecorder.start(...)` accepts two new optional inputs:

- `correlation: RunCorrelation | None`
- `trace_factory: TraceFactory = LocalTraceRecorder.start`

It creates `traces.jsonl`, starts the pipeline root span, and exposes
`recorder.span(spec)`. `RunRecorder.complete()` and `RunRecorder.fail()` close
the root with the same intended status used for the manifest. This makes the
run lifecycle the single ownership seam while retaining `recorder_factory` as
the existing test seam.

`RunCorrelation` contains optional `experiment_id` and `case_id`, mandatory
`run_id`, and an optional valid W3C parent context. An evaluation runner passes
its case span context. A standalone CLI run has `paper_agent.pipeline.run` as
the trace root.

## 5. Span ownership

> **Superseded by section 0:** the table below records the earlier draft. Final
> V1 uses only `paper_agent.evaluation.case` and `paper_agent.pipeline.run`;
> the listed operations become allowlisted events on the applicable root span.

`run_pipeline` owns spans for operations it orchestrates. Domain modules remain
free of tracing imports.

| Span | Cardinality | Owner | Required attributes |
|---|---:|---|---|
| `paper_agent.pipeline.run` | one/run | `RunRecorder` | run/correlation IDs, safe config hashes, limit, `no_pdf` |
| `paper_agent.paper.search` | one/run | pipeline | provider, requested limit, result count |
| `paper_agent.document.acquire` | one/paper | pipeline | paper ID, requested source, actual source, fallback code |
| `paper_agent.document.chunk` | one/document | pipeline | paper ID, content hash, page/chunk/warning counts |
| `paper_agent.retrieval` | one/paper | pipeline | paper ID, requested/actual mode, candidate counts, top-k |
| `paper_agent.analysis` | one/attempted paper | pipeline | paper ID, model, attempts, token usage, supported finding count |
| `paper_agent.citation.validate_paper` | one/analyzed paper | pipeline | paper ID, sanitized/dropped counts |
| `paper_agent.synthesis` | one/run | pipeline | paper/evidence counts, model, attempts, token usage |
| `paper_agent.citation.validate_report` | one/run | pipeline | supported/rejected/sanitized claim counts |
| `paper_agent.report.render` | one/run | pipeline | output format and safe counts |
| `paper_agent.artifacts.publish` | one/run | pipeline | artifact names and publication status |

When the evaluation project is present, it owns
`paper_agent.evaluation.case`; the pipeline root is its child. Evaluation
metrics are sibling/descendant spans owned by the evaluation runner, not by the
production pipeline.

V1 records generation retries as aggregate attributes (`attempts`, usage, and
elapsed time) because `StructuredGeneration` and `GenerationFailureMetadata`
already expose these facts. A later provider-level adapter may add child
`LLM`/HTTP-attempt spans only when a second provider or attempt-level debugging
justifies that new seam.

Retrieval continues to emit its existing `RetrievalEvent`; the pipeline uses
that event to populate the active retrieval span and still writes the
backward-compatible `RunEvent`.

## 6. Local trace schema

Final schema `1.0` also includes strict `span_event` and `trace_seal` records,
plus standard OpenTelemetry Span Links on span start records. Sealed files
reject every later append.

`traces.jsonl` contains strict versioned lifecycle records. A start record is
written immediately so an interrupted operation remains visible; an end
record completes it.

```json
{
  "schema_version": "1.0",
  "record_type": "span_start",
  "timestamp": "2026-07-23T12:00:00Z",
  "trace_id": "32-lowercase-hex",
  "span_id": "16-lowercase-hex",
  "parent_span_id": null,
  "name": "paper_agent.pipeline.run",
  "kind": "INTERNAL",
  "run_id": "run-...",
  "experiment_id": null,
  "case_id": null,
  "attributes": {}
}
```

```json
{
  "schema_version": "1.0",
  "record_type": "span_end",
  "timestamp": "2026-07-23T12:00:03Z",
  "trace_id": "32-lowercase-hex",
  "span_id": "16-lowercase-hex",
  "status": "degraded",
  "code": "pdf_not_found",
  "duration_ms": 3000.0,
  "attributes": {}
}
```

Allowed local statuses are `ok`, `degraded`, and `error`. A missing end record
means `interrupted`; it is not rewritten on the next run. IDs follow W3C trace
format and are generated independently of filesystem names.

All writes reuse the append-one-JSON-object durability semantics already used
by `append_json_line`. The writer is process-local in V1. Same-file writes
from multiple processes are unsupported; future workers always receive
separate run directories.

## 7. OpenTelemetry/OpenInference mapping

The local contract is framework-neutral but maps deterministically:

- local `trace_id`, `span_id`, and `parent_span_id` map unchanged;
- `paper_agent.analysis` and `paper_agent.synthesis` map to OpenInference
  `LLM` spans;
- an embedding child span, when later instrumented, maps to `EMBEDDING`;
- retrieval maps to `RETRIEVER`;
- remaining orchestration spans map to `CHAIN`;
- `run_id`, `experiment_id`, `case_id`, `paper_id`, model, token, and document
  count attributes use semantic names defined centrally in
  `openinference.py`.

Resource attributes include `service.name=paper-agent`,
`service.version`, Python version, and an explicit environment value. Prompt
text, response text, evidence quotes, authorization data, endpoint query
strings, and full paper content are excluded.

OTel/OpenInference packages belong in an `observability` optional dependency
extra. Core modules do not import them. `otlp.py` imports them only when OTLP is
explicitly enabled. Enabling OTLP without the extra yields a safe configuration
error before the pipeline starts.

## 8. Failure and degradation semantics

Span state follows domain state:

- normal completion -> `ok`;
- permitted fallback, skipped per-paper analysis, retrieval fallback, or
  citation sanitization -> affected span `degraded`;
- an exception escaping an operation -> affected span `error`;
- a run containing any manifest degradation -> root `degraded`;
- terminal pipeline failure -> root `error`.

Explicit `--no-pdf` is not degradation, matching the current manifest
contract. A PDF failure followed by abstract fallback degrades only that
paper's acquisition span and ultimately the root.

OTLP initialization or export failure is **not** a research degradation and
does not alter `run_manifest.status`. The local trace writer records one
rate-limited `paper_agent.observability.export` error record and `logs.jsonl`
may receive a sanitized `otlp_export_failed` warning. Export is disabled for
the remainder of the run after a configured bounded failure threshold.

Local trace persistence failure is different: when tracing is enabled, it is
an integrity failure. The operation raises `TracePersistenceError`; the
pipeline attempts to finalize the manifest with
`trace_persistence_failed` and fails the run. Manifest finalization remains
best effort if the filesystem itself is unavailable.

The earlier ordering below is replaced by section 0.5. In particular, the
run-level trace is sealed and hashed before terminal manifest replacement.

The earlier ordering was:

1. finish all child spans;
2. append the root end record with intended terminal state;
3. atomically replace the terminal manifest;
4. flush/shutdown the optional exporter with a bounded timeout.

If step 3 fails, the manifest remains authoritative and reconciliation reports
the mismatch. Step 4 can never change the manifest.

## 9. Security policy

Every start/end record passes through `sanitize_event_data` before model
validation and persistence. In addition, each span name has an attribute
allowlist; arbitrary dictionaries from providers are never copied wholesale.

Persist safe identifiers, hashes, counts, ranks, durations, model names, retry
counts, token usage, stable error codes, and endpoint hostnames. Do not persist:

- API keys, credentials, authorization headers, cookies, or `.env` values;
- raw provider requests or responses;
- full prompts, generated responses, abstracts, PDF text, or evidence quotes;
- exception objects, stack traces, or arbitrary exception messages;
- full endpoint URLs with credentials, queries, or fragments.

Questions and prompt templates are represented by content hash, character
count, and version ID. Known runtime secrets are supplied to the sanitizer;
credential-like keys remain redacted even when a value is unknown.

## 10. Trace completeness

`trace_validation.py` reads sealed run/evaluation traces plus the manifest and
returns deterministic metrics. It distinguishes `fresh_child` from
`declared_reuse_link`, verifies seals and manifest hashes, and can rebuild
`trace-index.json`. The following per-file metrics remain applicable:

- `root_span_count` must equal one;
- `orphan_span_count` must equal zero;
- `duplicate_span_start_count` and `duplicate_span_end_count` must equal zero;
- `unfinished_span_count` must equal zero for terminal runs;
- `trace_id_consistency` must equal one;
- `correlation_coverage` must equal one for required IDs;
- `required_stage_coverage` must equal one for stages applicable to the run;
- `terminal_status_consistency` must equal one;
- `sensitive_value_findings` must equal zero.

Applicability is data-driven: an empty search has no per-paper spans;
`--no-pdf` does not require a PDF attempt; a failed search does not require
retrieval, analysis, or synthesis. The validator derives expectations from the
manifest, document records, and terminal failure stage rather than demanding
all nominal spans after early failure.

The evaluation project consumes these results as trace-quality metrics.
Pipeline success is never reclassified by a post-run completeness score.

## 11. Configuration and optional Phoenix use

Configuration is explicit and safe:

```text
TRACE_ENABLED=true
OTLP_EXPORT_ENABLED=false
OTLP_ENDPOINT=https://...
OTLP_EXPORT_TIMEOUT_SECONDS=3
```

Local tracing defaults on. OTLP defaults off. Endpoint validation follows the
same HTTPS/no-credentials/no-query policy as generation configuration.
Headers containing credentials are accepted only through secret settings and
never copied to safe settings, manifests, logs, or traces.

Phoenix is documented as one possible OTLP destination. MOMO Scholar does not
start, manage, import, or depend on Phoenix. Removing Phoenix loses only its
query UI; local artifacts remain complete.

## 12. Test strategy

All normal tests are offline and require no optional packages.

1. **Model tests:** strict schema, UTC timestamps, W3C IDs, Span Links,
   execution/scoring identity separation, status invariants, extra-field
   rejection, and correlation validation.
2. **Local writer tests:** start-before-operation, end-after-operation,
   interrupted span visibility, append failure, ordering, nesting, and
   no mutation of inputs.
3. **Security tests:** nested credential keys, known secret substrings, raw
   payload keys, malicious exception objects, prompts/responses, URLs, and
   serialized-file scanning.
4. **Pipeline tests:** normal, degraded, and failed executions produce one
   pipeline root with the required events, then seal and hash the run trace
   before terminal manifest publication.
5. **Exporter adapter tests:** absent optional dependency, mapping, timeout,
   bounded failures, shutdown, and proof that exporter failures do not alter
   the manifest.
6. **Completeness tests:** fresh-child correlation, declared reuse links,
   synthetic external parents, duplicate/unfinished records, seal/hash
   mismatch, forbidden post-seal append, missing required event, early failure
   applicability, and manifest/root mismatch.
7. **Compatibility tests:** existing manifest and `logs.jsonl` assertions
   remain unchanged.

A separate opt-in smoke test may send one synthetic trace to a local Phoenix
instance. It is never part of ordinary `pytest`.

## 13. Future Redis/worker evolution

The correlation and storage contracts are deliberately independent of process
execution. A later Web/worker phase can use:

```text
Web/API -> Redis queue -> worker -> per-run local/object artifacts
                              \-> OTLP -> Phoenix/other backend
```

Redis will own queueing, leases, cancellation, progress, rate limiting, and
short-lived coordination. It will not be the sole store for manifests,
traces, experiment results, or evidence. Workers receive immutable
`experiment_id`, `case_id`, `run_id`, and parent trace context in the job
envelope, then use the same `TraceRecorder` interface.

Durable multi-user metadata belongs in a future relational store and large
artifacts in object storage. No Redis abstraction is added in this phase.

## 14. Implementation boundaries and acceptance

Implementation should proceed in small tasks:

1. strict two-span trace, event, link, identity, and seal models;
2. sealed local writers for execution and scoring artifacts;
3. `RunRecorder` event, hash, and terminal-manifest integration;
4. cross-file completeness, security, and fresh/reuse validation;
5. optional OTel/OpenInference OTLP adapter preserving IDs and links;
6. documentation, trace-index rebuild, and opt-in Phoenix smoke.

The phase is complete when:

- every standalone execution has one sealed run trace;
- every scoring attempt has one independent sealed evaluation trace;
- fresh and reused executions use child context and Span Link respectively;
- existing manifest/log contracts and offline tests remain valid;
- normal, degraded, failed, and interrupted operations are distinguishable;
- trace completeness can be scored without a backend;
- persisted artifacts contain no known secret or prohibited raw content;
- absent/unavailable OTLP/Phoenix never prevents a pipeline result;
- enabled local trace persistence failure cannot be silently ignored;
- Redis is neither installed nor required.
