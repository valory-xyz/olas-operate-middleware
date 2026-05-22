# Testing Guide

How tests are organised in this repo, how to run them, and the rules
CI enforces. Generic pytest / VCR tutorial material lives in upstream
docs; this file documents only what's specific to operate-middleware.

## Test Organization

### Unit Tests (~1,640 tests, ~2 minutes)

Fast tests with no external dependencies. Run with:

```bash
uv run tox -e unit-tests
```

### Integration Tests (~260 tests, slow)

Tests requiring testnet RPC endpoints. **Run selectively** — full
suite takes 7-10 minutes and burns Tenderly quota.

```bash
export BASE_TESTNET_RPC="https://..."
export ETHEREUM_TESTNET_RPC="https://..."
export GNOSIS_TESTNET_RPC="https://..."
export OPTIMISM_TESTNET_RPC="https://..."
export POLYGON_TESTNET_RPC="https://..."

uv run tox -e integration-tests -- path/to/test -v
```

By default runs with `pytest-xdist` in parallel (`-n auto`); CI
overrides to `-n 8`. To debug or narrow parallelism locally:

```bash
export CI=true
export PYTEST_XDIST_WORKERS=2
uv run tox -e integration-tests -- path/to/test -v
```

### Recorded HTTP tests (pytest-recording)

Some tests replay previously recorded HTTP responses via
`pytest-recording` (VCR.py wrapper) instead of hitting live RPC.
Cassettes live in `tests/cassettes/` and are committed to git. This
is a deterministic-replay system, not a mock — re-record when the
upstream API actually changes.

**Tests that use VCR cassettes today:**

| Test | What's recorded |
|---|---|
| `TestNativeBridgeProvider::test_find_block_before_timestamp` | 11 cassettes — Base RPC JSON-RPC requests |
| `TestProvider::test_update_execution_status_failure_then_success` | 18 cassettes — Relay API + Optimism Tenderly RPC |

**Cassette matching strategy** (configured in [tests/conftest.py](tests/conftest.py)):
`method, scheme, host, port, path, query, body`. Body-matching is
critical for JSON-RPC where every request hits the same URL and
differs only in payload.

**Re-recording cassettes:**

```bash
# Delete old cassette(s) first
rm tests/cassettes/test_bridge_providers/<TestClass>.<test_name>*

# Re-record
uv run pytest tests/test_bridge_providers.py::<TestClass>::<test_name> \
  --record-mode=once -v
```

For VCR fundamentals (record modes, filter_headers, parameterised
tests), see the [VCR.py docs](https://vcrpy.readthedocs.io/) — we
don't duplicate them here.

## Test Coverage

**100% unit test coverage** is enforced across the `operate/`
package (~7,580 statements). CI fails on any drop
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

Integration tests in `test_services_manage.py`,
`test_services_funding.py`, `test_wallet_master.py`, and
`test_bridge_providers.py` make real RPC calls to Tenderly testnets.
This is intentional for end-to-end validation but means slow runs,
RPC env vars required, and rate-limit pressure on Tenderly.

To conserve Tenderly quota, tests inheriting from `OnTestnet` (in
`tests/conftest.py`) are skipped on Windows and macOS **in CI**:

```python
pytestmark = pytest.mark.skipif(
    RUNNING_IN_CI and system() != "Linux",
    reason="To avoid exhausting tenderly limits.",
)
```

Locally they run on every platform.

## CI Strategy

- **Linter checks** — run first, must pass.
- **Unit tests** — 3 OS × 5 Python versions (3.10–3.14), must pass.
- **Coverage** — Ubuntu × 3.14 with `--cov-fail-under=100`, must pass.
- **Integration tests** — 3 OS × Python 3.14, must pass.

See [.github/workflows/common_checks.yml](.github/workflows/common_checks.yml)
for the exact job matrix.

## Deferred work

Test-related gaps not yet covered (resource leaks, validation gaps)
are tracked in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md), not here —
that's the single source of truth for in-flight cleanup work.
