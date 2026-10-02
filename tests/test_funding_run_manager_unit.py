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

"""Unit tests for operate/funding_run/manager.py (providers, chain and bundler faked)."""

import asyncio
import threading
import time
import typing as t
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from operate.bridge.bridge_manager import BridgeManager
from operate.bridge.providers.provider import (
    ExecutionData,
    ProviderRequest,
    ProviderRequestStatus,
    QuoteData,
)
from operate.constants import ZERO_ADDRESS
from operate.funding_run.manager import (
    FundingRunConflictError,
    FundingRunError,
    FundingRunManager,
    FundingRunNotFoundError,
    MESSAGE_AWAITING_CONFIRMATION,
    MESSAGE_MONITOR_FAILED,
    MESSAGE_QUOTE_FAILED,
    MESSAGE_TRANSFER_FAILED,
    RUN_JOB_INTERVAL,
    SLOW_STEP_MIN_SECONDS,
    STEP_BRIDGE,
    STEP_CLEAR_DELEGATION,
    STEP_NATIVE,
    STEP_RECEIVE,
    STEP_SAFE,
    SWAP_STEP_PREFIX,
    USER_OP_RESOLUTION_TIMEOUT,
)
from operate.funding_run.models import (
    FundingRun,
    FundingRunMode,
    FundingRunStatus,
    FundingStepKind,
    FundingStepStatus,
)
from operate.ledger.profiles import (
    CLEAR_DELEGATION_GAS_RESERVE,
    DEFAULT_EOA_TOPUPS,
    GAS_ABSTRACTION_USDC_CAP,
    OLAS,
    PUSD,
    USDC,
)
from operate.operate_types import Chain
from operate.serialization import BigInt
from operate.wallet.gas_abstraction import (
    Call,
    GasAbstractedSender,
    GasAbstractionError,
    PreparedUserOperation,
    RECEIPT_TIMEOUT,
    UserOperationReverted,
)
from operate.wallet.master import CreateSafeStatus

MODULE = "operate.funding_run.manager"
EOA = "0x" + "a" * 40
SAFE = "0x" + "b" * 40
BASE_USDC = USDC[Chain.BASE]
POLYGON_USDC = USDC[Chain.POLYGON]
POLYGON_OLAS = OLAS[Chain.POLYGON]
POLYGON_PUSD = PUSD[Chain.POLYGON]
NATIVE = ZERO_ADDRESS
GAS = 7  # native gas per quoted request, in wei, on every chain
POLYGON_RESERVE = int(DEFAULT_EOA_TOPUPS[Chain.POLYGON][NATIVE])
GNOSIS_RESERVE = int(DEFAULT_EOA_TOPUPS[Chain.GNOSIS][NATIVE])
GNOSIS_USDC = "0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83"
GNOSIS_USDC_E = "0x2a22f9c3b484c3629090FeED35F17Ff8F88f76F0"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Crash(BaseException):
    """Simulates the process dying: nothing in the manager catches it."""


class FakeProvider:
    """Deterministic provider: 1 from-unit per to-unit, GAS native per request."""

    def __init__(self, bridge: "FakeBridge") -> None:
        """Bind to the owning bridge."""
        self.bridge = bridge

    def requirements(self, request: ProviderRequest) -> t.Dict:
        """Source amounts: 1:1 in the from token, plus GAS native."""
        chain = request.params["from"]["chain"]
        token = request.params["from"]["token"]
        amount = request.params["to"]["amount"]
        result = {NATIVE: GAS}
        result[token] = result.get(token, 0) + amount
        return {chain: {EOA: result}}

    def get_txs(self, request: ProviderRequest) -> t.List[t.Tuple[str, t.Dict]]:
        """One deposit tx per request, distinct per destination chain and token."""
        return [("deposit-0", _deposit_tx(request))]

    def quote(self, request: ProviderRequest) -> None:
        """Re-quote in place."""
        self.bridge.quote_count += 1
        request.status = ProviderRequestStatus.QUOTE_DONE
        request.quote_data = QuoteData(
            eta=60,
            elapsed_time=0,
            message=None,
            timestamp=int(time.time()),
            provider_data={},
        )

    def execute(self, request: ProviderRequest) -> None:
        """Mark as sent."""
        self.bridge.executed.append(request.params["to"]["token"])
        if self.bridge.fail_execute:
            raise RuntimeError("boom")
        request.execution_data = ExecutionData(
            elapsed_time=0,
            message=None,
            timestamp=int(time.time()),
            from_tx_hash="0x" + "e" * 64,
            to_tx_hash=None,
            provider_data=None,
        )
        request.status = ProviderRequestStatus.EXECUTION_PENDING

    def record_external_execution(self, request: ProviderRequest, tx_hash: str) -> None:
        """Mark as sent by the UserOp."""
        assert request.status == ProviderRequestStatus.QUOTE_DONE
        request.execution_data = ExecutionData(
            elapsed_time=0,
            message=None,
            timestamp=int(time.time()),
            from_tx_hash=tx_hash,
            to_tx_hash=None,
            provider_data=None,
        )
        request.status = ProviderRequestStatus.EXECUTION_PENDING

    def status_json(self, request: ProviderRequest) -> t.Dict:
        """Resolve to the outcome configured for the target token.

        Like the real providers, a request already settled is not looked up.
        """
        outcome = self.bridge.outcomes.get(request.params["to"]["token"])
        if outcome is not None and request.status in (
            ProviderRequestStatus.EXECUTION_PENDING,
            ProviderRequestStatus.EXECUTION_UNKNOWN,
        ):
            request.status = outcome
        return {"tx_hash": "0x" + "e" * 64, "explorer_link": "https://relay.link/x"}

    def failure_is_final(self, request: ProviderRequest) -> bool:
        """Final unless the target token is configured as still unconfirmed."""
        return request.params["to"]["token"] not in self.bridge.unconfirmed


def _deposit_tx(request: ProviderRequest) -> t.Dict:
    to = request.params["to"]
    return {
        "to": "0x" + "c" * 40,
        "value": int(to["amount"]),
        "data": "0x" + to["chain"].encode().hex() + to["token"][2:].lower(),
    }


@dataclass
class FakeBundle:
    """Stands in for ProviderRequestBundle."""

    provider_requests: t.List[ProviderRequest] = field(default_factory=list)


class FakeBridge:
    """Stands in for BridgeManager."""

    def __init__(self) -> None:
        """Start with no quotes, executions or outcomes."""
        self.provider = FakeProvider(self)
        self.quoted: t.List[t.Dict] = []
        self.executed: t.List[str] = []
        self.outcomes: t.Dict[str, ProviderRequestStatus] = {}
        self.unconfirmed: t.Set[str] = set()
        self.fail_quote = False
        self.fail_execute = False
        self.quote_count = 0

    def quote_requests(self, requests_params: t.List[t.Dict]) -> FakeBundle:
        """Quote each request."""
        self.quoted.extend(requests_params)
        return FakeBundle(
            [
                ProviderRequest(
                    params=params,
                    provider_id="relay-provider",
                    id=f"r-{uuid.uuid4()}",
                    status=(
                        ProviderRequestStatus.QUOTE_FAILED
                        if self.fail_quote
                        else ProviderRequestStatus.QUOTE_DONE
                    ),
                    quote_data=QuoteData(
                        eta=60,
                        elapsed_time=0,
                        message="no route" if self.fail_quote else None,
                        timestamp=int(time.time()),
                        provider_data={},
                    ),
                    execution_data=None,
                )
                for params in requests_params
            ]
        )

    def provider_for(self, request: ProviderRequest) -> FakeProvider:
        """Single provider."""
        return self.provider

    swap_source_token = staticmethod(BridgeManager.swap_source_token)

    def execute_request(self, request: ProviderRequest) -> None:
        """Execute through the provider."""
        self.provider.execute(request)


class Env:
    """A manager wired to fakes, with controllable balances."""

    def __init__(self, tmp_path: Path, safes: t.Optional[t.Dict] = None) -> None:
        """Wire a manager to fakes under `tmp_path`."""
        self.balances: t.Dict[t.Tuple[Chain, str], int] = {}
        self.wallet = MagicMock()
        self.wallet.address = EOA
        self.wallet.safes = safes if safes is not None else {}
        self.wallet.get_balance.side_effect = (
            lambda chain, asset=NATIVE, from_safe=True: self.balances.get(
                (chain, asset), 0
            )
        )
        self.wallet.create_safe_and_transfer_excess.return_value = {
            "status": CreateSafeStatus.SAFE_CREATED_TRANSFER_COMPLETED,
            "safe": SAFE,
            "create_tx": "0x" + "5" * 64,
            "transfer_txs": {},
            "transfer_errors": {},
            "message": "ok",
        }
        self.wallet.clear_delegation.return_value = "0x" + "c1" * 32
        wallet_manager = MagicMock()
        wallet_manager.load.return_value = self.wallet
        self.bridge = FakeBridge()
        self.funding_manager = MagicMock()
        self.funding_manager.master_eoa_lock = threading.Lock()
        self.service = MagicMock()
        self.service.home_chain = "polygon"
        service_manager = MagicMock()
        service_manager.load.return_value = self.service
        self.service_manager = service_manager
        self.sender = MagicMock()
        self.sender.prepare_batch.return_value = PreparedUserOperation(
            user_op={},
            user_op_hash="0x" + "0f" * 32,
            authorization_nonce=3,
            nonce=4,
            block_number=100,
        )
        self.sender.wait_for_tx_hash.return_value = "0x" + "1a" * 32
        self.sender.get_user_op_receipt.return_value = None
        self.sender.user_op_known.return_value = True
        self.sender.user_op_nonce_used.return_value = False
        self.sender.find_user_op_event.return_value = None
        self.sender.tx_hash_of.side_effect = GasAbstractedSender.tx_hash_of
        self.delegated = True
        self.sender.delegation_of.side_effect = lambda chain: (
            "0xdelegate" if self.delegated else None
        )

        def _clear(chain: Chain) -> str:
            self.delegated = False
            return "0x" + "c1" * 32

        self.wallet.clear_delegation.side_effect = _clear
        self.logger = MagicMock()
        self.manager = FundingRunManager(
            path=tmp_path / "funding_runs",
            wallet_manager=wallet_manager,
            bridge_manager=t.cast(t.Any, self.bridge),
            funding_manager=self.funding_manager,
            service_manager=lambda: service_manager,
            logger=self.logger,
            gas_abstracted_sender=lambda wallet: self.sender,
        )

    def reload(self, run: FundingRun) -> FundingRun:
        """Round-trip through disk."""
        return self.manager.load(run.id)

    def tick_until(
        self, run: FundingRun, status: FundingRunStatus, n: int = 20
    ) -> FundingRun:
        """Tick until the run reaches `status`."""
        for _ in range(n):
            self.manager.tick()
            run = self.reload(run)
            if run.status == status:
                return run
        raise AssertionError(f"{run.id} stuck in {run.status}: {run.steps}")


def _logged(env: Env, detail: str) -> bool:
    """Whether the manager logged `detail`; user-facing messages never carry it."""
    return any(detail in str(call) for call in env.logger.method_calls)


@pytest.fixture(autouse=True)
def _no_rpc() -> t.Iterator[None]:
    ledger_api = MagicMock()
    ledger_api.try_get_gas_pricing.return_value = {"maxFeePerGas": 1}
    with (
        patch(f"{MODULE}.get_default_ledger_api", return_value=ledger_api),
        patch(f"{MODULE}.get_asset_decimals", return_value=6),
    ):
        yield


def _required(run: FundingRun) -> int:
    assert run.required_amount is not None
    return int(run.required_amount)


def _gnosis_legs(run: FundingRun) -> t.Dict[str, int]:
    """Amount per token the source leg delivers to Gnosis."""
    return {
        r.params["to"]["token"]: r.params["to"]["amount"]
        for r in run.source_requests
        if r.params["to"]["chain"] == "gnosis"
    }


def _gnosis_overhead(n_assets: int) -> int:
    """Safe-step gas without a Safe plus the full Gnosis reserve, at gas price 1."""
    return 100_000 * (n_assets + 1) + 1_000_000 + GNOSIS_RESERVE


def _overhead(n_assets: int, with_safe: bool = False, eoa_native: int = 0) -> int:
    gas = 100_000 * (n_assets + 1) + (0 if with_safe else 1_000_000)
    return gas * 1 + max(0, POLYGON_RESERVE - eoa_native)


def _deposit_run(
    env: Env,
    source_chain: str = "base",
    source_token: str = BASE_USDC,
    amounts: t.Optional[t.Dict[str, int]] = None,
    destination_chain: str = "polygon",
) -> FundingRun:
    return env.manager.create_run(
        mode="deposit",
        source_chain=source_chain,
        source_token=source_token,
        destination_chain=destination_chain,
        deposit_amounts=amounts or {POLYGON_OLAS: 40, POLYGON_PUSD: 10},
    )


# ---------------------------------------------------------------------------
# Quote arithmetic
# ---------------------------------------------------------------------------


class TestQuote:
    """Targets -> swaps -> source leg + gas allowance."""

    def test_usdc_source_quote_arithmetic(self, tmp_path: Path) -> None:
        """Swaps' carrier + native gas, overhead, clearing reserve and $1 cap add up."""
        env = Env(tmp_path)

        run = _deposit_run(env)

        # Two swaps USDC->OLAS/pUSD on Polygon: carrier 40+10, native 2*GAS.
        native = 2 * GAS + _overhead(n_assets=3)
        clear = CLEAR_DELEGATION_GAS_RESERVE[Chain.BASE]
        # Source leg: carrier, native and (b2) clearing reserve, each GAS extra.
        assert run.required_amount == (
            50 + native + clear + GAS_ABSTRACTION_USDC_CAP[Chain.BASE]
        )
        kinds = [s.kind for s in run.steps]
        assert kinds == [
            FundingStepKind.RECEIVE,
            FundingStepKind.BRIDGE,
            FundingStepKind.NATIVE,
            FundingStepKind.SWAP,
            FundingStepKind.SWAP,
            FundingStepKind.SAFE_AND_TRANSFER,
            FundingStepKind.CLEAR_DELEGATION,
        ]
        assert all(p.get("explicit_deposit") for p in env.bridge.quoted[2:])
        assert run.status == FundingRunStatus.AWAITING_DEPOSIT

    def test_clearing_reserve_only_for_usdc_source_off_chain(
        self, tmp_path: Path
    ) -> None:
        """(b2) exists only for a USDC source on a chain other than the destination."""
        usdc_cross = Env(tmp_path / "a")
        _deposit_run(usdc_cross)
        native_cross = Env(tmp_path / "b")
        _deposit_run(native_cross, source_token=NATIVE)
        usdc_same = Env(tmp_path / "c")
        _deposit_run(usdc_same, source_chain="polygon", source_token=POLYGON_USDC)

        def _same_chain_native(env: Env, chain: str) -> t.List[t.Dict]:
            return [
                p
                for p in env.bridge.quoted
                if p["from"]["chain"] == chain == p["to"]["chain"]
                and p["to"]["token"] == NATIVE
            ]

        assert len(_same_chain_native(usdc_cross, "base")) == 1
        assert _same_chain_native(native_cross, "base") == []
        # Same chain: the native request lands on the source chain already.
        assert not any(
            s.kind == FundingStepKind.CLEAR_DELEGATION and s.request_ids
            for s in usdc_same.reload(
                usdc_same.manager.active_run()  # type: ignore[arg-type]
            ).steps
        )

    def test_native_source_single_bridge_request(self, tmp_path: Path) -> None:
        """A native source bridges native only; no gas cap, no clearing step."""
        env = Env(tmp_path)

        run = _deposit_run(env, source_token=NATIVE)

        assert [
            s.id
            for s in run.steps
            if s.kind in (FundingStepKind.BRIDGE, FundingStepKind.NATIVE)
        ] == [STEP_BRIDGE]
        assert not any(s.id == STEP_CLEAR_DELEGATION for s in run.steps)
        # carrier POL: swaps need 40+GAS and 10+GAS native.
        native = 50 + 2 * GAS + _overhead(n_assets=3)
        assert run.required_amount == native + GAS

    def test_existing_source_balance_counts_as_received(self, tmp_path: Path) -> None:
        """USDC already in the Master EOA on the source chain nets the quote."""
        env = Env(tmp_path)
        env.balances[(Chain.BASE, BASE_USDC)] = 1_000

        run = _deposit_run(env)
        body = env.manager.run_json(run)

        assert body["quote"]["received_amount"] == "1000"
        assert int(body["quote"]["outstanding_amount"]) == _required(run) - 1000

    def test_same_chain_native_partial_deposit_is_not_double_counted(
        self, tmp_path: Path
    ) -> None:
        """A partial native deposit on the destination chain still owes the reserve."""
        env = Env(tmp_path)
        run = _deposit_run(
            env, source_chain="polygon", source_token=NATIVE, amounts={NATIVE: 100}
        )
        required = _required(run)
        assert required == 100 + _overhead(n_assets=1)

        env.balances[(Chain.POLYGON, NATIVE)] = POLYGON_RESERVE
        env.manager.refresh_quote(run.id)
        run = env.reload(run)

        assert _required(run) == required
        assert int(run.received_amount) == POLYGON_RESERVE

    def test_same_chain_deposit_ignores_held_balance(self, tmp_path: Path) -> None:
        """A deposit adds its amounts: USDC already held neither nets nor pays for it."""
        env = Env(tmp_path)
        env.balances[(Chain.POLYGON, POLYGON_USDC)] = 50

        run = _deposit_run(
            env,
            source_chain="polygon",
            source_token=POLYGON_USDC,
            amounts={POLYGON_USDC: 100},
        )
        assert run.net_targets == {POLYGON_USDC: 100}
        assert int(run.received_amount) == 0

        env.balances[(Chain.POLYGON, POLYGON_USDC)] = 50 + _required(run) - 1
        env.manager.tick()
        assert env.reload(run).status == FundingRunStatus.AWAITING_DEPOSIT

        env.balances[(Chain.POLYGON, POLYGON_USDC)] = 50 + _required(run)
        env.manager.tick()
        assert env.reload(run).status == FundingRunStatus.PROCESSING

    def test_same_chain_deposit_ignores_held_source_token(self, tmp_path: Path) -> None:
        """Held USDC does not pay for a deposit of other tokens either."""
        env = Env(tmp_path)
        env.balances[(Chain.POLYGON, POLYGON_USDC)] = 30

        run = _deposit_run(env, source_chain="polygon", source_token=POLYGON_USDC)

        assert int(run.received_amount) == 0

    def test_same_chain_onboard_unnetted_balance_counts_as_received(
        self, tmp_path: Path
    ) -> None:
        """Onboarding: same-chain source funds no target counted still count."""
        env = Env(tmp_path)
        env.balances[(Chain.POLYGON, POLYGON_USDC)] = 30
        env.funding_manager.destination_targets.return_value = {POLYGON_OLAS: 5}

        run = env.manager.create_run(
            mode="onboard",
            source_chain="polygon",
            source_token=POLYGON_USDC,
            destination_chain="polygon",
            service_config_id="sc-1",
        )

        assert int(run.received_amount) == 30

    def test_onboard_overhead_leaves_reserve_to_refill_requirements(
        self, tmp_path: Path
    ) -> None:
        """Onboarding adds only transfer gas: the reserve and Safe gas are in the targets."""
        env = Env(tmp_path)
        env.funding_manager.destination_targets.return_value = {POLYGON_OLAS: 5}

        run = env.manager.create_run(
            mode="onboard",
            source_chain="base",
            source_token=BASE_USDC,
            destination_chain="polygon",
            service_config_id="sc-1",
        )

        # One swap (GAS native) plus the transfer gas of the other modes, with
        # no reserve or Safe-creation term.
        assert run.step(STEP_NATIVE).amount == GAS + _overhead(
            n_assets=2, with_safe=True, eoa_native=POLYGON_RESERVE
        )

    def test_run_json_names_the_onboarded_service(self, tmp_path: Path) -> None:
        """An onboard run reports its service; other modes report none."""
        env = Env(tmp_path)
        env.funding_manager.destination_targets.return_value = {POLYGON_OLAS: 5}

        onboard = env.manager.create_run(
            mode="onboard",
            source_chain="base",
            source_token=BASE_USDC,
            destination_chain="polygon",
            service_config_id="sc-1",
        )
        assert env.manager.run_json(onboard)["service_config_id"] == "sc-1"

        deposit = _deposit_run(env)
        assert env.manager.run_json(deposit)["service_config_id"] is None

    def test_quote_failure_sets_quote_failed(self, tmp_path: Path) -> None:
        """A failed Relay quote leaves the run in QUOTE_FAILED with a message."""
        env = Env(tmp_path)
        env.bridge.fail_quote = True

        run = _deposit_run(env)

        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert run.quote_message == MESSAGE_QUOTE_FAILED
        assert _logged(env, "no route")

    def test_unroutable_target_fails_the_quote_without_asking_relay(
        self, tmp_path: Path
    ) -> None:
        """OLAS on Mode has no route: QUOTE_FAILED names it, and nothing is quoted."""
        env = Env(tmp_path)

        run = env.manager.create_run(
            mode="deposit",
            source_chain="base",
            source_token=BASE_USDC,
            destination_chain="mode",
            deposit_amounts={OLAS[Chain.MODE]: 10},
        )

        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert run.quote_message == "OLAS can't be delivered to Mode yet"
        assert env.bridge.quoted == []
        assert _logged(env, "No route into")

    def test_gnosis_olas_is_bought_with_native_not_the_carrier(
        self, tmp_path: Path
    ) -> None:
        """The Balancer OLAS pool takes xDAI: the source leg delivers xDAI only."""
        env = Env(tmp_path)

        run = _deposit_run(
            env, destination_chain="gnosis", amounts={OLAS[Chain.GNOSIS]: 10}
        )

        assert run.status == FundingRunStatus.AWAITING_DEPOSIT
        (swap,) = run.swap_requests
        assert swap.params["from"]["token"] == NATIVE
        assert swap.params["to"]["token"] == OLAS[Chain.GNOSIS]
        assert list(_gnosis_legs(run)) == [NATIVE]
        assert [
            r.params["to"]["chain"]
            for r in run.source_requests
            if r.params["to"]["chain"] != "gnosis"
        ] == ["base"]
        assert [
            s.kind
            for s in run.steps
            if s.kind in (FundingStepKind.BRIDGE, FundingStepKind.NATIVE)
        ] == [FundingStepKind.NATIVE]

    def test_gnosis_native_leg_covers_the_olas_swap(self, tmp_path: Path) -> None:
        """The bridged xDAI pays the swap's value and gas plus the Safe step."""
        env = Env(tmp_path)

        run = _deposit_run(
            env, destination_chain="gnosis", amounts={OLAS[Chain.GNOSIS]: 10}
        )

        assert _gnosis_legs(run) == {NATIVE: 10 + GAS + _gnosis_overhead(n_assets=2)}

    def test_gnosis_mixed_targets_split_native_and_carrier(
        self, tmp_path: Path
    ) -> None:
        """OLAS comes from native, USDC.e from the carrier; neither pays for the other."""
        env = Env(tmp_path)

        run = _deposit_run(
            env,
            destination_chain="gnosis",
            amounts={OLAS[Chain.GNOSIS]: 10, GNOSIS_USDC_E: 5},
        )

        sources = {
            r.params["to"]["token"]: r.params["from"]["token"]
            for r in run.swap_requests
        }
        assert sources == {OLAS[Chain.GNOSIS]: NATIVE, GNOSIS_USDC_E: GNOSIS_USDC}
        assert _gnosis_legs(run) == {
            GNOSIS_USDC: 5,
            NATIVE: 10 + 2 * GAS + _gnosis_overhead(n_assets=3),
        }

    def test_gnosis_native_source_needs_no_source_leg(self, tmp_path: Path) -> None:
        """Gnosis xDAI is sent straight to the swap: no bridge request."""
        env = Env(tmp_path)

        run = _deposit_run(
            env,
            source_chain="gnosis",
            source_token=NATIVE,
            destination_chain="gnosis",
            amounts={OLAS[Chain.GNOSIS]: 10},
        )

        assert run.source_requests == []
        (swap,) = run.swap_requests
        assert swap.params["from"]["token"] == NATIVE
        assert _required(run) == 10 + GAS + _gnosis_overhead(n_assets=2)

    def test_gnosis_onboard_buys_olas_with_native(self, tmp_path: Path) -> None:
        """Onboarding a Gnosis staker routes OLAS through the native pool too."""
        env = Env(tmp_path)
        env.service.home_chain = "gnosis"
        env.funding_manager.destination_targets.return_value = {OLAS[Chain.GNOSIS]: 10}

        run = env.manager.create_run(
            mode="onboard",
            source_chain="base",
            source_token=BASE_USDC,
            destination_chain="gnosis",
            service_config_id="sc-1",
        )

        assert run.status == FundingRunStatus.AWAITING_DEPOSIT
        (swap,) = run.swap_requests
        assert swap.params["from"]["token"] == NATIVE
        # Onboarding adds only transfer gas: the reserve is in the targets.
        assert _gnosis_legs(run) == {NATIVE: 10 + GAS + 100_000 * 3}

    def test_gnosis_olas_run_completes(self, tmp_path: Path) -> None:
        """The OLAS swap runs after the native leg and the run completes."""
        env = Env(tmp_path)
        run = _deposit_run(
            env, destination_chain="gnosis", amounts={OLAS[Chain.GNOSIS]: 10}
        )
        env.balances[(Chain.BASE, BASE_USDC)] = _required(run)
        for token in (NATIVE, OLAS[Chain.GNOSIS]):
            env.bridge.outcomes[token] = ProviderRequestStatus.EXECUTION_DONE

        run = env.tick_until(run, FundingRunStatus.COMPLETED)

        assert env.bridge.executed == [OLAS[Chain.GNOSIS]]
        assert run.step(f"{SWAP_STEP_PREFIX}{OLAS[Chain.GNOSIS]}").status == (
            FundingStepStatus.DONE
        )


# ---------------------------------------------------------------------------
# Targets per mode
# ---------------------------------------------------------------------------


class TestTargets:
    """deposit / signer_gas / onboard targets."""

    def test_deposit_amounts_are_added_not_netted(self, tmp_path: Path) -> None:
        """Every entered amount is delivered, whatever the wallet already holds."""
        env = Env(tmp_path)
        env.balances[(Chain.POLYGON, POLYGON_OLAS)] = 50

        run = _deposit_run(env)

        assert (
            run.gross_targets == run.net_targets == {POLYGON_OLAS: 40, POLYGON_PUSD: 10}
        )
        assert [s.token for s in run.steps if s.kind == FundingStepKind.SWAP] == [
            POLYGON_OLAS,
            POLYGON_PUSD,
        ]

    def test_all_zero_targets_complete_immediately(self, tmp_path: Path) -> None:
        """Nothing to add: COMPLETED with an empty plan and to_receive."""
        env = Env(tmp_path)

        run = _deposit_run(env, amounts={POLYGON_OLAS: 0, POLYGON_PUSD: 0})
        body = env.manager.run_json(run)

        assert run.status == FundingRunStatus.COMPLETED
        assert body["to_receive"] == []
        assert body["steps"] == []
        assert env.bridge.quoted == []
        assert env.manager.active_run().id == run.id  # type: ignore[union-attr]

    def test_signer_gas_targets_eoa_reserve_without_safe_step(
        self, tmp_path: Path
    ) -> None:
        """signer_gas tops up DEFAULT_EOA_TOPUPS in the Master EOA; no Safe step."""
        env = Env(tmp_path)
        env.balances[(Chain.POLYGON, NATIVE)] = 1

        run = env.manager.create_run(
            mode="signer_gas",
            source_chain="base",
            source_token=NATIVE,
            destination_chain="polygon",
        )

        assert run.gross_targets == {NATIVE: POLYGON_RESERVE}
        assert run.net_targets == {NATIVE: POLYGON_RESERVE - 1}
        assert not any(s.id == STEP_SAFE for s in run.steps)
        assert env.manager.run_json(run)["destination"]["wallet"] == "master_eoa"

    def test_signer_gas_native_home_chain_completes_on_receipt(
        self, tmp_path: Path
    ) -> None:
        """A native deposit on the home chain is itself the top-up."""
        env = Env(tmp_path)

        run = env.manager.create_run(
            mode="signer_gas",
            source_chain="polygon",
            source_token=NATIVE,
            destination_chain="polygon",
        )
        assert [s.id for s in run.steps] == [STEP_RECEIVE]
        assert env.bridge.quoted == []

        env.balances[(Chain.POLYGON, NATIVE)] = POLYGON_RESERVE
        run = env.tick_until(run, FundingRunStatus.COMPLETED)
        assert run.step(STEP_RECEIVE).status == FundingStepStatus.DONE

    @pytest.mark.parametrize("with_safe", [False, True])
    def test_signer_gas_same_chain_native_asks_only_the_shortfall(
        self, tmp_path: Path, with_safe: bool
    ) -> None:
        """The existing balance nets the target once: R-B completes the top-up."""
        env = Env(tmp_path, safes={Chain.POLYGON: SAFE} if with_safe else {})
        existing = POLYGON_RESERVE * 3 // 4
        env.balances[(Chain.POLYGON, NATIVE)] = existing

        run = env.manager.create_run(
            mode="signer_gas",
            source_chain="polygon",
            source_token=NATIVE,
            destination_chain="polygon",
        )
        assert _required(run) == POLYGON_RESERVE - existing

        env.manager.tick()
        assert env.reload(run).status == FundingRunStatus.AWAITING_DEPOSIT

        env.balances[(Chain.POLYGON, NATIVE)] = POLYGON_RESERVE
        env.tick_until(run, FundingRunStatus.COMPLETED)

    def test_onboard_uses_service_targets_on_home_chain(self, tmp_path: Path) -> None:
        """Onboarding nets through FundingManager.destination_targets."""
        env = Env(tmp_path)
        env.funding_manager.destination_targets.return_value = {POLYGON_OLAS: 5}

        run = env.manager.create_run(
            mode="onboard",
            source_chain="base",
            source_token=BASE_USDC,
            destination_chain="polygon",
            service_config_id="sc-1",
        )

        assert run.net_targets == {POLYGON_OLAS: 5}
        env.funding_manager.destination_targets.assert_called_once_with(env.service)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {
                "mode": "onboard",
                "destination_chain": "gnosis",
                "service_config_id": "sc-1",
            },
            {"mode": "onboard", "destination_chain": "polygon"},
            {"mode": "deposit", "destination_chain": "polygon"},
            {
                "mode": "deposit",
                "destination_chain": "polygon",
                "source_token": "0x" + "9" * 40,
            },
            {"mode": "deposit", "destination_chain": "polygon", "source_chain": "celo"},
            {"mode": "nope", "destination_chain": "polygon"},
            {
                "mode": "deposit",
                "destination_chain": "polygon",
                "deposit_amounts": {NATIVE: 1},
                "backup_owner": "not-an-address",
            },
            {"mode": "deposit", "destination_chain": "polygon", "deposit_amounts": [1]},
            {
                "mode": "deposit",
                "destination_chain": "polygon",
                # Not an asset the Safe step sweeps into the Master Safe.
                "deposit_amounts": {"0x" + "9" * 40: 1},
            },
            {
                "mode": "deposit",
                "destination_chain": "polygon",
                "deposit_amounts": {POLYGON_OLAS: "not-a-number"},
            },
            {
                "mode": "deposit",
                "destination_chain": "polygon",
                "deposit_amounts": {POLYGON_OLAS: -1},
            },
            # JSON 1e999 parses as inf, and int(inf) overflows.
            {
                "mode": "deposit",
                "destination_chain": "polygon",
                "deposit_amounts": {POLYGON_OLAS: float("inf")},
            },
            # A valid Chain without a Master EOA reserve profile.
            {
                "mode": "deposit",
                "destination_chain": "local",
                "deposit_amounts": {NATIVE: 1},
            },
        ],
    )
    def test_invalid_requests_are_rejected(
        self, tmp_path: Path, kwargs: t.Dict
    ) -> None:
        """Wrong chain/token, missing ids or amounts are 400s."""
        env = Env(tmp_path)
        params = {
            "source_chain": "base",
            "source_token": BASE_USDC,
            "deposit_amounts": None,
            **kwargs,
        }
        with pytest.raises(FundingRunError):
            env.manager.create_run(**params)

    @pytest.mark.parametrize("service_config_id", ["../../keys", "sc 1", 123])
    def test_unsafe_service_config_id_is_rejected_before_any_lookup(
        self, tmp_path: Path, service_config_id: t.Any
    ) -> None:
        """The id reaches a filesystem path, so only safe identifiers pass."""
        env = Env(tmp_path)

        with pytest.raises(FundingRunError):
            env.manager.create_run(
                mode="onboard",
                source_chain="base",
                source_token=BASE_USDC,
                destination_chain="polygon",
                service_config_id=service_config_id,
            )
        env.service_manager.exists.assert_not_called()
        env.service_manager.load.assert_not_called()


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


class TestMonitor:
    """Deposit detection."""

    def test_partial_receipt_reduces_outstanding(self, tmp_path: Path) -> None:
        """Received grows with the Master EOA balance; the run keeps waiting."""
        env = Env(tmp_path)
        run = _deposit_run(env)

        env.balances[(Chain.BASE, BASE_USDC)] = 100
        env.manager.tick()
        run = env.reload(run)

        body = env.manager.run_json(run)
        assert run.status == FundingRunStatus.AWAITING_DEPOSIT
        assert body["quote"]["received_amount"] == "100"
        assert int(body["quote"]["outstanding_amount"]) == _required(run) - 100

    def test_wrong_token_or_chain_never_processes(self, tmp_path: Path) -> None:
        """Only the chosen token on the chosen chain counts as received."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        env.balances[(Chain.BASE, NATIVE)] = 10**30
        env.balances[(Chain.POLYGON, POLYGON_USDC)] = 10**30

        env.manager.tick()

        assert env.reload(run).status == FundingRunStatus.AWAITING_DEPOSIT

    def test_final_requote_shortfall_returns_to_waiting(self, tmp_path: Path) -> None:
        """If the final quote grew past the deposit, the run keeps waiting."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        env.balances[(Chain.BASE, BASE_USDC)] = _required(run)
        # The final quote sees a bigger target (price moved).
        original = env.manager._quote  # pylint: disable=protected-access

        def _bigger(r: FundingRun) -> None:
            r.net_targets[POLYGON_OLAS] = BigInt(r.net_targets[POLYGON_OLAS] + 1_000)
            original(r)

        with patch.object(env.manager, "_quote", side_effect=_bigger):
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.AWAITING_DEPOSIT
        assert run.step(STEP_RECEIVE).status == FundingStepStatus.PENDING

    def test_full_receipt_starts_processing(self, tmp_path: Path) -> None:
        """Full receipt freezes the plan and marks RECEIVE done."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        env.balances[(Chain.BASE, BASE_USDC)] = _required(run)

        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.step(STEP_RECEIVE).status == FundingStepStatus.DONE


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _funded(env: Env, **kwargs: t.Any) -> FundingRun:
    run = _deposit_run(env, **kwargs)
    env.balances[(Chain(run.source_chain), run.source_token)] = _required(run)
    env.manager.tick()
    return env.reload(run)


def _all_succeed(env: Env) -> None:
    for token in (POLYGON_USDC, NATIVE, POLYGON_OLAS, POLYGON_PUSD):
        env.bridge.outcomes[token] = ProviderRequestStatus.EXECUTION_DONE


class TestExecution:
    """Source leg, swaps, Safe step and delegation clearing."""

    def test_usdc_run_end_to_end(self, tmp_path: Path) -> None:
        """One UserOp for the whole source leg, then swaps, Safe, clearing."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        source_requests = list(run.source_requests)

        run = env.tick_until(run, FundingRunStatus.COMPLETED)

        env.sender.prepare_batch.assert_called_once()
        (chain, calls), _ = env.sender.prepare_batch.call_args
        assert chain == Chain.BASE
        # Carrier, native, then the clearing reserve, each request's own tx.
        assert [
            (r.params["to"]["chain"], r.params["to"]["token"]) for r in source_requests
        ] == [
            ("polygon", POLYGON_USDC),
            ("polygon", NATIVE),
            ("base", NATIVE),
        ]
        assert calls == [
            Call(target=tx["to"], value=tx["value"], data=tx["data"])
            for tx in map(_deposit_tx, source_requests)
        ]
        assert len({c.data for c in calls}) == 3
        env.sender.submit.assert_called_once_with(
            Chain.BASE, env.sender.prepare_batch.return_value
        )
        assert run.user_op_hash == "0x" + "0f" * 32
        assert run.user_op_nonce == 4
        assert run.source_tx_hash == "0x" + "1a" * 32
        assert run.delegation_auth_nonce == 3
        assert env.bridge.executed == [POLYGON_OLAS, POLYGON_PUSD]
        env.wallet.create_safe_and_transfer_excess.assert_called_once_with(
            chain=Chain.POLYGON, backup_owner=None
        )
        env.wallet.clear_delegation.assert_called_once_with(Chain.BASE)
        assert run.delegation_cleared is True
        assert run.step(STEP_CLEAR_DELEGATION).status == FundingStepStatus.DONE
        body = env.manager.run_json(run)
        assert all(s["status"] == "DONE" for s in body["steps"])
        assert env.manager.active_run().id == run.id  # type: ignore[union-attr]

    def test_state_round_trips_through_disk_at_every_transition(
        self, tmp_path: Path
    ) -> None:
        """What a fresh manager loads after each tick is the run the tick left in memory."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        stored: t.List[FundingRun] = []
        real_store = FundingRunManager._store  # pylint: disable=protected-access

        def _spy(r: FundingRun) -> None:
            stored.append(r)
            real_store(r)

        seen = set()
        with patch.object(env.manager, "_store", side_effect=_spy):
            for _ in range(20):
                stored.clear()
                env.manager.tick()
                in_memory = [r for r in stored if r.id == run.id][-1]
                fresh = Env(tmp_path).manager.load(run.id)
                assert fresh.json == in_memory.json
                seen.add(fresh.status)
                if fresh.status == FundingRunStatus.COMPLETED:
                    break
        assert seen >= {FundingRunStatus.PROCESSING, FundingRunStatus.COMPLETED}

    def test_restart_with_recorded_user_op_reconciles_without_resend(
        self, tmp_path: Path
    ) -> None:
        """A UserOp hash persisted before a crash is looked up, never resubmitted."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.submit.side_effect = _Crash()
        with pytest.raises(_Crash):
            env.manager.tick()  # the process dies between persisting and submitting
        run = env.reload(run)
        assert run.user_op_hash
        assert not run.source_tx_hash

        restarted = Env(tmp_path)
        restarted.sender.get_user_op_receipt.return_value = {
            "success": True,
            "receipt": {"transactionHash": "0x" + "2b" * 32},
        }
        restarted.manager.reconcile()
        restarted.manager.tick()

        run = restarted.reload(run)
        restarted.sender.submit.assert_not_called()
        restarted.sender.prepare_batch.assert_not_called()
        assert run.status == FundingRunStatus.PROCESSING
        assert run.source_tx_hash == "0x" + "2b" * 32
        assert all(
            r.execution_data is not None
            and r.execution_data.from_tx_hash == "0x" + "2b" * 32
            for r in run.source_requests
        )

    def test_reverted_user_op_fails_with_its_reason_and_records_nothing(
        self, tmp_path: Path
    ) -> None:
        """success=false fails the leg with the revert reason; no request counts as sent."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.wait_for_tx_hash.side_effect = GasAbstractionError("timed out")
        env.manager.tick()
        env.sender.get_user_op_receipt.return_value = {
            "success": False,
            "reason": "AA33 reverted",
            "userOpHash": "0x" + "0f" * 32,
            "receipt": {"transactionHash": "0x" + "3c" * 32},
        }

        with patch.object(env.bridge.provider, "record_external_execution") as record:
            env.manager.tick()

        run = env.reload(run)
        record.assert_not_called()
        assert run.status == FundingRunStatus.FAILED
        assert run.error is not None
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": "Couldn't bridge to Polygon",
        }
        assert _logged(env, "AA33 reverted")
        assert run.source_tx_hash is None
        assert all(r.execution_data is None for r in run.source_requests)

    def test_receipt_lookup_error_keeps_waiting(self, tmp_path: Path) -> None:
        """A bundler lookup error is "unknown": the leg waits, then records the receipt."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.wait_for_tx_hash.side_effect = GasAbstractionError("timed out")
        env.manager.tick()
        env.sender.get_user_op_receipt.side_effect = GasAbstractionError("503")

        later = int(time.time()) + RECEIPT_TIMEOUT + 60
        with patch(f"{MODULE}._now", return_value=later):
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.error is None
        assert run.step(STEP_BRIDGE).status == FundingStepStatus.PROCESSING
        env.sender.user_op_known.assert_not_called()

        env.sender.get_user_op_receipt.side_effect = None
        env.sender.get_user_op_receipt.return_value = {
            "success": True,
            "receipt": {"transactionHash": "0x" + "4d" * 32},
        }
        env.manager.tick()

        assert env.reload(run).source_tx_hash == "0x" + "4d" * 32
        env.sender.prepare_batch.assert_called_once()

    def test_lost_user_op_fails_only_once_overdue_and_dropped(
        self, tmp_path: Path
    ) -> None:
        """No receipt: wait; overdue but still pending: keep waiting; dropped: fail."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.wait_for_tx_hash.side_effect = GasAbstractionError("timed out")
        env.manager.tick()  # submitted, no receipt yet

        env.manager.tick()
        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        env.sender.user_op_known.assert_not_called()

        later = int(time.time()) + max(RECEIPT_TIMEOUT, SLOW_STEP_MIN_SECONDS) + 60
        with patch(f"{MODULE}._now", return_value=later):
            env.manager.tick()
        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.step(STEP_BRIDGE).is_slow is True
        env.sender.user_op_known.assert_called_with(Chain.BASE, "0x" + "0f" * 32)
        env.sender.user_op_nonce_used.assert_called_with(Chain.BASE, 4)

        env.sender.user_op_known.return_value = False
        with patch(f"{MODULE}._now", return_value=later):
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": "Couldn't bridge to Polygon",
        }
        assert _logged(env, f"UserOperation {run.user_op_hash} was not included.")

    def test_used_nonce_without_receipt_is_recorded_from_the_entrypoint_event(
        self, tmp_path: Path
    ) -> None:
        """A used nonce whose bundler receipt is missing is found in the EntryPoint logs."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.wait_for_tx_hash.side_effect = GasAbstractionError("timed out")
        env.manager.tick()
        env.sender.user_op_known.return_value = False
        env.sender.user_op_nonce_used.return_value = True
        env.sender.find_user_op_event.return_value = {
            "success": True,
            "receipt": {"transactionHash": "0x" + "7a" * 32},
        }

        later = int(time.time()) + RECEIPT_TIMEOUT + 60
        with patch(f"{MODULE}._now", return_value=later):
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.source_tx_hash == "0x" + "7a" * 32
        env.sender.find_user_op_event.assert_called_once_with(
            Chain.BASE, "0x" + "0f" * 32, 100
        )

    def test_used_nonce_without_any_record_keeps_waiting(self, tmp_path: Path) -> None:
        """A used nonce with no receipt and no event is unknown, never dropped."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.wait_for_tx_hash.side_effect = GasAbstractionError("timed out")
        env.manager.tick()
        env.sender.user_op_known.return_value = False
        env.sender.user_op_nonce_used.return_value = True

        later = int(time.time()) + RECEIPT_TIMEOUT + 60
        with patch(f"{MODULE}._now", return_value=later):
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.error is None
        assert run.user_op_hash == "0x" + "0f" * 32

    @pytest.mark.parametrize("lookup_error", [False, True])
    def test_unresolved_user_op_fails_after_the_bound_and_retry_keeps_it(
        self, tmp_path: Path, lookup_error: bool
    ) -> None:
        """A UserOp still pending or unknown past the bound gives the user a retry."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.wait_for_tx_hash.side_effect = GasAbstractionError("timed out")
        env.manager.tick()
        if lookup_error:
            env.sender.get_user_op_receipt.side_effect = GasAbstractionError("503")

        start = t.cast(int, env.reload(run).step(STEP_BRIDGE).started_at)
        with patch(f"{MODULE}._now", return_value=start + USER_OP_RESOLUTION_TIMEOUT):
            env.manager.tick()
        assert env.reload(run).status == FundingRunStatus.PROCESSING

        with patch(
            f"{MODULE}._now", return_value=start + USER_OP_RESOLUTION_TIMEOUT + 1
        ):
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": MESSAGE_AWAITING_CONFIRMATION,
        }
        quoted = len(env.bridge.quoted)

        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert run.user_op_hash == "0x" + "0f" * 32
        assert len(env.bridge.quoted) == quoted
        env.sender.prepare_batch.assert_called_once()

    def test_unexpected_source_leg_error_fails_the_run(self, tmp_path: Path) -> None:
        """A non-GasAbstractionError from preparing the UserOp is a visible failure."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.prepare_batch.side_effect = ConnectionError("rpc unreachable")

        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": "Couldn't bridge to Polygon",
        }
        assert _logged(env, "rpc unreachable")

    def test_unexpected_safe_step_error_fails_the_run(self, tmp_path: Path) -> None:
        """An exception from the hidden Safe step surfaces on the last visible step."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.wallet.create_safe_and_transfer_excess.side_effect = ConnectionError(
            "rpc unreachable"
        )

        run = env.tick_until(run, FundingRunStatus.FAILED)

        assert run.step(STEP_SAFE).status == FundingStepStatus.FAILED
        assert run.error == {
            "step_id": f"swap:{POLYGON_PUSD}",
            "message": MESSAGE_TRANSFER_FAILED,
        }
        assert _logged(env, "rpc unreachable")

    def test_interrupted_native_send_is_not_resent(self, tmp_path: Path) -> None:
        """A native-source request marked as sending but unrecorded fails, not resends."""
        env = Env(tmp_path)
        run = _funded(env, source_token=NATIVE)
        run.sending_request_ids = [run.source_requests[0].id]
        run.step(STEP_BRIDGE).status = FundingStepStatus.PROCESSING
        run.store()

        env.manager.tick()

        run = env.reload(run)
        assert env.bridge.executed == []
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": "Couldn't bridge to Polygon",
        }

    def test_retry_after_interrupted_native_send_resends_it_once(
        self, tmp_path: Path
    ) -> None:
        """Retry is the user's go-ahead: the interrupted request is re-quoted and sent once.

        Nothing checks on-chain whether the interrupted send went out.
        """
        env = Env(tmp_path)
        run = _funded(env, source_token=NATIVE)
        interrupted = run.source_requests[0]
        run.sending_request_ids = [interrupted.id]
        run.step(STEP_BRIDGE).status = FundingStepStatus.PROCESSING
        run.store()
        env.manager.tick()
        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        quoted = len(env.bridge.quoted)

        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert run.sending_request_ids == []
        assert env.bridge.quoted[quoted:] == [interrupted.params]
        assert interrupted.id not in {r.id for r in run.source_requests}
        assert run.step(STEP_BRIDGE).status == FundingStepStatus.PENDING
        _all_succeed(env)
        env.tick_until(run, FundingRunStatus.COMPLETED)
        assert env.bridge.executed == [NATIVE, POLYGON_OLAS, POLYGON_PUSD]

    def test_retry_after_interrupted_swap_resends_it_once(self, tmp_path: Path) -> None:
        """The swap equivalent: only the interrupted swap is re-quoted and sent once."""
        env = Env(tmp_path)
        _all_succeed(env)
        run = _funded(env)
        for _ in range(5):
            env.manager.tick()
            run = env.reload(run)
            if run.step(STEP_NATIVE).status == FundingStepStatus.DONE:
                break
        swap_id = f"swap:{POLYGON_OLAS}"
        (interrupted,) = run.requests_of(run.step(swap_id))
        run.step(swap_id).status = FundingStepStatus.PROCESSING
        run.store()
        env.manager.tick()
        run = env.reload(run)
        assert run.error == {"step_id": swap_id, "message": "Couldn't get OLAS"}
        quoted = len(env.bridge.quoted)

        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert env.bridge.quoted[quoted:] == [interrupted.params]
        assert run.step(swap_id).status == FundingStepStatus.PENDING
        env.tick_until(run, FundingRunStatus.COMPLETED)
        assert env.bridge.executed == [POLYGON_OLAS, POLYGON_PUSD]
        env.sender.prepare_batch.assert_called_once()

    def test_failed_swap_retry_resumes_at_failed_step(self, tmp_path: Path) -> None:
        """Retry re-quotes only the failed swap and continues from it."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.bridge.outcomes[POLYGON_OLAS] = ProviderRequestStatus.EXECUTION_FAILED

        run = env.tick_until(run, FundingRunStatus.FAILED)
        assert run.error["step_id"] == f"swap:{POLYGON_OLAS}"  # type: ignore[index]
        with pytest.raises(FundingRunConflictError):
            env.manager.create_run(
                mode="deposit",
                source_chain="base",
                source_token=BASE_USDC,
                destination_chain="polygon",
                deposit_amounts={POLYGON_OLAS: 1},
            )

        quoted_before = len(env.bridge.quoted)
        run = env.manager.retry(run.id)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.error is None
        assert len(env.bridge.quoted) == quoted_before + 1  # only the OLAS swap
        assert run.step(f"swap:{POLYGON_OLAS}").status == FundingStepStatus.PENDING
        assert run.step(STEP_BRIDGE).status == FundingStepStatus.DONE

        env.bridge.outcomes[POLYGON_OLAS] = ProviderRequestStatus.EXECUTION_DONE

        run = env.tick_until(run, FundingRunStatus.COMPLETED)
        env.sender.prepare_batch.assert_called_once()  # source leg not resent

    def test_retry_reconciles_landed_step_instead_of_resending(
        self, tmp_path: Path
    ) -> None:
        """A failed step whose Relay fill later succeeded is not resent."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.bridge.outcomes[NATIVE] = ProviderRequestStatus.EXECUTION_FAILED
        run = env.tick_until(run, FundingRunStatus.FAILED)
        assert run.error == {"step_id": STEP_NATIVE, "message": "Couldn't get POL"}

        env.bridge.outcomes[NATIVE] = ProviderRequestStatus.EXECUTION_DONE
        quoted_before = len(env.bridge.quoted)
        run = env.manager.retry(run.id)

        assert len(env.bridge.quoted) == quoted_before
        assert run.step(STEP_NATIVE).status == FundingStepStatus.DONE

    def test_retry_keeps_unconfirmed_source_leg_failed_without_resending(
        self, tmp_path: Path
    ) -> None:
        """A deposit that landed but the bridge never confirmed is not sent twice."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.bridge.outcomes[NATIVE] = ProviderRequestStatus.EXECUTION_FAILED
        run = env.tick_until(run, FundingRunStatus.FAILED)
        env.bridge.unconfirmed.add(NATIVE)

        quoted_before = len(env.bridge.quoted)
        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_NATIVE,
            "message": MESSAGE_AWAITING_CONFIRMATION,
        }
        assert len(env.bridge.quoted) == quoted_before
        env.sender.prepare_batch.assert_called_once()
        assert env.reload(run).error == run.error

    def test_retry_keeps_unconfirmed_swap_failed_without_resending(
        self, tmp_path: Path
    ) -> None:
        """A swap that landed but was never confirmed is not re-quoted or resent."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.bridge.outcomes[POLYGON_OLAS] = ProviderRequestStatus.EXECUTION_FAILED
        run = env.tick_until(run, FundingRunStatus.FAILED)
        env.bridge.unconfirmed.add(POLYGON_OLAS)
        executed_before = list(env.bridge.executed)

        quoted_before = len(env.bridge.quoted)
        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": f"swap:{POLYGON_OLAS}",
            "message": MESSAGE_AWAITING_CONFIRMATION,
        }
        assert len(env.bridge.quoted) == quoted_before
        assert env.bridge.executed == executed_before

    def test_hidden_safe_failure_surfaces_on_last_visible_step(
        self, tmp_path: Path
    ) -> None:
        """A Safe/transfer failure is reported through the last visible step."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.wallet.create_safe_and_transfer_excess.return_value = {
            "status": CreateSafeStatus.SAFE_CREATION_FAILED,
            "safe": None,
            "create_tx": None,
            "transfer_txs": {},
            "transfer_errors": {},
            "message": "Failed to create Safe.",
        }

        run = env.tick_until(run, FundingRunStatus.FAILED)

        assert run.step(STEP_SAFE).status == FundingStepStatus.FAILED
        assert run.error == {
            "step_id": f"swap:{POLYGON_PUSD}",
            "message": MESSAGE_TRANSFER_FAILED,
        }
        assert _logged(env, "Failed to create Safe.")

    def test_clear_delegation_failure_keeps_run_completed(self, tmp_path: Path) -> None:
        """Clearing failures never fail the run and are retried in the background."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.wallet.clear_delegation.side_effect = RuntimeError("no gas")

        run = env.tick_until(run, FundingRunStatus.COMPLETED)

        assert run.error is None
        assert run.step(STEP_CLEAR_DELEGATION).status == FundingStepStatus.FAILED
        pointer = env.manager._pointer()  # pylint: disable=protected-access
        assert pointer.pending_clear_run_ids == [run.id]

        # Picked up by start-up reconciliation after a restart.
        restarted = Env(tmp_path)
        restarted.manager.reconcile()
        run = restarted.reload(run)
        assert run.delegation_cleared is True
        assert (
            restarted.manager._pointer().pending_clear_run_ids == []
        )  # pylint: disable=protected-access

    def test_processing_holds_the_master_eoa_lock(self, tmp_path: Path) -> None:
        """fund_master_eoa cannot move Master EOA funds mid-run."""
        env = Env(tmp_path)
        run = _funded(env)
        seen: t.List[bool] = []
        original = env.bridge.execute_request

        def _execute(request: ProviderRequest) -> None:
            seen.append(env.funding_manager.master_eoa_lock.locked())
            original(request)

        env.bridge.execute_request = _execute  # type: ignore[method-assign]
        _all_succeed(env)
        env.tick_until(run, FundingRunStatus.COMPLETED)
        assert seen
        assert all(seen)


# ---------------------------------------------------------------------------
# Single-run rule and lifecycle routes
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Replace, cancel, refresh, 404/409."""

    def test_create_replaces_awaiting_run(self, tmp_path: Path) -> None:
        """Using 'Change' replaces an AWAITING_DEPOSIT run."""
        env = Env(tmp_path)
        first = _deposit_run(env)
        second = _deposit_run(env, source_token=NATIVE)

        assert env.reload(first).status == FundingRunStatus.CANCELLED
        assert env.manager.active_run().id == second.id  # type: ignore[union-attr]

    def test_waiting_run_that_received_funds_is_kept(self, tmp_path: Path) -> None:
        """Neither cancel nor a new run drops a waiting run once funds arrive."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        env.balances[(Chain.BASE, BASE_USDC)] = 1

        with pytest.raises(FundingRunConflictError):
            env.manager.cancel(run.id)
        with pytest.raises(FundingRunConflictError):
            _deposit_run(env, source_token=NATIVE)

        assert env.reload(run).status == FundingRunStatus.AWAITING_DEPOSIT
        assert env.manager.active_run().id == run.id  # type: ignore[union-attr]

    def test_create_while_processing_conflicts(self, tmp_path: Path) -> None:
        """One run at a time, whatever the UI does."""
        env = Env(tmp_path)
        _funded(env)
        with pytest.raises(FundingRunConflictError):
            _deposit_run(env)

    def test_cancel_and_refresh_state_rules(self, tmp_path: Path) -> None:
        """cancel/refresh only while waiting; retry only when FAILED."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        with pytest.raises(FundingRunConflictError):
            env.manager.retry(run.id)
        count = env.bridge.quote_count + len(env.bridge.quoted)
        env.manager.refresh_quote(run.id)
        assert len(env.bridge.quoted) > count - env.bridge.quote_count
        env.manager.cancel(run.id)
        assert env.reload(run).status == FundingRunStatus.CANCELLED
        assert env.manager.active_run() is None
        with pytest.raises(FundingRunConflictError):
            env.manager.cancel(run.id)

    def test_cancel_failed_run_frees_the_slot_and_clears_delegation(
        self, tmp_path: Path
    ) -> None:
        """A step that keeps failing no longer blocks every later run."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.bridge.outcomes[POLYGON_OLAS] = ProviderRequestStatus.EXECUTION_FAILED
        run = env.tick_until(run, FundingRunStatus.FAILED)

        run = env.manager.cancel(run.id)

        assert run.status == FundingRunStatus.CANCELLED
        assert env.manager.active_run() is None
        env.manager.tick()
        env.wallet.clear_delegation.assert_called_once_with(Chain.BASE)
        assert env.reload(run).delegation_cleared is True
        assert _deposit_run(env).status == FundingRunStatus.AWAITING_DEPOSIT

    @pytest.mark.parametrize("reverted", [False, True])
    def test_cancel_failed_run_with_undelivered_user_op_does_not_wait_on_it(
        self, tmp_path: Path, reverted: bool
    ) -> None:
        """A dropped or reverted source leg never sent the clearing reserve; clearing still settles."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.submit.side_effect = GasAbstractionError("Bundler 503")
        env.manager.tick()
        assert env.reload(run).status == FundingRunStatus.FAILED
        if reverted:
            # Included: the authorization applied even though the calls reverted.
            env.sender.get_user_op_receipt.return_value = {
                "success": False,
                "reason": "AA33",
                "receipt": {"transactionHash": "0x" + "3c" * 32},
            }
        else:
            env.sender.user_op_known.return_value = False
            env.delegated = False

        env.manager.cancel(run.id)
        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.CANCELLED
        assert run.step(STEP_CLEAR_DELEGATION).status == FundingStepStatus.DONE
        assert env.wallet.clear_delegation.call_count == int(reverted)
        # pylint: disable-next=protected-access
        assert env.manager._pointer().pending_clear_run_ids == []

    def test_cancel_failed_run_refuses_while_a_user_op_may_land(
        self, tmp_path: Path
    ) -> None:
        """A UserOp the bundler still lists may yet move the deposit."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.submit.side_effect = GasAbstractionError("Bundler 503")
        env.manager.tick()
        assert env.reload(run).status == FundingRunStatus.FAILED

        with pytest.raises(FundingRunConflictError):
            env.manager.cancel(run.id)
        assert env.reload(run).status == FundingRunStatus.FAILED

    def test_cancel_failed_run_refuses_while_a_request_is_pending(
        self, tmp_path: Path
    ) -> None:
        """The bridge failed but the native request is still being filled."""
        env = Env(tmp_path)
        run = _funded(env)
        env.bridge.outcomes[POLYGON_USDC] = ProviderRequestStatus.EXECUTION_FAILED
        run = env.tick_until(run, FundingRunStatus.FAILED)
        assert run.step(STEP_NATIVE).status == FundingStepStatus.PROCESSING

        with pytest.raises(FundingRunConflictError):
            env.manager.cancel(run.id)
        assert env.reload(run).status == FundingRunStatus.FAILED

    def test_cancel_failed_run_refuses_an_unconfirmed_failure(
        self, tmp_path: Path
    ) -> None:
        """A deposit that mined but the bridge never confirmed may still deliver."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.bridge.outcomes[NATIVE] = ProviderRequestStatus.EXECUTION_FAILED
        run = env.tick_until(run, FundingRunStatus.FAILED)
        env.bridge.unconfirmed.add(NATIVE)

        with pytest.raises(FundingRunConflictError):
            env.manager.cancel(run.id)
        assert env.reload(run).status == FundingRunStatus.FAILED

    def test_unknown_run_is_not_found(self, tmp_path: Path) -> None:
        """Unknown or malformed ids are 404s."""
        env = Env(tmp_path)
        for run_id in (
            f"fr-{uuid.uuid4()}",
            "fr-missing",
            "fr-../../etc/passwd",
            "../../etc/passwd",
        ):
            with pytest.raises(FundingRunNotFoundError):
                env.manager.load(run_id)


# ---------------------------------------------------------------------------
# Validation, baselines and quoting edge cases
# ---------------------------------------------------------------------------


def _fail_source_leg_quotes(env: Env, source_chain: str, message: str) -> None:
    """Make every quote leaving `source_chain` fail while swaps still quote."""
    original = env.bridge.quote_requests

    def _quote(requests_params: t.List[t.Dict]) -> FakeBundle:
        bundle = original(requests_params)
        for request in bundle.provider_requests:
            if request.params["from"]["chain"] == source_chain:
                request.status = ProviderRequestStatus.QUOTE_FAILED
                t.cast(QuoteData, request.quote_data).message = message
        return bundle

    env.bridge.quote_requests = _quote  # type: ignore[method-assign]


class TestEdgeCases:
    """Paths off the main flow: unknown services, baselines, stale quotes, locks."""

    @pytest.mark.parametrize(
        ("read_symbol", "symbol", "message"),
        [
            ({"return_value": "FOO"}, "FOO", "Couldn't get FOO"),
            (
                {"side_effect": ValueError("execution reverted")},
                None,
                MESSAGE_TRANSFER_FAILED,
            ),
        ],
    )
    def test_unknown_token_is_named_by_its_on_chain_symbol(
        self,
        tmp_path: Path,
        read_symbol: t.Dict[str, t.Any],
        symbol: t.Optional[str],
        message: str,
    ) -> None:
        """A token outside the known maps never shows as a raw address."""
        unknown = "0x" + "c" * 40
        env = Env(tmp_path)
        env.funding_manager.destination_targets.return_value = {unknown: 5}
        _all_succeed(env)
        env.bridge.outcomes[unknown] = ProviderRequestStatus.EXECUTION_FAILED

        with patch("operate.ledger.profiles._get_erc20_symbol", **read_symbol):
            run = env.manager.create_run(
                mode="onboard",
                source_chain="base",
                source_token=BASE_USDC,
                destination_chain="polygon",
                service_config_id="sc-1",
            )
            assert env.manager.run_json(run)["to_receive"] == [
                {"token": unknown, "symbol": symbol, "amount": "5"}
            ]
            env.balances[(Chain.BASE, BASE_USDC)] = _required(run)
            run = env.tick_until(run, FundingRunStatus.FAILED)

        assert run.error == {"step_id": f"swap:{unknown}", "message": message}

    def test_onboard_unknown_service_is_rejected(self, tmp_path: Path) -> None:
        """An onboard run for a service that does not exist is a 400."""
        env = Env(tmp_path)
        env.service_manager.exists.return_value = False

        with pytest.raises(FundingRunError, match="not found"):
            env.manager.create_run(
                mode="onboard",
                source_chain="base",
                source_token=BASE_USDC,
                destination_chain="polygon",
                service_config_id="sc-1",
            )
        env.service_manager.load.assert_not_called()
        assert env.manager.active_run() is None

    def test_same_chain_native_source_baseline_is_the_reserve(
        self, tmp_path: Path
    ) -> None:
        """Onboarding: native held up to the reserve is not a deposit; above it is."""
        env = Env(tmp_path)
        env.balances[(Chain.POLYGON, NATIVE)] = POLYGON_RESERVE + 500
        env.funding_manager.destination_targets.return_value = {POLYGON_OLAS: 40}

        run = env.manager.create_run(
            mode="onboard",
            source_chain="polygon",
            source_token=NATIVE,
            destination_chain="polygon",
            service_config_id="sc-1",
        )

        assert run.receive_baseline == POLYGON_RESERVE
        assert int(run.received_amount) == 500

    def test_same_chain_deposit_baseline_is_the_full_balance(
        self, tmp_path: Path
    ) -> None:
        """Deposit: no native already held counts, not even above the reserve."""
        env = Env(tmp_path)
        env.balances[(Chain.POLYGON, NATIVE)] = POLYGON_RESERVE + 500

        run = _deposit_run(
            env,
            source_chain="polygon",
            source_token=NATIVE,
            amounts={POLYGON_OLAS: 40},
        )

        assert run.receive_baseline == POLYGON_RESERVE + 500
        assert int(run.received_amount) == 0

    def test_cross_chain_native_source_keeps_source_reserve_when_safe_exists(
        self, tmp_path: Path
    ) -> None:
        """With a Safe on the source chain, its Master EOA reserve is not "received"."""
        env = Env(tmp_path, safes={Chain.BASE: SAFE})
        base_reserve = int(DEFAULT_EOA_TOPUPS[Chain.BASE][NATIVE])
        env.balances[(Chain.BASE, NATIVE)] = base_reserve + 123

        run = _deposit_run(env, source_token=NATIVE)

        assert run.receive_baseline is None
        assert int(run.received_amount) == 123

    def test_source_leg_quote_failure_sets_quote_failed(self, tmp_path: Path) -> None:
        """Swaps quote but the source leg does not: QUOTE_FAILED with its message."""
        env = Env(tmp_path)
        _fail_source_leg_quotes(env, "base", "no source route")

        run = _deposit_run(env)

        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert run.quote_message == MESSAGE_QUOTE_FAILED
        assert _logged(env, "no source route")
        assert run.required_amount is None
        assert run.source_requests == []
        assert env.reload(run).status == FundingRunStatus.QUOTE_FAILED

    def test_quote_failed_run_requotes_only_once_stale(self, tmp_path: Path) -> None:
        """A QUOTE_FAILED run waits out the validity period, then re-quotes and recovers."""
        env = Env(tmp_path)
        env.bridge.fail_quote = True
        run = _deposit_run(env)
        assert run.status == FundingRunStatus.QUOTE_FAILED
        quoted = len(env.bridge.quoted)

        env.manager.tick()
        assert len(env.bridge.quoted) == quoted
        assert env.reload(run).status == FundingRunStatus.QUOTE_FAILED

        env.bridge.fail_quote = False
        run = env.reload(run)
        run.quoted_at = 0
        run.store()
        env.manager.tick()

        run = env.reload(run)
        assert len(env.bridge.quoted) > quoted
        assert run.status == FundingRunStatus.AWAITING_DEPOSIT
        assert run.quote_message is None
        assert run.required_amount is not None

    def test_stale_awaiting_quote_is_refreshed_on_tick(self, tmp_path: Path) -> None:
        """An AWAITING_DEPOSIT quote past its validity is re-quoted by the loop."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        run.quoted_at = 1
        run.store()
        quoted = len(env.bridge.quoted)

        env.manager.tick()

        run = env.reload(run)
        assert len(env.bridge.quoted) > quoted
        assert run.quoted_at is not None
        assert run.quoted_at > 1
        assert run.status == FundingRunStatus.AWAITING_DEPOSIT

    @pytest.mark.parametrize("pricing", [None, {}, {"maxFeePerGas": 0}])
    def test_missing_gas_price_fails_the_quote(
        self, tmp_path: Path, pricing: t.Optional[t.Dict]
    ) -> None:
        """No destination gas price is QUOTE_FAILED, not a quote that omits the Safe gas."""
        env = Env(tmp_path)
        ledger_api = MagicMock()
        ledger_api.try_get_gas_pricing.return_value = pricing
        with patch(f"{MODULE}.get_default_ledger_api", return_value=ledger_api):
            run = _deposit_run(env)

        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert run.quote_message == MESSAGE_QUOTE_FAILED
        assert _logged(env, "Unable to retrieve gas pricing on polygon.")
        assert run.required_amount is None
        assert env.reload(run).status == FundingRunStatus.QUOTE_FAILED

    @pytest.mark.parametrize("failing_chain", ["base", "polygon"])
    def test_requirements_failure_fails_the_quote(
        self, tmp_path: Path, failing_chain: str
    ) -> None:
        """A request requirements() marks failed is QUOTE_FAILED, never a zero amount."""
        env = Env(tmp_path)
        original = env.bridge.provider.requirements

        def _requirements(request: ProviderRequest) -> t.Dict:
            if request.params["from"]["chain"] != failing_chain:
                return original(request)
            # What Provider.requirements does when _get_txs raises.
            request.status = ProviderRequestStatus.QUOTE_FAILED
            t.cast(QuoteData, request.quote_data).message = "cannot build txs"
            token = request.params["from"]["token"]
            return {failing_chain: {EOA: {NATIVE: 0, token: 0}}}

        with patch.object(
            env.bridge.provider, "requirements", side_effect=_requirements
        ):
            run = _deposit_run(env, source_token=NATIVE)
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert run.quote_message == MESSAGE_QUOTE_FAILED
        assert _logged(env, "cannot build txs")
        assert run.required_amount is None
        assert run.steps == []

    def test_requirement_missing_the_token_fails_the_quote(
        self, tmp_path: Path
    ) -> None:
        """A requirements() result without the source token is QUOTE_FAILED, not 0."""
        env = Env(tmp_path)
        with patch.object(
            env.bridge.provider,
            "requirements",
            side_effect=lambda r: {r.params["from"]["chain"]: {EOA: {}}},
        ):
            run = _deposit_run(env)

        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert run.quote_message == MESSAGE_QUOTE_FAILED
        assert _logged(env, "No 0x")

    def test_busy_lock_is_a_conflict(self, tmp_path: Path) -> None:
        """A mutation that cannot take the run lock in time is refused with a 409."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        held, release = threading.Event(), threading.Event()

        def _hold() -> None:
            with env.manager._lock:  # pylint: disable=protected-access
                held.set()
                release.wait(5)

        holder = threading.Thread(target=_hold)
        holder.start()
        try:
            assert held.wait(5)
            with patch(f"{MODULE}.LOCK_TIMEOUT", 0.01):
                with pytest.raises(FundingRunConflictError, match="being processed"):
                    env.manager.cancel(run.id)
        finally:
            release.set()
            holder.join()
        assert env.reload(run).status == FundingRunStatus.AWAITING_DEPOSIT


# ---------------------------------------------------------------------------
# Execution edge cases
# ---------------------------------------------------------------------------


def _source_leg_done(env: Env, run: FundingRun) -> FundingRun:
    """Tick until both source-leg steps are DONE (no swap sent yet)."""
    for _ in range(5):
        env.manager.tick()
        run = env.reload(run)
        if all(
            s.status == FundingStepStatus.DONE
            for s in run.steps
            if s.kind in (FundingStepKind.BRIDGE, FundingStepKind.NATIVE)
        ):
            return run
    raise AssertionError(f"source leg of {run.id} not done: {run.steps}")


class TestExecutionEdgeCases:
    """Native sends, bundler errors, swap re-quotes, slow steps, clearing."""

    def test_native_source_run_sends_directly_end_to_end(self, tmp_path: Path) -> None:
        """A native source is sent as a plain transaction, never as a UserOp."""
        env = Env(tmp_path)
        run = _funded(env, source_token=NATIVE)
        _all_succeed(env)

        run = env.tick_until(run, FundingRunStatus.COMPLETED)

        assert env.bridge.executed == [NATIVE, POLYGON_OLAS, POLYGON_PUSD]
        assert run.sending_request_ids == []
        assert run.step(STEP_BRIDGE).status == FundingStepStatus.DONE
        env.sender.prepare_batch.assert_not_called()
        env.wallet.clear_delegation.assert_not_called()

    def test_pending_steps_are_processing_then_flagged_slow(
        self, tmp_path: Path
    ) -> None:
        """Unconfirmed source-leg requests keep their steps PROCESSING, then slow."""
        env = Env(tmp_path)
        run = _funded(env)
        env.manager.tick()  # UserOp sent; requests EXECUTION_PENDING
        env.manager.tick()

        run = env.reload(run)
        bridge = run.step(STEP_BRIDGE)
        assert bridge.status == FundingStepStatus.PROCESSING
        assert bridge.is_slow is False

        later = int(time.time()) + SLOW_STEP_MIN_SECONDS + 60
        with patch(f"{MODULE}._now", return_value=later):
            env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.step(STEP_BRIDGE).is_slow is True
        body = env.manager.run_json(run)
        assert {s["id"]: s["is_slow"] for s in body["steps"]}[STEP_NATIVE] is True

    def test_user_op_preparation_error_fails_the_source_leg(
        self, tmp_path: Path
    ) -> None:
        """A bundler refusal while preparing fails the leg before any hash is stored."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.prepare_batch.side_effect = GasAbstractionError("paymaster refused")

        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": "Couldn't bridge to Polygon",
        }
        assert _logged(env, "paymaster refused")
        assert run.user_op_hash is None
        env.sender.submit.assert_not_called()

    def test_rejected_submit_fails_with_bundler_message_and_retry_requotes(
        self, tmp_path: Path
    ) -> None:
        """The bundler's rejection is the error; once dropped, retry re-quotes the leg."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.submit.side_effect = GasAbstractionError(
            "Bundler eth_sendUserOperation error -32602: USDC below cap"
        )
        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": "Couldn't bridge to Polygon",
        }
        assert _logged(env, "USDC below cap")
        env.sender.wait_for_tx_hash.assert_not_called()
        old_ids = {r.id for r in run.source_requests}
        assert len(old_ids) == 3  # carrier, native, clearing reserve

        env.sender.user_op_known.return_value = False
        quoted = len(env.bridge.quoted)
        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert run.user_op_hash is None
        assert run.user_op_nonce is None
        assert run.source_tx_hash is None
        assert len(env.bridge.quoted) == quoted + 3
        assert not old_ids & {r.id for r in run.source_requests}
        assert not old_ids & set(run.step(STEP_CLEAR_DELEGATION).request_ids)
        assert run.step(STEP_BRIDGE).status == FundingStepStatus.PENDING
        assert run.step(STEP_NATIVE).status == FundingStepStatus.PENDING

        env.sender.submit.side_effect = None
        _all_succeed(env)
        env.tick_until(run, FundingRunStatus.COMPLETED)
        assert env.sender.prepare_batch.call_count == 2

    @pytest.mark.parametrize("lookup_error", [False, True])
    def test_retry_keeps_a_user_op_that_may_still_land(
        self, tmp_path: Path, lookup_error: bool
    ) -> None:
        """A pending or unknown UserOp is waited for again, then tracked on its own requests."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.submit.side_effect = GasAbstractionError("Bundler 503")
        env.manager.tick()
        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        old_ids = [r.id for r in run.source_requests]
        if lookup_error:
            env.sender.get_user_op_receipt.side_effect = GasAbstractionError("503")

        quoted = len(env.bridge.quoted)
        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert run.error is None
        assert run.user_op_hash == "0x" + "0f" * 32
        assert [r.id for r in run.source_requests] == old_ids
        assert len(env.bridge.quoted) == quoted
        assert run.step(STEP_BRIDGE).status == FundingStepStatus.PROCESSING
        assert env.reload(run).user_op_hash == run.user_op_hash

        # The old UserOp lands: its requests are the ones tracked, nothing is resent.
        env.sender.get_user_op_receipt.side_effect = None
        env.sender.get_user_op_receipt.return_value = {
            "success": True,
            "receipt": {"transactionHash": "0x" + "5e" * 32},
        }
        _all_succeed(env)
        run = env.tick_until(run, FundingRunStatus.COMPLETED)
        assert run.source_tx_hash == "0x" + "5e" * 32
        env.sender.prepare_batch.assert_called_once()
        env.sender.submit.assert_called_once()

    def test_retry_records_a_user_op_found_in_the_entrypoint_logs(
        self, tmp_path: Path
    ) -> None:
        """No receipt but a used nonce and an EntryPoint event: it landed, nothing is re-quoted."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.submit.side_effect = GasAbstractionError("Bundler 503")
        env.manager.tick()
        env.sender.user_op_known.return_value = False
        env.sender.user_op_nonce_used.return_value = True
        env.sender.find_user_op_event.return_value = {
            "success": True,
            "receipt": {"transactionHash": "0x" + "6f" * 32},
        }
        quoted = len(env.bridge.quoted)

        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert run.source_tx_hash == "0x" + "6f" * 32
        assert run.user_op_hash == "0x" + "0f" * 32
        assert len(env.bridge.quoted) == quoted

    def test_retry_after_revert_requotes(self, tmp_path: Path) -> None:
        """A UserOp that was included and reverted delivered nothing: retry re-quotes."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.wait_for_tx_hash.side_effect = UserOperationReverted("AA33")
        env.manager.tick()
        run = env.reload(run)
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": STEP_BRIDGE,
            "message": "Couldn't bridge to Polygon",
        }
        env.sender.get_user_op_receipt.return_value = {
            "success": False,
            "reason": "AA33",
            "receipt": {"transactionHash": "0x" + "3c" * 32},
        }
        quoted = len(env.bridge.quoted)

        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert run.user_op_hash is None
        assert run.user_op_block is None
        assert len(env.bridge.quoted) == quoted + 3
        env.sender.user_op_known.assert_not_called()

    def test_retry_resets_failed_safe_step(self, tmp_path: Path) -> None:
        """Retry after a Safe failure re-runs only the Safe step."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        ok = env.wallet.create_safe_and_transfer_excess.return_value
        env.wallet.create_safe_and_transfer_excess.return_value = {
            **ok,
            "status": CreateSafeStatus.SAFE_CREATION_FAILED,
            "message": "Failed to create Safe.",
        }
        run = env.tick_until(run, FundingRunStatus.FAILED)
        executed = list(env.bridge.executed)

        run = env.manager.retry(run.id)

        assert run.status == FundingRunStatus.PROCESSING
        assert run.step(STEP_SAFE).status == FundingStepStatus.PENDING
        assert run.step(STEP_SAFE).message is None
        env.wallet.create_safe_and_transfer_excess.return_value = ok
        run = env.tick_until(run, FundingRunStatus.COMPLETED)
        assert env.wallet.create_safe_and_transfer_excess.call_count == 2
        assert env.bridge.executed == executed
        assert run.step(STEP_SAFE).tx_hash == ok["create_tx"]

    def test_interrupted_swap_is_not_resent(self, tmp_path: Path) -> None:
        """A swap marked PROCESSING with nothing recorded fails instead of resending."""
        env = Env(tmp_path)
        _all_succeed(env)
        run = _source_leg_done(env, _funded(env))
        swap_id = f"swap:{POLYGON_OLAS}"
        run.step(swap_id).status = FundingStepStatus.PROCESSING
        run.store()

        env.manager.tick()

        run = env.reload(run)
        assert env.bridge.executed == []
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {"step_id": swap_id, "message": "Couldn't get OLAS"}

    def test_stale_swap_quote_is_refreshed_before_sending(self, tmp_path: Path) -> None:
        """A swap whose quote expired is re-quoted, then sent."""
        env = Env(tmp_path)
        _all_succeed(env)
        run = _source_leg_done(env, _funded(env))
        t.cast(QuoteData, run.swap_requests[0].quote_data).timestamp = 0
        run.store()

        env.manager.tick()

        assert env.bridge.quote_count == 1
        assert env.bridge.executed == [POLYGON_OLAS]

    @pytest.mark.parametrize(
        ("quote_data", "message"),
        [
            (
                QuoteData(
                    eta=None,
                    elapsed_time=0,
                    message="price moved",
                    timestamp=0,
                    provider_data=None,
                ),
                "price moved",
            ),
            (None, "Quote failed."),
        ],
    )
    def test_failed_swap_requote_fails_the_step(
        self, tmp_path: Path, quote_data: t.Optional[QuoteData], message: str
    ) -> None:
        """A re-quote that fails stops the run at that swap, without sending it."""
        env = Env(tmp_path)
        _all_succeed(env)
        run = _source_leg_done(env, _funded(env))
        t.cast(QuoteData, run.swap_requests[0].quote_data).timestamp = 0
        run.store()

        def _fail(request: ProviderRequest) -> None:
            request.status = ProviderRequestStatus.QUOTE_FAILED
            request.quote_data = quote_data

        with patch.object(env.bridge.provider, "quote", side_effect=_fail):
            env.manager.tick()

        run = env.reload(run)
        assert env.bridge.executed == []
        assert run.status == FundingRunStatus.FAILED
        assert run.error == {
            "step_id": f"swap:{POLYGON_OLAS}",
            "message": "Couldn't get OLAS",
        }
        assert _logged(env, message)

    def test_clearing_waits_for_its_reserve_request(self, tmp_path: Path) -> None:
        """Clearing is deferred while the source-chain reserve swap is unsettled."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        original = env.bridge.provider.status_json

        def _reserve_pending(request: ProviderRequest) -> t.Dict:
            if request.params["to"]["chain"] == "base":
                return {"tx_hash": None, "explorer_link": None}
            return original(request)

        with patch.object(
            env.bridge.provider, "status_json", side_effect=_reserve_pending
        ):
            run = env.tick_until(run, FundingRunStatus.COMPLETED)
            env.manager.tick()

        run = env.reload(run)
        assert run.step(STEP_CLEAR_DELEGATION).status == FundingStepStatus.PENDING
        assert not run.delegation_cleared
        env.wallet.clear_delegation.assert_not_called()
        pointer = env.manager._pointer()  # pylint: disable=protected-access
        assert pointer.pending_clear_run_ids == [run.id]

        env.manager.tick()

        assert env.reload(run).delegation_cleared is True
        env.wallet.clear_delegation.assert_called_once_with(Chain.BASE)

    def test_delegation_still_present_after_clearing_is_retried(
        self, tmp_path: Path
    ) -> None:
        """A clearing tx that leaves the delegation in place keeps the run pending."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.wallet.clear_delegation.side_effect = lambda chain: "0x" + "c2" * 32

        run = env.tick_until(run, FundingRunStatus.COMPLETED)

        step = run.step(STEP_CLEAR_DELEGATION)
        assert step.status == FundingStepStatus.FAILED
        assert step.message == "Delegation still present after clearing."
        assert run.clear_delegation_tx_hash == "0x" + "c2" * 32
        assert not run.delegation_cleared
        pointer = env.manager._pointer()  # pylint: disable=protected-access
        assert pointer.pending_clear_run_ids == [run.id]


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------


class TestBackgroundLoop:
    """reconcile / tick robustness and run_job."""

    def test_repeated_monitor_failures_surface_as_quote_failed(
        self, tmp_path: Path
    ) -> None:
        """A monitor that keeps raising shows QUOTE_FAILED, and recovers once it works."""
        env = Env(tmp_path)
        run = _deposit_run(env)
        env.wallet.get_balance.side_effect = ConnectionError("https://rpc/key-123")

        for _ in range(2):
            env.manager.tick()
            assert env.reload(run).status == FundingRunStatus.AWAITING_DEPOSIT
        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert env.manager.run_json(run)["quote_message"] == MESSAGE_QUOTE_FAILED
        assert _logged(env, MESSAGE_MONITOR_FAILED)
        assert run.quote_message == MESSAGE_QUOTE_FAILED

        env.wallet.get_balance.side_effect = (
            lambda chain, asset=NATIVE, from_safe=True: 0
        )
        run.quoted_at = 0
        run.store()
        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.AWAITING_DEPOSIT
        assert run.quote_message is None

    def test_monitor_failure_does_not_stop_pending_clears(self, tmp_path: Path) -> None:
        """Delegation clearing still runs while the active run's monitor raises."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.wallet.clear_delegation.side_effect = RuntimeError("no gas")
        done = env.tick_until(run, FundingRunStatus.COMPLETED)
        env.wallet.clear_delegation.side_effect = None
        env.wallet.clear_delegation.return_value = "0x" + "c1" * 32
        env.delegated = False
        # Make the pending clear due again.
        done.step(STEP_CLEAR_DELEGATION).started_at = 1
        done.store()

        waiting = _deposit_run(env)
        with patch.object(env.manager, "_monitor", side_effect=RuntimeError("rpc")):
            env.manager.tick()

        assert env.reload(done).delegation_cleared is True
        assert env.reload(waiting).status == FundingRunStatus.AWAITING_DEPOSIT

    def test_one_broken_pending_clear_does_not_block_the_others(
        self, tmp_path: Path
    ) -> None:
        """Each pending clear is attempted on its own."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        first = env.tick_until(run, FundingRunStatus.COMPLETED)
        pointer = env.manager._pointer()  # pylint: disable=protected-access
        broken = f"fr-{uuid.uuid4()}"
        pointer.pending_clear_run_ids = [broken, first.id]
        pointer.store()
        first.delegation_cleared = None
        first.step(STEP_CLEAR_DELEGATION).started_at = None
        first.store()
        real_load = env.manager.load

        def _load(run_id: str) -> FundingRun:
            if run_id == broken:
                raise ValueError("corrupt run file")
            return real_load(run_id)

        with patch.object(env.manager, "load", side_effect=_load):
            env.manager.tick()

        assert env.reload(first).delegation_cleared is True
        assert any(
            broken in c.args[0]
            for c in t.cast(MagicMock, env.manager.logger).exception.call_args_list
        )

    @pytest.mark.parametrize("entry", ["tick", "reconcile"])
    def test_pending_clear_holds_the_master_eoa_lock(
        self, tmp_path: Path, entry: str
    ) -> None:
        """The clearing tx takes a Master EOA nonce, so it runs under master_eoa_lock."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        env.wallet.clear_delegation.side_effect = RuntimeError("no gas")
        run = env.tick_until(run, FundingRunStatus.COMPLETED)
        run.step(STEP_CLEAR_DELEGATION).started_at = 1
        run.store()
        seen: t.List[bool] = []

        def _clear(chain: Chain) -> str:
            seen.append(env.funding_manager.master_eoa_lock.locked())
            env.delegated = False
            return "0x" + "c1" * 32

        env.wallet.clear_delegation.side_effect = _clear
        getattr(env.manager, entry)()

        assert seen == [True]
        assert env.reload(run).delegation_cleared is True

    def test_missing_pending_clear_runs_are_skipped(self, tmp_path: Path) -> None:
        """A pending-clear id whose file is gone does not break reconcile or tick."""
        env = Env(tmp_path)
        pointer = env.manager._pointer()  # pylint: disable=protected-access
        pointer.pending_clear_run_ids = [f"fr-{uuid.uuid4()}"]
        pointer.store()

        env.manager.reconcile()
        env.manager.tick()

        env.wallet.clear_delegation.assert_not_called()
        env.sender.delegation_of.assert_not_called()

    async def test_run_job_survives_reconcile_and_tick_errors(
        self, tmp_path: Path
    ) -> None:
        """Failures are logged and the loop keeps going until cancelled."""
        env = Env(tmp_path)
        manager = env.manager
        with (
            patch.object(
                manager, "reconcile", side_effect=RuntimeError("reconcile")
            ) as reconcile,
            patch.object(manager, "tick", side_effect=RuntimeError("tick")) as tick,
            patch(
                f"{MODULE}.asyncio.sleep",
                new=AsyncMock(side_effect=[None, asyncio.CancelledError()]),
            ) as sleep,
        ):
            with pytest.raises(asyncio.CancelledError):
                await manager.run_job()

        reconcile.assert_called_once_with()
        assert tick.call_count == 2
        sleep.assert_awaited_with(RUN_JOB_INTERVAL)
        logged = [
            c.args[0]
            for c in t.cast(MagicMock, manager.logger).exception.call_args_list
        ]
        assert logged == [
            "[FUNDING RUN] Reconciliation failed",
            "[FUNDING RUN] Tick failed",
            "[FUNDING RUN] Tick failed",
        ]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    """Enum rendering and step lookup."""

    @pytest.mark.parametrize(
        "member",
        [
            FundingRunMode.DEPOSIT,
            FundingRunStatus.PROCESSING,
            FundingStepKind.SWAP,
            FundingStepStatus.DONE,
        ],
    )
    def test_enums_render_as_their_value(self, member: t.Any) -> None:
        """str() of every model enum is its persisted value."""
        assert str(member) == member.value

    def test_unknown_step_raises_key_error(self, tmp_path: Path) -> None:
        """Looking up a step the plan does not have is a KeyError."""
        run = _deposit_run(Env(tmp_path))
        with pytest.raises(KeyError):
            run.step("nope")
