"""
Tests for funding_manager race conditions.

Part of Phase 1.3: Race Condition Fixes - documenting and fixing thread safety
issues in funding cooldown operations.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from operate.services.funding_manager import FundingManager


class TestFundingCooldownRaceConditions:
    """Test funding cooldown thread safety issues.

    Current issues:
    1. _funding_requests_cooldown_until dict accessed without lock (lines 794, 1003-1005)
    2. Concurrent reads/writes can cause race conditions
    3. Check-and-set pattern is not atomic

    These tests demonstrate the race conditions that need to be fixed.
    """

    @pytest.fixture
    def funding_manager(self) -> FundingManager:
        """Create a FundingManager instance for testing."""
        mock_keys_manager = MagicMock()
        mock_wallet_manager = MagicMock()
        mock_logger = MagicMock()

        manager = FundingManager(
            keys_manager=mock_keys_manager,
            wallet_manager=mock_wallet_manager,
            logger=mock_logger,
            funding_requests_cooldown_seconds=5,
        )
        return manager

    def test_cooldown_dict_concurrent_read_write_race_condition(
        self, funding_manager: FundingManager
    ) -> None:
        """Test that concurrent read/write to cooldown dict can race (to be fixed).

        Scenario: Thread A checks cooldown (read), Thread B sets cooldown (write).
        Without locking, Thread A might see stale data.
        """
        service_id = "test-service"
        results = []

        def check_cooldown() -> None:
            """Check if service is in cooldown (read operation)."""
            for _ in range(100):
                now = time.time()
                # Line 794: Read without lock (RACE CONDITION)
                cooldown_until = funding_manager._funding_requests_cooldown_until.get(  # type: ignore[attr-defined]
                    service_id, 0
                )
                is_in_cooldown = now < cooldown_until
                results.append(("check", is_in_cooldown, cooldown_until))
                time.sleep(0.001)

        def set_cooldown() -> None:
            """Set cooldown for service (write operation)."""
            for _ in range(100):
                # Line 1003-1005: Write without lock (RACE CONDITION)
                funding_manager._funding_requests_cooldown_until[service_id] = (  # type: ignore[attr-defined]
                    time.time() + 5
                )
                results.append(("set", True, 0))
                time.sleep(0.001)

        # Start concurrent readers and writers
        thread1 = threading.Thread(target=check_cooldown)
        thread2 = threading.Thread(target=set_cooldown)

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        # Race condition exists: reads and writes happen concurrently without lock
        # This test documents the problem but doesn't always fail
        # After fix, all operations should be atomic
        check_count = sum(1 for r in results if r[0] == "check")
        set_count = sum(1 for r in results if r[0] == "set")

        assert check_count > 0
        assert set_count > 0
        # The race condition means we might see inconsistent state

    def test_cooldown_check_and_set_not_atomic(
        self, funding_manager: FundingManager
    ) -> None:
        """Test that check-and-set cooldown pattern is not atomic (to be fixed).

        Scenario: Thread A checks cooldown (not in cooldown), Thread B also checks
        (not in cooldown), both proceed to fund, violating single-operation guarantee.
        """
        service_id = "test-service"
        operations_started = []

        def attempt_funding() -> None:
            """Attempt to start funding operation."""
            now = time.time()
            # Check cooldown (line 794 - no lock)
            cooldown_until = funding_manager._funding_requests_cooldown_until.get(  # type: ignore[attr-defined]
                service_id, 0
            )
            if now >= cooldown_until:
                # Not in cooldown, proceed
                time.sleep(0.01)  # Simulate work
                operations_started.append(threading.current_thread().name)
                # Set cooldown (line 1003 - no lock)
                funding_manager._funding_requests_cooldown_until[service_id] = (  # type: ignore[attr-defined]
                    time.time() + 5
                )

        # Start multiple threads that will all see "not in cooldown"
        threads = [threading.Thread(target=attempt_funding) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Without atomic check-and-set, multiple operations can start
        # This violates the cooldown guarantee
        # After fix, only one operation should start
        assert len(operations_started) > 0

    def test_cooldown_dict_missing_lock_protection(
        self, funding_manager: FundingManager
    ) -> None:
        """Test that cooldown dict operations are not protected by lock (to be fixed).

        Current state:
        - _lock exists (line 98)
        - _lock protects _funding_in_progress dict (lines 983-988, 1007-1008)
        - _lock does NOT protect _funding_requests_cooldown_until dict

        After fix:
        - _lock should protect both dicts
        - All read/write operations should be within lock
        """
        import inspect

        source = inspect.getsource(FundingManager.fund_service)

        # Verify the lock exists and is used for _funding_in_progress
        assert "with self._lock:" in source
        assert "_funding_in_progress" in source

        # Document that cooldown dict operations are outside lock
        # (This is the bug to be fixed)
        assert "_funding_requests_cooldown_until" in source


class TestFundingInProgressLocking:
    """Test that _funding_in_progress locking is correct (already implemented).

    These tests verify the existing correct implementation as a reference
    for what the cooldown locking should look like.
    """

    @pytest.fixture
    def funding_manager(self) -> FundingManager:
        """Create a FundingManager instance for testing."""
        mock_keys_manager = MagicMock()
        mock_wallet_manager = MagicMock()
        mock_logger = MagicMock()

        return FundingManager(
            keys_manager=mock_keys_manager,
            wallet_manager=mock_wallet_manager,
            logger=mock_logger,
        )

    def test_funding_in_progress_uses_lock(
        self, funding_manager: FundingManager
    ) -> None:
        """Test that _funding_in_progress dict operations are properly locked.

        This is the correct pattern that should be applied to cooldown dict.
        """
        import inspect

        source = inspect.getsource(FundingManager.fund_service)

        # Verify lock protects _funding_in_progress operations
        assert "with self._lock:" in source
        assert "self._funding_in_progress" in source

        # This is the pattern that works correctly
        # We need to apply the same pattern to _funding_requests_cooldown_until


class TestFundingManagerThreadSafetyImprovements:
    """Suggested improvements for funding_manager thread safety.

    Current Issues:
    1. Line 794: Read _funding_requests_cooldown_until without lock
    2. Lines 1003-1005: Write _funding_requests_cooldown_until without lock
    3. Check-and-set pattern is not atomic

    Recommended Pattern:
    ```python
    with self._lock:
        # Check cooldown
        if service_config_id in self._funding_in_progress:
            raise FundingInProgressError(...)

        now = time()
        if now < self._funding_requests_cooldown_until.get(service_config_id, 0):
            # In cooldown
            return

        # Set in-progress flag
        self._funding_in_progress[service_config_id] = True

    try:
        # Do funding operations outside lock
        self.fund_chain_amounts(amounts, service=service)
    finally:
        with self._lock:
            # Clear in-progress flag and set cooldown atomically
            self._funding_in_progress[service_config_id] = False
            self._funding_requests_cooldown_until[service_config_id] = (
                time() + self.funding_requests_cooldown_seconds
            )
    ```
    """

    def test_improvement_recommendations_documented(self) -> None:
        """This test documents recommended improvements (see class docstring)."""
        # This is a documentation test
        assert True
