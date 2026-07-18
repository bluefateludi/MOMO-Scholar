# Safe Dotenv Configuration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load persistent local settings from the current working directory `.env` without mutating process environment variables or exposing secrets.

**Architecture:** `load_settings()` will read one explicit path with `dotenv_values(Path.cwd() / ".env")`, then resolve each supported key from the process environment first and the file mapping second. Existing parsing and validation remain authoritative; `.env.example` documents safe placeholders and defaults.

**Tech Stack:** Python 3.10+, python-dotenv, dataclasses, pytest

---

## Chunk 1: Configuration behavior

### Task 1: Read isolated current-directory dotenv values

**Files:**
- Modify: `pyproject.toml`
- Modify: `paper_agent/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add focused failing tests**

Add an autouse fixture that clears every supported configuration environment variable and calls `monkeypatch.chdir(tmp_path)` so a developer's ignored `.env` cannot influence any configuration test. Special dotenv tests create files inside that temporary directory. Add tests that prove:

```python
@pytest.fixture(autouse=True)
def isolated_settings_environment(tmp_path, monkeypatch):
    for name in SUPPORTED_SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
```

```python
(tmp_path / ".env").write_text(
    "DASHSCOPE_API_KEY=file-key\nRETRIEVAL_MODE=hybrid\n",
    encoding="utf-8",
)
settings = load_settings()
assert settings.dashscope_api_key == "file-key"
assert settings.retrieval_mode == "hybrid"
```

Also test that a process `DASHSCOPE_API_KEY` wins, a parent `.env` is ignored by creating parent/child directories and entering the child, two consecutive cwd loads do not leak, and `os.environ` is unchanged.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/test_config.py -q`
Expected: new dotenv tests fail because `load_settings()` reads only `os.environ`.

- [ ] **Step 3: Add the runtime dependency**

Add `python-dotenv>=1.0` to `[project].dependencies` in `pyproject.toml`.

- [ ] **Step 4: Implement a local configuration mapping**

In `paper_agent/config.py`, import `Path`, `Mapping`, and `dotenv_values`. Add a helper that reads only `Path.cwd() / ".env"`, and a resolver equivalent to:

```python
def _setting(name: str, dotenv: Mapping[str, str | None]) -> str | None:
    if name in os.environ:
        return os.environ[name]
    return dotenv.get(name)
```

Call `dotenv_values()` once per `load_settings()` invocation and replace direct `os.environ.get(...)` calls with the resolver. Do not modify `os.environ`.

- [ ] **Step 5: Refresh the editable environment**

Run: `python -m pip install -e ".[dev]"`
Expected: the project and `python-dotenv>=1.0` install successfully. No lockfile update is required.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 7: Add blank-value compatibility tests**

Assert blank optional/defaulted string behavior remains unchanged and blank `RETRIEVAL_MODE`/K values still raise their existing validation errors.

- [ ] **Step 8: Run focused tests**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 9: Commit behavior**

```bash
git add pyproject.toml paper_agent/config.py tests/test_config.py
git commit -m "feat: load settings from local dotenv"
```

## Chunk 2: Safe configuration example and verification

### Task 2: Document local configuration safely

**Files:**
- Create: `.env.example`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add failing safety test**

Resolve the repository root with `Path(__file__).resolve().parents[1]` because the autouse fixture changes cwd. Test that the root `.env.example` exists, includes an empty `DASHSCOPE_API_KEY=`, contains retrieval defaults, and does not contain a non-empty API key.

- [ ] **Step 2: Run the safety test and confirm RED**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL because `.env.example` is absent.

- [ ] **Step 3: Add `.env.example`**

```dotenv
DASHSCOPE_API_KEY=
RETRIEVAL_MODE=auto
RETRIEVAL_CANDIDATE_K=30
RETRIEVAL_TOP_K=8
RETRIEVAL_RRF_K=60
```

- [ ] **Step 4: Verify focused and full suites**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS.

Run: `python -m pytest -q`
Expected: all tests PASS.

Run: `git diff --check`
Expected: no output.

- [ ] **Step 5: Confirm security and isolation**

Run before staging:

```bash
git check-ignore -q .env
if ($LASTEXITCODE -ne 0) { throw '.env must be ignored' }

git check-ignore -q .env.example
if ($LASTEXITCODE -ne 1) { throw '.env.example must not be ignored' }
``` 

Expected: `.env` is ignored and `.env.example` is not ignored. Inspect the diff to confirm no secret appears and rely on the focused cross-cwd test for isolation.

- [ ] **Step 6: Commit example**

```bash
git add .env.example tests/test_config.py
git commit -m "docs: add safe dotenv example"
```
After staging, run: `git ls-files --error-unmatch .env.example`
Expected: `.env.example` is tracked.

Preserve any unrelated or pre-existing worktree changes; stage only the files listed by each task and report residual status honestly.