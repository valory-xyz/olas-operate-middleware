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

import typing as t
from http import HTTPStatus
from pathlib import Path
from typing import List, Tuple
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from operate.cli import CreateSafeStatus, create_app
from operate.constants import (
    MIN_PASSWORD_LENGTH,
    MSG_SAFE_CREATED_TRANSFER_COMPLETED,
    MSG_SAFE_CREATED_TRANSFER_FAILED,
    MSG_SAFE_CREATION_FAILED,
    MSG_SAFE_EXISTS_AND_FUNDED,
    MSG_SAFE_EXISTS_TRANSFER_COMPLETED,
    MSG_SAFE_EXISTS_TRANSFER_FAILED,
    OPERATE,
    ZERO_ADDRESS,
)
from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import (
    DEFAULT_EOA_TOPUPS,
    DEFAULT_NEW_SAFE_FUNDS,
    ERC20_TOKENS,
    OLAS,
    USDC,
)
from operate.operate_types import Chain, LedgerType
from operate.utils import subtract_dicts
from operate.utils.gnosis import get_asset_balance, get_assets_balances
from operate.wallet.master import EthereumMasterWallet

from tests.conftest import OnTestnet, random_mnemonic, tenderly_add_balance


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


def test_get_settings(client_no_account: TestClient) -> None:
    """Test the /api/settings endpoint."""
    response = client_no_account.get("/api/settings")
    assert response.status_code == HTTPStatus.OK, response.json()
    assert "version" in response.json()
    assert "eoa_topups" in response.json()


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
        assert response.json() == {"error": "Account already exists."}

    @pytest.mark.parametrize(
        ("password_input", "expected_error"),
        [
            ("", f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."),
            (
                "short",
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.",
            ),
            (
                "1234567",
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.",
            ),
            (None, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."),
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
            "message": "Password updated successfully.",
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

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"error": "User account not found."}

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
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long.",
            ),
            (
                "short",
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long.",
            ),
            (
                "1234567",
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long.",
            ),
            (
                None,
                f"New password must be at least {MIN_PASSWORD_LENGTH} characters long.",
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
            "error": "Exactly one of 'old_password' or 'mnemonic' (seed phrase) is required."
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
            "error": "Exactly one of 'old_password' or 'mnemonic' (seed phrase) is required."
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
            "message": "Password updated successfully.",
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


@pytest.mark.integration
class TestWalletCreateSafe(OnTestnet):
    """Tests for wallet-related endpoints."""

    def _assert_safe_balances(
        self,
        chain: Chain,
        safe_address: str,
        expected_balances: dict,
        native_asset_tolerance: float = 0.0,
    ) -> None:
        """Helper method to assert safe balances match expected values."""

        all_tokens = {ZERO_ADDRESS} | {
            token[chain] for token in ERC20_TOKENS.values() if chain in token
        }

        for token in all_tokens:
            if token not in expected_balances:
                expected_balances[token] = 0

        ledger_api = get_default_ledger_api(chain=chain)
        asset_addresses = set(expected_balances.keys())
        safe_balances = get_assets_balances(
            ledger_api=ledger_api,
            addresses={safe_address},
            asset_addresses=asset_addresses,
            raise_on_invalid_address=False,
        )[safe_address]

        for asset, target_amount in expected_balances.items():
            received = safe_balances.get(asset, 0)
            if asset == ZERO_ADDRESS and native_asset_tolerance > 0.0:
                min_accepted = target_amount * (1 - native_asset_tolerance)
                assert min_accepted <= received <= target_amount, (
                    f"Safe did not receive enough native ({asset}): "
                    f"got {received}, {min_accepted:.0f} <= expected <= {target_amount}."
                )
            else:
                assert received == target_amount, (
                    f"Safe did not receive correct amount for asset {asset}: "
                    f"got {received}, expected {target_amount}."
                )

    def test_create_safe_api_with_default_funds(self, client: TestClient) -> None:
        """Test creating gnosis safe via API."""

        # Step 1: Check initial wallet state (no safe yet)
        response = client.get(
            url="/api/wallet",
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data[0]["address"] is not None
        assert data[0]["ledger_type"] == LedgerType.ETHEREUM.value
        assert data[0]["safes"] == {}
        master_eoa = data[0]["address"]

        # Step 2: Fund master EOA (native + tokens)
        chain = Chain.GNOSIS
        amount_native = 10 * 10**18
        amount_olas = 100 * 10**18
        amount_usdc = 200 * 10**6

        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_native),
            token=ZERO_ADDRESS,
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_olas),
            token=OLAS[chain],
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_usdc),
            token=USDC[chain],
        )

        # Step 3: Create Safe (no initial_funds → uses DEFAULT_NEW_SAFE_FUNDS)
        response = client.post(
            "/api/wallet/safe",
            json={"chain": chain.value},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["safe"].startswith("0x")
        safe_address = data["safe"]
        assert data["create_tx"] is not None
        assert isinstance(data["transfer_txs"], dict)
        default_initial_funds = DEFAULT_NEW_SAFE_FUNDS[chain]
        assert len(data["transfer_txs"]) == len(default_initial_funds)
        assert not data["transfer_errors"]
        assert data["status"] == CreateSafeStatus.SAFE_CREATED_TRANSFER_COMPLETED
        assert MSG_SAFE_CREATED_TRANSFER_COMPLETED in data["message"]

        # Step 4: Verify safe now appears in wallet
        response = client.get("/api/wallet")
        assert response.status_code == HTTPStatus.OK
        updated_wallet = next(w for w in response.json() if w["address"] == master_eoa)
        assert chain.value in updated_wallet["safes"]
        assert updated_wallet["safes"][chain.value] == data["safe"]

        # Step 5: Verify actual balances on Safe increased (using backend utils)
        self._assert_safe_balances(
            chain=chain,
            safe_address=safe_address,
            expected_balances=default_initial_funds,
        )

    def test_create_safe_api_with_custom_initial_funds(
        self, client: TestClient
    ) -> None:
        """Test creating Gnosis Safe via API with explicit custom initial_funds."""

        # Step 1: Check initial wallet state (no safe yet)
        response = client.get(
            url="/api/wallet",
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data[0]["address"] is not None
        assert data[0]["ledger_type"] == LedgerType.ETHEREUM.value
        assert data[0]["safes"] == {}
        master_eoa = data[0]["address"]

        # Step 2: Fund master EOA (native + tokens)
        chain = Chain.GNOSIS
        amount_native = 10 * 10**18
        amount_olas = 300 * 10**18
        amount_usdc = 600 * 10**6

        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_native),
            token=ZERO_ADDRESS,
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_olas),
            token=OLAS[chain],
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_usdc),
            token=USDC[chain],
        )

        # Step 3: Define custom initial_funds (different from defaults)
        custom_initial_funds = {
            ZERO_ADDRESS: 2 * 10**18,
            OLAS[chain]: 250 * 10**18,
            USDC[chain]: 500 * 10**6,
        }

        # Step 4: Create Safe with explicit initial_funds
        response = client.post(
            url="/api/wallet/safe",
            json={
                "chain": chain.value,
                "initial_funds": custom_initial_funds,
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()

        safe_address = data["safe"]
        assert safe_address.startswith("0x")
        assert data["create_tx"] is not None
        assert isinstance(data["transfer_txs"], dict)
        assert set(data["transfer_txs"].keys()) == set(custom_initial_funds.keys())
        assert not data["transfer_errors"]
        assert data["status"] == CreateSafeStatus.SAFE_CREATED_TRANSFER_COMPLETED
        assert MSG_SAFE_CREATED_TRANSFER_COMPLETED in data["message"]

        # Step 5: Verify safe now appears in wallet
        response = client.get(url="/api/wallet")
        assert response.status_code == HTTPStatus.OK
        updated_wallet = next(w for w in response.json() if w["address"] == master_eoa)
        assert chain.value in updated_wallet["safes"]
        assert updated_wallet["safes"][chain.value] == safe_address

        # Step 6: Verify actual balances on Safe match the custom targets
        self._assert_safe_balances(
            chain=chain,
            safe_address=safe_address,
            expected_balances=custom_initial_funds,
        )

    def test_create_safe_api_with_transfer_excess_assets(
        self, client: TestClient
    ) -> None:
        """Test creating Gnosis Safe via API with explicit custom initial_funds."""

        # Step 1: Check initial wallet state (no safe yet)
        response = client.get(
            url="/api/wallet",
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data[0]["address"] is not None
        assert data[0]["ledger_type"] == LedgerType.ETHEREUM.value
        assert data[0]["safes"] == {}
        master_eoa = data[0]["address"]

        # Step 2: Fund master EOA (native + tokens)
        chain = Chain.GNOSIS
        amount_native = 10 * 10**18
        amount_olas = 300 * 10**18
        amount_usdc = 600 * 10**6

        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_native),
            token=ZERO_ADDRESS,
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_olas),
            token=OLAS[chain],
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_usdc),
            token=USDC[chain],
        )

        # Step 3: Create Safe with explicit initial_funds
        response = client.post(
            url="/api/wallet/safe",
            json={
                "chain": chain.value,
                "transfer_excess_assets": "true",
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()

        # Step 5: Determine excess initial funds
        ledger_api = get_default_ledger_api(chain=chain)
        master_eoa_native_balance = get_asset_balance(
            ledger_api=ledger_api,
            address=master_eoa,
            asset_address=ZERO_ADDRESS,
        )
        assert (
            int(0.9 * DEFAULT_EOA_TOPUPS[chain][ZERO_ADDRESS])
            < master_eoa_native_balance
            <= DEFAULT_EOA_TOPUPS[chain][ZERO_ADDRESS]
        )

        excess_initial_funds = subtract_dicts(
            {
                ZERO_ADDRESS: amount_native,
                OLAS[chain]: amount_olas,
                USDC[chain]: amount_usdc,
            },
            DEFAULT_EOA_TOPUPS[chain],
        )

        safe_address = data["safe"]
        assert safe_address.startswith("0x")
        assert data["create_tx"] is not None
        assert isinstance(data["transfer_txs"], dict)
        assert set(data["transfer_txs"].keys()) == set(excess_initial_funds.keys())
        assert not data["transfer_errors"]
        assert data["status"] == CreateSafeStatus.SAFE_CREATED_TRANSFER_COMPLETED
        assert MSG_SAFE_CREATED_TRANSFER_COMPLETED in data["message"]

        # Step 4: Verify safe now appears in wallet
        response = client.get(url="/api/wallet")
        assert response.status_code == HTTPStatus.OK
        updated_wallet = next(w for w in response.json() if w["address"] == master_eoa)
        assert chain.value in updated_wallet["safes"]
        assert updated_wallet["safes"][chain.value] == safe_address

        # Step 6: Verify actual balances on Safe match the custom targets
        self._assert_safe_balances(
            chain=chain,
            safe_address=safe_address,
            expected_balances=excess_initial_funds,
            native_asset_tolerance=0.05,
        )

    def test_create_safe_with_failures_and_retries(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test creating Gnosis Safe via API with failures and retries."""

        # Step 1: Check initial wallet state (no safe yet)
        response = client.get(
            url="/api/wallet",
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data[0]["address"] is not None
        assert data[0]["ledger_type"] == LedgerType.ETHEREUM.value
        assert data[0]["safes"] == {}
        master_eoa = data[0]["address"]

        # Step 2: Fund master EOA (native + tokens)
        chain = Chain.GNOSIS
        amount_native = 10 * 10**18
        amount_olas = 300 * 10**18
        amount_usdc = 600 * 10**6

        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_native),
            token=ZERO_ADDRESS,
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_olas),
            token=OLAS[chain],
        )
        tenderly_add_balance(
            chain=chain,
            recipient=master_eoa,
            amount=int(amount_usdc),
            token=USDC[chain],
        )

        # Step 3: Compute expected excess before any calls
        excess_initial_funds = subtract_dicts(
            {
                ZERO_ADDRESS: amount_native,
                OLAS[chain]: amount_olas,
                USDC[chain]: amount_usdc,
            },
            DEFAULT_EOA_TOPUPS[chain],
        )

        # Step 4: First call - creation fails
        original_create_safe = EthereumMasterWallet.create_safe

        def mock_create_safe_failure(self: t.Any, **kwargs: t.Any) -> str | None:
            raise RuntimeError("Mock create_safe failure")

        monkeypatch.setattr(
            EthereumMasterWallet, "create_safe", mock_create_safe_failure
        )

        response = client.post(
            url="/api/wallet/safe",
            json={
                "chain": chain.value,
                "transfer_excess_assets": "true",
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["status"] == CreateSafeStatus.SAFE_CREATION_FAILED
        assert MSG_SAFE_CREATION_FAILED in data["message"]

        monkeypatch.setattr(EthereumMasterWallet, "create_safe", original_create_safe)

        # Step 5: Second call - failure on all transfers
        original_transfer = EthereumMasterWallet.transfer

        def mock_transfer_failure_all(
            self: t.Any, to: str, amount: int, chain: Chain, asset: str, **kwargs: t.Any
        ) -> str | None:
            raise RuntimeError("Mock transfer failure")

        monkeypatch.setattr(EthereumMasterWallet, "transfer", mock_transfer_failure_all)

        response = client.post(
            url="/api/wallet/safe",
            json={
                "chain": chain.value,
                "transfer_excess_assets": "true",
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        safe_address = data["safe"]
        assert safe_address.startswith("0x")
        create_tx = data["create_tx"]
        assert create_tx is not None
        assert isinstance(data["transfer_txs"], dict)
        assert USDC[chain] in data.get("transfer_errors", {})
        assert ZERO_ADDRESS in data.get("transfer_errors", {})
        assert OLAS[chain] in data.get("transfer_errors", {})
        assert len(data["transfer_txs"]) == 0
        assert data["status"] == CreateSafeStatus.SAFE_CREATED_TRANSFER_FAILED
        assert MSG_SAFE_CREATED_TRANSFER_FAILED in data["message"]

        # Step 6: Third call - failure on USDC transfer
        def mock_transfer_failure_usdc(
            self: t.Any, to: str, amount: int, chain: Chain, asset: str, **kwargs: t.Any
        ) -> str | None:
            if asset == USDC[chain]:
                raise RuntimeError("Mock USDC transfer failure")
            return original_transfer(self, to, amount, chain, asset, **kwargs)

        monkeypatch.setattr(
            EthereumMasterWallet, "transfer", mock_transfer_failure_usdc
        )

        response = client.post(
            url="/api/wallet/safe",
            json={
                "chain": chain.value,
                "transfer_excess_assets": "true",
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        safe_address = data["safe"]
        assert safe_address.startswith("0x")
        create_tx = data["create_tx"]
        assert create_tx is None
        assert isinstance(data["transfer_txs"], dict)
        assert USDC[chain] in data.get("transfer_errors", {})
        assert len(data["transfer_txs"]) == len(excess_initial_funds) - 1
        assert not data.get("transfer_errors", {}).get(ZERO_ADDRESS)
        assert not data.get("transfer_errors", {}).get(OLAS[chain])
        assert data["status"] == CreateSafeStatus.SAFE_EXISTS_TRANSFER_FAILED
        assert MSG_SAFE_EXISTS_TRANSFER_FAILED in data["message"]

        # Step 7: Fourth call - USDC transfer succeeds
        monkeypatch.setattr(EthereumMasterWallet, "transfer", original_transfer)

        response = client.post(
            url="/api/wallet/safe",
            json={
                "chain": chain.value,
                "transfer_excess_assets": "true",
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["safe"] == safe_address
        assert data["create_tx"] is None
        assert USDC[chain] in data["transfer_txs"]
        assert not data["transfer_errors"]
        assert data["status"] == CreateSafeStatus.SAFE_EXISTS_TRANSFER_COMPLETED
        assert MSG_SAFE_EXISTS_TRANSFER_COMPLETED in data["message"]

        # Verify balances
        self._assert_safe_balances(
            chain=chain,
            safe_address=safe_address,
            expected_balances=excess_initial_funds,
            native_asset_tolerance=0.05,
        )

        # Step 8: Fifth call - no more transfers needed (no-op)
        response = client.post(
            url="/api/wallet/safe",
            json={
                "chain": chain.value,
                "transfer_excess_assets": "true",
            },
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["safe"] == safe_address
        assert data["create_tx"] is None
        assert data["transfer_txs"] == {}
        assert not data["transfer_errors"]
        assert data["status"] == CreateSafeStatus.SAFE_EXISTS_ALREADY_FUNDED
        assert MSG_SAFE_EXISTS_AND_FUNDED in data["message"]

        # Step 9: Verify safe now appears in wallet
        response = client.get(url="/api/wallet")
        assert response.status_code == HTTPStatus.OK
        updated_wallet = next(w for w in response.json() if w["address"] == master_eoa)
        assert chain.value in updated_wallet["safes"]
        assert updated_wallet["safes"][chain.value] == safe_address

        # Step 10: Verify actual balances on Safe match expected excess
        self._assert_safe_balances(
            chain=chain,
            safe_address=safe_address,
            expected_balances=excess_initial_funds,
            native_asset_tolerance=0.05,
        )
