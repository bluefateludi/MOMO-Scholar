# Safe `.env` Configuration Loading Design

Date: 2026-07-18
Status: approved for implementation planning

## Goal

Allow MOMO Scholar to load persistent local configuration, including `DASHSCOPE_API_KEY`, from a `.env` file in the process current working directory so users do not need to set PowerShell environment variables for every session.

## Decisions

- Add `python-dotenv>=1.0` as a runtime dependency.
- `load_settings()` loads only `.env` in `Path.cwd()`.
- Existing process environment variables take precedence; `.env` never overrides them.
- Loading `.env` must not mutate process-global `os.environ`.
- A missing `.env` is normal and preserves current behavior.
- Keep `.env` ignored by Git.
- Add a committed `.env.example` containing placeholders and documented retrieval defaults, never real secrets.
- Do not add CLI flags or search parent directories for configuration.

## Data Flow

1. A caller invokes `load_settings()`.
2. Configuration loading calls `dotenv_values(Path.cwd() / ".env")` without parent-directory discovery.
3. A local mapping resolves each setting as `os.environ` value, then current `.env` value, then the existing default.
4. Parsing and validation consume that local mapping without modifying `os.environ`.
5. `Settings` remains the single configuration contract used by the retrieval factory and pipeline.

## Security and Error Handling

- API keys remain repr-hidden in `Settings`.
- Keys are not written to logs, reports, fixtures, examples, or exception messages.
- `.env.example` uses an empty placeholder for `DASHSCOPE_API_KEY`.
- Malformed retrieval values continue to fail through the existing explicit validators.
- Blank optional strings and API keys normalize to `None`; blank strings with defaults use their existing defaults.
- Blank `RETRIEVAL_MODE` remains a validation error.
- Blank `RETRIEVAL_CANDIDATE_K`, `RETRIEVAL_TOP_K`, and `RETRIEVAL_RRF_K` remain validation errors.
- Missing `.env` files do not raise an error.

## Tests

Add focused configuration tests proving that:

- values are loaded from a `tmp_path` current directory `.env`;
- parent-directory `.env` files are not searched;
- an existing environment variable overrides the file;
- a missing `.env` preserves defaults;
- consecutive loads from two current directories do not leak values;
- loading does not modify `os.environ` and tests clear supported variables with `monkeypatch`;
- blank optional/defaulted strings normalize as specified while blank mode and K values raise validation errors;
- the example contains no secret and `.env` remains ignored.

Run focused configuration tests followed by the complete test suite and `git diff --check`.
