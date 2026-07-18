# Safe `.env` Configuration Loading Design

Date: 2026-07-18
Status: approved for implementation planning

## Goal

Allow MOMO Scholar to load persistent local configuration, including `DASHSCOPE_API_KEY`, from a `.env` file in the process current working directory so users do not need to set PowerShell environment variables for every session.

## Decisions

- Add `python-dotenv` as a runtime dependency.
- `load_settings()` loads only `.env` in `Path.cwd()`.
- Existing process environment variables take precedence; `.env` never overrides them.
- A missing `.env` is normal and preserves current behavior.
- Keep `.env` ignored by Git.
- Add a committed `.env.example` containing placeholders and documented retrieval defaults, never real secrets.
- Do not add CLI flags or search parent directories for configuration.

## Data Flow

1. A caller invokes `load_settings()`.
2. Configuration loading calls `load_dotenv(Path.cwd() / ".env", override=False)`.
3. Existing parsing and validation read the resulting values from `os.environ`.
4. `Settings` remains the single configuration contract used by the retrieval factory and pipeline.

## Security and Error Handling

- API keys remain repr-hidden in `Settings`.
- Keys are not written to logs, reports, fixtures, examples, or exception messages.
- `.env.example` uses an empty placeholder for `DASHSCOPE_API_KEY`.
- Malformed retrieval values continue to fail through the existing explicit validators.
- Missing `.env` files do not raise an error.

## Tests

Add focused configuration tests proving that:

- values are loaded from the current directory `.env`;
- an existing environment variable overrides the file;
- a missing `.env` preserves defaults;
- blank values continue to normalize safely;
- the example contains no secret and `.env` remains ignored.

Run focused configuration tests followed by the complete test suite and `git diff --check`.
