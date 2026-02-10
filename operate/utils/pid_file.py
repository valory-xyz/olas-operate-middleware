"""
PID file management utilities with proper locking and validation.

Provides thread-safe and process-safe PID file operations to prevent race
conditions in process management.
"""

import logging
import platform
import time
from pathlib import Path
from typing import Optional

import psutil


logger = logging.getLogger(__name__)


class PIDFileError(Exception):
    """Base exception for PID file operations."""


class PIDFileLocked(PIDFileError):
    """Raised when PID file is already locked by another process."""


class StalePIDFile(PIDFileError):
    """Raised when PID file exists but process is dead."""


def _acquire_lock(file_handle: int) -> None:
    """Acquire exclusive lock on file.

    :param file_handle: File descriptor to lock
    :raises PIDFileLocked: If file is already locked
    """
    if platform.system() == "Windows":
        import msvcrt  # type: ignore[import] # pylint: disable=import-outside-toplevel,import-error

        try:
            msvcrt.locking(file_handle, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError as e:
            raise PIDFileLocked("PID file is locked by another process") from e
    else:
        import fcntl  # pylint: disable=import-outside-toplevel

        try:
            fcntl.flock(file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise PIDFileLocked("PID file is locked by another process") from e


def _release_lock(file_handle: int) -> None:
    """Release lock on file.

    :param file_handle: File descriptor to unlock
    """
    if platform.system() == "Windows":
        import msvcrt  # type: ignore[import] # pylint: disable=import-outside-toplevel,import-error

        try:
            msvcrt.locking(file_handle, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            pass  # Best effort unlock
    else:
        import fcntl  # pylint: disable=import-outside-toplevel

        try:
            fcntl.flock(file_handle, fcntl.LOCK_UN)
        except OSError:
            pass  # Best effort unlock


def validate_pid(pid: int, expected_process_names: Optional[list] = None) -> bool:
    """Validate that PID exists and optionally matches expected process.

    :param pid: Process ID to validate
    :param expected_process_names: Optional list of expected process names
    :return: True if PID is valid, False otherwise
    """
    try:
        if not psutil.pid_exists(pid):
            logger.debug(f"PID {pid} does not exist")
            return False

        if expected_process_names is not None:
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
                logger.debug(f"PID {pid} process name: {proc_name}")

                # Match against any expected name (case-insensitive)
                if not any(
                    expected.lower() in proc_name.lower()
                    for expected in expected_process_names
                ):
                    logger.warning(
                        f"PID {pid} process name '{proc_name}' "
                        f"does not match expected {expected_process_names}"
                    )
                    return False
            except psutil.NoSuchProcess:
                logger.debug(f"PID {pid} disappeared during validation")
                return False

        return True
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error validating PID {pid}: {e}")
        return False


def write_pid_file(
    pid_file: Path,
    pid: int,
    timeout: float = 5.0,
    expected_process_names: Optional[list] = None,
) -> None:
    """Write PID to file with exclusive lock.

    :param pid_file: Path to PID file
    :param pid: Process ID to write
    :param timeout: Maximum time to wait for lock acquisition
    :param expected_process_names: Optional list of expected process names for validation
    :raises PIDFileLocked: If file is locked and timeout expires
    :raises PIDFileError: If write fails
    """
    # Validate PID before writing
    if not validate_pid(pid, expected_process_names):
        raise PIDFileError(
            f"PID {pid} validation failed "
            f"(expected names: {expected_process_names})"
        )

    start_time = time.time()
    last_error = None

    while time.time() - start_time < timeout:
        try:
            # Open file for writing (creates if doesn't exist)
            with open(pid_file, "w", encoding="utf-8") as f:
                # Acquire exclusive lock
                _acquire_lock(f.fileno())
                try:
                    # Write PID
                    f.write(str(pid))
                    f.flush()
                    logger.debug(f"Wrote PID {pid} to {pid_file}")
                    return
                finally:
                    _release_lock(f.fileno())
        except PIDFileLocked as e:
            last_error = e
            time.sleep(0.1)  # Wait before retry
        except OSError as e:
            raise PIDFileError(f"Failed to write PID file {pid_file}: {e}") from e

    # Timeout expired
    raise PIDFileLocked(
        f"Could not acquire lock on {pid_file} within {timeout}s: {last_error}"
    )


def read_pid_file(
    pid_file: Path,
    timeout: float = 5.0,
    expected_process_names: Optional[list] = None,
    remove_stale: bool = True,
) -> int:
    """Read PID from file with shared lock and validation.

    :param pid_file: Path to PID file
    :param timeout: Maximum time to wait for lock acquisition
    :param expected_process_names: Optional list of expected process names for validation
    :param remove_stale: Whether to remove stale PID files
    :return: Process ID
    :raises FileNotFoundError: If PID file doesn't exist
    :raises PIDFileLocked: If file is locked and timeout expires
    :raises StalePIDFile: If PID file exists but process is dead
    :raises PIDFileError: If read fails or PID is invalid
    """
    if not pid_file.exists():
        raise FileNotFoundError(f"PID file {pid_file} not found")

    start_time = time.time()
    last_error = None

    while time.time() - start_time < timeout:
        try:
            # Read and validate PID (with file closed after this block)
            pid_is_stale = False
            pid = None

            with open(pid_file, "r", encoding="utf-8") as f:
                # Acquire shared lock for reading
                # (multiple readers OK, but blocks writers)
                if platform.system() != "Windows":
                    import fcntl  # pylint: disable=import-outside-toplevel

                    fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                try:
                    content = f.read().strip()
                    if not content:
                        raise PIDFileError(f"PID file {pid_file} is empty")

                    try:
                        pid = int(content)
                    except ValueError as e:
                        raise PIDFileError(
                            f"Invalid PID in {pid_file}: {content}"
                        ) from e

                    # Validate PID
                    if not validate_pid(pid, expected_process_names):
                        pid_is_stale = True

                    logger.debug(f"Read PID {pid} from {pid_file}")
                finally:
                    if platform.system() != "Windows":
                        import fcntl  # pylint: disable=import-outside-toplevel

                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # File is now closed - safe to remove on Windows
            if pid_is_stale:
                if remove_stale:
                    logger.warning(
                        f"Removing stale PID file {pid_file} (PID {pid})"
                    )
                    try:
                        pid_file.unlink()
                    except OSError as e:
                        logger.error(
                            f"Failed to remove stale PID file {pid_file}: {e}"
                        )
                raise StalePIDFile(
                    f"PID {pid} in {pid_file} is stale "
                    f"(process not found or name mismatch)"
                )

            return pid
        except PIDFileLocked as e:
            last_error = e
            time.sleep(0.1)  # Wait before retry
        except (StalePIDFile, PIDFileError):  # pylint: disable=try-except-raise
            raise  # Don't retry on these errors
        except OSError as e:
            raise PIDFileError(f"Failed to read PID file {pid_file}: {e}") from e

    # Timeout expired
    raise PIDFileLocked(
        f"Could not acquire lock on {pid_file} within {timeout}s: {last_error}"
    )


def remove_pid_file(pid_file: Path, force: bool = False) -> None:
    """Remove PID file.

    :param pid_file: Path to PID file
    :param force: If True, remove even if locked or process still running
    """
    if not pid_file.exists():
        return

    if not force:
        # Check if process is still running
        try:
            pid = read_pid_file(
                pid_file, timeout=1.0, expected_process_names=None, remove_stale=False
            )
            logger.warning(
                f"Not removing {pid_file}: process {pid} is still running "
                f"(use force=True to override)"
            )
            return
        except (StalePIDFile, PIDFileError, FileNotFoundError):
            pass  # OK to remove

    try:
        pid_file.unlink()
        logger.debug(f"Removed PID file {pid_file}")
    except OSError as e:
        logger.error(f"Failed to remove PID file {pid_file}: {e}")
