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

"""Utility module for enforcing single-instance application behavior and monitoring parent process."""

import asyncio
import logging
import os
import socket
import time
from contextlib import suppress
from typing import Callable, Optional

import psutil
import requests


class AppSingleInstance:
    """Ensure that only one instance of an application is running."""

    host = "127.0.0.1"
    after_kill_sleep_time = 1
    proc_kill_wait_timeout = 3
    proc_terminate_wait_timeout = 3
    http_request_timeout = 1

    def __init__(self, port_number: int, shutdown_endpoint: str = "/shutdown") -> None:
        """Initialize the AppSingleInstance manager."""
        self.port_number = port_number
        self.shutdown_endpoint = shutdown_endpoint
        self.logger = logging.getLogger("app_single_instance")
        self.logger.setLevel(logging.DEBUG)

    @staticmethod
    def is_port_in_use(port: int) -> bool:
        """Return True if a given TCP port is currently in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    def shutdown_previous_instance(self) -> None:
        """Attempt to stop a previously running instance of the application."""
        if not self.is_port_in_use(self.port_number):
            self.logger.info(f"Port {self.port_number} is free. All good.")
            return

        self.logger.warning(f"Port {self.port_number} is in use. Trying to free it!")
        self.logger.warning(
            f"Trying to stop previous instance via shutdown endpoint: {self.shutdown_endpoint}"
        )
        self.try_shutdown_with_endpoint()

        if not self.is_port_in_use(self.port_number):
            self.logger.info(f"Port {self.port_number} is free. All good.")
            return

        self.logger.warning(
            f"Trying to stop previous instance by killing process using port {self.port_number}"
        )
        self.try_kill_proc_using_port()

        if not self.is_port_in_use(self.port_number):
            self.logger.info(f"Port {self.port_number} is free. All good.")
            return

        self.logger.error(f"Port {self.port_number} still in use. Cannot continue.")
        raise RuntimeError(f"Port {self.port_number} is in use, cannot continue!")

    def try_shutdown_with_endpoint(self) -> None:
        """Attempt to gracefully shut down the previous instance via HTTP or HTTPS."""
        try:
            self.logger.warning(
                "Attempting to stop previous instance via HTTPS shutdown endpoint."
            )
            requests.get(
                f"https://{self.host}:{self.port_number}{self.shutdown_endpoint}",
                timeout=self.http_request_timeout,
                verify=False,  # nosec
            )
            time.sleep(self.after_kill_sleep_time)
        except requests.exceptions.SSLError:
            self.logger.warning("HTTPS shutdown failed, retrying without SSL.")
            try:
                requests.get(
                    f"http://{self.host}:{self.port_number}{self.shutdown_endpoint}",
                    timeout=self.http_request_timeout,
                )
                time.sleep(self.after_kill_sleep_time)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error(
                    f"Failed to stop previous instance (HTTP). Error: {e}"
                )
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(f"Failed to stop previous instance (HTTPS). Error: {e}")

    def try_kill_proc_using_port(self) -> None:
        """Attempt to forcibly terminate the process occupying the target port."""
        for conn in psutil.net_connections(kind="tcp"):
            if (
                conn.laddr.port == self.port_number
                and conn.status == psutil.CONN_LISTEN
            ):
                if conn.pid is None:
                    self.logger.info(
                        f"Process using port {self.port_number} found but PID is None. Cannot continue."
                    )
                    return
                self.logger.info(
                    f"Process using port {self.port_number} found (PID={conn.pid}). Terminating..."
                )
                try:
                    self.kill_process_tree(conn.pid)
                    time.sleep(self.after_kill_sleep_time)
                    return
                except Exception as e:  # pylint: disable=broad-except
                    self.logger.error(f"Error stopping process {conn.pid}: {e}")
        self.logger.info(f"No process found using port {self.port_number}.")

    def kill_process_tree(self, pid: int) -> None:
        """Terminate a process and all its child processes."""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)

            for child in children:
                with suppress(psutil.NoSuchProcess):
                    child.terminate()

            _, still_alive = psutil.wait_procs(
                children, timeout=self.proc_terminate_wait_timeout
            )

            for child in still_alive:
                with suppress(psutil.NoSuchProcess):
                    child.kill()

            parent.terminate()
            try:
                parent.wait(timeout=self.proc_terminate_wait_timeout)
            except psutil.TimeoutExpired:
                parent.kill()
                parent.wait(timeout=self.proc_kill_wait_timeout)

        except psutil.NoSuchProcess:
            self.logger.info(f"Process {pid} already terminated.")
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(f"Error killing process {pid}: {e}")


logger = logging.getLogger("parent_watchdog")


class ParentWatchdog:
    """Monitor the parent process and trigger a shutdown when it exits."""

    def __init__(
        self, on_parent_exit: Callable[[], asyncio.Future], check_interval: int = 3
    ) -> None:
        """Initialize the ParentWatchdog."""
        self.on_parent_exit = on_parent_exit
        self.check_interval = check_interval
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    async def _watch_loop(self) -> None:
        """Continuously monitor the parent process and invoke the shutdown callback when it exits."""
        try:
            own_pid = os.getpid()
            logger.info(f"ParentWatchdog started (pid={own_pid}, ppid={os.getppid()})")

            while not self._stopping:
                try:
                    parent = psutil.Process(os.getppid())
                    if not parent.is_running() or os.getppid() == 1:
                        logger.warning(
                            "Parent process no longer alive, initiating shutdown."
                        )
                        await self.on_parent_exit()
                        break
                except psutil.NoSuchProcess:
                    logger.warning("Parent process not found, initiating shutdown.")
                    await self.on_parent_exit()
                    break
                except Exception:  # pylint: disable=broad-except
                    logger.exception("Parent check iteration failed.")
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info("ParentWatchdog task cancelled.")
        except Exception:  # pylint: disable=broad-except
            logger.exception("ParentWatchdog crashed unexpectedly.")
        finally:
            logger.info("ParentWatchdog stopped.")

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> asyncio.Task:
        """Start monitoring the parent process."""
        if self._task:
            logger.warning("ParentWatchdog already running.")
            return self._task
        loop = loop or asyncio.get_running_loop()
        self._task = loop.create_task(self._watch_loop())
        return self._task

    async def stop(self) -> None:
        """Stop the parent process watchdog."""
        self._stopping = True
        if self._task:
            with suppress(Exception):
                self._task.cancel()
                await self._task
            self._task = None
