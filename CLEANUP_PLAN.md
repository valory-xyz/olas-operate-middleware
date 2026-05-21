# Cleanup plan — olas-operate-middleware

**Status:** plan-for-review. No code changes yet. Once approved, the
implementation lands in this same PR.

Baseline: `main` at `e38113d6` (v0.15.23). The repo is already on
tomte 0.7.0, uv_build, PEP 621, OA 0.21.21 — so it's structurally past
the cleanup-deps wave that trader/mech recently went through. This is
a Wave 2-style cleanup: kill dead infra, fold config into
`pyproject.toml`, stub overgrown docs, collapse the gitleaks config.

## Current state vs. trader (post-cleanup, PR #925)

| Aspect | trader (post-Wave-2) | operate-middleware (today) |
|---|---|---|
| Tomte pin | `v0.7.0` (git pin) | `0.7.0` (PyPI) — fine |
| `tox.ini` | 82 lines | 315 lines |
| pytest config | inlined in pyproject | separate `pytest.ini` (11 lines) |
| pylint config | inlined / pinned | separate `.pylintrc` (61 lines) |
| `CONTRIBUTING.md` | ~60 lines | 345 lines |
| `.gitleaks.toml` | deleted (extend pattern) | 544 lines, full ruleset |
| `.spelling` | deleted | already absent |

## Punch list (verified by grep over the working tree)

### Broken testenvs (reference files that don't exist)

- `[testenv:vulture]` — needs `scripts/whitelist.py`, missing
- `[testenv:check-copyright]` + `[testenv:fix-copyright]` — need
  `scripts/check_copyright.py`, missing

Neither is invoked in CI, so nothing fails today. They will surface
the moment someone runs `tox -e vulture` locally.

### Unused testenvs (declared, never invoked in CI or docs)

- `[testenv:darglint]`
- `[testenv:liccheck]`
- `[testenv:all-tests]`

### Dead CI step

- `sudo npm install -g markdown-spellcheck` in
  `.github/workflows/common_checks.yml` — no spell-check tox env
  exists to consume it.

### Stale tox config

- `envlist = isort` at the top of `tox.ini` — leftover, makes bare
  `tox` invocations do something surprising.
- `[mypy-typing_extentions.*]` — typo (`extentions`), permanently
  dead block.

### Dead or trivially swappable dependencies

Confirmed by grepping `operate/` + `tests/`:

| Dep | Hits | Action |
|---|---|---|
| `cytoolz` | 0 | drop |
| `typing_extensions` | 2 (only `Annotated`, `TypedDict`) | both stdlib on Python ≥ 3.10; swap imports to `typing` and drop the dep |
| `multiaddr` | 1 — only `operate/pearl.py:43-44` (PyInstaller bundling hint) | tied to pearl.py decision below |

### Pearl.py — broken on main, separately

`operate/pearl.py` imports `aea_ledger_ethereum_flashbots`, but that
plugin was removed from `pyproject.toml` during the uv migration.
The PyInstaller build is currently broken. Either:

- pearl.py is dead → delete it, the `.coveragerc` exclusion entry,
  and drop `pyinstaller` + `multiaddr`, OR
- pearl.py is alive (used by the Pearl Electron app) → re-add
  `open-aea-ledger-ethereum-flashbots` to dependencies.

Either way, this is a real bug — flagging it so we don't ship the
cleanup without resolving it.

## Phase plan (all changes in this single PR after review)

### Phase 1 — Delete dead infra

| File | Action |
|---|---|
| `tox.ini` | remove `[testenv:vulture]`, `[testenv:check-copyright]`, `[testenv:fix-copyright]`, `[testenv:darglint]`, `[testenv:liccheck]`, `[testenv:all-tests]`, the orphaned `[darglint]` block, the typo'd `[mypy-typing_extentions.*]` block; fix `envlist =` to something sane (empty or `unit-tests`) |
| `.github/workflows/common_checks.yml` | drop the `markdown-spellcheck` `npm install` line |
| `pyproject.toml` | drop `cytoolz` |
| `operate/operate_types.py`, `operate/cli.py` | swap `from typing_extensions import Annotated/TypedDict` → `from typing import …`; drop `typing_extensions` from `pyproject.toml` |
| `operate/pearl.py` + `.coveragerc` + `pyproject.toml` | resolve pearl.py per the "Pearl.py" section above |

**Expected delta:** `tox.ini` 315 → ~180 lines, `pyproject.toml`
loses 1-3 deps.

### Phase 2 — Fold config files into pyproject.toml

| From | To |
|---|---|
| `pytest.ini` (11 lines) | `[tool.pytest.ini_options]` in `pyproject.toml`; `rm pytest.ini` |
| `.pylintrc` (61 lines) | `[tool.pylint.master]`, `[tool.pylint."messages control"]`, `[tool.pylint.imports]`, `[tool.pylint.design]`, `[tool.pylint.spelling]`, `[tool.pylint.similarities]` in `pyproject.toml`; `rm .pylintrc`; drop `--rcfile=.pylintrc` from `[testenv:pylint]` |
| `tox.ini [isort]` + `[flake8]` | `[tool.isort]`, `[tool.flake8]` in `pyproject.toml` (Flake8-pyproject ships with `tomte[flake8]==0.7.0`) |
| `tox.ini [mypy]` (global flags) | `[tool.mypy]` in `pyproject.toml` |
| `tox.ini [mypy-*]` per-module ignores | **stay in `tox.ini`** — mypy doesn't read these from `pyproject.toml` when invoked via the testenv's `--config-file tox.ini`. Audit the list and drop blocks for deps that are gone |

**Verification gate:** `tox -e pylint,flake8,isort-check,black-check,mypy`
output must be byte-identical to pre-PR.

**Risks:** pylint's section names use the dotted-quote form
(`[tool.pylint."messages control"]`) and are easy to mis-type as
`[tool.pylint.messages_control]`. The latter is silently ignored. Verify
lint output, don't trust a green tox env alone.

**Expected delta:** `tox.ini` 180 → ~120 lines, two files deleted,
`pyproject.toml` grows by ~70 lines.

### Phase 3 — Docs cleanup (aggressive stub)

- **`CONTRIBUTING.md` → ~10-line stub** linking to the OA canonical
  (`https://github.com/valory-xyz/open-autonomy/blob/main/CONTRIBUTING.md`)
  plus a repo-specific notes block: run-tests command, pointer to
  `TESTING.md` and `IMPROVEMENT_PLAN.md`. Wave 2a pattern from the
  fleet plan.
- **`TESTING.md`** — trim sections that duplicate `CLAUDE.md`'s
  architecture diagram and command lists. Target ~250 lines (from
  427). Keep test organization, RPC env setup, pytest-recording
  setup. Drop generic pytest tutorial content.
- **`IMPROVEMENT_PLAN.md`** — historical record from 2026-02-25.
  Either keep with a date marker, or move to
  `docs/improvement-plan-2026-02.md`. Do not delete — it documents
  Phase 1+2 completion.
- **`docs/test-suite-guide.md`** — appears in working trees but
  isn't on `main`. Check provenance before this PR lands: merge into
  `TESTING.md` or commit and cross-reference.

**Expected delta:** `CONTRIBUTING.md` 345 → ~15, `TESTING.md` 427 → ~250.

### Phase 4 — Gitleaks → canonical extend stub

1. **Baseline capture:**
   ```
   gitleaks detect --config=.gitleaks.toml \
     --report-format=json --report-path=/tmp/gl-before.json
   ```
2. Replace `.gitleaks.toml` with:
   ```toml
   [extend]
   path = "https://raw.githubusercontent.com/valory-xyz/open-autonomy/<SHA>/.gitleaks.toml"

   [allowlist]
   description = "operate-middleware-specific allowlist"
   paths = [ ... ]   # whatever operate-middleware needs beyond canonical
   ```
3. Pin the SHA explicitly, not a branch — prevents surprise rule
   churn breaking CI.
4. **Verify the gitleaks action we use supports remote `[extend]
   path = URL`.** Some versions only support local paths; if ours
   doesn't, vendor the canonical instead of extending it.
5. Re-run gitleaks. Require identical findings vs the baseline.
6. `.gitleaksignore` stays — it's a per-repo path allowlist with
   real entries.

**Expected delta:** `.gitleaks.toml` 544 → ~15 lines.

## Sequencing within the PR

All four phases land in this same PR, committed in this order so the
diff stays reviewable:

1. `chore: drop dead testenvs, dead CI step, broken script refs`
2. `chore: prune dead deps; swap typing_extensions for stdlib`
3. `chore: fix or remove pearl.py PyInstaller entry point`
4. `chore: fold pytest.ini / .pylintrc / tool config into pyproject.toml`
5. `chore: stub CONTRIBUTING.md, trim TESTING.md`
6. `chore: collapse .gitleaks.toml to extend the OA canonical`

## Net effect (estimate)

| Metric | Before | After | Δ |
|---|---|---|---|
| `tox.ini` | 315 | ~120 | -195 |
| `pyproject.toml` | 50 | ~120 | +70 |
| `pytest.ini` | 11 | 0 | -11 |
| `.pylintrc` | 61 | 0 | -61 |
| `CONTRIBUTING.md` | 345 | ~15 | -330 |
| `.gitleaks.toml` | 544 | ~15 | -529 |
| `TESTING.md` | 427 | ~250 | -177 |
| testenvs | 19 | 13 | -6 |
| runtime deps | -2 to -4 | | |
| **Net** | | | **~-1,230 lines** |

## Things to confirm before implementing

These are blocking. Without answers, the PR can't move from
plan-for-review to implementation.

1. **`operate/pearl.py`** — still built downstream by the Pearl
   Electron app, or dead? If alive, the missing
   `open-aea-ledger-ethereum-flashbots` dep needs re-adding (separate
   bug, surfaced by this audit). If dead, delete pearl.py and drop
   `pyinstaller` + `multiaddr`.
2. **`gitleaks-action` version compatibility** — does our pinned
   action version support `[extend] path = <URL>`? If not, vendor the
   canonical inside the repo or pin to a vendored copy under
   `.github/` instead of extending remotely.
3. **`docs/test-suite-guide.md`** — provenance + relationship to
   `TESTING.md`. Was it added as a replacement or as a complementary
   doc? Decides whether Phase 3 merges or cross-references.

## Verification gate before this PR moves out of draft

Every check below must pass against `main` and against the cleanup
branch with byte-identical (or strictly-fewer-warning) output:

```
tox -e bandit
tox -e black-check
tox -e isort-check
tox -e flake8
tox -e mypy
tox -e pylint
tox -e safety
tox -e unit-tests
tox -e unit-tests-coverage
# integration-tests on at least one RPC env, smoke-only
```

Plus gitleaks parity check from Phase 4 step 5.
