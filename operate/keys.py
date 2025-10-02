# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""Keys manager."""

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aea_ledger_ethereum.ethereum import EthereumCrypto

from operate.operate_types import LedgerType
from operate.resource import LocalResource
from operate.utils import SingletonMeta


@dataclass
class Key(LocalResource):
    """Key resource."""

    ledger: LedgerType
    address: str
    private_key: str

    @classmethod
    def load(cls, path: Path) -> "Key":
        """Load a service"""
        return super().load(path)  # type: ignore


class KeysManager(metaclass=SingletonMeta):
    """Keys manager."""

    def __init__(self, **kwargs: Any) -> None:
        """
        Initialize keys manager

        :param path: Path to keys storage.
        :param logger: logging.Logger object.
        """
        if "path" not in kwargs:
            raise ValueError("Path must be provided for KeysManager")

        self.path = kwargs["path"]
        self.logger = kwargs["logger"]
        self.path.mkdir(exist_ok=True, parents=True)

    def get(self, key: str) -> Key:
        """Get key object."""
        KeysManager.migrate_format(self.path / key)
        return Key.from_json(  # type: ignore
            obj=json.loads(
                (self.path / key).read_text(
                    encoding="utf-8",
                )
            )
        )

    def get_crypto_instance(self, address: str) -> EthereumCrypto:
        """Get EthereumCrypto instance for the given address."""
        key: Key = Key.from_json(  # type: ignore
            obj=json.loads(
                (self.path / address).read_text(
                    encoding="utf-8",
                )
            )
        )
        private_key = key.private_key
        # Create temporary file with delete=False to handle it manually
        with tempfile.NamedTemporaryFile(
            dir=self.path,
            mode="w",
            suffix=".txt",
            delete=False,  # Handle cleanup manually
        ) as temp_file:
            temp_file_name = temp_file.name
            temp_file.write(private_key)
            temp_file.flush()
            temp_file.close()  # Close the file before reading

            # Set proper file permissions (readable by owner only)
            os.chmod(temp_file_name, 0o600)
            crypto = EthereumCrypto(private_key_path=temp_file_name)

            try:
                with open(temp_file_name, "r+", encoding="utf-8") as f:
                    f.seek(0)
                    f.write("\0" * len(private_key))
                    f.flush()
                    f.close()
                os.unlink(temp_file_name)  # Clean up the temporary file
            except OSError as e:
                self.logger.error(f"Failed to delete temp file {temp_file.name}: {e}")

        return crypto

    def create(self) -> str:
        """Creates new key."""
        self.path.mkdir(exist_ok=True, parents=True)
        crypto = EthereumCrypto()
        for path in (
            self.path / f"{crypto.address}.bak",
            self.path / crypto.address,
        ):
            if path.is_file():
                continue

            path.write_text(
                json.dumps(
                    Key(
                        ledger=LedgerType.ETHEREUM,
                        address=crypto.address,
                        private_key=crypto.private_key,
                    ).json,
                    indent=4,
                ),
                encoding="utf-8",
            )

        return crypto.address

    def delete(self, key: str) -> None:
        """Delete key."""
        os.remove(self.path / key)

    @classmethod
    def migrate_format(cls, path: Path) -> bool:
        """Migrate the JSON file format if needed."""
        migrated = False
        backup_path = path.with_suffix(".bak")
        if not backup_path.is_file():
            shutil.copyfile(path, backup_path)
            migrated = True

        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

        old_to_new_ledgers = {0: "ethereum", 1: "solana"}
        if data.get("ledger") in old_to_new_ledgers:
            data["ledger"] = old_to_new_ledgers.get(data["ledger"])
            migrated = True

        if migrated:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)

        return migrated
