# Hybrid retrieval operations

MOMO Scholar supports three retrieval modes. `RETRIEVAL_MODE` defaults to
`auto`.

| Mode | Behavior |
|---|---|
| `auto` | Uses lexical retrieval when no non-blank DashScope API key is configured. With a configured key, it attempts hybrid lexical and vector retrieval. |
| `lexical` | Uses the deterministic offline lexical retriever and does not initialize the vector path. |
| `hybrid` | Requires vector configuration and combines lexical and vector candidates with Reciprocal Rank Fusion (RRF). |

Configuration is read from the current working directory's `.env` file, with
process environment variables taking precedence.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DASHSCOPE_API_KEY` | none | DashScope credential used by the embedding client. Keep it outside source control and logs. |
| `BAILIAN_REGION` | `beijing` | Bailian endpoint region. Currently only `beijing` is supported. |
| `BAILIAN_EMBEDDING_MODEL` | `text-embedding-v4` | Embedding model identity used by the embedder and vector store. |
| `RETRIEVAL_MODE` | `auto` | Requested mode: `auto`, `lexical`, or `hybrid`. |
| `RETRIEVAL_CANDIDATE_K` | `30` | Maximum candidates requested from each active source before fusion. |
| `RETRIEVAL_TOP_K` | `8` | Maximum Evidence items returned after retrieval or fusion. |
| `RETRIEVAL_RRF_K` | `60` | Positive RRF rank constant used in hybrid mode. |

All three `K` settings must be positive integers. If candidate K is smaller
than Top K, the application returns only the candidates that are available; it
does not rewrite either setting.

On a vector-enabled path, a `BAILIAN_REGION` value other than `beijing` fails
configuration without lexical fallback.

### Offline lexical example

This example deliberately omits `DASHSCOPE_API_KEY`:

```env
RETRIEVAL_MODE=lexical
RETRIEVAL_CANDIDATE_K=30
RETRIEVAL_TOP_K=8
RETRIEVAL_RRF_K=60
```

`RETRIEVAL_MODE=auto` with no `DASHSCOPE_API_KEY` also selects this lexical
path.

### Configured hybrid example

Set the real credential in the process environment or another local secret
mechanism. The placeholder below is the only credential value shown in this
guide:

```env
DASHSCOPE_API_KEY=<set-in-shell>
BAILIAN_REGION=beijing
BAILIAN_EMBEDDING_MODEL=text-embedding-v4
RETRIEVAL_MODE=hybrid
RETRIEVAL_CANDIDATE_K=30
RETRIEVAL_TOP_K=8
RETRIEVAL_RRF_K=60
```

Do not commit a real key. Configuration only establishes that a non-blank key
is present; authentication is checked by the provider when a request is made.
`<set-in-shell>` is a documentation placeholder, not a literal credential.

## Failure and fallback behavior

In `auto` mode, only vector availability failures may degrade a hybrid attempt
to lexical retrieval:

- embedding timeout;
- network failure;
- provider rate limiting;
- provider server failure.

The terminal event identifies these fallbacks with a stable degradation code:
`embedding_timeout`, `vector_network_unavailable`, `vector_rate_limited`, or
`vector_server_unavailable`.

Authentication failures, request or configuration errors, malformed provider
responses, response-shape errors, dimension or model mismatches, invalid
metadata, and all other contract or programming failures are not degraded.
They fail the run. Forced `hybrid` mode fails on every vector failure, including
availability failures.

Empty chunks are a successful empty retrieval in every requested mode. The
application reports actual mode `lexical`, returns no Evidence, and does not
validate, initialize, index, or query vector configuration.

## Retrieval terminal events

Each pipeline retrieval attempt appends exactly one sanitized terminal event to
`logs.jsonl`, whether retrieval succeeds or fails. Events contain no API key,
query or chunk text, embedding, exception message, or provider response body.

Important fields are:

- `status`: `ok` or `error`.
- `requested_mode`: the configured `auto`, `lexical`, or `hybrid` mode.
- `actual_mode`: the selected `lexical` or `hybrid` path for the terminal
  event. On validation failures, this is the planned path even though no source
  ran. It is `null` for an assembly failure before service creation.
- `lexical_candidate_count` and `vector_candidate_count`: source candidates
  after each source's candidate-K truncation and before cross-source
  deduplication.
- `fused_candidate_count`: unique candidates after merging by `chunk_id` and
  before Top-K truncation.
- `returned_evidence_count`: final Evidence count after Top-K truncation.
- `vector_attempted`: whether vector indexing or querying was attempted.
- `degraded`: whether `auto` fell back from a vector attempt to lexical.
- `degradation_code`: the stable availability code for that fallback, otherwise
  `null`.
- `failure_stage`: on errors, the stage that failed: `validation`, `assembly`,
  `lexical`, `vector_index`, `vector_query`, `fusion`, or
  `evidence_conversion`.
- `error_code`: on errors, a sanitized stable category rather than exception
  text.

Successful events serialize `failure_stage` and `error_code` as `null`.
Error events retain the counts known when the failure occurred; stages that
have not started remain zero.

## Current limits

The standard pipeline constructs a new retrieval service and
`InMemoryVectorStore` for each run. Every non-empty vector-enabled run therefore
embeds and indexes its chunks again; no index is persisted between runs.

This stage does not provide reranking, a persistent vector database, source
weight or fusion-weight tuning, retry loops, or CLI flags for selecting the
retrieval mode. Configure the mode through the environment or `.env`.
