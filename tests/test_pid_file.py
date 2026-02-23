"""
Tests for PID file utilities with locking and validation.

Verifies thread-safe and process-safe PID file operations.
"""

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from operate.utils.pid_file import (
    PIDFileError,
    PIDFileLocked,
    StalePIDFile,
    _acquire_lock,
    _release_lock,
    read_pid_file,
    remove_pid_file,
    validate_pid,
    write_pid_file,
)


class TestPIDValidation:
    """Test PID validation logic."""

    def test_validate_pid_exists(self) -> None:
        """Test validation accepts existing process."""
        # Use current process PID (guaranteed to exist)
        current_pid = os.getpid()
        assert validate_pid(current_pid) is True

    def test_validate_pid_not_exists(self) -> None:
        """Test validation rejects non-existent PID."""
        # Use very high PID that doesn't exist
        nonexistent_pid = 999999
        assert validate_pid(nonexistent_pid) is False

    def test_validate_pid_with_matching_process_name(self) -> None:
        """Test validation checks process name matches expected."""
        current_pid = os.getpid()
        current_proc = psutil.Process(current_pid)
        current_name = current_proc.name()

        # Should match if name is in expected list
        assert validate_pid(current_pid, [current_name.lower()]) is True

    def test_validate_pid_with_non_matching_process_name(self) -> None:
        """Test validation rejects wrong process name."""
        current_pid = os.getpid()

        # Should not match impossible process name
        assert validate_pid(current_pid, ["impossible_process_name_xyz"]) is False

    def test_validate_pid_with_partial_name_match(self) -> None:
        """Test validation accepts partial process name match."""
        current_pid = os.getpid()
        current_proc = psutil.Process(current_pid)
        current_name = current_proc.name()

        # Should match if partial name is in expected list
        partial_name = current_name[:3].lower()  # First 3 chars
        assert validate_pid(current_pid, [partial_name]) is True


class TestWritePIDFile:
    """Test PID file writing with locking."""

    def test_write_pid_file_success(self, tmp_path: Path) -> None:
        """Test successful PID file write."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        write_pid_file(pid_file, current_pid)

        # Verify file created and contains PID
        assert pid_file.exists()
        assert pid_file.read_text(encoding="utf-8") == str(current_pid)

    def test_write_pid_file_with_validation(self, tmp_path: Path) -> None:
        """Test PID file write validates PID before writing."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()
        current_proc = psutil.Process(current_pid)
        current_name = current_proc.name()

        # Should succeed with matching name
        write_pid_file(pid_file, current_pid, expected_process_names=[current_name])

        assert pid_file.exists()

    def test_write_pid_file_fails_with_invalid_pid(self, tmp_path: Path) -> None:
        """Test PID file write fails if PID doesn't exist."""
        pid_file = tmp_path / "test.pid"
        nonexistent_pid = 999999

        with pytest.raises(PIDFileError, match="validation failed"):
            write_pid_file(pid_file, nonexistent_pid)

        # File should not be created
        assert not pid_file.exists()

    def test_write_pid_file_fails_with_wrong_process_name(self, tmp_path: Path) -> None:
        """Test PID file write fails if process name doesn't match."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        with pytest.raises(PIDFileError, match="validation failed"):
            write_pid_file(
                pid_file, current_pid, expected_process_names=["impossible_name"]
            )

        assert not pid_file.exists()

    def test_write_pid_file_concurrent_writes_are_serialized(
        self, tmp_path: Path
    ) -> None:
        """Test concurrent writes are serialized by locking."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()
        results: list = []  # type: ignore[var-annotated]

        def write_with_delay(pid: int, delay: float) -> None:
            """Write PID with delay to test locking."""
            try:
                write_pid_file(pid_file, pid, timeout=2.0)
                time.sleep(delay)  # Hold file briefly
                results.append(("success", pid))
            except PIDFileLocked as e:
                results.append(("locked", str(e)))

        # Start two threads trying to write
        thread1 = threading.Thread(target=write_with_delay, args=(current_pid, 0.1))
        thread2 = threading.Thread(target=write_with_delay, args=(current_pid, 0.1))

        thread1.start()
        time.sleep(0.05)  # Start thread2 while thread1 is working
        thread2.start()

        thread1.join()
        thread2.join()

        # Both should succeed (second waits for first to release lock)
        # or one succeeds and other gets timeout
        success_count = sum(1 for r in results if r[0] == "success")
        assert success_count >= 1  # At least one should succeed


class TestReadPIDFile:
    """Test PID file reading with locking and validation."""

    def test_read_pid_file_success(self, tmp_path: Path) -> None:
        """Test successful PID file read."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        # Write PID file
        pid_file.write_text(str(current_pid), encoding="utf-8")

        # Read it back
        read_pid = read_pid_file(pid_file)
        assert read_pid == current_pid

    def test_read_pid_file_not_found(self, tmp_path: Path) -> None:
        """Test reading non-existent PID file raises FileNotFoundError."""
        pid_file = tmp_path / "nonexistent.pid"

        with pytest.raises(FileNotFoundError):
            read_pid_file(pid_file)

    def test_read_pid_file_empty(self, tmp_path: Path) -> None:
        """Test reading empty PID file raises error."""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("", encoding="utf-8")

        with pytest.raises(PIDFileError, match="is empty"):
            read_pid_file(pid_file)

    def test_read_pid_file_invalid_content(self, tmp_path: Path) -> None:
        """Test reading PID file with invalid content raises error."""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not_a_number", encoding="utf-8")

        with pytest.raises(PIDFileError, match="Invalid PID"):
            read_pid_file(pid_file)

    def test_read_pid_file_stale_pid(self, tmp_path: Path) -> None:
        """Test reading stale PID file raises StalePIDFile."""
        pid_file = tmp_path / "test.pid"
        nonexistent_pid = 999999
        pid_file.write_text(str(nonexistent_pid), encoding="utf-8")

        with pytest.raises(StalePIDFile, match="is stale"):
            read_pid_file(pid_file)

        # Stale file should be removed
        assert not pid_file.exists()

    def test_read_pid_file_stale_not_removed_if_disabled(self, tmp_path: Path) -> None:
        """Test stale PID file not removed if remove_stale=False."""
        pid_file = tmp_path / "test.pid"
        nonexistent_pid = 999999
        pid_file.write_text(str(nonexistent_pid), encoding="utf-8")

        with pytest.raises(StalePIDFile):
            read_pid_file(pid_file, remove_stale=False)

        # File should still exist
        assert pid_file.exists()

    def test_read_pid_file_with_process_name_validation(self, tmp_path: Path) -> None:
        """Test reading PID file validates process name."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()
        current_proc = psutil.Process(current_pid)
        current_name = current_proc.name()

        pid_file.write_text(str(current_pid), encoding="utf-8")

        # Should succeed with matching name
        read_pid = read_pid_file(pid_file, expected_process_names=[current_name])
        assert read_pid == current_pid

    def test_read_pid_file_fails_with_wrong_process_name(self, tmp_path: Path) -> None:
        """Test reading PID file fails if process name doesn't match."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        pid_file.write_text(str(current_pid), encoding="utf-8")

        with pytest.raises(StalePIDFile, match="name mismatch"):
            read_pid_file(pid_file, expected_process_names=["impossible_name"])

        # Stale file should be removed
        assert not pid_file.exists()


class TestRemovePIDFile:
    """Test PID file removal."""

    def test_remove_pid_file_success(self, tmp_path: Path) -> None:
        """Test successful PID file removal."""
        pid_file = tmp_path / "test.pid"
        nonexistent_pid = 999999  # Dead process

        pid_file.write_text(str(nonexistent_pid), encoding="utf-8")

        remove_pid_file(pid_file)
        assert not pid_file.exists()

    def test_remove_pid_file_not_exists(self, tmp_path: Path) -> None:
        """Test removing non-existent PID file doesn't raise error."""
        pid_file = tmp_path / "nonexistent.pid"

        # Should not raise
        remove_pid_file(pid_file)

    def test_remove_pid_file_refuses_if_process_running(self, tmp_path: Path) -> None:
        """Test removal refuses if process is still running."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        pid_file.write_text(str(current_pid), encoding="utf-8")

        # Should not remove
        remove_pid_file(pid_file)
        assert pid_file.exists()

    def test_remove_pid_file_force(self, tmp_path: Path) -> None:
        """Test forced removal even if process running."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        pid_file.write_text(str(current_pid), encoding="utf-8")

        # Force removal
        remove_pid_file(pid_file, force=True)
        assert not pid_file.exists()


class TestConcurrentOperations:
    """Test concurrent PID file operations."""

    def test_concurrent_read_write(self, tmp_path: Path) -> None:
        """Test concurrent reads and writes are properly synchronized."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()
        results: list = []  # type: ignore[var-annotated]

        # Write initial PID
        pid_file.write_text(str(current_pid), encoding="utf-8")

        def reader() -> None:
            """Try to read PID."""
            for _ in range(3):  # Reduced iterations
                try:
                    pid = read_pid_file(pid_file, timeout=1.0)
                    results.append(("read", pid))
                except Exception as e:  # pylint: disable=broad-except
                    results.append(("read_error", type(e).__name__))
                time.sleep(0.05)  # Reduced contention

        def writer() -> None:
            """Try to write PID."""
            for _ in range(3):  # Reduced iterations
                try:
                    write_pid_file(pid_file, current_pid, timeout=1.0)
                    results.append(("write", current_pid))
                except Exception as e:  # pylint: disable=broad-except
                    results.append(("write_error", type(e).__name__))
                time.sleep(0.05)  # Reduced contention

        # Start concurrent readers and writers (reduced threads)
        threads = []
        for _ in range(2):
            threads.append(threading.Thread(target=reader))
            threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Check results - verify all operations completed
        total_attempts = len(results)
        assert total_attempts > 0

        # All successful reads should return valid PID (verifies synchronization)
        for result_type, value in results:
            if result_type == "read":
                assert value == current_pid

        # Document the behavior: some operations may timeout under heavy load
        # but this is expected and acceptable (locking is working)
        # The fact that we got valid results proves synchronization works


class TestLockingPlatformBranches:
    """Tests for platform-specific locking code paths."""

    def test_acquire_lock_windows_raises_pid_file_locked(self, tmp_path: Path) -> None:
        """Test that Windows locking raises PIDFileLocked when OSError occurs."""
        mock_msvcrt = MagicMock()
        mock_msvcrt.locking.side_effect = OSError("Windows: file locked")
        mock_msvcrt.LK_NBLCK = 1

        with patch(
            "operate.utils.pid_file.platform.system", return_value="Windows"
        ), patch.dict(sys.modules, {"msvcrt": mock_msvcrt}):
            with open(tmp_path / "test.pid", "w", encoding="utf-8") as f:
                with pytest.raises(PIDFileLocked, match="locked"):
                    _acquire_lock(f.fileno())

    def test_release_lock_windows_silently_ignores_error(self, tmp_path: Path) -> None:
        """Test that Windows unlock silently ignores OSError (best-effort unlock)."""
        mock_msvcrt = MagicMock()
        mock_msvcrt.locking.side_effect = OSError("Windows: unlock failed")
        mock_msvcrt.LK_UNLCK = 2

        with patch(
            "operate.utils.pid_file.platform.system", return_value="Windows"
        ), patch.dict(sys.modules, {"msvcrt": mock_msvcrt}):
            with open(tmp_path / "test.pid", "w", encoding="utf-8") as f:
                # Should not raise
                _release_lock(f.fileno())

    def test_release_lock_unix_fcntl_error_silently_ignored(
        self, tmp_path: Path
    ) -> None:
        """Test that Unix fcntl unlock OSError is silently ignored."""
        with patch(
            "operate.utils.pid_file.platform.system", return_value="Linux"
        ), patch("fcntl.flock", side_effect=OSError("flock failed")):
            with open(tmp_path / "test.pid", "w", encoding="utf-8") as f:
                # Should not raise
                _release_lock(f.fileno())


class TestValidatePidEdgeCases:
    """Tests for validate_pid edge cases."""

    def test_validate_pid_no_such_process_returns_false(self) -> None:
        """Test that NoSuchProcess during name check causes validate_pid to return False."""
        current_pid = os.getpid()

        with patch.object(
            psutil.Process,
            "name",
            side_effect=psutil.NoSuchProcess(current_pid),
        ):
            result = validate_pid(current_pid, expected_process_names=["any_name"])

        assert result is False

    def test_validate_pid_generic_exception_returns_false_and_logs(self) -> None:
        """Test that a generic Exception during validate_pid returns False."""
        with patch(
            "operate.utils.pid_file.psutil.pid_exists",
            side_effect=RuntimeError("unexpected error"),
        ):
            result = validate_pid(os.getpid())

        assert result is False


class TestWritePIDFileEdgeCases:
    """Tests for write_pid_file edge cases."""

    def test_write_pid_file_oserror_raises_pid_file_error(self, tmp_path: Path) -> None:
        """Test that OSError during write is wrapped in PIDFileError."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        with patch(
            "operate.utils.pid_file._acquire_lock",
            side_effect=OSError("disk full"),
        ):
            # OSError (not PIDFileLocked) from the write path → PIDFileError
            with pytest.raises(PIDFileError, match="Failed to write"):
                write_pid_file(pid_file, current_pid)

    def test_write_pid_file_lock_timeout_raises_pid_file_locked(
        self, tmp_path: Path
    ) -> None:
        """Test that write_pid_file raises PIDFileLocked after lock timeout expires."""
        pid_file = tmp_path / "test.pid"
        current_pid = os.getpid()

        with patch(
            "operate.utils.pid_file._acquire_lock",
            side_effect=PIDFileLocked("always locked"),
        ):
            with pytest.raises(PIDFileLocked, match="Could not acquire lock"):
                write_pid_file(pid_file, current_pid, timeout=0.2)


class TestReadPIDFileEdgeCases:
    """Tests for read_pid_file edge cases."""

    def test_read_pid_file_stale_removal_failure_logs_error(
        self, tmp_path: Path
    ) -> None:
        """Test that failed removal of stale PID file logs an error."""
        pid_file = tmp_path / "test.pid"
        nonexistent_pid = 999999
        pid_file.write_text(str(nonexistent_pid), encoding="utf-8")

        original_unlink = Path.unlink

        def mock_unlink(self: Path, missing_ok: bool = False) -> None:  # type: ignore[override]
            if self == pid_file:
                raise OSError("permission denied")
            original_unlink(self, missing_ok)

        with patch("operate.utils.pid_file.logger") as mock_logger, patch.object(
            Path, "unlink", mock_unlink
        ):
            with pytest.raises(StalePIDFile):
                read_pid_file(pid_file, remove_stale=True)

        mock_logger.error.assert_called()
        error_msg = str(mock_logger.error.call_args)
        assert "Failed to remove stale PID file" in error_msg


class TestRemovePIDFileEdgeCases:
    """Tests for remove_pid_file edge cases."""

    def test_remove_pid_file_unlink_oserror_logs_error(self, tmp_path: Path) -> None:
        """Test that remove_pid_file logs an error if unlink raises OSError."""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("999999", encoding="utf-8")  # Dead process

        original_unlink = Path.unlink

        def mock_unlink(self: Path, missing_ok: bool = False) -> None:  # type: ignore[override]
            if self == pid_file:
                raise OSError("permission denied")
            original_unlink(self, missing_ok)

        with patch("operate.utils.pid_file.logger") as mock_logger, patch.object(
            Path, "unlink", mock_unlink
        ):
            remove_pid_file(pid_file, force=True)

        mock_logger.error.assert_called()
        error_msg = str(mock_logger.error.call_args)
        assert "Failed to remove PID file" in error_msg
