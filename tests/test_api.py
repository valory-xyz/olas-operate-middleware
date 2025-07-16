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

"""Tests for APIs."""

from http import HTTPStatus
from pathlib import Path
from typing import List, Tuple
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from operate.cli import create_app
from operate.constants import MIN_PASSWORD_LENGTH, OPERATE
from operate.operate_types import LedgerType
from operate.wallet.master import EthereumMasterWallet

from tests.conftest import random_mnemonic


@pytest.fixture
def logged_in() -> bool:
    """Fixture to configure the client to be logged in."""
    return True


@pytest.fixture
def ethereum_master_wallet(
    password: str,
    tmp_path: Path,
) -> Tuple[EthereumMasterWallet, List[str]]:
    """Fixture to provide an Ethereum master wallet."""
    wallet_path = tmp_path / OPERATE / "wallets"
    wallet_path.mkdir(parents=True, exist_ok=True)
    print(wallet_path)
    return EthereumMasterWallet.new(
        password=password,
        path=wallet_path,
    )


@pytest.fixture
def client(
    client_no_account: TestClient,
    password: str,
    logged_in: bool,
    tmp_path: Path,
    ethereum_master_wallet: Tuple[EthereumMasterWallet, List[str]],
) -> TestClient:
    """Create a test client for the FastAPI app."""
    client = client_no_account
    client.post(
        url="/api/account",
        json={"password": password},
    )
    with mock.patch(
        "operate.wallet.master.EthereumMasterWallet.new",
        return_value=ethereum_master_wallet,
    ):
        client.post(
            url="/api/wallet",
            json={"ledger_type": LedgerType.ETHEREUM},
        )

    if not logged_in:
        app = create_app(home=tmp_path / OPERATE)
        client = TestClient(app)

    return client


@pytest.fixture
def client_no_account(tmp_path: Path) -> TestClient:
    """Create a test client for the FastAPI app without an account."""
    temp_dir = Path(tmp_path)
    app = create_app(home=temp_dir / OPERATE)
    return TestClient(app)


class TestAccountCreation:
    """Tests for POST /api/account endpoint."""

    def test_create_account_success(
        self, client_no_account: TestClient, password: str
    ) -> None:
        """Test successful account creation."""
        response = client_no_account.post(
            url="/api/account",
            json={"password": password},
        )

        assert response.status_code == HTTPStatus.OK, response.json()
        assert response.json() == {"error": None}

    def test_create_account_already_exists(
        self, client: TestClient, password: str
    ) -> None:
        """Test account creation when account already exists."""
        response = client.post(
            url="/api/account",
            json={"password": password},
        )

        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json() == {"error": "Account already exists"}

    @pytest.mark.parametrize(
        ("password_input", "expected_error"),
        [
            ("", f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"),
            (
                "short",
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters long",
            ),
            (
                "1234567",
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters long",
            ),
            (None, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"),
        ],
    )
    def test_create_account_invalid_password(
        self, client_no_account: TestClient, password_input: str, expected_error: str
    ) -> None:
        """Test account creation with invalid passwords."""
        response = client_no_account.post(
            url="/api/account",
            json={"password": password_input},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {"error": expected_error}

    def test_create_account_minimum_valid_password(
        self, client_no_account: TestClient
    ) -> None:
        """Test account creation with minimum valid password length."""
        min_password = "a" * MIN_PASSWORD_LENGTH
        response = client_no_account.post(
            url="/api/account",
            json={"password": min_password},
        )

        assert response.status_code == HTTPStatus.OK, response.json()
        assert response.json() == {"error": None}


class TestPasswordUpdate:
    """Tests for PUT /api/account endpoint."""

    def test_update_password_with_old_password_success(
        self, client: TestClient, password: str
    ) -> None:
        """Test successful password update with old password."""
        new_password = "new_secure_password123"  # nosec  # just for testing purpose
        response = client.put(
            url="/api/account",
            json={"old_password": password, "new_password": new_password},
        )

        assert response.status_code == HTTPStatus.OK, response.json()
        assert response.json() == {
            "error": None,
            "message": "Password updated successfully",
        }

    def test_update_password_with_mnemonic_success(
        self,
        client: TestClient,
        ethereum_master_wallet: Tuple[EthereumMasterWallet, List[str]],
    ) -> None:
        """Test successful password update with mnemonic."""
        # First we need to get the mnemonic from the wallet creation
        # This test assumes the wallet was created in the client fixture
        _, mnemonic = ethereum_master_wallet
        new_password = "new_secure_password123"  # nosec  # just for testing purpose

        response = client.put(
            url="/api/account",
            json={"mnemonic": " ".join(mnemonic), "new_password": new_password},
        )

        assert response.status_code == HTTPStatus.OK, response.json()

    def test_update_password_no_account(self, client_no_account: TestClient) -> None:
        """Test password update when no account exists."""
        response = client_no_account.put(
            url="/api/account",
            json={"old_password": "some_password", "new_password": "new_password123"},
        )

        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json() == {"error": "Account does not exist"}

    def test_update_password_invalid_old_password(self, client: TestClient) -> None:
        """Test password update with invalid old password."""
        new_password = "new_secure_password123"  # nosec  # just for testing purpose
        response = client.put(
            url="/api/account",
            json={"old_password": "wrong_password", "new_password": new_password},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {
            "error": "Failed to update password: Password is not valid."
        }

    @pytest.mark.parametrize(
        ("new_password", "expected_error"),
        [
            (
                "",
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long",
            ),
            (
                "short",
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long",
            ),
            (
                "1234567",
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long",
            ),
            (
                None,
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long",
            ),
        ],
    )
    def test_update_password_invalid_new_password(
        self, client: TestClient, password: str, new_password: str, expected_error: str
    ) -> None:
        """Test password update with invalid new passwords."""
        response = client.put(
            url="/api/account",
            json={"old_password": password, "new_password": new_password},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {"error": expected_error}

    def test_update_password_no_credentials(self, client: TestClient) -> None:
        """Test password update without providing old password or mnemonic."""
        new_password = "new_secure_password123"  # nosec  # just for testing purpose
        response = client.put(
            url="/api/account",
            json={"new_password": new_password},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {
            "error": "You must provide either your current password or seed phrase"
        }

    def test_update_password_both_credentials(
        self, client: TestClient, password: str
    ) -> None:
        """Test password update with both old password and mnemonic provided."""
        mnemonic = random_mnemonic()
        new_password = "new_secure_password123"  # nosec  # just for testing purpose
        response = client.put(
            url="/api/account",
            json={
                "old_password": password,
                "mnemonic": mnemonic,
                "new_password": new_password,
            },
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {
            "error": "Please provide either your current password or seed phrase, not both"
        }

    def test_update_password_invalid_mnemonic(self, client: TestClient) -> None:
        """Test password update with invalid mnemonic."""
        invalid_mnemonic = "invalid mnemonic phrase that should not work"
        new_password = "new_secure_password123"  # nosec  # just for testing purpose
        response = client.put(
            url="/api/account",
            json={"mnemonic": invalid_mnemonic, "new_password": new_password},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {
            "error": "Failed to update password: Seed phrase is not valid."
        }

    def test_update_password_minimum_valid_new_password(
        self, client: TestClient, password: str
    ) -> None:
        """Test password update with minimum valid new password length."""
        min_password = "a" * MIN_PASSWORD_LENGTH
        response = client.put(
            url="/api/account",
            json={"old_password": password, "new_password": min_password},
        )

        assert response.status_code == HTTPStatus.OK, response.json()
        assert response.json() == {
            "error": None,
            "message": "Password updated successfully",
        }


@pytest.mark.parametrize("logged_in", [True, False])
@pytest.mark.parametrize(
    "case",
    [
        (lambda pw: pw, True),
        (lambda pw: "wrong" + pw, False),
        (lambda pw: None, False),
    ],
)
def test_get_private_key(
    client: TestClient, logged_in: bool, case: Tuple, password: str
) -> None:
    """Test the /private_key endpoint."""
    password_modifier, should_succeed = case
    password = password_modifier(password)
    response = client.post(
        url="/api/wallet/private_key",
        json={"password": password, "ledger_type": LedgerType.ETHEREUM},
    )

    if should_succeed and logged_in:
        assert response.status_code == HTTPStatus.OK, response.json()
        assert "private_key" in response.json()
    else:
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json().get("private_key") is None
