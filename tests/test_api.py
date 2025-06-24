from pathlib import Path
from typing import Tuple
import pytest
from fastapi.testclient import TestClient
from http import HTTPStatus

from operate.cli import create_app
from operate.operate_types import LedgerType


@pytest.fixture
def mock_password():
    """Fixture to provide a mock password for testing."""
    return "test_password"

@pytest.fixture
def logged_in():
    """Fixture to configure the client to be logged in."""
    return True

@pytest.fixture
def client(mock_password, logged_in, tmp_path):
    """Create a test client for the FastAPI app."""
    temp_dir = Path(tmp_path)
    app = create_app(home=temp_dir)
    client = TestClient(app)
    client.post(
        url="/api/account",
        json={"password": mock_password},
    )
    client.post(
        url="/api/wallet",
        json={"ledger_type": LedgerType.ETHEREUM},
    )
    if not logged_in:
        app = create_app(home=temp_dir)
        client = TestClient(app)

    return client


@pytest.mark.parametrize("logged_in", [True, False])
@pytest.mark.parametrize("case", [
    ("test_password", True),
    ("wrong_password", False),
])
def test_get_private_key(
    client: TestClient,
    logged_in: bool,
    case: Tuple
):
    """Test the /private_key endpoint."""
    password, should_succeed = case
    response = client.post(
        url="/api/wallet/private_key",
        json={"password": password, "ledger_type": LedgerType.ETHEREUM},
    )

    if should_succeed and logged_in:
        assert response.status_code == HTTPStatus.OK
        assert "private_key" in response.json()
    else:
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json().get("private_key") is None
