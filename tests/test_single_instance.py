# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""Tests for single-instance and parent watchdog utilities."""

import asyncio
from contextlib import suppress
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest
import requests

from operate.utils.single_instance import AppSingleInstance, ParentWatchdog


class TestAppSingleInstanceInit:
    """Tests for AppSingleInstance initialisation."""

    def test_default_endpoint(self) -> None:
        """Test that the default shutdown endpoint is /shutdown."""
        instance = AppSingleInstance(port_number=8080)
        assert instance.port_number == 8080
        assert instance.shutdown_endpoint == "/shutdown"

    def test_custom_endpoint(self) -> None:
        """Test that a custom shutdown endpoint is stored correctly."""
        instance = AppSingleInstance(port_number=9090, shutdown_endpoint="/stop")
        assert instance.shutdown_endpoint == "/stop"


class TestIsPortInUse:
    """Tests for AppSingleInstance.is_port_in_use static method."""

    def test_port_free_returns_false(self) -> None:
        """Test that a non-zero connect_ex result means the port is free."""
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 1
        with patch("socket.socket", return_value=mock_sock):
            assert AppSingleInstance.is_port_in_use(8080) is False

    def test_port_occupied_returns_true(self) -> None:
        """Test that a zero connect_ex result means the port is occupied."""
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 0
        with patch("socket.socket", return_value=mock_sock):
            assert AppSingleInstance.is_port_in_use(8080) is True


class TestShutdownPreviousInstance:
    """Tests for AppSingleInstance.shutdown_previous_instance."""

    def test_port_already_free(self) -> None:
        """Test that no action is taken when port is already free."""
        instance = AppSingleInstance(port_number=8080)
        with patch.object(
            AppSingleInstance, "is_port_in_use", return_value=False
        ), patch.object(
            AppSingleInstance, "try_shutdown_with_endpoint"
        ) as mock_endpoint:
            instance.shutdown_previous_instance()
        mock_endpoint.assert_not_called()

    def test_freed_after_endpoint_shutdown(self) -> None:
        """Test that endpoint shutdown frees the port successfully."""
        instance = AppSingleInstance(port_number=8080)
        call_count: List[int] = [0]

        def is_in_use(_port: int) -> bool:
            idx = call_count[0]
            call_count[0] += 1
            return idx == 0  # True on first call, False on second

        with patch.object(
            AppSingleInstance, "is_port_in_use", side_effect=is_in_use
        ), patch.object(
            AppSingleInstance, "try_shutdown_with_endpoint"
        ) as mock_endpoint:
            instance.shutdown_previous_instance()
        mock_endpoint.assert_called_once()

    def test_freed_after_kill(self) -> None:
        """Test that process kill frees the port when endpoint fails."""
        instance = AppSingleInstance(port_number=8080)
        call_count: List[int] = [0]

        def is_in_use(_port: int) -> bool:
            idx = call_count[0]
            call_count[0] += 1
            return idx < 2  # True for first two calls, False on third

        with patch.object(
            AppSingleInstance, "is_port_in_use", side_effect=is_in_use
        ), patch.object(AppSingleInstance, "try_shutdown_with_endpoint"), patch.object(
            AppSingleInstance, "try_kill_proc_using_port"
        ) as mock_kill:
            instance.shutdown_previous_instance()
        mock_kill.assert_called_once()

    def test_raises_when_port_still_occupied(self) -> None:
        """Test RuntimeError when the port cannot be freed."""
        instance = AppSingleInstance(port_number=8080)
        with patch.object(
            AppSingleInstance, "is_port_in_use", return_value=True
        ), patch.object(AppSingleInstance, "try_shutdown_with_endpoint"), patch.object(
            AppSingleInstance, "try_kill_proc_using_port"
        ):
            with pytest.raises(RuntimeError, match="Port 8080 is in use"):
                instance.shutdown_previous_instance()


class TestTryShutdownWithEndpoint:
    """Tests for AppSingleInstance.try_shutdown_with_endpoint."""

    def test_https_success(self) -> None:
        """Test that a successful HTTPS request shuts down the previous instance."""
        instance = AppSingleInstance(port_number=8080)
        with patch("operate.utils.single_instance.requests.get") as mock_get, patch(
            "operate.utils.single_instance.time.sleep"
        ):
            instance.try_shutdown_with_endpoint()
        mock_get.assert_called_once()

    def test_ssl_error_fallback_to_http(self) -> None:
        """Test HTTP fallback when HTTPS fails with SSLError."""
        instance = AppSingleInstance(port_number=8080)
        with patch(
            "operate.utils.single_instance.requests.get",
            side_effect=[requests.exceptions.SSLError("ssl"), MagicMock()],
        ) as mock_get, patch("operate.utils.single_instance.time.sleep"):
            instance.try_shutdown_with_endpoint()
        assert mock_get.call_count == 2

    def test_ssl_error_http_fallback_also_fails(self) -> None:
        """Test that HTTP fallback failure is handled without raising."""
        instance = AppSingleInstance(port_number=8080)
        with patch(
            "operate.utils.single_instance.requests.get",
            side_effect=[
                requests.exceptions.SSLError("ssl"),
                Exception("http fail"),
            ],
        ), patch("operate.utils.single_instance.time.sleep"):
            instance.try_shutdown_with_endpoint()  # should not raise

    def test_general_exception_handled(self) -> None:
        """Test that a general exception is handled without raising."""
        instance = AppSingleInstance(port_number=8080)
        with patch(
            "operate.utils.single_instance.requests.get",
            side_effect=Exception("generic error"),
        ):
            instance.try_shutdown_with_endpoint()  # should not raise


class TestTryKillProcUsingPort:
    """Tests for AppSingleInstance.try_kill_proc_using_port."""

    def test_no_matching_connection(self) -> None:
        """Test that no action is taken when no connection matches the port."""
        instance = AppSingleInstance(port_number=8080)
        mock_conn = MagicMock()
        mock_conn.laddr.port = 9999
        mock_conn.status = psutil.CONN_LISTEN
        with patch(
            "operate.utils.single_instance.psutil.net_connections",
            return_value=[mock_conn],
        ), patch.object(AppSingleInstance, "kill_process_tree") as mock_kill:
            instance.try_kill_proc_using_port()
        mock_kill.assert_not_called()

    def test_pid_none_returns_early(self) -> None:
        """Test that a None PID is handled without killing."""
        instance = AppSingleInstance(port_number=8080)
        mock_conn = MagicMock()
        mock_conn.laddr.port = 8080
        mock_conn.status = psutil.CONN_LISTEN
        mock_conn.pid = None
        with patch(
            "operate.utils.single_instance.psutil.net_connections",
            return_value=[mock_conn],
        ), patch.object(AppSingleInstance, "kill_process_tree") as mock_kill:
            instance.try_kill_proc_using_port()
        mock_kill.assert_not_called()

    def test_kills_matching_process(self) -> None:
        """Test that the matching process is killed."""
        instance = AppSingleInstance(port_number=8080)
        mock_conn = MagicMock()
        mock_conn.laddr.port = 8080
        mock_conn.status = psutil.CONN_LISTEN
        mock_conn.pid = 1234
        with patch(
            "operate.utils.single_instance.psutil.net_connections",
            return_value=[mock_conn],
        ), patch.object(AppSingleInstance, "kill_process_tree") as mock_kill, patch(
            "operate.utils.single_instance.time.sleep"
        ):
            instance.try_kill_proc_using_port()
        mock_kill.assert_called_once_with(1234)

    def test_kill_error_is_handled(self) -> None:
        """Test that errors during process kill are handled without raising."""
        instance = AppSingleInstance(port_number=8080)
        mock_conn = MagicMock()
        mock_conn.laddr.port = 8080
        mock_conn.status = psutil.CONN_LISTEN
        mock_conn.pid = 1234
        with patch(
            "operate.utils.single_instance.psutil.net_connections",
            return_value=[mock_conn],
        ), patch.object(
            AppSingleInstance,
            "kill_process_tree",
            side_effect=Exception("kill failed"),
        ):
            instance.try_kill_proc_using_port()  # should not raise


class TestKillProcessTree:
    """Tests for AppSingleInstance.kill_process_tree."""

    def test_success_with_children(self) -> None:
        """Test terminating a process tree with child processes."""
        instance = AppSingleInstance(port_number=8080)
        mock_child = MagicMock()
        mock_parent = MagicMock()
        mock_parent.children.return_value = [mock_child]
        mock_parent.wait.return_value = None
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch(
            "operate.utils.single_instance.psutil.wait_procs",
            return_value=([], []),
        ):
            instance.kill_process_tree(1234)
        mock_child.terminate.assert_called_once()
        mock_parent.terminate.assert_called_once()

    def test_timeout_triggers_kill(self) -> None:
        """Test that a timeout on wait causes kill() to be called."""
        instance = AppSingleInstance(port_number=8080)
        mock_parent = MagicMock()
        mock_parent.children.return_value = []
        mock_parent.wait.side_effect = psutil.TimeoutExpired(3)
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch(
            "operate.utils.single_instance.psutil.wait_procs",
            return_value=([], []),
        ):
            instance.kill_process_tree(1234)
        mock_parent.kill.assert_called_once()

    def test_still_alive_children_are_killed(self) -> None:
        """Test that children still alive after terminate() are killed."""
        instance = AppSingleInstance(port_number=8080)
        mock_child_alive = MagicMock()
        mock_parent = MagicMock()
        mock_parent.children.return_value = [mock_child_alive]
        mock_parent.wait.return_value = None
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch(
            "operate.utils.single_instance.psutil.wait_procs",
            return_value=([], [mock_child_alive]),  # one child still alive
        ):
            instance.kill_process_tree(1234)
        mock_child_alive.kill.assert_called_once()

    def test_no_such_process_is_handled(self) -> None:
        """Test that NoSuchProcess is handled without raising."""
        instance = AppSingleInstance(port_number=8080)
        with patch(
            "operate.utils.single_instance.psutil.Process",
            side_effect=psutil.NoSuchProcess(pid=1234),
        ):
            instance.kill_process_tree(1234)  # should not raise

    def test_general_exception_is_handled(self) -> None:
        """Test that general exceptions are handled without raising."""
        instance = AppSingleInstance(port_number=8080)
        with patch(
            "operate.utils.single_instance.psutil.Process",
            side_effect=Exception("error"),
        ):
            instance.kill_process_tree(1234)  # should not raise


class TestParentWatchdog:
    """Tests for ParentWatchdog.

    Key constraint: in Python 3.10, calling task.cancel() *before* the task
    ever awaits sets Task._must_cancel=True.  When the coroutine then exits
    normally (even after catching CancelledError), asyncio marks the task as
    cancelled and `await task` raises CancelledError.

    To avoid this, every test that calls stop() first does at least one
    `await asyncio.sleep(0)` so the task reaches its own asyncio.sleep and
    has a live _fut_waiter.  cancel() then cancels that future directly,
    _must_cancel is never set, and the task exits gracefully.
    """

    async def test_start_creates_task(self) -> None:
        """Test that start() creates and returns a monitoring task."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        mock_parent = MagicMock()
        mock_parent.is_running.return_value = True
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch("os.getppid", return_value=1234):
            task = watchdog.start()
            assert task is not None
            await asyncio.sleep(0)  # let task reach its asyncio.sleep(0)
            await watchdog.stop()  # cancel via _fut_waiter – no CancelledError

    async def test_start_already_running_returns_same_task(self) -> None:
        """Test that calling start() twice returns the same task."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        mock_parent = MagicMock()
        mock_parent.is_running.return_value = True
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch("os.getppid", return_value=1234):
            task1 = watchdog.start()
            task2 = watchdog.start()
            assert task1 is task2
            await asyncio.sleep(0)  # let task reach its asyncio.sleep(0)
            await watchdog.stop()

    async def test_stop_cancels_task(self) -> None:
        """Test that stop() cancels the monitoring task and clears state."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        mock_parent = MagicMock()
        mock_parent.is_running.return_value = True
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch("os.getppid", return_value=1234):
            watchdog.start()
            await asyncio.sleep(0)  # task reaches asyncio.sleep(0)
            await watchdog.stop()  # cancel via _fut_waiter, exits cleanly
        assert watchdog._task is None
        assert watchdog._stopping is True

    async def test_stop_without_start_does_not_raise(self) -> None:
        """Test that stop() without a prior start() does not raise."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit)
        await watchdog.stop()  # should not raise
        assert watchdog._stopping is True

    async def test_watch_loop_calls_callback_when_parent_not_running(
        self,
    ) -> None:
        """Test that the callback is invoked when the parent process stops."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        mock_parent = MagicMock()
        mock_parent.is_running.return_value = False
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch("os.getppid", return_value=2):
            task = asyncio.create_task(watchdog._watch_loop())
            await task  # completes after break
        on_exit.assert_called_once()

    async def test_watch_loop_calls_callback_on_no_such_process(self) -> None:
        """Test that the callback is invoked when the parent PID does not exist."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        with patch(
            "operate.utils.single_instance.psutil.Process",
            side_effect=psutil.NoSuchProcess(pid=1234),
        ), patch("os.getppid", return_value=1234):
            task = asyncio.create_task(watchdog._watch_loop())
            await task  # completes after break
        on_exit.assert_called_once()

    async def test_watch_loop_cancelled_gracefully(self) -> None:
        """Test that task cancellation is handled gracefully."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        mock_parent = MagicMock()
        mock_parent.is_running.return_value = True
        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch("os.getppid", return_value=1234):
            task = asyncio.create_task(watchdog._watch_loop())
            await asyncio.sleep(0)  # let the task reach asyncio.sleep(0)
            task.cancel()  # cancels via _fut_waiter; task handles CancelledError
            with suppress(asyncio.CancelledError):
                await task

    async def test_watch_loop_inner_exception_is_logged(self) -> None:
        """Test that non-psutil exceptions in the inner loop are caught and logged."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        call_count: List[int] = [0]

        def flaky_process(_pid: int) -> MagicMock:
            """Raise a generic error on first call, then signal stop."""
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("unexpected psutil error")
            watchdog._stopping = True
            mock_parent = MagicMock()
            mock_parent.is_running.return_value = True
            return mock_parent

        with patch(
            "operate.utils.single_instance.psutil.Process", side_effect=flaky_process
        ), patch("os.getppid", return_value=1234):
            task = asyncio.create_task(watchdog._watch_loop())
            await task  # first iteration logs error, second exits via _stopping

    async def test_watch_loop_outer_exception_is_logged(self) -> None:
        """Test that an exception escaping the while loop is caught by the outer handler."""
        on_exit = AsyncMock()
        watchdog = ParentWatchdog(on_parent_exit=on_exit, check_interval=0)
        mock_parent = MagicMock()
        mock_parent.is_running.return_value = True
        sleep_call_count: List[int] = [0]

        async def _failing_sleep(_seconds: float) -> None:
            sleep_call_count[0] += 1
            raise RuntimeError("sleep exploded")

        with patch(
            "operate.utils.single_instance.psutil.Process", return_value=mock_parent
        ), patch("os.getppid", return_value=1234), patch(
            "operate.utils.single_instance.asyncio.sleep",
            side_effect=_failing_sleep,
        ):
            task = asyncio.create_task(watchdog._watch_loop())
            await task  # outer except Exception catches RuntimeError; task finishes
