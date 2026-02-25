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

"""Tests for operate.ledger.profiles module."""

from unittest.mock import MagicMock, patch

from autonomy.chain.base import registry_contracts

from operate.constants import NO_STAKING_PROGRAM_ID, ZERO_ADDRESS
from operate.ledger import NATIVE_CURRENCY_DECIMALS
from operate.ledger.profiles import (
    OLAS,
    WRAPPED_NATIVE_ASSET,
    format_asset_amount,
    get_asset_decimals,
    get_asset_name,
    get_staking_contract,
)
from operate.operate_types import Chain


class TestGetAssetName:
    """Tests for get_asset_name function (lines 338-348)."""

    def test_zero_address_returns_native_denom(self) -> None:
        """Test ZERO_ADDRESS returns the chain's native currency denom (line 339)."""
        result = get_asset_name(Chain.GNOSIS, ZERO_ADDRESS)
        assert result == "xDAI"

    def test_wrapped_native_asset_returns_w_prefixed(self) -> None:
        """Test wrapped native asset address returns 'W{denom}' (line 342)."""
        wrapped_address = WRAPPED_NATIVE_ASSET[Chain.GNOSIS]
        result = get_asset_name(Chain.GNOSIS, wrapped_address)
        assert result == "WxDAI"

    def test_known_erc20_returns_symbol(self) -> None:
        """Test a known ERC20 token address returns its symbol (lines 344-346)."""
        olas_address = OLAS[Chain.ETHEREUM]
        result = get_asset_name(Chain.ETHEREUM, olas_address)
        assert result == "OLAS"

    def test_unknown_address_returns_address_itself(self) -> None:
        """Test an unknown address is returned unchanged (line 348)."""
        unknown = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        result = get_asset_name(Chain.GNOSIS, unknown)
        assert result == unknown


class TestGetAssetDecimals:
    """Tests for get_asset_decimals function (lines 354-360)."""

    def test_zero_address_returns_native_decimals(self) -> None:
        """Test ZERO_ADDRESS returns NATIVE_CURRENCY_DECIMALS without RPC call (line 355)."""
        result = get_asset_decimals(Chain.BASE, ZERO_ADDRESS)
        assert result == NATIVE_CURRENCY_DECIMALS

    def test_erc20_address_calls_contract_decimals(self) -> None:
        """Test ERC20 address triggers on-chain decimals() call (lines 356-360)."""
        mock_instance = MagicMock()
        mock_instance.functions.decimals.return_value.call.return_value = 6

        # Use a unique fake address so the @cache does not return a previously stored result
        fake_erc20 = "0xFAKEERC20TOKENADDRESS0000000000000000001"

        with patch.object(
            registry_contracts.erc20,
            "get_instance",
            return_value=mock_instance,
        ):
            result = get_asset_decimals(Chain.GNOSIS, fake_erc20)

        assert result == 6


class TestFormatAssetAmount:
    """Tests for format_asset_amount function (lines 367-370)."""

    def test_format_native_amount_gnosis(self) -> None:
        """Test format_asset_amount returns human-readable string for native token."""
        # 1.5 xDAI = 1.5 * 10^18 wei
        amount = int(1.5 * 10**18)
        result = format_asset_amount(Chain.GNOSIS, ZERO_ADDRESS, amount)
        assert "1.5000" in result
        assert "xDAI" in result


class TestGetStakingContract:
    """Tests for get_staking_contract function (lines 378-384)."""

    def test_none_staking_program_id_returns_none(self) -> None:
        """Test None staking_program_id returns None (line 379)."""
        result = get_staking_contract("gnosis", None)
        assert result is None

    def test_no_staking_program_id_returns_none(self) -> None:
        """Test NO_STAKING_PROGRAM_ID returns None (line 379)."""
        result = get_staking_contract("gnosis", NO_STAKING_PROGRAM_ID)
        assert result is None

    def test_known_staking_program_returns_contract_address(self) -> None:
        """Test a known staking program ID returns its contract address (lines 381-383)."""
        result = get_staking_contract("gnosis", "pearl_alpha")
        assert result == "0xEE9F19b5DF06c7E8Bfc7B28745dcf944C504198A"

    def test_unknown_staking_program_returns_program_id(self) -> None:
        """Test an unknown staking program ID is returned unchanged (line 383)."""
        result = get_staking_contract("gnosis", "not_a_real_program_xyz")
        assert result == "not_a_real_program_xyz"
