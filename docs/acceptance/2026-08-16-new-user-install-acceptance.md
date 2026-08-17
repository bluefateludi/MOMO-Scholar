# New-user source installation acceptance — 2026-08-16

## Scope and authority

- Baseline: `fb9751bf0da963e1695c82117f11a4b274503c33` (`origin/master`, PR #98 merge).
- Host covered: Windows with PowerShell, Python 3.12.3, Node 22.19.0, npm 10.9.3, Docker CLI 28.3.2, and Docker Compose 2.39.1.
- Source boundary: a clean `git archive` export with no `.git`, local `.env`, `node_modules`, Python environment, generated Web build, outputs, or untracked workspace files.
- Product boundary: the synthetic Fast Demo only. No provider credential, live research, or real Verified Hero Case is claimed here.
- Not covered: macOS, Linux, other supported Python/Node versions, and a running Docker daemon.

## Commands and results

| Path | Command | Result |
|---|---|---|
| Isolated Python install | `python -m venv .venv`, activate it, then `python -m pip install -e .` | Passed from the clean source export; `paper-agent==0.1.0` and its declared runtime dependencies installed without repository-external source files. |
| Frontend dependencies | `cd web` then `npm ci` | Passed; 290 packages installed from the lockfile. |
| Generated contracts | `npm run contracts:check` with the source venv active | Passed. Without venv activation, the npm script used an unrelated system Python and failed with `ModuleNotFoundError`; the quick start now makes activation explicit. |
| Production frontend | `npm run build` | Passed with Vite 7.1.12: 63 modules transformed and production assets emitted. The supported Node range is now explicit in documentation and package metadata. |
| Local server | `techscout serve --port 8765 --state-root .acceptance/state --output-root .acceptance/outputs` | Passed on loopback; `/` returned HTTP 200 and served the React root. |
| Fast Demo API | `POST /api/v2/runs` with `mode=fast`, then poll `GET /api/v2/runs/{id}` | Passed without a provider key or Docker daemon. Run `eb085609-5b49-4ee6-9aac-5381398a0f5a` terminalized as `completed` within the 120-second bound and remained explicitly `synthetic=true`. This run ID is local acceptance evidence, not a product metric. |
| Report and projections | `GET` report, candidates, evidence, and Trace endpoints | Passed: `recommended` synthetic report, 3 candidates, 6 evidence projections, and 22 Trace projections. |
| Durable artifacts | Inspect the run output and verify `traces.jsonl` with `verify_sealed_jsonl` | Passed: report, evidence, PoC, manifest, checkpoint, projection, and Trace artifacts were present; the 37-record Trace was sealed and verified. |
| Restart persistence | Stop the server, restart with the same state/output roots, then refetch the run and report | Passed: the run remained `completed`, `synthetic=true`, with its synthetic report available after restart. |
| Compose schema | `docker compose config` | Passed; the resolved service binds `127.0.0.1:8000`, uses the declared read-only/capability restrictions, and persists `/data` in the named volume. |
| Compose build/start | `docker compose up --build --detach` | Not executed to completion: both sandboxed and unsandboxed attempts reached the same exact blocker, a missing Docker Desktop Linux engine named pipe. No image build or container runtime success is claimed. |

## Findings

1. New users using an isolated Python environment need to activate it before repository npm scripts and `techscout`; otherwise different Python interpreters can be selected. The quick start now shows this prerequisite.
2. Vite 7's Node floor was implicit. The repository now declares `^20.19.0 || >=22.12.0` in `web/package.json` and documents it.
3. Docker Compose syntax and security projection were verified, but the image build, container start, HTTP path, and named-volume restart behavior still require a host with a running Linux Docker engine.

The acceptance above is a single installation-path check, not a performance, reliability, compatibility-matrix, or product-effect measurement.
