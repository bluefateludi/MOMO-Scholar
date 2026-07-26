# Trace and Observability

MOMO Scholar writes schema 1.0 JSONL traces locally by default. The only
span names are paper_agent.pipeline.run and paper_agent.evaluation.case;
Pipeline stages and Evaluation metrics are events on those spans.

## Artifact authority

- run_manifest.json is the Pipeline terminal authority. A root span with an
  ok status does not imply success when no terminal manifest exists.
- traces.jsonl belongs to one Pipeline execution_id.
- evaluation-traces.jsonl belongs to one Evaluation scoring_attempt_id.
- logs.jsonl remains the backward-compatible operational warning log.
- trace-index.json is a rebuildable projection, never authoritative.

Every trace ends with trace_seal. Its pre_seal_sha256 covers the exact bytes
before the seal; run_manifest.json.trace_sha256 covers the complete sealed
file. Sealed files cannot be appended.

## Correlation

Fresh scoring makes paper_agent.evaluation.case the parent of a new
paper_agent.pipeline.run through W3C trace context. Recovery scoring never
reparents an old execution: the new Evaluation span carries a standard OTel
Span Link to the sealed historical Pipeline root and records
reused_execution_id.

Pipeline finalization order is root end, local trace seal and flush, complete
file hash, atomic terminal manifest replacement, then optional exporter
flush. Export failure can add only the sanitized otlp_export_failed log
warning and cannot change the sealed trace or terminal manifest.

## Configuration

Local traces are enabled by default. TRACE_ENABLED=false is an emergency and
test opt-out; the manifest records the disabled state and contains null trace
metadata.

Optional OTLP export requires:

~~~dotenv
OTLP_ENABLED=true
OTLP_ENDPOINT=https://collector.example.test/v1/traces
OTLP_TIMEOUT_SECONDS=5
OTLP_FAILURE_THRESHOLD=3
OTLP_HEADERS_JSON={"Authorization":"Bearer secret"}
~~~

Install the optional dependencies with:

~~~console
python -m pip install -e ".[observability]"
~~~

The endpoint must use HTTPS and cannot contain credentials, query parameters,
or fragments. Header values are secret configuration and never enter safe
settings, manifests, logs, or traces. OpenTelemetry imports remain lazy, so
local tracing works without the optional extra.

Use validate_pipeline_trace, validate_trace_pair, and rebuild_trace_index for
local integrity checks. The Evaluation project owns the final 60-case
integration acceptance.
