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
from pathlib import Path

import argon2
import pytest
from web3 import Web3

from operate.cli import OperateApp
from operate.constants import OPERATE
from operate.operate_types import LedgerType

from tests.conftest import random_string


ROOT_PATH = Path(__file__).resolve().parent

MSG_NEW_PASSWORD_MISSING = "You must provide a new password"  # nosec
MSG_INVALID_PASSWORD = "Password is not valid"  # nosec
MSG_INVALID_MNEMONIC = "Seed phrase is not valid"  # nosec


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
        user_json_path = operate_home_path / "user.json"
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
