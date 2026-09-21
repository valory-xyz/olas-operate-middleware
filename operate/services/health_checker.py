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
"""Source code for checking aea is alive.."""

import asyncio
import enum
import json
import logging
import threading
import time
import typing as t
from dataclasses import asdict, dataclass
from http import HTTPStatus
from pathlib import Path

import aiohttp  # type: ignore

from operate.constants import (
    AGENT_PID_FILE,
    AGENT_PROCESS_NAMES,
    DEPLOYMENT_DIR,
    HEALTHCHECK_JSON,
    HEALTH_CHECK_URL,
)
from operate.operate_types import StakingReconcileOutcome
from operate.services.manage import ServiceManager  # type: ignore
from operate.utils.pid_file import read_raw_pid, validate_pid


class AgentLivenessReason(str, enum.Enum):
    """Why the agent of a service is not considered alive."""

    AGENT_PROCESS_EXITED = "agent_process_exited"
    AGENT_UNRESPONSIVE = "agent_unresponsive"
    EVICTED_CANNOT_RESTAKE = "evicted_cannot_restake"
    NOT_MONITORED = "not_monitored"


@dataclass
class AgentLiveness:
    """Liveness of a service's agent, as reported on the deployment payload."""

    is_alive: bool = False
    reason: t.Optional[AgentLivenessReason] = AgentLivenessReason.NOT_MONITORED
    last_checked_at: t.Optional[float] = None
    last_healthy_at: t.Optional[float] = None
    consecutive_failures: int = 0
    restarts_since_last_healthy: int = 0

    def mark_healthy(self, probed_at: t.Optional[float] = None) -> None:
        """Mark the agent alive, counting a successful probe if one is given."""
        self.is_alive = True
        self.reason = None
        if probed_at is None:
            return

        self.last_checked_at = probed_at
        self.last_healthy_at = probed_at
        self.consecutive_failures = 0
        self.restarts_since_last_healthy = 0

    def mark_unhealthy(
        self, reason: AgentLivenessReason, probed_at: t.Optional[float] = None
    ) -> None:
        """Mark the agent not alive and why, counting a failed probe if one is given."""
        self.is_alive = False
        self.reason = reason
        if probed_at is None:
            return

        self.last_checked_at = probed_at
        self.consecutive_failures += 1

    def mark_restarted(self) -> None:
        """Count a restart attempted since the agent was last healthy."""
        self.restarts_since_last_healthy += 1

    def json(self) -> t.Dict[str, t.Any]:
        """Serialise for the deployment payload."""
        payload = asdict(self)
        payload["reason"] = None if self.reason is None else self.reason.value
        return payload


class HealthChecker:  # pylint: disable=too-many-instance-attributes
    """Health checker manager."""

    SLEEP_PERIOD_DEFAULT = 5  # seconds
    PORT_UP_TIMEOUT_DEFAULT = 300  # seconds
    REQUEST_TIMEOUT_DEFAULT = 90  # seconds
    NUMBER_OF_FAILS_DEFAULT = 60
    FAILFAST_NUM = 15
    FAILFAST_TIMEOUT = 15 * 60  # 15 minutes

    def __init__(
        self,
        service_manager: ServiceManager,
        logger: logging.Logger,
        port_up_timeout: int | None = None,
        sleep_period: int | None = None,
        number_of_fails: int | None = None,
    ) -> None:
        """Init the healtch checker."""
        self._jobs: t.Dict[str, asyncio.Task] = {}
        self._jobs_lock = threading.Lock()  # Protect _jobs dict operations
        self._liveness: t.Dict[str, AgentLiveness] = {}
        self._liveness_lock = threading.Lock()  # Protect _liveness dict operations
        self._loop: t.Optional[asyncio.AbstractEventLoop] = None
        self._service_manager = service_manager
        self.logger = logger
        self.port_up_timeout = port_up_timeout or self.PORT_UP_TIMEOUT_DEFAULT
        self.sleep_period = sleep_period or self.SLEEP_PERIOD_DEFAULT
        self.number_of_fails = number_of_fails or self.NUMBER_OF_FAILS_DEFAULT

    def start_for_service(self, service_config_id: str) -> None:
        """Start for a specific service."""
        self.logger.info(
            f"[HEALTH_CHECKER]: Starting healthcheck job for {service_config_id}"
        )
        # A fresh deployment invalidates the previous record, `evicted_cannot_restake` included.
        self.forget_service(service_config_id=service_config_id)

        # Thread-safe job management: check and stop existing job atomically
        with self._jobs_lock:
            if service_config_id in self._jobs:
                # Stop existing job (cancel and clean up)
                old_task = self._jobs[service_config_id]
                old_task.cancel()
                # Remove from dict - task will handle cancellation
                del self._jobs[service_config_id]
                self.logger.info(
                    f"[HEALTH_CHECKER]: Cancelled existing job for {service_config_id}"
                )

            # Create new job
            loop = asyncio.get_running_loop()
            self._loop = loop
            self._jobs[service_config_id] = loop.create_task(
                self.healthcheck_job(
                    service_config_id=service_config_id,
                )
            )

    def stop_for_service(self, service_config_id: str) -> None:
        """Stop for a specific service."""
        # A stopped agent is not alive; only the reason it could not be restarted outlives it.
        self._forget_unless_evicted(service_config_id=service_config_id)

        # Thread-safe job cancellation
        with self._jobs_lock:
            if service_config_id not in self._jobs:
                return

            self.logger.info(
                f"[HEALTH_CHECKER]: Cancelling existing healthcheck_jobs job for {service_config_id}"
            )
            task = self._jobs[service_config_id]
            # Use call_soon_threadsafe so cancellation is safe from any thread
            # (pool workers call this via pause_all_services)
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(task.cancel)
            else:
                status = task.cancel()
                if not status:
                    self.logger.info(
                        f"[HEALTH_CHECKER]: Healthcheck job cancellation for {service_config_id} failed"
                    )
            # Remove from dict - task will handle cancellation
            del self._jobs[service_config_id]

    async def check_service_health(
        self, service_config_id: str, service_path: t.Optional[Path] = None
    ) -> bool:
        """Check the service health and record the outcome on its liveness record."""
        healthy = await self._probe_agent(service_path=service_path)
        if healthy:
            self.record_healthy_probe(service_config_id=service_config_id)
            return True

        # Reads the PID file and asks psutil, so it stays off the event loop.
        agent_is_running = await asyncio.to_thread(
            self._is_agent_process_alive, service_path
        )
        self.record_failed_probe(
            service_config_id=service_config_id,
            reason=(
                AgentLivenessReason.AGENT_UNRESPONSIVE
                if agent_is_running
                else AgentLivenessReason.AGENT_PROCESS_EXITED
            ),
        )
        return False

    async def _probe_agent(  # pylint: disable=too-many-return-statements
        self, service_path: t.Optional[Path] = None
    ) -> bool:
        """Probe the agent HTTP healthcheck endpoint."""
        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT_DEFAULT)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(HEALTH_CHECK_URL) as resp:
                    status = resp.status

                    if status != HTTPStatus.OK:
                        # not HTTP OK -> not healthy for sure
                        content = await resp.text()
                        self.logger.warning(
                            f"[HEALTH_CHECKER] Bad http status code : {status} content: {content}. not healthy!"
                        )
                        return False

                    response_json = await resp.json()

                    if service_path:
                        healthcheck_json_path = service_path / HEALTHCHECK_JSON
                        healthcheck_json_path.write_text(
                            json.dumps(response_json, indent=2), encoding="utf-8"
                        )

                    return response_json.get(
                        "is_healthy", response_json.get("is_transitioning_fast", False)
                    )  # TODO: remove is_transitioning_fast after all the services start reporting is_healthy
        except asyncio.TimeoutError as e:
            # NOTE: Must come before OSError since TimeoutError is a subclass of OSError in Python 3.10+
            self.logger.error(
                f"[HEALTH_CHECKER] Request timeout during health check: {e}. set not healthy!"
            )
            return False
        except aiohttp.ClientError as e:
            self.logger.error(
                f"[HEALTH_CHECKER] HTTP client error during health check: {e}. set not healthy!"
            )
            return False
        except json.JSONDecodeError as e:
            self.logger.error(
                f"[HEALTH_CHECKER] JSON decode error while parsing health check response: {e}. set not healthy!",
                exc_info=True,
            )
            return False
        except (OSError, PermissionError) as e:
            # NOTE: Comes after TimeoutError to avoid catching it (TimeoutError is subclass of OSError)
            self.logger.error(
                f"[HEALTH_CHECKER] File system error while writing healthcheck.json: {e}. set not healthy!",
                exc_info=True,
            )
            return False
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(
                f"[HEALTH_CHECKER] Unexpected error during health check: {e}. set not healthy!",
                exc_info=True,
            )
            return False

    @staticmethod
    def _is_agent_process_alive(service_path: t.Optional[Path]) -> bool:
        """Answer whether the agent process recorded for this service is still live."""
        if service_path is None:
            return False

        pid = read_raw_pid(service_path / DEPLOYMENT_DIR / AGENT_PID_FILE)
        if pid is None:
            return False

        return validate_pid(pid, expected_process_names=AGENT_PROCESS_NAMES)

    def _update_liveness(
        self, service_config_id: str, update: t.Callable[[AgentLiveness], None]
    ) -> None:
        """Apply an update to a service's liveness record, creating it on first use."""
        with self._liveness_lock:
            update(self._liveness.setdefault(service_config_id, AgentLiveness()))

    def record_healthy_probe(self, service_config_id: str) -> None:
        """Record a probe the agent answered."""
        probed_at = time.time()
        self._update_liveness(
            service_config_id, lambda record: record.mark_healthy(probed_at)
        )

    def record_failed_probe(
        self, service_config_id: str, reason: AgentLivenessReason
    ) -> None:
        """Record a probe the agent did not answer, and why."""
        probed_at = time.time()
        self._update_liveness(
            service_config_id,
            lambda record: record.mark_unhealthy(reason, probed_at=probed_at),
        )

    def record_restart(self, service_config_id: str) -> None:
        """Record that a restart was attempted for a service."""
        self._update_liveness(service_config_id, AgentLiveness.mark_restarted)

    def record_reason(
        self, service_config_id: str, reason: AgentLivenessReason
    ) -> None:
        """Record why a service is not alive, without a probe behind it."""
        self._update_liveness(
            service_config_id, lambda record: record.mark_unhealthy(reason)
        )

    def forget_service(self, service_config_id: str) -> None:
        """Drop the liveness record of a service."""
        with self._liveness_lock:
            self._liveness.pop(service_config_id, None)

    def _forget_unless_evicted(self, service_config_id: str) -> None:
        """Drop the liveness record of a service unless it reports an eviction."""
        with self._liveness_lock:
            record = self._liveness.get(service_config_id)
            if (
                record is not None
                and record.reason != AgentLivenessReason.EVICTED_CANNOT_RESTAKE
            ):
                del self._liveness[service_config_id]

    def get_liveness(
        self, service_config_id: str, service_path: t.Optional[Path] = None
    ) -> t.Dict[str, t.Any]:
        """Return the liveness of a service's agent for the deployment payload."""
        with self._liveness_lock:
            record = self._liveness.get(service_config_id)
            if record is not None:
                # Serialise while still holding the lock: the writers set
                # `is_alive` and `reason` in separate statements, so a snapshot
                # taken between the two reports `is_alive: false` with no reason.
                return record.json()

        # Records are in-memory, so a middleware restart leaves none; the PID
        # file the deployment runner wrote outlives this process.
        fallback = AgentLiveness()
        if self._is_agent_process_alive(service_path):
            fallback.mark_healthy()
        return fallback.json()

    async def healthcheck_job(  # pylint: disable=too-many-statements
        self,
        service_config_id: str,
    ) -> None:
        """Start a background health check job."""

        service_path = self._service_manager.load(service_config_id).path
        try:
            self.logger.info(
                f"[HEALTH_CHECKER] Start healthcheck job for service: {service_config_id}"
            )

            async def _wait_for_port(sleep_period: int = 15) -> None:
                self.logger.info("[HEALTH_CHECKER]: wait port is up")
                while True:
                    try:
                        await self.check_service_health(service_config_id, service_path)
                        self.logger.info("[HEALTH_CHECKER]: port is UP")
                        return
                    except aiohttp.ClientConnectionError:
                        self.logger.error(
                            "[HEALTH_CHECKER]: error connecting http port"
                        )
                    await asyncio.sleep(sleep_period)

            async def _check_port_ready(
                timeout: int = self.port_up_timeout, sleep_period: int = 15
            ) -> bool:
                try:
                    await asyncio.wait_for(
                        _wait_for_port(sleep_period=sleep_period), timeout=timeout
                    )
                    return True
                except asyncio.TimeoutError:
                    return False

            async def _check_health(
                number_of_fails: int = 5, sleep_period: int = self.sleep_period
            ) -> float:
                """Check health in a loop; return the longest continuous healthy span (seconds)."""
                fails = 0
                longest_healthy: float = 0.0
                healthy_since: float = 0.0
                while True:
                    try:
                        # Check the service health
                        healthy = await self.check_service_health(
                            service_config_id, service_path
                        )
                    except aiohttp.ClientConnectionError as e:
                        if fails >= number_of_fails:
                            self.logger.debug(
                                f"[HEALTH_CHECKER] Connection error detail: {e}",
                                exc_info=True,
                            )

                        self.logger.warning(
                            f"[HEALTH_CHECKER] {service_config_id} port read failed. assume not healthy {e}"
                        )
                        healthy = False

                    if not healthy:
                        if healthy_since > 0.0:
                            longest_healthy = max(
                                longest_healthy, time.time() - healthy_since
                            )
                            healthy_since = 0.0
                        fails += 1
                        if fails == 1 or fails % 10 == 0 or fails >= number_of_fails:
                            self.logger.warning(
                                f"[HEALTH_CHECKER] {service_config_id} not healthy for {fails} time in a row"
                            )
                    else:
                        self.logger.debug(
                            f"[HEALTH_CHECKER] {service_config_id} is HEALTHY"
                        )
                        if healthy_since == 0.0:
                            healthy_since = time.time()
                        # reset fails if comes healthy
                        fails = 0

                    if fails >= number_of_fails:
                        self.logger.error(
                            f"[HEALTH_CHECKER]  {service_config_id} failed {fails} times in a row. restart"
                        )
                        return longest_healthy

                    await asyncio.sleep(sleep_period)

            async def _restart(
                service_manager: ServiceManager, service_config_id: str
            ) -> StakingReconcileOutcome:
                """Restart the service, clearing an on-chain eviction first."""

                def _do_restart() -> StakingReconcileOutcome:
                    service_manager.stop_service_locally(
                        service_config_id=service_config_id
                    )
                    try:
                        outcome = service_manager.reconcile_staking_for_restart(
                            service_config_id=service_config_id
                        )
                    except Exception:  # pylint: disable=broad-except
                        # A chain read must never wedge the health checker: restart anyway.
                        self.logger.exception(
                            f"[HEALTH_CHECKER] {service_config_id} staking reconciliation failed"
                        )
                        outcome = StakingReconcileOutcome.FAILED

                    if outcome in (
                        StakingReconcileOutcome.EVICTED_CANNOT_RESTAKE,
                        StakingReconcileOutcome.SKIPPED,
                    ):
                        # Either the eviction is known to be unclearable, or another
                        # caller is mid-reconciliation and it is not yet known to be
                        # cleared. Neither is a state to boot the agent back into.
                        return outcome

                    service_manager.deploy_service_locally(
                        service_config_id=service_config_id
                    )
                    return outcome

                return await asyncio.to_thread(_do_restart)

            async def _stop(
                service_manager: ServiceManager, service_config_id: str
            ) -> None:
                def _do_stop() -> None:
                    service_manager.stop_service_locally(
                        service_config_id=service_config_id
                    )

                await asyncio.to_thread(_do_stop)

            # upper cycle
            failfast_records: t.List[float] = []
            while True:
                self.logger.info(
                    f"[HEALTH_CHECKER] {service_config_id} wait for port ready"
                )
                if await _check_port_ready(timeout=self.port_up_timeout):
                    # blocking till restart needed
                    self.logger.info(
                        f"[HEALTH_CHECKER]  {service_config_id} port is ready, checking health every {self.sleep_period}"
                    )
                    longest_healthy = await _check_health(
                        number_of_fails=self.number_of_fails,
                        sleep_period=self.sleep_period,
                    )
                    if longest_healthy >= self.FAILFAST_TIMEOUT:
                        failfast_records = []

                else:
                    self.logger.info(
                        "[HEALTH_CHECKER] port not ready within timeout. restart deployment"
                    )

                # perform restart
                last_restart_exc: t.Optional[Exception] = None
                while True:
                    failfast_records.append(time.time())
                    restart_failed = False
                    outcome = StakingReconcileOutcome.FAILED
                    try:
                        outcome = await _restart(
                            self._service_manager, service_config_id
                        )
                        if outcome == StakingReconcileOutcome.SKIPPED:
                            # Another caller is mid-reconciliation; their transaction is not ours to charge for.
                            self.logger.info(
                                f"[HEALTH_CHECKER] {service_config_id} staking reconciliation "
                                "is already in progress elsewhere. Retrying shortly."
                            )
                            failfast_records.pop()
                        elif outcome == StakingReconcileOutcome.RECONCILED:
                            # The eviction that caused these restarts is cleared, so they were not futile.
                            failfast_records = []
                    except Exception as exc:  # pylint: disable=broad-except
                        restart_failed = True
                        last_restart_exc = exc
                        self.logger.exception(f"Restart problem: {service_config_id}")

                    retry_restart = outcome == StakingReconcileOutcome.SKIPPED
                    if not retry_restart:
                        self.record_restart(service_config_id=service_config_id)

                    if outcome == StakingReconcileOutcome.EVICTED_CANNOT_RESTAKE:
                        self.logger.error(
                            f"[HEALTH_CHECKER] {service_config_id} is evicted on-chain and "
                            "cannot be re-staked yet. Leaving the service stopped."
                        )
                        self.record_reason(
                            service_config_id=service_config_id,
                            reason=AgentLivenessReason.EVICTED_CANNOT_RESTAKE,
                        )
                        return

                    if failfast_records and (
                        (len(failfast_records) >= self.FAILFAST_NUM)
                        or (time.time() - failfast_records[0]) > self.FAILFAST_TIMEOUT
                    ):
                        self.logger.error(
                            f"[HEALTH_CHECKER] {service_config_id} failfast triggered "
                            f"({len(failfast_records)} restarts). Stopping service."
                        )
                        await _stop(self._service_manager, service_config_id)
                        raise RuntimeError(
                            f"Service {service_config_id} stopped by failfast after "
                            f"{len(failfast_records)} restarts"
                        ) from last_restart_exc

                    if not (restart_failed or retry_restart):
                        break

                    await asyncio.sleep(30)

        except Exception:
            self.logger.exception(
                f"Problems running healthcheck job for {service_config_id}"
            )
            raise
