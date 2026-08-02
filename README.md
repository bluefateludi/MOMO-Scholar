# MOMO Scholar

MOMO Scholar is a local CLI that builds citation-traceable literature surveys from public, text-native arXiv papers. PDF-backed analysis is the default; OCR and non-arXiv sources are outside the current scope.

## Local Web demo (offline)

The bundled Web demo is immutable synthetic data. It needs no provider key and
makes no provider or research-network call.

```console
python -m pip install -e .
cd web
npm ci
npm run build
cd ..
python -m paper_agent.web
```

Open `http://127.0.0.1:8000`, choose **Open offline demo**, and keep the
`Synthetic offline demo` warning visible while reviewing the report, paper
analysis, Evidence, and eight artifact downloads. Do not submit the create-run
form unless a separately authorized live provider run is intended. See the
[Stage 4 demo runbook](docs/stage4-demo-runbook.md) for the 3–5 minute script and
[final delivery record](docs/final-delivery.md) for architecture, verified
metrics, and pending authorities.

## Install and configure

```console
python -m pip install -e .
copy .env.example .env
```

Set `DASHSCOPE_API_KEY=your-key-here` in `.env`. The same key powers DashScope embeddings and Qwen generation.

## Run

Default PDF workflow:

```console
paper-agent run "hybrid retrieval for scientific literature review" --limit 3
```

Explicit abstract-only workflow (generation still uses Qwen):

```console
paper-agent run "hybrid retrieval for scientific literature review" --limit 3 --no-pdf
```

Runs are written below `outputs/` unless `--output-dir` is supplied. See [the full-text survey guide](docs/fulltext-survey.md) for artifacts, terminal states, failure semantics, limits, licensing, and verification.

Local sealed traces are enabled by default. See
[Trace and Observability](docs/observability.md) for artifact authority,
fresh/reuse correlation, validation, security, and optional OTLP export.

MOMO Scholar is licensed under AGPL-3.0; see `LICENSE` and `THIRD_PARTY_NOTICES.md`.
