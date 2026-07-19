# Explicit Package Discovery Design

Date: 2026-07-19
Status: approved for specification review

## Goal

Make editable and wheel installation succeed when runtime artifact directories such as
`outputs/` exist at the repository root.

## Root Cause

Setuptools currently uses automatic flat-layout discovery. With an `outputs/` directory
present, namespace discovery finds both `outputs` and `paper_agent` and aborts rather
than risk packaging unrelated files.

## Design

- Configure setuptools package discovery explicitly in `pyproject.toml`.
- Include only `paper_agent` and `paper_agent.*`, covering the main package and all
  current or future subpackages without matching sibling names such as
  `paper_agent_backup`.
- Declare setuptools as the PEP 517 build backend so clean environments have an
  explicit, reproducible backend contract.
- Do not enumerate exclusion rules for runtime or documentation directories.
- Do not move the project to a `src/` layout in this fix.
- Preserve project metadata, CLI entry points, dependencies, and runtime behavior.

## Verification

- Add a regression test that reads the authoritative `pyproject.toml` and proves package
  discovery is restricted to `paper_agent*`.
- Reproduce the original scenario with a root `outputs/` directory and run an actual
  package build or editable-install metadata/build command.
- Confirm the built distribution contains `paper_agent` modules and does not contain
  `outputs`.
- Run the focused packaging test, the complete test suite, and `git diff --check`.

## Scope

Modify only packaging configuration, its focused regression test, and the associated
specification/implementation plan. Do not change application code or delete user output.
