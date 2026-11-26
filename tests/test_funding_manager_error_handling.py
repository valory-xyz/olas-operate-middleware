"""
Tests for funding_manager error handling.

Part of Phase 1.2: Error Handling Improvements - documenting exception handling
in the funding job background task.
"""

from unittest.mock import MagicMock

import pytest

from operate.services.funding_manager import FundingManager


class TestFundingJobExceptionHandlingBehavior:
    """Each funding-job task logs its own error and lets the job go on.

    The handler runs in the worker thread (`FundingManager._run_logging_errors`),
    so the error is logged even after a re-login cancelled the job awaiting it.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "Error occurred while claiming rewards",
            "Error occurred while funding Master EOA",
        ],
    )
    def test_a_task_error_is_logged_not_raised(self, message: str) -> None:
        """The error is logged with the task's message and exc_info, and swallowed."""
        logger = MagicMock()
        manager = FundingManager(
            keys_manager=MagicMock(), wallet_manager=MagicMock(), logger=logger
        )

        manager._run_logging_errors(  # pylint: disable=protected-access
            MagicMock(side_effect=RuntimeError("rpc down")), message
        )

        logger.exception.assert_called_once_with(message)

    def test_funding_manager_can_be_instantiated(self) -> None:
        """Verify FundingManager can be created for testing."""
        mock_keys_manager = MagicMock()
        mock_wallet_manager = MagicMock()
        mock_logger = MagicMock()

        manager = FundingManager(
            keys_manager=mock_keys_manager,
            wallet_manager=mock_wallet_manager,
            logger=mock_logger,
        )

        # Verify instance created
        assert manager is not None
        assert manager.logger == mock_logger


class TestFundingManagerErrorHandlingImprovements:
    """Suggested improvements for funding_manager error handling.

    Current Issues:
    1. No specific exception handling
       - Catches all exceptions equally
       - Should distinguish between:
         * Network errors (retryable with backoff)
         * Permission errors (alert, may need manual intervention)
         * Insufficient funds (alert, but expected in some cases)
         * RPC errors (retryable, maybe switch RPC)

    2. No failure tracking
       - No metrics on repeated failures
       - Could mask persistent issues
       - Should alert if same error occurs repeatedly

    Recommended Pattern:
    ```python
    try:
        await loop.run_in_executor(
            executor,
            service_manager.claim_all_on_chain_from_safe,
        )
    except (NetworkError, RPCError) as e:
        self.logger.warning(
            f"Transient error during reward claiming: {e}",
            exc_info=True
        )
        # Could implement exponential backoff here
    except PermissionError as e:
        self.logger.error(
            f"Permission error during reward claiming: {e}",
            exc_info=True
        )
        # Alert - needs manual intervention
    except Exception as e:
        self.logger.error(
            f"Unexpected error during reward claiming: {e}",
            exc_info=True
        )
        # Alert - unknown error type
    finally:
        last_claim = time()
    ```
    """

    def test_improvement_recommendations_documented(self) -> None:
        """This test documents recommended improvements (see class docstring)."""
        # This is a documentation test
        assert True
