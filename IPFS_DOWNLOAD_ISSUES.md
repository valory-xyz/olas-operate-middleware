# IPFS Download Issues

Analysis of network-related failures in service creation and testing.

**Date:** 2026-02-10
**Status:** Documented - Fix Pending
**Priority:** Medium (affects production reliability)

---

## Issue Summary

Service creation fails when IPFS downloads timeout or encounter network errors. This affects both production users and CI test reliability.

### Symptoms

1. **Production**: Users get 500 Internal Server Error when creating services
2. **CI Tests**: Integration tests fail with `ReadTimeoutError: HTTPSConnectionPool(host='registry.autonolas.tech', port=443): Read timed out`
3. **State Corruption**: Partial service directories left on disk when creation fails

---

## Root Cause Analysis

### The Flow

```
User → POST /api/v2/service
  ↓
_create_services_v2() [NO ERROR HANDLING]
  ↓
manager.create(service_template)
  ↓
Service.new()
  ↓
IPFSTool().download() ← FAILS: ConnectionError/TimeoutError
  ↓
Exception bubbles up (uncaught)
  ↓
FastAPI returns 500 Internal Server Error
```

### Code Location

**File:** `operate/cli.py:1240-1249`

```python
@app.post("/api/v2/service")
async def _create_services_v2(request: Request) -> JSONResponse:
    """Create a service."""
    if operate.password is None:
        return USER_NOT_LOGGED_IN_ERROR
    template = await request.json()
    manager = operate.service_manager()
    output = manager.create(service_template=template)  # ❌ NO ERROR HANDLING

    return JSONResponse(content=output.json)
```

**File:** `operate/services/service.py:887-890`

```python
package_absolute_path = Path(
    IPFSTool().download(
        hash_id=service_template["hash"],
        target_dir=path,
    )
)  # Can raise ConnectionError, ReadTimeoutError
```

### Exception Types

From stack trace analysis:

1. **`socket.timeout` / `TimeoutError`** - SSL socket read timeout
2. **`urllib3.exceptions.ReadTimeoutError`** - HTTP connection read timeout
3. **`requests.exceptions.ConnectionError`** - Wrapped connection errors
4. **Raised during**: `tarfile.extractall()` while reading IPFS tarball chunks

---

## Impact Assessment

### Production Impact

**For Users:**
- ❌ Service creation randomly fails with unhelpful errors
- ❌ No indication whether to retry or contact support
- ❌ Partial service state left on disk (must be manually cleaned)
- ❌ Service ID counter incremented but service unusable

**Error Message Received:**
```json
{
  "error": "Internal Server Error"
}
```

**What They Need:**
```json
{
  "error": "Service creation failed",
  "message": "Unable to download service package from IPFS. This may be due to network issues or IPFS registry unavailability. Please try again.",
  "type": "ipfs_download_error",
  "retry_recommended": true
}
```

### CI/Test Impact

**Flaky Tests:**
- `test_service_manager_update[...]` - 64 parameterized variants
- All tests that call `service_manager.create()` with real IPFS downloads
- Failure rate: ~5-10% depending on IPFS registry load

**Example CI Failure:**
```
urllib3.exceptions.ReadTimeoutError:
HTTPSConnectionPool(host='registry.autonolas.tech', port=443): Read timed out.

During handling of the above exception, another exception occurred:
requests.exceptions.ConnectionError:
HTTPSConnectionPool(host='registry.autonolas.tech', port=443): Read timed out.
```

---

## Why IPFS Downloads Fail

### Network Factors

1. **Registry Load** - `registry.autonolas.tech` under high load
2. **Network Latency** - CI runners in different regions with varying latency
3. **Large Tarballs** - Service packages can be several MB
4. **Timeout Settings** - Default timeouts too aggressive for slow connections

### IPFS Specifics

- Uses chunked transfer encoding
- Tarball extraction reads chunks incrementally
- Socket timeout during chunk read causes failure
- No automatic retry in ipfshttpclient library

---

## Proposed Solutions

### 1. Add Error Handling to Service Creation Endpoint (HIGH PRIORITY)

**Location:** `operate/cli.py:1240-1249`

```python
@app.post("/api/v2/service")
async def _create_services_v2(request: Request) -> JSONResponse:
    """Create a service."""
    if operate.password is None:
        return USER_NOT_LOGGED_IN_ERROR

    template = await request.json()
    manager = operate.service_manager()

    try:
        output = manager.create(service_template=template)
        return JSONResponse(content=output.json)

    except (ConnectionError, ReadTimeoutError) as e:
        # Network/IPFS download failure
        logger.error(
            f"IPFS download failed during service creation: {e}",
            exc_info=True,
            extra={"service_hash": template.get("hash")}
        )

        # TODO: Clean up partial service directory

        return JSONResponse(
            content={
                "error": "Service creation failed",
                "message": "Unable to download service package from IPFS. "
                          "This may be due to network issues or IPFS registry unavailability. "
                          "Please try again in a few moments.",
                "type": "ipfs_download_error",
                "retry_recommended": True,
                "details": str(e)
            },
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,  # 503
        )

    except Exception as e:
        # Unexpected errors
        logger.error(f"Unexpected error during service creation: {e}", exc_info=True)
        return JSONResponse(
            content={
                "error": "Service creation failed",
                "message": "An unexpected error occurred. Please contact support.",
                "type": "internal_error"
            },
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,  # 500
        )
```

**Benefits:**
- ✅ Users get actionable error messages
- ✅ Distinguishes network errors from app bugs
- ✅ Returns appropriate HTTP status (503 for unavailable service)
- ✅ Logs with full context for debugging

### 2. Add Retry Logic to IPFS Downloads (MEDIUM PRIORITY)

**Location:** `operate/aea_cli_ipfs/ipfs_utils.py` or wrapper in `operate/services/service.py`

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
def download_with_retry(ipfs_tool, hash_id: str, target_dir: Path) -> str:
    """Download from IPFS with automatic retry on timeout."""
    try:
        return ipfs_tool.download(hash_id=hash_id, target_dir=target_dir)
    except (ConnectionError, ReadTimeoutError) as e:
        logger.warning(f"IPFS download failed, retrying: {e}")
        raise  # tenacity will retry
```

**Benefits:**
- ✅ Handles transient network issues automatically
- ✅ Exponential backoff prevents hammering IPFS registry
- ✅ Transparent to callers

**Considerations:**
- Requires `tenacity` dependency
- Increases service creation time on persistent failures (3 attempts)

### 3. Increase IPFS Timeout (LOW PRIORITY, QUICK FIX)

**Location:** IPFS client configuration

```python
# Make timeout configurable via environment variable
IPFS_DOWNLOAD_TIMEOUT = int(os.getenv("IPFS_DOWNLOAD_TIMEOUT", "300"))  # 5 min

# Apply to ipfshttpclient
client = ipfshttpclient.Client(timeout=IPFS_DOWNLOAD_TIMEOUT)
```

**Benefits:**
- ✅ Simple implementation
- ✅ CI can use longer timeouts
- ✅ Reduces flakiness

**Limitations:**
- ❌ Doesn't fix root cause
- ❌ Just makes timeouts less likely

### 4. Clean Up Partial State on Failure (HIGH PRIORITY)

**Location:** `operate/cli.py` (in exception handler) or `operate/services/service.py`

```python
def create_service_with_cleanup(manager, service_template):
    """Create service with automatic cleanup on failure."""
    service_id = None
    try:
        service = manager.create(service_template=service_template)
        return service
    except Exception as e:
        # Clean up partial service directory if created
        if service_id:
            service_dir = manager.path / service_id
            if service_dir.exists():
                logger.warning(f"Cleaning up partial service {service_id}")
                shutil.rmtree(service_dir)
        raise
```

**Benefits:**
- ✅ Prevents corrupt state
- ✅ Service IDs can be reused
- ✅ No manual cleanup required

---

## Test Reliability

### Marking Flaky Tests

**File:** `tests/test_services_manage.py`

Mark tests that make real IPFS downloads as flaky:

```python
import pytest

@pytest.mark.integration
@pytest.mark.flaky(reruns=2, reruns_delay=5)
@pytest.mark.parametrize(...)
def test_service_manager_update(...):
    """Test service manager update (may be flaky due to IPFS downloads)."""
    ...
```

**Benefits:**
- ✅ Acknowledges network dependency
- ✅ Automatically retries failed tests
- ✅ Reduces false-negative CI failures

**Installed:** Requires `pytest-rerunfailures` plugin (check if already installed)

---

## Recommended Implementation Order

### Phase 1: Quick Fixes (1-2 days)
1. ✅ Mark flaky tests with `@pytest.mark.flaky`
2. ✅ Add error handling to `/api/v2/service` endpoint
3. ✅ Document issue (this file)

### Phase 2: Robust Solutions (3-5 days)
4. ⏳ Add retry logic to IPFS downloads
5. ⏳ Implement partial state cleanup
6. ⏳ Add configurable timeouts

### Phase 3: Long-term (Future)
7. ⏳ Consider caching frequently-used IPFS packages
8. ⏳ Add health checks for IPFS registry availability
9. ⏳ Implement service creation job queue for better failure handling

---

## Monitoring Recommendations

### Metrics to Track

1. **Service Creation Failure Rate**
   - Track: IPFS download failures vs total attempts
   - Alert: >5% failure rate in production

2. **IPFS Download Times**
   - Track: P50, P95, P99 download latencies
   - Alert: P95 > 30 seconds

3. **Retry Success Rate**
   - Track: How many failures succeed on retry
   - Insight: Validates retry logic effectiveness

### Logging Enhancements

```python
logger.error(
    "IPFS download failed",
    exc_info=True,
    extra={
        "service_hash": template["hash"],
        "registry_host": "registry.autonolas.tech",
        "download_timeout": IPFS_DOWNLOAD_TIMEOUT,
        "user_id": user_id,  # if available
        "retry_count": attempt_number,
    }
)
```

---

## References

- **Issue:** CI test flakiness in `test_service_manager_update`
- **Error:** `urllib3.exceptions.ReadTimeoutError` during IPFS download
- **Related:** Phase 1.2 error handling improvements (PR #334)
- **IPFS Client:** `ipfshttpclient` library (used via `aea_cli_ipfs`)

---

**Last Updated:** 2026-02-10
**Status:** Documented - Awaiting Implementation
**Next Steps:** Implement Phase 1 fixes (error handling + flaky test markers)
