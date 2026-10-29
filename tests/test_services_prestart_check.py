# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for operate/services/prestart_check.py."""

import json
import subprocess  # nosec
from pathlib import Path
from typing import Any, Iterator, Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from operate.operate_types import PrestartCheckStatus
from operate.services.prestart_check import (
    PRESTART_CHECK_TIMEOUT,
    run_prestart_check,
)

BINARY = "/services/sc-1/agent_runner_bin"
HELP_WITH_CHECK = b"Commands:\n  prestart-check  Check that this machine can run...\n"
HELP_WITHOUT_CHECK = b"Commands:\n  run  Run the agent.\n"
ISSUE = {
    "code": "polymarket_unreachable",
    "title": "Can't reach Polymarket",
    "description": "Polystrat can't connect to Polymarket.",
}
MODULE = "operate.services.prestart_check"


def _service(tmp_path: Path, is_aea: bool = False) -> MagicMock:
    service = MagicMock()
    service.service_config_id = "sc-1"
    service.path = tmp_path
    service.package_absolute_path = tmp_path / "polymarket_trader"
    service.agent_release = {"is_aea": is_aea}
    service.env_variables = {
        "IS_RUNNING_ON_POLYMARKET": {"value": "true"},
        "POLYMARKET_CLOB_HOST": {"value": "https://clob.example"},
    }
    return service


def _completed(returncode: int, stdout: Any, stderr: bytes = b"") -> MagicMock:
    if not isinstance(stdout, bytes):
        stdout = json.dumps(stdout).encode()
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(name="runner")
def fixture_runner() -> Iterator[MagicMock]:
    """Patch the binary download, its --help and the check subprocess."""
    with (
        patch(f"{MODULE}.get_agent_runner_path", return_value=BINARY),
        patch(
            f"{MODULE}.agent_runner_help",
            return_value=MagicMock(returncode=0, stdout=HELP_WITH_CHECK),
        ),
        patch(f"{MODULE}.subprocess.run") as run,
    ):
        yield run


def _check(
    tmp_path: Path, runner: MagicMock, output: Optional[MagicMock] = None
) -> Any:
    if output is not None:
        runner.return_value = output
    return run_prestart_check(_service(tmp_path))


class TestRunPrestartCheck:
    """Tests for run_prestart_check."""

    def test_passed(self, tmp_path: Path, runner: MagicMock) -> None:
        """Exit 0 with a passed result passes, with no issues."""
        result = _check(
            tmp_path, runner, _completed(0, {"status": "passed", "issues": []})
        )
        assert result == {"status": PrestartCheckStatus.PASSED, "issues": []}

    def test_runs_the_command_like_the_agent_start(
        self, tmp_path: Path, runner: MagicMock
    ) -> None:
        """The check runs on the service package, with the service env and a timeout."""
        _check(tmp_path, runner, _completed(0, {"status": "passed", "issues": []}))
        args = runner.call_args.args[0]
        kwargs = runner.call_args.kwargs
        assert args == [
            BINARY,
            "prestart-check",
            "--service-dir",
            str(tmp_path / "polymarket_trader"),
        ]
        assert kwargs["timeout"] == PRESTART_CHECK_TIMEOUT == 120
        assert kwargs["env"]["POLYMARKET_CLOB_HOST"] == "https://clob.example"
        assert kwargs["env"]["IS_RUNNING_ON_POLYMARKET"] == "true"
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["cwd"] == tmp_path

    def test_runtime_ca_bundle_reaches_the_check(
        self, tmp_path: Path, runner: MagicMock
    ) -> None:
        """The check gets the CA bundle the agent gets at start."""
        with (
            patch(
                "operate.services.deployment_runner.get_runtime_ca_bundle_env",
                return_value={"REQUESTS_CA_BUNDLE": "/bundle.pem"},
            ),
            patch(
                "operate.services.deployment_runner._is_usable_ca_bundle_path",
                return_value=False,
            ),
        ):
            _check(tmp_path, runner, _completed(0, {"status": "passed", "issues": []}))
        assert runner.call_args.kwargs["env"]["REQUESTS_CA_BUNDLE"] == "/bundle.pem"

    def test_failed_returns_the_agent_issues(
        self, tmp_path: Path, runner: MagicMock
    ) -> None:
        """Exit 1 with a failed result passes the agent's issues on as written."""
        result = _check(
            tmp_path,
            runner,
            _completed(1, {"status": "failed", "issues": [{**ISSUE, "extra": 1}]}),
        )
        assert result == {"status": PrestartCheckStatus.FAILED, "issues": [ISSUE]}

    def test_aea_service_is_not_supported(
        self, tmp_path: Path, runner: MagicMock
    ) -> None:
        """A service run by the aea CLI has no agent runner to ask."""
        result = run_prestart_check(_service(tmp_path, is_aea=True))
        assert result == {"status": PrestartCheckStatus.NOT_SUPPORTED, "issues": []}
        runner.assert_not_called()

    def test_runner_without_the_command_is_not_supported(
        self, tmp_path: Path, runner: MagicMock
    ) -> None:
        """An agent release whose --help does not list the command allows the start."""
        with patch(
            f"{MODULE}.agent_runner_help",
            return_value=MagicMock(returncode=0, stdout=HELP_WITHOUT_CHECK),
        ):
            result = _check(tmp_path, runner)
        assert result == {"status": PrestartCheckStatus.NOT_SUPPORTED, "issues": []}
        runner.assert_not_called()

    def test_crashing_help_is_an_error(self, tmp_path: Path, runner: MagicMock) -> None:
        """A --help that crashes is a broken runner, not one without the command."""
        with patch(
            f"{MODULE}.agent_runner_help",
            return_value=MagicMock(returncode=1, stdout=b"Segmentation fault"),
        ):
            result = _check(tmp_path, runner)
        assert result == {"status": PrestartCheckStatus.ERROR, "issues": []}
        runner.assert_not_called()

    @pytest.mark.parametrize(
        ("patched", "error"),
        [
            ("get_agent_runner_path", requests.ConnectionError("offline")),
            ("agent_runner_help", subprocess.TimeoutExpired("--help", 60)),
            ("agent_runner_help", OSError("exec format error")),
        ],
    )
    def test_runner_unavailable_is_an_error(
        self, tmp_path: Path, runner: MagicMock, patched: str, error: Exception
    ) -> None:
        """A binary that cannot be fetched or asked is an error, not a pass."""
        with patch(f"{MODULE}.{patched}", side_effect=error):
            result = _check(tmp_path, runner)
        assert result == {"status": PrestartCheckStatus.ERROR, "issues": []}
        runner.assert_not_called()

    def test_timeout_is_an_error(self, tmp_path: Path, runner: MagicMock) -> None:
        """A check that does not finish in time is an error."""
        runner.side_effect = subprocess.TimeoutExpired("prestart-check", 120)
        result = _check(tmp_path, runner)
        assert result == {"status": PrestartCheckStatus.ERROR, "issues": []}

    @pytest.mark.parametrize(
        ("returncode", "stdout"),
        [
            (2, b""),
            (-9, b""),
            (0, b"not json"),
            (0, b""),
            (0, ["passed"]),
            (0, {"status": "failed", "issues": [ISSUE]}),
            (1, {"status": "passed", "issues": []}),
            (0, {"status": "passed"}),
            (1, {"status": "failed", "issues": []}),
            (1, {"status": "failed", "issues": [{"code": "c", "title": "t"}]}),
            (1, {"status": "failed", "issues": ["polymarket_unreachable"]}),
        ],
    )
    def test_output_off_contract_is_an_error(
        self, tmp_path: Path, runner: MagicMock, returncode: int, stdout: Any
    ) -> None:
        """An exit code or output outside the contract is an error, never a pass."""
        result = _check(tmp_path, runner, _completed(returncode, stdout, b"trace"))
        assert result == {"status": PrestartCheckStatus.ERROR, "issues": []}
