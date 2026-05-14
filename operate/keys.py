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
import tempfile
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any, Optional

from aea_ledger_ethereum.ethereum import EthereumCrypto
from web3 import Web3

from operate.operate_types import LedgerType
from operate.resource import LocalResource
from operate.utils import unrecoverable_delete


@dataclass
class Key(LocalResource):
    """Key resource."""

    ledger: LedgerType
    address: str
    private_key: str

    def get_decrypted_json(self, password: str) -> dict:
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


class KeysManager:
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
        self.password: Optional[str] = kwargs.get("password")
        self.path.mkdir(exist_ok=True, parents=True)

    def private_key_to_crypto(
        self, private_key: str, password: Optional[str]
    ) -> EthereumCrypto:
        """Convert private key string to EthereumCrypto instance."""
        temp_file = tempfile.NamedTemporaryFile(  # pylint: disable=consider-using-with
            mode="w",
            suffix=".txt",
            delete=False,
        )
        temp_file_name = temp_file.name
        try:
            temp_file.write(private_key)
            temp_file.flush()
            temp_file.close()
            os.chmod(temp_file_name, 0o600)
            return EthereumCrypto(private_key_path=temp_file_name, password=password)
        finally:
            try:
                unrecoverable_delete(Path(temp_file_name))
            except (OSError, ValueError) as e:
                self.logger.error(f"Failed to delete temp file {temp_file_name}: {e}")

    def get(self, key: str) -> Key:
        """Get key object."""
        return Key.from_json(  # type: ignore
            obj=json.loads(
                (self.path / key).read_text(
                    encoding="utf-8",
                )
            )
        )

    def get_decrypted(self, key: str) -> dict:
        """Get key json."""
        if self.password is not None:
            return self.get(key).get_decrypted_json(self.password)
        return self.get(key).json

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
        key: Key = self.get(address)
        return self.private_key_to_crypto(key.private_key, self.password)

    def create(self) -> str:
        """Creates new key."""
        self.path.mkdir(exist_ok=True, parents=True)
        crypto = EthereumCrypto(password=self.password)
        key = Key(
            ledger=LedgerType.ETHEREUM,
            address=crypto.address,
            private_key=(
                crypto.encrypt(password=self.password)
                if self.password is not None
                else crypto.private_key
            ),
        )
        for path in (
            self.path / f"{crypto.address}.bak",
            self.path / crypto.address,
        ):
            if path.is_file():
                continue

            path.write_text(
                json.dumps(
                    key.json,
                    indent=2,
                ),
                encoding="utf-8",
            )

        return crypto.address

    def delete(self, key: str) -> None:
        """Delete key."""
        os.remove(self.path / key)

    def update_password(self, new_password: str) -> None:
        """Update password for all keys.

        Idempotent: a key already encrypted with ``new_password`` is detected
        and skipped, so retrying a previously-interrupted update converges.
        """
        for key_file in self.path.iterdir():
            if not key_file.is_file() or key_file.suffix == ".bak":
                continue
            if not Web3.is_address(key_file.name):
                self.logger.warning(f"Skipping non-key file: {key_file}")
                continue

            key = self.get(key_file.name)
            try:
                crypto = self.private_key_to_crypto(key.private_key, self.password)
            except ValueError as primary_exc:
                # Decrypt with new_password to detect a prior partial migration.
                self.logger.info(
                    "Key %s did not open with the current password (%s); "
                    "checking new password.",
                    key_file.name,
                    primary_exc,
                )
                try:
                    self.private_key_to_crypto(key.private_key, new_password)
                except ValueError:
                    raise ValueError(
                        f"Key {key_file.name} cannot be decrypted with the "
                        "current or the new password."
                    ) from primary_exc

                # The .bak written here is a post-migration snapshot
                # (encrypted with new_password), not a rollback artifact.
                backup_path = self.path / f"{key.address}.bak"
                if not backup_path.exists():
                    backup_path.write_text(
                        json.dumps(key.json, indent=2),
                        encoding="utf-8",
                    )
                continue

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
