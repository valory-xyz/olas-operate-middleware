"""
Tests for custom RPC support in protocol operations.

These tests verify that custom RPC endpoints from service chain configurations
are properly used in protocol/staking operations instead of defaulting to
the global RPC settings.

This is a critical bug fix to ensure users can configure custom RPC providers
(like Alchemy, Infura) for their services.
"""

from unittest.mock import MagicMock, patch

import pytest

from operate.operate_types import Chain
from operate.services.protocol import StakingManager


class TestStakingManagerCustomRPC:
    """Test that StakingManager properly uses custom RPC endpoints."""

    def test_staking_manager_accepts_custom_rpc_parameter(self) -> None:
        """Test that StakingManager constructor accepts optional rpc parameter."""
        custom_rpc = "https://custom-rpc.example.com"

        # This should not raise an error
        staking_manager = StakingManager(chain=Chain.GNOSIS, rpc=custom_rpc)

        assert staking_manager.chain == Chain.GNOSIS
        assert staking_manager._rpc == custom_rpc

    def test_staking_manager_stores_none_when_no_rpc_provided(self) -> None:
        """Test that StakingManager stores None when no RPC provided."""
        staking_manager = StakingManager(chain=Chain.GNOSIS)

        # Verify RPC is None (default behavior preserved)
        assert staking_manager._rpc is None

    @patch("operate.services.protocol.make_chain_ledger_api")
    @patch("operate.services.protocol.get_default_ledger_api")
    def test_staking_manager_uses_custom_rpc_in_ledger_api_property(
        self, mock_get_default: MagicMock, mock_make_chain: MagicMock
    ) -> None:
        """Test that ledger_api property uses custom RPC when provided."""
        custom_rpc = "https://custom-rpc.example.com"
        mock_ledger = MagicMock()
        mock_make_chain.return_value = mock_ledger

        staking_manager = StakingManager(chain=Chain.GNOSIS, rpc=custom_rpc)

        # Access the ledger_api property
        _ = staking_manager.ledger_api

        # Should call make_chain_ledger_api with custom RPC, not get_default_ledger_api
        mock_make_chain.assert_called_once_with(Chain.GNOSIS, rpc=custom_rpc)
        mock_get_default.assert_not_called()

    def test_get_staking_params_passes_rpc_to_static_method(self) -> None:
        """Test that get_staking_params instance method passes RPC to _get_staking_params."""
        custom_rpc = "https://custom-rpc.example.com"

        staking_manager = StakingManager(chain=Chain.GNOSIS, rpc=custom_rpc)

        with patch.object(
            StakingManager, "_get_staking_params", return_value={}
        ) as mock_static:
            staking_manager.get_staking_params(staking_contract="0x" + "1" * 40)

            # Verify _get_staking_params was called with RPC
            mock_static.assert_called_once_with(
                chain=Chain.GNOSIS, staking_contract="0x" + "1" * 40, rpc=custom_rpc
            )

    def test_get_staking_params_passes_none_when_no_rpc(self) -> None:
        """Test that get_staking_params passes None when no RPC provided."""
        staking_manager = StakingManager(chain=Chain.GNOSIS)

        with patch.object(
            StakingManager, "_get_staking_params", return_value={}
        ) as mock_static:
            staking_manager.get_staking_params(staking_contract="0x" + "1" * 40)

            # Verify _get_staking_params was called with None for RPC
            mock_static.assert_called_once_with(
                chain=Chain.GNOSIS, staking_contract="0x" + "1" * 40, rpc=None
            )


class TestOnChainManagerCustomRPC:
    """Test that OnChainManager properly passes custom RPC to StakingManager."""

    @patch("operate.services.protocol.StakingManager")
    def test_on_chain_manager_passes_rpc_to_staking_manager(
        self, mock_staking_manager_class: MagicMock
    ) -> None:
        """Test that OnChainManager passes custom RPC when creating StakingManager instances."""
        from autonomy.chain.config import ChainType

        from operate.services.protocol import OnChainManager

        custom_rpc = "https://custom-rpc.example.com"
        mock_staking_instance = MagicMock()
        mock_staking_instance.get_staking_params.return_value = {}
        mock_staking_manager_class.return_value = mock_staking_instance

        # Create mock wallet
        mock_wallet = MagicMock()

        # Create OnChainManager with custom RPC
        manager = OnChainManager(
            rpc=custom_rpc,
            wallet=mock_wallet,
            contracts={},
            chain_type=ChainType.GNOSIS,
        )

        # Call a method that uses StakingManager
        with patch.object(manager, "_patch"):
            manager.get_staking_params(staking_contract="0x" + "1" * 40)

        # Verify StakingManager was created with custom RPC
        mock_staking_manager_class.assert_called_with(
            chain=Chain.GNOSIS, rpc=custom_rpc
        )


@pytest.mark.integration
class TestRPCIntegrationWithFundingManager:
    """Integration test to verify funding manager uses correct RPC for staking operations."""

    def test_funding_manager_staking_operations_use_service_rpc(
        self, tmp_path: object
    ) -> None:
        """
        Test that FundingManager creates StakingManager with service's custom RPC.

        This is an integration test that verifies the full flow:
        1. Service has custom RPC in chain_configs
        2. FundingManager computes asset requirements
        3. StakingManager is created with the service's custom RPC
        """
        # This test will be implemented after the fix
        # For now, it serves as documentation of expected behavior
        pytest.skip("Integration test to be implemented after fix")
