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
from unittest.mock import Mock, patch

import pytest
from aea_ledger_ethereum.ethereum import EthereumCrypto

from operate.keys import Key, KeysManager
from operate.operate_types import LedgerType


@pytest.fixture
def keys_manager(temp_keys_dir: Path) -> KeysManager:
    """Create a KeysManager instance with a temporary directory."""
    # Clear the singleton instance to avoid interference between tests
    KeysManager._instances = {}
    logger = Mock(spec=logging.Logger)
    manager = KeysManager(path=temp_keys_dir, logger=logger)
    return manager


@pytest.fixture
def sample_key() -> Key:
    """Create a sample key for testing."""
    crypto = EthereumCrypto()
    return Key(
        ledger=LedgerType.ETHEREUM,
        address=crypto.address,
        private_key=crypto.private_key,
    )


@pytest.fixture
def key_file(keys_manager: KeysManager, sample_key: Key) -> tuple[Path, Key]:
    """Create a key file in the keys manager directory."""
    key_file_path = keys_manager.path / sample_key.address
    key_file_path.write_text(
        json.dumps(sample_key.json, indent=4),
        encoding="utf-8",
    )
    return key_file_path, sample_key


@pytest.mark.skip(reason="DEBUG")

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
        assert crypto_instance.private_key == sample_key.private_key

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
        assert crypto_instance.private_key == sample_key.private_key

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
        assert len(initial_files) == 1

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
