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
from io import TextIOWrapper
from pathlib import Path
from traceback import print_exc
from typing import Any, Dict, List
from venv import main as venv_cli
from aea.helpers.logging import setup_logger

import psutil
import requests
from aea.__version__ import __version__ as aea_version
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
        print("Running aea command: ", cmd, " at ", str(cwd))
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
            print_exc()
            raise

    @staticmethod
    def _run_cmd(args: t.List[str], cwd: t.Optional[Path] = None) -> None:
        """Run command in a subprocess."""
        print(f"Running: {' '.join(args)}")
        print(f"Working dir: {os.getcwd()}")
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
        # Patch for trader agent
        if "SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_STORE_PATH" in env:
            data_dir = working_dir / "data"
            data_dir.mkdir(exist_ok=True)
            env["SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_STORE_PATH"] = str(data_dir)

        # TODO: Dynamic port allocation, backport to service builder
        env["CONNECTION_ABCI_CONFIG_HOST"] = "localhost"
        env["CONNECTION_ABCI_CONFIG_PORT"] = "26658"
        env["PYTHONUTF8"] = "1"
        for var in env:
            # Fix tendermint connection params
            if var.endswith("MODELS_PARAMS_ARGS_TENDERMINT_COM_URL"):
                env[var] = self.TM_CONTROL_URL

            if var.endswith("MODELS_PARAMS_ARGS_TENDERMINT_URL"):
                env[var] = "http://localhost:26657"

            if var.endswith("MODELS_PARAMS_ARGS_TENDERMINT_P2P_URL"):
                env[var] = "localhost:26656"

            if var.endswith("MODELS_BENCHMARK_TOOL_ARGS_LOG_DIR"):
                benchmarks_dir = working_dir / "benchmarks"
                benchmarks_dir.mkdir(exist_ok=True, parents=True)
                env[var] = str(benchmarks_dir.resolve())

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

        self._run_aea_command(
            "-s", "fetch", env["AEA_AGENT"], "--alias", "agent", cwd=working_dir
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
        for i in range(self.START_TRIES):
            try:
                self._start()
                return
            except Exception as e:
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
            print(f"No Tendermint process listening on {self._get_tm_exit_url()}.")
        except Exception:  # pylint: disable=broad-except
            print_exc()

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


def _get_host_deployment_runner(build_dir: Path) -> BaseDeploymentRunner:
    """Return depoyment runner according to running env."""
    deployment_runner: BaseDeploymentRunner

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # pyinstaller inside!
        if platform.system() == "Darwin":
            deployment_runner = PyInstallerHostDeploymentRunnerMac(build_dir)
        elif platform.system() == "Windows":
            deployment_runner = PyInstallerHostDeploymentRunnerWindows(build_dir)
        else:
            raise ValueError(f"Platform not supported {platform.system()}")
    else:
        deployment_runner = HostPythonHostDeploymentRunner(build_dir)
    return deployment_runner


def run_host_deployment(build_dir: Path) -> None:
    """Run host deployment."""
    deployment_runner = _get_host_deployment_runner(build_dir=build_dir)
    deployment_runner.start()


def stop_host_deployment(build_dir: Path) -> None:
    """Stop host deployment."""
    deployment_runner = _get_host_deployment_runner(build_dir=build_dir)
    deployment_runner.stop()
