# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Unit tests for /api/fund_recovery/scan and /api/fund_recovery/execute endpoints."""

from http import HTTPStatus
from unittest.mock import patch

from fastapi.testclient import TestClient

from operate.constants import ZERO_ADDRESS
from operate.operate_types import (
    ChainAmounts,
    FundRecoveryExecuteResponse,
    FundRecoveryScanResponse,
)

# A syntactically valid BIP-39 test mnemonic (never commit a real mnemonic)
_VALID_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
_VALID_DESTINATION = "0x1234567890123456789012345678901234567890"
_ZERO_DESTINATION = ZERO_ADDRESS


# ---------------------------------------------------------------------------
# /api/fund_recovery/scan
# ---------------------------------------------------------------------------


class TestFundRecoveryScanValidation:
    """Request-validation tests for POST /api/fund_recovery/scan."""

    def test_missing_body_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """Empty body triggers request-parse error → 400."""
        resp = client_no_account.post("/api/fund_recovery/scan", json={})
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_mnemonic_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """A non-BIP39 mnemonic string is rejected with 400."""
        resp = client_no_account.post(
            "/api/fund_recovery/scan",
            json={
                "mnemonic": "not a valid mnemonic phrase at all zzz",
                "destination_address": _VALID_DESTINATION,
            },
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert "mnemonic" in resp.json()["error"].lower()

    def test_invalid_destination_address_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """A non-EVM destination address is rejected with 400."""
        resp = client_no_account.post(
            "/api/fund_recovery/scan",
            json={
                "mnemonic": _VALID_MNEMONIC,
                "destination_address": "not-an-address",
            },
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_zero_address_destination_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """The zero address is rejected with 400 to prevent fund loss."""
        resp = client_no_account.post(
            "/api/fund_recovery/scan",
            json={
                "mnemonic": _VALID_MNEMONIC,
                "destination_address": _ZERO_DESTINATION,
            },
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert "zero" in resp.json()["error"].lower()

    def test_valid_request_calls_manager_and_returns_200(
        self, client_no_account: TestClient
    ) -> None:
        """Happy path: valid mnemonic + destination → 200 with scan result."""
        scan_result = FundRecoveryScanResponse(
            master_eoa_address=_VALID_DESTINATION,
            balances=ChainAmounts(),
            services=[],
            gas_warning={},
        )
        with patch(
            "operate.services.fund_recovery_manager.FundRecoveryManager.scan",
            return_value=scan_result,
        ):
            resp = client_no_account.post(
                "/api/fund_recovery/scan",
                json={
                    "mnemonic": _VALID_MNEMONIC,
                    "destination_address": _VALID_DESTINATION,
                },
            )
        assert resp.status_code == HTTPStatus.OK
        body = resp.json()
        assert "master_eoa_address" in body

    def test_non_json_body_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """Non-JSON body triggers the broad except clause → 400."""
        resp = client_no_account.post(
            "/api/fund_recovery/scan",
            content=b"not-json!!!",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert resp.json()["error"] == "Invalid request body."

    def test_manager_exception_returns_500(self, client_no_account: TestClient) -> None:
        """When FundRecoveryManager.scan() raises, the endpoint returns 500."""
        with patch(
            "operate.services.fund_recovery_manager.FundRecoveryManager.scan",
            side_effect=RuntimeError("scan boom"),
        ):
            resp = client_no_account.post(
                "/api/fund_recovery/scan",
                json={
                    "mnemonic": _VALID_MNEMONIC,
                    "destination_address": _VALID_DESTINATION,
                },
            )
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "error" in resp.json()


# ---------------------------------------------------------------------------
# /api/fund_recovery/execute
# ---------------------------------------------------------------------------


class TestFundRecoveryExecuteValidation:
    """Request-validation tests for POST /api/fund_recovery/execute."""

    def test_missing_body_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """Empty body triggers request-parse error → 400."""
        resp = client_no_account.post("/api/fund_recovery/execute", json={})
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_mnemonic_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """A non-BIP39 mnemonic string is rejected with 400."""
        resp = client_no_account.post(
            "/api/fund_recovery/execute",
            json={
                "mnemonic": "totally wrong phrase here",
                "destination_address": _VALID_DESTINATION,
            },
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_destination_address_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """A non-EVM destination address is rejected with 400."""
        resp = client_no_account.post(
            "/api/fund_recovery/execute",
            json={
                "mnemonic": _VALID_MNEMONIC,
                "destination_address": "0xBADBADBAD",
            },
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_zero_address_destination_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """The zero address is rejected with 400 to prevent irrecoverable fund loss."""
        resp = client_no_account.post(
            "/api/fund_recovery/execute",
            json={
                "mnemonic": _VALID_MNEMONIC,
                "destination_address": _ZERO_DESTINATION,
            },
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert "zero" in resp.json()["error"].lower()

    def test_valid_request_calls_manager_and_returns_200(
        self, client_no_account: TestClient
    ) -> None:
        """Happy path: valid mnemonic + destination → 200 with execute result."""
        execute_result = FundRecoveryExecuteResponse(
            success=True,
            partial_failure=False,
            total_funds_moved=ChainAmounts(),
            errors=[],
        )
        with patch(
            "operate.services.fund_recovery_manager.FundRecoveryManager.execute",
            return_value=execute_result,
        ):
            resp = client_no_account.post(
                "/api/fund_recovery/execute",
                json={
                    "mnemonic": _VALID_MNEMONIC,
                    "destination_address": _VALID_DESTINATION,
                },
            )
        assert resp.status_code == HTTPStatus.OK
        body = resp.json()
        assert body["success"] is True
        assert body["errors"] == []

    def test_non_json_body_returns_bad_request(
        self, client_no_account: TestClient
    ) -> None:
        """Non-JSON body triggers the broad except clause → 400."""
        resp = client_no_account.post(
            "/api/fund_recovery/execute",
            content=b"not-json!!!",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert resp.json()["error"] == "Invalid request body."

    def test_manager_exception_returns_500(self, client_no_account: TestClient) -> None:
        """When FundRecoveryManager.execute() raises, the endpoint returns 500."""
        with patch(
            "operate.services.fund_recovery_manager.FundRecoveryManager.execute",
            side_effect=RuntimeError("unexpected boom"),
        ):
            resp = client_no_account.post(
                "/api/fund_recovery/execute",
                json={
                    "mnemonic": _VALID_MNEMONIC,
                    "destination_address": _VALID_DESTINATION,
                },
            )
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "error" in resp.json()
