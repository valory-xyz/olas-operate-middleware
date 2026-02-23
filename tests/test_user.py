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

"""Tests for operate.account.user module."""

import hashlib
from pathlib import Path
from unittest.mock import patch

import argon2
import pytest

from operate.account.user import UserAccount, argon2id


class TestUserAccount:
    """Tests for UserAccount class."""

    def test_is_valid_triggers_rehash(self, tmp_path: Path) -> None:
        """Test that is_valid() re-hashes and stores when check_needs_rehash returns True."""
        password = "testpassword123"  # nosec B105
        account_path = tmp_path / "user.json"
        account = UserAccount.new(password=password, path=account_path)

        original_hash = account.password_hash

        with patch.object(
            argon2.PasswordHasher, "check_needs_rehash", return_value=True
        ):
            result = account.is_valid(password=password)

        assert result is True
        # Hash should have been updated (re-hashed)
        assert account.password_hash != original_hash
        # The new hash should be stored in the file
        reloaded = UserAccount.load(account_path)
        assert reloaded.password_hash == account.password_hash

    def test_is_valid_sha256_wrong_password_returns_false(self, tmp_path: Path) -> None:
        """Test that is_valid() returns False for wrong password against SHA256 hash."""
        # Create account with SHA256 hash directly (legacy format)
        sha256_hash = hashlib.sha256(b"correct_password").hexdigest()
        account = UserAccount(password_hash=sha256_hash, path=tmp_path / "user.json")

        # Calling is_valid with wrong password: ph.verify raises InvalidHashError
        # (because sha256 hex is not a valid Argon2 hash), then SHA256 check fails
        result = account.is_valid(password="wrong_password")  # nosec B106
        assert result is False

    def test_is_valid_sha256_correct_password_upgrades_hash(
        self, tmp_path: Path
    ) -> None:
        """Test that is_valid() upgrades SHA256 hash to Argon2 when password matches."""
        password = "correct_password"  # nosec B105
        sha256_hash = hashlib.sha256(password.encode()).hexdigest()
        account_path = tmp_path / "user.json"
        account = UserAccount(password_hash=sha256_hash, path=account_path)
        # Write it to disk so store() works
        account_path.write_text(
            '{"password_hash": "' + sha256_hash + '"}', encoding="utf-8"
        )

        result = account.is_valid(password=password)
        assert result is True
        # Hash should be upgraded to Argon2
        ph = argon2.PasswordHasher()
        assert ph.verify(account.password_hash, password)

    def test_update_with_wrong_old_password_raises(self, tmp_path: Path) -> None:
        """Test that update() raises ValueError when old password is wrong."""
        password = "testpassword123"  # nosec B105
        account = UserAccount.new(password=password, path=tmp_path / "user.json")

        with pytest.raises(ValueError, match="Old password is not valid"):
            account.update(
                old_password="wrong_password", new_password="newpassword456"
            )  # nosec B106

    def test_update_with_correct_old_password(self, tmp_path: Path) -> None:
        """Test that update() succeeds with correct old password."""
        password = "testpassword123"  # nosec B105
        new_password = "newpassword456"  # nosec B105
        account_path = tmp_path / "user.json"
        account = UserAccount.new(password=password, path=account_path)

        account.update(old_password=password, new_password=new_password)

        # New password should be valid
        assert account.is_valid(password=new_password)
        # Old password should no longer be valid
        assert not account.is_valid(password=password)

    def test_argon2id_returns_valid_hash(self) -> None:
        """Test that argon2id() returns a valid Argon2id hash."""
        password = "testpassword"  # nosec B105
        hashed = argon2id(password)
        ph = argon2.PasswordHasher()
        assert ph.verify(hashed, password)
