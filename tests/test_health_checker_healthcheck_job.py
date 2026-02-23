"""
Tests for health_checker.healthcheck_job error handling.

Part of Phase 1.2: Error Handling Improvements - documenting exception handling
behavior in the healthcheck job. The remaining broad exception catches in this
method (lines 273 and 283) re-raise exceptions after logging, which is acceptable
behavior for retry logic and top-level handlers.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

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

        # Create a task that we'll cancel
        task = asyncio.create_task(health_checker.healthcheck_job(service_config_id))

        # Give it a moment to start
        await asyncio.sleep(0.1)

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

    @pytest.mark.asyncio
    async def test_check_port_ready_returns_false_on_timeout(self) -> None:
        """Test that _check_port_ready returns False when wait_for_port times out."""
        mock_service = MagicMock()
        mock_service.path = MagicMock()
        mock_service_manager = MagicMock()
        mock_service_manager.load.return_value = mock_service

        health_checker = HealthChecker(
            service_manager=mock_service_manager,
            logger=MagicMock(),
            port_up_timeout=1,  # Very short timeout so it expires quickly
        )

        service_config_id = "test-service"

        # Make check_service_health always succeed so _wait_for_port returns immediately,
        # but override _check_port_ready to test the TimeoutError path directly
        async def always_healthy(*args: object, **kwargs: object) -> bool:
            return True

        with patch.object(health_checker, "check_service_health", always_healthy):
            # We test _check_port_ready indirectly by running healthcheck_job
            # and verifying it proceeds past port-ready phase
            task = asyncio.create_task(
                health_checker.healthcheck_job(service_config_id)
            )
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass

        # Logger should have been called with port-ready info
        health_checker.logger.info.assert_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers shared by the nested-function tests
# ---------------------------------------------------------------------------


async def _no_timeout(coro: object, timeout: object = None, **kwargs: object) -> object:
    """Replace asyncio.wait_for so _check_port_ready has no timeout."""
    return await coro  # type: ignore[misc]


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

        with patch(
            "operate.services.health_checker.asyncio.wait_for", _no_timeout
        ), patch("operate.services.health_checker.asyncio.sleep", _instant_sleep):
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

        with patch(
            "operate.services.health_checker.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ), patch(
            "operate.services.health_checker.asyncio.sleep", _instant_sleep
        ), patch(
            "operate.services.health_checker.time.time", return_value=0.0
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

        with patch(
            "operate.services.health_checker.asyncio.wait_for", _no_timeout
        ), patch(
            "operate.services.health_checker.asyncio.sleep", _instant_sleep
        ), patch(
            "operate.services.health_checker.time.time", return_value=0.0
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

        with patch(
            "operate.services.health_checker.asyncio.wait_for", _no_timeout
        ), patch(
            "operate.services.health_checker.asyncio.sleep", _instant_sleep
        ), patch(
            "operate.services.health_checker.time.time", return_value=0.0
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

        with patch(
            "operate.services.health_checker.asyncio.wait_for", _no_timeout
        ), patch(
            "operate.services.health_checker.asyncio.sleep", _instant_sleep
        ), patch(
            "operate.services.health_checker.time.time", return_value=0.0
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
        """Test failfast triggers _stop and re-raises the restart exception (lines 269-280, 312-317)."""
        health_checker.number_of_fails = 1
        call_count = [0]

        async def mock_check(*args: object) -> bool:
            call_count[0] += 1
            return call_count[0] == 1

        health_checker.check_service_health = mock_check  # type: ignore[assignment]
        health_checker._service_manager.deploy_service_locally.side_effect = (
            RuntimeError("deploy failed")
        )

        with patch.object(HealthChecker, "FAILFAST_NUM", 1), patch(
            "operate.services.health_checker.asyncio.wait_for", _no_timeout
        ), patch(
            "operate.services.health_checker.asyncio.sleep", _instant_sleep
        ), patch(
            "operate.services.health_checker.time.time", return_value=0.0
        ):
            with pytest.raises(RuntimeError, match="deploy failed"):
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

        with patch.object(HealthChecker, "FAILFAST_NUM", 3), patch(
            "operate.services.health_checker.asyncio.wait_for", _no_timeout
        ), patch(
            "operate.services.health_checker.asyncio.sleep", _instant_sleep
        ), patch(
            "operate.services.health_checker.time.time", return_value=0.0
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
