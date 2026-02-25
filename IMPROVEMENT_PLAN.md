# Improvement Plan

**Last reviewed:** 2026-02-25
**Replaces:** STABILITY_AND_QUALITY_IMPROVEMENT_PLAN.md, PHASE3_REFACTORING_PLAN.md, RESOURCE_LEAKS.md, VALIDATION_GAPS.md, IPFS_DOWNLOAD_ISSUES.md

---

## Completed Work

### Phase 1: Stability Fixes (all merged/ready)
- **1.1 RPC bug fix** — custom RPC endpoints now used in balance checks and funding
- **1.2 Error handling** — specific exception types in health_checker, deployment_runner, funding_manager
- **1.3 Race conditions** — PID file locking (`operate/utils/pid_file.py`), funding cooldown thread safety, health checker job lock
- **1.4 Resource leaks** — file handle leak in deployment_runner fixed (log files now tracked and closed in `_stop_agent`/`_stop_tendermint`)
- **1.5 Input validation** — `Deployment.delete()` state guard, `fund_service()` address validation, non-positive amount warnings

### Phase 2: Testing (complete)
- **1,647 unit tests**, 100% coverage (7,580 statements), CI-enforced via `--cov-fail-under=100`
- `.coveragerc` excludes `operate/pearl.py` (PyInstaller-only)
- All 6 linters passing (isort, black, flake8, pylint 10.00/10, mypy, bandit)

---

## Remaining High-Impact Work

Prioritized by production risk. Only items with verified impact are listed.

### A. Security Fixes

#### A1. Traceback exposure in HTTP error handler
**File:** `operate/operate_http/__init__.py:140-146`
**Issue:** Full Python tracebacks returned in HTTP error responses — leaks file paths, variable names, internal structure.
**Fix:** Return generic error message; log traceback server-side only.
**Priority:** Low — both client and server run on localhost. Good practice to address eventually.

#### A2. Private keys file not cleaned up on builder failure
**Files:** `operate/services/service.py`
- `_build_kubernetes()` (lines 421-437): no try/except around builder creation — keys file not cleaned up on failure
- `_build_docker()` handles this correctly (calls `unrecoverable_delete(keys_file)`)
- `_build_host()`: keys file is written in **encrypted** form (unlike docker's plain text), so `unrecoverable_delete` is not needed here

**Fix:** Add try/finally to `_build_kubernetes()` to ensure cleanup on failure.

#### A3. Password comparison vulnerable to timing attacks
**File:** `operate/cli.py:703, 724`
**Issue:** Plain `!=` comparison on password for `/api/wallet/private_key` and `/api/wallet/mnemonic` endpoints.
**Fix:** Use `hmac.compare_digest()`.
**Priority:** Low — localhost API, limited practical risk. Easy to fix.

### B. Data Integrity Fixes

#### B1. Package deleted before new IPFS download succeeds
**File:** `operate/services/service.py:1196-1206`
**Issue:** In `update()`, old package is `shutil.rmtree()`'d before `IPFSTool().download()` — if download fails, old package is gone and state is corrupted.
**Fix:** Download to temp location first, then swap. Or: keep old package until new download confirmed.

#### B2. Unsafe global `os.environ["CUSTOM_CHAIN_RPC"]` mutation
**File:** `operate/services/manage.py` (7+ locations: lines 350, 654, 1332, 1670, 2394, 2597, 2699)
**Issue:** Global env var set before each chain operation. Not thread-safe — concurrent operations on different chains use wrong RPC. Code has `# TODO fix this` comments.
**Fix:** Pass RPC through the call chain or use thread-local storage. This is the most impactful refactoring item — a single helper would replace 7 duplicate patterns.
**Note:** This is a legacy hot-fix due to how the framework works. Already tagged for investigation on whether it should be removed.

#### B3. Shallow copy of nested overrides
**File:** `operate/services/service.py:198`
**Issue:** `copy()` (shallow) used on nested overrides dict. Mutations to the copy affect the original `self.service.overrides`.
**Fix:** Use `deepcopy()`.

### C. Dead Code Removal

All items below are marked `# pragma: no cover` and/or `# TODO deprecate`. Removing them reduces maintenance burden, attack surface, and confusion.

#### C1. Deprecated funding methods in manage.py (~400 lines)
- `fund_service_single_chain()` (line 2022)
- `fund_service_erc20()` (line 2187) — comment says "possibly not used anymore"
- `refill_requirements()` (line 2373)
- `_compute_bonded_assets()` (line 2574)
- `_compute_protocol_asset_requirements()` (line 2690)
- `get_master_eoa_native_funding_values()` (line 2821)

#### C2. On-chain methods in manage.py — genericize, don't remove (~500 lines)
- `deploy_service_onchain()` (line 319)
- `_deploy_service_onchain()` (line 333)
- `terminate_service_on_chain()` (line 1287)
- `unbond_service_on_chain()` (line 1616)
- `unstake_service_on_chain()` (line 1838)
- `stake_service_on_chain()` (line 1644) — stub that raises `NotImplementedError`

Currently marked "Deprecated usage in favour of Safe version." **The plan is not to remove these but to make their logic generic using dependency injection with a `from_safe` parameter**, so all on-chain operations can be done from both Safe and EOA. See also E4.

#### C3. Dead stub in protocol.py
- `get_swap_data()` (line 1869) — raises `NotImplementedError`

### D. Reliability Improvements

#### D1. IPFS download error handling
**File:** `operate/cli.py` (service creation endpoint), `operate/services/service.py`
**Issue:** IPFS download failures (timeout, connection error) bubble up as 500 Internal Server Error. Partial service directories left on disk.
**Fix:** Catch network errors specifically, return 503 with retry guidance, clean up partial state.
**Note:** Uses open-autonomy's `IPFSTool` class — error handling improvements should ideally be contributed upstream to the OA package.

#### D2. Broad exception handling in staking params
**File:** `operate/services/protocol.py:268, 688`
**Issue:** `except Exception: pass` masks RPC failures as "not found". Code has `# TODO` acknowledging this.
**Fix:** Catch specific `ContractLogicError` instead.

#### ~~D3. `@cache` on static method with RPC parameter~~ — Not a bug
**File:** `operate/services/protocol.py:237`
**Rationale:** `_get_staking_params()` is decorated with `@cache`. This is intentional — the staking contract data never changes, so caching is correct. The RPC parameter difference is irrelevant since the data is the same regardless of which RPC is used to read it.

### E. High-Impact Refactoring (only if pursuing)

These are not bugs but reduce bug surface area by eliminating duplication:

#### E1. Extract RPC setup helper in manage.py
7 identical patterns of `chain_config` extraction + `os.environ` mutation + `sftxb` creation. A single helper fixes B2 and eliminates duplication simultaneously.

#### E2. Extract builder setup helper in service.py
3 near-identical sequences in `_build_kubernetes()`, `_build_docker()`, `_build_host()` with inconsistent error handling (causes A2).

#### E3. Refactor wallet to abstract transaction sending
**Files:** `operate/wallet/master.py`, `operate/services/protocol.py`, `operate/services/manage.py`
**Issue:** Manager/protocol code builds raw transactions and manually handles Safe vs EOA sending logic. This is spread across EthSafeTxBuilder and various call sites.
**Fix:** Wallet should accept raw transactions and abstract sending them via either EOA (`from_safe=False`) or Safe (generating and setting the required Safe messages). Manager/protocol builds the raw txs, `wallet.send_tx()` takes care of the rest. This would simplify EthSafeTxBuilder operations significantly.

#### E4. Genericize on-chain methods with dependency injection
**Files:** `operate/services/manage.py`
**Issue:** Duplicate `*_on_chain()` and `*_on_chain_from_safe()` method pairs with near-identical logic.
**Fix:** Make the on-chain methods generic with a `from_safe` parameter, using dependency injection so all on-chain operations work from both Safe and EOA. Related to C2 and E3.

#### E5. State machine enforcement for service status transitions
**File:** `operate/services/service.py`
**Issue:** `self.status = DeploymentStatus.X` can be set to any value from any state. A validated `set_status()` method would prevent invalid transitions.
**Status:** Deferred — low incident rate in practice.

---

## Items Explicitly NOT Planned

These were in previous plans but are not high-impact enough to pursue:

- **SQLite migration** (was Phase 3.1) — JSON storage works fine with current scale. Migration is high-risk, high-effort, low-reward.
- **ServiceManager class decomposition** (was Phase 3) — splitting for the sake of class size doesn't prevent bugs. The real fix is removing dead code (C1) and genericizing on-chain methods (C2/E4).
- **Structured logging / correlation IDs** (was Phase 4.1) — nice-to-have, not high-impact.
- **Configuration externalization** (was Phase 3.5) — current approach works.
- **Performance optimizations** (was Phase 4.3) — no evidence of performance bottlenecks.

---

## Metrics

| Metric | Value |
|--------|-------|
| Unit tests | 1,647 |
| Coverage | 100% (7,580 statements) |
| Production code | ~11,000 lines (core files) |
| TODO/FIXME comments | 100 |
| `# pragma: no cover` lines | 100 |
| Deprecated dead code | ~900 lines in manage.py |
