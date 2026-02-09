"""
Tests for deployment_runner error handling.

Part of Phase 1.2: Error Handling Improvements - documenting and fixing exception
handling in deployment operations.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.services.deployment_runner import DeploymentManager, States


class TestDeploymentManagerErrorHandling:
    """Test error handling in DeploymentManager."""

    @pytest.fixture
    def deployment_manager(self) -> DeploymentManager:
        """Create a DeploymentManager instance for testing."""
        manager = DeploymentManager()
        # Replace logger with mock for testing
        manager.logger = MagicMock()
        return manager

    def test_run_deployment_swallows_exception_on_start_failure(
        self, deployment_manager: DeploymentManager, tmp_path: Path
    ) -> None:
        """Test that run_deployment swallows exceptions (BUG to be fixed).

        Current behavior at line 814: When deployment.start() fails, the exception
        is caught, logged, state is set to ERROR, and stop_deployment is called,
        but the exception is NOT re-raised. This means the caller has no way to
        know that the deployment failed except by checking the state.

        This is a bug that should be fixed - the exception should be re-raised
        after cleanup so callers can handle the failure appropriately.
        """
        build_dir = tmp_path / "test-deployment"
        build_dir.mkdir()

        # Mock the deployment runner to raise an error on start
        with patch.object(
            deployment_manager, "_get_deployment_runner"
        ) as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.start.side_effect = RuntimeError("Docker daemon not running")
            mock_get_runner.return_value = mock_runner

            # Currently, run_deployment does NOT raise the exception
            # After the fix, this should raise RuntimeError
            deployment_manager.run_deployment(
                build_dir=build_dir, password="test", is_aea=True
            )

            # Verify state: Line 818 sets to ERROR but line 819 calls stop_deployment
            # which successfully stops and sets state to STOPPED (line 844)
            # So final state is STOPPED, not ERROR - this demonstrates the issue
            assert deployment_manager.get_state(build_dir) == States.STOPPED

            # Verify logger.exception was called
            deployment_manager.logger.exception.assert_called()

            # The exception was caught and NOT re-raised (this is the bug)
            # Caller has no way to know deployment failed except checking logs/state

    def test_stop_deployment_reraises_exception_after_logging(
        self, deployment_manager: DeploymentManager, tmp_path: Path
    ) -> None:
        """Test that stop_deployment re-raises exceptions (correct behavior).

        The exception handler at line 845 correctly logs the error, sets state
        to ERROR, and re-raises the exception so callers know the stop failed.
        """
        build_dir = tmp_path / "test-deployment"
        build_dir.mkdir()

        # Set initial state to STARTED so stop is allowed
        deployment_manager._states[build_dir] = States.STARTED

        # Mock the deployment runner to raise an error on stop
        with patch.object(
            deployment_manager, "_get_deployment_runner"
        ) as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.stop.side_effect = RuntimeError("Process not found")
            mock_get_runner.return_value = mock_runner

            # Should raise the exception after logging
            with pytest.raises(RuntimeError, match="Process not found"):
                deployment_manager.stop_deployment(build_dir=build_dir, is_aea=True)

            # Verify state was set to ERROR
            assert deployment_manager.get_state(build_dir) == States.ERROR

            # Verify logger.exception was called
            deployment_manager.logger.exception.assert_called()


class TestDeploymentRunnerRetryLogic:
    """Document acceptable retry logic patterns in deployment_runner.

    The deployment runner has several exception handlers that implement retry logic:

    1. Line 280 (_setup_agent): Retries agent setup with backoff, re-raises after max attempts
    2. Line 298 (start): Retries deployment start, raises RuntimeError after max attempts
    3. Line 781 (_check_ipfs_connection): Retries IPFS connection, raises RuntimeError after failures

    These are acceptable broad exception handling patterns because:
    - They implement retry logic with proper backoff
    - They re-raise or raise new exception after exhausting retries
    - They log each attempt for debugging
    """

    def test_setup_agent_retry_logic_reraises_after_max_attempts(self) -> None:
        """Document that _setup_agent retry logic (line 280) re-raises.

        The exception handler:
        - Catches any exception during agent setup
        - Logs the failure with attempt number
        - Retries with exponential backoff (attempt * 5 seconds)
        - Re-raises the original exception after max attempts

        This is acceptable broad exception handling for retry logic.
        """
        import inspect

        from operate.services.deployment_runner import BaseDeploymentRunner

        # Verify the pattern exists in the source
        source = inspect.getsource(BaseDeploymentRunner._setup_agent)  # type: ignore[attr-defined]

        assert "except Exception" in source
        assert "raise" in source
        assert "max_attempts" in source

    def test_start_retry_logic_raises_runtime_error_after_failures(self) -> None:
        """Document that start retry logic (line 298) raises after failures.

        The exception handler:
        - Catches any exception during start
        - Logs with full traceback
        - Retries START_TRIES times
        - Raises RuntimeError with descriptive message after all retries fail

        This is acceptable broad exception handling for retry logic.
        """
        import inspect

        from operate.services.deployment_runner import BaseDeploymentRunner

        source = inspect.getsource(BaseDeploymentRunner.start)

        assert "except Exception" in source
        assert "raise RuntimeError" in source
        assert "START_TRIES" in source

    def test_ipfs_connection_retry_logic_raises_after_max_retries(self) -> None:
        """Document that IPFS retry logic (line 781) raises after failures.

        The exception handler:
        - Catches OSError separately and re-raises immediately (critical error)
        - Catches other exceptions and retries with backoff
        - Raises RuntimeError after exhausting all retry attempts

        This is acceptable broad exception handling with proper exception type handling.
        """
        import inspect

        from operate.services.deployment_runner import DeploymentManager

        source = inspect.getsource(DeploymentManager.check_ipfs_connection_works)

        assert "except OSError:" in source
        assert "except Exception:" in source
        assert "raise RuntimeError" in source


class TestStopTendermintExceptionHandling:
    """Document _stop_tendermint exception handling behavior.

    The _stop_tendermint method (line 337) has a broad exception handler that:
    - Catches ConnectionError specifically for expected "not listening" case
    - Catches all other exceptions and logs them
    - Does NOT re-raise, continues with PID cleanup

    This might be intentional - during shutdown, you want to continue cleanup
    even if some steps fail. However, it lacks specific exception handling
    and could mask important errors.
    """

    def test_stop_tendermint_continues_after_exception(self) -> None:
        """Document that _stop_tendermint swallows exceptions (line 337).

        The exception handler catches all exceptions during tendermint stop
        and logs them but does NOT re-raise. This allows cleanup to continue.

        This might be intentional for graceful shutdown, but could mask issues.
        After fix, we might want to distinguish between expected failures
        (ConnectionError) and unexpected errors (which should be logged differently).
        """
        import inspect

        from operate.services.deployment_runner import BaseDeploymentRunner

        source = inspect.getsource(BaseDeploymentRunner._stop_tendermint)

        # Verify the pattern exists
        assert "except requests.ConnectionError:" in source
        assert "except Exception:" in source
        # Note: Does NOT re-raise after the broad except
        # This allows cleanup to continue but might mask errors
