# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""User account implementation."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import argon2

from operate.resource import LocalResource


def argon2id(password: str) -> str:
    """Get Argon2id digest of a password."""
    ph = argon2.PasswordHasher()  # Defaults to Argon2id
    return ph.hash(password)


@dataclass
class UserAccount(LocalResource):
    """User account."""

    password_hash: str
    path: Path

    @classmethod
    def load(cls, path: Path) -> "UserAccount":
        """Load user account."""
        return super().load(path)  # type: ignore

    @classmethod
    def new(cls, password: str, path: Path) -> "UserAccount":
        """Create a new user."""
        user = UserAccount(
            password_hash=argon2id(password=password),
            path=path,
        )
        user.store()
        return UserAccount.load(path=path)

    def is_valid(self, password: str) -> bool:
        """Check if a password string is valid."""
        try:
            ph = argon2.PasswordHasher()
            valid = ph.verify(self.password_hash, password)

            if valid and ph.check_needs_rehash(self.password_hash):
                self.password_hash = argon2id(password)
                self.store()

            return valid
        except argon2.exceptions.VerificationError:
            return False
        except argon2.exceptions.InvalidHashError:
            # Verify legacy password hash and update it to Argon2id if valid
            sha256 = hashlib.sha256()
            sha256.update(password.encode())
            if sha256.hexdigest() == self.password_hash:
                self.password_hash = argon2id(password=password)
                self.store()
                return True

            return False

    def update(self, old_password: str, new_password: str) -> None:
        """Update current password."""
        if not self.is_valid(password=old_password):
            raise ValueError("Old password is not valid")
        self.password_hash = argon2id(password=new_password)
        self.store()

    def force_update(self, new_password: str) -> None:
        """Force update current password."""
        self.password_hash = argon2id(password=new_password)
        self.store()
