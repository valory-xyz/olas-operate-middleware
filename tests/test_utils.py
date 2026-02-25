# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""Tests for utils module."""

import time
import typing as t
from pathlib import Path
from unittest.mock import patch

import pytest
from deepdiff import DeepDiff

import operate.utils as utils
from operate.serialization import BigInt
from operate.utils import (
    concurrent_execute,
    concurrent_execute_async,
    create_backup,
    merge_sum_dicts,
    safe_file_operation,
    subtract_dicts,
    unrecoverable_delete,
)


class TestUtils:
    """TestUtils"""

    @pytest.mark.parametrize(
        ("a", "b", "c", "d", "expected_result"),
        [
            ({}, {}, {}, {}, {}),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b1": {"c1": 3, "c2": 4}}},
                {},
                {},
                {"a1": {"b1": {"c1": 4, "c2": 6}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b1": {"c1": 3, "c3": 4}}},
                {},
                {},
                {"a1": {"b1": {"c1": 4, "c2": 2, "c3": 4}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b2": {"c1": 3, "c3": 4}}},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}, "b2": {"c1": 3, "c3": 4}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b2": 5}},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}, "b2": 5}},
            ),
            (
                {"a1": {"b2": 5}},
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}, "b2": 5}},
            ),
        ],
    )
    def test_merge_sum_dicts(
        self, a: t.Dict, b: t.Dict, c: t.Dict, d: t.Dict, expected_result: t.Dict
    ) -> None:
        """test_merge_sum_dicts"""
        result = merge_sum_dicts(a, b, c, d)
        diff = DeepDiff(result, expected_result)
        if diff:
            print(diff)
        assert not diff, "Test failed."

    @pytest.mark.parametrize(
        ("a", "b", "expected_result"),
        [
            ({}, {}, {}),
            (
                {"a1": {"b1": {"c1": 10, "c2": 20}}},
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b1": {"c1": BigInt(9), "c2": BigInt(18)}}},
            ),
            (
                {"a1": {"b1": {"c1": 5, "c2": 20}}},
                {"a1": {"b1": {"c1": 10, "c2": 0}}},
                {"a1": {"b1": {"c1": BigInt(0), "c2": BigInt(20)}}},
            ),
            (
                {"a1": {"b1": {"c1": 10, "c2": 20}, "b2": {"d1": 5, "d4": 20}}},
                {"a1": {"b1": {"c1": 5, "c2": 0}}},
                {
                    "a1": {
                        "b1": {"c1": BigInt(5), "c2": BigInt(20)},
                        "b2": {"d1": BigInt(5), "d4": BigInt(20)},
                    }
                },
            ),
            (
                {"a1": {"b1": {"c1": 10, "c2": 20}}},
                {"a1": {"b1": {"c1": 1}}},
                {"a1": {"b1": {"c1": BigInt(9), "c2": BigInt(20)}}},
            ),
            (
                {"a1": {"b1": {"c1": 10}}},
                {"a1": {"b1": {"c1": 1, "c2": 20}}},
                {"a1": {"b1": {"c1": BigInt(9), "c2": BigInt(0)}}},
            ),
        ],
    )
    def test_subtract_dicts(
        self, a: t.Dict, b: t.Dict, expected_result: t.Dict
    ) -> None:
        """test_subtract_dicts"""
        result = subtract_dicts(a, b)
        diff = DeepDiff(result, expected_result)
        if diff:
            print(diff)
        assert not diff, "Test failed."


class TestSafeFileOperation:
    """Tests for the safe_file_operation helper."""

    def test_safe_file_operation_success(self) -> None:
        """It should call the operation once when no error occurs."""

        calls = []

        def operation(*args: t.Any, **kwargs: t.Any) -> None:
            calls.append((args, kwargs))

        safe_file_operation(operation, 1, key="value")

        assert calls == [((1,), {"key": "value"})]

    def test_safe_file_operation_retries_on_windows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It should retry up to three times on Windows before succeeding."""

        monkeypatch.setattr("operate.utils.platform.system", lambda: "Windows")
        monkeypatch.setattr("operate.utils.time.sleep", lambda _delay: None)

        attempts = {"count": 0}

        def flaky_operation() -> None:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise PermissionError("locked")

        safe_file_operation(flaky_operation)

        assert attempts["count"] == 3

    def test_safe_file_operation_raises_after_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It should raise the last error after exhausting retries."""

        monkeypatch.setattr("operate.utils.platform.system", lambda: "Windows")
        monkeypatch.setattr("operate.utils.time.sleep", lambda _delay: None)

        attempts = {"count": 0}

        def failing_operation() -> None:
            attempts["count"] += 1
            raise FileNotFoundError("missing")

        with pytest.raises(FileNotFoundError):
            safe_file_operation(failing_operation)

        assert attempts["count"] == 3


class TestUnrecoverableDelete:
    """Tests for the unrecoverable_delete helper."""

    def test_unrecoverable_delete_removes_file(self, tmp_path: Path) -> None:
        """It should securely remove an existing file."""

        file_path = tmp_path / "secret.txt"
        file_path.write_bytes(b"initial data")

        unrecoverable_delete(file_path)

        assert not file_path.exists()

    def test_unrecoverable_delete_raises_for_directory(self, tmp_path: Path) -> None:
        """It should raise a ValueError when the path is a directory."""

        directory_path = tmp_path / "nested"
        directory_path.mkdir()

        with pytest.raises(ValueError, match="nested is not a file"):
            unrecoverable_delete(directory_path)

    def test_unrecoverable_delete_ignores_missing_file(self, tmp_path: Path) -> None:
        """It should silently return when the file does not exist."""

        missing_path = tmp_path / "missing.txt"

        # Should not raise
        unrecoverable_delete(missing_path)

        assert not missing_path.exists()

    def test_unrecoverable_delete_overwrites_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It should overwrite file contents before deletion."""

        file_path = tmp_path / "secure.txt"
        original_data = b"top secret"
        file_path.write_bytes(original_data)

        monkeypatch.setattr("operate.utils.os.urandom", lambda size: b"\xaa" * size)

        overwritten_data: t.List[bytes] = []
        original_remove = utils.os.remove

        def monitored_remove(path: t.Union[str, Path]) -> None:
            with open(path, "rb") as file:  # type: ignore[arg-type]
                overwritten_data.append(file.read())
            original_remove(path)

        monkeypatch.setattr("operate.utils.os.remove", monitored_remove)

        unrecoverable_delete(file_path)

        assert not file_path.exists()
        assert overwritten_data
        assert overwritten_data[0] == b"\xaa" * len(original_data)
        assert overwritten_data[0] != original_data


class TestParallelExecute:
    """Tests for the parallel_execute helper."""

    def test_parallel_execute_runs_and_preserves_order(self) -> None:
        """It should return results aligned to funcs/args_list order."""

        def add(a: int, b: int) -> int:
            return a + b

        def double(x: int) -> int:
            return x * 2

        def constant() -> str:
            return "ok"

        assert concurrent_execute(
            (add, (1, 2)),
            (double, (3,)),
            (constant, ()),
        ) == [3, 6, "ok"]

    def test_parallel_execute_propagates_exceptions(self) -> None:
        """It should propagate exceptions when ignore_exceptions is False."""

        def ok() -> str:
            return "ok"

        def boom() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            concurrent_execute((ok, ()), (boom, ()))

    def test_parallel_execute_ignores_exceptions_when_enabled(self) -> None:
        """It should return None for failing calls when ignore_exceptions is True."""

        def ok() -> str:
            return "ok"

        def boom() -> None:
            raise RuntimeError("boom")

        result = concurrent_execute(
            (ok, ()), (boom, ()), (ok, ()), ignore_exceptions=True
        )
        assert result == ["ok", None, "ok"]

    def test_parallel_execute_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """It should raise TimeoutError when futures exceed DEFAULT_TIMEOUT."""

        from concurrent.futures import TimeoutError

        monkeypatch.setattr("operate.utils.DEFAULT_TIMEOUT", 0.01)

        def slow() -> None:
            time.sleep(0.05)

        with pytest.raises(TimeoutError):
            concurrent_execute((slow, ()))


class TestCreateBackup:
    """Tests for create_backup function (lines 67, 73)."""

    def test_create_backup_raises_when_path_does_not_exist(
        self, tmp_path: Path
    ) -> None:
        """Test create_backup raises FileNotFoundError when path doesn't exist (line 67)."""
        missing = tmp_path / "nonexistent.txt"
        with pytest.raises(FileNotFoundError):
            create_backup(missing)

    def test_create_backup_file(self, tmp_path: Path) -> None:
        """Test create_backup creates a timestamped copy of a file."""
        source = tmp_path / "data.txt"
        source.write_text("hello", encoding="utf-8")
        backup = create_backup(source)
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == "hello"
        assert ".bak" in backup.name

    def test_create_backup_directory(self, tmp_path: Path) -> None:
        """Test create_backup uses shutil.copytree for directories (line 73)."""
        source_dir = tmp_path / "mydir"
        source_dir.mkdir()
        (source_dir / "file.txt").write_text("content", encoding="utf-8")
        backup = create_backup(source_dir)
        assert backup.is_dir()
        assert (backup / "file.txt").read_text(encoding="utf-8") == "content"
        assert ".bak" in backup.name


class TestUnrecoverableDeleteErrors:
    """Tests for unrecoverable_delete error-handling branches (lines 164-167)."""

    def test_unrecoverable_delete_handles_permission_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test PermissionError inside the delete block is caught and printed (lines 164-165)."""
        file_path = tmp_path / "locked.txt"
        file_path.write_bytes(b"data")

        with patch(
            "operate.utils.os.path.getsize", side_effect=PermissionError("denied")
        ):
            unrecoverable_delete(file_path)  # should not raise

        captured = capsys.readouterr()
        assert "Permission denied" in captured.out

    def test_unrecoverable_delete_handles_generic_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Generic Exception inside the delete block is caught and printed (lines 166-167)."""
        file_path = tmp_path / "file.txt"
        file_path.write_bytes(b"data")

        with patch("operate.utils.os.path.getsize", side_effect=RuntimeError("oops")):
            unrecoverable_delete(file_path)  # should not raise

        captured = capsys.readouterr()
        assert "Error during secure deletion" in captured.out


class TestConcurrentExecuteFromEventLoop:
    """Tests for concurrent_execute when called from a running event loop (lines 207-209)."""

    async def test_concurrent_execute_from_running_event_loop(self) -> None:
        """concurrent_execute uses ThreadPoolExecutor when an event loop is already running."""

        def add(a: int, b: int) -> int:
            return a + b

        result = concurrent_execute((add, (1, 2)))
        assert result == [3]


class TestConcurrentExecuteAsyncCallable:
    """Tests for concurrent_execute_async with async callables (line 227)."""

    async def test_concurrent_execute_with_async_callable(self) -> None:
        """Async callables are awaited directly (line 227)."""

        async def async_double(x: int) -> int:
            return x * 2

        result = await concurrent_execute_async((async_double, (5,)))
        assert result == [10]
