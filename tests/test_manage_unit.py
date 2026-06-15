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
from operate.exceptions import InsufficientFundsException
from operate.operate_types import (
    Chain,
    DeploymentStatus,
    LedgerConfig,
    OnChainState,
)
from operate.services.manage import ServiceManager
from operate.services.protocol import StakingState
from operate.services.service import (
    NON_EXISTENT_MULTISIG,
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

    def test_get_eth_safe_tx_builder(self, tmp_path: Path) -> None:
        """get_eth_safe_tx_builder constructs EthSafeTxBuilder correctly."""
        manager = _make_manager(tmp_path)
        ledger_config = _make_ledger_config()
        mock_wallet = MagicMock()
        manager.wallet_manager.load.return_value = mock_wallet  # type: ignore

        with (
            patch("operate.services.manage.EthSafeTxBuilder") as mock_sftxb_cls,
            patch(
                "operate.services.manage.CONTRACTS",
                {Chain.GNOSIS: {"service_manager": "0xabc"}},
            ),
            patch("operate.services.manage.ChainType") as mock_chain_type,
        ):
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

        with (
            patch.object(manager, "get_eth_safe_tx_builder", return_value=mock_sftxb),
            patch("operate.services.manage.requests.get", return_value=mock_resp),
        ):
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

        with (
            patch.object(manager, "get_eth_safe_tx_builder", return_value=mock_sftxb),
            patch("operate.services.manage.requests.get", return_value=mock_resp),
        ):
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

        with (
            patch.object(manager, "get_eth_safe_tx_builder", return_value=mock_sftxb),
            patch("operate.services.manage.get_staking_contract", return_value=None),
        ):
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

        with (
            patch.object(manager, "get_eth_safe_tx_builder", return_value=mock_sftxb),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xStakingContract",
            ),
            patch(
                "operate.services.manage.MechActivityContract.from_dir",
                return_value=mock_mech_contract,
            ),
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

        with (
            patch.object(manager, "get_eth_safe_tx_builder", return_value=mock_sftxb),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xStakingContract",
            ),
            patch(
                "operate.services.manage.MechActivityContract.from_dir",
                side_effect=Exception("mech contract failed"),
            ),
            patch(
                "operate.services.manage.RequesterActivityCheckerContract.from_dir",
                return_value=mock_requester_contract,
            ),
            patch(
                "operate.services.manage.DEFAULT_PRIORITY_MECH",
                {mech_marketplace_addr: (priority_mech, priority_service_id)},
            ),
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

        with (
            patch.object(manager, "get_eth_safe_tx_builder", return_value=mock_sftxb),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xStakingContract",
            ),
            patch(
                "operate.services.manage.MechActivityContract.from_dir",
                side_effect=Exception("mech failed"),
            ),
            patch(
                "operate.services.manage.RequesterActivityCheckerContract.from_dir",
                side_effect=Exception("requester failed"),
            ),
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

        with (
            patch.object(
                manager, "get_all_services", return_value=([svc1, svc2], True)
            ),
            patch.object(manager, "claim_on_chain_from_safe") as mock_claim,
        ):
            manager.claim_all_on_chain_from_safe()

        assert mock_claim.call_count == 2
        mock_claim.assert_any_call(service_config_id="sc-1", chain="gnosis")
        mock_claim.assert_any_call(service_config_id="sc-2", chain="base")

    def test_no_services_no_claims(self, tmp_path: Path) -> None:
        """No services means no claims."""
        manager = _make_manager(tmp_path)

        with (
            patch.object(manager, "get_all_services", return_value=([], True)),
            patch.object(manager, "claim_on_chain_from_safe") as mock_claim,
        ):
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

    def test_drain_acquires_withdrawal_lock(self, tmp_path: Path) -> None:
        """drain() holds the per-(service, chain) withdrawal lock while draining.

        Regression: a user withdrawal must serialize with a concurrent
        maintenance drain, else both transfer the same balances and the
        second reverts on an already-emptied safe.
        """
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()
        lock = MagicMock()
        manager.funding_manager.get_withdrawal_lock.return_value = lock  # type: ignore

        with patch.object(manager, "load", return_value=mock_service):
            manager.drain(
                service_config_id="sc-1",
                chain_str="gnosis",
                withdrawal_address="0xWithdrawal",
            )

        manager.funding_manager.get_withdrawal_lock.assert_called_once_with(  # type: ignore
            service_config_id="sc-1", chain=Chain.GNOSIS
        )
        lock.__enter__.assert_called_once()
        lock.__exit__.assert_called_once()
        manager.funding_manager.drain_service_safe.assert_called_once()  # type: ignore
        manager.funding_manager.drain_agents_eoas.assert_called_once()  # type: ignore

    def test_drain_unlocked_does_not_acquire_lock(self, tmp_path: Path) -> None:
        """_drain_unlocked() drains without touching the lock (caller holds it)."""
        manager = _make_manager(tmp_path)
        mock_service = _make_mock_service()

        with patch.object(manager, "load", return_value=mock_service):
            manager._drain_unlocked(  # pylint: disable=protected-access
                service_config_id="sc-1",
                chain_str="gnosis",
                withdrawal_address="0xWithdrawal",
            )

        manager.funding_manager.get_withdrawal_lock.assert_not_called()  # type: ignore
        manager.funding_manager.drain_service_safe.assert_called_once()  # type: ignore
        manager.funding_manager.drain_agents_eoas.assert_called_once()  # type: ignore


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


def _make_maintenance_service(
    token: int = 1,
    multisig: t.Optional[str] = "0xAgentSafe",
    chains: t.Optional[t.List[str]] = None,
    status: DeploymentStatus = DeploymentStatus.STOPPED,
) -> MagicMock:
    """Create a mock service suitable for service_maintenance tests."""
    service = _make_mock_service()
    service.deployment.status = status
    service.chain_configs = {}
    for chain_str in chains or [_CHAIN]:
        chain_config = MagicMock()
        chain_config.chain_data.token = token
        chain_config.chain_data.multisig = multisig
        chain_config.ledger_config.rpc = _RPC
        service.chain_configs[chain_str] = chain_config
    return service


class TestServiceMaintenance:
    """Tests for ServiceManager.service_maintenance()."""

    def _run(
        self,
        tmp_path: Path,
        services: t.List[MagicMock],
        state: OnChainState = OnChainState.PRE_REGISTRATION,
        master_safes: t.Optional[t.Dict[Chain, str]] = None,
    ) -> t.Tuple[ServiceManager, t.Dict[str, t.List[str]], MagicMock]:
        """Run service_maintenance with mocked collaborators; returns (manager, result, drain)."""
        manager = _make_manager(tmp_path)
        wallet = MagicMock()
        wallet.safes = (
            master_safes if master_safes is not None else {Chain.GNOSIS: "0xMasterSafe"}
        )
        manager.wallet_manager.load.return_value = wallet
        with (
            patch.object(manager, "get_all_services", return_value=(services, True)),
            patch.object(
                manager, "_get_on_chain_state", return_value=state
            ) as state_mock,
            patch.object(manager, "_drain_unlocked") as drain_mock,
        ):
            result = manager.service_maintenance()
        self._last_state_mock = state_mock
        return manager, result, drain_mock

    def test_processes_pre_registration_service(self, tmp_path: Path) -> None:
        """A PreRegistration service is drained to the master safe."""
        service = _make_maintenance_service()
        _, result, drain = self._run(tmp_path, [service])
        drain.assert_called_once_with(
            service_config_id=service.service_config_id,
            chain_str=_CHAIN,
            withdrawal_address="0xMasterSafe",
        )
        assert result["processed"] == [f"{service.service_config_id}:{_CHAIN}"]
        assert result["failed"] == []

    def test_processes_active_registration_service(self, tmp_path: Path) -> None:
        """An ActiveRegistration service is drained."""
        service = _make_maintenance_service()
        _, result, drain = self._run(
            tmp_path, [service], state=OnChainState.ACTIVE_REGISTRATION
        )
        drain.assert_called_once()
        assert result["processed"] == [f"{service.service_config_id}:{_CHAIN}"]

    @pytest.mark.parametrize(
        "state",
        [
            OnChainState.NON_EXISTENT,
            OnChainState.FINISHED_REGISTRATION,
            OnChainState.DEPLOYED,
            OnChainState.TERMINATED_BONDED,
            OnChainState.UNBONDED,
        ],
    )
    def test_state_gate_blocks_other_states(
        self, tmp_path: Path, state: OnChainState
    ) -> None:
        """Services in other on-chain states are not drained."""
        _, result, drain = self._run(
            tmp_path, [_make_maintenance_service()], state=state
        )
        drain.assert_not_called()
        assert result == {"processed": [], "skipped": [], "failed": []}

    @pytest.mark.parametrize("multisig", [NON_EXISTENT_MULTISIG, ZERO_ADDRESS, ""])
    def test_multisig_gate(self, tmp_path: Path, multisig: t.Optional[str]) -> None:
        """Services without an agent safe are skipped before any on-chain query."""
        service = _make_maintenance_service(multisig=multisig)
        _, result, drain = self._run(tmp_path, [service])
        drain.assert_not_called()
        self._last_state_mock.assert_not_called()
        assert result == {"processed": [], "skipped": [], "failed": []}

    def test_token_gate(self, tmp_path: Path) -> None:
        """Services never minted on a chain are skipped without on-chain queries."""
        service = _make_maintenance_service(token=NON_EXISTENT_TOKEN)
        _, result, drain = self._run(tmp_path, [service])
        drain.assert_not_called()
        self._last_state_mock.assert_not_called()

    def test_missing_master_safe_is_skipped(self, tmp_path: Path) -> None:
        """Chains without a master safe are reported as skipped."""
        service = _make_maintenance_service()
        _, result, drain = self._run(tmp_path, [service], master_safes={})
        drain.assert_not_called()
        assert result["skipped"] == [f"{service.service_config_id}:{_CHAIN}"]

    def test_per_chain_error_is_isolated(self, tmp_path: Path) -> None:
        """A failure on one service does not prevent draining the next one."""
        failing = _make_maintenance_service()
        failing.service_config_id = "sc-failing"
        healthy = _make_maintenance_service()
        healthy.service_config_id = "sc-healthy"
        manager = _make_manager(tmp_path)
        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: "0xMasterSafe"}
        manager.wallet_manager.load.return_value = wallet
        with (
            patch.object(
                manager, "get_all_services", return_value=([failing, healthy], True)
            ),
            patch.object(
                manager,
                "_get_on_chain_state",
                side_effect=[RuntimeError("RPC down"), OnChainState.PRE_REGISTRATION],
            ),
            patch.object(manager, "_drain_unlocked") as drain_mock,
        ):
            result = manager.service_maintenance()
        drain_mock.assert_called_once()
        assert result["failed"] == [f"sc-failing:{_CHAIN}"]
        assert result["processed"] == [f"sc-healthy:{_CHAIN}"]

    def test_drain_insufficient_funds_is_isolated(self, tmp_path: Path) -> None:
        """An InsufficientFundsException from drain is logged, not raised."""
        service = _make_maintenance_service()
        manager = _make_manager(tmp_path)
        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: "0xMasterSafe"}
        manager.wallet_manager.load.return_value = wallet
        with (
            patch.object(manager, "get_all_services", return_value=([service], True)),
            patch.object(
                manager,
                "_get_on_chain_state",
                return_value=OnChainState.PRE_REGISTRATION,
            ),
            patch.object(
                manager,
                "drain",
                side_effect=InsufficientFundsException("no gas", chain=_CHAIN),
            ),
        ):
            result = manager.service_maintenance()
        assert result["failed"] == [f"{service.service_config_id}:{_CHAIN}"]
        assert result["processed"] == []

    def test_lock_held_returns_immediately(self, tmp_path: Path) -> None:
        """An in-progress maintenance run makes a concurrent call a no-op."""
        manager = _make_manager(tmp_path)
        with patch.object(manager, "get_all_services") as get_all_mock:
            manager._maintenance_lock.acquire()  # pylint: disable=consider-using-with
            try:
                result = manager.service_maintenance()
            finally:
                manager._maintenance_lock.release()
        get_all_mock.assert_not_called()
        assert result == {"processed": [], "skipped": [], "failed": []}

    def test_enumeration_error_is_swallowed(self, tmp_path: Path) -> None:
        """An error while enumerating services aborts quietly without raising."""
        manager = _make_manager(tmp_path)
        with patch.object(
            manager, "get_all_services", side_effect=RuntimeError("disk error")
        ):
            result = manager.service_maintenance()
        assert result == {"processed": [], "skipped": [], "failed": []}
        assert not manager._maintenance_lock.locked()

    def test_multi_chain_only_passing_chain_drained(self, tmp_path: Path) -> None:
        """Only the chain meeting all gates is drained on a multi-chain service."""
        service = _make_maintenance_service(chains=["gnosis", "base"])
        service.chain_configs["base"].chain_data.token = NON_EXISTENT_TOKEN
        _, result, drain = self._run(tmp_path, [service])
        drain.assert_called_once_with(
            service_config_id=service.service_config_id,
            chain_str="gnosis",
            withdrawal_address="0xMasterSafe",
        )
        assert result["processed"] == [f"{service.service_config_id}:gnosis"]

    @pytest.mark.parametrize(
        "status",
        [
            DeploymentStatus.DEPLOYING,
            DeploymentStatus.DEPLOYED,
            DeploymentStatus.STOPPING,
        ],
    )
    def test_locally_active_deployment_skipped(
        self, tmp_path: Path, status: DeploymentStatus
    ) -> None:
        """Locally running/transitioning deployments are never drained."""
        service = _make_maintenance_service(status=status)
        _, result, drain = self._run(tmp_path, [service])
        drain.assert_not_called()
        self._last_state_mock.assert_not_called()
        assert result == {"processed": [], "skipped": [], "failed": []}

    def test_busy_withdrawal_lock_is_skipped(self, tmp_path: Path) -> None:
        """A held per-(service, chain) withdrawal lock skips the service chain."""
        service = _make_maintenance_service()
        manager = _make_manager(tmp_path)
        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: "0xMasterSafe"}
        manager.wallet_manager.load.return_value = wallet
        busy_lock = MagicMock()
        busy_lock.acquire.return_value = False
        manager.funding_manager.get_withdrawal_lock.return_value = busy_lock
        with (
            patch.object(manager, "get_all_services", return_value=([service], True)),
            patch.object(manager, "_get_on_chain_state") as state_mock,
            patch.object(manager, "_drain_unlocked") as drain_mock,
        ):
            result = manager.service_maintenance()
        drain_mock.assert_not_called()
        state_mock.assert_not_called()
        busy_lock.release.assert_not_called()
        assert result["skipped"] == [f"{service.service_config_id}:{_CHAIN}"]

    def test_withdrawal_lock_released_after_drain(self, tmp_path: Path) -> None:
        """The withdrawal lock is acquired before the state check and released after."""
        service = _make_maintenance_service()
        manager = _make_manager(tmp_path)
        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: "0xMasterSafe"}
        manager.wallet_manager.load.return_value = wallet
        lock = MagicMock()
        lock.acquire.return_value = True
        manager.funding_manager.get_withdrawal_lock.return_value = lock
        with (
            patch.object(manager, "get_all_services", return_value=([service], True)),
            patch.object(
                manager,
                "_get_on_chain_state",
                return_value=OnChainState.PRE_REGISTRATION,
            ),
            patch.object(manager, "_drain_unlocked") as drain_mock,
        ):
            result = manager.service_maintenance()
        # Maintenance already holds the withdrawal lock, so it must use the
        # unlocked drain (the public drain() would re-acquire and deadlock).
        drain_mock.assert_called_once()
        manager.funding_manager.get_withdrawal_lock.assert_called_once_with(
            service_config_id=service.service_config_id, chain=Chain.GNOSIS
        )
        lock.acquire.assert_called_once_with(blocking=False)
        lock.release.assert_called_once_with()
        assert result["processed"] == [f"{service.service_config_id}:{_CHAIN}"]

    def test_withdrawal_lock_released_when_state_gate_fails(
        self, tmp_path: Path
    ) -> None:
        """The withdrawal lock is released even when the state gate skips."""
        service = _make_maintenance_service()
        manager = _make_manager(tmp_path)
        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: "0xMasterSafe"}
        manager.wallet_manager.load.return_value = wallet
        lock = MagicMock()
        lock.acquire.return_value = True
        manager.funding_manager.get_withdrawal_lock.return_value = lock
        with (
            patch.object(manager, "get_all_services", return_value=([service], True)),
            patch.object(
                manager, "_get_on_chain_state", return_value=OnChainState.DEPLOYED
            ),
            patch.object(manager, "_drain_unlocked") as drain_mock,
        ):
            manager.service_maintenance()
        drain_mock.assert_not_called()
        lock.release.assert_called_once_with()


# ── Section E: Lifecycle batching ────────────────────────────


class TestTerminateAndUnbond:
    """Tests for _terminate_and_unbond helper."""

    def _make_sftxb(self) -> MagicMock:
        sftxb = MagicMock()
        tx_mock = MagicMock()
        tx_mock.add.return_value = tx_mock
        sftxb.new_tx.return_value = tx_mock
        sftxb.get_terminate_data.return_value = {"to": "0xReg", "data": "0xTerm"}
        sftxb.get_unbond_data.return_value = {"to": "0xReg", "data": "0xUnbond"}
        return sftxb

    def test_terminate_and_unbond_batches_when_deployed(self, tmp_path: Path) -> None:
        """When state is DEPLOYED, both terminate and unbond are batched."""
        manager = _make_manager(tmp_path)
        sftxb = self._make_sftxb()
        service = MagicMock()
        chain_data = MagicMock()
        chain_data.token = 42

        with patch.object(
            manager,
            "_get_on_chain_state",
            return_value=OnChainState.DEPLOYED,
        ):
            manager._terminate_and_unbond(sftxb, service, _CHAIN, chain_data)

        sftxb.new_tx.assert_called_once()
        tx = sftxb.new_tx.return_value
        assert tx.add.call_count == 2
        sftxb.get_terminate_data.assert_called_once_with(service_id=42)
        sftxb.get_unbond_data.assert_called_once_with(service_id=42)
        tx.settle.assert_called_once()

    def test_terminate_and_unbond_only_unbonds_when_terminated_bonded(
        self, tmp_path: Path
    ) -> None:
        """When already TERMINATED_BONDED, only unbond is called."""
        manager = _make_manager(tmp_path)
        sftxb = self._make_sftxb()
        service = MagicMock()
        chain_data = MagicMock()
        chain_data.token = 42

        with patch.object(
            manager,
            "_get_on_chain_state",
            return_value=OnChainState.TERMINATED_BONDED,
        ):
            manager._terminate_and_unbond(sftxb, service, _CHAIN, chain_data)

        sftxb.new_tx.assert_called_once()
        tx = sftxb.new_tx.return_value
        assert tx.add.call_count == 1
        sftxb.get_unbond_data.assert_called_once_with(service_id=42)
        sftxb.get_terminate_data.assert_not_called()
        tx.settle.assert_called_once()

    def test_terminate_and_unbond_terminate_only_when_active_registration(
        self, tmp_path: Path
    ) -> None:
        """When ACTIVE_REGISTRATION, only terminate is called (no unbond)."""
        manager = _make_manager(tmp_path)
        sftxb = self._make_sftxb()
        service = MagicMock()
        chain_data = MagicMock()
        chain_data.token = 42

        with patch.object(
            manager,
            "_get_on_chain_state",
            return_value=OnChainState.ACTIVE_REGISTRATION,
        ):
            manager._terminate_and_unbond(sftxb, service, _CHAIN, chain_data)

        sftxb.new_tx.assert_called_once()
        tx = sftxb.new_tx.return_value
        assert tx.add.call_count == 1
        sftxb.get_terminate_data.assert_called_once_with(service_id=42)
        sftxb.get_unbond_data.assert_not_called()
        tx.settle.assert_called_once()

    def test_terminate_and_unbond_noop_when_pre_registration(
        self, tmp_path: Path
    ) -> None:
        """When already PRE_REGISTRATION, nothing happens."""
        manager = _make_manager(tmp_path)
        sftxb = self._make_sftxb()
        service = MagicMock()
        chain_data = MagicMock()

        with patch.object(
            manager,
            "_get_on_chain_state",
            return_value=OnChainState.PRE_REGISTRATION,
        ):
            manager._terminate_and_unbond(sftxb, service, _CHAIN, chain_data)

        sftxb.new_tx.assert_not_called()


class TestTerminateBatching:
    """Tests for batched terminate flow in terminate_service_on_chain_from_safe."""

    def _setup_manager(
        self, tmp_path: Path
    ) -> t.Tuple[ServiceManager, MagicMock, MagicMock]:
        manager = _make_manager(tmp_path)
        service = MagicMock()
        chain_data = MagicMock()
        chain_data.token = 42
        chain_data.multisig = "0xMultisig"
        chain_data.user_params.use_staking = True
        chain_data.user_params.staking_program_id = "pearl_beta"
        chain_data.user_params.fund_requirements = {ZERO_ADDRESS: MagicMock(agent=100)}
        chain_config = MagicMock()
        chain_config.chain_data = chain_data
        chain_config.ledger_config = _make_ledger_config()
        service.chain_configs = {_CHAIN: chain_config}
        service.agent_addresses = ["0xAgentAddr"]

        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: "0xMasterSafe"}
        manager.wallet_manager.load.return_value = wallet

        sftxb = MagicMock()
        tx_mock = MagicMock()
        tx_mock.add.return_value = tx_mock
        sftxb.new_tx.return_value = tx_mock
        sftxb.get_unstaking_data.return_value = {"to": "0xS", "data": "0xU"}
        sftxb.get_terminate_data.return_value = {"to": "0xR", "data": "0xT"}
        sftxb.get_unbond_data.return_value = {"to": "0xR", "data": "0xB"}
        sftxb.get_service_safe_owners.return_value = ["0xMasterSafe"]

        return manager, service, sftxb

    def test_staked_service_batches_unstake_terminate_unbond(
        self, tmp_path: Path
    ) -> None:
        """Staked + can_unstake → claim, then batch unstake+terminate+unbond."""
        manager, service, sftxb = self._setup_manager(tmp_path)

        sftxb.can_unstake.return_value = True
        sftxb.staking_status.return_value = StakingState.STAKED

        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(
                manager,
                "_get_current_staking_program",
                return_value="pearl_beta",
            ),
            patch.object(manager, "claim_on_chain_from_safe") as claim_mock,
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xStakingContract",
            ),
        ):
            manager.terminate_service_on_chain_from_safe(
                service_config_id="sc-test", chain=_CHAIN
            )

        # Claim is called separately first
        claim_mock.assert_called_once()

        # Batch: unstake + terminate + unbond = 3 adds
        tx = sftxb.new_tx.return_value
        assert tx.add.call_count == 3
        sftxb.get_unstaking_data.assert_called_once()
        sftxb.get_terminate_data.assert_called_once()
        sftxb.get_unbond_data.assert_called_once()
        tx.settle.assert_called_once()

    def test_cannot_unstake_returns_early(self, tmp_path: Path) -> None:
        """Staked but can_unstake=False → return without terminating."""
        manager, service, sftxb = self._setup_manager(tmp_path)

        sftxb.can_unstake.return_value = False

        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(
                manager,
                "_get_current_staking_program",
                return_value="pearl_beta",
            ),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xStakingContract",
            ),
        ):
            manager.terminate_service_on_chain_from_safe(
                service_config_id="sc-test", chain=_CHAIN
            )

        # No txs should be built
        sftxb.new_tx.assert_not_called()

    def test_not_staked_batches_terminate_unbond(self, tmp_path: Path) -> None:
        """Not staked → batch terminate+unbond via _terminate_and_unbond."""
        manager, service, sftxb = self._setup_manager(tmp_path)

        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(
                manager,
                "_get_current_staking_program",
                return_value=None,
            ),
            patch.object(manager, "_terminate_and_unbond") as tab_mock,
            patch(
                "operate.services.manage.get_staking_contract",
                return_value=None,
            ),
        ):
            manager.terminate_service_on_chain_from_safe(
                service_config_id="sc-test", chain=_CHAIN
            )

        tab_mock.assert_called_once()


class TestStakeBatching:
    """Tests for batched approve+stake in stake_service_on_chain_from_safe."""

    def test_approvals_and_stake_in_one_tx(self, tmp_path: Path) -> None:
        """NFT approve + additional token approves + stake in one tx."""
        manager = _make_manager(tmp_path)
        service = MagicMock()
        chain_data = MagicMock()
        chain_data.token = 42
        chain_data.user_params.use_staking = True
        chain_data.user_params.staking_program_id = "pearl_beta"
        chain_config = MagicMock()
        chain_config.chain_data = chain_data
        chain_config.ledger_config = _make_ledger_config()
        service.chain_configs = {_CHAIN: chain_config}

        wallet = MagicMock()
        wallet.safes = {Chain.GNOSIS: "0xMasterSafe"}
        manager.wallet_manager.load.return_value = wallet

        sftxb = MagicMock()
        tx_mock = MagicMock()
        tx_mock.add.return_value = tx_mock
        sftxb.new_tx.return_value = tx_mock
        sftxb.staking_status.return_value = StakingState.UNSTAKED
        sftxb.staking_rewards_available.return_value = True
        sftxb.staking_slots_available.return_value = True
        sftxb.can_unstake.return_value = False
        sftxb.get_staking_params.return_value = {
            "additional_staking_tokens": {"0xOLAS": 1000},
        }
        sftxb.get_staking_approval_data.return_value = {"to": "0xR", "data": "a"}
        sftxb.get_erc20_approval_data.return_value = {"to": "0xO", "data": "b"}
        sftxb.get_staking_data.return_value = {"to": "0xS", "data": "c"}

        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(
                manager,
                "_get_on_chain_state",
                return_value=OnChainState.DEPLOYED,
            ),
            patch.object(
                manager,
                "_get_current_staking_program",
                return_value=None,
            ),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xStakingContract",
            ),
        ):
            manager.stake_service_on_chain_from_safe(
                service_config_id="sc-test", chain=_CHAIN
            )

        # Single tx with NFT approve + token approve + stake = 3 adds
        sftxb.new_tx.assert_called_once()
        tx = sftxb.new_tx.return_value
        assert tx.add.call_count == 3
        tx.settle.assert_called_once()
