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

"""Tests for operate.quickstart.run_service non-interactive params."""

import json
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.constants import NO_STAKING_PROGRAM_ID
from operate.operate_types import (
    ConfigurationTemplate,
    ServiceEnvProvisionType,
    ServiceTemplate,
)
from operate.quickstart.run_service import configure_local_config, run_service


def _make_template(
    home_chain: str = "gnosis",
    chains: t.Optional[t.List[str]] = None,
    user_env_vars: t.Optional[t.Dict[str, t.Dict]] = None,
) -> ServiceTemplate:
    """Build a minimal ServiceTemplate for testing."""
    if chains is None:
        chains = [home_chain]

    configurations = {}
    for chain in chains:
        configurations[chain] = ConfigurationTemplate(
            {
                "staking_program_id": None,
                "nft": "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq",
                "rpc": f"https://rpc.{chain}.example",
                "agent_id": 14,
                "cost_of_bond": 1,
                "fund_requirements": {},
                "fallback_chain_params": None,
            }
        )

    env_variables: t.Dict[str, t.Any] = {
        f"{home_chain.upper()}_LEDGER_RPC": {
            "name": f"{home_chain} ledger RPC",
            "description": "",
            "value": "",
            "provision_type": ServiceEnvProvisionType.COMPUTED,
        },
    }
    if user_env_vars:
        env_variables.update(user_env_vars)

    return ServiceTemplate(
        {
            "name": "Test Agent",
            "hash": "bafybeifhxeoar5hdwilmnzhy6jf664zqp5lgrzi6lpbkc4qmoqrr24ow4q",
            "image": "",
            "description": "Test",
            "service_version": "v0.0.1",
            "agent_release": {
                "is_aea": True,
                "repository": {
                    "owner": "test",
                    "name": "test",
                    "version": "v0.0.1",
                },
            },
            "home_chain": home_chain,
            "configurations": configurations,
            "env_variables": env_variables,
        }
    )


@pytest.fixture
def mock_operate(tmp_path: Path) -> MagicMock:
    """Create a mock OperateApp."""
    operate = MagicMock()
    operate._path = tmp_path / ".operate"
    operate._path.mkdir(parents=True)

    mock_manager = MagicMock()
    mock_manager.get_mech_configs.return_value = MagicMock(
        priority_mech_address="0x" + "0" * 40,
        priority_mech_service_id="1",
    )
    operate.service_manager.return_value = mock_manager
    return operate


def _mock_check_rpc(chain: str, rpc_url: t.Optional[str] = None) -> bool:
    """Mock check_rpc that returns True for any non-None URL."""
    return rpc_url is not None


def _mock_make_ledger_api(*args: t.Any, **kwargs: t.Any) -> MagicMock:
    """Mock make_ledger_api."""
    return MagicMock()


def _mock_get_staking_contract(chain: t.Any, program_id: str) -> t.Optional[str]:
    """Mock get_staking_contract."""
    if program_id == NO_STAKING_PROGRAM_ID:
        return None
    return "0x" + "1" * 40


# Patches common to all configure_local_config tests
_COMMON_PATCHES = {
    "operate.quickstart.run_service.check_rpc": _mock_check_rpc,
    "operate.quickstart.run_service.make_ledger_api": _mock_make_ledger_api,
    "operate.quickstart.run_service.get_staking_contract": _mock_get_staking_contract,
}


def _apply_patches(extra: t.Optional[t.Dict[str, t.Any]] = None):
    """Build a combined context manager for all common patches."""
    patches = dict(_COMMON_PATCHES)
    if extra:
        patches.update(extra)
    # Return list of patch objects
    return [
        patch(target, side_effect if callable(side_effect) else side_effect)
        for target, side_effect in patches.items()
    ]


class TestConfigureLocalConfigRpcOverrides:
    """Tests that rpc_overrides skip RPC prompting."""

    @patch("operate.quickstart.run_service.check_rpc", side_effect=_mock_check_rpc)
    @patch(
        "operate.quickstart.run_service.make_ledger_api",
        side_effect=_mock_make_ledger_api,
    )
    @patch(
        "operate.quickstart.run_service.get_staking_contract",
        side_effect=_mock_get_staking_contract,
    )
    @patch("operate.quickstart.run_service.StakingTokenContract")
    @patch("operate.quickstart.run_service.ask_or_get_from_env")
    def test_rpc_overrides_skip_prompting(
        self,
        mock_ask: MagicMock,
        mock_staking_ctr: MagicMock,
        mock_get_staking: MagicMock,
        mock_ledger: MagicMock,
        mock_check: MagicMock,
        mock_operate: MagicMock,
    ) -> None:
        """When rpc_overrides provides a valid RPC, ask_or_get_from_env is never called for that chain's RPC."""
        template = _make_template(home_chain="gnosis")

        # Pre-set staking so we skip that interactive block too
        config = configure_local_config(
            template,
            mock_operate,
            rpc_overrides={"gnosis": "https://rpc.gnosis.example"},
            staking_program_id=NO_STAKING_PROGRAM_ID,
        )

        # ask_or_get_from_env should NOT have been called for the RPC prompt
        for call_args in mock_ask.call_args_list:
            prompt = call_args[0][0] if call_args[0] else ""
            assert (
                "RPC" not in prompt
            ), f"ask_or_get_from_env was called with an RPC prompt: {prompt}"

        assert config.rpc["gnosis"] == "https://rpc.gnosis.example"

    @patch("operate.quickstart.run_service.check_rpc", side_effect=_mock_check_rpc)
    @patch(
        "operate.quickstart.run_service.make_ledger_api",
        side_effect=_mock_make_ledger_api,
    )
    @patch(
        "operate.quickstart.run_service.get_staking_contract",
        side_effect=_mock_get_staking_contract,
    )
    @patch("operate.quickstart.run_service.StakingTokenContract")
    @patch("operate.quickstart.run_service.ask_or_get_from_env")
    def test_rpc_overrides_multichain(
        self,
        mock_ask: MagicMock,
        mock_staking_ctr: MagicMock,
        mock_get_staking: MagicMock,
        mock_ledger: MagicMock,
        mock_check: MagicMock,
        mock_operate: MagicMock,
    ) -> None:
        """rpc_overrides works for multi-chain templates."""
        template = _make_template(
            home_chain="gnosis",
            chains=["gnosis", "base"],
        )

        config = configure_local_config(
            template,
            mock_operate,
            rpc_overrides={
                "gnosis": "https://rpc.gnosis.example",
                "base": "https://rpc.base.example",
            },
            staking_program_id=NO_STAKING_PROGRAM_ID,
        )

        assert config.rpc["gnosis"] == "https://rpc.gnosis.example"
        assert config.rpc["base"] == "https://rpc.base.example"

        # No RPC prompts
        for call_args in mock_ask.call_args_list:
            prompt = call_args[0][0] if call_args[0] else ""
            assert "RPC" not in prompt


class TestConfigureLocalConfigStakingOverride:
    """Tests that staking_program_id skips staking menu."""

    @patch("operate.quickstart.run_service.check_rpc", side_effect=_mock_check_rpc)
    @patch(
        "operate.quickstart.run_service.make_ledger_api",
        side_effect=_mock_make_ledger_api,
    )
    @patch(
        "operate.quickstart.run_service.get_staking_contract",
        side_effect=_mock_get_staking_contract,
    )
    @patch("operate.quickstart.run_service.StakingTokenContract")
    @patch("operate.quickstart.run_service.print_section")
    @patch("operate.quickstart.run_service.ask_or_get_from_env")
    def test_staking_override_skips_menu(
        self,
        mock_ask: MagicMock,
        mock_print_section: MagicMock,
        mock_staking_ctr: MagicMock,
        mock_get_staking: MagicMock,
        mock_ledger: MagicMock,
        mock_check: MagicMock,
        mock_operate: MagicMock,
    ) -> None:
        """When staking_program_id is provided, the staking selection menu is never shown."""
        template = _make_template(home_chain="gnosis")

        config = configure_local_config(
            template,
            mock_operate,
            rpc_overrides={"gnosis": "https://rpc.gnosis.example"},
            staking_program_id=NO_STAKING_PROGRAM_ID,
        )

        assert config.staking_program_id == NO_STAKING_PROGRAM_ID

        # The staking selection prompt should never appear
        for call_args in mock_print_section.call_args_list:
            text = call_args[0][0] if call_args[0] else ""
            assert (
                "staking program" not in text.lower()
            ), f"Staking menu was shown: {text}"

    @patch("operate.quickstart.run_service.check_rpc", side_effect=_mock_check_rpc)
    @patch(
        "operate.quickstart.run_service.make_ledger_api",
        side_effect=_mock_make_ledger_api,
    )
    @patch(
        "operate.quickstart.run_service.get_staking_contract",
        side_effect=_mock_get_staking_contract,
    )
    @patch("operate.quickstart.run_service.StakingTokenContract")
    @patch("operate.quickstart.run_service.ask_or_get_from_env")
    def test_staking_override_with_custom_id(
        self,
        mock_ask: MagicMock,
        mock_staking_ctr: MagicMock,
        mock_get_staking: MagicMock,
        mock_ledger: MagicMock,
        mock_check: MagicMock,
        mock_operate: MagicMock,
    ) -> None:
        """A custom staking program ID is accepted and stored."""
        template = _make_template(home_chain="gnosis")

        config = configure_local_config(
            template,
            mock_operate,
            rpc_overrides={"gnosis": "https://rpc.gnosis.example"},
            staking_program_id="my_custom_staking",
        )

        assert config.staking_program_id == "my_custom_staking"


class TestConfigureLocalConfigUserProvidedArgs:
    """Tests that user_provided_args skip env var prompting."""

    @patch("operate.quickstart.run_service.check_rpc", side_effect=_mock_check_rpc)
    @patch(
        "operate.quickstart.run_service.make_ledger_api",
        side_effect=_mock_make_ledger_api,
    )
    @patch(
        "operate.quickstart.run_service.get_staking_contract",
        side_effect=_mock_get_staking_contract,
    )
    @patch("operate.quickstart.run_service.StakingTokenContract")
    @patch("operate.quickstart.run_service.ask_or_get_from_env")
    def test_user_provided_args_skip_prompting(
        self,
        mock_ask: MagicMock,
        mock_staking_ctr: MagicMock,
        mock_get_staking: MagicMock,
        mock_ledger: MagicMock,
        mock_check: MagicMock,
        mock_operate: MagicMock,
    ) -> None:
        """When user_provided_args contains a USER env var, that var is not prompted for."""
        template = _make_template(
            home_chain="gnosis",
            user_env_vars={
                "MY_API_KEY": {
                    "name": "My API Key",
                    "description": "API key for the service",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.USER,
                },
            },
        )

        config = configure_local_config(
            template,
            mock_operate,
            rpc_overrides={"gnosis": "https://rpc.gnosis.example"},
            staking_program_id=NO_STAKING_PROGRAM_ID,
            user_provided_args={"MY_API_KEY": "secret123"},
        )

        assert config.user_provided_args["MY_API_KEY"] == "secret123"
        # Template env var should also be updated
        assert template["env_variables"]["MY_API_KEY"]["value"] == "secret123"

        # ask_or_get_from_env should NOT have been called for MY_API_KEY
        for call_args in mock_ask.call_args_list:
            prompt = call_args[0][0] if call_args[0] else ""
            assert (
                "My API Key" not in prompt
            ), f"ask_or_get_from_env was called for MY_API_KEY: {prompt}"

    @patch("operate.quickstart.run_service.check_rpc", side_effect=_mock_check_rpc)
    @patch(
        "operate.quickstart.run_service.make_ledger_api",
        side_effect=_mock_make_ledger_api,
    )
    @patch(
        "operate.quickstart.run_service.get_staking_contract",
        side_effect=_mock_get_staking_contract,
    )
    @patch("operate.quickstart.run_service.StakingTokenContract")
    @patch("operate.quickstart.run_service.ask_or_get_from_env")
    def test_user_provided_args_partial_override(
        self,
        mock_ask: MagicMock,
        mock_staking_ctr: MagicMock,
        mock_get_staking: MagicMock,
        mock_ledger: MagicMock,
        mock_check: MagicMock,
        mock_operate: MagicMock,
    ) -> None:
        """When only some USER vars are overridden, the rest are still prompted."""
        mock_ask.return_value = "prompted_value"

        template = _make_template(
            home_chain="gnosis",
            user_env_vars={
                "VAR_A": {
                    "name": "Variable A",
                    "description": "First var",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.USER,
                },
                "VAR_B": {
                    "name": "Variable B",
                    "description": "Second var",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.USER,
                },
            },
        )

        config = configure_local_config(
            template,
            mock_operate,
            rpc_overrides={"gnosis": "https://rpc.gnosis.example"},
            staking_program_id=NO_STAKING_PROGRAM_ID,
            user_provided_args={"VAR_A": "override_a"},
        )

        # VAR_A should use the override
        assert config.user_provided_args["VAR_A"] == "override_a"
        # VAR_B should have been prompted (mock returns "prompted_value")
        assert config.user_provided_args["VAR_B"] == "prompted_value"


class TestConfigureLocalConfigNoOverrides:
    """Tests that without overrides, behavior is unchanged (backward compat)."""

    @patch("operate.quickstart.run_service.check_rpc", side_effect=_mock_check_rpc)
    @patch(
        "operate.quickstart.run_service.make_ledger_api",
        side_effect=_mock_make_ledger_api,
    )
    @patch(
        "operate.quickstart.run_service.get_staking_contract",
        side_effect=_mock_get_staking_contract,
    )
    @patch("operate.quickstart.run_service.StakingTokenContract")
    @patch("operate.quickstart.run_service.ask_or_get_from_env")
    def test_none_overrides_preserve_interactive_behavior(
        self,
        mock_ask: MagicMock,
        mock_staking_ctr: MagicMock,
        mock_get_staking: MagicMock,
        mock_ledger: MagicMock,
        mock_check: MagicMock,
        mock_operate: MagicMock,
    ) -> None:
        """With all overrides as None, configure_local_config prompts for RPC (at minimum)."""
        # check_rpc returns False first (no cached RPC), then True after prompting
        mock_check.side_effect = [False, True]
        mock_ask.return_value = "https://rpc.gnosis.prompted"

        template = _make_template(home_chain="gnosis")

        # We need staking_program_id to avoid the staking menu (too complex to mock fully)
        config = configure_local_config(
            template,
            mock_operate,
            staking_program_id=NO_STAKING_PROGRAM_ID,
        )

        # RPC should have been prompted since no override was given
        rpc_prompts = [
            call_args
            for call_args in mock_ask.call_args_list
            if "RPC" in (call_args[0][0] if call_args[0] else "")
        ]
        assert len(rpc_prompts) > 0, "Expected an RPC prompt but none occurred"
        assert config.rpc["gnosis"] == "https://rpc.gnosis.prompted"


class TestRunServiceDockerParam:
    """Tests for the use_docker parameter in run_service."""

    def test_use_docker_false_sets_no_docker(
        self,
        mock_operate: MagicMock,
        tmp_path: Path,
    ) -> None:
        """use_docker=False means deploy_service_locally gets use_docker=False."""
        template = _make_template(home_chain="gnosis")
        config_path = tmp_path / "template.json"
        config_path.write_text(json.dumps(dict(template)))

        mock_manager = MagicMock()
        mock_manager.get_mech_configs.return_value = MagicMock(
            priority_mech_address="0x" + "0" * 40,
            priority_mech_service_id="1",
        )
        mock_operate.service_manager.return_value = mock_manager

        with (
            patch(
                "operate.quickstart.run_service.configure_local_config"
            ) as mock_config,
            patch("operate.quickstart.run_service.ask_password_if_needed"),
            patch("operate.quickstart.run_service._maybe_create_master_eoa"),
            patch("operate.quickstart.run_service.get_service") as mock_get_svc,
            patch("operate.quickstart.run_service.load_local_config") as mock_load,
            patch("operate.quickstart.run_service.ensure_enough_funds"),
            patch("operate.quickstart.run_service.print_title"),
            patch("operate.quickstart.run_service.print_section"),
            patch("operate.quickstart.run_service.print_box"),
        ):
            mock_config.return_value = MagicMock(principal_chain="gnosis")
            mock_service = MagicMock()
            mock_service.service_config_id = "test-id"
            mock_service.name = "Test Agent"
            mock_get_svc.return_value = mock_service
            mock_load.return_value = MagicMock(principal_chain="gnosis")

            run_service(
                operate=mock_operate,
                config_path=str(config_path),
                use_docker=False,
            )

            # Verify deploy_service_locally was called with use_docker=False
            deploy_call = mock_manager.deploy_service_locally
            assert deploy_call.called
            call_kwargs = deploy_call.call_args[1]
            assert call_kwargs["use_docker"] is False
            assert call_kwargs["use_kubernetes"] is True  # not use_docker

    def test_use_docker_none_with_binary(
        self,
        mock_operate: MagicMock,
        tmp_path: Path,
    ) -> None:
        """use_docker=None + use_binary=True means use_docker=False, use_k8s=False."""
        template = _make_template(home_chain="gnosis")
        config_path = tmp_path / "template.json"
        config_path.write_text(json.dumps(dict(template)))

        mock_manager = MagicMock()
        mock_manager.get_mech_configs.return_value = MagicMock(
            priority_mech_address="0x" + "0" * 40,
            priority_mech_service_id="1",
        )
        mock_operate.service_manager.return_value = mock_manager

        with (
            patch(
                "operate.quickstart.run_service.configure_local_config"
            ) as mock_config,
            patch("operate.quickstart.run_service.ask_password_if_needed"),
            patch("operate.quickstart.run_service._maybe_create_master_eoa"),
            patch("operate.quickstart.run_service.get_service") as mock_get_svc,
            patch("operate.quickstart.run_service.load_local_config") as mock_load,
            patch("operate.quickstart.run_service.ensure_enough_funds"),
            patch("operate.quickstart.run_service.print_title"),
            patch("operate.quickstart.run_service.print_section"),
            patch("operate.quickstart.run_service.print_box"),
        ):
            mock_config.return_value = MagicMock(principal_chain="gnosis")
            mock_service = MagicMock()
            mock_service.service_config_id = "test-id"
            mock_service.name = "Test Agent"
            mock_get_svc.return_value = mock_service
            mock_load.return_value = MagicMock(principal_chain="gnosis")

            run_service(
                operate=mock_operate,
                config_path=str(config_path),
                use_binary=True,
                use_docker=None,
            )

            deploy_call = mock_manager.deploy_service_locally
            assert deploy_call.called
            call_kwargs = deploy_call.call_args[1]
            assert call_kwargs["use_docker"] is False
            assert call_kwargs["use_kubernetes"] is False


class TestRunServiceThreadsParams:
    """Tests that run_service threads new params to configure_local_config."""

    def test_params_threaded_to_configure(
        self,
        mock_operate: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run_service passes rpc_overrides, staking_program_id, user_provided_args to configure_local_config."""
        template = _make_template(home_chain="gnosis")
        config_path = tmp_path / "template.json"
        config_path.write_text(json.dumps(dict(template)))

        mock_manager = MagicMock()
        mock_manager.get_mech_configs.return_value = MagicMock(
            priority_mech_address="0x" + "0" * 40,
            priority_mech_service_id="1",
        )
        mock_operate.service_manager.return_value = mock_manager

        with (
            patch(
                "operate.quickstart.run_service.configure_local_config"
            ) as mock_config,
            patch("operate.quickstart.run_service.ask_password_if_needed"),
            patch("operate.quickstart.run_service._maybe_create_master_eoa"),
            patch("operate.quickstart.run_service.get_service") as mock_get_svc,
            patch("operate.quickstart.run_service.load_local_config") as mock_load,
            patch("operate.quickstart.run_service.ensure_enough_funds"),
            patch("operate.quickstart.run_service.print_title"),
            patch("operate.quickstart.run_service.print_section"),
            patch("operate.quickstart.run_service.print_box"),
        ):
            mock_config.return_value = MagicMock(principal_chain="gnosis")
            mock_service = MagicMock()
            mock_service.service_config_id = "test-id"
            mock_service.name = "Test Agent"
            mock_get_svc.return_value = mock_service
            mock_load.return_value = MagicMock(principal_chain="gnosis")

            rpc = {"gnosis": "https://rpc.gnosis.example"}
            env_args = {"MY_KEY": "my_value"}

            run_service(
                operate=mock_operate,
                config_path=str(config_path),
                rpc_overrides=rpc,
                staking_program_id="no_staking",
                user_provided_args=env_args,
            )

            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["rpc_overrides"] == rpc
            assert call_kwargs["staking_program_id"] == "no_staking"
            assert call_kwargs["user_provided_args"] == env_args
