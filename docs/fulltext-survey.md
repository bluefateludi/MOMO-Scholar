# Production full-text survey workflow

## Scope and configuration

The production path supports public, text-native arXiv PDFs only. It does not perform OCR, accept uploaded PDFs, or retrieve arbitrary websites. PDF download and page-aware extraction are the default. `--no-pdf` explicitly selects abstract-backed documents; it does not disable generation.

Copy `.env.example` to `.env` and set `DASHSCOPE_API_KEY=your-key-here`. Embeddings and generation share this single DashScope key. Defaults are `text-embedding-v4` for embeddings and exactly `qwen3.7-plus` for generation. Provider endpoints, timeouts, limits, and retrieval settings are listed in `.env.example`; never commit `.env`.

## Running and artifacts

```console
paper-agent run "hybrid retrieval for scientific literature review" --limit 3
paper-agent run "hybrid retrieval for scientific literature review" --limit 3 --no-pdf
```

Each timestamped directory below `outputs/` contains eight successful-run artifacts:

| Artifact | Meaning |
| --- | --- |
| `papers.json` | normalized arXiv paper metadata |
| `documents.json` | source, hash, page count, warnings, and fallback provenance |
| `evidence.json` | selected quotes with paper/chunk/page/section trace |
| `analyses.json` | citation-checked per-paper findings |
| `report.json` | checked cross-paper survey contract |
| `report.md` | formal human-readable report |
| `run_manifest.json` | settings (without secrets), counts, issues, timings, usage, and terminal state |
| `logs.jsonl` | structured run events and safe diagnostics |

Terminal states are `completed`, `completed_with_degradation`, and `failed`. The manifest is authoritative and is finalized last. Failed runs do not claim a `report.md`; safe intermediate files may remain, and the CLI points to the manifest and log when available.

## Failure and evidence semantics

Approved PDF download or parsing failures may fall back per paper to a usable abstract and record a fallback code, producing `completed_with_degradation`. A paper without usable PDF or abstract can be excluded only if enough checked analyses remain. Explicit abstract mode is intentional and is not itself degradation.

Retrieval is isolated per paper. In `auto` mode, a transient vector failure may degrade to lexical retrieval and is recorded; explicit `hybrid` failures and lexical/fusion/configuration failures are terminal. Generation authentication, configuration, request/model, and network failures are terminal. Exhausted timeout, rate-limit, server, or valid-envelope response failures may skip one paper only when the minimum analysis count remains; survey generation failure is always terminal.

Citation checking removes duplicate, unknown, foreign-paper, and foreign-run references. Only supported claims may appear in TL;DR and key findings. Sanitization is recorded as degradation; an insufficient supported report is terminal. Evidence IDs in the report resolve through `evidence.json` to paper, chunk, page, section, and quote. `run_manifest.json` records generation operations, HTTP attempts, latency, and available prompt/completion/total token usage; provider token counts are billing-oriented, while chunk token estimates are deterministic local estimates.

## Limits and known constraints

Safe defaults are a 30-second PDF timeout, 25,000,000-byte PDF limit, 200-page limit, six analysis evidence items per paper, 30 retrieval candidates, top eight results, and RRF constant 60. Parsing assumes extractable text and uses conservative reading order and section detection. Scanned documents, OCR, complex layouts, exhaustive figure/table/equation reconstruction, durable caches, and resumable runs are unsupported.

## Licensing

MOMO Scholar uses PyMuPDF/MuPDF under the AGPL path and the project is AGPL-3.0. Distributors must review and satisfy the corresponding-source and notice obligations; see `LICENSE`, `THIRD_PARTY_NOTICES.md`, and the linked upstream terms there. Other dependencies retain their own licenses. This documentation is engineering guidance, not legal advice.

## Verification

The normal suite is deterministic and offline:

```console
python -m pytest -q
python -m paper_agent.cli --help
python -m paper_agent.cli run --help
```

A manual live smoke is deliberately separate and requires a real local key:

```console
DASHSCOPE_API_KEY=your-key-here paper-agent run "hybrid retrieval for scientific literature review" --limit 3
```

Do not add this live command to automated tests. Inspect the manifest status, usage, issues, all eight artifacts, and evidence links after a live run.
