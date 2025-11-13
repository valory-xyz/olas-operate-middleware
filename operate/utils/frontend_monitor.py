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

"""Frontend monitoring module for detecting Electron/Next.js death."""

import asyncio
import logging
import os
import typing as t
from contextlib import suppress
from datetime import datetime

try:
    import httpx
except ImportError:
    httpx = None


logger = logging.getLogger("frontend_monitor")


class FrontendMonitor:
    """Monitors Next.js frontend availability as proxy for Electron health.
    
    When Next.js stops responding, it means Electron has crashed or been closed.
    This is more reliable than heartbeat for user-facing applications that may
    go into sleep mode for extended periods.
    """

    def __init__(
        self,
        url: str = "http://localhost:3000",
        timeout_seconds: int = 30,
        check_interval: int = 5,
        enabled: bool = True,
    ) -> None:
        """
        Initialize the FrontendMonitor.

        :param url: URL of the Next.js frontend to monitor
        :param timeout_seconds: Seconds without response before triggering shutdown
        :param check_interval: How often to check frontend (in seconds)
        :param enabled: Whether monitoring is enabled (can be disabled for testing)
        """
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.check_interval = check_interval
        self.enabled = enabled
        self.last_successful_check: t.Optional[datetime] = None
        self._task: t.Optional[asyncio.Task] = None
        self._stopping = False
        self._shutdown_callback: t.Optional[t.Callable] = None

        if httpx is None:
            logger.warning(
                "httpx not installed, frontend monitoring will be disabled. "
                "Install with: pip install httpx"
            )
            self.enabled = False

    async def check_frontend(self) -> bool:
        """Check if Next.js frontend is responding."""
        if httpx is None:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.url, timeout=5.0)
                # Any response (200, 304, 404, etc.) means frontend is alive
                # We don't care about the status code, just that it responds
                self.last_successful_check = datetime.now()
                logger.debug(
                    f"Frontend check OK (status: {response.status_code})"
                )
                return True
        except Exception as e:
            logger.debug(f"Frontend check failed: {e}")
            return False

    def get_time_since_last_check(self) -> t.Optional[float]:
        """Get seconds since last successful check, or None if no check yet."""
        if self.last_successful_check is None:
            return None
        return (datetime.now() - self.last_successful_check).total_seconds()

    async def _monitor_loop(self) -> None:
        """Continuously monitor frontend and invoke shutdown callback when timeout occurs."""
        try:
            # Give time for first successful check after startup
            logger.info(
                f"Frontend monitor starting (timeout: {self.timeout_seconds}s, "
                f"check interval: {self.check_interval}s, url: {self.url})"
            )
            await asyncio.sleep(self.timeout_seconds)

            while not self._stopping:
                is_alive = await self.check_frontend()

                if not is_alive:
                    if self.last_successful_check is None:
                        logger.debug("No successful frontend check yet, waiting...")
                    else:
                        time_since_last = (
                            datetime.now() - self.last_successful_check
                        ).total_seconds()

                        if time_since_last > self.timeout_seconds:
                            logger.error(
                                f"❌ FRONTEND TIMEOUT: Next.js not responding for "
                                f"{time_since_last:.1f} seconds (timeout: {self.timeout_seconds}s)"
                            )
                            logger.error(
                                "Assuming Electron is dead or crashed. Initiating graceful shutdown..."
                            )

                            if self._shutdown_callback:
                                await self._shutdown_callback()
                            break

                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info("Frontend monitor task cancelled")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Frontend monitor crashed unexpectedly")
        finally:
            logger.info("Frontend monitor stopped")

    def start(
        self,
        shutdown_callback: t.Callable[[], t.Awaitable[None]],
        loop: t.Optional[asyncio.AbstractEventLoop] = None,
    ) -> t.Optional[asyncio.Task]:
        """
        Start monitoring frontend.

        :param shutdown_callback: Async function to call when timeout occurs
        :param loop: Event loop to use (defaults to current running loop)
        :return: The monitoring task, or None if disabled
        """
        if not self.enabled:
            logger.info("Frontend monitor is disabled")
            return None

        if httpx is None:
            logger.warning("Frontend monitor disabled: httpx not installed")
            return None

        if self._task:
            logger.warning("Frontend monitor already running")
            return self._task

        self._shutdown_callback = shutdown_callback
        loop = loop or asyncio.get_running_loop()
        self._task = loop.create_task(self._monitor_loop())
        logger.info("Frontend monitor started successfully")
        return self._task

    async def stop(self) -> None:
        """Stop the frontend monitor."""
        self._stopping = True
        if self._task:
            with suppress(Exception):
                self._task.cancel()
                await self._task
            self._task = None
        logger.info("Frontend monitor stopped")

    @property
    def is_running(self) -> bool:
        """Check if monitor is currently running."""
        return self._task is not None and not self._task.done()

    def get_status(self) -> t.Dict[str, t.Any]:
        """Get current status of the frontend monitor."""
        time_since_last = self.get_time_since_last_check()
        return {
            "enabled": self.enabled,
            "running": self.is_running,
            "url": self.url,
            "timeout_seconds": self.timeout_seconds,
            "check_interval": self.check_interval,
            "last_successful_check": (
                self.last_successful_check.isoformat()
                if self.last_successful_check
                else None
            ),
            "seconds_since_last_check": time_since_last,
            "status": (
                "ok"
                if time_since_last is None
                or time_since_last < self.timeout_seconds
                else "timeout"
            ),
        }


def create_frontend_monitor_from_env() -> FrontendMonitor:
    """Create FrontendMonitor instance from environment variables."""
    url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    timeout = int(os.environ.get("FRONTEND_TIMEOUT", "30"))
    check_interval = int(os.environ.get("FRONTEND_CHECK_INTERVAL", "5"))
    enabled = os.environ.get("FRONTEND_MONITOR_ENABLED", "true").lower() == "true"

    return FrontendMonitor(
        url=url,
        timeout_seconds=timeout,
        check_interval=check_interval,
        enabled=enabled,
    )
