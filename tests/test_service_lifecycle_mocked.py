# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""
Unit tests for Service lifecycle with mocked dependencies.

Part of Phase 2.2: Fast Unit Test Suite Expansion - Strategic mocked unit tests
for service operations without external dependencies (IPFS, blockchain).
"""

import json
import typing as t
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from operate.operate_types import Chain
from operate.services.service import NON_EXISTENT_MULTISIG, NON_EXISTENT_TOKEN, Service


@pytest.fixture
def mock_ipfs_download(monkeypatch: pytest.MonkeyPatch) -> t.Callable[[str, Path], str]:
    """Mock IPFS download to avoid network calls."""

    def fake_download(hash_id: str, target_dir: Path) -> str:
        """Create fake service package structure."""
        # Create minimal service package structure
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
    """Create a minimal service template for testing."""
    return {
        "name": "test_service",
        "description": "Test service for unit tests",
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
            }
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


class TestServiceCreationMocked:
    """Test service creation with mocked IPFS downloads."""

    def test_service_new_creates_service_without_network(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> None:
        """Test Service.new() creates service without making network calls."""
        storage = tmp_path / "services"
        storage.mkdir()

        # Create service with mocked IPFS
        service = Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=service_template,
        )

        # Verify service was created
        assert service.service_config_id.startswith("sc-")
        assert service.path.exists()
        assert service.hash == "bafytest123"

        # Verify chain configs were created
        assert "ethereum" in service.chain_configs
        chain_config = service.chain_configs["ethereum"]
        assert chain_config.ledger_config.rpc == "https://ethereum.test"

        # Verify on-chain data initialized correctly
        assert chain_config.chain_data.token == NON_EXISTENT_TOKEN
        assert chain_config.chain_data.multisig == NON_EXISTENT_MULTISIG

    def test_service_new_creates_directory_structure(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> None:
        """Test Service.new() creates proper directory structure."""
        storage = tmp_path / "services"
        storage.mkdir()

        service = Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=service_template,
        )

        # Verify directory structure
        assert service.path.exists()
        assert service.path.is_dir()

        # Verify service package directory exists
        package_dir = service.path / "service_package"
        assert package_dir.exists()
        assert (package_dir / "aea-config.yaml").exists()
        assert (package_dir / "service.yaml").exists()

    def test_service_new_with_multiple_chains(
        self, tmp_path: Path, mock_ipfs_download: t.Callable[[str, Path], str]
    ) -> None:
        """Test Service.new() with multiple chain configurations."""
        storage = tmp_path / "services"
        storage.mkdir()

        multi_chain_template = {
            "name": "multi_chain_service",
            "description": "Service with multiple chain configs",
            "hash": "bafytest456",
            "home_chain": "ethereum",
            "configurations": {
                "ethereum": {
                    "rpc": "https://ethereum.test",
                    "staking_program_id": "no_staking",
                    "nft": "0x0000000000000000000000000000000000000000",
                    "agent_id": 1,
                    "cost_of_bond": 10000000000000000,
                    "fund_requirements": {
                        "0x0000000000000000000000000000000000000000": {
                            "agent": 100000000000000000,
                            "safe": 50000000000000000,
                        }
                    },
                },
                "gnosis": {
                    "rpc": "https://gnosis.test",
                    "staking_program_id": "no_staking",
                    "nft": "0x0000000000000000000000000000000000000000",
                    "agent_id": 1,
                    "cost_of_bond": 10000000000000000,
                    "fund_requirements": {
                        "0x0000000000000000000000000000000000000000": {
                            "agent": 100000000000000000,
                            "safe": 50000000000000000,
                        }
                    },
                },
                "base": {
                    "rpc": "https://base.test",
                    "staking_program_id": "no_staking",
                    "nft": "0x0000000000000000000000000000000000000000",
                    "agent_id": 1,
                    "cost_of_bond": 10000000000000000,
                    "fund_requirements": {
                        "0x0000000000000000000000000000000000000000": {
                            "agent": 100000000000000000,
                            "safe": 50000000000000000,
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

        service = Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=multi_chain_template,
        )

        # Verify all chains configured
        assert len(service.chain_configs) == 3
        assert "ethereum" in service.chain_configs
        assert "gnosis" in service.chain_configs
        assert "base" in service.chain_configs

        # Verify each chain has correct RPC
        assert (
            service.chain_configs["ethereum"].ledger_config.rpc
            == "https://ethereum.test"
        )
        assert (
            service.chain_configs["gnosis"].ledger_config.rpc == "https://gnosis.test"
        )
        assert service.chain_configs["base"].ledger_config.rpc == "https://base.test"

    def test_service_new_with_agent_addresses(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> None:
        """Test Service.new() initializes with provided agent addresses."""
        storage = tmp_path / "services"
        storage.mkdir()

        agent_addresses = [
            "0x1234567890123456789012345678901234567890",
            "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
            "0x9876543210987654321098765432109876543210",
            "0xfedcbafedcbafedcbafedcbafedcbafedcbafed",
        ]

        service = Service.new(
            agent_addresses=agent_addresses,
            storage=storage,
            service_template=service_template,
        )

        # Verify agent addresses were stored
        assert service.agent_addresses == agent_addresses
        assert len(service.agent_addresses) == 4


class TestServiceStateTransitions:
    """Test service state transitions without blockchain."""

    @pytest.fixture
    def test_service(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> Service:
        """Create a test service for state transition tests."""
        storage = tmp_path / "services"
        storage.mkdir()
        return Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=service_template,
        )

    def test_service_persists_to_disk(self, test_service: Service) -> None:
        """Test service.store() persists configuration to disk."""
        # Modify service
        test_service.agent_addresses = ["0x1111111111111111111111111111111111111111"]
        test_service.store()

        # Verify config file exists
        config_file = test_service.path / "config.json"
        assert config_file.exists()

        # Verify can load from disk
        loaded_service = Service.load(test_service.path)
        assert loaded_service.service_config_id == test_service.service_config_id
        assert loaded_service.agent_addresses == [
            "0x1111111111111111111111111111111111111111"
        ]

    def test_service_load_restores_state(self, test_service: Service) -> None:
        """Test Service.load() restores service state from disk."""
        # Store initial service
        test_service.agent_addresses = [
            "0x2222222222222222222222222222222222222222",
            "0x3333333333333333333333333333333333333333",
        ]
        test_service.store()

        # Load service
        loaded_service = Service.load(test_service.path)

        # Verify state restored
        assert loaded_service.service_config_id == test_service.service_config_id
        assert loaded_service.hash == test_service.hash
        assert loaded_service.agent_addresses == test_service.agent_addresses
        assert loaded_service.path == test_service.path

    def test_service_json_serialization(self, test_service: Service) -> None:
        """Test service.json returns serializable dictionary."""
        service_json = test_service.json

        # Verify basic structure
        assert isinstance(service_json, dict)
        assert "service_config_id" in service_json
        assert "hash" in service_json
        assert "chain_configs" in service_json

        # Verify can serialize to JSON
        json_str = json.dumps(service_json)
        assert isinstance(json_str, str)

        # Verify can deserialize
        deserialized = json.loads(json_str)
        assert deserialized["service_config_id"] == test_service.service_config_id


class TestServiceConfigurationUpdates:
    """Test service configuration updates without blockchain."""

    @pytest.fixture
    def test_service(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> Service:
        """Create a test service for configuration update tests."""
        storage = tmp_path / "services"
        storage.mkdir()
        return Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=service_template,
        )

    def test_update_agent_addresses(self, test_service: Service) -> None:
        """Test updating service agent addresses."""
        original_addresses = test_service.agent_addresses.copy()

        new_addresses = [
            "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "0xcccccccccccccccccccccccccccccccccccccccc",
        ]

        test_service.agent_addresses = new_addresses
        test_service.store()

        # Reload and verify
        loaded_service = Service.load(test_service.path)
        assert loaded_service.agent_addresses == new_addresses
        assert loaded_service.agent_addresses != original_addresses

    def test_update_rpc_endpoint(self, test_service: Service) -> None:
        """Test updating RPC endpoint for a chain."""
        original_rpc = test_service.chain_configs["ethereum"].ledger_config.rpc
        new_rpc = "https://new-ethereum-rpc.test"

        # Update RPC
        test_service.chain_configs["ethereum"].ledger_config.rpc = new_rpc
        test_service.store()

        # Reload and verify
        loaded_service = Service.load(test_service.path)
        assert loaded_service.chain_configs["ethereum"].ledger_config.rpc == new_rpc
        assert (
            loaded_service.chain_configs["ethereum"].ledger_config.rpc != original_rpc
        )

    def test_update_hash_triggers_redeployment_flag(
        self, test_service: Service, mock_ipfs_download: t.Callable[[str, Path], str]
    ) -> None:
        """Test updating service hash indicates need for redeployment."""
        original_hash = test_service.hash
        new_hash = "bafynewtest789"

        # Update hash
        test_service.hash = new_hash
        test_service.store()

        # Verify hash changed
        loaded_service = Service.load(test_service.path)
        assert loaded_service.hash == new_hash
        assert loaded_service.hash != original_hash

        # Note: In real system, this would trigger redeployment
        # Here we just verify the hash update persists


class TestServiceChainConfigManagement:
    """Test chain configuration management without blockchain."""

    @pytest.fixture
    def test_service(
        self,
        tmp_path: Path,
        mock_ipfs_download: t.Callable[[str, Path], str],
        service_template: t.Dict[str, t.Any],
    ) -> Service:
        """Create a test service for chain config tests."""
        storage = tmp_path / "services"
        storage.mkdir()
        return Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=service_template,
        )

    def test_chain_config_initialized_correctly(self, test_service: Service) -> None:
        """Test chain configurations are initialized with correct defaults."""
        chain_config = test_service.chain_configs["ethereum"]

        # Verify ledger config
        assert chain_config.ledger_config.rpc == "https://ethereum.test"
        assert chain_config.ledger_config.chain == Chain.ETHEREUM

        # Verify chain data defaults
        assert chain_config.chain_data.token == NON_EXISTENT_TOKEN
        assert chain_config.chain_data.multisig == NON_EXISTENT_MULTISIG
        assert chain_config.chain_data.instances == []

    def test_multiple_chain_configs_independent(
        self, tmp_path: Path, mock_ipfs_download: t.Callable[[str, Path], str]
    ) -> None:
        """Test multiple chain configurations are independent."""
        storage = tmp_path / "services"
        storage.mkdir()

        multi_chain_template = {
            "name": "multi_chain_test",
            "description": "Test independence of chain configs",
            "hash": "bafytest999",
            "home_chain": "ethereum",
            "configurations": {
                "ethereum": {
                    "rpc": "https://eth.test",
                    "staking_program_id": "no_staking",
                    "nft": "0x0000000000000000000000000000000000000000",
                    "agent_id": 1,
                    "cost_of_bond": 10000000000000000,
                    "fund_requirements": {
                        "0x0000000000000000000000000000000000000000": {
                            "agent": 100000000000000000,
                            "safe": 50000000000000000,
                        }
                    },
                },
                "gnosis": {
                    "rpc": "https://gnosis.test",
                    "staking_program_id": "no_staking",
                    "nft": "0x0000000000000000000000000000000000000000",
                    "agent_id": 1,
                    "cost_of_bond": 10000000000000000,
                    "fund_requirements": {
                        "0x0000000000000000000000000000000000000000": {
                            "agent": 100000000000000000,
                            "safe": 50000000000000000,
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

        service = Service.new(
            agent_addresses=[],
            storage=storage,
            service_template=multi_chain_template,
        )

        # Modify ethereum config
        service.chain_configs["ethereum"].ledger_config.rpc = (
            "https://eth-modified.test"
        )

        # Verify gnosis config unchanged
        assert (
            service.chain_configs["gnosis"].ledger_config.rpc == "https://gnosis.test"
        )
        assert (
            service.chain_configs["ethereum"].ledger_config.rpc
            == "https://eth-modified.test"
        )
