# Testing Guide

## Overview

This document describes the test coverage, gaps, and testing strategy for the Olas Operate Middleware project.

## Test Organization

### Unit Tests (1,639 tests, ~2 minutes)
Fast tests with no external dependencies. Run with:
```bash
tox -e unit-tests
```

### Integration Tests (262 tests, ~7-10 minutes)
Tests requiring testnet RPC endpoints. Run with:
```bash
# Requires environment variables
export BASE_TESTNET_RPC="https://..."
export ETHEREUM_TESTNET_RPC="https://..."
export GNOSIS_TESTNET_RPC="https://..."
export OPTIMISM_TESTNET_RPC="https://..."
export POLYGON_TESTNET_RPC="https://..."

tox -e integration-tests
```

### Recorded HTTP tests (pytest-recording)

Several tests replay previously recorded HTTP responses using `pytest-recording` (VCR.py)
to eliminate flakiness from live RPC calls and reduce test execution time. These cassettes
are stored in `tests/cassettes/` and committed to git.

**Recorded tests**:

1. **`TestNativeBridgeProvider::test_find_block_before_timestamp`** (11 cassettes)
   - Records JSON-RPC requests to `https://rpc-gate.autonolas.tech/base-rpc/`
   - Cassettes stored in: `tests/cassettes/test_bridge_providers/TestNativeBridgeProvider.test_find_block_before_timestamp[...].yaml`
   - Execution time: ~0.78s (replayed), ~1-2min (live)
   
2. **`TestProvider::test_update_execution_status_failure_then_success`** (18 cassettes)
   - Records API calls from Relay provider (`https://api.relay.link/requests/v2`)
   - Records RPC calls to Optimism Tenderly endpoint
   - Cassettes stored in: `tests/cassettes/test_bridge_providers/TestProvider.test_update_execution_status_failure_then_success[...].yaml`
   - Covers RelayProvider, LiFiProvider, and NativeBridgeProvider
   
**Cassette Matching Strategy**:
The VCR configuration in `tests/conftest.py` matches requests on:
- `method`, `scheme`, `host`, `port`, `path`, `query`
- **`body`** (critical for JSON-RPC determinism)

This ensures different RPC payloads (e.g., different block numbers) match the correct cassettes.

**Re-recording cassettes**:
When API behavior changes, re-record cassettes with:
```bash
# Record all cassettes for a specific test
pytest tests/test_bridge_providers.py::TestNativeBridgeProvider::test_find_block_before_timestamp --record-mode=once -v

# Record for the other test
pytest tests/test_bridge_providers.py::TestProvider::test_update_execution_status_failure_then_success --record-mode=once -v

# Record all cassettes at once
pytest tests/test_bridge_providers.py -k "vcr" --record-mode=once -v
```

## Working with VCR Tests

### What is VCR?

VCR (Video Cassette Recorder) is a testing pattern that records HTTP interactions and replays them during subsequent test runs. This provides several benefits:

- **Deterministic tests**: Same results every time, no network flakiness
- **Fast execution**: No network latency (48-155x faster in our tests)
- **Offline testing**: Run tests without internet connectivity
- **Reduced costs**: Fewer API calls to external services
- **Reproducible**: Cassettes are versioned in git for regression testing

We use `pytest-recording` (a pytest plugin wrapping VCR.py) to implement this pattern.

### Running VCR Tests

**Normal test execution** (using cassettes):
```bash
# Run specific VCR test
pytest tests/test_bridge_providers.py::TestNativeBridgeProvider::test_find_block_before_timestamp -v

# Run all VCR tests
pytest tests/test_bridge_providers.py -m vcr -v

# VCR tests run as part of integration tests
tox -e integration-tests
```

Tests with recorded cassettes run automatically in replay mode—no special flags needed.

### Recording New Cassettes

**When to record:**
- First time running a new VCR test
- API endpoints change behavior
- Cassette files are deleted or corrupted
- Test parameters change (new parameterized test cases)

**How to record:**

1. **Delete old cassettes** (if re-recording):
   ```bash
   rm -rf tests/cassettes/test_bridge_providers/TestNativeBridgeProvider.test_find_block_before_timestamp*
   ```

2. **Record with `--record-mode=once`**:
   ```bash
   pytest tests/test_bridge_providers.py::TestNativeBridgeProvider::test_find_block_before_timestamp --record-mode=once -v
   ```

3. **Verify cassettes were created**:
   ```bash
   ls -lh tests/cassettes/test_bridge_providers/
   ```

4. **Test replay works**:
   ```bash
   pytest tests/test_bridge_providers.py::TestNativeBridgeProvider::test_find_block_before_timestamp -v
   ```

**Record modes:**
- `once` (default): Record if cassette missing, otherwise replay
- `new_episodes`: Add new interactions to existing cassette
- `all`: Rewrite entire cassette (use when API changes)
- `none`: Replay only, fail if cassette missing

### Writing Tests with VCR

**1. Mark the test with `@pytest.mark.vcr`:**

```python
@pytest.mark.vcr
def test_my_api_call(self):
    response = requests.get("https://api.example.com/data")
    assert response.status_code == 200
```

**2. For parameterized tests, each parameter set gets its own cassette:**

```python
@pytest.mark.vcr
@pytest.mark.parametrize("value", [1, 2, 3])
def test_with_params(self, value: int):
    response = requests.get(f"https://api.example.com/data/{value}")
    assert response.status_code == 200
```

This creates 3 cassettes, one per parameter value.

**3. Configure matching strategy (in `conftest.py` if needed):**

```python
@pytest.fixture(scope="module")
def vcr_config() -> dict:
    return {
        "match_on": ["method", "scheme", "host", "port", "path", "query", "body"]
    }
```

**Body matching is critical for JSON-RPC** where all requests go to the same URL but differ in payload.

### Editing Existing VCR Tests

**When modifying a test that uses VCR:**

1. **Understand what's recorded**: Check the cassette file to see what HTTP interactions are stored
   ```bash
   cat tests/cassettes/test_bridge_providers/TestProvider.test_update_execution_status[...].yaml
   ```

2. **If changing test logic** (not HTTP calls):
   - No re-recording needed
   - Just update assertions/test code

3. **If changing HTTP calls**:
   - Delete the cassette file
   - Re-record with `--record-mode=once`
   - Commit the new cassette

4. **If changing test parameters**:
   - Old cassettes for removed parameters can be deleted
   - New parameters need new cassettes recorded

### Troubleshooting VCR Tests

**Problem: Test fails with "No matching cassette"**
```
CannotOverwriteExistingCassetteException
```
**Solution**: Record the cassette:
```bash
pytest tests/test_file.py::test_name --record-mode=once
```

**Problem: Test passes on first run but fails on replay**
```
AssertionError: Expected X but got Y
```
**Solution**: The cassette might contain non-deterministic data (timestamps, random IDs).
- Check test assertions for time-sensitive data
- Use mocking for non-deterministic values
- Ensure cassette matching strategy is correct (especially for JSON-RPC)

**Problem: Cassette doesn't match the request**
```
requests.exceptions.ConnectionError: ... Please use --record-mode=once
```
**Solution**: The request changed but cassette wasn't updated.
- Check if URL, method, or body changed
- Re-record: `--record-mode=all` to overwrite
- Verify `match_on` configuration in `vcr_config` fixture

**Problem: Cassette file is too large (>1MB)**
```
Git complains about large files
```
**Solution**: 
- Review what's being recorded—might need to use `vcr.filter_headers` or `vcr.filter_post_data_parameters`
- Consider if this test should use VCR or mock the responses instead
- For large response bodies, consider using `before_record_response` to truncate data

**Problem: Test works locally but fails in CI**
```
Test passes with live network but fails with cassette
```
**Solution**:
- Ensure cassettes are committed to git
- Check `.gitignore` doesn't exclude cassette files
- Verify cassette paths are relative, not absolute

### Best Practices

**DO:**
- ✅ Commit cassettes to git for team reproducibility
- ✅ Use `@pytest.mark.vcr` on tests that make HTTP calls
- ✅ Configure body-matching for JSON-RPC endpoints
- ✅ Keep cassettes small (filter unnecessary headers/data)
- ✅ Document what external APIs are being recorded
- ✅ Re-record cassettes when APIs change

**DON'T:**
- ❌ Record sensitive data (API keys, passwords) in cassettes
- ❌ Use VCR for tests that need live network validation
- ❌ Commit cassettes with non-deterministic data
- ❌ Mix VCR and mocking for the same HTTP call
- ❌ Use VCR for WebSocket or streaming connections

### VCR Configuration Reference

The project's VCR configuration is in `tests/conftest.py`:

```python
@pytest.fixture(scope="module")
def vcr_config() -> t.Dict[str, t.Any]:
    """VCR configuration for deterministic JSON-RPC request matching."""
    return {
        "match_on": ["method", "scheme", "host", "port", "path", "query", "body"],
        # Can also add:
        # "filter_headers": ["authorization"],  # Remove sensitive headers
        # "record_mode": "once",  # Default record mode
    }
```

For more VCR options, see [VCR.py documentation](https://vcrpy.readthedocs.io/).

## Test Coverage

**100% unit test coverage** is enforced across the entire `operate/` package (7,580 statements). CI fails if coverage drops below 100% (`--cov-fail-under=100`).

The only exclusion is `operate/pearl.py`, which is a PyInstaller entry point not executable in unit-test context (excluded via `.coveragerc`).

### Coverage by test file

| Test file | Key modules covered |
|-----------|---------------------|
| `test_operate_types.py` | `operate/operate_types.py` |
| `test_keys.py` | `operate/keys.py` |
| `test_resource.py` | `operate/resource.py` |
| `test_operate_init.py` | `operate/__init__.py` |
| `test_operate_http.py` | `operate/operate_http/` |
| `test_cli_unit.py` | `operate/cli.py` (175 tests) |
| `test_manage_unit.py` | `operate/services/manage.py` (56 tests) |
| `test_service_unit2.py` | `operate/services/service.py` |
| `test_deployment_runner_unit2.py` | `operate/services/deployment_runner.py` |
| `test_funding_manager_unit2.py` | `operate/services/funding_manager.py` |
| `test_protocol_unit2.py` | `operate/services/protocol.py` |
| `test_health_checker_*.py` | `operate/services/health_checker.py` |
| `test_single_instance.py` | `operate/utils/single_instance.py` |
| `test_tendermint_unit.py` | `operate/services/utils/tendermint.py` |
| `test_wallet_master_unit.py` | `operate/wallet/master.py` |
| `test_bridge_manager.py` | `operate/bridge/bridge_manager.py` |
| `test_bridge_providers.py` | `operate/bridge/providers/` |
| `test_quickstart_unit.py` | `operate/quickstart/` (92 tests) |
| `test_utils.py` | `operate/utils/` |
| `test_ssl.py` | `operate/utils/ssl.py` |
| `test_contracts.py` | contract interfaces |

### `# pragma: no cover` policy

Pragmas are used sparingly for code that genuinely cannot be reached in unit tests:

- **Dead code / defensive branches** — e.g., `TYPE_CHECKING` blocks, unreachable `else` clauses
- **Pure I/O wrappers** — thin wrappers over `print`, `input`, `Halo` spinner that test nothing when mocked
- **Blockchain-interactive orchestration** — high-level functions in quickstart that chain multiple blockchain calls; tested end-to-end via integration tests
- **Subprocess wrappers** — one-liner wrappers over `subprocess.run` in `tendermint.py`

Pragmas are **not** used to skip real business logic.

## Test Quality Notes

### Integration tests still rely on live networks

The integration tests in `test_services_manage.py`, `test_services_funding.py`, `test_wallet_master.py`, and `test_bridge_providers.py` make real RPC calls to Tenderly testnets. This is intentional for end-to-end validation but means:
- Slow execution (~7-10 minutes)
- Require RPC environment variables
- Rate-limited to Ubuntu/Linux in CI (see `OnTestnet` class in `conftest.py`)

### Deferred improvements

See `RESOURCE_LEAKS.md` and `VALIDATION_GAPS.md` for documented gaps that are deferred to Phase 3.

## Test Markers

Tests are marked for easy filtering:

```python
@pytest.mark.unit          # Pure unit tests
@pytest.mark.integration   # Integration tests (requires RPC)
@pytest.mark.requires_rpc  # Explicitly requires RPC endpoints
```

Run specific categories:
```bash
# Only unit tests
pytest -m "unit"

# Only integration tests
pytest -m "integration"

# Exclude integration tests
pytest -m "not integration"
```

## CI/CD Testing Strategy

### Current Strategy
- **Linter checks**: Run first, must pass
- **Unit tests**: Run in parallel on 3 OS × 2 Python versions (3.10, 3.11), must pass
- **Coverage**: Run on Ubuntu Python 3.10 with `--cov-fail-under=100`, must pass
- **Integration tests**: Run in parallel on 3 OS × Python 3.10, can fail (`continue-on-error: true`)

### Platform-Specific Test Behavior

**Important**: Tests inheriting from `OnTestnet` (in `tests/conftest.py`) only run on **Ubuntu/Linux** in CI:

```python
pytestmark = pytest.mark.skipif(
    RUNNING_IN_CI and system() != "Linux",
    reason="To avoid exhausting tenderly limits.",
)
```

**Affected test classes**:
- `TestFunding` (`test_services_funding.py`)
- Tests using Tenderly testnet simulation

**Why**: To conserve Tenderly API usage limits, these integration tests are skipped on Windows and macOS when running in CI. Locally, they run on all platforms.

### Recommended Improvements
1. Run unit tests on every commit (already done)
2. Run integration tests on main/staging only
3. Add nightly integration test runs with full coverage
4. Add performance regression tests weekly
5. Generate and track coverage reports

## Coverage Metrics

| Metric | Value |
|--------|-------|
| Total statements | 7,580 |
| Missing | 0 |
| Coverage | **100%** |
| Total unit tests | 1,639 |
| CI enforcement | `--cov-fail-under=100` |

## Contributing Tests

When adding new tests:

1. **Choose the right type**: Unit test if possible, integration only if necessary
2. **Use appropriate markers**: Add `@pytest.mark.integration` if it needs RPC
3. **Mock external services**: Use `requests-mock`, `pytest-mock`, or fixtures
4. **Follow naming conventions**: `test_<component>_<scenario>_<expected>`
5. **Add docstrings**: Explain what the test validates
6. **Test edge cases**: Don't just test happy paths
7. **Keep tests fast**: Unit tests should run in milliseconds
8. **Make tests deterministic**: Avoid flaky tests, fix timing issues

Example:
```python
@pytest.mark.unit
def test_version_parsing_with_local_identifier() -> None:
    """Test that Version class handles local identifiers correctly."""
    version = Version("1.2.3+local")
    assert version.major == 1
    assert version.minor == 2
    assert version.patch == 3
```

## Resources

- **Pytest Documentation**: https://docs.pytest.org/
- **Testing Best Practices**: https://docs.pytest.org/en/latest/goodpractices.html
- **Mocking Guide**: https://requests-mock.readthedocs.io/
- **Coverage Tools**: https://coverage.readthedocs.io/
