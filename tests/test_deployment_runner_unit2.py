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

"""Unit tests for deployment_runner.py – part 2, targeting uncovered lines."""

import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, PropertyMock, patch

import psutil
import pytest

from operate.services.deployment_runner import (
    BaseDeploymentRunner,
    DeploymentManager,
    HostPythonHostDeploymentRunner,
    PyInstallerHostDeploymentRunnerLinux,
    PyInstallerHostDeploymentRunnerMac,
    _kill_process,
    kill_process,
)
from operate.utils.pid_file import PIDFileError, StalePIDFile


# ---------------------------------------------------------------------------
# Concrete subclass for testing BaseDeploymentRunner abstract methods
# ---------------------------------------------------------------------------


class ConcreteDeploymentRunner(BaseDeploymentRunner):
    """Concrete subclass of BaseDeploymentRunner for testing."""

    @property
    def _agent_runner_bin(self) -> str:
        """Return a fake agent runner binary path."""
        return "/fake/agent_runner"

    def _start_tendermint(self) -> None:
        """No-op tendermint start."""

    def _start_agent(self, password: str) -> None:
        """No-op agent start."""


# ---------------------------------------------------------------------------
# _kill_process tests
# ---------------------------------------------------------------------------


class TestKillProcessHelper:
    """Tests for the module-level _kill_process function (lines 74-91)."""

    def test_pid_does_not_exist_returns_early(self) -> None:
        """When pid_exists returns False, _kill_process returns immediately."""
        with patch(
            "operate.services.deployment_runner.psutil.pid_exists", return_value=False
        ):
            _kill_process(99999)  # Should not raise

    def test_pid_exists_but_status_dead(self) -> None:
        """When process status is DEAD, _kill_process returns without killing."""
        mock_proc = MagicMock()
        mock_proc.status.return_value = psutil.STATUS_DEAD
        with patch(
            "operate.services.deployment_runner.psutil.pid_exists", return_value=True
        ), patch(
            "operate.services.deployment_runner.psutil.Process", return_value=mock_proc
        ):
            _kill_process(12345)
        mock_proc.kill.assert_not_called()

    def test_pid_exists_but_status_zombie(self) -> None:
        """When process status is ZOMBIE, _kill_process returns without killing."""
        mock_proc = MagicMock()
        mock_proc.status.return_value = psutil.STATUS_ZOMBIE
        with patch(
            "operate.services.deployment_runner.psutil.pid_exists", return_value=True
        ), patch(
            "operate.services.deployment_runner.psutil.Process", return_value=mock_proc
        ):
            _kill_process(12345)
        mock_proc.kill.assert_not_called()

    def test_kill_raises_oserror_returns(self) -> None:
        """When process.kill() raises OSError, _kill_process returns."""
        mock_proc = MagicMock()
        mock_proc.status.return_value = psutil.STATUS_RUNNING
        mock_proc.kill.side_effect = OSError("operation not permitted")
        with patch(
            "operate.services.deployment_runner.psutil.pid_exists", return_value=True
        ), patch(
            "operate.services.deployment_runner.psutil.Process", return_value=mock_proc
        ):
            _kill_process(12345)  # Should not raise
        mock_proc.kill.assert_called_once()

    def test_kill_raises_access_denied_returns(self) -> None:
        """When process.kill() raises AccessDenied, _kill_process returns."""
        mock_proc = MagicMock()
        mock_proc.status.return_value = psutil.STATUS_RUNNING
        mock_proc.kill.side_effect = psutil.AccessDenied(pid=12345)
        with patch(
            "operate.services.deployment_runner.psutil.pid_exists", return_value=True
        ), patch(
            "operate.services.deployment_runner.psutil.Process", return_value=mock_proc
        ):
            _kill_process(12345)  # Should not raise
        mock_proc.kill.assert_called_once()

    def test_kill_succeeds_then_pid_disappears(self) -> None:
        """When kill() succeeds, loop continues until pid no longer exists."""
        mock_proc = MagicMock()
        mock_proc.status.return_value = psutil.STATUS_RUNNING
        # First call: pid exists; second call: pid gone
        pid_exists_side_effects = [True, False]

        with patch(
            "operate.services.deployment_runner.psutil.pid_exists",
            side_effect=pid_exists_side_effects,
        ), patch(
            "operate.services.deployment_runner.psutil.Process", return_value=mock_proc
        ), patch(
            "operate.services.deployment_runner.time.sleep"
        ):
            _kill_process(12345)
        mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# kill_process tests
# ---------------------------------------------------------------------------


class TestKillProcess:
    """Tests for the module-level kill_process function (lines 94-104)."""

    def test_pid_does_not_exist_returns_early(self) -> None:
        """When pid_exists returns False, kill_process returns immediately."""
        with patch(
            "operate.services.deployment_runner.psutil.pid_exists", return_value=False
        ) as mock_exists:
            kill_process(99999)
        mock_exists.assert_called_once_with(pid=99999)

    def test_kills_children_then_parent(self) -> None:
        """kill_process kills children first, then the parent."""
        child1 = MagicMock()
        child1.pid = 11111
        child2 = MagicMock()
        child2.pid = 22222
        parent_proc = MagicMock()
        parent_proc.children.return_value = [child1, child2]

        with patch(
            "operate.services.deployment_runner.psutil.pid_exists", return_value=True
        ), patch(
            "operate.services.deployment_runner.psutil.Process",
            return_value=parent_proc,
        ), patch(
            "operate.services.deployment_runner._kill_process"
        ) as mock_kill:
            kill_process(99999)

        # Children killed first (reversed), then parent – each killed twice
        calls = [c.args[0] for c in mock_kill.call_args_list]
        # reversed([child1, child2]) → [child2, child1]
        assert calls == [22222, 22222, 11111, 11111, 99999, 99999]


# ---------------------------------------------------------------------------
# BaseDeploymentRunner.__init__ and log file helpers
# ---------------------------------------------------------------------------


class TestBaseDeploymentRunnerInit:
    """Tests for BaseDeploymentRunner.__init__ (lines 115-118)."""

    def test_init_stores_work_directory_and_is_aea(self, tmp_path: Path) -> None:
        """__init__ stores work_directory and is_aea correctly."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        assert runner._work_directory == tmp_path
        assert runner._is_aea is True

    def test_init_stores_is_aea_false(self, tmp_path: Path) -> None:
        """__init__ works with is_aea=False."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=False)
        assert runner._is_aea is False


class TestOpenLogFiles:
    """Tests for _open_agent_runner_log_file and _open_tendermint_log_file (lines 120-138)."""

    def test_open_agent_runner_log_file(self, tmp_path: Path) -> None:
        """_open_agent_runner_log_file opens a file in the operate dir."""
        # work_directory = tmp_path/svc/hash/build → operate dir = tmp_path
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        runner = ConcreteDeploymentRunner(build_dir, is_aea=True)
        fh = runner._open_agent_runner_log_file()
        assert fh is not None
        fh.close()
        assert (tmp_path / "agent_runner.log").exists()

    def test_open_tendermint_log_file(self, tmp_path: Path) -> None:
        """_open_tendermint_log_file opens a file in the operate dir."""
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        runner = ConcreteDeploymentRunner(build_dir, is_aea=True)
        fh = runner._open_tendermint_log_file()
        assert fh is not None
        fh.close()
        assert (tmp_path / "tm.log").exists()


class TestGetOperateDir:
    """Tests for _get_operate_dir (line 140-142)."""

    def test_get_operate_dir_returns_correct_path(self, tmp_path: Path) -> None:
        """_get_operate_dir returns parent.parent.parent of work_directory."""
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        runner = ConcreteDeploymentRunner(build_dir, is_aea=True)
        assert runner._get_operate_dir() == tmp_path


# ---------------------------------------------------------------------------
# _run_aea_command tests
# ---------------------------------------------------------------------------


class TestRunAeaCommand:
    """Tests for _run_aea_command (lines 144-167)."""

    def test_success_with_exitcode_zero(self, tmp_path: Path) -> None:
        """When process exitcode is 0, no exception is raised."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        mock_proc = MagicMock()
        mock_proc.exitcode = 0

        with patch(
            "operate.services.deployment_runner.multiprocessing.Process",
            return_value=mock_proc,
        ):
            runner._run_aea_command("init", "--reset", cwd=tmp_path)

        mock_proc.start.assert_called_once()
        mock_proc.join.assert_called_once()

    def test_raises_runtime_error_on_nonzero_exitcode(self, tmp_path: Path) -> None:
        """When process exitcode is non-zero, RuntimeError is raised."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        mock_proc = MagicMock()
        mock_proc.exitcode = 1

        with patch(
            "operate.services.deployment_runner.multiprocessing.Process",
            return_value=mock_proc,
        ), pytest.raises(RuntimeError, match="execution failed with exit code"):
            runner._run_aea_command("init", cwd=tmp_path)

    def test_password_arg_is_masked_in_log(self, tmp_path: Path) -> None:
        """Password value following --password is masked in log output."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        mock_proc = MagicMock()
        mock_proc.exitcode = 0
        logged_messages: List[str] = []

        def capture_info(msg: str, *args: Any, **kwargs: Any) -> None:
            logged_messages.append(msg)

        runner.logger = MagicMock()
        runner.logger.info.side_effect = capture_info

        with patch(
            "operate.services.deployment_runner.multiprocessing.Process",
            return_value=mock_proc,
        ):
            runner._run_aea_command(
                "add-key", "--password", "super_secret", "ethereum", cwd=tmp_path
            )

        combined = " ".join(logged_messages)
        assert "super_secret" not in combined
        assert "******" in combined

    def test_password_equals_arg_is_masked_in_log(self, tmp_path: Path) -> None:
        """Password in --password=<value> form is masked in log output."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        mock_proc = MagicMock()
        mock_proc.exitcode = 0
        logged_messages: List[str] = []

        def capture_info(msg: str, *args: Any, **kwargs: Any) -> None:
            logged_messages.append(msg)

        runner.logger = MagicMock()
        runner.logger.info.side_effect = capture_info

        with patch(
            "operate.services.deployment_runner.multiprocessing.Process",
            return_value=mock_proc,
        ):
            runner._run_aea_command("--password=super_secret", cwd=tmp_path)

        combined = " ".join(logged_messages)
        assert "super_secret" not in combined
        assert "--password=******" in combined


# ---------------------------------------------------------------------------
# _run_cmd tests
# ---------------------------------------------------------------------------


class TestRunCmd:
    """Tests for _run_cmd (lines 190-203)."""

    def test_success_with_returncode_zero(self, tmp_path: Path) -> None:
        """When subprocess returncode is 0, no exception is raised."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch(
            "operate.services.deployment_runner.subprocess.run",
            return_value=mock_result,
        ):
            runner._run_cmd(args=["echo", "hello"])

    def test_raises_runtime_error_on_nonzero_returncode(self, tmp_path: Path) -> None:
        """When subprocess returncode is non-zero, RuntimeError is raised."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"some error"

        with patch(
            "operate.services.deployment_runner.subprocess.run",
            return_value=mock_result,
        ), pytest.raises(RuntimeError, match="Error running"):
            runner._run_cmd(args=["false"])


# ---------------------------------------------------------------------------
# _prepare_agent_env tests
# ---------------------------------------------------------------------------


class TestPrepareAgentEnv:
    """Tests for _prepare_agent_env (lines 205-227)."""

    def _make_agent_json(self, work_dir: Path, env: Dict[str, str]) -> None:
        """Write an agent.json file in work_dir."""
        (work_dir / "agent.json").write_text(json.dumps(env), encoding="utf-8")

    def test_basic_env_read_and_pythonutf8_added(self, tmp_path: Path) -> None:
        """_prepare_agent_env reads agent.json and adds PYTHONUTF8=1."""
        self._make_agent_json(tmp_path, {"SOME_VAR": "hello"})
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        result = runner._prepare_agent_env()
        assert result["PYTHONUTF8"] == "1"
        assert result["SOME_VAR"] == "hello"

    def test_tm_control_url_replaced_for_matching_var(self, tmp_path: Path) -> None:
        """TM_CONTROL_URL vars ending in TENDERMINT_COM_URL get replaced."""
        env = {
            "AEA_AGENT": "my_agent",
            "PREFIX_MODELS_PARAMS_ARGS_TENDERMINT_COM_URL": "http://old:9999",
            "PREFIX_MODELS_PARAMS_ARGS_TENDERMINT_URL": "http://old:9998",
            "PREFIX_MODELS_PARAMS_ARGS_TENDERMINT_P2P_URL": "old:9997",
        }
        self._make_agent_json(tmp_path, env)
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        result = runner._prepare_agent_env()

        assert (
            result["PREFIX_MODELS_PARAMS_ARGS_TENDERMINT_COM_URL"]
            == runner.TM_CONTROL_URL
        )
        assert (
            result["PREFIX_MODELS_PARAMS_ARGS_TENDERMINT_URL"]
            == "http://localhost:26657"
        )
        assert (
            result["PREFIX_MODELS_PARAMS_ARGS_TENDERMINT_P2P_URL"] == "localhost:26656"
        )

    def test_agent_json_updated_after_call(self, tmp_path: Path) -> None:
        """agent.json on disk is rewritten with the new env."""
        self._make_agent_json(tmp_path, {"AEA_AGENT": "some/agent:0.1.0:bafybei"})
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner._prepare_agent_env()
        written = json.loads((tmp_path / "agent.json").read_text(encoding="utf-8"))
        assert written["PYTHONUTF8"] == "1"


# ---------------------------------------------------------------------------
# _setup_agent tests
# ---------------------------------------------------------------------------


class TestSetupAgent:
    """Tests for _setup_agent (lines 229-313)."""

    def _make_basic_work_dir(self, tmp_path: Path) -> Path:
        """Create a minimal work dir with agent.json and ethereum key."""
        agent_env = {"AEA_AGENT": "valory/test_agent:0.1.0:bafybei"}
        (tmp_path / "agent.json").write_text(json.dumps(agent_env), encoding="utf-8")
        (tmp_path / "ethereum_private_key.txt").write_text(
            "0xdeadbeef", encoding="utf-8"
        )
        return tmp_path

    def test_success_on_first_attempt(self, tmp_path: Path) -> None:
        """_setup_agent completes without error when commands succeed."""
        work_dir = self._make_basic_work_dir(tmp_path)
        runner = ConcreteDeploymentRunner(work_dir, is_aea=True)

        with patch.object(runner, "_run_aea_command"), patch(
            "operate.services.deployment_runner.shutil.copy"
        ):
            runner._setup_agent(password="testpass")  # nosec B106

    def test_failure_all_attempts_raises_last_exception(self, tmp_path: Path) -> None:
        """_setup_agent raises the last exception after all attempts fail."""
        work_dir = self._make_basic_work_dir(tmp_path)
        runner = ConcreteDeploymentRunner(work_dir, is_aea=True)
        runner.START_TRIES = 1  # type: ignore[assignment]

        with patch.object(
            runner, "_run_aea_command", side_effect=RuntimeError("cmd failed")
        ), patch("operate.services.deployment_runner.time.sleep"), pytest.raises(
            RuntimeError, match="cmd failed"
        ):
            runner._setup_agent(password="testpass")  # nosec B106

    def test_retry_then_succeed(self, tmp_path: Path) -> None:
        """_setup_agent retries and succeeds after initial failures."""
        work_dir = self._make_basic_work_dir(tmp_path)
        runner = ConcreteDeploymentRunner(work_dir, is_aea=True)
        call_count = 0

        def maybe_fail(*args: Any, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient failure")

        with patch.object(runner, "_run_aea_command", side_effect=maybe_fail), patch(
            "operate.services.deployment_runner.shutil.copy"
        ), patch("operate.services.deployment_runner.time.sleep"):
            runner._setup_agent(password="testpass")  # nosec B106

    def test_agent_dir_cleanup_on_retry(self, tmp_path: Path) -> None:
        """Existing agent dir is removed before each attempt."""
        work_dir = self._make_basic_work_dir(tmp_path)
        agent_dir = work_dir / "agent"
        agent_dir.mkdir()
        runner = ConcreteDeploymentRunner(work_dir, is_aea=True)
        call_count = 0

        def succeed_on_second(*args: Any, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("fail once")

        with patch.object(
            runner, "_run_aea_command", side_effect=succeed_on_second
        ), patch("operate.services.deployment_runner.shutil.copy"), patch(
            "operate.services.deployment_runner.time.sleep"
        ), patch(
            "operate.services.deployment_runner.shutil.rmtree"
        ) as mock_rmtree:
            runner._setup_agent(password="testpass")  # nosec B106

        # rmtree called at least once because agent dir existed
        mock_rmtree.assert_called()


# ---------------------------------------------------------------------------
# start / _start tests
# ---------------------------------------------------------------------------


class TestStart:
    """Tests for start (lines 315-325) and _start (lines 327-333)."""

    def test_start_succeeds_first_try(self, tmp_path: Path) -> None:
        """start() calls _start and returns on first success."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        with patch.object(runner, "_start") as mock_start:
            runner.start(password="testpass")  # nosec B106
        mock_start.assert_called_once_with(password="testpass")  # nosec B106

    def test_start_raises_after_all_attempts_fail(self, tmp_path: Path) -> None:
        """start() raises RuntimeError after START_TRIES failures."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        with patch.object(
            runner, "_start", side_effect=RuntimeError("boom")
        ), pytest.raises(RuntimeError, match="Failed to start"):
            runner.start(password="testpass")  # nosec B106

    def test_internal_start_calls_tendermint_when_is_aea(self, tmp_path: Path) -> None:
        """_start calls _start_tendermint when is_aea=True."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        with patch.object(runner, "_setup_agent"), patch.object(
            runner, "_start_tendermint"
        ) as mock_tm, patch.object(runner, "_start_agent"):
            runner._start(password="testpass")  # nosec B106
        mock_tm.assert_called_once()

    def test_internal_start_skips_tendermint_when_not_is_aea(
        self, tmp_path: Path
    ) -> None:
        """_start skips _start_tendermint when is_aea=False."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=False)
        with patch.object(runner, "_setup_agent"), patch.object(
            runner, "_start_tendermint"
        ) as mock_tm, patch.object(runner, "_start_agent"):
            runner._start(password="testpass")  # nosec B106
        mock_tm.assert_not_called()


# ---------------------------------------------------------------------------
# stop tests
# ---------------------------------------------------------------------------


class TestStop:
    """Tests for stop (lines 335-339)."""

    def test_stop_calls_stop_tendermint_when_is_aea(self, tmp_path: Path) -> None:
        """stop() calls _stop_tendermint when is_aea=True."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        with patch.object(runner, "_stop_agent"), patch.object(
            runner, "_stop_tendermint"
        ) as mock_tm:
            runner.stop()
        mock_tm.assert_called_once()

    def test_stop_skips_tendermint_when_not_is_aea(self, tmp_path: Path) -> None:
        """stop() does not call _stop_tendermint when is_aea=False."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=False)
        with patch.object(runner, "_stop_agent"), patch.object(
            runner, "_stop_tendermint"
        ) as mock_tm:
            runner.stop()
        mock_tm.assert_not_called()


# ---------------------------------------------------------------------------
# _stop_agent tests
# ---------------------------------------------------------------------------


class TestStopAgent:
    """Tests for _stop_agent (lines 341-364)."""

    def test_returns_early_if_pid_file_does_not_exist(self, tmp_path: Path) -> None:
        """_stop_agent returns without action when pid file is absent."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        with patch("operate.services.deployment_runner.read_pid_file") as mock_read:
            runner._stop_agent()
        mock_read.assert_not_called()

    def test_kills_process_when_pid_file_exists(self, tmp_path: Path) -> None:
        """_stop_agent reads pid and calls kill_process."""
        pid_file = tmp_path / "agent.pid"
        pid_file.write_text("12345", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)

        with patch(
            "operate.services.deployment_runner.read_pid_file", return_value=12345
        ), patch("operate.services.deployment_runner.kill_process") as mock_kill, patch(
            "operate.services.deployment_runner.remove_pid_file"
        ):
            runner._stop_agent()

        mock_kill.assert_called_once_with(12345)

    def test_file_not_found_error_logged(self, tmp_path: Path) -> None:
        """_stop_agent logs debug when FileNotFoundError raised."""
        pid_file = tmp_path / "agent.pid"
        pid_file.write_text("12345", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch(
            "operate.services.deployment_runner.read_pid_file",
            side_effect=FileNotFoundError("not found"),
        ), patch("operate.services.deployment_runner.kill_process") as mock_kill:
            runner._stop_agent()

        mock_kill.assert_not_called()
        runner.logger.debug.assert_called()

    def test_stale_pid_file_logged(self, tmp_path: Path) -> None:
        """_stop_agent logs debug when StalePIDFile raised."""
        pid_file = tmp_path / "agent.pid"
        pid_file.write_text("12345", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch(
            "operate.services.deployment_runner.read_pid_file",
            side_effect=StalePIDFile("stale"),
        ), patch("operate.services.deployment_runner.kill_process") as mock_kill:
            runner._stop_agent()

        mock_kill.assert_not_called()
        runner.logger.debug.assert_called()

    def test_pid_file_error_logged_and_file_removed(self, tmp_path: Path) -> None:
        """_stop_agent logs error and calls remove_pid_file when PIDFileError raised."""
        pid_file = tmp_path / "agent.pid"
        pid_file.write_text("12345", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch(
            "operate.services.deployment_runner.read_pid_file",
            side_effect=PIDFileError("bad pid"),
        ), patch("operate.services.deployment_runner.remove_pid_file") as mock_remove:
            runner._stop_agent()

        runner.logger.error.assert_called()
        mock_remove.assert_called_once_with(pid_file, force=True)


# ---------------------------------------------------------------------------
# _get_tm_exit_url test
# ---------------------------------------------------------------------------


class TestGetTmExitUrl:
    """Tests for _get_tm_exit_url (line 366-367)."""

    def test_returns_correct_url(self, tmp_path: Path) -> None:
        """_get_tm_exit_url returns TM_CONTROL_URL + /exit."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        url = runner._get_tm_exit_url()
        assert url == f"{runner.TM_CONTROL_URL}/exit"


# ---------------------------------------------------------------------------
# _stop_tendermint tests
# ---------------------------------------------------------------------------


class TestStopTendermint:
    """Tests for _stop_tendermint (lines 369-402)."""

    def test_requests_get_succeeds_and_no_pid_file(self, tmp_path: Path) -> None:
        """_stop_tendermint calls requests.get and returns if no pid file."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        with patch(
            "operate.services.deployment_runner.requests.get"
        ) as mock_get, patch("operate.services.deployment_runner.time.sleep"):
            runner._stop_tendermint()
        mock_get.assert_called_once()

    def test_connection_error_logged(self, tmp_path: Path) -> None:
        """_stop_tendermint logs error when ConnectionError raised."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch(
            "operate.services.deployment_runner.requests.get",
            side_effect=__import__("requests").ConnectionError("no conn"),
        ):
            runner._stop_tendermint()

        runner.logger.error.assert_called()

    def test_generic_exception_logged(self, tmp_path: Path) -> None:
        """_stop_tendermint logs exception for non-ConnectionError exceptions."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch(
            "operate.services.deployment_runner.requests.get",
            side_effect=RuntimeError("generic error"),
        ):
            runner._stop_tendermint()

        runner.logger.exception.assert_called()

    def test_pid_file_exists_kills_process(self, tmp_path: Path) -> None:
        """_stop_tendermint reads pid file and kills process."""
        pid_file = tmp_path / "tendermint.pid"
        pid_file.write_text("55555", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)

        with patch("operate.services.deployment_runner.requests.get"), patch(
            "operate.services.deployment_runner.time.sleep"
        ), patch(
            "operate.services.deployment_runner.read_pid_file", return_value=55555
        ), patch(
            "operate.services.deployment_runner.kill_process"
        ) as mock_kill, patch(
            "operate.services.deployment_runner.remove_pid_file"
        ):
            runner._stop_tendermint()

        mock_kill.assert_called_once_with(55555)

    def test_stale_pid_file_logged(self, tmp_path: Path) -> None:
        """_stop_tendermint logs debug on StalePIDFile."""
        pid_file = tmp_path / "tendermint.pid"
        pid_file.write_text("55555", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch("operate.services.deployment_runner.requests.get"), patch(
            "operate.services.deployment_runner.time.sleep"
        ), patch(
            "operate.services.deployment_runner.read_pid_file",
            side_effect=StalePIDFile("stale"),
        ):
            runner._stop_tendermint()

        runner.logger.debug.assert_called()

    def test_pid_file_error_logs_and_removes(self, tmp_path: Path) -> None:
        """_stop_tendermint logs error and removes file on PIDFileError."""
        pid_file = tmp_path / "tendermint.pid"
        pid_file.write_text("55555", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch("operate.services.deployment_runner.requests.get"), patch(
            "operate.services.deployment_runner.time.sleep"
        ), patch(
            "operate.services.deployment_runner.read_pid_file",
            side_effect=PIDFileError("bad"),
        ), patch(
            "operate.services.deployment_runner.remove_pid_file"
        ) as mock_remove:
            runner._stop_tendermint()

        runner.logger.error.assert_called()
        mock_remove.assert_called_once_with(pid_file, force=True)

    def test_file_not_found_error_logged(self, tmp_path: Path) -> None:
        """_stop_tendermint logs debug when FileNotFoundError raised."""
        pid_file = tmp_path / "tendermint.pid"
        pid_file.write_text("55555", encoding="utf-8")
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        runner.logger = MagicMock()

        with patch("operate.services.deployment_runner.requests.get"), patch(
            "operate.services.deployment_runner.time.sleep"
        ), patch(
            "operate.services.deployment_runner.read_pid_file",
            side_effect=FileNotFoundError("gone"),
        ):
            runner._stop_tendermint()

        runner.logger.debug.assert_called()


# ---------------------------------------------------------------------------
# get_agent_start_args tests
# ---------------------------------------------------------------------------


class TestGetAgentStartArgs:
    """Tests for get_agent_start_args (lines 418-434)."""

    def test_is_aea_true_includes_run_args(self, tmp_path: Path) -> None:
        """get_agent_start_args includes '-s run' when is_aea=True."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=True)
        args = runner.get_agent_start_args(password="pw")  # nosec B106
        assert "/fake/agent_runner" in args
        assert "-s" in args
        assert "run" in args
        assert "--password" in args
        assert "pw" in args  # nosec B106

    def test_is_aea_false_excludes_run_args(self, tmp_path: Path) -> None:
        """get_agent_start_args omits '-s run' when is_aea=False."""
        runner = ConcreteDeploymentRunner(tmp_path, is_aea=False)
        args = runner.get_agent_start_args(password="pw")  # nosec B106
        assert "/fake/agent_runner" in args
        assert "run" not in args
        assert "--password" in args


# ---------------------------------------------------------------------------
# PyInstallerHostDeploymentRunner._agent_runner_bin / _tendermint_bin
# ---------------------------------------------------------------------------


class TestPyInstallerBinProperties:
    """Tests for PyInstallerHostDeploymentRunner properties (lines 440-450)."""

    def test_agent_runner_bin_calls_get_agent_runner_path(self, tmp_path: Path) -> None:
        """_agent_runner_bin uses get_agent_runner_path with service dir."""
        build_dir = tmp_path / "service" / "build"
        build_dir.mkdir(parents=True)
        runner = PyInstallerHostDeploymentRunnerMac(build_dir, is_aea=True)
        with patch(
            "operate.services.deployment_runner.get_agent_runner_path",
            return_value=Path("/fake/path/agent_runner"),
        ) as mock_path:
            result = runner._agent_runner_bin

        mock_path.assert_called_once_with(service_dir=tmp_path / "service")
        assert result == "/fake/path/agent_runner"

    def test_tendermint_bin_ends_with_tendermint_bin(self, tmp_path: Path) -> None:
        """_tendermint_bin ends with 'tendermint_bin'."""
        runner = PyInstallerHostDeploymentRunnerMac(tmp_path, is_aea=True)
        result = runner._tendermint_bin
        assert result.endswith("tendermint_bin")


# ---------------------------------------------------------------------------
# PyInstallerHostDeploymentRunner._start_agent tests
# ---------------------------------------------------------------------------


class TestPyInstallerStartAgent:
    """Tests for PyInstallerHostDeploymentRunner._start_agent (lines 452-479)."""

    def _make_work_dir(self, tmp_path: Path) -> Path:
        """Create work dir with agent.json."""
        env = {"SOME_VAR": "value"}
        (tmp_path / "agent.json").write_text(json.dumps(env), encoding="utf-8")
        return tmp_path

    def test_start_agent_writes_pid_file_on_success(self, tmp_path: Path) -> None:
        """_start_agent writes PID file when process starts successfully."""
        work_dir = self._make_work_dir(tmp_path)
        runner = PyInstallerHostDeploymentRunnerMac(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 42

        with patch.object(
            runner, "_start_agent_process", return_value=mock_process
        ), patch("operate.services.deployment_runner.write_pid_file") as mock_write:
            runner._start_agent(password="pw")  # nosec B106

        mock_write.assert_called_once()

    def test_start_agent_kills_process_on_pid_file_error(self, tmp_path: Path) -> None:
        """_start_agent kills process and re-raises on PIDFileError."""
        work_dir = self._make_work_dir(tmp_path)
        runner = PyInstallerHostDeploymentRunnerMac(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 42

        with patch.object(
            runner, "_start_agent_process", return_value=mock_process
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process"
        ) as mock_kill, pytest.raises(
            PIDFileError
        ):
            runner._start_agent(password="pw")  # nosec B106

        mock_kill.assert_called_once_with(42)

    def test_start_agent_kill_exception_swallowed_pid_error_propagates(
        self, tmp_path: Path
    ) -> None:
        """_start_agent swallows kill exception; original PIDFileError propagates."""
        work_dir = self._make_work_dir(tmp_path)
        runner = PyInstallerHostDeploymentRunnerMac(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 42

        with patch.object(
            runner, "_start_agent_process", return_value=mock_process
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process",
            side_effect=OSError("kill failed"),
        ), pytest.raises(
            PIDFileError
        ):
            runner._start_agent(password="pw")  # nosec B106


# ---------------------------------------------------------------------------
# PyInstallerHostDeploymentRunner._start_tendermint tests
# ---------------------------------------------------------------------------


class TestPyInstallerStartTendermint:
    """Tests for PyInstallerHostDeploymentRunner._start_tendermint (lines 487-516)."""

    def _make_work_dir(self, tmp_path: Path) -> Path:
        """Create work dir with tendermint.json."""
        env = {"SOME_TM_VAR": "value"}
        (tmp_path / "tendermint.json").write_text(json.dumps(env), encoding="utf-8")
        return tmp_path

    def test_start_tendermint_writes_pid_file_on_success(self, tmp_path: Path) -> None:
        """_start_tendermint writes PID file when process starts successfully."""
        work_dir = self._make_work_dir(tmp_path)
        runner = PyInstallerHostDeploymentRunnerMac(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 99

        with patch.object(
            runner, "_start_tendermint_process", return_value=mock_process
        ), patch("operate.services.deployment_runner.write_pid_file") as mock_write:
            runner._start_tendermint()

        mock_write.assert_called_once()

    def test_start_tendermint_kills_process_on_pid_file_error(
        self, tmp_path: Path
    ) -> None:
        """_start_tendermint kills process and re-raises on PIDFileError."""
        work_dir = self._make_work_dir(tmp_path)
        runner = PyInstallerHostDeploymentRunnerMac(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 99

        with patch.object(
            runner, "_start_tendermint_process", return_value=mock_process
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process"
        ) as mock_kill, pytest.raises(
            PIDFileError
        ):
            runner._start_tendermint()

        mock_kill.assert_called_once_with(99)

    def test_start_tendermint_kill_exception_swallowed_pid_error_propagates(
        self, tmp_path: Path
    ) -> None:
        """_start_tendermint swallows kill exception; original PIDFileError propagates."""
        work_dir = self._make_work_dir(tmp_path)
        runner = PyInstallerHostDeploymentRunnerMac(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 99

        with patch.object(
            runner, "_start_tendermint_process", return_value=mock_process
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process",
            side_effect=OSError("kill failed"),
        ), pytest.raises(
            PIDFileError
        ):
            runner._start_tendermint()


# ---------------------------------------------------------------------------
# PyInstallerHostDeploymentRunnerMac._start_agent_process / _start_tendermint_process
# ---------------------------------------------------------------------------


class TestPyInstallerMacStartProcessMethods:
    """Tests for Mac-specific process start methods (lines 527-559)."""

    def test_start_agent_process_returns_popen(self, tmp_path: Path) -> None:
        """_start_agent_process returns a subprocess.Popen object."""
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        (build_dir / "agent").mkdir()
        runner = PyInstallerHostDeploymentRunnerMac(build_dir, is_aea=True)

        mock_popen = MagicMock(spec=subprocess.Popen)
        mock_log_file = MagicMock()

        with patch.object(
            runner, "_open_agent_runner_log_file", return_value=mock_log_file
        ), patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_popen,
        ) as mock_popen_cls, patch.object(
            runner,
            "get_agent_start_args",
            return_value=["/fake/runner", "--password", "pw"],  # nosec B106
        ):
            result = runner._start_agent_process(
                env={"VAR": "val"}, working_dir=build_dir, password="pw"  # nosec B106
            )

        assert result is mock_popen
        mock_popen_cls.assert_called_once()

    def test_start_tendermint_process_returns_popen(self, tmp_path: Path) -> None:
        """_start_tendermint_process returns a subprocess.Popen object."""
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        runner = PyInstallerHostDeploymentRunnerMac(build_dir, is_aea=True)

        mock_popen = MagicMock(spec=subprocess.Popen)
        mock_log_file = MagicMock()

        with patch.object(
            runner, "_open_tendermint_log_file", return_value=mock_log_file
        ), patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_popen,
        ) as mock_popen_cls, patch.object(
            type(runner),
            "_tendermint_bin",
            new_callable=PropertyMock,
            return_value="/fake/tm",
        ):
            result = runner._start_tendermint_process(
                env={"VAR": "val"}, working_dir=build_dir
            )

        assert result is mock_popen
        mock_popen_cls.assert_called_once()


# ---------------------------------------------------------------------------
# PyInstallerHostDeploymentRunnerLinux
# ---------------------------------------------------------------------------


class TestPyInstallerLinux:
    """Tests for PyInstallerHostDeploymentRunnerLinux (inherits from Mac)."""

    def test_linux_runner_is_mac_subclass(self) -> None:
        """Test that Linux runner is a subclass of Mac runner."""
        assert issubclass(
            PyInstallerHostDeploymentRunnerLinux, PyInstallerHostDeploymentRunnerMac
        )

    def test_linux_runner_can_be_instantiated(self, tmp_path: Path) -> None:
        """Test that Linux runner can be instantiated."""
        runner = PyInstallerHostDeploymentRunnerLinux(tmp_path, is_aea=False)
        assert runner._is_aea is False


# ---------------------------------------------------------------------------
# HostPythonHostDeploymentRunner._agent_runner_bin
# ---------------------------------------------------------------------------


class TestHostPythonAgentRunnerBin:
    """Tests for HostPythonHostDeploymentRunner._agent_runner_bin (lines 692-700)."""

    def test_is_aea_true_returns_venv_aea_path(self, tmp_path: Path) -> None:
        """When is_aea=True, _agent_runner_bin returns venv/bin/aea path."""
        runner = HostPythonHostDeploymentRunner(tmp_path, is_aea=True)
        result = runner._agent_runner_bin
        assert result == str(tmp_path / "venv" / "bin" / "aea")

    def test_is_aea_false_uses_get_agent_runner_path(self, tmp_path: Path) -> None:
        """When is_aea=False, _agent_runner_bin uses get_agent_runner_path."""
        build_dir = tmp_path / "service" / "build"
        build_dir.mkdir(parents=True)
        runner = HostPythonHostDeploymentRunner(build_dir, is_aea=False)

        with patch(
            "operate.services.deployment_runner.get_agent_runner_path",
            return_value=Path("/fake/agent_runner"),
        ) as mock_path:
            result = runner._agent_runner_bin

        mock_path.assert_called_once_with(service_dir=tmp_path / "service")
        assert result == "/fake/agent_runner"


# ---------------------------------------------------------------------------
# HostPythonHostDeploymentRunner._start_agent tests
# ---------------------------------------------------------------------------


class TestHostPythonStartAgent:
    """Tests for HostPythonHostDeploymentRunner._start_agent (lines 702-736)."""

    def _make_work_dir(self, tmp_path: Path) -> Path:
        """Create work dir with agent.json."""
        env = {"SOME_VAR": "value"}
        (tmp_path / "agent.json").write_text(json.dumps(env), encoding="utf-8")
        (tmp_path / "agent").mkdir()
        return tmp_path

    def test_start_agent_writes_pid_file_on_success(self, tmp_path: Path) -> None:
        """_start_agent writes PID file when process starts successfully."""
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        work_dir = self._make_work_dir(build_dir)
        runner = HostPythonHostDeploymentRunner(work_dir, is_aea=False)

        mock_process = MagicMock()
        mock_process.pid = 77
        mock_log_file = MagicMock()

        with patch.object(
            runner, "_open_agent_runner_log_file", return_value=mock_log_file
        ), patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_process,
        ), patch.object(
            runner,
            "get_agent_start_args",
            return_value=["/fake/runner", "--password", "pw"],  # nosec B106
        ), patch(
            "operate.services.deployment_runner.write_pid_file"
        ) as mock_write:
            runner._start_agent(password="pw")  # nosec B106

        mock_write.assert_called_once()

    def test_start_agent_kills_process_on_pid_file_error(self, tmp_path: Path) -> None:
        """_start_agent kills process and re-raises on PIDFileError."""
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        work_dir = self._make_work_dir(build_dir)
        runner = HostPythonHostDeploymentRunner(work_dir, is_aea=False)

        mock_process = MagicMock()
        mock_process.pid = 77
        mock_log_file = MagicMock()

        with patch.object(
            runner, "_open_agent_runner_log_file", return_value=mock_log_file
        ), patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_process,
        ), patch.object(
            runner,
            "get_agent_start_args",
            return_value=["/fake/runner", "--password", "pw"],  # nosec B106
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process"
        ) as mock_kill, pytest.raises(
            PIDFileError
        ):
            runner._start_agent(password="pw")  # nosec B106

        mock_kill.assert_called_once_with(77)

    def test_start_agent_kill_exception_swallowed_pid_error_propagates(
        self, tmp_path: Path
    ) -> None:
        """_start_agent swallows kill exception; original PIDFileError propagates."""
        build_dir = tmp_path / "svc" / "hash" / "build"
        build_dir.mkdir(parents=True)
        work_dir = self._make_work_dir(build_dir)
        runner = HostPythonHostDeploymentRunner(work_dir, is_aea=False)

        mock_process = MagicMock()
        mock_process.pid = 77
        mock_log_file = MagicMock()

        with patch.object(
            runner, "_open_agent_runner_log_file", return_value=mock_log_file
        ), patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_process,
        ), patch.object(
            runner,
            "get_agent_start_args",
            return_value=["/fake/runner", "--password", "pw"],  # nosec B106
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process",
            side_effect=OSError("kill failed"),
        ), pytest.raises(
            PIDFileError
        ):
            runner._start_agent(password="pw")  # nosec B106


# ---------------------------------------------------------------------------
# HostPythonHostDeploymentRunner._start_tendermint tests
# ---------------------------------------------------------------------------


class TestHostPythonStartTendermint:
    """Tests for HostPythonHostDeploymentRunner._start_tendermint (lines 738-778)."""

    def _make_work_dir(self, tmp_path: Path) -> Path:
        """Create work dir with tendermint.json."""
        env = {"SOME_TM_VAR": "value"}
        (tmp_path / "tendermint.json").write_text(json.dumps(env), encoding="utf-8")
        return tmp_path

    def test_start_tendermint_writes_pid_file_on_success(self, tmp_path: Path) -> None:
        """_start_tendermint writes PID file when process starts successfully."""
        work_dir = self._make_work_dir(tmp_path)
        runner = HostPythonHostDeploymentRunner(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 88

        with patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_process,
        ), patch("operate.services.deployment_runner.write_pid_file") as mock_write:
            runner._start_tendermint()

        mock_write.assert_called_once()

    def test_start_tendermint_kills_process_on_pid_file_error(
        self, tmp_path: Path
    ) -> None:
        """_start_tendermint kills process and re-raises on PIDFileError."""
        work_dir = self._make_work_dir(tmp_path)
        runner = HostPythonHostDeploymentRunner(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 88

        with patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_process,
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process"
        ) as mock_kill, pytest.raises(
            PIDFileError
        ):
            runner._start_tendermint()

        mock_kill.assert_called_once_with(88)

    def test_start_tendermint_kill_exception_swallowed_pid_error_propagates(
        self, tmp_path: Path
    ) -> None:
        """_start_tendermint swallows kill exception; original PIDFileError propagates."""
        work_dir = self._make_work_dir(tmp_path)
        runner = HostPythonHostDeploymentRunner(work_dir, is_aea=True)

        mock_process = MagicMock()
        mock_process.pid = 88

        with patch(
            "operate.services.deployment_runner.subprocess.Popen",
            return_value=mock_process,
        ), patch(
            "operate.services.deployment_runner.write_pid_file",
            side_effect=PIDFileError("write failed"),
        ), patch(
            "operate.services.deployment_runner.kill_process",
            side_effect=OSError("kill failed"),
        ), pytest.raises(
            PIDFileError
        ):
            runner._start_tendermint()


# ---------------------------------------------------------------------------
# HostPythonHostDeploymentRunner._venv_dir
# ---------------------------------------------------------------------------


class TestHostPythonVenvDir:
    """Tests for HostPythonHostDeploymentRunner._venv_dir (line 780-783)."""

    def test_venv_dir_is_work_directory_venv(self, tmp_path: Path) -> None:
        """_venv_dir returns work_directory / 'venv'."""
        runner = HostPythonHostDeploymentRunner(tmp_path, is_aea=True)
        assert runner._venv_dir == tmp_path / "venv"


# ---------------------------------------------------------------------------
# HostPythonHostDeploymentRunner._setup_venv tests
# ---------------------------------------------------------------------------


class TestHostPythonSetupVenv:
    """Tests for HostPythonHostDeploymentRunner._setup_venv (lines 785-809)."""

    def test_setup_venv_returns_early_when_not_is_aea(self, tmp_path: Path) -> None:
        """_setup_venv returns early when is_aea=False."""
        runner = HostPythonHostDeploymentRunner(tmp_path, is_aea=False)
        with patch(
            "operate.services.deployment_runner.venv_cli"
        ) as mock_venv, patch.object(runner, "_run_cmd") as mock_cmd:
            runner._setup_venv()
        mock_venv.assert_not_called()
        mock_cmd.assert_not_called()

    def test_setup_venv_calls_venv_cli_and_run_cmd_when_is_aea(
        self, tmp_path: Path
    ) -> None:
        """_setup_venv calls venv_cli and _run_cmd when is_aea=True."""
        runner = HostPythonHostDeploymentRunner(tmp_path, is_aea=True)
        with patch(
            "operate.services.deployment_runner.venv_cli"
        ) as mock_venv, patch.object(runner, "_run_cmd") as mock_cmd:
            runner._setup_venv()

        mock_venv.assert_called_once()
        mock_cmd.assert_called_once()


# ---------------------------------------------------------------------------
# HostPythonHostDeploymentRunner._setup_agent tests
# ---------------------------------------------------------------------------


class TestHostPythonSetupAgent:
    """Tests for HostPythonHostDeploymentRunner._setup_agent (lines 811-830)."""

    def test_setup_agent_not_aea_returns_after_super(self, tmp_path: Path) -> None:
        """_setup_agent returns early after super() call when is_aea=False."""
        runner = HostPythonHostDeploymentRunner(tmp_path, is_aea=False)
        with patch(
            "operate.services.deployment_runner.multiprocessing.set_start_method"
        ), patch.object(runner, "_setup_venv"), patch(
            "operate.services.deployment_runner.BaseDeploymentRunner._setup_agent"
        ), patch.object(
            runner, "_run_cmd"
        ) as mock_cmd:
            runner._setup_agent(password="pw")  # nosec B106

        mock_cmd.assert_not_called()

    def test_setup_agent_is_aea_calls_run_cmd(self, tmp_path: Path) -> None:
        """_setup_agent calls _run_cmd for pip install when is_aea=True."""
        runner = HostPythonHostDeploymentRunner(tmp_path, is_aea=True)
        with patch(
            "operate.services.deployment_runner.multiprocessing.set_start_method"
        ), patch.object(runner, "_setup_venv"), patch(
            "operate.services.deployment_runner.BaseDeploymentRunner._setup_agent"
        ), patch.object(
            runner, "_run_cmd"
        ) as mock_cmd:
            runner._setup_agent(password="pw")  # nosec B106

        mock_cmd.assert_called_once()


# ---------------------------------------------------------------------------
# DeploymentManager._get_host_deployment_runner_class frozen paths
# ---------------------------------------------------------------------------


class TestDeploymentManagerFrozenPaths:
    """Tests for DeploymentManager._get_host_deployment_runner_class frozen paths (line 858)."""

    def test_frozen_darwin_returns_mac_runner(self) -> None:
        """Test frozen + Darwin returns PyInstallerHostDeploymentRunnerMac."""
        with patch("sys.frozen", True, create=True), patch(
            "sys._MEIPASS", "/path", create=True
        ), patch("platform.system", return_value="Darwin"):
            cls = DeploymentManager._get_host_deployment_runner_class()
        assert cls is PyInstallerHostDeploymentRunnerMac

    def test_frozen_linux_returns_linux_runner(self) -> None:
        """Test frozen + Linux returns PyInstallerHostDeploymentRunnerLinux."""
        with patch("sys.frozen", True, create=True), patch(
            "sys._MEIPASS", "/path", create=True
        ), patch("platform.system", return_value="Linux"):
            cls = DeploymentManager._get_host_deployment_runner_class()
        assert cls is PyInstallerHostDeploymentRunnerLinux

    def test_frozen_unsupported_platform_raises_value_error(self) -> None:
        """Test frozen + unsupported platform raises ValueError."""
        with patch("sys.frozen", True, create=True), patch(
            "sys._MEIPASS", "/path", create=True
        ), patch("platform.system", return_value="FreeBSD"), pytest.raises(
            ValueError, match="Platform is not supported"
        ):
            DeploymentManager._get_host_deployment_runner_class()

    def test_not_frozen_returns_python_runner(self) -> None:
        """Not frozen → HostPythonHostDeploymentRunner."""
        frozen_was_set = hasattr(sys, "frozen")
        saved = getattr(sys, "frozen", None)
        if frozen_was_set:
            del sys.frozen  # type: ignore[attr-defined]
        try:
            cls = DeploymentManager._get_host_deployment_runner_class()
        finally:
            if frozen_was_set and saved is not None:
                sys.frozen = saved  # type: ignore[attr-defined]
        assert cls is HostPythonHostDeploymentRunner


# ---------------------------------------------------------------------------
# DeploymentManager._get_deployment_runner
# ---------------------------------------------------------------------------


class TestDeploymentManagerGetDeploymentRunner:
    """Tests for DeploymentManager._get_deployment_runner (line 854-858)."""

    def test_returns_instance_of_runner_class(self, tmp_path: Path) -> None:
        """_get_deployment_runner returns an instance of the runner class."""
        manager = DeploymentManager()
        manager._deployment_runner_class = ConcreteDeploymentRunner  # type: ignore[assignment]
        runner = manager._get_deployment_runner(build_dir=tmp_path, is_aea=True)
        assert isinstance(runner, ConcreteDeploymentRunner)
        assert runner._work_directory == tmp_path
        assert runner._is_aea is True
