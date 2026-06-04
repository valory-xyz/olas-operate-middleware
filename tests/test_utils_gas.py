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

import pytest
from autonomy.chain.exceptions import ChainInteractionError

from operate.exceptions import InsufficientFundsException
from operate.utils.gas import wrap_gas_spike_as_insufficient_funds


class TestWrapGasSpikeAsInsufficientFunds:
    """Direct tests for the wrap_gas_spike_as_insufficient_funds context manager."""

    def test_value_error_gas_spike_chains_original_exception(self) -> None:
        """Verify ValueError gas-spike is wrapped and __cause__ is chained."""
        original = ValueError("insufficient funds for gas * price + value")
        with (
            pytest.raises(InsufficientFundsException) as exc_info,
            wrap_gas_spike_as_insufficient_funds("gnosis", "test action"),
        ):
            raise original
        assert exc_info.value.__cause__ is original

    def test_chain_interaction_error_gas_spike_chains_original_exception(self) -> None:
        """Verify ChainInteractionError gas-spike is wrapped and __cause__ is chained."""
        original = ChainInteractionError("max fee per gas less than block base fee")
        with (
            pytest.raises(InsufficientFundsException) as exc_info,
            wrap_gas_spike_as_insufficient_funds("gnosis", "test action"),
        ):
            raise original
        assert exc_info.value.__cause__ is original

    def test_non_gas_value_error_reraises_unchanged(self) -> None:
        """Verify ValueError not related to gas propagates unchanged."""
        original = ValueError("contract reverted")
        with (
            pytest.raises(ValueError, match="contract reverted"),
            wrap_gas_spike_as_insufficient_funds("gnosis", "test action"),
        ):
            raise original

    def test_non_gas_chain_interaction_error_reraises_unchanged(self) -> None:
        """Verify ChainInteractionError not related to gas propagates unchanged."""
        original = ChainInteractionError("nonce too low")
        with (
            pytest.raises(ChainInteractionError, match="nonce too low"),
            wrap_gas_spike_as_insufficient_funds("gnosis", "test action"),
        ):
            raise original

    def test_chain_field_is_set_correctly(self) -> None:
        """Verify the chain field on InsufficientFundsException is set from the argument."""
        with (
            pytest.raises(InsufficientFundsException) as exc_info,
            wrap_gas_spike_as_insufficient_funds("ethereum", "deploy safe"),
        ):
            raise ValueError("insufficient funds for gas * price + value")
        assert exc_info.value.chain == "ethereum"

    def test_no_exception_passes_through(self) -> None:
        """Verify the context manager does nothing when no exception is raised."""
        with wrap_gas_spike_as_insufficient_funds("gnosis", "test action"):
            pass  # Should not raise

    def test_unrelated_exception_type_propagates(self) -> None:
        """Verify exceptions other than ValueError/ChainInteractionError propagate."""
        with (
            pytest.raises(RuntimeError, match="something else"),
            wrap_gas_spike_as_insufficient_funds("gnosis", "test action"),
        ):
            raise RuntimeError("something else")
