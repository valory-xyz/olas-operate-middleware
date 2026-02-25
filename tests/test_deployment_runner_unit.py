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

"""Unit tests for operate/services/deployment_runner.py – no subprocess required."""

import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.services.deployment_runner import (
    AbstractDeploymentRunner,
    DeploymentManager,
    HostPythonHostDeploymentRunner,
    PyInstallerHostDeploymentRunnerLinux,
    PyInstallerHostDeploymentRunnerMac,
    PyInstallerHostDeploymentRunnerWindows,
    States,
    run_host_deployment,
    stop_deployment_manager,
    stop_host_deployment,
)


# ---------------------------------------------------------------------------
# States enum
# ---------------------------------------------------------------------------


class TestStates:
    """Tests for the States deployment enum (lines 833-841)."""

    def test_none_value(self) -> None:
        """Test NONE has value 0."""
        assert States.NONE.value == 0

    def test_starting_value(self) -> None:
        """Test STARTING has value 1."""
        assert States.STARTING.value == 1

    def test_started_value(self) -> None:
        """Test STARTED has value 2."""
        assert States.STARTED.value == 2

    def test_stopping_value(self) -> None:
        """Test STOPPING has value 3."""
        assert States.STOPPING.value == 3

    def test_stopped_value(self) -> None:
        """Test STOPPED has value 4."""
        assert States.STOPPED.value == 4

    def test_error_value(self) -> None:
        """Test ERROR has value 5."""
        assert States.ERROR.value == 5

    def test_from_int(self) -> None:
        """Test States can be constructed from its integer value."""
        assert States(0) == States.NONE
        assert States(5) == States.ERROR


# ---------------------------------------------------------------------------
# AbstractDeploymentRunner
# ---------------------------------------------------------------------------


class TestAbstractDeploymentRunner:
    """Tests for AbstractDeploymentRunner.__init__ (line 63)."""

    def test_init_stores_work_directory(self, tmp_path: Path) -> None:
        """Test that __init__ stores the work directory."""

        class _Concrete(AbstractDeploymentRunner):
            def start(self, password: str) -> None:
                pass

            def stop(self) -> None:
                pass

        runner = _Concrete(tmp_path)
        assert runner._work_directory == tmp_path


# ---------------------------------------------------------------------------
# DeploymentManager
# ---------------------------------------------------------------------------


def _make_manager() -> DeploymentManager:
    """Create a fresh DeploymentManager with an empty state."""
    manager = DeploymentManager()
    # Reset state to avoid module-level singleton pollution
    manager._states = {}
    manager._is_stopping = False
    return manager


class TestDeploymentManagerGetHostClass:
    """Tests for DeploymentManager._get_host_deployment_runner_class (lines 860-874)."""

    def test_returns_python_runner_when_not_frozen(self) -> None:
        """Test that HostPythonHostDeploymentRunner is returned when not frozen."""
        import sys

        # Ensure sys.frozen is absent (non-PyInstaller environment)
        frozen_was_set = hasattr(sys, "frozen")
        if frozen_was_set:
            del sys.frozen  # type: ignore[attr-defined]
        try:
            cls = DeploymentManager._get_host_deployment_runner_class()
        finally:
            if frozen_was_set:
                sys.frozen = True  # type: ignore[attr-defined]
        assert cls is HostPythonHostDeploymentRunner

    def test_returns_mac_runner_for_darwin_when_frozen(self) -> None:
        """Test that PyInstallerHostDeploymentRunnerMac is returned on macOS+frozen."""
        with patch("sys.frozen", True, create=True), patch(
            "sys._MEIPASS", "/path", create=True
        ), patch("platform.system", return_value="Darwin"):
            cls = DeploymentManager._get_host_deployment_runner_class()
        assert cls is PyInstallerHostDeploymentRunnerMac

    def test_returns_windows_runner_for_windows_when_frozen(self) -> None:
        """Test that PyInstallerHostDeploymentRunnerWindows is returned on Windows+frozen."""
        with patch("sys.frozen", True, create=True), patch(
            "sys._MEIPASS", "/path", create=True
        ), patch("platform.system", return_value="Windows"):
            cls = DeploymentManager._get_host_deployment_runner_class()
        assert cls is PyInstallerHostDeploymentRunnerWindows

    def test_returns_linux_runner_for_linux_when_frozen(self) -> None:
        """Test that PyInstallerHostDeploymentRunnerLinux is returned on Linux+frozen."""
        with patch("sys.frozen", True, create=True), patch(
            "sys._MEIPASS", "/path", create=True
        ), patch("platform.system", return_value="Linux"):
            cls = DeploymentManager._get_host_deployment_runner_class()
        assert cls is PyInstallerHostDeploymentRunnerLinux

    def test_raises_for_unknown_platform_when_frozen(self) -> None:
        """Test that ValueError is raised for an unknown platform when frozen."""
        with patch("sys.frozen", True, create=True), patch(
            "sys._MEIPASS", "/path", create=True
        ), patch("platform.system", return_value="FreeBSD"):
            with pytest.raises(ValueError, match="Platform is not supported"):
                DeploymentManager._get_host_deployment_runner_class()


class TestDeploymentManagerStop:
    """Tests for DeploymentManager.stop (lines 876-879)."""

    def test_stop_sets_is_stopping(self) -> None:
        """Test that stop() sets _is_stopping to True."""
        manager = _make_manager()
        assert manager._is_stopping is False
        manager.stop()
        assert manager._is_stopping is True


class TestDeploymentManagerGetState:
    """Tests for DeploymentManager.get_state (lines 881-883)."""

    def test_returns_none_state_for_unknown_build_dir(self, tmp_path: Path) -> None:
        """Test that get_state returns States.NONE for an unknown build dir."""
        manager = _make_manager()
        result = manager.get_state(tmp_path)
        assert result == States.NONE

    def test_returns_correct_state_for_known_build_dir(self, tmp_path: Path) -> None:
        """Test that get_state returns the stored state."""
        manager = _make_manager()
        manager._states[tmp_path] = States.STARTED
        assert manager.get_state(tmp_path) == States.STARTED


class TestDeploymentManagerCheckIpfsConnection:
    """Tests for DeploymentManager.check_ipfs_connection_works (lines 885-907)."""

    def test_succeeds_on_first_attempt(self) -> None:
        """Test that check_ipfs_connection_works returns when requests.get succeeds."""
        manager = _make_manager()
        with patch("operate.services.deployment_runner.requests.get") as mock_get:
            manager.check_ipfs_connection_works()
        mock_get.assert_called_once()

    def test_retries_on_generic_exception_then_raises(self) -> None:
        """Test that non-OSError exceptions trigger retries, then raise RuntimeError."""
        manager = _make_manager()
        with patch(
            "operate.services.deployment_runner.requests.get",
            side_effect=Exception("connection failed"),
        ), patch("operate.services.deployment_runner.time.sleep"):
            with pytest.raises(RuntimeError, match="Failed to perform test connection"):
                manager.check_ipfs_connection_works()

    def test_raises_os_error_immediately(self) -> None:
        """Test that OSError is re-raised immediately without further retries."""
        manager = _make_manager()
        with patch(
            "operate.services.deployment_runner.requests.get",
            side_effect=OSError("network unreachable"),
        ):
            with pytest.raises(OSError, match="network unreachable"):
                manager.check_ipfs_connection_works()


class TestDeploymentManagerRunDeployment:
    """Tests for DeploymentManager.run_deployment (lines 909-941)."""

    def test_raises_when_manager_is_stopping(self, tmp_path: Path) -> None:
        """Test RuntimeError when the manager is already stopping."""
        manager = _make_manager()
        manager._is_stopping = True
        with pytest.raises(RuntimeError, match="deployment manager stopped"):
            manager.run_deployment(build_dir=tmp_path, password="pass")  # nosec B106

    def test_raises_when_service_already_starting(self, tmp_path: Path) -> None:
        """Test ValueError when the service is already in STARTING state."""
        manager = _make_manager()
        manager._states[tmp_path] = States.STARTING
        with pytest.raises(ValueError, match="Service already in transition"):
            manager.run_deployment(build_dir=tmp_path, password="pass")  # nosec B106

    def test_raises_when_service_already_stopping(self, tmp_path: Path) -> None:
        """Test ValueError when the service is already in STOPPING state."""
        manager = _make_manager()
        manager._states[tmp_path] = States.STOPPING
        with pytest.raises(ValueError, match="Service already in transition"):
            manager.run_deployment(build_dir=tmp_path, password="pass")  # nosec B106

    def test_successful_run_sets_started_state(self, tmp_path: Path) -> None:
        """Test that a successful run sets state to STARTED."""
        manager = _make_manager()
        mock_runner = MagicMock()
        with patch.object(
            manager, "_get_deployment_runner", return_value=mock_runner
        ), patch.object(manager, "check_ipfs_connection_works"):
            manager.run_deployment(build_dir=tmp_path, password="pass")  # nosec B106

        assert manager._states[tmp_path] == States.STARTED
        mock_runner.start.assert_called_once_with(password="pass")  # nosec B106

    def test_exception_sets_error_state_and_stops(self, tmp_path: Path) -> None:
        """Test that an exception during start sets ERROR state and calls stop."""
        manager = _make_manager()
        mock_runner = MagicMock()
        mock_runner.start.side_effect = RuntimeError("start failed")
        with patch.object(
            manager, "_get_deployment_runner", return_value=mock_runner
        ), patch.object(manager, "check_ipfs_connection_works"), patch.object(
            manager, "stop_deployment"
        ) as mock_stop:
            manager.run_deployment(build_dir=tmp_path, password="pass")  # nosec B106

        assert manager._states[tmp_path] == States.ERROR
        mock_stop.assert_called_once_with(build_dir=tmp_path, force=True)

    def test_stops_if_is_stopping_set_during_run(self, tmp_path: Path) -> None:
        """Test that a warning is logged and deployment is stopped if is_stopping is set."""
        manager = _make_manager()
        mock_runner = MagicMock()

        def set_stopping(*_args: t.Any, **_kwargs: t.Any) -> None:
            manager._is_stopping = True

        mock_runner.start.side_effect = set_stopping
        with patch.object(
            manager, "_get_deployment_runner", return_value=mock_runner
        ), patch.object(manager, "check_ipfs_connection_works"), patch.object(
            manager, "stop_deployment"
        ) as mock_stop:
            manager.run_deployment(build_dir=tmp_path, password="pass")  # nosec B106

        mock_stop.assert_called_with(build_dir=tmp_path, force=True)


class TestDeploymentManagerStopDeployment:
    """Tests for DeploymentManager.stop_deployment (lines 943-964)."""

    def test_raises_when_service_in_transition_without_force(
        self, tmp_path: Path
    ) -> None:
        """Test ValueError when service is in transition and force is False."""
        manager = _make_manager()
        manager._states[tmp_path] = States.STARTING
        with pytest.raises(ValueError, match="Service already in transition"):
            manager.stop_deployment(build_dir=tmp_path)

    def test_force_overrides_transition_check(self, tmp_path: Path) -> None:
        """Test that force=True allows stopping even when in transition."""
        manager = _make_manager()
        manager._states[tmp_path] = States.STARTING
        mock_runner = MagicMock()
        with patch.object(manager, "_get_deployment_runner", return_value=mock_runner):
            manager.stop_deployment(build_dir=tmp_path, force=True)
        assert manager._states[tmp_path] == States.STOPPED

    def test_successful_stop_sets_stopped_state(self, tmp_path: Path) -> None:
        """Test that a successful stop sets state to STOPPED."""
        manager = _make_manager()
        mock_runner = MagicMock()
        with patch.object(manager, "_get_deployment_runner", return_value=mock_runner):
            manager.stop_deployment(build_dir=tmp_path)
        assert manager._states[tmp_path] == States.STOPPED

    def test_exception_during_stop_sets_error_and_reraises(
        self, tmp_path: Path
    ) -> None:
        """Test that exception during stop sets ERROR state and re-raises."""
        manager = _make_manager()
        mock_runner = MagicMock()
        mock_runner.stop.side_effect = RuntimeError("stop failed")
        with patch.object(manager, "_get_deployment_runner", return_value=mock_runner):
            with pytest.raises(RuntimeError, match="stop failed"):
                manager.stop_deployment(build_dir=tmp_path)
        assert manager._states[tmp_path] == States.ERROR


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    """Tests for run_host_deployment, stop_host_deployment, stop_deployment_manager."""

    def test_run_host_deployment_delegates_to_manager(self, tmp_path: Path) -> None:
        """Test run_host_deployment calls deployment_manager.run_deployment."""
        import operate.services.deployment_runner as dr

        with patch.object(dr.deployment_manager, "run_deployment") as mock_run:
            run_host_deployment(build_dir=tmp_path, password="pass")  # nosec B106
        mock_run.assert_called_once_with(
            build_dir=tmp_path, password="pass", is_aea=True  # nosec B106
        )

    def test_stop_host_deployment_delegates_to_manager(self, tmp_path: Path) -> None:
        """Test stop_host_deployment calls deployment_manager.stop_deployment."""
        import operate.services.deployment_runner as dr

        with patch.object(dr.deployment_manager, "stop_deployment") as mock_stop:
            stop_host_deployment(build_dir=tmp_path)
        mock_stop.assert_called_once_with(build_dir=tmp_path, is_aea=True)

    def test_stop_deployment_manager_calls_manager_stop(self) -> None:
        """Test stop_deployment_manager calls deployment_manager.stop()."""
        import operate.services.deployment_runner as dr

        with patch.object(dr.deployment_manager, "stop") as mock_stop:
            stop_deployment_manager()
        mock_stop.assert_called_once()
