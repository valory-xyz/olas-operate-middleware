"""
Tests for health_checker.healthcheck_job error handling.

Part of Phase 1.2: Error Handling Improvements - documenting exception handling
behavior in the healthcheck job. The remaining broad exception catches in this
method (lines 273 and 283) re-raise exceptions after logging, which is acceptable
behavior for retry logic and top-level handlers.
"""

import asyncio
import itertools
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from operate.operate_types import StakingReconcileOutcome
from operate.services.health_checker import HealthChecker

# Save the REAL asyncio.sleep before any test patches it so nested-function
# tests can still perform real timing waits inside a patch("asyncio.sleep") block.
_REAL_SLEEP = asyncio.sleep


async def _instant_sleep(*_args: object, **_kwargs: object) -> None:
    """Yield to the event loop once without actually sleeping.

    An empty async def with no awaits never yields to the event loop, which
    starves timers.  Using _REAL_SLEEP(0) (the real asyncio.sleep, captured
    before any patches) schedules a single call_soon callback so the event
    loop can process timers and other pending tasks between iterations.
    """
    await _REAL_SLEEP(0)


class TestHealthcheckJobErrorHandling:
    """Test error handling behavior in healthcheck_job method."""

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Create a HealthChecker instance for testing."""
        mock_service_manager = MagicMock()
        mock_logger = MagicMock()
        return HealthChecker(service_manager=mock_service_manager, logger=mock_logger)

    @pytest.mark.asyncio
    async def test_healthcheck_job_service_load_happens_before_try_block(
        self, health_checker: HealthChecker
    ) -> None:
        """Test that service loading failure is not caught (happens before try block).

        NOTE: This documents current behavior where service loading at line 140
        happens before the try block at line 141, so exceptions during load
        are not logged by the top-level handler. This could be considered a bug.
        """
        service_config_id = "nonexistent-service"

        # Mock service manager to raise error when loading service
        health_checker._service_manager.load.side_effect = ValueError(
            "Service not found"
        )

        # Should raise the exception without logging (current behavior)
        with pytest.raises(ValueError, match="Service not found"):
            await health_checker.healthcheck_job(service_config_id)

        # Logger exception should NOT be called because load happens before try block
        health_checker.logger.exception.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_healthcheck_job_handles_cancellation(
        self, health_checker: HealthChecker
    ) -> None:
        """Test that healthcheck job can be cancelled properly."""
        service_config_id = "test-service"

        # Mock service to provide path
        mock_service = MagicMock()
        mock_service.path = MagicMock()
        health_checker._service_manager.load.return_value = mock_service

        # Mock check_service_health to avoid real aiohttp calls — an
        # in-flight connection to localhost can block task cancellation on
        # some Python versions (observed on 3.11), causing the test to hang.
        async def mock_check(*args: object, **kwargs: object) -> bool:
            await _REAL_SLEEP(0)  # yield to event loop
            return True

        with (
            patch.object(health_checker, "check_service_health", mock_check),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
        ):
            # Create a task that we'll cancel
            task = asyncio.create_task(
                health_checker.healthcheck_job(service_config_id)
            )

            # Give it a moment to start
            await _REAL_SLEEP(0.1)

            # Cancel the task
            task.cancel()

            # Should raise CancelledError
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_healthcheck_job_exception_handler_logs_and_reraises(
        self, health_checker: HealthChecker
    ) -> None:
        """Test that top-level exception handler logs before re-raising.

        The broad exception handler at line 283 catches all exceptions, logs them
        with service context, and re-raises. This is acceptable behavior for a
        top-level handler as it doesn't mask errors.
        """
        service_config_id = "test-service"

        # Mock service with path
        mock_service = MagicMock()
        mock_service.path = MagicMock()
        health_checker._service_manager.load.return_value = mock_service

        # Inject an error into the healthcheck job by making logger.info raise
        # This happens inside the try block (line 142-143)
        health_checker.logger.info.side_effect = RuntimeError("Unexpected error")  # type: ignore[attr-defined]

        # Should raise the exception (not swallow it)
        with pytest.raises(RuntimeError, match="Unexpected error"):
            await health_checker.healthcheck_job(service_config_id)

        # Should have logged with exception handler before re-raising
        health_checker.logger.exception.assert_called_once()  # type: ignore[attr-defined]
        call_args = str(health_checker.logger.exception.call_args)  # type: ignore[attr-defined]

        # Should mention the service ID in the log
        assert service_config_id in call_args


class TestHealthcheckJobExceptionHandlingBehavior:
    """Document the exception handling patterns in healthcheck_job.

    The healthcheck_job method has two broad exception handlers:

    1. Line 273: Catches exceptions during service restart
       - Implements retry logic with failfast protection
       - Re-raises after max retries
       - This is acceptable: retry logic needs to catch any error

    2. Line 283: Top-level exception handler
       - Catches all exceptions in the healthcheck job
       - Logs with service context
       - Re-raises the exception
       - This is acceptable: top-level handler providing safety net

    Both handlers re-raise exceptions rather than swallowing them, which means
    they don't mask errors. They add logging context, which is helpful for
    debugging.
    """

    def test_restart_exception_handler_reraises_after_retries(self) -> None:
        """Document that restart exception handler (line 273) re-raises.

        The exception handler in the restart retry loop:
        - Catches any exception from _restart()
        - Checks failfast conditions
        - If over limits: stops service and re-raises
        - If under limits: logs and retries after sleep

        This is acceptable broad exception handling because:
        1. It's implementing retry logic
        2. It re-raises after max retries (line 278)
        3. Retry logic legitimately needs to catch any error
        """
        # This is a documentation test - just verify the pattern exists
        import inspect

        from operate.services.health_checker import HealthChecker

        source = inspect.getsource(HealthChecker.healthcheck_job)

        # Verify the except Exception pattern exists in restart logic
        assert "except Exception:" in source
        # Verify it re-raises
        assert "raise" in source

    def test_top_level_exception_handler_logs_and_reraises(self) -> None:
        """Document that top-level exception handler (line 283) re-raises.

        The top-level exception handler:
        - Catches all exceptions in healthcheck_job
        - Logs with service_config_id for context
        - Re-raises the exception (line 287)

        This is acceptable broad exception handling because:
        1. It's a top-level safety net
        2. It adds valuable logging context
        3. It re-raises rather than swallowing the error
        """
        # This is a documentation test - just verify the pattern exists
        import inspect

        from operate.services.health_checker import HealthChecker

        source = inspect.getsource(HealthChecker.healthcheck_job)

        # Verify the pattern exists
        assert "except Exception:" in source
        assert "logger.exception" in source or "self.logger.exception" in source
        assert "raise" in source


class TestHealthCheckerJobManagement:
    """Tests for start_for_service and stop_for_service job management."""

    @pytest.mark.asyncio
    async def test_start_for_service_cancels_existing_job(self) -> None:
        """Test that start_for_service cancels an existing job for the same service ID."""
        mock_service = MagicMock()
        mock_service.path = MagicMock()
        mock_service_manager = MagicMock()
        mock_service_manager.load.return_value = mock_service

        health_checker = HealthChecker(
            service_manager=mock_service_manager,
            logger=MagicMock(),
        )

        service_config_id = "test-service"

        # Pre-populate _jobs with a mock existing task
        old_task = MagicMock()
        health_checker._jobs[service_config_id] = old_task

        # Mock healthcheck_job to be a quick-completing coroutine
        async def mock_healthcheck_job(**kwargs: object) -> None:
            await asyncio.sleep(0)

        with patch.object(health_checker, "healthcheck_job", mock_healthcheck_job):
            health_checker.start_for_service(service_config_id)

        # Old task should have been cancelled
        old_task.cancel.assert_called_once()

        # A new task should be registered
        assert service_config_id in health_checker._jobs
        assert health_checker._jobs[service_config_id] is not old_task

        # Clean up: cancel the new task
        new_task = health_checker._jobs[service_config_id]
        new_task.cancel()
        try:
            await new_task
        except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
            pass

    def test_stop_for_service_cancellation_returns_false_logs_info(self) -> None:
        """Test that stop_for_service logs info when task cancellation returns False."""
        health_checker = HealthChecker(
            service_manager=MagicMock(),
            logger=MagicMock(),
        )
        service_config_id = "test-service"

        # Mock task whose cancel() returns False
        mock_task = MagicMock()
        mock_task.cancel.return_value = False
        health_checker._jobs[service_config_id] = mock_task

        health_checker.stop_for_service(service_config_id)

        mock_task.cancel.assert_called_once()

        # Should log the cancellation failure
        health_checker.logger.info.assert_called()  # type: ignore[attr-defined]
        info_calls_str = str(health_checker.logger.info.call_args_list)  # type: ignore[attr-defined]
        assert (
            "failed" in info_calls_str.lower()
            or "cancellation" in info_calls_str.lower()
        )

        # Task should be removed from _jobs
        assert service_config_id not in health_checker._jobs

    def test_stop_for_service_uses_call_soon_threadsafe_when_loop_running(
        self,
    ) -> None:
        """Test that stop_for_service uses call_soon_threadsafe when event loop is running."""
        health_checker = HealthChecker(
            service_manager=MagicMock(),
            logger=MagicMock(),
        )
        service_config_id = "test-service"

        mock_task = MagicMock()
        health_checker._jobs[service_config_id] = mock_task

        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        health_checker._loop = mock_loop

        health_checker.stop_for_service(service_config_id)

        mock_loop.call_soon_threadsafe.assert_called_once_with(mock_task.cancel)
        mock_task.cancel.assert_not_called()
        assert service_config_id not in health_checker._jobs

    @pytest.mark.asyncio
    async def test_healthcheck_job_runs_when_service_always_healthy(self) -> None:
        """Test that healthcheck_job starts and runs without error when the service is always healthy."""
        mock_service = MagicMock()
        mock_service.path = MagicMock()
        mock_service_manager = MagicMock()
        mock_service_manager.load.return_value = mock_service

        health_checker = HealthChecker(
            service_manager=mock_service_manager,
            logger=MagicMock(),
            port_up_timeout=1,
        )

        service_config_id = "test-service"

        async def always_healthy(*args: object, **kwargs: object) -> bool:
            return True

        with patch.object(health_checker, "check_service_health", always_healthy):
            task = asyncio.create_task(
                health_checker.healthcheck_job(service_config_id)
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        # Job ran — at minimum the startup log should have been emitted
        health_checker.logger.info.assert_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers shared by the nested-function tests
# ---------------------------------------------------------------------------


async def _no_timeout(coro: object, timeout: object = None, **kwargs: object) -> object:
    """Replace asyncio.wait_for so _check_port_ready has no timeout."""
    return await coro  # type: ignore[misc]


def _clock_serving(values: t.Iterable[float]) -> t.Any:
    """Patch the job's clock to serve `values` in order, then hold the last one.

    `healthcheck_job` reads the clock once per restart, to stamp the record it is
    about to append, so one value is consumed per restart. The job loops until it
    is cancelled or raises, so an infinite iterable is the right shape for a test
    that expects no escalation.

    :param values: the successive readings to serve.
    :return: the patch context manager.
    """
    remaining = iter(values)
    last = [0.0]

    def _tick() -> float:
        last[0] = next(remaining, last[0])
        return last[0]

    return patch("operate.services.health_checker.time.time", side_effect=_tick)


class TestHealthCheckerStopForServiceEarlyReturn:
    """Tests for the early-return guard in stop_for_service (line 96)."""

    def test_stop_for_service_returns_early_when_not_in_jobs(self) -> None:
        """Test stop_for_service returns immediately when service is not tracked (line 96)."""
        health_checker = HealthChecker(service_manager=MagicMock(), logger=MagicMock())
        health_checker.stop_for_service("nonexistent-service")
        # No log calls should be made because we return before them
        health_checker.logger.info.assert_not_called()  # type: ignore[attr-defined]
        health_checker.logger.warning.assert_not_called()  # type: ignore[attr-defined]


class TestHealthCheckerNestedAsyncFunctions:
    """Tests for nested async functions inside healthcheck_job (lines 192-320).

    Strategy: patch asyncio.sleep inside health_checker with _instant_sleep (no-op)
    to avoid long internal delays.  For test-side timing we use _REAL_SLEEP which
    was captured at module import before any patches are applied.
    """

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Return a HealthChecker wired with fast defaults."""
        mock_sm = MagicMock()
        mock_sm.load.return_value.path = Path("/fake/service")
        return HealthChecker(
            service_manager=mock_sm,
            logger=MagicMock(),
            sleep_period=0,
            number_of_fails=1,
        )

    async def test_wait_for_port_logs_on_client_connection_error(
        self, health_checker: HealthChecker
    ) -> None:
        """Test _wait_for_port catches ClientConnectionError and logs error (lines 192-196)."""
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            if call_count[0] == 1:
                raise aiohttp.ClientConnectionError("connection refused")
            return True

        health_checker.check_service_health = mock_check  # type: ignore[assignment]

        with (
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.1)  # real wait — gives the task time to run
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        error_calls = str(
            health_checker.logger.error.call_args_list  # type: ignore[attr-defined]
        )
        assert "error connecting http port" in error_calls

    async def test_check_port_ready_returns_false_on_timeout(
        self, health_checker: HealthChecker
    ) -> None:
        """Test _check_port_ready returns False when asyncio.TimeoutError is raised (lines 206-207)."""
        health_checker._service_manager.stop_service_locally = MagicMock()
        health_checker._service_manager.deploy_service_locally = MagicMock()

        with (
            patch(
                "operate.services.health_checker.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        info_calls = str(
            health_checker.logger.info.call_args_list  # type: ignore[attr-defined]
        )
        assert "port not ready" in info_calls

    async def test_check_health_client_connection_error_logs_warning(
        self, health_checker: HealthChecker
    ) -> None:
        """Test _check_health catches ClientConnectionError and logs warning (lines 219-228)."""
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            if call_count[0] <= 1:
                return True  # Port-ready check passes
            raise aiohttp.ClientConnectionError("health port error")

        health_checker.check_service_health = mock_check  # type: ignore[assignment]
        health_checker._service_manager.stop_service_locally = MagicMock()
        health_checker._service_manager.deploy_service_locally = MagicMock()

        with (
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        warning_calls = str(
            health_checker.logger.warning.call_args_list  # type: ignore[attr-defined]
        )
        assert "port read failed" in warning_calls

    async def test_check_health_client_connection_error_calls_debug_exc_info(
        self, health_checker: HealthChecker
    ) -> None:
        """Test _check_health calls logger.debug with exc_info when failure threshold is met."""
        # Edge case: with threshold 0, first connection error enters the debug branch.
        health_checker.number_of_fails = 0
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            if call_count[0] == 1:
                return True  # Port-ready check passes
            raise aiohttp.ClientConnectionError("health port error")

        health_checker.check_service_health = mock_check  # type: ignore[assignment]
        health_checker._service_manager.stop_service_locally = MagicMock()
        health_checker._service_manager.deploy_service_locally = MagicMock()

        with (
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        # logger.debug should have been called with exc_info=True for the connection error
        debug_calls = health_checker.logger.debug.call_args_list  # type: ignore[attr-defined]
        assert any(
            call.kwargs.get("exc_info") is True for call in debug_calls
        ), "Expected logger.debug to be called with exc_info=True"

    async def test_check_health_exhausts_fails_triggers_restart(
        self, health_checker: HealthChecker
    ) -> None:
        """Test _check_health exits and logs error after fail threshold (lines 240-243)."""
        health_checker.number_of_fails = 1
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            return call_count[0] == 1  # True only for port-ready check

        health_checker.check_service_health = mock_check  # type: ignore[assignment]
        health_checker._service_manager.stop_service_locally = MagicMock()
        health_checker._service_manager.deploy_service_locally = MagicMock()

        with (
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        error_calls = str(
            health_checker.logger.error.call_args_list  # type: ignore[attr-defined]
        )
        assert "restart" in error_calls

    async def test_restart_calls_stop_and_deploy_service(
        self, health_checker: HealthChecker
    ) -> None:
        """Test _restart calls stop_service_locally and deploy_service_locally (lines 250-264)."""
        health_checker.number_of_fails = 1
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            return call_count[0] == 1

        health_checker.check_service_health = mock_check  # type: ignore[assignment]

        with (
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.2)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        health_checker._service_manager.stop_service_locally.assert_called_with(
            service_config_id="test-service"
        )
        health_checker._service_manager.deploy_service_locally.assert_called_with(
            service_config_id="test-service"
        )

    async def test_restart_failfast_calls_stop_and_reraises(
        self, health_checker: HealthChecker
    ) -> None:
        """Test failfast triggers _stop and raises a RuntimeError (lines 269-280, 312-317)."""
        health_checker.number_of_fails = 1
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            return call_count[0] == 1

        health_checker.check_service_health = mock_check  # type: ignore[assignment]
        health_checker._service_manager.deploy_service_locally.side_effect = (
            RuntimeError("deploy failed")
        )

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 1),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            with pytest.raises(RuntimeError, match="stopped by failfast"):
                await health_checker.healthcheck_job("test-service")

        # stop_service_locally called at least once (inside _restart + inside _stop)
        assert health_checker._service_manager.stop_service_locally.call_count >= 1

    async def test_restart_logs_problem_before_failfast(
        self, health_checker: HealthChecker
    ) -> None:
        """Test logger.exception and sleep are called when under failfast limit (lines 319-320)."""
        health_checker.number_of_fails = 1
        call_count = [0]
        deploy_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            return call_count[0] == 1

        def mock_deploy(**kwargs: object) -> None:
            deploy_count[0] += 1
            if deploy_count[0] == 1:
                raise RuntimeError("temporary failure")

        health_checker.check_service_health = mock_check  # type: ignore[assignment]
        health_checker._service_manager.deploy_service_locally.side_effect = mock_deploy

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 3),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.2)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        exception_calls = str(
            health_checker.logger.exception.call_args_list  # type: ignore[attr-defined]
        )
        assert "Restart problem" in exception_calls

    async def test_check_health_resets_the_fail_streak_on_a_healthy_probe(
        self, health_checker: HealthChecker
    ) -> None:
        """A healthy probe mid-streak restarts the count, it does not carry it.

        Sequence: port-ready (True), health True (resets fails), health False
        (fail threshold reached) → return, then restart.
        """
        health_checker.number_of_fails = 1
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            if call_count[0] <= 2:
                return True  # call 1: port-ready, call 2: healthy inside _check_health
            return False  # call 3+: unhealthy

        health_checker.check_service_health = mock_check  # type: ignore[assignment]
        health_checker._service_manager.stop_service_locally = MagicMock()
        health_checker._service_manager.deploy_service_locally = MagicMock()

        with (
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=1000.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.2)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        # The healthy probe did not end the loop; the failure after it did
        assert call_count[0] >= 3
        error_calls = str(
            health_checker.logger.error.call_args_list  # type: ignore[attr-defined]
        )
        assert "restart" in error_calls


class TestFailfastBehaviorPinned:
    """Tests pinning the failfast escalation rule.

    The rule is a rolling window: a service is stopped once FAILFAST_NUM restarts
    have been recorded inside the last FAILFAST_WINDOW seconds. What it replaced
    compared the age of the *oldest surviving* record against the same constant,
    so a long span with few restarts escalated sooner than a short span with many
    -- backwards, and the arm that actually stopped this ticket's service.

    Each test is designed to fail against a specific code mutation:
    1. Reverting unconditional post-restart failfast check → test 1 fails
    2. Dropping the prune, so records accumulate for the life of the job → test 2 fails
    3. Reintroducing a continuous-health reset of the budget → test 3 fails
    4. Changing `<=` to `<` in the window comparison → test 4 fails
    5. Counting a skipped reconciliation towards the window → test 5 fails
    """

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Return a HealthChecker wired with fast defaults."""
        mock_sm = MagicMock()
        mock_sm.load.return_value.path = Path("/fake/service")
        return HealthChecker(
            service_manager=mock_sm,
            logger=MagicMock(),
            sleep_period=0,
            number_of_fails=1,
        )

    @staticmethod
    def _always_unhealthy_at(
        health_checker: HealthChecker, restart_times: t.Iterable[float]
    ) -> t.Any:
        """Drive a job whose agent never recovers, restarting at the given times.

        :param health_checker: the checker to drive.
        :param restart_times: the clock value to serve at each successive restart.
        :return: the patch context manager for the job's clock.
        """

        async def always_unhealthy(*_args: object, **_kwargs: object) -> bool:
            return False

        health_checker.check_service_health = always_unhealthy  # type: ignore[assignment]
        health_checker._service_manager.stop_service_locally = MagicMock()
        health_checker._service_manager.deploy_service_locally = MagicMock()
        return _clock_serving(restart_times)

    @pytest.mark.asyncio
    async def test_failfast_fires_on_successful_restarts(
        self, health_checker: HealthChecker
    ) -> None:
        """True positive: _restart succeeds but agent is always unhealthy → failfast fires.

        Pre-fix code only checked failfast inside 'except Exception:', so a
        successful restart never counted toward escalation.  This test must
        fail against that code.
        """
        clock = self._always_unhealthy_at(health_checker, [0.0])

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 3),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            clock,
        ):
            with pytest.raises(RuntimeError, match="stopped by failfast"):
                await health_checker.healthcheck_job("test-service")

        # _stop called stop_service_locally for failfast
        assert health_checker._service_manager.stop_service_locally.call_count >= 1

    @pytest.mark.asyncio
    async def test_failfast_no_fire_when_restarts_are_spread_beyond_the_window(
        self, health_checker: HealthChecker
    ) -> None:
        """False-positive guard: restarts that have aged out are not evidence.

        A service restarting once an hour is recovering badly but it is not
        failing to recover, and stopping it costs the operator the rest of the
        epoch. Each restart here lands one second past the window, so the
        previous record is pruned and the count never reaches two.
        """
        step = HealthChecker.FAILFAST_WINDOW + 1.0
        spaced = (i * step for i in itertools.count())
        clock = self._always_unhealthy_at(health_checker, spaced)

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 2),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            clock,
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except RuntimeError:
                pytest.fail(
                    "Failfast should not fire when restarts are spread beyond the window"
                )

        # At least 3 restarts ran (past FAILFAST_NUM=2), proving records aged out
        assert health_checker._service_manager.deploy_service_locally.call_count >= 3

    @pytest.mark.asyncio
    async def test_failfast_window_is_not_cleared_by_a_healthy_stretch(
        self, health_checker: HealthChecker
    ) -> None:
        """Recovering for a while and failing again is the case failfast is for.

        The removed rule cleared the whole budget after 900 s of continuous
        health, so a service alternating long healthy stretches with restarts
        never escalated however many restarts it took. Here the two restarts are
        1100 s apart -- past that old bar, well inside the window -- and the
        agent does report healthy in between, so a reintroduced continuous-health
        reset would clear the budget here and this test would fail.
        """
        call_count = [0]

        async def cycling_check(*args: object, **kwargs: object) -> bool:
            call_count[0] += 1
            # Port-ready (idx 0): False; health call 1 (idx 1): True; call 2: False
            return (call_count[0] - 1) % 3 == 1

        health_checker.check_service_health = cycling_check  # type: ignore[assignment]
        health_checker._service_manager.stop_service_locally = MagicMock()
        health_checker._service_manager.deploy_service_locally = MagicMock()

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 2),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            _clock_serving([100.0, 1200.0]),
        ):
            with pytest.raises(RuntimeError, match="stopped by failfast"):
                await health_checker.healthcheck_job("test-service")

        # The agent really did report healthy between the two restarts
        assert call_count[0] >= 6
        assert health_checker._service_manager.stop_service_locally.call_count >= 1

    @pytest.mark.asyncio
    async def test_failfast_counts_a_record_exactly_at_the_window_edge(
        self, health_checker: HealthChecker
    ) -> None:
        """Boundary: a record exactly FAILFAST_WINDOW old is still inside the window.

        The prune keeps records with `now - at <= FAILFAST_WINDOW`. Only the first
        two restarts sit exactly a window apart; every one after them is spread
        beyond it, so changing that comparison to `<` drops the first record and
        the count never reaches two at all.
        """
        window = float(HealthChecker.FAILFAST_WINDOW)
        edge = itertools.chain(
            [0.0, window],
            (window + i * (window + 1.0) for i in itertools.count(1)),
        )
        clock = self._always_unhealthy_at(health_checker, edge)

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 2),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            clock,
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.3)
            task.cancel()
            ended_on: t.Optional[Exception] = None
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pylint: disable=broad-except
                ended_on = exc

        assert isinstance(
            ended_on, RuntimeError
        ), "A record exactly at the window edge must still count towards failfast"
        assert "stopped by failfast" in str(ended_on)
        assert health_checker._service_manager.stop_service_locally.call_count >= 1

    @pytest.mark.asyncio
    async def test_skipped_reconciliation_does_not_fill_the_window(
        self, health_checker: HealthChecker
    ) -> None:
        """A restart that never happened must not spend window budget.

        SKIPPED means another caller is mid-reconciliation and will deploy the
        service itself, so the record just appended is popped. Under a rolling
        window that pop has to survive the prune, or a service waiting on someone
        else's transaction would be stopped for it.
        """
        sm = health_checker._service_manager
        sm.reconcile_staking_for_restart.return_value = StakingReconcileOutcome.SKIPPED
        clock = self._always_unhealthy_at(health_checker, [0.0])

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 2),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            clock,
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except RuntimeError:
                pytest.fail("A skipped reconciliation must not trigger failfast")

        sm.deploy_service_locally.assert_not_called()

    @pytest.mark.asyncio
    async def test_failfast_stop_leaves_the_reason_readable(
        self, health_checker: HealthChecker
    ) -> None:
        """The reason must survive the stop, not merely be written before it.

        `_stop()` goes through `ServiceManager`, which holds no health-checker
        reference, so it cannot drop the liveness record -- which is the only
        reason a consumer can still read why the service was stopped. That is an
        absence, so it needs a test: making `_stop()` symmetric with the API stop
        route would erase the reason and Pearl would see a plain user stop.
        """
        clock = self._always_unhealthy_at(health_checker, [0.0, 0.0])

        with (
            patch.object(HealthChecker, "FAILFAST_NUM", 2),
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            clock,
        ):
            with pytest.raises(RuntimeError, match="stopped by failfast"):
                await health_checker.healthcheck_job("test-service")

        liveness = health_checker.get_liveness("test-service")
        assert liveness["is_alive"] is False
        assert liveness["reason"] == "stopped_by_failfast"


class TestRestartStakingReconciliation:
    """Tests for the staking reconciliation _restart performs before redeploying.

    An evicted agent exits on every boot, so a restart that does not clear the
    eviction restarts a process that is structurally incapable of staying up.
    """

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Return a HealthChecker whose service manager is fully mocked."""
        mock_sm = MagicMock()
        mock_sm.load.return_value.path = Path("/fake/service")
        mock_sm.reconcile_staking_for_restart.return_value = (
            StakingReconcileOutcome.NOTHING_TO_DO
        )
        return HealthChecker(
            service_manager=mock_sm,
            logger=MagicMock(),
            sleep_period=0,
            number_of_fails=1,
        )

    @staticmethod
    async def _run_until_restart(
        health_checker: HealthChecker,
    ) -> t.Optional[BaseException]:
        """Drive healthcheck_job through one unhealthy cycle and its restart.

        :return: the exception the job ended on, or None if it was still running.
        """

        async def always_unhealthy(*_args: object, **_kwargs: object) -> bool:
            return False

        health_checker.check_service_health = always_unhealthy  # type: ignore[assignment]

        with (
            patch("operate.services.health_checker.asyncio.wait_for", _no_timeout),
            patch("operate.services.health_checker.asyncio.sleep", _instant_sleep),
            patch("operate.services.health_checker.time.time", return_value=0.0),
        ):
            task = asyncio.create_task(health_checker.healthcheck_job("test-service"))
            await _REAL_SLEEP(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                return None
            except Exception as exc:  # pylint: disable=broad-except
                return exc
            return None

    @pytest.mark.asyncio
    async def test_reconciliation_runs_between_stop_and_deploy(
        self, health_checker: HealthChecker
    ) -> None:
        """The ordering is the defect: reconciling after the redeploy fixes nothing."""
        calls: t.List[str] = []
        sm = health_checker._service_manager
        sm.stop_service_locally.side_effect = lambda **_: calls.append("stop")

        def _reconcile(**_kwargs: object) -> StakingReconcileOutcome:
            calls.append("reconcile")
            return StakingReconcileOutcome.NOTHING_TO_DO

        sm.reconcile_staking_for_restart.side_effect = _reconcile
        sm.deploy_service_locally.side_effect = lambda **_: calls.append("deploy")

        await self._run_until_restart(health_checker)

        assert calls[:3] == ["stop", "reconcile", "deploy"]

    @pytest.mark.asyncio
    async def test_reconciled_eviction_redeploys_and_clears_failfast(
        self, health_checker: HealthChecker
    ) -> None:
        """A cleared eviction makes the restarts it caused stop counting.

        The budget is reset against a condition the chain has confirmed is
        gone — `reconcile_staking_for_restart` re-reads before reporting
        RECONCILED — and it resumes counting on the next restart, which is what
        keeps the loop bounded.
        """
        sm = health_checker._service_manager
        outcomes = [StakingReconcileOutcome.RECONCILED] * 3

        def _reconcile(**_kwargs: object) -> StakingReconcileOutcome:
            if outcomes:
                return outcomes.pop()
            return StakingReconcileOutcome.NOTHING_TO_DO

        sm.reconcile_staking_for_restart.side_effect = _reconcile

        with patch.object(HealthChecker, "FAILFAST_NUM", 2):
            exc = await self._run_until_restart(health_checker)

        sm.deploy_service_locally.assert_called_with(service_config_id="test-service")
        # Three reconciled restarts cleared the budget, so the service outlived
        # FAILFAST_NUM restarts instead of being stopped at the second...
        assert sm.deploy_service_locally.call_count > 2
        # ...and once reconciliation stopped clearing evictions, failfast fired.
        assert isinstance(exc, RuntimeError)

    @pytest.mark.asyncio
    async def test_skipped_reconciliation_waits_instead_of_redeploying(
        self, health_checker: HealthChecker
    ) -> None:
        """Another caller is mid-reconciliation, and will deploy the service itself.

        Booting an agent now would boot it into a service that may still be
        evicted, and the restart is not this service's fault, so it must not
        spend failfast budget either.
        """
        sm = health_checker._service_manager
        sm.reconcile_staking_for_restart.return_value = StakingReconcileOutcome.SKIPPED

        with patch.object(HealthChecker, "FAILFAST_NUM", 2):
            exc = await self._run_until_restart(health_checker)

        sm.deploy_service_locally.assert_not_called()
        assert exc is None

    @pytest.mark.asyncio
    async def test_skipped_reconciliation_does_not_count_as_a_restart(
        self, health_checker: HealthChecker
    ) -> None:
        """No restart was attempted, so the count the API reports must not move."""
        sm = health_checker._service_manager
        sm.reconcile_staking_for_restart.return_value = StakingReconcileOutcome.SKIPPED

        await self._run_until_restart(health_checker)

        assert (
            health_checker.get_liveness("test-service")["restarts_since_last_healthy"]
            == 0
        )

    @pytest.mark.asyncio
    async def test_locked_eviction_stops_the_service_with_a_reason(
        self, health_checker: HealthChecker
    ) -> None:
        """Restarting into an eviction that cannot be cleared only repeats it."""
        health_checker._service_manager.reconcile_staking_for_restart.return_value = (
            StakingReconcileOutcome.EVICTED_CANNOT_RESTAKE
        )

        await self._run_until_restart(health_checker)

        health_checker._service_manager.stop_service_locally.assert_called_with(
            service_config_id="test-service"
        )
        health_checker._service_manager.deploy_service_locally.assert_not_called()
        liveness = health_checker.get_liveness("test-service")
        assert liveness["is_alive"] is False
        assert liveness["reason"] == "evicted_cannot_restake"

    @pytest.mark.asyncio
    async def test_failing_reconciliation_falls_through_to_a_plain_restart(
        self, health_checker: HealthChecker
    ) -> None:
        """A chain read must never wedge the component that recovers everything else."""
        health_checker._service_manager.reconcile_staking_for_restart.side_effect = (
            RuntimeError("rpc down")
        )

        await self._run_until_restart(health_checker)

        health_checker._service_manager.deploy_service_locally.assert_called_with(
            service_config_id="test-service"
        )
        health_checker.logger.exception.assert_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_restart_counts_towards_liveness(
        self, health_checker: HealthChecker
    ) -> None:
        """Restarts since the last healthy probe are reported to API consumers."""
        await self._run_until_restart(health_checker)

        assert (
            health_checker.get_liveness("test-service")["restarts_since_last_healthy"]
            > 0
        )
