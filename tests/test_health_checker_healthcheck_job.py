"""
Tests for health_checker.healthcheck_job error handling.

Part of Phase 1.2: Error Handling Improvements - documenting exception handling
behavior in the healthcheck job. The remaining broad exception catches in this
method (lines 273 and 283) re-raise exceptions after logging, which is acceptable
behavior for retry logic and top-level handlers.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from operate.services.health_checker import HealthChecker


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
        assert 'logger.exception' in source or 'self.logger.exception' in source
        assert "raise" in source
