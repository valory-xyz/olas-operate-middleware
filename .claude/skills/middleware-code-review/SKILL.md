---
name: middleware-code-review
description: Run the strict pre-commit checklist for middleware changes, resolve issues, and rerun relevant checks before commit.
---

Use this skill whenever Claude is preparing to commit changes in `olas-operate-middleware`, or when a hook or human instruction says to run middleware code review first.

## Purpose

This skill is the canonical pre-commit checklist for this repository.

## Required workflow

Before committing, Claude must complete all of the following:

1. Inspect the current staged and unstaged changes that are relevant to the intended commit.
2. Review the changes against this strict checklist one by one:
   - everything from the approved design/spec for the change is accurately implemented,
   - newly added code or logic is not duplicated with anything else relevant in the repository; if duplication is found, de-duplicate it,
   - naming and module boundaries still match repo conventions,
   - SOLID, DRY, YAGNI, KISS, and separation of concerns are followed strictly,
   - error handling is explicit and not silently swallowed,
   - comments explain **why**, not **what**,
   - no obvious dead code, duplicate instruction drift, or invalid workflow guidance was introduced,
   - `.claude/**`, `CLAUDE.md`, `docs/**`, and related workflow/docs remain consistent with actual repo behavior,
   - the pre-commit git hook is set using `git config core.hooksPath .githooks`,
   - transaction-flow changes include Tenderly-backed integration tests,
   - security-sensitive changes do not leave obvious validation, input-handling, or secret-management gaps,
   - newly added and other relevant unit/integration tests have been run locally and passed,
   - if a PR already exists, all review comments are addressed, resolved, or replied to before commit.
3. Treat unresolved checklist failures as blocking before commit.
4. Apply the necessary fixes and complete the checklist.
5. Only treat the branch as commit-ready when checklist issues are resolved and relevant validation passes.
6. If any point is impossible to do (for example, no .env is available to run integration tests), explain that in the commit message or PR comment.

## Failure handling

- If checklist issues remain unresolved, address them before committing.
- If relevant tests/checks fail after fixes, address them before committing.

## Notes

- This skill is the canonical entrypoint for middleware pre-commit checks.
