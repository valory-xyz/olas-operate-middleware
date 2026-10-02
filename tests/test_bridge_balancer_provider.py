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
"""Unit tests for the Balancer V2 swap provider."""

import logging
import time
import typing as t
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from web3 import Web3
from web3.exceptions import ContractLogicError, TransactionNotFound

from operate.bridge.bridge_manager import BALANCER_PROVIDER_ID, BridgeManager
from operate.bridge.providers.balancer_provider import (
    BALANCER_POOLS,
    BALANCER_VAULT,
    BalancerProvider,
    SWAP_GAS,
    _VAULT_ABI,
    has_native_pool,
)
from operate.bridge.providers.provider import (
    ExecutionData,
    MESSAGE_EXECUTION_FAILED_QUOTE_FAILED,
    MESSAGE_EXECUTION_FAILED_REVERTED,
    MESSAGE_EXECUTION_SKIPPED,
    MESSAGE_QUOTE_ZERO,
    ProviderRequest,
    ProviderRequestStatus,
)
from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import OLAS
from operate.operate_types import Chain

MODULE = "operate.bridge.providers.balancer_provider"
EOA = "0x4Eeb1a1d9B2694Eee27c7937f45D549775cFA3a4"
POOL_ID = BALANCER_POOLS[(Chain.GNOSIS, OLAS[Chain.GNOSIS])]
TX_HASH = "0x" + "ab" * 32
VAULT = Web3().eth.contract(address=BALANCER_VAULT, abi=_VAULT_ABI)


def _params(
    amount: int = 100,
    to_chain: str = "gnosis",
    to_token: str = OLAS[Chain.GNOSIS],
    from_token: str = ZERO_ADDRESS,
) -> t.Dict:
    return {
        "from": {"chain": "gnosis", "address": EOA, "token": from_token},
        "to": {"chain": to_chain, "address": EOA, "token": to_token, "amount": amount},
    }


def _provider() -> BalancerProvider:
    return BalancerProvider(
        wallet_manager=MagicMock(),
        provider_id=BALANCER_PROVIDER_ID,
        logger=logging.getLogger("test"),
    )


def _ledger(api: t.Any) -> t.Any:
    ledger_api = MagicMock()
    ledger_api.api = api
    return patch(
        "operate.bridge.providers.provider.get_default_ledger_api",
        return_value=ledger_api,
    )


def _quote(
    provider: BalancerProvider,
    request: ProviderRequest,
    result: t.Optional[t.List[int]] = None,
    error: t.Optional[Exception] = None,
) -> MagicMock:
    api = MagicMock()
    query = api.eth.contract.return_value.functions.queryBatchSwap.return_value
    query.call.return_value = result or [4_000, -100]
    query.call.side_effect = error
    with _ledger(api):
        provider.quote(request)
    return api


def _quoted(provider: BalancerProvider, amount: int = 100) -> ProviderRequest:
    request = provider.create_request(_params(amount))
    _quote(provider, request)
    return request


@contextmanager
def _tx_env(api: t.Any) -> t.Iterator[MagicMock]:
    """Real ABI encoding, no gas RPCs; yields the gas-estimate mock."""
    api.eth.contract.side_effect = Web3().eth.contract
    with (
        _ledger(api),
        patch(f"{MODULE}.update_tx_with_gas_pricing"),
        patch(f"{MODULE}.update_tx_with_gas_estimate") as estimate,
    ):
        yield estimate


def _receipt_api(
    receipt: t.Optional[t.Dict] = None, error: t.Optional[Exception] = None
) -> MagicMock:
    api = MagicMock()
    api.eth.get_transaction_receipt.return_value = receipt
    api.eth.get_transaction_receipt.side_effect = error
    return api


def _executed(
    provider: BalancerProvider, tx_hash: t.Optional[str] = TX_HASH
) -> ProviderRequest:
    request = _quoted(provider)
    request.execution_data = ExecutionData(
        elapsed_time=0,
        message=None,
        timestamp=int(time.time()),
        from_tx_hash=tx_hash,
        to_tx_hash=None,
        provider_data=None,
    )
    request.status = ProviderRequestStatus.EXECUTION_PENDING
    return request


class TestCanHandleRequest:
    """Only same-chain native-in routes with a configured pool."""

    def test_configured_pool(self) -> None:
        """Gnosis xDAI -> OLAS is handled, whatever the address case."""
        assert _provider().can_handle_request(_params())
        assert _provider().can_handle_request(
            _params(to_token=OLAS[Chain.GNOSIS].lower())
        )

    @pytest.mark.parametrize(
        "params",
        [
            _params(to_chain="base"),
            _params(to_token="0x" + "1" * 40),
            _params(from_token="0x" + "2" * 40),
            {"from": {}},
        ],
    )
    def test_unhandled(self, params: t.Dict) -> None:
        """Cross-chain, unknown pairs, an ERC-20 in and malformed params are not handled."""
        assert not _provider().can_handle_request(params)

    def test_has_native_pool(self) -> None:
        """Pool lookups ignore address case and are per chain."""
        assert has_native_pool(Chain.GNOSIS, OLAS[Chain.GNOSIS].lower())
        assert not has_native_pool(Chain.BASE, OLAS[Chain.GNOSIS])

    def test_description(self) -> None:
        """Human-readable name."""
        assert _provider().description() == "Balancer V2 swap provider."


class TestQuote:
    """GIVEN_OUT queries against the Vault."""

    def test_success_records_amount_and_slippage_limit(self) -> None:
        """The limit is the queried amount in plus 1%."""
        provider = _provider()
        request = provider.create_request(_params())
        api = _quote(provider, request)

        assert request.status == ProviderRequestStatus.QUOTE_DONE
        assert request.quote_data is not None
        assert request.quote_data.provider_data == {
            "pool_id": POOL_ID,
            "amount_in": 4_000,
            "max_amount_in": 4_040,
        }
        api.eth.contract.assert_called_once_with(address=BALANCER_VAULT, abi=_VAULT_ABI)
        api.eth.contract.return_value.functions.queryBatchSwap.assert_called_once_with(
            1,
            [(POOL_ID, 0, 1, 100, b"")],
            [ZERO_ADDRESS, OLAS[Chain.GNOSIS]],
            (EOA, False, EOA, False),
        )

    def test_requote_replaces_the_limit(self) -> None:
        """A stale quote is replaced, so the swap uses the current price."""
        provider = _provider()
        request = _quoted(provider)
        _quote(provider, request, result=[5_000, -100])

        assert request.quote_data is not None
        assert request.quote_data.provider_data is not None
        assert request.quote_data.provider_data["max_amount_in"] == 5_050

    def test_zero_amount(self) -> None:
        """Nothing to swap needs no query."""
        provider = _provider()
        request = provider.create_request(_params(amount=0))
        provider.quote(request)

        assert request.status == ProviderRequestStatus.QUOTE_DONE
        assert request.quote_data is not None
        assert request.quote_data.message == MESSAGE_QUOTE_ZERO
        assert provider.get_txs(request) == []

    @pytest.mark.parametrize(
        ("result", "error", "message"),
        [
            (None, RuntimeError("BAL#304"), "BAL#304"),
            ([0, -100], None, "Non-positive amount in 0."),
            ([-5, -100], None, "Non-positive amount in -5."),
        ],
    )
    def test_failure(
        self,
        result: t.Optional[t.List[int]],
        error: t.Optional[Exception],
        message: str,
    ) -> None:
        """A reverting query or a non-positive amount in fails the quote."""
        provider = _provider()
        request = provider.create_request(_params())
        _quote(provider, request, result=result, error=error)

        assert request.status == ProviderRequestStatus.QUOTE_FAILED
        assert request.quote_data is not None
        assert request.quote_data.message == message
        assert request.quote_data.provider_data is None

    def test_refuses_after_execution(self) -> None:
        """An executed request is never re-quoted."""
        provider = _provider()
        request = _quoted(provider)
        request.status = ProviderRequestStatus.EXECUTION_PENDING
        with pytest.raises(RuntimeError, match="with status"):
            provider.quote(request)

        request.status = ProviderRequestStatus.QUOTE_DONE
        request.execution_data = MagicMock()
        with pytest.raises(RuntimeError, match="execution already present"):
            provider.quote(request)


class TestGetTxs:
    """One payable Vault.swap with the native limit as value."""

    def test_swap_tx(self) -> None:
        """The swap carries the limit as value and the exact output."""
        provider = _provider()
        request = _quoted(provider)
        with _tx_env(MagicMock()) as estimate:
            ((label, tx),) = provider.get_txs(request)

        assert label == "swap_tx"
        assert tx["to"] == BALANCER_VAULT
        assert tx["from"] == EOA
        assert tx["value"] == 4_040
        assert tx["chainId"] == Chain.GNOSIS.id
        assert tx["gas"] == SWAP_GAS
        estimate.assert_called_once()
        func, args = VAULT.decode_function_input(tx["data"])
        assert func.fn_name == "swap"
        single_swap = args["singleSwap"]
        assert "0x" + single_swap["poolId"].hex() == POOL_ID
        assert (
            single_swap["kind"],
            single_swap["assetIn"],
            single_swap["assetOut"],
            single_swap["amount"],
        ) == (1, ZERO_ADDRESS, OLAS[Chain.GNOSIS], 100)
        assert args["funds"] == {
            "sender": EOA,
            "fromInternalBalance": False,
            "recipient": EOA,
            "toInternalBalance": False,
        }
        assert args["limit"] == 4_040
        assert args["deadline"] > time.time()

    def test_missing_quote(self) -> None:
        """Transactions need a quote."""
        provider = _provider()
        request = provider.create_request(_params())
        with pytest.raises(RuntimeError, match="quote data not present"):
            provider.get_txs(request)


class TestPrecheck:
    """The exact swap is simulated before sending."""

    @staticmethod
    def _precheck(call: t.Any) -> t.Tuple[t.Optional[str], MagicMock]:
        provider = _provider()
        request = _quoted(provider)
        api = MagicMock()
        api.eth.call.side_effect = call
        with _tx_env(api):
            txs = provider.get_txs(request)
            reason = provider._precheck(  # pylint: disable=protected-access
                request, txs
            )
        return reason, api

    def test_simulates_the_swap_tx(self) -> None:
        """The simulated call is the swap itself, with its value and no gas cap."""
        reason, api = self._precheck(None)

        assert reason is None
        (call,), _ = api.eth.call.call_args
        assert set(call) == {"from", "to", "data", "value"}
        assert (call["from"], call["to"], call["value"]) == (EOA, BALANCER_VAULT, 4_040)
        func, args = VAULT.decode_function_input(call["data"])
        assert func.fn_name == "swap"
        assert args["limit"] == 4_040

    def test_revert_is_the_reason(self) -> None:
        """BAL#507 after a price move is reported."""
        reason, _ = self._precheck(ContractLogicError("BAL#507"))

        assert reason is not None
        assert "BAL#507" in reason

    def test_rpc_error_is_not_a_revert(self) -> None:
        """An RPC error leaves the decision to the send."""
        reason, _ = self._precheck(RuntimeError("rpc down"))

        assert reason is None


class TestExecute:
    """The base execute runs the precheck only for a quote it would send."""

    @staticmethod
    def _execute(
        request: ProviderRequest, provider: BalancerProvider, reason: t.Optional[str]
    ) -> t.Tuple[MagicMock, MagicMock]:
        with (
            _tx_env(MagicMock()),
            patch.object(provider, "_precheck", return_value=reason) as precheck,
            patch("operate.bridge.providers.provider.TxSettler") as settler,
        ):
            settler.return_value.transact.return_value.tx_hash = TX_HASH
            provider.execute(request)
        return precheck, settler

    def test_failed_precheck_is_not_sent(self) -> None:
        """A swap that would revert fails with the reason and no tx hash."""
        provider = _provider()
        request = _quoted(provider)
        precheck, settler = self._execute(request, provider, "BAL#507")

        precheck.assert_called_once()
        settler.assert_not_called()
        assert request.status == ProviderRequestStatus.EXECUTION_FAILED
        assert request.execution_data is not None
        assert request.execution_data.from_tx_hash is None
        assert "BAL#507" in str(request.execution_data.message)

    def test_passed_precheck_is_sent(self) -> None:
        """A swap that simulates fine is sent."""
        provider = _provider()
        request = _quoted(provider)
        precheck, settler = self._execute(request, provider, None)

        precheck.assert_called_once()
        settler.assert_called_once()
        assert request.status == ProviderRequestStatus.EXECUTION_PENDING
        assert request.execution_data is not None
        assert request.execution_data.from_tx_hash == TX_HASH

    def test_failed_quote_is_not_simulated(self) -> None:
        """A failed quote fails execution the usual way."""
        provider = _provider()
        request = provider.create_request(_params())
        _quote(provider, request, error=RuntimeError("BAL#304"))
        precheck, settler = self._execute(request, provider, None)

        precheck.assert_not_called()
        settler.assert_not_called()
        assert request.status == ProviderRequestStatus.EXECUTION_FAILED
        assert request.execution_data is not None
        assert request.execution_data.message == MESSAGE_EXECUTION_FAILED_QUOTE_FAILED

    def test_zero_amount_is_not_simulated(self) -> None:
        """Nothing to swap is skipped without a simulation."""
        provider = _provider()
        request = provider.create_request(_params(amount=0))
        provider.quote(request)
        precheck, settler = self._execute(request, provider, None)

        precheck.assert_not_called()
        settler.assert_not_called()
        assert request.status == ProviderRequestStatus.EXECUTION_DONE
        assert request.execution_data is not None
        assert MESSAGE_EXECUTION_SKIPPED in str(request.execution_data.message)


class TestExecutionStatus:
    """A same-chain swap is done when its transaction succeeded."""

    def test_success(self) -> None:
        """A successful receipt completes the request."""
        provider = _provider()
        request = _executed(provider)
        with _ledger(_receipt_api({"status": 1})):
            status = provider.status_json(request)

        assert request.status == ProviderRequestStatus.EXECUTION_DONE
        assert request.execution_data is not None
        assert request.execution_data.to_tx_hash == TX_HASH
        assert TX_HASH in status["explorer_link"]

    def test_revert(self) -> None:
        """A reverted swap fails the request."""
        provider = _provider()
        request = _executed(provider)
        with _ledger(_receipt_api({"status": 0})):
            provider.status_json(request)

        assert request.status == ProviderRequestStatus.EXECUTION_FAILED
        assert request.execution_data is not None
        assert request.execution_data.message == MESSAGE_EXECUTION_FAILED_REVERTED

    @pytest.mark.parametrize(
        ("error", "likely_failed", "expected"),
        [
            (
                TransactionNotFound("none"),
                False,
                ProviderRequestStatus.EXECUTION_PENDING,
            ),
            (TransactionNotFound("none"), True, ProviderRequestStatus.EXECUTION_FAILED),
            (RuntimeError("rpc down"), False, ProviderRequestStatus.EXECUTION_UNKNOWN),
            (RuntimeError("rpc down"), True, ProviderRequestStatus.EXECUTION_FAILED),
        ],
    )
    def test_no_receipt(
        self,
        error: Exception,
        likely_failed: bool,
        expected: ProviderRequestStatus,
    ) -> None:
        """Without a receipt the swap waits until it is likely dropped."""
        provider = _provider()
        request = _executed(provider)
        with (
            _ledger(_receipt_api(error=error)),
            patch.object(
                provider, "_bridge_tx_likely_failed", return_value=likely_failed
            ),
        ):
            provider.status_json(request)

        assert request.status == expected

    def test_missing_tx_hash(self) -> None:
        """An execution without a transaction hash failed, and has no link."""
        provider = _provider()
        request = _executed(provider, tx_hash=None)
        provider.status_json(request)

        assert request.status == ProviderRequestStatus.EXECUTION_FAILED
        assert (
            provider._get_explorer_link(request)  # pylint: disable=protected-access
            is None
        )


class TestRouting:
    """BridgeManager sends every configured pool to Balancer."""

    def test_every_pool_is_routed_to_balancer(self, tmp_path: Path) -> None:
        """Each native-in pool route goes to Balancer, with no fallback."""
        manager = BridgeManager(
            path=tmp_path, wallet_manager=MagicMock(), logger=logging.getLogger("t")
        )

        for chain, token_out in BALANCER_POOLS:
            params = {
                "from": {"chain": chain.value, "address": EOA, "token": ZERO_ADDRESS},
                "to": {
                    "chain": chain.value,
                    "address": EOA,
                    "token": token_out,
                    "amount": 1,
                },
            }
            assert manager._build_provider_chain(  # pylint: disable=protected-access
                params
            ) == [BALANCER_PROVIDER_ID]
            assert (
                BridgeManager.swap_source_token(chain, "0x" + "c" * 40, token_out)
                == ZERO_ADDRESS
            )
        assert isinstance(
            manager._providers[  # pylint: disable=protected-access
                BALANCER_PROVIDER_ID
            ],
            BalancerProvider,
        )

    def test_other_target_keeps_the_carrier(self) -> None:
        """Without a native pool the carrier is used."""
        carrier = "0x" + "c" * 40
        assert (
            BridgeManager.swap_source_token(Chain.BASE, carrier, OLAS[Chain.BASE])
            == carrier
        )
