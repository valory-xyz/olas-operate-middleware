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

"""Utilities for format migration"""


import json
import logging
import shutil
import traceback
from pathlib import Path
from time import time

from aea_cli_ipfs.ipfs_utils import IPFSTool

from operate.constants import USER_JSON, ZERO_ADDRESS
from operate.operate_types import Chain, LedgerType
from operate.services.manage import ServiceManager
from operate.services.service import (
    NON_EXISTENT_MULTISIG,
    SERVICE_CONFIG_PREFIX,
    SERVICE_CONFIG_VERSION,
    Service,
)
from operate.utils import create_backup
from operate.wallet.master import LEDGER_TYPE_TO_WALLET_CLASS, MasterWalletManager


DEFAULT_TRADER_ENV_VARS = {
    "GNOSIS_LEDGER_RPC": {
        "name": "Gnosis ledger RPC",
        "description": "",
        "value": "",
        "provision_type": "computed",
    },
    "STAKING_CONTRACT_ADDRESS": {
        "name": "Staking contract address",
        "description": "",
        "value": "",
        "provision_type": "computed",
    },
    "MECH_MARKETPLACE_CONFIG": {
        "name": "Mech marketplace configuration",
        "description": "",
        "value": "",
        "provision_type": "computed",
    },
    "MECH_ACTIVITY_CHECKER_CONTRACT": {
        "name": "Mech activity checker contract",
        "description": "",
        "value": "",
        "provision_type": "computed",
    },
    "MECH_CONTRACT_ADDRESS": {
        "name": "Mech contract address",
        "description": "",
        "value": "",
        "provision_type": "computed",
    },
    "MECH_REQUEST_PRICE": {
        "name": "Mech request price",
        "description": "",
        "value": "10000000000000000",
        "provision_type": "computed",
    },
    "USE_MECH_MARKETPLACE": {
        "name": "Use Mech marketplace",
        "description": "",
        "value": "False",
        "provision_type": "computed",
    },
    "REQUESTER_STAKING_INSTANCE_ADDRESS": {
        "name": "Requester staking instance address",
        "description": "",
        "value": "",
        "provision_type": "computed",
    },
    "PRIORITY_MECH_ADDRESS": {
        "name": "Priority Mech address",
        "description": "",
        "value": "",
        "provision_type": "computed",
    },
}


class MigrationManager:
    """MigrationManager"""

    def __init__(
        self,
        home: Path,
        logger: logging.Logger,
    ) -> None:
        """Initialize object."""
        super().__init__()
        self._path = home
        self.logger = logger

    def log_directories(self, path: Path) -> None:
        """Log directories present in `path`."""
        directories = [f"  - {str(p)}" for p in path.iterdir() if p.is_dir()]
        directories_str = "\n".join(directories)
        self.logger.info(f"Directories in {path}:\n{directories_str}")

    def migrate_user_account(self) -> None:
        """Migrates user.json"""

        path = self._path / USER_JSON
        if not path.exists():
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "password_sha" not in data:
            return

        create_backup(path)
        new_data = {"password_hash": data["password_sha"]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=4)

        self.logger.info("[MIGRATION MANAGER] Migrated user.json.")

    def migrate_wallets(self, wallet_manager: MasterWalletManager) -> None:
        """Migrate old wallet config formats to new ones, if applies."""
        self.logger.info("Migrating wallet configs...")

        for ledger_type in LedgerType:
            if not wallet_manager.exists(ledger_type=ledger_type):
                continue

            wallet_class = LEDGER_TYPE_TO_WALLET_CLASS.get(ledger_type)
            if wallet_class is None:
                continue

            migrated = wallet_class.migrate_format(path=wallet_manager.path)
            if migrated:
                self.logger.info(f"Wallet {wallet_class} has been migrated.")

        self.logger.info("Migrating wallet configs done.")

    def _migrate_service(  # pylint: disable=too-many-statements,too-many-locals
        self,
        path: Path,
    ) -> bool:
        """Migrate the JSON file format if needed."""

        if not path.is_dir():
            self.logger.warning(f"Service config path {path} is not a directory.")
            return False

        if not path.name.startswith(SERVICE_CONFIG_PREFIX) and not path.name.startswith(
            "bafybei"
        ):
            self.logger.warning(
                f"Service config path {path} is not a valid service config."
            )
            return False

        if path.name.startswith("bafybei"):
            backup_name = f"backup_{int(time())}_{path.name}"
            backup_path = path.parent / backup_name
            shutil.copytree(path, backup_path)
            deployment_path = backup_path / "deployment"
            if deployment_path.is_dir():
                shutil.rmtree(deployment_path)

        with open(
            path / Service._file,  # pylint: disable=protected-access
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        version = data.get("version", 0)
        if version > SERVICE_CONFIG_VERSION:
            raise RuntimeError(
                f"Service configuration in {path} has version {version}, which means it was created with a newer version of olas-operate-middleware. Only configuration versions <= {SERVICE_CONFIG_VERSION} are supported by this version of olas-operate-middleware."
            )

        # Complete missing env vars for trader
        if "trader" in data["name"].lower():
            data.setdefault("env_variables", {})

            for key, value in DEFAULT_TRADER_ENV_VARS.items():
                if key not in data["env_variables"]:
                    data["env_variables"][key] = value

            with open(
                path / Service._file,  # pylint: disable=protected-access
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(data, file, indent=2)

        if version == SERVICE_CONFIG_VERSION:
            return False

        self.logger.info(
            f"Migrating service config in {path} from version {version} to {SERVICE_CONFIG_VERSION}..."
        )

        # Migration steps for older versions
        if version == 0:
            new_data = {
                "version": 2,
                "hash": data.get("hash"),
                "keys": data.get("keys"),
                "home_chain_id": "100",  # This is the default value for version 2 - do not change, will be corrected below
                "chain_configs": {
                    "100": {  # This is the default value for version 2 - do not change, will be corrected below
                        "ledger_config": {
                            "rpc": data.get("ledger_config", {}).get("rpc"),
                            "type": data.get("ledger_config", {}).get("type"),
                            "chain": data.get("ledger_config", {}).get("chain"),
                        },
                        "chain_data": {
                            "instances": data.get("chain_data", {}).get(
                                "instances", []
                            ),
                            "token": data.get("chain_data", {}).get("token"),
                            "multisig": data.get("chain_data", {}).get("multisig"),
                            "staked": data.get("chain_data", {}).get("staked", False),
                            "on_chain_state": data.get("chain_data", {}).get(
                                "on_chain_state", 3
                            ),
                            "user_params": {
                                "staking_program_id": "pearl_alpha",
                                "nft": data.get("chain_data", {})
                                .get("user_params", {})
                                .get("nft"),
                                "threshold": data.get("chain_data", {})
                                .get("user_params", {})
                                .get("threshold"),
                                "use_staking": data.get("chain_data", {})
                                .get("user_params", {})
                                .get("use_staking"),
                                "cost_of_bond": data.get("chain_data", {})
                                .get("user_params", {})
                                .get("cost_of_bond"),
                                "fund_requirements": data.get("chain_data", {})
                                .get("user_params", {})
                                .get("fund_requirements", {}),
                                "agent_id": data.get("chain_data", {})
                                .get("user_params", {})
                                .get("agent_id", "14"),
                            },
                        },
                    }
                },
                "service_path": data.get("service_path", ""),
                "name": data.get("name", ""),
            }
            data = new_data

        if version < 4:
            # Add missing fields introduced in later versions, if necessary.
            for _, chain_data in data.get("chain_configs", {}).items():
                chain_data.setdefault("chain_data", {}).setdefault(
                    "user_params", {}
                ).setdefault("use_mech_marketplace", False)
                service_name = data.get("name", "")
                agent_id = Service.determine_agent_id(service_name)
                chain_data.setdefault("chain_data", {}).setdefault("user_params", {})[
                    "agent_id"
                ] = agent_id

            data["description"] = data.setdefault("description", data.get("name"))
            data["hash_history"] = data.setdefault(
                "hash_history", {int(time()): data["hash"]}
            )

            if "service_config_id" not in data:
                service_config_id = Service.get_new_service_config_id(path)
                new_path = path.parent / service_config_id
                data["service_config_id"] = service_config_id
                path = path.rename(new_path)

            old_to_new_ledgers = ["ethereum", "solana"]
            for key_data in data["keys"]:
                key_data["ledger"] = old_to_new_ledgers[key_data["ledger"]]

            old_to_new_chains = [
                "ethereum",
                "goerli",
                "gnosis",
                "solana",
                "optimism",
                "base",
                "mode",
            ]
            new_chain_configs = {}
            for chain_id, chain_data in data["chain_configs"].items():
                chain_data["ledger_config"]["chain"] = old_to_new_chains[
                    chain_data["ledger_config"]["chain"]
                ]
                del chain_data["ledger_config"]["type"]
                new_chain_configs[Chain.from_id(int(chain_id)).value] = chain_data  # type: ignore

            data["chain_configs"] = new_chain_configs
            data["home_chain"] = data.setdefault("home_chain", Chain.from_id(int(data.get("home_chain_id", "100"))).value)  # type: ignore
            del data["home_chain_id"]

            if "env_variables" not in data:
                if data["name"] == "valory/trader_pearl":
                    data["env_variables"] = DEFAULT_TRADER_ENV_VARS
                else:
                    data["env_variables"] = {}

        if version < 5:
            new_chain_configs = {}
            for chain, chain_data in data["chain_configs"].items():
                fund_requirements = chain_data["chain_data"]["user_params"][
                    "fund_requirements"
                ]
                if ZERO_ADDRESS not in fund_requirements:
                    chain_data["chain_data"]["user_params"]["fund_requirements"] = {
                        ZERO_ADDRESS: fund_requirements
                    }

                new_chain_configs[chain] = chain_data  # type: ignore
            data["chain_configs"] = new_chain_configs

        if version < 7:
            for _, chain_data in data.get("chain_configs", {}).items():
                if chain_data["chain_data"]["multisig"] == "0xm":
                    chain_data["chain_data"]["multisig"] = NON_EXISTENT_MULTISIG

            data["agent_addresses"] = [key["address"] for key in data["keys"]]
            del data["keys"]

        if version < 8:
            if data["home_chain"] == "optimistic":
                data["home_chain"] = Chain.OPTIMISM.value

            if "optimistic" in data["chain_configs"]:
                data["chain_configs"]["optimism"] = data["chain_configs"].pop(
                    "optimistic"
                )

            for _, chain_config in data["chain_configs"].items():
                if chain_config["ledger_config"]["chain"] == "optimistic":
                    chain_config["ledger_config"]["chain"] = Chain.OPTIMISM.value

        data["version"] = SERVICE_CONFIG_VERSION

        # Redownload service path
        if "service_path" in data:
            package_absolute_path = path / Path(data["service_path"]).name
            data.pop("service_path")
        else:
            package_absolute_path = path / data["package_path"]

        if package_absolute_path.exists() and package_absolute_path.is_dir():
            shutil.rmtree(package_absolute_path)

        package_absolute_path = Path(
            IPFSTool().download(
                hash_id=data["hash"],
                target_dir=path,
            )
        )
        data["package_path"] = str(package_absolute_path.name)

        with open(
            path / Service._file,  # pylint: disable=protected-access
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(data, file, indent=2)

        return True

    def migrate_services(self, service_manager: ServiceManager) -> None:
        """Migrate old service config formats to new ones, if applies."""
        self.log_directories(service_manager.path)
        self.logger.info("Migrating service configs...")

        bafybei_count = sum(
            1
            for path in service_manager.path.iterdir()
            if path.name.startswith("bafybei")
        )
        if bafybei_count > 1:
            raise RuntimeError(
                f"Your services folder contains {bafybei_count} folders starting with 'bafybei'. This is an unintended situation. Please contact support."
            )

        paths = list(service_manager.path.iterdir())
        for path in paths:
            try:
                migrated = self._migrate_service(path)
                if migrated:
                    self.logger.info(f"Folder {str(path)} has been migrated.")
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error(
                    f"Failed to migrate service: {path.name}. Exception {e}: {traceback.format_exc()}"
                )

        self.logger.info("Migrating service configs done.")
        self.log_directories(service_manager.path)

    def migrate_qs_configs(self) -> None:
        """Migrates quickstart configs."""

        for qs_config in self._path.glob("*-quickstart-config.json"):
            if not qs_config.exists():
                continue

            migrated = False
            with open(qs_config, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "optimistic" in data.get("rpc", {}):
                data["rpc"]["optimism"] = data["rpc"].pop("optimistic")
                migrated = True

            if "optimistic" == data.get("principal_chain", ""):
                data["principal_chain"] = "optimism"
                migrated = True

            if not migrated:
                continue

            with open(qs_config, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            self.logger.info(
                "[MIGRATION MANAGER] Migrated quickstart config: %s.", qs_config.name
            )
