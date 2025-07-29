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
from pathlib import Path

from operate.utils import create_backup


class MigrationManager:
    """MigrationManager"""

    # TODO Backport here migration for services/config.json, etc.

    def __init__(
        self,
        home: Path,
        logger: logging.Logger,
    ) -> None:
        """Initialize object."""
        super().__init__()
        self._path = home
        self.logger = logger

    def migrate_user_account(self) -> None:
        """Migrates user.json"""

        path = self._path / "user.json"
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

    def migrate_wallets(self) -> None:
        """Migrates wallets."""

        path = self._path / "wallets" / "ethereum.json"
        if not path.exists():
            return

        migrated = False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "optimistic" in data.get("safes", {}):
            data["safes"]["optimism"] = data["safes"].pop("optimistic")
            migrated = True

        if "optimistic" in data.get("safe_chains"):
            data["safe_chains"] = [
                "optimism" if chain == "optimistic" else chain
                for chain in data["safe_chains"]
            ]
            migrated = True

        if not migrated:
            return

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        self.logger.info("[MIGRATION MANAGER] Migrated wallets.")

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
