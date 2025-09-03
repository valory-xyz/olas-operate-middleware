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

"""Funding manager"""


# pylint: disable=too-many-locals

import typing as t
from collections import defaultdict
from logging import Logger

from autonomy.chain.base import registry_contracts
from autonomy.chain.constants import CHAIN_PROFILES

from operate.constants import MIN_AGENT_BOND, MIN_SECURITY_DEPOSIT, ZERO_ADDRESS
from operate.operate_types import Chain, OnChainState
from operate.services.protocol import StakingManager, StakingState
from operate.services.service import NON_EXISTENT_TOKEN, Service
from operate.wallet.master import MasterWalletManager


class FundingManager:
    """FundingManager"""

    def __init__(
        self,
        wallet_manager: MasterWalletManager,
        logger: Logger,
    ) -> None:
        """Initialize master wallet manager."""
        self.wallet_manager = wallet_manager
        self.logger = logger

    def _compute_protocol_asset_requirements(self, service: Service) -> t.Dict:
        """Computes the protocol asset requirements to deploy on-chain and stake (if necessary)"""

        self.logger.info(
            f"[FUNDING MANAGER] Computing protocol asset requirements for service {service.service_config_id}"
        )
        protocol_asset_requirements = {}

        for chain, chain_config in service.chain_configs.items():
            user_params = chain_config.chain_data.user_params
            number_of_agents = len(service.agent_addresses)
            # os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc  # TODO do we need this?

            requirements: defaultdict = defaultdict(int)

            if not user_params.use_staking or not user_params.staking_program_id:
                protocol_agent_bonds = (
                    max(MIN_AGENT_BOND, user_params.cost_of_bond) * number_of_agents
                )
                protocol_security_deposit = max(
                    MIN_SECURITY_DEPOSIT, user_params.cost_of_bond
                )
                staking_agent_bonds = 0
                staking_security_deposit = 0
            else:
                protocol_agent_bonds = MIN_AGENT_BOND * number_of_agents
                protocol_security_deposit = MIN_SECURITY_DEPOSIT

                staking_manager = StakingManager(chain=Chain(chain))
                staking_params = staking_manager.get_staking_params(
                    staking_contract=staking_manager.get_staking_contract(
                        staking_program_id=user_params.staking_program_id,
                    ),
                )

                staking_agent_bonds = (
                    staking_params["min_staking_deposit"] * number_of_agents
                )
                staking_security_deposit = staking_params["min_staking_deposit"]
                staking_token = staking_params["staking_token"]
                requirements[staking_token] += staking_agent_bonds
                requirements[staking_token] += staking_security_deposit

                for token, amount in staking_params[
                    "additional_staking_tokens"
                ].items():
                    requirements[token] = amount

            requirements[ZERO_ADDRESS] += protocol_agent_bonds
            requirements[ZERO_ADDRESS] += protocol_security_deposit
            protocol_asset_requirements[chain] = dict(requirements)

        return dict(protocol_asset_requirements)

        # TODO address this comment
        # This computation assumes the service will be/has been minted with these
        # parameters. Otherwise, these values should be retrieved on-chain as follows:
        # - agent_bonds: by combining the output of ServiceRegistry .getAgentParams .getService
        #   and ServiceRegistryTokenUtility .getAgentBond
        # - security_deposit: as the maximum agent bond.

    def _compute_protocol_bonded_assets(  # pylint: disable=too-many-locals
        self, service: Service
    ) -> t.Dict:
        """Computes the bonded assets: current agent bonds and current security deposit"""

        protocol_bonded_assets = {}

        for chain, chain_config in service.chain_configs.items():
            ledger_config = chain_config.ledger_config
            user_params = chain_config.chain_data.user_params
            wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
            ledger_api = wallet.ledger_api(Chain(chain))
            staking_manager = StakingManager(Chain(chain))

            bonded_assets: defaultdict = defaultdict(int)

            if Chain(chain) not in wallet.safes:
                return dict(bonded_assets)

            master_safe = wallet.safes[Chain(chain)]

            service_id = chain_config.chain_data.token
            if service_id == NON_EXISTENT_TOKEN:
                return dict(bonded_assets)

            # os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc  # TODO do we need this?

            # Determine bonded native amount
            service_registry_address = CHAIN_PROFILES[chain]["service_registry"]
            service_registry = registry_contracts.service_registry.get_instance(
                ledger_api=ledger_api,
                contract_address=service_registry_address,
            )
            service_info = service_registry.functions.getService(service_id).call()
            security_deposit = service_info[0]
            service_state = service_info[6]
            agent_ids = service_info[7]

            if (
                OnChainState.ACTIVE_REGISTRATION
                <= service_state
                < OnChainState.TERMINATED_BONDED
            ):
                bonded_assets[ZERO_ADDRESS] += security_deposit

            operator_balance = service_registry.functions.getOperatorBalance(
                master_safe, service_id
            ).call()
            bonded_assets[ZERO_ADDRESS] += operator_balance

            # Determine bonded token amount for staking programs
            current_staking_program = staking_manager.get_current_staking_program(
                service_id=service_id,
            )
            target_staking_program = user_params.staking_program_id
            staking_contract = staking_manager.get_staking_contract(
                staking_program_id=current_staking_program or target_staking_program,
            )

            if not staking_contract:
                return dict(bonded_assets)

            staking_manager = StakingManager(Chain(chain))
            staking_params = staking_manager.get_staking_params(
                staking_contract=staking_manager.get_staking_contract(
                    staking_program_id=user_params.staking_program_id,
                ),
            )

            service_registry_token_utility_address = staking_params[
                "service_registry_token_utility"
            ]
            service_registry_token_utility = (
                registry_contracts.service_registry_token_utility.get_instance(
                    ledger_api=ledger_api,
                    contract_address=service_registry_token_utility_address,
                )
            )

            agent_bonds = 0
            for agent_id in agent_ids:
                num_agent_instances = service_registry.functions.getInstancesForAgentId(
                    service_id, agent_id
                ).call()[0]
                agent_bond = service_registry_token_utility.functions.getAgentBond(
                    service_id, agent_id
                ).call()
                agent_bonds += num_agent_instances * agent_bond

            if service_state == OnChainState.TERMINATED_BONDED:
                num_agent_instances = service_info[5]
                token_bond = (
                    service_registry_token_utility.functions.getOperatorBalance(
                        master_safe,
                        service_id,
                    ).call()
                )
                agent_bonds += num_agent_instances * token_bond

            security_deposit = 0
            if (
                OnChainState.ACTIVE_REGISTRATION
                <= service_state
                < OnChainState.TERMINATED_BONDED
            ):
                security_deposit = (
                    service_registry_token_utility.functions.mapServiceIdTokenDeposit(
                        service_id
                    ).call()[1]
                )

            bonded_assets[staking_params["staking_token"]] += agent_bonds
            bonded_assets[staking_params["staking_token"]] += security_deposit

            staking_state = staking_manager.staking_state(
                service_id=service_id,
                staking_contract=staking_params["staking_contract"],
            )

            if staking_state in (StakingState.STAKED, StakingState.EVICTED):
                for token, amount in staking_params[
                    "additional_staking_tokens"
                ].items():
                    bonded_assets[token] += amount

            protocol_bonded_assets[chain] = dict(bonded_assets)

        return dict(protocol_bonded_assets)

    def refill_requirements(  # pylint: disable=too-many-locals,too-many-statements,too-many-nested-blocks
        self, service_config_id: str
    ) -> t.Dict:
        """Get user refill requirements for a service."""
        service = self.load(service_config_id=service_config_id)

        balances: t.Dict = {}
        bonded_assets: t.Dict = {}
        protocol_asset_requirements: t.Dict = {}
        refill_requirements: t.Dict = {}
        total_requirements: t.Dict = {}
        allow_start_agent = True
        is_refill_required = False

        for chain, chain_config in service.chain_configs.items():
            ledger_config = chain_config.ledger_config
            chain_data = chain_config.chain_data
            wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
            ledger_api = wallet.ledger_api(
                chain=ledger_config.chain, rpc=ledger_config.rpc
            )
            os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

            master_eoa = wallet.address
            master_safe_exists = wallet.safes.get(Chain(chain)) is not None
            master_safe = wallet.safes.get(Chain(chain), "master_safe")

            agent_addresses = set(service.agent_addresses)
            service_safe = (
                chain_data.multisig if chain_data.multisig else "service_safe"
            )

            if not master_safe_exists:
                allow_start_agent = False

            # Protocol asset requirements
            protocol_asset_requirements[
                chain
            ] = self._compute_protocol_asset_requirements(service_config_id, chain)
            service_asset_requirements = chain_data.user_params.fund_requirements

            # Bonded assets
            bonded_assets[chain] = self._compute_bonded_assets(service_config_id, chain)

            # Balances
            addresses = agent_addresses | {service_safe, master_eoa, master_safe}
            asset_addresses = (
                {ZERO_ADDRESS}
                | service_asset_requirements.keys()
                | protocol_asset_requirements[chain].keys()
                | bonded_assets[chain].keys()
            )

            balances[chain] = get_assets_balances(
                ledger_api=ledger_api,
                addresses=addresses,
                asset_addresses=asset_addresses,
                raise_on_invalid_address=False,
            )

            # TODO this is a patch for the case when excess balance is in MasterEOA
            # and MasterSafe is not created (typically for onboarding bridging).
            # It simulates the "balance in the future" for both addesses when
            # transfering the excess assets.
            if master_safe == "master_safe":
                eoa_funding_values = self.get_master_eoa_native_funding_values(
                    master_safe_exists=master_safe_exists,
                    chain=Chain(chain),
                    balance=balances[chain][master_eoa][ZERO_ADDRESS],
                )

                for asset in balances[chain][master_safe]:
                    if asset == ZERO_ADDRESS:
                        balances[chain][master_safe][asset] = max(
                            balances[chain][master_eoa][asset]
                            - eoa_funding_values["topup"],
                            0,
                        )
                        balances[chain][master_eoa][asset] = min(
                            balances[chain][master_eoa][asset],
                            eoa_funding_values["topup"],
                        )
                    else:
                        balances[chain][master_safe][asset] = balances[chain][
                            master_eoa
                        ][asset]
                        balances[chain][master_eoa][asset] = 0

            # TODO this is a balances patch to count wrapped native asset as
            # native assets for the service safe
            if Chain(chain) in WRAPPED_NATIVE_ASSET:
                if WRAPPED_NATIVE_ASSET[Chain(chain)] not in asset_addresses:
                    balances[chain][service_safe][ZERO_ADDRESS] += get_asset_balance(
                        ledger_api=ledger_api,
                        asset_address=WRAPPED_NATIVE_ASSET[Chain(chain)],
                        address=service_safe,
                        raise_on_invalid_address=False,
                    )

            # Refill requirements
            refill_requirements[chain] = {}
            total_requirements[chain] = {}

            # Refill requirements for Master Safe
            for asset_address in (
                service_asset_requirements.keys()
                | protocol_asset_requirements[chain].keys()
            ):
                agent_asset_funding_values = {}
                if asset_address in service_asset_requirements:
                    fund_requirements = service_asset_requirements[asset_address]
                    agent_asset_funding_values = {
                        address: {
                            "topup": fund_requirements.agent,
                            "threshold": int(
                                fund_requirements.agent * DEFAULT_TOPUP_THRESHOLD
                            ),  # TODO make threshold configurable
                            "balance": balances[chain][address][asset_address],
                        }
                        for address in agent_addresses
                    }
                    agent_asset_funding_values[service_safe] = {
                        "topup": fund_requirements.safe,
                        "threshold": int(
                            fund_requirements.safe * DEFAULT_TOPUP_THRESHOLD
                        ),  # TODO make threshold configurable
                        "balance": balances[chain][service_safe][asset_address],
                    }

                recommended_refill = self._compute_refill_requirement(
                    asset_funding_values=agent_asset_funding_values,
                    sender_topup=protocol_asset_requirements[chain].get(
                        asset_address, 0
                    ),
                    sender_threshold=protocol_asset_requirements[chain].get(
                        asset_address, 0
                    ),
                    sender_balance=balances[chain][master_safe][asset_address]
                    + bonded_assets[chain].get(asset_address, 0),
                )["recommended_refill"]

                refill_requirements[chain].setdefault(master_safe, {})[
                    asset_address
                ] = recommended_refill

                total_requirements[chain].setdefault(master_safe, {})[
                    asset_address
                ] = sum(
                    agent_asset_funding_values[address]["topup"]
                    for address in agent_asset_funding_values
                ) + protocol_asset_requirements[
                    chain
                ].get(
                    asset_address, 0
                )

                if asset_address == ZERO_ADDRESS and any(
                    balances[chain][master_safe][asset_address] == 0
                    and balances[chain][address][asset_address] == 0
                    and agent_asset_funding_values[address]["threshold"] > 0
                    for address in agent_asset_funding_values
                ):
                    allow_start_agent = False

            # Refill requirements for Master EOA
            eoa_funding_values = self.get_master_eoa_native_funding_values(
                master_safe_exists=master_safe_exists,
                chain=Chain(chain),
                balance=balances[chain][master_eoa][ZERO_ADDRESS],
            )

            eoa_recommended_refill = self._compute_refill_requirement(
                asset_funding_values={},
                sender_topup=eoa_funding_values["topup"],
                sender_threshold=eoa_funding_values["threshold"],
                sender_balance=balances[chain][master_eoa][ZERO_ADDRESS],
            )["recommended_refill"]

            refill_requirements[chain].setdefault(master_eoa, {})[
                ZERO_ADDRESS
            ] = eoa_recommended_refill

            total_requirements[chain].setdefault(master_eoa, {})[
                ZERO_ADDRESS
            ] = eoa_funding_values["topup"]

        is_refill_required = any(
            amount > 0
            for chain in refill_requirements.values()
            for asset in chain.values()
            for amount in asset.values()
        )

        return {
            "balances": balances,
            "bonded_assets": bonded_assets,
            "total_requirements": total_requirements,
            "refill_requirements": refill_requirements,
            "protocol_asset_requirements": protocol_asset_requirements,
            "is_refill_required": is_refill_required,
            "allow_start_agent": allow_start_agent,
        }
