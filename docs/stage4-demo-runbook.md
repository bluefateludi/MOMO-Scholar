# Stage 4 demo runbook and release acceptance

This runbook covers the local-only Stage 4 Web MVP. The safe demo path uses the
bundled frontend contract fixture. It makes no provider, credential, benchmark,
or evaluation call and must always be described as synthetic.

## Safe local demo

Prerequisites: Python 3.10 or newer and Node.js 20 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Set-Location web
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. Do not set `VITE_API_MODE=live` for the synthetic
demo. Confirm the top banner says `Contract fixture mode`, then open `Open offline
demo`. The run, report, paper, Evidence, Markdown, and download areas must retain
the `Synthetic offline demo` warning.

Recommended interview path:

1. Open the synthetic run and point out `completed with degradation`.
2. Open the checked report and compare support labels with Evidence links.
3. Switch to Markdown and confirm persisted Evidence markers resolve.
4. Open the abstract-backed paper and its Evidence provenance.
5. Show unknown page/section labels and the explicit fallback code.
6. Show all eight download links and repeat that they contain fixture data.

Never describe fixture claims as research output, evaluation evidence, provider
results, or production-quality metrics. Do not add provider credentials for this
demo.

## Verification

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/web -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q paper_agent tests

Set-Location web
npm test
npm run build
```

The backend can be started read-only for API/OpenAPI inspection with:

```powershell
.\.venv\Scripts\python.exe -m uvicorn paper_agent.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

This is not currently the synthetic demo path. Do not submit a run to that server
during offline verification: the default executor is the production pipeline.
The supported fake runner is injected by the backend test harness.

## Known limitations on `origin/master@ae70b48`

- Live frontend/backend integration is incomplete. The backend does not implement
  `GET /api/v1/runs`, `GET /api/v1/runs/{id}/papers`, or
  `GET /api/v1/runs/{id}/papers/{paper_id}/analysis`, although the frontend calls
  all three.
- The backend does not register or validate a bundled synthetic artifact row. The
  current demo is an in-memory frontend contract fixture, so it does not yet prove
  the frozen bundled-demo artifact-reader contract.
- There is no same-origin production host for the built frontend and no verified
  Content-Security-Policy delivery path.
- Backend coverage does not yet include a complete degraded artifact run or every
  required demo validation case. Frontend coverage does not independently exercise
  every empty/interrupted/reconnect timing boundary.
- The Vite page requests a missing `favicon.ico`, producing one harmless console
  404 during browser smoke.
- A cold Python install can be slow because the PyMuPDF wheel is large. Let the
  install finish rather than falling back to an unverified global environment.

## Acceptance matrix

| Area | Result | Evidence / remaining work |
|---|---|---|
| Clean Python and Node install | Pass | Fresh venv editable dev install and `npm ci` completed. |
| Backend focused tests | Pass | `tests/web`: 11 passed. |
| Backend full regression | Pass after packaging fix | 1,324 passed and 1 skipped; the sole initial clean-venv wheel failure was fixed by declaring `setuptools` in the dev extra. |
| Frontend tests and production build | Pass | 9 tests passed; TypeScript checks and Vite build completed. |
| Synthetic labeling / no provider use | Pass for fixture UI | Persistent fixture/demo warnings; no provider or network execution was invoked. |
| Successful fake run and Evidence | Pass | Fake backend run published a checked report; exact quote, chunk, and source resolved. |
| Degraded display | Pass for fixture UI | Persistent degradation warning and fallback provenance verified. |
| Failed / provider-offline display | Pass in deterministic tests | Safe `provider_configuration_missing` presentation; raw exception/secret canary absent. |
| Interrupted and empty states | Partial | Backend restart interruption is tested; UI branches exist, but complete browser coverage is pending. |
| Eight artifact downloads | Pass with fake backend | All allowlisted names returned attachment responses with expected content types. |
| Markdown safety | Pass | Browser DOM contained no injected script or raw script text. |
| Path and secret safety | Pass for covered cases | Traversal/private names denied; secret canary absent from API and downloads. |
| Desktop and narrow-screen UI | Pass for fixture UI | 1440 px and 390 px Chromium smoke completed; no narrow-screen horizontal overflow. |
| Live-mode end-to-end flow | Blocked | Missing list, papers, and analysis backend routes. |
| Backend bundled demo | Blocked | No immutable validated bundle or demo registry row. |
| Same-origin production security headers | Blocked | Built UI is not served by the backend; CSP path is absent. |

## Re-run after integration lands

Repeat the full commands above, then run one offline fake-executor browser flow in
`VITE_API_MODE=live`: list runs, submit, observe queued/running progress, open both
successful statuses, failed and interrupted runs, read report/paper/Evidence, and
download all eight artifacts. Restart during a blocking fake run to verify
reconciliation. Finally verify the validated backend demo row, same-origin built
UI, CSP/frame protections, encoded opaque IDs, connection-loss recovery, and both
desktop and 390 px layouts. Real-provider and evaluation runs remain out of scope.
