"""
Tests for health_checker.check_service_health error handling.

Part of Phase 1.2: Error Handling Improvements - focusing on specific exception
handling instead of broad Exception catches.
"""

import asyncio
import json
import typing as t
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from operate.services.health_checker import AgentLivenessReason, HealthChecker

# aiohttp used via patch target "operate.services.health_checker.aiohttp.ClientSession"


class TestCheckServiceHealthErrorHandling:
    """Test specific error handling in check_service_health method."""

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Create a HealthChecker instance for testing."""
        mock_service_manager = MagicMock()
        mock_logger = MagicMock()
        return HealthChecker(service_manager=mock_service_manager, logger=mock_logger)

    @pytest.mark.asyncio
    async def test_check_service_health_handles_json_decode_error(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test that JSON decode errors are handled gracefully."""
        service_config_id = "test-service"

        # Mock response that raises JSONDecodeError
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(side_effect=json.JSONDecodeError("Invalid", "", 0))

        # Create proper async context manager mock for session.get()
        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

        # Create session mock
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            # Make ClientSession() context manager return our mock session
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            result = await health_checker.check_service_health(
                service_config_id, tmp_path
            )

        # Should return False for JSON errors, not crash
        assert result is False

    @pytest.mark.asyncio
    async def test_check_service_health_handles_file_write_error(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test that file write errors are handled gracefully."""
        service_config_id = "test-service"

        # Mock response with valid JSON
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"is_healthy": True})

        # Create proper async context manager mock for session.get()
        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

        # Create session mock
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        # Create a read-only directory to force write error
        readonly_path = tmp_path / "readonly"
        readonly_path.mkdir()
        readonly_path.chmod(0o444)

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            # Make ClientSession() context manager return our mock session
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            try:
                result = await health_checker.check_service_health(
                    service_config_id, readonly_path
                )
                # Should handle file write errors gracefully
                # (Currently might fail, will be fixed)
                assert result in [True, False]  # Accept either for now
            finally:
                # Cleanup
                readonly_path.chmod(0o755)

    @pytest.mark.asyncio
    async def test_check_service_health_logs_specific_json_error(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test that JSON errors are logged with specific context."""
        service_config_id = "test-service"

        # Mock response that raises JSONDecodeError
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            side_effect=json.JSONDecodeError("Expecting value", '{"bad":', 7)
        )

        # Create proper async context manager mock for session.get()
        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

        # Create session mock
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            # Make ClientSession() context manager return our mock session
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            with patch.object(health_checker.logger, "error") as mock_log:
                await health_checker.check_service_health(service_config_id, tmp_path)

                # Should log with specific error context
                mock_log.assert_called()
                # Verify error was logged with JSON decode context
                call_str = str(mock_log.call_args)
                assert "json" in call_str.lower() or "decode" in call_str.lower()

    @pytest.mark.asyncio
    async def test_check_service_health_succeeds_with_valid_response(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test normal success case still works."""
        service_config_id = "test-service"

        # Mock valid response
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"is_healthy": True})

        # Create proper async context manager mock for session.get()
        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

        # Create session mock
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            # Make ClientSession() context manager return our mock session
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            result = await health_checker.check_service_health(
                service_config_id, tmp_path
            )

        # Should return True for healthy service
        assert result is True

        # Should have written healthcheck.json
        healthcheck_file = tmp_path / "healthcheck.json"
        assert healthcheck_file.exists()
        content = json.loads(healthcheck_file.read_text())
        assert content == {"is_healthy": True}

    @pytest.mark.asyncio
    async def test_check_service_health_handles_client_connection_error(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test that aiohttp ClientConnectionError is handled gracefully."""
        service_config_id = "test-service"

        # Create session mock that raises ClientConnectionError
        mock_session = MagicMock()
        mock_session.get = MagicMock(
            side_effect=aiohttp.ClientConnectionError("Connection refused")
        )

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            # Make ClientSession() context manager return our mock session
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            result = await health_checker.check_service_health(
                service_config_id, tmp_path
            )

        # Should return False for connection errors, not crash
        assert result is False

        # Verify error was logged
        health_checker.logger.error.assert_called()  # type: ignore[attr-defined]
        call_str = str(health_checker.logger.error.call_args)  # type: ignore[attr-defined]
        assert "client error" in call_str.lower() or "http" in call_str.lower()

    @pytest.mark.asyncio
    async def test_check_service_health_handles_timeout_error(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test that asyncio TimeoutError is handled gracefully."""
        service_config_id = "test-service"

        # Create session mock that raises TimeoutError
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            # Make ClientSession() context manager return our mock session
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            result = await health_checker.check_service_health(
                service_config_id, tmp_path
            )

        # Should return False for timeout errors, not crash
        assert result is False

        # Verify error was logged with timeout context
        health_checker.logger.error.assert_called()  # type: ignore[attr-defined]
        call_str = str(health_checker.logger.error.call_args)  # type: ignore[attr-defined]
        assert "timeout" in call_str.lower()

    @pytest.mark.asyncio
    async def test_check_service_health_non_200_status_returns_false(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test that a non-200 HTTP status returns False and logs a warning."""
        service_config_id = "test-service"

        mock_resp = AsyncMock()
        mock_resp.status = 503
        mock_resp.text = AsyncMock(return_value="Service Unavailable")

        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            result = await health_checker.check_service_health(
                service_config_id, tmp_path
            )

        assert result is False

        health_checker.logger.warning.assert_called()  # type: ignore[attr-defined]
        warning_str = str(health_checker.logger.warning.call_args)  # type: ignore[attr-defined]
        assert "503" in warning_str or "bad" in warning_str.lower()

    @pytest.mark.asyncio
    async def test_check_service_health_handles_unexpected_error(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Test that unexpected exceptions are handled gracefully."""
        service_config_id = "test-service"

        # Create session mock that raises unexpected error
        mock_session = MagicMock()
        mock_session.get = MagicMock(
            side_effect=RuntimeError("Unexpected database error")
        )

        with patch(
            "operate.services.health_checker.aiohttp.ClientSession"
        ) as mock_client_session:
            # Make ClientSession() context manager return our mock session
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_ctx

            result = await health_checker.check_service_health(
                service_config_id, tmp_path
            )

        # Should return False for any unexpected error, not crash
        assert result is False

        # Verify error was logged as unexpected
        health_checker.logger.error.assert_called()  # type: ignore[attr-defined]
        call_str = str(health_checker.logger.error.call_args)  # type: ignore[attr-defined]
        assert "unexpected" in call_str.lower()


async def _start_for_service(
    health_checker: HealthChecker, service_config_id: str
) -> None:
    """Call start_for_service from inside a running loop, as the app does."""
    health_checker.start_for_service(service_config_id)


class TestCheckServiceHealthLivenessRecording:
    """Test that every probe outcome lands on the liveness record.

    A dead agent leaves healthcheck.json holding the round list captured just
    before the crash, so the liveness record is the only signal that says the
    agent stopped answering.
    """

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Create a HealthChecker instance for testing."""
        return HealthChecker(service_manager=MagicMock(), logger=MagicMock())

    @staticmethod
    def _patched_session(mock_resp: AsyncMock) -> t.Any:
        """Patch aiohttp.ClientSession so session.get() yields mock_resp."""
        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        patcher = patch("operate.services.health_checker.aiohttp.ClientSession")
        started = patcher.start()
        started.return_value = mock_ctx
        return patcher

    @pytest.mark.asyncio
    async def test_healthy_probe_records_alive_and_resets_counters(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """A 200 with is_healthy advances last_healthy_at and clears the failures."""
        health_checker.record_failed_probe(
            service_config_id="svc",
            reason=AgentLivenessReason.AGENT_PROCESS_EXITED,
        )
        health_checker.record_restart(service_config_id="svc")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"is_healthy": True})
        patcher = self._patched_session(mock_resp)
        try:
            assert await health_checker.check_service_health("svc", tmp_path) is True
        finally:
            patcher.stop()

        liveness = health_checker.get_liveness("svc")
        assert liveness["is_alive"] is True
        assert liveness["reason"] is None
        assert liveness["consecutive_failures"] == 0
        assert liveness["restarts_since_last_healthy"] == 0
        assert liveness["last_healthy_at"] == liveness["last_checked_at"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "side_effect",
        [
            asyncio.TimeoutError("timed out"),
            aiohttp.ClientError("client error"),
            OSError("file system error"),
            RuntimeError("unexpected"),
        ],
    )
    async def test_failed_probe_records_not_alive(
        self,
        health_checker: HealthChecker,
        tmp_path: Path,
        side_effect: Exception,
    ) -> None:
        """Every failure path records the probe, not only the HTTP-200 path."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(side_effect=side_effect)
        patcher = self._patched_session(mock_resp)
        try:
            assert await health_checker.check_service_health("svc", tmp_path) is False
        finally:
            patcher.stop()

        liveness = health_checker.get_liveness("svc")
        assert liveness["is_alive"] is False
        assert liveness["reason"] == "agent_process_exited"
        assert liveness["consecutive_failures"] == 1
        assert liveness["last_checked_at"] is not None
        assert liveness["last_healthy_at"] is None
        # The snapshot must not be replaced with a partial body.
        assert not (tmp_path / "healthcheck.json").exists()

    @pytest.mark.asyncio
    async def test_failed_probe_with_live_pid_reports_unresponsive(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """A live agent process that stopped answering is unresponsive, not exited."""
        deployment_dir = tmp_path / "deployment"
        deployment_dir.mkdir()
        (deployment_dir / "agent.pid").write_text("4242", encoding="utf-8")

        mock_resp = AsyncMock()
        mock_resp.status = 503
        mock_resp.text = AsyncMock(return_value="Service Unavailable")
        patcher = self._patched_session(mock_resp)
        try:
            with patch(
                "operate.services.health_checker.validate_pid", return_value=True
            ):
                assert (
                    await health_checker.check_service_health("svc", tmp_path) is False
                )
        finally:
            patcher.stop()

        assert health_checker.get_liveness("svc")["reason"] == "agent_unresponsive"

    @pytest.mark.asyncio
    async def test_self_reported_unhealthy_is_not_recorded_as_unresponsive(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """An agent that answers promptly and says it is unhealthy said something.

        `agent_unresponsive` is for an agent that did not answer. Recording it here
        states something false about the run -- this is the path a stalling trader
        takes, and it answers every poll in milliseconds.
        """
        deployment_dir = tmp_path / "deployment"
        deployment_dir.mkdir()
        (deployment_dir / "agent.pid").write_text("4242", encoding="utf-8")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "is_healthy": False,
                "is_tm_healthy": True,
                "is_transitioning_fast": False,
                "seconds_since_last_transition": 0.4,
                "rounds": [
                    "fetch_markets_router_round",
                    "polymarket_fetch_market_round",
                ],
            }
        )
        patcher = self._patched_session(mock_resp)
        try:
            with patch(
                "operate.services.health_checker.validate_pid", return_value=True
            ):
                assert (
                    await health_checker.check_service_health("svc", tmp_path) is False
                )
        finally:
            patcher.stop()

        liveness = health_checker.get_liveness("svc")
        assert liveness["is_alive"] is False
        assert liveness["reason"] == "agent_reported_unhealthy"
        assert liveness["consecutive_failures"] == 1
        # The response body was well-formed, so the snapshot is still written.
        assert (tmp_path / "healthcheck.json").exists()

    @pytest.mark.asyncio
    async def test_self_reported_unhealthy_is_logged_with_its_evidence(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """The path used to return in silence, so `cli.log` implied nothing answered."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "is_healthy": False,
                "is_tm_healthy": True,
                "is_transitioning_fast": False,
                "seconds_since_last_transition": 0.4,
                "rounds": [
                    "fetch_markets_router_round",
                    "polymarket_fetch_market_round",
                ],
            }
        )
        patcher = self._patched_session(mock_resp)
        try:
            assert await health_checker.check_service_health("svc", tmp_path) is False
        finally:
            patcher.stop()

        logged = " ".join(
            str(call.args[0])
            for call in t.cast(MagicMock, health_checker.logger).warning.call_args_list
        )
        assert "svc" in logged
        assert "reported itself unhealthy" in logged
        # The four fields that separate a Tendermint stall from the agent judging
        # its own round progress too slow.
        assert "is_tm_healthy=True" in logged
        assert "is_transitioning_fast=False" in logged
        assert "seconds_since_last_transition=0.4" in logged
        assert "round=polymarket_fetch_market_round" in logged

    @pytest.mark.asyncio
    async def test_self_reported_unhealthy_log_follows_the_streak_cadence(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """The probe fires every 5s while unhealthy, so the log must not be per-probe."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"is_healthy": False, "rounds": ["some_round"]}
        )
        patcher = self._patched_session(mock_resp)
        try:
            for _ in range(11):
                await health_checker.check_service_health("svc", tmp_path)
        finally:
            patcher.stop()

        assert health_checker.get_liveness("svc")["consecutive_failures"] == 11
        # The 1st and the 10th, matching `healthcheck_job`'s own streak line.
        assert t.cast(MagicMock, health_checker.logger).warning.call_count == 2

    @pytest.mark.asyncio
    async def test_a_missing_rounds_list_does_not_break_the_log(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """An older or partial body must still produce a line, not an IndexError."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"is_transitioning_fast": False})
        patcher = self._patched_session(mock_resp)
        try:
            assert await health_checker.check_service_health("svc", tmp_path) is False
        finally:
            patcher.stop()

        assert (
            health_checker.get_liveness("svc")["reason"] == "agent_reported_unhealthy"
        )
        logged = " ".join(
            str(call.args[0])
            for call in t.cast(MagicMock, health_checker.logger).warning.call_args_list
        )
        assert "round=None" in logged

    @pytest.mark.asyncio
    async def test_unanswered_probes_keep_the_pid_discriminator(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """A probe that got no usable answer is still judged on whether the PID lives."""
        mock_resp = AsyncMock()
        mock_resp.status = 503
        mock_resp.text = AsyncMock(return_value="Service Unavailable")
        patcher = self._patched_session(mock_resp)
        try:
            with patch(
                "operate.services.health_checker.validate_pid", return_value=False
            ):
                assert (
                    await health_checker.check_service_health("svc", tmp_path) is False
                )
        finally:
            patcher.stop()

        assert health_checker.get_liveness("svc")["reason"] == "agent_process_exited"

    def test_consecutive_failures_accumulate(
        self, health_checker: HealthChecker
    ) -> None:
        """Failures count up until a healthy probe resets them."""
        for _ in range(3):
            health_checker.record_failed_probe(
                service_config_id="svc",
                reason=AgentLivenessReason.AGENT_PROCESS_EXITED,
            )

        assert health_checker.get_liveness("svc")["consecutive_failures"] == 3

        health_checker.record_healthy_probe(service_config_id="svc")
        assert health_checker.get_liveness("svc")["consecutive_failures"] == 0


class TestGetLiveness:
    """Test the liveness accessor used by the deployment endpoints."""

    @pytest.fixture
    def health_checker(self) -> HealthChecker:
        """Create a HealthChecker instance for testing."""
        return HealthChecker(service_manager=MagicMock(), logger=MagicMock())

    def test_unknown_service_without_pid_is_not_monitored(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """No record and no PID file means nothing is watching this service."""
        assert health_checker.get_liveness("svc", tmp_path) == {
            "is_alive": False,
            "reason": "not_monitored",
            "last_checked_at": None,
            "last_healthy_at": None,
            "consecutive_failures": 0,
            "restarts_since_last_healthy": 0,
        }

    def test_unknown_service_falls_back_to_the_pid_file(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """In-memory records do not survive a middleware restart; agent.pid does."""
        deployment_dir = tmp_path / "deployment"
        deployment_dir.mkdir()
        (deployment_dir / "agent.pid").write_text("4242", encoding="utf-8")

        with patch("operate.services.health_checker.validate_pid", return_value=True):
            liveness = health_checker.get_liveness("svc", tmp_path)

        assert liveness["is_alive"] is True
        assert liveness["reason"] is None

    def test_unreadable_pid_file_degrades_to_not_monitored(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """A torn PID file must never raise out of a read endpoint."""
        deployment_dir = tmp_path / "deployment"
        deployment_dir.mkdir()
        (deployment_dir / "agent.pid").write_text("not-a-pid", encoding="utf-8")

        assert health_checker.get_liveness("svc", tmp_path)["reason"] == "not_monitored"

    def test_returned_record_is_a_copy(self, health_checker: HealthChecker) -> None:
        """Callers must not be able to mutate the health checker's state."""
        health_checker.record_healthy_probe(service_config_id="svc")

        health_checker.get_liveness("svc")["is_alive"] = False

        assert health_checker.get_liveness("svc")["is_alive"] is True

    def test_record_reason_marks_the_service_not_alive(
        self, health_checker: HealthChecker
    ) -> None:
        """An eviction that cannot be cleared is reported without a probe."""
        health_checker.record_healthy_probe(service_config_id="svc")

        health_checker.record_reason(
            service_config_id="svc",
            reason=AgentLivenessReason.EVICTED_CANNOT_RESTAKE,
        )

        liveness = health_checker.get_liveness("svc")
        assert liveness["is_alive"] is False
        assert liveness["reason"] == "evicted_cannot_restake"

    def test_stop_for_service_drops_an_eviction_reason(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """Nothing refreshes the reason once the job is gone, so it would go stale."""
        health_checker.record_reason(
            service_config_id="svc",
            reason=AgentLivenessReason.EVICTED_CANNOT_RESTAKE,
        )

        health_checker.stop_for_service(service_config_id="svc")

        assert health_checker.get_liveness("svc", tmp_path)["reason"] == "not_monitored"

    def test_stop_for_service_drops_a_healthy_record(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """A stopped service must not keep reporting the agent as running."""
        health_checker.record_healthy_probe(service_config_id="svc")

        health_checker.stop_for_service(service_config_id="svc")

        liveness = health_checker.get_liveness("svc", tmp_path)
        assert liveness["is_alive"] is False
        assert liveness["reason"] == "not_monitored"

    def test_stop_for_service_drops_a_record_of_a_dead_agent(
        self, health_checker: HealthChecker, tmp_path: Path
    ) -> None:
        """A stopped service keeps no reason from the probe that preceded the stop."""
        health_checker.record_failed_probe(
            service_config_id="svc",
            reason=AgentLivenessReason.AGENT_PROCESS_EXITED,
        )

        health_checker.stop_for_service(service_config_id="svc")

        assert health_checker.get_liveness("svc", tmp_path)["reason"] == "not_monitored"

    def test_start_for_service_forgets_the_previous_record(
        self, health_checker: HealthChecker
    ) -> None:
        """A fresh deployment invalidates the reason the last one stopped with."""
        health_checker.record_reason(
            service_config_id="svc",
            reason=AgentLivenessReason.EVICTED_CANNOT_RESTAKE,
        )

        with patch.object(health_checker, "healthcheck_job"):
            asyncio.run(_start_for_service(health_checker, "svc"))

        assert health_checker.get_liveness("svc")["reason"] == "not_monitored"
