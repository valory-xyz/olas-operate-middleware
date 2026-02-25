# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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
"""Unit tests for operate/services/manage.py."""
import logging
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS
from operate.operate_types import Chain, LedgerConfig
from operate.services.manage import NUM_LOCAL_AGENT_INSTANCES, ServiceManager
from operate.services.service import (
    NON_EXISTENT_TOKEN,
    SERVICE_CONFIG_PREFIX,
    SERVICE_CONFIG_VERSION,
)


_CHAIN = "gnosis"
_RPC = "http://localhost:8545"


def _make_manager(tmp_path: Path) -> ServiceManager:
    """Create a ServiceManager with mocked dependencies."""
    return ServiceManager(
        path=tmp_path / "services",
        keys_manager=MagicMock(),
        wallet_manager=MagicMock(),
        funding_manager=MagicMock(),
        logger=logging.getLogger("test"),
    )


def _make_ledger_config() -> LedgerConfig:
    """Create a LedgerConfig for Gnosis chain."""
    return LedgerConfig(chain=Chain.GNOSIS, rpc=_RPC)


def _make_mock_service(
    home_chain: str = _CHAIN, version: int = SERVICE_CONFIG_VERSION
) -> MagicMock:
    """Create a mock service."""
    service = MagicMock()
    service.home_chain = home_chain
    service.version = version
    service.service_config_id = "sc-test-id"
    service.json = {"name": "test"}
    service.chain_configs = {}
    service.agent_addresses = ["0xaaaa"]
    service.agent_release = {"is_aea": True}
    return service


class TestSetup:
    """Tests for setup()."""

    def test_setup_creates_directory(self, tmp_path: Path) -> None:
        """Setup creates the services directory."""
        manager = _make_manager(tmp_path)
        services_dir = tmp_path / "services"
        assert not services_dir.exists()
        manager.setup()
        assert services_dir.exists()

    def test_setup_is_idempotent(self, tmp_path: Path) -> None:
        """Setup can be called multiple times without error."""
        manager = _make_manager(tmp_path)
        manager.setup()
        manager.setup()  # Should not raise


class TestGetAllServiceIds:
    """Tests for get_all_service_ids()."""

    def test_returns_matching_dirs(self, tmp_path: Path) -> None:
        """Returns only directories starting with SERVICE_CONFIG_PREFIX."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / f"{SERVICE_CONFIG_PREFIX}abc").mkdir()
        (services_dir / f"{SERVICE_CONFIG_PREFIX}xyz").mkdir()
        (services_dir / "other_dir").mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        ids = manager.get_all_service_ids()
        assert sorted(ids) == sorted(
            [f"{SERVICE_CONFIG_PREFIX}abc", f"{SERVICE_CONFIG_PREFIX}xyz"]
        )

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Returns empty list when no matching dirs."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        assert manager.get_all_service_ids() == []

    def test_skips_non_prefix_entries(self, tmp_path: Path) -> None:
        """Does not include non-prefix dirs or files."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / "not_a_service").mkdir()
        (services_dir / "also_not").touch()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        assert manager.get_all_service_ids() == []


class TestGetAllServices:
    """Tests for get_all_services()."""

    def test_happy_path_single_service(self, tmp_path: Path) -> None:
        """Loads a valid service and returns it."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / f"{SERVICE_CONFIG_PREFIX}a").mkdir()

        mock_service = _make_mock_service()
        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        with patch("operate.services.service.Service.load", return_value=mock_service):
            services, success = manager.get_all_services()

        assert success is True
        assert services == [mock_service]

    def test_version_mismatch_sets_success_false(self, tmp_path: Path) -> None:
        """Version mismatch causes success=False."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / f"{SERVICE_CONFIG_PREFIX}b").mkdir()

        mock_service = _make_mock_service(version=SERVICE_CONFIG_VERSION + 1)
        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        with patch("operate.services.service.Service.load", return_value=mock_service):
            services, success = manager.get_all_services()

        assert success is False
        assert services == []

    def test_exception_loading_sets_success_false(self, tmp_path: Path) -> None:
        """Exception during load causes success=False."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / f"{SERVICE_CONFIG_PREFIX}c").mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        with patch(
            "operate.services.service.Service.load",
            side_effect=Exception("load error"),
        ):
            services, success = manager.get_all_services()

        assert success is False
        assert services == []

    def test_skips_non_prefix_dir(self, tmp_path: Path) -> None:
        """Non-prefix dirs are skipped entirely."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / "not_a_service").mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        services, success = manager.get_all_services()
        assert success is True
        assert services == []

    def test_multiple_services(self, tmp_path: Path) -> None:
        """Multiple services are all loaded."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / f"{SERVICE_CONFIG_PREFIX}1").mkdir()
        (services_dir / f"{SERVICE_CONFIG_PREFIX}2").mkdir()

        mock_service = _make_mock_service()
        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        with patch("operate.services.service.Service.load", return_value=mock_service):
            services, success = manager.get_all_services()

        assert success is True
        assert len(services) == 2


class TestValidateServicesAndJsonProperty:
    """Tests for validate_services() and json property."""

    def test_validate_services_delegates(self, tmp_path: Path) -> None:
        """validate_services() returns the success flag from get_all_services."""
        manager = _make_manager(tmp_path)
        with patch.object(manager, "get_all_services", return_value=([], True)):
            assert manager.validate_services() is True

        with patch.object(manager, "get_all_services", return_value=([], False)):
            assert manager.validate_services() is False

    def test_json_returns_service_json_list(self, tmp_path: Path) -> None:
        """Json property returns list of service.json."""
        manager = _make_manager(tmp_path)
        mock_service = MagicMock()
        mock_service.json = {"name": "test"}
        with patch.object(
            manager, "get_all_services", return_value=([mock_service], True)
        ):
            result = manager.json

        assert result == [{"name": "test"}]


class TestExists:
    """Tests for exists()."""

    def test_exists_true_when_path_exists(self, tmp_path: Path) -> None:
        """Returns True when directory exists."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        svc_dir = services_dir / "my-service"
        svc_dir.mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        assert manager.exists("my-service") is True

    def test_exists_false_when_path_missing(self, tmp_path: Path) -> None:
        """Returns False when directory does not exist."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        assert manager.exists("nonexistent") is False


class TestGetOnChainManagerAndBuilder:
    """Tests for get_on_chain_manager() and get_eth_safe_tx_builder()."""

    def test_get_on_chain_manager(self, tmp_path: Path) -> None:
        """get_on_chain_manager constructs OnChainManager correctly."""
        manager = _make_manager(tmp_path)
        ledger_config = _make_ledger_config()
        mock_wallet = MagicMock()
        manager.wallet_manager.load.return_value = mock_wallet  # type: ignore

        with patch("operate.services.manage.OnChainManager") as mock_ocm_cls, patch(
            "operate.services.manage.CONTRACTS",
            {Chain.GNOSIS: {"service_manager": "0xabc"}},
        ), patch("operate.services.manage.ChainType") as mock_chain_type:
            mock_chain_type.return_value = MagicMock()
            result = manager.get_on_chain_manager(ledger_config)

        mock_ocm_cls.assert_called_once()
        assert result == mock_ocm_cls.return_value

    def test_get_eth_safe_tx_builder(self, tmp_path: Path) -> None:
        """get_eth_safe_tx_builder constructs EthSafeTxBuilder correctly."""
        manager = _make_manager(tmp_path)
        ledger_config = _make_ledger_config()
        mock_wallet = MagicMock()
        manager.wallet_manager.load.return_value = mock_wallet  # type: ignore

        with patch("operate.services.manage.EthSafeTxBuilder") as mock_sftxb_cls, patch(
            "operate.services.manage.CONTRACTS",
            {Chain.GNOSIS: {"service_manager": "0xabc"}},
        ), patch("operate.services.manage.ChainType") as mock_chain_type:
            mock_chain_type.return_value = MagicMock()
            result = manager.get_eth_safe_tx_builder(ledger_config)

        mock_sftxb_cls.assert_called_once()
        assert result == mock_sftxb_cls.return_value


class TestLoadOrCreate:
    """Tests for load_or_create()."""

    def test_path_exists_no_template(self, tmp_path: Path) -> None:
        """When path exists and no template, load and return service."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        svc_hash = "QmTestHash"
        (services_dir / svc_hash).mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        mock_service = _make_mock_service()

        with patch("operate.services.manage.Service.load", return_value=mock_service):
            result = manager.load_or_create(hash=svc_hash)

        assert result == mock_service

    def test_path_exists_with_template(self, tmp_path: Path) -> None:
        """When path exists and template provided, load and update."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        svc_hash = "QmTestHash"
        (services_dir / svc_hash).mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        mock_service = _make_mock_service()
        mock_template: t.Dict[str, t.Any] = {"name": "test", "hash": svc_hash}

        with patch("operate.services.manage.Service.load", return_value=mock_service):
            result = manager.load_or_create(
                hash=svc_hash, service_template=mock_template  # type: ignore
            )

        mock_service.update_user_params_from_template.assert_called_once_with(
            service_template=mock_template
        )
        assert result == mock_service

    def test_path_not_exists_no_template_raises(self, tmp_path: Path) -> None:
        """When path does not exist and no template, raise ValueError."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        with pytest.raises(ValueError, match="service_template.*cannot be None"):
            manager.load_or_create(hash="QmNew")

    def test_path_not_exists_with_template_calls_create(self, tmp_path: Path) -> None:
        """When path does not exist and template provided, call create()."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        mock_service = _make_mock_service()
        mock_template: t.Dict[str, t.Any] = {"name": "test", "hash": "QmNew"}

        with patch.object(manager, "create", return_value=mock_service) as mock_create:
            result = manager.load_or_create(
                hash="QmNew",
                service_template=mock_template,  # type: ignore
                agent_addresses=["0x1"],
            )

        mock_create.assert_called_once_with(
            service_template=mock_template, agent_addresses=["0x1"]
        )
        assert result == mock_service


class TestGetOnChainState:
    """Tests for _get_on_chain_state()."""

    def test_returns_non_existent_when_token_is_minus_one(self, tmp_path: Path) -> None:
        """Returns NON_EXISTENT when token == NON_EXISTENT_TOKEN."""
        from operate.operate_types import OnChainState

        manager = _make_manager(tmp_path)
        mock_service = MagicMock()
        mock_chain_data = MagicMock()
        mock_chain_data.token = NON_EXISTENT_TOKEN
        mock_chain_config = MagicMock()
        mock_chain_config.chain_data = mock_chain_data
        mock_service.chain_configs = {_CHAIN: mock_chain_config}

        result = manager._get_on_chain_state(service=mock_service, chain=_CHAIN)
        assert result == OnChainState.NON_EXISTENT

    def test_returns_state_from_sftxb_info(self, tmp_path: Path) -> None:
        """Calls sftxb.info and returns the on-chain state."""
        from operate.operate_types import OnChainState

        manager = _make_manager(tmp_path)
        mock_service = MagicMock()
        mock_chain_data = MagicMock()
        mock_chain_data.token = 42
        mock_chain_config = MagicMock()
        mock_chain_config.chain_data = mock_chain_data
        mock_chain_config.ledger_config = _make_ledger_config()
        mock_service.chain_configs = {_CHAIN: mock_chain_config}

        mock_sftxb = MagicMock()
        mock_sftxb.info.return_value = {"service_state": 4}  # DEPLOYED

        with patch.object(manager, "get_eth_safe_tx_builder", return_value=mock_sftxb):
            result = manager._get_on_chain_state(service=mock_service, chain=_CHAIN)

        assert result == OnChainState.DEPLOYED
        mock_sftxb.info.assert_called_once_with(token_id=42)


class TestGetOnChainMetadata:
    """Tests for _get_on_chain_metadata()."""

    def test_returns_empty_dict_for_non_existent_token(self, tmp_path: Path) -> None:
        """Returns {} when token == NON_EXISTENT_TOKEN."""
        manager = _make_manager(tmp_path)
        mock_chain_config = MagicMock()
        mock_chain_config.chain_data.token = NON_EXISTENT_TOKEN

        result = manager._get_on_chain_metadata(chain_config=mock_chain_config)
        assert result == {}

    def test_returns_json_on_successful_http(self, tmp_path: Path) -> None:
        """Fetches IPFS metadata and returns JSON."""
        manager = _make_manager(tmp_path)
        mock_chain_config = MagicMock()
        mock_chain_config.chain_data.token = 5
        mock_chain_config.ledger_config = _make_ledger_config()

        mock_sftxb = MagicMock()
        mock_sftxb.info.return_value = {"config_hash": "QmABC123"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name": "my service"}

        with patch.object(
            manager, "get_eth_safe_tx_builder", return_value=mock_sftxb
        ), patch("operate.services.manage.requests.get", return_value=mock_resp):
            result = manager._get_on_chain_metadata(chain_config=mock_chain_config)

        assert result == {"name": "my service"}

    def test_raises_on_non_200_response(self, tmp_path: Path) -> None:
        """Raises ValueError when HTTP response is not 200."""
        manager = _make_manager(tmp_path)
        mock_chain_config = MagicMock()
        mock_chain_config.chain_data.token = 5
        mock_chain_config.ledger_config = _make_ledger_config()

        mock_sftxb = MagicMock()
        mock_sftxb.info.return_value = {"config_hash": "QmABC123"}

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(
            manager, "get_eth_safe_tx_builder", return_value=mock_sftxb
        ), patch("operate.services.manage.requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="on-chain metadata"):
                manager._get_on_chain_metadata(chain_config=mock_chain_config)


class TestGetMechConfigs:
    """Tests for get_mech_configs()."""

    def _make_ledger_api(self) -> MagicMock:
        """Create a mock ledger_api."""
        ledger_api = MagicMock()
        ledger_api.api.provider.endpoint_uri = _RPC
        return ledger_api

    def test_returns_default_when_no_staking_contract(self, tmp_path: Path) -> None:
        """Returns default MechMarketplaceConfig when staking contract is None."""
        from operate.operate_types import MechMarketplaceConfig

        manager = _make_manager(tmp_path)

        mock_sftxb = MagicMock()

        with patch.object(
            manager, "get_eth_safe_tx_builder", return_value=mock_sftxb
        ), patch("operate.services.manage.get_staking_contract", return_value=None):
            result = manager.get_mech_configs(
                chain=_CHAIN,
                ledger_api=self._make_ledger_api(),
                staking_program_id="no_staking",
            )

        assert isinstance(result, MechMarketplaceConfig)
        assert result.use_mech_marketplace is False
        assert result.mech_marketplace_address == ZERO_ADDRESS
        assert result.priority_mech_address == ZERO_ADDRESS
        assert result.priority_mech_service_id == 0

    def test_mech_activity_contract_success(self, tmp_path: Path) -> None:
        """Returns use_mech_marketplace=False when MechActivityContract succeeds."""
        from operate.operate_types import MechMarketplaceConfig

        manager = _make_manager(tmp_path)

        mock_sftxb = MagicMock()
        mock_sftxb.get_staking_params.return_value = {
            "activity_checker": "0xActivityChecker"
        }

        mech_address = "0xMechAddress"
        mock_mech_instance = MagicMock()
        mock_mech_instance.functions.agentMech.return_value.call.return_value = (
            mech_address
        )

        mock_mech_contract = MagicMock()
        mock_mech_contract.get_instance.return_value = mock_mech_instance

        with patch.object(
            manager, "get_eth_safe_tx_builder", return_value=mock_sftxb
        ), patch(
            "operate.services.manage.get_staking_contract",
            return_value="0xStakingContract",
        ), patch(
            "operate.services.manage.MechActivityContract.from_dir",
            return_value=mock_mech_contract,
        ):
            result = manager.get_mech_configs(
                chain=_CHAIN,
                ledger_api=self._make_ledger_api(),
                staking_program_id="staking_v1",
            )

        assert isinstance(result, MechMarketplaceConfig)
        assert result.use_mech_marketplace is False
        assert result.priority_mech_address == mech_address

    def test_fallback_to_requester_activity_checker(self, tmp_path: Path) -> None:
        """Falls back to RequesterActivityChecker when MechActivityContract fails."""
        from operate.operate_types import MechMarketplaceConfig

        manager = _make_manager(tmp_path)

        mock_sftxb = MagicMock()
        mock_sftxb.get_staking_params.return_value = {
            "activity_checker": "0xActivityChecker"
        }

        mech_marketplace_addr = "0xMechMarket"
        mock_requester_instance = MagicMock()
        mock_requester_instance.functions.mechMarketplace.return_value.call.return_value = (
            mech_marketplace_addr
        )

        mock_requester_contract = MagicMock()
        mock_requester_contract.get_instance.return_value = mock_requester_instance

        priority_mech = "0xPriorityMech"
        priority_service_id = 123

        with patch.object(
            manager, "get_eth_safe_tx_builder", return_value=mock_sftxb
        ), patch(
            "operate.services.manage.get_staking_contract",
            return_value="0xStakingContract",
        ), patch(
            "operate.services.manage.MechActivityContract.from_dir",
            side_effect=Exception("mech contract failed"),
        ), patch(
            "operate.services.manage.RequesterActivityCheckerContract.from_dir",
            return_value=mock_requester_contract,
        ), patch(
            "operate.services.manage.DEFAULT_PRIORITY_MECH",
            {mech_marketplace_addr: (priority_mech, priority_service_id)},
        ):
            result = manager.get_mech_configs(
                chain=_CHAIN,
                ledger_api=self._make_ledger_api(),
                staking_program_id="staking_v1",
            )

        assert isinstance(result, MechMarketplaceConfig)
        assert result.use_mech_marketplace is True
        assert result.priority_mech_address == priority_mech
        assert result.mech_marketplace_address == mech_marketplace_addr
        assert result.priority_mech_service_id == priority_service_id

    def test_both_contracts_fail_uses_defaults(self, tmp_path: Path) -> None:
        """When both contracts fail, returns default mech address."""
        from operate.operate_types import MechMarketplaceConfig

        manager = _make_manager(tmp_path)

        mock_sftxb = MagicMock()
        mock_sftxb.get_staking_params.return_value = {
            "activity_checker": "0xActivityChecker"
        }

        with patch.object(
            manager, "get_eth_safe_tx_builder", return_value=mock_sftxb
        ), patch(
            "operate.services.manage.get_staking_contract",
            return_value="0xStakingContract",
        ), patch(
            "operate.services.manage.MechActivityContract.from_dir",
            side_effect=Exception("mech failed"),
        ), patch(
            "operate.services.manage.RequesterActivityCheckerContract.from_dir",
            side_effect=Exception("requester failed"),
        ):
            result = manager.get_mech_configs(
                chain=_CHAIN,
                ledger_api=self._make_ledger_api(),
                staking_program_id="staking_v1",
            )

        assert isinstance(result, MechMarketplaceConfig)
        assert result.use_mech_marketplace is False
        # Uses the hardcoded default address
        assert (
            result.priority_mech_address == "0x77af31De935740567Cf4fF1986D04B2c964A786a"
        )


class TestGetCurrentStakingProgram:
    """Tests for _get_current_staking_program()."""

    def test_delegates_to_staking_manager(self, tmp_path: Path) -> None:
        """Calls StakingManager.get_current_staking_program with correct args."""
        manager = _make_manager(tmp_path)
        mock_service = MagicMock()
        mock_service.chain_configs = {
            _CHAIN: MagicMock(
                **{
                    "ledger_config.rpc": _RPC,
                    "chain_data.token": 77,
                }
            )
        }

        mock_staking_mgr = MagicMock()
        mock_staking_mgr.get_current_staking_program.return_value = "staking_v1"

        with patch(
            "operate.services.manage.StakingManager", return_value=mock_staking_mgr
        ):
            result = manager._get_current_staking_program(
                service=mock_service, chain=_CHAIN
            )

        assert result == "staking_v1"
        mock_staking_mgr.get_current_staking_program.assert_called_once_with(
            service_id=77
        )

    def test_returns_none_when_no_program(self, tmp_path: Path) -> None:
        """Returns None when service is not staked."""
        manager = _make_manager(tmp_path)
        mock_service = MagicMock()
        mock_service.chain_configs = {
            _CHAIN: MagicMock(
                **{
                    "ledger_config.rpc": _RPC,
                    "chain_data.token": 5,
                }
            )
        }

        mock_staking_mgr = MagicMock()
        mock_staking_mgr.get_current_staking_program.return_value = None

        with patch(
            "operate.services.manage.StakingManager", return_value=mock_staking_mgr
        ):
            result = manager._get_current_staking_program(
                service=mock_service, chain=_CHAIN
            )

        assert result is None


class TestStakeServiceOnChain:
    """Tests for stake_service_on_chain()."""

    def test_raises_not_implemented(self, tmp_path: Path) -> None:
        """stake_service_on_chain raises NotImplementedError."""
        manager = _make_manager(tmp_path)
        with pytest.raises(NotImplementedError):
            manager.stake_service_on_chain(hash="QmTest")


class TestClaimAllOnChainFromSafe:
    """Tests for claim_all_on_chain_from_safe()."""

    def test_claims_from_all_services(self, tmp_path: Path) -> None:
        """Calls claim_on_chain_from_safe for each service on home_chain."""
        manager = _make_manager(tmp_path)

        svc1 = MagicMock()
        svc1.service_config_id = "sc-1"
        svc1.home_chain = "gnosis"

        svc2 = MagicMock()
        svc2.service_config_id = "sc-2"
        svc2.home_chain = "base"

        with patch.object(
            manager, "get_all_services", return_value=([svc1, svc2], True)
        ), patch.object(manager, "claim_on_chain_from_safe") as mock_claim:
            manager.claim_all_on_chain_from_safe()

        assert mock_claim.call_count == 2
        mock_claim.assert_any_call(service_config_id="sc-1", chain="gnosis")
        mock_claim.assert_any_call(service_config_id="sc-2", chain="base")

    def test_no_services_no_claims(self, tmp_path: Path) -> None:
        """No services means no claims."""
        manager = _make_manager(tmp_path)

        with patch.object(
            manager, "get_all_services", return_value=([], True)
        ), patch.object(manager, "claim_on_chain_from_safe") as mock_claim:
            manager.claim_all_on_chain_from_safe()

        mock_claim.assert_not_called()


class TestFundService:
    """Tests for fund_service()."""

    def test_delegates_to_funding_manager(self, tmp_path: Path) -> None:
        """Calls funding_manager.fund_service with loaded service and amounts."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        mock_amounts = MagicMock()

        with patch.object(manager, "load", return_value=mock_service):
            manager.fund_service(service_config_id="sc-1", amounts=mock_amounts)

        manager.funding_manager.fund_service.assert_called_once_with(  # type: ignore
            service=mock_service, amounts=mock_amounts
        )


class TestDrain:
    """Tests for drain()."""

    def test_drains_safe_and_eoas(self, tmp_path: Path) -> None:
        """Calls both drain_service_safe and drain_agents_eoas."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()

        with patch.object(manager, "load", return_value=mock_service):
            manager.drain(
                service_config_id="sc-1",
                chain_str="gnosis",
                withdrawal_address="0xWithdrawal",
            )

        manager.funding_manager.drain_service_safe.assert_called_once_with(  # type: ignore
            service=mock_service,
            withdrawal_address="0xWithdrawal",
            chain=Chain.GNOSIS,
        )
        manager.funding_manager.drain_agents_eoas.assert_called_once_with(  # type: ignore
            service=mock_service,
            withdrawal_address="0xWithdrawal",
            chain=Chain.GNOSIS,
        )


class TestDeployServiceLocally:
    """Tests for deploy_service_locally()."""

    def test_full_deploy_calls_build_and_start(self, tmp_path: Path) -> None:
        """Build and start are called when build_only=False."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        mock_deployment = MagicMock()
        mock_service.deployment = mock_deployment
        manager.wallet_manager.password = "pw"  # nosec B105

        with patch.object(manager, "load", return_value=mock_service):
            result = manager.deploy_service_locally(
                service_config_id="sc-1",
                chain="gnosis",
                use_docker=True,
                build_only=False,
            )

        mock_deployment.build.assert_called_once_with(
            use_docker=True,
            use_kubernetes=False,
            force=True,
            chain="gnosis",
            keys_manager=manager.keys_manager,
        )
        mock_deployment.start.assert_called_once_with(
            password="pw",  # nosec B106
            use_docker=True,
            is_aea=True,
        )
        assert result == mock_deployment

    def test_build_only_skips_start(self, tmp_path: Path) -> None:
        """When build_only=True, start is not called."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        mock_deployment = MagicMock()
        mock_service.deployment = mock_deployment
        manager.wallet_manager.password = "pw"  # nosec B105

        with patch.object(manager, "load", return_value=mock_service):
            result = manager.deploy_service_locally(
                service_config_id="sc-1",
                build_only=True,
            )

        mock_deployment.build.assert_called_once()
        mock_deployment.start.assert_not_called()
        assert result == mock_deployment

    def test_uses_home_chain_when_chain_not_provided(self, tmp_path: Path) -> None:
        """Uses service.home_chain when chain argument is None."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service(home_chain="base")
        mock_deployment = MagicMock()
        mock_service.deployment = mock_deployment
        manager.wallet_manager.password = "pw"  # nosec B105

        with patch.object(manager, "load", return_value=mock_service):
            manager.deploy_service_locally(
                service_config_id="sc-1",
                chain=None,
                build_only=False,
            )

        mock_deployment.build.assert_called_once_with(
            use_docker=False,
            use_kubernetes=False,
            force=True,
            chain="base",
            keys_manager=manager.keys_manager,
        )


class TestStopServiceLocally:
    """Tests for stop_service_locally()."""

    def test_stop_without_delete(self, tmp_path: Path) -> None:
        """Stop is called, delete is not called when delete=False."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        mock_deployment = MagicMock()
        mock_service.deployment = mock_deployment

        with patch.object(manager, "load", return_value=mock_service):
            result = manager.stop_service_locally(
                service_config_id="sc-1", delete=False, use_docker=True
            )

        mock_service.remove_latest_healthcheck.assert_called_once()
        mock_deployment.stop.assert_called_once_with(
            use_docker=True, force=False, is_aea=True
        )
        mock_deployment.delete.assert_not_called()
        assert result == mock_deployment

    def test_stop_with_delete(self, tmp_path: Path) -> None:
        """Delete is called when delete=True."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        mock_deployment = MagicMock()
        mock_service.deployment = mock_deployment

        with patch.object(manager, "load", return_value=mock_service):
            manager.stop_service_locally(service_config_id="sc-1", delete=True)

        mock_deployment.delete.assert_called_once()


class TestUpdate:
    """Tests for update()."""

    def test_update_delegates_to_service(self, tmp_path: Path) -> None:
        """Loads service and calls service.update()."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        mock_template: t.Dict[str, t.Any] = {"name": "updated"}

        with patch.object(manager, "load", return_value=mock_service):
            result = manager.update(
                service_config_id="sc-1",
                service_template=mock_template,  # type: ignore
                allow_different_service_public_id=True,
                partial_update=False,
            )

        mock_service.update.assert_called_once_with(
            service_template=mock_template,
            allow_different_service_public_id=True,
            partial_update=False,
        )
        assert result == mock_service


class TestFundingRequirements:
    """Tests for funding_requirements()."""

    def test_delegates_to_funding_manager(self, tmp_path: Path) -> None:
        """Calls funding_manager.funding_requirements with loaded service."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        expected_result = {"gnosis": {"0x0": 100}}

        manager.funding_manager.funding_requirements.return_value = expected_result  # type: ignore

        with patch.object(manager, "load", return_value=mock_service):
            result = manager.funding_requirements(service_config_id="sc-1")

        manager.funding_manager.funding_requirements.assert_called_once_with(  # type: ignore
            mock_service
        )
        assert result == expected_result


class TestComputeProtocolAssetRequirements:
    """Tests for _compute_protocol_asset_requirements()."""

    def test_non_staking_uses_cost_of_bond(self, tmp_path: Path) -> None:
        """Non-staking: returns cost_of_bond * num_agents + cost_of_bond for ZERO_ADDRESS."""
        import os

        manager = _make_manager(tmp_path)

        mock_user_params = MagicMock()
        mock_user_params.use_staking = False
        mock_user_params.cost_of_bond = 10
        mock_user_params.staking_program_id = None

        mock_chain_config = MagicMock()
        mock_chain_config.chain_data.user_params = mock_user_params
        mock_chain_config.ledger_config = _make_ledger_config()

        mock_service = MagicMock()
        mock_service.chain_configs = {_CHAIN: mock_chain_config}

        with patch.object(manager, "load", return_value=mock_service), patch.object(
            manager, "get_eth_safe_tx_builder"
        ), patch.dict(os.environ, {"CUSTOM_CHAIN_RPC": _RPC}):
            result = manager._compute_protocol_asset_requirements("sc-1", _CHAIN)

        expected = {ZERO_ADDRESS: 10 * NUM_LOCAL_AGENT_INSTANCES + 10}
        assert result == expected

    def test_staking_uses_staking_params(self, tmp_path: Path) -> None:
        """Staking: uses staking_params from sftxb.get_staking_params."""
        import os

        manager = _make_manager(tmp_path)

        mock_user_params = MagicMock()
        mock_user_params.use_staking = True
        mock_user_params.staking_program_id = "staking_v1"

        mock_chain_config = MagicMock()
        mock_chain_config.chain_data.user_params = mock_user_params
        mock_chain_config.ledger_config = _make_ledger_config()

        mock_service = MagicMock()
        mock_service.chain_configs = {_CHAIN: mock_chain_config}

        mock_sftxb = MagicMock()
        staking_params = {
            "min_staking_deposit": 100,
            "staking_token": "0xOLAS",
            "additional_staking_tokens": {"0xExtraToken": 50},
        }
        mock_sftxb.get_staking_params.return_value = staking_params

        with patch.object(manager, "load", return_value=mock_service), patch.object(
            manager, "get_eth_safe_tx_builder", return_value=mock_sftxb
        ), patch(
            "operate.services.manage.get_staking_contract",
            return_value="0xStaking",
        ), patch.dict(
            os.environ, {"CUSTOM_CHAIN_RPC": _RPC}
        ):
            result = manager._compute_protocol_asset_requirements("sc-1", _CHAIN)

        assert result[ZERO_ADDRESS] == NUM_LOCAL_AGENT_INSTANCES + 1
        assert result["0xOLAS"] == 100 * NUM_LOCAL_AGENT_INSTANCES + 100
        assert result["0xExtraToken"] == 50

    def test_no_staking_program_id_uses_cost_of_bond(self, tmp_path: Path) -> None:
        """use_staking=True but no staking_program_id uses cost_of_bond path."""
        import os

        manager = _make_manager(tmp_path)

        mock_user_params = MagicMock()
        mock_user_params.use_staking = True
        mock_user_params.staking_program_id = None  # No program ID
        mock_user_params.cost_of_bond = 5

        mock_chain_config = MagicMock()
        mock_chain_config.chain_data.user_params = mock_user_params
        mock_chain_config.ledger_config = _make_ledger_config()

        mock_service = MagicMock()
        mock_service.chain_configs = {_CHAIN: mock_chain_config}

        with patch.object(manager, "load", return_value=mock_service), patch.object(
            manager, "get_eth_safe_tx_builder"
        ), patch.dict(os.environ, {"CUSTOM_CHAIN_RPC": _RPC}):
            result = manager._compute_protocol_asset_requirements("sc-1", _CHAIN)

        assert result == {ZERO_ADDRESS: 5 * NUM_LOCAL_AGENT_INSTANCES + 5}


class TestComputeRefillRequirement:
    """Tests for _compute_refill_requirement() static method."""

    def test_raises_when_threshold_gt_topup(self) -> None:
        """Raises when sender_threshold > sender_topup."""
        with pytest.raises(ValueError, match="sender_threshold.*sender_topup"):
            ServiceManager._compute_refill_requirement(
                asset_funding_values={},
                sender_topup=10,
                sender_threshold=20,
                sender_balance=0,
            )

    def test_raises_when_threshold_negative(self) -> None:
        """Raises when sender_threshold < 0."""
        with pytest.raises(ValueError, match="sender_threshold.*sender_topup"):
            ServiceManager._compute_refill_requirement(
                asset_funding_values={},
                sender_topup=0,
                sender_threshold=-1,
                sender_balance=0,
            )

    def test_raises_when_sender_balance_negative(self) -> None:
        """Raises when sender_balance < 0."""
        with pytest.raises(ValueError, match="sender_balance.*>= 0"):
            ServiceManager._compute_refill_requirement(
                asset_funding_values={},
                sender_topup=0,
                sender_threshold=0,
                sender_balance=-1,
            )

    def test_raises_when_asset_threshold_gt_topup(self) -> None:
        """Raises when asset threshold > topup."""
        with pytest.raises(ValueError, match="threshold.*topup"):
            ServiceManager._compute_refill_requirement(
                asset_funding_values={
                    "0xAgent": {
                        "topup": 10,
                        "threshold": 20,
                        "balance": 0,
                    }
                },
                sender_topup=100,
                sender_threshold=50,
                sender_balance=0,
            )

    def test_raises_when_asset_balance_negative(self) -> None:
        """Raises when asset balance < 0."""
        with pytest.raises(ValueError, match="balance.*>= 0"):
            ServiceManager._compute_refill_requirement(
                asset_funding_values={
                    "0xAgent": {
                        "topup": 10,
                        "threshold": 5,
                        "balance": -1,
                    }
                },
                sender_topup=100,
                sender_threshold=50,
                sender_balance=0,
            )

    def test_no_shortfall_returns_zeros(self) -> None:
        """No shortfall when balances are above thresholds."""
        result = ServiceManager._compute_refill_requirement(
            asset_funding_values={
                "0xAgent": {"topup": 100, "threshold": 50, "balance": 200}
            },
            sender_topup=100,
            sender_threshold=50,
            sender_balance=500,
        )
        assert result == {"minimum_refill": 0, "recommended_refill": 0}

    def test_shortfall_computes_correctly(self) -> None:
        """Shortfall is computed when balance is below threshold."""
        result = ServiceManager._compute_refill_requirement(
            asset_funding_values={
                "0xAgent": {
                    "topup": 100,
                    "threshold": 80,
                    "balance": 30,  # below threshold by 50, below topup by 70
                }
            },
            sender_topup=200,
            sender_threshold=100,
            sender_balance=120,  # 120 - 50 = 70 remaining (< threshold=100) → need 30 min
        )
        # minimum_obligations_shortfall = 80 - 30 = 50
        # recommended_obligations_shortfall = 100 - 30 = 70
        # remaining_balance_minimum = 120 - 50 = 70 < sender_threshold=100
        #   → minimum_refill = 100 - 70 = 30
        # remaining_balance_recommended = 120 - 70 = 50 < sender_threshold=100
        #   → recommended_refill = 200 - 50 = 150
        assert result["minimum_refill"] == 30
        assert result["recommended_refill"] == 150

    def test_empty_asset_funding_values(self) -> None:
        """Empty asset_funding_values means only sender is considered."""
        result = ServiceManager._compute_refill_requirement(
            asset_funding_values={},
            sender_topup=100,
            sender_threshold=50,
            sender_balance=20,  # below threshold
        )
        # remaining = 20 - 0 = 20 < threshold=50 → min_refill = 50 - 20 = 30
        assert result["minimum_refill"] == 30
        assert result["recommended_refill"] == 80  # 100 - 20 = 80


class TestGetMasterEoaNativeFundingValues:
    """Tests for get_master_eoa_native_funding_values() static method."""

    def test_master_safe_exists_threshold_is_half_topup(self) -> None:
        """When master_safe_exists=True, threshold = topup/2."""
        topup = DEFAULT_EOA_TOPUPS[Chain.GNOSIS][ZERO_ADDRESS]
        result = ServiceManager.get_master_eoa_native_funding_values(
            master_safe_exists=True,
            chain=Chain.GNOSIS,
            balance=999,
        )
        assert result["topup"] == topup
        assert result["threshold"] == topup / 2
        assert result["balance"] == 999

    def test_master_safe_not_exists_threshold_equals_topup(self) -> None:
        """When master_safe_exists=False, threshold = topup."""
        topup = DEFAULT_EOA_TOPUPS[Chain.GNOSIS][ZERO_ADDRESS]
        result = ServiceManager.get_master_eoa_native_funding_values(
            master_safe_exists=False,
            chain=Chain.GNOSIS,
            balance=0,
        )
        assert result["topup"] == topup
        assert result["threshold"] == topup
        assert result["balance"] == 0
