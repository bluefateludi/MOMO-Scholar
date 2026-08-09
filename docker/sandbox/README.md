# TechScout Wave 1 sandbox

Build the reviewed image from the repository root:

```text
docker build --network techscout-pypi-egress -t momo-techscout-sandbox:wave1 docker/sandbox
```

The image contains only the reviewed Chroma and Qdrant Local smoke scripts and
their pinned V1 packages. Runtime test stages use Docker network `none`; the
Python runner also applies CPU, memory, PID, disk, timeout, read-only-root,
capability, work-directory, and mount restrictions. `pgvector` intentionally has
no recipe in Wave 1 and remains research-only.

CI builds only the common runtime and its dependency-free probe. This keeps the
Docker gate bounded without downloading the Chroma/Qdrant package matrix:

```text
docker build --network none --target ci-smoke -t momo-techscout-sandbox:ci docker/sandbox
```

The CI probe is run with no network or forwarded secrets, explicit CPU, memory,
PID, read-only-root, and timeout boundaries. The default Dockerfile target
remains the complete reviewed recipe image used by the optional local smoke.

`techscout-pypi-egress` is not a built-in Docker bridge. It must be a dedicated
network whose external gateway/firewall allowlists only `pypi.org` and
`files.pythonhosted.org`. Runtime installation is denied unless callers provide
the same enforced destination allowlist through `InstallNetworkPolicy`.

The optional local smoke is opt-in because ordinary tests do not require Docker:

```text
$env:TECHSCOUT_DOCKER_SMOKE = "1"
python -m pytest tests/techscout/test_sandbox_docker_smoke.py
```
