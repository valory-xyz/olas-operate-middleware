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
from typing import Tuple

import pytest
from fastapi.testclient import TestClient

from operate.cli import create_app
from operate.operate_types import LedgerType


@pytest.fixture
def logged_in() -> bool:
    """Fixture to configure the client to be logged in."""
    return True


@pytest.fixture
def client(password: str, logged_in: bool, tmp_path: Path) -> TestClient:
    """Create a test client for the FastAPI app."""
    temp_dir = Path(tmp_path)
    app = create_app(home=temp_dir)
    client = TestClient(app)
    client.post(
        url="/api/account",
        json={"password": password},
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
        assert response.status_code == HTTPStatus.OK
        assert "private_key" in response.json()
    else:
        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json().get("private_key") is None
