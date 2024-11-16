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

import json
import typing as t
from pathlib import Path

import pytest
from deepdiff import DeepDiff

from operate.services.service import SERVICE_CONFIG_PREFIX, Service


SERVICE_CONFIG_ID_PLACEHOLDER = "sc-00000000-0000-0000-0000-000000000000"
TIMESTAMP_PLACEHOLDER = 1704063600


def config_json_data_v0(use_staking: bool = True, **kwargs) -> t.Dict[str, t.Any]:
    return {
        "hash": "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u",
        "keys": [
            {
                "ledger": 0,
                "address": "0x0000000000000000000000000000000000000000",
                "private_key": "0x0000000000000000000000000000000000000000000000000000000000000000",
            }
        ],
        "ledger_config": {"rpc": "https://rpc", "type": 0, "chain": 2},
        "chain_data": {
            "instances": ["0x0000000000000000000000000000000000000001"],
            "token": 101,
            "multisig": "0x0000000000000000000000000000000000000002",
            "staked": True,
            "on_chain_state": 4,
            "user_params": {
                "nft": "bafybei0000000000000000000000000000000000000000000000000001",
                "agent_id": 14,
                "threshold": 1,
                "use_staking": use_staking,
                "cost_of_bond": 10000000000000000,
                "olas_cost_of_bond": 10000000000000000000,
                "olas_required_to_stake": 10000000000000000000,
                "fund_requirements": {
                    "agent": 100000000000000000,
                    "safe": 5000000000000000000,
                },
            },
        },
        "service_path": "/home/user/.operate/services/bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u/trader_pearl",
        "name": "Trader",
    }


def config_json_data_v2(use_staking: bool = True, **kwargs) -> t.Dict[str, t.Any]:
    return {
        "version": 2,
        "hash": "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u",
        "keys": [
            {
                "ledger": 0,
                "address": "0x0000000000000000000000000000000000000000",
                "private_key": "0x0000000000000000000000000000000000000000000000000000000000000000",
            }
        ],
        "home_chain_id": "100",
        "chain_configs": {
            "100": {
                "ledger_config": {"rpc": "https://rpc", "type": 0, "chain": 2},
                "chain_data": {
                    "instances": ["0x0000000000000000000000000000000000000001"],
                    "token": 101,
                    "multisig": "0x0000000000000000000000000000000000000002",
                    "staked": True,
                    "on_chain_state": 4,
                    "user_params": {
                        "staking_program_id": "pearl_alpha",  # TODO use a different program and change reference_data dynamically on the test.
                        "nft": "bafybei0000000000000000000000000000000000000000000000000001",
                        "threshold": 1,
                        "use_staking": use_staking,
                        "cost_of_bond": 10000000000000000,
                        "fund_requirements": {
                            "agent": 100000000000000000,
                            "safe": 5000000000000000000,
                        },
                    },
                },
            }
        },
        "service_path": "/home/user/.operate/services/bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u/trader_pearl",
        "name": "Trader",
    }


def config_json_data_v3(
    use_staking: bool = True, use_mech_marketplace: bool = True, **kwargs
) -> t.Dict[str, t.Any]:
    return {
        "version": 3,
        "hash": "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u",
        "keys": [
            {
                "ledger": 0,
                "address": "0x0000000000000000000000000000000000000000",
                "private_key": "0x0000000000000000000000000000000000000000000000000000000000000000",
            }
        ],
        "home_chain_id": "100",
        "chain_configs": {
            "100": {
                "ledger_config": {"rpc": "https://rpc", "type": 0, "chain": 2},
                "chain_data": {
                    "instances": ["0x0000000000000000000000000000000000000001"],
                    "token": 101,
                    "multisig": "0x0000000000000000000000000000000000000002",
                    "staked": True,
                    "on_chain_state": 4,
                    "user_params": {
                        "staking_program_id": "pearl_alpha",  # TODO use a different program and change reference_data dynamically on the test.
                        "nft": "bafybei0000000000000000000000000000000000000000000000000001",
                        "threshold": 1,
                        "use_staking": use_staking,
                        "use_mech_marketplace": use_mech_marketplace,
                        "cost_of_bond": 10000000000000000,
                        "fund_requirements": {
                            "agent": 100000000000000000,
                            "safe": 5000000000000000000,
                        },
                    },
                },
            }
        },
        "service_path": "/home/user/.operate/services/bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u/trader_pearl",
        "name": "Trader",
    }


def get_expected_data(  # pylint: disable=too-many-arguments
    version: int = 4,
    service_config_id: str = "sc-00000000-0000-0000-0000-000000000000",
    service_path: str = "/home/user/.operate/services/sc-00000000-0000-0000-0000-000000000000/trader_pearl",
    token: int = 101,
    staked: bool = True,
    on_chain_state: int = 4,
    use_staking: bool = True,
    use_mech_marketplace: bool = False,
    cost_of_bond: int = 10000000000000000,
    agent_fund: int = 100000000000000000,
    safe_fund: int = 5000000000000000000,
    hash_timestamp: int = 1704063600,
    threshold: int = 1,
    agent_id: int = 14,
    staking_program_id: str = "pearl_alpha",
) -> t.Dict[str, t.Any]:
    return {
        "version": version,
        "service_config_id": service_config_id,
        "hash": "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u",
        "hash_history": {
            hash_timestamp: "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u"
        },
        "keys": [
            {
                "ledger": "ethereum",
                "address": "0x0000000000000000000000000000000000000000",
                "private_key": "0x0000000000000000000000000000000000000000000000000000000000000000",
            }
        ],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": "https://rpc", "chain": "gnosis"},
                "chain_data": {
                    "instances": ["0x0000000000000000000000000000000000000001"],
                    "token": token,
                    "multisig": "0x0000000000000000000000000000000000000002",
                    "staked": staked,
                    "on_chain_state": on_chain_state,
                    "user_params": {
                        "staking_program_id": staking_program_id,
                        "nft": "bafybei0000000000000000000000000000000000000000000000000001",
                        "threshold": threshold,
                        "agent_id": agent_id,
                        "use_staking": use_staking,
                        "use_mech_marketplace": use_mech_marketplace,
                        "cost_of_bond": cost_of_bond,
                        "fund_requirements": {
                            "agent": agent_fund,
                            "safe": safe_fund,
                        },
                    },
                },
            }
        },
        "description": "Trader",
        "env_variables": {},
        "service_path": service_path,
        "name": "Trader",
    }


class TestService:
    """Tests for services.service.Service class."""

    @pytest.mark.parametrize(
        "config_json_data_func, use_staking, use_mech_marketplace",
        [
            (config_json_data_v0, True, False),
            (config_json_data_v2, True, False),
            (config_json_data_v3, True, False),
        ],
    )
    def test_service_migrate_format(
        self,
        config_json_data_func: t.Callable[..., t.Dict[str, t.Any]],
        use_staking: bool,
        use_mech_marketplace: bool,
        tmp_path: Path,
    ):
        """Test services.service.Service.migrate_format()"""

        config_json_data = config_json_data_func(
            use_staking=use_staking, use_mech_marketplace=use_mech_marketplace
        )
        service_config_dir = (
            tmp_path / "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u"
        )
        service_config_dir.mkdir(parents=True, exist_ok=True)

        # Write the config_json_data data to config.json
        config_json_path = service_config_dir / "config.json"
        with open(config_json_path, "w", encoding="utf-8") as file:
            json.dump(config_json_data, file, indent=4)

        # Migrate the service using Service.migrate_format
        Service.migrate_format(service_config_dir)

        # Locate the new path (directory starting with 'sc-')
        new_config_dir = next(tmp_path.glob(f"{SERVICE_CONFIG_PREFIX}*/"))
        new_config_json_path = new_config_dir / "config.json"

        # Read the resulting config.json
        with open(new_config_json_path, "r", encoding="utf-8") as file:
            migrated_data = json.load(file)
            migrated_data["hash_history"] = {
                TIMESTAMP_PLACEHOLDER: list(migrated_data["hash_history"].values())[0]
            }

        expected_data = get_expected_data(
            use_staking=use_staking,
            use_mech_marketplace=use_mech_marketplace,
            service_config_id=new_config_dir.name,
            service_path=str(new_config_dir / "trader_pearl"),
        )

        diff = DeepDiff(expected_data, migrated_data)
        if diff:
            print(diff)

        assert not diff, "Migrated data does not match expected data."
