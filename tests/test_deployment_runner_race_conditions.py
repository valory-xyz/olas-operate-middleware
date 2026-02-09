"""
Tests for deployment_runner race conditions.

Part of Phase 1.3: Race Condition Fixes - implementing proper file locking,
PID validation, and stale PID handling.
"""

import platform
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import psutil
import pytest

from operate.services.deployment_runner import DeploymentManager


class TestPIDFileRaceConditions:
    """Test PID file race conditions in deployment_runner.

    Current issues:
    1. No file locking - multiple threads can read/write PID files simultaneously
    2. No PID validation - doesn't check if process exists or matches expected command
    3. No stale PID handling - doesn't clean up or validate old PID files

    These tests demonstrate the race conditions that need to be fixed.
    """

    @pytest.fixture
    def deployment_manager(self) -> DeploymentManager:
        """Create a DeploymentManager instance for testing."""
        manager = DeploymentManager()
        manager.logger = MagicMock()
        return manager

    def test_pid_file_concurrent_write_race_condition(
        self, tmp_path: Path
    ) -> None:
        """Test that concurrent PID writes can cause race condition (to be fixed).

        Scenario: Two threads try to start the same process and write PID files.
        Without locking, second write can overwrite first, losing track of first process.
        """
        pid_file = tmp_path / "agent.pid"
        results = []

        def write_pid(pid: int) -> None:
            """Simulate writing PID without lock."""
            # Read-modify-write pattern without lock
            time.sleep(0.001)  # Simulate processing delay
            pid_file.write_text(str(pid), encoding="utf-8")
            # Verify what was written
            time.sleep(0.001)
            written = int(pid_file.read_text(encoding="utf-8"))
            results.append((pid, written))

        # Two threads write different PIDs
        thread1 = threading.Thread(target=write_pid, args=(12345,))
        thread2 = threading.Thread(target=write_pid, args=(67890,))

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        # Race condition: second write overwrites first
        # One thread writes PID but reads different PID (from other thread)
        final_pid = int(pid_file.read_text(encoding="utf-8"))
        assert final_pid in (12345, 67890)

        # At least one thread should see inconsistency (wrote X, read Y)
        # This demonstrates the race condition
        wrote_pids = [r[0] for r in results]
        read_pids = [r[1] for r in results]
        # If both threads wrote but only one PID remains, we have a race condition
        assert len(set(wrote_pids)) == 2  # Two different PIDs written
        # Verify race condition can occur
        _ = read_pids  # Acknowledge variable used for demonstration
        # Note: This test demonstrates the problem but doesn't always fail
        # In a real race condition, timing determines if we see the issue

    def test_pid_file_read_during_write_race_condition(
        self, tmp_path: Path
    ) -> None:
        """Test that reading PID during write can get partial data (to be fixed).

        Scenario: Thread A writes PID, Thread B reads while write in progress.
        Without locking, Thread B might read incomplete data or old data.
        """
        pid_file = tmp_path / "agent.pid"
        results: list = []

        def write_pid_slowly() -> None:
            """Write PID byte by byte to simulate slow write."""
            # Write in two stages to create race window
            with open(pid_file, "w", encoding="utf-8") as f:
                f.write("123")
                time.sleep(0.01)  # Race window
                f.write("45")

        def read_pid() -> None:
            """Try to read PID."""
            time.sleep(0.005)  # Start during write
            try:
                if pid_file.exists():
                    content = pid_file.read_text(encoding="utf-8")
                    results.append(content)
            except (ValueError, FileNotFoundError):
                results.append(None)

        thread1 = threading.Thread(target=write_pid_slowly)
        thread2 = threading.Thread(target=read_pid)

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        # May read partial data ("123"), complete data ("12345"),
        # empty string (read during file creation), or None (file not ready)
        # This demonstrates the need for atomic read/write
        if results:
            assert results[0] in ("", "123", "12345", None)

    def test_stale_pid_file_reuse_vulnerability(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that stale PID files can cause killing wrong process (to be fixed).

        Scenario:
        1. Process A (PID 1234) starts and writes PID file
        2. Process A dies but PID file not cleaned up
        3. OS reuses PID 1234 for unrelated process B
        4. We try to stop Process A, read stale PID 1234, kill Process B (wrong!)
        """
        pid_file = tmp_path / "agent.pid"

        # Simulate: old process wrote PID 1234
        pid_file.write_text("1234", encoding="utf-8")

        # Simulate: PID 1234 now belongs to different process
        # (In reality, original process died and OS reused PID)

        # Current code just reads PID and kills without validation
        pid_to_kill = int(pid_file.read_text(encoding="utf-8"))
        assert pid_to_kill == 1234

        # Problem: We would kill PID 1234 without checking:
        # 1. Does process 1234 still exist?
        # 2. Is process 1234 the process we started (check command name)?
        # 3. Is PID file stale (older than process start time)?

        # After fix, should implement validation:
        # - Check if process exists: psutil.pid_exists(pid)
        # - Check process name matches expected
        # - Check process start time vs PID file modification time

    def test_pid_validation_missing(self, tmp_path: Path) -> None:
        """Test that current code doesn't validate PID before killing (to be fixed).

        Current behavior: Reads PID and calls kill_process without any validation.
        After fix: Should validate PID exists and belongs to expected process.
        """
        pid_file = tmp_path / "agent.pid"

        # Write a PID that doesn't exist
        nonexistent_pid = 999999
        pid_file.write_text(str(nonexistent_pid), encoding="utf-8")

        # Current code would try to kill this PID
        # After fix, should check psutil.pid_exists() first
        pid = int(pid_file.read_text(encoding="utf-8"))

        # Validation that should be added:
        if not psutil.pid_exists(pid):
            # Should log warning and clean up stale PID file
            pass
        else:
            # Should check process name matches expected
            try:
                proc = psutil.Process(pid)
                # Check if proc.name() matches expected (e.g., "aea" or "flask")
                _ = proc  # Use variable to avoid unused warning
            except psutil.NoSuchProcess:
                # Process died between exists check and Process creation
                pass


class TestPIDFileLockingImplementation:
    """Tests for PID file locking implementation (will be added).

    After fixes, PID operations should use file locking to prevent races.
    """

    def test_pid_file_locking_cross_platform(self, tmp_path: Path) -> None:
        """Test that PID file locking works on all platforms (to be implemented).

        Should use:
        - fcntl.flock() on Unix/macOS
        - msvcrt.locking() on Windows
        """
        # After implementation, this will test the locking mechanism
        # For now, document the requirement
        _ = tmp_path  # Will use after implementation

        if platform.system() == "Windows":
            # Should use msvcrt.locking(fd, msvcrt.LK_NBLCK, size)
            pass
        else:
            # Should use fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pass

        # Lock should be:
        # 1. Exclusive (only one writer at a time)
        # 2. Non-blocking (fail fast if already locked)
        # 3. Released automatically when file closed

    def test_concurrent_pid_writes_with_locking(self, tmp_path: Path) -> None:
        """Test that locking prevents concurrent PID writes (to be implemented).

        After fix: Second write attempt should fail or wait while first is in progress.
        """
        # This will be implemented after adding locking
        # Should verify second thread gets lock error
        pass

    def test_pid_read_waits_for_write_completion(self, tmp_path: Path) -> None:
        """Test that read waits for write to complete (to be implemented).

        After fix: Read should either wait for lock or fail fast.
        """
        # This will be implemented after adding locking
        pass


class TestPIDValidationImplementation:
    """Tests for PID validation implementation (will be added)."""

    def test_validate_pid_exists(self, tmp_path: Path) -> None:
        """Test PID validation checks if process exists (to be implemented).

        After fix: Should use psutil.pid_exists() before killing.
        """
        # Will implement validation logic
        pass

    def test_validate_pid_matches_expected_process(self, tmp_path: Path) -> None:
        """Test PID validation checks process name (to be implemented).

        After fix: Should verify process name matches expected (aea, flask, etc).
        """
        # Will implement process name checking
        pass

    def test_stale_pid_file_cleanup(self, tmp_path: Path) -> None:
        """Test stale PID files are cleaned up (to be implemented).

        After fix: Should remove PID file if process doesn't exist.
        """
        # Will implement stale file cleanup
        pass


class TestFundingManagerCooldownRaceConditions:
    """Tests for funding manager cooldown thread safety (Phase 1.3 item 2).

    To be implemented next after PID fixes.
    """

    def test_cooldown_dict_concurrent_access(self) -> None:
        """Document cooldown dict thread safety issue (to be fixed).

        Current issue: _funding_requests_cooldown_until dict accessed without lock.
        Line ~100 in funding_manager.py needs lock extension.
        """
        # Placeholder for next set of race condition tests
        pass


class TestHealthCheckerJobRaceConditions:
    """Tests for health checker job cancellation races (Phase 1.3 item 3).

    To be implemented after funding manager fixes.
    """

    def test_start_stop_race_condition(self) -> None:
        """Document race between start_for_service and stop_for_service (to be fixed).

        Current issue: No lock around job dict operations.
        Need to add lock and wait for cancellation completion.
        """
        # Placeholder for health checker race condition tests
        pass
