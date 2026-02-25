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

"""Unit tests for operate/services/protocol.py – no blockchain required."""

from unittest.mock import MagicMock, patch

import pytest
from autonomy.chain.config import ChainType

from operate.constants import NO_STAKING_PROGRAM_ID
from operate.operate_types import Chain
from operate.services.protocol import (
    GnosisSafeTransaction,
    MintManager,
    StakingManager,
    StakingState,
)


# ---------------------------------------------------------------------------
# StakingState enum
# ---------------------------------------------------------------------------


class TestStakingState:
    """Tests for StakingState enum values."""

    def test_unstaked_is_zero(self) -> None:
        """Test UNSTAKED has value 0."""
        assert StakingState.UNSTAKED.value == 0

    def test_staked_is_one(self) -> None:
        """Test STAKED has value 1."""
        assert StakingState.STAKED.value == 1

    def test_evicted_is_two(self) -> None:
        """Test EVICTED has value 2."""
        assert StakingState.EVICTED.value == 2

    def test_from_int(self) -> None:
        """Test StakingState can be constructed from its integer value."""
        assert StakingState(0) == StakingState.UNSTAKED
        assert StakingState(1) == StakingState.STAKED
        assert StakingState(2) == StakingState.EVICTED


# ---------------------------------------------------------------------------
# GnosisSafeTransaction
# ---------------------------------------------------------------------------


class TestGnosisSafeTransaction:
    """Tests for GnosisSafeTransaction (lines 106-195)."""

    def _make_safe_tx(self) -> GnosisSafeTransaction:
        """Create a minimal GnosisSafeTransaction with all deps mocked."""
        return GnosisSafeTransaction(
            ledger_api=MagicMock(),
            crypto=MagicMock(),
            chain_type=ChainType.GNOSIS,
            safe="0x" + "b" * 40,
        )

    def test_init_stores_all_attributes(self) -> None:
        """Test __init__ stores ledger_api, crypto, chain_type, safe, and empty _txs."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        safe_addr = "0x" + "b" * 40

        tx = GnosisSafeTransaction(
            ledger_api=mock_ledger,
            crypto=mock_crypto,
            chain_type=ChainType.GNOSIS,
            safe=safe_addr,
        )

        assert tx.ledger_api is mock_ledger
        assert tx.crypto is mock_crypto
        assert tx.chain_type == ChainType.GNOSIS
        assert tx.safe == safe_addr
        assert tx._txs == []

    def test_add_appends_tx_and_returns_self(self) -> None:
        """Test add() appends the tx dict to _txs and returns self for chaining."""
        safe_tx = self._make_safe_tx()
        tx_dict = {"to": "0xRecipient", "value": 0}

        result = safe_tx.add(tx_dict)

        assert result is safe_tx
        assert safe_tx._txs == [tx_dict]

    def test_add_multiple_txs(self) -> None:
        """Test add() can be called multiple times to accumulate transactions."""
        safe_tx = self._make_safe_tx()
        tx1 = {"to": "0xA", "value": 0}
        tx2 = {"to": "0xB", "value": 1}

        safe_tx.add(tx1).add(tx2)

        assert safe_tx._txs == [tx1, tx2]

    def test_build_calls_registry_contracts(self) -> None:
        """Test build() calls multisend and gnosis_safe contract methods."""
        mock_ledger = MagicMock()
        mock_crypto = MagicMock()
        mock_ledger.api.to_checksum_address.return_value = "0x" + "a" * 40
        mock_ledger.api.eth.get_transaction_count.return_value = 0

        safe_tx = GnosisSafeTransaction(
            ledger_api=mock_ledger,
            crypto=mock_crypto,
            chain_type=ChainType.GNOSIS,
            safe="0x" + "b" * 40,
        )

        multisend_addr = "0x" + "c" * 40
        safe_tx_hash_hex = "0x" + "aa" * 32  # 64 hex chars after stripping 0x

        with patch(
            "operate.services.protocol.registry_contracts"
        ) as mock_contracts, patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_config, patch(
            "operate.services.protocol.update_tx_with_gas_pricing"
        ), patch(
            "operate.services.protocol.update_tx_with_gas_estimate"
        ):
            mock_config.multisend.contracts.__getitem__.return_value = multisend_addr
            mock_contracts.multisend.get_tx_data.return_value = {
                "data": "0x" + "ab" * 16  # valid hex after 0x prefix
            }
            mock_contracts.gnosis_safe.get_raw_safe_transaction_hash.return_value = {
                "tx_hash": safe_tx_hash_hex
            }
            mock_contracts.gnosis_safe.get_raw_safe_transaction.return_value = {
                "to": multisend_addr,
                "value": 0,
                "data": b"",
            }

            result = safe_tx.build()

        mock_contracts.multisend.get_tx_data.assert_called_once()
        mock_contracts.gnosis_safe.get_raw_safe_transaction_hash.assert_called_once()
        mock_contracts.gnosis_safe.get_raw_safe_transaction.assert_called_once()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# StakingManager
# ---------------------------------------------------------------------------


class TestStakingManagerDefaultRpc:
    """Tests for StakingManager.ledger_api with no RPC (line 234)."""

    @patch("operate.services.protocol.get_default_ledger_api")
    def test_ledger_api_uses_default_when_no_rpc(
        self, mock_get_default: MagicMock
    ) -> None:
        """Test that ledger_api property calls get_default_ledger_api when rpc is None."""
        mock_ledger = MagicMock()
        mock_get_default.return_value = mock_ledger

        manager = StakingManager(chain=Chain.GNOSIS)
        result = manager.ledger_api

        mock_get_default.assert_called_once_with(Chain.GNOSIS)
        assert result is mock_ledger


class TestGetStakingContract:
    """Tests for StakingManager.get_staking_contract (lines 649-659)."""

    def test_returns_none_for_no_staking_program_id(self) -> None:
        """Test returns None when staking_program_id is the no-staking sentinel."""
        manager = StakingManager(chain=Chain.GNOSIS)
        result = manager.get_staking_contract(NO_STAKING_PROGRAM_ID)
        assert result is None

    def test_returns_none_for_none_staking_program_id(self) -> None:
        """Test returns None when staking_program_id is None."""
        manager = StakingManager(chain=Chain.GNOSIS)
        result = manager.get_staking_contract(None)
        assert result is None

    def test_returns_contract_address_for_known_program(self) -> None:
        """Test returns the contract address for a known staking program."""
        from operate.ledger.profiles import STAKING

        manager = StakingManager(chain=Chain.GNOSIS)
        # Use the first known staking program ID for Gnosis
        known_programs = STAKING.get(Chain.GNOSIS, {})
        if not known_programs:
            pytest.skip("No staking programs defined for Chain.GNOSIS")

        program_id = next(iter(known_programs))
        expected_address = known_programs[program_id]

        result = manager.get_staking_contract(program_id)
        assert result == expected_address

    def test_returns_program_id_as_fallback_for_unknown_program(self) -> None:
        """Test that an unknown program ID is returned as-is (fallback)."""
        manager = StakingManager(chain=Chain.GNOSIS)
        unknown_id = "unknown_staking_program_xyz"
        result = manager.get_staking_contract(unknown_id)
        # STAKING[chain].get(id, id) returns the id itself as fallback
        assert result == unknown_id


# ---------------------------------------------------------------------------
# MintManager.set_metadata_fields
# ---------------------------------------------------------------------------


class TestMintManagerSetMetadataFields:
    """Tests for MintManager.set_metadata_fields (lines 727-741)."""

    def _make_mint_manager(self) -> MintManager:
        """Create a bare MintManager without calling __init__."""
        return object.__new__(MintManager)  # type: ignore[return-value]

    def test_set_description_only(self) -> None:
        """Test that only description is set when other fields are None."""
        mm = self._make_mint_manager()
        result = mm.set_metadata_fields(description="My agent service")
        assert mm.metadata_description == "My agent service"
        assert mm.metadata_name is None
        assert mm.metadata_attributes is None
        assert result is mm  # returns self

    def test_set_all_fields(self) -> None:
        """Test that all three fields are set correctly."""
        mm = self._make_mint_manager()
        attrs = {"version": "1.0", "env": "prod"}
        mm.set_metadata_fields(
            name="My Agent", description="Agent desc", attributes=attrs
        )
        assert mm.metadata_name == "My Agent"
        assert mm.metadata_description == "Agent desc"
        assert mm.metadata_attributes == attrs

    def test_set_no_fields_sets_all_none(self) -> None:
        """Test that calling with no arguments sets all fields to None."""
        mm = self._make_mint_manager()
        mm.metadata_name = "old"  # type: ignore[assignment]
        mm.metadata_description = "old"  # type: ignore[assignment]
        mm.set_metadata_fields()
        assert mm.metadata_name is None
        assert mm.metadata_description is None
        assert mm.metadata_attributes is None

    def test_returns_self_for_method_chaining(self) -> None:
        """Test that set_metadata_fields returns self for chaining."""
        mm = self._make_mint_manager()
        result = mm.set_metadata_fields(description="chain test")
        assert result is mm
