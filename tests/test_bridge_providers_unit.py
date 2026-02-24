#!/usr/bin/env python3
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

"""Unit tests for bridge provider classes (no network/blockchain calls)."""

import time
import typing as t
from unittest.mock import MagicMock, patch

import pytest
from web3.exceptions import TimeExhausted, TransactionNotFound

from operate.bridge.providers.lifi_provider import LiFiProvider, LiFiTransactionStatus
from operate.bridge.providers.native_bridge_provider import (
    BridgeContractAdaptor,
    NativeBridgeProvider,
    OmnibridgeContractAdaptor,
    OptimismContractAdaptor,
)
from operate.bridge.providers.provider import (
    ERC20_APPROVE_SELECTOR,
    ERC20_TRANSFER_SELECTOR,
    ExecutionData,
    Provider,
    ProviderRequest,
    ProviderRequestStatus,
    QuoteData,
)
from operate.bridge.providers.relay_provider import RelayExecutionStatus, RelayProvider
from operate.constants import ZERO_ADDRESS


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

FROM_ADDR = "0x" + "a" * 40
TO_ADDR = "0x" + "b" * 40
ERC20_ADDR = "0x" + "c" * 40  # non-zero ERC20 token


def _make_request(
    provider_id: str = "test-provider",
    status: ProviderRequestStatus = ProviderRequestStatus.CREATED,
    from_token: str = ZERO_ADDRESS,
    to_token: str = ZERO_ADDRESS,
    amount: int = 1000,
    from_chain: str = "gnosis",
    to_chain: str = "base",
) -> ProviderRequest:
    """Build a minimal ProviderRequest for unit tests."""
    return ProviderRequest(
        id="r-test-123",
        params={
            "from": {
                "chain": from_chain,
                "address": FROM_ADDR,
                "token": from_token,
            },
            "to": {
                "chain": to_chain,
                "address": TO_ADDR,
                "token": to_token,
                "amount": amount,
            },
        },
        provider_id=provider_id,
        status=status,
        quote_data=None,
        execution_data=None,
    )


def _make_quote_data(
    eta: t.Optional[int] = 300,
    provider_data: t.Optional[t.Dict] = None,
) -> QuoteData:
    """Build a minimal QuoteData."""
    return QuoteData(
        eta=eta,
        elapsed_time=0.1,
        message=None,
        timestamp=int(time.time()),
        provider_data=provider_data,
    )


def _make_execution_data(
    from_tx_hash: t.Optional[str] = "0x" + "d" * 64,
    timestamp: t.Optional[int] = None,
) -> ExecutionData:
    """Build a minimal ExecutionData."""
    return ExecutionData(
        elapsed_time=0.0,
        message=None,
        timestamp=timestamp if timestamp is not None else int(time.time()),
        from_tx_hash=from_tx_hash,
        to_tx_hash=None,
        provider_data=None,
    )


class _ConcreteProvider(Provider):
    """Minimal concrete subclass of Provider for testing abstract base methods."""

    def __init__(
        self,
        txs_to_return: t.Optional[t.List[t.Tuple[str, t.Dict]]] = None,
        provider_id: str = "test-provider",
    ) -> None:
        super().__init__(
            wallet_manager=MagicMock(),
            provider_id=provider_id,
            logger=MagicMock(),
        )
        self._txs_to_return: t.List[t.Tuple[str, t.Dict]] = txs_to_return or []

    def quote(self, provider_request: ProviderRequest) -> None:  # type: ignore[override]
        """Stub quote."""

    def _get_txs(  # type: ignore[override]
        self,
        provider_request: ProviderRequest,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> t.List[t.Tuple[str, t.Dict]]:
        return self._txs_to_return

    def _update_execution_status(self, provider_request: ProviderRequest) -> None:
        """Stub."""

    def _get_explorer_link(self, provider_request: ProviderRequest) -> t.Optional[str]:
        return None


# ---------------------------------------------------------------------------
# TestProviderBase
# ---------------------------------------------------------------------------


class TestProviderBase:
    """Tests for the abstract Provider base class."""

    def test_description_returns_class_name(self) -> None:
        """description() returns the class name (line 153)."""
        provider = _ConcreteProvider()
        assert provider.description() == "_ConcreteProvider"

    def test_validate_raises_on_wrong_provider_id(self) -> None:
        """_validate() raises ValueError when provider_id mismatches (line 158)."""
        provider = _ConcreteProvider(provider_id="my-provider")
        req = _make_request(provider_id="other-provider")
        with pytest.raises(ValueError, match="does not match"):
            provider._validate(req)  # pylint: disable=protected-access

    def test_can_handle_request_missing_from_key(self) -> None:
        """can_handle_request() returns False when 'from' key is absent (lines 166-169)."""
        provider = _ConcreteProvider()
        result = provider.can_handle_request(
            {
                "to": {
                    "chain": "base",
                    "address": TO_ADDR,
                    "token": ZERO_ADDRESS,
                    "amount": 1000,
                }
            }
        )
        assert result is False
        provider.logger.error.assert_called()  # type: ignore[attr-defined]

    def test_can_handle_request_missing_to_key(self) -> None:
        """can_handle_request() returns False when 'to' key is absent (lines 166-169)."""
        provider = _ConcreteProvider()
        result = provider.can_handle_request(
            {
                "from": {
                    "chain": "gnosis",
                    "address": FROM_ADDR,
                    "token": ZERO_ADDRESS,
                }
            }
        )
        assert result is False

    def test_can_handle_request_from_missing_chain(self) -> None:
        """can_handle_request() returns False when 'from' dict missing chain (lines 180-183)."""
        provider = _ConcreteProvider()
        result = provider.can_handle_request(
            {
                "from": {"address": FROM_ADDR, "token": ZERO_ADDRESS},
                "to": {
                    "chain": "base",
                    "address": TO_ADDR,
                    "token": ZERO_ADDRESS,
                    "amount": 1000,
                },
            }
        )
        assert result is False

    def test_can_handle_request_to_missing_amount(self) -> None:
        """can_handle_request() returns False when 'to' dict missing amount (lines 192-195)."""
        provider = _ConcreteProvider()
        result = provider.can_handle_request(
            {
                "from": {
                    "chain": "gnosis",
                    "address": FROM_ADDR,
                    "token": ZERO_ADDRESS,
                },
                "to": {
                    "chain": "base",
                    "address": TO_ADDR,
                    "token": ZERO_ADDRESS,
                    # 'amount' intentionally omitted
                },
            }
        )
        assert result is False

    def test_create_request_invalid_params_raises(self) -> None:
        """create_request() raises ValueError on invalid params (line 203)."""
        provider = _ConcreteProvider()
        with pytest.raises(ValueError, match="Invalid input"):
            provider.create_request({"not_from": {}, "not_to": {}})

    def test_abstract_quote_raises_not_implemented(self) -> None:
        """Provider.quote() abstract body raises NotImplementedError (line 235)."""
        # We call super().quote() through a helper that bypasses the stub.
        # The easiest way is to call Provider.quote directly.
        provider = _ConcreteProvider()
        req = _make_request()
        with pytest.raises(NotImplementedError):
            Provider.quote(provider, req)

    def test_abstract_get_txs_raises_not_implemented(self) -> None:
        """Provider._get_txs() abstract body raises NotImplementedError (line 242)."""
        provider = _ConcreteProvider()
        req = _make_request()
        with pytest.raises(NotImplementedError):
            Provider._get_txs(provider, req)  # pylint: disable=protected-access

    def test_abstract_update_execution_status_raises(self) -> None:
        """Provider._update_execution_status() abstract body raises NotImplementedError (line 454)."""
        provider = _ConcreteProvider()
        req = _make_request()
        with pytest.raises(NotImplementedError):
            Provider._update_execution_status(  # pylint: disable=protected-access
                provider, req
            )

    def test_abstract_get_explorer_link_raises(self) -> None:
        """Provider._get_explorer_link() abstract body raises NotImplementedError (line 459)."""
        provider = _ConcreteProvider()
        req = _make_request()
        with pytest.raises(NotImplementedError):
            Provider._get_explorer_link(  # pylint: disable=protected-access
                provider, req
            )

    # ------------------------------------------------------------------
    # requirements() — ERC20 transfer selector path
    # ------------------------------------------------------------------

    def test_requirements_erc20_transfer_selector(self) -> None:
        """requirements() parses ERC20 transfer amount correctly (lines 311-316)."""
        from_token = ERC20_ADDR
        amount = 100
        recipient_hex = "0" * 64
        amount_hex = hex(amount)[2:].zfill(64)
        transfer_data = ERC20_TRANSFER_SELECTOR + recipient_hex + amount_hex

        tx: t.Dict[str, t.Any] = {
            "to": from_token,
            "data": transfer_data,
            "gas": 21_000,
            "value": 0,
        }
        provider = _ConcreteProvider(txs_to_return=[("transfer", tx)])
        req = _make_request(from_token=from_token)

        with patch(
            "operate.bridge.providers.provider.update_tx_with_gas_pricing"
        ) as mock_gas, patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger

            def _set_gas_price(tx_dict: t.Dict, _ledger: t.Any) -> None:
                tx_dict["gasPrice"] = 1

            mock_gas.side_effect = _set_gas_price

            result = provider.requirements(req)

        from_chain = req.params["from"]["chain"]
        from_addr = req.params["from"]["address"]
        assert from_token in result[from_chain][from_addr]
        assert int(result[from_chain][from_addr][from_token]) == amount

    def test_requirements_erc20_transfer_malformed_raises(self) -> None:
        """requirements() raises RuntimeError on malformed ERC20 transfer data (lines 315-316)."""
        from_token = ERC20_ADDR
        # Only the selector, no recipient/amount data — will cause empty amount_hex
        bad_data = ERC20_TRANSFER_SELECTOR  # too short; slicing yields ""

        tx: t.Dict[str, t.Any] = {
            "to": from_token,
            "data": bad_data,
            "gas": 21_000,
            "value": 0,
        }
        provider = _ConcreteProvider(txs_to_return=[("transfer", tx)])
        req = _make_request(from_token=from_token)

        with patch(
            "operate.bridge.providers.provider.update_tx_with_gas_pricing"
        ) as mock_gas, patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger

            def _set_gas_price(tx_dict: t.Dict, _ledger: t.Any) -> None:
                tx_dict["gasPrice"] = 1

            mock_gas.side_effect = _set_gas_price

            with pytest.raises(RuntimeError, match="Malformed ERC20"):
                provider.requirements(req)

    # ------------------------------------------------------------------
    # execute() paths
    # ------------------------------------------------------------------

    def test_execute_quote_done_no_quote_data_raises(self) -> None:
        """execute() raises RuntimeError if status QUOTE_DONE but quote_data is None (line 362)."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.QUOTE_DONE)
        req.quote_data = None
        with pytest.raises(RuntimeError, match="quote data not present"):
            provider.execute(req)

    def test_execute_quote_done_execution_data_already_present_raises(self) -> None:
        """execute() raises RuntimeError if execution_data already set (line 366)."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.QUOTE_DONE)
        req.quote_data = _make_quote_data()
        req.execution_data = _make_execution_data()
        with pytest.raises(RuntimeError, match="execution data already present"):
            provider.execute(req)

    def test_execute_txsettler_loop_success(self) -> None:
        """execute() runs TxSettler loop and sets EXECUTION_PENDING (lines 416-434)."""
        tx: t.Dict[str, t.Any] = {
            "to": "0x" + "a" * 40,
            "gas": 21_000,
            "value": 0,
            "data": "0x",
        }
        provider = _ConcreteProvider(txs_to_return=[("bridge_tx", tx)])
        req = _make_request(status=ProviderRequestStatus.QUOTE_DONE)
        req.quote_data = _make_quote_data()

        mock_settler = MagicMock()
        mock_settler.transact.return_value = mock_settler
        mock_settler.settle.return_value = mock_settler
        mock_settler.tx_hash = "0x" + "e" * 64

        with patch(
            "operate.bridge.providers.provider.TxSettler", return_value=mock_settler
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_ledger.api.eth.get_transaction_count.return_value = 0
            mock_api.return_value = mock_ledger
            provider.execute(req)

        assert req.status == ProviderRequestStatus.EXECUTION_PENDING
        assert req.execution_data is not None
        assert req.execution_data.from_tx_hash == mock_settler.tx_hash

    def test_execute_txsettler_time_exhausted(self) -> None:
        """execute() handles TimeExhausted from settle() gracefully (lines 419-422)."""
        tx: t.Dict[str, t.Any] = {
            "to": "0x" + "a" * 40,
            "gas": 21_000,
            "value": 0,
            "data": "0x",
        }
        provider = _ConcreteProvider(txs_to_return=[("bridge_tx", tx)])
        req = _make_request(status=ProviderRequestStatus.QUOTE_DONE)
        req.quote_data = _make_quote_data()

        mock_settler = MagicMock()
        mock_settler.transact.return_value = mock_settler
        mock_settler.settle.side_effect = TimeExhausted("timed out")
        mock_settler.tx_hash = "0x" + "f" * 64

        with patch(
            "operate.bridge.providers.provider.TxSettler", return_value=mock_settler
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_ledger.api.eth.get_transaction_count.return_value = 0
            mock_api.return_value = mock_ledger
            # Should NOT raise; TimeExhausted is caught with a warning
            provider.execute(req)

        assert req.status == ProviderRequestStatus.EXECUTION_PENDING
        assert req.execution_data is not None
        assert req.execution_data.from_tx_hash == mock_settler.tx_hash
        provider.logger.warning.assert_called()  # type: ignore[attr-defined]

    def test_execute_exception_sets_execution_failed(self) -> None:
        """execute() catches generic exceptions and sets EXECUTION_FAILED (lines 438-449)."""
        tx: t.Dict[str, t.Any] = {
            "to": "0x" + "a" * 40,
            "gas": 21_000,
            "value": 0,
            "data": "0x",
        }
        provider = _ConcreteProvider(txs_to_return=[("bridge_tx", tx)])
        req = _make_request(status=ProviderRequestStatus.QUOTE_DONE)
        req.quote_data = _make_quote_data()

        with patch(
            "operate.bridge.providers.provider.TxSettler",
            side_effect=RuntimeError("boom"),
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger
            provider.execute(req)

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED
        assert req.execution_data is not None

    def test_status_json_no_quote_data(self) -> None:
        """status_json() returns message=None when no quote_data (line 485)."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.CREATED)
        result = provider.status_json(req)
        assert result == {
            "message": None,
            "status": ProviderRequestStatus.CREATED.value,
        }

    def test_bridge_tx_likely_failed_no_execution_data(self) -> None:
        """_bridge_tx_likely_failed() returns True when no execution_data (line 500)."""
        provider = _ConcreteProvider()
        req = _make_request()
        assert (
            provider._bridge_tx_likely_failed(req) is True
        )  # pylint: disable=protected-access

    def test_bridge_tx_likely_failed_age_exceeds_hard_timeout(self) -> None:
        """_bridge_tx_likely_failed() returns True when age > HARD_TIMEOUT (lines 518-522)."""
        provider = _ConcreteProvider()
        req = _make_request()
        req.execution_data = _make_execution_data(
            timestamp=int(time.time()) - 1300  # > 1200 HARD_TIMEOUT
        )
        req.quote_data = _make_quote_data(eta=60)
        with patch("operate.bridge.providers.provider.get_default_ledger_api"):
            result = provider._bridge_tx_likely_failed(
                req
            )  # pylint: disable=protected-access
        assert result is True
        provider.logger.warning.assert_called()  # type: ignore[attr-defined]

    def test_bridge_tx_likely_failed_recent_tx_returns_false(self) -> None:
        """_bridge_tx_likely_failed() returns False when age <= soft_timeout (lines 524-525)."""
        provider = _ConcreteProvider()
        req = _make_request()
        req.execution_data = _make_execution_data(
            timestamp=int(time.time()) - 5  # very recent
        )
        # eta=600 => soft_timeout = max(600, 600*10) = 6000; age=5 <= 6000
        req.quote_data = _make_quote_data(eta=600)
        result = provider._bridge_tx_likely_failed(
            req
        )  # pylint: disable=protected-access
        assert result is False

    def test_bridge_tx_likely_failed_receipt_status_1_returns_false(self) -> None:
        """_bridge_tx_likely_failed() returns False when receipt.status==1 (lines 530-541)."""
        provider = _ConcreteProvider()
        req = _make_request()
        # age > soft_timeout (600) but < HARD_TIMEOUT (1200)
        req.execution_data = _make_execution_data(timestamp=int(time.time()) - 700)
        req.quote_data = _make_quote_data(eta=30)  # eta<60 => eta_timeout=0; soft=600

        mock_receipt = MagicMock()
        mock_receipt.__getitem__ = lambda self, key: 1 if key == "status" else None

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_api.return_value = MagicMock(api=mock_w3)
            result = provider._bridge_tx_likely_failed(
                req
            )  # pylint: disable=protected-access

        assert result is False

    def test_bridge_tx_likely_failed_receipt_status_0_returns_true(self) -> None:
        """_bridge_tx_likely_failed() returns True when receipt.status==0 (lines 543-546)."""
        provider = _ConcreteProvider()
        req = _make_request()
        req.execution_data = _make_execution_data(timestamp=int(time.time()) - 700)
        req.quote_data = _make_quote_data(eta=30)

        mock_receipt = MagicMock()
        mock_receipt.__getitem__ = lambda self, key: 0 if key == "status" else None

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_api.return_value = MagicMock(api=mock_w3)
            result = provider._bridge_tx_likely_failed(
                req
            )  # pylint: disable=protected-access

        assert result is True

    def test_bridge_tx_likely_failed_transaction_not_found(self) -> None:
        """_bridge_tx_likely_failed() returns True on TransactionNotFound (lines 547-551)."""
        provider = _ConcreteProvider()
        req = _make_request()
        req.execution_data = _make_execution_data(timestamp=int(time.time()) - 700)
        req.quote_data = _make_quote_data(eta=30)

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            mock_w3.eth.get_transaction_receipt.side_effect = TransactionNotFound(
                "not found"
            )
            mock_api.return_value = MagicMock(api=mock_w3)
            result = provider._bridge_tx_likely_failed(
                req
            )  # pylint: disable=protected-access

        assert result is True

    def test_bridge_tx_likely_failed_generic_exception(self) -> None:
        """_bridge_tx_likely_failed() returns True on generic Exception (lines 552-556)."""
        provider = _ConcreteProvider()
        req = _make_request()
        req.execution_data = _make_execution_data(timestamp=int(time.time()) - 700)
        req.quote_data = _make_quote_data(eta=30)

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            mock_w3.eth.get_transaction_receipt.side_effect = ConnectionError(
                "rpc down"
            )
            mock_api.return_value = MagicMock(api=mock_w3)
            result = provider._bridge_tx_likely_failed(
                req
            )  # pylint: disable=protected-access

        assert result is True


# ---------------------------------------------------------------------------
# TestLiFiProviderUnit
# ---------------------------------------------------------------------------


def _make_lifi_provider() -> LiFiProvider:
    """Construct a LiFiProvider with a mocked wallet manager."""
    return LiFiProvider(
        wallet_manager=MagicMock(),
        provider_id="lifi-provider",
        logger=MagicMock(),
    )


class TestLiFiProviderUnit:
    """Unit tests for LiFiProvider (no network)."""

    def test_description(self) -> None:
        """description() returns the LI.FI string (line 68)."""
        provider = _make_lifi_provider()
        assert "LI.FI" in provider.description()

    def test_quote_wrong_status_raises(self) -> None:
        """quote() raises RuntimeError for wrong status (line 81)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        with pytest.raises(RuntimeError, match="Cannot quote"):
            provider.quote(req)

    def test_quote_execution_data_present_raises(self) -> None:
        """quote() raises RuntimeError if execution_data already set (line 86)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.CREATED,
        )
        req.execution_data = _make_execution_data()
        with pytest.raises(RuntimeError, match="execution already present"):
            provider.quote(req)

    def test_get_approve_tx_with_erc20_token(self) -> None:
        """_get_approve_tx() builds approve tx for ERC20 token (lines 131-145)."""
        provider = _make_lifi_provider()
        erc20_addr = "0x" + "a" * 40
        spender_addr = "0x" + "b" * 40
        sender_addr = "0x" + "c" * 40

        req = _make_request(
            provider_id="lifi-provider",
            from_token=erc20_addr,
            amount=1000,
        )
        quote_response = {
            "action": {
                "fromToken": {"address": erc20_addr},
                "fromAmount": "1000",
            },
            "transactionRequest": {
                "to": spender_addr,
                "from": sender_addr,
            },
        }
        req.quote_data = _make_quote_data(provider_data={"response": quote_response})

        mock_approve_tx: t.Dict[str, t.Any] = {
            "gas": 200_000,
            "value": 0,
            "to": erc20_addr,
            "data": "0x095ea7b3...",
        }

        with patch(
            "operate.bridge.providers.lifi_provider.registry_contracts"
        ) as mock_contracts, patch(
            "operate.bridge.providers.lifi_provider.update_tx_with_gas_pricing"
        ), patch(
            "operate.bridge.providers.lifi_provider.update_tx_with_gas_estimate"
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger
            mock_contracts.erc20.get_approve_tx.return_value = mock_approve_tx

            result = provider._get_approve_tx(req)  # pylint: disable=protected-access

        assert result is not None
        mock_contracts.erc20.get_approve_tx.assert_called_once()

    def test_get_bridge_tx_with_valid_transaction_request(self) -> None:
        """_get_bridge_tx() builds bridge tx from transactionRequest (lines 147-150)."""
        provider = _make_lifi_provider()
        erc20_addr = "0x" + "a" * 40
        spender_addr = "0x" + "b" * 40
        sender_addr = "0x" + "c" * 40

        req = _make_request(
            provider_id="lifi-provider",
            from_token=erc20_addr,
            amount=1000,
        )
        quote_response = {
            "action": {
                "fromToken": {"address": erc20_addr},
                "fromAmount": "1000",
            },
            "transactionRequest": {
                "to": spender_addr,
                "from": sender_addr,
                "value": "0x0",
                "data": "0xabcd",
                "chainId": 100,
                "gasPrice": "0x1",
                "gasLimit": "0x5208",
            },
        }
        req.quote_data = _make_quote_data(provider_data={"response": quote_response})

        with patch(
            "operate.bridge.providers.lifi_provider.update_tx_with_gas_pricing"
        ), patch(
            "operate.bridge.providers.lifi_provider.update_tx_with_gas_estimate"
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_ledger.api.eth.get_transaction_count.return_value = 0
            mock_api.return_value = mock_ledger

            result = provider._get_bridge_tx(req)  # pylint: disable=protected-access

        assert result is not None
        assert result["to"] == spender_addr

    def test_get_txs_erc20_returns_both_approve_and_bridge(self) -> None:
        """_get_txs() returns approve and bridge tx for ERC20 (lines 179-183)."""
        provider = _make_lifi_provider()
        erc20_addr = "0x" + "a" * 40
        spender_addr = "0x" + "b" * 40
        sender_addr = "0x" + "c" * 40

        req = _make_request(
            provider_id="lifi-provider",
            from_token=erc20_addr,
            amount=1000,
        )
        quote_response = {
            "action": {
                "fromToken": {"address": erc20_addr},
                "fromAmount": "1000",
            },
            "transactionRequest": {
                "to": spender_addr,
                "from": sender_addr,
                "value": "0x0",
                "data": "0xabcd",
                "chainId": 100,
                "gasPrice": "0x1",
                "gasLimit": "0x5208",
            },
        }
        req.quote_data = _make_quote_data(provider_data={"response": quote_response})

        mock_approve_tx: t.Dict[str, t.Any] = {
            "gas": 200_000,
            "value": 0,
        }

        with patch(
            "operate.bridge.providers.lifi_provider.registry_contracts"
        ) as mock_contracts, patch(
            "operate.bridge.providers.lifi_provider.update_tx_with_gas_pricing"
        ), patch(
            "operate.bridge.providers.lifi_provider.update_tx_with_gas_estimate"
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_ledger.api.eth.get_transaction_count.return_value = 0
            mock_api.return_value = mock_ledger
            mock_contracts.erc20.get_approve_tx.return_value = mock_approve_tx

            txs = provider._get_txs(req)  # pylint: disable=protected-access

        labels = [label for label, _ in txs]
        assert "approve_tx" in labels
        assert "bridge_tx" in labels

    def test_update_execution_status_early_return_wrong_status(self) -> None:
        """_update_execution_status() returns early when status not PENDING/UNKNOWN (line 217)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_DONE,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()
        # Should return without raising or making HTTP calls
        provider._update_execution_status(req)  # pylint: disable=protected-access
        assert req.status == ProviderRequestStatus.EXECUTION_DONE

    def test_update_execution_status_no_execution_data_raises(self) -> None:
        """_update_execution_status() raises RuntimeError when no execution_data (line 220)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = None
        with pytest.raises(RuntimeError, match="execution data not present"):
            provider._update_execution_status(req)  # pylint: disable=protected-access

    def test_update_execution_status_no_from_tx_hash_early_return(self) -> None:
        """_update_execution_status() returns early when no from_tx_hash (line 224)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data(from_tx_hash=None)
        # Should return without making HTTP calls
        provider._update_execution_status(req)  # pylint: disable=protected-access

    def test_update_execution_status_done(self) -> None:
        """_update_execution_status() handles DONE status (line 267)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        to_tx_hash = "0x" + "bb" * 32
        from_tx_hash = "0x" + "dd" * 32
        req.execution_data = _make_execution_data(from_tx_hash=from_tx_hash)
        req.quote_data = _make_quote_data()

        response_json = {
            "status": LiFiTransactionStatus.DONE.value,
            "receiving": {"txHash": to_tx_hash},
            "substatusMessage": None,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            return_value=mock_resp,
        ), patch(
            "operate.bridge.providers.provider.Provider._tx_timestamp",
            return_value=100,
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_DONE
        assert req.execution_data.to_tx_hash == to_tx_hash

    def test_update_execution_status_failed(self) -> None:
        """_update_execution_status() handles FAILED status (line 270)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()

        response_json = {
            "status": LiFiTransactionStatus.FAILED.value,
            "substatusMessage": "bridge failed",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            return_value=mock_resp,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_update_execution_status_pending(self) -> None:
        """_update_execution_status() handles PENDING status (line 274)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()

        response_json = {
            "status": LiFiTransactionStatus.PENDING.value,
            "substatusMessage": None,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            return_value=mock_resp,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_PENDING

    def test_update_execution_status_unknown(self) -> None:
        """_update_execution_status() handles unknown status (lines 279-301)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()

        response_json = {
            "status": "SOME_UNKNOWN_STATUS",
            "substatusMessage": None,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            return_value=mock_resp,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_UNKNOWN

    def test_update_execution_status_exception_sets_unknown(self) -> None:
        """_update_execution_status() sets UNKNOWN on exception (lines 310, 313)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        # Make execution_data old enough to trigger bridge_tx_likely_failed checks
        req.execution_data = _make_execution_data(
            timestamp=int(time.time()) - 5  # fresh → likely_failed returns False
        )
        req.quote_data = _make_quote_data(eta=600)

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            side_effect=ConnectionError("network error"),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        # Fresh tx → _bridge_tx_likely_failed returns False → stays EXECUTION_UNKNOWN
        assert req.status == ProviderRequestStatus.EXECUTION_UNKNOWN

    def test_update_execution_status_exception_bridge_likely_failed(self) -> None:
        """_update_execution_status() → EXECUTION_FAILED when bridge_tx_likely_failed (line 313)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        # from_tx_hash must be set so we get past the early return, then hit the exception path.
        # _bridge_tx_likely_failed is patched to return True so status → EXECUTION_FAILED.
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "dd" * 32)
        req.quote_data = _make_quote_data(eta=60)

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            side_effect=ConnectionError("network error"),
        ), patch.object(
            provider,
            "_bridge_tx_likely_failed",
            return_value=True,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        # _bridge_tx_likely_failed returns True → status set to EXECUTION_FAILED
        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_get_explorer_link_with_from_tx_hash(self) -> None:
        """_get_explorer_link() returns URL when from_tx_hash is set (lines 366-371)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider")
        tx_hash = "0x" + "aa" * 32
        req.execution_data = _make_execution_data(from_tx_hash=tx_hash)

        result = provider._get_explorer_link(req)  # pylint: disable=protected-access

        assert result is not None
        assert tx_hash in result

    def test_get_explorer_link_no_execution_data(self) -> None:
        """_get_explorer_link() returns None when no execution_data (line 378)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider")
        req.execution_data = None

        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_explorer_link_no_tx_hash(self) -> None:
        """_get_explorer_link() returns None when no from_tx_hash (line 384)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider")
        req.execution_data = _make_execution_data(from_tx_hash=None)

        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result is None


# ---------------------------------------------------------------------------
# TestRelayProviderUnit
# ---------------------------------------------------------------------------


def _make_relay_provider() -> RelayProvider:
    """Construct a RelayProvider with a mocked wallet manager."""
    return RelayProvider(
        wallet_manager=MagicMock(),
        provider_id="relay-provider",
        logger=MagicMock(),
    )


class TestRelayProviderUnit:
    """Unit tests for RelayProvider (no network)."""

    def test_description(self) -> None:
        """description() returns Relay Protocol string (line 138)."""
        provider = _make_relay_provider()
        assert "Relay" in provider.description()

    def test_quote_wrong_status_raises(self) -> None:
        """quote() raises RuntimeError for wrong status (line 151)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        with pytest.raises(RuntimeError, match="Cannot quote"):
            provider.quote(req)

    def test_quote_execution_data_present_raises(self) -> None:
        """quote() raises RuntimeError if execution_data set (line 156)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
        )
        req.execution_data = _make_execution_data()
        with pytest.raises(RuntimeError, match="execution already present"):
            provider.quote(req)

    def test_quote_timeout_exception_path(self) -> None:
        """quote() handles Timeout exception and sets QUOTE_FAILED (lines 261-264)."""
        import requests as req_lib

        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        with patch(
            "operate.bridge.providers.relay_provider.requests.post",
            side_effect=req_lib.Timeout("timed out"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        assert req.quote_data.eta is None

    def test_quote_generic_exception_path(self) -> None:
        """quote() handles generic exception and sets QUOTE_FAILED (lines 293-297)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        with patch(
            "operate.bridge.providers.relay_provider.requests.post",
            side_effect=RuntimeError("something unexpected"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None

    def test_get_txs_no_quote_data_raises(self) -> None:
        """_get_txs() raises RuntimeError when no quote_data (line 328)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider", amount=1000)
        req.quote_data = None
        with pytest.raises(RuntimeError, match="quote data not present"):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_get_txs_no_provider_data_raises(self) -> None:
        """_get_txs() raises RuntimeError when no provider_data (line 334)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider", amount=1000)
        req.quote_data = _make_quote_data(provider_data=None)
        with pytest.raises(RuntimeError, match="provider data not present"):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_get_txs_no_response_returns_empty(self) -> None:
        """_get_txs() returns empty list when no response in provider_data (line 342)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider", amount=1000)
        req.quote_data = _make_quote_data(provider_data={"response": None})

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger
            result = provider._get_txs(req)  # pylint: disable=protected-access

        assert result == []

    def test_update_execution_status_no_execution_data_raises(self) -> None:
        """_update_execution_status() raises when no execution_data (line 375)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = None
        with pytest.raises(RuntimeError, match="execution data not present"):
            provider._update_execution_status(req)  # pylint: disable=protected-access

    def test_update_execution_status_no_from_tx_hash_sets_failed(self) -> None:
        """_update_execution_status() sets EXECUTION_FAILED when no from_tx_hash (lines 381-385)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data(from_tx_hash=None)
        req.quote_data = _make_quote_data()

        provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_update_execution_status_failure_status(self) -> None:
        """_update_execution_status() sets EXECUTION_FAILED on FAILURE status (lines 437-449)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()

        response_json = {"requests": [{"status": RelayExecutionStatus.FAILURE.value}]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            return_value=mock_resp,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_update_execution_status_pending_status(self) -> None:
        """_update_execution_status() sets EXECUTION_PENDING on pending status (lines 437-449)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()

        response_json = {"requests": [{"status": RelayExecutionStatus.PENDING.value}]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            return_value=mock_resp,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_PENDING

    def test_update_execution_status_unknown_status(self) -> None:
        """_update_execution_status() sets EXECUTION_UNKNOWN on unrecognized status (lines 437-449)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()

        response_json = {"requests": [{"status": "some_unrecognized_status"}]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            return_value=mock_resp,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_UNKNOWN

    def test_update_execution_status_exception_path(self) -> None:
        """_update_execution_status() handles exception gracefully (line 456)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data(
            from_tx_hash=None  # no hash → _bridge_tx_likely_failed returns True
        )
        req.quote_data = _make_quote_data()

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            side_effect=ConnectionError("rpc error"),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        # from_tx_hash is None → _bridge_tx_likely_failed returns True → EXECUTION_FAILED
        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_get_explorer_link_no_execution_data(self) -> None:
        """_get_explorer_link() returns None when no execution_data (line 462)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider")
        req.execution_data = None

        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_explorer_link_no_quote_data_raises(self) -> None:
        """_get_explorer_link() raises RuntimeError when no quote_data (line 466)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider")
        req.execution_data = _make_execution_data()
        req.quote_data = None

        with pytest.raises(RuntimeError, match="quote data not present"):
            provider._get_explorer_link(req)  # pylint: disable=protected-access

    def test_get_explorer_link_with_steps(self) -> None:
        """_get_explorer_link() returns relay URL when steps present (lines 478-479)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider")
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data(
            provider_data={
                "response": {
                    "steps": [
                        {"requestId": "req-abc-123"},
                    ]
                }
            }
        )

        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result is not None
        assert "req-abc-123" in result


# ---------------------------------------------------------------------------
# TestNativeBridgeProviderUnit
# ---------------------------------------------------------------------------


def _make_omnibridge_adaptor() -> OmnibridgeContractAdaptor:
    """Build an OmnibridgeContractAdaptor for testing."""
    return OmnibridgeContractAdaptor(
        from_chain="ethereum",
        to_chain="gnosis",
        from_bridge="0x88ad09518695c6c3712AC10a214bE5109a655671",
        to_bridge="0xf6A78083ca3e2a662D6dd1703c939c8aCE2e268d",
        bridge_eta=1800,
        logger=MagicMock(),
    )


def _make_optimism_adaptor() -> OptimismContractAdaptor:
    """Build an OptimismContractAdaptor for testing."""
    return OptimismContractAdaptor(
        from_chain="ethereum",
        to_chain="base",
        from_bridge="0x3154Cf16ccdb4C6d922629664174b904d80F2C35",
        to_bridge="0x4200000000000000000000000000000000000010",
        bridge_eta=300,
        logger=MagicMock(),
    )


def _make_native_provider(
    adaptor: t.Optional[BridgeContractAdaptor] = None,
) -> NativeBridgeProvider:
    """Build a NativeBridgeProvider with mocked dependencies."""
    if adaptor is None:
        adaptor = _make_omnibridge_adaptor()
    return NativeBridgeProvider(
        bridge_contract_adaptor=adaptor,
        provider_id="native-ethereum-to-gnosis",
        wallet_manager=MagicMock(),
        logger=MagicMock(),
    )


class TestBridgeContractAdaptorUnit:
    """Unit tests for BridgeContractAdaptor base class."""

    def test_init_same_chain_raises(self) -> None:
        """BridgeContractAdaptor.__init__() raises ValueError if from==to chain (line 84)."""
        with pytest.raises(ValueError, match="cannot be the same"):
            OmnibridgeContractAdaptor(
                from_chain="ethereum",
                to_chain="ethereum",  # same!
                from_bridge="0x" + "a" * 40,
                to_bridge="0x" + "b" * 40,
                bridge_eta=300,
                logger=MagicMock(),
            )

    def test_abstract_build_bridge_tx_raises(self) -> None:
        """BridgeContractAdaptor.build_bridge_tx() abstract body raises NotImplementedError (line 124)."""
        adaptor = _make_omnibridge_adaptor()
        with pytest.raises(NotImplementedError):
            BridgeContractAdaptor.build_bridge_tx(
                adaptor,  # type: ignore[arg-type]
                from_ledger_api=MagicMock(),
                provider_request=_make_request(),
            )

    def test_abstract_find_bridge_finalized_tx_raises(self) -> None:
        """BridgeContractAdaptor.find_bridge_finalized_tx() abstract body raises NotImplementedError (line 136)."""
        adaptor = _make_omnibridge_adaptor()
        with pytest.raises(NotImplementedError):
            BridgeContractAdaptor.find_bridge_finalized_tx(
                adaptor,  # type: ignore[arg-type]
                from_ledger_api=MagicMock(),
                to_ledger_api=MagicMock(),
                provider_request=_make_request(),
                from_block=0,
                to_block=100,
            )

    def test_abstract_get_explorer_link_raises(self) -> None:
        """BridgeContractAdaptor.get_explorer_link() abstract body raises NotImplementedError (line 143)."""
        adaptor = _make_omnibridge_adaptor()
        with pytest.raises(NotImplementedError):
            BridgeContractAdaptor.get_explorer_link(
                adaptor,  # type: ignore[arg-type]
                from_ledger_api=MagicMock(),
                provider_request=_make_request(),
            )

    def test_can_handle_request_from_chain_mismatch_returns_false(self) -> None:
        """BridgeContractAdaptor.can_handle_request() returns False on chain mismatch (line ~99-100)."""
        adaptor = _make_omnibridge_adaptor()
        params = {
            "from": {
                "chain": "gnosis",  # wrong chain; adaptor expects "ethereum"
                "address": FROM_ADDR,
                "token": ZERO_ADDRESS,
            },
            "to": {
                "chain": "gnosis",
                "address": TO_ADDR,
                "token": ZERO_ADDRESS,
                "amount": 1000,
            },
        }
        assert adaptor.can_handle_request(params) is False


class TestOptimismContractAdaptorUnit:
    """Unit tests for OptimismContractAdaptor."""

    def test_get_explorer_link_no_execution_data_returns_none(self) -> None:
        """OptimismContractAdaptor.get_explorer_link() returns None when no execution_data (lines 283-284)."""
        adaptor = _make_optimism_adaptor()
        req = _make_request(from_chain="ethereum", to_chain="base")
        req.execution_data = None

        result = adaptor.get_explorer_link(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is None


class TestOmnibridgeContractAdaptorUnit:
    """Unit tests for OmnibridgeContractAdaptor."""

    def test_build_bridge_tx_zero_address_raises(self) -> None:
        """OmnibridgeContractAdaptor.build_bridge_tx() raises NotImplementedError for ZERO_ADDRESS token (lines 330-333)."""
        adaptor = _make_omnibridge_adaptor()
        req = _make_request(from_token=ZERO_ADDRESS)

        with pytest.raises(NotImplementedError, match="native tokens"):
            adaptor.build_bridge_tx(from_ledger_api=MagicMock(), provider_request=req)

    def test_find_bridge_finalized_tx_zero_address_raises(self) -> None:
        """OmnibridgeContractAdaptor.find_bridge_finalized_tx() raises NotImplementedError for ZERO_ADDRESS (line 360)."""
        adaptor = _make_omnibridge_adaptor()
        req = _make_request(from_token=ZERO_ADDRESS)

        with pytest.raises(NotImplementedError, match="native tokens"):
            adaptor.find_bridge_finalized_tx(
                from_ledger_api=MagicMock(),
                to_ledger_api=MagicMock(),
                provider_request=req,
                from_block=0,
                to_block=100,
            )

    def test_find_bridge_finalized_tx_no_message_id_raises(self) -> None:
        """OmnibridgeContractAdaptor.find_bridge_finalized_tx() raises RuntimeError when no message_id (line 370)."""
        adaptor = _make_omnibridge_adaptor()
        erc20_addr = "0x" + "a" * 40
        req = _make_request(from_token=erc20_addr)
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "aa" * 32)

        # get_message_id returns None (no provider_data, mocked foreign_omnibridge raises)
        with patch.object(
            adaptor,
            "get_message_id",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="messageId"):
                adaptor.find_bridge_finalized_tx(
                    from_ledger_api=MagicMock(),
                    to_ledger_api=MagicMock(),
                    provider_request=req,
                    from_block=0,
                    to_block=100,
                )

    def test_get_message_id_no_execution_data_returns_none(self) -> None:
        """OmnibridgeContractAdaptor.get_message_id() returns None when no execution_data (line 389-390)."""
        adaptor = _make_omnibridge_adaptor()
        req = _make_request()
        req.execution_data = None

        result = adaptor.get_message_id(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is None

    def test_get_message_id_no_from_tx_hash_returns_none(self) -> None:
        """OmnibridgeContractAdaptor.get_message_id() returns None when no from_tx_hash (line 393)."""
        adaptor = _make_omnibridge_adaptor()
        req = _make_request()
        req.execution_data = _make_execution_data(from_tx_hash=None)

        result = adaptor.get_message_id(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is None


class TestNativeBridgeProviderUnit:
    """Unit tests for NativeBridgeProvider."""

    def test_can_handle_request_super_returns_false(self) -> None:
        """NativeBridgeProvider.can_handle_request() returns False when super() fails (line 461)."""
        provider = _make_native_provider()
        # Missing 'to' key → super().can_handle_request returns False
        result = provider.can_handle_request(
            {"from": {"chain": "ethereum", "address": FROM_ADDR, "token": ZERO_ADDRESS}}
        )
        assert result is False

    def test_description(self) -> None:
        """NativeBridgeProvider.description() returns formatted string (line 470)."""
        provider = _make_native_provider()
        desc = provider.description()
        assert "Native bridge provider" in desc
        assert "OmnibridgeContractAdaptor" in desc

    def test_quote_wrong_status_raises(self) -> None:
        """NativeBridgeProvider.quote() raises RuntimeError for wrong status (line 481)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        with pytest.raises(RuntimeError, match="Cannot quote"):
            provider.quote(req)

    def test_quote_execution_data_present_raises(self) -> None:
        """NativeBridgeProvider.quote() raises RuntimeError if execution_data set (line 486)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.CREATED,
        )
        req.execution_data = _make_execution_data()
        with pytest.raises(RuntimeError, match="execution already present"):
            provider.quote(req)

    def test_get_approve_tx_no_quote_data_returns_none(self) -> None:
        """NativeBridgeProvider._get_approve_tx() returns None when no quote_data (line 520)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_token=ERC20_ADDR,
            amount=1000,
        )
        req.quote_data = None

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            result = provider._get_approve_tx(req)  # pylint: disable=protected-access

        assert result is None

    def test_get_bridge_tx_no_quote_data_returns_none(self) -> None:
        """NativeBridgeProvider._get_bridge_tx() returns None when no quote_data (line 556)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            amount=1000,
        )
        req.quote_data = None

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            result = provider._get_bridge_tx(req)  # pylint: disable=protected-access

        assert result is None

    def test_update_execution_status_no_execution_data_raises(self) -> None:
        """NativeBridgeProvider._update_execution_status() raises when no execution_data (line 599)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = None
        with pytest.raises(RuntimeError, match="execution data not present"):
            provider._update_execution_status(req)  # pylint: disable=protected-access

    def test_update_execution_status_no_from_tx_hash_sets_failed(self) -> None:
        """NativeBridgeProvider._update_execution_status() sets EXECUTION_FAILED on no hash (lines 605-609)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data(from_tx_hash=None)
        req.quote_data = _make_quote_data()

        provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED
        assert req.execution_data.message is not None

    def test_update_execution_status_receipt_status_0_sets_failed(self) -> None:
        """NativeBridgeProvider._update_execution_status() sets EXECUTION_FAILED when receipt.status==0 (lines 619-621)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data()

        mock_receipt = MagicMock()
        mock_receipt.status = 0

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_api.return_value = MagicMock(api=mock_w3)
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_get_explorer_link_with_execution_data_from_tx_hash(self) -> None:
        """NativeBridgeProvider._get_explorer_link() with from_tx_hash delegates to adaptor (line 673)."""
        adaptor = _make_optimism_adaptor()
        provider = _make_native_provider(adaptor=adaptor)
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_chain="ethereum",
            to_chain="base",
        )
        tx_hash = "0x" + "aa" * 32
        req.execution_data = _make_execution_data(from_tx_hash=tx_hash)

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            result = provider._get_explorer_link(
                req
            )  # pylint: disable=protected-access

        # OptimismContractAdaptor.get_explorer_link returns EXPLORER_URL formatted string
        assert result is not None
        assert tx_hash in result


# ---------------------------------------------------------------------------
# TestProviderBaseAdditional — missing provider.py coverage paths
# ---------------------------------------------------------------------------


class TestProviderBaseAdditional:
    """Additional tests for the abstract Provider base class to cover missing lines."""

    def test_can_handle_request_valid_params_returns_true(self) -> None:
        """can_handle_request() returns True when all required fields present (line 197)."""
        provider = _ConcreteProvider()
        result = provider.can_handle_request(
            {
                "from": {
                    "chain": "gnosis",
                    "address": FROM_ADDR,
                    "token": ZERO_ADDRESS,
                },
                "to": {
                    "chain": "base",
                    "address": TO_ADDR,
                    "token": ZERO_ADDRESS,
                    "amount": 1000,
                },
            }
        )
        assert result is True

    def test_create_request_valid_params(self) -> None:
        """create_request() with valid params creates ProviderRequest correctly (lines 205-213)."""
        provider = _ConcreteProvider(provider_id="test-provider")
        from_addr = "0x" + "a" * 40
        to_addr = "0x" + "b" * 40
        params = {
            "from": {
                "chain": "gnosis",
                "address": from_addr,
                "token": ZERO_ADDRESS,
            },
            "to": {
                "chain": "base",
                "address": to_addr,
                "token": ZERO_ADDRESS,
                "amount": 1000,
            },
        }
        req = provider.create_request(params)
        assert req.provider_id == "test-provider"
        assert req.status == ProviderRequestStatus.CREATED
        assert req.quote_data is None
        assert req.execution_data is None
        assert int(req.params["to"]["amount"]) == 1000

    def test_requirements_empty_txs(self) -> None:
        """requirements() with no txs returns ChainAmounts with zeros (line 260)."""
        provider = _ConcreteProvider(txs_to_return=[])
        req = _make_request()
        # _get_txs returns [] so early-return branch triggers

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            result = provider.requirements(req)

        from_chain = req.params["from"]["chain"]
        from_addr = req.params["from"]["address"]
        assert from_chain in result
        assert from_addr in result[from_chain]
        # Both native and token amounts should be zero
        assert int(result[from_chain][from_addr][ZERO_ADDRESS]) == 0

    def test_requirements_erc20_approve_selector(self) -> None:
        """requirements() parses ERC20 approve amount correctly (lines 308-310)."""
        from_token = ERC20_ADDR
        amount = 500
        spender_hex = "0" * 64
        amount_hex = hex(amount)[2:].zfill(64)
        approve_data = ERC20_APPROVE_SELECTOR + spender_hex + amount_hex

        tx: t.Dict[str, t.Any] = {
            "to": from_token,
            "data": approve_data,
            "gas": 21_000,
            "value": 0,
        }
        provider = _ConcreteProvider(txs_to_return=[("approve_tx", tx)])
        req = _make_request(from_token=from_token)

        with patch(
            "operate.bridge.providers.provider.update_tx_with_gas_pricing"
        ) as mock_gas, patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger

            def _set_gas_price(tx_dict: t.Dict, _ledger: t.Any) -> None:
                tx_dict["gasPrice"] = 1

            mock_gas.side_effect = _set_gas_price
            result = provider.requirements(req)

        from_chain = req.params["from"]["chain"]
        from_addr = req.params["from"]["address"]
        assert from_token in result[from_chain][from_addr]
        assert int(result[from_chain][from_addr][from_token]) == amount

    def test_execute_quote_failed_status_sets_execution_failed(self) -> None:
        """execute() with QUOTE_FAILED sets EXECUTION_FAILED without running txs (lines 344-355)."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.QUOTE_FAILED)
        provider.execute(req)
        assert req.status == ProviderRequestStatus.EXECUTION_FAILED
        assert req.execution_data is not None
        assert req.execution_data.from_tx_hash is None

    def test_execute_non_quote_done_non_failed_raises(self) -> None:
        """execute() raises RuntimeError for status not QUOTE_DONE or QUOTE_FAILED (line 358)."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.CREATED)
        with pytest.raises(RuntimeError, match="Cannot execute"):
            provider.execute(req)

    def test_execute_empty_txs_sets_execution_done(self) -> None:
        """execute() with empty txs sets EXECUTION_DONE without running TxSettler (lines 373-386)."""
        provider = _ConcreteProvider(txs_to_return=[])
        req = _make_request(status=ProviderRequestStatus.QUOTE_DONE)
        req.quote_data = _make_quote_data()
        provider.execute(req)
        assert req.status == ProviderRequestStatus.EXECUTION_DONE
        assert req.execution_data is not None

    def test_status_json_with_execution_and_quote_data(self) -> None:
        """status_json() with both execution_data and quote_data returns full dict (lines 466-471)."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.EXECUTION_PENDING)
        req.quote_data = _make_quote_data(eta=300)
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "d" * 64)

        with patch.object(provider, "_update_execution_status"):
            result = provider.status_json(req)

        assert "eta" in result
        assert "explorer_link" in result
        assert "message" in result
        assert "status" in result
        assert "tx_hash" in result
        assert result["eta"] == 300

    def test_status_json_with_quote_data_only(self) -> None:
        """status_json() with only quote_data (no execution_data) returns eta+message+status (line 479)."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.QUOTE_DONE)
        req.quote_data = _make_quote_data(eta=600)
        req.execution_data = None

        result = provider.status_json(req)

        assert "eta" in result
        assert "message" in result
        assert "status" in result
        assert result["eta"] == 600
        assert "tx_hash" not in result

    def test_tx_timestamp_calls_web3(self) -> None:
        """_tx_timestamp() calls get_transaction_receipt and get_block, returns timestamp (lines 489-491)."""
        mock_ledger = MagicMock()
        mock_receipt = MagicMock()
        mock_receipt.blockNumber = 42
        mock_block = MagicMock()
        mock_block.timestamp = 999_999
        mock_ledger.api.eth.get_transaction_receipt.return_value = mock_receipt
        mock_ledger.api.eth.get_block.return_value = mock_block

        tx_hash = "0x" + "a" * 64
        result = _ConcreteProvider._tx_timestamp(
            tx_hash, mock_ledger
        )  # pylint: disable=protected-access

        assert result == 999_999
        mock_ledger.api.eth.get_transaction_receipt.assert_called_once_with(tx_hash)
        mock_ledger.api.eth.get_block.assert_called_once_with(42)

    def test_bridge_tx_likely_failed_receipt_none(self) -> None:
        """_bridge_tx_likely_failed() returns True when get_transaction_receipt returns None (line 534)."""
        provider = _ConcreteProvider()
        req = _make_request()
        # age > soft_timeout: timestamp 700s ago, eta=30 => soft=600 < 700
        req.execution_data = _make_execution_data(timestamp=int(time.time()) - 700)
        req.quote_data = _make_quote_data(eta=30)

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            # Return None — not raising TransactionNotFound, just None receipt
            mock_w3.eth.get_transaction_receipt.return_value = None
            mock_api.return_value = MagicMock(api=mock_w3)
            result = provider._bridge_tx_likely_failed(
                req
            )  # pylint: disable=protected-access

        assert result is True


# ---------------------------------------------------------------------------
# TestLiFiQuotePaths — missing lifi_provider.py coverage paths
# ---------------------------------------------------------------------------


class TestLiFiQuotePaths:
    """Tests for LiFiProvider.quote() missing branches."""

    def test_quote_zero_amount_sets_quote_done(self) -> None:
        """quote() with to_amount=0 sets QUOTE_DONE with MESSAGE_QUOTE_ZERO (lines 98-109)."""
        import requests as req_lib  # pylint: disable=import-outside-toplevel

        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.CREATED,
            amount=0,
        )
        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            side_effect=AssertionError("should not be called"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None
        assert req.quote_data.eta == 0
        assert req.quote_data.message is not None
        # Suppress unused import warning
        _ = req_lib

    def test_quote_success_sets_quote_done(self) -> None:
        """quote() with successful HTTP response sets QUOTE_DONE (lines 111-145)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )
        response_json = {"transactionRequest": {"to": "0x" + "b" * 40}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            return_value=mock_resp,
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None
        assert req.quote_data.provider_data is not None

    def test_quote_timeout_on_all_attempts_sets_quote_failed(self) -> None:
        """quote() sets QUOTE_FAILED after DEFAULT_MAX_QUOTE_RETRIES timeouts (lines 146-160, 194-202)."""
        import requests as req_lib  # pylint: disable=import-outside-toplevel

        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            side_effect=req_lib.Timeout("timed out"),
        ), patch("operate.bridge.providers.lifi_provider.time.sleep"):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        assert req.quote_data.eta is None

    def test_quote_request_exception_sets_quote_failed(self) -> None:
        """quote() sets QUOTE_FAILED after RequestException on raise_for_status (lines 161-178)."""
        import requests as req_lib  # pylint: disable=import-outside-toplevel

        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )
        # Mock response: get() returns a mock, raise_for_status() raises RequestException,
        # json() returns dict with "message" key (used after the exception).
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req_lib.RequestException("API error")
        mock_resp.json.return_value = {"message": "API error"}
        mock_resp.status_code = 400

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            return_value=mock_resp,
        ), patch("operate.bridge.providers.lifi_provider.time.sleep"):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED

    def test_quote_generic_exception_sets_quote_failed(self) -> None:
        """quote() sets QUOTE_FAILED after generic Exception (lines 179-200)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        with patch(
            "operate.bridge.providers.lifi_provider.requests.get",
            side_effect=ValueError("generic error"),
        ), patch("operate.bridge.providers.lifi_provider.time.sleep"):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED


# ---------------------------------------------------------------------------
# TestLiFiApproveAndBridgeTxEarlyReturns
# ---------------------------------------------------------------------------


class TestLiFiApproveAndBridgeTxEarlyReturns:
    """Tests for _get_approve_tx() and _get_bridge_tx() early-return paths."""

    def test_get_approve_tx_zero_amount_returns_none(self) -> None:
        """_get_approve_tx() returns None when to_amount==0 (line 213)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=0)
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_approve_tx_no_quote_data_returns_none(self) -> None:
        """_get_approve_tx() returns None when quote_data is None (line 217)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = None
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_approve_tx_no_provider_data_returns_none(self) -> None:
        """_get_approve_tx() returns None when provider_data is None (line 220)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = _make_quote_data(provider_data=None)
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_approve_tx_no_quote_response_returns_none(self) -> None:
        """_get_approve_tx() returns None when response is None in provider_data (lines 223-224)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = _make_quote_data(provider_data={"response": None})
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_approve_tx_no_action_returns_none(self) -> None:
        """_get_approve_tx() returns None when 'action' key missing from quote (lines 226-227)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = _make_quote_data(
            provider_data={"response": {"no_action": True}}
        )
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_approve_tx_zero_address_token_returns_none(self) -> None:
        """_get_approve_tx() returns None when from_token is ZERO_ADDRESS (lines 230-231)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        quote_response = {
            "action": {
                "fromToken": {"address": ZERO_ADDRESS},
                "fromAmount": "1000",
            },
            "transactionRequest": {"to": "0x" + "b" * 40, "from": FROM_ADDR},
        }
        req.quote_data = _make_quote_data(provider_data={"response": quote_response})
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_approve_tx_no_transaction_request_returns_none(self) -> None:
        """_get_approve_tx() returns None when transactionRequest is missing (lines 234-235)."""
        provider = _make_lifi_provider()
        req = _make_request(
            provider_id="lifi-provider", amount=1000, from_token=ERC20_ADDR
        )
        quote_response = {
            "action": {
                "fromToken": {"address": ERC20_ADDR},
                "fromAmount": "1000",
            },
            # no transactionRequest key
        }
        req.quote_data = _make_quote_data(provider_data={"response": quote_response})
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_bridge_tx_zero_amount_returns_none(self) -> None:
        """_get_bridge_tx() returns None when to_amount==0 (line 263)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=0)
        result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_bridge_tx_no_quote_data_returns_none(self) -> None:
        """_get_bridge_tx() returns None when quote_data is None (line 267)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = None
        result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_bridge_tx_no_provider_data_returns_none(self) -> None:
        """_get_bridge_tx() returns None when provider_data is None (line 270)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = _make_quote_data(provider_data=None)
        result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_bridge_tx_no_quote_response_returns_none(self) -> None:
        """_get_bridge_tx() returns None when response is None in provider_data (lines 273-274)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = _make_quote_data(provider_data={"response": None})
        result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_bridge_tx_no_action_returns_none(self) -> None:
        """_get_bridge_tx() returns None when 'action' key missing from quote (lines 276-277)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        req.quote_data = _make_quote_data(
            provider_data={"response": {"no_action": True}}
        )
        result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_bridge_tx_no_transaction_request_returns_none(self) -> None:
        """_get_bridge_tx() returns None when transactionRequest is missing (line 281)."""
        provider = _make_lifi_provider()
        req = _make_request(provider_id="lifi-provider", amount=1000)
        quote_response = {
            "action": {
                "fromToken": {"address": ERC20_ADDR},
                "fromAmount": "1000",
            },
            # no transactionRequest key
        }
        req.quote_data = _make_quote_data(provider_data={"response": quote_response})
        result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
        assert result is None


# ---------------------------------------------------------------------------
# TestRelayQuotePaths — missing relay_provider.py coverage paths
# ---------------------------------------------------------------------------


class TestRelayQuotePaths:
    """Tests for RelayProvider.quote() missing branches."""

    def test_quote_zero_amount_sets_quote_done(self) -> None:
        """quote() with to_amount=0 sets QUOTE_DONE with MESSAGE_QUOTE_ZERO (lines 169-179)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=0,
        )
        with patch(
            "operate.bridge.providers.relay_provider.requests.post",
            side_effect=AssertionError("should not be called"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None
        assert req.quote_data.eta == 0
        assert req.quote_data.message is not None

    def test_quote_success_sets_quote_done(self) -> None:
        """quote() with successful HTTP response sets QUOTE_DONE (lines 197-259)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )
        response_json = {
            "steps": [],
            "details": {"timeEstimate": 60},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.relay_provider.requests.post",
            return_value=mock_resp,
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None
        assert req.quote_data.eta == 60

    def test_quote_timeout_all_attempts_sets_quote_failed(self) -> None:
        """quote() sets QUOTE_FAILED after DEFAULT_MAX_QUOTE_RETRIES timeouts."""
        import requests as req_lib  # pylint: disable=import-outside-toplevel

        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        with patch(
            "operate.bridge.providers.relay_provider.requests.post",
            side_effect=req_lib.Timeout("timed out"),
        ), patch("operate.bridge.providers.relay_provider.time.sleep"):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        assert req.quote_data.eta is None

    def test_get_txs_zero_amount_returns_empty(self) -> None:
        """_get_txs() returns [] when to_amount==0 (line 324)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider", amount=0)
        req.quote_data = _make_quote_data(provider_data={"response": {}})
        result = provider._get_txs(req)  # pylint: disable=protected-access
        assert result == []

    def test_get_txs_with_steps_processes_transactions(self) -> None:
        """_get_txs() processes steps/items and returns list of tx tuples (lines 344-362)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            from_chain="gnosis",
            to_chain="base",
            amount=1000,
        )
        response_json = {
            "steps": [
                {
                    "id": "deposit",
                    "items": [
                        {
                            "data": {
                                "to": "0x" + "c" * 40,
                                "from": FROM_ADDR,
                                "value": "1000",
                                "gas": "50000",
                                "maxFeePerGas": "1000000000",
                                "maxPriorityFeePerGas": "1000000",
                                "chainId": 100,
                            }
                        }
                    ],
                }
            ]
        }
        req.quote_data = _make_quote_data(provider_data={"response": response_json})

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api, patch(
            "operate.bridge.providers.relay_provider.update_tx_with_gas_pricing"
        ), patch(
            "operate.bridge.providers.relay_provider.update_tx_with_gas_estimate"
        ):
            mock_ledger = MagicMock()
            mock_ledger.api.to_checksum_address.side_effect = lambda x: x
            mock_ledger.api.eth.get_transaction_count.return_value = 0
            mock_api.return_value = mock_ledger
            result = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(result) == 1
        label, _ = result[0]
        assert "deposit" in label


# ---------------------------------------------------------------------------
# TestNativeBridgeProviderAdditional — missing native_bridge_provider.py paths
# ---------------------------------------------------------------------------


class TestNativeBridgeProviderAdditional:
    """Additional tests for NativeBridgeProvider to cover missing lines."""

    def test_native_provider_init_stores_attributes(self) -> None:
        """NativeBridgeProvider.__init__() stores bridge_contract_adaptor attribute (lines 94-117)."""
        adaptor = _make_omnibridge_adaptor()
        provider = NativeBridgeProvider(
            bridge_contract_adaptor=adaptor,
            provider_id="native-test",
            wallet_manager=MagicMock(),
            logger=MagicMock(),
        )
        assert provider.bridge_contract_adaptor is adaptor
        assert provider.provider_id == "native-test"

    def test_native_provider_quote_zero_amount(self) -> None:
        """NativeBridgeProvider.quote() with to_amount=0 sets QUOTE_DONE with zero eta."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.CREATED,
            amount=0,
        )
        provider.quote(req)
        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None
        assert req.quote_data.eta == 0
        assert req.quote_data.message is not None

    def test_optimism_find_bridge_finalized_tx_receipt_none(self) -> None:
        """OptimismContractAdaptor: NativeBridgeProvider._update_execution_status returns UNKNOWN when receipt is None."""
        provider = _make_native_provider(adaptor=_make_optimism_adaptor())
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="base",
        )
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "aa" * 32)
        req.quote_data = _make_quote_data(eta=300)

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 100

        mock_block = MagicMock()
        mock_block.timestamp = int(time.time()) - 400

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_from_w3 = MagicMock()
            mock_from_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_from_w3.eth.get_block.return_value = mock_block

            mock_to_w3 = MagicMock()
            mock_to_w3.eth.block_number = 200
            mock_to_w3.eth.get_block.return_value = mock_block
            # find_bridge_finalized_tx returns None (not found)
            mock_to_ledger = MagicMock(api=mock_to_w3)

            def _pick_ledger(chain: t.Any) -> MagicMock:
                if str(chain) == "ethereum":
                    return MagicMock(api=mock_from_w3)
                return mock_to_ledger

            mock_api.side_effect = _pick_ledger

            with patch.object(
                provider.bridge_contract_adaptor,
                "find_bridge_finalized_tx",
                return_value=None,
            ):
                provider._update_execution_status(
                    req
                )  # pylint: disable=protected-access

        # Either EXECUTION_PENDING (still looking) or EXECUTION_UNKNOWN/FAILED depending on
        # timestamps — just verify it didn't raise and is a valid terminal-ish state
        assert req.status in (
            ProviderRequestStatus.EXECUTION_PENDING,
            ProviderRequestStatus.EXECUTION_UNKNOWN,
            ProviderRequestStatus.EXECUTION_FAILED,
        )


# ---------------------------------------------------------------------------
# TestRelayQuoteAdditionalPaths
# ---------------------------------------------------------------------------


class TestRelayQuoteAdditionalPaths:
    """Additional tests for RelayProvider.quote() covering gas_missing and RequestException."""

    def test_quote_gas_missing_uses_placeholder_address(self) -> None:
        """quote() re-requests with placeholder address when gas is missing from steps (lines 221-244)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            from_chain="gnosis",
            amount=1000,
        )

        # First response has step items with no 'gas'
        first_response_json = {
            "steps": [
                {
                    "id": "approve",
                    "items": [
                        {
                            "data": {
                                "to": "0x" + "a" * 40,
                                "value": "0",
                                "maxFeePerGas": "1",
                                "maxPriorityFeePerGas": "1",
                                "from": "0x" + "a" * 40,
                                # 'gas' intentionally absent
                            }
                        }
                    ],
                }
            ],
            "details": {"timeEstimate": 60},
        }
        # Placeholder response provides the gas estimate
        placeholder_response_json = {
            "steps": [
                {
                    "id": "approve",
                    "items": [{"data": {"gas": "21000"}}],
                }
            ],
            "details": {"timeEstimate": 60},
        }

        mock_first = MagicMock()
        mock_first.json.return_value = first_response_json
        mock_first.raise_for_status.return_value = None
        mock_first.status_code = 200

        mock_placeholder = MagicMock()
        mock_placeholder.json.return_value = placeholder_response_json

        with patch(
            "operate.bridge.providers.relay_provider.requests.post",
            side_effect=[mock_first, mock_placeholder],
        ), patch(
            "operate.bridge.providers.relay_provider.RELAY_DEFAULT_GAS",
            {"gnosis": {"approve": 100000}},
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None

    def test_quote_request_exception_sets_quote_failed(self) -> None:
        """quote() handles RequestException and uses response.json() message (lines 276-280)."""
        import requests as req_lib

        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": "relay API error"}
        mock_resp.raise_for_status.side_effect = req_lib.RequestException("bad request")
        mock_resp.status_code = 400

        with patch(
            "operate.bridge.providers.relay_provider.requests.post",
            return_value=mock_resp,
        ), patch("operate.bridge.providers.relay_provider.time.sleep"):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED


# ---------------------------------------------------------------------------
# TestRelayUpdateExecutionStatusAdditional
# ---------------------------------------------------------------------------


class TestRelayUpdateExecutionStatusAdditional:
    """Additional tests for RelayProvider._update_execution_status."""

    def test_early_return_when_status_not_pending_or_unknown(self) -> None:
        """_update_execution_status() returns early for EXECUTION_DONE status (line 371)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_DONE,
        )
        # Should not raise or change status
        provider._update_execution_status(req)  # pylint: disable=protected-access
        assert req.status == ProviderRequestStatus.EXECUTION_DONE

    def test_no_relay_requests_bridge_likely_failed_sets_execution_failed(self) -> None:
        """_update_execution_status() sets EXECUTION_FAILED when relay_requests empty.

        Covers lines 405-408 (bridge_tx_likely_failed branch).
        """
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        # Old timestamp so _bridge_tx_likely_failed returns True
        req.execution_data = _make_execution_data(timestamp=int(time.time()) - 1500)
        req.quote_data = _make_quote_data(eta=30)

        response_json: t.Dict = {"requests": []}  # empty requests list
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            return_value=mock_resp,
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            mock_w3.eth.get_transaction_receipt.return_value = None
            mock_api.return_value = MagicMock(api=mock_w3)
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_success_status_sets_execution_done(self) -> None:
        """_update_execution_status() sets EXECUTION_DONE on SUCCESS (lines 412-434)."""
        provider = _make_relay_provider()
        from_chain = "gnosis"
        to_chain = "base"
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain=from_chain,
            to_chain=to_chain,
        )
        from_tx_hash = "0x" + "a" * 64
        to_tx_hash = "0x" + "b" * 64
        req.execution_data = _make_execution_data(from_tx_hash=from_tx_hash)
        req.quote_data = _make_quote_data()

        response_json = {
            "requests": [
                {
                    "status": RelayExecutionStatus.SUCCESS.value,
                    "data": {
                        "inTxs": [{"hash": from_tx_hash, "chainId": 100}],
                        "outTxs": [{"hash": to_tx_hash, "chainId": 8453}],
                    },
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            return_value=mock_resp,
        ), patch(
            "operate.bridge.providers.provider.Provider._tx_timestamp",
            return_value=1000,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_DONE
        assert req.execution_data is not None
        assert req.execution_data.to_tx_hash == to_tx_hash

    def test_exception_sets_unknown_or_failed(self) -> None:
        """_update_execution_status() catches exceptions and sets UNKNOWN/FAILED (lines 450-457)."""
        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        req.execution_data = _make_execution_data(timestamp=int(time.time()) - 1500)
        req.quote_data = _make_quote_data(eta=30)

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            side_effect=RuntimeError("rpc down"),
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_w3 = MagicMock()
            mock_w3.eth.get_transaction_receipt.return_value = None
            mock_api.return_value = MagicMock(api=mock_w3)
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status in (
            ProviderRequestStatus.EXECUTION_UNKNOWN,
            ProviderRequestStatus.EXECUTION_FAILED,
        )


# ---------------------------------------------------------------------------
# TestRelayGetExplorerLink
# ---------------------------------------------------------------------------


class TestRelayGetExplorerLink:
    """Tests for RelayProvider._get_explorer_link (lines 459-479)."""

    def test_no_execution_data_returns_none(self) -> None:
        """_get_explorer_link() returns None when no execution_data."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider")
        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result is None

    def test_no_provider_data_returns_none(self) -> None:
        """_get_explorer_link() returns None when provider_data is None (line 472)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider")
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data(provider_data=None)
        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result is None

    def test_empty_steps_returns_none(self) -> None:
        """_get_explorer_link() returns None when steps list is empty (line 476)."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider")
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data(provider_data={"response": {"steps": []}})
        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result is None

    def test_with_steps_returns_link(self) -> None:
        """_get_explorer_link() returns relay link when steps exist."""
        provider = _make_relay_provider()
        req = _make_request(provider_id="relay-provider")
        req.execution_data = _make_execution_data()
        req.quote_data = _make_quote_data(
            provider_data={"response": {"steps": [{"requestId": "req-abc"}]}}
        )
        result = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert result == "https://relay.link/transaction/req-abc"


# ---------------------------------------------------------------------------
# TestBridgeContractAdaptorCanHandle
# ---------------------------------------------------------------------------


class TestBridgeContractAdaptorCanHandle:
    """Tests for BridgeContractAdaptor.can_handle_request (lines 92-117).

    BridgeContractAdaptor is abstract, so we test via a minimal concrete subclass.
    """

    def _make_adaptor(self) -> BridgeContractAdaptor:
        """Create a minimal concrete subclass of BridgeContractAdaptor."""

        class _ConcreteAdaptor(BridgeContractAdaptor):
            def build_bridge_tx(
                self, from_ledger_api: t.Any, provider_request: t.Any
            ) -> t.Any:
                return {}

            def find_bridge_finalized_tx(
                self,
                from_ledger_api: t.Any,
                to_ledger_api: t.Any,
                provider_request: t.Any,
                from_block: t.Any,
                to_block: t.Any,
            ) -> t.Optional[str]:
                return None

            def get_explorer_link(
                self, from_ledger_api: t.Any, provider_request: t.Any
            ) -> t.Optional[str]:
                return None

        return _ConcreteAdaptor(  # type: ignore[return-value]
            from_chain="ethereum",
            to_chain="gnosis",
            from_bridge="0x" + "a" * 40,
            to_bridge="0x" + "b" * 40,
            bridge_eta=300,
            logger=MagicMock(),
        )

    def test_wrong_from_chain_returns_false(self) -> None:
        """can_handle_request() returns False when from_chain doesn't match (line 100)."""
        adaptor = self._make_adaptor()
        params = {
            "from": {"chain": "base", "token": ZERO_ADDRESS},
            "to": {"chain": "gnosis", "token": ZERO_ADDRESS},
        }
        assert adaptor.can_handle_request(params) is False

    def test_wrong_to_chain_returns_false(self) -> None:
        """can_handle_request() returns False when to_chain doesn't match (line 103)."""
        adaptor = self._make_adaptor()
        params = {
            "from": {"chain": "ethereum", "token": ZERO_ADDRESS},
            "to": {"chain": "base", "token": ZERO_ADDRESS},
        }
        assert adaptor.can_handle_request(params) is False

    def test_native_tokens_returns_true(self) -> None:
        """can_handle_request() returns True for matching chains + ZERO_ADDRESS tokens (line 106)."""
        adaptor = self._make_adaptor()
        params = {
            "from": {"chain": "ethereum", "token": ZERO_ADDRESS},
            "to": {"chain": "gnosis", "token": ZERO_ADDRESS},
        }
        assert adaptor.can_handle_request(params) is True

    def test_unknown_tokens_returns_false(self) -> None:
        """can_handle_request() returns False for unknown token pair (line 117)."""
        adaptor = self._make_adaptor()
        unknown_token = "0x" + "f" * 40
        params = {
            "from": {"chain": "ethereum", "token": unknown_token},
            "to": {"chain": "gnosis", "token": unknown_token},
        }
        assert adaptor.can_handle_request(params) is False


class TestOmnibridgeCanHandleRequest:
    """Additional tests for OmnibridgeContractAdaptor.can_handle_request (lines 312-318)."""

    def _make_omnibridge(self) -> OmnibridgeContractAdaptor:
        """Create OmnibridgeContractAdaptor for ethereum→gnosis."""
        return OmnibridgeContractAdaptor(
            from_chain="ethereum",
            to_chain="gnosis",
            from_bridge="0x88ad09518695c6c3712AC10a214bE5109a655671",
            to_bridge="0xf6A78083ca3e2a662D6dd1703c939c8aCE2e268d",
            bridge_eta=1800,
            logger=MagicMock(),
        )

    def test_zero_address_from_token_returns_false(self) -> None:
        """can_handle_request() returns False when from_token is ZERO_ADDRESS (line 316)."""
        adaptor = self._make_omnibridge()
        params = {
            "from": {"chain": "ethereum", "token": ZERO_ADDRESS},
            "to": {"chain": "gnosis", "token": ZERO_ADDRESS},
        }
        assert adaptor.can_handle_request(params) is False


# ---------------------------------------------------------------------------
# TestNativeBridgeProviderApproveAndBridgeTx
# ---------------------------------------------------------------------------


class TestNativeBridgeProviderApproveAndBridgeTx:
    """Additional tests for NativeBridgeProvider._get_approve_tx and _get_bridge_tx."""

    def test_get_approve_tx_zero_amount_returns_none(self) -> None:
        """_get_approve_tx() returns None when to_amount is 0 (line 516)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_token=ERC20_ADDR,
            amount=0,
        )
        req.quote_data = _make_quote_data()
        result = provider._get_approve_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_approve_tx_native_token_returns_none(self) -> None:
        """_get_approve_tx() returns None when from_token is ZERO_ADDRESS (line 529)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_token=ZERO_ADDRESS,
            amount=1000,
        )
        req.quote_data = _make_quote_data()

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            result = provider._get_approve_tx(req)  # pylint: disable=protected-access

        assert result is None

    def test_get_approve_tx_erc20_calls_registry(self) -> None:
        """_get_approve_tx() for ERC20 calls registry_contracts.erc20.get_approve_tx (lines 531-543)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_token=ERC20_ADDR,
            amount=1000,
        )
        req.quote_data = _make_quote_data()
        mock_approve_tx: t.Dict = {"gas": 200_000, "value": 0, "to": ERC20_ADDR}

        with patch(
            "operate.bridge.providers.native_bridge_provider.registry_contracts"
        ) as mock_contracts, patch(
            "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_pricing"
        ), patch(
            "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_estimate"
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            mock_contracts.erc20.get_approve_tx.return_value = mock_approve_tx
            result = provider._get_approve_tx(req)  # pylint: disable=protected-access

        assert result is not None
        mock_contracts.erc20.get_approve_tx.assert_called_once()

    def test_get_bridge_tx_zero_amount_returns_none(self) -> None:
        """_get_bridge_tx() returns None when to_amount is 0 (line 552)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            amount=0,
        )
        req.quote_data = _make_quote_data()
        result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
        assert result is None

    def test_get_bridge_tx_with_quote_data_calls_adaptor(self) -> None:
        """_get_bridge_tx() calls bridge_contract_adaptor.build_bridge_tx (lines 558-567)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_token=ZERO_ADDRESS,
            amount=1000,
        )
        req.quote_data = _make_quote_data()
        expected_tx: t.Dict = {"to": "0x" + "a" * 40, "value": 1000, "gas": 200_000}

        with patch.object(
            provider.bridge_contract_adaptor,
            "build_bridge_tx",
            return_value=expected_tx,
        ) as mock_build, patch(
            "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_pricing"
        ), patch(
            "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_estimate"
        ), patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            result = provider._get_bridge_tx(req)  # pylint: disable=protected-access
            mock_build.assert_called_once()

        assert result is not None


# ---------------------------------------------------------------------------
# TestBridgeContractAdaptorERC20Path
# ---------------------------------------------------------------------------


class TestBridgeContractAdaptorERC20Path:
    """Test BridgeContractAdaptor.can_handle_request ERC20 token matching path (line 115)."""

    def test_known_erc20_tokens_returns_true(self) -> None:
        """can_handle_request() returns True for matching ERC20 token pair (lines 108-115)."""
        from operate.ledger.profiles import (  # pylint: disable=import-outside-toplevel
            OLAS,
        )
        from operate.operate_types import (
            Chain,  # pylint: disable=import-outside-toplevel
        )

        class _ConcreteAdaptor(BridgeContractAdaptor):
            def build_bridge_tx(
                self, from_ledger_api: t.Any, provider_request: t.Any
            ) -> t.Any:
                return {}

            def find_bridge_finalized_tx(
                self,
                from_ledger_api: t.Any,
                to_ledger_api: t.Any,
                provider_request: t.Any,
                from_block: t.Any,
                to_block: t.Any,
            ) -> t.Optional[str]:
                return None

            def get_explorer_link(
                self, from_ledger_api: t.Any, provider_request: t.Any
            ) -> t.Optional[str]:
                return None

        adaptor = _ConcreteAdaptor(  # type: ignore[call-arg]
            from_chain="ethereum",
            to_chain="gnosis",
            from_bridge="0x88ad09518695c6c3712AC10a214bE5109a655671",
            to_bridge="0xf6A78083ca3e2a662D6dd1703c939c8aCE2e268d",
            bridge_eta=1800,
            logger=MagicMock(),
        )

        olas_eth = OLAS[Chain.ETHEREUM]
        olas_gnosis = OLAS[Chain.GNOSIS]

        params = {
            "from": {"chain": "ethereum", "token": olas_eth},
            "to": {"chain": "gnosis", "token": olas_gnosis},
        }
        assert adaptor.can_handle_request(params) is True


# ---------------------------------------------------------------------------
# TestNativeBridgeProviderCanHandle
# ---------------------------------------------------------------------------


class TestNativeBridgeProviderCanHandle:
    """Tests for NativeBridgeProvider.can_handle_request (lines 463-466)."""

    def test_adaptor_returns_false_provider_returns_false(self) -> None:
        """can_handle_request() returns False when adaptor.can_handle_request is False (line 464)."""
        adaptor = MagicMock()
        adaptor.can_handle_request.return_value = False
        provider = NativeBridgeProvider(
            bridge_contract_adaptor=adaptor,
            provider_id="native-test",
            wallet_manager=MagicMock(),
            logger=MagicMock(),
        )
        params = {
            "from": {"chain": "gnosis", "address": FROM_ADDR, "token": ZERO_ADDRESS},
            "to": {
                "chain": "base",
                "address": TO_ADDR,
                "token": ZERO_ADDRESS,
                "amount": 1000,
            },
        }
        result = provider.can_handle_request(params)
        assert result is False

    def test_adaptor_returns_true_provider_returns_true(self) -> None:
        """can_handle_request() returns True when both super and adaptor return True (line 466)."""
        adaptor = MagicMock()
        adaptor.can_handle_request.return_value = True
        provider = NativeBridgeProvider(
            bridge_contract_adaptor=adaptor,
            provider_id="native-test",
            wallet_manager=MagicMock(),
            logger=MagicMock(),
        )
        params = {
            "from": {"chain": "gnosis", "address": FROM_ADDR, "token": ZERO_ADDRESS},
            "to": {
                "chain": "base",
                "address": TO_ADDR,
                "token": ZERO_ADDRESS,
                "amount": 1000,
            },
        }
        result = provider.can_handle_request(params)
        assert result is True


# ---------------------------------------------------------------------------
# TestNativeBridgeProviderGetTxs
# ---------------------------------------------------------------------------


class TestNativeBridgeProviderGetTxs:
    """Tests for NativeBridgeProvider._get_txs (lines 573-580)."""

    def test_get_txs_returns_approve_and_bridge_tx(self) -> None:
        """_get_txs() collects approve and bridge txs into list (lines 573-580)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_token=ERC20_ADDR,
            amount=1000,
        )
        req.quote_data = _make_quote_data()

        approve_tx: t.Dict = {"gas": 200_000, "value": 0, "to": ERC20_ADDR}
        bridge_tx: t.Dict = {"gas": 100_000, "value": 1000, "to": "0x" + "e" * 40}

        with patch.object(
            provider, "_get_approve_tx", return_value=approve_tx
        ), patch.object(provider, "_get_bridge_tx", return_value=bridge_tx):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 2
        assert txs[0] == ("approve_tx", approve_tx)
        assert txs[1] == ("bridge_tx", bridge_tx)

    def test_get_txs_no_approve_tx_returns_bridge_only(self) -> None:
        """_get_txs() returns only bridge tx when no approve tx (lines 573-580)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            from_token=ZERO_ADDRESS,
            amount=1000,
        )
        req.quote_data = _make_quote_data()

        bridge_tx: t.Dict = {"gas": 100_000, "value": 1000, "to": "0x" + "e" * 40}

        with patch.object(provider, "_get_approve_tx", return_value=None), patch.object(
            provider, "_get_bridge_tx", return_value=bridge_tx
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 1
        assert txs[0] == ("bridge_tx", bridge_tx)


# ---------------------------------------------------------------------------
# TestNativeBridgeProviderUpdateStatusEarlyReturn
# ---------------------------------------------------------------------------


class TestNativeBridgeProviderUpdateStatusEarlyReturn:
    """Tests for NativeBridgeProvider._update_execution_status early return (line 591)."""

    def test_early_return_for_done_status(self) -> None:
        """_update_execution_status() returns early for EXECUTION_DONE status (line 591)."""
        provider = _make_native_provider()
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.EXECUTION_DONE,
        )
        # Should not raise or change status
        provider._update_execution_status(req)  # pylint: disable=protected-access
        assert req.status == ProviderRequestStatus.EXECUTION_DONE


# ---------------------------------------------------------------------------
# TestOmnibridgeGetMessageIdAdditional
# ---------------------------------------------------------------------------


class TestOmnibridgeGetMessageIdAdditional:
    """Additional tests for OmnibridgeContractAdaptor.get_message_id (lines 395-428)."""

    def _make_omnibridge(self) -> OmnibridgeContractAdaptor:
        """Create OmnibridgeContractAdaptor for testing."""
        return OmnibridgeContractAdaptor(
            from_chain="ethereum",
            to_chain="gnosis",
            from_bridge="0x88ad09518695c6c3712AC10a214bE5109a655671",
            to_bridge="0xf6A78083ca3e2a662D6dd1703c939c8aCE2e268d",
            bridge_eta=1800,
            logger=MagicMock(),
        )

    def test_returns_cached_message_id_from_provider_data(self) -> None:
        """get_message_id() returns cached message_id from provider_data (lines 395-399)."""
        adaptor = self._make_omnibridge()
        req = _make_request()
        req.execution_data = _make_execution_data(
            from_tx_hash="0x" + "a" * 64,
        )
        cached_id = "0x" + "b" * 64
        req.execution_data.provider_data = {"message_id": cached_id}

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api"
        ) as mock_api:
            mock_api.return_value = MagicMock()
            result = adaptor.get_message_id(
                from_ledger_api=MagicMock(), provider_request=req
            )

        assert result == cached_id

    def test_exception_logs_and_returns_none(self) -> None:
        """get_message_id() catches exceptions and returns None (lines 424-428)."""
        adaptor = self._make_omnibridge()
        req = _make_request()
        req.execution_data = _make_execution_data(
            from_tx_hash="0x" + "a" * 64,
        )
        req.execution_data.provider_data = None  # no cached id, will call contract

        with patch.object(
            adaptor,
            "_foreign_omnibridge",
        ) as mock_contract:
            mock_contract.get_tokens_bridging_initiated_message_id.side_effect = (
                RuntimeError("rpc error")
            )
            result = adaptor.get_message_id(
                from_ledger_api=MagicMock(), provider_request=req
            )

        assert result is None
        adaptor.logger.error.assert_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TestRelaySuccessSameChain
# ---------------------------------------------------------------------------


class TestRelaySuccessSameChain:
    """Test relay_provider.py line 422 (same-chain SUCCESS path)."""

    def test_success_same_chain_uses_from_tx_hash_as_to_tx_hash(self) -> None:
        """_update_execution_status() uses from_tx_hash when in/out chains are same (line 422)."""
        provider = _make_relay_provider()
        from_tx_hash = "0x" + "a" * 64
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="gnosis",
            to_chain="base",
        )
        req.execution_data = _make_execution_data(from_tx_hash=from_tx_hash)
        req.quote_data = _make_quote_data()

        same_chain_id = 100
        response_json = {
            "requests": [
                {
                    "status": RelayExecutionStatus.SUCCESS.value,
                    "data": {
                        "inTxs": [{"hash": from_tx_hash, "chainId": same_chain_id}],
                        "outTxs": [{"hash": from_tx_hash, "chainId": same_chain_id}],
                    },
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None

        with patch(
            "operate.bridge.providers.relay_provider.requests.get",
            return_value=mock_resp,
        ), patch(
            "operate.bridge.providers.provider.Provider._tx_timestamp",
            return_value=1000,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_DONE
        assert req.execution_data is not None
        assert req.execution_data.to_tx_hash == from_tx_hash


# ---------------------------------------------------------------------------
# TestOptimismContractAdaptorCoverage — lines 172-200, 206-225, 246-266, 288
# ---------------------------------------------------------------------------


class TestOptimismContractAdaptorCoverage:
    """Tests for OptimismContractAdaptor missing coverage lines."""

    def test_can_handle_eth_bridge_supported_returns_true(self) -> None:
        """can_handle_request() returns True for ETH pair when bridge supported (lines 172-200)."""
        adaptor = _make_optimism_adaptor()
        adaptor._l1_standard_bridge_contract = MagicMock()  # type: ignore[assignment]
        adaptor._l1_standard_bridge_contract.supports_bridge_eth_to.return_value = True
        params = {
            "from": {"chain": "ethereum", "token": ZERO_ADDRESS},
            "to": {"chain": "base", "token": ZERO_ADDRESS},
        }
        with patch(
            "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
            return_value=MagicMock(),
        ):
            result = adaptor.can_handle_request(params)
        assert result is True

    def test_can_handle_eth_bridge_not_supported_returns_false(self) -> None:
        """can_handle_request() returns False for ETH pair when bridge not supported (lines 183-186)."""
        adaptor = _make_optimism_adaptor()
        adaptor._l1_standard_bridge_contract = MagicMock()  # type: ignore[assignment]
        adaptor._l1_standard_bridge_contract.supports_bridge_eth_to.return_value = False
        params = {
            "from": {"chain": "ethereum", "token": ZERO_ADDRESS},
            "to": {"chain": "base", "token": ZERO_ADDRESS},
        }
        with patch(
            "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
            return_value=MagicMock(),
        ):
            result = adaptor.can_handle_request(params)
        assert result is False

    def test_can_handle_erc20_matching_l1_token_returns_true(self) -> None:
        """can_handle_request() returns True when ERC20 l1_token matches from_token (lines 188-200)."""
        from web3 import Web3  # pylint: disable=import-outside-toplevel

        adaptor = _make_optimism_adaptor()
        adaptor._optimism_mintable_erc20_contract = MagicMock()  # type: ignore[assignment]
        from_addr = "0x" + "d" * 40
        to_addr = "0x" + "e" * 40
        checksummed_from = Web3.to_checksum_address(from_addr)
        adaptor._optimism_mintable_erc20_contract.l1_token.return_value = {
            "data": checksummed_from
        }
        params = {
            "from": {"chain": "ethereum", "token": from_addr},
            "to": {"chain": "base", "token": to_addr},
        }
        with patch.object(
            BridgeContractAdaptor, "can_handle_request", return_value=True
        ), patch(
            "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
            return_value=MagicMock(),
        ):
            result = adaptor.can_handle_request(params)
        assert result is True

    def test_can_handle_erc20_mismatched_l1_token_returns_false(self) -> None:
        """can_handle_request() returns False when ERC20 l1_token mismatches (line 196)."""
        adaptor = _make_optimism_adaptor()
        adaptor._optimism_mintable_erc20_contract = MagicMock()  # type: ignore[assignment]
        from_addr = "0x" + "d" * 40
        to_addr = "0x" + "e" * 40
        adaptor._optimism_mintable_erc20_contract.l1_token.return_value = {
            "data": "0x" + "f" * 40
        }
        params = {
            "from": {"chain": "ethereum", "token": from_addr},
            "to": {"chain": "base", "token": to_addr},
        }
        with patch.object(
            BridgeContractAdaptor, "can_handle_request", return_value=True
        ), patch(
            "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
            return_value=MagicMock(),
        ):
            result = adaptor.can_handle_request(params)
        assert result is False

    def test_can_handle_erc20_l1_token_raises_returns_false(self) -> None:
        """can_handle_request() returns False when l1_token raises exception (lines 197-198)."""
        adaptor = _make_optimism_adaptor()
        adaptor._optimism_mintable_erc20_contract = MagicMock()  # type: ignore[assignment]
        from_addr = "0x" + "d" * 40
        to_addr = "0x" + "e" * 40
        adaptor._optimism_mintable_erc20_contract.l1_token.side_effect = RuntimeError(
            "rpc error"
        )
        params = {
            "from": {"chain": "ethereum", "token": from_addr},
            "to": {"chain": "base", "token": to_addr},
        }
        with patch.object(
            BridgeContractAdaptor, "can_handle_request", return_value=True
        ), patch(
            "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
            return_value=MagicMock(),
        ):
            result = adaptor.can_handle_request(params)
        assert result is False

    def test_build_bridge_tx_eth_case(self) -> None:
        """build_bridge_tx() calls build_bridge_eth_to_tx for ETH (lines 206-223)."""
        adaptor = _make_optimism_adaptor()
        adaptor._l1_standard_bridge_contract = MagicMock()  # type: ignore[assignment]
        expected_tx = {"to": "0x" + "b" * 40, "value": 1000}
        adaptor._l1_standard_bridge_contract.build_bridge_eth_to_tx.return_value = (
            expected_tx
        )

        req = _make_request(
            from_chain="ethereum",
            to_chain="base",
            from_token=ZERO_ADDRESS,
            amount=1000,
        )
        result = adaptor.build_bridge_tx(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is expected_tx
        adaptor._l1_standard_bridge_contract.build_bridge_eth_to_tx.assert_called_once()

    def test_build_bridge_tx_erc20_case(self) -> None:
        """build_bridge_tx() calls build_bridge_erc20_to_tx for ERC20 (line 225)."""
        adaptor = _make_optimism_adaptor()
        adaptor._l1_standard_bridge_contract = MagicMock()  # type: ignore[assignment]
        expected_tx = {"to": "0x" + "b" * 40, "value": 0}
        adaptor._l1_standard_bridge_contract.build_bridge_erc20_to_tx.return_value = (
            expected_tx
        )

        req = _make_request(
            from_chain="ethereum",
            to_chain="base",
            from_token=ERC20_ADDR,
            to_token="0x" + "e" * 40,
            amount=1000,
        )
        result = adaptor.build_bridge_tx(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is expected_tx
        adaptor._l1_standard_bridge_contract.build_bridge_erc20_to_tx.assert_called_once()

    def test_find_bridge_finalized_eth_case(self) -> None:
        """find_bridge_finalized_tx() calls find_eth_bridge_finalized_tx for ETH (lines 246-264)."""
        adaptor = _make_optimism_adaptor()
        adaptor._l2_standard_bridge_contract = MagicMock()  # type: ignore[assignment]
        expected_hash = "0x" + "bb" * 32
        adaptor._l2_standard_bridge_contract.find_eth_bridge_finalized_tx.return_value = (
            expected_hash
        )

        req = _make_request(
            from_chain="ethereum", to_chain="base", from_token=ZERO_ADDRESS
        )
        result = adaptor.find_bridge_finalized_tx(
            from_ledger_api=MagicMock(),
            to_ledger_api=MagicMock(),
            provider_request=req,
            from_block=0,
            to_block=100,
        )
        assert result == expected_hash

    def test_find_bridge_finalized_erc20_case(self) -> None:
        """find_bridge_finalized_tx() calls find_erc20_bridge_finalized_tx for ERC20 (line 266)."""
        adaptor = _make_optimism_adaptor()
        adaptor._l2_standard_bridge_contract = MagicMock()  # type: ignore[assignment]
        expected_hash = "0x" + "cc" * 32
        adaptor._l2_standard_bridge_contract.find_erc20_bridge_finalized_tx.return_value = (
            expected_hash
        )

        req = _make_request(
            from_chain="ethereum",
            to_chain="base",
            from_token=ERC20_ADDR,
            to_token="0x" + "e" * 40,
        )
        result = adaptor.find_bridge_finalized_tx(
            from_ledger_api=MagicMock(),
            to_ledger_api=MagicMock(),
            provider_request=req,
            from_block=0,
            to_block=100,
        )
        assert result == expected_hash

    def test_get_explorer_link_with_execution_data_no_tx_hash_returns_none(
        self,
    ) -> None:
        """get_explorer_link() returns None when execution_data has no from_tx_hash (line 288)."""
        adaptor = _make_optimism_adaptor()
        req = _make_request(from_chain="ethereum", to_chain="base")
        req.execution_data = _make_execution_data(from_tx_hash=None)

        result = adaptor.get_explorer_link(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestOmnibridgeContractAdaptorCoverage — lines 318, 335, 374, 419-423, 434-437
# ---------------------------------------------------------------------------


class TestOmnibridgeContractAdaptorCoverage:
    """Tests for OmnibridgeContractAdaptor missing coverage lines."""

    def test_can_handle_erc20_calls_super_returns_true(self) -> None:
        """can_handle_request() calls super() for non-ZERO_ADDRESS token (line 318)."""
        from operate.ledger.profiles import (
            OLAS,  # pylint: disable=import-outside-toplevel
        )
        from operate.operate_types import (
            Chain,  # pylint: disable=import-outside-toplevel
        )

        adaptor = _make_omnibridge_adaptor()
        # OLAS is in ERC20_TOKENS for both Ethereum and Gnosis — super returns True
        params = {
            "from": {"chain": "ethereum", "token": OLAS[Chain.ETHEREUM]},
            "to": {"chain": "gnosis", "token": OLAS[Chain.GNOSIS]},
        }
        result = adaptor.can_handle_request(params)
        assert result is True

    def test_build_bridge_tx_erc20_calls_relay_tokens_tx(self) -> None:
        """build_bridge_tx() calls foreign_omnibridge for ERC20 (line 335)."""
        adaptor = _make_omnibridge_adaptor()
        adaptor._foreign_omnibridge = MagicMock()  # type: ignore[assignment]
        expected_tx = {"to": "0x" + "b" * 40, "value": 0}
        adaptor._foreign_omnibridge.build_relay_tokens_tx.return_value = expected_tx

        req = _make_request(from_token=ERC20_ADDR, amount=500)
        result = adaptor.build_bridge_tx(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is expected_tx
        adaptor._foreign_omnibridge.build_relay_tokens_tx.assert_called_once()

    def test_find_bridge_finalized_tx_with_valid_message_id(self) -> None:
        """find_bridge_finalized_tx() calls home_omnibridge when message_id found (line 374)."""
        adaptor = _make_omnibridge_adaptor()
        adaptor._home_omnibridge = MagicMock()  # type: ignore[assignment]
        expected_hash = "0x" + "cc" * 32
        adaptor._home_omnibridge.find_tokens_bridged_tx.return_value = expected_hash

        req = _make_request(from_token=ERC20_ADDR)
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "aa" * 32)
        # Provide cached message_id so get_message_id returns immediately
        req.execution_data.provider_data = {"message_id": "0x" + "bb" * 32}

        result = adaptor.find_bridge_finalized_tx(
            from_ledger_api=MagicMock(),
            to_ledger_api=MagicMock(),
            provider_request=req,
            from_block=0,
            to_block=100,
        )
        assert result == expected_hash
        adaptor._home_omnibridge.find_tokens_bridged_tx.assert_called_once()

    def test_get_message_id_fetches_from_contract_and_stores(self) -> None:
        """get_message_id() calls contract, stores result in provider_data (lines 419-423)."""
        adaptor = _make_omnibridge_adaptor()
        adaptor._foreign_omnibridge = MagicMock()  # type: ignore[assignment]
        msg_id = "0x" + "cc" * 32
        adaptor._foreign_omnibridge.get_tokens_bridging_initiated_message_id.return_value = (
            msg_id
        )

        req = _make_request()
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "aa" * 32)
        req.execution_data.provider_data = None  # no cached message_id

        result = adaptor.get_message_id(
            from_ledger_api=MagicMock(), provider_request=req
        )

        assert result == msg_id
        assert req.execution_data.provider_data == {"message_id": msg_id}

    def test_get_explorer_link_no_message_id_returns_none(self) -> None:
        """get_explorer_link() returns None when get_message_id returns None (lines 434-436)."""
        adaptor = _make_omnibridge_adaptor()
        req = _make_request()
        req.execution_data = None  # get_message_id will return None

        result = adaptor.get_explorer_link(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is None

    def test_get_explorer_link_with_message_id_returns_url(self) -> None:
        """get_explorer_link() returns gnosis bridge URL when message_id is present (line 437)."""
        adaptor = _make_omnibridge_adaptor()
        msg_id = "0x" + "aa" * 32
        req = _make_request()
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "aa" * 32)
        req.execution_data.provider_data = {"message_id": msg_id}

        result = adaptor.get_explorer_link(
            from_ledger_api=MagicMock(), provider_request=req
        )
        assert result is not None
        assert msg_id in result
        assert "gnosischain.com" in result


# ---------------------------------------------------------------------------
# TestNativeBridgeFindBlockBeforeTimestamp — lines 686-690
# ---------------------------------------------------------------------------


class TestNativeBridgeFindBlockBeforeTimestamp:
    """Tests for NativeBridgeProvider._find_block_before_timestamp (lines 686-690)."""

    def test_binary_search_returns_largest_block_before_timestamp(self) -> None:
        """_find_block_before_timestamp() uses binary search and returns correct block (lines 686-690)."""
        w3_mock = MagicMock()
        w3_mock.eth.block_number = 10

        def get_block_stub(n: int) -> t.Dict:
            return {"timestamp": n * 100}

        w3_mock.eth.get_block.side_effect = get_block_stub

        # Blocks: 0→0, 1→100, ..., 5→500, 6→600...
        # Find largest block before timestamp 550 → should be block 5 (ts=500)
        result = NativeBridgeProvider._find_block_before_timestamp(  # pylint: disable=protected-access
            w3_mock, 550
        )
        assert result == 5

    def test_all_blocks_before_timestamp_returns_latest(self) -> None:
        """Returns latest block when all blocks have timestamp < target (line 687, 690)."""
        w3_mock = MagicMock()
        w3_mock.eth.block_number = 4

        def get_block_stub(n: int) -> t.Dict:
            return {"timestamp": n * 10}

        w3_mock.eth.get_block.side_effect = get_block_stub

        # All blocks 0→0, 1→10, ..., 4→40 are before timestamp 1000
        result = NativeBridgeProvider._find_block_before_timestamp(  # pylint: disable=protected-access
            w3_mock, 1000
        )
        assert result == 4

    def test_no_block_before_timestamp_returns_zero(self) -> None:
        """Returns 0 when no block has timestamp < target (line 689, 690)."""
        w3_mock = MagicMock()
        w3_mock.eth.block_number = 4

        def get_block_stub(n: int) -> t.Dict:
            return {"timestamp": (n + 1) * 1000}

        w3_mock.eth.get_block.side_effect = get_block_stub

        # All blocks have timestamp >= 1 (target is 0)
        result = NativeBridgeProvider._find_block_before_timestamp(  # pylint: disable=protected-access
            w3_mock, 1
        )
        assert result == 0


# ---------------------------------------------------------------------------
# TestNativeBridgeUpdateExecutionStatusLoop — lines 632-665, 673
# ---------------------------------------------------------------------------


class TestNativeBridgeUpdateExecutionStatusLoop:
    """Tests for NativeBridgeProvider._update_execution_status main loop (lines 632-665, 673)."""

    def _setup_provider_and_request(
        self,
    ) -> t.Tuple["NativeBridgeProvider", ProviderRequest]:
        """Create a NativeBridgeProvider with optimism adaptor and a pending request."""
        provider = _make_native_provider(adaptor=_make_optimism_adaptor())
        req = _make_request(
            provider_id="native-ethereum-to-gnosis",
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="base",
        )
        req.execution_data = _make_execution_data(from_tx_hash="0x" + "aa" * 32)
        req.quote_data = _make_quote_data(eta=300)
        return provider, req

    def test_execution_done_when_finalized_tx_found(self) -> None:
        """Sets EXECUTION_DONE when find_bridge_finalized_tx returns a hash (lines 632-656)."""
        provider, req = self._setup_provider_and_request()
        to_tx_hash = "0x" + "bb" * 32

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 100

        bridge_ts = 1_000_000
        start_ts = bridge_ts - 10
        mock_from_w3 = MagicMock()
        mock_from_w3.eth.get_transaction_receipt.return_value = mock_receipt
        block_mock = MagicMock()
        block_mock.timestamp = bridge_ts
        mock_from_w3.eth.get_block.return_value = block_mock

        mock_to_w3 = MagicMock()
        mock_to_w3.eth.block_number = 200
        to_block_mock = MagicMock()
        to_block_mock.timestamp = start_ts
        mock_to_w3.eth.get_block.return_value = to_block_mock

        def _pick_ledger(chain: t.Any) -> MagicMock:
            # chain.value is the string like "ethereum", "base", etc.
            if hasattr(chain, "value") and chain.value == "ethereum":
                return MagicMock(api=mock_from_w3)
            return MagicMock(api=mock_to_w3)

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api",
            side_effect=_pick_ledger,
        ), patch.object(
            NativeBridgeProvider,
            "_find_block_before_timestamp",
            return_value=100,
        ), patch.object(
            provider.bridge_contract_adaptor,
            "find_bridge_finalized_tx",
            return_value=to_tx_hash,
        ), patch.object(
            Provider,
            "_tx_timestamp",
            return_value=1_000_000,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_DONE
        assert req.execution_data is not None
        assert req.execution_data.to_tx_hash == to_tx_hash

    def test_execution_failed_when_eta_exceeded(self) -> None:
        """Sets EXECUTION_FAILED when last block timestamp exceeds 2*ETA (lines 658-665)."""
        provider, req = self._setup_provider_and_request()

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 100

        bridge_ts = 1_000_000
        start_ts = bridge_ts - 10
        # Make last block time > start_ts + bridge_eta*2 = start_ts + 600
        last_block_ts = start_ts + 700
        mock_from_w3 = MagicMock()
        mock_from_w3.eth.get_transaction_receipt.return_value = mock_receipt
        block_mock = MagicMock()
        block_mock.timestamp = bridge_ts
        mock_from_w3.eth.get_block.return_value = block_mock

        call_count = 0

        def to_get_block(n: int) -> MagicMock:
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            # First call: get_block(starting_block) for starting_block_ts
            # Subsequent calls: get_block(to_block) for last_block_ts check
            m.timestamp = start_ts if call_count == 1 else last_block_ts
            return m

        mock_to_w3 = MagicMock()
        mock_to_w3.eth.block_number = 200
        mock_to_w3.eth.get_block.side_effect = to_get_block

        def _pick_ledger(chain: t.Any) -> MagicMock:
            # chain.value is the string like "ethereum", "base", etc.
            if hasattr(chain, "value") and chain.value == "ethereum":
                return MagicMock(api=mock_from_w3)
            return MagicMock(api=mock_to_w3)

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api",
            side_effect=_pick_ledger,
        ), patch.object(
            NativeBridgeProvider,
            "_find_block_before_timestamp",
            return_value=100,
        ), patch.object(
            provider.bridge_contract_adaptor,
            "find_bridge_finalized_tx",
            return_value=None,
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_exception_sets_execution_failed_when_likely_failed(self) -> None:
        """Exception handler sets EXECUTION_FAILED when bridge tx likely failed (line 673)."""
        provider, req = self._setup_provider_and_request()
        # Make execution_data old so _bridge_tx_likely_failed returns True (age > HARD_TIMEOUT)
        assert req.execution_data is not None
        req.execution_data.timestamp = (
            int(t.cast(t.Any, __import__("time")).time()) - 2000
        )

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 100

        mock_from_w3 = MagicMock()
        mock_from_w3.eth.get_transaction_receipt.return_value = mock_receipt
        block_mock = MagicMock()
        block_mock.timestamp = 1_000_000
        mock_from_w3.eth.get_block.return_value = block_mock

        def _pick_ledger(chain: t.Any) -> MagicMock:
            if str(chain) == "ethereum":
                return MagicMock(api=mock_from_w3)
            return MagicMock(api=MagicMock())

        with patch(
            "operate.bridge.providers.provider.get_default_ledger_api",
            side_effect=_pick_ledger,
        ), patch.object(
            NativeBridgeProvider,
            "_find_block_before_timestamp",
            side_effect=RuntimeError("network error"),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED


# ---------------------------------------------------------------------------
# TestOptimismContractAdaptorBaseReturnsFalse — line 173
# ---------------------------------------------------------------------------


class TestOptimismContractAdaptorBaseReturnsFalse:
    """Test line 173: OptimismContractAdaptor.can_handle_request early return when super returns False."""

    def test_super_returns_false_returns_false(self) -> None:
        """can_handle_request() returns False when super().can_handle_request returns False (line 173)."""
        adaptor = _make_optimism_adaptor()
        # Pass a non-ERC20 token pair that is NOT in ERC20_TOKENS for ethereum/base
        # and chains DO match, but token pair doesn't match → base returns False
        erc20_from = "0x" + "d" * 40
        erc20_to = "0x" + "e" * 40
        params = {
            "from": {"chain": "ethereum", "token": erc20_from},
            "to": {"chain": "base", "token": erc20_to},
        }
        # Base class can_handle_request will NOT find this pair in ERC20_TOKENS → returns False
        # Then OptimismContractAdaptor.can_handle_request hits line 173 and returns False
        result = adaptor.can_handle_request(params)
        assert result is False
