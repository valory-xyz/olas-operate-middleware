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
from logging import Logger
from pathlib import Path
from typing import Any

from aea_ledger_ethereum.ethereum import EthereumCrypto

from operate.operate_types import LedgerType
from operate.resource import LocalResource
from operate.utils import SingletonMeta, unrecoverable_delete


@dataclass
class Key(LocalResource):
    """Key resource."""

    ledger: LedgerType
    address: str
    private_key: str

    def get_decrypted(self, password: str) -> dict:
        """Get decrypted key json."""
        return {
            "ledger": self.ledger.value,
            "address": self.address,
            "private_key": "0x"
            + EthereumCrypto.decrypt(self.private_key, password=password),
        }

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

        self.path: Path = kwargs["path"]
        self.logger: Logger = kwargs["logger"]
        self.password: str = kwargs.get("password", "")
        self.path.mkdir(exist_ok=True, parents=True)

    def get(self, key: str) -> Key:
        """Get key object."""
        KeysManager.migrate_format(self.path / key, password=self.password)
        return Key.from_json(  # type: ignore
            obj=json.loads(
                (self.path / key).read_text(
                    encoding="utf-8",
                )
            )
        )

    def get_private_key_file(self, address: str) -> Path:
        """Get the path to the private key file for the given address."""
        path = self.path / f"{address}_private_key"

        if path.is_file():
            return path

        key = self.get(address)
        private_key = key.private_key
        path.write_text(private_key, encoding="utf-8")
        os.chmod(path, 0o600)
        return path

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
            password = None if private_key.startswith("0x") else self.password
            crypto = EthereumCrypto(private_key_path=temp_file_name, password=password)

            try:
                with open(temp_file_name, "r+", encoding="utf-8") as f:
                    f.seek(0)
                    f.write("\0" * len(private_key))
                    f.flush()
                    f.close()
                unrecoverable_delete(
                    Path(temp_file.name)
                )  # Clean up the temporary file
            except OSError as e:
                self.logger.error(f"Failed to delete temp file {temp_file.name}: {e}")

        return crypto

    def create(self) -> str:
        """Creates new key."""
        self.path.mkdir(exist_ok=True, parents=True)
        crypto = EthereumCrypto(password=self.password)
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
    def migrate_format(cls, path: Path, password: str) -> bool:
        """Migrate the JSON file format if needed."""
        migrated = False
        backup_path = path.with_suffix(".bak")

        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

        old_to_new_ledgers = {0: "ethereum", 1: "solana"}
        if data.get("ledger") in old_to_new_ledgers:
            data["ledger"] = old_to_new_ledgers.get(data["ledger"])
            with open(path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)

            migrated = True

        private_key = data.get("private_key")
        if private_key and private_key.startswith("0x"):
            crypto: EthereumCrypto = KeysManager().get_crypto_instance(data["address"])
            encrypted_private_key = crypto.encrypt(password=password)
            data["private_key"] = encrypted_private_key
            if backup_path.exists():
                unrecoverable_delete(backup_path)

            migrated = True

        if migrated:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)

        if not backup_path.is_file():
            shutil.copyfile(path, backup_path)

        return migrated

    def update_password(self, new_password: str) -> None:
        """Update password for all keys."""
        for key_file in self.path.iterdir():
            if not key_file.is_file() or key_file.suffix == ".bak":
                continue

            key = self.get(key_file.name)
            crypto = self.get_crypto_instance(key_file.name)
            encrypted_private_key = crypto.encrypt(password=new_password)
            key.private_key = encrypted_private_key
            key.path = self.path / key_file.name
            key.store()

            backup_path = self.path / f"{key.address}.bak"
            backup_path.write_text(
                json.dumps(key.json, indent=2),
                encoding="utf-8",
            )

        self.password = new_password
