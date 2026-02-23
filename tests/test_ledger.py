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

"""Tests for operate/ledger/__init__.py."""

from copy import deepcopy
from math import ceil
from unittest.mock import MagicMock, patch

import pytest
from aea_ledger_ethereum import DEFAULT_GAS_PRICE_STRATEGIES, EIP1559, GWEI, to_wei

from operate.ledger import (
    DEFAULT_GAS_ESTIMATE_MULTIPLIER,
    GAS_ESTIMATE_FALLBACK_ADDRESSES,
    get_currency_smallest_unit,
    make_chain_ledger_api,
    update_tx_with_gas_estimate,
    update_tx_with_gas_pricing,
)
from operate.operate_types import Chain


class TestGetCurrencySmallestUnit:
    """Tests for get_currency_smallest_unit (line 110)."""

    def test_known_chain_returns_correct_unit(self) -> None:
        """Test that known chains return their configured smallest unit."""
        assert get_currency_smallest_unit(Chain.SOLANA) == "Lamport"
        assert get_currency_smallest_unit(Chain.ETHEREUM) == "Wei"

    def test_unknown_chain_falls_back_to_wei(self) -> None:
        """Test unknown chain falls back to 'Wei' default (line 110)."""
        mock_chain = MagicMock()
        result = get_currency_smallest_unit(mock_chain)
        assert result == "Wei"


class TestMakeChainLedgerApi:
    """Tests for make_chain_ledger_api (lines 122, 126, 130-131)."""

    def test_solana_raises_not_implemented(self) -> None:
        """Test Solana chain raises NotImplementedError (line 122)."""
        with pytest.raises(NotImplementedError, match="Solana"):
            make_chain_ledger_api(Chain.SOLANA)

    @pytest.mark.parametrize("chain", [Chain.BASE, Chain.MODE, Chain.OPTIMISM])
    def test_base_mode_optimism_set_fallback_max_fee_per_gas(
        self, chain: Chain
    ) -> None:
        """Test BASE/MODE/OPTIMISM set fallback maxFeePerGas to 5 GWEI (line 126)."""
        captured: dict = {}

        def fake_make_ledger_api(ledger_type: str, **kwargs: object) -> MagicMock:
            captured["gas_price_strategies"] = kwargs.get("gas_price_strategies")
            return MagicMock()

        with patch("operate.ledger.make_ledger_api", side_effect=fake_make_ledger_api):
            make_chain_ledger_api(chain)

        gps = captured["gas_price_strategies"]
        assert gps[EIP1559]["fallback_estimate"]["maxFeePerGas"] == to_wei(5, GWEI)

    def test_polygon_sets_max_gas_fast_and_max_fee_per_gas(self) -> None:
        """Test Polygon sets max_gas_fast and fallback maxFeePerGas (lines 130-131)."""
        captured: dict = {}

        def fake_make_ledger_api(ledger_type: str, **kwargs: object) -> MagicMock:
            captured["gas_price_strategies"] = kwargs.get("gas_price_strategies")
            return MagicMock()

        with patch("operate.ledger.make_ledger_api", side_effect=fake_make_ledger_api):
            make_chain_ledger_api(Chain.POLYGON)

        gps = captured["gas_price_strategies"]
        assert gps[EIP1559]["max_gas_fast"] == 10000
        assert gps[EIP1559]["fallback_estimate"]["maxFeePerGas"] == to_wei(6000, GWEI)

    def test_other_chains_do_not_modify_gas_strategies(self) -> None:
        """Test unmodified chains pass default gas_price_strategies unchanged."""
        default = deepcopy(DEFAULT_GAS_PRICE_STRATEGIES)
        captured: dict = {}

        def fake_make_ledger_api(ledger_type: str, **kwargs: object) -> MagicMock:
            captured["gas_price_strategies"] = kwargs.get("gas_price_strategies")
            return MagicMock()

        with patch("operate.ledger.make_ledger_api", side_effect=fake_make_ledger_api):
            make_chain_ledger_api(Chain.GNOSIS)

        assert captured["gas_price_strategies"] == default


class TestUpdateTxWithGasPricing:
    """Tests for update_tx_with_gas_pricing (lines 166-180)."""

    def test_removes_existing_gas_fields_before_applying(self) -> None:
        """Test that old gas fields are stripped before new pricing is applied."""
        mock_api = MagicMock()
        mock_api.try_get_gas_pricing.return_value = {"gasPrice": 100}
        tx = {
            "from": "0x1",
            "maxFeePerGas": 999,
            "maxPriorityFeePerGas": 99,
            "gasPrice": 50,
        }
        update_tx_with_gas_pricing(tx, mock_api)
        assert "maxFeePerGas" not in tx
        assert "maxPriorityFeePerGas" not in tx
        assert tx["gasPrice"] == 100

    def test_raises_when_gas_pricing_unavailable(self) -> None:
        """Test RuntimeError raised when gas pricing returns None (lines 171-172)."""
        mock_api = MagicMock()
        mock_api.try_get_gas_pricing.return_value = None
        with pytest.raises(RuntimeError, match="Unable to retrieve gas pricing"):
            update_tx_with_gas_pricing({}, mock_api)

    def test_applies_eip1559_gas_pricing(self) -> None:
        """Test EIP-1559 pricing sets maxFeePerGas and maxPriorityFeePerGas (lines 174-176)."""
        mock_api = MagicMock()
        mock_api.try_get_gas_pricing.return_value = {
            "maxFeePerGas": 500,
            "maxPriorityFeePerGas": 50,
        }
        tx: dict = {}
        update_tx_with_gas_pricing(tx, mock_api)
        assert tx["maxFeePerGas"] == 500
        assert tx["maxPriorityFeePerGas"] == 50
        assert "gasPrice" not in tx

    def test_applies_legacy_gas_price(self) -> None:
        """Test legacy pricing sets gasPrice (lines 177-178)."""
        mock_api = MagicMock()
        mock_api.try_get_gas_pricing.return_value = {"gasPrice": 77}
        tx: dict = {}
        update_tx_with_gas_pricing(tx, mock_api)
        assert tx["gasPrice"] == 77
        assert "maxFeePerGas" not in tx

    def test_raises_on_invalid_pricing_format(self) -> None:
        """Test RuntimeError raised when pricing format is unrecognised (line 180)."""
        mock_api = MagicMock()
        mock_api.try_get_gas_pricing.return_value = {"unknown_field": 123}
        with pytest.raises(RuntimeError, match="invalid gas pricing"):
            update_tx_with_gas_pricing({}, mock_api)


class TestUpdateTxWithGasEstimate:
    """Tests for update_tx_with_gas_estimate (lines 191-205)."""

    def test_first_address_succeeds(self) -> None:
        """Test gas estimated successfully on first address (lines 191-199)."""

        def set_gas(tx: dict) -> None:
            tx["gas"] = 80000

        mock_api = MagicMock()
        mock_api.update_with_gas_estimate.side_effect = set_gas
        tx = {"from": "0xABCD", "gas": 50}
        update_tx_with_gas_estimate(tx, mock_api)

        assert tx["from"] == "0xABCD"
        assert tx["gas"] == ceil(80000 * DEFAULT_GAS_ESTIMATE_MULTIPLIER)
        assert mock_api.update_with_gas_estimate.call_count == 1

    def test_fallback_address_used_when_first_fails(self) -> None:
        """Test fallback address is tried when primary address fails (lines 194-199)."""
        call_count = [0]

        def set_gas(tx: dict) -> None:
            call_count[0] += 1
            if call_count[0] == 1:
                tx["gas"] = 1  # Primary fails (gas unchanged at 1)
            else:
                tx["gas"] = 120000  # Fallback succeeds

        mock_api = MagicMock()
        mock_api.update_with_gas_estimate.side_effect = set_gas
        tx = {"from": "0xABCD"}
        update_tx_with_gas_estimate(tx, mock_api)

        assert tx["from"] == "0xABCD"
        assert tx["gas"] == ceil(120000 * DEFAULT_GAS_ESTIMATE_MULTIPLIER)
        assert call_count[0] == 2

    def test_all_addresses_fail_restores_original_gas(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Test original gas restored and warning printed when all addresses fail (lines 202-204)."""
        mock_api = MagicMock()
        mock_api.update_with_gas_estimate.side_effect = lambda tx: None  # no-op

        tx = {"from": "0xABCD", "gas": 50000}
        update_tx_with_gas_estimate(tx, mock_api)

        assert tx["from"] == "0xABCD"
        assert tx["gas"] == ceil(50000 * DEFAULT_GAS_ESTIMATE_MULTIPLIER)
        captured = capsys.readouterr()
        assert "Unable to estimate gas" in captured.out
        expected_calls = 1 + len(GAS_ESTIMATE_FALLBACK_ADDRESSES)
        assert mock_api.update_with_gas_estimate.call_count == expected_calls

    def test_custom_multiplier_is_applied(self) -> None:
        """Test custom gas_estimate_multiplier is applied to final gas (line 205)."""

        def set_gas(tx: dict) -> None:
            tx["gas"] = 60000

        mock_api = MagicMock()
        mock_api.update_with_gas_estimate.side_effect = set_gas
        tx = {"from": "0x1"}
        update_tx_with_gas_estimate(tx, mock_api, gas_estimate_multiplier=2.0)

        assert tx["gas"] == ceil(60000 * 2.0)
