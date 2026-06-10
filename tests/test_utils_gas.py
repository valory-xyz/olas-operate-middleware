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

"""Tests for operate/utils/gas.py — direct unit tests for wrap_gas_spike_as_insufficient_funds."""

from unittest.mock import MagicMock

import pytest
from aea_ledger_ethereum import EIP1559, get_default_gas_strategy
from autonomy.chain.exceptions import ChainInteractionError

from operate.exceptions import InsufficientFundsException
from operate.utils.gas import MIN_GAS_UNITS, wrap_gas_spike_as_insufficient_funds

CHAIN = "gnosis"
GNOSIS_CHAIN_ID = 100
SIGNER = "0xSigner"
GAS_PRICE = 10_000_000_000  # 10 Gwei
FALLBACK_GAS_PRICE = get_default_gas_strategy(GNOSIS_CHAIN_ID)[EIP1559][
    "fallback_estimate"
]["maxFeePerGas"]


def _make_ledger(balance: int, gas_price: int = GAS_PRICE) -> MagicMock:
    ledger = MagicMock()
    ledger.get_balance.return_value = balance
    ledger.try_get_gas_pricing.return_value = {"maxFeePerGas": gas_price}
    return ledger


def _healthy_ledger() -> MagicMock:
    """A ledger whose signer balance comfortably passes the pre-flight check."""
    return _make_ledger(balance=GAS_PRICE * MIN_GAS_UNITS * 10)


def _enter_preflight(ledger: MagicMock) -> None:
    """Enter and exit the guarded block; raises if the pre-flight check fires."""
    with wrap_gas_spike_as_insufficient_funds(CHAIN, "transfer", ledger, SIGNER):
        pass


class TestWrapGasSpikeAsInsufficientFunds:
    """Direct tests for the wrap_gas_spike_as_insufficient_funds context manager."""

    def test_value_error_gas_spike_chains_original_exception(self) -> None:
        """Verify ValueError gas-spike is wrapped and __cause__ is chained."""
        original = ValueError("insufficient funds for gas * price + value")
        with (
            pytest.raises(InsufficientFundsException) as exc_info,
            wrap_gas_spike_as_insufficient_funds(
                CHAIN, "test action", _healthy_ledger(), SIGNER
            ),
        ):
            raise original
        assert exc_info.value.__cause__ is original

    def test_chain_interaction_error_gas_spike_chains_original_exception(self) -> None:
        """Verify ChainInteractionError gas-spike is wrapped and __cause__ is chained."""
        original = ChainInteractionError("max fee per gas less than block base fee")
        with (
            pytest.raises(InsufficientFundsException) as exc_info,
            wrap_gas_spike_as_insufficient_funds(
                CHAIN, "test action", _healthy_ledger(), SIGNER
            ),
        ):
            raise original
        assert exc_info.value.__cause__ is original

    def test_non_gas_value_error_reraises_unchanged(self) -> None:
        """Verify ValueError not related to gas propagates unchanged."""
        original = ValueError("contract reverted")
        with (
            pytest.raises(ValueError, match="contract reverted"),
            wrap_gas_spike_as_insufficient_funds(
                CHAIN, "test action", _healthy_ledger(), SIGNER
            ),
        ):
            raise original

    def test_non_gas_chain_interaction_error_reraises_unchanged(self) -> None:
        """Verify ChainInteractionError not related to gas propagates unchanged."""
        original = ChainInteractionError("nonce too low")
        with (
            pytest.raises(ChainInteractionError, match="nonce too low"),
            wrap_gas_spike_as_insufficient_funds(
                CHAIN, "test action", _healthy_ledger(), SIGNER
            ),
        ):
            raise original

    def test_chain_field_is_set_correctly(self) -> None:
        """Verify the chain field on InsufficientFundsException is set from the argument."""
        with (
            pytest.raises(InsufficientFundsException) as exc_info,
            wrap_gas_spike_as_insufficient_funds(
                "ethereum", "deploy safe", _healthy_ledger(), SIGNER
            ),
        ):
            raise ValueError("insufficient funds for gas * price + value")
        assert exc_info.value.chain == "ethereum"

    def test_no_exception_passes_through(self) -> None:
        """Verify the context manager does nothing when no exception is raised."""
        with wrap_gas_spike_as_insufficient_funds(
            CHAIN, "test action", _healthy_ledger(), SIGNER
        ):
            pass  # Should not raise

    def test_unrelated_exception_type_propagates(self) -> None:
        """Verify exceptions other than ValueError/ChainInteractionError propagate."""
        with (
            pytest.raises(RuntimeError, match="something else"),
            wrap_gas_spike_as_insufficient_funds(
                CHAIN, "test action", _healthy_ledger(), SIGNER
            ),
        ):
            raise RuntimeError("something else")


class TestPreflightSignerGas:
    """Unit tests for the pre-flight path of wrap_gas_spike_as_insufficient_funds."""

    def test_balance_zero_fires_immediately(self) -> None:
        """Zero balance raises InsufficientFundsException before yielding."""
        ledger = _make_ledger(balance=0)
        with pytest.raises(InsufficientFundsException) as exc_info:
            _enter_preflight(ledger)
        assert exc_info.value.chain == CHAIN
        assert (
            exc_info.value.to_error_fields()["error_code"] == "INSUFFICIENT_SIGNER_GAS"
        )

    def test_dust_balance_below_threshold_fires(self) -> None:
        """Balance far below gas_price * MIN_GAS_UNITS raises immediately."""
        threshold = GAS_PRICE * MIN_GAS_UNITS
        ledger = _make_ledger(balance=threshold // 1000)
        with pytest.raises(InsufficientFundsException):
            _enter_preflight(ledger)

    def test_sufficient_balance_passes_through(self) -> None:
        """Balance exactly above threshold lets body execute normally."""
        threshold = GAS_PRICE * MIN_GAS_UNITS
        ledger = _make_ledger(balance=threshold + 1)
        executed = []
        with wrap_gas_spike_as_insufficient_funds(CHAIN, "transfer", ledger, SIGNER):
            executed.append(True)
        assert executed == [True]

    def test_fast_path_skips_gas_pricing_rpc(self) -> None:
        """Balance above the fallback-estimate threshold never calls try_get_gas_pricing."""
        ledger = _make_ledger(balance=FALLBACK_GAS_PRICE * MIN_GAS_UNITS)
        _enter_preflight(ledger)
        ledger.try_get_gas_pricing.assert_not_called()

    def test_gray_zone_low_live_price_passes(self) -> None:
        """Balance below the fallback threshold passes when live gas price is low enough."""
        low_gas_price = FALLBACK_GAS_PRICE // 5
        balance = low_gas_price * MIN_GAS_UNITS + 1
        assert balance < FALLBACK_GAS_PRICE * MIN_GAS_UNITS
        ledger = _make_ledger(balance=balance, gas_price=low_gas_price)
        _enter_preflight(ledger)
        ledger.try_get_gas_pricing.assert_called_once()

    def test_get_balance_raises_is_swallowed(self) -> None:
        """RPC error in get_balance is swallowed; body executes normally."""
        ledger = MagicMock()
        ledger.get_balance.side_effect = RuntimeError("RPC down")
        executed = []
        with wrap_gas_spike_as_insufficient_funds(CHAIN, "transfer", ledger, SIGNER):
            executed.append(True)
        assert executed == [True]

    def test_no_gas_pricing_uses_fallback_estimate_fires(self) -> None:
        """When try_get_gas_pricing returns None, the chain's fallback_estimate gas price is used."""
        ledger = MagicMock()
        ledger.get_balance.return_value = FALLBACK_GAS_PRICE * MIN_GAS_UNITS - 1
        ledger.try_get_gas_pricing.return_value = None
        with pytest.raises(InsufficientFundsException):
            _enter_preflight(ledger)

    def test_legacy_gas_price_key_used_as_threshold(self) -> None:
        """Legacy gasPrice key (no maxFeePerGas) is used to compute threshold."""
        ledger = MagicMock()
        ledger.get_balance.return_value = 0
        ledger.try_get_gas_pricing.return_value = {"gasPrice": GAS_PRICE}
        with pytest.raises(InsufficientFundsException):
            _enter_preflight(ledger)

    def test_non_int_balance_skips_check(self) -> None:
        """Non-int get_balance return (e.g. MagicMock in tests) skips check safely."""
        ledger = MagicMock()
        ledger.get_balance.return_value = MagicMock()  # not an int
        ledger.try_get_gas_pricing.return_value = {"maxFeePerGas": GAS_PRICE}
        executed = []
        with wrap_gas_spike_as_insufficient_funds(CHAIN, "transfer", ledger, SIGNER):
            executed.append(True)
        assert executed == [True]

    def test_existing_message_path_still_works_with_preflight(self) -> None:
        """Sufficient balance passes pre-flight; gas-spike ValueError in body still raises InsufficientFundsException."""
        with (
            pytest.raises(InsufficientFundsException) as exc_info,
            wrap_gas_spike_as_insufficient_funds(
                CHAIN, "test action", _healthy_ledger(), SIGNER
            ),
        ):
            raise ValueError("insufficient funds for gas * price + value")
        assert exc_info.value.chain == CHAIN
