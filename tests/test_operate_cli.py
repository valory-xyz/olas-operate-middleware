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
import shutil
from pathlib import Path
from typing import Optional
from unittest.mock import patch
from uuid import uuid4

import argon2
import pytest
from web3 import Web3

from operate.cli import OperateApp
from operate.constants import (
    AGENT_RUNNER_PREFIX,
    DEPLOYMENT_DIR,
    OPERATE,
    SERVICES_DIR,
    USER_JSON,
    VERSION_FILE,
)
from operate.operate_types import LedgerType, Version
from operate.services.service import SERVICE_CONFIG_PREFIX

from tests.conftest import random_string


MSG_NEW_PASSWORD_MISSING = "'new_password' is required."  # nosec
MSG_INVALID_PASSWORD = "Password is not valid."  # nosec
MSG_INVALID_MNEMONIC = "Seed phrase is not valid."  # nosec


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
            found_backup_path = tmp_path / f"{OPERATE}_v0.0.0_bkp"
            shutil.copytree(found_operate, found_backup_path)

        (found_service / DEPLOYMENT_DIR).mkdir(parents=True, exist_ok=True)
        (found_service / f"{AGENT_RUNNER_PREFIX}_{uuid4()}").touch()

        if found_version is None:
            assert not Path(tmp_path / OPERATE / VERSION_FILE).exists()
            assert len(list(Path(tmp_path).glob(f"{OPERATE}_v*_bkp"))) == 0
        else:
            assert Path(tmp_path / OPERATE / VERSION_FILE).read_text() == found_version
            assert len(list(Path(tmp_path).glob(f"{OPERATE}_v*_bkp"))) == 1

        with patch("operate.cli.__version__", current_version):
            OperateApp(home=tmp_path / OPERATE)

        backup_paths = sorted(list(Path(tmp_path).glob(f"{OPERATE}_v*_bkp")))
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
