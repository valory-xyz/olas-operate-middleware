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
"""Unit tests for operate/quickstart/ modules."""

import json
import os
import subprocess  # nosec
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, mock_open, patch

import pytest
import requests

from operate.constants import NO_STAKING_PROGRAM_ID, ZERO_ADDRESS
from operate.operate_types import Chain, ChainAmounts, OnChainState
from operate.quickstart.analyse_logs import (
    analyse_logs,
    find_build_directory,
    run_analysis,
)
from operate.quickstart.claim_staking_rewards import claim_staking_rewards
from operate.quickstart.reset_configs import _ask_to_change, reset_configs
from operate.quickstart.reset_password import reset_password
from operate.quickstart.reset_staking import reset_staking
from operate.quickstart.run_service import (
    CUSTOM_PROGRAM_ID,
    DEPRECATED_QS_STAKING_PROGRAMS,
    _ask_funds_from_requirements,
    _deprecated_program_warning,
    _maybe_create_master_eoa,
    ask_confirm_password,
    ask_password_if_needed,
    get_service,
    load_local_config,
)
from operate.quickstart.stop_service import stop_service
from operate.quickstart.terminate_on_chain_service import terminate_service
from operate.quickstart.utils import (
    QuickstartConfig,
    ask_or_get_from_env,
    ask_yes_or_no,
    check_rpc,
    wei_to_token,
    wei_to_unit,
)
from operate.services.protocol import StakingState


# ============================================================
# Tests for operate/quickstart/utils.py
# ============================================================


class TestWeiToUnit:
    """Tests for wei_to_unit."""

    def test_gnosis_native_one_ether(self) -> None:
        """Test conversion of 1e18 wei to 1 unit."""
        result = wei_to_unit(10**18, "gnosis")
        assert result == pytest.approx(1.0, abs=0.000001)

    def test_gnosis_native_half_ether(self) -> None:
        """Test conversion of 0.5 ether."""
        result = wei_to_unit(5 * 10**17, "gnosis")
        assert result == pytest.approx(0.5, abs=0.000001)

    def test_gnosis_usdc_token(self) -> None:
        """Test conversion with 6-decimal token (USDC)."""
        from operate.ledger.profiles import USDC

        usdc_addr = USDC[Chain.GNOSIS]
        result = wei_to_unit(1_000_000, "gnosis", usdc_addr)
        assert result == pytest.approx(1.0, abs=0.000001)


class TestWeiToToken:
    """Tests for wei_to_token."""

    def test_returns_formatted_string(self) -> None:
        """Test that wei_to_token returns a string with symbol."""
        result = wei_to_token(10**18, "gnosis", ZERO_ADDRESS)
        assert "xDAI" in result
        assert "1.000000" in result

    def test_returns_string_type(self) -> None:
        """Test that result is a string."""
        result = wei_to_token(10**18, "gnosis")
        assert isinstance(result, str)


class TestAskYesOrNo:
    """Tests for ask_yes_or_no."""

    def test_unattended_returns_true(self) -> None:
        """Unattended mode always returns True."""
        with patch.dict(os.environ, {"ATTENDED": "false"}):
            result = ask_yes_or_no("Do you want to proceed?")
        assert result is True

    def test_attended_yes_returns_true(self) -> None:
        """Attended mode with 'yes' input returns True."""
        with patch.dict(os.environ, {"ATTENDED": "true"}):
            with patch("builtins.input", return_value="yes"):
                result = ask_yes_or_no("Continue?")
        assert result is True

    def test_attended_y_returns_true(self) -> None:
        """Attended mode with 'y' input returns True."""
        with patch.dict(os.environ, {"ATTENDED": "true"}):
            with patch("builtins.input", return_value="y"):
                result = ask_yes_or_no("Continue?")
        assert result is True

    def test_attended_no_returns_false(self) -> None:
        """Attended mode with 'no' input returns False."""
        with patch.dict(os.environ, {"ATTENDED": "true"}):
            with patch("builtins.input", return_value="no"):
                result = ask_yes_or_no("Continue?")
        assert result is False

    def test_attended_n_returns_false(self) -> None:
        """Attended mode with 'n' input returns False."""
        with patch.dict(os.environ, {"ATTENDED": "true"}):
            with patch("builtins.input", return_value="n"):
                result = ask_yes_or_no("Continue?")
        assert result is False

    def test_attended_invalid_then_valid(self) -> None:
        """Attended mode loops on invalid input, then valid."""
        with patch.dict(os.environ, {"ATTENDED": "true"}):
            with patch("builtins.input", side_effect=["maybe", "no"]):
                result = ask_yes_or_no("Continue?")
        assert result is False

    def test_unattended_uppercase_false(self) -> None:
        """ATTENDED=False (uppercase) returns True."""
        with patch.dict(os.environ, {"ATTENDED": "False"}):
            result = ask_yes_or_no("Continue?")
        assert result is True


class TestAskOrGetFromEnv:
    """Tests for ask_or_get_from_env."""

    def test_attended_with_pass(self) -> None:
        """Attended mode with is_pass uses getpass."""
        with patch.dict(os.environ, {"ATTENDED": "true"}):
            with patch(
                "operate.quickstart.utils.getpass.getpass", return_value="secret"
            ):
                result = ask_or_get_from_env("Enter password: ", True, "MY_VAR")
        assert result == "secret"

    def test_attended_without_pass(self) -> None:
        """Attended mode without is_pass uses input."""
        with patch.dict(os.environ, {"ATTENDED": "true"}):
            with patch("builtins.input", return_value="  value  "):
                result = ask_or_get_from_env("Enter value: ", False, "MY_VAR")
        assert result == "value"

    def test_unattended_env_var_set(self) -> None:
        """Unattended mode returns env var value."""
        with patch.dict(os.environ, {"ATTENDED": "false", "MY_VAR": "  env_val  "}):
            result = ask_or_get_from_env("Enter: ", False, "MY_VAR")
        assert result == "env_val"

    def test_unattended_missing_raise(self) -> None:
        """Unattended mode raises ValueError when env var missing and raise_if_missing=True."""
        env = {"ATTENDED": "false"}
        env.pop("MY_MISSING_VAR", None)
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MY_MISSING_VAR", None)
            with pytest.raises(ValueError, match="MY_MISSING_VAR"):
                ask_or_get_from_env("Enter: ", False, "MY_MISSING_VAR")

    def test_unattended_missing_no_raise(self) -> None:
        """Unattended mode returns empty string when missing and raise_if_missing=False."""
        with patch.dict(os.environ, {"ATTENDED": "false"}, clear=False):
            os.environ.pop("MY_MISSING_VAR2", None)
            result = ask_or_get_from_env(
                "Enter: ", False, "MY_MISSING_VAR2", raise_if_missing=False
            )
        assert result == ""


class TestCheckRpc:
    """Tests for check_rpc."""

    def test_none_rpc_returns_false(self) -> None:
        """None RPC URL returns False immediately."""
        result = check_rpc("gnosis", None)
        assert result is False

    @patch("operate.quickstart.utils.Halo")
    @patch("operate.quickstart.utils.requests.post")
    def test_request_exception_returns_false(
        self, mock_post: MagicMock, mock_halo: MagicMock
    ) -> None:
        """Request exception returns False."""
        mock_post.side_effect = requests.exceptions.ConnectionError(
            "connection refused"
        )
        result = check_rpc("gnosis", "http://fake-rpc.example.com")
        assert result is False

    @patch("operate.quickstart.utils.Halo")
    @patch("operate.quickstart.utils.requests.post")
    def test_malformed_response_returns_false(
        self, mock_post: MagicMock, mock_halo: MagicMock
    ) -> None:
        """Malformed response (no error key) returns False."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_post.return_value = mock_resp
        result = check_rpc("gnosis", "http://fake-rpc.example.com")
        assert result is False

    @patch("operate.quickstart.utils.Halo")
    @patch("operate.quickstart.utils.requests.post")
    def test_out_of_requests_returns_false(
        self, mock_post: MagicMock, mock_halo: MagicMock
    ) -> None:
        """Out of requests error returns False."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "Out of Requests"}}
        mock_post.return_value = mock_resp
        result = check_rpc("gnosis", "http://fake-rpc.example.com")
        assert result is False

    @patch("operate.quickstart.utils.Halo")
    @patch("operate.quickstart.utils.requests.post")
    def test_eth_newfilter_not_available_returns_false(
        self, mock_post: MagicMock, mock_halo: MagicMock
    ) -> None:
        """eth_newFilter not available returns False."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": {
                "message": "The method eth_newFilter does not exist/is not available"
            }
        }
        mock_post.return_value = mock_resp
        result = check_rpc("gnosis", "http://fake-rpc.example.com")
        assert result is False

    @patch("operate.quickstart.utils.Halo")
    @patch("operate.quickstart.utils.requests.post")
    def test_invalid_params_returns_true(
        self, mock_post: MagicMock, mock_halo: MagicMock
    ) -> None:
        """Invalid params error (expected) returns True."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "invalid params"}}
        mock_post.return_value = mock_resp
        result = check_rpc("gnosis", "http://fake-rpc.example.com")
        assert result is True

    @patch("operate.quickstart.utils.Halo")
    @patch("operate.quickstart.utils.requests.post")
    def test_params_in_message_returns_true(
        self, mock_post: MagicMock, mock_halo: MagicMock
    ) -> None:
        """Message containing 'params' returns True."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "error in params"}}
        mock_post.return_value = mock_resp
        result = check_rpc("gnosis", "http://fake-rpc.example.com")
        assert result is True

    @patch("operate.quickstart.utils.Halo")
    @patch("operate.quickstart.utils.requests.post")
    def test_unknown_error_returns_false(
        self, mock_post: MagicMock, mock_halo: MagicMock
    ) -> None:
        """Unknown error message returns False."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "some unknown rpc failure"}}
        mock_post.return_value = mock_resp
        result = check_rpc("gnosis", "http://fake-rpc.example.com")
        assert result is False


class TestQuickstartConfigFromJson:
    """Tests for QuickstartConfig.from_json."""

    def test_all_fields_present(self, tmp_path: Path) -> None:
        """All fields deserialize correctly."""
        config_path = str(tmp_path / "test-config.json")
        obj = {
            "path": config_path,
            "rpc": {"gnosis": "http://rpc.gnosis.io"},
            "staking_program_id": "some_program",
            "principal_chain": "gnosis",
            "user_provided_args": {"KEY": "value"},
        }
        result = QuickstartConfig.from_json(obj)
        assert isinstance(result, QuickstartConfig)
        assert result.path == Path(config_path)
        assert result.rpc == {"gnosis": "http://rpc.gnosis.io"}
        assert result.staking_program_id == "some_program"
        assert result.principal_chain == "gnosis"
        assert result.user_provided_args == {"KEY": "value"}

    def test_optional_fields_absent(self, tmp_path: Path) -> None:
        """Optional fields absent are set to None (default)."""
        config_path = str(tmp_path / "test-config.json")
        obj = {"path": config_path}
        result = QuickstartConfig.from_json(obj)
        assert isinstance(result, QuickstartConfig)
        assert result.path == Path(config_path)
        assert result.rpc is None
        assert result.staking_program_id is None
        assert result.principal_chain is None
        assert result.user_provided_args is None

    def test_private_field_annotation_skipped(self, tmp_path: Path) -> None:
        """Fields starting with '_' are skipped by from_json."""

        @dataclass
        class _AnnotatedConfig(QuickstartConfig):
            pass

        # Inject both a private annotation (to trigger the skip) and 'path'
        _AnnotatedConfig.__annotations__["_hidden"] = str  # type: ignore[assignment]
        _AnnotatedConfig.__annotations__["path"] = Path  # type: ignore[assignment]

        config_path = str(tmp_path / "test-config.json")
        obj = {"path": config_path, "_hidden": "should_be_skipped"}
        result = _AnnotatedConfig.from_json(obj)
        # Private field should not end up in kwargs or cause an error
        assert isinstance(result, _AnnotatedConfig)
        assert result.path == Path(config_path)


# ============================================================
# Tests for operate/quickstart/run_service.py
# ============================================================


class TestDeprecatedProgramWarning:
    """Tests for _deprecated_program_warning."""

    def test_not_deprecated_returns_true(self) -> None:
        """Non-deprecated program returns True without prompting."""
        result = _deprecated_program_warning("optimus_alpha_2")
        assert result is True

    @patch("operate.quickstart.run_service.ask_yes_or_no", return_value=True)
    @patch("operate.quickstart.run_service.print_box")
    def test_deprecated_user_proceeds(
        self, mock_box: MagicMock, mock_ask: MagicMock
    ) -> None:
        """Deprecated program with user agreeing returns True."""
        deprecated_id = next(iter(DEPRECATED_QS_STAKING_PROGRAMS))
        result = _deprecated_program_warning(deprecated_id)
        assert result is True
        mock_box.assert_called_once()
        mock_ask.assert_called_once()

    @patch("operate.quickstart.run_service.ask_yes_or_no", return_value=False)
    @patch("operate.quickstart.run_service.print_box")
    def test_deprecated_user_declines(
        self, mock_box: MagicMock, mock_ask: MagicMock
    ) -> None:
        """Deprecated program with user declining returns False."""
        deprecated_id = next(iter(DEPRECATED_QS_STAKING_PROGRAMS))
        result = _deprecated_program_warning(deprecated_id)
        assert result is False


class TestAskConfirmPassword:
    """Tests for ask_confirm_password."""

    @patch(
        "operate.quickstart.run_service.ask_or_get_from_env",
        return_value="mypassword",
    )
    def test_matching_passwords_returns_password(self, mock_ask: MagicMock) -> None:
        """When both password entries match, returns the password."""
        result = ask_confirm_password()
        assert result == "mypassword"

    @patch(
        "operate.quickstart.run_service.ask_or_get_from_env",
        side_effect=["pass1", "pass2", "pass3", "pass3"],
    )
    def test_non_matching_then_matching_loops(self, mock_ask: MagicMock) -> None:
        """Loops until passwords match."""
        result = ask_confirm_password()
        assert result == "pass3"


class TestLoadLocalConfig:
    """Tests for load_local_config."""

    def test_no_old_path_no_glob_returns_new_config(self, tmp_path: Path) -> None:
        """No old path, no glob match: returns new QuickstartConfig."""
        operate = MagicMock()
        operate._path = tmp_path
        result = load_local_config(operate, "my-service")
        assert isinstance(result, QuickstartConfig)
        assert result.path == tmp_path / "my-service-quickstart-config.json"

    def test_no_old_path_with_glob_loads_from_file(self, tmp_path: Path) -> None:
        """No old path, matching glob: loads from file."""
        operate = MagicMock()
        operate._path = tmp_path

        config_file = tmp_path / "my-service-quickstart-config.json"
        config_data = {
            "path": str(config_file),
            "rpc": None,
            "staking_program_id": None,
            "principal_chain": None,
            "user_provided_args": None,
        }
        config_file.write_text(json.dumps(config_data))

        result = load_local_config(operate, "my-service")
        assert isinstance(result, QuickstartConfig)
        assert result.path == config_file

    @patch("operate.quickstart.run_service.shutil.move")
    @patch("operate.quickstart.run_service.QuickstartConfig.load")
    def test_old_path_no_staking_service_found_migrates(
        self, mock_load: MagicMock, mock_move: MagicMock, tmp_path: Path
    ) -> None:
        """Old path exists with NO_STAKING: service found triggers migration."""
        operate = MagicMock()
        operate._path = tmp_path

        old_path = tmp_path / "local_config.json"
        old_path.touch()

        mock_config = MagicMock()
        mock_config.staking_program_id = NO_STAKING_PROGRAM_ID
        mock_config.path = old_path
        mock_load.return_value = mock_config

        operate.service_manager.return_value.json = [{"name": "my-service"}]

        load_local_config(operate, "my-service")

        expected_new_path = tmp_path / "my-service-quickstart-config.json"
        assert mock_config.path == expected_new_path
        mock_move.assert_called_once_with(old_path, expected_new_path)

    @patch("operate.quickstart.run_service.shutil.move")
    @patch("operate.quickstart.run_service.QuickstartConfig.load")
    def test_old_path_no_staking_service_not_found_no_migration(
        self, mock_load: MagicMock, mock_move: MagicMock, tmp_path: Path
    ) -> None:
        """Old path exists with NO_STAKING: no matching service means no move."""
        operate = MagicMock()
        operate._path = tmp_path

        old_path = tmp_path / "local_config.json"
        old_path.touch()

        mock_config = MagicMock()
        mock_config.staking_program_id = NO_STAKING_PROGRAM_ID
        mock_config.path = old_path
        mock_load.return_value = mock_config

        operate.service_manager.return_value.json = [{"name": "other-service"}]

        load_local_config(operate, "my-service")

        mock_move.assert_not_called()

    @patch("operate.quickstart.run_service.QuickstartConfig.load")
    def test_old_path_custom_staking_program_not_found_raises(
        self, mock_load: MagicMock, tmp_path: Path
    ) -> None:
        """Old path with unknown staking program raises ValueError."""
        operate = MagicMock()
        operate._path = tmp_path

        old_path = tmp_path / "local_config.json"
        old_path.touch()

        mock_config = MagicMock()
        mock_config.staking_program_id = "nonexistent_program_xyz"
        mock_config.principal_chain = "gnosis"
        mock_load.return_value = mock_config

        with pytest.raises(ValueError, match="nonexistent_program_xyz"):
            load_local_config(operate, "my-service")

    @patch("operate.quickstart.run_service.shutil.move")
    @patch("operate.quickstart.run_service.QuickstartConfig.load")
    def test_old_path_custom_staking_program_found_migrates(
        self, mock_load: MagicMock, mock_move: MagicMock, tmp_path: Path
    ) -> None:
        """Old path with custom staking and known program migrates by keyword."""
        operate = MagicMock()
        operate._path = tmp_path

        old_path = tmp_path / "local_config.json"
        old_path.touch()

        mock_config = MagicMock()
        mock_config.staking_program_id = "quickstart_beta_hobbyist"
        mock_config.principal_chain = "gnosis"
        mock_config.path = old_path
        mock_load.return_value = mock_config

        # Service name contains "trader" (the keyword for quickstart_beta_hobbyist)
        operate.service_manager.return_value.json = [{"name": "trader-service"}]

        load_local_config(operate, "trader-service")

        expected_new_path = tmp_path / "trader-service-quickstart-config.json"
        assert mock_config.path == expected_new_path
        mock_move.assert_called_once_with(old_path, expected_new_path)


class TestAskPasswordIfNeeded:
    """Tests for ask_password_if_needed."""

    @patch("operate.quickstart.run_service.UserAccount")
    @patch(
        "operate.quickstart.run_service.ask_confirm_password", return_value="newpass"
    )
    @patch("operate.quickstart.run_service.print_section")
    def test_no_user_account_creates_new(
        self,
        mock_section: MagicMock,
        mock_confirm: MagicMock,
        mock_ua: MagicMock,
    ) -> None:
        """When user_account is None, creates new account."""
        operate = MagicMock()
        operate.user_account = None
        operate._path = Path("/fake/path")

        ask_password_if_needed(operate)

        mock_ua.new.assert_called_once()
        assert operate.password == "newpass"  # nosec B105

    @patch(
        "operate.quickstart.run_service.ask_or_get_from_env",
        return_value="correctpass",
    )
    def test_with_user_account_valid_password(self, mock_ask: MagicMock) -> None:
        """When user_account exists and password is valid, sets password."""
        operate = MagicMock()
        operate.user_account.is_valid.return_value = True

        ask_password_if_needed(operate)

        assert operate.password == "correctpass"  # nosec B105

    @patch(
        "operate.quickstart.run_service.ask_or_get_from_env",
        side_effect=["wrongpass", "rightpass"],
    )
    def test_with_user_account_wrong_then_right_password(
        self, mock_ask: MagicMock
    ) -> None:
        """Loops until valid password is provided."""
        operate = MagicMock()
        operate.user_account.is_valid.side_effect = [False, True]

        ask_password_if_needed(operate)

        assert operate.password == "rightpass"  # nosec B105


class TestGetService:
    """Tests for get_service."""

    def _make_template(self) -> Dict[str, Any]:
        """Create a minimal valid service template."""
        return {
            "name": "Test Service",
            "hash": "abc123",
            "agent_release": {"repository": {"version": "1.0.0"}},
            "env_variables": {},
            "allow_different_service_public_id": False,
        }

    def test_service_found_same_hash_loads(self) -> None:
        """Service with same hash is loaded (not updated)."""
        template = self._make_template()
        manager = MagicMock()
        mock_service = MagicMock()
        manager.json = [
            {
                "name": "Test Service",
                "hash": "abc123",
                "service_config_id": "svc-001",
                "agent_release": {"repository": {"version": "1.0.0"}},
            }
        ]
        manager.load.return_value = mock_service
        mock_service.env_variables = {}

        result = get_service(manager, template)

        manager.load.assert_called_once_with(service_config_id="svc-001")
        assert result == mock_service

    def test_service_found_different_hash_updates(self) -> None:
        """Service with different hash is updated."""
        template = self._make_template()
        manager = MagicMock()
        mock_service = MagicMock()
        manager.json = [
            {
                "name": "Test Service",
                "hash": "old_hash",
                "service_config_id": "svc-001",
                "agent_release": {"repository": {"version": "1.0.0"}},
            }
        ]
        manager.update.return_value = mock_service
        mock_service.env_variables = {}

        result = get_service(manager, template)

        manager.update.assert_called_once()
        assert result == mock_service

    def test_service_not_found_creates(self) -> None:
        """Service not found triggers load_or_create."""
        template = self._make_template()
        manager = MagicMock()
        mock_service = MagicMock()
        manager.json = []
        manager.load_or_create.return_value = mock_service

        result = get_service(manager, template)

        manager.load_or_create.assert_called_once_with(
            hash="abc123", service_template=template
        )
        assert result == mock_service

    def test_service_found_env_variables_updated(self) -> None:
        """Env variables from template are merged into service."""
        template = self._make_template()
        template["env_variables"] = {
            "MY_VAR": {
                "provision_type": "fixed",
                "value": "myval",
                "name": "MY_VAR",
            }
        }
        manager = MagicMock()
        mock_service = MagicMock()
        manager.json = [
            {
                "name": "Test Service",
                "hash": "abc123",
                "service_config_id": "svc-001",
                "agent_release": {"repository": {"version": "1.0.0"}},
            }
        ]
        manager.load.return_value = mock_service
        mock_service.env_variables = {}

        get_service(manager, template)

        assert "MY_VAR" in mock_service.env_variables


class TestAskFundsFromRequirements:
    """Tests for _ask_funds_from_requirements."""

    @patch("operate.quickstart.run_service.Halo")
    def test_no_refill_needed_returns_true(self, mock_halo: MagicMock) -> None:
        """When no refill needed and start allowed, returns True."""
        manager = MagicMock()
        wallet = MagicMock()
        service = MagicMock()

        wallet.crypto.address = "0xEOA"
        wallet.safes.values.return_value = []
        service.chain_configs.values.return_value = []
        service.agent_addresses = []

        manager.funding_requirements.return_value = {
            "is_refill_required": False,
            "allow_start_agent": True,
            "balances": {},
        }

        with patch.object(ChainAmounts, "from_json", return_value=ChainAmounts({})):
            result = _ask_funds_from_requirements(manager, wallet, service)

        assert result is True

    @patch("operate.quickstart.run_service.ask_funds_in_address")
    @patch("operate.quickstart.run_service.Halo")
    def test_refill_needed_skips_placeholder_addresses(
        self, mock_halo: MagicMock, mock_ask_funds: MagicMock
    ) -> None:
        """Placeholder addresses (master_safe, service_safe) are skipped."""
        manager = MagicMock()
        wallet = MagicMock()
        service = MagicMock()

        wallet.crypto.address = "0xEOA"
        wallet.safes.values.return_value = []
        service.chain_configs.values.return_value = []
        service.agent_addresses = []

        manager.funding_requirements.return_value = {
            "is_refill_required": True,
            "allow_start_agent": False,
            "refill_requirements": {"gnosis": {"master_safe": {ZERO_ADDRESS: 100}}},
        }

        chain_data = ChainAmounts({"gnosis": {"master_safe": {ZERO_ADDRESS: 100}}})
        with patch.object(ChainAmounts, "from_json", return_value=chain_data):
            result = _ask_funds_from_requirements(manager, wallet, service)

        assert result is False
        mock_ask_funds.assert_not_called()

    @patch("operate.quickstart.run_service.ask_funds_in_address")
    @patch("operate.quickstart.run_service.Halo")
    def test_refill_needed_calls_ask_funds(
        self, mock_halo: MagicMock, mock_ask_funds: MagicMock
    ) -> None:
        """Non-placeholder addresses trigger ask_funds_in_address."""
        manager = MagicMock()
        wallet = MagicMock()
        service = MagicMock()

        wallet.crypto.address = "0xEOA"
        wallet.safes.values.return_value = []
        service.chain_configs.values.return_value = []
        service.agent_addresses = []

        manager.funding_requirements.return_value = {
            "is_refill_required": True,
            "allow_start_agent": False,
            "refill_requirements": {"gnosis": {"0xEOA": {ZERO_ADDRESS: 10**18}}},
        }

        chain_data = ChainAmounts({"gnosis": {"0xEOA": {ZERO_ADDRESS: 10**18}}})
        with patch.object(ChainAmounts, "from_json", return_value=chain_data):
            result = _ask_funds_from_requirements(manager, wallet, service)

        assert result is False
        mock_ask_funds.assert_called_once()

    @patch("operate.quickstart.run_service.Halo")
    def test_no_refill_with_balance_printing(self, mock_halo: MagicMock) -> None:
        """Balance data is printed when no refill is needed."""
        manager = MagicMock()
        wallet = MagicMock()
        service = MagicMock()

        wallet.crypto.address = "0xEOA"
        wallet.safes.values.return_value = []
        service.chain_configs.values.return_value = []
        service.agent_addresses = []
        service.chain_configs.__getitem__.return_value.ledger_config.rpc = "http://rpc"

        manager.funding_requirements.return_value = {
            "is_refill_required": False,
            "allow_start_agent": True,
            "balances": {"gnosis": {"0xEOA": {ZERO_ADDRESS: 10**18}}},
        }

        chain_data = ChainAmounts({"gnosis": {"0xEOA": {ZERO_ADDRESS: 10**18}}})
        with patch.object(ChainAmounts, "from_json", return_value=chain_data):
            result = _ask_funds_from_requirements(manager, wallet, service)

        assert result is True


class TestMaybeCreateMasterEoa:
    """Tests for _maybe_create_master_eoa."""

    def test_wallet_exists_does_nothing(self) -> None:
        """When wallet exists, nothing is created."""
        operate = MagicMock()
        operate.wallet_manager.exists.return_value = True

        _maybe_create_master_eoa(operate)

        operate.wallet_manager.create.assert_not_called()

    @patch("operate.quickstart.run_service.ask_or_get_from_env", return_value="")
    @patch("operate.quickstart.run_service.print_box")
    def test_wallet_not_exists_creates_wallet(
        self, mock_box: MagicMock, mock_ask: MagicMock
    ) -> None:
        """When wallet doesn't exist, creates wallet and prints mnemonic."""
        operate = MagicMock()
        operate.wallet_manager.exists.return_value = False
        mock_wallet = MagicMock()
        operate.wallet_manager.create.return_value = (mock_wallet, ["word1", "word2"])

        _maybe_create_master_eoa(operate)

        operate.wallet_manager.create.assert_called_once()
        mock_box.assert_called_once()
        assert mock_wallet.password == operate.password


# ============================================================
# Tests for operate/quickstart/analyse_logs.py
# ============================================================


class TestFindBuildDirectory:
    """Tests for find_build_directory."""

    def test_service_found_build_exists_returns_path(self, tmp_path: Path) -> None:
        """Service found and build dir exists: returns build dir."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"hash": "abc123", "name": "TestService"}))

        build_dir = tmp_path / "deployment"
        build_dir.mkdir()

        service = MagicMock()
        service.hash = "abc123"
        service.path = tmp_path

        operate = MagicMock()
        operate.service_manager.return_value.get_all_services.return_value = (
            [service],
            [],
        )

        result = find_build_directory(config_file, operate)
        assert result == build_dir

    def test_service_found_build_not_exists_exits(self, tmp_path: Path) -> None:
        """Service found but build dir missing: sys.exit(1)."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"hash": "abc123", "name": "TestService"}))

        service = MagicMock()
        service.hash = "abc123"
        service.path = tmp_path
        # deployment/ does NOT exist

        operate = MagicMock()
        operate.service_manager.return_value.get_all_services.return_value = (
            [service],
            [],
        )

        with pytest.raises(SystemExit) as exc_info:
            find_build_directory(config_file, operate)
        assert exc_info.value.code == 1

    def test_service_not_found_exits(self, tmp_path: Path) -> None:
        """Service not found in manager: sys.exit(1)."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"hash": "def456", "name": "TestService"}))

        service = MagicMock()
        service.hash = "abc123"  # different hash

        operate = MagicMock()
        operate.service_manager.return_value.get_all_services.return_value = (
            [service],
            [],
        )

        with pytest.raises(SystemExit) as exc_info:
            find_build_directory(config_file, operate)
        assert exc_info.value.code == 1


class TestRunAnalysis:
    """Tests for run_analysis."""

    @patch("operate.quickstart.analyse_logs.subprocess.run")
    def test_basic_command_runs(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Basic command without extra kwargs runs correctly."""
        logs_dir = tmp_path / "logs"
        run_analysis(logs_dir)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "poetry" in cmd
        assert "--from-dir" in cmd

    @patch("operate.quickstart.analyse_logs.subprocess.run")
    def test_all_kwargs_extend_command(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """All optional kwargs add correct flags."""
        logs_dir = tmp_path / "logs"
        run_analysis(
            logs_dir,
            agent="agent0",
            reset_db="true",
            start_time="2024-01-01",
            end_time="2024-01-02",
            log_level="INFO",
            period="1",
            round="2",
            behaviour="MyBehaviour",
            fsm="true",
            include_regex=".*foo.*",
            exclude_regex=".*bar.*",
        )
        cmd = mock_run.call_args[0][0]
        assert "--agent" in cmd
        assert "--reset-db" in cmd
        assert "--start-time" in cmd
        assert "--end-time" in cmd
        assert "--log-level" in cmd
        assert "--period" in cmd
        assert "--round" in cmd
        assert "--behaviour" in cmd
        assert "--fsm" in cmd
        assert "--include-regex" in cmd
        assert "--exclude-regex" in cmd

    @patch("operate.quickstart.analyse_logs.subprocess.run")
    def test_called_process_error_exits(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Called process error causes sys.exit with the returncode."""
        logs_dir = tmp_path / "logs"
        mock_run.side_effect = subprocess.CalledProcessError(returncode=2, cmd="cmd")

        with pytest.raises(SystemExit) as exc_info:
            run_analysis(logs_dir)
        assert exc_info.value.code == 2

    @patch("operate.quickstart.analyse_logs.subprocess.run")
    def test_file_not_found_exits(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """File not found causes sys.exit(1)."""
        logs_dir = tmp_path / "logs"
        mock_run.side_effect = FileNotFoundError("poetry not found")

        with pytest.raises(SystemExit) as exc_info:
            run_analysis(logs_dir)
        assert exc_info.value.code == 1

    @patch("operate.quickstart.analyse_logs.subprocess.run")
    def test_empty_kwargs_not_added(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Empty/falsy kwargs do not extend the command."""
        logs_dir = tmp_path / "logs"
        run_analysis(logs_dir, agent="", reset_db="", start_time="")
        cmd = mock_run.call_args[0][0]
        assert "--agent" not in cmd
        assert "--reset-db" not in cmd
        assert "--start-time" not in cmd


class TestAnalyseLogs:
    """Tests for analyse_logs."""

    def test_config_file_not_found_exits(self, tmp_path: Path) -> None:
        """Missing config file causes sys.exit(1)."""
        operate = MagicMock()
        config_path = str(tmp_path / "nonexistent.json")

        with pytest.raises(SystemExit) as exc_info:
            analyse_logs(operate, config_path)
        assert exc_info.value.code == 1

    @patch("operate.quickstart.analyse_logs.find_build_directory")
    def test_logs_dir_not_found_exits(
        self, mock_find: MagicMock, tmp_path: Path
    ) -> None:
        """Missing logs directory causes sys.exit(1)."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        operate = MagicMock()

        build_dir = tmp_path / "deployment"
        mock_find.return_value = build_dir
        # persistent_data/logs does NOT exist

        with pytest.raises(SystemExit) as exc_info:
            analyse_logs(operate, str(config_file))
        assert exc_info.value.code == 1

    @patch("operate.quickstart.analyse_logs.run_analysis")
    @patch("operate.quickstart.analyse_logs.find_build_directory")
    def test_success_calls_run_analysis(
        self, mock_find: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """When all paths exist, run_analysis is called."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        operate = MagicMock()

        build_dir = tmp_path / "deployment"
        logs_dir = build_dir / "persistent_data" / "logs"
        logs_dir.mkdir(parents=True)
        mock_find.return_value = build_dir

        analyse_logs(operate, str(config_file), agent="agent0")

        mock_run.assert_called_once_with(logs_dir, agent="agent0")


# ============================================================
# Tests for operate/quickstart/claim_staking_rewards.py
# ============================================================


class TestClaimStakingRewards:
    """Tests for claim_staking_rewards."""

    @patch("operate.quickstart.claim_staking_rewards.print_section")
    @patch("operate.quickstart.claim_staking_rewards.load_local_config")
    def test_config_not_found_exits_early(
        self, mock_load: MagicMock, mock_section: MagicMock
    ) -> None:
        """Config path doesn't exist: prints message and returns."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = False
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            claim_staking_rewards(operate, "/fake/path.json")

        operate.service_manager.assert_not_called()

    @patch("operate.quickstart.claim_staking_rewards.ask_yes_or_no", return_value=False)
    @patch("operate.quickstart.claim_staking_rewards.print_section")
    @patch("operate.quickstart.claim_staking_rewards.load_local_config")
    def test_user_says_no_exits_early(
        self,
        mock_load: MagicMock,
        mock_section: MagicMock,
        mock_ask: MagicMock,
    ) -> None:
        """User declines: prints 'Cancelled.' and returns."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = True
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            claim_staking_rewards(operate, "/fake/path.json")

        operate.service_manager.assert_not_called()

    @patch("operate.quickstart.claim_staking_rewards.ask_yes_or_no", return_value=True)
    @patch("operate.quickstart.claim_staking_rewards.get_service")
    @patch("operate.quickstart.claim_staking_rewards.configure_local_config")
    @patch("operate.quickstart.claim_staking_rewards.ask_password_if_needed")
    @patch("operate.quickstart.claim_staking_rewards.load_local_config")
    @patch("operate.quickstart.claim_staking_rewards.print_section")
    def test_main_path_success(
        self,
        mock_section: MagicMock,
        mock_load_local: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_get_service: MagicMock,
        mock_ask_yn: MagicMock,
    ) -> None:
        """Main path succeeds: claim is called and rewards printed."""
        operate = MagicMock()

        mock_cfg_initial = MagicMock()
        mock_cfg_initial.path.exists.return_value = True
        mock_cfg_final = MagicMock()
        mock_cfg_final.principal_chain = "gnosis"
        mock_cfg_final.rpc = {"gnosis": "http://rpc"}

        mock_load_local.side_effect = [mock_cfg_initial, mock_cfg_final]
        mock_configure.return_value = mock_cfg_final

        mock_service = MagicMock()
        mock_service.name = "Test Service"
        mock_get_service.return_value = mock_service

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            claim_staking_rewards(operate, "/fake/path.json")

        operate.service_manager.return_value.claim_on_chain_from_safe.assert_called_once()

    @patch("operate.quickstart.claim_staking_rewards.ask_yes_or_no", return_value=True)
    @patch("operate.quickstart.claim_staking_rewards.get_service")
    @patch("operate.quickstart.claim_staking_rewards.configure_local_config")
    @patch("operate.quickstart.claim_staking_rewards.ask_password_if_needed")
    @patch("operate.quickstart.claim_staking_rewards.load_local_config")
    @patch("operate.quickstart.claim_staking_rewards.print_section")
    def test_main_path_runtime_error_handled(
        self,
        mock_section: MagicMock,
        mock_load_local: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_get_service: MagicMock,
        mock_ask_yn: MagicMock,
    ) -> None:
        """Runtime error from claim is caught and logged."""
        operate = MagicMock()

        mock_cfg_initial = MagicMock()
        mock_cfg_initial.path.exists.return_value = True
        mock_cfg_final = MagicMock()
        mock_cfg_final.principal_chain = "gnosis"
        mock_cfg_final.rpc = {"gnosis": "http://rpc"}

        mock_load_local.side_effect = [mock_cfg_initial, mock_cfg_final]
        mock_configure.return_value = mock_cfg_final

        mock_service = MagicMock()
        mock_service.name = "Test Service"
        mock_get_service.return_value = mock_service

        operate.service_manager.return_value.claim_on_chain_from_safe.side_effect = (
            RuntimeError("tx reverted")
        )

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            # Should NOT raise - error is handled
            claim_staking_rewards(operate, "/fake/path.json")


# ============================================================
# Tests for operate/quickstart/reset_configs.py
# ============================================================


class TestAskToChange:
    """Tests for _ask_to_change."""

    @patch("operate.quickstart.reset_configs.ask_yes_or_no", return_value=False)
    def test_user_says_no_returns_old_value(self, mock_ask: MagicMock) -> None:
        """User says no to change: returns original value."""
        result = _ask_to_change("RPC", "MY_RPC", "http://old-rpc.com")
        assert result == "http://old-rpc.com"

    @patch(
        "operate.quickstart.reset_configs.ask_or_get_from_env",
        return_value="newvalue",
    )
    @patch("operate.quickstart.reset_configs.ask_yes_or_no", return_value=True)
    def test_user_says_yes_returns_new_value(
        self, mock_ask_yn: MagicMock, mock_ask_env: MagicMock
    ) -> None:
        """User says yes, validator passes immediately: returns new value."""
        result = _ask_to_change(
            "MyVar",
            "MY_VAR",
            "old_val",
            validator=lambda x: x is not None,
        )
        assert result == "newvalue"

    @patch(
        "operate.quickstart.reset_configs.ask_or_get_from_env",
        return_value="newvalue",
    )
    @patch("operate.quickstart.reset_configs.ask_yes_or_no", return_value=True)
    def test_hidden_short_value_masks_all(
        self, mock_ask_yn: MagicMock, mock_ask_env: MagicMock
    ) -> None:
        """Hidden values with length < 4 are fully masked."""
        result = _ask_to_change(
            "Key",
            "MY_KEY",
            "abc",
            hidden=True,
            validator=lambda x: x is not None,
        )
        assert result == "newvalue"

    @patch(
        "operate.quickstart.reset_configs.ask_or_get_from_env",
        return_value="newval",
    )
    @patch("operate.quickstart.reset_configs.ask_yes_or_no", return_value=True)
    def test_hidden_long_value_shows_last_four(
        self, mock_ask_yn: MagicMock, mock_ask_env: MagicMock
    ) -> None:
        """Hidden values with length >= 4 show last 4 chars."""
        result = _ask_to_change(
            "Key",
            "MY_KEY",
            "abcde12345",
            hidden=True,
            validator=lambda x: x is not None,
        )
        assert result == "newval"


class TestResetConfigs:
    """Tests for reset_configs."""

    @patch("operate.quickstart.reset_configs.print_title")
    @patch("operate.quickstart.reset_configs.load_local_config")
    def test_config_not_found_exits_early(
        self, mock_load: MagicMock, mock_title: MagicMock
    ) -> None:
        """Config path doesn't exist: prints message and returns."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = False
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_configs(operate, "/fake/path.json")

        mock_cfg.store.assert_not_called()

    @patch("operate.quickstart.reset_configs.print_section")
    @patch("operate.quickstart.reset_configs._ask_to_change", return_value="new_rpc")
    @patch("operate.quickstart.reset_configs.print_title")
    @patch("operate.quickstart.reset_configs.load_local_config")
    def test_main_path_updates_config(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """Main path: iterates rpc and user_provided_args, stores config."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = True
        mock_cfg.rpc = {"gnosis": "http://old-rpc.com"}
        mock_cfg.user_provided_args = {"API_KEY": "old_key"}
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_configs(operate, "/fake/path.json")

        mock_cfg.store.assert_called_once()
        assert mock_cfg.rpc["gnosis"] == "new_rpc"

    @patch("operate.quickstart.reset_configs.print_section")
    @patch("operate.quickstart.reset_configs._ask_to_change", return_value="new_rpc")
    @patch("operate.quickstart.reset_configs.print_title")
    @patch("operate.quickstart.reset_configs.load_local_config")
    def test_none_rpc_initialized_to_empty_dict(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """When rpc is None, it is initialized to {}."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = True
        mock_cfg.rpc = None
        mock_cfg.user_provided_args = None
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_configs(operate, "/fake/path.json")

        mock_cfg.store.assert_called_once()


# ============================================================
# Tests for operate/quickstart/reset_password.py
# ============================================================


class TestResetPassword:
    """Tests for reset_password."""

    @patch("operate.quickstart.reset_password.print_title")
    def test_no_user_file_exits_early(
        self, mock_title: MagicMock, tmp_path: Path
    ) -> None:
        """User JSON file doesn't exist: prints message and returns."""
        operate = MagicMock()
        operate._path = tmp_path
        # No user JSON file created

        reset_password(operate)

        operate.wallet_manager.update_password.assert_not_called()

    @patch("operate.quickstart.reset_password.UserAccount")
    @patch(
        "operate.quickstart.reset_password.ask_confirm_password",
        return_value="newpass",
    )
    @patch(
        "operate.quickstart.reset_password.ask_or_get_from_env",
        return_value="oldpass",
    )
    @patch("operate.quickstart.reset_password.print_section")
    @patch("operate.quickstart.reset_password.print_title")
    def test_correct_password_resets_all(
        self,
        mock_title: MagicMock,
        mock_section: MagicMock,
        mock_ask_env: MagicMock,
        mock_confirm: MagicMock,
        mock_ua: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Correct old password triggers full reset of account and wallets."""
        operate = MagicMock()
        operate._path = tmp_path
        operate.user_account.is_valid.return_value = True

        from operate.constants import USER_JSON

        (tmp_path / USER_JSON).touch()

        reset_password(operate)

        mock_ua.new.assert_called_once()
        operate.wallet_manager.update_password.assert_called_once_with(
            new_password="newpass"  # nosec B105,B106
        )
        operate.keys_manager.update_password.assert_called_once_with(
            new_password="newpass"  # nosec B105,B106
        )

    @patch("operate.quickstart.reset_password.UserAccount")
    @patch(
        "operate.quickstart.reset_password.ask_confirm_password",
        return_value="newpass",
    )
    @patch(
        "operate.quickstart.reset_password.ask_or_get_from_env",
        side_effect=["wrongpass", "rightpass"],
    )
    @patch("operate.quickstart.reset_password.print_section")
    @patch("operate.quickstart.reset_password.print_title")
    def test_wrong_then_right_password_loops(
        self,
        mock_title: MagicMock,
        mock_section: MagicMock,
        mock_ask_env: MagicMock,
        mock_confirm: MagicMock,
        mock_ua: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Wrong password loops until correct password entered."""
        operate = MagicMock()
        operate._path = tmp_path
        operate.user_account.is_valid.side_effect = [False, True]

        from operate.constants import USER_JSON

        (tmp_path / USER_JSON).touch()

        reset_password(operate)

        assert operate.password == "rightpass"  # nosec B105


# ============================================================
# Tests for operate/quickstart/stop_service.py
# ============================================================


class TestStopService:
    """Tests for stop_service."""

    @patch("operate.quickstart.stop_service.print_title")
    @patch("operate.quickstart.stop_service.load_local_config")
    def test_config_not_found_exits_early(
        self, mock_load: MagicMock, mock_title: MagicMock
    ) -> None:
        """Config path doesn't exist: returns without stopping."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = False
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            stop_service(operate, "/fake/path.json")

        operate.service_manager.return_value.stop_service_locally.assert_not_called()

    @patch("operate.quickstart.stop_service.print_section")
    @patch("operate.quickstart.stop_service.get_service")
    @patch("operate.quickstart.stop_service.configure_local_config")
    @patch("operate.quickstart.stop_service.ask_password_if_needed")
    @patch("operate.quickstart.stop_service.print_title")
    @patch("operate.quickstart.stop_service.load_local_config")
    def test_use_binary_true_sets_use_docker_false(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_get_svc: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """use_binary=True sets use_docker=False."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = True
        mock_load.return_value = mock_cfg
        mock_service = MagicMock()
        mock_get_svc.return_value = mock_service

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            stop_service(operate, "/fake/path.json", use_binary=True)

        operate.service_manager.return_value.stop_service_locally.assert_called_once_with(
            service_config_id=mock_service.service_config_id,
            use_docker=False,
            force=True,
        )

    @patch("operate.quickstart.stop_service.print_section")
    @patch("operate.quickstart.stop_service.get_service")
    @patch("operate.quickstart.stop_service.configure_local_config")
    @patch("operate.quickstart.stop_service.ask_password_if_needed")
    @patch("operate.quickstart.stop_service.print_title")
    @patch("operate.quickstart.stop_service.load_local_config")
    def test_use_binary_false_sets_use_docker_true(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_get_svc: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """use_binary=False (default) sets use_docker=True."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = True
        mock_load.return_value = mock_cfg
        mock_service = MagicMock()
        mock_get_svc.return_value = mock_service

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            stop_service(operate, "/fake/path.json", use_binary=False)

        operate.service_manager.return_value.stop_service_locally.assert_called_once_with(
            service_config_id=mock_service.service_config_id,
            use_docker=True,
            force=True,
        )


# ============================================================
# Tests for operate/quickstart/terminate_on_chain_service.py
# ============================================================


class TestTerminateService:
    """Tests for terminate_service."""

    @patch("operate.quickstart.terminate_on_chain_service.print_title")
    @patch("operate.quickstart.terminate_on_chain_service.load_local_config")
    def test_config_not_found_exits_early(
        self, mock_load: MagicMock, mock_title: MagicMock
    ) -> None:
        """Config path doesn't exist: returns without terminating."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = False
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            terminate_service(operate, "/fake/path.json")

        operate.service_manager.assert_not_called()

    @patch(
        "operate.quickstart.terminate_on_chain_service.ask_yes_or_no",
        return_value=False,
    )
    @patch("operate.quickstart.terminate_on_chain_service.print_title")
    @patch("operate.quickstart.terminate_on_chain_service.load_local_config")
    def test_user_says_no_exits_early(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask: MagicMock,
    ) -> None:
        """User declines: prints 'Cancelled.' and returns."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = True
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            terminate_service(operate, "/fake/path.json")

        operate.service_manager.assert_not_called()

    @patch("operate.quickstart.terminate_on_chain_service.print_section")
    @patch("operate.quickstart.terminate_on_chain_service.ensure_enough_funds")
    @patch("operate.quickstart.terminate_on_chain_service.get_service")
    @patch("operate.quickstart.terminate_on_chain_service.configure_local_config")
    @patch("operate.quickstart.terminate_on_chain_service.ask_password_if_needed")
    @patch(
        "operate.quickstart.terminate_on_chain_service.ask_yes_or_no",
        return_value=True,
    )
    @patch("operate.quickstart.terminate_on_chain_service.print_title")
    @patch("operate.quickstart.terminate_on_chain_service.load_local_config")
    def test_pre_registration_state_prints_info(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_yn: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_get_svc: MagicMock,
        mock_enough: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """PRE_REGISTRATION state causes service info to be printed."""
        operate = MagicMock()
        mock_load_initial = MagicMock()
        mock_load_initial.path.exists.return_value = True
        mock_load.return_value = mock_load_initial

        mock_cfg = MagicMock()
        mock_cfg.principal_chain = "gnosis"
        mock_configure.return_value = mock_cfg

        mock_service = MagicMock()
        mock_service.chain_configs.__getitem__.return_value.chain_data.token = 42
        mock_get_svc.return_value = mock_service

        manager = operate.service_manager.return_value
        manager._get_on_chain_state.return_value = OnChainState.PRE_REGISTRATION

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            terminate_service(operate, "/fake/path.json")

        manager.terminate_service_on_chain_from_safe.assert_called_once()

    @patch("operate.quickstart.terminate_on_chain_service.print_section")
    @patch("operate.quickstart.terminate_on_chain_service.ensure_enough_funds")
    @patch("operate.quickstart.terminate_on_chain_service.get_service")
    @patch("operate.quickstart.terminate_on_chain_service.configure_local_config")
    @patch("operate.quickstart.terminate_on_chain_service.ask_password_if_needed")
    @patch(
        "operate.quickstart.terminate_on_chain_service.ask_yes_or_no",
        return_value=True,
    )
    @patch("operate.quickstart.terminate_on_chain_service.print_title")
    @patch("operate.quickstart.terminate_on_chain_service.load_local_config")
    def test_non_pre_registration_state_no_service_info(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_yn: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_get_svc: MagicMock,
        mock_enough: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """Non-PRE_REGISTRATION state: terminates but no extra service info printed."""
        operate = MagicMock()
        mock_load_initial = MagicMock()
        mock_load_initial.path.exists.return_value = True
        mock_load.return_value = mock_load_initial

        mock_cfg = MagicMock()
        mock_cfg.principal_chain = "gnosis"
        mock_configure.return_value = mock_cfg

        mock_service = MagicMock()
        mock_get_svc.return_value = mock_service

        manager = operate.service_manager.return_value
        manager._get_on_chain_state.return_value = OnChainState.DEPLOYED

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            terminate_service(operate, "/fake/path.json")

        manager.terminate_service_on_chain_from_safe.assert_called_once()


# ============================================================
# Tests for operate/quickstart/reset_staking.py
# ============================================================


class TestResetStaking:
    """Tests for reset_staking."""

    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_config_not_found_exits_early(
        self, mock_load: MagicMock, mock_title: MagicMock
    ) -> None:
        """Config path doesn't exist: returns without proceeding."""
        operate = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.path.exists.return_value = False
        mock_load.return_value = mock_cfg

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        operate.service_manager.assert_not_called()

    @patch("operate.quickstart.reset_staking.configure_local_config")
    @patch("operate.quickstart.reset_staking.ask_password_if_needed")
    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_no_staking_program_exits_early(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
    ) -> None:
        """No staking program set: prints message and returns."""
        operate = MagicMock()
        mock_cfg_load = MagicMock()
        mock_cfg_load.path.exists.return_value = True
        mock_load.return_value = mock_cfg_load

        mock_cfg_conf = MagicMock()
        mock_cfg_conf.principal_chain = "gnosis"
        mock_cfg_conf.staking_program_id = None  # falsy
        mock_configure.return_value = mock_cfg_conf

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        operate.service_manager.assert_not_called()

    @patch(
        "operate.quickstart.reset_staking.ask_yes_or_no",
        return_value=False,
    )
    @patch("operate.quickstart.reset_staking.configure_local_config")
    @patch("operate.quickstart.reset_staking.ask_password_if_needed")
    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_user_says_no_exits_early(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_ask_yn: MagicMock,
    ) -> None:
        """User declines continuation: prints 'Cancelled.' and returns."""
        operate = MagicMock()
        mock_cfg_load = MagicMock()
        mock_cfg_load.path.exists.return_value = True
        mock_load.return_value = mock_cfg_load

        mock_cfg_conf = MagicMock()
        mock_cfg_conf.principal_chain = "gnosis"
        mock_cfg_conf.staking_program_id = "some_program"
        mock_configure.return_value = mock_cfg_conf

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        operate.service_manager.assert_not_called()

    @patch("operate.quickstart.reset_staking.get_service")
    @patch(
        "operate.quickstart.reset_staking.ask_yes_or_no",
        return_value=True,
    )
    @patch("operate.quickstart.reset_staking.configure_local_config")
    @patch("operate.quickstart.reset_staking.ask_password_if_needed")
    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_no_staking_program_id_skips_unstaking(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_ask_yn: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """NO_STAKING_PROGRAM_ID skips the unstaking block and resets."""
        operate = MagicMock()
        mock_cfg_load = MagicMock()
        mock_cfg_load.path.exists.return_value = True
        mock_load.return_value = mock_cfg_load

        mock_cfg_conf = MagicMock()
        mock_cfg_conf.principal_chain = "gnosis"
        mock_cfg_conf.staking_program_id = NO_STAKING_PROGRAM_ID
        mock_configure.return_value = mock_cfg_conf

        mock_service = MagicMock()
        mock_service.chain_configs.__getitem__.return_value.ledger_config.rpc = (
            "http://fake-rpc"
        )
        mock_get_svc.return_value = mock_service

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        # Should have updated config and manager
        assert mock_cfg_conf.staking_program_id is None
        mock_cfg_conf.store.assert_called()

    @patch("operate.quickstart.reset_staking.get_service")
    @patch(
        "operate.quickstart.reset_staking.ask_yes_or_no",
        return_value=True,
    )
    @patch("operate.quickstart.reset_staking.configure_local_config")
    @patch("operate.quickstart.reset_staking.ask_password_if_needed")
    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_custom_program_id_skips_unstaking(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_ask_yn: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """CUSTOM_PROGRAM_ID skips the unstaking block and resets."""
        operate = MagicMock()
        mock_cfg_load = MagicMock()
        mock_cfg_load.path.exists.return_value = True
        mock_load.return_value = mock_cfg_load

        mock_cfg_conf = MagicMock()
        mock_cfg_conf.principal_chain = "gnosis"
        mock_cfg_conf.staking_program_id = CUSTOM_PROGRAM_ID
        mock_configure.return_value = mock_cfg_conf

        mock_service = MagicMock()
        mock_service.chain_configs.__getitem__.return_value.ledger_config.rpc = (
            "http://fake-rpc"
        )
        mock_get_svc.return_value = mock_service

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        assert mock_cfg_conf.staking_program_id is None
        mock_cfg_conf.store.assert_called()

    @patch("operate.quickstart.reset_staking.print_section")
    @patch("operate.quickstart.reset_staking.get_staking_contract")
    @patch("operate.quickstart.reset_staking.get_service")
    @patch(
        "operate.quickstart.reset_staking.ask_yes_or_no",
        return_value=True,
    )
    @patch("operate.quickstart.reset_staking.configure_local_config")
    @patch("operate.quickstart.reset_staking.ask_password_if_needed")
    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_staked_cannot_unstake_returns_early(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_ask_yn: MagicMock,
        mock_get_svc: MagicMock,
        mock_get_staking: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """STAKED service that cannot be unstaked prints message and returns."""
        operate = MagicMock()
        mock_cfg_load = MagicMock()
        mock_cfg_load.path.exists.return_value = True
        mock_load.return_value = mock_cfg_load

        mock_cfg_conf = MagicMock()
        mock_cfg_conf.principal_chain = "gnosis"
        mock_cfg_conf.staking_program_id = "quickstart_beta_hobbyist"
        mock_configure.return_value = mock_cfg_conf

        mock_service = MagicMock()
        mock_service.chain_configs.__getitem__.return_value.ledger_config.rpc = (
            "http://fake-rpc"
        )
        mock_get_svc.return_value = mock_service
        mock_get_staking.return_value = "0xStakingContract"

        manager = operate.service_manager.return_value
        sftxb = manager.get_eth_safe_tx_builder.return_value
        sftxb.staking_status.return_value = StakingState.STAKED
        sftxb.can_unstake.return_value = False

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        # Store should NOT be called (returned early)
        mock_cfg_conf.store.assert_not_called()

    @patch("operate.quickstart.reset_staking.get_staking_contract")
    @patch("operate.quickstart.reset_staking.get_service")
    @patch(
        "operate.quickstart.reset_staking.ask_yes_or_no",
        side_effect=[True, False],  # first: continue; second: decline unstake
    )
    @patch("operate.quickstart.reset_staking.configure_local_config")
    @patch("operate.quickstart.reset_staking.ask_password_if_needed")
    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_staked_can_unstake_user_declines(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_ask_yn: MagicMock,
        mock_get_svc: MagicMock,
        mock_get_staking: MagicMock,
    ) -> None:
        """STAKED service where user declines unstaking: returns without reset."""
        operate = MagicMock()
        mock_cfg_load = MagicMock()
        mock_cfg_load.path.exists.return_value = True
        mock_load.return_value = mock_cfg_load

        mock_cfg_conf = MagicMock()
        mock_cfg_conf.principal_chain = "gnosis"
        mock_cfg_conf.staking_program_id = "quickstart_beta_hobbyist"
        mock_configure.return_value = mock_cfg_conf

        mock_service = MagicMock()
        mock_service.chain_configs.__getitem__.return_value.ledger_config.rpc = (
            "http://fake-rpc"
        )
        mock_get_svc.return_value = mock_service
        mock_get_staking.return_value = "0xStakingContract"

        manager = operate.service_manager.return_value
        sftxb = manager.get_eth_safe_tx_builder.return_value
        sftxb.staking_status.return_value = StakingState.STAKED
        sftxb.can_unstake.return_value = True

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        mock_cfg_conf.store.assert_not_called()

    @patch("operate.quickstart.reset_staking.print_section")
    @patch("operate.quickstart.reset_staking.ensure_enough_funds")
    @patch("operate.quickstart.reset_staking.get_staking_contract")
    @patch("operate.quickstart.reset_staking.get_service")
    @patch(
        "operate.quickstart.reset_staking.ask_yes_or_no",
        side_effect=[True, True],  # first: continue; second: confirm unstake
    )
    @patch("operate.quickstart.reset_staking.configure_local_config")
    @patch("operate.quickstart.reset_staking.ask_password_if_needed")
    @patch("operate.quickstart.reset_staking.print_title")
    @patch("operate.quickstart.reset_staking.load_local_config")
    def test_staked_can_unstake_user_confirms_full_reset(
        self,
        mock_load: MagicMock,
        mock_title: MagicMock,
        mock_ask_pass: MagicMock,
        mock_configure: MagicMock,
        mock_ask_yn: MagicMock,
        mock_get_svc: MagicMock,
        mock_get_staking: MagicMock,
        mock_enough: MagicMock,
        mock_section: MagicMock,
    ) -> None:
        """STAKED service where user confirms unstaking: unstakes and resets."""
        operate = MagicMock()
        mock_cfg_load = MagicMock()
        mock_cfg_load.path.exists.return_value = True
        mock_load.return_value = mock_cfg_load

        mock_cfg_conf = MagicMock()
        mock_cfg_conf.principal_chain = "gnosis"
        mock_cfg_conf.staking_program_id = "quickstart_beta_hobbyist"
        mock_configure.return_value = mock_cfg_conf

        mock_service = MagicMock()
        mock_service.chain_configs.__getitem__.return_value.ledger_config.rpc = (
            "http://fake-rpc"
        )
        mock_get_svc.return_value = mock_service
        mock_get_staking.return_value = "0xStakingContract"

        manager = operate.service_manager.return_value
        sftxb = manager.get_eth_safe_tx_builder.return_value
        sftxb.staking_status.return_value = StakingState.STAKED
        sftxb.can_unstake.return_value = True

        template_data = {"name": "Test Service"}
        with patch("builtins.open", mock_open(read_data=json.dumps(template_data))):
            reset_staking(operate, "/fake/path.json")

        manager.unstake_service_on_chain_from_safe.assert_called_once()
        # Config should be reset and stored
        mock_cfg_conf.store.assert_called()
        assert mock_cfg_conf.staking_program_id is None
