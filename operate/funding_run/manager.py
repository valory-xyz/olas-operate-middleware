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

"""Funding run manager.

A funding run turns one deposit of a user-chosen token on a user-chosen chain
into the tokens Pearl needs on the destination chain:

    RECEIVE -> source leg (BRIDGE + NATIVE) -> SWAP per token
            -> SAFE_AND_TRANSFER -> CLEAR_DELEGATION (USDC sources only)

It is a persisted state machine advanced by one background loop. Every
transition is stored before its side effect, and a step with a recorded
UserOp hash, tx hash or Relay requestId is reconciled, never blindly resent.
"""

import asyncio
import re
import threading
import time
import typing as t
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from logging import Logger
from pathlib import Path

from web3 import Web3

from operate.bridge.bridge_manager import (
    BridgeManager,
    DEFAULT_BUNDLE_VALIDITY_PERIOD,
)
from operate.bridge.providers.provider import ProviderRequest, ProviderRequestStatus
from operate.constants import ZERO_ADDRESS
from operate.funding_run.models import (
    FUNDING_RUN_PREFIX,
    FundingRun,
    FundingRunMode,
    FundingRunPointer,
    FundingRunStatus,
    FundingRunStep,
    FundingStepKind,
    FundingStepStatus,
)
from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import (
    CLEAR_DELEGATION_GAS_RESERVE,
    DEFAULT_EOA_TOPUPS,
    EXPLORER_URL,
    FUNDING_SOURCES,
    GAS_ABSTRACTION_USDC_CAP,
    USDC,
    get_asset_decimals,
    get_asset_name,
)
from operate.operate_types import Chain, LedgerType
from operate.serialization import BigInt
from operate.services.funding_manager import FundingManager
from operate.wallet.gas_abstraction import (
    Call,
    GasAbstractedSender,
    GasAbstractionError,
    RECEIPT_TIMEOUT,
    is_gas_abstracted,
)
from operate.wallet.master import (
    CreateSafeStatus,
    EthereumMasterWallet,
    MasterWalletManager,
)

if t.TYPE_CHECKING:  # pragma: no cover
    from operate.services.manage import ServiceManager  # pylint: disable=unused-import

NATIVE = ZERO_ADDRESS
FUNDING_RUN_ID_RE = re.compile(
    rf"{FUNDING_RUN_PREFIX}[0-9a-f]{{8}}(-[0-9a-f]{{4}}){{3}}-[0-9a-f]{{12}}"
)
RUN_JOB_INTERVAL = 10
# How long GET /active keeps returning a finished run, so the app can still
# show the success modal after a restart.
RECENT_COMPLETION_WINDOW = 5 * 60
LOCK_TIMEOUT = 30
# Conservative destination gas budgets for the Safe step, priced at the
# current gas price when quoting.
SAFE_CREATION_GAS = 1_000_000
SAFE_TRANSFER_GAS = 100_000
SLOW_STEP_MIN_SECONDS = 600
CLEAR_DELEGATION_RETRY_SECONDS = 600

STEP_RECEIVE = "receive"
STEP_BRIDGE = "bridge"
STEP_NATIVE = "native"
STEP_SAFE = "safe"
STEP_CLEAR_DELEGATION = "clear_delegation"
SWAP_STEP_PREFIX = "swap:"
SOURCE_LEG_KINDS = (FundingStepKind.BRIDGE, FundingStepKind.NATIVE)


class FundingRunError(ValueError):
    """Invalid funding run request (HTTP 400)."""


class FundingRunNotFoundError(KeyError):
    """Unknown funding run id (HTTP 404)."""


class FundingRunConflictError(RuntimeError):
    """The request conflicts with the run's state or another run (HTTP 409)."""


def _now() -> int:
    return int(time.time())


class FundingRunManager:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Owns the funding run lifecycle."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        path: Path,
        wallet_manager: MasterWalletManager,
        bridge_manager: BridgeManager,
        funding_manager: FundingManager,
        service_manager: t.Callable[[], "ServiceManager"],
        logger: Logger,
        gas_abstracted_sender: t.Optional[
            t.Callable[[EthereumMasterWallet], GasAbstractedSender]
        ] = None,
    ) -> None:
        """Initialize the manager."""
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self.wallet_manager = wallet_manager
        self.bridge_manager = bridge_manager
        self.funding_manager = funding_manager
        self.service_manager = service_manager
        self.logger = logger
        self._sender_factory = gas_abstracted_sender or (
            lambda wallet: GasAbstractedSender(wallet, logger)
        )
        # Serialises run mutations between API handlers and the background
        # loop. Reads (GET /active) go to disk without it.
        self._lock = threading.RLock()

    # --- persistence --------------------------------------------------------

    def _pointer(self) -> FundingRunPointer:
        if not FundingRunPointer.exists_at(self.path):
            FundingRunPointer(path=self.path).store()
        return t.cast(FundingRunPointer, FundingRunPointer.load(self.path))

    def _run_path(self, run_id: str) -> Path:
        return self.path / f"{run_id}.json"

    def load(self, run_id: str) -> FundingRun:
        """Load a run by id."""
        # Ids come from the URL path: only accept ids this manager could mint.
        if not FUNDING_RUN_ID_RE.fullmatch(run_id):
            raise FundingRunNotFoundError(run_id)
        path = self._run_path(run_id)
        if not path.exists():
            raise FundingRunNotFoundError(run_id)
        return t.cast(FundingRun, FundingRun.load(path))

    @staticmethod
    def _store(run: FundingRun) -> None:
        run.store()

    def _set_active(self, run: t.Optional[FundingRun]) -> None:
        pointer = self._pointer()
        pointer.active_run_id = run.id if run else None
        if run:
            pointer.last_run_id = run.id
        pointer.store()

    def _finish(self, run: FundingRun, status: FundingRunStatus) -> None:
        run.status = status
        run.finished_at = _now()
        self._store(run)
        pointer = self._pointer()
        if pointer.active_run_id == run.id:
            pointer.active_run_id = None
        pointer.last_run_id = run.id
        if (
            status == FundingRunStatus.COMPLETED
            and self._has_step(run, STEP_CLEAR_DELEGATION)
            and run.id not in pointer.pending_clear_run_ids
        ):
            pointer.pending_clear_run_ids.append(run.id)
        pointer.store()

    def active_run(self) -> t.Optional[FundingRun]:
        """The single non-terminal run, else a run completed moments ago."""
        pointer = self._pointer()
        if pointer.active_run_id:
            return self.load(pointer.active_run_id)
        if pointer.last_run_id and self._run_path(pointer.last_run_id).exists():
            run = self.load(pointer.last_run_id)
            if (
                run.status == FundingRunStatus.COMPLETED
                and run.finished_at is not None
                and _now() - run.finished_at <= RECENT_COMPLETION_WINDOW
            ):
                return run
        return None

    # --- wallet helpers -----------------------------------------------------

    def _wallet(self) -> EthereumMasterWallet:
        return t.cast(
            EthereumMasterWallet, self.wallet_manager.load(LedgerType.ETHEREUM)
        )

    @staticmethod
    def sources() -> t.Dict[str, t.List[str]]:
        """The v1 source matrix: chain -> accepted tokens."""
        return {chain.value: list(tokens) for chain, tokens in FUNDING_SOURCES.items()}

    # --- create / replace / cancel ------------------------------------------

    def create_run(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        mode: str,
        source_chain: str,
        source_token: str,
        destination_chain: str,
        service_config_id: t.Optional[str] = None,
        deposit_amounts: t.Optional[t.Dict[str, t.Any]] = None,
        backup_owner: t.Optional[str] = None,
    ) -> FundingRun:
        """Create a run, replacing an AWAITING_DEPOSIT/QUOTE_FAILED one."""
        run_mode, source, token, destination = self._validate(
            mode, source_chain, source_token, destination_chain
        )
        if run_mode == FundingRunMode.DEPOSIT and not deposit_amounts:
            raise FundingRunError("'deposit_amounts' is required in deposit mode.")
        if run_mode == FundingRunMode.ONBOARD and not service_config_id:
            raise FundingRunError("'service_config_id' is required in onboard mode.")
        if backup_owner is not None and not Web3.is_address(backup_owner):
            raise FundingRunError(f"Invalid backup_owner {backup_owner}.")

        with self._locked():
            current = self.active_run()
            if current and current.status in (
                FundingRunStatus.PROCESSING,
                FundingRunStatus.FAILED,
            ):
                raise FundingRunConflictError(
                    f"Funding run {current.id} is {current.status}."
                )

            gross, net = self._targets(
                run_mode, destination, service_config_id, deposit_amounts
            )
            run = FundingRun(
                path=Path(),
                id=f"{FUNDING_RUN_PREFIX}{uuid.uuid4()}",
                mode=run_mode,
                status=FundingRunStatus.AWAITING_DEPOSIT,
                source_chain=source.value,
                source_token=token,
                destination_chain=destination.value,
                created_at=_now(),
                service_config_id=(
                    service_config_id if run_mode == FundingRunMode.ONBOARD else None
                ),
                backup_owner=backup_owner,
                gross_targets={k: BigInt(v) for k, v in gross.items()},
                net_targets={k: BigInt(v) for k, v in net.items() if v > 0},
            )
            run.path = self._run_path(run.id)

            if current and current.status in (
                FundingRunStatus.AWAITING_DEPOSIT,
                FundingRunStatus.QUOTE_FAILED,
            ):
                self._finish(current, FundingRunStatus.CANCELLED)

            if not run.net_targets:
                # Nothing is missing: the app says so instead of asking for funds.
                self._finish(run, FundingRunStatus.COMPLETED)
                return run

            self._quote(run)
            self._store(run)
            self._set_active(run)
            return run

    @staticmethod
    def _validate(
        mode: str, source_chain: str, source_token: str, destination_chain: str
    ) -> t.Tuple[FundingRunMode, Chain, str, Chain]:
        try:
            run_mode = FundingRunMode(mode)
            source = Chain(source_chain)
            destination = Chain(destination_chain)
        except ValueError as e:
            raise FundingRunError(str(e)) from e
        allowed = FUNDING_SOURCES.get(source, [])
        token = next((a for a in allowed if a.lower() == source_token.lower()), None)
        if token is None:
            raise FundingRunError(
                f"Unsupported funding source {source_token} on {source_chain}."
            )
        if destination not in DEFAULT_EOA_TOPUPS:
            raise FundingRunError(f"Unsupported destination chain {destination_chain}.")
        return run_mode, source, token, destination

    def _targets(
        self,
        mode: FundingRunMode,
        destination: Chain,
        service_config_id: t.Optional[str],
        deposit_amounts: t.Optional[t.Dict[str, t.Any]],
    ) -> t.Tuple[t.Dict[str, int], t.Dict[str, int]]:
        """Gross targets per mode, and net targets = shortfall against holdings."""
        if mode == FundingRunMode.ONBOARD:
            service_manager = self.service_manager()
            if not service_manager.exists(service_config_id=service_config_id):
                raise FundingRunError(f"Service {service_config_id} not found.")
            service = service_manager.load(service_config_id=service_config_id)
            if service.home_chain != destination.value:
                raise FundingRunError(
                    f"Onboarding destination must be the service home chain {service.home_chain}."
                )
            # funding_requirements is already net of balances.
            targets = self.funding_manager.destination_targets(service)
            return targets, targets

        if mode == FundingRunMode.DEPOSIT:
            try:
                gross = {
                    Web3.to_checksum_address(token): int(amount)
                    for token, amount in (deposit_amounts or {}).items()
                }
            except (TypeError, ValueError) as e:
                raise FundingRunError(f"Invalid deposit_amounts: {e}") from e
            if any(amount < 0 for amount in gross.values()):
                raise FundingRunError("deposit_amounts must not be negative.")
            held = self.funding_manager.held_balances(destination, gross.keys())
            return gross, {
                token: max(0, amount - held.get(token, 0))
                for token, amount in gross.items()
            }

        reserve = int(DEFAULT_EOA_TOPUPS[destination][NATIVE])
        balance = int(self._wallet().get_balance(destination, NATIVE, from_safe=False))
        return {NATIVE: reserve}, {NATIVE: max(0, reserve - balance)}

    def cancel(self, run_id: str) -> FundingRun:
        """Cancel a run that has not started processing."""
        with self._locked():
            run = self.load(run_id)
            self._require(
                run, FundingRunStatus.AWAITING_DEPOSIT, FundingRunStatus.QUOTE_FAILED
            )
            # Received funds stay in the Master EOA and count toward the next quote.
            self._finish(run, FundingRunStatus.CANCELLED)
            return run

    def refresh_quote(self, run_id: str) -> FundingRun:
        """Re-quote a run that is still waiting for its deposit."""
        with self._locked():
            run = self.load(run_id)
            self._require(
                run, FundingRunStatus.AWAITING_DEPOSIT, FundingRunStatus.QUOTE_FAILED
            )
            self._quote(run)
            self._store(run)
            return run

    def retry(self, run_id: str) -> FundingRun:
        """Resume a FAILED run at its failed step.

        A step whose on-chain effect has landed meanwhile (e.g. Relay later
        reports success) is reconciled instead of resent.
        """
        with self._locked():
            run = self.load(run_id)
            self._require(run, FundingRunStatus.FAILED)
            source_steps = self._source_steps(run)
            if any(s.status == FundingStepStatus.FAILED for s in source_steps):
                if run.user_op_hash and not run.source_tx_hash:
                    self._reconcile_user_op(run)
                for step in source_steps:
                    self._track(run, step)
                failed = [
                    r
                    for s in source_steps
                    if s.status == FundingStepStatus.FAILED
                    for r in run.requests_of(s)
                ]
                if failed:
                    # A source leg that never landed also takes the hidden
                    # clearing-reserve request with it.
                    failed += [
                        r
                        for r in run.source_requests
                        if r not in failed
                        and (
                            r.execution_data is None
                            or r.status == ProviderRequestStatus.EXECUTION_FAILED
                        )
                    ]
                    self._reset_requests(run, failed)
                    run.user_op_hash = None
                    run.source_tx_hash = None
            for step in run.steps:
                if (
                    step.kind == FundingStepKind.SWAP
                    and step.status == FundingStepStatus.FAILED
                ):
                    self._track(run, step)
                    if step.status == FundingStepStatus.FAILED:
                        self._reset_requests(run, run.requests_of(step))
                if step.status == FundingStepStatus.FAILED:
                    self._reset_step(step)
            run.sending_request_ids = []
            run.error = None
            run.status = FundingRunStatus.PROCESSING
            self._store(run)
            return run

    @staticmethod
    def _reset_step(step: FundingRunStep) -> None:
        step.status = FundingStepStatus.PENDING
        step.message = None
        step.is_slow = None
        step.started_at = None
        step.finished_at = None

    def _reset_requests(self, run: FundingRun, old: t.List[ProviderRequest]) -> None:
        """Replace `old` requests with freshly quoted ones; others are untouched."""
        fresh = self.bridge_manager.quote_requests([dict(r.params) for r in old])
        mapping = {o.id: n for o, n in zip(old, fresh.provider_requests)}
        run.source_requests = [mapping.get(r.id, r) for r in run.source_requests]
        run.swap_requests = [mapping.get(r.id, r) for r in run.swap_requests]
        for step in run.steps:
            if not any(i in mapping for i in step.request_ids):
                continue
            step.request_ids = [
                mapping[i].id if i in mapping else i for i in step.request_ids
            ]
            step.tx_hash = None
            step.explorer_link = None
            if step.kind != FundingStepKind.CLEAR_DELEGATION:
                self._reset_step(step)

    @staticmethod
    def _require(run: FundingRun, *statuses: FundingRunStatus) -> None:
        if run.status not in statuses:
            raise FundingRunConflictError(
                f"Funding run {run.id} is {run.status}; expected one of "
                f"{', '.join(str(s) for s in statuses)}."
            )

    @contextmanager
    def _locked(self) -> t.Iterator[None]:
        if not self._lock.acquire(timeout=LOCK_TIMEOUT):
            raise FundingRunConflictError("A funding run is being processed.")
        try:
            yield
        finally:
            self._lock.release()

    # --- quoting ------------------------------------------------------------

    @staticmethod
    def _params(  # pylint: disable=too-many-arguments
        from_chain: Chain,
        from_token: str,
        to_chain: Chain,
        to_token: str,
        amount: int,
        address: str,
        explicit_deposit: bool = False,
    ) -> t.Dict:
        params: t.Dict[str, t.Any] = {
            "from": {
                "chain": from_chain.value,
                "address": address,
                "token": from_token,
            },
            "to": {
                "chain": to_chain.value,
                "address": address,
                "token": to_token,
                "amount": int(amount),
            },
        }
        if explicit_deposit:
            params["explicit_deposit"] = True
        return params

    def _native_price(self, chain: Chain) -> int:
        pricing = get_default_ledger_api(chain).try_get_gas_pricing() or {}
        return int(pricing.get("maxFeePerGas", pricing.get("gasPrice", 0)))

    def _destination_overhead(self, run: FundingRun, n_assets: int) -> int:
        """Destination native for the Safe step and the Master EOA reserve."""
        if run.mode == FundingRunMode.SIGNER_GAS:
            return 0
        destination = Chain(run.destination_chain)
        wallet = self._wallet()
        gas = SAFE_TRANSFER_GAS * (n_assets + 1)
        if destination not in wallet.safes:
            gas += SAFE_CREATION_GAS
        balance = int(wallet.get_balance(destination, NATIVE, from_safe=False))
        if run.source_chain == run.destination_chain and run.source_token == NATIVE:
            # The deposit itself lands here: it is already counted as received
            # and must not also count as covering the reserve.
            balance -= self._received(run)
        reserve = int(DEFAULT_EOA_TOPUPS[destination][NATIVE])
        return gas * self._native_price(destination) + max(0, reserve - balance)

    def _source_amount(self, request: ProviderRequest, token: str) -> int:
        requirements = self.bridge_manager.provider_for(request).requirements(request)
        chain = request.params["from"]["chain"]
        address = request.params["from"]["address"]
        return int(requirements[chain][address].get(token, 0))

    def _quote(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self, run: FundingRun
    ) -> None:
        """Walk back from the net targets to one source-chain amount."""
        source = Chain(run.source_chain)
        destination = Chain(run.destination_chain)
        token = run.source_token
        eoa = self._wallet().address
        gas_abstracted = is_gas_abstracted(source, token)
        carrier = USDC.get(destination) if token == USDC.get(source) else None
        carrier = carrier or NATIVE

        targets = {k: int(v) for k, v in run.net_targets.items() if int(v) > 0}
        native_needed = targets.pop(NATIVE, 0)
        carrier_needed = targets.pop(carrier, 0) if carrier != NATIVE else 0

        # (a) Destination swaps carrier -> target token.
        swap_params = [
            self._params(destination, carrier, destination, target, amount, eoa)
            for target, amount in targets.items()
        ]
        swaps = (
            self.bridge_manager.quote_requests(swap_params).provider_requests
            if swap_params
            else []
        )
        if self._quote_failed(run, swaps):
            return
        for request in swaps:
            native_needed += self._source_amount(request, NATIVE)
            if carrier != NATIVE:
                carrier_needed += self._source_amount(request, carrier)

        if swaps or native_needed or carrier_needed:
            native_needed += self._destination_overhead(run, len(targets) + 1)

        clear_reserve = (
            CLEAR_DELEGATION_GAS_RESERVE.get(source, 0) if gas_abstracted else 0
        )
        if source == destination:
            # The native request already lands on the source chain.
            native_needed += clear_reserve
            clear_reserve = 0

        # (b) The source leg; same-token same-chain amounts need no request.
        direct = 0
        leg: t.List[t.Tuple[FundingStepKind, t.Dict]] = []
        if carrier != NATIVE and carrier_needed:
            if source == destination and token == carrier:
                direct += carrier_needed
            else:
                leg.append(
                    (
                        FundingStepKind.BRIDGE,
                        self._params(
                            source,
                            token,
                            destination,
                            carrier,
                            carrier_needed,
                            eoa,
                            gas_abstracted,
                        ),
                    )
                )
        if native_needed:
            if source == destination and token == NATIVE:
                direct += native_needed
            else:
                kind = (
                    FundingStepKind.NATIVE
                    if carrier != NATIVE
                    else FundingStepKind.BRIDGE
                )
                leg.append(
                    (
                        kind,
                        self._params(
                            source,
                            token,
                            destination,
                            NATIVE,
                            native_needed,
                            eoa,
                            gas_abstracted,
                        ),
                    )
                )
        # (b2) Source native for the final delegation-clearing transaction.
        if clear_reserve:
            leg.append(
                (
                    FundingStepKind.CLEAR_DELEGATION,
                    self._params(
                        source, token, source, NATIVE, clear_reserve, eoa, True
                    ),
                )
            )

        source_requests = (
            self.bridge_manager.quote_requests([p for _, p in leg]).provider_requests
            if leg
            else []
        )
        if self._quote_failed(run, source_requests):
            return

        # (c) Required = source-leg inputs + direct amounts + gas allowance.
        required = direct + sum(self._source_amount(r, token) for r in source_requests)
        if gas_abstracted and source_requests:
            required += GAS_ABSTRACTION_USDC_CAP

        run.source_requests = list(source_requests)
        run.swap_requests = list(swaps)
        run.required_amount = BigInt(required)
        run.quoted_at = _now()
        run.quote_message = None
        run.eta_seconds = max(
            [r.quote_data.eta or 0 for r in source_requests if r.quote_data] or [0]
        ) + sum(r.quote_data.eta or 0 for r in swaps if r.quote_data)
        run.steps = self._plan_steps(
            run, [k for k, _ in leg], source_requests, swaps, gas_abstracted
        )
        run.received_amount = BigInt(self._received(run))
        if run.status == FundingRunStatus.QUOTE_FAILED:
            run.status = FundingRunStatus.AWAITING_DEPOSIT

    def _quote_failed(self, run: FundingRun, requests: t.List[ProviderRequest]) -> bool:
        failed = [r for r in requests if r.status == ProviderRequestStatus.QUOTE_FAILED]
        if not failed:
            return False
        run.status = FundingRunStatus.QUOTE_FAILED
        run.quoted_at = _now()
        run.quote_message = next(
            (r.quote_data.message for r in failed if r.quote_data), "Quote failed."
        )
        self.logger.warning(
            f"[FUNDING RUN] Quote failed for {run.id}: {run.quote_message}"
        )
        return True

    def _plan_steps(
        self,
        run: FundingRun,
        leg_kinds: t.List[FundingStepKind],
        source_requests: t.List[ProviderRequest],
        swaps: t.List[ProviderRequest],
        gas_abstracted: bool,
    ) -> t.List[FundingRunStep]:
        steps = [
            FundingRunStep(
                id=STEP_RECEIVE,
                kind=FundingStepKind.RECEIVE,
                status=FundingStepStatus.PENDING,
                visible=True,
                token=run.source_token,
                amount=run.required_amount,
            )
        ]
        clear_request_ids: t.List[str] = []
        for kind, request in zip(leg_kinds, source_requests):
            if kind == FundingStepKind.CLEAR_DELEGATION:
                clear_request_ids.append(request.id)
                continue
            steps.append(
                FundingRunStep(
                    id=STEP_BRIDGE if kind == FundingStepKind.BRIDGE else STEP_NATIVE,
                    kind=kind,
                    status=FundingStepStatus.PENDING,
                    visible=True,
                    token=request.params["to"]["token"],
                    amount=BigInt(request.params["to"]["amount"]),
                    request_ids=[request.id],
                    eta_seconds=request.quote_data.eta if request.quote_data else None,
                )
            )
        for request in swaps:
            token = request.params["to"]["token"]
            steps.append(
                FundingRunStep(
                    id=f"{SWAP_STEP_PREFIX}{token}",
                    kind=FundingStepKind.SWAP,
                    status=FundingStepStatus.PENDING,
                    visible=True,
                    token=token,
                    amount=BigInt(request.params["to"]["amount"]),
                    request_ids=[request.id],
                    eta_seconds=request.quote_data.eta if request.quote_data else None,
                )
            )
        if run.mode != FundingRunMode.SIGNER_GAS:
            steps.append(
                FundingRunStep(
                    id=STEP_SAFE,
                    kind=FundingStepKind.SAFE_AND_TRANSFER,
                    status=FundingStepStatus.PENDING,
                    visible=False,
                )
            )
        if gas_abstracted and source_requests:
            steps.append(
                FundingRunStep(
                    id=STEP_CLEAR_DELEGATION,
                    kind=FundingStepKind.CLEAR_DELEGATION,
                    status=FundingStepStatus.PENDING,
                    visible=False,
                    request_ids=clear_request_ids,
                )
            )
        return steps

    # --- monitoring ----------------------------------------------------------

    def _received(self, run: FundingRun) -> int:
        """What the Master EOA holds of the source token on the source chain.

        Idempotent by construction: "received" is simply the current balance,
        so partial deposits and restarts need no bookkeeping.
        """
        source = Chain(run.source_chain)
        wallet = self._wallet()
        balance = int(wallet.get_balance(source, run.source_token, from_safe=False))
        if run.source_token == NATIVE and source in wallet.safes:
            balance -= int(DEFAULT_EOA_TOPUPS[source][NATIVE])
        return max(0, balance)

    def _monitor(self, run: FundingRun) -> None:
        stale = (
            run.quoted_at is None
            or _now() > run.quoted_at + DEFAULT_BUNDLE_VALIDITY_PERIOD
        )
        if run.status == FundingRunStatus.QUOTE_FAILED:
            if stale:
                self._quote(run)
                self._store(run)
            return

        run.received_amount = BigInt(self._received(run))
        if stale:
            self._quote(run)
        if (
            run.status == FundingRunStatus.AWAITING_DEPOSIT
            and run.required_amount is not None
            and run.received_amount >= run.required_amount
        ):
            # Final quote against the funds actually held; a shortfall sends
            # the run back to waiting with the new amount.
            self._quote(run)
            if (
                run.status == FundingRunStatus.AWAITING_DEPOSIT
                and run.required_amount is not None
                and run.received_amount >= run.required_amount
            ):
                receive = run.step(STEP_RECEIVE)
                receive.status = FundingStepStatus.DONE
                receive.started_at = receive.started_at or run.created_at
                receive.finished_at = _now()
                run.status = FundingRunStatus.PROCESSING
                self.logger.info(
                    f"[FUNDING RUN] {run.id} deposit received; processing."
                )
        self._store(run)

    # --- execution -----------------------------------------------------------

    @staticmethod
    def _has_step(run: FundingRun, step_id: str) -> bool:
        return any(step.id == step_id for step in run.steps)

    def _fail(self, run: FundingRun, step: FundingRunStep, message: str) -> None:
        step.status = FundingStepStatus.FAILED
        step.message = message
        step.finished_at = _now()
        # A hidden step fails through the last visible step before it.
        reported = step
        if not step.visible:
            visible = [s for s in run.steps[: run.steps.index(step)] if s.visible]
            reported = visible[-1] if visible else step
        run.error = {"step_id": reported.id, "message": message}
        run.status = FundingRunStatus.FAILED
        self._store(run)
        self.logger.error(f"[FUNDING RUN] {run.id} step {step.id} failed: {message}")

    def _track(self, run: FundingRun, step: FundingRunStep) -> None:
        """Refresh a step from the provider status of its requests."""
        requests = run.requests_of(step)
        statuses = []
        for request in requests:
            if request.execution_data is None:
                statuses.append(request.status)
                continue
            status = self.bridge_manager.provider_for(request).status_json(request)
            step.tx_hash = step.tx_hash or status.get("tx_hash")
            step.explorer_link = status.get("explorer_link") or step.explorer_link
            statuses.append(request.status)
        if statuses and all(
            s == ProviderRequestStatus.EXECUTION_DONE for s in statuses
        ):
            step.status = FundingStepStatus.DONE
            step.finished_at = step.finished_at or _now()
            step.is_slow = None
        elif any(s == ProviderRequestStatus.EXECUTION_FAILED for s in statuses):
            step.status = FundingStepStatus.FAILED
            step.message = next(
                (
                    r.execution_data.message
                    for r in requests
                    if r.execution_data and r.execution_data.message
                ),
                "Execution failed.",
            )
        elif any(r.execution_data is not None for r in requests):
            step.status = FundingStepStatus.PROCESSING

    def _advance(self, run: FundingRun) -> None:
        """Move a PROCESSING run forward by at most one side effect."""
        for step in run.steps:
            if step.status == FundingStepStatus.DONE:
                continue
            if step.kind == FundingStepKind.CLEAR_DELEGATION:
                break  # never blocks completion
            if step.kind in SOURCE_LEG_KINDS:
                self._advance_source_leg(run)
            elif step.kind == FundingStepKind.SWAP:
                self._advance_swap(run, step)
            elif step.kind == FundingStepKind.SAFE_AND_TRANSFER:
                self._advance_safe(run, step)
            failed = next(
                (s for s in run.steps if s.status == FundingStepStatus.FAILED), None
            )
            if failed is not None and failed.kind != FundingStepKind.CLEAR_DELEGATION:
                self._fail(run, failed, failed.message or "Step failed.")
            self._store(run)
            return

        self._finish(run, FundingRunStatus.COMPLETED)
        self.logger.info(f"[FUNDING RUN] {run.id} completed.")
        self._clear_delegation(run)

    def _source_steps(self, run: FundingRun) -> t.List[FundingRunStep]:
        return [s for s in run.steps if s.kind in SOURCE_LEG_KINDS]

    def _advance_source_leg(self, run: FundingRun) -> None:
        source = Chain(run.source_chain)
        steps = self._source_steps(run)
        unsent = [r for r in run.source_requests if r.execution_data is None]

        if run.user_op_hash and not run.source_tx_hash:
            self._reconcile_user_op(run)
            return

        if run.sending_request_ids:
            interrupted = {r.id for r in unsent if r.id in run.sending_request_ids}
            run.sending_request_ids = []
            if interrupted:
                # The process stopped mid-send: never resend blindly, the user
                # retries explicitly once the outcome is visible.
                for step in steps:
                    if interrupted & set(step.request_ids):
                        step.status = FundingStepStatus.FAILED
                        step.message = "Interrupted before the transfer was confirmed."
                return

        if unsent:
            unsent_ids = {r.id for r in unsent}
            for step in steps:
                if unsent_ids & set(step.request_ids):
                    step.status = FundingStepStatus.PROCESSING
                    step.started_at = _now()
            self._store(run)
            if is_gas_abstracted(source, run.source_token):
                self._send_user_op(run, unsent)
            else:
                for request in unsent:
                    run.sending_request_ids = [request.id]
                    self._store(run)
                    self.bridge_manager.execute_request(request)
                    run.sending_request_ids = []
                    self._store(run)
            return

        for step in steps:
            self._track(run, step)
            self._mark_slow(step)

    def _send_user_op(self, run: FundingRun, requests: t.List[ProviderRequest]) -> None:
        source = Chain(run.source_chain)
        sender = self._sender_factory(self._wallet())
        calls = [
            Call(
                target=tx["to"],
                value=int(tx.get("value", 0)),
                data=tx.get("data", "0x"),
            )
            for request in requests
            for _, tx in self.bridge_manager.provider_for(request).get_txs(request)
        ]
        try:
            prepared = sender.prepare_batch(source, calls)
        except GasAbstractionError as e:
            for step in self._source_steps(run):
                step.status = FundingStepStatus.FAILED
                step.message = str(e)
            return
        run.user_op_hash = prepared.user_op_hash
        run.delegation_auth_nonce = prepared.authorization_nonce
        self._store(run)
        try:
            sender.submit(source, prepared)
            self._record_source_tx(
                run, sender.wait_for_tx_hash(source, run.user_op_hash)
            )
        except GasAbstractionError as e:
            # Reconciled against the bundler on the next tick.
            self.logger.warning(f"[FUNDING RUN] UserOp {run.user_op_hash}: {e}")

    def _record_source_tx(self, run: FundingRun, tx_hash: str) -> None:
        run.source_tx_hash = tx_hash
        # Every request not yet executed was batched into this UserOp.
        for request in run.source_requests:
            if request.execution_data is None:
                self.bridge_manager.provider_for(request).record_external_execution(
                    request, tx_hash
                )
        self._store(run)

    def _reconcile_user_op(self, run: FundingRun) -> None:
        source = Chain(run.source_chain)
        sender = self._sender_factory(self._wallet())
        try:
            receipt = sender.get_user_op_receipt(source, t.cast(str, run.user_op_hash))
            if receipt:
                self._record_source_tx(run, sender.tx_hash_of(receipt))
                return
        except GasAbstractionError as e:
            for step in self._source_steps(run):
                step.status = FundingStepStatus.FAILED
                step.message = str(e)
            return
        started = min((s.started_at or _now()) for s in self._source_steps(run))
        if _now() - started > RECEIPT_TIMEOUT:
            for step in self._source_steps(run):
                step.status = FundingStepStatus.FAILED
                step.message = f"UserOperation {run.user_op_hash} was not included."

    def _advance_swap(self, run: FundingRun, step: FundingRunStep) -> None:
        (request,) = run.requests_of(step)
        if request.execution_data is None:
            if step.status == FundingStepStatus.PROCESSING:
                step.status = FundingStepStatus.FAILED
                step.message = "Interrupted before the swap was confirmed."
                return
            provider = self.bridge_manager.provider_for(request)
            if (
                request.quote_data is None
                or _now()
                > request.quote_data.timestamp + DEFAULT_BUNDLE_VALIDITY_PERIOD
            ):
                provider.quote(request)
            if request.status == ProviderRequestStatus.QUOTE_FAILED:
                step.status = FundingStepStatus.FAILED
                step.message = (
                    request.quote_data.message
                    if request.quote_data
                    else "Quote failed."
                )
                return
            step.status = FundingStepStatus.PROCESSING
            step.started_at = _now()
            self._store(run)
            self.bridge_manager.execute_request(request)
            return
        self._track(run, step)
        self._mark_slow(step)

    def _advance_safe(self, run: FundingRun, step: FundingRunStep) -> None:
        destination = Chain(run.destination_chain)
        step.status = FundingStepStatus.PROCESSING
        step.started_at = _now()
        self._store(run)
        result = self._wallet().create_safe_and_transfer_excess(
            chain=destination, backup_owner=run.backup_owner
        )
        if (
            result["status"] == CreateSafeStatus.SAFE_CREATION_FAILED
            or result["transfer_errors"]
        ):
            step.status = FundingStepStatus.FAILED
            step.message = result["message"]
            return
        tx_hash = result["create_tx"] or next(
            iter(result["transfer_txs"].values()), None
        )
        step.tx_hash = tx_hash
        if tx_hash:
            step.explorer_link = EXPLORER_URL[destination]["tx"].format(tx_hash=tx_hash)
        step.status = FundingStepStatus.DONE
        step.finished_at = _now()

    @staticmethod
    def _mark_slow(step: FundingRunStep) -> None:
        """Flag a step running well past its ETA ("Taking longer than usual")."""
        if step.status != FundingStepStatus.PROCESSING or step.started_at is None:
            return
        threshold = max(SLOW_STEP_MIN_SECONDS, 2 * (step.eta_seconds or 0))
        step.is_slow = _now() - step.started_at > threshold

    # --- delegation clearing --------------------------------------------------

    def _clear_delegation(self, run: FundingRun) -> None:
        """Reset the source-chain delegation; failures never fail the run."""
        if not self._has_step(run, STEP_CLEAR_DELEGATION) or run.delegation_cleared:
            return
        step = run.step(STEP_CLEAR_DELEGATION)
        if (
            step.started_at
            and step.status != FundingStepStatus.PENDING
            and _now() - step.started_at < CLEAR_DELEGATION_RETRY_SECONDS
        ):
            return
        source = Chain(run.source_chain)
        try:
            if step.request_ids:
                self._track(run, step)
                # The clearing gas is still being swapped in on the source
                # chain. A failed swap does not stop the attempt: the Master
                # EOA may hold native anyway.
                if any(
                    r.status
                    not in (
                        ProviderRequestStatus.EXECUTION_DONE,
                        ProviderRequestStatus.EXECUTION_FAILED,
                    )
                    for r in run.requests_of(step)
                ):
                    step.status = FundingStepStatus.PENDING
                    self._store(run)
                    return
            sender = self._sender_factory(self._wallet())
            step.status = FundingStepStatus.PROCESSING
            step.started_at = _now()
            self._store(run)
            if sender.delegation_of(source) is not None:
                run.clear_delegation_tx_hash = self._wallet().clear_delegation(source)
                step.tx_hash = run.clear_delegation_tx_hash
            if sender.delegation_of(source) is not None:
                raise GasAbstractionError("Delegation still present after clearing.")
            step.status = FundingStepStatus.DONE
            step.finished_at = _now()
            run.delegation_cleared = True
            self._store(run)
            pointer = self._pointer()
            if run.id in pointer.pending_clear_run_ids:
                pointer.pending_clear_run_ids.remove(run.id)
                pointer.store()
        except Exception as e:  # pylint: disable=broad-except
            # Custody is unaffected either way; retried in the background.
            step.status = FundingStepStatus.FAILED
            step.message = str(e)
            self._store(run)
            self.logger.warning(
                f"[FUNDING RUN] Clearing delegation for {run.id} failed: {e}"
            )

    # --- background loop ------------------------------------------------------

    def reconcile(self) -> None:
        """Start-up reconciliation of pending delegation clearing."""
        with self._lock:
            for run_id in list(self._pointer().pending_clear_run_ids):
                try:
                    run = self.load(run_id)
                except FundingRunNotFoundError:
                    continue
                step = run.step(STEP_CLEAR_DELEGATION)
                step.started_at = None  # retry now
                self._clear_delegation(run)

    def tick(self) -> None:
        """Advance the active run and retry pending delegation clearing."""
        with self._lock:
            run = self.active_run()
            if run is not None and not run.status.is_terminal:
                if run.status in (
                    FundingRunStatus.AWAITING_DEPOSIT,
                    FundingRunStatus.QUOTE_FAILED,
                ):
                    self._monitor(run)
                elif run.status == FundingRunStatus.PROCESSING:
                    with self.funding_manager.master_eoa_lock:
                        self._advance(run)
            for run_id in list(self._pointer().pending_clear_run_ids):
                try:
                    self._clear_delegation(self.load(run_id))
                except FundingRunNotFoundError:
                    continue

    async def run_job(self, loop: t.Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Background loop advancing the run, started after login."""
        loop = loop or asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                await loop.run_in_executor(executor, self.reconcile)
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("[FUNDING RUN] Reconciliation failed")
            while True:
                try:
                    await loop.run_in_executor(executor, self.tick)
                except Exception:  # pylint: disable=broad-except
                    self.logger.exception("[FUNDING RUN] Tick failed")
                await asyncio.sleep(RUN_JOB_INTERVAL)

    # --- API representation ----------------------------------------------------

    def run_json(self, run: FundingRun) -> t.Dict[str, t.Any]:
        """The run object returned by every /api/funding_run route."""
        source = Chain(run.source_chain)
        destination = Chain(run.destination_chain)
        required = run.required_amount
        received = int(run.received_amount)
        quote = None
        if required is not None and run.quoted_at is not None:
            quote = {
                "required_amount": str(required),
                "received_amount": str(received),
                "outstanding_amount": str(max(0, int(required) - received)),
                "eta_seconds": run.eta_seconds,
                "quoted_at": run.quoted_at,
                "next_refresh_at": run.quoted_at + DEFAULT_BUNDLE_VALIDITY_PERIOD,
            }
        return {
            "id": run.id,
            "mode": run.mode.value,
            "status": run.status.value,
            "source": {
                "chain": source.value,
                "token": run.source_token,
                "symbol": get_asset_name(source, run.source_token),
                "decimals": get_asset_decimals(source, run.source_token),
                "deposit_address": self._wallet().address,
            },
            "destination": {
                "chain": destination.value,
                "wallet": (
                    "master_eoa"
                    if run.mode == FundingRunMode.SIGNER_GAS
                    else "master_safe"
                ),
            },
            "quote": quote,
            "quote_message": run.quote_message,
            "to_receive": [
                {
                    "token": token,
                    "symbol": get_asset_name(destination, token),
                    "amount": str(amount),
                }
                for token, amount in run.net_targets.items()
            ],
            "steps": [
                {
                    "id": step.id,
                    "kind": step.kind.value,
                    "status": step.status.value,
                    "token": step.token,
                    "amount": str(step.amount) if step.amount is not None else None,
                    "tx_hash": step.tx_hash,
                    "explorer_link": step.explorer_link,
                    "started_at": step.started_at,
                    "finished_at": step.finished_at,
                    "is_slow": bool(step.is_slow),
                    "visible": step.visible,
                }
                for step in run.steps
            ],
            "error": run.error,
        }
