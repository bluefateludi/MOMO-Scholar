# MOMO Scholar Development Guidelines

## Scope

This file defines development rules for agents working in this repository. It covers implementation, testing, verification, and delivery only.

Interview preparation, study notes, knowledge reviews, and mock-interview material do not belong in this file. Keep those concerns in separate documentation when requested.

## Source of Truth

- Read the relevant specification and implementation plan before changing code.
- Follow the current Chunk and Task boundaries in the active plan.
- Treat the repository's current package name, structure, and tests as authoritative when older plan examples differ from the implemented project.
- Do not implement later-Chunk functionality early unless the current Task requires an interface or placeholder for it.

## Development Workflow

For each Task:

1. Inspect the relevant plan section, existing implementation, tests, and current Git changes.
2. State the Task goal, expected inputs and outputs, and files likely to change.
3. Add or update a focused failing test before implementation when the change affects behavior.
4. Run the focused test and confirm that it fails for the expected reason.
5. Implement the smallest change that satisfies the Task.
6. Run the focused tests, then the broader relevant test suite.
7. Review the diff for unintended changes, stale names, debug code, and formatting problems.
8. Report what changed, what was verified, and any remaining limitation.

Do not interrupt implementation with long conceptual explanations unless the user asks for them. Keep development updates concise and action-oriented.

## Code and Architecture

- Preserve clear module boundaries and keep each unit focused on one responsibility.
- Separate external I/O from deterministic transformation logic so that core behavior can be tested without network access.
- Use the project's schemas as the contract between retrieval, processing, persistence, and rendering layers.
- Prefer explicit dependencies and small injectable interfaces over hidden global state.
- Keep MVP implementations simple, but make known limitations visible in code, tests, or delivery notes.
- Avoid unrelated refactors and broad cleanup while completing a scoped Task.
- Preserve existing user changes and do not overwrite or revert unrelated work.

## Testing

- Use deterministic fixtures or fakes for external services in the normal test suite.
- Keep live-network tests separate from unit and local integration tests.
- Cover normal behavior plus important boundaries such as empty input, malformed external data, duplicates, invalid options, and I/O failures when relevant to the Task.
- Test observable behavior and contracts rather than private implementation details.
- Never claim that work passes without running the relevant verification command and checking its result.

## External Services and Data

- Set explicit timeouts for network requests.
- Surface HTTP and parsing failures at the appropriate boundary.
- Do not expose secrets in source code, logs, examples, fixtures, or error messages.
- Normalize third-party data before passing it into downstream modules.
- Preserve stable source identifiers and provenance wherever available.

## Git and Delivery

- Check the working tree before editing and distinguish current Task changes from pre-existing user work.
- Do not stage, commit, push, merge, reset, or delete work unless the user explicitly requests it or the active plan explicitly requires it.
- Before handoff, summarize changed files, verification commands and results, and known remaining limitations.
- Keep interview preparation and learning documentation separate from development delivery unless the user explicitly requests both.
