# Cleanup plan — olas-operate-middleware

**Status:** implemented in PR #447 (commits 366a1b42 and 884611f4).
This doc remains as the design rationale behind those commits.

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
| `multiaddr` | 1 — only `operate/pearl.py:42-43` (PyInstaller bundling hint) | dropped with pearl.py (see below) |

### Pearl.py — dead in this repo

`operate/pearl.py` is the PyInstaller entry point. Confirmed by
@OjusWiZard: the live Pearl entry point is in `olas-operate-app`
(the Electron repo); the copy here is dead. Action:

- delete `operate/pearl.py`
- remove the `omit = operate/pearl.py` line from `.coveragerc`
- drop `pyinstaller` and `multiaddr` from `pyproject.toml`

## Phase plan (all changes in this single PR after review)

### Phase 1 — Delete dead infra

| File | Action |
|---|---|
| `tox.ini` | remove `[testenv:vulture]`, `[testenv:check-copyright]`, `[testenv:fix-copyright]`, `[testenv:darglint]`, `[testenv:liccheck]`, `[testenv:all-tests]`, the orphaned `[darglint]` block, the typo'd `[mypy-typing_extentions.*]` block; remove the `envlist = isort` line entirely so a bare `tox` is a no-op (setting `envlist = unit-tests` would auto-run the longest local job, which is the opposite of "sane") |
| `.github/workflows/common_checks.yml` | drop the `markdown-spellcheck` `npm install` line |
| `pyproject.toml` | drop `cytoolz` |
| `operate/operate_types.py`, `operate/cli.py` | swap `from typing_extensions import Annotated/TypedDict` → `from typing import …` (`operate_types.py` is imported by ~30 files but the change is the import line only, no API change); drop `typing_extensions` from `pyproject.toml` |
| `operate/pearl.py` + `.coveragerc` + `pyproject.toml` | delete pearl.py, remove the `.coveragerc` omit entry, drop `pyinstaller` + `multiaddr` |

**Expected delta:** `tox.ini` 315 → ~180 lines, `pyproject.toml`
loses 1-3 deps.

### Phase 2 — Fold config files into pyproject.toml

| From | To |
|---|---|
| `pytest.ini` (11 lines) | `[tool.pytest.ini_options]` in `pyproject.toml`; `rm pytest.ini` |
| `.pylintrc` (61 lines) | `[tool.pylint.master]`, `[tool.pylint."messages control"]`, `[tool.pylint.imports]`, `[tool.pylint.design]`, `[tool.pylint.spelling]`, `[tool.pylint.similarities]` in `pyproject.toml`; `rm .pylintrc`; drop `--rcfile=.pylintrc` from `[testenv:pylint]` |
| `tox.ini [isort]` + `[flake8]` | `[tool.isort]`, `[tool.flake8]` in `pyproject.toml` (Flake8-pyproject ships with `tomte[flake8]==0.7.0`) |
| `tox.ini [mypy]` + `[mypy-*]` | **all stay in `tox.ini`.** `[testenv:mypy]` at `tox.ini:69` passes `--config-file tox.ini`. With `--config-file` set, mypy reads ONLY that file and silently ignores `[tool.mypy]` in `pyproject.toml` — splitting them would lose config without failing CI. Audit the list and drop blocks for deps that are gone, but don't move them |

**Verification gate:** for each of `tox -e pylint,flake8,isort-check,
black-check,mypy`, the post-PR finding set must be a (non-strict)
subset of the pre-PR finding set — i.e. no new findings introduced.
Byte-identical output is too strict (these tools shift cosmetic
output on file traversal order, rule-list summaries, timing lines).
Compare normalised finding lists, not raw stdout.

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

**Expected delta:** `CONTRIBUTING.md` 345 → ~15, `TESTING.md` 427 → ~250.

### Phase 4 — Gitleaks: delete the local ruleset

Match trader's post-cleanup state (PR #925 deleted `.gitleaks.toml`
entirely, leaving only `.gitleaksignore`). The 544-line file in this
repo is the upstream default ruleset plus a handful of Valory-style
allowlists; gitleaks falls back to its bundled default when the file
is absent.

1. **Baseline capture:**
   ```
   gitleaks detect --config=.gitleaks.toml \
     --report-format=json --report-path=/tmp/gl-before.json
   ```
2. `rm .gitleaks.toml`. Move any genuinely-operate-middleware-specific
   path allowlists into `.gitleaksignore` (which stays).
3. Re-run gitleaks with no `--config`. Require the new findings
   set ⊆ baseline (i.e. no *new* secrets surface). New
   false-positives are allowlisted in `.gitleaksignore`.

**Expected delta:** `.gitleaks.toml` 544 → 0 lines.

## Sequencing within the PR

All four phases land in this same PR, committed in this order so the
diff stays reviewable:

1. `chore: drop dead testenvs, dead CI step, broken script refs`
2. `chore: prune dead deps; swap typing_extensions for stdlib`
3. `chore: delete pearl.py (live entry point is in olas-operate-app)`
4. `chore: fold pytest.ini / .pylintrc / tool config into pyproject.toml`
5. `chore: stub CONTRIBUTING.md, trim TESTING.md`
6. `chore: delete local .gitleaks.toml ruleset (match trader)`

## Net effect (estimate)

| Metric | Before | After | Δ |
|---|---|---|---|
| `tox.ini` | 315 | ~120 | -195 |
| `pyproject.toml` | 50 | ~120 | +70 |
| `pytest.ini` | 11 | 0 | -11 |
| `.pylintrc` | 61 | 0 | -61 |
| `CONTRIBUTING.md` | 345 | ~15 | -330 |
| `.gitleaks.toml` | 544 | 0 | -544 |
| `TESTING.md` | 427 | ~250 | -177 |
| testenvs | 19 | 13 | -6 |
| runtime deps | -2 to -4 | | |
| **Net** | | | **~-1,230 lines** |

## Review feedback resolved (round 1, @OjusWiZard)

- `operate/pearl.py` is dead in this repo (live one is in
  `olas-operate-app`). Phase 1 deletes it.
- `operate/operate_types.py` is widely imported, so the
  `typing_extensions` swap touches a central file — the change is
  import-line only, no API change.
- `docs/test-suite-guide.md` was local-context pollution from my
  working tree, not on `main`. Removed from this plan.
- Gitleaks: simplifying further — trader's actual end state is no
  local `.gitleaks.toml` at all, so Phase 4 now matches that
  instead of the extend-stub pattern.

## Verification gate before this PR moves out of draft

For each check below, the post-PR finding set must be a (non-strict)
subset of the pre-PR finding set — no *new* findings, errors, or
failures introduced. Compare normalised lint reports, not raw stdout
(pylint/mypy/flake8 reorder cosmetic output on config changes).

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
