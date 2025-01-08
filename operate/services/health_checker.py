from traceback import print_exc
from aea.helpers.logging import setup_logger
from operate.constants import HEALTH_CHECK_URL, HTTP_OK


import asyncio
from concurrent.futures import ThreadPoolExecutor
import typing as t
from pathlib import Path
import aiohttp


class HealtChecker:
    SLEEP_PERIOD_DEFAULT = 30
    PORT_UP_TIMEOUT_DEFAULT = 120  # seconds
    NUMBER_OF_FAILS_DEFAULT = 10
    HEALTH_CHECK_URL = HEALTH_CHECK_URL
    EVENT_LOOP = None

    def __init__(
        self,
        deployment_dir: Path,
        restart_method: t.Callable,
        port_up_timeout: int | None = None,
        sleep_period: int | None = None,
        number_of_fails: int | None = None,
    ):
        self.deployment_dir = deployment_dir
        self._restart_method = restart_method
        self.logger = setup_logger(name="operate.deployment_runner")
        self.port_up_timeout = port_up_timeout or self.PORT_UP_TIMEOUT_DEFAULT
        self.sleep_period = sleep_period or self.SLEEP_PERIOD_DEFAULT
        self.number_of_fails = number_of_fails or self.NUMBER_OF_FAILS_DEFAULT
        self._task = None

    def _set_task(self):
        try:
            print("TASK SET")
            self.logger.info("[HEALTHCHECKER] set task called")
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(self._healthchecker_loop())
            self.logger.info("[HEALTHCHECKER] task created")
        except Exception as e:
            print(1111111111, e)
            print_exc()

    def start(self):
        self.logger.info("[HEALTHCHECKER] start called")
        if self._task:
            raise ValueError("aready running")
        loop: asyncio.BaseEventLoop = self.EVENT_LOOP
        assert loop
        loop.call_soon_threadsafe(callback=self._set_task)

    @classmethod
    async def _check_service_health(cls) -> bool:
        """Check the service health"""
        async with aiohttp.ClientSession() as session:
            async with session.get(cls.HEALTH_CHECK_URL) as resp:
                status = resp.status
                response_json = await resp.json()
                return status == HTTP_OK and response_json.get(
                    "is_transitioning_fast", False
                )

    async def _wait_for_port(self) -> None:
        self.logger.info("[HEALTH_CHECKER]: wait port is up")
        while True:
            try:
                await self._check_service_health()
                self.logger.info("[HEALTH_CHECKER]: port is UP")
                return
            except aiohttp.ClientConnectionError:
                self.logger.error("[HEALTH_CHECKER]: error connecting http port")
            await asyncio.sleep(5)

    async def _check_health_in_loop(
        self,
    ) -> None:
        fails = 0
        while True:
            try:
                # Check the service health
                healthy = await self._check_service_health()
            except aiohttp.ClientConnectionError as e:
                print_exc()
                self.logger.warning(
                    f"[HEALTH_CHECKER] port read failed. assume not healthy {e}"
                )
                healthy = False

            if not healthy:
                fails += 1
                self.logger.warning(
                    f"[HEALTH_CHECKER] not healthy for {fails} time in a row"
                )
            else:
                self.logger.info(f"[HEALTH_CHECKER] is HEALTHY")
                # reset fails if comes healty
                fails = 0

            if fails >= self.number_of_fails:
                # too much fails, exit
                self.logger.error(
                    f"[HEALTH_CHECKER]  failed {fails} times in a row. restart"
                )
                return

            await asyncio.sleep(self.sleep_period)

    async def _check_port_ready(
        self,
    ) -> bool:
        try:
            await asyncio.wait_for(self._wait_for_port(), timeout=self.port_up_timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _perform_restart(self) -> None:
        def _do_restart() -> None:
            self._restart_method()

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            future = loop.run_in_executor(executor, _do_restart)
            await future
            exception = future.exception()
            if exception is not None:
                raise exception

    async def _healthchecker_loop(self):
        """Start a background health check job."""

        try:
            self.logger.info(f"[HEALTH_CHECKER] Start healthcheck job for service")

            # upper cycle
            while True:
                self.logger.info(f"[HEALTH_CHECKER] wait for port ready")
                if await self._check_port_ready():
                    # blocking till restart needed
                    self.logger.info(
                        f"[HEALTH_CHECKER] port is ready, checking health every {self.sleep_period}"
                    )
                    await self._check_health_in_loop()

                else:
                    self.logger.info(
                        "[HEALTH_CHECKER] port not ready within timeout. restart deployment"
                    )

                # perform restart
                # TODO: blocking!!!!!!!
                await self._perform_restart()
        except Exception:
            self.logger.exception(f"problems running healthcheckr")
            raise

    def stop(self):
        if not self._task:
            return

        if not self._task.done():
            self.EVENT_LOOP.call_soon_threadsafe(callback=self._task.cancel)
        self._task = None
