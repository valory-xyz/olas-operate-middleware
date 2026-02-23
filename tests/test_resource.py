# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------
"""Tests for LocalResource and key file integrity."""

import json
import os
import platform
import subprocess  # nosec
import sys
from pathlib import Path
from time import sleep, time
from unittest.mock import patch

import pytest

from operate.constants import ZERO_ADDRESS
from operate.keys import Key
from operate.operate_types import LedgerType


def _run_read_write() -> int:
    """Run the read-write script."""
    process = subprocess.Popen(  # pylint: disable=subprocess-run-check # nosec
        args=[
            sys.executable,
            Path(__file__).parent / "rw.py",
        ],
    )
    return process.pid


def _terminate_process(pid: int) -> None:
    """Terminate process in a platform-specific way."""
    if platform.system() == "Windows":
        # Use taskkill on Windows
        subprocess.run(  # pylint: disable=subprocess-run-check # nosec
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        # Use kill on Unix-like systems
        subprocess.run(  # pylint: disable=subprocess-run-check # nosec
            ["kill", str(pid)],
            check=False,
        )


def test_no_corruption() -> None:
    """Test that the key file is not corrupted during read-write operations."""
    # Create a temporary resource to store the key
    temp_resource = Key(LedgerType.ETHEREUM, ZERO_ADDRESS, "0xkey")
    temp_resource.path = Path("key.json")
    temp_resource.store()
    success = True

    current_time = time()
    while time() - current_time < 60:
        pid = _run_read_write()
        sleep(1)
        _terminate_process(pid)

        # On Windows, wait a bit longer for file handles to be released
        if platform.system() == "Windows":
            sleep(0.5)

        try:
            with open(temp_resource.path) as f:
                final_key = json.load(f)  # this line should not fail for 60 seconds
        except (json.JSONDecodeError, FileNotFoundError, PermissionError):
            break

    # Final validation
    try:
        with open(temp_resource.path) as f:
            final_key = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, PermissionError):
        success = False

    # Cleanup
    for file in Path(".").glob("key.json*"):
        try:
            file.unlink()
        except (PermissionError, FileNotFoundError):
            # On Windows, files might still be locked
            pass

    assert success, "Key file should not be corrupted after read-write operations"
    assert len(final_key) == 3, "Key should not be empty after 60 seconds"
    assert final_key["address"] == ZERO_ADDRESS, "Key address should match"
    assert final_key["ledger"] == LedgerType.ETHEREUM, "Ledger type should match"
    assert final_key["private_key"] == "0xkey", "Public key should match"


def test_store_raises_when_path_is_none() -> None:
    """Test that store() raises RuntimeError when path is None."""
    key = Key(LedgerType.ETHEREUM, ZERO_ADDRESS, "0xkey")
    key.path = None  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="Path value not provided"):
        key.store()


def test_store_cleans_up_stale_tmp_file(tmp_path: Path) -> None:
    """Test that store() removes a pre-existing stale .tmp file before writing."""
    key = Key(LedgerType.ETHEREUM, ZERO_ADDRESS, "0xkey")
    key.path = tmp_path / "key.json"

    # Pre-create a stale tmp file
    tmp_file = tmp_path / ".key.json.tmp"
    tmp_file.write_text("stale content", encoding="utf-8")
    assert tmp_file.exists()

    key.store()

    # After store, the key file should exist with correct content
    assert key.path.exists()
    data = json.loads(key.path.read_text(encoding="utf-8"))
    assert data["address"] == ZERO_ADDRESS

    # The stale tmp file should be gone
    assert not tmp_file.exists()


def test_store_windows_permission_error_cleanup(tmp_path: Path) -> None:
    """Test that on Windows PermissionError during replace, tmp file cleanup is attempted."""
    key = Key(LedgerType.ETHEREUM, ZERO_ADDRESS, "0xkey")
    key.path = tmp_path / "key.json"

    ops_called = []

    def mock_safe_file_op(op: object, *args: object, **kwargs: object) -> None:
        """Mock safe_file_operation that tracks calls and raises PermissionError for os.replace."""
        ops_called.append(op)
        if op is os.replace:
            raise PermissionError("Windows: file locked")
        # Execute other operations normally
        try:
            op(*args, **kwargs)  # type: ignore[operator]
        except (FileNotFoundError, OSError, PermissionError):
            pass

    with patch("operate.resource.platform.system", return_value="Windows"), patch(
        "operate.resource.safe_file_operation", side_effect=mock_safe_file_op
    ):
        try:
            key.store()
        except Exception:  # pylint: disable=broad-except  # nosec B110
            pass  # Expected: self.load() may fail since file wasn't atomically replaced

    # os.replace should have been attempted
    assert os.replace in ops_called, "os.replace should have been called"

    # After PermissionError, cleanup (unlink) should be called
    replace_idx = ops_called.index(os.replace)
    post_replace_ops = ops_called[replace_idx + 1 :]
    assert any(
        "unlink" in getattr(op, "__name__", "") for op in post_replace_ops
    ), "tmp file unlink should be called after PermissionError on Windows"
