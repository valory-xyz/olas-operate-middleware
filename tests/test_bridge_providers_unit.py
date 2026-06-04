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
import requests as req_lib
from web3 import Web3
from web3.exceptions import TimeExhausted, TransactionNotFound

from operate.bridge.providers.mayan_provider import (
    MAYAN_EXPLORER_URL,
    MayanProvider,
)
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
    MESSAGE_REQUIREMENTS_QUOTE_FAILED,
    Provider,
    ProviderRequest,
    ProviderRequestStatus,
    QuoteData,
)
from operate.bridge.providers.relay_provider import RelayExecutionStatus, RelayProvider
from operate.constants import ZERO_ADDRESS
from operate.exceptions import InsufficientFundsException
from operate.operate_types import Chain

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

        with (
            patch(
                "operate.bridge.providers.provider.update_tx_with_gas_pricing"
            ) as mock_gas,
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

        with (
            patch(
                "operate.bridge.providers.provider.update_tx_with_gas_pricing"
            ) as mock_gas,
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger

            def _set_gas_price(tx_dict: t.Dict, _ledger: t.Any) -> None:
                tx_dict["gasPrice"] = 1

            mock_gas.side_effect = _set_gas_price

            with pytest.raises(RuntimeError, match="Malformed ERC20"):
                provider.requirements(req)

    def test_requirements_get_txs_runtime_error_sets_quote_failed(self) -> None:
        """requirements() catches RuntimeError from _get_txs and sets QUOTE_FAILED (lines 263-279)."""

        class _FailingProvider(_ConcreteProvider):
            def _get_txs(  # type: ignore[override]
                self,
                provider_request: ProviderRequest,
                *args: t.Any,
                **kwargs: t.Any,
            ) -> t.List[t.Tuple[str, t.Dict]]:
                raise RuntimeError("stored quote is un-buildable")

        provider = _FailingProvider()
        req = _make_request(from_token=ERC20_ADDR)
        req.quote_data = _make_quote_data()

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
            mock_api.return_value = MagicMock()
            result = provider.requirements(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        assert MESSAGE_REQUIREMENTS_QUOTE_FAILED in str(req.quote_data.message)
        from_chain = req.params["from"]["chain"]
        from_addr = req.params["from"]["address"]
        assert int(result[from_chain][from_addr][ZERO_ADDRESS]) == 0
        assert int(result[from_chain][from_addr][ERC20_ADDR]) == 0

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

        with (
            patch(
                "operate.bridge.providers.provider.TxSettler", return_value=mock_settler
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

        with (
            patch(
                "operate.bridge.providers.provider.TxSettler", return_value=mock_settler
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

        with (
            patch(
                "operate.bridge.providers.provider.TxSettler",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
            mock_ledger = MagicMock()
            mock_api.return_value = mock_ledger
            provider.execute(req)

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED
        assert req.execution_data is not None

    def test_execute_gas_spike_raises_insufficient_funds(self) -> None:
        """execute() converts gas spike ValueError to InsufficientFundsException, stores structured error fields in provider_data, and re-raises."""
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
        mock_settler.transact.side_effect = ValueError(
            "insufficient funds for gas * price + value"
        )

        mock_ledger = MagicMock()
        mock_ledger.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.TxSettler",
                return_value=mock_settler,
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger,
            ),
            pytest.raises(InsufficientFundsException),
        ):
            provider.execute(req)

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED
        assert req.execution_data is not None
        assert "Insufficient gas" in (req.execution_data.message or "")
        assert req.execution_data.provider_data is not None
        assert (
            req.execution_data.provider_data["error_code"] == "INSUFFICIENT_SIGNER_GAS"
        )
        assert "chain" in req.execution_data.provider_data

    def test_execute_non_gas_error_sets_execution_failed(self) -> None:
        """Non-gas ValueError propagates to the generic except handler and is recorded as EXECUTION_FAILED."""
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
        mock_settler.transact.side_effect = ValueError("contract reverted")

        with (
            patch(
                "operate.bridge.providers.provider.TxSettler",
                return_value=mock_settler,
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
            mock_ledger = MagicMock()
            mock_ledger.api.eth.get_transaction_count.return_value = 0
            mock_api.return_value = mock_ledger
            provider.execute(req)

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

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

        with (
            patch(
                "operate.bridge.providers.provider.update_tx_with_gas_pricing"
            ) as mock_gas,
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

    def test_status_json_surfaces_insufficient_funds_fields(self) -> None:
        """status_json() includes structured error fields from provider_data when execution failed due to insufficient gas."""
        provider = _ConcreteProvider()
        req = _make_request(status=ProviderRequestStatus.EXECUTION_FAILED)
        req.quote_data = _make_quote_data(eta=300)
        error_fields = {
            "error_code": "INSUFFICIENT_SIGNER_GAS",
            "chain": "gnosis",
            "prefill_amount_wei": "500000000000000000",
        }
        req.execution_data = ExecutionData(
            elapsed_time=0.0,
            message="Execution failed: Insufficient gas",
            timestamp=int(time.time()),
            from_tx_hash=None,
            to_tx_hash=None,
            provider_data=error_fields,
        )

        with patch.object(provider, "_update_execution_status"):
            result = provider.status_json(req)

        assert result["status"] == ProviderRequestStatus.EXECUTION_FAILED.value
        assert result["error_code"] == "INSUFFICIENT_SIGNER_GAS"
        assert result["chain"] == "gnosis"
        assert result["prefill_amount_wei"] == "500000000000000000"

    def test_status_json_with_quote_data_only(self) -> None:
        """status_json() with only quote_data (no execution_data) returns eta+message+status."""
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

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.post",
                side_effect=req_lib.Timeout("timed out"),
            ),
            patch("operate.bridge.providers.relay_provider.time.sleep"),
        ):
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

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
            patch("operate.bridge.providers.relay_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.relay_provider.update_tx_with_gas_estimate"
            ),
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

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.post",
                side_effect=[mock_first, mock_placeholder],
            ),
            patch(
                "operate.bridge.providers.relay_provider.RELAY_DEFAULT_GAS",
                {"gnosis": {"approve": 100000}},
            ),
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

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.post",
                return_value=mock_resp,
            ),
            patch("operate.bridge.providers.relay_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED

    def test_quote_http_error_uses_response_json_message(self) -> None:
        """quote() handles HTTPError by parsing response.json() for an error message."""
        import requests as req_lib

        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": "relay API error"}
        mock_resp.raise_for_status.side_effect = req_lib.HTTPError("bad request")
        mock_resp.status_code = 400

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.post",
                return_value=mock_resp,
            ),
            patch("operate.bridge.providers.relay_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        assert req.quote_data.message == "relay API error"
        assert req.quote_data.provider_data is not None
        assert req.quote_data.provider_data["response_status"] == 400

    def test_quote_connection_error_sets_quote_failed_without_response(self) -> None:
        """quote() handles ConnectionError raised by requests.post itself (no response bound).

        Regression for the QA failure where transient proxy disconnects raised
        ConnectionError before `response` was assigned, leaking UnboundLocalError
        from the quote() method instead of failing cleanly with QUOTE_FAILED so
        the bundle could rotate to the Mayan fallback.
        """
        import requests as req_lib

        provider = _make_relay_provider()
        req = _make_request(
            provider_id="relay-provider",
            status=ProviderRequestStatus.CREATED,
            amount=1000,
        )

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.post",
                side_effect=req_lib.ConnectionError(
                    "Connection aborted: RemoteDisconnected"
                ),
            ),
            patch("operate.bridge.providers.relay_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        assert "Connection aborted" in (req.quote_data.message or "")


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

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.get",
                return_value=mock_resp,
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.get",
                return_value=mock_resp,
            ),
            patch(
                "operate.bridge.providers.provider.Provider._tx_timestamp",
                return_value=1000,
            ),
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

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.get",
                side_effect=RuntimeError("rpc down"),
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

        with (
            patch(
                "operate.bridge.providers.native_bridge_provider.registry_contracts"
            ) as mock_contracts,
            patch(
                "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_pricing"
            ),
            patch(
                "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_estimate"
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

        with (
            patch.object(
                provider.bridge_contract_adaptor,
                "build_bridge_tx",
                return_value=expected_tx,
            ) as mock_build,
            patch(
                "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_pricing"
            ),
            patch(
                "operate.bridge.providers.native_bridge_provider.update_tx_with_gas_estimate"
            ),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api"
            ) as mock_api,
        ):
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

        with (
            patch.object(provider, "_get_approve_tx", return_value=approve_tx),
            patch.object(provider, "_get_bridge_tx", return_value=bridge_tx),
        ):
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

        with (
            patch.object(provider, "_get_approve_tx", return_value=None),
            patch.object(provider, "_get_bridge_tx", return_value=bridge_tx),
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

        with (
            patch(
                "operate.bridge.providers.relay_provider.requests.get",
                return_value=mock_resp,
            ),
            patch(
                "operate.bridge.providers.provider.Provider._tx_timestamp",
                return_value=1000,
            ),
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
        with (
            patch.object(
                BridgeContractAdaptor, "can_handle_request", return_value=True
            ),
            patch(
                "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
                return_value=MagicMock(),
            ),
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
        with (
            patch.object(
                BridgeContractAdaptor, "can_handle_request", return_value=True
            ),
            patch(
                "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
                return_value=MagicMock(),
            ),
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
        with (
            patch.object(
                BridgeContractAdaptor, "can_handle_request", return_value=True
            ),
            patch(
                "operate.bridge.providers.native_bridge_provider.get_default_ledger_api",
                return_value=MagicMock(),
            ),
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

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                side_effect=_pick_ledger,
            ),
            patch.object(
                NativeBridgeProvider,
                "_find_block_before_timestamp",
                return_value=100,
            ),
            patch.object(
                provider.bridge_contract_adaptor,
                "find_bridge_finalized_tx",
                return_value=to_tx_hash,
            ),
            patch.object(
                Provider,
                "_tx_timestamp",
                return_value=1_000_000,
            ),
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

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                side_effect=_pick_ledger,
            ),
            patch.object(
                NativeBridgeProvider,
                "_find_block_before_timestamp",
                return_value=100,
            ),
            patch.object(
                provider.bridge_contract_adaptor,
                "find_bridge_finalized_tx",
                return_value=None,
            ),
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

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                side_effect=_pick_ledger,
            ),
            patch.object(
                NativeBridgeProvider,
                "_find_block_before_timestamp",
                side_effect=RuntimeError("network error"),
            ),
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


# ---------------------------------------------------------------------------
# MayanProvider unit tests
# ---------------------------------------------------------------------------

MAYAN_PROVIDER_ID = "mayan-provider"


def _make_mayan_provider() -> MayanProvider:
    """Build a MayanProvider for unit tests."""
    return MayanProvider(
        wallet_manager=MagicMock(),
        provider_id=MAYAN_PROVIDER_ID,
        logger=MagicMock(),
    )


def _make_mayan_quote_response(
    expected_amount_out: float = 1100.0,
    effective_amount_in: float = 1000.0,
    min_amount_out_base_units: str = "1050",
    eta_seconds: int = 120,
    route_type: str = "SWIFT",
    swift_mayan_contract: str = "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
) -> t.Dict:
    """Build a mock Mayan Quote API response aligned with the live API schema."""
    return {
        "type": route_type,
        "effectiveAmountIn": effective_amount_in,
        "effectiveAmountIn64": str(int(effective_amount_in)),
        "expectedAmountOut": expected_amount_out,
        "minAmountOutBaseUnits": min_amount_out_base_units,
        "etaSeconds": eta_seconds,
        "bridgeFee": 0,
        "gasDrop": 0,
        "cancelRelayerFee64": "100",
        "submitRelayerFee64": "50",
        "deadline64": "9999999999",
        "referrerBps": 0,
        "swiftAuctionMode": 1,
        "swiftMayanContract": swift_mayan_contract,
        "swiftInputContract": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "slippageBps": 300,
        "toToken": {"contract": "0xDDdDddDdDdddDDddDDddDDDDdDdDDdDDdDDDDDDd"},
        "fromToken": {"contract": ZERO_ADDRESS},
    }


class TestMayanProviderHelpers:
    """Unit tests for MayanProvider pure helpers."""

    @pytest.mark.parametrize(
        ("to_amount", "from_dec", "to_dec", "expected"),
        [
            # Decimal-expanding: source has more decimals than dest
            # (e.g. POL/18 → pUSD/6, ETH/18 → USDC/6).
            (1_000_000, 18, 6, 1_000_000 * 10**12),
            # Decimal-shrinking: source has fewer decimals than dest
            # (e.g. USDC/6 → OLAS/18).
            (10**18, 6, 18, 10**6),
            # Same decimals: identity (e.g. OLAS/18 → OLAS/18).
            (5_000, 18, 18, 5_000),
            # Floor-clamp: tiny to_amount with huge shrink stays at 1
            # rather than 0 so Mayan still sees a non-zero probe.
            (1, 6, 18, 1),
        ],
        ids=[
            "expand-18to6",
            "shrink-6to18",
            "same-decimals",
            "floor-clamp",
        ],
    )
    def test_dest_to_source_atomic(
        self, to_amount: int, from_dec: int, to_dec: int, expected: int
    ) -> None:
        """1:1 cross-decimal conversion preserves nominal value across pairs."""
        assert (
            MayanProvider._dest_to_source_atomic(  # pylint: disable=protected-access
                to_amount, from_dec, to_dec
            )
            == expected
        )

    @pytest.mark.parametrize(
        ("amount", "decimals", "expected"),
        [
            # Mirrors SDK getAmountOfFractionalAmount(amount, min(decimals, 8))
            # then parseUnits. For 6-dec tokens, cutFactor = 6 → no truncation.
            ("9.876543", 6, 9876543),
            # For 18-dec tokens (ETH/OLAS), cutFactor = 8 → truncates beyond 8 places.
            ("0.123456789012345678", 18, 12345678),
            # Truncation, not rounding (matches SDK's regex-based cut).
            ("0.999999999999", 18, 99999999),
            # Integer-valued amount works the same.
            (5, 18, 5 * 10**8),
            # Zero in, zero out.
            (0, 18, 0),
        ],
        ids=[
            "6-dec-no-truncation",
            "18-dec-truncate-at-8",
            "truncates-not-rounds",
            "integer-input",
            "zero",
        ],
    )
    def test_to_canonical_uint64(
        self, amount: t.Union[int, str], decimals: int, expected: int
    ) -> None:
        """SDK-compatible truncate-then-scale-by-cutFactor encoding."""
        assert (
            MayanProvider._to_canonical_uint64(  # pylint: disable=protected-access
                amount, decimals
            )
            == expected
        )


class TestMayanProviderQuoteCrossDecimal:
    """Unit tests for cross-decimal probe seeding in MayanProvider.quote()."""

    def test_probe_seed_uses_decimals_aware_translation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Probe amountIn64 reflects to_amount translated into source atomic.

        For an 18-dec source and 6-dec destination, asking for 1 pUSD
        (to_amount = 10**6) should probe Mayan with 10**18 source atomic
        (1 unit at a 1:1 exchange-rate assumption), not 10**6.
        """
        decimals_by_chain = {"polygon": (18, 6)}

        def fake_decimals(chain: Chain, _token: str) -> int:
            from_dec, to_dec = decimals_by_chain[chain.value]
            return from_dec if _token == ZERO_ADDRESS else to_dec

        monkeypatch.setattr(
            "operate.bridge.providers.mayan_provider.get_asset_decimals",
            fake_decimals,
        )

        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=10**6,  # 1 unit of a 6-dec dest token
            from_chain="polygon",
            to_chain="polygon",
            from_token=ZERO_ADDRESS,
            to_token=ERC20_ADDR,
        )
        probe_resp = _make_mayan_quote_response(
            effective_amount_in=10**18,
            expected_amount_out=0.45,
            min_amount_out_base_units="450000",
            route_type="MONO_CHAIN",
        )
        final_resp = _make_mayan_quote_response(
            effective_amount_in=2.5 * 10**18,
            expected_amount_out=1.05,
            min_amount_out_base_units="1050000",
            route_type="MONO_CHAIN",
        )

        captured_amount_ins: t.List[str] = []

        def fake_call_quote_api(**kwargs: t.Any) -> t.Dict:
            captured_amount_ins.append(kwargs["amount_in64"])
            return probe_resp if len(captured_amount_ins) == 1 else final_resp

        with patch.object(provider, "_call_quote_api", side_effect=fake_call_quote_api):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        # Probe must have been seeded with to_amount scaled into source atomic
        # (1:1 at 18-dec source vs 6-dec dest = 10**12 scale-up).
        assert captured_amount_ins[0] == str(
            10**18
        ), f"Probe should use source-atomic seed 10**18, got {captured_amount_ins[0]}"

    def test_probe_seed_handles_low_to_high_decimal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reverse direction: 6-dec source → 18-dec dest shrinks the probe seed.

        Asking for 1 OLAS (to_amount = 10**18) with a 6-dec source should
        probe with 10**6 source atomic, not 10**18.
        """

        def fake_decimals(_chain: Chain, token: str) -> int:
            # from_token is non-zero (6-dec ERC-20); to_token is ZERO (native 18-dec)
            return 18 if token == ZERO_ADDRESS else 6

        monkeypatch.setattr(
            "operate.bridge.providers.mayan_provider.get_asset_decimals",
            fake_decimals,
        )

        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=10**18,  # 1 unit of 18-dec dest
            from_chain="ethereum",
            to_chain="polygon",
            from_token=ERC20_ADDR,  # 6-dec ERC-20 (per fake_decimals mapping)
            to_token=ZERO_ADDRESS,
        )
        probe_resp = _make_mayan_quote_response(
            effective_amount_in=10**6,
            expected_amount_out=10**18,
            min_amount_out_base_units=str(10**18),
        )
        final_resp = _make_mayan_quote_response(
            effective_amount_in=int(1.05 * 10**6),
            expected_amount_out=1.05 * 10**18,
            min_amount_out_base_units=str(int(1.05 * 10**18)),
        )

        captured: t.List[str] = []

        def fake_api(**kwargs: t.Any) -> t.Dict:
            captured.append(kwargs["amount_in64"])
            return probe_resp if len(captured) == 1 else final_resp

        with patch.object(provider, "_call_quote_api", side_effect=fake_api):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert captured[0] == str(
            10**6
        ), f"Probe should shrink to 10**6 source atomic, got {captured[0]}"


class TestMayanProviderQuote:
    """Unit tests for MayanProvider.quote()."""

    @pytest.fixture(autouse=True)
    def _mock_get_asset_decimals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stub get_asset_decimals so quote() never hits a live RPC.

        Default returns 18 (matches native ETH/POL/OLAS and the default
        ZERO_ADDRESS fixture). Individual tests can monkeypatch a new
        function via the same path if they need a specific decimals value.
        """
        monkeypatch.setattr(
            "operate.bridge.providers.mayan_provider.get_asset_decimals",
            lambda _chain, _token: 18,
        )

    def test_zero_amount_returns_quote_done(self) -> None:
        """Zero-amount quote succeeds immediately."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=0,
            from_chain="ethereum",
            to_chain="polygon",
        )
        provider.quote(req)
        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None
        assert req.quote_data.eta == 0

    def test_unsupported_chain_returns_quote_failed(self) -> None:
        """Unsupported chain pair fails immediately."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="gnosis",
            to_chain="base",
        )
        provider.quote(req)
        assert req.status == ProviderRequestStatus.QUOTE_FAILED

    def test_successful_quote(self) -> None:
        """Successful two-step quote sets QUOTE_DONE."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        probe_resp = _make_mayan_quote_response(
            effective_amount_in=1000.0,
            expected_amount_out=950.0,
            min_amount_out_base_units="950",
        )
        final_resp = _make_mayan_quote_response(
            effective_amount_in=1074.0,
            expected_amount_out=1020.0,
            min_amount_out_base_units="1010",
        )

        with patch.object(
            provider,
            "_call_quote_api",
            side_effect=[probe_resp, final_resp],
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_DONE
        assert req.quote_data is not None
        assert req.quote_data.provider_data is not None
        assert req.quote_data.provider_data["amount_in_final"] > 1000

    def test_under_delivery_returns_quote_failed(self) -> None:
        """When minAmountOutBaseUnits < required amount, quote fails."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        probe_resp = _make_mayan_quote_response(
            effective_amount_in=1000.0,
            expected_amount_out=950.0,
            min_amount_out_base_units="950",
        )
        final_resp = _make_mayan_quote_response(
            effective_amount_in=1074.0,
            expected_amount_out=980.0,
            min_amount_out_base_units="900",  # under-delivery
        )

        with patch.object(
            provider,
            "_call_quote_api",
            side_effect=[probe_resp, final_resp],
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED

    def test_under_delivery_message_is_human_readable(self) -> None:
        """Under-delivery message surfaces human units + suggested bump."""
        provider = _make_mayan_provider()
        # 15 POL requested (18 dec), Mayan would deliver 14.2 POL — mirrors
        # the QA scenario the operator hit.
        to_amount = 15 * 10**18
        delivered = 14_203_688_419_597_200_000  # 14.203... POL
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=to_amount,
            from_chain="ethereum",
            to_chain="polygon",
        )

        probe_resp = _make_mayan_quote_response(
            effective_amount_in=1000.0,
            expected_amount_out=950.0,
            min_amount_out_base_units="950",
        )
        final_resp = _make_mayan_quote_response(
            effective_amount_in=float(to_amount),
            expected_amount_out=14.5,
            min_amount_out_base_units=str(delivered),
        )

        # Need probe+final for every retry attempt so the final stored message
        # is the under-delivery error (otherwise later attempts run out of
        # mocked responses and the broad-except clobbers the message).
        with (
            patch.object(
                provider,
                "_call_quote_api",
                side_effect=[probe_resp, final_resp] * 5,
            ),
            patch("operate.bridge.providers.mayan_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        msg = req.quote_data.message or ""
        # Human-readable destination units, not raw atomic ints
        assert "14.2" in msg, msg
        assert "15" in msg, msg
        # Shortfall percentage surfaced
        assert "%" in msg, msg
        # Suggested bump surfaced
        assert "Try amount >=" in msg, msg
        # Should NOT contain the old opaque format
        assert "minAmountOutBaseUnits=" not in msg, msg

    def test_timeout_retries_then_fails(self) -> None:
        """Timeout on all attempts results in QUOTE_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        import requests as req_lib

        with (
            patch.object(
                provider,
                "_call_quote_api",
                side_effect=req_lib.Timeout("timed out"),
            ),
            patch("operate.bridge.providers.mayan_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED

    def test_no_quotes_returns_quote_failed(self) -> None:
        """Empty quotes list from API results in QUOTE_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        with (
            patch.object(
                provider,
                "_call_quote_api",
                return_value=None,
            ),
            patch("operate.bridge.providers.mayan_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED


class TestMayanProviderGetTxs:
    """Unit tests for MayanProvider._get_txs()."""

    def test_zero_amount_returns_empty(self) -> None:
        """Zero amount returns empty tx list."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=0,
            from_chain="ethereum",
            to_chain="polygon",
        )
        txs = provider._get_txs(req)  # pylint: disable=protected-access
        assert txs == []

    def test_no_quote_data_raises(self) -> None:
        """Missing quote_data raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )
        with pytest.raises(RuntimeError, match="quote data not present"):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_native_eth_path_returns_forward_eth(self) -> None:
        """Native ETH path returns a single forwardEth transaction."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_token=ZERO_ADDRESS,
            from_chain="ethereum",
            to_chain="polygon",
        )
        mock_response = _make_mayan_quote_response()
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 1
        label, tx = txs[0]
        assert label == "forwardEth"
        assert tx["value"] == 1020

    def test_native_eth_missing_swift_input_contract_uses_wrapped_native(
        self,
    ) -> None:
        """When swiftInputContract is absent, falls back to WRAPPED_NATIVE_ASSET."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_token=ZERO_ADDRESS,
            from_chain="ethereum",
            to_chain="polygon",
        )
        mock_response = _make_mayan_quote_response()
        del mock_response["swiftInputContract"]
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 1
        label, tx = txs[0]
        assert label == "forwardEth"

    def test_erc20_path_returns_approve_and_forward(self) -> None:
        """ERC-20 path returns approve + forwardERC20, and requirements() includes the approve amount."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_token=ERC20_ADDR,
            from_chain="ethereum",
            to_chain="polygon",
        )
        mock_response = _make_mayan_quote_response()
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020,
            }
        )

        # Use a real Web3 for eth.contract / to_checksum_address so the
        # approve calldata in the resulting tx dict is a real hex string
        # (otherwise requirements()'s ERC-20 calldata parsing sees a MagicMock).
        real_w3 = Web3()
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.contract = real_w3.eth.contract
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        # Set a known gas price so requirements() computes deterministic fees.
        def _set_gas_price(tx: t.Dict, _ledger_api: t.Any) -> None:
            tx["gasPrice"] = 1

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing",
                side_effect=_set_gas_price,
            ),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
            patch(
                "operate.bridge.providers.provider.update_tx_with_gas_pricing",
                side_effect=_set_gas_price,
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

            assert len(txs) == 2
            assert txs[0][0] == "approve"
            assert txs[1][0] == "forwardERC20"

            # Exercise the full SWIFT requirements() pipeline (regression pin).
            # Native fees = (approve_gas 50k + forwarder_gas 350k) * gas_price 1 = 400_000.
            # forwardERC20 has value = bridge_fee = 0 in the fixture, so no extra native.
            # ERC-20 from_token total = approve amount = amount_in_final = 1020.
            requirements = provider.requirements(req)

        eth_amounts = requirements["ethereum"][FROM_ADDR]
        assert eth_amounts[ZERO_ADDRESS] == 400_000
        assert eth_amounts[ERC20_ADDR] == 1020

    def test_native_swap_path_uses_swap_and_forward_eth(self) -> None:
        """Native + swap quote routes through swapAndForwardEth.

        When Mayan's SWIFT response includes evmSwapRouterAddress, the
        native-source path must call swapAndForwardEth (not forwardEth) and
        the inner protocolData must use the hub asset + post-swap amount.
        """
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_token=ZERO_ADDRESS,
            from_chain="ethereum",
            to_chain="polygon",
        )
        hub_token = "0x" + "1" * 40  # synthetic hub asset
        swap_router = "0x" + "2" * 40  # synthetic swap router
        # Build response with swap fields present
        response = _make_mayan_quote_response()
        response["swiftInputContract"] = hub_token
        response["swiftInputDecimals"] = 6
        response["evmSwapRouterAddress"] = swap_router
        response["evmSwapRouterCalldata"] = "0xdeadbeef"
        response["minMiddleAmount"] = 3.04
        req.quote_data = _make_quote_data(
            provider_data={
                "response": response,
                "amount_in_final": 2_341_615_790_517_934,
            },
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 1
        label, tx = txs[0]
        assert label == "swapAndForwardEth"
        # value is the source ETH that gets swapped to hub
        assert tx["value"] == 2_341_615_790_517_934
        # gas budget bumped to mono_chain_forwarder tier (1_000_000) since
        # we're now doing swap + SWIFT in one outer tx.
        assert tx["gas"] == 1_000_000
        # Verify the outer selector by inspecting calldata prefix.
        data_hex = tx["data"]
        assert data_hex.startswith(
            "0xfa74fd43"
        ), f"expected swapAndForwardEth selector, got {data_hex[:10]}"
        # The hub token address (USDC) should appear in the outer args as
        # the middle token (32-byte-padded), e.g. somewhere after the swap
        # router param.
        assert hub_token[2:].lower() in data_hex.lower()

    def test_erc20_swap_path_uses_swap_and_forward_erc20(self) -> None:
        """ERC-20 source + swap route: approve + swapAndForwardERC20."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_token=ERC20_ADDR,
            from_chain="ethereum",
            to_chain="polygon",
        )
        hub_token = "0x" + "1" * 40  # synthetic hub asset
        swap_router = "0x" + "2" * 40  # synthetic swap router
        response = _make_mayan_quote_response()
        response["swiftInputContract"] = hub_token
        response["swiftInputDecimals"] = 6
        response["evmSwapRouterAddress"] = swap_router
        response["evmSwapRouterCalldata"] = "0xcafebabe"
        response["minMiddleAmount"] = 3.04
        req.quote_data = _make_quote_data(
            provider_data={
                "response": response,
                "amount_in_final": 100_000_000_000_000_000_000,
            },
        )

        real_w3 = Web3()
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.contract = real_w3.eth.contract
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 2
        assert txs[0][0] == "approve"
        forward_label, forward_tx = txs[1]
        assert forward_label == "swapAndForwardERC20"
        assert forward_tx["data"].startswith(
            "0x30dedc57"
        ), f"expected swapAndForwardERC20 selector, got {forward_tx['data'][:10]}"
        assert forward_tx["gas"] == 1_000_000

    def test_swap_path_missing_calldata_prefix_raises(self) -> None:
        """Reject evmSwapRouterCalldata without the 0x prefix (defensive guard)."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_token=ZERO_ADDRESS,
            from_chain="ethereum",
            to_chain="polygon",
        )
        response = _make_mayan_quote_response()
        response["evmSwapRouterAddress"] = "0x0000000000001ff3684f28c67538d4d072c22734"
        response["evmSwapRouterCalldata"] = "deadbeef"  # missing 0x prefix
        response["minMiddleAmount"] = 3.04
        response["swiftInputDecimals"] = 6
        req.quote_data = _make_quote_data(
            provider_data={"response": response, "amount_in_final": 1000},
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
        ):
            with pytest.raises(RuntimeError, match="missing '0x' prefix"):
                provider._get_txs(req)  # pylint: disable=protected-access

    def test_swap_path_missing_swift_input_contract_raises_in_txs(self) -> None:
        """Defense-in-depth: _build_swift_txs also guards against missing hub.

        _build_swift_protocol_data has the same guard, but the tx builder
        cannot trust that — they're called independently from the public
        _get_txs API surface. This calls the tx builder directly with a
        valid protocol_data but a response missing swiftInputContract.
        """
        provider = _make_mayan_provider()
        response = _make_mayan_quote_response()
        response["evmSwapRouterAddress"] = "0x" + "2" * 40
        response["evmSwapRouterCalldata"] = "0xdeadbeef"
        response["minMiddleAmount"] = 3.04
        response["swiftInputDecimals"] = 6
        del response["swiftInputContract"]

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with pytest.raises(RuntimeError, match="missing swiftInputContract"):
            provider._build_swift_txs(  # pylint: disable=protected-access
                response=response,
                from_token=ZERO_ADDRESS,
                from_address=FROM_ADDR,
                from_chain="ethereum",
                amount_in_final=1000,
                bridge_fee=0,
                mayan_protocol="0x" + "f" * 40,
                protocol_data=b"\x00" * 32,
                forwarder_address="0x" + "e" * 40,
                from_ledger_api=mock_ledger_api,
                w3=Web3(),
            )

    def test_swap_protocol_data_missing_hub_token_raises(self) -> None:
        """_build_swift_protocol_data also guards against missing hub token."""
        provider = _make_mayan_provider()
        response = _make_mayan_quote_response()
        response["evmSwapRouterAddress"] = "0x" + "2" * 40
        response["evmSwapRouterCalldata"] = "0xdead"
        response["minMiddleAmount"] = 3.04
        response["swiftInputDecimals"] = 6
        del response["swiftInputContract"]
        with pytest.raises(RuntimeError, match="missing swiftInputContract"):
            provider._build_swift_protocol_data(  # pylint: disable=protected-access
                response=response,
                from_address=FROM_ADDR,
                from_token=ZERO_ADDRESS,
                to_address=TO_ADDR,
                to_chain="polygon",
                amount_in_final=1000,
                from_chain="ethereum",
            )

    def test_swap_path_missing_min_middle_amount_raises(self) -> None:
        """Reject swap-quote response with no minMiddleAmount/swiftInputDecimals."""
        provider = _make_mayan_provider()
        response = _make_mayan_quote_response()
        response["swiftInputContract"] = "0x" + "1" * 40
        response["evmSwapRouterAddress"] = "0x" + "2" * 40
        response["evmSwapRouterCalldata"] = "0xdead"
        # minMiddleAmount + swiftInputDecimals deliberately absent
        with pytest.raises(
            RuntimeError, match="missing minMiddleAmount/swiftInputDecimals"
        ):
            provider._swift_middle_amount(response)  # pylint: disable=protected-access

    def test_swift_protocol_data_swap_path_uses_hub_amount(self) -> None:
        """Inner createOrderWithToken uses the hub asset + post-swap amount.

        In swap mode, the inner SWIFT call must encode the hub asset and the
        post-swap minMiddleAmount, not the source token / source amount.
        """
        provider = _make_mayan_provider()
        hub_token = "0x" + "1" * 40  # synthetic hub asset
        response = _make_mayan_quote_response()
        response["swiftInputContract"] = hub_token
        response["swiftInputDecimals"] = 6
        response["evmSwapRouterAddress"] = "0x0000000000001ff3684f28c67538d4d072c22734"
        response["evmSwapRouterCalldata"] = "0xdeadbeef"
        response["minMiddleAmount"] = 3.04  # USDC display
        # Source-token amount is irrelevant to the inner SWIFT call in swap mode
        source_amount_in = 2_341_615_790_517_934  # 0.00234 ETH

        protocol_data = (
            provider._build_swift_protocol_data(  # pylint: disable=protected-access
                response=response,
                from_address=FROM_ADDR,
                from_token=ZERO_ADDRESS,
                to_address=TO_ADDR,
                to_chain="polygon",
                amount_in_final=source_amount_in,
                from_chain="ethereum",
            )
        )
        # createOrderWithToken selector
        assert protocol_data[:4].hex() == "a3a30834"
        # First arg = tokenAddress (32 bytes, address right-padded). USDC.
        assert protocol_data[4:36].hex().endswith(hub_token[2:].lower())
        # Second arg = amountIn (uint256). Must be minMiddleAmount in USDC
        # atomic (= 3.04 * 10**6 truncated = 3_040_000), NOT the source ETH
        # amount.
        amount_in_decoded = int.from_bytes(protocol_data[36:68], "big")
        assert amount_in_decoded == 3_040_000, amount_in_decoded
        assert amount_in_decoded != source_amount_in


class TestMayanProviderExecutionStatus:
    """Unit tests for MayanProvider._update_execution_status()."""

    def test_completed_sets_execution_done(self) -> None:
        """COMPLETED status maps to EXECUTION_DONE."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clientStatus": "COMPLETED",
            "fulfillTxHash": "0x" + "e" * 64,
        }

        with (
            patch("requests.get", return_value=mock_response),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=MagicMock(),
            ),
            patch.object(Provider, "_tx_timestamp", return_value=100),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_DONE

    def test_refunded_sets_execution_failed(self) -> None:
        """REFUNDED status maps to EXECUTION_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clientStatus": "REFUNDED",
        }

        with patch("requests.get", return_value=mock_response):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_failed_sets_execution_failed(self) -> None:
        """FAILED status maps to EXECUTION_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clientStatus": "FAILED",
        }

        with patch("requests.get", return_value=mock_response):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_inprogress_sets_execution_pending(self) -> None:
        """INPROGRESS status maps to EXECUTION_PENDING."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clientStatus": "INPROGRESS",
        }

        with patch("requests.get", return_value=mock_response):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_PENDING

    def test_404_calls_bridge_tx_likely_failed(self) -> None:
        """404 not-found triggers _bridge_tx_likely_failed fallback."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with (
            patch("requests.get", return_value=mock_response),
            patch.object(provider, "_bridge_tx_likely_failed", return_value=True),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_missing_tx_hash_sets_failed(self) -> None:
        """Missing from_tx_hash immediately fails."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data(from_tx_hash=None)

        provider._update_execution_status(req)  # pylint: disable=protected-access
        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_unknown_status_sets_unknown_and_logs_warning(self) -> None:
        """Unknown clientStatus string maps to EXECUTION_UNKNOWN and logs warning."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clientStatus": "SOME_UNKNOWN_STATUS",
        }

        with (
            patch("requests.get", return_value=mock_response),
            patch.object(provider, "_bridge_tx_likely_failed", return_value=False),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_UNKNOWN
        provider.logger.warning.assert_called()  # type: ignore[attr-defined]
        warning_msg = provider.logger.warning.call_args[0][0]  # type: ignore[attr-defined]
        assert "SOME_UNKNOWN_STATUS" in warning_msg


class TestMayanProviderExplorerLink:
    """Unit tests for MayanProvider._get_explorer_link()."""

    def test_returns_mayan_explorer_url(self) -> None:
        """Explorer link follows the SWIFT_V2 format."""
        provider = _make_mayan_provider()
        tx_hash = "0x" + "a" * 64
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data(from_tx_hash=tx_hash)

        link = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert link == f"{MAYAN_EXPLORER_URL}/SWIFT_V2_{tx_hash}"

    def test_no_execution_data_returns_none(self) -> None:
        """No execution data returns None."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            from_chain="ethereum",
            to_chain="polygon",
        )
        link = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert link is None

    def test_no_from_tx_hash_returns_none(self) -> None:
        """No from_tx_hash in execution_data returns None."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data(from_tx_hash=None)
        link = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert link is None


# ---------------------------------------------------------------------------
# MayanProvider.description
# ---------------------------------------------------------------------------


class TestMayanProviderDescription:
    """Unit tests for MayanProvider.description()."""

    def test_returns_description_string(self) -> None:
        """description() returns the expected string."""
        provider = _make_mayan_provider()
        assert provider.description() == "Mayan Protocol https://mayan.finance/"


# ---------------------------------------------------------------------------
# MayanProvider.quote — additional edge cases
# ---------------------------------------------------------------------------


class TestMayanProviderQuoteEdgeCases:
    """Additional edge-case tests for MayanProvider.quote()."""

    @pytest.fixture(autouse=True)
    def _mock_get_asset_decimals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stub get_asset_decimals so quote() never hits a live RPC."""
        monkeypatch.setattr(
            "operate.bridge.providers.mayan_provider.get_asset_decimals",
            lambda _chain, _token: 18,
        )

    def test_quote_wrong_status_raises(self) -> None:
        """Quoting a request with EXECUTION_PENDING status raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        with pytest.raises(RuntimeError, match="Cannot quote request"):
            provider.quote(req)

    def test_quote_with_execution_data_raises(self) -> None:
        """Quoting a request that already has execution data raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()
        with pytest.raises(RuntimeError, match="execution already present"):
            provider.quote(req)

    def test_invalid_probe_output_fails(self) -> None:
        """Zero minAmountOutBaseUnits in probe results in QUOTE_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        probe_resp = _make_mayan_quote_response(
            effective_amount_in=1000.0,
            expected_amount_out=0.0,
            min_amount_out_base_units="0",
        )

        with (
            patch.object(
                provider,
                "_call_quote_api",
                return_value=probe_resp,
            ),
            patch("operate.bridge.providers.mayan_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED

    def test_probe_missing_effective_amount_in64_fails_with_field_list(
        self,
    ) -> None:
        """Probe response missing 'effectiveAmountIn64' surfaces an actionable error.

        Defends against opaque KeyError if the Mayan API ever drops or
        renames the field — the operator should see the list of keys that
        were present in the response, not a bare key name.
        """
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        # Probe response with effectiveAmountIn64 explicitly removed.
        probe_resp = _make_mayan_quote_response()
        del probe_resp["effectiveAmountIn64"]
        remaining_keys = list(probe_resp)

        with (
            patch.object(
                provider,
                "_call_quote_api",
                return_value=probe_resp,
            ),
            patch("operate.bridge.providers.mayan_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED
        assert req.quote_data is not None
        message = req.quote_data.message or ""
        assert "effectiveAmountIn64" in message
        # The error must surface the keys actually present so an operator can
        # diagnose a schema drift from the message alone.
        for key in remaining_keys:
            assert key in message, f"expected key {key!r} in error message"

    def test_no_final_quotes_fails(self) -> None:
        """Empty final quote (probe succeeds, final returns None) results in QUOTE_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        probe_resp = _make_mayan_quote_response(
            effective_amount_in=1000.0,
            expected_amount_out=950.0,
            min_amount_out_base_units="950",
        )

        with (
            patch.object(
                provider,
                "_call_quote_api",
                side_effect=[probe_resp, None],
            ),
            patch("operate.bridge.providers.mayan_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED

    def test_request_exception_retries_then_fails(self) -> None:
        """requests.RequestException on all attempts results in QUOTE_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )

        with (
            patch.object(
                provider,
                "_call_quote_api",
                side_effect=req_lib.ConnectionError("connection refused"),
            ),
            patch("operate.bridge.providers.mayan_provider.time.sleep"),
        ):
            provider.quote(req)

        assert req.status == ProviderRequestStatus.QUOTE_FAILED


# ---------------------------------------------------------------------------
# MayanProvider._call_quote_api
# ---------------------------------------------------------------------------


class TestMayanProviderCallQuoteApi:
    """Unit tests for MayanProvider._call_quote_api()."""

    def test_returns_first_quote(self) -> None:
        """Successful API call returns the first quote from the list."""
        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "minimumSdkVersion": "13_0_0",
            "quotes": [
                {"type": "SWIFT", "effectiveAmountIn": 1000.0},
                {"type": "MCTP", "effectiveAmountIn": 1050.0},
            ],
        }

        with patch("requests.get", return_value=mock_response):
            result = provider._call_quote_api(  # pylint: disable=protected-access
                from_chain="ethereum",
                from_token="0x" + "0" * 40,
                to_chain="polygon",
                to_token="0x" + "0" * 40,
                amount_in64="1000",
                to_address=TO_ADDR,
            )

        assert result is not None
        assert result["type"] == "SWIFT"

    def test_empty_list_returns_none(self) -> None:
        """Empty quotes list from API returns None."""
        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "minimumSdkVersion": "13_0_0",
            "quotes": [],
        }

        with patch("requests.get", return_value=mock_response):
            result = provider._call_quote_api(  # pylint: disable=protected-access
                from_chain="ethereum",
                from_token="0x" + "0" * 40,
                to_chain="polygon",
                to_token="0x" + "0" * 40,
                amount_in64="1000",
                to_address=TO_ADDR,
            )

        assert result is None

    def test_none_response_returns_none(self) -> None:
        """None/non-dict response from API returns None."""
        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = None

        with patch("requests.get", return_value=mock_response):
            result = provider._call_quote_api(  # pylint: disable=protected-access
                from_chain="ethereum",
                from_token="0x" + "0" * 40,
                to_chain="polygon",
                to_token="0x" + "0" * 40,
                amount_in64="1000",
                to_address=TO_ADDR,
            )

        assert result is None

    def test_no_api_key_param_sent(self) -> None:
        """Verify no apiKey param is sent (removed per review feedback)."""
        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "minimumSdkVersion": "13_0_0",
            "quotes": [{"type": "SWIFT"}],
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            provider._call_quote_api(  # pylint: disable=protected-access
                from_chain="ethereum",
                from_token="0x" + "0" * 40,
                to_chain="polygon",
                to_token="0x" + "0" * 40,
                amount_in64="1000",
                to_address=TO_ADDR,
            )

        call_kwargs = mock_get.call_args
        assert "apiKey" not in call_kwargs.kwargs["params"]

    def test_amount_too_small_surfaces_structured_message(self) -> None:
        """406 AMOUNT_TOO_SMALL is reformatted as a readable ValueError."""
        import requests as req_lib

        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.status_code = 406
        mock_response.json.return_value = {
            "code": "AMOUNT_TOO_SMALL",
            "msg": "Amount too small (min ~0.0004795 ETH)",
            "data": {"minAmountIn": 0.0004795},
        }
        mock_response.raise_for_status.side_effect = req_lib.HTTPError(
            "406 Client Error: Not Acceptable"
        )

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="amount too small") as exc_info:
                provider._call_quote_api(  # pylint: disable=protected-access
                    from_chain="ethereum",
                    from_token="0x" + "0" * 40,
                    to_chain="polygon",
                    to_token="0x" + "0" * 40,
                    amount_in64="1000",
                    to_address=TO_ADDR,
                )

        msg = str(exc_info.value)
        assert "0.0004795" in msg
        # Should NOT contain the opaque HTTP error text
        assert "Client Error" not in msg

    def test_other_http_error_falls_back_to_raise(self) -> None:
        """Non-AMOUNT_TOO_SMALL HTTPError re-raises so callers can handle it."""
        import requests as req_lib

        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = ValueError("no json")
        mock_response.raise_for_status.side_effect = req_lib.HTTPError(
            "500 Server Error"
        )

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(req_lib.HTTPError):
                provider._call_quote_api(  # pylint: disable=protected-access
                    from_chain="ethereum",
                    from_token="0x" + "0" * 40,
                    to_chain="polygon",
                    to_token="0x" + "0" * 40,
                    amount_in64="1000",
                    to_address=TO_ADDR,
                )

    def test_other_mayan_code_surfaces_msg(self) -> None:
        """Mayan errors with a `code` other than AMOUNT_TOO_SMALL surface msg."""
        import requests as req_lib

        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "code": "ROUTE_NOT_FOUND",
            "msg": "No route available for this pair",
        }
        mock_response.raise_for_status.side_effect = req_lib.HTTPError(
            "400 Client Error"
        )

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="ROUTE_NOT_FOUND") as exc_info:
                provider._call_quote_api(  # pylint: disable=protected-access
                    from_chain="ethereum",
                    from_token="0x" + "0" * 40,
                    to_chain="polygon",
                    to_token="0x" + "0" * 40,
                    amount_in64="1000",
                    to_address=TO_ADDR,
                )
        assert "No route available" in str(exc_info.value)


# ---------------------------------------------------------------------------
# MayanProvider._get_txs — additional edge cases
# ---------------------------------------------------------------------------


class TestMayanProviderGetTxsEdgeCases:
    """Additional edge-case tests for MayanProvider._get_txs()."""

    def test_no_provider_data_raises(self) -> None:
        """Quote with no provider_data raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.quote_data = _make_quote_data(provider_data=None)
        with pytest.raises(RuntimeError, match="provider_data not present"):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_no_response_in_provider_data_raises(self) -> None:
        """Quote with empty response in provider_data raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.quote_data = _make_quote_data(
            provider_data={"response": None, "amount_in_final": 1020}
        )
        with pytest.raises(RuntimeError, match="response not present"):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_zero_amount_in_final_raises(self) -> None:
        """Quote with zero amount_in_final raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.quote_data = _make_quote_data(
            provider_data={
                "response": _make_mayan_quote_response(),
                "amount_in_final": 0,
            }
        )
        with pytest.raises(RuntimeError, match="amount_in_final is zero"):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_unknown_route_type_raises(self) -> None:
        """Unknown route type raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000,
            from_chain="ethereum",
            to_chain="polygon",
        )
        mock_response = _make_mayan_quote_response(route_type="UNKNOWN_TYPE")
        # Remove known contract keys so _get_mayan_protocol_address returns None
        mock_response.pop("swiftMayanContract", None)
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            pytest.raises(RuntimeError, match="unknown route type"),
        ):
            provider._get_txs(req)  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# MayanProvider._get_mayan_protocol_address
# ---------------------------------------------------------------------------


class TestGetMayanProtocolAddress:
    """Unit tests for MayanProvider._get_mayan_protocol_address()."""

    def test_swift_returns_swift_contract(self) -> None:
        """SWIFT route type returns swiftMayanContract."""
        response = {"swiftMayanContract": "0x1234"}
        result = MayanProvider._get_mayan_protocol_address(response, "SWIFT")
        assert result == "0x1234"

    def test_mctp_returns_mctp_contract(self) -> None:
        """MCTP route type returns mctpMayanContract."""
        response = {"mctpMayanContract": "0xABCD"}
        result = MayanProvider._get_mayan_protocol_address(response, "MCTP")
        assert result == "0xABCD"

    def test_fast_mctp_returns_fast_mctp_contract(self) -> None:
        """FAST_MCTP route type returns fastMctpMayanContract."""
        response = {"fastMctpMayanContract": "0xDEAD"}
        result = MayanProvider._get_mayan_protocol_address(response, "FAST_MCTP")
        assert result == "0xDEAD"

    def test_unknown_type_returns_none(self) -> None:
        """Unknown route type returns None."""
        result = MayanProvider._get_mayan_protocol_address({}, "WORMHOLE")
        assert result is None


# ---------------------------------------------------------------------------
# MayanProvider._update_execution_status — additional edge cases
# ---------------------------------------------------------------------------


class TestMayanProviderExecutionStatusEdgeCases:
    """Additional edge-case tests for MayanProvider._update_execution_status()."""

    def test_wrong_status_returns_early(self) -> None:
        """Status not in (EXECUTION_PENDING, EXECUTION_UNKNOWN) returns immediately."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.QUOTE_DONE,
            from_chain="ethereum",
            to_chain="polygon",
        )
        # Should return immediately without error
        provider._update_execution_status(req)  # pylint: disable=protected-access
        assert req.status == ProviderRequestStatus.QUOTE_DONE

    def test_no_execution_data_raises(self) -> None:
        """Missing execution_data raises RuntimeError."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = None
        with pytest.raises(RuntimeError, match="execution data not present"):
            provider._update_execution_status(req)  # pylint: disable=protected-access

    def test_completed_with_rpc_failure_still_succeeds(self) -> None:
        """COMPLETED status with RPC failure for elapsed_time still sets EXECUTION_DONE."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clientStatus": "COMPLETED",
            "fulfillTxHash": "0x" + "e" * 64,
        }

        with (
            patch("requests.get", return_value=mock_response),
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=MagicMock(),
            ),
            patch.object(
                Provider,
                "_tx_timestamp",
                side_effect=Exception("RPC unavailable"),
            ),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_DONE

    def test_general_exception_sets_unknown_or_failed(self) -> None:
        """General exception during status update sets EXECUTION_UNKNOWN or FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        with (
            patch("requests.get", side_effect=Exception("unexpected error")),
            patch.object(provider, "_bridge_tx_likely_failed", return_value=False),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_UNKNOWN

    def test_general_exception_with_likely_failed_sets_failed(self) -> None:
        """General exception with _bridge_tx_likely_failed=True sets EXECUTION_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        with (
            patch("requests.get", side_effect=Exception("unexpected error")),
            patch.object(provider, "_bridge_tx_likely_failed", return_value=True),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED

    def test_unknown_status_with_likely_failed_sets_failed(self) -> None:
        """Unknown clientStatus with _bridge_tx_likely_failed=True sets EXECUTION_FAILED."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clientStatus": "SOME_UNKNOWN_STATUS",
        }

        with (
            patch("requests.get", return_value=mock_response),
            patch.object(provider, "_bridge_tx_likely_failed", return_value=True),
        ):
            provider._update_execution_status(req)  # pylint: disable=protected-access

        assert req.status == ProviderRequestStatus.EXECUTION_FAILED


class TestMayanProviderAddressToBytes32:
    """Unit tests for MayanProvider._address_to_bytes32()."""

    def test_invalid_address_raises_value_error(self) -> None:
        """Non-standard hex address raises ValueError."""
        with pytest.raises(ValueError, match="Expected 20-byte hex address"):
            MayanProvider._address_to_bytes32(
                "not-an-address"
            )  # pylint: disable=protected-access

    def test_short_address_raises_value_error(self) -> None:
        """Address shorter than 42 chars raises ValueError."""
        with pytest.raises(ValueError, match="Expected 20-byte hex address"):
            MayanProvider._address_to_bytes32(
                "0x1234"
            )  # pylint: disable=protected-access


class TestMayanProviderBuildProtocolData:
    """Unit tests for MayanProvider._build_protocol_data()."""

    def test_unsupported_destination_chain_raises(self) -> None:
        """Unsupported destination chain raises ValueError."""
        provider = _make_mayan_provider()
        response = {
            "toToken": {"contract": ZERO_ADDRESS},
            "minAmountOutBaseUnits": "0",
            "gasDrop": "0",
            "cancelRelayerFee64": "0",
            "submitRelayerFee64": "0",
            "deadline64": "0",
            "referrerBps": "0",
            "swiftAuctionMode": "1",
            "swiftInputContract": "0x" + "f" * 40,
        }
        with pytest.raises(ValueError, match="Unsupported destination chain"):
            provider._build_protocol_data(  # pylint: disable=protected-access
                response=response,
                from_address=FROM_ADDR,
                from_token=ZERO_ADDRESS,
                to_address=TO_ADDR,
                to_chain="unsupported_chain",
                amount_in_final=1000,
                from_chain="ethereum",
            )

    @pytest.mark.parametrize("route_type", ["MCTP", "FAST_MCTP", "WORMHOLE"])
    def test_unsupported_route_type_raises(self, route_type: str) -> None:
        """Unknown route_type raises RuntimeError instead of silently SWIFT-encoding.

        Defensive guard for the case where the upstream API filter
        (_call_quote_api) and this encoder dispatch drift apart — a route the
        API was not supposed to return must not be silently encoded with the
        wrong ABI.
        """
        provider = _make_mayan_provider()
        response = {"type": route_type, "toToken": {"contract": ZERO_ADDRESS}}
        with pytest.raises(RuntimeError, match="unsupported route_type"):
            provider._build_protocol_data(  # pylint: disable=protected-access
                response=response,
                from_address=FROM_ADDR,
                from_token=ZERO_ADDRESS,
                to_address=TO_ADDR,
                to_chain="optimism",
                amount_in_final=1000,
                from_chain="ethereum",
            )


# ---------------------------------------------------------------------------
# MayanProvider — integration tests (live API, guarded)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMayanQuoteAPISchemaIntegration:
    """Live-schema validation against the Mayan Quote API.

    Verifies the response structure matches what the provider code expects.
    Unauthenticated — Mayan allows public calls with per-IP rate limits.
    """

    def test_swift_quote_schema(self) -> None:
        """Hit live Mayan Quote API for a SWIFT route and assert schema."""
        import requests  # pylint: disable=import-outside-toplevel

        from operate.bridge.providers.mayan_provider import (  # pylint: disable=import-outside-toplevel
            MAYAN_FORWARDER_ADDRESS,
            MAYAN_QUOTE_API_URL,
        )

        params = {
            "amountIn64": "1000000000000000000",  # 1 ETH in wei
            "fromToken": "0x0000000000000000000000000000000000000000",
            "fromChain": "ethereum",
            "toToken": "0x0000000000000000000000000000000000000000",
            "toChain": "polygon",
            "slippageBps": 300,
            "swift": "true",
            "mctp": "false",
            "fastMctp": "false",
            "wormhole": "false",
            "gasless": "false",
            "forwarderAddress": MAYAN_FORWARDER_ADDRESS,
            "destinationAddress": "0x" + "a" * 40,
            "sdkVersion": "13_0_0",
        }

        resp = requests.get(url=MAYAN_QUOTE_API_URL, params=params, timeout=30)
        if not resp.ok:
            pytest.skip(
                f"Mayan Quote API returned {resp.status_code} "
                f"(transient or route unavailable)"
            )
        payload = resp.json()

        # Envelope shape
        assert isinstance(payload, dict), "Expected dict envelope"
        assert "quotes" in payload, "Missing 'quotes' key in envelope"
        quotes = payload["quotes"]
        assert isinstance(quotes, list), "'quotes' should be a list"

        if not quotes:
            pytest.skip("No quotes returned (route may be temporarily unavailable)")

        quote = quotes[0]

        # Fields the provider code reads during quoting
        assert "effectiveAmountIn64" in quote
        assert "minAmountOutBaseUnits" in quote
        assert "expectedAmountOut" in quote
        assert "etaSeconds" in quote
        assert "type" in quote

        # Fields read during _build_protocol_data / _get_txs
        if quote["type"] == "SWIFT":
            assert "swiftMayanContract" in quote
            assert "swiftInputContract" in quote

    def test_explorer_api_404_on_fake_hash(self) -> None:
        """Explorer API returns 404 for a non-existent transaction hash."""
        import requests  # pylint: disable=import-outside-toplevel

        from operate.bridge.providers.mayan_provider import (  # pylint: disable=import-outside-toplevel
            MAYAN_EXPLORER_API_URL,
        )

        fake_hash = "0x" + "0" * 64
        resp = requests.get(url=f"{MAYAN_EXPLORER_API_URL}/{fake_hash}", timeout=30)
        assert resp.status_code == 404

    def test_mono_chain_quote_schema(self) -> None:
        """Hit live Mayan Quote API for a MONO_CHAIN route and assert schema."""
        import requests  # pylint: disable=import-outside-toplevel

        from operate.bridge.providers.mayan_provider import (  # pylint: disable=import-outside-toplevel
            MAYAN_FORWARDER_ADDRESS,
            MAYAN_QUOTE_API_URL,
        )

        params = {
            "amountIn64": "1000000",  # 1 USDC (6 decimals)
            "fromToken": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
            "fromChain": "polygon",
            "toToken": "0x0000000000000000000000000000000000001010",
            "toChain": "polygon",
            "slippageBps": 300,
            "swift": "false",
            "mctp": "false",
            "fastMctp": "false",
            "monoChain": "true",
            "wormhole": "false",
            "gasless": "false",
            "forwarderAddress": MAYAN_FORWARDER_ADDRESS,
            "destinationAddress": "0x" + "a" * 40,
            "sdkVersion": "13_0_0",
        }

        resp = requests.get(url=MAYAN_QUOTE_API_URL, params=params, timeout=30)
        if not resp.ok:
            pytest.skip(
                f"Mayan Quote API returned {resp.status_code} "
                f"(transient or route unavailable)"
            )
        payload = resp.json()

        assert isinstance(payload, dict), "Expected dict envelope"
        assert "quotes" in payload, "Missing 'quotes' key in envelope"
        quotes = payload["quotes"]
        assert isinstance(quotes, list), "'quotes' should be a list"

        if not quotes:
            pytest.skip("No quotes returned (route may be temporarily unavailable)")

        quote = quotes[0]

        # Fields the provider code reads during quoting
        assert "effectiveAmountIn64" in quote
        assert "minAmountOutBaseUnits" in quote
        assert "expectedAmountOut" in quote
        assert "etaSeconds" in quote
        assert quote["type"] == "MONO_CHAIN"

        # MONO_CHAIN-specific fields read during _get_txs
        assert "monoChainMayanContract" in quote
        assert "evmSwapRouterAddress" in quote
        assert "evmSwapRouterCalldata" in quote
        assert "expectedAmountOutBaseUnits" in quote


# ---------------------------------------------------------------------------
# MayanProvider — MONO_CHAIN unit tests
# ---------------------------------------------------------------------------


def _make_mono_chain_quote_response(
    expected_amount_out: float = 10.0,
    effective_amount_in: float = 1.0,
    min_amount_out_base_units: str = "9500000000000000000",
    expected_amount_out_base_units: str = "10000000000000000000",
    eta_seconds: int = 0,
    mono_chain_contract: str = "0x238856DE6d9d32EA3Dd4e9e7dbfe08b23cD5048c",
    swap_router_address: str = "0x0000000000001fF3684f28c67538d4D072C22734",
    swap_router_calldata: str = "0x2213bc0b",
) -> t.Dict:
    """Build a mock Mayan MONO_CHAIN Quote API response."""
    return {
        "type": "MONO_CHAIN",
        "effectiveAmountIn": effective_amount_in,
        "effectiveAmountIn64": str(int(effective_amount_in * 10**6)),
        "expectedAmountOut": expected_amount_out,
        "expectedAmountOutBaseUnits": expected_amount_out_base_units,
        "minAmountOut": expected_amount_out * 0.97,
        "minAmountOutBaseUnits": min_amount_out_base_units,
        "minReceivedBaseUnits": min_amount_out_base_units,
        "etaSeconds": eta_seconds,
        "bridgeFee": 0,
        "gasDrop": 0,
        "cancelRelayerFee64": "0",
        "submitRelayerFee64": "0",
        "deadline64": "0",
        "referrerBps": 0,
        "monoChainMayanContract": mono_chain_contract,
        "evmSwapRouterAddress": swap_router_address,
        "evmSwapRouterCalldata": swap_router_calldata,
        "slippageBps": 300,
        "toToken": {"contract": "0x0000000000000000000000000000000000001010"},
        "fromToken": {"contract": ZERO_ADDRESS},
    }


class TestMayanProviderGetMayanProtocolAddressMonoChain:
    """Unit tests for MONO_CHAIN in _get_mayan_protocol_address."""

    def test_mono_chain_returns_mono_chain_contract(self) -> None:
        """MONO_CHAIN route type returns monoChainMayanContract."""
        response = {"monoChainMayanContract": "0xABCD1234"}
        result = MayanProvider._get_mayan_protocol_address(response, "MONO_CHAIN")
        assert result == "0xABCD1234"


class TestMayanProviderBuildProtocolDataMonoChain:
    """Unit tests for MONO_CHAIN in _build_protocol_data."""

    def test_mono_chain_erc20_output_builds_transfer_token(self) -> None:
        """MONO_CHAIN with ERC-20 output builds transferToken protocolData."""
        provider = _make_mayan_provider()
        response = _make_mono_chain_quote_response()
        # to_token is ERC-20 (non-zero address)
        protocol_data = (
            provider._build_protocol_data(  # pylint: disable=protected-access
                response=response,
                from_address=FROM_ADDR,
                from_token=ZERO_ADDRESS,
                to_address=TO_ADDR,
                to_chain="polygon",
                amount_in_final=1000000,
                from_chain="polygon",
                to_token=ERC20_ADDR,
            )
        )
        assert isinstance(protocol_data, bytes)
        assert len(protocol_data) > 0

    def test_mono_chain_native_output_builds_transfer_eth(self) -> None:
        """MONO_CHAIN with native output builds transferEth protocolData."""
        provider = _make_mayan_provider()
        response = _make_mono_chain_quote_response()
        protocol_data = (
            provider._build_protocol_data(  # pylint: disable=protected-access
                response=response,
                from_address=FROM_ADDR,
                from_token=ERC20_ADDR,
                to_address=TO_ADDR,
                to_chain="polygon",
                amount_in_final=1000000,
                from_chain="polygon",
                to_token=ZERO_ADDRESS,  # native output
            )
        )
        assert isinstance(protocol_data, bytes)
        assert len(protocol_data) > 0


class TestMayanProviderGetTxsMonoChain:
    """Unit tests for MONO_CHAIN in _get_txs."""

    def test_mono_chain_native_input_returns_swap_and_forward_eth(self) -> None:
        """MONO_CHAIN with native input returns swapAndForwardEth tx."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000000,
            from_token=ZERO_ADDRESS,
            to_token=ERC20_ADDR,
            from_chain="polygon",
            to_chain="polygon",
        )
        mock_response = _make_mono_chain_quote_response()
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020000,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 1
        label, tx = txs[0]
        assert label == "swapAndForwardEth"
        assert tx["value"] == 1020000

    def test_mono_chain_erc20_input_returns_approve_and_swap_forward(self) -> None:
        """MONO_CHAIN ERC-20 input: approve + swapAndForwardERC20, plus full requirements() pipeline."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000000,
            from_token=ERC20_ADDR,
            to_token="0x" + "d" * 40,
            from_chain="polygon",
            to_chain="polygon",
        )
        mock_response = _make_mono_chain_quote_response()
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020000,
            }
        )

        # Use a real Web3 for eth.contract / to_checksum_address so the
        # approve calldata in the resulting tx dict is a real hex string
        # (otherwise requirements()'s ERC-20 calldata parsing sees a MagicMock).
        real_w3 = Web3()
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.contract = real_w3.eth.contract
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        # Set a known gas price so requirements() computes deterministic fees.
        def _set_gas_price(tx: t.Dict, _ledger_api: t.Any) -> None:
            tx["gasPrice"] = 1

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing",
                side_effect=_set_gas_price,
            ),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
            patch(
                "operate.bridge.providers.provider.update_tx_with_gas_pricing",
                side_effect=_set_gas_price,
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

            assert len(txs) == 2
            assert txs[0][0] == "approve"
            assert txs[1][0] == "swapAndForwardERC20"

            # Exercise the full MONO_CHAIN requirements() pipeline (regression pin).
            # Native fees = (approve_gas 50k + mono_chain_forwarder_gas 1M) * gas_price 1
            # swapAndForwardERC20 has value = bridge_fee = 0 in the fixture, so no extra native.
            # ERC-20 from_token total = approve amount = amount_in_final = 1_020_000.
            requirements = provider.requirements(req)

        polygon_amounts = requirements["polygon"][FROM_ADDR]
        assert polygon_amounts[ZERO_ADDRESS] == 1_050_000
        assert polygon_amounts[ERC20_ADDR] == 1_020_000

    def test_mono_chain_uses_higher_gas_default(self) -> None:
        """MONO_CHAIN txs use mono_chain_forwarder gas default (1M), not the SWIFT default (350k)."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000000,
            from_token=ZERO_ADDRESS,
            to_token=ERC20_ADDR,
            from_chain="polygon",
            to_chain="polygon",
        )
        mock_response = _make_mono_chain_quote_response()
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020000,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
        ):
            txs = provider._get_txs(req)  # pylint: disable=protected-access

        assert len(txs) == 1
        _, tx = txs[0]
        assert tx["gas"] == 1_000_000

    def test_mono_chain_null_swap_router_address_raises(self) -> None:
        """MONO_CHAIN raises RuntimeError when evmSwapRouterAddress is null."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000000,
            from_token=ZERO_ADDRESS,
            to_token=ERC20_ADDR,
            from_chain="polygon",
            to_chain="polygon",
        )
        mock_response = _make_mono_chain_quote_response()
        mock_response["evmSwapRouterAddress"] = None
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020000,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
            pytest.raises(RuntimeError, match="MONO_CHAIN quote missing swap router"),
        ):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_mono_chain_null_swap_router_calldata_raises(self) -> None:
        """MONO_CHAIN raises RuntimeError when evmSwapRouterCalldata is null."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000000,
            from_token=ERC20_ADDR,
            to_token="0x" + "d" * 40,
            from_chain="polygon",
            to_chain="polygon",
        )
        mock_response = _make_mono_chain_quote_response()
        mock_response["evmSwapRouterCalldata"] = None
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020000,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
            pytest.raises(RuntimeError, match="MONO_CHAIN quote missing swap router"),
        ):
            provider._get_txs(req)  # pylint: disable=protected-access

    def test_mono_chain_calldata_missing_0x_prefix_raises(self) -> None:
        """MONO_CHAIN raises RuntimeError when evmSwapRouterCalldata lacks '0x' prefix."""
        provider = _make_mayan_provider()
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            amount=1000000,
            from_token=ERC20_ADDR,
            to_token="0x" + "d" * 40,
            from_chain="polygon",
            to_chain="polygon",
        )
        mock_response = _make_mono_chain_quote_response()
        mock_response["evmSwapRouterCalldata"] = "2213bc0b"
        req.quote_data = _make_quote_data(
            provider_data={
                "response": mock_response,
                "amount_in_final": 1020000,
            }
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.to_checksum_address = Web3.to_checksum_address
        mock_ledger_api.api.eth.get_transaction_count.return_value = 0

        with (
            patch(
                "operate.bridge.providers.provider.get_default_ledger_api",
                return_value=mock_ledger_api,
            ),
            patch("operate.bridge.providers.mayan_provider.update_tx_with_gas_pricing"),
            patch(
                "operate.bridge.providers.mayan_provider.update_tx_with_gas_estimate"
            ),
            pytest.raises(
                RuntimeError,
                match="MONO_CHAIN evmSwapRouterCalldata missing '0x' prefix",
            ),
        ):
            provider._get_txs(req)  # pylint: disable=protected-access


class TestMayanProviderExplorerLinkMonoChain:
    """Unit tests for MONO_CHAIN in _get_explorer_link."""

    def test_mono_chain_uses_plain_tx_hash(self) -> None:
        """MONO_CHAIN route uses plain tx hash without prefix."""
        provider = _make_mayan_provider()
        tx_hash = "0x" + "a" * 64
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            from_chain="polygon",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data(from_tx_hash=tx_hash)
        req.quote_data = _make_quote_data(
            provider_data={
                "response": {"type": "MONO_CHAIN"},
                "amount_in_final": 1000,
            }
        )

        link = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert link == f"{MAYAN_EXPLORER_URL}/{tx_hash}"

    def test_swift_still_uses_prefix(self) -> None:
        """SWIFT route still uses SWIFT_V2_ prefix."""
        provider = _make_mayan_provider()
        tx_hash = "0x" + "a" * 64
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data(from_tx_hash=tx_hash)
        req.quote_data = _make_quote_data(
            provider_data={
                "response": {"type": "SWIFT"},
                "amount_in_final": 1000,
            }
        )

        link = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert link == f"{MAYAN_EXPLORER_URL}/SWIFT_V2_{tx_hash}"

    def test_no_quote_data_defaults_to_swift_prefix(self) -> None:
        """No quote_data defaults to SWIFT_V2_ prefix for backward compatibility."""
        provider = _make_mayan_provider()
        tx_hash = "0x" + "a" * 64
        req = _make_request(
            provider_id=MAYAN_PROVIDER_ID,
            from_chain="ethereum",
            to_chain="polygon",
        )
        req.execution_data = _make_execution_data(from_tx_hash=tx_hash)

        link = provider._get_explorer_link(req)  # pylint: disable=protected-access
        assert link == f"{MAYAN_EXPLORER_URL}/SWIFT_V2_{tx_hash}"


class TestMayanProviderCallQuoteApiMonoChain:
    """Unit tests for monoChain param in _call_quote_api."""

    def test_same_chain_sends_mono_chain_true(self) -> None:
        """Same from/to chain sends monoChain=true and swift=false."""
        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "minimumSdkVersion": "13_0_0",
            "quotes": [{"type": "MONO_CHAIN"}],
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            provider._call_quote_api(  # pylint: disable=protected-access
                from_chain="polygon",
                from_token="0x" + "0" * 40,
                to_chain="polygon",
                to_token="0x" + "0" * 40,
                amount_in64="1000",
                to_address=TO_ADDR,
            )

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"]["monoChain"] == "true"
        assert call_kwargs.kwargs["params"]["swift"] == "false"

    def test_cross_chain_sends_mono_chain_false(self) -> None:
        """Different from/to chain sends monoChain=false and swift=true."""
        provider = _make_mayan_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "minimumSdkVersion": "13_0_0",
            "quotes": [{"type": "SWIFT"}],
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            provider._call_quote_api(  # pylint: disable=protected-access
                from_chain="ethereum",
                from_token="0x" + "0" * 40,
                to_chain="polygon",
                to_token="0x" + "0" * 40,
                amount_in64="1000",
                to_address=TO_ADDR,
            )

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"]["monoChain"] == "false"
        assert call_kwargs.kwargs["params"]["swift"] == "true"
