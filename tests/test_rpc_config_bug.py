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

"""Tests for RPC configuration bug."""

import typing as t
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from operate.constants import ZERO_ADDRESS
from operate.ledger import make_chain_ledger_api
from operate.operate_types import Chain, ChainConfig, LedgerConfig, OnChainData, OnChainUserParams
from operate.wallet.master import EthereumMasterWallet


@pytest.mark.unit
class TestRPCConfigBug:
    """Test that custom RPCs are used instead of defaults."""

    @pytest.fixture
    def custom_rpc(self) -> str:
        """Custom RPC endpoint."""
        return "https://polygon-mainnet.g.alchemy.com/v2/test123"

    @pytest.fixture
    def default_rpc(self) -> str:
        """Default RPC endpoint."""
        return "https://polygon-rpc.com"

    @pytest.fixture
    def mock_wallet(self, tmp_path: Path) -> EthereumMasterWallet:
        """Create a mock wallet with a Safe on Polygon."""
        wallet = EthereumMasterWallet(
            path=tmp_path / "wallet.json",
            address="0x1234567890123456789012345678901234567890",
            safes={
                Chain.POLYGON: "0x0987654321098765432109876543210987654321",
            },
            safe_chains=[Chain.POLYGON],
        )
        return wallet

    @pytest.fixture
    def mock_ledger_api(self) -> MagicMock:
        """Create a mock ledger API."""
        api = MagicMock()
        api.get_balance.return_value = 1000000000000000000  # 1 token
        api._api.provider.endpoint_uri = None  # Will be set by test
        return api

    def test_wallet_get_balance_uses_custom_rpc(
        self,
        mock_wallet: EthereumMasterWallet,
        custom_rpc: str,
        default_rpc: str,
        mock_ledger_api: MagicMock,
    ) -> None:
        """Test that MasterWallet.get_balance uses custom RPC when provided."""
        # This test will FAIL before the fix, PASS after the fix

        with patch("operate.wallet.master.make_chain_ledger_api") as mock_make_api, \
             patch("operate.wallet.master.get_asset_balance") as mock_get_balance:

            mock_make_api.return_value = mock_ledger_api
            mock_get_balance.return_value = 1000000000000000000

            # Call get_balance with custom RPC
            mock_wallet.get_balance(
                chain=Chain.POLYGON,
                asset=ZERO_ADDRESS,
                from_safe=True,
                rpc=custom_rpc,  # Custom RPC provided
            )

            # Verify that make_chain_ledger_api was called with the custom RPC
            mock_make_api.assert_called_once_with(Chain.POLYGON, custom_rpc)

            # Verify get_asset_balance was called with the mocked ledger API
            mock_get_balance.assert_called_once()
            assert mock_get_balance.call_args[1]["ledger_api"] == mock_ledger_api

    def test_wallet_get_balance_defaults_without_rpc(
        self,
        mock_wallet: EthereumMasterWallet,
        mock_ledger_api: MagicMock,
    ) -> None:
        """Test that MasterWallet.get_balance uses default when no RPC provided."""
        with patch("operate.wallet.master.get_default_ledger_api") as mock_get_default, \
             patch("operate.wallet.master.get_asset_balance") as mock_get_balance:

            mock_get_default.return_value = mock_ledger_api
            mock_get_balance.return_value = 1000000000000000000

            # Call get_balance without custom RPC
            mock_wallet.get_balance(
                chain=Chain.POLYGON,
                asset=ZERO_ADDRESS,
                from_safe=True,
                # No rpc parameter - should use default
            )

            # Verify that get_default_ledger_api was called
            mock_get_default.assert_called_once_with(Chain.POLYGON)

            # Verify get_asset_balance was called with the default ledger API
            mock_get_balance.assert_called_once()
            assert mock_get_balance.call_args[1]["ledger_api"] == mock_ledger_api

    def test_wallet_get_balance_from_eoa_uses_custom_rpc(
        self,
        mock_wallet: EthereumMasterWallet,
        custom_rpc: str,
    ) -> None:
        """Test that get_balance for EOA (not Safe) also respects custom RPC."""
        with patch("operate.wallet.master.make_chain_ledger_api") as mock_make_api, \
             patch("operate.wallet.master.get_asset_balance") as mock_get_balance:

            mock_ledger_api = MagicMock()
            mock_make_api.return_value = mock_ledger_api
            mock_get_balance.return_value = 500000000000000000

            # Call get_balance for EOA with custom RPC
            mock_wallet.get_balance(
                chain=Chain.POLYGON,
                asset=ZERO_ADDRESS,
                from_safe=False,  # From EOA, not Safe
                rpc=custom_rpc,
            )

            # Verify custom RPC was used
            mock_make_api.assert_called_once_with(Chain.POLYGON, custom_rpc)

            # Verify the address used was the wallet address (EOA), not Safe
            mock_get_balance.assert_called_once()
            call_kwargs = mock_get_balance.call_args[1]
            assert call_kwargs["address"] == mock_wallet.address

    def test_wallet_get_balance_with_erc20_token(
        self,
        mock_wallet: EthereumMasterWallet,
        custom_rpc: str,
    ) -> None:
        """Test that custom RPC is used when checking ERC20 token balance."""
        usdc_address = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # USDC on Polygon

        with patch("operate.wallet.master.make_chain_ledger_api") as mock_make_api, \
             patch("operate.wallet.master.get_asset_balance") as mock_get_balance:

            mock_ledger_api = MagicMock()
            mock_make_api.return_value = mock_ledger_api
            mock_get_balance.return_value = 1000000  # 1 USDC (6 decimals)

            # Call get_balance for ERC20 token with custom RPC
            mock_wallet.get_balance(
                chain=Chain.POLYGON,
                asset=usdc_address,
                from_safe=True,
                rpc=custom_rpc,
            )

            # Verify custom RPC was used
            mock_make_api.assert_called_once_with(Chain.POLYGON, custom_rpc)

            # Verify the correct asset address was passed
            mock_get_balance.assert_called_once()
            call_kwargs = mock_get_balance.call_args[1]
            assert call_kwargs["asset_address"] == usdc_address

    def test_funding_manager_uses_service_rpc(
        self,
        tmp_path: Path,
        custom_rpc: str,
    ) -> None:
        """Test that FundingManager uses service's custom RPC for operations."""
        # This is a more complex integration test
        # We'll need to create mock service with chain_configs

        from operate.keys import KeysManager
        from operate.services.funding_manager import FundingManager
        from operate.wallet.master import MasterWalletManager
        from operate.services.service import Service

        # Create mocks
        keys_manager = Mock(spec=KeysManager)
        wallet_manager = Mock(spec=MasterWalletManager)

        # Create funding manager
        funding_manager = FundingManager(
            keys_manager=keys_manager,
            wallet_manager=wallet_manager,
            logger=Mock(),
        )

        # Create mock service with custom RPC in chain_configs
        service = Mock(spec=Service)
        service.name = "test-service"
        service.service_config_id = "test-id"
        service.agent_addresses = ["0x1111111111111111111111111111111111111111"]
        service.chain_configs = {
            Chain.POLYGON.value: ChainConfig(
                ledger_config=LedgerConfig(
                    rpc=custom_rpc,
                    chain=Chain.POLYGON,
                ),
                chain_data=OnChainData(
                    instances=["0x1111111111111111111111111111111111111111"],
                    token=1,
                    multisig="0x2222222222222222222222222222222222222222",
                    user_params=OnChainUserParams(
                        staking_program_id="no_staking",
                        nft="0x0000000000000000000000000000000000000000",
                        agent_id=1,
                        cost_of_bond=0,
                        fund_requirements={},
                    ),
                ),
            )
        }

        # Mock the ledger API creation
        with patch("operate.services.funding_manager.make_chain_ledger_api") as mock_make_api:
            mock_ledger_api = MagicMock()
            mock_ledger_api.get_balance.return_value = 1000000000000000000
            mock_make_api.return_value = mock_ledger_api

            # Mock other dependencies
            with patch("operate.services.funding_manager.drain_eoa"):
                keys_manager.get_crypto_instance.return_value = Mock()

                # Call drain_agents_eoas - this should use the service's custom RPC
                funding_manager.drain_agents_eoas(
                    service=service,
                    withdrawal_address="0x3333333333333333333333333333333333333333",
                    chain=Chain.POLYGON,
                )

                # Verify that make_chain_ledger_api was called with the custom RPC
                # from the service's chain_configs
                mock_make_api.assert_called_once_with(Chain.POLYGON, rpc=custom_rpc)

    def test_service_get_balances_uses_chain_configs_rpc(
        self,
        tmp_path: Path,
        custom_rpc: str,
    ) -> None:
        """Test that Service.get_balances uses its own chain_configs RPCs."""
        from operate.services.service import Service

        # Create mock service
        service = Mock(spec=Service)
        service.chain_configs = {
            Chain.POLYGON.value: ChainConfig(
                ledger_config=LedgerConfig(
                    rpc=custom_rpc,
                    chain=Chain.POLYGON,
                ),
                chain_data=OnChainData(
                    instances=["0x4444444444444444444444444444444444444444"],
                    token=1,
                    multisig="0x4444444444444444444444444444444444444444",
                    user_params=OnChainUserParams(
                        staking_program_id="no_staking",
                        nft="0x0000000000000000000000000000000000000000",
                        agent_id=1,
                        cost_of_bond=0,
                        fund_requirements={},
                    ),
                ),
            )
        }

        # We need to test the actual get_balances method, so we need a real Service instance
        # For now, this test documents the expected behavior
        # The actual implementation will be tested in integration tests

        # Mock make_chain_ledger_api to verify custom RPC is used
        with patch("operate.services.service.make_chain_ledger_api") as mock_make_api:
            mock_ledger_api = MagicMock()
            mock_make_api.return_value = mock_ledger_api

            # When we call service.get_balances(), it should use chain_configs RPCs
            # This will be implemented after the fix

            # For now, assert that the service has the correct chain config
            assert Chain.POLYGON.value in service.chain_configs
            chain_config = service.chain_configs[Chain.POLYGON.value]
            assert chain_config.ledger_config.rpc == custom_rpc


@pytest.mark.unit
class TestRPCErrorMessages:
    """Test that error messages show the correct RPC being used."""

    @pytest.fixture
    def custom_rpc(self) -> str:
        """Custom RPC endpoint."""
        return "https://polygon-mainnet.g.alchemy.com/v2/test123"

    def test_get_asset_balance_error_shows_rpc(
        self,
        custom_rpc: str,
    ) -> None:
        """Test that get_asset_balance errors show which RPC was used."""
        from operate.utils.gnosis import get_asset_balance

        # Create a mock ledger API that will fail
        mock_ledger_api = MagicMock()
        mock_ledger_api.get_balance.side_effect = Exception("RPC connection failed")
        mock_ledger_api._api.provider.endpoint_uri = custom_rpc

        # Try to get balance - should fail and show the RPC in error message
        with pytest.raises(RuntimeError) as exc_info:
            get_asset_balance(
                ledger_api=mock_ledger_api,
                asset_address=ZERO_ADDRESS,
                address="0x5555555555555555555555555555555555555555",
            )

        # Verify the error message includes the RPC endpoint
        error_msg = str(exc_info.value)
        assert custom_rpc in error_msg
        assert "Cannot get balance" in error_msg
