# Contributing to MOMO TechScout

Thanks for helping improve TechScout. Contributions should preserve its central promise: unsupported evidence or execution must become a visible limitation, never a fabricated recommendation.

## Before opening a change

- Use a GitHub issue for bugs and scoped feature proposals. Do not disclose vulnerabilities in a public issue; follow [SECURITY.md](SECURITY.md).
- Keep changes focused. Avoid renaming the historical `paper_agent` package unless a separately approved migration requires it.
- Read the [mode boundaries](docs/techscout/running.md), [support and safety contract](docs/techscout/support-and-safety.md), and relevant plan or decision record.
- Discuss changes that add a candidate family, trusted recipe, network destination, secret, host mount, remote MCP server, or write-capable integration before implementation.

## Development setup

Supported baselines are Python 3.10+, Node 20 LTS, and—only for Docker work—Docker Engine with BuildKit and Compose v2.

```console
python -m pip install -e ".[dev]"
cd web
npm ci --ignore-scripts
cd ..
```

Normal Python and Web tests are deterministic and must not need provider credentials or live network calls. Docker recipe installation and the opt-in sandbox smoke are separate, controlled workflows.

## Make and verify a change

1. Branch from current `master` with a descriptive branch name.
2. Add or update a focused failing test before changing behavior.
3. Implement the smallest scoped change and preserve unrelated work.
4. Run the focused test, then the relevant broader checks.
5. Review the diff for secrets, generated outputs, stale product names, unsupported claims, and accidental authority changes.
6. Open a Draft pull request with the supplied template and link its issue or specification.

Common checks:

```console
python -m ruff check .
python -m pytest
python -m pip wheel --no-build-isolation --no-deps --wheel-dir dist .
cd web
npm run contracts:check
npm test
npm run build
```

Run only the relevant subset while iterating, but state exactly what was and was not verified in the pull request. Do not claim provider, Compose, browser, Docker, or Verified success unless that exact boundary was exercised and recorded.

## Documentation and product claims

- Always label Fast as synthetic. A Fast `completed` result is fixture acceptance only.
- Describe Verified as implemented only for the bounded Hero Case and dependent on provider/cache, Docker, and an externally enforced install network.
- Keep pgvector and unknown candidates research-only until a reviewed fixture and decision promote them.
- Do not convert synthetic evaluation diagnostics into product-effect or resume metrics.
- Do not add a screenshot or GIF as evidence unless it is reproducible, carries the synthetic/live label in-frame, and records its source commit and capture steps.
- Update README, operator guidance, templates, examples, and generated API contracts when a public contract changes.

## Security and data hygiene

Never commit `.env`, tokens, provider bodies, private evaluation inputs, local caches, run outputs, or credentials in logs and fixtures. Sandbox changes must retain explicit argv, closed recipes, no test-stage network, bounded resources/output/time, and default-deny behavior.

By contributing, you agree that your contribution is licensed under the repository's [AGPL-3.0 license](LICENSE).
