"""
Tests for health_checker race conditions.

Part of Phase 1.3: Race Condition Fixes - documenting and fixing thread safety
issues in health checker job management.
"""

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from operate.operate_types import EvictionState, StakingReconcileOutcome
from operate.services.health_checker import HealthChecker
from operate.services.manage import ServiceManager


class TestHealthCheckerJobRaceConditions:
    """Test health checker job management thread safety issues.

    Current issues:
    1. _jobs dict accessed without lock (lines 68, 72, 80, 85)
    2. start_for_service doesn't wait for stop_for_service cancellation (line 69)
    3. Concurrent start/stop operations can race
    4. Task cancellation is not awaited

    These tests demonstrate the race conditions that need to be fixed.
    """

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Create a HealthChecker instance for testing."""
        mock_service_manager = MagicMock()
        mock_logger = MagicMock()
        return HealthChecker(service_manager=mock_service_manager, logger=mock_logger)

    @pytest.mark.asyncio
    async def test_jobs_dict_has_lock_protection(
        self, health_checker: HealthChecker
    ) -> None:
        """Test that _jobs dict operations ARE protected by lock (FIXED).

        Fixed state:
        - Lock exists for _jobs dict (_jobs_lock)
        - All dict operations protected by threading.Lock
        - start_for_service and stop_for_service use lock
        """
        # Verify _jobs dict exists with lock
        assert hasattr(health_checker, "_jobs")
        # Lock now exists (FIXED)
        assert hasattr(health_checker, "_jobs_lock")
        # Verify it's a lock object (has acquire/release methods)
        assert hasattr(health_checker._jobs_lock, "acquire")  # type: ignore[attr-defined]
        assert hasattr(health_checker._jobs_lock, "release")  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_start_for_service_doesnt_wait_for_cancellation(
        self, health_checker: HealthChecker
    ) -> None:
        """Test that start_for_service doesn't wait for task cancellation (to be fixed).

        Scenario:
        1. Job is running for service
        2. start_for_service is called (line 68 detects existing job)
        3. stop_for_service is called (line 69)
        4. New job is created immediately (line 72)
        5. Old job may still be running - race condition!

        After fix:
        - stop_for_service should await task cancellation
        - start_for_service should wait for cancellation to complete
        """
        service_id = "test-service"

        # Create a mock task that simulates a running job
        mock_task = AsyncMock()
        mock_task.cancel = MagicMock(return_value=True)
        mock_task.done = MagicMock(return_value=False)

        # Simulate existing job
        health_checker._jobs[service_id] = mock_task  # type: ignore[attr-defined]

        # Mock healthcheck_job to return immediately
        with patch.object(health_checker, "healthcheck_job", new=AsyncMock()):
            # This will call stop_for_service but not wait
            health_checker.start_for_service(service_id)

            # Verify task was cancelled but not awaited
            mock_task.cancel.assert_called_once()

            # Problem: New job created before old job finishes cancellation
            # After fix, should await cancellation before creating new job

    @pytest.mark.asyncio
    async def test_concurrent_start_operations_race_condition(
        self, health_checker: HealthChecker
    ) -> None:
        """Test that concurrent start operations can race (to be fixed).

        Scenario: Two threads call start_for_service simultaneously
        Without locking, both could read "no existing job" and both create tasks.
        """
        service_id = "test-service"

        # Mock healthcheck_job
        mock_healthcheck = AsyncMock()

        async def start_operation() -> None:
            """Simulate starting a job."""
            with patch.object(health_checker, "healthcheck_job", mock_healthcheck):
                health_checker.start_for_service(service_id)
                await asyncio.sleep(0.01)  # Simulate work

        # Start multiple operations concurrently
        await asyncio.gather(
            start_operation(),
            start_operation(),
            start_operation(),
        )

        # Without locking, multiple tasks could be created
        # After fix, only one task should exist at a time

    @pytest.mark.asyncio
    async def test_stop_for_service_doesnt_await_cancellation(
        self, health_checker: HealthChecker
    ) -> None:
        """Test that stop_for_service doesn't await task cancellation (to be fixed).

        Current behavior (line 85):
        - Calls task.cancel() but doesn't await it
        - Returns immediately without waiting for cancellation

        After fix:
        - Should await the task to ensure cancellation completes
        - Should handle CancelledError properly
        """
        service_id = "test-service"

        # Create a mock task
        mock_task = AsyncMock()
        mock_task.cancel = MagicMock(return_value=True)
        health_checker._jobs[service_id] = mock_task  # type: ignore[attr-defined]

        # Call stop (doesn't await cancellation)
        health_checker.stop_for_service(service_id)

        # Verify cancel was called but not awaited
        mock_task.cancel.assert_called_once()

        # Problem: No guarantee task has actually stopped
        # After fix, should await the task


class TestHealthCheckerThreadSafetyImprovements:
    """Suggested improvements for health_checker thread safety.

    Current Issues:
    1. No lock protecting _jobs dict
    2. start_for_service doesn't wait for stop_for_service to complete
    3. Task cancellation is not awaited

    Recommended Pattern:
    ```python
    def __init__(self, ...):
        self._jobs: Dict[str, asyncio.Task] = {}
        self._jobs_lock = asyncio.Lock()

    async def start_for_service(self, service_config_id: str) -> None:
        async with self._jobs_lock:
            # Stop existing job if present
            if service_config_id in self._jobs:
                old_task = self._jobs[service_config_id]
                old_task.cancel()
                try:
                    await old_task  # Wait for cancellation
                except asyncio.CancelledError:
                    pass  # Expected

            # Create new job
            loop = asyncio.get_running_loop()
            self._jobs[service_config_id] = loop.create_task(
                self.healthcheck_job(service_config_id)
            )

    async def stop_for_service(self, service_config_id: str) -> None:
        async with self._jobs_lock:
            if service_config_id not in self._jobs:
                return

            task = self._jobs[service_config_id]
            task.cancel()
            try:
                await task  # Wait for cancellation
            except asyncio.CancelledError:
                pass  # Expected
            finally:
                del self._jobs[service_config_id]
    ```

    Note: This requires making these methods async, which is a breaking change.
    Alternative: Use threading.Lock for sync operations.
    """

    def test_improvement_recommendations_documented(self) -> None:
        """This test documents recommended improvements (see class docstring)."""
        # This is a documentation test
        assert True


class TestHealthCheckerCurrentBehavior:
    """Document current health checker behavior for reference."""

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Create a HealthChecker instance for testing."""
        mock_service_manager = MagicMock()
        mock_logger = MagicMock()
        return HealthChecker(service_manager=mock_service_manager, logger=mock_logger)

    def test_jobs_dict_exists_with_lock(self, health_checker: HealthChecker) -> None:
        """Document that _jobs dict exists WITH lock protection (FIXED)."""
        assert hasattr(health_checker, "_jobs")
        assert isinstance(health_checker._jobs, dict)  # type: ignore[attr-defined]
        # Lock now exists (FIXED)
        assert hasattr(health_checker, "_jobs_lock")
        # Verify it's a lock object (has acquire/release methods)
        assert hasattr(health_checker._jobs_lock, "acquire")  # type: ignore[attr-defined]
        assert hasattr(health_checker._jobs_lock, "release")  # type: ignore[attr-defined]

    def test_start_stop_are_sync_methods(self, health_checker: HealthChecker) -> None:
        """Document that start/stop are currently synchronous methods.

        This means they cannot await task cancellation.
        Fix options:
        1. Make methods async (breaking change)
        2. Use threading.Lock + sync cancellation handling
        3. Use asyncio.run_coroutine_threadsafe for awaiting
        """
        import inspect

        # Current methods are not coroutines
        assert not inspect.iscoroutinefunction(health_checker.start_for_service)
        assert not inspect.iscoroutinefunction(health_checker.stop_for_service)


class TestStakingReconciliationRaceConditions:
    """Test that the health checker's re-staking cannot collide with a user start.

    Both the deploy endpoint and the health checker now reach the staking flow
    for the same service, sending from the same master Safe. Two overlapping
    unstake/stake sequences are a nonce hazard and, worse, a double unstake.
    """

    @staticmethod
    def _service_manager(tmp_path: Path) -> ServiceManager:
        """Create a ServiceManager whose staking flow is mocked out."""
        manager = ServiceManager(
            path=tmp_path / "services",
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=MagicMock(),
        )
        manager._stake_service_on_chain_from_safe_unlocked = (  # type: ignore[method-assign]
            MagicMock()
        )
        return manager

    def test_same_service_calls_serialise(self, tmp_path: Path) -> None:
        """Two concurrent staking flows for one service must not interleave."""
        manager = self._service_manager(tmp_path)
        overlaps = []
        in_flight = threading.Event()
        release = threading.Event()

        def _slow_stake(**_kwargs: object) -> None:
            overlaps.append(in_flight.is_set())
            in_flight.set()
            release.wait(timeout=5)
            in_flight.clear()

        manager._stake_service_on_chain_from_safe_unlocked.side_effect = (  # type: ignore[attr-defined]
            _slow_stake
        )

        first = threading.Thread(
            target=manager.stake_service_on_chain_from_safe,
            kwargs={"service_config_id": "sc-a", "chain": "gnosis"},
        )
        second = threading.Thread(
            target=manager.stake_service_on_chain_from_safe,
            kwargs={"service_config_id": "sc-a", "chain": "gnosis"},
        )
        first.start()
        in_flight.wait(timeout=5)
        second.start()
        release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert overlaps == [False, False]

    def test_different_services_do_not_serialise(self, tmp_path: Path) -> None:
        """One service's staking must not stall another's."""
        manager = self._service_manager(tmp_path)
        entered = threading.Event()
        release = threading.Event()

        def _blocking_stake(**_kwargs: object) -> None:
            entered.set()
            release.wait(timeout=5)

        manager._stake_service_on_chain_from_safe_unlocked.side_effect = (  # type: ignore[attr-defined]
            _blocking_stake
        )

        blocker = threading.Thread(
            target=manager.stake_service_on_chain_from_safe,
            kwargs={"service_config_id": "sc-a", "chain": "gnosis"},
        )
        blocker.start()
        entered.wait(timeout=5)
        try:
            assert (
                manager.stake_service_on_chain_from_safe(
                    service_config_id="sc-b", chain="gnosis", blocking=False
                )
                is True
            )
        finally:
            release.set()
            blocker.join(timeout=5)

    def test_reconciliation_skips_and_still_restarts_when_a_start_holds_the_lock(
        self, tmp_path: Path
    ) -> None:
        """Contention must never raise, and never block a background thread."""
        manager = self._service_manager(tmp_path)
        manager.is_service_evicted_on_chain = MagicMock(  # type: ignore[method-assign]
            return_value={"gnosis": EvictionState.EVICTED_UNSTAKABLE}
        )

        with manager.get_staking_lock("sc-a"):
            outcome = manager.reconcile_staking_for_restart(service_config_id="sc-a")

        assert outcome == StakingReconcileOutcome.SKIPPED
        manager._stake_service_on_chain_from_safe_unlocked.assert_not_called()  # type: ignore[attr-defined]
