# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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
"""Reset configurations."""

import json
from typing import Callable, Optional, TYPE_CHECKING, cast

from operate.quickstart.run_service import load_local_config
from operate.quickstart.utils import (
    ask_or_get_from_env,
    ask_yes_or_no,
    check_rpc,
    print_section,
    print_title,
)


if TYPE_CHECKING:
    from operate.cli import OperateApp


def _ask_to_change(
    name: str,
    env_var: str,
    old_value: str,
    hidden: bool = False,
    validator: Callable[[Optional[str]], bool] = lambda x: False if x is None else True,
) -> str:
    """Ask user if they want to change a configuration value."""
    old_value_str = old_value
    if hidden:
        if len(old_value_str) < 4:
            old_value_str = "*" * len(old_value_str)
        else:
            old_value_str = "*" * len(old_value_str[:-4]) + old_value_str[-4:]

    print(f"\nCurrent '{name}' is set to: {old_value_str}")
    if ask_yes_or_no(f"Do you want to change the '{name}'?"):
        new_value = None
        while not validator(new_value):
            new_value = ask_or_get_from_env(
                prompt=f"Enter new value for '{name}' {'[hidden]' if hidden else ''}: ",
                env_var_name=env_var,
                is_pass=hidden,
            )

        return str(new_value)

    return old_value


def reset_configs(operate: "OperateApp", config_path: str) -> None:
    """Reset configurations."""
    with open(config_path, "r") as config_file:
        template = json.load(config_file)

    print_title(f"Reset your {template['name']} configurations")

    # check if agent was started before
    config = load_local_config(
        operate=operate, service_name=cast(str, template["name"])
    )
    if not config.path.exists():
        print("No previous agent setup found. Exiting.")
        return

    if config.rpc is None:
        config.rpc = {}

    for chain_name in config.rpc:
        config.rpc[chain_name] = _ask_to_change(
            name=f"{chain_name.capitalize()} RPC URL",
            env_var=f"{chain_name.upper()}_LEDGER_RPC",
            old_value=config.rpc[chain_name],
            hidden=True,
            validator=check_rpc,
        )

    if config.user_provided_args is None:
        config.user_provided_args = {}

    for env_var in config.user_provided_args:
        config.user_provided_args[env_var] = _ask_to_change(
            name=env_var,
            env_var=env_var,
            old_value=config.user_provided_args[env_var],
        )

    config.store()
    print_section("Configurations updated")
