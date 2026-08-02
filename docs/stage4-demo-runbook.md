# Stage 4 demo runbook and release acceptance

This runbook covers the local-only Stage 4 Web MVP. The safe path is the packaged,
read-only `synthetic-demo-v1` artifact bundle served by the real same-origin
FastAPI/React assembly. It performs no provider, credential, benchmark, or
evaluation call and must always be described as synthetic.

## Safe local demo

Prerequisites: Python 3.10+ and Node.js 20+.

```powershell
python -m pip install -e .
Set-Location web
npm ci
npm run build
Set-Location ..
python -m paper_agent.web
```

Open `http://127.0.0.1:8000` and choose **Open offline demo**. Do not submit the
create-run form. The packaged demo is validated through the production artifact
reader and seeded into the local registry as `origin="bundled_demo"`; viewing it
does not execute the pipeline.

## 3–5 minute demo script

1. **0:00–0:30 — Scope.** Point to `Local research desk` and say the app is a
   single-user local MVP. Open the offline demo and call it synthetic, not research
   output or evaluation evidence.
2. **0:30–1:15 — Completion state.** Show `completed with degradation`, the
   terminal phase record, the abstract fallback, and the persistent demo warning.
3. **1:15–2:15 — Checked report.** Open the report, compare visible support labels
   with Evidence markers, then switch between checked and Markdown views.
4. **2:15–3:15 — Paper and Evidence.** Open a paper analysis, follow an Evidence
   link, and show the persisted quote, paper, chunk, score, source mode, and honest
   `Unknown section` / `Unknown page` labels where provenance is unavailable.
5. **3:15–4:00 — Portable artifacts.** Return to the run and show all eight
   allowlisted downloads: papers, documents, Evidence, analyses, report JSON,
   report Markdown, run manifest, and log. Repeat that these are fixture artifacts.
6. **4:00–5:00 — Boundary.** Explain that a real create-run invokes the production
   provider path and requires separate credential, network, and cost authorization.

## Focused offline acceptance

From the repository root:

```powershell
python -m pytest tests/web -q
Set-Location web
npm test
npm run contracts:check
npm run build
```

Then start `tests.web.fake_server:app` only for an explicit synthetic browser
smoke. Submit one fake run, observe the progress/terminal record, and open its
report, paper analysis, Evidence, and artifact links at desktop and 390 px widths.
The fake runner records zero provider operations. Do not use the default production
runner for this step.

## Fixed completion-state and Evidence matrix

| State / surface | Report | Paper / Evidence | Artifacts | User-facing rule |
|---|---:|---:|---:|---|
| `queued` / `running` | Not yet | Not yet | Only terminal-safe files | Poll and preserve last known state; connectivity loss never fabricates failure. |
| `completed` | Required | Required | Eight allowlisted files | Render checked claims and exact persisted provenance. |
| `completed_with_degradation` | Required | Required | Eight allowlisted files | Keep degradation and fallback warnings visible beside usable output. |
| `failed` | Absent | Absent | Manifest/log only when present | Show the safe issue code; never invent a substitute report. |
| `interrupted` | Absent | Absent | Existing safe files only | Registry terminal state; never rewrite or fabricate a pipeline manifest. |
| bundled offline demo | Required | Required | Eight immutable fixture files | Persistent synthetic warning; zero provider/pipeline execution at view time. |

The verified release facts, source-to-report architecture, engineering tradeoffs,
pending evaluation authorities, and final live action are maintained in
[Final delivery](final-delivery.md).
