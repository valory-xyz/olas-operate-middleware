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
"""Agent Quickstart script."""

import json
import os
import shutil
import textwrap
import time
import typing as t
import warnings
from http import HTTPStatus

import requests
from aea.crypto.registries import make_ledger_api
from aea_ledger_ethereum import LedgerApi
from halo import Halo  # type: ignore[import]
from web3.exceptions import Web3Exception

from operate.account.user import UserAccount
from operate.constants import (
    IPFS_ADDRESS,
    NO_STAKING_PROGRAM_ID,
    OPERATE_HOME,
    USER_JSON,
)
from operate.data import DATA_DIR
from operate.data.contracts.staking_token.contract import StakingTokenContract
from operate.ledger.profiles import STAKING, get_staking_contract
from operate.operate_types import (
    Chain,
    LedgerType,
    ServiceEnvProvisionType,
    ServiceTemplate,
)
from operate.quickstart.utils import (
    CHAIN_TO_METADATA,
    QuickstartConfig,
    ask_or_get_from_env,
    check_rpc,
    print_box,
    print_section,
    print_title,
    wei_to_token,
)
from operate.services.manage import ServiceManager
from operate.services.service import Service
from operate.utils.gnosis import get_asset_balance
from operate.wallet.master import MasterWallet


warnings.filterwarnings("ignore", category=UserWarning)


if t.TYPE_CHECKING:
    from operate.cli import OperateApp

NO_STAKING_PROGRAM_METADATA = {
    "name": "No staking",
    "description": "Your agent will still work as expected, but it will not be staked within any staking program.",
}
CUSTOM_PROGRAM_ID = "custom_staking"
QS_STAKING_PROGRAMS: t.Dict[Chain, t.Dict[str, str]] = {
    Chain.GNOSIS: {
        "quickstart_beta_hobbyist": "trader",
        "quickstart_beta_hobbyist_2": "trader",
        "quickstart_beta_expert": "trader",
        "quickstart_beta_expert_2": "trader",
        "quickstart_beta_expert_3": "trader",
        "quickstart_beta_expert_4": "trader",
        "quickstart_beta_expert_5": "trader",
        "quickstart_beta_expert_6": "trader",
        "quickstart_beta_expert_7": "trader",
        "quickstart_beta_expert_8": "trader",
        "quickstart_beta_expert_9": "trader",
        "quickstart_beta_expert_10": "trader",
        "quickstart_beta_expert_11": "trader",
        "quickstart_beta_expert_12": "trader",
        "quickstart_beta_expert_15_mech_marketplace": "trader",
        "quickstart_beta_expert_16_mech_marketplace": "trader",
        "quickstart_beta_expert_17_mech_marketplace": "trader",
        "quickstart_beta_expert_18_mech_marketplace": "trader",
        "quickstart_beta_mech_marketplace_expert_3": "trader",
        "quickstart_beta_mech_marketplace_expert_4": "trader",
        "quickstart_beta_mech_marketplace_expert_5": "trader",
        "quickstart_beta_mech_marketplace_expert_6": "trader",
        "quickstart_beta_mech_marketplace_expert_7": "trader",
        "quickstart_beta_mech_marketplace_expert_8": "trader",
        "mech_marketplace": "mech",
        "marketplace_supply_alpha": "mech",
    },
    Chain.OPTIMISM: {
        "optimus_alpha_2": "optimus",
        "optimus_alpha_3": "optimus",
        "optimus_alpha_4": "optimus",
    },
    Chain.ETHEREUM: {},
    Chain.BASE: {
        "meme_base_alpha_2": "memeooorr",
        "marketplace_supply_alpha": "mech",
        "agents_fun_1": "memeooorr",
        "agents_fun_2": "memeooorr",
        "agents_fun_3": "memeooorr",
    },
    Chain.CELO: {},
    Chain.MODE: {
        "optimus_alpha": "modius",
    },
}


def ask_confirm_password() -> str:
    """Ask for password confirmation."""
    while True:
        password = ask_or_get_from_env(
            "Please input your password (or press enter): ", True, "OPERATE_PASSWORD"
        )
        confirm_password = ask_or_get_from_env(
            "Please confirm your password: ", True, "OPERATE_PASSWORD"
        )

        if password == confirm_password:
            return password
        else:
            print("Passwords do not match!")


def load_local_config(operate: "OperateApp", service_name: str) -> QuickstartConfig:
    """Load the local quickstart configuration."""
    old_path = OPERATE_HOME / "local_config.json"
    if old_path.exists():  # Migrate to new naming scheme
        config = t.cast(QuickstartConfig, QuickstartConfig.load(old_path))
        service_manager = operate.service_manager()
        services = service_manager.json
        if config.staking_program_id == NO_STAKING_PROGRAM_ID:
            for service in services:
                if service["name"] == service_name:
                    config.path = (
                        config.path.parent / f"{service_name}-quickstart-config.json"
                    )
                    shutil.move(old_path, config.path)
                    break
        else:
            for staking_program, _agent_keyword in QS_STAKING_PROGRAMS[
                Chain.from_string(config.principal_chain)
            ].items():
                if staking_program == config.staking_program_id:
                    break
            else:
                raise ValueError(
                    f"Staking program {config.staking_program_id} not found in {QS_STAKING_PROGRAMS[Chain.from_string(config.principal_chain)].keys()}.\n"
                    "Please resolve manually!"
                )

            for service in services:
                if _agent_keyword in service["name"].lower():
                    config.path = (
                        config.path.parent / f"{service['name']}-quickstart-config.json"
                    )
                    shutil.move(old_path, config.path)
                    break

    for qs_config in OPERATE_HOME.glob("*-quickstart-config.json"):
        if f"{service_name}-quickstart-config.json" == qs_config.name:
            config = t.cast(QuickstartConfig, QuickstartConfig.load(qs_config))
            break
    else:
        config = QuickstartConfig(
            OPERATE_HOME / f"{service_name}-quickstart-config.json"
        )

    return config


def configure_local_config(
    template: ServiceTemplate, operate: "OperateApp"
) -> QuickstartConfig:
    """Configure local quickstart configuration."""
    config = load_local_config(operate=operate, service_name=template["name"])

    if config.rpc is None:
        config.rpc = {}

    for chain in template["configurations"]:
        while not check_rpc(config.rpc.get(chain)):
            config.rpc[chain] = ask_or_get_from_env(
                f"Enter a {CHAIN_TO_METADATA[chain]['name']} RPC that supports eth_newFilter [hidden input]: ",
                True,
                f"{chain.upper()}_LEDGER_RPC",
            )
        os.environ[f"{chain.upper()}_LEDGER_RPC"] = config.rpc[chain]

    config.principal_chain = template["home_chain"]

    home_chain = Chain.from_string(config.principal_chain)
    staking_ctr = t.cast(
        StakingTokenContract,
        StakingTokenContract.from_dir(
            directory=str(DATA_DIR / "contracts" / "staking_token")
        ),
    )
    ledger_api = make_ledger_api(
        LedgerType.ETHEREUM.lower(),
        address=config.rpc[config.principal_chain],  # type: ignore[index]
        chain_id=home_chain.id,
    )

    if config.staking_program_id is None:
        print_section("Please, select your staking program preference")
        available_choices = {}
        ids = (
            [NO_STAKING_PROGRAM_ID]
            + [
                id
                for id in STAKING[home_chain]
                if id in QS_STAKING_PROGRAMS[home_chain]
                and QS_STAKING_PROGRAMS[home_chain][id] in template["name"].lower()
            ]
            + [CUSTOM_PROGRAM_ID]
        )

        for index, program_id in enumerate(ids):
            if program_id == NO_STAKING_PROGRAM_ID:
                metadata = NO_STAKING_PROGRAM_METADATA
            elif program_id == CUSTOM_PROGRAM_ID:
                metadata = {
                    "name": "Custom Staking contract",
                    "description": "If you choose this option, you will be asked to provide the staking contract address.",
                }
            else:
                instance = staking_ctr.get_instance(
                    ledger_api=ledger_api,
                    contract_address=STAKING[home_chain][program_id],
                )
                try:
                    metadata_hash = instance.functions.metadataHash().call().hex()
                    ipfs_address = IPFS_ADDRESS.format(hash=metadata_hash)
                    response = requests.get(ipfs_address)
                    if response.status_code != HTTPStatus.OK:
                        raise requests.RequestException(
                            f"Failed to fetch data from {ipfs_address}: {response.status_code}"
                        )
                    metadata = response.json()
                except (Web3Exception, requests.RequestException):
                    metadata = {
                        "name": program_id,
                        "description": program_id,
                        "available_staking_slots": "?",
                    }

                # Add staking slots count to successful response
                try:
                    max_services = instance.functions.maxNumServices().call()
                    current_services = instance.functions.getServiceIds().call()
                    metadata["available_staking_slots"] = max_services - len(
                        current_services
                    )
                except Web3Exception:
                    metadata["available_staking_slots"] = "?"

            name = metadata["name"]
            description = metadata["description"]
            if "available_staking_slots" in metadata:
                available_slots_str = (
                    f"(available slots : {metadata['available_staking_slots']})"
                )
            else:
                available_slots_str = ""

            wrapped_description = textwrap.fill(
                description, width=80, initial_indent="   ", subsequent_indent="   "
            )
            print(
                f"{index + 1}) {name}\t{available_slots_str}\n{wrapped_description}\n"
            )
            if available_slots_str or program_id in (
                NO_STAKING_PROGRAM_ID,
                CUSTOM_PROGRAM_ID,
            ):
                available_choices[index + 1] = {
                    "program_id": program_id,
                    "slots": available_slots_str,
                    "name": name,
                }

        while True:
            try:
                input_value = ask_or_get_from_env(
                    f"Enter your choice (1 - {len(ids)}): ", False, "STAKING_PROGRAM"
                )
                try:
                    choice = int(input_value)
                    if choice not in available_choices:
                        print("\nPlease select a program with available slots:")
                        for idx, prog in available_choices.items():
                            print(f"{idx}) {prog['name']} : {prog['slots']}")
                        continue
                    selected_program = available_choices[choice]
                    config.staking_program_id = selected_program["program_id"]
                    print(f"Selected staking program: {selected_program['name']}")
                    break
                except ValueError:
                    if input_value in ids:
                        config.staking_program_id = input_value
                        break
                    else:
                        raise ValueError(f"STAKING_PROGRAM must be one of {ids}")
            except Exception as e:
                print(f"Error in getting input: {str(e)}")
                raise

        if config.staking_program_id == CUSTOM_PROGRAM_ID:
            while True:
                try:
                    config.staking_program_id = ask_or_get_from_env(
                        "Enter the staking contract address: ",
                        False,
                        "STAKING_CONTRACT_ADDRESS",
                    )
                    instance = staking_ctr.get_instance(
                        ledger_api=ledger_api,
                        contract_address=config.staking_program_id,
                    )
                    max_services = instance.functions.maxNumServices().call()
                    current_services = instance.functions.getServiceIds().call()
                    available_slots = max_services - len(current_services)
                    if available_slots > 0:
                        print(f"Found {available_slots} available staking slots.")
                        break
                    else:
                        print(
                            "No available staking slots found. Please enter another address."
                        )
                except Exception:
                    print("This address is not a valid staking contract address.")

    # set chain configs in the service template
    for chain in template["configurations"]:
        if chain == config.principal_chain:
            staking_contract_address = get_staking_contract(
                chain, config.staking_program_id
            )
            if staking_contract_address is None:
                min_staking_deposit = 1
            else:
                instance = staking_ctr.get_instance(
                    ledger_api=ledger_api,
                    contract_address=staking_contract_address,
                )
                min_staking_deposit = int(instance.functions.minStakingDeposit().call())

            template["configurations"][chain] |= {
                "staking_program_id": config.staking_program_id,
                "rpc": config.rpc[chain],
                "cost_of_bond": min_staking_deposit,
            }
        else:
            template["configurations"][chain] |= {
                "staking_program_id": NO_STAKING_PROGRAM_ID,
                "rpc": config.rpc[chain],
                "cost_of_bond": 1,
            }

    if config.user_provided_args is None:
        config.user_provided_args = {}

    if any(
        (
            env_var_data["provision_type"] == ServiceEnvProvisionType.USER
            and env_var_name not in config.user_provided_args
        )
        for env_var_name, env_var_data in template["env_variables"].items()
    ):
        print_section("Please enter the arguments that will be used by the service.")

    service_manager = operate.service_manager()
    mech_configs = service_manager.get_mech_configs(
        chain=config.principal_chain,
        ledger_api=ledger_api,
        staking_program_id=config.staking_program_id,
    )

    for env_var_name, env_var_data in template["env_variables"].items():
        if env_var_data["provision_type"] == ServiceEnvProvisionType.USER:
            # PRIORITY_MECH_ADDRESS and PRIORITY_MECH_SERVICE_ID are given dynamic default values
            if env_var_name == "PRIORITY_MECH_ADDRESS":
                env_var_data["value"] = mech_configs.priority_mech_address
                if (
                    env_var_name in config.user_provided_args
                    and env_var_data["value"] != config.user_provided_args[env_var_name]
                ):
                    del config.user_provided_args[env_var_name]

            if env_var_name == "PRIORITY_MECH_SERVICE_ID":
                env_var_data["value"] = mech_configs.priority_mech_service_id
                if (
                    env_var_name in config.user_provided_args
                    and env_var_data["value"] != config.user_provided_args[env_var_name]
                ):
                    del config.user_provided_args[env_var_name]

            if env_var_name not in config.user_provided_args:
                print(f"Description: {env_var_data['description']}")
                if env_var_data["value"] is not None and env_var_data["value"] != "":
                    print(f"Default: {env_var_data['value']}")

                user_provided_arg = ask_or_get_from_env(
                    f"Please enter {env_var_data['name']}: ", False, env_var_name
                )
                config.user_provided_args[env_var_name] = env_var_data["value"]
                if user_provided_arg:
                    config.user_provided_args[env_var_name] = user_provided_arg

                print()

            template["env_variables"][env_var_name][
                "value"
            ] = config.user_provided_args[env_var_name]

        # TODO: Handle it in a more generic way
        if (
            template["env_variables"][env_var_name]["provision_type"]
            == ServiceEnvProvisionType.COMPUTED
            and "SUBGRAPH_API_KEY" in config.user_provided_args
            and "{SUBGRAPH_API_KEY}" in template["env_variables"][env_var_name]["value"]
        ):
            template["env_variables"][env_var_name]["value"] = template[
                "env_variables"
            ][env_var_name]["value"].format(
                SUBGRAPH_API_KEY=config.user_provided_args["SUBGRAPH_API_KEY"],
            )

    config.store()
    return config


def ask_password_if_needed(operate: "OperateApp") -> None:
    """Ask password if needed."""
    if operate.user_account is None:
        print_section("Set up local user account")
        print("Creating a new local user account...")
        password = ask_confirm_password()
        UserAccount.new(
            password=password,
            path=operate._path / USER_JSON,
        )
    else:
        _password = None
        while _password is None:
            _password = ask_or_get_from_env(
                "\nEnter local user account password [hidden input]: ",
                True,
                "OPERATE_PASSWORD",
            )
            if operate.user_account.is_valid(password=_password):
                break
            _password = None
            print("Invalid password!")

        password = _password

    operate.password = password


def get_service(manager: ServiceManager, template: ServiceTemplate) -> Service:
    """Get service."""
    for service in manager.json:
        if service["name"] == template["name"]:
            old_hash = service["hash"]
            if old_hash == template["hash"]:
                print(f'Loading service {template["hash"]}')
                service = manager.load(
                    service_config_id=service["service_config_id"],
                )
            else:
                print(f"Updating service from {old_hash} to " + template["hash"])
                service = manager.update(
                    service_config_id=service["service_config_id"],
                    service_template=template,
                )

            service.env_variables = template["env_variables"]
            service.update_user_params_from_template(service_template=template)
            service.store()
            break
    else:
        print(f'Creating service {template["hash"]}')
        service = manager.load_or_create(
            hash=template["hash"],
            service_template=template,
        )

    return service


def ask_funds_in_address(
    ledger_api: LedgerApi,
    required_balance: int,
    asset_address: str,
    recipient_name: str,
    recipient_address: str,
    chain: str,
) -> None:
    """Ask for funds in address."""
    if required_balance == 0:
        return

    current_balance = get_asset_balance(ledger_api, asset_address, recipient_address)
    print(
        f"[{chain}] Please transfer at least {wei_to_token(required_balance, chain, asset_address)} "
        f"to the {recipient_name} {recipient_address} "
    )
    spinner = Halo(
        text=f"[{chain}] Waiting for at least {wei_to_token(required_balance, chain, asset_address)}...",
        spinner="dots",
    )
    spinner.start()

    while True:
        time.sleep(1)
        updated_balance = get_asset_balance(
            ledger_api, asset_address, recipient_address
        )
        if updated_balance >= current_balance + required_balance:
            break

        remaining_requirement = current_balance + required_balance - updated_balance
        spinner.text = f"[{chain}] Waiting for at least {wei_to_token(remaining_requirement, chain, asset_address)}..."

    spinner.succeed(
        f"[{chain}] {recipient_name} updated balance: {wei_to_token(updated_balance, chain, asset_address)}."
    )


def _ask_funds_from_requirements(
    manager: ServiceManager,
    wallet: MasterWallet,
    service: Service,
) -> bool:
    """Ask for funds from requirements."""
    spinner = Halo(text="Calculating funds requirements...", spinner="dots")
    spinner.start()
    requirements = manager.refill_requirements(
        service_config_id=service.service_config_id
    )
    spinner.stop()

    wallet_names = (
        {
            wallet.crypto.address: "Master EOA",
            "master_safe": "Master Safe",
            "service_safe": "Service Safe",
        }
        | {safe_address: "Master Safe" for safe_address in wallet.safes.values()}
        | {
            chain_config.chain_data.multisig: "Service Safe"
            for chain_config in service.chain_configs.values()
        }
        | {address: "Agent EOA" for address in service.agent_addresses}
    )

    if not requirements["is_refill_required"] and requirements["allow_start_agent"]:
        for chain_name, balances in requirements["balances"].items():
            ledger_api = wallet.ledger_api(
                chain=Chain(chain_name),
                rpc=service.chain_configs[chain_name].ledger_config.rpc,
            )
            for wallet_address, asset_balances in balances.items():
                for asset_address, balance in asset_balances.items():
                    print(
                        f"[{chain_name}] {wallet_names[wallet_address]} has {wei_to_token(balance, chain_name, asset_address)}"
                    )

        return True

    for chain_name, chain_requirements in requirements["refill_requirements"].items():
        chain = Chain(chain_name)
        ledger_api = wallet.ledger_api(
            chain=chain,
            rpc=service.chain_configs[chain_name].ledger_config.rpc,
        )
        for wallet_address, requirements in chain_requirements.items():
            if wallet_address in ("master_safe", "service_safe"):
                continue  # we can't ask funds in placeholder addresses

            for asset_address, requirement in requirements.items():
                ask_funds_in_address(
                    ledger_api=ledger_api,
                    chain=chain_name,
                    asset_address=asset_address,
                    required_balance=requirement,
                    recipient_address=wallet_address,
                    recipient_name=wallet_names[wallet_address],
                )

    return False


def _maybe_create_master_eoa(operate: "OperateApp") -> None:
    """Maybe create the Master EOA."""
    if not operate.wallet_manager.exists(ledger_type=LedgerType.ETHEREUM):
        print("Creating the Master EOA...")
        wallet, mnemonic = operate.wallet_manager.create(
            ledger_type=LedgerType.ETHEREUM
        )
        wallet.password = operate.password
        print_box(
            f"Please save the mnemonic phrase for the Master EOA:\n{', '.join(mnemonic)}",
            0,
            "-",
        )
        ask_or_get_from_env(
            "Press enter to continue...", False, "CONTINUE", raise_if_missing=False
        )


def ensure_enough_funds(operate: "OperateApp", service: Service) -> None:
    """Ensure enough funds."""
    _maybe_create_master_eoa(operate)
    wallet = operate.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)
    manager = operate.service_manager()

    backup_owner = None
    while not _ask_funds_from_requirements(manager, wallet, service):
        for chain_name, chain_config in service.chain_configs.items():
            chain = Chain.from_string(chain_name)
            if wallet.safes.get(chain) is None:
                print(f"[{chain_name}] Creating Master Safe")
                if backup_owner is None:
                    backup_owner = ask_or_get_from_env(
                        "Please input your backup owner (leave empty to skip): ",
                        False,
                        "BACKUP_OWNER",
                        raise_if_missing=False,
                    )

                wallet.create_safe(
                    chain=chain,
                    rpc=chain_config.ledger_config.rpc,
                    backup_owner=None if backup_owner == "" else backup_owner,
                )


def run_service(
    operate: "OperateApp",
    config_path: str,
    build_only: bool = False,
    skip_dependency_check: bool = False,
) -> None:
    """Run service."""

    with open(config_path, "r") as config_file:
        template = json.load(config_file)

    print_title(f"{template['name']} quickstart")

    ask_password_if_needed(operate)
    _maybe_create_master_eoa(operate)

    config = configure_local_config(template, operate)
    manager = operate.service_manager()
    service = get_service(manager, template)

    # reload manger and config after setting operate.password
    manager = operate.service_manager(skip_dependency_check=skip_dependency_check)
    config = load_local_config(operate=operate, service_name=t.cast(str, service.name))
    ensure_enough_funds(operate, service)

    print_box("PLEASE, DO NOT INTERRUPT THIS PROCESS.")
    print_section(f"Deploying on-chain service on {config.principal_chain}...")
    print(
        "Cancelling the on-chain service update prematurely could lead to an inconsistent state of the Safe or the on-chain service state, which may require manual intervention to resolve.\n"
    )
    manager.deploy_service_onchain_from_safe(
        service_config_id=service.service_config_id
    )

    print_section("Funding the service")
    manager.fund_service(service_config_id=service.service_config_id)

    print_section("Deploying the service")
    manager.deploy_service_locally(
        service_config_id=service.service_config_id,
        use_docker=True,
        use_kubernetes=True,
        build_only=build_only,
    )
    if build_only:
        print_section(f"Built the {template['name']}")
    else:
        print_section(f"Starting the {template['name']}")
