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
import logging
import typing as t
from pathlib import Path
from unittest.mock import Mock

import pytest
from deepdiff import DeepDiff

from operate.cli import OperateApp
from operate.constants import (
    ACHIEVEMENTS_NOTIFICATIONS_JSON,
    AGENT_PERSISTENT_STORAGE_DIR,
    CONFIG_JSON,
)
from operate.migration import MigrationManager
from operate.services.service import (
    NON_EXISTENT_MULTISIG,
    SERVICE_CONFIG_PREFIX,
    SERVICE_CONFIG_VERSION,
    Service,
)

from tests.conftest import _get_service_template_trader


DEFAULT_CONFIG_KWARGS = {
    "hash": "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u",
    "rpc": "https://rpc.com",
    "service_config_id": "sc-00000000-0000-0000-0000-000000000000",
    "hash_timestamp": 1704063600,
    "token": 42,
    "staked": True,
    "on_chain_state": 4,
    "staking_program_id": "staking_program_1",
    "agent_id": 25,
    "cost_of_bond": 10000000000000000,
    "fund_requirements_agent": 100000000000000000,
    "fund_requirements_safe": 5000000000000000000,
    "nft": "bafybeinft",
    "name": "Test Service",
    "description": "Service description",
    "keys_address_0": "0x0000000000000000000000000000000000000001",
    "keys_private_key_0": "0x0000000000000000000000000000000000000000000000000000000000000001",
    "instance_0": "0x0000000000000000000000000000000000000001",
    "multisig": NON_EXISTENT_MULTISIG,
    "package_path": "trader_pearl",
    "agent_release": {
        "is_aea": True,
        "repository": {"owner": "valory-xyz", "name": "trader", "version": "v0.0.101"},
    },
}


def get_config_json_data_v0(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v0"""

    return {
        "hash": kwargs.get("hash"),
        "keys": [
            {
                "ledger": 0,
                "address": kwargs.get("keys_address_0"),
                "private_key": kwargs.get("keys_private_key_0"),
            }
        ],
        "ledger_config": {"rpc": kwargs.get("rpc"), "type": 0, "chain": 2},
        "chain_data": {
            "instances": [kwargs.get("instance_0")],
            "token": kwargs.get("token"),
            "multisig": kwargs.get("multisig"),
            "staked": True,
            "on_chain_state": kwargs.get("on_chain_state"),
            "user_params": {
                "nft": kwargs.get("nft"),
                "agent_id": kwargs.get("agent_id"),
                "cost_of_bond": kwargs.get("cost_of_bond"),
                "olas_cost_of_bond": 10000000000000000000,
                "olas_required_to_stake": 10000000000000000000,
                "fund_requirements": {
                    "agent": kwargs.get("fund_requirements_agent"),
                    "safe": kwargs.get("fund_requirements_safe"),
                },
            },
        },
        "service_path": f"/home/user/.operate/services/{kwargs.get('hash')}/trader_pearl",
        "name": kwargs.get("name"),
    }


def get_config_json_data_v2(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v2"""

    return {
        "version": 2,
        "hash": kwargs.get("hash"),
        "keys": [
            {
                "ledger": 0,
                "address": kwargs.get("keys_address_0"),
                "private_key": kwargs.get("keys_private_key_0"),
            }
        ],
        "home_chain_id": "100",
        "chain_configs": {
            "100": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "type": 0, "chain": 2},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": True,
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "agent": kwargs.get("fund_requirements_agent"),
                            "safe": kwargs.get("fund_requirements_safe"),
                        },
                    },
                },
            }
        },
        "service_path": f"/home/user/.operate/services/{kwargs.get('hash')}/trader_pearl",
        "name": kwargs.get("name"),
    }


def get_config_json_data_v3(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v3"""

    return {
        "version": 3,
        "hash": kwargs.get("hash"),
        "keys": [
            {
                "ledger": 0,
                "address": kwargs.get("keys_address_0"),
                "private_key": kwargs.get("keys_private_key_0"),
            }
        ],
        "home_chain_id": "100",
        "chain_configs": {
            "100": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "type": 0, "chain": 2},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": True,
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "agent": kwargs.get("fund_requirements_agent"),
                            "safe": kwargs.get("fund_requirements_safe"),
                        },
                    },
                },
            }
        },
        "service_path": f"/home/user/.operate/services/{kwargs.get('hash')}/trader_pearl",
        "name": kwargs.get("name"),
    }


def get_config_json_data_v4(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v4"""

    return {
        "version": 4,
        "service_config_id": kwargs.get("service_config_id"),
        "hash": kwargs.get("hash"),
        "hash_history": {kwargs.get("hash_timestamp"): kwargs.get("hash")},
        "keys": [
            {
                "ledger": "ethereum",
                "address": kwargs.get("keys_address_0"),
                "private_key": kwargs.get("keys_private_key_0"),
            }
        ],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "chain": "gnosis"},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": kwargs.get("staked"),
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "agent_id": kwargs.get("agent_id"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "agent": kwargs.get("fund_requirements_agent"),
                            "safe": kwargs.get("fund_requirements_safe"),
                        },
                    },
                },
            }
        },
        "description": kwargs.get("description"),
        "env_variables": {},
        "service_path": f"/home/user/.operate/services/{kwargs.get('service_config_id')}/trader_pearl",
        "name": kwargs.get("name"),
    }


def get_config_json_data_v5(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v5"""

    return {
        "version": 5,
        "service_config_id": kwargs.get("service_config_id"),
        "hash": kwargs.get("hash"),
        "hash_history": {kwargs.get("hash_timestamp"): kwargs.get("hash")},
        "keys": [
            {
                "ledger": "ethereum",
                "address": kwargs.get("keys_address_0"),
                "private_key": kwargs.get("keys_private_key_0"),
            }
        ],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "chain": "gnosis"},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": kwargs.get("staked"),
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "agent_id": kwargs.get("agent_id"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "0x0000000000000000000000000000000000000000": {
                                "agent": kwargs.get("fund_requirements_agent"),
                                "safe": kwargs.get("fund_requirements_safe"),
                            }
                        },
                    },
                },
            }
        },
        "description": kwargs.get("description"),
        "env_variables": {},
        "service_path": f"/home/user/.operate/services/{kwargs.get('service_config_id')}/trader_pearl",
        "name": kwargs.get("name"),
    }


def get_config_json_data_v6(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v6"""

    return {
        "version": 6,
        "service_config_id": kwargs.get("service_config_id"),
        "hash": kwargs.get("hash"),
        "hash_history": {kwargs.get("hash_timestamp"): kwargs.get("hash")},
        "keys": [
            {
                "ledger": "ethereum",
                "address": kwargs.get("keys_address_0"),
                "private_key": kwargs.get("keys_private_key_0"),
            }
        ],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "chain": "gnosis"},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": kwargs.get("staked"),
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "agent_id": kwargs.get("agent_id"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "0x0000000000000000000000000000000000000000": {
                                "agent": kwargs.get("fund_requirements_agent"),
                                "safe": kwargs.get("fund_requirements_safe"),
                            }
                        },
                    },
                },
            }
        },
        "description": kwargs.get("description"),
        "env_variables": {},
        "package_path": kwargs.get("package_path"),
        "name": kwargs.get("name"),
    }


def get_config_json_data_v7(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v7"""

    return {
        "version": 7,
        "service_config_id": kwargs.get("service_config_id"),
        "hash": kwargs.get("hash"),
        "hash_history": {kwargs.get("hash_timestamp"): kwargs.get("hash")},
        "agent_addresses": [kwargs.get("keys_address_0")],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "chain": "gnosis"},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": kwargs.get("staked"),
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "agent_id": kwargs.get("agent_id"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "0x0000000000000000000000000000000000000000": {
                                "agent": kwargs.get("fund_requirements_agent"),
                                "safe": kwargs.get("fund_requirements_safe"),
                            }
                        },
                    },
                },
            }
        },
        "description": kwargs.get("description"),
        "env_variables": {},
        "package_path": kwargs.get("package_path"),
        "name": kwargs.get("name"),
    }


def get_config_json_data_v8(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v8"""

    return {
        "version": 8,
        "service_config_id": kwargs.get("service_config_id"),
        "hash": kwargs.get("hash"),
        "hash_history": {kwargs.get("hash_timestamp"): kwargs.get("hash")},
        "agent_addresses": [kwargs.get("keys_address_0")],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "chain": "gnosis"},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": kwargs.get("staked"),
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "agent_id": kwargs.get("agent_id"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "0x0000000000000000000000000000000000000000": {
                                "agent": kwargs.get("fund_requirements_agent"),
                                "safe": kwargs.get("fund_requirements_safe"),
                            }
                        },
                    },
                },
            }
        },
        "description": kwargs.get("description"),
        "env_variables": {},
        "package_path": kwargs.get("package_path"),
        "name": kwargs.get("name"),
    }


def get_config_json_data_v9(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    """get_config_json_data_v9"""

    return {
        "version": 9,
        "service_config_id": kwargs.get("service_config_id"),
        "hash": kwargs.get("hash"),
        "hash_history": {kwargs.get("hash_timestamp"): kwargs.get("hash")},
        "agent_addresses": [kwargs.get("keys_address_0")],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": kwargs.get("rpc"), "chain": "gnosis"},
                "chain_data": {
                    "instances": [kwargs.get("instance_0")],
                    "token": kwargs.get("token"),
                    "multisig": kwargs.get("multisig"),
                    "staked": kwargs.get("staked"),
                    "on_chain_state": kwargs.get("on_chain_state"),
                    "user_params": {
                        "staking_program_id": kwargs.get("staking_program_id"),
                        "nft": kwargs.get("nft"),
                        "agent_id": kwargs.get("agent_id"),
                        "cost_of_bond": kwargs.get("cost_of_bond"),
                        "fund_requirements": {
                            "0x0000000000000000000000000000000000000000": {
                                "agent": kwargs.get("fund_requirements_agent"),
                                "safe": kwargs.get("fund_requirements_safe"),
                            }
                        },
                    },
                },
            }
        },
        "description": kwargs.get("description"),
        "env_variables": {},
        "package_path": kwargs.get("package_path"),
        "name": kwargs.get("name"),
        "agent_release": kwargs.get("agent_release"),
    }


get_expected_data = get_config_json_data_v9


class TestService:
    """Tests for services.service.Service class."""

    @pytest.mark.parametrize(
        "staking_program_id", ["staking_program_1", "staking_program_2"]
    )
    @pytest.mark.parametrize(
        "get_config_json_data",
        [
            get_config_json_data_v0,
            get_config_json_data_v2,
            get_config_json_data_v3,
            get_config_json_data_v4,
            get_config_json_data_v5,
            get_config_json_data_v6,
            get_config_json_data_v7,
            get_config_json_data_v8,
        ],
    )
    def test_service_migrate_format(
        self,
        get_config_json_data: t.Callable[..., t.Dict[str, t.Any]],
        staking_program_id: str,
        tmp_path: Path,
    ) -> None:
        """Test services.service.Service.migrate_format()"""

        config_kwargs = DEFAULT_CONFIG_KWARGS.copy()
        config_kwargs["staking_program"] = staking_program_id
        old_config_json_data = get_config_json_data(**config_kwargs)

        # Emulate an existing service directory contents
        service_dir = tmp_path / "services"
        service_config_dir = service_dir / old_config_json_data.get(
            "service_config_id", old_config_json_data.get("hash", "")
        )
        service_config_dir.mkdir(parents=True, exist_ok=True)

        if old_config_json_data.get("version", 0) == 7:
            old_config_json_data["home_chain"] = "optimistic"
            old_config_json_data["chain_configs"]["optimistic"] = old_config_json_data[
                "chain_configs"
            ].pop("gnosis")
            old_config_json_data["chain_configs"]["optimistic"]["ledger_config"][
                "chain"
            ] = "optimistic"

        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "w", encoding="utf-8") as file:
            json.dump(old_config_json_data, file, indent=4)

        # Migrate the service using the MigrationManager and read the resulting
        # migrated data
        mm = MigrationManager(tmp_path, logging.getLogger("test"))
        service_manager = Mock()
        service_manager.path = service_dir
        mm.migrate_services(service_manager)

        migrated_config_dir = next(service_dir.glob(f"{SERVICE_CONFIG_PREFIX}*/"))
        new_config_json_path = migrated_config_dir / CONFIG_JSON
        with open(new_config_json_path, "r", encoding="utf-8") as file:
            migrated_data = json.load(file)

        # Construct the expected data
        if old_config_json_data.get("version", 0) < 2:
            config_kwargs["staking_program_id"] = "pearl_alpha"

        if old_config_json_data.get("version", 0) < 4:
            config_kwargs["description"] = config_kwargs["name"]

        if old_config_json_data.get("version", 0) == 7:
            assert migrated_data["home_chain"] == "optimism"
            assert "optimism" in migrated_data["chain_configs"]
            assert "gnosis" not in migrated_data["chain_configs"]
            assert (
                migrated_data["chain_configs"]["optimism"]["ledger_config"]["chain"]
                == "optimism"
            )

            migrated_data["home_chain"] = "gnosis"
            migrated_data["chain_configs"]["gnosis"] = migrated_data[
                "chain_configs"
            ].pop("optimism")
            migrated_data["chain_configs"]["gnosis"]["ledger_config"][
                "chain"
            ] = "gnosis"

        config_kwargs["service_config_id"] = migrated_config_dir.name
        config_kwargs["version"] = SERVICE_CONFIG_VERSION
        config_kwargs["hash_timestamp"] = list(migrated_data["hash_history"].keys())[0]
        config_kwargs["service_path"] = str(migrated_config_dir / "trader_pearl")

        expected_data = get_expected_data(**config_kwargs)

        diff = DeepDiff(migrated_data, expected_data)
        if diff:
            print(diff)

        assert not diff, "Migrated data does not match expected data."


class TestServiceAchievementsNotifications:
    """Tests for achievements notifications functionality in services.service.Service."""

    def test_load_achievements_notifications_creates_default(
        self, test_operate: OperateApp
    ) -> None:
        """Test that _load_achievements_notifications creates default file if not exists."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Call _load_achievements_notifications
        achievements_notifications, agent_achievements = (
            service._load_achievements_notifications()
        )

        # Verify the file was created
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        assert achievements_file.exists()

        # Verify default values
        assert achievements_notifications.path == service_config_dir
        assert achievements_notifications.notifications == {}
        assert agent_achievements == {}

    def test_load_achievements_notifications_with_existing_data(
        self, test_operate: OperateApp
    ) -> None:
        """Test _load_achievements_notifications with existing data."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path

        # Create existing achievements_notifications.json
        achievements_data = {
            "path": str(service_config_dir),
            "notifications": {
                "achievement_1": {
                    "achievement_id": "achievement_1",
                    "acknowledged": False,
                    "acknowledgement_timestamp": 0,
                },
                "achievement_2": {
                    "achievement_id": "achievement_2",
                    "acknowledged": True,
                    "acknowledgement_timestamp": 1704063600,
                },
            },
        }
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        with open(achievements_file, "w", encoding="utf-8") as f:
            json.dump(achievements_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Call _load_achievements_notifications
        achievements_notifications, agent_achievements = (
            service._load_achievements_notifications()
        )

        # Verify loaded data
        assert len(achievements_notifications.notifications) == 2
        assert "achievement_1" in achievements_notifications.notifications
        assert "achievement_2" in achievements_notifications.notifications
        assert (
            achievements_notifications.notifications["achievement_1"].acknowledged
            is False
        )
        assert (
            achievements_notifications.notifications["achievement_2"].acknowledged
            is True
        )

    def test_load_achievements_notifications_with_agent_performance(
        self, test_operate: OperateApp
    ) -> None:
        """Test _load_achievements_notifications loads agent achievements from agent_performance.json."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create agent_performance.json with achievements
        agent_performance_data = {
            "timestamp": 1704063600,
            "metrics": [],
            "last_activity": None,
            "last_chat_message": None,
            "achievements": {
                "items": {
                    "achievement_1": {
                        "title": "First Trade",
                        "description": "Completed your first trade",
                        "timestamp": 1704063000,
                    },
                    "achievement_2": {
                        "title": "Ten Trades",
                        "description": "Completed ten trades",
                        "timestamp": 1704063500,
                    },
                }
            },
        }
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Call _load_achievements_notifications
        achievements_notifications, agent_achievements = (
            service._load_achievements_notifications()
        )

        # Verify agent achievements were loaded
        assert len(agent_achievements) == 2
        assert "achievement_1" in agent_achievements
        assert "achievement_2" in agent_achievements
        assert agent_achievements["achievement_1"]["title"] == "First Trade"

        # Verify new notifications were created for agent achievements
        assert len(achievements_notifications.notifications) == 2
        assert "achievement_1" in achievements_notifications.notifications
        assert "achievement_2" in achievements_notifications.notifications

    def test_load_achievements_notifications_invalid_json(
        self, test_operate: OperateApp, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test _load_achievements_notifications handles invalid agent_performance.json."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create invalid agent_performance.json
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            f.write("invalid json content")

        # Load the service
        service = Service.load(service_config_dir)

        # Call _load_achievements_notifications
        with caplog.at_level(logging.WARNING):
            _, agent_achievements = service._load_achievements_notifications()

        # Verify graceful handling
        assert agent_achievements == {}
        assert "Cannot read file 'agent_performance.json'" in caplog.text

    def test_load_achievements_notifications_non_dict_root(
        self, test_operate: OperateApp, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test _load_achievements_notifications handles non-dict root in agent_performance.json."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create agent_performance.json with list root (invalid)
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(["item1", "item2"], f)

        # Load the service
        service = Service.load(service_config_dir)

        # Call _load_achievements_notifications
        with caplog.at_level(logging.WARNING):
            _, agent_achievements = service._load_achievements_notifications()

        # Verify graceful handling
        assert agent_achievements == {}
        assert "Invalid agent_performance.json" in caplog.text

    def test_get_achievements_notifications_empty(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test get_achievements_notifications returns empty list when no achievements."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path

        # Load the service
        service = Service.load(service_config_dir)

        # Get achievements notifications
        result = service.get_achievements_notifications(include_acknowledged=False)

        # Verify empty result
        assert result == []

    def test_get_achievements_notifications_excludes_acknowledged(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test get_achievements_notifications excludes acknowledged when include_acknowledged=False."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create achievements_notifications.json
        achievements_data = {
            "path": str(service_config_dir),
            "notifications": {
                "achievement_1": {
                    "achievement_id": "achievement_1",
                    "acknowledged": False,
                    "acknowledgement_timestamp": 0,
                },
                "achievement_2": {
                    "achievement_id": "achievement_2",
                    "acknowledged": True,
                    "acknowledgement_timestamp": 1704063600,
                },
            },
        }
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        with open(achievements_file, "w", encoding="utf-8") as f:
            json.dump(achievements_data, f)

        # Create agent_performance.json with matching achievements
        agent_performance_data = {
            "achievements": {
                "items": {
                    "achievement_1": {"title": "First Trade", "timestamp": 1704063000},
                    "achievement_2": {"title": "Ten Trades", "timestamp": 1704063500},
                }
            }
        }
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Get achievements notifications without acknowledged
        result = service.get_achievements_notifications(include_acknowledged=False)

        # Verify only unacknowledged achievement is returned
        assert len(result) == 1
        assert result[0]["achievement_id"] == "achievement_1"
        assert result[0]["title"] == "First Trade"

    def test_get_achievements_notifications_includes_acknowledged(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test get_achievements_notifications includes acknowledged when include_acknowledged=True."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create achievements_notifications.json
        achievements_data = {
            "path": str(service_config_dir),
            "notifications": {
                "achievement_1": {
                    "achievement_id": "achievement_1",
                    "acknowledged": False,
                    "acknowledgement_timestamp": 0,
                },
                "achievement_2": {
                    "achievement_id": "achievement_2",
                    "acknowledged": True,
                    "acknowledgement_timestamp": 1704063600,
                },
            },
        }
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        with open(achievements_file, "w", encoding="utf-8") as f:
            json.dump(achievements_data, f)

        # Create agent_performance.json with matching achievements
        agent_performance_data = {
            "achievements": {
                "items": {
                    "achievement_1": {"title": "First Trade", "timestamp": 1704063000},
                    "achievement_2": {"title": "Ten Trades", "timestamp": 1704063500},
                }
            }
        }
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Get achievements notifications with acknowledged
        result = service.get_achievements_notifications(include_acknowledged=True)

        # Verify all achievements are returned
        assert len(result) == 2
        achievement_ids = {a["achievement_id"] for a in result}
        assert "achievement_1" in achievement_ids
        assert "achievement_2" in achievement_ids

    def test_get_achievements_notifications_merges_data(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test get_achievements_notifications merges notification and agent achievement data."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create achievements_notifications.json
        achievements_data = {
            "path": str(service_config_dir),
            "notifications": {
                "achievement_1": {
                    "achievement_id": "achievement_1",
                    "acknowledged": False,
                    "acknowledgement_timestamp": 0,
                },
            },
        }
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        with open(achievements_file, "w", encoding="utf-8") as f:
            json.dump(achievements_data, f)

        # Create agent_performance.json with additional data
        agent_performance_data = {
            "achievements": {
                "items": {
                    "achievement_1": {
                        "title": "First Trade",
                        "description": "Completed your first trade",
                        "timestamp": 1704063000,
                        "extra_field": "extra_value",
                    },
                }
            }
        }
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Get achievements notifications
        result = service.get_achievements_notifications(include_acknowledged=False)

        # Verify merged data
        assert len(result) == 1
        achievement = result[0]
        assert achievement["achievement_id"] == "achievement_1"
        assert achievement["acknowledged"] is False
        assert achievement["acknowledgement_timestamp"] == 0
        assert achievement["title"] == "First Trade"
        assert achievement["description"] == "Completed your first trade"
        assert achievement["extra_field"] == "extra_value"

    def test_get_achievements_notifications_missing_agent_achievement(
        self, test_operate: OperateApp, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test get_achievements_notifications handles missing agent achievement data."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create achievements_notifications.json with achievement not in agent_performance
        achievements_data = {
            "path": str(service_config_dir),
            "notifications": {
                "orphan_achievement": {
                    "achievement_id": "orphan_achievement",
                    "acknowledged": False,
                    "acknowledgement_timestamp": 0,
                },
            },
        }
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        with open(achievements_file, "w", encoding="utf-8") as f:
            json.dump(achievements_data, f)

        # Create agent_performance.json without the orphan achievement
        agent_performance_data = {
            "achievements": {
                "items": {
                    "other_achievement": {"title": "Other", "timestamp": 1704063000},
                }
            }
        }
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Get achievements notifications
        with caplog.at_level(logging.WARNING):
            result = service.get_achievements_notifications(include_acknowledged=False)

        # Verify warning was logged and orphan was skipped
        assert "orphan_achievement" in caplog.text
        assert "Corrupted file?" in caplog.text
        assert len(result) == 1

    def test_acknowledge_achievement_success(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test acknowledge_achievement successfully acknowledges an achievement."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create achievements_notifications.json
        achievements_data = {
            "path": str(service_config_dir),
            "notifications": {
                "achievement_1": {
                    "achievement_id": "achievement_1",
                    "acknowledged": False,
                    "acknowledgement_timestamp": 0,
                },
            },
        }
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        with open(achievements_file, "w", encoding="utf-8") as f:
            json.dump(achievements_data, f)

        # Create agent_performance.json
        agent_performance_data = {
            "achievements": {
                "items": {
                    "achievement_1": {"title": "First Trade", "timestamp": 1704063000},
                }
            }
        }
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Acknowledge the achievement
        service.acknowledge_achievement("achievement_1")

        # Verify the achievement is now acknowledged
        result = service.get_achievements_notifications(include_acknowledged=True)
        assert len(result) == 1
        assert result[0]["acknowledged"] is True
        assert result[0]["acknowledgement_timestamp"] > 0

        # Verify it's not returned when include_acknowledged=False
        result_unacknowledged = service.get_achievements_notifications(
            include_acknowledged=False
        )
        assert len(result_unacknowledged) == 0

    def test_acknowledge_achievement_nonexistent(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test acknowledge_achievement raises KeyError for nonexistent achievement."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path

        # Load the service
        service = Service.load(service_config_dir)

        # Try to acknowledge nonexistent achievement
        with pytest.raises(KeyError, match="nonexistent_achievement.*does not exist"):
            service.acknowledge_achievement("nonexistent_achievement")

    def test_acknowledge_achievement_already_acknowledged(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test acknowledge_achievement raises ValueError for already acknowledged achievement."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path

        # Create achievements_notifications.json with already acknowledged achievement
        achievements_data = {
            "path": str(service_config_dir),
            "notifications": {
                "achievement_1": {
                    "achievement_id": "achievement_1",
                    "acknowledged": True,
                    "acknowledgement_timestamp": 1704063600,
                },
            },
        }
        achievements_file = service_config_dir / ACHIEVEMENTS_NOTIFICATIONS_JSON
        with open(achievements_file, "w", encoding="utf-8") as f:
            json.dump(achievements_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Try to acknowledge already acknowledged achievement
        with pytest.raises(ValueError, match="already acknowledged"):
            service.acknowledge_achievement("achievement_1")

    def test_load_achievements_notifications_missing_achievements_key(
        self, test_operate: OperateApp, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test _load_achievements_notifications handles missing achievements key."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create agent_performance.json without achievements key
        agent_performance_data = {
            "timestamp": 1704063600,
            "metrics": [],
        }
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Call _load_achievements_notifications
        _, agent_achievements = service._load_achievements_notifications()

        # Verify empty achievements
        assert agent_achievements == {}

    def test_load_achievements_notifications_missing_items_key(
        self,
        test_operate: OperateApp,
    ) -> None:
        """Test _load_achievements_notifications handles missing items key in achievements."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path
        persistent_dir = service.path / AGENT_PERSISTENT_STORAGE_DIR
        persistent_dir.mkdir(parents=True, exist_ok=True)

        # Update service config to include STORE_PATH env variable
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config_data["env_variables"] = {"STORE_PATH": {"value": str(persistent_dir)}}
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Create agent_performance.json with achievements but no items
        agent_performance_data: t.Dict = {"achievements": {}}
        agent_performance_file = persistent_dir / "agent_performance.json"
        with open(agent_performance_file, "w", encoding="utf-8") as f:
            json.dump(agent_performance_data, f)

        # Load the service
        service = Service.load(service_config_dir)

        # Call _load_achievements_notifications
        _, agent_achievements = service._load_achievements_notifications()

        # Verify empty achievements
        assert agent_achievements == {}

    def test_load_achievements_notifications_no_store_path_env(
        self, test_operate: OperateApp, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test _load_achievements_notifications when STORE_PATH env var is not set."""

        test_operate.service_manager().create(
            service_template=_get_service_template_trader()
        )

        service_config_id = test_operate.service_manager().json[0]["service_config_id"]

        # Load the service
        service = test_operate.service_manager().load(service_config_id)
        service_config_dir = service.path

        # Remove STORE_PATH env variable from config so it is truly unset
        config_json_path = service_config_dir / CONFIG_JSON
        with open(config_json_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        env_vars = config_data.get("env_variables", {})
        env_vars.pop("STORE_PATH", None)
        if env_vars:
            config_data["env_variables"] = env_vars
        else:
            config_data.pop("env_variables", None)
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        # Don't set STORE_PATH env variable - agent_performance.json won't be found
        # Load the service
        service = Service.load(service_config_dir)

        # Call _load_achievements_notifications
        _, agent_achievements = service._load_achievements_notifications()

        # Verify empty agent achievements (no file found)
        assert agent_achievements == {}
