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

"""Tests for operate/utils/gnosis.py utility functions."""

from unittest.mock import MagicMock, patch

import pytest
from autonomy.chain.exceptions import ChainInteractionError

from operate.constants import ZERO_ADDRESS
from operate.serialization import BigInt
from operate.utils.gnosis import (
    MultiSendOperation,
    SENTINEL_OWNERS,
    SafeOperation,
    _get_nonce,
    gas_fees_spent_in_tx,
    get_asset_balance,
    get_assets_balances,
    get_prev_owner,
    hash_payload_to_hex,
    skill_input_hex_to_payload,
)


class TestSafeOperation:
    """Tests for SafeOperation enum."""

    def test_call_value(self) -> None:
        """Test that CALL has value 0."""
        assert SafeOperation.CALL.value == 0

    def test_delegate_call_value(self) -> None:
        """Test that DELEGATE_CALL has value 1."""
        assert SafeOperation.DELEGATE_CALL.value == 1

    def test_create_value(self) -> None:
        """Test that CREATE has value 2."""
        assert SafeOperation.CREATE.value == 2


class TestMultiSendOperation:
    """Tests for MultiSendOperation enum."""

    def test_call_value(self) -> None:
        """Test that CALL has value 0."""
        assert MultiSendOperation.CALL.value == 0

    def test_delegate_call_value(self) -> None:
        """Test that DELEGATE_CALL has value 1."""
        assert MultiSendOperation.DELEGATE_CALL.value == 1


class TestHashPayloadRoundtrip:
    """Tests for hash_payload_to_hex and skill_input_hex_to_payload."""

    SAFE_TX_HASH = "a" * 64
    TO_ADDRESS = "0x" + "b" * 40

    def test_roundtrip_basic(self) -> None:
        """Test that basic encode/decode roundtrip preserves all values."""
        data = b"\x01\x02\x03"
        payload = hash_payload_to_hex(
            safe_tx_hash=self.SAFE_TX_HASH,
            ether_value=100,
            safe_tx_gas=200,
            to_address=self.TO_ADDRESS,
            data=data,
        )
        decoded = skill_input_hex_to_payload(payload)
        assert decoded["safe_tx_hash"] == self.SAFE_TX_HASH
        assert decoded["ether_value"] == 100
        assert decoded["safe_tx_gas"] == 200
        assert decoded["to_address"] == self.TO_ADDRESS
        assert decoded["data"] == data

    def test_roundtrip_empty_data(self) -> None:
        """Test roundtrip with empty data bytes."""
        payload = hash_payload_to_hex(
            safe_tx_hash=self.SAFE_TX_HASH,
            ether_value=0,
            safe_tx_gas=0,
            to_address=self.TO_ADDRESS,
            data=b"",
        )
        decoded = skill_input_hex_to_payload(payload)
        assert decoded["data"] == b""

    def test_roundtrip_with_optional_params(self) -> None:
        """Test roundtrip with all optional parameters set."""
        gas_token = "0x" + "c" * 40
        refund_receiver = "0x" + "d" * 40
        payload = hash_payload_to_hex(
            safe_tx_hash=self.SAFE_TX_HASH,
            ether_value=0,
            safe_tx_gas=0,
            to_address=self.TO_ADDRESS,
            data=b"",
            operation=SafeOperation.CALL.value,
            base_gas=50,
            safe_gas_price=10,
            gas_token=gas_token,
            refund_receiver=refund_receiver,
            use_flashbots=True,
            gas_limit=21000,
            raise_on_failed_simulation=True,
        )
        decoded = skill_input_hex_to_payload(payload)
        assert decoded["base_gas"] == 50
        assert decoded["safe_gas_price"] == 10
        assert decoded["gas_token"] == gas_token
        assert decoded["refund_receiver"] == refund_receiver
        assert decoded["use_flashbots"]  # truthy: 1 or True
        assert decoded["gas_limit"] == 21000
        assert decoded["raise_on_failed_simulation"]  # truthy: 1 or True

    def test_use_flashbots_non_bool_raises(self) -> None:
        """Test that passing a non-bool use_flashbots raises ValueError."""
        with pytest.raises(ValueError, match="use_flashbots"):
            hash_payload_to_hex(
                safe_tx_hash=self.SAFE_TX_HASH,
                ether_value=0,
                safe_tx_gas=0,
                to_address=self.TO_ADDRESS,
                data=b"",
                use_flashbots=42,  # type: ignore[arg-type]
            )

    def test_default_addresses_in_roundtrip(self) -> None:
        """Test that default gas_token and refund_receiver round-trip correctly."""
        payload = hash_payload_to_hex(
            safe_tx_hash=self.SAFE_TX_HASH,
            ether_value=0,
            safe_tx_gas=0,
            to_address=self.TO_ADDRESS,
            data=b"",
        )
        decoded = skill_input_hex_to_payload(payload)
        assert decoded["gas_token"] == ZERO_ADDRESS
        assert decoded["refund_receiver"] == ZERO_ADDRESS


class TestGetNonce:
    """Tests for _get_nonce helper."""

    def test_returns_integer(self) -> None:
        """Test that _get_nonce returns an integer."""
        nonce = _get_nonce()
        assert isinstance(nonce, int)

    def test_within_valid_range(self) -> None:
        """Test that the nonce is within [0, 2**256 - 1]."""
        nonce = _get_nonce()
        assert 0 <= nonce <= 2**256 - 1

    def test_multiple_calls_produce_different_values(self) -> None:
        """Test that repeated calls likely produce distinct nonces."""
        nonces = {_get_nonce() for _ in range(5)}
        assert len(nonces) > 1  # probability of collision is negligible


class TestGetPrevOwner:
    """Tests for get_prev_owner."""

    def test_first_owner_returns_sentinel(self) -> None:
        """Test that the first owner's predecessor is SENTINEL_OWNERS."""
        mock_ledger = MagicMock()
        owners = ["0xOwner1", "0xOwner2", "0xOwner3"]
        with patch("operate.utils.gnosis.get_owners", return_value=owners):
            prev = get_prev_owner(mock_ledger, "0xSafe", "0xOwner1")
        assert prev == SENTINEL_OWNERS

    def test_second_owner_returns_first(self) -> None:
        """Test that the second owner's predecessor is the first owner."""
        mock_ledger = MagicMock()
        owners = ["0xOwner1", "0xOwner2", "0xOwner3"]
        with patch("operate.utils.gnosis.get_owners", return_value=owners):
            prev = get_prev_owner(mock_ledger, "0xSafe", "0xOwner2")
        assert prev == "0xOwner1"

    def test_owner_not_found_raises(self) -> None:
        """Test that a missing owner raises ValueError."""
        mock_ledger = MagicMock()
        owners = ["0xOwner1", "0xOwner2"]
        with patch("operate.utils.gnosis.get_owners", return_value=owners):
            with pytest.raises(ValueError, match="not found in the owners"):
                get_prev_owner(mock_ledger, "0xSafe", "0xUnknown")


class TestGetAssetBalance:
    """Tests for get_asset_balance."""

    VALID_ADDRESS = "0x" + "a" * 40

    def test_invalid_address_raises_value_error(self) -> None:
        """Test that an invalid address raises ValueError."""
        mock_ledger = MagicMock()
        with patch("operate.utils.gnosis.Web3.is_address", return_value=False):
            with pytest.raises(ValueError, match="Invalid address"):
                get_asset_balance(mock_ledger, ZERO_ADDRESS, "not_an_address")

    def test_invalid_address_returns_zero_when_no_raise(self) -> None:
        """Test BigInt(0) is returned for an invalid address when raise is disabled."""
        mock_ledger = MagicMock()
        with patch("operate.utils.gnosis.Web3.is_address", return_value=False):
            result = get_asset_balance(
                mock_ledger,
                ZERO_ADDRESS,
                "not_an_address",
                raise_on_invalid_address=False,
            )
        assert result == BigInt(0)

    def test_native_balance_zero_address(self) -> None:
        """Test retrieving native token balance via zero asset address."""
        mock_ledger = MagicMock()
        mock_ledger.get_balance.return_value = 1000
        with patch("operate.utils.gnosis.Web3.is_address", return_value=True):
            result = get_asset_balance(
                mock_ledger, ZERO_ADDRESS, self.VALID_ADDRESS
            )
        assert result == BigInt(1000)
        mock_ledger.get_balance.assert_called_once()

    def test_erc20_token_balance(self) -> None:
        """Test retrieving ERC20 token balance."""
        mock_ledger = MagicMock()
        mock_instance = MagicMock()
        mock_instance.functions.balanceOf.return_value.call.return_value = 500
        token_address = "0x" + "e" * 40
        with patch("operate.utils.gnosis.Web3.is_address", return_value=True), patch(
            "operate.utils.gnosis.registry_contracts"
        ) as mock_contracts:
            mock_contracts.erc20.get_instance.return_value = mock_instance
            result = get_asset_balance(
                mock_ledger, token_address, self.VALID_ADDRESS
            )
        assert result == BigInt(500)

    def test_exception_wraps_in_runtime_error(self) -> None:
        """Test that internal exceptions are wrapped in RuntimeError."""
        mock_ledger = MagicMock()
        mock_ledger.get_balance.side_effect = Exception("rpc error")
        mock_ledger._api.provider.endpoint_uri = "http://rpc"
        with patch("operate.utils.gnosis.Web3.is_address", return_value=True):
            with pytest.raises(RuntimeError, match="Cannot get balance"):
                get_asset_balance(mock_ledger, ZERO_ADDRESS, self.VALID_ADDRESS)


class TestGetAssetsBalances:
    """Tests for get_assets_balances."""

    def test_single_asset_single_address(self) -> None:
        """Test that a single asset/address pair returns the expected structure."""
        mock_ledger = MagicMock()
        address = "0x" + "a" * 40
        asset = "0x" + "b" * 40
        with patch(
            "operate.utils.gnosis.get_asset_balance", return_value=BigInt(100)
        ):
            result = get_assets_balances(
                ledger_api=mock_ledger,
                asset_addresses={asset},
                addresses={address},
            )
        assert address in result
        assert result[address][asset] == BigInt(100)

    def test_multiple_assets_and_addresses(self) -> None:
        """Test itertools.product across multiple assets and addresses."""
        mock_ledger = MagicMock()
        addresses = {"0x" + "a" * 40, "0x" + "b" * 40}
        assets = {"0x" + "c" * 40, "0x" + "d" * 40}
        with patch(
            "operate.utils.gnosis.get_asset_balance", return_value=BigInt(50)
        ):
            result = get_assets_balances(
                ledger_api=mock_ledger,
                asset_addresses=assets,
                addresses=addresses,
            )
        assert len(result) == 2
        for addr in addresses:
            assert addr in result
            assert len(result[addr]) == 2


class TestGasFeesSpentInTx:
    """Tests for gas_fees_spent_in_tx."""

    def test_with_effective_gas_price(self) -> None:
        """Test gas fee calculation using EIP-1559 effectiveGasPrice."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.get_transaction_receipt.return_value = {
            "gasUsed": 21000,
            "effectiveGasPrice": 2000000000,
        }
        result = gas_fees_spent_in_tx(mock_ledger, "0xtxhash")
        assert result == 21000 * 2000000000

    def test_with_gas_price_fallback(self) -> None:
        """Test gas fee calculation falling back to legacy gasPrice."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.get_transaction_receipt.return_value = {
            "gasUsed": 21000,
            "effectiveGasPrice": 0,
            "gasPrice": 1000000000,
        }
        result = gas_fees_spent_in_tx(mock_ledger, "0xtxhash")
        assert result == 21000 * 1000000000

    def test_no_receipt_raises_chain_interaction_error(self) -> None:
        """Test that a missing receipt raises ChainInteractionError."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.get_transaction_receipt.return_value = None
        with pytest.raises(
            ChainInteractionError, match="Cannot fetch transaction receipt"
        ):
            gas_fees_spent_in_tx(mock_ledger, "0xtxhash")
