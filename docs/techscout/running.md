# Run modes and operator guide

The words Fast, Live, and Offline describe evidence/execution authority, not just a speed toggle. Do not use them interchangeably in a demo.

## Mode truth table

| User-facing path | Request/API value | Evidence and execution | Current outcome |
|---|---|---|---|
| Fast Demo | `fast` | Frozen synthetic source records and deterministic synthetic PoC responses pass through the real Harness, Skill policy, local stdio MCP transport, checkpoints, gate, artifacts, and Trace. No provider, external research network, or Docker is used. | Implemented. A `completed` result proves the fixture vertical slice passed, not that a real candidate was verified. |
| Verified (Live intent) | `verified` | The current Web executor does not connect live providers or the real Docker runner. | Explicitly limited with `live_execution_unavailable`; never describe this as a completed Live run. |
| Offline fixture/replay | no new research run | Bundled immutable or frontend mock data; the lifecycle may be simulated. | Implemented for UI review and deterministic acceptance only. |
| Live | no honest default Web path yet | Intended to refresh missing/stale official/GitHub evidence through bounded adapters and run reviewed recipes in Docker. | Future integration. The adapters/runners existing in source do not make the end-to-end path implemented. |

## Start with the TechScout CLI

```console
python -m pip install -e .
cd web
npm ci
npm run build
cd ..
techscout serve
```

Then open `http://127.0.0.1:8000`. The v2 API is under `/api/v2/runs`; the UI submits `fast` or `verified`. The default server is single-process and loopback-only. Binding beyond loopback requires the explicit CLI flag and is not recommended because authentication is not implemented.

`techscout --help` and `techscout serve --help` show the current mode boundary. A non-loopback bind is rejected unless the operator explicitly adds `--allow-network`:

```console
techscout serve --host 0.0.0.0 --allow-network
```

That opt-in exposes an unauthenticated local product and must be protected by the operator's network boundary. The compatibility command `python -m paper_agent.web` remains available. The installed `paper-agent` console script still addresses the historical Scholar workflow.

## Start with Docker Compose

Prerequisites: Docker Engine with Docker Compose v2 and a local checkout.

```console
docker compose up --build
```

Then open `http://127.0.0.1:8000`. Compose binds the published host port to loopback, runs the application with a read-only root filesystem and dropped capabilities, and stores Web state/artifacts in the `techscout-data` named volume. Stop it with `docker compose down`; add `--volumes` only when you intentionally want to delete that local run data.

The Web container does not receive `/var/run/docker.sock`. Compose starts only the existing Web product: Fast Demo remains frozen and synthetic, while a `verified` request still terminates as `completed_with_limitations` with `live_execution_unavailable`. The real sandbox runner and reviewed recipes remain a separate, explicit opt-in boundary described below.

## Optional sandbox smoke

The reviewed Docker image and runner are separate from the Fast Demo. The full sandbox image includes the closed Chroma and Qdrant Local recipes. Its installation network must be a dedicated externally enforced egress network restricted to the approved package hosts; it is not created automatically.

For the repository's opt-in Docker smoke:

```powershell
$env:TECHSCOUT_DOCKER_SMOKE = "1"
python -m pytest tests/techscout/test_sandbox_docker_smoke.py
```

This verifies the sandbox path when local Docker prerequisites are deliberately provided. It does not turn the Web Fast Demo into a Docker-backed run.

## Interpreting a run

Check these fields before discussing the result:

- `synthetic` / fixture notice: if true, do not present claims as live research.
- `mode`: `fast` currently means the frozen harness-backed demo; `verified` currently means an attempted boundary that returns limited.
- terminal status: distinguish `completed`, `completed_with_limitations`, and `failed`.
- verdict: `recommended` versus `no_safe_winner`.
- candidate support level: only `v1_supported` candidates may be recommendation-eligible.
- PoC status and recipe ID: `research_only` is not a failed benchmark.
- issues/limitations: cache degradation, unavailable live execution, missing recipe, or exhausted recovery must remain visible.
- Trace checkpoint/recovery links: confirm only the failed stage was repeated.

## Demo wording

Safe wording: “This Fast Demo exercises the actual orchestration, policy, MCP, checkpoint, validation, artifact, and Trace seams with frozen synthetic inputs.”

Unsafe wording: “This is a live comparison,” “Docker verified these candidates,” or “the final benchmark passed” unless the corresponding external authority is later supplied and verified.
