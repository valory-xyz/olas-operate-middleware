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
"""Reset staking."""

import json
import os
from typing import TYPE_CHECKING, cast

from operate.constants import NO_STAKING_PROGRAM_ID
from operate.ledger.profiles import get_staking_contract
from operate.quickstart.run_service import (
    CUSTOM_PROGRAM_ID,
    ask_password_if_needed,
    configure_local_config,
    ensure_enough_funds,
    get_service,
    load_local_config,
)
from operate.quickstart.utils import ask_yes_or_no, print_section, print_title
from operate.services.protocol import StakingState


if TYPE_CHECKING:
    from operate.cli import OperateApp


def reset_staking(operate: "OperateApp", config_path: str) -> None:
    """Reset staking."""
    with open(config_path, "r") as config_file:
        template = json.load(config_file)

    print_title("Reset your staking program preference")

    # check if agent was started before
    config = load_local_config(
        operate=operate, service_name=cast(str, template["name"])
    )
    if not config.path.exists():
        print("No previous agent setup found. Exiting.")
        return

    ask_password_if_needed(operate)
    config = configure_local_config(template, operate)
    assert (  # nosec
        config.principal_chain is not None
    ), "Principal chain not set in quickstart config"

    if not config.staking_program_id:
        print("No staking program preference found. Exiting.")
        return

    print(
        f"Your current staking program preference is set to '{config.staking_program_id}'.\n"
    )
    print(
        "You can reset your preference. "
        "However, your agent might not be able to switch between staking contracts "
        "until it has been staked for a minimum staking period in the current program.\n"
    )

    if not ask_yes_or_no(
        "Please, ensure that your service is stopped (./stop_service.sh) before proceeding. "
        "Do you want to continue?"
    ):
        print("Cancelled.")
        return

    manager = operate.service_manager()
    service = get_service(manager, template)

    # Check if service can be unstaked from current program
    os.environ["CUSTOM_CHAIN_RPC"] = service.chain_configs[
        config.principal_chain
    ].ledger_config.rpc
    sftxb = manager.get_eth_safe_tx_builder(
        ledger_config=service.chain_configs[config.principal_chain].ledger_config
    )
    service_id = service.chain_configs[config.principal_chain].chain_data.token
    staking_contract = get_staking_contract(
        chain=config.principal_chain,
        staking_program_id=config.staking_program_id,
    )

    if (
        config.staking_program_id is not None
        and config.staking_program_id not in (NO_STAKING_PROGRAM_ID, CUSTOM_PROGRAM_ID)
        and sftxb.staking_status(
            service_id=service_id, staking_contract=staking_contract
        )
        in (StakingState.STAKED, StakingState.EVICTED)
    ):
        if not sftxb.can_unstake(
            service_id=service_id,
            staking_contract=staking_contract,
        ):
            print_section("Cannot Reset Staking Preference")
            print(
                "Your service cannot be unstaked at this time. This could be due to:\n"
                "- Minimum staking period not elapsed\n"
                "- Available rewards pending\n\n"
                "Please try again once the staking conditions allow unstaking."
            )
            return

        if not ask_yes_or_no(
            "Service can be unstaked. Would you like to proceed with unstaking and reset?"
        ):
            print("Cancelled.")
            return

        # Unstake the service
        ensure_enough_funds(operate, service)
        manager.unstake_service_on_chain_from_safe(
            service_config_id=service.service_config_id,
            chain=config.principal_chain,
            staking_program_id=config.staking_program_id,
        )
        print_section("Service has been unstaked successfully")

    # Update local config and service template
    config.staking_program_id = None
    config.store()
    config = configure_local_config(template, operate)
    service = get_service(manager, template)
    manager.update(
        service_config_id=service.service_config_id,
        service_template=template,
    )
    print("\nStaking preference has been reset successfully.")
