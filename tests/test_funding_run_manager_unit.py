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

import threading
import time
import typing as t
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
    STEP_BRIDGE,
    STEP_CLEAR_DELEGATION,
    STEP_NATIVE,
    STEP_RECEIVE,
    STEP_SAFE,
)
from operate.funding_run.models import (
    FundingRun,
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
from operate.wallet.gas_abstraction import GasAbstractionError, PreparedUserOperation
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


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeProvider:
    """Deterministic provider: 1 from-unit per to-unit, GAS native per request."""

    def __init__(self, bridge: "FakeBridge") -> None:
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
        """One deposit tx per request."""
        return [("deposit-0", {"to": "0x" + "c" * 40, "value": 0, "data": "0x01"})]

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
        """Resolve to the outcome configured for the target token."""
        outcome = self.bridge.outcomes.get(request.params["to"]["token"])
        if outcome is not None:
            request.status = outcome
        return {"tx_hash": "0x" + "e" * 64, "explorer_link": "https://relay.link/x"}


@dataclass
class FakeBundle:
    """Stands in for ProviderRequestBundle."""

    provider_requests: t.List[ProviderRequest] = field(default_factory=list)


class FakeBridge:
    """Stands in for BridgeManager."""

    def __init__(self) -> None:
        self.provider = FakeProvider(self)
        self.quoted: t.List[t.Dict] = []
        self.executed: t.List[str] = []
        self.outcomes: t.Dict[str, ProviderRequestStatus] = {}
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

    def execute_request(self, request: ProviderRequest) -> None:
        """Execute through the provider."""
        self.provider.execute(request)


class Env:
    """A manager wired to fakes, with controllable balances."""

    def __init__(self, tmp_path: Path, safes: t.Optional[t.Dict] = None) -> None:
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
        self.funding_manager.held_balances.return_value = {}
        self.service = MagicMock()
        self.service.home_chain = "polygon"
        service_manager = MagicMock()
        service_manager.load.return_value = self.service
        self.sender = MagicMock()
        self.sender.prepare_batch.return_value = PreparedUserOperation(
            user_op={}, user_op_hash="0x" + "0f" * 32, authorization_nonce=3
        )
        self.sender.wait_for_tx_hash.return_value = "0x" + "1a" * 32
        self.delegated = True
        self.sender.delegation_of.side_effect = lambda chain: (
            "0xdelegate" if self.delegated else None
        )

        def _clear(chain: Chain) -> str:
            self.delegated = False
            return "0x" + "c1" * 32

        self.wallet.clear_delegation.side_effect = _clear
        self.manager = FundingRunManager(
            path=tmp_path / "funding_runs",
            wallet_manager=wallet_manager,
            bridge_manager=t.cast(t.Any, self.bridge),
            funding_manager=self.funding_manager,
            service_manager=lambda: service_manager,
            logger=MagicMock(),
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


@pytest.fixture(autouse=True)
def _no_rpc() -> t.Iterator[None]:
    ledger_api = MagicMock()
    ledger_api.try_get_gas_pricing.return_value = {"maxFeePerGas": 1}
    with (
        patch(f"{MODULE}.get_default_ledger_api", return_value=ledger_api),
        patch(f"{MODULE}.get_asset_decimals", return_value=6),
    ):
        yield


def _overhead(n_assets: int, with_safe: bool = False, eoa_native: int = 0) -> int:
    gas = 100_000 * (n_assets + 1) + (0 if with_safe else 1_000_000)
    return gas * 1 + max(0, POLYGON_RESERVE - eoa_native)


def _deposit_run(
    env: Env,
    source_chain: str = "base",
    source_token: str = BASE_USDC,
    amounts: t.Optional[t.Dict[str, int]] = None,
) -> FundingRun:
    return env.manager.create_run(
        mode="deposit",
        source_chain=source_chain,
        source_token=source_token,
        destination_chain="polygon",
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
        assert run.required_amount == 50 + native + clear + GAS_ABSTRACTION_USDC_CAP
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
        assert (
            int(body["quote"]["outstanding_amount"]) == int(run.required_amount) - 1000
        )

    def test_same_chain_native_partial_deposit_is_not_double_counted(
        self, tmp_path: Path
    ) -> None:
        """A partial native deposit on the destination chain still owes the reserve."""
        env = Env(tmp_path)
        run = _deposit_run(
            env, source_chain="polygon", source_token=NATIVE, amounts={NATIVE: 100}
        )
        required = int(run.required_amount)
        assert required == 100 + _overhead(n_assets=1)

        env.balances[(Chain.POLYGON, NATIVE)] = POLYGON_RESERVE
        env.manager.refresh_quote(run.id)
        run = env.reload(run)

        assert int(run.required_amount) == required
        assert int(run.received_amount) == POLYGON_RESERVE

    def test_quote_failure_sets_quote_failed(self, tmp_path: Path) -> None:
        """A failed Relay quote leaves the run in QUOTE_FAILED with a message."""
        env = Env(tmp_path)
        env.bridge.fail_quote = True

        run = _deposit_run(env)

        assert run.status == FundingRunStatus.QUOTE_FAILED
        assert run.quote_message == "no route"


# ---------------------------------------------------------------------------
# Targets per mode
# ---------------------------------------------------------------------------


class TestTargets:
    """deposit / signer_gas / onboard target netting."""

    def test_deposit_target_below_balance_drops_out(self, tmp_path: Path) -> None:
        """A token already held above its target is not requested."""
        env = Env(tmp_path)
        env.funding_manager.held_balances.return_value = {
            POLYGON_OLAS: 50,
            POLYGON_PUSD: 4,
        }

        run = _deposit_run(env)

        assert run.net_targets == {POLYGON_PUSD: 6}
        assert [s.token for s in run.steps if s.kind == FundingStepKind.SWAP] == [
            POLYGON_PUSD
        ]

    def test_all_zero_targets_complete_immediately(self, tmp_path: Path) -> None:
        """Nothing missing: COMPLETED with an empty plan and to_receive."""
        env = Env(tmp_path)
        env.funding_manager.held_balances.return_value = {
            POLYGON_OLAS: 50,
            POLYGON_PUSD: 50,
        }

        run = _deposit_run(env)
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

    def test_onboard_uses_service_targets_on_home_chain(self, tmp_path: Path) -> None:
        """onboard nets through FundingManager.destination_targets."""
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
        assert (
            int(body["quote"]["outstanding_amount"]) == int(run.required_amount) - 100
        )

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
        env.balances[(Chain.BASE, BASE_USDC)] = int(run.required_amount)
        env.funding_manager.held_balances.return_value = {}
        # The final quote sees a bigger target (price moved).
        original = env.manager._quote  # pylint: disable=protected-access

        def _bigger(r: FundingRun) -> None:
            r.net_targets[POLYGON_OLAS] = r.net_targets[POLYGON_OLAS] + 1_000
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
        env.balances[(Chain.BASE, BASE_USDC)] = int(run.required_amount)

        env.manager.tick()

        run = env.reload(run)
        assert run.status == FundingRunStatus.PROCESSING
        assert run.step(STEP_RECEIVE).status == FundingStepStatus.DONE


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _funded(env: Env, **kwargs: t.Any) -> FundingRun:
    run = _deposit_run(env, **kwargs)
    env.balances[(Chain(run.source_chain), run.source_token)] = int(run.required_amount)
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

        run = env.tick_until(run, FundingRunStatus.COMPLETED)

        env.sender.prepare_batch.assert_called_once()
        (_, calls), _ = env.sender.prepare_batch.call_args
        assert len(calls) == 3  # carrier + native + clearing reserve
        assert run.user_op_hash == "0x" + "0f" * 32
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
        """Each tick's state is what a fresh manager loads from disk."""
        env = Env(tmp_path)
        run = _funded(env)
        _all_succeed(env)
        seen = set()
        for _ in range(20):
            env.manager.tick()
            fresh = Env(tmp_path).manager.load(run.id)
            assert fresh.json == env.manager.load(run.id).json
            seen.add(fresh.status)
            if fresh.status == FundingRunStatus.COMPLETED:
                break
        assert seen >= {FundingRunStatus.PROCESSING, FundingRunStatus.COMPLETED}

    def test_restart_with_recorded_user_op_reconciles_without_resend(
        self, tmp_path: Path
    ) -> None:
        """A persisted UserOp hash is looked up, never resubmitted."""
        env = Env(tmp_path)
        run = _funded(env)
        env.sender.submit.side_effect = GasAbstractionError("process died")
        env.manager.tick()  # hash persisted, submit "fails"
        run = env.reload(run)
        assert run.user_op_hash and not run.source_tx_hash

        restarted = Env(tmp_path)
        restarted.sender.get_user_op_receipt.return_value = {"success": True}
        restarted.sender.tx_hash_of.return_value = "0x" + "2b" * 32
        restarted.manager.reconcile()
        restarted.manager.tick()

        run = restarted.reload(run)
        restarted.sender.submit.assert_not_called()
        restarted.sender.prepare_batch.assert_not_called()
        assert run.source_tx_hash == "0x" + "2b" * 32

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
            "message": "Interrupted before the transfer was confirmed.",
        }

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
        assert run.error["step_id"] == STEP_NATIVE  # type: ignore[index]

        env.bridge.outcomes[NATIVE] = ProviderRequestStatus.EXECUTION_DONE
        quoted_before = len(env.bridge.quoted)
        run = env.manager.retry(run.id)

        assert len(env.bridge.quoted) == quoted_before
        assert run.step(STEP_NATIVE).status == FundingStepStatus.DONE

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
            "message": "Failed to create Safe.",
        }

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
        assert seen and all(seen)


# ---------------------------------------------------------------------------
# Single-run rule and lifecycle routes
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Replace, cancel, refresh, 404/409."""

    def test_create_replaces_awaiting_run(self, tmp_path: Path) -> None:
        """'Change' replaces an AWAITING_DEPOSIT run."""
        env = Env(tmp_path)
        first = _deposit_run(env)
        second = _deposit_run(env, source_token=NATIVE)

        assert env.reload(first).status == FundingRunStatus.CANCELLED
        assert env.manager.active_run().id == second.id  # type: ignore[union-attr]

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
