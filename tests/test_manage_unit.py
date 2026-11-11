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
from autonomy.chain.exceptions import ChainInteractionError
from hexbytes import HexBytes
from web3 import Web3

from operate.constants import ZERO_ADDRESS
from operate.exceptions import (
    AgentCouldNotEnableRecoveryModuleError,
    InsufficientFundsException,
    RecoveryModuleNotEnabledError,
)
from operate.operate_types import (
    Chain,
    DeploymentStatus,
    LedgerConfig,
    OnChainState,
    StakingEvictionState,
    StakingReconcileOutcome,
)
from operate.services.manage import (
    ServiceManager,
    _stop_refused_reuse_before_txs,
)
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

    @pytest.mark.parametrize(
        "service_config_id",
        ["..", "../sibling", "../services-evil", "", ".", "{tmp_path}/sibling"],
    )
    def test_exists_false_outside_services_dir(
        self, tmp_path: Path, service_config_id: str
    ) -> None:
        """Returns False for an id that resolves to the directory or beyond it."""
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (tmp_path / "sibling").mkdir()
        # Starts with the services dir's name; only a separator-aware check rejects it.
        (tmp_path / "services-evil").mkdir()
        service_config_id = service_config_id.format(tmp_path=tmp_path)

        manager = ServiceManager(
            path=services_dir,
            keys_manager=MagicMock(),
            wallet_manager=MagicMock(),
            funding_manager=MagicMock(),
            logger=logging.getLogger("test"),
        )
        assert manager.exists(service_config_id) is False


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


_SERVICE_SAFE = "0x5afe000000000000000000000000000000000001"
_MASTER_SAFE = "0xd5afe00000000000000000000000000000000002"
_AGENT = "0xaaaa"
_RECOVERY_MODULE = "0x7ec0000000000000000000000000000000000003"
_NFT_HASH = "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq"
# One case per failure _try_enable_recovery_module keeps (manage._ENABLE_ERRORS).
_each_kept_enable_error = pytest.mark.parametrize(
    "error",
    [
        RecoveryModuleNotEnabledError("agent tx failed"),
        InsufficientFundsException("no gas", chain=_CHAIN),
    ],
    ids=["module-not-enabled", "master-eoa-out-of-gas"],
)


class TestEnableRecoveryModule:
    """Tests for _enable_recovery_module()."""

    def _run(
        self,
        tmp_path: Path,
        owners: t.List[str],
        module_enabled: bool = False,
        token: int = 7,
        multisig: str = _SERVICE_SAFE,
        agent_settle_error: t.Optional[Exception] = None,
        master_settle_error: t.Optional[Exception] = None,
        exec_messages_error: t.Optional[Exception] = None,
    ) -> t.Dict[str, t.Any]:
        """Run _enable_recovery_module against mocked chain state."""
        manager = _make_manager(tmp_path)
        service = _make_mock_service()
        service.agent_addresses = [_AGENT]
        chain_config = MagicMock()
        chain_config.chain_data.token = token
        chain_config.ledger_config = _make_ledger_config()
        service.chain_configs = {_CHAIN: chain_config}
        manager.wallet_manager.load.return_value.safes = {  # type: ignore
            Chain.GNOSIS: _MASTER_SAFE
        }

        sftxb = MagicMock()
        sftxb.info.return_value = {"multisig": multisig}
        sftxb.get_service_safe_owners.return_value = owners
        sftxb.get_enable_module_data.return_value = {"enable": "module"}
        sftxb.get_safe_b_exec_messages.return_value = (
            {"approve": "hash"},
            {"exec": "tx"},
        )
        agent_tx = MagicMock()
        agent_tx.add.return_value = agent_tx
        if agent_settle_error is not None:
            agent_tx.settle.side_effect = agent_settle_error
        if master_settle_error is not None:
            sftxb.new_tx.return_value.settle.side_effect = master_settle_error
        if exec_messages_error is not None:
            sftxb.get_safe_b_exec_messages.side_effect = exec_messages_error

        error: t.Optional[Exception] = None
        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch(
                "operate.services.manage.CONTRACTS",
                {Chain.GNOSIS: {"recovery_module": _RECOVERY_MODULE}},
            ),
            patch("operate.services.manage.registry_contracts") as mock_rc,
            patch(
                "operate.services.manage.EthSafeTxBuilder._new_tx",
                return_value=agent_tx,
            ) as new_agent_tx,
        ):
            mock_rc.gnosis_safe.is_module_enabled.return_value = {
                "enabled": module_enabled
            }
            try:
                manager._enable_recovery_module(
                    service_config_id="sc-test-id", chain=_CHAIN
                )
            except Exception as e:  # pylint: disable=broad-except
                error = e

        return {
            "error": error,
            "sftxb": sftxb,
            "agent_tx": agent_tx,
            "new_agent_tx": new_agent_tx,
            "keys_manager": manager.keys_manager,
        }

    @pytest.mark.parametrize(
        ("token", "multisig", "module_enabled"),
        [
            (NON_EXISTENT_TOKEN, _SERVICE_SAFE, False),
            (7, ZERO_ADDRESS, False),
            (7, _SERVICE_SAFE, True),
        ],
        ids=["not-minted", "no-safe", "already-enabled"],
    )
    def test_nothing_to_enable_sends_no_tx(
        self, tmp_path: Path, token: int, multisig: str, module_enabled: bool
    ) -> None:
        """No Safe yet, or the module already on: nothing is sent, nothing raised."""
        result = self._run(
            tmp_path,
            owners=[_AGENT],
            module_enabled=module_enabled,
            token=token,
            multisig=multisig,
        )

        assert result["error"] is None
        result["new_agent_tx"].assert_not_called()
        result["sftxb"].new_tx.assert_not_called()

    def test_agent_owned_safe_enables_module_with_agent_key(
        self, tmp_path: Path
    ) -> None:
        """The Agent Signer signs enableModule on its own Safe."""
        result = self._run(tmp_path, owners=[_AGENT])

        assert result["error"] is None
        result["keys_manager"].get_crypto_instance.assert_called_once_with(
            address=_AGENT
        )
        assert result["new_agent_tx"].call_args.kwargs["safe"] == _SERVICE_SAFE
        result["agent_tx"].add.assert_called_once_with({"enable": "module"})
        result["agent_tx"].settle.assert_called_once()
        result["sftxb"].new_tx.assert_not_called()

    def test_agent_owned_safe_raises_when_agent_tx_fails(self, tmp_path: Path) -> None:
        """A failed agent enableModule stops the flow with an actionable error."""
        cause = RuntimeError("403 for url https://rpc.example/secret-key")
        result = self._run(tmp_path, owners=[_AGENT], agent_settle_error=cause)

        error = result["error"]
        assert isinstance(error, RecoveryModuleNotEnabledError)
        assert error.__cause__ is cause
        assert _SERVICE_SAFE in str(error)
        assert f"Make sure the Agent EOA {_AGENT} holds enough gas" in str(error)
        assert "secret-key" not in str(error)
        # A stepwise teardown swaps this Safe to the Master Safe, which can enable it.
        assert isinstance(error, AgentCouldNotEnableRecoveryModuleError)

    def test_master_safe_owned_safe_enables_module_through_nested_safe_tx(
        self, tmp_path: Path
    ) -> None:
        """The Master Safe executes enableModule on the service Safe it owns."""
        result = self._run(tmp_path, owners=[_MASTER_SAFE])

        sftxb = result["sftxb"]
        assert result["error"] is None
        sftxb.get_enable_module_data.assert_called_once_with(
            module_address=_RECOVERY_MODULE, safe_address=_SERVICE_SAFE
        )
        sftxb.get_safe_b_exec_messages.assert_called_once_with(
            safe_b_address=_SERVICE_SAFE, txs=[{"enable": "module"}]
        )
        master_tx = sftxb.new_tx.return_value
        assert [c.args[0] for c in master_tx.add.call_args_list] == [
            {"approve": "hash"},
            {"exec": "tx"},
        ]
        master_tx.settle.assert_called_once()
        result["new_agent_tx"].assert_not_called()

    def test_master_safe_tx_failure_raises_actionable_error(
        self, tmp_path: Path
    ) -> None:
        """A reverted nested Safe tx surfaces as RecoveryModuleNotEnabledError."""
        cause = ChainInteractionError("reverted via https://rpc.example/secret-key")
        result = self._run(tmp_path, owners=[_MASTER_SAFE], master_settle_error=cause)

        error = result["error"]
        assert isinstance(error, RecoveryModuleNotEnabledError)
        assert error.__cause__ is cause
        assert "contact Pearl support" in str(error)
        assert "secret-key" not in str(error)
        assert not isinstance(error, AgentCouldNotEnableRecoveryModuleError)

    def test_master_safe_message_build_failure_raises_actionable_error(
        self, tmp_path: Path
    ) -> None:
        """An RPC failure while building the nested tx (nonce read) is not left raw."""
        cause = ConnectionError("read timed out")
        result = self._run(tmp_path, owners=[_MASTER_SAFE], exec_messages_error=cause)

        error = result["error"]
        assert isinstance(error, RecoveryModuleNotEnabledError)
        assert error.__cause__ is cause
        result["sftxb"].new_tx.return_value.settle.assert_not_called()

    def test_master_safe_out_of_gas_keeps_insufficient_funds_error(
        self, tmp_path: Path
    ) -> None:
        """The Master EOA gas shortfall keeps its own structured error."""
        cause = InsufficientFundsException("no gas", chain=_CHAIN)
        result = self._run(tmp_path, owners=[_MASTER_SAFE], master_settle_error=cause)

        assert result["error"] is cause

    @pytest.mark.parametrize(
        "owners",
        [["0xbbbb"], [_AGENT, _MASTER_SAFE], []],
        ids=["stranger", "agent-and-master", "none"],
    )
    def test_inconsistent_owners_raise_without_sending(
        self, tmp_path: Path, owners: t.List[str]
    ) -> None:
        """Owners that are neither the agent nor the Master Safe raise; no tx is sent."""
        result = self._run(tmp_path, owners=owners)

        error = result["error"]
        assert isinstance(error, RecoveryModuleNotEnabledError)
        assert "Contact Pearl support" in str(error)
        assert not isinstance(error, AgentCouldNotEnableRecoveryModuleError)
        result["new_agent_tx"].assert_not_called()
        result["sftxb"].new_tx.assert_not_called()

    def _run_deploy_until_staking_read(
        self, tmp_path: Path, service_state: OnChainState, error: Exception
    ) -> t.Tuple[t.Optional[BaseException], MagicMock]:
        """Run the deploy with a failing enable; stop it at the staking-program read."""

        class _ReachedStakingRead(Exception):
            """Raised by the first call after the early reuse gate."""

        manager = _make_manager(tmp_path)
        service = _make_mock_service()
        chain_config = MagicMock()
        chain_config.chain_data.token = 7
        chain_config.ledger_config = _make_ledger_config()
        service.chain_configs = {_CHAIN: chain_config}
        manager.wallet_manager.load.return_value.safes = {  # type: ignore
            Chain.GNOSIS: _MASTER_SAFE
        }
        sftxb = MagicMock()
        sftxb.info.return_value = {
            "service_state": service_state.value,
            "instances": [_AGENT],
            "multisig": _SERVICE_SAFE,
            "canonical_agents": [25],
        }

        raised: t.Optional[BaseException] = None
        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(manager, "_enable_recovery_module", side_effect=error),
            patch.object(
                manager,
                "_get_current_staking_program",
                side_effect=_ReachedStakingRead,
            ),
            patch.dict("os.environ", {}),
        ):
            try:
                manager._deploy_service_onchain_from_safe(
                    service_config_id="sc-test-id", chain=_CHAIN
                )
            except Exception as e:  # pylint: disable=broad-except
                raised = e
        assert raised is not None
        if isinstance(raised, _ReachedStakingRead):
            raised = None
        return raised, sftxb

    @_each_kept_enable_error
    def test_deploy_continues_when_module_cannot_be_enabled(
        self, tmp_path: Path, error: Exception
    ) -> None:
        """A running service still restarts when the enable fails: it reuses no Safe."""
        raised, _ = self._run_deploy_until_staking_read(
            tmp_path, OnChainState.DEPLOYED, error
        )

        assert raised is None

    @pytest.mark.parametrize(
        "service_state",
        [
            OnChainState.PRE_REGISTRATION,
            OnChainState.ACTIVE_REGISTRATION,
            OnChainState.FINISHED_REGISTRATION,
        ],
    )
    @_each_kept_enable_error
    def test_reuse_deploy_stops_before_any_bond_tx(
        self, tmp_path: Path, service_state: OnChainState, error: Exception
    ) -> None:
        """A deploy that will reuse the Safe stops before activate or register is sent."""
        raised, sftxb = self._run_deploy_until_staking_read(
            tmp_path, service_state, error
        )

        assert raised is error
        sftxb.new_tx.assert_not_called()
        sftxb.get_activate_data.assert_not_called()
        sftxb.get_register_instances_data.assert_not_called()
        sftxb.get_deploy_data_from_safe.assert_not_called()

    def _run_deployed_update(  # pylint: disable=too-many-locals
        self,
        tmp_path: Path,
        teardown_prefix: t.Optional[t.List[t.Any]],
        enable_effect: t.Any,
        terminate_effect: t.Any = None,
        cannot_unstake: bool = False,
        terminate_tears_down: bool = True,
    ) -> t.Dict[str, t.Any]:
        """Run an update of a DEPLOYED service whose first module enable fails.

        ``terminate_effect`` defaults to stopping at the stepwise terminate. A terminate
        that returns tears down unless ``terminate_tears_down`` is false: the registry
        then reads PRE_REGISTRATION. The deploy is stopped where
        ``get_deploy_data_from_safe`` would build the deploy.
        """

        class _ReachedTeardown(Exception):
            """Raised by the stepwise terminate."""

        class _ReachedDeploy(Exception):
            """Raised where the deploy data would be built."""

        manager = _make_manager(tmp_path)
        service = _make_mock_service(home_chain="ethereum")
        service.path = tmp_path
        service.description = "new description"
        service.service_public_id.return_value = "valory/trader:0.1.0"
        chain_config = MagicMock()
        chain_config.chain_data.token = 7
        chain_config.chain_data.user_params.use_staking = False
        chain_config.chain_data.user_params.nft = _NFT_HASH
        chain_config.ledger_config = _make_ledger_config()
        service.chain_configs = {_CHAIN: chain_config}
        manager.wallet_manager.load.return_value.safes = {  # type: ignore
            Chain.GNOSIS: _MASTER_SAFE
        }
        sftxb = MagicMock()
        sftxb.info.return_value = {
            "service_state": OnChainState.DEPLOYED.value,
            "instances": ["0xaaaa"],
            "multisig": _SERVICE_SAFE,
            "canonical_agents": [25],
        }
        sftxb.get_deploy_data_from_safe.side_effect = _ReachedDeploy
        terminate = MagicMock(
            side_effect=(
                _ReachedTeardown if terminate_effect is None else terminate_effect
            )
        )

        def _state(**_: t.Any) -> OnChainState:
            # A terminate that returned has torn the service down.
            torn_down = (
                terminate_tears_down
                and terminate.called
                and terminate.side_effect is not _ReachedTeardown
            )
            return OnChainState.PRE_REGISTRATION if torn_down else OnChainState.DEPLOYED

        enabled: t.List[bool] = []

        def _enable(**kwargs: t.Any) -> None:
            if isinstance(enable_effect, BaseException):
                raise enable_effect
            if callable(enable_effect):
                enable_effect(**kwargs)
            enabled.append(True)

        enable = MagicMock(side_effect=_enable)

        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(manager, "_enable_recovery_module", enable),
            patch.object(manager, "_get_current_staking_program", return_value=None),
            patch.object(
                manager,
                "_get_on_chain_metadata",
                return_value={"code_uri": "ipfs://hash", "description": "old"},
            ),
            patch.object(manager, "_get_on_chain_state", side_effect=_state),
            patch.object(
                manager, "_build_update_teardown_prefix", return_value=teardown_prefix
            ) as build_prefix,
            patch.object(
                manager, "_cannot_unstake_yet", return_value=cannot_unstake
            ) as cannot_unstake_yet,
            patch.object(manager, "terminate_service_on_chain_from_safe", terminate),
            patch.object(
                manager, "_execute_recovery_module_flow_from_safe"
            ) as recovery_flow,
            patch(
                "operate.services.manage.registry_contracts.gnosis_safe.is_module_enabled",
                # Enabled once an enable call has succeeded.
                side_effect=lambda **_: {"enabled": bool(enabled)},
            ),
            patch("operate.services.manage.get_staking_contract", return_value=None),
            patch.dict("os.environ", {}),
        ):
            try:
                manager._deploy_service_onchain_from_safe(
                    service_config_id="sc-test-id", chain=_CHAIN
                )
                raised: t.Optional[BaseException] = None
            except Exception as e:  # pylint: disable=broad-except
                raised = e
        return {
            "raised": raised,
            "terminate": terminate,
            "sftxb": sftxb,
            "enable": enable,
            "cannot_unstake_yet": cannot_unstake_yet,
            "recovery_flow": recovery_flow,
            "build_prefix": build_prefix,
            "reached_teardown": isinstance(raised, _ReachedTeardown),
            "reached_deploy": isinstance(raised, _ReachedDeploy),
        }

    @pytest.mark.parametrize(
        "error",
        [
            RecoveryModuleNotEnabledError("owners are neither"),
            InsufficientFundsException("no gas", chain=_CHAIN),
        ],
        ids=["module-not-enabled", "master-eoa-out-of-gas"],
    )
    def test_deployed_update_stops_before_a_stepwise_teardown(
        self, tmp_path: Path, error: Exception
    ) -> None:
        """A stepwise teardown that cannot fix the module stops before unstake/terminate."""
        run = self._run_deployed_update(tmp_path, None, error)

        assert run["raised"] is error
        run["terminate"].assert_not_called()
        run["sftxb"].new_tx.assert_not_called()

    @_each_kept_enable_error
    def test_deployed_update_in_the_staking_lock_window_goes_ahead(
        self, tmp_path: Path, error: Exception
    ) -> None:
        """Locked in staking, the gate lets the update reach terminate, deciding as it does."""
        run = self._run_deployed_update(tmp_path, None, error, cannot_unstake=True)

        assert run["reached_teardown"]
        # One lock read, shared by the prefix, the gate and terminate.
        run["cannot_unstake_yet"].assert_called_once()
        assert run["build_prefix"].call_args.kwargs["staking_locked"] is True
        assert run["terminate"].call_args.kwargs["staking_locked"] is True

    def test_deployed_update_reuses_the_safe_once_the_owner_swap_lets_the_master_safe_enable(
        self, tmp_path: Path
    ) -> None:
        """The agent's enable fails; terminate swaps the Safe; the Master Safe then enables it."""
        enable_calls: t.List[bool] = []

        def _enable(**_: t.Any) -> None:
            # Only the enable after the teardown (owned by the Master Safe) succeeds.
            swapped = run_terminate.called
            enable_calls.append(swapped)
            if not swapped:
                raise AgentCouldNotEnableRecoveryModuleError("agent tx failed")

        run_terminate = MagicMock(return_value=None)
        run = self._run_deployed_update(
            tmp_path, None, _enable, terminate_effect=run_terminate
        )

        assert run["reached_deploy"]
        run["terminate"].assert_called_once()
        # Deploy start (agent-owned, fails), then _resolve_safe_reuse after the swap.
        assert enable_calls == [False, True]
        assert (
            run["sftxb"].get_deploy_data_from_safe.call_args.kwargs["reuse_multisig"]
            is True
        )

    def test_deployed_update_reports_a_failed_agent_funding_after_the_teardown(
        self, tmp_path: Path
    ) -> None:
        """Terminate cannot fund the Agent EOA for the swap: its funding error is raised, not hidden."""
        funding_error = InsufficientFundsException("no gas", chain=_CHAIN)

        run = self._run_deployed_update(
            tmp_path,
            None,
            AgentCouldNotEnableRecoveryModuleError("agent tx failed"),
            terminate_effect=funding_error,
        )

        assert run["raised"] is funding_error
        run["sftxb"].get_deploy_data_from_safe.assert_not_called()

    def test_batched_update_refuses_the_reuse_before_sending_the_batch(
        self, tmp_path: Path
    ) -> None:
        """An update folded into one batch refuses the reuse before the batch settles."""
        error = RecoveryModuleNotEnabledError("agent tx failed")

        run = self._run_deployed_update(tmp_path, [({"to": "0x1"}, "unstake")], error)

        assert run["raised"] is error
        run["terminate"].assert_not_called()
        run["sftxb"].new_tx.assert_called_once()
        run["sftxb"].get_register_instances_data.assert_called_once()
        run["sftxb"].new_tx.return_value.settle.assert_not_called()
        run["sftxb"].get_deploy_data_from_safe.assert_not_called()

    @_each_kept_enable_error
    def test_try_enable_returns_the_error_instead_of_raising(
        self, tmp_path: Path, error: Exception
    ) -> None:
        """The caller keeps the error, so a restart is not blocked by it."""
        manager = _make_manager(tmp_path)
        with patch.object(manager, "_enable_recovery_module", side_effect=error):
            assert (
                manager._try_enable_recovery_module(
                    service_config_id="sc-test-id", chain=_CHAIN
                )
                is error
            )
        with patch.object(manager, "_enable_recovery_module"):
            assert (
                manager._try_enable_recovery_module(
                    service_config_id="sc-test-id", chain=_CHAIN
                )
                is None
            )

    def test_try_enable_lets_an_unexpected_error_through(self, tmp_path: Path) -> None:
        """Only the enable's own failures are kept; anything else still raises."""
        manager = _make_manager(tmp_path)
        with patch.object(
            manager, "_enable_recovery_module", side_effect=RuntimeError("bug")
        ):
            with pytest.raises(RuntimeError, match="bug"):
                manager._try_enable_recovery_module(
                    service_config_id="sc-test-id", chain=_CHAIN
                )


class TestCannotUnstakeYet:
    """Tests for _cannot_unstake_yet()."""

    @pytest.mark.parametrize(
        ("program", "can_unstake", "expected"),
        [(None, False, False), ("program", True, False), ("program", False, True)],
        ids=["not-staked", "staked-unlocked", "staked-locked"],
    )
    def test_only_a_staked_service_that_cannot_unstake_is_locked(
        self,
        tmp_path: Path,
        program: t.Optional[str],
        can_unstake: bool,
        expected: bool,
    ) -> None:
        """Locked means staked and not yet unstakeable, e.g. inside the lock window."""
        manager = _make_manager(tmp_path)
        sftxb = MagicMock()
        sftxb.can_unstake.return_value = can_unstake

        with patch(
            "operate.services.manage.get_staking_contract",
            return_value="0x5ta",
        ):
            locked = manager._cannot_unstake_yet(
                chain=_CHAIN,
                sftxb=sftxb,
                service_id=7,
                current_staking_program=program,
            )

        assert locked is expected
        if program is not None:
            sftxb.can_unstake.assert_called_once_with(
                service_id=7, staking_contract="0x5ta"
            )


class TestStopRefusedReuseBeforeTxs:
    """Tests for _stop_refused_reuse_before_txs()."""

    def test_no_error_lets_the_deploy_go_on(self) -> None:
        """Without an enable error nothing stops."""
        _stop_refused_reuse_before_txs(
            recovery_module_error=None,
            on_chain_state=OnChainState.FINISHED_REGISTRATION,
        )

    def test_a_deployed_service_is_not_stopped(self) -> None:
        """A restart reuses no Safe, so the error does not stop it."""
        _stop_refused_reuse_before_txs(
            recovery_module_error=RecoveryModuleNotEnabledError("agent tx failed"),
            on_chain_state=OnChainState.DEPLOYED,
        )

    def test_a_deployed_service_torn_down_stepwise_is_stopped(self) -> None:
        """An update that tears a running service down step by step reuses its Safe."""
        error = InsufficientFundsException("no gas", chain=_CHAIN)
        with pytest.raises(InsufficientFundsException) as exc_info:
            _stop_refused_reuse_before_txs(
                recovery_module_error=error,
                on_chain_state=OnChainState.DEPLOYED,
                tears_down_stepwise=True,
            )
        assert exc_info.value is error

    def test_a_failure_the_owner_swap_fixes_does_not_stop_a_stepwise_teardown(
        self,
    ) -> None:
        """The teardown swaps an Agent-EOA-owned Safe to the Master Safe, which can enable it."""
        _stop_refused_reuse_before_txs(
            recovery_module_error=AgentCouldNotEnableRecoveryModuleError(
                "agent tx failed"
            ),
            on_chain_state=OnChainState.DEPLOYED,
            tears_down_stepwise=True,
        )

    def test_a_failure_the_owner_swap_fixes_still_stops_a_deploy_not_yet_running(
        self,
    ) -> None:
        """Before the bond is posted nothing swaps the owner, so the deploy still stops."""
        error = AgentCouldNotEnableRecoveryModuleError("agent tx failed")
        with pytest.raises(RecoveryModuleNotEnabledError):
            _stop_refused_reuse_before_txs(
                recovery_module_error=error,
                on_chain_state=OnChainState.PRE_REGISTRATION,
            )

    def test_a_service_that_will_reuse_the_safe_is_stopped(self) -> None:
        """The enable error stops a deploy that has not posted its bond yet."""
        error = RecoveryModuleNotEnabledError("agent tx failed")
        with pytest.raises(RecoveryModuleNotEnabledError) as exc_info:
            _stop_refused_reuse_before_txs(
                recovery_module_error=error,
                on_chain_state=OnChainState.PRE_REGISTRATION,
            )
        assert exc_info.value is error


class TestResolveSafeReuse:
    """Tests for ServiceManager._resolve_safe_reuse(), called by both deploy paths."""

    def _run(
        self,
        tmp_path: Path,
        multisig: str,
        enabled_reads: t.List[bool],
        enable_error: t.Optional[Exception] = None,
    ) -> t.Dict[str, t.Any]:
        """Run _resolve_safe_reuse with mocked module reads and enable step."""
        manager = _make_manager(tmp_path)
        result: t.Dict[str, t.Any] = {"error": None, "reuse": None}
        with (
            patch(
                "operate.services.manage.CONTRACTS",
                {Chain.GNOSIS: {"recovery_module": _RECOVERY_MODULE}},
            ),
            patch("operate.services.manage.registry_contracts") as mock_rc,
            patch.object(
                manager, "_enable_recovery_module", side_effect=enable_error
            ) as enable,
        ):
            mock_rc.gnosis_safe.is_module_enabled.side_effect = [
                {"enabled": value} for value in enabled_reads
            ]
            try:
                result["reuse"] = manager._resolve_safe_reuse(
                    sftxb=MagicMock(),
                    service_config_id="sc-test-id",
                    chain=_CHAIN,
                    service_safe_address=multisig,
                )
            except Exception as e:  # pylint: disable=broad-except
                result["error"] = e
        result["enable"] = enable
        return result

    def test_no_safe_is_not_reused(self, tmp_path: Path) -> None:
        """Without an Agent Safe the deploy creates one; no module check is needed."""
        result = self._run(tmp_path, multisig=ZERO_ADDRESS, enabled_reads=[])

        assert result["reuse"] is False
        result["enable"].assert_not_called()

    def test_safe_with_module_is_reused(self, tmp_path: Path) -> None:
        """A Safe that already has the module is reused as is."""
        result = self._run(tmp_path, multisig=_SERVICE_SAFE, enabled_reads=[True])

        assert result["reuse"] is True
        result["enable"].assert_not_called()

    def test_safe_without_module_is_enabled_then_reused(self, tmp_path: Path) -> None:
        """The module is enabled for the Safe's current owners, then the Safe is reused."""
        result = self._run(
            tmp_path, multisig=_SERVICE_SAFE, enabled_reads=[False, True]
        )

        assert result["reuse"] is True
        result["enable"].assert_called_once_with(
            service_config_id="sc-test-id", chain=_CHAIN
        )

    def test_enable_failure_for_current_owners_is_raised(self, tmp_path: Path) -> None:
        """The error comes from a fresh attempt, so it matches the Safe's owners now."""
        error = RecoveryModuleNotEnabledError("owned by the Master Safe now")
        result = self._run(
            tmp_path,
            multisig=_SERVICE_SAFE,
            enabled_reads=[False],
            enable_error=error,
        )

        assert result["error"] is error

    def test_module_still_missing_raises(self, tmp_path: Path) -> None:
        """A reuse deploy is never built while the module is missing."""
        result = self._run(
            tmp_path, multisig=_SERVICE_SAFE, enabled_reads=[False, False]
        )

        error = result["error"]
        assert isinstance(error, RecoveryModuleNotEnabledError)
        assert _SERVICE_SAFE in str(error)


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


_STAKING = "0x5a4e000000000000000000000000000000000004"
_REWARD_ERC20 = "0xce11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
_OTHER_ERC20 = "0x0e40000000000000000000000000000000000005"
_RECEIVER_A = "0xa000000000000000000000000000000000000006"
_RECEIVER_B = "0xb000000000000000000000000000000000000007"
_TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)")


def _topic(address: str) -> HexBytes:
    """Left-pad an address to a 32-byte log topic."""
    return HexBytes(bytes(12) + bytes.fromhex(address[2:]))


def _transfer_log(
    token: str, sender: str, receiver: str, amount: int
) -> t.Dict[str, t.Any]:
    """An ERC-20 Transfer log shaped like a web3 receipt entry."""
    return {
        "address": token,
        "topics": [_TRANSFER_TOPIC, _topic(sender), _topic(receiver)],
        "data": HexBytes(amount.to_bytes(32, "big")),
    }


class TestClaimOnChainFromSafe:
    """Tests for claim_on_chain_from_safe()."""

    def _run(
        self,
        tmp_path: Path,
        logs: t.List[t.Dict[str, t.Any]],
        agent_safe_balance: int = 0,
        token: int = 7,
        staking_contract: t.Optional[str] = _STAKING,
        claimable: bool = True,
        sftxb: t.Optional[MagicMock] = None,
    ) -> t.Tuple[int, MagicMock]:
        """Run claim_on_chain_from_safe with a mocked claim receipt."""
        manager = _make_manager(tmp_path)
        service = _make_mock_service()
        chain_config = MagicMock()
        chain_config.chain_data.token = token
        chain_config.chain_data.multisig = _SERVICE_SAFE
        chain_config.ledger_config = _make_ledger_config()
        service.chain_configs = {_CHAIN: chain_config}
        manager.wallet_manager.load.return_value.safes = {  # type: ignore
            Chain.GNOSIS: _MASTER_SAFE
        }

        receipt = MagicMock()
        receipt.__getitem__.side_effect = {"logs": logs}.__getitem__
        if sftxb is None:
            sftxb = MagicMock()
            sftxb.get_staking_params.return_value = {"staking_token": _REWARD_ERC20}
        sftxb.staking_rewards_claimable.return_value = claimable
        sftxb.new_tx.return_value.add.return_value.settle.return_value = receipt

        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(manager, "_get_current_staking_program"),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value=staking_contract,
            ),
            patch(
                "operate.services.manage.get_asset_balance",
                return_value=agent_safe_balance,
            ),
            patch("operate.services.manage.transfer_erc20_from_safe") as sweep,
        ):
            self._last_sweep = sweep
            amount = manager.claim_on_chain_from_safe(
                service_config_id="sc-test-id", chain=_CHAIN
            )
        return amount, sweep

    def test_reward_token_read_failure_stops_before_the_claim_tx(
        self, tmp_path: Path
    ) -> None:
        """The reward token is read before claiming, so a failed read sends no claim."""
        sftxb = MagicMock()
        sftxb.get_staking_params.side_effect = RuntimeError("rpc down")

        with pytest.raises(RuntimeError, match="rpc down"):
            self._run(tmp_path, logs=[], sftxb=sftxb)

        sftxb.new_tx.return_value.add.return_value.settle.assert_not_called()

    def test_single_transfer_receipt_returns_its_amount(self, tmp_path: Path) -> None:
        """A claim paying one receiver returns that transfer's amount."""
        logs = [
            {
                "address": _MASTER_SAFE,
                "topics": [HexBytes(b"\x01" * 32)],
                "data": HexBytes(b""),
            },
            _transfer_log(_REWARD_ERC20, _STAKING, _SERVICE_SAFE, 10**18),
        ]

        amount, _ = self._run(tmp_path, logs)

        assert amount == 10**18

    def test_multi_transfer_receipt_sums_reward_transfers_from_staking(
        self, tmp_path: Path
    ) -> None:
        """Every reward-token transfer from the staking contract counts; nothing else does."""
        logs = [
            _transfer_log(_REWARD_ERC20, _STAKING, _RECEIVER_A, 600),
            _transfer_log(_REWARD_ERC20, _MASTER_SAFE, _RECEIVER_A, 10_000),
            _transfer_log(_OTHER_ERC20, _STAKING, _RECEIVER_A, 20_000),
            {
                "address": _REWARD_ERC20,
                "topics": [
                    _TRANSFER_TOPIC,
                    _topic(_STAKING),
                    _topic(_RECEIVER_A),
                    HexBytes((5).to_bytes(32, "big")),
                ],
                "data": HexBytes((30_000).to_bytes(32, "big")),
            },
            {
                "address": _REWARD_ERC20,
                "topics": [
                    Web3.keccak(text="Approval(address,address,uint256)"),
                    _topic(_STAKING),
                    _topic(_RECEIVER_A),
                ],
                "data": HexBytes((40_000).to_bytes(32, "big")),
            },
            _transfer_log(_REWARD_ERC20.lower(), _STAKING, _RECEIVER_B, 400),
        ]

        amount, _ = self._run(tmp_path, logs)

        assert amount == 1_000

    def test_receipt_without_reward_transfer_returns_zero(self, tmp_path: Path) -> None:
        """No transfer from the staking contract means nothing was claimed."""
        amount, _ = self._run(tmp_path, logs=[])

        assert amount == 0

    def test_agent_safe_balance_is_swept_to_master_safe(self, tmp_path: Path) -> None:
        """Rewards paid into the Agent Safe are still moved to the Master Safe."""
        logs = [_transfer_log(_REWARD_ERC20, _STAKING, _SERVICE_SAFE, 700)]

        amount, sweep = self._run(tmp_path, logs, agent_safe_balance=900)

        assert amount == 700
        sweep_kwargs = sweep.call_args.kwargs
        assert sweep_kwargs["safe"] == _SERVICE_SAFE
        assert sweep_kwargs["token"] == _REWARD_ERC20
        assert sweep_kwargs["to"] == _MASTER_SAFE
        assert sweep_kwargs["amount"] == 900

    def test_empty_agent_safe_is_not_swept(self, tmp_path: Path) -> None:
        """At zero Agent Safe balance the sweep does nothing."""
        logs = [_transfer_log(_REWARD_ERC20, _STAKING, _RECEIVER_A, 700)]

        amount, sweep = self._run(tmp_path, logs, agent_safe_balance=0)

        assert amount == 700
        sweep.assert_not_called()

    @pytest.mark.parametrize(
        "overrides",
        [
            {"token": NON_EXISTENT_TOKEN},
            {"staking_contract": None},
            {"claimable": False},
        ],
        ids=["not-minted", "no-staking-contract", "nothing-claimable"],
    )
    def test_returns_zero_without_a_successful_claim(
        self, tmp_path: Path, overrides: t.Dict[str, t.Any]
    ) -> None:
        """Nothing to claim returns 0 and sweeps nothing."""
        logs = [_transfer_log(_REWARD_ERC20, _STAKING, _RECEIVER_A, 700)]

        amount, sweep = self._run(tmp_path, logs, agent_safe_balance=900, **overrides)

        assert amount == 0
        sweep.assert_not_called()

    def test_reverted_claim_raises_and_sweeps_nothing(self, tmp_path: Path) -> None:
        """settle() raises on a reverted claim, so nothing is swept."""
        sftxb = MagicMock()
        sftxb.get_staking_params.return_value = {"staking_token": _REWARD_ERC20}
        sftxb.new_tx.return_value.add.return_value.settle.side_effect = (
            ChainInteractionError("Safe transaction 0xabc reverted on-chain.")
        )

        with pytest.raises(ChainInteractionError):
            self._run(tmp_path, logs=[], agent_safe_balance=900, sftxb=sftxb)

        self._last_sweep.assert_not_called()


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

    def test_swap_runs_when_recovery_module_cannot_be_enabled(
        self, tmp_path: Path
    ) -> None:
        """The Safe owner swap still runs, so the next deploy can enable the module."""
        manager, service, sftxb = self._setup_manager(tmp_path)
        sftxb.get_service_safe_owners.return_value = ["0xAgentAddr"]

        with (
            patch.object(manager, "load", return_value=service),
            patch.object(manager, "get_eth_safe_tx_builder", return_value=sftxb),
            patch.object(manager, "_get_current_staking_program", return_value=None),
            patch.object(manager, "_terminate_and_unbond"),
            patch("operate.services.manage.get_staking_contract", return_value=None),
            patch("operate.services.manage.get_asset_balance", return_value=10**18),
            patch.object(
                manager,
                "_enable_recovery_module",
                side_effect=RecoveryModuleNotEnabledError("agent tx failed"),
            ),
            patch.object(manager, "logger") as logger,
        ):
            manager.terminate_service_on_chain_from_safe(
                service_config_id="sc-test", chain=_CHAIN
            )

        sftxb.swap.assert_called_once()
        assert sftxb.swap.call_args.kwargs["new_owner_address"] == "0xMasterSafe"
        assert logger.error.call_args.kwargs["exc_info"] is True


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


def _make_staking_service(
    use_staking: bool = True, chains: t.Optional[t.List[str]] = None
) -> MagicMock:
    """Create a mock service with staking-enabled chain configs."""
    service = _make_mock_service()
    service.chain_configs = {
        chain: MagicMock(
            **{
                "ledger_config.rpc": _RPC,
                "ledger_config.chain": Chain(chain),
                "chain_data.token": 32,
                "chain_data.user_params.use_staking": use_staking,
            }
        )
        for chain in (chains or [_CHAIN])
    }
    return service


class TestIsServiceEvictedOnChain:
    """Tests for is_service_evicted_on_chain()."""

    @staticmethod
    def _patched_staking(
        staking_state: StakingState, unstaking_error: t.Optional[Exception] = None
    ) -> MagicMock:
        """Build a StakingManager mock with the given on-chain answers."""
        staking_manager = MagicMock()
        staking_manager.staking_state.return_value = staking_state
        staking_manager.check_if_unstaking_possible.side_effect = unstaking_error
        return staking_manager

    def _run(
        self,
        tmp_path: Path,
        service: MagicMock,
        staking_manager: MagicMock,
        staking_program: t.Optional[str] = "staking_v1",
    ) -> t.Dict[str, t.Any]:
        """Run is_service_evicted_on_chain against mocked chain reads."""
        manager = _make_manager(tmp_path)
        manager.load = MagicMock(return_value=service)  # type: ignore[method-assign]
        with (
            patch(
                "operate.services.manage.StakingManager", return_value=staking_manager
            ),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xstaking",
            ),
            patch.object(
                ServiceManager,
                "_get_current_staking_program",
                return_value=staking_program,
            ),
        ):
            return manager.is_service_evicted_on_chain(service_config_id="sc-test-id")

    def test_skips_chains_that_do_not_stake(self, tmp_path: Path) -> None:
        """A chain with use_staking off cannot be evicted."""
        result = self._run(
            tmp_path,
            _make_staking_service(use_staking=False),
            self._patched_staking(StakingState.EVICTED),
        )

        assert result == {}

    def test_unstaked_service_is_not_evicted(self, tmp_path: Path) -> None:
        """No current staking program means nothing to reconcile."""
        result = self._run(
            tmp_path,
            _make_staking_service(),
            self._patched_staking(StakingState.EVICTED),
            staking_program=None,
        )

        assert result == {_CHAIN: StakingEvictionState.NOT_EVICTED}

    def test_staked_service_is_not_evicted(self, tmp_path: Path) -> None:
        """A healthy staked service reports not evicted."""
        result = self._run(
            tmp_path,
            _make_staking_service(),
            self._patched_staking(StakingState.STAKED),
        )

        assert result == {_CHAIN: StakingEvictionState.NOT_EVICTED}

    def test_evicted_and_unstakable(self, tmp_path: Path) -> None:
        """Past minStakingDuration, the eviction can be cleared."""
        result = self._run(
            tmp_path,
            _make_staking_service(),
            self._patched_staking(StakingState.EVICTED),
        )

        assert result == {_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE}

    def test_evicted_and_locked(self, tmp_path: Path) -> None:
        """Inside minStakingDuration with rewards outstanding, it cannot."""
        result = self._run(
            tmp_path,
            _make_staking_service(),
            self._patched_staking(
                StakingState.EVICTED,
                unstaking_error=ValueError("Service cannot be unstaked yet."),
            ),
        )

        assert result == {_CHAIN: StakingEvictionState.EVICTED_LOCKED}

    def test_reports_every_staking_chain(self, tmp_path: Path) -> None:
        """A multi-chain service is answered per chain."""
        result = self._run(
            tmp_path,
            _make_staking_service(chains=[_CHAIN, "base"]),
            self._patched_staking(StakingState.EVICTED),
        )

        assert result == {
            _CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE,
            "base": StakingEvictionState.EVICTED_UNSTAKABLE,
        }

    def test_loads_no_wallet(self, tmp_path: Path) -> None:
        """The read runs on a background thread where no password may be set."""
        manager = _make_manager(tmp_path)
        manager.load = MagicMock(  # type: ignore[method-assign]
            return_value=_make_staking_service()
        )
        manager.get_eth_safe_tx_builder = MagicMock()  # type: ignore[method-assign]

        with (
            patch(
                "operate.services.manage.StakingManager",
                return_value=self._patched_staking(StakingState.EVICTED),
            ),
            patch(
                "operate.services.manage.get_staking_contract",
                return_value="0xstaking",
            ),
            patch.object(
                ServiceManager,
                "_get_current_staking_program",
                return_value="staking_v1",
            ),
        ):
            manager.is_service_evicted_on_chain(service_config_id="sc-test-id")

        manager.get_eth_safe_tx_builder.assert_not_called()
        manager.wallet_manager.load.assert_not_called()


class TestReconcileStakingForRestart:
    """Tests for reconcile_staking_for_restart()."""

    @staticmethod
    def _manager(
        tmp_path: Path,
        eviction_states: t.Dict[str, StakingEvictionState],
        after_restake: t.Optional[t.Dict[str, StakingEvictionState]] = None,
    ) -> ServiceManager:
        """Create a manager whose eviction read returns the given states.

        The reconciliation re-reads the chain after delegating, so the second
        read reports what the re-stake actually achieved — by default, an
        eviction that cleared.
        """
        manager = _make_manager(tmp_path)
        cleared = (
            after_restake
            if after_restake is not None
            else {chain: StakingEvictionState.NOT_EVICTED for chain in eviction_states}
        )
        first_read = iter([eviction_states])
        manager.is_service_evicted_on_chain = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda **_kwargs: next(first_read, cleared)
        )
        manager.stake_service_on_chain_from_safe = MagicMock(  # type: ignore[method-assign]
            return_value=True
        )
        return manager

    def test_not_evicted_touches_nothing(self, tmp_path: Path) -> None:
        """A healthy service must not reach a wallet at all."""
        manager = self._manager(tmp_path, {_CHAIN: StakingEvictionState.NOT_EVICTED})

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.NOTHING_TO_DO
        manager.stake_service_on_chain_from_safe.assert_not_called()  # type: ignore[attr-defined]

    def test_unstakable_eviction_is_delegated(self, tmp_path: Path) -> None:
        """The existing staking flow performs the unstake and the re-stake."""
        manager = self._manager(
            tmp_path, {_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE}
        )

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.RECONCILED
        manager.stake_service_on_chain_from_safe.assert_called_once_with(  # type: ignore[attr-defined]
            service_config_id="sc-test-id", chain=_CHAIN, blocking=False
        )

    def test_reconciled_is_verified_against_the_chain(self, tmp_path: Path) -> None:
        """Having run the staking flow is not proof the eviction cleared.

        It returns without sending anything when the service is not on-chain
        DEPLOYED, and its stake branch also needs rewards and a free slot.
        Reporting RECONCILED there would redeploy into the same eviction and
        clear the failfast budget on every cycle.
        """
        manager = self._manager(
            tmp_path,
            {_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE},
            after_restake={_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE},
        )

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.EVICTED_CANNOT_RESTAKE
        manager.stake_service_on_chain_from_safe.assert_called_once()  # type: ignore[attr-defined]

    def test_locked_eviction_sends_no_transaction(self, tmp_path: Path) -> None:
        """The staking flow is a no-op for a locked eviction; skip the wallet load."""
        manager = self._manager(tmp_path, {_CHAIN: StakingEvictionState.EVICTED_LOCKED})

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.EVICTED_CANNOT_RESTAKE
        manager.stake_service_on_chain_from_safe.assert_not_called()  # type: ignore[attr-defined]

    def test_one_locked_chain_spends_no_gas_on_the_others(self, tmp_path: Path) -> None:
        """The agent exits while any staking chain is evicted.

        Re-staking the chains that can be cleared cannot bring it up before the
        locked window ends, so nothing is sent.
        """
        manager = self._manager(
            tmp_path,
            {
                _CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE,
                "base": StakingEvictionState.EVICTED_LOCKED,
            },
        )

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.EVICTED_CANNOT_RESTAKE
        manager.stake_service_on_chain_from_safe.assert_not_called()  # type: ignore[attr-defined]

    def test_lock_contention_is_reported_as_skipped(self, tmp_path: Path) -> None:
        """A start already reconciling this chain is doing the same work."""
        manager = self._manager(
            tmp_path, {_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE}
        )
        manager.stake_service_on_chain_from_safe.return_value = False  # type: ignore[attr-defined]

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.SKIPPED

    def test_failing_read_returns_an_outcome_not_an_exception(
        self, tmp_path: Path
    ) -> None:
        """A chain read must never wedge the health checker's restart loop."""
        manager = self._manager(tmp_path, {})
        manager.is_service_evicted_on_chain.side_effect = RuntimeError(  # type: ignore[attr-defined]
            "rpc down"
        )

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.FAILED

    def test_failing_verification_read_returns_failed(self, tmp_path: Path) -> None:
        """An RPC that dies after the re-stake leaves the outcome unknown, not good."""
        manager = self._manager(
            tmp_path, {_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE}
        )
        manager.is_service_evicted_on_chain.side_effect = [  # type: ignore[attr-defined]
            {_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE},
            RuntimeError("rpc down"),
        ]

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.FAILED

    def test_failing_restake_returns_an_outcome_not_an_exception(
        self, tmp_path: Path
    ) -> None:
        """Same for a transaction that reverts."""
        manager = self._manager(
            tmp_path, {_CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE}
        )
        manager.stake_service_on_chain_from_safe.side_effect = RuntimeError(  # type: ignore[attr-defined]
            "reverted"
        )

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.FAILED

    def test_a_failing_chain_does_not_abandon_the_others(self, tmp_path: Path) -> None:
        """Chains settle on their own Safes, so one revert must not skip the rest."""
        manager = self._manager(
            tmp_path,
            {
                _CHAIN: StakingEvictionState.EVICTED_UNSTAKABLE,
                "base": StakingEvictionState.EVICTED_UNSTAKABLE,
            },
        )
        manager.stake_service_on_chain_from_safe.side_effect = [  # type: ignore[attr-defined]
            RuntimeError("reverted"),
            True,
        ]

        outcome = manager.reconcile_staking_for_restart(service_config_id="sc-test-id")

        assert outcome == StakingReconcileOutcome.FAILED
        assert [
            call.kwargs["chain"]
            for call in manager.stake_service_on_chain_from_safe.call_args_list  # type: ignore[attr-defined]
        ] == [_CHAIN, "base"]


class TestChainTransactionLock:
    """Tests for the per-chain lock serialising master-Safe transactions."""

    def test_lock_is_per_chain_and_stable(self, tmp_path: Path) -> None:
        """One lock per chain, reused across calls.

        Keyed on the chain because that is what the master Safe is scoped to:
        two services staking on Gnosis share a Safe and therefore a nonce, and
        one service staking on Gnosis and Base does not.
        """
        manager = _make_manager(tmp_path)

        assert manager.get_chain_tx_lock(_CHAIN) is manager.get_chain_tx_lock(_CHAIN)
        assert manager.get_chain_tx_lock(_CHAIN) is not manager.get_chain_tx_lock(
            "base"
        )

    def test_blocking_caller_runs_the_staking_flow(self, tmp_path: Path) -> None:
        """The deploy path must never silently skip staking."""
        manager = _make_manager(tmp_path)
        manager._stake_service_on_chain_from_safe_unlocked = MagicMock()  # type: ignore[method-assign]

        assert (
            manager.stake_service_on_chain_from_safe(
                service_config_id="sc-a", chain=_CHAIN
            )
            is True
        )
        manager._stake_service_on_chain_from_safe_unlocked.assert_called_once_with(  # type: ignore[attr-defined]
            service_config_id="sc-a", chain=_CHAIN
        )

    def test_non_blocking_caller_skips_on_contention(self, tmp_path: Path) -> None:
        """A background reconciliation must not queue behind a foreground start."""
        manager = _make_manager(tmp_path)
        manager._stake_service_on_chain_from_safe_unlocked = MagicMock()  # type: ignore[method-assign]

        with manager.get_chain_tx_lock(_CHAIN):
            ran = manager.stake_service_on_chain_from_safe(
                service_config_id="sc-a", chain=_CHAIN, blocking=False
            )

        assert ran is False
        manager._stake_service_on_chain_from_safe_unlocked.assert_not_called()  # type: ignore[attr-defined]

    def test_another_service_on_the_same_chain_is_blocked(self, tmp_path: Path) -> None:
        """The Safe is shared, so a different service is still a collision."""
        manager = _make_manager(tmp_path)
        manager._stake_service_on_chain_from_safe_unlocked = MagicMock()  # type: ignore[method-assign]

        with manager.get_chain_tx_lock(_CHAIN):
            ran = manager.stake_service_on_chain_from_safe(
                service_config_id="sc-b", chain=_CHAIN, blocking=False
            )

        assert ran is False

    def test_another_chain_is_not_blocked(self, tmp_path: Path) -> None:
        """Different chain, different Safe, different nonce."""
        manager = _make_manager(tmp_path)
        manager._stake_service_on_chain_from_safe_unlocked = MagicMock()  # type: ignore[method-assign]

        with manager.get_chain_tx_lock(_CHAIN):
            ran = manager.stake_service_on_chain_from_safe(
                service_config_id="sc-a", chain="base", blocking=False
            )

        assert ran is True

    def test_lock_is_released_when_the_staking_flow_raises(
        self, tmp_path: Path
    ) -> None:
        """A reverted transaction must not wedge every later start."""
        manager = _make_manager(tmp_path)
        manager._stake_service_on_chain_from_safe_unlocked = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("reverted")
        )

        with pytest.raises(RuntimeError, match="reverted"):
            manager.stake_service_on_chain_from_safe(
                service_config_id="sc-a", chain=_CHAIN
            )

        assert manager.get_chain_tx_lock(_CHAIN).acquire(blocking=False) is True

    def test_the_whole_onchain_deploy_sequence_holds_the_lock(
        self, tmp_path: Path
    ) -> None:
        """Registration, bonding and funding send from the same Safe as staking.

        Locking only the staking leaf would leave a reconciliation free to
        interleave with the rest of the deploy path.
        """
        manager = _make_manager(tmp_path)
        service = MagicMock()
        service.chain_configs = {_CHAIN: MagicMock()}
        manager.load = MagicMock(return_value=service)  # type: ignore[method-assign]
        held = []

        def _deploy(**_kwargs: object) -> None:
            held.append(
                manager.get_chain_tx_lock(_CHAIN).acquire(blocking=False) is False
            )

        manager._deploy_service_onchain_from_safe = MagicMock(  # type: ignore[method-assign]
            side_effect=_deploy
        )

        manager.deploy_service_onchain_from_safe(service_config_id="sc-a")

        assert held == [True]
        assert manager.get_chain_tx_lock(_CHAIN).acquire(blocking=False) is True

    def test_unstaking_is_serialised_with_staking(self, tmp_path: Path) -> None:
        """`unstake_service_on_chain_from_safe` is public and reachable on its own.

        `quickstart/reset_staking.py` calls it directly, from the same Safe.
        """
        manager = _make_manager(tmp_path)
        manager._unstake_service_on_chain_from_safe_unlocked = MagicMock()  # type: ignore[method-assign]
        manager._stake_service_on_chain_from_safe_unlocked = MagicMock()  # type: ignore[method-assign]

        def _unstake(**_kwargs: object) -> None:
            assert (
                manager.stake_service_on_chain_from_safe(
                    service_config_id="sc-b", chain=_CHAIN, blocking=False
                )
                is False
            )

        manager._unstake_service_on_chain_from_safe_unlocked.side_effect = (  # type: ignore[attr-defined]
            _unstake
        )

        manager.unstake_service_on_chain_from_safe(
            service_config_id="sc-a", chain=_CHAIN, staking_program_id="staking_v1"
        )

        manager._unstake_service_on_chain_from_safe_unlocked.assert_called_once_with(  # type: ignore[attr-defined]
            service_config_id="sc-a",
            chain=_CHAIN,
            staking_program_id="staking_v1",
            force=False,
        )
