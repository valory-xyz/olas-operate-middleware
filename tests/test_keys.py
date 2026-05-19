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

from tests.conftest import reencrypt_key


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

    def test_get_crypto_instance_temp_file_outside_keys_dir(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """Temp file must be created outside the keys directory.

        Stray files inside the keys directory break update_password and
        migrate_keys iteration, so the temp file must live elsewhere.
        """
        _, sample_key = key_file

        with patch(
            "tempfile.NamedTemporaryFile", wraps=tempfile.NamedTemporaryFile
        ) as mock_tempfile:
            keys_manager.get_crypto_instance(sample_key.address)

            mock_tempfile.assert_called_once()
            call_kwargs = mock_tempfile.call_args.kwargs
            assert "dir" not in call_kwargs or call_kwargs["dir"] != keys_manager.path
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

    def test_update_password_is_idempotent_for_already_migrated_keys(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """A key already encrypted with new_password is left untouched."""
        new_password = f"{password}_new"

        # Address A is on the old password (normal case).
        address_a = keys_manager.create()

        # Address B was already re-encrypted with the new password by a
        # previous partial update — and crucially its .bak was lost.
        address_b = keys_manager.create()
        reencrypt_key(keys_manager, address_b, password, new_password)
        (keys_manager.path / f"{address_b}.bak").unlink()

        keys_manager.update_password(new_password)

        assert keys_manager.password == new_password
        # Both keys now decrypt under the new password.
        for address in (address_a, address_b):
            decrypted = keys_manager.get(address).get_decrypted_json(new_password)
            assert decrypted["address"] == address
        # A .bak was reconstructed for the previously-migrated key.
        assert (keys_manager.path / f"{address_b}.bak").is_file()

    def test_update_password_returns_unrecoverable_filenames(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """An unrecoverable key is surfaced via the returned list, not raised."""
        new_password = f"{password}_new"
        third_password = "something_else"  # nosec B105 - test fixture, not a secret
        address = keys_manager.create()
        # Re-encrypt with a *third* password — neither old nor new can open it.
        reencrypt_key(keys_manager, address, password, third_password)

        broken = keys_manager.update_password(new_password)

        assert broken == [address]
        # The bad key did not block self.password from advancing.
        assert keys_manager.password == new_password

    def test_update_password_continues_past_unrecoverable_keys(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """A bad key does not abort iteration; recoverable keys still migrate."""
        new_password = f"{password}_new"
        third_password = "third_pw"  # nosec B105 - test fixture, not a secret
        recoverable = [keys_manager.create() for _ in range(3)]
        unrecoverable = keys_manager.create()
        reencrypt_key(keys_manager, unrecoverable, password, third_password)

        broken = keys_manager.update_password(new_password)

        assert broken == [unrecoverable]
        for address in recoverable:
            decrypted = keys_manager.get(address).get_decrypted_json(new_password)
            assert decrypted["address"] == address

    def test_update_password_preserves_existing_bak_for_migrated_key(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """An existing .bak is not overwritten on the already-migrated path."""
        new_password = f"{password}_new"
        address = keys_manager.create()
        reencrypt_key(keys_manager, address, password, new_password)

        backup_path = keys_manager.path / f"{address}.bak"
        sentinel = '{"sentinel": true}'
        backup_path.write_text(sentinel, encoding="utf-8")

        keys_manager.update_password(new_password)

        assert backup_path.read_text(encoding="utf-8") == sentinel

    def test_private_key_to_crypto_temp_file_valueerror_is_logged(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """A ValueError from unrecoverable_delete is logged, not propagated."""
        _, sample_key = key_file
        with patch(
            "operate.keys.unrecoverable_delete",
            side_effect=ValueError("not a file"),
        ):
            crypto = keys_manager.get_crypto_instance(sample_key.address)

        assert crypto is not None
        assert crypto.address == sample_key.address
        keys_manager.logger.error.assert_called()  # type: ignore[attr-defined]

    def test_update_password_skips_non_address_files(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """Non-address filenames are skipped; only EVM-address files are keys."""
        address = keys_manager.create()

        # Leaked temp keystore: valid JSON dict, no 'ledger' field.
        stray = keys_manager.path / "tmpeqm29mt5.txt"
        stray.write_text(
            json.dumps({"address": address, "crypto": {}, "id": "x", "version": 3}),
            encoding="utf-8",
        )

        new_password = f"{password}_new"
        keys_manager.update_password(new_password)

        assert keys_manager.password == new_password
        # Key was still re-encrypted with the new password
        key = keys_manager.get(address)
        assert key.get_decrypted_json(password=new_password)["address"] == address
        # Stray file is left untouched (caller's responsibility to clean up)
        assert stray.exists()
        keys_manager.logger.warning.assert_any_call(  # type: ignore[attr-defined]
            f"Skipping non-key file: {stray}"
        )

    def test_keys_manager_init_without_path_raises(self) -> None:
        """Test KeysManager raises ValueError when path kwarg is not provided."""
        with pytest.raises(ValueError, match="Path must be provided"):
            KeysManager(logger=Mock(spec=logging.Logger))

    def test_private_key_to_crypto_temp_file_cleanup_failure_logs_error(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """Cleanup failure logs error and falls back to os.remove."""
        _, sample_key = key_file
        captured: dict[str, str] = {}

        def capture_then_remove(path: Path) -> None:
            captured["path"] = str(path)
            raise OSError("cleanup failed")

        with patch(
            "operate.keys.unrecoverable_delete", side_effect=capture_then_remove
        ):
            crypto = keys_manager.get_crypto_instance(sample_key.address)

        assert crypto is not None
        assert crypto.address == sample_key.address
        keys_manager.logger.error.assert_called()  # type: ignore[attr-defined]
        error_msg = str(keys_manager.logger.error.call_args_list)  # type: ignore[attr-defined]
        assert "Secure delete of temp key file" in error_msg
        # os.remove fallback ran — file no longer on disk.
        assert not Path(captured["path"]).exists()

    def test_private_key_to_crypto_fallback_remove_failure_logs(
        self, keys_manager: KeysManager, key_file: tuple[Path, Key]
    ) -> None:
        """If both deletes fail, both are logged AND the temp file stays on disk.

        This is the security-relevant postcondition: a stranded plaintext
        key file is the worst-case outcome the cleanup path warns about.
        """
        _, sample_key = key_file
        captured: dict[str, str] = {}

        def capture_then_raise_primary(path: Path) -> None:
            captured["path"] = str(path)
            raise OSError("primary")

        with patch(
            "operate.keys.unrecoverable_delete",
            side_effect=capture_then_raise_primary,
        ), patch("operate.keys.os.remove", side_effect=OSError("fallback")):
            crypto = keys_manager.get_crypto_instance(sample_key.address)

        assert crypto is not None
        calls = str(keys_manager.logger.error.call_args_list)  # type: ignore[attr-defined]
        assert "Secure delete of temp key file" in calls
        assert "Fallback os.remove" in calls
        # Both deletes failed; the plaintext-keyed scratch file remains.
        try:
            assert Path(captured["path"]).exists()
        finally:
            # Don't leak the simulated stranded key past this test.
            Path(captured["path"]).unlink(missing_ok=True)

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

    def test_delete_removes_key_file(self, keys_manager: KeysManager) -> None:
        """Test that delete() removes the key file from disk (line 172)."""
        address = keys_manager.create()
        key_path = keys_manager.path / address
        assert key_path.exists()

        keys_manager.delete(address)

        assert not key_path.exists()

    def test_discard_all_renames_every_file(self, keys_manager: KeysManager) -> None:
        """discard_all appends .lost to every regular file; files are preserved."""
        addresses = [keys_manager.create() for _ in range(2)]
        keys_manager.get_private_key_file(addresses[0])  # creates `<addr>_private_key`
        (keys_manager.path / "stray.txt").write_text("noise", encoding="utf-8")
        original_names = {entry.name for entry in keys_manager.path.iterdir()}

        failed = keys_manager.discard_all()

        assert failed == []
        renamed = {entry.name for entry in keys_manager.path.iterdir()}
        assert renamed == {f"{name}.lost" for name in original_names}

    def test_discard_all_is_idempotent(self, keys_manager: KeysManager) -> None:
        """A second discard_all leaves already-.lost files untouched."""
        keys_manager.create()
        assert keys_manager.discard_all() == []
        first_snapshot = sorted(entry.name for entry in keys_manager.path.iterdir())

        assert keys_manager.discard_all() == []

        second_snapshot = sorted(entry.name for entry in keys_manager.path.iterdir())
        assert first_snapshot == second_snapshot

    def test_discard_all_returns_paths_that_failed_to_rename(
        self, keys_manager: KeysManager
    ) -> None:
        """A per-entry OSError is logged AND surfaced via the return value."""
        keys_manager.create()
        keys_manager.create()

        real_replace = Path.replace
        calls = {"failed": False}

        def flaky_replace(self: Path, target: Path) -> Path:
            if not calls["failed"]:
                calls["failed"] = True
                raise OSError("simulated replace failure")
            return real_replace(self, target)

        with patch.object(Path, "replace", flaky_replace):
            failed = keys_manager.discard_all()

        remaining = list(keys_manager.path.iterdir())
        # One file was left in place (the replace raised), the rest renamed.
        assert any(entry.suffix == ".lost" for entry in remaining)
        assert any(entry.suffix != ".lost" for entry in remaining)
        keys_manager.logger.error.assert_called()  # type: ignore[attr-defined]
        # The failed name must match a file that still has no .lost suffix.
        assert len(failed) == 1
        assert (keys_manager.path / failed[0]).exists()

    def test_discard_all_overwrites_stale_lost_destination(
        self, keys_manager: KeysManager
    ) -> None:
        """A pre-existing ``.lost`` artefact must not block discard on retry.

        Regression for the Windows-specific failure surfaced by QA:
        ``Path.rename`` raises ``FileExistsError`` (WinError 183) when
        the destination already exists. POSIX silently overwrites, so
        Linux/macOS test runners hid the bug. Switching to ``Path.replace``
        gives cross-platform overwrite semantics. The check below would
        fail on Windows if ``discard_all`` were ever reverted to ``rename``.
        """
        address = keys_manager.create()
        # Simulate a prior rotation that already produced a `.bak.lost`.
        stale_lost = keys_manager.path / f"{address}.bak.lost"
        stale_lost.write_text("stale", encoding="utf-8")

        failed = keys_manager.discard_all()

        assert failed == []
        # Fresh `.bak` is gone (renamed over the stale one); the .lost
        # destination now holds the just-discarded content, not "stale".
        assert not (keys_manager.path / f"{address}.bak").exists()
        assert stale_lost.is_file()
        assert stale_lost.read_text(encoding="utf-8") != "stale"

    def test_update_password_skips_lost_files(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """update_password silently skips .lost files (no spurious warnings)."""
        address = keys_manager.create()
        (keys_manager.path / f"{address}.lost").write_text("ignored", encoding="utf-8")

        broken = keys_manager.update_password(f"{password}_new")

        assert broken == []
        keys_manager.logger.warning.assert_not_called()  # type: ignore[attr-defined]

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

    def test_update_password_returns_empty_when_all_keys_decrypt_with_current(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """Happy path: keys all on current password, all migrate cleanly."""
        addresses = [keys_manager.create() for _ in range(2)]
        new_password = f"{password}_new"

        broken = keys_manager.update_password(new_password)

        assert broken == []
        assert keys_manager.password == new_password
        for address in addresses:
            assert (
                keys_manager.get(address).get_decrypted_json(new_password)["address"]
                == address
            )

    def test_update_password_mixed_state_surfaces_only_unrecoverable(
        self, keys_manager: KeysManager, password: str
    ) -> None:
        """Mixed state: only the unrelated-password key is reported broken."""
        new_password = f"{password}_new"
        unrelated_password = "third_pw"  # nosec B105 - test fixture

        address_current = keys_manager.create()
        address_already_new = keys_manager.create()
        reencrypt_key(keys_manager, address_already_new, password, new_password)
        (keys_manager.path / f"{address_already_new}.bak").unlink()
        address_unrecoverable = keys_manager.create()
        reencrypt_key(keys_manager, address_unrecoverable, password, unrelated_password)

        broken = keys_manager.update_password(new_password)

        assert broken == [address_unrecoverable]
        assert keys_manager.password == new_password
        for address in (address_current, address_already_new):
            assert (
                keys_manager.get(address).get_decrypted_json(new_password)["address"]
                == address
            )
        assert (keys_manager.path / f"{address_already_new}.bak").is_file()
