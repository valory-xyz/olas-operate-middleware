# Testing Guide

## Overview

This document describes the test coverage, gaps, and testing strategy for the Olas Operate Middleware project.

## Test Organization

### Unit Tests (130 tests, ~2 minutes)
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

## Test Coverage by Component

### ✅ Good Coverage

#### Core Types (`test_operate_types.py`)
- **Coverage**: Excellent
- **Tests**: 9 unit tests
- **What's tested**:
  - Version comparison and parsing
  - ChainAmounts arithmetic operations (add, subtract, multiply, divide)
  - Immutability guarantees
  - Edge cases (division by zero, negative results)

#### Service Configuration (`test_services_service.py`)
- **Coverage**: Good
- **Tests**: Multiple tests for service config management
- **What's tested**:
  - Service configuration creation and updates
  - Hash history tracking
  - Service state transitions
  - Configuration validation

#### Keys Management (`test_keys.py`)
- **Coverage**: Good
- **What's tested**:
  - Key generation and storage
  - Encryption/decryption
  - Key file management

#### API Endpoints (`test_api.py`)
- **Coverage**: Good for core endpoints
- **What's tested**:
  - Account creation and authentication
  - Password management
  - Basic wallet operations
  - Settings management

#### Contract Interfaces (`test_contracts.py`)
- **Coverage**: Good
- **What's tested**:
  - Contract ABI loading
  - Contract wrapper functionality

### ⚠️ Partial Coverage

#### Service Management (`test_services_manage.py`)
- **Coverage**: Good for integration, limited unit coverage
- **Tests**: 170+ parameterized integration tests
- **What's tested**:
  - Service CRUD operations
  - Partial updates with various combinations
  - Refill requirement calculations
- **Gaps**:
  - Heavy reliance on real testnets
  - Limited mocking of blockchain interactions
  - Slow test execution due to network calls

#### Wallet Management (`test_wallet_master.py`)
- **Coverage**: Good for integration flows
- **Tests**: 10+ integration tests
- **What's tested**:
  - Master EOA/Safe creation
  - Fund transfers
  - Multi-chain operations
- **Gaps**:
  - No unit tests with mocked blockchain
  - All tests require live testnet RPCs
  - Recovery scenarios could use more coverage

#### Bridge Operations (`test_bridge_*.py`)
- **Coverage**: Good for provider interfaces
- **Tests**: Multiple tests for bridge providers
- **What's tested**:
  - Bridge quote requests
  - Transaction execution
  - Provider-specific logic
- **Gaps**:
  - No mocking of bridge provider APIs
  - Limited error scenario coverage
  - Rate limiting not tested

### ❌ Limited or Missing Coverage

#### Deployment Runner (`operate/services/deployment_runner.py`)
- **Coverage**: Limited
- **Tests**: Tested indirectly through service tests
- **Gaps**:
  - No dedicated unit tests
  - Docker interaction not mocked
  - Process management edge cases not tested

#### Health Checker (`operate/services/health_checker.py`)
- **Coverage**: Limited
- **Tests**: Tested indirectly
- **Gaps**:
  - No dedicated tests for health monitoring logic
  - File parsing edge cases not tested
  - Timeout scenarios not tested

#### Funding Manager (`operate/services/funding_manager.py`)
- **Coverage**: Integration tests only
- **Tests**: Part of `test_services_funding.py`
- **Gaps**:
  - Cooldown mechanism not unit tested
  - Race condition scenarios not tested
  - Insufficient balance handling could be more comprehensive

#### Migration (`operate/migration.py`)
- **Coverage**: Limited
- **Tests**: Some tests in `test_operate_cli.py`
- **Gaps**:
  - Version migration paths not fully tested
  - Backup/restore scenarios incomplete
  - Edge cases (corrupted data) not tested

#### CLI Commands (`operate/cli.py`)
- **Coverage**: Limited
- **Tests**: Basic tests in `test_operate_cli.py`
- **Gaps**:
  - Many CLI commands not tested
  - Argument parsing not comprehensively tested
  - Error handling paths not covered

#### Wallet Recovery (`operate/wallet/wallet_recovery_manager.py`)
- **Coverage**: Integration tests only
- **Tests**: 4 integration tests in `test_wallet_wallet_recovery.py`
- **Gaps**:
  - No unit tests with mocked blockchain
  - Edge cases (partial recovery, failed swaps) need more coverage
  - Multi-chain recovery scenarios incomplete

## Test Quality Issues

### Heavy Reliance on Live Networks

**Problem**: Many tests make real RPC calls to testnets
- Slow execution (7-10 minutes for integration tests)
- Flaky due to network issues
- Rate limiting from RPC providers
- Costs (Tenderly usage)

**Files affected**:
- `test_services_manage.py`
- `test_services_funding.py`
- `test_wallet_master.py`
- `test_bridge_providers.py`

**Improvement needed**: Mock RPC calls using `responses` or `requests-mock`

### Limited Error Scenario Testing

**Problem**: Tests primarily cover happy paths
- Insufficient balance scenarios
- Network failures
- Invalid configurations
- Timeout scenarios
- Race conditions

**Improvement needed**: Add negative test cases for all major operations

### Test Data Management

**Problem**: Test data scattered across files
- Magic numbers in tests
- Duplicated test fixtures
- Unclear test data relationships

**Files affected**: Multiple test files use inline data

**Improvement needed**:
- Centralize test data in fixtures
- Use factory functions for test objects
- Document test data relationships

## Missing Test Categories

### Performance Tests
- No tests for performance degradation
- No load testing for API endpoints
- No benchmarks for critical operations

### Security Tests
- No tests for authentication edge cases
- No tests for authorization bypasses
- No tests for rate limiting
- No tests for input sanitization

### Concurrency Tests
- No tests for concurrent service operations
- No tests for race conditions in funding
- No tests for parallel API requests

### Upgrade/Migration Tests
- Limited tests for version migrations
- No tests for backward compatibility
- No tests for data corruption recovery

## Recommendations

### High Priority

1. **Mock RPC calls in unit tests**
   - Use `responses` or `requests-mock`
   - Create fixtures for common RPC responses
   - Separate true unit tests from integration tests

2. **Add error scenario tests**
   - Test insufficient balance cases
   - Test network failure handling
   - Test invalid input handling

3. **Add tests for Health Checker**
   - File parsing logic
   - Timeout scenarios
   - Error detection

4. **Add tests for Deployment Runner**
   - Docker interaction mocking
   - Process lifecycle management
   - Error recovery

### Medium Priority

5. **Improve test data management**
   - Create test data factories
   - Centralize fixtures
   - Document test scenarios

6. **Add concurrency tests**
   - Test parallel service operations
   - Test funding race conditions
   - Test API concurrent requests

7. **Add migration tests**
   - Test all version upgrade paths
   - Test rollback scenarios
   - Test corrupted data recovery

### Low Priority

8. **Add performance tests**
   - Benchmark critical operations
   - Load test API endpoints
   - Profile memory usage

9. **Add security tests**
   - Test authentication flows
   - Test authorization boundaries
   - Test rate limiting

10. **Improve integration test speed**
    - Use local test networks
    - Implement test network snapshots
    - Parallel test execution

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
- **Unit tests**: Run in parallel on 3 OS × 2 Python versions, must pass
- **Integration tests**: Run in parallel on 3 OS × 1 Python version, can fail (`continue-on-error: true`)

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

Current estimated coverage by component:

| Component | Coverage | Quality |
|-----------|----------|---------|
| Core Types | 95% | ⭐⭐⭐⭐⭐ |
| Service Config | 85% | ⭐⭐⭐⭐ |
| Keys Management | 80% | ⭐⭐⭐⭐ |
| API Endpoints | 75% | ⭐⭐⭐⭐ |
| Wallet Management | 70% | ⭐⭐⭐ |
| Service Management | 65% | ⭐⭐⭐ |
| Bridge Operations | 60% | ⭐⭐⭐ |
| Funding Manager | 50% | ⭐⭐ |
| Health Checker | 40% | ⭐⭐ |
| Deployment Runner | 35% | ⭐⭐ |
| Migration | 30% | ⭐ |
| CLI Commands | 25% | ⭐ |

**Overall estimated coverage: ~60%**

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
