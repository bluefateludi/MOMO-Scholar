# Explicit Package Discovery Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make editable and wheel builds succeed when a root `outputs/` directory exists.

**Architecture:** Setuptools discovery will be constrained to `paper_agent` and `paper_agent.*` in the authoritative `pyproject.toml`, with an explicit PEP 517 setuptools backend. A subprocess integration test will build a temporary project copy containing `outputs/`, then inspect the wheel to prove application packages are included and runtime output is excluded.

**Tech Stack:** Python 3.10+, setuptools, pip wheel, pytest, zipfile

---

## Chunk 1: Package discovery regression

### Task 1: Restrict setuptools discovery to application packages

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_packaging.py`

- [ ] **Step 1: Add the failing integration test**

Create a temporary project containing the current `pyproject.toml`, a copy of
`paper_agent/`, and a root `outputs/example.txt`. Run:

```python
subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        str(project),
        "--no-deps",
        "--no-build-isolation",
        "--no-index",
        "--disable-pip-version-check",
        "--wheel-dir",
        str(wheel_dir),
    ],
    capture_output=True,
    text=True,
    check=False,
)
```

Assert the build succeeds. Open the single generated wheel with `zipfile.ZipFile`;
assert at least one entry starts with `paper_agent/` and no entry starts with
`outputs/`.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest tests/test_packaging.py -q`

Expected: FAIL because setuptools reports multiple top-level packages
`outputs` and `paper_agent`.

- [ ] **Step 3: Add the minimal package discovery configuration**

Append to `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["paper_agent", "paper_agent.*"]
```

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `python -m pytest tests/test_packaging.py -q`

Expected: PASS.

- [ ] **Step 5: Reproduce the user's original editable-install scenario**

Only if the isolated worktree has no `outputs/`, create
`outputs/package-discovery-sentinel/result.txt`, record that this step owns the new
tree, and run `python -m pip install -e ".[dev]"`. Use `try/finally` semantics and
remove only the tree created by this step. If `outputs/` already exists, stop rather
than modifying or deleting it.

Expected: editable installation succeeds.

- [ ] **Step 6: Run regressions**

Run: `python -m pytest -q`

Expected: all tests PASS.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 7: Review scope and commit**

Confirm only `pyproject.toml` and `tests/test_packaging.py` changed, no runtime
artifacts are tracked, and no application code changed.

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "fix: restrict setuptools package discovery"
```
