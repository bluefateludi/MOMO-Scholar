# TechScout v0.1.0 real Verified acceptance — 2026-08-16

## Authority and conclusion

- Baseline: `origin/master@fb9751bf0da963e1695c82117f11a4b274503c33` (`Phase 2D: connect verified Web execution (#98)`).
- Acceptance branch: `codex/techscout-real-verified-acceptance` in a dedicated Codex worktree.
- Real Verified success: **not established**. This machine did not have a Tavily credential, a running Docker daemon, or a dedicated externally enforced install-egress network.
- Honest degraded result: **established after the scoped fix below**. A cold run and a cache-fallback run both reached `completed_with_limitations` with `no_safe_winner`, no recommendation, and no verified PoC claim inside the 300-second boundary.
- This record is one environment acceptance, not evidence of product quality, component performance, or benchmark results.

No secret value was printed, copied into an artifact, or committed. Credential checks below report presence only.

## Preflight

| Check | Command | Result |
|---|---|---|
| Git baseline | `git switch -c codex/techscout-real-verified-acceptance origin/master` | Branch created at `fb9751bf` with a clean starting tree. |
| Effective Verified settings | `python -c "from paper_agent.config import load_settings; ..."` (boolean presence projection only) | `tavily_api_key_present=False`, `github_token_present=False`, `install_network_configured=False`, `egress_allowlist_enforced=False`. `.env` and `.env.local` were absent. |
| Docker service | `Get-Service -Name com.docker.service` | Installed but `Stopped` (`Manual`). |
| Docker daemon | `docker version --format '{{.Server.Version}}'` and `docker network ls --format '{{.Name}}'` | Failed to open `//./pipe/docker_engine`; no daemon or network could be inspected. Docker also warned that the user Docker config was inaccessible. |
| Host dependency network | `python -m pip install -e ".[dev]"` using the isolated Codex runtime | Succeeded through the configured Aliyun PyPI mirror. This proves host package access only; it is not the required dedicated Docker egress allowlist. |
| Runtimes | `python --version; node --version; npm --version` | Host Python `3.12.3`, Node `v22.19.0`, npm `10.9.3`; verification used the isolated Codex Python `3.12.13`. The submitted Hero environment remained Python `3.11` in the reviewed container contract. |

## Real default-composition runs

The request compared Chroma, Qdrant Local, and pgvector for a Python 3.11 single-node local RAG service with collection, upsert/query, metadata-filter, and persistence-reopen constraints. Runs used `create_app`'s default Verified composition rather than injected test fakes.

### Discovery run before the fix

- Run: `db05a1e6-8634-42a5-857e-f360de288edf`.
- Terminal state: safe `failed` in `5.562` seconds; `synthetic=false`.
- Trace observed one real HTTPS/GitHub acquisition with `cache_state=live`, then the research stage failed as `report_schema_invalid` before Docker execution.
- Root cause: normalized Qdrant and pgvector GitHub content produced 90 and 135 research evidence records respectively, but `CandidateContextData.evidence` accepts at most 50. The unbounded research-to-context handoff raised a Pydantic validation error instead of reaching the intended limited result.
- The failed run still published a sealed terminal Trace and failure artifacts, but `/report` correctly returned `report_unavailable`; it is not a successful acceptance artifact.

### Scoped fix

`LiveEvidenceResearchService.research` now preserves the complete bounded `CandidateResearchResult` while passing only the first 50 deterministic evidence records into `CandidateContextData`. A public-service regression test constructs more than 50 normalized evidence records and verifies that research remains complete while context delivery remains bounded.

### Cold post-fix run

- Run: `ffc398f8-28bf-4ea4-9e46-8a8bb90e53d9`.
- Wall clock: `4.453` seconds.
- Result: `completed_with_limitations`, `no_safe_winner`, no recommendation, `synthetic=false`.
- Provenance: Chroma, Qdrant Local, and pgvector were all `unavailable` in this fresh cache root.
- PoCs: all three were `research_only`, `verified=false`. Chroma and Qdrant retained their reviewed recipe IDs; pgvector had no recipe ID. The run reported `tool_unavailable` and did not claim Docker execution.
- Recovery: not attempted; `attempts_used=0`.
- Terminal Trace: sealed and reported `completed_with_limitations`.

Selected durable artifact hashes:

| Artifact | SHA-256 |
|---|---|
| `decision-report.json` | `34b42b8c2291e5c34703538ff41a126af8f3ada2f0ebe6d8c5e26d4d4cf0e6ce` |
| `run_manifest.json` | `bd8f0ea3fa67a818b62c220c5e691fc82b42ccdf27b8f660fd1aea2c36110a7e` |
| `traces.jsonl` | `6e0adfd0b206adc9448d98ab5aa9017f587829c580b0d011f4a69484b071a8eb` |
| `traces-manifest.json` | `18904956593567778953be23235ca2fca2e80493c8a546d311bc09ecde002716` |
| `poc-results.json` | `d28201078f2cbbea9cf5865db8b44aa0b41600c0bcea45c7961a2d72ba60df8b` |
| `web-projection.json` | `7768a4789248477b6dc60618e1481d24d28334869c5a1660c2620d3bc5b43bd6` |

The local run directory is under gitignored `outputs/acceptance-2026-08-16-postfix/`; the hashes above make this record self-contained without committing generated run data.

### Warm-cache post-fix run

- Run: `786c1e1b-ee7b-4594-8ae9-764035a0ba6a`.
- Wall clock: `1.672` seconds.
- Result: `completed_with_limitations`, `no_safe_winner`, no recommendation.
- Provenance: Chroma=`cache`, Qdrant Local=`cache`, pgvector=`unavailable` in both API evidence and Trace tool states.
- PoCs: Chroma/Qdrant/pgvector all `research_only`, `verified=false`; pgvector remained recipe-less.
- This proves visible cache fallback and unavailable provenance after the fix. A fresh post-fix `live` completion was not observed, so live success remains unverified.

## Docker PoC blocker

The opt-in smoke was deliberately enabled rather than left skipped:

```powershell
$env:TECHSCOUT_DOCKER_SMOKE = "1"
python -m pytest tests/techscout/test_sandbox_docker_smoke.py -q
```

Result: `2 failed` because both reviewed recipes returned `PocStatus.FAILED` with `FailureCode.TOOL_UNAVAILABLE`; neither returned `PASSED`. This agrees with the stopped daemon preflight. It is blocker evidence, not a product regression claim.

## Offline and build verification

| Command | Result |
|---|---|
| `python -m pytest tests/techscout/research/test_service.py -q` before implementation | Expected RED: large source failed at 63 evidence records; `10 passed, 1 failed`. |
| Same focused command after implementation | `11 passed`. |
| `python -m pytest tests/web/test_techscout_verified_integration.py -q` | `8 passed`; covers live, cache, unavailable/Docker limitation, pgvector research-only, one-stage recovery, sanitized Trace, Fast/Verified isolation, and the 300-second budget. |
| Focused research/context/PoC/sandbox suite with Docker smoke opt-out | `42 passed, 2 skipped`; the two skips are the explicit Docker smoke cases. |
| Focused Web/API/config/Compose suite | `85 passed`. |
| `python -m pytest -q` | `1513 passed, 3 skipped` in `93.11s`. |
| `npm test` | `23 passed` across 3 Vitest files. |
| `npm run contracts:check` | Passed. |
| `npm run build` | Passed; production Vite build completed. |
| `python -m ruff check .` | Passed. |
| `git diff --check` | Passed. |

The actual terminal runs completed in 1.672–5.562 seconds. Together with the deterministic deadline integration test, this verifies terminalization behavior in this environment; it is not a latency benchmark.

## Remaining unverified items and reproduction steps

Real Verified success, a real Chroma PoC pass, and a real Qdrant Local PoC pass remain unverified. To rerun without changing product authority:

1. Supply `TAVILY_API_KEY` through the local process environment or untracked `.env`; never commit it. `GITHUB_TOKEN` is optional for authenticated GitHub capacity.
2. Start Docker Engine and require `docker version` to return a server version.
3. Provision a dedicated Docker network whose external gateway/firewall permits only `pypi.org` and `files.pythonhosted.org`. A normal bridge network is insufficient.
4. Set `TECHSCOUT_DOCKER_INSTALL_NETWORK` to that network name and `TECHSCOUT_DOCKER_EGRESS_ALLOWLIST_ENFORCED=true`.
5. Build the reviewed image: `docker build --network <controlled-network> -t momo-techscout-sandbox:wave1 docker/sandbox`.
6. Run the opt-in smoke above and require both cases to pass before submitting the Web Verified Hero Case.
7. Submit the same three-candidate request, then verify: `synthetic=false`; explicit `live`/`cache`/`unavailable` per candidate; Chroma and Qdrant `passed` with `verified=true`; pgvector `research_only` with `verified=false`; a non-empty report and sealed Trace/artifact manifests; and a terminal state before 300 seconds.

Do not turn that single run into a throughput, quality, durability, cost, or production-readiness claim.
