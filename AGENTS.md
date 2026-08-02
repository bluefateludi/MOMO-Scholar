# MOMO Scholar Development Guidelines

## Scope

This file defines development rules for agents working in this repository. It covers implementation, testing, verification, and delivery only.

Interview preparation, study notes, knowledge reviews, and mock-interview material do not belong in this file. Keep those concerns in separate documentation when requested.

## Source of Truth

- Read relevant specifications or plans when they exist and are needed for the Task.
- When an active plan applies, follow its current Chunk and Task boundaries.
- Treat the repository's current package name, structure, and tests as authoritative when older plan examples differ from the implemented project.
- Do not implement later-Chunk functionality early unless the current Task requires an interface or placeholder for it.

## Development Workflow

For each Task:

1. Inspect the relevant plan section, existing implementation, tests, and current Git changes.
2. For non-trivial Tasks, briefly state the goal and files likely to change.
3. Implement the smallest change that satisfies the Task.
4. Match verification effort to the risk of the change. By default, run only the necessary tests and perform a brief diff review. Use RED -> GREEN and broader verification when justified by risk. Run independent reviews only when the user requests them. The user's explicitly requested workflow takes precedence.
5. Report what changed, what was verified, and any remaining limitation.

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
- Cover the important behavior and boundaries relevant to the change.
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
- For implementation Tasks that produce verified tracked changes, delivery is an automatic part of the Task. Without requesting additional confirmation, create or use a `codex/` branch, stage only the active Task's files, create a scoped commit, push the branch with a normal non-force push, and create or update a Draft pull request targeting `master`.
- Treat the preceding automatic delivery workflow as standing user authorization for branch creation, scoped staging, commit creation, normal push, and Draft pull request creation or updates. Do not ask the user to perform these steps manually when the required credentials and tools are available.
- Do not create an empty commit or pull request when a Task produces no tracked changes or only gitignored/local artifacts. Do not stage unrelated user changes.
- Merge, rebase, reset, clean, amend, force push, pull request conversion to Ready, branch deletion, and worktree deletion still require explicit user authorization.
- Deleting or renaming source files is allowed when it is a necessary, scoped part of the approved Task and is visible in the final diff.
- If authentication, repository policy, or tooling blocks automatic delivery, complete all safe local work and report the exact blocker instead of delegating routine Git commands back to the user.
- Report the branch, commit, push, and Draft pull request during handoff.
- Before handoff, summarize changed files, verification commands and results, and known remaining limitations.
- Keep interview preparation and learning documentation separate from development delivery unless the user explicitly requests both.
