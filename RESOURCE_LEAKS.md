# Resource Leak Analysis

This document tracks known resource leaks in the codebase that need future cleanup.

## File Handle Leaks in deployment_runner.py

**Status:** Fixed (2026-02-25)
**Priority:** Low
**Impact:** Minor - OS cleans up on subprocess termination

### Issue Description

Log file handles are opened but never explicitly closed in the subprocess management code.

**Affected Code:**
- `operate/services/deployment_runner.py:122` - `_open_agent_runner_log_file()`
- `operate/services/deployment_runner.py:126` - `_open_tendermint_log_file()`

**Usage Pattern:**
```python
# File opened without context manager
agent_runner_log_file = self._open_agent_runner_log_file()

# Passed to subprocess as stdout/stderr
process = subprocess.Popen(
    args=...,
    stdout=agent_runner_log_file,
    stderr=agent_runner_log_file,  # File handle kept by subprocess
    ...
)

# Process runs...
# File handle never explicitly closed
```

**Used In:**
- Line 515: `_start_agent_process()`
- Line 534: `_start_tendermint_process()`
- Line 635: Agent process start (LocalDockerDeploymentRunner)
- Line 654: Tendermint process start (LocalDockerDeploymentRunner)
- Line 688: Agent process start (LocalDeploymentRunner)

### Why This Is (Currently) Acceptable

1. **OS Cleanup:** When the subprocess terminates, the OS automatically closes all file descriptors owned by that process
2. **Low Frequency:** Service starts/stops happen infrequently (not in tight loops)
3. **No Accumulation:** File handles don't accumulate because processes are long-running
4. **Single Instance:** Typically only one agent and one tendermint process per service

### Why We Should Still Fix It

1. **Best Practices:** Explicit resource management is clearer and more robust
2. **Rapid Restarts:** Rapid service restart cycles could temporarily accumulate handles
3. **Clean Shutdown:** Proper cleanup ensures clean shutdown behavior
4. **Testing:** Integration tests that rapidly start/stop services could accumulate handles

### Proposed Solution

**Option 1: Store File Handle References (Recommended)**
```python
class BaseDeploymentRunner:
    def __init__(self, work_directory: Path) -> None:
        self._work_directory = work_directory
        self.logger = _default_logger
        # NEW: Track file handles for cleanup
        self._agent_log_file: Optional[TextIOWrapper] = None
        self._tm_log_file: Optional[TextIOWrapper] = None

    def _start_agent_process(self, env: Dict, working_dir: Path, password: str) -> subprocess.Popen:
        """Start agent process."""
        # Store handle for later cleanup
        self._agent_log_file = self._open_agent_runner_log_file()
        process = subprocess.Popen(
            args=self.get_agent_start_args(password=password),
            stdout=self._agent_log_file,
            stderr=self._agent_log_file,
            ...
        )
        return process

    def _stop_agent(self) -> None:
        """Stop agent process."""
        # ... existing PID file logic ...

        # NEW: Close log file if open
        if self._agent_log_file is not None:
            try:
                self._agent_log_file.close()
            except Exception as e:
                self.logger.debug(f"Error closing agent log file: {e}")
            finally:
                self._agent_log_file = None
```

**Option 2: Context Manager Approach**

Restructure process lifecycle to use context managers:
```python
def start_service(self):
    with self._open_agent_runner_log_file() as log_file:
        with self._managed_process(..., stdout=log_file) as process:
            # Process lifecycle managed here
            ...
```

This requires significant restructuring and may not fit the current architecture.

**Option 3: Subprocess Context Manager Wrapper**

Create a wrapper that manages both process and file handles:
```python
class ManagedSubprocess:
    def __init__(self, process: subprocess.Popen, log_file: TextIOWrapper):
        self.process = process
        self.log_file = log_file

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.log_file.close()
        # Process cleanup...
```

### Implementation (Option 1 — applied)

`BaseDeploymentRunner` now tracks open log file handles:
- `_agent_log_file: Optional[TextIOWrapper]` — set by each `_start_agent_process` / `_start_agent` call
- `_tm_log_file: Optional[TextIOWrapper]` — set by each `_start_tendermint_process` call
- `_close_agent_log_file()` — closes and clears `_agent_log_file`; called unconditionally in `_stop_agent()`
- `_close_tm_log_file()` — closes and clears `_tm_log_file`; called unconditionally in `_stop_tendermint()`

All close calls use `suppress(Exception)` to avoid masking shutdown errors.

Tests added to `tests/test_deployment_runner_unit2.py` (`TestCloseLogFiles`).

## Other Resource Leak Checks

### Network Sessions ✅

**Status:** No leaks found

All `aiohttp.ClientSession` instances properly use `async with` context managers:
- `operate/services/health_checker.py:116` - ✅ Correct usage

### Subprocess Management ✅

**Status:** Acceptable

Subprocesses are properly tracked via PID files and killed in `_stop_agent()` / `_stop_tendermint()`. No subprocess zombies or orphans detected.

## Monitoring Recommendations

To detect resource leaks in production:

```python
import resource

# Monitor file descriptors
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
current_fds = len(os.listdir('/proc/self/fd'))  # Linux

# Log metrics
logger.info(f"Open file descriptors: {current_fds}/{soft}")
```

Add to health check endpoint:
```json
{
  "is_healthy": true,
  "resource_usage": {
    "open_files": 42,
    "max_files": 1024
  }
}
```

---

**Last Updated:** 2026-02-10
**Next Review:** After Phase 1 completion
