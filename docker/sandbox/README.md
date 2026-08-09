# TechScout Wave 1 sandbox

Build the reviewed image from the repository root:

```text
docker build -t momo-techscout-sandbox:wave1 docker/sandbox
```

The image contains only the reviewed Chroma and Qdrant Local smoke scripts and
their pinned V1 packages. Runtime test stages use Docker network `none`; the
Python runner also applies CPU, memory, PID, disk, timeout, read-only-root,
capability, work-directory, and mount restrictions. `pgvector` intentionally has
no recipe in Wave 1 and remains research-only.

The optional local smoke is opt-in because ordinary tests do not require Docker:

```text
$env:TECHSCOUT_DOCKER_SMOKE = "1"
python -m pytest tests/techscout/test_sandbox_docker_smoke.py
```
