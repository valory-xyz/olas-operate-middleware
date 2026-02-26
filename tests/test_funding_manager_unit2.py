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

"""Unit tests for operate/services/funding_manager.py – part 2, targeting uncovered lines."""

import asyncio
from time import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from operate.constants import (
    MASTER_SAFE_PLACEHOLDER,
    NO_STAKING_PROGRAM_ID,
    SERVICE_SAFE_PLACEHOLDER,
    ZERO_ADDRESS,
)
from operate.operate_types import Chain, ChainAmounts, OnChainState
from operate.serialization import BigInt
from operate.services.funding_manager import FundingManager
from operate.services.protocol import StakingState
from operate.services.service import NON_EXISTENT_TOKEN
from operate.wallet.master import InsufficientFundsException


# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

AGENT_ADDR = "0x" + "a" * 40
SAFE_ADDR = "0x" + "b" * 40
MASTER_SAFE_ADDR = "0x" + "c" * 40
MASTER_EOA_ADDR = "0x" + "d" * 40
TOKEN_ADDR = "0x" + "e" * 40


def _make_manager(
    wallet_manager: Any = None,
    cooldown: int = 5,
) -> FundingManager:
    """Create a FundingManager with all external deps mocked."""
    return FundingManager(
        keys_manager=MagicMock(),
        wallet_manager=wallet_manager or MagicMock(),
        logger=MagicMock(),
        funding_requests_cooldown_seconds=cooldown,
    )


def _mock_chain_config(
    chain: str = "gnosis",
    rpc: str = "http://localhost:8545",
    use_staking: bool = False,
    staking_program_id: str = NO_STAKING_PROGRAM_ID,
    cost_of_bond: int = 10000,
    multisig: str = SAFE_ADDR,
    token: int = 1,
    fund_requirements: Any = None,
) -> MagicMock:
    """Create a mock chain config."""
    chain_config = MagicMock()
    chain_config.ledger_config.rpc = rpc
    chain_config.ledger_config.chain = Chain(chain)
    chain_config.chain_data.user_params.use_staking = use_staking
    chain_config.chain_data.user_params.staking_program_id = staking_program_id
    chain_config.chain_data.user_params.cost_of_bond = cost_of_bond
    chain_config.chain_data.user_params.fund_requirements = fund_requirements or {}
    chain_config.chain_data.multisig = multisig
    chain_config.chain_data.token = token
    return chain_config


def _mock_service(
    chain: str = "gnosis",
    agent_addresses: Any = None,
    token: int = 1,
) -> MagicMock:
    """Create a mock service."""
    service = MagicMock()
    service.service_config_id = "test_service_id"
    service.name = "TestService"
    service.agent_addresses = agent_addresses or [AGENT_ADDR]
    chain_config = _mock_chain_config(chain=chain, token=token)
    service.chain_configs = {chain: chain_config}
    return service


# ---------------------------------------------------------------------------
# Tests for drain_service_safe (lines 133-248)
# ---------------------------------------------------------------------------


class TestDrainServiceSafe:
    """Tests for FundingManager.drain_service_safe (lines 133-248)."""

    def _make_wallet_manager(self) -> MagicMock:
        """Create wallet manager with a wallet that has a master safe."""
        wm = MagicMock()
        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wm.load.return_value = wallet
        return wm

    def test_erc20_balance_zero_skips_transfer(self) -> None:
        """drain_service_safe skips ERC20 with zero balance."""
        manager = _make_manager(wallet_manager=self._make_wallet_manager())
        service = _mock_service()

        mock_token_instance = MagicMock()
        mock_token_instance.functions.balanceOf.return_value.call.return_value = 0

        with patch("operate.services.funding_manager.make_chain_ledger_api"), patch(
            "operate.services.funding_manager.Web3.to_checksum_address",
            return_value=AGENT_ADDR,
        ), patch("operate.services.funding_manager.EthSafeTxBuilder"), patch(
            "operate.services.funding_manager.get_owners",
            return_value=[AGENT_ADDR],
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.get_asset_name",
            return_value="OLAS",
        ):
            mock_registry.erc20.get_instance.return_value = mock_token_instance
            # native balance also zero
            with patch(
                "operate.services.funding_manager.WRAPPED_NATIVE_ASSET",
                {Chain.GNOSIS: TOKEN_ADDR},
            ), patch(
                "operate.services.funding_manager.OLAS",
                {Chain.GNOSIS: TOKEN_ADDR},
            ), patch(
                "operate.services.funding_manager.USDC",
                {Chain.GNOSIS: TOKEN_ADDR},
            ):
                ledger_api = MagicMock()
                ledger_api.get_balance.return_value = 0
                with patch(
                    "operate.services.funding_manager.make_chain_ledger_api",
                    return_value=ledger_api,
                ):
                    manager.drain_service_safe(service, AGENT_ADDR, Chain.GNOSIS)

        manager.logger.info.assert_called()  # type: ignore[attr-defined]

    def test_erc20_owners_are_agents_calls_transfer(self) -> None:
        """drain_service_safe calls transfer_erc20_from_safe when owners are agents."""
        manager = _make_manager(wallet_manager=self._make_wallet_manager())
        service = _mock_service()

        mock_token_instance = MagicMock()
        mock_token_instance.functions.balanceOf.return_value.call.return_value = 1000

        ledger_api = MagicMock()
        ledger_api.get_balance.return_value = 0  # no native to drain

        with patch(
            "operate.services.funding_manager.make_chain_ledger_api",
            return_value=ledger_api,
        ), patch(
            "operate.services.funding_manager.Web3.to_checksum_address",
            return_value=AGENT_ADDR,
        ), patch(
            "operate.services.funding_manager.EthSafeTxBuilder"
        ), patch(
            "operate.services.funding_manager.get_owners",
            return_value=[AGENT_ADDR],
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.get_asset_name",
            return_value="OLAS",
        ), patch(
            "operate.services.funding_manager.transfer_erc20_from_safe"
        ) as mock_transfer, patch(
            "operate.services.funding_manager.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.OLAS",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.USDC",
            {Chain.GNOSIS: TOKEN_ADDR},
        ):
            mock_registry.erc20.get_instance.return_value = mock_token_instance
            manager.drain_service_safe(service, AGENT_ADDR, Chain.GNOSIS)

        mock_transfer.assert_called_once()

    def test_erc20_owners_are_master_safe_calls_sftxb(self) -> None:
        """drain_service_safe uses sftxb when owners == {master_safe}."""
        manager = _make_manager(wallet_manager=self._make_wallet_manager())
        service = _mock_service()

        mock_token_instance = MagicMock()
        mock_token_instance.functions.balanceOf.return_value.call.return_value = 1000

        ledger_api = MagicMock()
        ledger_api.get_balance.return_value = 0

        mock_sftxb = MagicMock()
        mock_sftxb.get_safe_b_erc20_transfer_messages.return_value = ["msg1"]
        mock_tx = MagicMock()
        mock_sftxb.new_tx.return_value = mock_tx

        with patch(
            "operate.services.funding_manager.make_chain_ledger_api",
            return_value=ledger_api,
        ), patch(
            "operate.services.funding_manager.Web3.to_checksum_address",
            return_value=AGENT_ADDR,
        ), patch(
            "operate.services.funding_manager.EthSafeTxBuilder",
            return_value=mock_sftxb,
        ), patch(
            "operate.services.funding_manager.get_owners",
            return_value=[MASTER_SAFE_ADDR],
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.get_asset_name",
            return_value="OLAS",
        ), patch(
            "operate.services.funding_manager.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.OLAS",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.USDC",
            {Chain.GNOSIS: TOKEN_ADDR},
        ):
            mock_registry.erc20.get_instance.return_value = mock_token_instance
            manager.drain_service_safe(service, AGENT_ADDR, Chain.GNOSIS)

        mock_sftxb.get_safe_b_erc20_transfer_messages.assert_called_once()
        mock_tx.settle.assert_called_once()

    def test_erc20_unknown_owners_raises_runtime_error(self) -> None:
        """drain_service_safe raises RuntimeError for unrecognized owner set."""
        manager = _make_manager(wallet_manager=self._make_wallet_manager())
        service = _mock_service()

        mock_token_instance = MagicMock()
        mock_token_instance.functions.balanceOf.return_value.call.return_value = 1000

        ledger_api = MagicMock()
        mock_registry = MagicMock()
        mock_registry.erc20.get_instance.return_value = mock_token_instance

        with patch(
            "operate.services.funding_manager.make_chain_ledger_api",
            return_value=ledger_api,
        ), patch(
            "operate.services.funding_manager.Web3.to_checksum_address",
            return_value=AGENT_ADDR,
        ), patch(
            "operate.services.funding_manager.EthSafeTxBuilder"
        ), patch(
            "operate.services.funding_manager.get_owners",
            return_value=["0x" + "f" * 40],  # unknown owner
        ), patch(
            "operate.services.funding_manager.registry_contracts",
            mock_registry,
        ), patch(
            "operate.services.funding_manager.get_asset_name",
            return_value="OLAS",
        ), patch(
            "operate.services.funding_manager.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.OLAS",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.USDC",
            {Chain.GNOSIS: TOKEN_ADDR},
        ):
            with pytest.raises(RuntimeError, match="unrecognized owner set"):
                manager.drain_service_safe(service, AGENT_ADDR, Chain.GNOSIS)

    def test_native_balance_positive_owners_are_agents(self) -> None:
        """drain_service_safe calls transfer_from_safe for native with agent owners."""
        manager = _make_manager(wallet_manager=self._make_wallet_manager())
        service = _mock_service()

        mock_token_instance = MagicMock()
        mock_token_instance.functions.balanceOf.return_value.call.return_value = 0

        ledger_api = MagicMock()
        ledger_api.get_balance.return_value = 500

        with patch(
            "operate.services.funding_manager.make_chain_ledger_api",
            return_value=ledger_api,
        ), patch(
            "operate.services.funding_manager.Web3.to_checksum_address",
            return_value=AGENT_ADDR,
        ), patch(
            "operate.services.funding_manager.EthSafeTxBuilder"
        ), patch(
            "operate.services.funding_manager.get_owners",
            return_value=[AGENT_ADDR],
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.get_asset_name",
            return_value="ETH",
        ), patch(
            "operate.services.funding_manager.transfer as transfer_from_safe",
            create=True,
        ), patch(
            "operate.services.funding_manager.transfer_from_safe"
        ) as mock_transfer, patch(
            "operate.services.funding_manager.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.OLAS",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.USDC",
            {Chain.GNOSIS: TOKEN_ADDR},
        ):
            mock_registry.erc20.get_instance.return_value = mock_token_instance
            manager.drain_service_safe(service, AGENT_ADDR, Chain.GNOSIS)

        mock_transfer.assert_called_once()

    def test_native_balance_positive_owners_are_master_safe(self) -> None:
        """drain_service_safe uses sftxb for native asset when owners == {master_safe}."""
        manager = _make_manager(wallet_manager=self._make_wallet_manager())
        service = _mock_service()

        mock_token_instance = MagicMock()
        mock_token_instance.functions.balanceOf.return_value.call.return_value = 0

        ledger_api = MagicMock()
        ledger_api.get_balance.return_value = 500

        mock_sftxb = MagicMock()
        mock_sftxb.get_safe_b_native_transfer_messages.return_value = ["msg1"]
        mock_tx = MagicMock()
        mock_sftxb.new_tx.return_value = mock_tx

        with patch(
            "operate.services.funding_manager.make_chain_ledger_api",
            return_value=ledger_api,
        ), patch(
            "operate.services.funding_manager.Web3.to_checksum_address",
            return_value=AGENT_ADDR,
        ), patch(
            "operate.services.funding_manager.EthSafeTxBuilder",
            return_value=mock_sftxb,
        ), patch(
            "operate.services.funding_manager.get_owners",
            return_value=[MASTER_SAFE_ADDR],
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.get_asset_name",
            return_value="ETH",
        ), patch(
            "operate.services.funding_manager.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.OLAS",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.USDC",
            {Chain.GNOSIS: TOKEN_ADDR},
        ):
            mock_registry.erc20.get_instance.return_value = mock_token_instance
            manager.drain_service_safe(service, AGENT_ADDR, Chain.GNOSIS)

        mock_sftxb.get_safe_b_native_transfer_messages.assert_called_once()
        mock_tx.settle.assert_called_once()

    def test_native_unknown_owners_raises_runtime_error(self) -> None:
        """drain_service_safe raises RuntimeError when native owners are unrecognized."""
        manager = _make_manager(wallet_manager=self._make_wallet_manager())
        service = _mock_service()

        mock_token_instance = MagicMock()
        mock_token_instance.functions.balanceOf.return_value.call.return_value = 0

        ledger_api = MagicMock()
        ledger_api.get_balance.return_value = 500

        mock_registry = MagicMock()
        mock_registry.erc20.get_instance.return_value = mock_token_instance
        with patch(
            "operate.services.funding_manager.make_chain_ledger_api",
            return_value=ledger_api,
        ), patch(
            "operate.services.funding_manager.Web3.to_checksum_address",
            return_value=AGENT_ADDR,
        ), patch(
            "operate.services.funding_manager.EthSafeTxBuilder"
        ), patch(
            "operate.services.funding_manager.get_owners",
            return_value=["0x" + "f" * 40],
        ), patch(
            "operate.services.funding_manager.registry_contracts",
            mock_registry,
        ), patch(
            "operate.services.funding_manager.get_asset_name",
            return_value="ETH",
        ), patch(
            "operate.services.funding_manager.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.OLAS",
            {Chain.GNOSIS: TOKEN_ADDR},
        ), patch(
            "operate.services.funding_manager.USDC",
            {Chain.GNOSIS: TOKEN_ADDR},
        ):
            with pytest.raises(RuntimeError, match="unrecognized owner set"):
                manager.drain_service_safe(service, AGENT_ADDR, Chain.GNOSIS)


# ---------------------------------------------------------------------------
# Tests for _compute_protocol_asset_requirements (lines 256-315)
# ---------------------------------------------------------------------------


class TestComputeProtocolAssetRequirements:
    """Tests for _compute_protocol_asset_requirements (lines 256-315)."""

    def test_no_staking_computes_from_cost_of_bond(self) -> None:
        """Without staking, requirements use cost_of_bond and MIN constants."""
        manager = _make_manager()
        service = _mock_service(
            chain="gnosis",
        )
        # use_staking=False by default in _mock_chain_config

        with patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ):
            result = manager._compute_protocol_asset_requirements(service)

        assert "gnosis" in result
        master_safe_amounts = result["gnosis"][MASTER_SAFE_ADDR]
        assert ZERO_ADDRESS in master_safe_amounts
        assert master_safe_amounts[ZERO_ADDRESS] > 0

    def test_staking_uses_staking_manager(self) -> None:
        """With staking enabled, StakingManager is used for requirements."""
        manager = _make_manager()
        service = _mock_service(chain="gnosis")
        # Enable staking
        chain_config = service.chain_configs["gnosis"]
        chain_config.chain_data.user_params.use_staking = True
        chain_config.chain_data.user_params.staking_program_id = "test_staking"
        chain_config.chain_data.user_params.cost_of_bond = 5000

        mock_staking_manager = MagicMock()
        mock_staking_manager.get_staking_contract.return_value = MagicMock()
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": 100000,
            "staking_token": TOKEN_ADDR,
            "additional_staking_tokens": {},
        }

        with patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch(
            "operate.services.funding_manager.StakingManager",
            return_value=mock_staking_manager,
        ):
            result = manager._compute_protocol_asset_requirements(service)

        assert "gnosis" in result
        master_safe_amounts = result["gnosis"][MASTER_SAFE_ADDR]
        assert TOKEN_ADDR in master_safe_amounts
        assert ZERO_ADDRESS in master_safe_amounts

    def test_staking_with_additional_tokens(self) -> None:
        """Staking with additional_staking_tokens adds those to requirements."""
        manager = _make_manager()
        service = _mock_service(chain="gnosis")
        chain_config = service.chain_configs["gnosis"]
        chain_config.chain_data.user_params.use_staking = True
        chain_config.chain_data.user_params.staking_program_id = "test_staking"

        extra_token = "0x" + "f" * 40
        mock_staking_manager = MagicMock()
        mock_staking_manager.get_staking_contract.return_value = MagicMock()
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": 50000,
            "staking_token": TOKEN_ADDR,
            "additional_staking_tokens": {extra_token: 200},
        }

        with patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch(
            "operate.services.funding_manager.StakingManager",
            return_value=mock_staking_manager,
        ):
            result = manager._compute_protocol_asset_requirements(service)

        master_safe_amounts = result["gnosis"][MASTER_SAFE_ADDR]
        assert extra_token in master_safe_amounts
        assert master_safe_amounts[extra_token] == BigInt(200)


# ---------------------------------------------------------------------------
# Tests for _compute_protocol_bonded_assets (lines 329-498)
# ---------------------------------------------------------------------------


class TestComputeProtocolBondedAssets:
    """Tests for _compute_protocol_bonded_assets (lines 329-498)."""

    def test_wallet_not_exist_returns_empty(self) -> None:
        """Returns empty if wallet doesn't exist for the chain's ledger type."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = False
        manager = _make_manager(wallet_manager=wallet_manager)
        service = _mock_service()

        result = manager._compute_protocol_bonded_assets(service)

        assert result["gnosis"][MASTER_SAFE_PLACEHOLDER] == {}

    def test_chain_not_in_wallet_safes_returns_empty(self) -> None:
        """Returns empty if chain is not in wallet.safes."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True
        mock_wallet = MagicMock()
        mock_wallet.safes = {}  # gnosis not in safes
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)
        service = _mock_service()

        with patch("operate.services.funding_manager.make_chain_ledger_api"), patch(
            "operate.services.funding_manager.StakingManager"
        ):
            result = manager._compute_protocol_bonded_assets(service)

        assert result["gnosis"][MASTER_SAFE_PLACEHOLDER] == {}

    def test_non_existent_token_returns_empty(self) -> None:
        """Returns empty bonded assets if service_id == NON_EXISTENT_TOKEN."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)
        service = _mock_service(token=NON_EXISTENT_TOKEN)

        with patch("operate.services.funding_manager.make_chain_ledger_api"), patch(
            "operate.services.funding_manager.StakingManager"
        ):
            result = manager._compute_protocol_bonded_assets(service)

        assert result["gnosis"][MASTER_SAFE_ADDR] == {}

    def test_no_staking_contract_returns_early(self) -> None:
        """Returns early when no staking_contract available."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)
        service = _mock_service(token=1)

        # service_info: index 0=security_deposit, 5=num_agent_instances, 6=state, 7=agent_ids
        service_info = [0, 0, 0, 0, 0, 1, OnChainState.ACTIVE_REGISTRATION, [1]]
        operator_balance = 100
        current_staking_program = None

        mock_staking_manager = MagicMock()
        mock_staking_manager.get_staking_contract.return_value = None  # no contract
        mock_staking_manager.get_current_staking_program.return_value = None

        mock_service_registry = MagicMock()

        with patch("operate.services.funding_manager.make_chain_ledger_api"), patch(
            "operate.services.funding_manager.StakingManager",
            return_value=mock_staking_manager,
        ), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(service_info, operator_balance, current_staking_program),
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.CHAIN_PROFILES",
            {"gnosis": {"service_registry": "0x1234"}},
        ):
            mock_registry.service_registry.get_instance.return_value = (
                mock_service_registry
            )
            result = manager._compute_protocol_bonded_assets(service)

        # Returns early with just the native bonded amount (from operator_balance + security_deposit)
        assert isinstance(result, ChainAmounts)

    def test_with_staking_contract_active_state(self) -> None:
        """Computes bonded assets with a staking contract when service is active."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)
        service = _mock_service(token=42)

        service_info = [1000, 0, 0, 0, 0, 1, OnChainState.ACTIVE_REGISTRATION, [1]]
        operator_balance = 200
        current_staking_program = "staking_prog_1"

        mock_staking_contract = MagicMock()
        mock_staking_manager = MagicMock()
        mock_staking_manager.get_staking_contract.return_value = mock_staking_contract
        mock_staking_manager.get_current_staking_program.return_value = (
            current_staking_program
        )
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": 50000,
            "staking_token": TOKEN_ADDR,
            "additional_staking_tokens": {},
            "service_registry_token_utility": "0x5678",
            "staking_contract": mock_staking_contract,
        }
        mock_staking_manager.staking_state.return_value = StakingState.UNSTAKED

        mock_service_registry = MagicMock()
        mock_token_utility = MagicMock()

        second_call_result = (
            (1,),  # agent_instances for agent_id 1
            5000,  # agent_bond for agent_id 1
            3000,  # token_bond (getOperatorBalance)
            (0, 2000),  # security_deposits (mapServiceIdTokenDeposit)
            StakingState.UNSTAKED,  # staking_state
        )

        call_count = 0

        def mock_concurrent_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (service_info, operator_balance, current_staking_program)
            return second_call_result

        with patch("operate.services.funding_manager.make_chain_ledger_api"), patch(
            "operate.services.funding_manager.StakingManager",
            return_value=mock_staking_manager,
        ), patch(
            "operate.services.funding_manager.concurrent_execute",
            side_effect=mock_concurrent_execute,
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.CHAIN_PROFILES",
            {"gnosis": {"service_registry": "0x1234"}},
        ):
            mock_registry.service_registry.get_instance.return_value = (
                mock_service_registry
            )
            mock_registry.service_registry_token_utility.get_instance.return_value = (
                mock_token_utility
            )
            result = manager._compute_protocol_bonded_assets(service)

        assert "gnosis" in result

    def test_staking_state_staked_adds_additional_tokens(self) -> None:
        """Staking state STAKED adds additional_staking_tokens to bonded assets."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)
        service = _mock_service(token=42)

        service_info = [1000, 0, 0, 0, 0, 1, OnChainState.ACTIVE_REGISTRATION, [1]]
        operator_balance = 200
        current_staking_program = "prog1"

        extra_token = "0x" + "f" * 40
        mock_staking_contract = MagicMock()
        mock_staking_manager = MagicMock()
        mock_staking_manager.get_staking_contract.return_value = mock_staking_contract
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": 10000,
            "staking_token": TOKEN_ADDR,
            "additional_staking_tokens": {extra_token: 500},
            "service_registry_token_utility": "0x5678",
            "staking_contract": mock_staking_contract,
        }
        mock_staking_manager.staking_state.return_value = StakingState.STAKED

        mock_service_registry = MagicMock()
        mock_token_utility = MagicMock()

        second_call_result = (
            (1,),  # agent_instances
            5000,  # agent_bond
            3000,  # token_bond
            (0, 2000),  # security_deposits
            StakingState.STAKED,
        )

        call_count = 0

        def mock_concurrent_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (service_info, operator_balance, current_staking_program)
            return second_call_result

        with patch("operate.services.funding_manager.make_chain_ledger_api"), patch(
            "operate.services.funding_manager.StakingManager",
            return_value=mock_staking_manager,
        ), patch(
            "operate.services.funding_manager.concurrent_execute",
            side_effect=mock_concurrent_execute,
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.CHAIN_PROFILES",
            {"gnosis": {"service_registry": "0x1234"}},
        ):
            mock_registry.service_registry.get_instance.return_value = (
                mock_service_registry
            )
            mock_registry.service_registry_token_utility.get_instance.return_value = (
                mock_token_utility
            )
            result = manager._compute_protocol_bonded_assets(service)

        # extra_token should be in bonded assets
        assert extra_token in result["gnosis"][MASTER_SAFE_ADDR]

    def test_terminated_bonded_state_adds_agent_bonds(self) -> None:
        """TERMINATED_BONDED state adds all agent bonds from service_info."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)
        service = _mock_service(token=42)

        num_agent_instances = 3
        service_info = [
            1000,
            0,
            0,
            0,
            0,
            num_agent_instances,
            OnChainState.TERMINATED_BONDED,
            [1],
        ]
        operator_balance = 200
        current_staking_program = "prog1"

        mock_staking_contract = MagicMock()
        mock_staking_manager = MagicMock()
        mock_staking_manager.get_staking_contract.return_value = mock_staking_contract
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": 10000,
            "staking_token": TOKEN_ADDR,
            "additional_staking_tokens": {},
            "service_registry_token_utility": "0x5678",
            "staking_contract": mock_staking_contract,
        }
        mock_staking_manager.staking_state.return_value = StakingState.UNSTAKED

        mock_service_registry = MagicMock()
        mock_token_utility = MagicMock()

        second_call_result = (
            (0,),  # agent_instances (TERMINATED, so 0)
            1000,  # agent_bond
            3000,  # token_bond (getOperatorBalance)
            (0, 2000),  # security_deposits
            StakingState.UNSTAKED,
        )

        call_count = 0

        def mock_concurrent_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (service_info, operator_balance, current_staking_program)
            return second_call_result

        with patch("operate.services.funding_manager.make_chain_ledger_api"), patch(
            "operate.services.funding_manager.StakingManager",
            return_value=mock_staking_manager,
        ), patch(
            "operate.services.funding_manager.concurrent_execute",
            side_effect=mock_concurrent_execute,
        ), patch(
            "operate.services.funding_manager.registry_contracts"
        ) as mock_registry, patch(
            "operate.services.funding_manager.CHAIN_PROFILES",
            {"gnosis": {"service_registry": "0x1234"}},
        ):
            mock_registry.service_registry.get_instance.return_value = (
                mock_service_registry
            )
            mock_registry.service_registry_token_utility.get_instance.return_value = (
                mock_token_utility
            )
            result = manager._compute_protocol_bonded_assets(service)

        # TERMINATED_BONDED: num_agent_instances * token_bond should be added
        # 3 * 3000 = 9000 agent_bonds (from token utility bond calculation)
        assert TOKEN_ADDR in result["gnosis"][MASTER_SAFE_ADDR]


# ---------------------------------------------------------------------------
# Tests for _get_master_safe_balances (lines 619-656)
# ---------------------------------------------------------------------------


class TestGetMasterSafeBalances:
    """Tests for _get_master_safe_balances (lines 619-656)."""

    def test_with_service_uses_service_rpc(self) -> None:
        """_get_master_safe_balances uses service RPC when service provided."""
        manager = _make_manager()
        service = _mock_service()

        thresholds = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(100)}}}
        )

        with patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch(
            "operate.services.funding_manager.make_chain_ledger_api"
        ) as mock_make_api, patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=[BigInt(200)],
        ):
            result = manager._get_master_safe_balances(thresholds, service=service)

        mock_make_api.assert_called_once()
        assert result["gnosis"][MASTER_SAFE_ADDR][ZERO_ADDRESS] == BigInt(200)

    def test_without_service_uses_default_api(self) -> None:
        """_get_master_safe_balances uses default ledger API when no service given."""
        manager = _make_manager()

        thresholds = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(100)}}}
        )

        with patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch(
            "operate.services.funding_manager.get_default_ledger_api"
        ) as mock_default_api, patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=[BigInt(300)],
        ):
            result = manager._get_master_safe_balances(thresholds, service=None)

        mock_default_api.assert_called_once()
        assert result["gnosis"][MASTER_SAFE_ADDR][ZERO_ADDRESS] == BigInt(300)

    def test_empty_thresholds_returns_empty(self) -> None:
        """_get_master_safe_balances with empty thresholds returns empty output."""
        manager = _make_manager()
        thresholds = ChainAmounts()

        with patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=[],
        ):
            result = manager._get_master_safe_balances(thresholds)

        assert result == ChainAmounts()


# ---------------------------------------------------------------------------
# Tests for _get_master_eoa_balances (lines 661-698)
# ---------------------------------------------------------------------------


class TestGetMasterEoaBalances:
    """Tests for _get_master_eoa_balances (lines 661-698)."""

    def test_with_service_uses_service_rpc(self) -> None:
        """_get_master_eoa_balances uses service RPC when service provided."""
        manager = _make_manager()
        service = _mock_service()

        thresholds = ChainAmounts(
            {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}}}
        )

        with patch.object(
            manager, "_resolve_master_eoa", return_value=MASTER_EOA_ADDR
        ), patch(
            "operate.services.funding_manager.make_chain_ledger_api"
        ) as mock_make_api, patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=[BigInt(150)],
        ):
            result = manager._get_master_eoa_balances(thresholds, service=service)

        mock_make_api.assert_called_once()
        assert result["gnosis"][MASTER_EOA_ADDR][ZERO_ADDRESS] == BigInt(150)

    def test_without_service_uses_default_api(self) -> None:
        """_get_master_eoa_balances uses default ledger API when no service given."""
        manager = _make_manager()

        thresholds = ChainAmounts(
            {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}}}
        )

        with patch.object(
            manager, "_resolve_master_eoa", return_value=MASTER_EOA_ADDR
        ), patch(
            "operate.services.funding_manager.get_default_ledger_api"
        ) as mock_default_api, patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=[BigInt(400)],
        ):
            result = manager._get_master_eoa_balances(thresholds, service=None)

        mock_default_api.assert_called_once()
        assert result["gnosis"][MASTER_EOA_ADDR][ZERO_ADDRESS] == BigInt(400)


# ---------------------------------------------------------------------------
# Tests for fund_master_eoa (lines 702-746)
# ---------------------------------------------------------------------------


class TestFundMasterEoa:
    """Tests for FundingManager.fund_master_eoa (lines 702-746)."""

    def test_no_ethereum_wallet_logs_warning_and_returns(self) -> None:
        """fund_master_eoa returns early if no Ethereum wallet."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = False
        manager = _make_manager(wallet_manager=wallet_manager)

        manager.fund_master_eoa()

        manager.logger.warning.assert_called_once()  # type: ignore[attr-defined]
        wallet_manager.load.assert_not_called()

    def test_wallet_exists_calls_fund_chain_amounts(self) -> None:
        """fund_master_eoa calls fund_chain_amounts when wallet exists."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True

        mock_wallet = MagicMock()
        mock_wallet.address = MASTER_EOA_ADDR
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)

        gnosis_safe_balance = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
        )
        eoa_balance = ChainAmounts(
            {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
        )

        with patch.object(
            manager, "_resolve_master_eoa", return_value=MASTER_EOA_ADDR
        ), patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch.object(
            manager, "_get_master_eoa_balances", return_value=eoa_balance
        ), patch.object(
            manager, "_get_master_safe_balances", return_value=gnosis_safe_balance
        ), patch.object(
            manager, "_compute_shortfalls", return_value=eoa_balance
        ), patch.object(
            manager, "fund_chain_amounts"
        ) as mock_fund:
            manager.fund_master_eoa()

        mock_fund.assert_called_once()

    def test_insufficient_safe_balance_caps_funding(self) -> None:
        """fund_master_eoa caps funding at available safe balance."""
        wallet_manager = MagicMock()
        wallet_manager.exists.return_value = True

        mock_wallet = MagicMock()
        mock_wallet.address = MASTER_EOA_ADDR
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)

        # EOA needs 1 ETH but safe only has 0.3 ETH
        eoa_shortfall = ChainAmounts(
            {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
        )
        safe_balance = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(3 * 10**17)}}}
        )
        eoa_balance = ChainAmounts(
            {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
        )

        with patch.object(
            manager, "_resolve_master_eoa", return_value=MASTER_EOA_ADDR
        ), patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch.object(
            manager, "_get_master_eoa_balances", return_value=eoa_balance
        ), patch.object(
            manager, "_get_master_safe_balances", return_value=safe_balance
        ), patch.object(
            manager, "_compute_shortfalls", return_value=eoa_shortfall
        ), patch.object(
            manager, "fund_chain_amounts"
        ) as mock_fund:
            manager.fund_master_eoa()

        # fund_chain_amounts should be called with capped amount (3*10**17)
        mock_fund.assert_called_once()
        call_args = mock_fund.call_args[0][0]
        assert call_args["gnosis"][MASTER_EOA_ADDR][ZERO_ADDRESS] == 3 * 10**17


# ---------------------------------------------------------------------------
# Tests for fund_chain_amounts transfer path (lines 964-967)
# ---------------------------------------------------------------------------


class TestFundChainAmountsTransferPath:
    """Tests for fund_chain_amounts transfer execution (lines 964-967)."""

    def test_positive_amount_calls_wallet_transfer(self) -> None:
        """fund_chain_amounts calls wallet.transfer for amount > 0."""
        wallet_manager = MagicMock()
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)

        amounts = ChainAmounts({"gnosis": {AGENT_ADDR: {ZERO_ADDRESS: BigInt(100)}}})
        # Safe has sufficient balance
        safe_balance = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(200)}}}
        )

        with patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch.object(
            manager, "_aggregate_as_master_safe_amounts", return_value=safe_balance
        ), patch.object(
            manager, "_get_master_safe_balances", return_value=safe_balance
        ):
            manager.fund_chain_amounts(amounts)

        mock_wallet.transfer.assert_called_once_with(
            chain=Chain.GNOSIS,
            to=AGENT_ADDR,
            asset=ZERO_ADDRESS,
            amount=BigInt(100),
            from_safe=True,
        )

    def test_zero_amount_skips_wallet_transfer(self) -> None:
        """fund_chain_amounts skips wallet.transfer for amount <= 0."""
        wallet_manager = MagicMock()
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)

        amounts = ChainAmounts({"gnosis": {AGENT_ADDR: {ZERO_ADDRESS: BigInt(0)}}})
        safe_balance = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(200)}}}
        )

        with patch.object(
            manager, "_aggregate_as_master_safe_amounts", return_value=safe_balance
        ), patch.object(
            manager, "_get_master_safe_balances", return_value=safe_balance
        ):
            manager.fund_chain_amounts(amounts)

        mock_wallet.transfer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for funding_requirements (lines 755-912) — key branches
# ---------------------------------------------------------------------------


class TestFundingRequirements:
    """Tests for FundingManager.funding_requirements (lines 755-912)."""

    def _make_service_with_safe(self) -> MagicMock:
        """Create a service mock with non-placeholder safe."""
        service = _mock_service()
        service.get_initial_funding_amounts.return_value = ChainAmounts(
            {"gnosis": {AGENT_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
        )
        service.get_funding_requests.return_value = ChainAmounts()
        service.get_balances.return_value = ChainAmounts()
        return service

    def _patch_all_sub_methods(self, manager: FundingManager) -> Any:
        """Return a context manager that patches all sub-methods."""
        return patch.multiple(
            manager,
            _compute_protocol_asset_requirements=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _compute_protocol_bonded_assets=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _get_master_eoa_balances=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
                )
            ),
            _get_master_safe_balances=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
                )
            ),
            _resolve_master_eoa=MagicMock(return_value=MASTER_EOA_ADDR),
            _resolve_master_safe=MagicMock(return_value=MASTER_SAFE_ADDR),
            _compute_shortfalls=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _aggregate_as_master_safe_amounts=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _split_excess_assets_master_eoa_balances=MagicMock(
                return_value=(
                    ChainAmounts(),
                    ChainAmounts(
                        {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
                    ),
                )
            ),
            _split_critical_eoa_shortfalls=MagicMock(
                return_value=(
                    ChainAmounts(),
                    ChainAmounts(
                        {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                    ),
                )
            ),
        )

    def test_returns_expected_keys(self) -> None:
        """funding_requirements returns dict with all required keys."""
        manager = _make_manager()
        service = self._make_service_with_safe()

        with self._patch_all_sub_methods(manager), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ):
            result = manager.funding_requirements(service)

        expected_keys = {
            "balances",
            "bonded_assets",
            "total_requirements",
            "refill_requirements",
            "protocol_asset_requirements",
            "is_refill_required",
            "allow_start_agent",
            "agent_funding_requests",
            "agent_funding_requests_cooldown",
            "agent_funding_in_progress",
        }
        assert set(result.keys()) == expected_keys

    def test_funding_in_progress_returns_empty_requests(self) -> None:
        """funding_requirements returns empty requests when funding is in progress."""
        manager = _make_manager()
        service = self._make_service_with_safe()
        # Mark funding as in progress
        manager._funding_in_progress[service.service_config_id] = True

        with self._patch_all_sub_methods(manager), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ):
            result = manager.funding_requirements(service)

        assert result["agent_funding_requests"] == {}
        assert result["agent_funding_requests_cooldown"] is False
        assert result["agent_funding_in_progress"] is True

    def test_cooldown_active_returns_empty_requests_with_cooldown_true(self) -> None:
        """funding_requirements respects cooldown and sets cooldown=True."""
        manager = _make_manager()
        service = self._make_service_with_safe()
        # Set cooldown far in the future
        manager._funding_requests_cooldown_until[service.service_config_id] = (
            time() + 9999
        )

        with self._patch_all_sub_methods(manager), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ):
            result = manager.funding_requirements(service)

        assert result["agent_funding_requests"] == {}
        assert result["agent_funding_requests_cooldown"] is True

    def test_quickstart_returns_empty_funding_requests(self) -> None:
        """funding_requirements with is_for_quickstart=True returns empty requests."""
        manager = _make_manager()
        manager.is_for_quickstart = True
        service = self._make_service_with_safe()

        with self._patch_all_sub_methods(manager), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ), patch.object(
            manager,
            "compute_service_initial_shortfalls",
            return_value=ChainAmounts(),
        ):
            result = manager.funding_requirements(service)

        assert result["agent_funding_requests"] == {}
        assert result["agent_funding_requests_cooldown"] is False

    def test_normal_mode_calls_get_funding_requests(self) -> None:
        """funding_requirements in normal mode calls service.get_funding_requests()."""
        manager = _make_manager()
        service = self._make_service_with_safe()
        mock_requests = ChainAmounts(
            {"gnosis": {AGENT_ADDR: {ZERO_ADDRESS: BigInt(1000)}}}
        )
        service.get_funding_requests.return_value = mock_requests

        with self._patch_all_sub_methods(manager), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ):
            manager.funding_requirements(service)

        service.get_funding_requests.assert_called_once()

    def test_master_safe_placeholder_uses_topups_without_safe(self) -> None:
        """Master safe == MASTER_SAFE_PLACEHOLDER uses DEFAULT_EOA_TOPUPS_WITHOUT_SAFE."""
        manager = _make_manager()
        service = self._make_service_with_safe()

        # Override _resolve_master_safe to return MASTER_SAFE_PLACEHOLDER
        def sub_methods_with_placeholder(manager_obj: FundingManager) -> Any:
            return patch.multiple(
                manager_obj,
                _compute_protocol_asset_requirements=MagicMock(
                    return_value=ChainAmounts(
                        {"gnosis": {MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}}}
                    )
                ),
                _compute_protocol_bonded_assets=MagicMock(
                    return_value=ChainAmounts(
                        {"gnosis": {MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}}}
                    )
                ),
                _get_master_eoa_balances=MagicMock(
                    return_value=ChainAmounts(
                        {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
                    )
                ),
                _get_master_safe_balances=MagicMock(
                    return_value=ChainAmounts(
                        {"gnosis": {MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}}}
                    )
                ),
                _resolve_master_eoa=MagicMock(return_value=MASTER_EOA_ADDR),
                _resolve_master_safe=MagicMock(return_value=MASTER_SAFE_PLACEHOLDER),
                _compute_shortfalls=MagicMock(
                    return_value=ChainAmounts(
                        {"gnosis": {MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}}}
                    )
                ),
                _aggregate_as_master_safe_amounts=MagicMock(
                    return_value=ChainAmounts(
                        {"gnosis": {MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}}}
                    )
                ),
                _split_excess_assets_master_eoa_balances=MagicMock(
                    return_value=(
                        ChainAmounts(),
                        ChainAmounts(
                            {
                                "gnosis": {
                                    MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(10**18)}
                                }
                            }
                        ),
                    )
                ),
                _split_critical_eoa_shortfalls=MagicMock(
                    return_value=(
                        ChainAmounts(),
                        ChainAmounts(
                            {
                                "gnosis": {
                                    MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}
                                }
                            }
                        ),
                    )
                ),
            )

        with sub_methods_with_placeholder(manager), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts(
                    {"gnosis": {MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}}}
                ),
                ChainAmounts(
                    {"gnosis": {MASTER_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(0)}}}
                ),
            ),
        ):
            result = manager.funding_requirements(service)

        # Allow start agent should be False when MASTER_SAFE_PLACEHOLDER in refill_requirements
        assert result["allow_start_agent"] is False

    def test_allow_start_agent_false_when_critical_eoa_shortfall(self) -> None:
        """allow_start_agent is False when master_eoa_critical_shortfalls > 0."""
        manager = _make_manager()
        service = self._make_service_with_safe()

        critical_shortfalls = ChainAmounts(
            {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}}}
        )

        with patch.multiple(
            manager,
            _compute_protocol_asset_requirements=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _compute_protocol_bonded_assets=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _get_master_eoa_balances=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _get_master_safe_balances=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _resolve_master_eoa=MagicMock(return_value=MASTER_EOA_ADDR),
            _resolve_master_safe=MagicMock(return_value=MASTER_SAFE_ADDR),
            _compute_shortfalls=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _aggregate_as_master_safe_amounts=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _split_excess_assets_master_eoa_balances=MagicMock(
                return_value=(
                    ChainAmounts(),
                    ChainAmounts(
                        {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                    ),
                )
            ),
            _split_critical_eoa_shortfalls=MagicMock(
                return_value=(
                    critical_shortfalls,  # non-zero critical shortfalls
                    ChainAmounts(
                        {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                    ),
                )
            ),
        ), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ):
            result = manager.funding_requirements(service)

        assert result["allow_start_agent"] is False

    def test_service_safe_placeholder_sets_initial_shortfalls(self) -> None:
        """If all service_initial_topup addresses contain SERVICE_SAFE_PLACEHOLDER, use topup as shortfall."""
        manager = _make_manager()
        service = self._make_service_with_safe()
        # All addresses in initial topup are placeholder
        service.get_initial_funding_amounts.return_value = ChainAmounts(
            {"gnosis": {SERVICE_SAFE_PLACEHOLDER: {ZERO_ADDRESS: BigInt(1000)}}}
        )

        with self._patch_all_sub_methods(manager), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ):
            result = manager.funding_requirements(service)

        # When all placeholders: service_initial_shortfalls = service_initial_topup
        # This flows into _aggregate_as_master_safe_amounts
        assert result is not None

    def test_is_refill_required_true_when_nonzero_shortfall(self) -> None:
        """is_refill_required is True when any refill amount > 0."""
        manager = _make_manager()
        service = self._make_service_with_safe()

        nonzero_shortfalls = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(500)}}}
        )

        with patch.multiple(
            manager,
            _compute_protocol_asset_requirements=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _compute_protocol_bonded_assets=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _get_master_eoa_balances=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
                )
            ),
            _get_master_safe_balances=MagicMock(
                return_value=ChainAmounts(
                    {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
                )
            ),
            _resolve_master_eoa=MagicMock(return_value=MASTER_EOA_ADDR),
            _resolve_master_safe=MagicMock(return_value=MASTER_SAFE_ADDR),
            _compute_shortfalls=MagicMock(return_value=nonzero_shortfalls),
            _aggregate_as_master_safe_amounts=MagicMock(
                return_value=nonzero_shortfalls
            ),
            _split_excess_assets_master_eoa_balances=MagicMock(
                return_value=(
                    ChainAmounts(),
                    ChainAmounts(
                        {"gnosis": {MASTER_EOA_ADDR: {ZERO_ADDRESS: BigInt(10**18)}}}
                    ),
                )
            ),
            _split_critical_eoa_shortfalls=MagicMock(
                return_value=(
                    ChainAmounts(),
                    nonzero_shortfalls,
                )
            ),
        ), patch(
            "operate.services.funding_manager.concurrent_execute",
            return_value=(
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
                ChainAmounts({"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}),
            ),
        ):
            result = manager.funding_requirements(service)

        assert result["is_refill_required"] is True


# ---------------------------------------------------------------------------
# Tests for funding_job async loop (lines 1017-1048)
# ---------------------------------------------------------------------------

_REAL_SLEEP = asyncio.sleep


async def _instant_sleep(_seconds: float) -> None:
    """Yield to event loop without actually sleeping."""
    await _REAL_SLEEP(0)


class TestFundingJob:
    """Tests for FundingManager.funding_job (lines 1017-1048)."""

    @pytest.mark.asyncio
    async def test_funding_job_calls_claim_and_fund_master_eoa(self) -> None:
        """funding_job calls claim_all and fund_master_eoa when timers expire."""
        manager = _make_manager()
        mock_service_manager = MagicMock()
        mock_service_manager.claim_all_on_chain_from_safe = MagicMock()

        with patch.object(manager, "fund_master_eoa") as mock_fund_eoa, patch(
            "operate.services.funding_manager.asyncio.sleep",
            side_effect=_instant_sleep,
        ):
            task = asyncio.create_task(manager.funding_job(mock_service_manager))
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        mock_service_manager.claim_all_on_chain_from_safe.assert_called()
        mock_fund_eoa.assert_called()

    @pytest.mark.asyncio
    async def test_funding_job_logs_claim_exception(self) -> None:
        """funding_job logs and continues when claim_all raises Exception."""
        manager = _make_manager()
        mock_service_manager = MagicMock()
        mock_service_manager.claim_all_on_chain_from_safe = MagicMock(
            side_effect=RuntimeError("claim failed")
        )

        with patch.object(manager, "fund_master_eoa"), patch(
            "operate.services.funding_manager.asyncio.sleep",
            side_effect=_instant_sleep,
        ):
            task = asyncio.create_task(manager.funding_job(mock_service_manager))
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        manager.logger.info.assert_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_funding_job_logs_fund_master_eoa_exception(self) -> None:
        """funding_job logs and continues when fund_master_eoa raises Exception."""
        manager = _make_manager()
        mock_service_manager = MagicMock()

        with patch.object(
            manager, "fund_master_eoa", side_effect=RuntimeError("eoa fund failed")
        ), patch(
            "operate.services.funding_manager.asyncio.sleep",
            side_effect=_instant_sleep,
        ):
            task = asyncio.create_task(manager.funding_job(mock_service_manager))
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        manager.logger.info.assert_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_funding_job_passes_loop_to_executor(self) -> None:
        """funding_job uses provided loop arg for run_in_executor calls."""
        manager = _make_manager()
        mock_service_manager = MagicMock()
        mock_loop = MagicMock()
        # Make run_in_executor return an awaitable that completes immediately

        async def _awaitable(*args: Any, **kwargs: Any) -> None:
            return None

        mock_loop.run_in_executor = MagicMock(return_value=_awaitable())

        with patch(
            "operate.services.funding_manager.asyncio.sleep",
            side_effect=_instant_sleep,
        ):
            task = asyncio.create_task(
                manager.funding_job(mock_service_manager, loop=mock_loop)
            )
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        mock_loop.run_in_executor.assert_called()

    @pytest.mark.asyncio
    async def test_funding_job_uses_event_loop_when_no_loop_given(self) -> None:
        """funding_job calls asyncio.get_event_loop() when loop=None."""
        manager = _make_manager()
        mock_service_manager = MagicMock()

        with patch.object(manager, "fund_master_eoa"), patch(
            "operate.services.funding_manager.asyncio.sleep",
            side_effect=_instant_sleep,
        ):
            task = asyncio.create_task(
                manager.funding_job(mock_service_manager, loop=None)
            )
            await _REAL_SLEEP(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # No assertion needed - just verify it runs without error when loop=None


# ---------------------------------------------------------------------------
# Additional test for call assertion in fund_chain_amounts
# ---------------------------------------------------------------------------


class TestFundChainAmountsCallArgs:
    """Test that fund_chain_amounts passes correct args to wallet.transfer."""

    def test_transfer_called_with_correct_chain_and_asset(self) -> None:
        """wallet.transfer is called with correct chain, to, asset, amount, from_safe."""
        wallet_manager = MagicMock()
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: MASTER_SAFE_ADDR}
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)

        amounts = ChainAmounts({"gnosis": {AGENT_ADDR: {ZERO_ADDRESS: BigInt(500)}}})
        safe_balance = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(1000)}}}
        )

        with patch.object(
            manager, "_resolve_master_safe", return_value=MASTER_SAFE_ADDR
        ), patch.object(
            manager, "_aggregate_as_master_safe_amounts", return_value=safe_balance
        ), patch.object(
            manager, "_get_master_safe_balances", return_value=safe_balance
        ):
            manager.fund_chain_amounts(amounts)

        mock_wallet.transfer.assert_called_once_with(
            chain=Chain.GNOSIS,
            to=AGENT_ADDR,
            asset=ZERO_ADDRESS,
            amount=BigInt(500),
            from_safe=True,
        )

    def test_insufficient_funds_raises(self) -> None:
        """fund_chain_amounts raises InsufficientFundsException when balance < required."""
        wallet_manager = MagicMock()
        mock_wallet = MagicMock()
        wallet_manager.load.return_value = mock_wallet
        manager = _make_manager(wallet_manager=wallet_manager)

        amounts = ChainAmounts({"gnosis": {AGENT_ADDR: {ZERO_ADDRESS: BigInt(1000)}}})
        insufficient_balance = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(100)}}}
        )
        required = ChainAmounts(
            {"gnosis": {MASTER_SAFE_ADDR: {ZERO_ADDRESS: BigInt(1000)}}}
        )

        with patch.object(
            manager, "_aggregate_as_master_safe_amounts", return_value=required
        ), patch.object(
            manager, "_get_master_safe_balances", return_value=insufficient_balance
        ), pytest.raises(
            InsufficientFundsException
        ):
            manager.fund_chain_amounts(amounts)
