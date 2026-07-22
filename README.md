# MOMO Scholar

MOMO Scholar is a local CLI that builds citation-traceable literature surveys from public, text-native arXiv papers. PDF-backed analysis is the default; OCR and non-arXiv sources are outside the current scope.

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

MOMO Scholar is licensed under AGPL-3.0; see `LICENSE` and `THIRD_PARTY_NOTICES.md`.
