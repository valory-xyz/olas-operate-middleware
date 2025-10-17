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


# pylint: disable=too-many-locals,too-many-statements

import asyncio
import threading
import traceback
import typing as t
from concurrent.futures import ThreadPoolExecutor
from logging import Logger
from time import time

from aea_ledger_ethereum import defaultdict
from autonomy.chain.base import registry_contracts
from autonomy.chain.config import CHAIN_PROFILES, ChainType
from web3 import Web3

from operate.constants import (
    DEFAULT_FUNDING_REQUESTS_COOLDOWN_SECONDS,
    MASTER_EOA_PLACEHOLDER,
    MASTER_SAFE_PLACEHOLDER,
    MIN_AGENT_BOND,
    MIN_SECURITY_DEPOSIT,
    NO_STAKING_PROGRAM_ID,
    SERVICE_SAFE_PLACEHOLDER,
    ZERO_ADDRESS,
)
from operate.keys import KeysManager
from operate.ledger import get_currency_denom, get_default_ledger_api
from operate.ledger.profiles import (
    CONTRACTS,
    DEFAULT_EOA_TOPUPS,
    DEFAULT_EOA_TOPUPS_WITHOUT_SAFE,
    OLAS,
    USDC,
    WRAPPED_NATIVE_ASSET,
    get_token_name,
)
from operate.operate_types import Chain, ChainAmounts, LedgerType, OnChainState
from operate.services.protocol import EthSafeTxBuilder, StakingManager, StakingState
from operate.services.service import NON_EXISTENT_TOKEN, Service
from operate.utils.gnosis import drain_eoa, get_asset_balance, get_owners
from operate.utils.gnosis import transfer as transfer_from_safe
from operate.utils.gnosis import transfer_erc20_from_safe
from operate.wallet.master import InsufficientFundsException, MasterWalletManager


if t.TYPE_CHECKING:
    from operate.services.manage import ServiceManager  # pylint: disable=unused-import


class FundingInProgressError(RuntimeError):
    """Raised when an attempt is made to fund a service that is already being funded."""


class FundingManager:
    """FundingManager"""

    def __init__(
        self,
        wallet_manager: MasterWalletManager,
        logger: Logger,
        funding_requests_cooldown_seconds: int = DEFAULT_FUNDING_REQUESTS_COOLDOWN_SECONDS,
    ) -> None:
        """Initialize funding manager."""
        self.wallet_manager = wallet_manager
        self.logger = logger
        self.funding_requests_cooldown_seconds = funding_requests_cooldown_seconds
        self._lock = threading.Lock()
        self._funding_in_progress: t.Dict[str, bool] = {}
        self._funding_requests_cooldown_until: t.Dict[str, float] = {}

    def drain_agents_eoas(
        self, service: Service, withdrawal_address: str, chain: Chain
    ) -> None:
        """Drain the funds out of the service agents EOAs."""
        service_config_id = service.service_config_id
        ledger_api = get_default_ledger_api(chain)
        self.logger.info(
            f"Draining service agents {service.name} ({service_config_id=})"
        )
        for agent_address in service.agent_addresses:
            ethereum_crypto = KeysManager().get_crypto_instance(agent_address)
            balance = ledger_api.get_balance(agent_address)
            self.logger.info(
                f"Draining {balance} (approx) {get_currency_denom(chain)} from {agent_address} (agent) to {withdrawal_address}"
            )
            drain_eoa(
                ledger_api=ledger_api,
                crypto=ethereum_crypto,
                withdrawal_address=withdrawal_address,
                chain_id=chain.id,
            )
            self.logger.info(f"{service.name} signer drained")

    def drain_service_safe(  # pylint: disable=too-many-locals
        self, service: Service, withdrawal_address: str, chain: Chain
    ) -> None:
        """Drain the funds out of the service safe."""
        service_config_id = service.service_config_id
        self.logger.info(f"Draining service safe {service.name} ({service_config_id=})")
        chain_config = service.chain_configs[chain.value]
        chain_data = chain_config.chain_data
        ledger_api = get_default_ledger_api(chain)
        withdrawal_address = Web3.to_checksum_address(withdrawal_address)
        service_safe = chain_data.multisig
        wallet = self.wallet_manager.load(chain.ledger_type)
        master_safe = wallet.safes[chain]
        ledger_config = chain_config.ledger_config
        sftxb = EthSafeTxBuilder(
            rpc=ledger_config.rpc,
            wallet=wallet,
            contracts=CONTRACTS[ledger_config.chain],
            chain_type=ChainType(ledger_config.chain.value),
        )

        owners = get_owners(ledger_api=ledger_api, safe=service_safe)

        # Drain ERC20 tokens from service Safe
        tokens = {
            WRAPPED_NATIVE_ASSET[chain],
            OLAS[chain],
            USDC[chain],
        } | service.chain_configs[
            chain.value
        ].chain_data.user_params.fund_requirements.keys()
        tokens.discard(ZERO_ADDRESS)

        for token_address in tokens:
            token_instance = registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=token_address,
            )
            balance = token_instance.functions.balanceOf(service_safe).call()
            token_name = get_token_name(chain, token_address)
            if balance == 0:
                self.logger.info(
                    f"No {token_name} to drain from service safe: {service_safe}"
                )
                continue

            self.logger.info(
                f"Draining {balance} {token_name} from {service_safe} (service safe) to {withdrawal_address}"
            )

            # Safe not swapped
            if set(owners) == set(service.agent_addresses):
                ethereum_crypto = KeysManager().get_crypto_instance(
                    service.agent_addresses[0]
                )
                transfer_erc20_from_safe(
                    ledger_api=ledger_api,
                    crypto=ethereum_crypto,
                    safe=chain_data.multisig,
                    token=token_address,
                    to=withdrawal_address,
                    amount=balance,
                )
            elif set(owners) == {master_safe}:
                messages = sftxb.get_safe_b_erc20_transfer_messages(
                    safe_b_address=service_safe,
                    token=token_address,
                    to=withdrawal_address,
                    amount=balance,
                )
                for message in messages:
                    tx = sftxb.new_tx()
                    tx.add(message)
                    tx.settle()

            else:
                raise RuntimeError(
                    f"Cannot drain service safe: unrecognized owner set {owners=}"
                )

        # Drain native asset from service Safe
        balance = ledger_api.get_balance(service_safe)
        if balance == 0:
            self.logger.info(
                f"No {get_currency_denom(chain)} to drain from service safe: {service_safe}"
            )
        else:
            self.logger.info(
                f"Draining {balance} {get_currency_denom(chain)} from {service_safe} (service safe) to {withdrawal_address}"
            )

            if set(owners) == set(service.agent_addresses):
                ethereum_crypto = KeysManager().get_crypto_instance(
                    service.agent_addresses[0]
                )
                transfer_from_safe(
                    ledger_api=ledger_api,
                    crypto=ethereum_crypto,
                    safe=chain_data.multisig,
                    to=withdrawal_address,
                    amount=balance,
                )
            elif set(owners) == {master_safe}:
                messages = sftxb.get_safe_b_native_transfer_messages(
                    safe_b_address=service_safe,
                    to=withdrawal_address,
                    amount=balance,
                )
                for message in messages:
                    tx = sftxb.new_tx()
                    tx.add(message)
                    tx.settle()

            else:
                raise RuntimeError(
                    f"Cannot drain service safe: unrecognized owner set {owners=}"
                )

        self.logger.info(f"Service safe {service.name} drained ({service_config_id=})")

    # -------------------------------------------------------------------------------------
    # -------------------------------------------------------------------------------------

    def _compute_protocol_asset_requirements(self, service: Service) -> ChainAmounts:
        """Computes the protocol asset requirements to deploy on-chain and stake (if necessary)"""

        self.logger.info(
            f"[FUNDING MANAGER] Computing protocol asset requirements for service {service.service_config_id}"
        )
        protocol_asset_requirements = ChainAmounts()

        for chain, chain_config in service.chain_configs.items():
            user_params = chain_config.chain_data.user_params
            number_of_agents = len(service.agent_addresses)

            requirements: defaultdict = defaultdict(int)

            if (
                not user_params.use_staking
                or not user_params.staking_program_id
                or user_params.staking_program_id == NO_STAKING_PROGRAM_ID
            ):
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

            master_safe = self._resolve_master_safe(Chain(chain))

            protocol_asset_requirements[chain] = {master_safe: dict(requirements)}

        return protocol_asset_requirements

        # TODO address this comment
        # This computation assumes the service will be/has been minted with these
        # parameters. Otherwise, these values should be retrieved on-chain as follows:
        # - agent_bonds: by combining the output of ServiceRegistry .getAgentParams .getService
        #   and ServiceRegistryTokenUtility .getAgentBond
        # - security_deposit: as the maximum agent bond.

    def _compute_protocol_bonded_assets(  # pylint: disable=too-many-locals,too-many-statements
        self, service: Service
    ) -> ChainAmounts:
        """Computes the bonded assets: current agent bonds and current security deposit"""

        protocol_bonded_assets = ChainAmounts()

        for chain, chain_config in service.chain_configs.items():
            bonded_assets: defaultdict = defaultdict(int)
            ledger_config = chain_config.ledger_config
            user_params = chain_config.chain_data.user_params

            if not self.wallet_manager.exists(ledger_config.chain.ledger_type):
                protocol_bonded_assets[chain] = {
                    MASTER_SAFE_PLACEHOLDER: dict(bonded_assets)
                }
                continue

            wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
            ledger_api = get_default_ledger_api(Chain(chain))
            staking_manager = StakingManager(Chain(chain))

            if Chain(chain) not in wallet.safes:
                protocol_bonded_assets[chain] = {
                    MASTER_SAFE_PLACEHOLDER: dict(bonded_assets)
                }
                continue

            master_safe = wallet.safes[Chain(chain)]

            service_id = chain_config.chain_data.token
            if service_id == NON_EXISTENT_TOKEN:
                protocol_bonded_assets[chain] = {master_safe: dict(bonded_assets)}
                continue

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

            protocol_bonded_assets[chain] = {master_safe: dict(bonded_assets)}

        return protocol_bonded_assets

    @staticmethod
    def _compute_shortfalls(
        balances: ChainAmounts,
        thresholds: ChainAmounts,
        topups: ChainAmounts,
    ) -> ChainAmounts:
        """Compute shortfall per chain/address/asset: if balance < threshold, shortfall = topup - balance, else 0"""
        shortfalls = ChainAmounts()

        for chain, addresses in thresholds.items():
            shortfalls.setdefault(chain, {})
            for address, assets in addresses.items():
                shortfalls[chain].setdefault(address, {})
                for asset, threshold in assets.items():
                    balance = balances.get(chain, {}).get(address, {}).get(asset, 0)
                    topup = topups.get(chain, {}).get(address, {}).get(asset, 0)
                    if balance < threshold:
                        shortfalls[chain][address][asset] = max(topup - balance, 0)
                    else:
                        shortfalls[chain][address][asset] = 0

        return shortfalls

    def _resolve_master_eoa(self, chain: Chain) -> str:
        if self.wallet_manager.exists(chain.ledger_type):
            wallet = self.wallet_manager.load(chain.ledger_type)
            return wallet.address
        return MASTER_EOA_PLACEHOLDER

    def _resolve_master_safe(self, chain: Chain) -> str:
        if self.wallet_manager.exists(chain.ledger_type):
            wallet = self.wallet_manager.load(chain.ledger_type)
            if chain in wallet.safes:
                return wallet.safes[chain]
        return MASTER_SAFE_PLACEHOLDER

    def _aggregate_as_master_safe_amounts(self, *amounts: ChainAmounts) -> ChainAmounts:
        output = ChainAmounts()
        for amts in amounts:
            for chain_str, addresses in amts.items():
                chain = Chain(chain_str)
                master_safe = self._resolve_master_safe(chain)
                master_safe_dict = output.setdefault(chain_str, {}).setdefault(
                    master_safe, {}
                )
                for _, assets in addresses.items():
                    for asset, amount in assets.items():
                        master_safe_dict[asset] = (
                            master_safe_dict.get(asset, 0) + amount
                        )

        return output

    def _split_excess_assets_master_eoa_balances(
        self, balances: ChainAmounts
    ) -> t.Tuple[ChainAmounts, ChainAmounts]:
        """Splits excess balances from master EOA only on chains without a Master Safe."""
        excess_balance = ChainAmounts()
        remaining_balance = ChainAmounts()

        for chain_str, addresses in balances.items():
            chain = Chain(chain_str)
            master_safe = self._resolve_master_safe(chain)
            for address, assets in addresses.items():
                for asset, amount in assets.items():
                    if master_safe == MASTER_SAFE_PLACEHOLDER:
                        remaining = min(
                            amount, DEFAULT_EOA_TOPUPS[chain].get(asset, 0)
                        )  # When transferring, the Master Safe will be already created, that is why we are only retaining DEFAULT_EOA_TOPUPS
                        excess = amount - remaining
                    else:
                        remaining = amount
                        excess = 0

                    excess_balance.setdefault(chain_str, {}).setdefault(
                        master_safe, {}
                    )[asset] = excess
                    remaining_balance.setdefault(chain_str, {}).setdefault(address, {})[
                        asset
                    ] = remaining

        return excess_balance, remaining_balance

    @staticmethod
    def _split_critical_eoa_shortfalls(
        balances: ChainAmounts, shortfalls: ChainAmounts
    ) -> t.Tuple[ChainAmounts, ChainAmounts]:
        """Splits critical EOA shortfalls in two: the first split containins the native shortfalls whose balance is < threshold / 2. The second one, contains the remaining shortfalls. This is to ensure EOA operational balance."""
        critical_shortfalls = ChainAmounts()
        remaining_shortfalls = ChainAmounts()

        for chain_str, addresses in shortfalls.items():
            chain = Chain(chain_str)
            for address, assets in addresses.items():
                for asset, amount in assets.items():
                    if asset == ZERO_ADDRESS and balances[chain_str][address][
                        asset
                    ] < int(
                        DEFAULT_EOA_TOPUPS[chain][asset] / 4
                    ):  # TODO Ensure that this is enough to pay a transfer tx at least.
                        critical_shortfalls.setdefault(chain_str, {}).setdefault(
                            address, {}
                        )[asset] = amount
                        remaining_shortfalls.setdefault(chain_str, {}).setdefault(
                            address, {}
                        )[asset] = 0
                    else:
                        critical_shortfalls.setdefault(chain_str, {}).setdefault(
                            address, {}
                        )[asset] = 0
                        remaining_shortfalls.setdefault(chain_str, {}).setdefault(
                            address, {}
                        )[asset] = amount

        return critical_shortfalls, remaining_shortfalls

    def _get_master_safe_balances(self, thresholds: ChainAmounts) -> ChainAmounts:
        output = ChainAmounts()
        for chain_str, addresses in thresholds.items():
            chain = Chain(chain_str)
            master_safe = self._resolve_master_safe(chain)
            master_safe_dict = output.setdefault(chain_str, {}).setdefault(
                master_safe, {}
            )
            for _, assets in addresses.items():
                for asset, _ in assets.items():
                    master_safe_dict[asset] = get_asset_balance(
                        ledger_api=get_default_ledger_api(chain),
                        asset_address=asset,
                        address=master_safe,
                        raise_on_invalid_address=False,
                    )

        return output

    def _get_master_eoa_balances(self, thresholds: ChainAmounts) -> ChainAmounts:
        output = ChainAmounts()
        for chain_str, addresses in thresholds.items():
            chain = Chain(chain_str)
            master_eoa = self._resolve_master_eoa(chain)
            master_eoa_dict = output.setdefault(chain_str, {}).setdefault(
                master_eoa, {}
            )
            for _, assets in addresses.items():
                for asset, _ in assets.items():
                    master_eoa_dict[asset] = get_asset_balance(
                        ledger_api=get_default_ledger_api(chain),
                        asset_address=asset,
                        address=master_eoa,
                        raise_on_invalid_address=False,
                    )

        return output

    def fund_master_eoa(self) -> None:
        """Fund Master EOA"""
        if not self.wallet_manager.exists(LedgerType.ETHEREUM):
            self.logger.warning(
                "[FUNDING MANAGER] Cannot fund Master EOA: No Ethereum wallet available."
            )
            return

        master_wallet = self.wallet_manager.load(
            ledger_type=LedgerType.ETHEREUM
        )  # Only for ethereum for now
        self.logger.info(
            f"[FUNDING MANAGER] Funding Master EOA {master_wallet.address}"
        )
        master_eoa_topups = ChainAmounts(
            {
                chain.value: {
                    self._resolve_master_eoa(chain): dict(DEFAULT_EOA_TOPUPS[chain])
                }
                for chain in master_wallet.safes
            }
        )
        master_eoa_balances = self._get_master_eoa_balances(master_eoa_topups)
        master_eoa_shortfalls = self._compute_shortfalls(
            balances=master_eoa_balances,
            thresholds=master_eoa_topups // 2,
            topups=master_eoa_topups,
        )
        self._fund_chain_amounts(master_eoa_shortfalls)

    def funding_requirements(self, service: Service) -> t.Dict:
        """Funding requirements"""
        balances: ChainAmounts
        protocol_bonded_assets: ChainAmounts
        protocol_asset_requirements: ChainAmounts
        refill_requirements: ChainAmounts
        total_requirements: ChainAmounts
        chains = [Chain(chain_str) for chain_str in service.chain_configs.keys()]

        # Protocol shortfall
        protocol_thresholds = self._compute_protocol_asset_requirements(service)
        protocol_balances = self._compute_protocol_bonded_assets(service)
        protocol_topups = protocol_thresholds
        protocol_shortfalls = self._compute_shortfalls(
            balances=protocol_balances,
            thresholds=protocol_thresholds,
            topups=protocol_topups,
        )

        # Initial service shortfall
        # We assume that if the service safe is created in any chain,
        # we have requested the funding already.
        service_initial_topup = service.get_initial_funding_amounts()
        if not all(
            SERVICE_SAFE_PLACEHOLDER in addresses
            for addresses in service_initial_topup.values()
        ):
            service_initial_shortfalls = ChainAmounts()
        else:
            service_initial_shortfalls = service_initial_topup

        # Service funding requests
        service_config_id = service.service_config_id
        funding_in_progress = self._funding_in_progress.get(service_config_id, False)
        now = time()
        if funding_in_progress:
            funding_requests = ChainAmounts()
            funding_requests_cooldown = False
        elif now < self._funding_requests_cooldown_until.get(service_config_id, 0):
            funding_requests = ChainAmounts()
            funding_requests_cooldown = True
        else:
            funding_requests = service.get_funding_requests()
            funding_requests_cooldown = False

        # Master EOA shortfall
        master_eoa_topups = ChainAmounts()
        for chain in chains:
            chain_str = chain.value
            master_eoa = self._resolve_master_eoa(chain)
            master_safe = self._resolve_master_safe(chain)

            if master_safe != MASTER_SAFE_PLACEHOLDER:
                master_eoa_topups[chain_str] = {
                    master_eoa: dict(DEFAULT_EOA_TOPUPS[chain])
                }
            else:
                master_eoa_topups[chain_str] = {
                    master_eoa: dict(DEFAULT_EOA_TOPUPS_WITHOUT_SAFE[chain])
                }

            # Set the topup for MasterEOA for remaining tokens to 0 if they don't exist
            # This ensures that the balances of MasterEOA are collected for relevant tokens
            all_assets = {ZERO_ADDRESS} | {
                asset
                for addresses in (
                    protocol_topups[chain_str],
                    service_initial_topup[chain_str],
                )
                for assets in addresses.values()
                for asset in assets
            }
            for asset in all_assets:
                master_eoa_topups[chain_str][master_eoa].setdefault(asset, 0)

        master_eoa_thresholds = master_eoa_topups // 2
        master_eoa_balances = self._get_master_eoa_balances(master_eoa_thresholds)

        # BEGIN Bridging patch: remove excess balances for chains without a Safe:
        (
            excess_master_eoa_balances,
            master_eoa_balances,
        ) = self._split_excess_assets_master_eoa_balances(master_eoa_balances)
        # END Bridging patch

        master_eoa_shortfalls = self._compute_shortfalls(
            balances=master_eoa_balances,
            thresholds=master_eoa_thresholds,
            topups=master_eoa_topups,
        )

        (
            master_eoa_critical_shortfalls,
            master_eoa_shortfalls,
        ) = self._split_critical_eoa_shortfalls(
            balances=master_eoa_balances, shortfalls=master_eoa_shortfalls
        )

        # Master Safe shortfall
        master_safe_thresholds = self._aggregate_as_master_safe_amounts(
            master_eoa_shortfalls,
            protocol_shortfalls,
            service_initial_shortfalls,
        )
        master_safe_topup = master_safe_thresholds
        master_safe_balances = ChainAmounts.add(
            self._get_master_safe_balances(master_safe_thresholds),
            self._aggregate_as_master_safe_amounts(excess_master_eoa_balances),
        )
        master_safe_shortfalls = self._compute_shortfalls(
            balances=master_safe_balances,
            thresholds=master_safe_thresholds,
            topups=master_safe_topup,
        )

        # Prepare output values
        protocol_bonded_assets = protocol_balances
        protocol_asset_requirements = protocol_thresholds
        refill_requirements = ChainAmounts.add(
            master_eoa_critical_shortfalls,
            master_safe_shortfalls,
        )
        total_requirements = ChainAmounts.add(  # TODO Review if this is correct
            master_eoa_critical_shortfalls,
            master_safe_thresholds,
        )
        balances = ChainAmounts.add(
            master_eoa_balances,
            master_safe_balances,
        )

        # Compute boolean flags
        is_refill_required = any(
            amount > 0
            for address in refill_requirements.values()
            for assets in address.values()
            for amount in assets.values()
        )

        allow_start_agent = True
        if any(
            MASTER_SAFE_PLACEHOLDER in addresses
            for addresses in refill_requirements.values()
        ) or any(
            amount > 0
            for address in master_eoa_critical_shortfalls.values()
            for assets in address.values()
            for amount in assets.values()
        ):
            allow_start_agent = False

        return {
            "balances": balances,
            "bonded_assets": protocol_bonded_assets,
            "total_requirements": total_requirements,
            "refill_requirements": refill_requirements,
            "protocol_asset_requirements": protocol_asset_requirements,
            "is_refill_required": is_refill_required,
            "allow_start_agent": allow_start_agent,
            "agent_funding_requests": funding_requests,
            "agent_funding_requests_cooldown": funding_requests_cooldown,
            "agent_funding_in_progress": funding_in_progress,
        }

    def fund_service_initial(self, service: Service) -> None:
        """Fund service initially"""
        self._fund_chain_amounts(service.get_initial_funding_amounts())

    def _fund_chain_amounts(self, amounts: ChainAmounts) -> None:
        required = self._aggregate_as_master_safe_amounts(amounts)
        balances = self._get_master_safe_balances(required)

        if balances < required:
            raise InsufficientFundsException(
                f"Insufficient funds in Master Safe to perform funding. Required: {amounts}, Available: {balances}"
            )

        for chain_str, addresses in amounts.items():
            chain = Chain(chain_str)
            wallet = self.wallet_manager.load(chain.ledger_type)
            for address, assets in addresses.items():
                for asset, amount in assets.items():
                    if amount <= 0:
                        continue

                    self.logger.info(
                        f"[FUNDING MANAGER] Funding {amount} of {asset} to {address} on chain {chain.value} from Master Safe {wallet.safes.get(chain, 'N/A')}"
                    )
                    wallet.transfer(
                        chain=chain,
                        to=address,
                        asset=asset,
                        amount=amount,
                        from_safe=True,
                    )

    def fund_service(self, service: Service, amounts: ChainAmounts) -> None:
        """Fund service-related wallets."""
        service_config_id = service.service_config_id

        # Atomic, thread-safe get-and-set of the _funding_in_progress boolean.
        # This ensures only one funding operation per service at a time, and
        # any call to fund_service while a funding operation is in progress will
        # raise a FundingInProgressError (instead of blocking and piling up calls).
        with self._lock:
            if self._funding_in_progress.get(service_config_id, False):
                raise FundingInProgressError(
                    f"Funding already in progress for service {service_config_id}."
                )
            self._funding_in_progress[service_config_id] = True

        try:
            for chain_str, addresses in amounts.items():
                for address in addresses:
                    if (
                        address not in service.agent_addresses
                        and address
                        != service.chain_configs[chain_str].chain_data.multisig
                    ):
                        raise ValueError(
                            f"Failed to fund from Master Safe: Address {address} is not an agent EOA or service Safe for service {service.service_config_id}."
                        )

            self._fund_chain_amounts(amounts)
            self._funding_requests_cooldown_until[service_config_id] = (
                time() + self.funding_requests_cooldown_seconds
            )
        finally:
            with self._lock:
                self._funding_in_progress[service_config_id] = False

    async def funding_job(
        self,
        service_manager: "ServiceManager",
        loop: t.Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Start a background funding job."""
        loop = loop or asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            last_claim = 0.0
            last_master_eoa_funding = 0.0
            while True:
                # try claiming rewards every hour
                if last_claim + 3600 < time():
                    try:
                        await loop.run_in_executor(
                            executor,
                            service_manager.claim_all_on_chain_from_safe,
                        )
                    except Exception:  # pylint: disable=broad-except
                        self.logger.info(
                            f"Error occured while claiming rewards\n{traceback.format_exc()}"
                        )
                    last_claim = time()

                # fund Master EOA every hour
                if last_master_eoa_funding + 3600 < time():
                    try:
                        await loop.run_in_executor(
                            executor,
                            self.fund_master_eoa,
                        )
                    except Exception:  # pylint: disable=broad-except
                        self.logger.info(
                            f"Error occured while funding Master EOA\n{traceback.format_exc()}"
                        )
                    last_master_eoa_funding = time()

                await asyncio.sleep(60)

    # TODO Below this line - pending finish funding Job for Master EOA
    # TODO cache _resolve methods to avoid loading multiple times file.
    # TODO refactor: move protocol_ methods to protocol class, refactor to accomodate arbitrary owner and operators,
    # refactor to manage multiple chains with different master safes, etc.
