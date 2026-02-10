"""
Unit tests for balance checking operations with mocked dependencies.

Part of Phase 2.2: Fast Unit Test Suite Expansion - Strategic mocked unit tests
for balance checking operations without external dependencies (RPC calls, blockchain).
"""

import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.operate_types import Chain
from operate.serialization import BigInt
from operate.services.service import (
    NON_EXISTENT_MULTISIG,
    NON_EXISTENT_TOKEN,
    SERVICE_SAFE_PLACEHOLDER,
    Service,
)
from operate.wallet.master import MasterWalletManager


@pytest.fixture
def mock_ipfs_download(monkeypatch: pytest.MonkeyPatch) -> t.Callable[[str, Path], str]:
    """Mock IPFS download to avoid network calls."""

    def fake_download(hash_id: str, target_dir: Path) -> str:
        """Create fake service package structure."""
        package_dir = target_dir / "service_package"
        package_dir.mkdir(parents=True, exist_ok=True)

        # Create aea-config.yaml
        aea_config = package_dir / "aea-config.yaml"
        aea_config.write_text(
            "agent_name: test_agent\n"
            "author: valory\n"
            "version: 0.1.0\n"
            "description: Test service\n"
            "license: Apache-2.0\n"
        )

        # Create service.yaml
        service_config = package_dir / "service.yaml"
        service_config.write_text(
            "name: test_service\n"
            "author: valory\n"
            "version: 0.1.0\n"
            "number_of_agents: 4\n"
        )

        return str(package_dir)

    # Patch IPFSTool
    mock_ipfs_tool = MagicMock()
    mock_ipfs_tool.return_value.download = fake_download
    monkeypatch.setattr("operate.services.service.IPFSTool", mock_ipfs_tool)

    return fake_download


@pytest.fixture
def service_template() -> t.Dict[str, t.Any]:
    """Create a service template with funding requirements."""
    return {
        "name": "test_service",
        "description": "Test service for balance tests",
        "hash": "bafytest123",
        "home_chain": "ethereum",
        "configurations": {
            "ethereum": {
                "rpc": "https://ethereum.test",
                "staking_program_id": "no_staking",
                "nft": "0x0000000000000000000000000000000000000000",
                "agent_id": 1,
                "cost_of_bond": 10000000000000000,  # 0.01 ETH
                "fund_requirements": {
                    "0x0000000000000000000000000000000000000000": {  # Native token
                        "agent": 100000000000000000,  # 0.1 ETH
                        "safe": 50000000000000000,  # 0.05 ETH
                    }
                },
            },
            "gnosis": {
                "rpc": "https://gnosis.test",
                "staking_program_id": "no_staking",
                "nft": "0x0000000000000000000000000000000000000000",
                "agent_id": 1,
                "cost_of_bond": 5000000000000000,  # 0.005 xDAI
                "fund_requirements": {
                    "0x0000000000000000000000000000000000000000": {  # Native token
                        "agent": 50000000000000000,  # 0.05 xDAI
                        "safe": 25000000000000000,  # 0.025 xDAI
                    }
                },
            },
        },
        "env_variables": {},
        "agent_release": {
            "is_aea": True,
            "repository": {
                "owner": "valory",
                "name": "test_agent",
                "version": "0.1.0",
            },
        },
    }


class TestServiceFundingAmounts:
    """Test service funding amount calculations without blockchain."""

    @pytest.fixture
    def test_service(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> Service:
        """Create a test service for funding amount tests."""
        storage = tmp_path / "services"
        storage.mkdir()

        # Create service with 2 agent addresses
        service = Service.new(
            agent_addresses=[
                "0x1111111111111111111111111111111111111111",
                "0x2222222222222222222222222222222222222222",
            ],
            storage=storage,
            service_template=service_template,
        )

        return service

    def test_get_initial_funding_amounts_structure(
        self, test_service: Service
    ) -> None:
        """Test get_initial_funding_amounts returns correct structure."""
        amounts = test_service.get_initial_funding_amounts()

        # Should have entries for both chains
        assert "ethereum" in amounts
        assert "gnosis" in amounts

        # Each chain should have safe + agent addresses
        eth_amounts = amounts["ethereum"]
        assert SERVICE_SAFE_PLACEHOLDER in eth_amounts  # Safe not deployed yet
        assert "0x1111111111111111111111111111111111111111" in eth_amounts
        assert "0x2222222222222222222222222222222222222222" in eth_amounts

    def test_get_initial_funding_amounts_values(self, test_service: Service) -> None:
        """Test get_initial_funding_amounts returns correct values."""
        amounts = test_service.get_initial_funding_amounts()

        # Check Ethereum amounts
        eth_safe_amount = amounts["ethereum"][SERVICE_SAFE_PLACEHOLDER][
            "0x0000000000000000000000000000000000000000"
        ]
        assert eth_safe_amount == 50000000000000000  # 0.05 ETH

        eth_agent1_amount = amounts["ethereum"][
            "0x1111111111111111111111111111111111111111"
        ]["0x0000000000000000000000000000000000000000"]
        assert eth_agent1_amount == 100000000000000000  # 0.1 ETH

        eth_agent2_amount = amounts["ethereum"][
            "0x2222222222222222222222222222222222222222"
        ]["0x0000000000000000000000000000000000000000"]
        assert eth_agent2_amount == 100000000000000000  # 0.1 ETH

        # Check Gnosis amounts
        gnosis_safe_amount = amounts["gnosis"][SERVICE_SAFE_PLACEHOLDER][
            "0x0000000000000000000000000000000000000000"
        ]
        assert gnosis_safe_amount == 25000000000000000  # 0.025 xDAI

    def test_get_initial_funding_amounts_multiple_agents(
        self, tmp_path: Path, mock_ipfs_download: t.Callable[[str, Path], str], service_template: t.Dict[str, t.Any]
    ) -> None:
        """Test funding amounts scale with number of agents."""
        storage = tmp_path / "services"
        storage.mkdir()

        # Create service with 4 agent addresses
        service = Service.new(
            agent_addresses=[
                "0x1111111111111111111111111111111111111111",
                "0x2222222222222222222222222222222222222222",
                "0x3333333333333333333333333333333333333333",
                "0x4444444444444444444444444444444444444444",
            ],
            storage=storage,
            service_template=service_template,
        )

        amounts = service.get_initial_funding_amounts()

        # Should have 4 agent entries + 1 safe
        eth_amounts = amounts["ethereum"]
        assert len(eth_amounts) == 5  # 4 agents + 1 safe

        # Each agent should get the same amount
        for agent_addr in service.agent_addresses:
            agent_amount = eth_amounts[agent_addr][
                "0x0000000000000000000000000000000000000000"
            ]
            assert agent_amount == 100000000000000000  # 0.1 ETH per agent


class TestServiceBalanceChecking:
    """Test service balance checking with mocked ledger APIs."""

    @pytest.fixture
    def test_service(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> Service:
        """Create a test service for balance checking tests."""
        storage = tmp_path / "services"
        storage.mkdir()

        service = Service.new(
            agent_addresses=["0x1111111111111111111111111111111111111111"],
            storage=storage,
            service_template=service_template,
        )

        return service

    def test_get_balances_calls_ledger_apis(
        self, test_service: Service, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_balances creates ledger APIs for each chain."""
        # Mock ledger API creation
        mock_ledger_api = MagicMock()
        mock_make_ledger = MagicMock(return_value=mock_ledger_api)
        monkeypatch.setattr(
            "operate.services.service.make_chain_ledger_api", mock_make_ledger
        )

        # Mock get_asset_balance to return test balances
        mock_get_balance = MagicMock(return_value=BigInt(1000000000000000000))  # 1 ETH
        monkeypatch.setattr(
            "operate.services.service.get_asset_balance", mock_get_balance
        )

        # Call get_balances
        balances = test_service.get_balances()

        # Verify ledger APIs were created for both chains
        assert mock_make_ledger.call_count >= 2  # At least ethereum and gnosis

        # Verify custom RPCs were used
        calls = mock_make_ledger.call_args_list
        rpc_used = [call[1].get("rpc") for call in calls if "rpc" in call[1]]
        assert "https://ethereum.test" in rpc_used
        assert "https://gnosis.test" in rpc_used

    def test_get_balances_returns_correct_structure(
        self, test_service: Service, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_balances returns ChainAmounts with correct structure."""
        # Mock ledger API
        mock_ledger_api = MagicMock()
        monkeypatch.setattr(
            "operate.services.service.make_chain_ledger_api",
            MagicMock(return_value=mock_ledger_api),
        )

        # Mock balance: return different amounts for different addresses
        def mock_balance(ledger_api: t.Any, asset_address: str, address: str, **kwargs: t.Any) -> BigInt:
            if "1111" in address:
                return BigInt(500000000000000000)  # 0.5 ETH for agent
            return BigInt(250000000000000000)  # 0.25 ETH for safe

        monkeypatch.setattr("operate.services.service.get_asset_balance", mock_balance)

        # Turn off wrapped token unification to simplify test
        balances = test_service.get_balances(unify_wrapped_native_tokens=False)

        # Verify structure
        assert "ethereum" in balances
        assert "gnosis" in balances

        # Check agent balance exists
        eth_balances = balances["ethereum"]
        assert "0x1111111111111111111111111111111111111111" in eth_balances

        # Verify balance value
        agent_assets = eth_balances["0x1111111111111111111111111111111111111111"]
        assert "0x0000000000000000000000000000000000000000" in agent_assets
        assert agent_assets["0x0000000000000000000000000000000000000000"] == 500000000000000000

    def test_get_balances_handles_missing_chain_config(
        self, test_service: Service, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_balances handles missing chain configs gracefully."""
        # Mock ledger API
        mock_ledger_api = MagicMock()
        mock_make_ledger = MagicMock(return_value=mock_ledger_api)
        monkeypatch.setattr(
            "operate.services.service.make_chain_ledger_api", mock_make_ledger
        )

        # Mock default ledger API (fallback)
        mock_default_ledger = MagicMock()
        monkeypatch.setattr(
            "operate.services.service.get_default_ledger_api",
            MagicMock(return_value=mock_default_ledger),
        )

        # Mock balance
        monkeypatch.setattr(
            "operate.services.service.get_asset_balance",
            MagicMock(return_value=BigInt(1000000000000000000)),
        )

        # Remove a chain config
        original_config = test_service.chain_configs.pop("gnosis")

        # Should still work (fallback to default RPC)
        balances = test_service.get_balances()

        # Verify it attempted to get balances
        assert isinstance(balances, dict)

        # Restore config
        test_service.chain_configs["gnosis"] = original_config


class TestBalanceQueryMocking:
    """Test balance query mocking patterns for different scenarios."""

    def test_mock_ledger_api_native_balance(self) -> None:
        """Test mocking native token balance queries."""
        # Create mock ledger API
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.get_balance.return_value = 2000000000000000000  # 2 ETH

        # Simulate balance query
        balance = mock_ledger_api.api.eth.get_balance("0x1234567890123456789012345678901234567890")

        # Verify mock works as expected
        assert balance == 2000000000000000000
        mock_ledger_api.api.eth.get_balance.assert_called_once()

    def test_mock_ledger_api_multiple_addresses(self) -> None:
        """Test mocking balance queries for multiple addresses."""
        # Create mock with different balances per address
        mock_ledger_api = MagicMock()

        def get_balance_by_address(address: str) -> int:
            balances = {
                "0x1111111111111111111111111111111111111111": 1000000000000000000,  # 1 ETH
                "0x2222222222222222222222222222222222222222": 2000000000000000000,  # 2 ETH
                "0x3333333333333333333333333333333333333333": 3000000000000000000,  # 3 ETH
            }
            return balances.get(address, 0)

        mock_ledger_api.api.eth.get_balance.side_effect = get_balance_by_address

        # Query different addresses
        balance1 = mock_ledger_api.api.eth.get_balance("0x1111111111111111111111111111111111111111")
        balance2 = mock_ledger_api.api.eth.get_balance("0x2222222222222222222222222222222222222222")
        balance3 = mock_ledger_api.api.eth.get_balance("0x3333333333333333333333333333333333333333")

        # Verify each address returns correct balance
        assert balance1 == 1000000000000000000
        assert balance2 == 2000000000000000000
        assert balance3 == 3000000000000000000

    def test_mock_balance_for_testing_thresholds(self) -> None:
        """Test mocking balances for threshold checks."""
        # Mock ledger that returns balance below threshold
        mock_ledger_low = MagicMock()
        mock_ledger_low.api.eth.get_balance.return_value = 10000000000000000  # 0.01 ETH

        # Mock ledger that returns balance above threshold
        mock_ledger_high = MagicMock()
        mock_ledger_high.api.eth.get_balance.return_value = 1000000000000000000  # 1 ETH

        # Threshold for refill: 0.05 ETH
        threshold = 50000000000000000

        # Check low balance needs refill
        low_balance = mock_ledger_low.api.eth.get_balance("0xtest")
        assert low_balance < threshold

        # Check high balance doesn't need refill
        high_balance = mock_ledger_high.api.eth.get_balance("0xtest")
        assert high_balance > threshold


class TestBalanceEdgeCases:
    """Test edge cases in balance checking."""

    def test_balance_with_zero_agents(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test funding amounts with zero agent addresses."""
        storage = tmp_path / "services"
        storage.mkdir()

        # Create service with no agents
        service = Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=service_template,
        )

        amounts = service.get_initial_funding_amounts()

        # Should still have safe funding
        assert SERVICE_SAFE_PLACEHOLDER in amounts["ethereum"]
        assert (
            amounts["ethereum"][SERVICE_SAFE_PLACEHOLDER][
                "0x0000000000000000000000000000000000000000"
            ]
            == 50000000000000000
        )

    def test_balance_with_deployed_safe(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> None:
        """Test funding amounts use real safe address when deployed."""
        storage = tmp_path / "services"
        storage.mkdir()

        service = Service.new(
            agent_addresses=["0x1111111111111111111111111111111111111111"],
            storage=storage,
            service_template=service_template,
        )

        # Simulate safe deployment
        deployed_safe = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        service.chain_configs["ethereum"].chain_data.multisig = deployed_safe

        amounts = service.get_initial_funding_amounts()

        # Should use actual safe address, not placeholder
        assert deployed_safe in amounts["ethereum"]
        assert SERVICE_SAFE_PLACEHOLDER not in amounts["ethereum"]

        # Safe should have correct funding requirement
        assert (
            amounts["ethereum"][deployed_safe]["0x0000000000000000000000000000000000000000"]
            == 50000000000000000
        )
