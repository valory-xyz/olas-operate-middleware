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

import typing as t
from unittest.mock import MagicMock, patch

import pytest
from autonomy.chain.exceptions import ChainInteractionError

from operate.constants import ZERO_ADDRESS
from operate.operate_types import Chain
from operate.serialization import BigInt
from operate.utils.gnosis import (
    MultiSendOperation,
    SENTINEL_OWNERS,
    SafeOperation,
    _get_nonce,
    add_owner,
    create_safe,
    drain_eoa,
    estimate_transfer_tx_fee,
    gas_fees_spent_in_tx,
    get_asset_balance,
    get_assets_balances,
    get_owners,
    get_prev_owner,
    hash_payload_to_hex,
    remove_owner,
    send_safe_txs,
    skill_input_hex_to_payload,
    swap_owner,
    transfer,
    transfer_erc20_from_safe,
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
            result = get_asset_balance(mock_ledger, ZERO_ADDRESS, self.VALID_ADDRESS)
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
            result = get_asset_balance(mock_ledger, token_address, self.VALID_ADDRESS)
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
        with patch("operate.utils.gnosis.get_asset_balance", return_value=BigInt(100)):
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
        with patch("operate.utils.gnosis.get_asset_balance", return_value=BigInt(50)):
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


class TestGetOwners:
    """Tests for get_owners."""

    def test_returns_owners_list(self) -> None:
        """Test that get_owners returns the list from the contract."""
        mock_ledger = MagicMock()
        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts:
            mock_contracts.gnosis_safe.get_owners.return_value = {
                "owners": ["0xOwnerA", "0xOwnerB"]
            }
            result = get_owners(mock_ledger, "0xSafe")
        assert result == ["0xOwnerA", "0xOwnerB"]
        mock_contracts.gnosis_safe.get_owners.assert_called_once_with(
            ledger_api=mock_ledger,
            contract_address="0xSafe",
        )

    def test_returns_empty_list_when_no_owners_key(self) -> None:
        """Test that get_owners returns [] when 'owners' key is absent."""
        mock_ledger = MagicMock()
        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts:
            mock_contracts.gnosis_safe.get_owners.return_value = {}
            result = get_owners(mock_ledger, "0xSafe")
        assert result == []


class TestCreateSafe:
    """Tests for create_safe."""

    def test_creates_safe_and_returns_address_nonce_and_tx_hash(self) -> None:
        """Test that create_safe returns (safe_address, salt_nonce, tx_hash)."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"

        mock_txsettler_cls = MagicMock()
        settler = (
            mock_txsettler_cls.return_value.transact.return_value.settle.return_value
        )
        settler.tx_hash = "0xtxhash"
        settler.get_events.return_value = [{"args": {"proxy": "0xNewSafe"}}]

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ):
            safe_address, salt_nonce, tx_hash = create_safe(
                mock_ledger, mock_crypto, salt_nonce=12345
            )

        assert safe_address == "0xNewSafe"
        assert salt_nonce == 12345
        assert tx_hash == "0xtxhash"

    def test_creates_safe_generates_nonce_when_not_provided(self) -> None:
        """Test that create_safe auto-generates a salt_nonce when none is given."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"

        mock_txsettler_cls = MagicMock()
        settler = (
            mock_txsettler_cls.return_value.transact.return_value.settle.return_value
        )
        settler.tx_hash = "0xtxhash"
        settler.get_events.return_value = [{"args": {"proxy": "0xNewSafe"}}]

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ), patch("operate.utils.gnosis._get_nonce", return_value=99999):
            safe_address, salt_nonce, tx_hash = create_safe(mock_ledger, mock_crypto)

        assert salt_nonce == 99999
        assert safe_address == "0xNewSafe"
        assert tx_hash == "0xtxhash"


class TestSendSafeTxs:
    """Tests for send_safe_txs."""

    def test_returns_tx_hash(self) -> None:
        """Test that send_safe_txs returns the transaction hash."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"
        mock_ledger.api.to_checksum_address.return_value = "0xCryptoAddress"

        mock_txsettler_cls = MagicMock()
        settler = (
            mock_txsettler_cls.return_value.transact.return_value.settle.return_value
        )
        settler.tx_hash = "0xtxhash"

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ):
            result = send_safe_txs(
                txd=b"\x00\x01\x02",
                safe="0xSafe",
                ledger_api=mock_ledger,
                crypto=mock_crypto,
            )

        assert result == "0xtxhash"

    def test_uses_custom_to_address(self) -> None:
        """Test that send_safe_txs accepts an explicit 'to' address."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"
        mock_ledger.api.to_checksum_address.return_value = "0xCryptoAddress"

        mock_txsettler_cls = MagicMock()
        settler = (
            mock_txsettler_cls.return_value.transact.return_value.settle.return_value
        )
        settler.tx_hash = "0xanotherhash"

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ):
            result = send_safe_txs(
                txd=b"\x00",
                safe="0xSafe",
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                to="0xExplicitTo",
            )

        assert result == "0xanotherhash"


class TestAddOwner:
    """Tests for add_owner."""

    def test_add_owner_calls_send_safe_txs(self) -> None:
        """Test that add_owner encodes the ABI and calls send_safe_txs."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xabcd"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs"
        ) as mock_send:
            mock_contracts.gnosis_safe.get_instance.return_value = mock_instance
            add_owner(mock_ledger, mock_crypto, "0xSafe", "0xNewOwner")

        mock_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="addOwnerWithThreshold",
            args=["0xNewOwner", 1],
        )
        mock_send.assert_called_once()

    def test_add_owner_passes_correct_txd(self) -> None:
        """Test that add_owner strips the 0x prefix before passing txd bytes."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        # 0xdeadbeef -> bytes.fromhex("deadbeef")
        mock_instance.encode_abi.return_value = "0xdeadbeef"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs"
        ) as mock_send:
            mock_contracts.gnosis_safe.get_instance.return_value = mock_instance
            add_owner(mock_ledger, mock_crypto, "0xSafe", "0xNewOwner")

        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["txd"] == bytes.fromhex("deadbeef")


class TestSwapOwner:
    """Tests for swap_owner."""

    def test_swap_owner_calls_send_safe_txs(self) -> None:
        """Test that swap_owner encodes the ABI and calls send_safe_txs."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xabcd"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs"
        ) as mock_send, patch(
            "operate.utils.gnosis.get_prev_owner", return_value=SENTINEL_OWNERS
        ):
            mock_contracts.gnosis_safe.get_instance.return_value = mock_instance
            swap_owner(
                mock_ledger,
                mock_crypto,
                "0xSafe",
                old_owner="0xOldOwner",
                new_owner="0xNewOwner",
            )

        mock_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="swapOwner",
            args=[SENTINEL_OWNERS, "0xOldOwner", "0xNewOwner"],
        )
        mock_send.assert_called_once()

    def test_swap_owner_passes_correct_txd(self) -> None:
        """Test that swap_owner strips the 0x prefix before passing txd bytes."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xcafe1234"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs"
        ) as mock_send, patch(
            "operate.utils.gnosis.get_prev_owner", return_value=SENTINEL_OWNERS
        ):
            mock_contracts.gnosis_safe.get_instance.return_value = mock_instance
            swap_owner(
                mock_ledger,
                mock_crypto,
                "0xSafe",
                old_owner="0xOldOwner",
                new_owner="0xNewOwner",
            )

        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["txd"] == bytes.fromhex("cafe1234")


class TestRemoveOwner:
    """Tests for remove_owner."""

    def test_remove_owner_calls_send_safe_txs(self) -> None:
        """Test that remove_owner encodes the ABI and calls send_safe_txs."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xabcd"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs"
        ) as mock_send, patch(
            "operate.utils.gnosis.get_prev_owner", return_value=SENTINEL_OWNERS
        ):
            mock_contracts.gnosis_safe.get_instance.return_value = mock_instance
            remove_owner(
                mock_ledger,
                mock_crypto,
                "0xSafe",
                owner="0xOwnerToRemove",
                threshold=1,
            )

        mock_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="removeOwner",
            args=[SENTINEL_OWNERS, "0xOwnerToRemove", 1],
        )
        mock_send.assert_called_once()

    def test_remove_owner_passes_correct_txd(self) -> None:
        """Test that remove_owner strips the 0x prefix before passing txd bytes."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xbeef0011"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs"
        ) as mock_send, patch(
            "operate.utils.gnosis.get_prev_owner", return_value=SENTINEL_OWNERS
        ):
            mock_contracts.gnosis_safe.get_instance.return_value = mock_instance
            remove_owner(
                mock_ledger,
                mock_crypto,
                "0xSafe",
                owner="0xOwnerToRemove",
                threshold=1,
            )

        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["txd"] == bytes.fromhex("beef0011")


class TestTransfer:
    """Tests for transfer."""

    def test_returns_tx_hash(self) -> None:
        """Test that transfer returns the transaction hash from TxSettler."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"
        mock_ledger.api.to_checksum_address.return_value = "0xCryptoAddress"

        mock_txsettler_cls = MagicMock()
        settler = (
            mock_txsettler_cls.return_value.transact.return_value.settle.return_value
        )
        settler.tx_hash = "0xtransferhash"

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ):
            result = transfer(
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                safe="0xSafe",
                to="0xRecipient",
                amount=1000,
            )

        assert result == "0xtransferhash"

    def test_amount_is_cast_to_int(self) -> None:
        """Test that a float amount is safely cast to int."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"
        mock_ledger.api.to_checksum_address.return_value = "0xCryptoAddress"

        mock_txsettler_cls = MagicMock()
        settler = (
            mock_txsettler_cls.return_value.transact.return_value.settle.return_value
        )
        settler.tx_hash = "0xhash"

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ):
            result = transfer(
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                safe="0xSafe",
                to="0xRecipient",
                amount=999.9,
            )

        assert result == "0xhash"


class TestTransferErc20FromSafe:
    """Tests for transfer_erc20_from_safe."""

    def test_returns_tx_hash(self) -> None:
        """Test that transfer_erc20_from_safe encodes ABI and calls send_safe_txs."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xabcdef"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs", return_value="0xerc20hash"
        ) as mock_send:
            mock_contracts.erc20.get_instance.return_value = mock_instance
            result = transfer_erc20_from_safe(  # nosec B106
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                safe="0xSafe",
                token="0xToken",
                to="0xRecipient",
                amount=500,
            )

        assert result == "0xerc20hash"
        mock_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="transfer",
            args=["0xRecipient", 500],
        )
        mock_send.assert_called_once()

    def test_passes_token_as_to_in_send_safe_txs(self) -> None:
        """Test that the token address is forwarded as 'to' in send_safe_txs."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xaabb"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs", return_value="0xhash"
        ) as mock_send:
            mock_contracts.erc20.get_instance.return_value = mock_instance
            transfer_erc20_from_safe(  # nosec B106
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                safe="0xSafe",
                token="0xTokenAddr",
                to="0xRecipient",
                amount=100,
            )

        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["to"] == "0xTokenAddr"

    def test_amount_is_cast_to_int(self) -> None:
        """Test that a float amount is safely cast to int."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = "0xaabb"

        with patch("operate.utils.gnosis.registry_contracts") as mock_contracts, patch(
            "operate.utils.gnosis.send_safe_txs", return_value="0xhash"
        ):
            mock_contracts.erc20.get_instance.return_value = mock_instance
            transfer_erc20_from_safe(  # nosec B106
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                safe="0xSafe",
                token="0xToken",
                to="0xRecipient",
                amount=123.7,
            )

        mock_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="transfer",
            args=["0xRecipient", 123],
        )


class TestEstimateTransferTxFee:
    """Tests for estimate_transfer_tx_fee."""

    def test_non_l2_chain_excludes_l1_fee(self) -> None:
        """Test that a non-L2 chain (Gnosis) does not add the L1 data fee."""
        mock_ledger = MagicMock()
        mock_ledger.get_transfer_transaction.return_value = {
            "gas": 21000,
            "maxFeePerGas": 1000,
        }
        mock_ledger.update_with_gas_estimate.return_value = {
            "gas": 21000,
            "maxFeePerGas": 1000,
        }
        mock_ledger.get_l1_data_fee.return_value = 5000

        with patch(
            "operate.utils.gnosis.get_default_ledger_api", return_value=mock_ledger
        ):
            fee = estimate_transfer_tx_fee(Chain.GNOSIS, "0xSender", "0xTo")

        assert fee == 21000 * 1000
        mock_ledger.get_l1_data_fee.assert_not_called()

    def test_l2_chain_includes_l1_fee(self) -> None:
        """Test that an L2 chain (Base) adds the L1 data fee on top."""
        mock_ledger = MagicMock()
        mock_ledger.get_transfer_transaction.return_value = {
            "gas": 21000,
            "maxFeePerGas": 1000,
        }
        mock_ledger.update_with_gas_estimate.return_value = {
            "gas": 21000,
            "maxFeePerGas": 1000,
        }
        mock_ledger.get_l1_data_fee.return_value = 5000

        with patch(
            "operate.utils.gnosis.get_default_ledger_api", return_value=mock_ledger
        ):
            fee = estimate_transfer_tx_fee(Chain.BASE, "0xSender", "0xTo")

        assert fee == 21000 * 1000 + 5000
        mock_ledger.get_l1_data_fee.assert_called_once()

    def test_optimism_chain_includes_l1_fee(self) -> None:
        """Test that Optimism chain also adds the L1 data fee."""
        mock_ledger = MagicMock()
        mock_ledger.get_transfer_transaction.return_value = {
            "gas": 50000,
            "maxFeePerGas": 2000,
        }
        mock_ledger.update_with_gas_estimate.return_value = {
            "gas": 50000,
            "maxFeePerGas": 2000,
        }
        mock_ledger.get_l1_data_fee.return_value = 9999

        with patch(
            "operate.utils.gnosis.get_default_ledger_api", return_value=mock_ledger
        ):
            fee = estimate_transfer_tx_fee(Chain.OPTIMISM, "0xSender", "0xTo")

        assert fee == 50000 * 2000 + 9999

    def test_mode_chain_includes_l1_fee(self) -> None:
        """Test that Mode chain also adds the L1 data fee."""
        mock_ledger = MagicMock()
        mock_ledger.get_transfer_transaction.return_value = {
            "gas": 21000,
            "maxFeePerGas": 500,
        }
        mock_ledger.update_with_gas_estimate.return_value = {
            "gas": 21000,
            "maxFeePerGas": 500,
        }
        mock_ledger.get_l1_data_fee.return_value = 1000

        with patch(
            "operate.utils.gnosis.get_default_ledger_api", return_value=mock_ledger
        ):
            fee = estimate_transfer_tx_fee(Chain.MODE, "0xSender", "0xTo")

        assert fee == 21000 * 500 + 1000


class TestDrainEoa:
    """Tests for drain_eoa."""

    def test_success_returns_tx_hash(self) -> None:
        """Test that drain_eoa returns the tx_hash on a successful drain."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()

        mock_txsettler_cls = MagicMock()
        settler = (
            mock_txsettler_cls.return_value.transact.return_value.settle.return_value
        )
        settler.tx_hash = "0xdrainhash"

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id", return_value=Chain.GNOSIS
        ):
            result = drain_eoa(
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                withdrawal_address="0xWithdrawal",
                chain_id=100,
            )

        assert result == "0xdrainhash"

    def test_no_balance_returns_none(self) -> None:
        """Test that drain_eoa returns None when wallet has no balance to drain."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xWalletAddr"

        mock_txsettler_cls = MagicMock()
        mock_txsettler_cls.return_value.transact.side_effect = ChainInteractionError(
            "No balance to drain from wallet: 0xWalletAddr"
        )

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id", return_value=Chain.GNOSIS
        ):
            result = drain_eoa(
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                withdrawal_address="0xWithdrawal",
                chain_id=100,
            )

        assert result is None

    def test_other_chain_interaction_error_reraises(self) -> None:
        """Test that drain_eoa re-raises ChainInteractionError for non-balance errors."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xWalletAddr"

        mock_txsettler_cls = MagicMock()
        mock_txsettler_cls.return_value.transact.side_effect = ChainInteractionError(
            "Network error"
        )

        with patch("operate.utils.gnosis.TxSettler", mock_txsettler_cls), patch(
            "operate.utils.gnosis.Chain.from_id", return_value=Chain.GNOSIS
        ):
            with pytest.raises(ChainInteractionError, match="Network error"):
                drain_eoa(
                    ledger_api=mock_ledger,
                    crypto=mock_crypto,
                    withdrawal_address="0xWithdrawal",
                    chain_id=100,
                )


# ---------------------------------------------------------------------------
# Helper: a fake TxSettler class that actually calls tx_builder during transact()
# This is used by the "closure coverage" tests below.
# ---------------------------------------------------------------------------


def _calling_txsettler_cls(
    tx_hash: str = "0xhash",
    events: t.Optional[t.List] = None,
) -> t.Type:
    """Return a fake TxSettler class that invokes tx_builder() inside transact().

    Using a real TxSettler requires a live blockchain; this fake drives the
    inner _build / _build_tx closures without any network access.
    """
    _events = events if events is not None else []

    class _Fake:
        def __init__(self, *, tx_builder: t.Callable, **_kwargs: t.Any) -> None:
            self._tx_builder = tx_builder
            self.tx_hash = tx_hash

        def transact(self) -> "_Fake":
            self._tx_builder()
            return self

        def settle(self) -> "_Fake":
            return self

        def get_events(self, **_kwargs: t.Any) -> t.List:
            return _events

    return _Fake


# ---------------------------------------------------------------------------
# Inner-closure coverage: create_safe._build (lines 172-180)
# ---------------------------------------------------------------------------


class TestCreateSafeBuildClosure:
    """Test the _build() closure inside create_safe (lines 172-180)."""

    def test_build_closure_calls_get_deploy_transaction(self) -> None:
        """Test _build() invokes gnosis_safe.get_deploy_transaction and strips contract_address."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"

        fake_settler_cls = _calling_txsettler_cls(
            tx_hash="0xcreatetxhash",
            events=[{"args": {"proxy": "0xNewSafe"}}],
        )

        with patch("operate.utils.gnosis.TxSettler", fake_settler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ), patch("operate.utils.gnosis.registry_contracts") as mock_contracts:
            mock_contracts.gnosis_safe.get_deploy_transaction.return_value = {
                "contract_address": "0xFactory",
                "data": "0xdeadbeef",
                "to": "0xProxy",
            }
            mock_proxy_instance = MagicMock()
            mock_contracts.gnosis_safe_proxy_factory.get_instance.return_value = (
                mock_proxy_instance
            )

            safe_addr, salt_nonce, tx_hash = create_safe(
                mock_ledger, mock_crypto, salt_nonce=42
            )

        # The _build() closure should have been called
        mock_contracts.gnosis_safe.get_deploy_transaction.assert_called_once()
        assert safe_addr == "0xNewSafe"
        assert salt_nonce == 42
        assert tx_hash == "0xcreatetxhash"


# ---------------------------------------------------------------------------
# Inner-closure coverage: send_safe_txs._build_tx (lines 232-250)
# ---------------------------------------------------------------------------


class TestSendSafeTxsBuildClosure:
    """Test the _build_tx() closure inside send_safe_txs (lines 232-250)."""

    def test_build_tx_closure_builds_and_signs_safe_tx(self) -> None:
        """Test _build_tx() hashes, signs, and assembles the safe transaction."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"
        mock_ledger.api.to_checksum_address.return_value = "0xCryptoAddress"
        mock_ledger.api.eth.get_transaction_count.return_value = 0
        # sign_message returns bytes-like; slicing [2:] on a MagicMock is safe
        mock_crypto.sign_message.return_value = MagicMock()

        fake_settler_cls = _calling_txsettler_cls(tx_hash="0xsafetxhash")

        with patch("operate.utils.gnosis.TxSettler", fake_settler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ), patch("operate.utils.gnosis.registry_contracts") as mock_contracts:
            mock_contracts.gnosis_safe.get_raw_safe_transaction_hash.return_value = {
                "tx_hash": "0x" + "ab" * 32  # 64 hex chars — valid for unhexlify
            }
            mock_contracts.gnosis_safe.get_raw_safe_transaction.return_value = {
                "data": "0xbeef"
            }

            result = send_safe_txs(
                txd=b"\x00\x01",
                safe="0xSafe",
                ledger_api=mock_ledger,
                crypto=mock_crypto,
            )

        # Both contract calls inside _build_tx must have been made
        mock_contracts.gnosis_safe.get_raw_safe_transaction_hash.assert_called_once()
        mock_contracts.gnosis_safe.get_raw_safe_transaction.assert_called_once()
        assert result == "0xsafetxhash"


# ---------------------------------------------------------------------------
# Inner-closure coverage: transfer._build_tx (lines 399-417)
# ---------------------------------------------------------------------------


class TestTransferBuildClosure:
    """Test the _build_tx() closure inside transfer (lines 399-417)."""

    def test_build_tx_closure_builds_signed_native_transfer(self) -> None:
        """Test _build_tx() hashes, signs, and assembles the native-token safe tx."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xCryptoAddress"
        mock_ledger.api.to_checksum_address.return_value = "0xCryptoAddress"
        mock_ledger.api.eth.get_transaction_count.return_value = 1

        fake_settler_cls = _calling_txsettler_cls(tx_hash="0xtransferhash2")

        with patch("operate.utils.gnosis.TxSettler", fake_settler_cls), patch(
            "operate.utils.gnosis.Chain.from_id"
        ), patch("operate.utils.gnosis.registry_contracts") as mock_contracts:
            mock_contracts.gnosis_safe.get_raw_safe_transaction_hash.return_value = {
                "tx_hash": "0x" + "cd" * 32
            }
            mock_contracts.gnosis_safe.get_raw_safe_transaction.return_value = {
                "data": "0xcafe"
            }

            result = transfer(
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                safe="0xSafe",
                to="0xRecipient",
                amount=500,
            )

        mock_contracts.gnosis_safe.get_raw_safe_transaction_hash.assert_called_once()
        mock_contracts.gnosis_safe.get_raw_safe_transaction.assert_called_once()
        assert result == "0xtransferhash2"


# ---------------------------------------------------------------------------
# Inner-closure coverage: drain_eoa._build_tx (lines 532-565)
# ---------------------------------------------------------------------------


class TestDrainEoaBuildClosure:
    """Test the _build_tx() closure inside drain_eoa (lines 532-565)."""

    def test_build_tx_closure_zero_balance_returns_none(self) -> None:
        """Test _build_tx raises when balance <= fee, causing drain_eoa to return None."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xWalletAddr"
        # get_balance returns less than the fee → amount <= 0 → exception → None
        mock_ledger.get_balance.return_value = 0

        fake_settler_cls = _calling_txsettler_cls()

        with patch("operate.utils.gnosis.TxSettler", fake_settler_cls), patch(
            "operate.utils.gnosis.Chain.from_id", return_value=Chain.GNOSIS
        ), patch("operate.utils.gnosis.estimate_transfer_tx_fee", return_value=100):
            result = drain_eoa(
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                withdrawal_address="0xWithdrawal",
                chain_id=100,
            )

        assert result is None

    def test_build_tx_closure_positive_balance_success(self) -> None:
        """Test _build_tx builds the drain transaction when balance exceeds fee."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_crypto.address = "0xWalletAddr"
        mock_ledger.get_balance.return_value = 10_000
        mock_ledger.get_transfer_transaction.return_value = {
            "gas": 21000,
            "maxFeePerGas": 1000,
            "value": 9_900,
        }
        mock_ledger.update_with_gas_estimate.return_value = {
            "gas": 25000,
            "maxFeePerGas": 1000,
        }

        fake_settler_cls = _calling_txsettler_cls(tx_hash="0xdrainsuccess")

        with patch("operate.utils.gnosis.TxSettler", fake_settler_cls), patch(
            "operate.utils.gnosis.Chain.from_id", return_value=Chain.GNOSIS
        ), patch("operate.utils.gnosis.estimate_transfer_tx_fee", return_value=100):
            result = drain_eoa(
                ledger_api=mock_ledger,
                crypto=mock_crypto,
                withdrawal_address="0xWithdrawal",
                chain_id=100,
            )

        assert result == "0xdrainsuccess"
        mock_ledger.get_transfer_transaction.assert_called_once()
        mock_ledger.update_with_gas_estimate.assert_called_once()
