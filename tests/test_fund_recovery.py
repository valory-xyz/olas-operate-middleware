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

import os
from contextlib import ExitStack
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from operate.cli import create_app
from operate.constants import ZERO_ADDRESS
from operate.operate_types import (
    FundRecoveryExecuteResponse,
    FundRecoveryScanResponse,
)


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

# A syntactically valid BIP-39 test mnemonic (never commit a real mnemonic)
_VALID_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
_VALID_DESTINATION = "0x1234567890123456789012345678901234567890"
_ZERO_DESTINATION = ZERO_ADDRESS


def _make_mock_operate() -> MagicMock:
    """Return a minimal mock OperateApp sufficient for the fund-recovery routes."""
    m = MagicMock()
    m._path = MagicMock()
    kill_mock = MagicMock()
    kill_mock.write_text = MagicMock()
    m._path.__truediv__ = MagicMock(return_value=kill_mock)
    m.password = None
    m.user_account = None
    m.json = {"name": "test", "version": "0.0.0", "home": "/tmp"}  # nosec B108
    m.settings = MagicMock()
    m.settings.json = {"version": "0.0.0"}
    m.wallet_manager = MagicMock()
    m.wallet_manager.__iter__ = MagicMock(side_effect=lambda: iter([]))
    m.bridge_manager = MagicMock()
    m.wallet_recovery_manager = MagicMock()
    m.funding_manager = MagicMock()
    m.funding_manager.funding_job = AsyncMock()
    svc_mgr = MagicMock()
    svc_mgr.validate_services.return_value = True
    svc_mgr.json = []
    svc_mgr.get_all_service_ids.return_value = []
    svc_mgr.get_all_services.return_value = ([], [])
    m.service_manager.return_value = svc_mgr
    return m


def _open_app(mock_operate: MagicMock) -> tuple:
    """Return (ExitStack, app) with all operate patches applied."""
    stack = ExitStack()
    stack.enter_context(patch("operate.cli.OperateApp", return_value=mock_operate))
    mock_hc_cls = stack.enter_context(patch("operate.cli.HealthChecker"))
    mock_hc_cls.NUMBER_OF_FAILS_DEFAULT = 60
    stack.enter_context(patch("operate.cli.signal"))
    stack.enter_context(patch("operate.cli.atexit"))
    mock_wd = MagicMock()
    mock_wd.start = MagicMock()
    mock_wd.stop = AsyncMock()
    stack.enter_context(patch("operate.cli.ParentWatchdog", return_value=mock_wd))
    stack.enter_context(patch.dict(os.environ, {"HEALTH_CHECKER_OFF": "1"}))
    app = create_app()
    return stack, app


# ---------------------------------------------------------------------------
# /api/fund_recovery/scan
# ---------------------------------------------------------------------------


class TestFundRecoveryScanValidation:
    """Request-validation tests for POST /api/fund_recovery/scan."""

    def _client(self) -> tuple:
        mock_op = _make_mock_operate()
        stack, app = _open_app(mock_op)
        return stack, app

    def test_missing_body_returns_bad_request(self) -> None:
        """Empty body triggers request-parse error → 400."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post("/api/fund_recovery/scan", json={})
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_mnemonic_returns_bad_request(self) -> None:
        """A non-BIP39 mnemonic string is rejected with 400."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/fund_recovery/scan",
                    json={
                        "mnemonic": "not a valid mnemonic phrase at all zzz",
                        "destination_address": _VALID_DESTINATION,
                    },
                )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert "mnemonic" in resp.json()["error"].lower()

    def test_invalid_destination_address_returns_bad_request(self) -> None:
        """A non-EVM destination address is rejected with 400."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/fund_recovery/scan",
                    json={
                        "mnemonic": _VALID_MNEMONIC,
                        "destination_address": "not-an-address",
                    },
                )
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_zero_address_destination_returns_bad_request(self) -> None:
        """The zero address is rejected with 400 to prevent fund loss."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/fund_recovery/scan",
                    json={
                        "mnemonic": _VALID_MNEMONIC,
                        "destination_address": _ZERO_DESTINATION,
                    },
                )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert "zero" in resp.json()["error"].lower()

    def test_valid_request_calls_manager_and_returns_200(self) -> None:
        """Happy path: valid mnemonic + destination → 200 with scan result."""
        scan_result = FundRecoveryScanResponse(
            master_eoa_address=_VALID_DESTINATION,
            balances={},
            services=[],
            gas_warning={},
        )
        stack, app = self._client()
        with stack:
            with patch(
                "operate.services.fund_recovery_manager.FundRecoveryManager.scan",
                return_value=scan_result,
            ):
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/fund_recovery/scan",
                        json={
                            "mnemonic": _VALID_MNEMONIC,
                            "destination_address": _VALID_DESTINATION,
                        },
                    )
        assert resp.status_code == HTTPStatus.OK
        body = resp.json()
        assert "master_eoa_address" in body


# ---------------------------------------------------------------------------
# /api/fund_recovery/execute
# ---------------------------------------------------------------------------


class TestFundRecoveryExecuteValidation:
    """Request-validation tests for POST /api/fund_recovery/execute."""

    def _client(self) -> tuple:
        mock_op = _make_mock_operate()
        stack, app = _open_app(mock_op)
        return stack, app

    def test_missing_body_returns_bad_request(self) -> None:
        """Empty body triggers request-parse error → 400."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post("/api/fund_recovery/execute", json={})
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_mnemonic_returns_bad_request(self) -> None:
        """A non-BIP39 mnemonic string is rejected with 400."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/fund_recovery/execute",
                    json={
                        "mnemonic": "totally wrong phrase here",
                        "destination_address": _VALID_DESTINATION,
                    },
                )
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_destination_address_returns_bad_request(self) -> None:
        """A non-EVM destination address is rejected with 400."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/fund_recovery/execute",
                    json={
                        "mnemonic": _VALID_MNEMONIC,
                        "destination_address": "0xBADBADBAD",
                    },
                )
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_zero_address_destination_returns_bad_request(self) -> None:
        """The zero address is rejected with 400 to prevent irrecoverable fund loss."""
        stack, app = self._client()
        with stack:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/fund_recovery/execute",
                    json={
                        "mnemonic": _VALID_MNEMONIC,
                        "destination_address": _ZERO_DESTINATION,
                    },
                )
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert "zero" in resp.json()["error"].lower()

    def test_valid_request_calls_manager_and_returns_200(self) -> None:
        """Happy path: valid mnemonic + destination → 200 with execute result."""
        execute_result = FundRecoveryExecuteResponse(
            success=True,
            partial_failure=False,
            total_funds_moved={},
            errors=[],
        )
        stack, app = self._client()
        with stack:
            with patch(
                "operate.services.fund_recovery_manager.FundRecoveryManager.execute",
                return_value=execute_result,
            ):
                with TestClient(app) as client:
                    resp = client.post(
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
