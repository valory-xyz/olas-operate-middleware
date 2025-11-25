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

"""Tests for services.service module."""

import random
import typing as t
from pathlib import Path

import pytest
from deepdiff import DeepDiff
from fastapi.testclient import TestClient

from operate.cli import OperateApp, create_app
from operate.constants import ZERO_ADDRESS
from operate.ledger import CHAINS, get_default_ledger_api
from operate.ledger.profiles import DUST, OLAS, USDC
from operate.operate_types import Chain, OnChainState, ServiceTemplate
from operate.services.manage import ServiceManager
from operate.utils.gnosis import get_asset_balance

from .test_services_service import DEFAULT_CONFIG_KWARGS
from tests.conftest import (
    OnTestnet,
    OperateTestEnv,
    tenderly_add_balance,
    tenderly_increase_time,
)
from tests.constants import LOGGER, OPERATE_TEST, RUNNING_IN_CI


# TODO Move this to test_services_funding.py once feat/funding_v2 branch is merged
AGENT_FUNDING_ASSETS: t.Dict[Chain, t.Dict[str, int]] = {}
SERVICE_SAFE_FUNDING_ASSETS: t.Dict[Chain, t.Dict[str, int]] = {}

for _chain in set(CHAINS) - {Chain.SOLANA}:
    AGENT_FUNDING_ASSETS[_chain] = {
        ZERO_ADDRESS: random.randint(int(1e18), int(2e18)),  # nosec B311
    }
    SERVICE_SAFE_FUNDING_ASSETS[_chain] = {
        ZERO_ADDRESS: random.randint(int(1e18), int(2e18)),  # nosec B311
        OLAS[_chain]: random.randint(int(100e6), int(200e6)),  # nosec B311
        USDC[_chain]: random.randint(int(100e6), int(200e6)),  # nosec B311
    }


def get_template(**kwargs: t.Any) -> ServiceTemplate:
    """get_template"""

    return {
        "name": kwargs.get("name"),
        "hash": kwargs.get("hash"),
        "description": kwargs.get("description"),
        "image": "https://image_url",
        "service_version": "",
        "agent_release": kwargs.get("agent_release"),
        "home_chain": "gnosis",
        "configurations": {
            "gnosis": {
                "staking_program_id": kwargs.get("staking_program_id"),
                "nft": kwargs.get("nft"),
                "rpc": "http://localhost:8545",
                "threshold": kwargs.get("threshold"),
                "agent_id": kwargs.get("agent_id"),
                "use_staking": kwargs.get("use_staking"),
                "use_mech_marketplace": kwargs.get("use_mech_marketplace"),
                "cost_of_bond": kwargs.get("cost_of_bond"),
                "fund_requirements": {
                    "0x0000000000000000000000000000000000000000": {
                        "agent": kwargs.get("fund_requirements_agent"),
                        "safe": kwargs.get("fund_requirements_safe"),
                    }
                },
                "fallback_chain_params": {},
            }
        },
        "env_variables": {
            "VAR1": {
                "name": "var1_name",
                "description": "var1_description",
                "value": "var1_value",
                "provision_type": "var1_provision_type",
            },
            "VAR2": {
                "name": "var2_name",
                "description": "var2_description",
                "value": "var2_value",
                "provision_type": "var2_provision_type",
            },
        },
    }


class TestServiceManager(OnTestnet):
    """Tests for services.manager.ServiceManager class."""

    @pytest.mark.parametrize("update_new_var", [True, False])
    @pytest.mark.parametrize("update_update_var", [True, False])
    @pytest.mark.parametrize("update_name", [True, False])
    @pytest.mark.parametrize("update_description", [True, False])
    @pytest.mark.parametrize("update_hash", [True, False])
    @pytest.mark.parametrize("update_release", [True, False])
    def test_service_manager_partial_update(
        self,
        update_new_var: bool,
        update_update_var: bool,
        update_name: bool,
        update_description: bool,
        update_hash: bool,
        update_release: bool,
        tmp_path: Path,
        password: str,
    ) -> None:
        """Test operate.service_manager().update()"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        service_manager = operate.service_manager()
        service_template = get_template(**DEFAULT_CONFIG_KWARGS)
        service = service_manager.create(service_template)
        service_config_id = service.service_config_id
        service_json = service_manager.load(service_config_id).json

        new_hash = "bafybeicts6zhavxzz2rxahz3wzs2pzamoq64n64wp4q4cdanfuz7id6c2q"
        VAR2_updated_attributes = {
            "name": "var2_name_updated",
            "description": "var2_description_updated",
            "value": "var2_value_updated",
            "provision_type": "var2_provision_type_updated",
            "extra_attr": "extra_val",
        }

        VAR3_attributes = {
            "name": "var3_name",
            "description": "var3_description",
            "value": "var3_value",
            "provision_type": "var3_provision_type",
        }

        # Partial update
        update_template: t.Dict = {}
        expected_service_json = service_json.copy()

        if update_new_var:
            update_template["env_variables"] = update_template.get("env_variables", {})
            update_template["env_variables"]["VAR3"] = VAR3_attributes
            expected_service_json["env_variables"]["VAR3"] = VAR3_attributes

        if update_update_var:
            update_template["env_variables"] = update_template.get("env_variables", {})
            update_template["env_variables"]["VAR2"] = VAR2_updated_attributes
            expected_service_json["env_variables"]["VAR2"] = VAR2_updated_attributes

        if update_name:
            update_template["name"] = "name_updated"
            expected_service_json["name"] = "name_updated"

        if update_description:
            update_template["description"] = "description_updated"
            expected_service_json["description"] = "description_updated"

        if update_hash:
            update_template["hash"] = new_hash
            expected_service_json["hash"] = new_hash

        if update_release:
            update_template["agent_release"] = {
                "is_aea": True,
                "repository": {
                    "owner": "valory-xyz",
                    "name": "optimus",
                    "version": "v0.0.1002",
                },
            }
            expected_service_json["agent_release"] = update_template["agent_release"]

        service_manager.update(
            service_config_id=service_config_id,
            service_template=update_template,
            allow_different_service_public_id=False,
            partial_update=True,
        )
        service_json = service_manager.load(service_config_id).json

        if update_hash:
            timestamp = max(service_json["hash_history"].keys())
            expected_service_json["hash_history"][timestamp] = new_hash

        diff = DeepDiff(service_json, expected_service_json)
        if diff:
            print(diff)

        assert not diff, "Updated service does not match expected service."

    @pytest.mark.parametrize("update_new_var", [True, False])
    @pytest.mark.parametrize("update_update_var", [True, False])
    @pytest.mark.parametrize("update_delete_var", [True, False])
    @pytest.mark.parametrize("update_name", [True, False])
    @pytest.mark.parametrize("update_description", [True, False])
    @pytest.mark.parametrize("update_hash", [True, False])
    def test_service_manager_update(
        self,
        update_new_var: bool,
        update_update_var: bool,
        update_delete_var: bool,
        update_name: bool,
        update_description: bool,
        update_hash: bool,
        tmp_path: Path,
        password: str,
    ) -> None:
        """Test operate.service_manager().update()"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        service_manager = operate.service_manager()
        service_template = get_template(**DEFAULT_CONFIG_KWARGS)
        service = service_manager.create(service_template)
        service_config_id = service.service_config_id
        service_json = service_manager.load(service_config_id).json

        new_hash = "bafybeicts6zhavxzz2rxahz3wzs2pzamoq64n64wp4q4cdanfuz7id6c2q"
        VAR2_updated_attributes = {
            "name": "var2_name_updated",
            "description": "var2_description_updated",
            "value": "var2_value_updated",
            "provision_type": "var2_provision_type_updated",
            "extra_attr": "extra_val",
        }

        VAR3_attributes = {
            "name": "var3_name",
            "description": "var3_description",
            "value": "var3_value",
            "provision_type": "var3_provision_type",
        }

        # Partial update
        update_template: t.Dict = service_template.copy()
        expected_service_json = service_json.copy()

        if update_new_var:
            update_template["env_variables"] = update_template.get("env_variables", {})
            update_template["env_variables"]["VAR3"] = VAR3_attributes
            expected_service_json["env_variables"]["VAR3"] = VAR3_attributes

        if update_update_var:
            update_template["env_variables"] = update_template.get("env_variables", {})
            update_template["env_variables"]["VAR2"] = VAR2_updated_attributes
            expected_service_json["env_variables"]["VAR2"] = VAR2_updated_attributes

        if update_delete_var:
            update_template["env_variables"] = update_template.get("env_variables", {})
            del update_template["env_variables"]["VAR1"]
            del expected_service_json["env_variables"]["VAR1"]

        if update_name:
            update_template["name"] = "name_updated"
            expected_service_json["name"] = "name_updated"

        if update_description:
            update_template["description"] = "description_updated"
            expected_service_json["description"] = "description_updated"

        if update_hash:
            update_template["hash"] = new_hash
            expected_service_json["hash"] = new_hash

        service_manager.update(
            service_config_id=service_config_id,
            service_template=update_template,
            allow_different_service_public_id=False,
            partial_update=False,
        )
        service_json = service_manager.load(service_config_id).json

        if update_hash:
            timestamp = max(service_json["hash_history"].keys())
            expected_service_json["hash_history"][timestamp] = new_hash

        diff = DeepDiff(service_json, expected_service_json)
        if diff:
            print(diff)

        assert not diff, "Updated service does not match expected service."

    @pytest.mark.parametrize(
        (
            "topup1",
            "threshold1",
            "balance1",
            "topup2",
            "threshold2",
            "balance2",
            "topup3",
            "threshold3",
            "balance3",
            "sender_topup",
            "sender_threshold",
            "sender_balance",
            "minimum_refill_required",
            "recommended_refill_required",
        ),
        [
            (10, 5, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 3, 8),
            (10, 5, 1, 10, 5, 8, 0, 0, 0, 0, 0, 1, 3, 8),
            (10, 5, 8, 10, 5, 1, 0, 0, 0, 0, 0, 1, 3, 8),
            (10, 5, 8, 10, 5, 1, 10, 5, 1, 0, 0, 1, 7, 17),
            (10, 5, 6, 10, 5, 6, 0, 0, 0, 0, 0, 1, 0, 0),
            (10, 5, 2, 20, 10, 7, 0, 0, 0, 0, 0, 4, 2, 17),
            (10, 5, 2, 20, 10, 3, 0, 0, 0, 0, 0, 4, 6, 21),
            (15, 15, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5, 5),
            (10, 5, 1, 0, 0, 0, 0, 0, 0, 10, 5, 1, 8, 18),
            (10, 5, 1, 10, 5, 8, 0, 0, 0, 10, 5, 1, 8, 18),
            (10, 5, 8, 10, 5, 1, 0, 0, 0, 10, 5, 1, 8, 18),
            (10, 5, 8, 10, 5, 1, 10, 5, 1, 10, 5, 1, 12, 27),
            (10, 5, 6, 10, 5, 6, 0, 0, 0, 10, 5, 1, 4, 9),
            (10, 5, 2, 20, 10, 7, 0, 0, 0, 10, 5, 4, 7, 27),
            (10, 5, 2, 20, 10, 3, 0, 0, 0, 10, 5, 4, 11, 31),
            (15, 15, 10, 0, 0, 0, 0, 0, 0, 10, 5, 0, 10, 15),
            (10, 5, 8, 10, 5, 1, 10, 5, 1, 10, 5, 28, 0, 0),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 10, 5, 3, 2, 7),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 10, 5, 7, 0, 0),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 10, 5, 11, 0, 0),
            (10, 5, 2, 0, 0, 0, 0, 0, 0, 10, 5, 3, 5, 15),
            (10, 5, 2, 0, 0, 0, 0, 0, 0, 10, 5, 7, 1, 11),
            (10, 5, 2, 0, 0, 0, 0, 0, 0, 10, 5, 11, 0, 7),
            (10, 5, 7, 0, 0, 0, 0, 0, 0, 10, 5, 3, 2, 7),
            (10, 5, 7, 0, 0, 0, 0, 0, 0, 10, 5, 7, 0, 0),
            (10, 5, 7, 0, 0, 0, 0, 0, 0, 10, 5, 11, 0, 0),
            (10, 5, 11, 0, 0, 0, 0, 0, 0, 10, 5, 3, 2, 7),
            (10, 5, 11, 0, 0, 0, 0, 0, 0, 10, 5, 7, 0, 0),
            (10, 5, 11, 0, 0, 0, 0, 0, 0, 10, 5, 11, 0, 0),
            (10, 5, 2, 0, 0, 0, 0, 0, 0, 10, 5, 1, 7, 17),
            (100, 50, 20, 0, 0, 0, 0, 0, 0, 10, 5, 1, 34, 89),
            (100, 50, 20, 0, 0, 0, 0, 0, 0, 10, 5, 7, 28, 83),
            (100, 50, 20, 0, 0, 0, 0, 0, 0, 10, 5, 11, 24, 79),
        ],
    )
    def test_service_manager_compute_refill_requirements(
        self,
        topup1: int,
        threshold1: int,
        balance1: int,
        topup2: int,
        threshold2: int,
        balance2: int,
        topup3: int,
        threshold3: int,
        balance3: int,
        sender_topup: int,
        sender_threshold: int,
        sender_balance: int,
        minimum_refill_required: int,
        recommended_refill_required: int,
    ) -> None:
        """Test operate.service_manager()._compute_refill_requirements()"""

        asset_funding_values = {}
        asset_funding_values["0x1"] = {
            "topup": topup1,
            "threshold": threshold1,
            "balance": balance1,
        }
        asset_funding_values["0x2"] = {
            "topup": topup2,
            "threshold": threshold2,
            "balance": balance2,
        }
        asset_funding_values["0x3"] = {
            "topup": topup3,
            "threshold": threshold3,
            "balance": balance3,
        }

        expected_result = {
            "minimum_refill": minimum_refill_required,
            "recommended_refill": recommended_refill_required,
        }
        result = ServiceManager._compute_refill_requirement(
            asset_funding_values=asset_funding_values,
            sender_topup=sender_topup,
            sender_threshold=sender_threshold,
            sender_balance=sender_balance,
        )

        diff = DeepDiff(result, expected_result)
        if diff:
            print(diff)

        assert not diff, "Failed to compute refill requirements."

    @pytest.mark.parametrize(
        (
            "topup1",
            "threshold1",
            "balance1",
            "topup2",
            "threshold2",
            "balance2",
            "topup3",
            "threshold3",
            "balance3",
            "sender_topup",
            "sender_threshold",
            "sender_balance",
        ),
        [
            (5, 10, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1),
            (10, 5, 1, 5, 10, 8, 0, 0, 0, 0, 0, 1),
            (10, 5, 8, 10, 5, 1, 0, 0, 0, 5, 10, 1),
            (10, 5, 8, 10, 5, 1, 2, 5, 1, 0, 0, 1),
            (10, 5, 6, 10, 5, 6, 0, 0, 0, 9, 10, 1),
            (10, 5, 8, 10, 5, -1, 10, 5, 1, 0, 0, 1),
            (10, 5, 8, 10, 5, 1, 10, 5, 1, 0, 0, -1),
        ],
    )
    def test_service_manager_compute_refill_requirements_raise(
        self,
        topup1: int,
        threshold1: int,
        balance1: int,
        topup2: int,
        threshold2: int,
        balance2: int,
        topup3: int,
        threshold3: int,
        balance3: int,
        sender_topup: int,
        sender_threshold: int,
        sender_balance: int,
    ) -> None:
        """Test operate.service_manager()._compute_refill_requirements()"""

        asset_funding_values = {}
        asset_funding_values["0x1"] = {
            "topup": topup1,
            "threshold": threshold1,
            "balance": balance1,
        }
        asset_funding_values["0x2"] = {
            "topup": topup2,
            "threshold": threshold2,
            "balance": balance2,
        }
        asset_funding_values["0x3"] = {
            "topup": topup3,
            "threshold": threshold3,
            "balance": balance3,
        }
        with pytest.raises(ValueError, match=r"^Argument.*must.*"):
            ServiceManager._compute_refill_requirement(
                asset_funding_values=asset_funding_values,
                sender_topup=sender_topup,
                sender_threshold=sender_threshold,
                sender_balance=sender_balance,
            )

    @pytest.mark.skipif(RUNNING_IN_CI, reason="Endpoint to be deprecated")
    def test_terminate_service(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """Test terminate service."""

        password = test_env.password
        operate = test_env.operate
        operate.password = password

        service_manager = operate.service_manager()
        services, _ = service_manager.get_all_services()

        service_config_id = None
        target_service = "Trader"
        for service in services:
            if target_service.lower() in service.name.lower():
                service_config_id = service.service_config_id
                break

        assert service_config_id is not None
        service = service_manager.load(service_config_id=service_config_id)

        for chain_config in service.chain_configs.values():
            assert chain_config.chain_data.multisig is None

        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )

        service = service_manager.load(service_config_id=service_config_id)
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            ledger_api = get_default_ledger_api(chain)
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.DEPLOYED
            )

            for asset, amount in AGENT_FUNDING_ASSETS[chain].items():
                for agent_address in service.agent_addresses:
                    tenderly_add_balance(chain, agent_address, amount, asset)
                    assert get_asset_balance(ledger_api, asset, agent_address) >= amount

            service_safe_address = chain_config.chain_data.multisig
            for asset, amount in SERVICE_SAFE_FUNDING_ASSETS[chain].items():
                tenderly_add_balance(chain, service_safe_address, amount, asset)
                assert (
                    get_asset_balance(ledger_api, asset, service_safe_address) >= amount
                )

            tenderly_increase_time(chain)

        LOGGER.info("Terminate without withdrawing")
        for chain_str, _ in service.chain_configs.items():
            service_manager.terminate_service_on_chain_from_safe(
                service_config_id=service_config_id,
                chain=chain_str,
            )
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.PRE_REGISTRATION
            )

        LOGGER.info("Terminate and withdraw")
        app = create_app(home=operate._path)
        client = TestClient(app)
        client.post(
            url="/api/account/login",
            json={"password": password},
        )
        response = client.post(
            url=f"/api/v2/service/{service_config_id}/onchain/withdraw",
            json={"withdrawal_address": test_env.backup_owner},
        )
        assert response.status_code == 200

        service = service_manager.load(service_config_id=service_config_id)
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.PRE_REGISTRATION
            )
            for asset in AGENT_FUNDING_ASSETS[chain]:
                for agent_address in service.agent_addresses:
                    balance = get_asset_balance(ledger_api, asset, agent_address)
                    LOGGER.info(f"Remaining balance for {agent_address}: {balance}")
                    if asset == ZERO_ADDRESS:
                        assert balance <= DUST[chain]
                    else:
                        assert balance == 0

            service_safe_address = chain_config.chain_data.multisig
            for asset in SERVICE_SAFE_FUNDING_ASSETS[chain]:
                assert get_asset_balance(ledger_api, asset, service_safe_address) == 0
