---
name: explore-middleware-codebase
description: Use this skill to gain a deep technical understanding of the `olas-operate-middleware` codebase before proposing or doing any implementation work. This skill emphasizes code exploration and detailed specification writing to ensure implementation-ready outputs.
---

# Explore Middleware Codebase

Use this skill when you need to analyze, scope, or plan anything in `olas-operate-middleware` and want a repo-specific exploration that traces the real codebase.

This skill is for producing complete, implementation-ready specs. Output should be detailed enough that a developer or coding agent can implement without follow-up questions.

**Before proposing anything, explore the codebase.** Use file search and code reading to find the actual classes, methods, and patterns involved. Never suggest changes to code you haven't read.

---

## Three Layers Always in Scope

Every change touches one or more of these layers. Identify which before proposing anything:

1. **HTTP API** — FastAPI server, route handlers, request/response schemas, docs
2. **Services Layer** — ServiceManager, Service lifecycle, FundingManager, HealthChecker, OnChainManager, DeploymentManager, deployment runners (e.g., BaseDeploymentRunner, PyInstallerHostDeploymentRunner)
3. **Wallet / Bridge / Chain** — MasterWallet, BridgeManager, ledger profiles, on-chain interactions

---

## Required Output — 10 Sections for Every Requirement

Produce all 10 sections. A plan with open items in section 10 is **not ready for handoff**.

### 1. Context
- Problem statement and what prompted this change
- Relevant prompts or user-facing symptoms
- Success criteria (what does "done" look like?)

### 2. Scope Classification
- **Type**: Bug / Feature / Refactor / Question
- **Scale**: Isolated (single file/class) / Module-wide (one layer) / Cross-cutting (multiple layers)

### 3. Data-Flow Trace
Trace the full path from entry point to effect:
- Which HTTP endpoint(s) are involved?
- Which ServiceManager method is called?
- Which downstream objects are touched (Service, FundingManager, OnChainManager, MasterWallet, BridgeManager)?
- Does anything hit the blockchain or external APIs?

### 4. File-Level Change List

| File | Class / Method | Change Type | Rationale |
|------|---------------|-------------|-----------|
| `operate/...` | `ClassName.method()` | Add / Modify / Delete | Why this file needs to change |
| `CLAUDE.md` or anything in `.claude/` | `Section 3` | Modify | Update the spec with new information discovered during exploration |

### 5. API Contract Changes
- List any new or modified HTTP endpoints (method, path, request schema, response schema)
- **FRONTEND BLOCKER**: Flag any change the Pearl app (`olas-operate-app`) depends on — do not design around nonexistent APIs
- If no API changes: state explicitly

### 6. State & Persistence Changes
- Any changes to JSON schemas on disk (services `config.json`, wallets `ethereum.json`, `settings.json`, `pearl_store.json` etc.)
- Does a migration need to be added in `operate/migration.py`?
- Any new files written to the operate home directory?
- If no persistence changes: state explicitly

### 7. Implementation Approach
- Primary recommended approach with reasoning
- Footnote alternatives considered and why they were ruled out
- Call out any existing utilities to reuse (explore the codebase first)
- Try to keep the changes minimal to achieve the goal, any new code adds maintenance burden. 

### 8. Hard Constraints Checklist
Verify each applies or does not apply to this change:

- [ ] A deep understanding has been gained about anything that's being touched in the codebase. If anything is still unclear, ask.
- [ ] CI checks passes
- [ ] Updates to existing code follows existing patterns in the codebase
- [ ] The existing code is re-used as much as possible, rather than new code being added.
- [ ] New code (if any) follows SOLID, DRY, KISS, and YAGNI principles.

### 9. Test Strategy
- Which tests need to be added or modified?
- Unit test or integration test (`@pytest.mark.integration`)?
- What to mock vs what to test with real objects?
- New fixtures needed in `tests/conftest.py`, or can existing ones be reused?
- Any new transactions flows that should be covered by one or more integration test?

### 10. Unresolved Questions
- List any blocking assumptions that must be resolved before implementation
- Identify any missing information about external systems (blockchain state, Pearl app behavior, etc.)
- If none: state "None — ready for handoff"

---

## Process Rules

1. **Explore before proposing** — read actual file contents and use real file paths, never assumptions
2. **Check for existing models** before creating new ones — look in `operate/operate_types.py`, etc.
3. **Check for existing utilities** before reimplementing — look in `operate/utils/`, etc.
4. **Flag API changes immediately** — Pearl app (`olas-operate-app`) consumes this API; changes are FRONTEND BLOCKERs
5. **Identify migrations early** — any JSON schema change needs a migration entry
6. **Reuse existing patterns** — for persistence, HTTP handlers, and test fixtures
7. **Plans with open section-10 questions are not ready for handoff**
