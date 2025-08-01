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
"""Claim staking rewards."""

import json
import logging
import os
import warnings
from typing import TYPE_CHECKING, cast

from operate.constants import SAFE_WEBAPP_URL
from operate.ledger.profiles import get_staking_contract
from operate.quickstart.run_service import (
    ask_password_if_needed,
    configure_local_config,
    get_service,
    load_local_config,
)
from operate.quickstart.utils import ask_yes_or_no, print_section, print_title


if TYPE_CHECKING:
    from operate.cli import OperateApp

warnings.filterwarnings("ignore", category=UserWarning)


def claim_staking_rewards(operate: "OperateApp", config_path: str) -> None:
    """Claim staking rewards."""
    with open(config_path, "r") as config_file:
        template = json.load(config_file)

    print_section(f"Claim staking rewards for {template['name']}")

    # check if agent was started before
    config = load_local_config(
        operate=operate, service_name=cast(str, template["name"])
    )
    if not config.path.exists():
        print("No previous agent setup found. Exiting.")
        return

    print(
        "This script will claim the OLAS staking rewards "
        "accrued in the current staking contract and transfer them to your service safe."
    )

    if not ask_yes_or_no("Do you want to continue?"):
        print("Cancelled.")
        return

    print("")

    ask_password_if_needed(operate)
    config = configure_local_config(template, operate)
    manager = operate.service_manager()
    service = get_service(manager, template)

    # reload manger and config after setting operate.password
    manager = operate.service_manager()
    config = load_local_config(operate=operate, service_name=cast(str, service.name))
    assert (  # nosec
        config.principal_chain is not None
    ), "Principal chain not set in quickstart config"
    assert config.rpc is not None, "RPC not set in quickstart config"  # nosec
    os.environ["CUSTOM_CHAIN_RPC"] = config.rpc[config.principal_chain]

    chain_config = service.chain_configs[config.principal_chain]
    sftxb = manager.get_eth_safe_tx_builder(
        ledger_config=chain_config.ledger_config,
    )
    staking_contract = get_staking_contract(
        chain=config.principal_chain,
        staking_program_id=config.staking_program_id,
    )
    if not staking_contract or not sftxb.staking_rewards_claimable(
        service_id=chain_config.chain_data.token,
        staking_contract=staking_contract,
    ):
        print("No rewards to claim. Exiting.")
        return

    try:
        tx_hash = manager.claim_on_chain_from_safe(
            service_config_id=service.service_config_id,
            chain=config.principal_chain,
        )
    except RuntimeError as e:
        print(
            "The transaction was reverted. "
            "This may be caused because your service does not have rewards to claim.\n"
        )
        logging.error(e)
        return

    service_safe_address = chain_config.chain_data.multisig
    print_title(f"Claim transaction done. Hash: {tx_hash.hex()}")
    print(f"Claimed staking transferred to your service Safe {service_safe_address}.\n")
    print(f"You may connect to service Safe at {SAFE_WEBAPP_URL}{service_safe_address}")
