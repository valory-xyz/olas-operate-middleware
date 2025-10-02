#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
"""Source code to run and stop deployments created."""
import ctypes
import json
import multiprocessing
import os
import platform
import shutil  # nosec
import subprocess  # nosec
import sys  # nosec
import time
import typing as t
from abc import ABC, ABCMeta, abstractmethod
from contextlib import suppress
from enum import Enum
from io import TextIOWrapper
from pathlib import Path
from traceback import print_exc
from typing import Any, Dict, List, Type
from venv import main as venv_cli

import psutil
import requests
from aea.__version__ import __version__ as aea_version
from aea.helpers.logging import setup_logger
from autonomy.__version__ import __version__ as autonomy_version

from operate import constants

from .agent_runner import get_agent_runner_path


class AbstractDeploymentRunner(ABC):
    """Abstract deployment runner."""

    def __init__(self, work_directory: Path) -> None:
        """Init the deployment runner."""
        self._work_directory = work_directory

    @abstractmethod
    def start(self) -> None:
        """Start the deployment."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the deployment."""


def _kill_process(pid: int) -> None:
    """Kill process."""
    while True:
        if not psutil.pid_exists(pid=pid):
            return
        process = psutil.Process(pid=pid)
        if process.status() in (
            psutil.STATUS_DEAD,
            psutil.STATUS_ZOMBIE,
        ):
            return
        try:
            process.kill()
        except OSError:
            return
        except psutil.AccessDenied:
            return
        time.sleep(1)


def kill_process(pid: int) -> None:
    """Kill the process and all children first."""
    if not psutil.pid_exists(pid=pid):
        return
    current_process = psutil.Process(pid=pid)
    children = list(reversed(current_process.children(recursive=True)))
    for child in children:
        _kill_process(child.pid)
        _kill_process(child.pid)
    _kill_process(pid)
    _kill_process(pid)


class BaseDeploymentRunner(AbstractDeploymentRunner, metaclass=ABCMeta):
    """Base deployment with aea support."""

    TM_CONTROL_URL = constants.TM_CONTROL_URL
    SLEEP_BEFORE_TM_KILL = 2  # seconds
    START_TRIES = constants.DEPLOYMENT_START_TRIES_NUM
    logger = setup_logger(name="operate.base_deployment_runner")

    def _open_agent_runner_log_file(self) -> TextIOWrapper:
        """Open agent_runner.log file."""
        return (
            Path(self._work_directory).parent.parent.parent / "agent_runner.log"
        ).open("w+")

    def _run_aea_command(self, *args: str, cwd: Path) -> Any:
        """Run aea command."""
        cmd = " ".join(args)
        self.logger.info(f"Running aea command: {cmd} at {str(cwd)}")
        p = multiprocessing.Process(
            target=self.__class__._call_aea_command,  # pylint: disable=protected-access
            args=(cwd, args),
        )
        p.start()
        p.join()
        if p.exitcode != 0:
            raise RuntimeError(
                f"aea command `{cmd}`execution failed with exit code: {p.exitcode}"
            )

    @staticmethod
    def _call_aea_command(cwd: str | Path, args: List[str]) -> None:
        try:
            import os  # pylint: disable=redefined-outer-name,reimported,import-outside-toplevel

            os.chdir(cwd)
            # pylint: disable-next=import-outside-toplevel
            from aea.cli.core import cli as call_aea

            call_aea(  # pylint: disable=unexpected-keyword-arg, no-value-for-parameter
                args, standalone_mode=False
            )
        except Exception:
            print(f"Error on calling aea command: {args}")
            print_exc()
            raise

    def _run_cmd(self, args: t.List[str], cwd: t.Optional[Path] = None) -> None:
        """Run command in a subprocess."""
        self.logger.info(f"Running: {' '.join(args)}")
        self.logger.info(f"Working dir: {os.getcwd()}")
        result = subprocess.run(  # pylint: disable=subprocess-run-check # nosec
            args=args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Error running: {args} @ {cwd}\n{result.stderr.decode()}"
            )

    def _prepare_agent_env(self) -> Any:
        """Prepare agent env, add keys, run aea commands."""
        working_dir = self._work_directory
        env = json.loads((working_dir / "agent.json").read_text(encoding="utf-8"))

        # TODO: Dynamic port allocation, backport to service builder
        env["PYTHONUTF8"] = "1"
        for var in env:
            # Fix tendermint connection params
            if var.endswith("MODELS_PARAMS_ARGS_TENDERMINT_COM_URL"):
                env[var] = self.TM_CONTROL_URL

            if var.endswith("MODELS_PARAMS_ARGS_TENDERMINT_URL"):
                env[var] = "http://localhost:26657"

            if var.endswith("MODELS_PARAMS_ARGS_TENDERMINT_P2P_URL"):
                env[var] = "localhost:26656"

        (working_dir / "agent.json").write_text(
            json.dumps(env, indent=4),
            encoding="utf-8",
        )
        return env

    def _setup_agent(self) -> None:
        """Setup agent."""
        working_dir = self._work_directory
        env = self._prepare_agent_env()

        self._run_aea_command(
            "init",
            "--reset",
            "--author",
            "valory",
            "--remote",
            "--ipfs",
            "--ipfs-node",
            "/dns/registry.autonolas.tech/tcp/443/https",
            cwd=working_dir,
        )

        agent_alias_name = "agent"

        agent_dir_full_path = Path(working_dir) / agent_alias_name

        if agent_dir_full_path.exists():
            # remove if exists before fetching! can have issues with retry mechanism of multiple start attempts
            with suppress(Exception):
                shutil.rmtree(agent_dir_full_path, ignore_errors=True)

        self._run_aea_command(
            "-s",
            "fetch",
            env["AEA_AGENT"],
            "--alias",
            agent_alias_name,
            cwd=working_dir,
        )

        # Add keys
        shutil.copy(
            working_dir / "ethereum_private_key.txt",
            working_dir / "agent" / "ethereum_private_key.txt",
        )

        self._run_aea_command("-s", "add-key", "ethereum", cwd=working_dir / "agent")

        self._run_aea_command("-s", "issue-certificates", cwd=working_dir / "agent")

    def start(self) -> None:
        """Start the deployment with retries."""
        for _ in range(self.START_TRIES):
            try:
                self._start()
                return
            except Exception as e:  # pylint: disable=broad-except
                self.logger.exception(f"Error on starting deployment: {e}")
        raise RuntimeError(
            f"Failed to start the deployment after {self.START_TRIES} attempts! Check logs"
        )

    def _start(self) -> None:
        """Start the deployment."""
        self._setup_agent()
        self._start_tendermint()
        self._start_agent()

    def stop(self) -> None:
        """Stop the deployment."""
        self._stop_agent()
        self._stop_tendermint()

    def _stop_agent(self) -> None:
        """Start process."""
        pid = self._work_directory / "agent.pid"
        if not pid.exists():
            return
        kill_process(int(pid.read_text(encoding="utf-8")))

    def _get_tm_exit_url(self) -> str:
        return f"{self.TM_CONTROL_URL}/exit"

    def _stop_tendermint(self) -> None:
        """Stop tendermint process."""
        try:
            requests.get(self._get_tm_exit_url(), timeout=(1, 10))
            time.sleep(self.SLEEP_BEFORE_TM_KILL)
        except requests.ConnectionError:
            self.logger.error(
                f"No Tendermint process listening on {self._get_tm_exit_url()}."
            )
        except Exception:  # pylint: disable=broad-except
            self.logger.exception("Exception on tendermint stop!")

        pid = self._work_directory / "tendermint.pid"
        if not pid.exists():
            return
        kill_process(int(pid.read_text(encoding="utf-8")))

    @abstractmethod
    def _start_tendermint(self) -> None:
        """Start tendermint  process."""

    @abstractmethod
    def _start_agent(self) -> None:
        """Start aea process."""

    @property
    @abstractmethod
    def _agent_runner_bin(self) -> str:
        """Return aea_bin path."""
        raise NotImplementedError


class PyInstallerHostDeploymentRunner(BaseDeploymentRunner):
    """Deployment runner within pyinstaller env."""

    @property
    def _agent_runner_bin(self) -> str:
        """Return aea_bin path."""
        env = json.loads(
            (self._work_directory / "agent.json").read_text(encoding="utf-8")
        )

        agent_publicid_str = env["AEA_AGENT"]
        service_dir = self._work_directory.parent

        agent_runner_bin = get_agent_runner_path(
            service_dir=service_dir, agent_public_id_str=agent_publicid_str
        )
        return str(agent_runner_bin)

    @property
    def _tendermint_bin(self) -> str:
        """Return tendermint path."""
        return str(Path(os.path.dirname(sys.executable)) / "tendermint_bin")  # type: ignore # pylint: disable=protected-access

    def _start_agent(self) -> None:
        """Start agent process."""
        working_dir = self._work_directory
        env = json.loads((working_dir / "agent.json").read_text(encoding="utf-8"))
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf8"
        env = {**os.environ, **env}

        process = self._start_agent_process(env=env, working_dir=working_dir)
        (working_dir / "agent.pid").write_text(
            data=str(process.pid),
            encoding="utf-8",
        )

    def _start_agent_process(self, env: Dict, working_dir: Path) -> subprocess.Popen:
        """Start agent process."""
        raise NotImplementedError

    def _start_tendermint(self) -> None:
        """Start tendermint process."""
        working_dir = self._work_directory
        env = json.loads((working_dir / "tendermint.json").read_text(encoding="utf-8"))
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf8"

        env = {
            **os.environ,
            **env,
        }

        process = self._start_tendermint_process(env=env, working_dir=working_dir)

        (working_dir / "tendermint.pid").write_text(
            data=str(process.pid),
            encoding="utf-8",
        )

    def _start_tendermint_process(
        self, env: Dict, working_dir: Path
    ) -> subprocess.Popen:
        raise NotImplementedError


class PyInstallerHostDeploymentRunnerMac(PyInstallerHostDeploymentRunner):
    """Mac deployment runner."""

    def _start_agent_process(self, env: Dict, working_dir: Path) -> subprocess.Popen:
        """Start agent process."""
        agent_runner_log_file = self._open_agent_runner_log_file()
        process = subprocess.Popen(  # pylint: disable=consider-using-with,subprocess-popen-preexec-fn # nosec
            args=[
                self._agent_runner_bin,
                "-s",
                "run",
            ],
            cwd=working_dir / "agent",
            stdout=agent_runner_log_file,
            stderr=agent_runner_log_file,
            env=env,
            preexec_fn=os.setpgrp,
        )
        return process

    def _start_tendermint_process(
        self, env: Dict, working_dir: Path
    ) -> subprocess.Popen:
        """Start tendermint process."""
        env = {
            **env,
        }
        env["PATH"] = os.path.dirname(sys.executable) + ":" + os.environ["PATH"]

        process = subprocess.Popen(  # pylint: disable=consider-using-with,subprocess-popen-preexec-fn # nosec
            args=[self._tendermint_bin],
            cwd=working_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            preexec_fn=os.setpgrp,  # pylint: disable=subprocess-popen-preexec-fn # nosec
        )
        return process


class PyInstallerHostDeploymentRunnerWindows(PyInstallerHostDeploymentRunner):
    """Windows deployment runner."""

    def __init__(self, work_directory: Path) -> None:
        """Init the runner."""
        super().__init__(work_directory)
        self._job = self.set_windows_object_job()

    @staticmethod
    def set_windows_object_job() -> Any:
        """Set windows job object to handle sub processes."""
        from ctypes import (  # type: ignore # pylint:disable=import-outside-toplevel,reimported
            wintypes,
        )

        kernel32 = ctypes.windll.kernel32  # type: ignore

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(
            ctypes.Structure
        ):  # pylint: disable=missing-class-docstring
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(wintypes.ULONG)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):  # pylint: disable=missing-class-docstring
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(
            ctypes.Structure
        ):  # pylint: disable=missing-class-docstring
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        # Создаем Job Object
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError()  # type: ignore

        # Настраиваем автоматическое завершение процессов при закрытии Job
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )

        if not kernel32.SetInformationJobObject(
            job,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(job)
            raise ctypes.WinError()  # type: ignore

        return job

    def assign_to_job(self, pid: int) -> None:
        """Windows-only: привязывает процесс к Job Object."""
        ctypes.windll.kernel32.AssignProcessToJobObject(self._job, pid)  # type: ignore

    @property
    def _tendermint_bin(self) -> str:
        """Return tendermint path."""
        return str(Path(os.path.dirname(sys.executable)) / "tendermint_win.exe")  # type: ignore # pylint: disable=protected-access

    def _start_agent_process(self, env: Dict, working_dir: Path) -> subprocess.Popen:
        """Start agent process."""
        agent_runner_log_file = self._open_agent_runner_log_file()
        process = subprocess.Popen(  # pylint: disable=consider-using-with # nosec
            args=[
                self._agent_runner_bin,
                "-s",
                "run",
            ],  # TODO: Patch for Windows failing hash
            cwd=working_dir / "agent",
            stdout=agent_runner_log_file,
            stderr=agent_runner_log_file,
            env=env,
            creationflags=0x00000200,  # Detach process from the main process
        )
        self.assign_to_job(process._handle)  # type: ignore # pylint: disable=protected-access
        return process

    def _start_tendermint_process(
        self, env: Dict, working_dir: Path
    ) -> subprocess.Popen:
        """Start tendermint process."""
        env = {
            **env,
        }
        env["PATH"] = os.path.dirname(sys.executable) + ";" + os.environ["PATH"]

        process = subprocess.Popen(  # pylint: disable=consider-using-with # nosec
            args=[self._tendermint_bin],
            cwd=working_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            creationflags=0x00000200,  # Detach process from the main process
        )
        self.assign_to_job(process._handle)  # type: ignore # pylint: disable=protected-access
        return process


class HostPythonHostDeploymentRunner(BaseDeploymentRunner):
    """Deployment runner for host installed python."""

    @property
    def _agent_runner_bin(self) -> str:
        """Return aea_bin path."""
        return str(self._venv_dir / "bin" / "aea")

    def _start_agent(self) -> None:
        """Start agent process."""
        working_dir = self._work_directory
        env = json.loads((working_dir / "agent.json").read_text(encoding="utf-8"))
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf8"
        agent_runner_log_file = self._open_agent_runner_log_file()

        process = subprocess.Popen(  # pylint: disable=consider-using-with # nosec
            args=[
                self._agent_runner_bin,
                "-s",
                "run",
            ],  # TODO: Patch for Windows failing hash
            cwd=str(working_dir / "agent"),
            env={**os.environ, **env},
            stdout=agent_runner_log_file,
            stderr=agent_runner_log_file,
            creationflags=(
                0x00000008 if platform.system() == "Windows" else 0
            ),  # Detach process from the main process
        )
        (working_dir / "agent.pid").write_text(
            data=str(process.pid),
            encoding="utf-8",
        )

    def _start_tendermint(self) -> None:
        """Start tendermint process."""
        working_dir = self._work_directory
        env = json.loads((working_dir / "tendermint.json").read_text(encoding="utf-8"))
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf8"

        process = subprocess.Popen(  # pylint: disable=consider-using-with # nosec
            args=[
                str(self._venv_dir / "bin" / "flask"),
                "run",
                "--host",
                "localhost",
                "--port",
                "8080",
            ],
            cwd=working_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **env},
            creationflags=(
                0x00000008 if platform.system() == "Windows" else 0
            ),  # Detach process from the main process
        )
        (working_dir / "tendermint.pid").write_text(
            data=str(process.pid),
            encoding="utf-8",
        )

    @property
    def _venv_dir(self) -> Path:
        """Get venv dir for aea."""
        return self._work_directory / "venv"

    def _setup_venv(self) -> None:
        """Perform venv setup, install deps."""
        self._venv_dir.mkdir(exist_ok=True)
        venv_cli(args=[str(self._venv_dir)])
        pbin = str(self._venv_dir / "bin" / "python")
        # Install agent dependencies
        self._run_cmd(
            args=[
                pbin,
                "-m",
                "pip",
                "install",
                f"open-autonomy[all]=={autonomy_version}",
                f"open-aea-ledger-ethereum=={aea_version}",
                f"open-aea-ledger-ethereum-flashbots=={aea_version}",
                f"open-aea-ledger-cosmos=={aea_version}",
                # Install tendermint dependencies
                "flask",
                "requests",
            ],
        )

    def _setup_agent(self) -> None:
        """Prepare agent."""
        multiprocessing.set_start_method("spawn")
        self._setup_venv()
        super()._setup_agent()
        # Install agent dependencies
        self._run_cmd(
            args=[
                self._agent_runner_bin,
                "-v",
                "debug",
                "install",
                "--timeout",
                "600",
            ],
            cwd=self._work_directory / "agent",
        )


class States(Enum):
    """Service deployment states."""

    NONE = 0
    STARTING = 1
    STARTED = 2
    STOPPING = 3
    STOPPED = 4
    ERROR = 5


class DeploymentManager:
    """Deployment manager to run and stop deployments."""

    def __init__(self) -> None:
        """Init the deployment manager."""
        self._deployment_runner_class = self._get_host_deployment_runner_class()
        self._is_stopping = False
        self.logger = setup_logger(name="operate.deployment_manager")
        self._states: Dict[Path, States] = {}

    def _get_deployment_runner(self, build_dir: Path) -> BaseDeploymentRunner:
        """Get deploymnent runner instance."""
        return self._deployment_runner_class(build_dir)

    @staticmethod
    def _get_host_deployment_runner_class() -> Type[BaseDeploymentRunner]:
        """Return depoyment runner class according to running env."""

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # pyinstaller inside!
            if platform.system() == "Darwin":
                return PyInstallerHostDeploymentRunnerMac
            if platform.system() == "Windows":
                return PyInstallerHostDeploymentRunnerWindows
            raise ValueError(f"Platform not supported {platform.system()}")

        return HostPythonHostDeploymentRunner

    def stop(self) -> None:
        """Stop deploment manager."""
        self.logger.info("Stop deployment manager")
        self._is_stopping = True

    def get_state(self, build_dir: Path) -> States:
        """Get state of the deployment."""
        return self._states.get(build_dir) or States.NONE

    def check_ipfs_connection_works(self) -> None:
        """Check ipfs works and there is a good net connection."""
        self.logger.info("Doing network connection check by test call to ipfs server.")
        for i in range(3):
            try:
                requests.get(constants.IPFS_CHECK_URL, timeout=60)
                return
            except OSError:
                self.logger.exception(
                    "failed to connect to ipfs to test connection. OSError, critical!"
                )
                raise
            except Exception:  # pylint: disable=broad-except
                self.logger.exception(
                    "failed to connect to ipfs to test connection. do another try"
                )
                time.sleep(i * 5)
        self.logger.error(
            "failed to connect to ipfs to test connection. no attempts left. raise error"
        )
        raise RuntimeError(
            "Failed to perform test connection to ipfs to check network connection!"
        )

    def run_deployment(self, build_dir: Path) -> None:
        """Run deployment."""
        if self._is_stopping:
            raise RuntimeError("deployment manager stopped")
        if self.get_state(build_dir=build_dir) in [States.STARTING, States.STOPPING]:
            raise ValueError("Service already in transition")

        # doing pre check for ipfs works fine, also network connection is ok.
        self.check_ipfs_connection_works()

        self.logger.info(f"Starting deployment {build_dir}...")
        self._states[build_dir] = States.STARTING
        try:
            deployment_runner = self._get_deployment_runner(build_dir=build_dir)
            deployment_runner.start()
            self.logger.info(f"Started deployment {build_dir}")
            self._states[build_dir] = States.STARTED
        except Exception:  # pylint: disable=broad-except
            self.logger.exception(
                f"Starting deployment failed {build_dir}. so try to stop"
            )
            self._states[build_dir] = States.ERROR
            self.stop_deployemnt(build_dir=build_dir, force=True)

        if self._is_stopping:
            self.logger.warning(
                f"Deployment at {build_dir} started when it was  going to stop, so stop it"
            )
            self.stop_deployemnt(build_dir=build_dir, force=True)

    def stop_deployemnt(self, build_dir: Path, force: bool = False) -> None:
        """Stop the deployment."""
        if (
            self.get_state(build_dir=build_dir) in [States.STARTING, States.STOPPING]
            and not force
        ):
            raise ValueError("Service already in transition")
        self.logger.info(f"Stopping deployment {build_dir}...")
        self._states[build_dir] = States.STOPPING
        deployment_runner = self._get_deployment_runner(build_dir=build_dir)
        try:
            deployment_runner.stop()
            self.logger.info(f"Stopped deployment {build_dir}...")
            self._states[build_dir] = States.STOPPED
        except Exception:
            self.logger.exception(f"Stopping deployment  failed {build_dir}...")
            self._states[build_dir] = States.ERROR
            raise


deployment_manager = DeploymentManager()


def run_host_deployment(build_dir: Path) -> None:
    """Run host deployment."""
    deployment_manager.run_deployment(build_dir=build_dir)


def stop_host_deployment(build_dir: Path) -> None:
    """Stop host deployment."""
    deployment_manager.stop_deployemnt(build_dir=build_dir)


def stop_deployment_manager() -> None:
    """Stop deployment manager."""
    deployment_manager.stop()
