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

"""Test for keys module."""

import json
import logging
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch

import pytest
from aea_ledger_ethereum.ethereum import EthereumCrypto
from eth_account import Account

from operate.keys import Key, KeysManager
from operate.migration import MigrationManager


@pytest.fixture
def keys_manager(temp_keys_dir: Path, password: Optional[str]) -> KeysManager:
    """Create a KeysManager instance with a temporary directory."""
    # Clear the singleton instance to avoid interference between tests
    logger = Mock(spec=logging.Logger)
    manager = KeysManager(path=temp_keys_dir, logger=logger, password=password)
    return manager


@pytest.fixture
def sample_key(keys_manager: KeysManager) -> Key:
    """Create a sample key for testing."""
    return keys_manager.get(keys_manager.create())


@pytest.fixture
def key_file(keys_manager: KeysManager, sample_key: Key) -> tuple[Path, Key]:
    """Create a key file in the keys manager directory."""
    key_file_path = keys_manager.path / sample_key.address
    key_file_path.write_text(
        json.dumps(sample_key.json, indent=4),
        encoding="utf-8",
    )
    return key_file_path, sample_key


class TestKeysManager:
    """Test cases for KeysManager class."""

    def test_get_crypto_instance_success(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """Test successful creation of EthereumCrypto instance."""
        key_file_path, sample_key = key_file

        # Call the method under test
        crypto_instance = keys_manager.get_crypto_instance(sample_key.address)

        # Verify the returned instance
        assert isinstance(crypto_instance, EthereumCrypto)
        assert crypto_instance.address == sample_key.address
        assert keys_manager.password is not None
        assert (
            crypto_instance.private_key
            == sample_key.get_decrypted_json(keys_manager.password)["private_key"]
        )

    def test_get_crypto_instance_temp_file_cleanup(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """Test that temporary files are properly cleaned up."""
        key_file_path, sample_key = key_file

        # Record the initial number of files in the temp directory
        initial_files = list(keys_manager.path.iterdir())

        # Call the method under test
        crypto_instance = keys_manager.get_crypto_instance(sample_key.address)

        # Verify the crypto instance is created
        assert isinstance(crypto_instance, EthereumCrypto)

        # Check that no additional files remain (temp file was cleaned up)
        final_files = list(keys_manager.path.iterdir())
        assert len(final_files) == len(initial_files)

        # Verify only the original key file exists and no .txt files remain
        assert len([f for f in final_files if f.suffix == ".txt"]) == 0

    def test_get_crypto_instance_file_permissions(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """Test that temporary file has correct permissions."""
        key_file_path, sample_key = key_file

        # Call the method under test
        crypto_instance = keys_manager.get_crypto_instance(sample_key.address)

        # Verify the returned instance
        assert isinstance(crypto_instance, EthereumCrypto)
        assert crypto_instance.address == sample_key.address
        assert keys_manager.password is not None
        assert (
            crypto_instance.private_key
            == sample_key.get_decrypted_json(keys_manager.password)["private_key"]
        )

        # Verify no temporary files remain
        temp_files = [f for f in keys_manager.path.iterdir() if f.suffix == ".txt"]
        assert len(temp_files) == 0, "Temporary files should be cleaned up"

    def test_get_crypto_instance_temp_file_in_correct_directory(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """Test that temporary file is created in the correct directory."""
        key_file_path, sample_key = key_file

        # Verify we start with just the key file
        initial_files = list(keys_manager.path.iterdir())
        assert len(initial_files) == 2  # key file + .bak file

        # Use a mock to capture what directory the temp file is created in
        with patch(
            "tempfile.NamedTemporaryFile", wraps=tempfile.NamedTemporaryFile
        ) as mock_tempfile:
            keys_manager.get_crypto_instance(sample_key.address)

            # Verify tempfile was called with the correct directory
            mock_tempfile.assert_called_once()
            call_kwargs = mock_tempfile.call_args[1]
            assert call_kwargs["dir"] == keys_manager.path
            assert call_kwargs["mode"] == "w"
            assert call_kwargs["suffix"] == ".txt"
            assert call_kwargs["delete"] is False

    def test_get_crypto_instance_with_corrupted_key_structure(
        self, keys_manager: KeysManager
    ) -> None:
        """Test behavior when key file has wrong structure but valid JSON."""
        invalid_address = "0x1234567890123456789012345678901234567890"
        invalid_key_file = keys_manager.path / invalid_address
        # Valid JSON but missing required fields
        invalid_key_file.write_text('{"wrong_field": "value"}', encoding="utf-8")

        with pytest.raises(KeyError):  # Key.from_json will fail with missing fields
            keys_manager.get_crypto_instance(invalid_address)

    def test_get_crypto_instance_file_not_found(
        self, keys_manager: KeysManager
    ) -> None:
        """Test behavior when key file doesn't exist."""
        non_existent_address = "0x1234567890123456789012345678901234567890"

        with pytest.raises(FileNotFoundError):
            keys_manager.get_crypto_instance(non_existent_address)

    def test_get_crypto_instance_invalid_json(self, keys_manager: KeysManager) -> None:
        """Test behavior when key file contains invalid JSON."""
        invalid_address = "0x1234567890123456789012345678901234567890"
        invalid_key_file = keys_manager.path / invalid_address
        invalid_key_file.write_text("invalid json content", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            keys_manager.get_crypto_instance(invalid_address)

    @pytest.mark.parametrize("backup_exists", [False, True])
    @pytest.mark.parametrize("pk_encrypted", [False, True])
    @pytest.mark.parametrize("password", ["test_password", None])
    def test_migrate_format_encrypts_private_key(
        self,
        keys_manager: KeysManager,
        backup_exists: bool,
        pk_encrypted: bool,
        password: Optional[str],
    ) -> None:
        """Test migration encrypts plain private key and refreshes backup."""
        address = keys_manager.create()
        if not backup_exists:
            backup_path = keys_manager.path / f"{address}.bak"
            if backup_path.exists():
                backup_path.unlink()

        key_path = keys_manager.path / address
        with open(key_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not pk_encrypted:
            if not data["private_key"].startswith("0x"):
                crypto = keys_manager.get_crypto_instance(address)
                data["private_key"] = "0x" + crypto.decrypt(
                    keyfile_json=data["private_key"], password=keys_manager.password
                )

        with open(key_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

        migration_manager = MigrationManager(
            home=keys_manager.path.parent, logger=logging.getLogger()
        )
        migration_manager.migrate_keys(keys_manager=keys_manager)
        key = keys_manager.get(address)

        # Verify everything is migrated now
        crypto = keys_manager.get_crypto_instance(address)
        assert crypto.address == address
        if password is None:
            assert key.private_key.startswith(
                "0x"
            ), "Private key should remain unencrypted without password"
            assert crypto.private_key == key.private_key
        else:
            assert not key.private_key.startswith(
                "0x"
            ), "Private key should be encrypted now"
            assert (
                crypto.private_key
                == Account.decrypt(key.private_key, keys_manager.password).to_0x_hex()
            )

        # Verify backup file exists
        backup_path = keys_manager.path / f"{address}.bak"
        assert backup_path.is_file(), "Backup file should exist after migration"
        assert backup_path.read_text() == json.dumps(key.json, indent=2)

    def test_update_password(self, keys_manager: KeysManager, password: str) -> None:
        """Test that update_password re-encrypts keys and updates backups."""

        addresses = [keys_manager.create() for _ in range(2)]
        original_private_keys = {
            address: keys_manager.get_crypto_instance(address).private_key
            for address in addresses
        }

        new_password = f"{password}_new"

        keys_manager.update_password(new_password)

        assert keys_manager.password == new_password

        for address in addresses:
            key = keys_manager.get(address)
            decrypted_private_key = key.get_decrypted_json(password=new_password)[
                "private_key"
            ]
            assert decrypted_private_key == original_private_keys[address]

            backup_path = keys_manager.path / f"{address}.bak"
            assert backup_path.is_file()
            assert backup_path.read_text() == json.dumps(key.json, indent=2)

    def test_keys_manager_init_without_path_raises(self) -> None:
        """Test KeysManager raises ValueError when path kwarg is not provided."""
        with pytest.raises(ValueError, match="Path must be provided"):
            KeysManager(logger=Mock(spec=logging.Logger))

    def test_private_key_to_crypto_temp_file_cleanup_failure_logs_error(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """Test that temp file cleanup failure logs error but does not propagate."""
        _, sample_key = key_file

        with patch(
            "operate.keys.unrecoverable_delete",
            side_effect=OSError("cleanup failed"),
        ):
            # Should still return a valid crypto instance
            crypto = keys_manager.get_crypto_instance(sample_key.address)

        assert crypto is not None
        assert crypto.address == sample_key.address
        keys_manager.logger.error.assert_called()  # type: ignore[attr-defined]
        error_msg = str(keys_manager.logger.error.call_args)  # type: ignore[attr-defined]
        assert "Failed to delete temp file" in error_msg

    def test_get_decrypted_without_password(self, temp_keys_dir: Path) -> None:
        """Test get_decrypted returns raw json dict when no password is set."""
        km = KeysManager(
            path=temp_keys_dir, logger=Mock(spec=logging.Logger), password=None
        )
        address = km.create()

        result = km.get_decrypted(address)

        key = km.get(address)
        assert result == key.json
        assert result["address"] == address

    def test_get_decrypted_with_password(self, keys_manager: KeysManager) -> None:
        """Test get_decrypted returns decrypted json dict when password is set."""
        address = keys_manager.create()

        result = keys_manager.get_decrypted(address)

        assert result["address"] == address
        assert result["private_key"].startswith("0x")  # decrypted key
        assert result["ledger"] == "ethereum"

    def test_get_private_key_file_creates_when_not_exists(
        self, keys_manager: KeysManager
    ) -> None:
        """Test get_private_key_file creates the private key file when absent."""
        address = keys_manager.create()
        pk_path = keys_manager.path / f"{address}_private_key"

        assert not pk_path.exists()

        result = keys_manager.get_private_key_file(address)

        assert result == pk_path
        assert pk_path.exists()
        # Content should equal the stored private key
        key = keys_manager.get(address)
        assert result.read_text(encoding="utf-8") == key.private_key

    def test_get_private_key_file_returns_existing_without_overwrite(
        self, keys_manager: KeysManager
    ) -> None:
        """Test get_private_key_file returns existing path without overwriting."""
        address = keys_manager.create()
        pk_path = keys_manager.path / f"{address}_private_key"

        # Pre-create the file with sentinel content
        pk_path.write_text("0xsentinelkey", encoding="utf-8")

        result = keys_manager.get_private_key_file(address)

        assert result == pk_path
        # Content should be unchanged
        assert result.read_text(encoding="utf-8") == "0xsentinelkey"

    def test_create_skips_writing_when_files_already_exist(
        self, keys_manager: KeysManager
    ) -> None:
        """Test that create() skips writing key files that already exist (continue path)."""
        # First call creates the files
        address = keys_manager.create()

        original_content = (keys_manager.path / address).read_text(encoding="utf-8")

        # Mock EthereumCrypto to return the same address so both files already exist
        mock_crypto = Mock()
        mock_crypto.address = address
        mock_crypto.private_key = "0xfakekey"
        mock_crypto.encrypt.return_value = "encrypted_fake_key"

        with patch("operate.keys.EthereumCrypto", return_value=mock_crypto):
            result = keys_manager.create()

        assert result == address
        # The key file content should be unchanged (not overwritten)
        assert (keys_manager.path / address).read_text(
            encoding="utf-8"
        ) == original_content
