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

"""Tests for operate.cli module."""

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch
from uuid import uuid4

import argon2
import pytest
from eth_account import Account
from web3 import Web3

from operate.cli import OperateApp
from operate.constants import (
    AGENT_RUNNER_PREFIX,
    DEPLOYMENT_DIR,
    MSG_INVALID_MNEMONIC,
    MSG_INVALID_PASSWORD,
    MSG_NEW_PASSWORD_MISSING,
    OPERATE,
    SERVICES_DIR,
    USER_JSON,
    VERSION_FILE,
)
from operate.keys import KeysManager
from operate.operate_types import EncryptedData, LedgerType, Version
from operate.services.service import SERVICE_CONFIG_PREFIX

from tests.conftest import random_string, reencrypt_key


def random_mnemonic(num_words: int = 12) -> str:
    """Generate a random BIP-39 mnemonic"""
    w3 = Web3()
    w3.eth.account.enable_unaudited_hdwallet_features()
    _, mnemonic = w3.eth.account.create_with_mnemonic(num_words=num_words)
    return mnemonic


class TestOperateApp:
    """Tests for operate.cli.OperateApp class."""

    def test_update_password(
        self,
        tmp_path: Path,
    ) -> None:
        """Test operate.update_password() and operate.update_password_with_mnemonic()"""

        operate = OperateApp(
            home=tmp_path / OPERATE,
        )
        operate.setup()
        password1 = random_string()
        operate.create_user_account(password=password1)
        operate.password = password1
        wallet_manager = operate.wallet_manager
        _, mnemonic_list = wallet_manager.create(LedgerType.ETHEREUM)
        num_words = len(mnemonic_list)
        mnemonic = " ".join(mnemonic_list)

        password2 = random_string()
        password3 = "!@#Test$%^"

        operate.update_password(password1, password1)
        assert operate.user_account.is_valid(password1)
        assert operate.wallet_manager.is_password_valid(password1)

        operate.update_password(password1, password2)
        assert not operate.user_account.is_valid(password1)
        assert not operate.wallet_manager.is_password_valid(password1)
        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)

        operate.update_password(password2, password3)
        assert not operate.user_account.is_valid(password2)
        assert not operate.wallet_manager.is_password_valid(password2)
        assert operate.user_account.is_valid(password3)
        assert operate.wallet_manager.is_password_valid(password3)

        operate.update_password(password3, password1)
        assert not operate.user_account.is_valid(password3)
        assert not operate.wallet_manager.is_password_valid(password3)
        assert operate.user_account.is_valid(password1)
        assert operate.wallet_manager.is_password_valid(password1)

        with pytest.raises(ValueError, match=rf"^{MSG_NEW_PASSWORD_MISSING}"):
            operate.update_password(password1, "")

        with pytest.raises(ValueError, match=rf"^{MSG_INVALID_PASSWORD}"):
            operate.update_password("", password2)

        wrong_password = random_string(length=9)
        with pytest.raises(ValueError, match=rf"^{MSG_INVALID_PASSWORD}"):
            operate.update_password(wrong_password, password2)

        operate.update_password_with_mnemonic(mnemonic, password1)
        assert operate.user_account.is_valid(password1)
        assert operate.wallet_manager.is_password_valid(password1)
        assert not operate.user_account.is_valid(password2)
        assert not operate.wallet_manager.is_password_valid(password2)

        operate.update_password_with_mnemonic(mnemonic, password2)
        assert not operate.user_account.is_valid(password1)
        assert not operate.wallet_manager.is_password_valid(password1)
        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)

        operate.update_password_with_mnemonic(mnemonic, password1)
        assert operate.user_account.is_valid(password1)
        assert operate.wallet_manager.is_password_valid(password1)
        assert not operate.user_account.is_valid(password2)
        assert not operate.wallet_manager.is_password_valid(password2)

        with pytest.raises(ValueError, match=rf"^{MSG_NEW_PASSWORD_MISSING}"):
            operate.update_password_with_mnemonic(mnemonic, "")

        with pytest.raises(ValueError, match=rf"^{MSG_INVALID_MNEMONIC}"):
            operate.update_password_with_mnemonic("", password2)

        invalid_mnemonic = random_mnemonic(num_words=num_words)
        with pytest.raises(ValueError, match=rf"^{MSG_INVALID_MNEMONIC}"):
            operate.update_password_with_mnemonic(invalid_mnemonic, password2)

        invalid_mnemonic = random_mnemonic(num_words=15)
        with pytest.raises(ValueError, match=rf"^{MSG_INVALID_MNEMONIC}"):
            operate.update_password_with_mnemonic(invalid_mnemonic, password2)

    def test_update_password_recovers_from_half_committed_state(
        self,
        tmp_path: Path,
    ) -> None:
        """Retry converges when the master wallet is already on new_password."""
        operate = OperateApp(home=tmp_path / OPERATE)
        operate.setup()

        password1 = random_string()
        password2 = random_string()

        operate.create_user_account(password=password1)
        operate.password = password1
        operate.wallet_manager.create(LedgerType.ETHEREUM)

        # Simulate the half-committed state: master wallet re-encrypted to
        # password2, but user.json still hashed for password1.
        wallet = next(iter(operate.wallet_manager))
        wallet.password = password1
        wallet.update_password(password2)
        assert operate.wallet_manager.is_password_valid(password2)
        assert not operate.wallet_manager.is_password_valid(password1)
        assert operate.user_account.is_valid(password1)

        # The retry must now succeed and bring everything to password2.
        operate.update_password(password1, password2)

        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)
        assert not operate.user_account.is_valid(password1)
        assert not operate.wallet_manager.is_password_valid(password1)

    def test_update_password_rejects_when_wallet_on_unknown_password(
        self,
        tmp_path: Path,
    ) -> None:
        """user.json passes auth but a stranger-password wallet still rejects the change."""
        operate = OperateApp(home=tmp_path / OPERATE)
        operate.setup()

        password1 = random_string()
        password2 = random_string()
        stranger = random_string()

        operate.create_user_account(password=password1)
        operate.password = password1
        operate.wallet_manager.create(LedgerType.ETHEREUM)

        wallet = next(iter(operate.wallet_manager))
        wallet.password = password1
        wallet.update_password(stranger)
        assert not operate.wallet_manager.is_password_valid(password1)
        assert not operate.wallet_manager.is_password_valid(password2)
        assert operate.user_account.is_valid(password1)

        with pytest.raises(ValueError, match=rf"^{MSG_INVALID_PASSWORD}"):
            operate.update_password(password1, password2)

    def test_update_password_raises_on_unrecoverable_agent_key(
        self,
        tmp_path: Path,
    ) -> None:
        """An agent key stuck on a forgotten password aborts the strict flow."""
        operate = OperateApp(home=tmp_path / OPERATE)
        operate.setup()

        password1 = random_string()
        password2 = random_string()
        forgotten = "forgotten-" + random_string()  # nosec B105 - test fixture

        operate.create_user_account(password=password1)
        operate.password = password1
        operate.wallet_manager.create(LedgerType.ETHEREUM)
        address_lost = operate.keys_manager.create()
        reencrypt_key(operate.keys_manager, address_lost, password1, forgotten)

        with pytest.raises(ValueError, match="cannot be decrypted"):
            operate.update_password(password1, password2)

    def test_update_password_converges_with_half_committed_agent_keys(
        self,
        tmp_path: Path,
    ) -> None:
        """End-to-end recovery when some agent keys are already on new_password."""
        operate = OperateApp(home=tmp_path / OPERATE)
        operate.setup()

        password1 = random_string()
        password2 = random_string()

        operate.create_user_account(password=password1)
        operate.password = password1
        operate.wallet_manager.create(LedgerType.ETHEREUM)
        address_old = operate.keys_manager.create()
        address_new = operate.keys_manager.create()

        # Half-commit: master wallet on password2, one agent key on password2,
        # user.json + the other agent key still on password1.
        wallet = next(iter(operate.wallet_manager))
        wallet.password = password1
        wallet.update_password(password2)
        reencrypt_key(operate.keys_manager, address_new, password1, password2)

        operate.update_password(password1, password2)

        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)
        # Re-read via a fresh KeysManager so the assertions exercise the
        # on-disk keystore rather than any in-memory state.
        fresh = KeysManager(
            path=operate.keys_manager.path,
            logger=logging.getLogger(),
            password=password2,
        )
        for address in (address_old, address_new):
            decrypted = fresh.get(address).get_decrypted_json(password2)
            assert decrypted["address"] == address

    def test_master_wallet_update_password_is_idempotent(
        self,
        tmp_path: Path,
    ) -> None:
        """Calling update_password twice with the same new password is safe."""
        operate = OperateApp(home=tmp_path / OPERATE)
        operate.setup()

        password1 = random_string()
        password2 = random_string()
        operate.create_user_account(password=password1)
        operate.password = password1
        operate.wallet_manager.create(LedgerType.ETHEREUM)

        wallet = next(iter(operate.wallet_manager))
        wallet.password = password1
        wallet.update_password(password2)
        # Second call must not raise even though the keystore is no longer
        # decryptable with the original self.password.
        wallet.update_password(password2)
        assert operate.wallet_manager.is_password_valid(password2)

    def test_migrate_account(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """Test operate.user_account.is_valid(password) and MigrationManager.migrate_user_account()"""

        operate_home_path = tmp_path / OPERATE
        operate = OperateApp(
            home=operate_home_path,
        )

        # Artificially create an old-format user.json
        sha256 = hashlib.sha256()
        sha256.update(password.encode())
        password_sha = sha256.hexdigest()
        data = {"password_sha": password_sha}
        user_json_path = operate_home_path / USER_JSON
        user_json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        operate = OperateApp(
            home=operate_home_path,
        )

        data = json.loads(user_json_path.read_text(encoding="utf-8"))

        assert operate.user_account
        assert "password_hash" in data
        assert "password_sha" not in data
        assert password_sha == data["password_hash"]
        ph = argon2.PasswordHasher()
        with pytest.raises(argon2.exceptions.InvalidHashError):
            ph.verify(data["password_hash"], password)

        operate.user_account.is_valid(password)
        data = json.loads(user_json_path.read_text(encoding="utf-8"))

        assert operate.user_account
        assert operate.user_account.is_valid(password)
        assert "password_hash" in data
        assert "password_sha" not in data
        assert password_sha != data["password_hash"]
        ph = argon2.PasswordHasher()
        assert ph.verify(data["password_hash"], password)

    @pytest.mark.parametrize("found_version", [None, "0.1.0", "0.5.0", "1.0.0"])
    @pytest.mark.parametrize("current_version", ["0.1.0", "0.5.0", "1.0.0"])
    def test_backup_operate_if_new_version(
        self, tmp_path: Path, found_version: Optional[str], current_version: str
    ) -> None:
        """Test operate.backup_operate_if_new_version()"""

        # prepare existing .operate directory (and backup if found_version is not None)
        found_operate = tmp_path / OPERATE
        found_operate.mkdir(parents=True, exist_ok=True)
        found_service = (
            found_operate / SERVICES_DIR / f"{SERVICE_CONFIG_PREFIX}{uuid4()}"
        )
        found_service.mkdir(parents=True, exist_ok=True)
        if found_version is not None:
            (found_operate / VERSION_FILE).write_text(found_version)
            found_backup_path = tmp_path / f"{OPERATE}_v0.0.0_bak"
            shutil.copytree(found_operate, found_backup_path)

        (found_service / DEPLOYMENT_DIR).mkdir(parents=True, exist_ok=True)
        (found_service / f"{AGENT_RUNNER_PREFIX}_{uuid4()}").touch()

        if found_version is None:
            assert not Path(tmp_path / OPERATE / VERSION_FILE).exists()
            assert len(list(Path(tmp_path).glob(f"{OPERATE}_v*_bak"))) == 0
        else:
            assert Path(tmp_path / OPERATE / VERSION_FILE).read_text() == found_version
            assert len(list(Path(tmp_path).glob(f"{OPERATE}_v*_bak"))) == 1

        with patch("operate.cli.__version__", current_version):
            OperateApp(home=tmp_path / OPERATE)

        backup_paths = sorted(list(Path(tmp_path).glob(f"{OPERATE}_v*_bak")))
        if found_version is None:
            # when no backup existed before, current .operate should be backed up
            assert len(backup_paths) == 1
            assert not (backup_paths[0] / VERSION_FILE).exists()
            assert (
                Path(tmp_path / OPERATE / VERSION_FILE).read_text() == current_version
            )
        elif Version(current_version) > Version(found_version):
            # when a newer version is detected, a new backup should be created
            assert len(backup_paths) == 2
            assert (backup_paths[0] / VERSION_FILE).read_text() == found_version
            assert (backup_paths[1] / VERSION_FILE).read_text() == found_version
            assert (
                Path(tmp_path / OPERATE / VERSION_FILE).read_text() == current_version
            )
        else:
            # when the version is the same or older, no new backup should be created
            assert len(backup_paths) == 1
            assert (backup_paths[0] / VERSION_FILE).read_text() == found_version
            assert Path(tmp_path / OPERATE / VERSION_FILE).read_text() == found_version

        for backup_path in backup_paths:
            # recoverable files should be removed from the backup
            service_dir = backup_path / SERVICES_DIR
            for service_path in service_dir.iterdir():
                deployment_dir = service_path / DEPLOYMENT_DIR
                assert not deployment_dir.exists()

                for agent_runner_path in service_path.glob(f"{AGENT_RUNNER_PREFIX}_*"):
                    assert not agent_runner_path.exists()


class TestMnemonicReencryptionOnPasswordChange:
    """The mnemonic blob must stay in sync with the user's current password."""

    def _setup_wallet_with_mnemonic(
        self, tmp_path: Path
    ) -> tuple[OperateApp, str, str]:
        operate = OperateApp(home=tmp_path / OPERATE)
        operate.setup()
        password1 = random_string()
        operate.create_user_account(password=password1)
        operate.password = password1
        _, mnemonic_list = operate.wallet_manager.create(LedgerType.ETHEREUM)
        return operate, password1, " ".join(mnemonic_list)

    def test_update_password_reencrypts_mnemonic_blob(self, tmp_path: Path) -> None:
        """update_password syncs the encrypted mnemonic to the new password."""
        operate, password1, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()

        operate.update_password(password1, password2)

        wallet = operate.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)
        assert wallet.decrypt_mnemonic(password=password2) == mnemonic.split()
        with pytest.raises(Exception):  # noqa: B017,PT011 - any decrypt error qualifies
            wallet.decrypt_mnemonic(password=password1)

    def test_update_password_with_mnemonic_refreshes_blob(self, tmp_path: Path) -> None:
        """update_password_with_mnemonic rewrites the blob under new_password."""
        operate, _, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()

        operate.update_password_with_mnemonic(mnemonic, password2)

        wallet = operate.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)
        assert wallet.decrypt_mnemonic(password=password2) == mnemonic.split()

    def test_update_password_without_mnemonic_blob_is_no_op_for_mnemonic_step(
        self, tmp_path: Path
    ) -> None:
        """A wallet missing its mnemonic blob still completes update_password."""
        operate, password1, _ = self._setup_wallet_with_mnemonic(tmp_path)
        wallet = next(iter(operate.wallet_manager))
        wallet.mnemonic_path.unlink()
        password2 = random_string()

        operate.update_password(password1, password2)

        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)
        assert not wallet.mnemonic_path.exists()

    def test_update_password_tolerates_wedged_mnemonic(self, tmp_path: Path) -> None:
        """Wedged blob (mnemonic encrypted under a forgotten password) doesn't block update."""
        operate, password1, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()
        wallet = next(iter(operate.wallet_manager))
        forgotten = "forgotten-" + random_string()  # nosec B105 - test fixture
        EncryptedData.new(
            path=wallet.mnemonic_path,
            password=forgotten,
            plaintext_bytes=mnemonic.encode("utf-8"),
        ).store()

        operate.update_password(password1, password2)

        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)
        # Wedged blob is left untouched; user must use seed-phrase recovery to
        # resync it.
        with pytest.raises(Exception):  # noqa: B017,PT011 - any decrypt error qualifies
            wallet.decrypt_mnemonic(password=password2)

    def test_update_password_with_mnemonic_discards_agent_keys(
        self,
        tmp_path: Path,
    ) -> None:
        """Seed-phrase recovery discards agent EOA keys (unrecoverable by definition).

        The original key files remain on disk for audit, but every entry
        in any service's ``agent_addresses`` is replaced with a freshly
        minted EOA encrypted under the new password.
        """
        operate, _, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()
        addresses = [operate.keys_manager.create(), operate.keys_manager.create()]

        operate.update_password_with_mnemonic(mnemonic, password2)

        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)
        for address in addresses:
            assert not (operate.keys_manager.path / address).exists()
            assert (operate.keys_manager.path / f"{address}.lost").is_file()
            assert (operate.keys_manager.path / f"{address}.bak.lost").is_file()

    def test_update_password_with_mnemonic_rotates_service_agent_addresses(
        self,
        tmp_path: Path,
    ) -> None:
        """Each service's agent_addresses are replaced with freshly minted EOAs.

        Pearl's seed-phrase password change loses access to existing
        agent EOA keys. Without rotation, the service config still
        references the (now ``.lost``) addresses and Service.build
        fails with ``FileNotFoundError`` on next start. The new flow
        mints a replacement per slot and rewrites the service config.
        """
        operate, _, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()
        old_agent_a = operate.keys_manager.create()
        old_agent_b = operate.keys_manager.create()
        # Two services to prove the rotation walks all of them.
        service_a = MagicMock(spec=["agent_addresses", "store"])
        service_a.agent_addresses = [old_agent_a]
        service_b = MagicMock(spec=["agent_addresses", "store"])
        service_b.agent_addresses = [old_agent_b]

        service_manager_stub = MagicMock()
        service_manager_stub.get_all_services.return_value = (
            [service_a, service_b],
            True,
        )
        with patch.object(
            operate, "service_manager", return_value=service_manager_stub
        ):
            operate.update_password_with_mnemonic(mnemonic, password2)

        for old, service in ((old_agent_a, service_a), (old_agent_b, service_b)):
            # Old key files are .lost; the new agent address is fresh and
            # has a real keystore on disk encrypted under password2.
            assert (operate.keys_manager.path / f"{old}.lost").is_file()
            assert not (operate.keys_manager.path / old).exists()
            [new_address] = service.agent_addresses
            assert new_address != old
            new_key_path = operate.keys_manager.path / new_address
            assert new_key_path.is_file()
            # decrypt with new password proves the file is usable.
            assert (
                operate.keys_manager.get(new_address).get_decrypted_json(
                    password=password2
                )["address"]
                == new_address
            )
            service.store.assert_called_once()

    def test_update_password_with_mnemonic_skips_services_without_agent_addresses(
        self,
        tmp_path: Path,
    ) -> None:
        """Services with empty agent_addresses are not rewritten."""
        operate, _, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()

        empty_service = MagicMock(spec=["agent_addresses", "store"])
        empty_service.agent_addresses = []

        service_manager_stub = MagicMock()
        service_manager_stub.get_all_services.return_value = ([empty_service], True)
        with patch.object(
            operate, "service_manager", return_value=service_manager_stub
        ):
            operate.update_password_with_mnemonic(mnemonic, password2)

        assert empty_service.agent_addresses == []
        empty_service.store.assert_not_called()

    def test_update_password_with_mnemonic_rotates_multi_agent_service(
        self,
        tmp_path: Path,
    ) -> None:
        """A service with multiple agent slots gets the right count of fresh, distinct EOAs."""
        operate, _, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()
        old_addresses = [
            operate.keys_manager.create(),
            operate.keys_manager.create(),
            operate.keys_manager.create(),
        ]
        service = MagicMock(spec=["agent_addresses", "store"])
        service.agent_addresses = list(old_addresses)

        service_manager_stub = MagicMock()
        service_manager_stub.get_all_services.return_value = ([service], True)
        with patch.object(
            operate, "service_manager", return_value=service_manager_stub
        ):
            operate.update_password_with_mnemonic(mnemonic, password2)

        assert len(service.agent_addresses) == len(old_addresses)
        # Each new address is distinct from every old one and from every
        # other new one.
        assert len(set(service.agent_addresses)) == len(old_addresses)
        assert set(service.agent_addresses).isdisjoint(set(old_addresses))
        for new_address in service.agent_addresses:
            assert (operate.keys_manager.path / new_address).is_file()
        service.store.assert_called_once()

    def test_update_password_with_mnemonic_warns_when_a_service_fails_to_load(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``get_all_services`` returning ``success=False`` must surface a warning.

        The loadable services are still rotated; the unloadable ones are
        skipped. The operator must be told because the unloadable
        services will keep hitting ``FileNotFoundError`` on start.
        """
        operate, _, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()
        old_address = operate.keys_manager.create()
        loadable_service = MagicMock(spec=["agent_addresses", "store"])
        loadable_service.agent_addresses = [old_address]

        service_manager_stub = MagicMock()
        # success=False signals that at least one service directory
        # failed to load and is missing from the returned list.
        service_manager_stub.get_all_services.return_value = (
            [loadable_service],
            False,
        )
        with caplog.at_level(logging.WARNING, logger="operate"):
            with patch.object(
                operate, "service_manager", return_value=service_manager_stub
            ):
                operate.update_password_with_mnemonic(mnemonic, password2)

        assert any(
            "service configs failed to load" in record.message
            for record in caplog.records
        )
        # The loadable service must still be rotated.
        [new_address] = loadable_service.agent_addresses
        assert new_address != old_address
        assert (operate.keys_manager.path / new_address).is_file()
        loadable_service.store.assert_called_once()

    def test_update_password_idempotent_path_still_reencrypts_mnemonic(
        self, tmp_path: Path
    ) -> None:
        """Idempotent retry must rewrite the blob even when the keystore is in sync.

        Simulates a crash between the keystore rewrite and the mnemonic
        rewrite: keystore is on password2, blob is still on password1. A
        retry with (password1, password2) must finish the blob rewrite,
        not skip it via the idempotent short-circuit.
        """
        operate, password1, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()
        wallet = next(iter(operate.wallet_manager))
        wallet.password = password1
        # Pre-rotate the keystore only, leaving the blob on password1.
        wallet.path.joinpath(wallet._key).write_text(  # type: ignore[attr-defined]
            json.dumps(
                Account.encrypt(
                    private_key=wallet.crypto.private_key,  # pylint: disable=protected-access
                    password=password2,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        assert wallet.is_password_valid(password2)

        operate.update_password(password1, password2)

        reloaded = operate.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)
        assert reloaded.decrypt_mnemonic(password=password2) == mnemonic.split()

    def test_update_password_with_mnemonic_raises_when_discard_fails(
        self, tmp_path: Path
    ) -> None:
        """A real rename OSError must propagate as ValueError from the seed-phrase flow."""
        operate, _, mnemonic = self._setup_wallet_with_mnemonic(tmp_path)
        password2 = random_string()
        address = operate.keys_manager.create()

        real_rename = Path.rename
        calls = {"failed": False}

        def flaky_rename(self: Path, target: Path) -> Path:
            # Only intercept the discard_all renames (target ends in
            # `.lost`); other Path.rename calls from resource storage
            # must continue to work.
            if str(target).endswith(".lost") and not calls["failed"]:
                calls["failed"] = True
                raise OSError("simulated rename failure")
            return real_rename(self, target)

        with patch.object(Path, "rename", flaky_rename):
            with pytest.raises(ValueError, match="discard"):
                operate.update_password_with_mnemonic(mnemonic, password2)

        # Wallet + user.json updates committed before discard_all, so the
        # partial-failure surface is: both auth surfaces on the new
        # password, one key file still not renamed.
        assert operate.user_account.is_valid(password2)
        assert operate.wallet_manager.is_password_valid(password2)
        remaining = list(operate.keys_manager.path.iterdir())
        assert any(entry.suffix != ".lost" for entry in remaining)
        assert any(entry.suffix == ".lost" for entry in remaining)
        # Retry must converge: with rename working normally, discard_all
        # finishes the .lost rename for the previously-stuck file.
        operate.update_password_with_mnemonic(mnemonic, password2)
        for entry in operate.keys_manager.path.iterdir():
            assert entry.suffix == ".lost"
        assert (operate.keys_manager.path / f"{address}.lost").is_file()
