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
"""Run an agent's own checks before it is started."""

import json
import os
import subprocess  # nosec
import typing as t

from aea.helpers.logging import setup_logger

from operate.operate_types import AgentIssue, PrestartCheckResult, PrestartCheckStatus
from operate.services.agent_assets import get_agent_runner_path
from operate.services.deployment_runner import (
    BaseDeploymentRunner,
    agent_runner_help,
    inject_runtime_ca_bundle,
    no_window_creationflags,
)
from operate.services.service import Service

PRESTART_CHECK_COMMAND = "prestart-check"
PRESTART_CHECK_TIMEOUT = 120  # seconds, the one-file binary's unpack included
# The exit code the agent runner uses for each outcome of its checks.
EXIT_CODE_STATUS = {0: PrestartCheckStatus.PASSED, 1: PrestartCheckStatus.FAILED}

logger = setup_logger(name="operate.prestart_check")


class PrestartCheckError(Exception):
    """The prestart check could not complete."""


def _result(
    status: PrestartCheckStatus, issues: t.Optional[t.List[AgentIssue]] = None
) -> PrestartCheckResult:
    return PrestartCheckResult(status=status, issues=issues or [])


def _service_env(service: Service) -> t.Dict[str, str]:
    """Return the environment the agent is started with, as far as its checks need it."""
    env = {
        **os.environ,
        **{
            name: str(attributes.get("value", ""))
            for name, attributes in service.env_variables.items()
        },
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf8",
    }
    return inject_runtime_ca_bundle(env)


def _parse_output(returncode: int, stdout: bytes) -> PrestartCheckResult:
    """Parse what the agent runner's prestart check printed.

    :raises PrestartCheckError: when the exit code or the output is not the contract's.
    """
    status = EXIT_CODE_STATUS.get(returncode)
    if status is None:
        raise PrestartCheckError(f"exited with code {returncode}")
    try:
        output = json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError as e:
        raise PrestartCheckError(f"printed no JSON result: {e}") from e
    if (
        not isinstance(output, dict)
        or output.get("status") != status.value
        or not isinstance(output.get("issues"), list)
    ):
        raise PrestartCheckError(f"printed {output!r} with exit code {returncode}")
    issues = output["issues"]
    if status == PrestartCheckStatus.PASSED:
        return _result(status)
    if not issues or not all(_is_issue(issue) for issue in issues):
        raise PrestartCheckError(f"failed without valid issues: {issues!r}")
    return _result(
        status,
        [
            AgentIssue(
                code=issue["code"],
                title=issue["title"],
                description=issue["description"],
            )
            for issue in issues
        ],
    )


def _is_issue(issue: t.Any) -> bool:
    return isinstance(issue, dict) and all(
        isinstance(issue.get(key), str) for key in ("code", "title", "description")
    )


def run_prestart_check(service: Service) -> PrestartCheckResult:
    """Run the agent runner's ``prestart-check`` command for a service.

    Never raises: anything that keeps the check from completing is an ``error``.
    """
    if service.agent_release["is_aea"]:
        return _result(PrestartCheckStatus.NOT_SUPPORTED)
    try:
        binary = get_agent_runner_path(service_dir=service.path)
        help_output = agent_runner_help(
            binary=binary, timeout=BaseDeploymentRunner.PASSWORD_STDIN_PROBE_TIMEOUT
        ).stdout.decode(errors="replace")
        if PRESTART_CHECK_COMMAND not in help_output:
            logger.info(f"Agent runner {binary} has no {PRESTART_CHECK_COMMAND}")
            return _result(PrestartCheckStatus.NOT_SUPPORTED)
        process = subprocess.run(  # nosec
            [
                binary,
                PRESTART_CHECK_COMMAND,
                "--service-dir",
                str(service.package_absolute_path),
            ],
            cwd=service.path,
            env=_service_env(service),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PRESTART_CHECK_TIMEOUT,
            check=False,
            creationflags=no_window_creationflags(),
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(
            f"Prestart check of {service.service_config_id} could not run: {e!r}"
        )
        return _result(PrestartCheckStatus.ERROR)
    try:
        result = _parse_output(process.returncode, process.stdout)
    except PrestartCheckError as e:
        stderr = process.stderr.decode(errors="replace")[-1000:]
        logger.error(
            f"Prestart check of {service.service_config_id} {e}; stderr: {stderr}"
        )
        return _result(PrestartCheckStatus.ERROR)
    logger.info(
        f"Prestart check of {service.service_config_id}: {result['status'].value}"
    )
    return result
