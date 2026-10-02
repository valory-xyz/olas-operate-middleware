# Testing Guide

How tests are organised in this repo, how to run them, and the rules
CI enforces. Generic pytest / VCR tutorial material lives in upstream
docs; this file documents only what's specific to operate-middleware.

## Test Organization

### Unit Tests (2,711 tests, ~2 minutes)

Fast tests with no external dependencies. Run with:

```bash
uv run tox -e unit-tests
```

### Integration Tests (329 tests, slow)

Three kinds, all marked `integration`. **Run selectively.**

| Kind | Needs | Examples |
|---|---|---|
| Fork tests (`OnFork`) | Docker | funding, Safe creation, staking, recovery |
| Live read-only tests | network | bridge quotes, staking config checks, IPFS |
| Cassette replays (`vcr`) | nothing | bridge execution status |

Mainnet RPCs come from the usual `*_RPC` env vars (`GNOSIS_RPC`,
`BASE_RPC`, `OPTIMISM_RPC`, `ETHEREUM_RPC`, `POLYGON_RPC`), falling
back to the public defaults in `operate/ledger/__init__.py`.

```bash
uv run tox -e integration-tests -- path/to/test -v
```

By default runs with `pytest-xdist` in parallel (`-n auto`); CI
overrides to `-n 8`. To debug or narrow parallelism locally:

```bash
export CI=true
export PYTEST_XDIST_WORKERS=2
uv run tox -e integration-tests -- path/to/test -v
```

### Fork tests (Anvil in Docker)

Tests inheriting `OnFork` (in [tests/conftest.py](tests/conftest.py))
send real transactions to local Anvil forks of mainnet. Docker is the
only requirement: pytest starts one container per chain on first use
(image pinned as `ANVIL_IMAGE` in [tests/forks.py](tests/forks.py)),
per xdist worker, and removes them at session end.

- Each test starts from a fresh fork of the latest upstream block, so
  balances and time warps never leak between tests. Archive RPCs are
  not needed.
- Use `fork_add_balance`, `fork_set_native_balance` and
  `fork_increase_time` to set up state.
- A chain the test never looks up is not forked, and never falls
  through to the live RPC.
- Containers carry the label `operate-test-fork`
  (`docker ps --filter label=operate-test-fork`).
- In CI they run on Linux only.

### Recorded HTTP tests (pytest-recording)

Some tests replay previously recorded HTTP responses via
`pytest-recording` (VCR.py wrapper) instead of hitting live RPC.
Cassettes live in `tests/cassettes/` and are committed to git. This
is a deterministic-replay system, not a mock — re-record when the
upstream API actually changes.

**Tests that use VCR cassettes today:**

| Test | Cassettes |
|---|---|
| `TestNativeBridgeProvider::test_find_block_before_timestamp` | 11 |
| `TestProvider::test_bridge_zero` | 2 |
| `TestProvider::test_update_execution_status` | 17 |
| `TestProvider::test_update_execution_status_failure_then_success` | 17 |
| `TestBridgeManager::test_correct_providers_native` | 7 |

**Cassette matching strategy** (configured in [tests/conftest.py](tests/conftest.py)):
`method`, `rpc_uri`, `rpc_body`. JSON-RPC requests match on the chain
inferred from the URL plus method and params; everything else matches
on exact URI and body. A request with no match fails the replay.

**Keeping requests reproducible:**

- Create the wallet with `CASSETTE_WALLET_MNEMONIC`, not a random one;
  its address is part of the recorded JSON-RPC params.
- `vcr`-marked tests automatically get sequential bridge request ids,
  a fresh ledger-API cache and no Chainlist RPC enrichment.

**Re-recording cassettes:**

```bash
# Delete old cassette(s) first
rm tests/cassettes/test_bridge_providers/<TestClass>.<test_name>*

# Re-record, one case at a time to stay under CoinGecko rate limits
uv run pytest -p no:pytest_anchorpy -m integration \
  tests/test_bridge_providers.py::<TestClass>::<test_name> \
  --record-mode=once -v

# Verify offline
uv run pytest -p no:pytest_anchorpy -m integration \
  tests/test_bridge_providers.py::<TestClass>::<test_name> \
  --block-network --record-mode=none -v
```

RPC URLs are stored verbatim, so record only with keyless `*_RPC`
URLs. Check that the recording run passed: a rate-limited response
gets recorded and replayed as a skip.

For VCR fundamentals (record modes, filter_headers, parameterised
tests), see the [VCR.py docs](https://vcrpy.readthedocs.io/) — we
don't duplicate them here.

## Test Coverage

**100% unit test coverage** is enforced across the `operate/`
package (8,561 statements). CI fails on any drop
(`--cov-fail-under=100`). The only file excluded from coverage is
`operate/data/contracts/uniswap_v2_erc20/tests/test_contract.py`
(see [`.coveragerc`](.coveragerc)).

### `# pragma: no cover` policy

Pragmas are reserved for code that genuinely cannot be reached in
unit tests:

- **Defensive branches** — `TYPE_CHECKING` blocks, unreachable `else`
- **Thin I/O wrappers** — `print`, `input`, `Halo` spinner — nothing
  to test when mocked
- **Blockchain-interactive orchestration** — high-level quickstart
  functions that chain multiple on-chain calls; covered end-to-end
  by integration tests
- **Subprocess wrappers** — one-liners over `subprocess.run` in
  `operate/services/utils/tendermint.py`

Pragmas are **not** used to skip real business logic.

## Test Markers

Defined in [`pyproject.toml`](pyproject.toml) `[tool.pytest.ini_options]`:

```python
@pytest.mark.unit          # Pure unit tests
@pytest.mark.integration   # Integration tests (requires RPC)
@pytest.mark.requires_rpc  # Explicitly requires RPC endpoints
@pytest.mark.vcr           # Records/replays HTTP via pytest-recording
```

Filter examples:

```bash
uv run pytest -m "unit"
uv run pytest -m "integration"
uv run pytest -m "not integration"
```

## Integration tests still rely on live networks

Fork tests read mainnet state through the upstream RPC, and the live
read-only tests call third-party services directly (Relay, Mayan,
CoinGecko, IPFS, GitHub). Both are slow and can fail on upstream
outages or rate limits; only the cassette replays are offline.

## CI Strategy

- **Linter checks** — run first, must pass.
- **Unit tests** — 3 OS × 5 Python versions (3.10–3.14), must pass.
- **Coverage** — Ubuntu × 3.14 with `--cov-fail-under=100`, must pass.
- **Integration tests** — 3 OS × Python 3.14, must pass. Fork tests
  run on the Linux runner only.

See [.github/workflows/common_checks.yml](.github/workflows/common_checks.yml)
for the exact job matrix.

## Deferred work

Test-related gaps not yet covered (resource leaks, validation gaps)
are tracked in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md), not here —
that's the single source of truth for in-flight cleanup work.
