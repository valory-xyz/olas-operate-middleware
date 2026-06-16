#!/usr/bin/env python3
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
"""Service manager."""

import json
import logging
import os
import threading
import traceback
import typing as t
from collections import Counter
from http import HTTPStatus
from pathlib import Path

import requests
from aea.configurations.data_types import PublicId
from aea.helpers.base import IPFSHash
from aea_ledger_ethereum import LedgerApi
from autonomy.chain.base import registry_contracts
from autonomy.chain.config import ChainType
from autonomy.chain.metadata import IPFS_URI_PREFIX

from operate.constants import (
    AGENT_LOG_DIR,
    AGENT_LOG_ENV_VAR,
    AGENT_PERSISTENT_STORAGE_DIR,
    AGENT_PERSISTENT_STORAGE_ENV_VAR,
    IPFS_ADDRESS,
    MIN_AGENT_BOND,
    POLY_SAFE_SERVICE_NAMES,
    ZERO_ADDRESS,
)
from operate.data import DATA_DIR
from operate.data.contracts.mech_activity.contract import MechActivityContract
from operate.data.contracts.requester_activity_checker.contract import (
    RequesterActivityCheckerContract,
)
from operate.keys import KeysManager
from operate.ledger import UnsupportedChainError, get_default_rpc
from operate.ledger.profiles import (
    CONTRACTS,
    DEFAULT_EOA_THRESHOLD,
    DEFAULT_PRIORITY_MECH,
    OLAS,
    get_staking_contract,
)
from operate.operate_types import (
    Chain,
    ChainAmounts,
    DeploymentStatus,
    LedgerConfig,
    MechMarketplaceConfig,
    OnChainState,
    ServiceEnvProvisionType,
    ServiceTemplate,
)
from operate.services.funding_manager import FundingManager
from operate.services.protocol import (
    EthSafeTxBuilder,
    StakingManager,
    StakingState,
)
from operate.services.service import (
    ChainConfig,
    Deployment,
    NON_EXISTENT_MULTISIG,
    NON_EXISTENT_TOKEN,
    SERVICE_CONFIG_PREFIX,
    SERVICE_CONFIG_VERSION,
    Service,
)
from operate.utils.gnosis import (
    get_asset_balance,
    simulate_safe_sub_tx,
    transfer_erc20_from_safe,
)
from operate.wallet.master import InsufficientFundsException, MasterWalletManager

# pylint: disable=redefined-builtin

# At the moment, we only support running one agent per service locally on a machine.
# If multiple agents are provided in the service.yaml file, only the 0th index config will be used.
NUM_LOCAL_AGENT_INSTANCES = 1

RPC_SYNC_TIMEOUT = 15

# Fallback gas limit for the mega-batch MultiSend. The full staking-update
# path adds well over a dozen sub-calls (teardown + update mint + approvals +
# activate/register/deploy + stake); this caps it generously and is only used
# when on-chain gas estimation is unavailable.
_MEGA_BATCH_GAS_FALLBACK = 3_000_000

# Registry states from which `terminate` is valid (it moves the service toward
# PRE_REGISTRATION). ACTIVE_REGISTRATION terminates straight to PRE_REGISTRATION;
# the others pass through TERMINATED_BONDED first.
_STATES_REQUIRING_TERMINATE = (
    OnChainState.ACTIVE_REGISTRATION,
    OnChainState.FINISHED_REGISTRATION,
    OnChainState.DEPLOYED,
)
# Registry states that pass through TERMINATED_BONDED, so `unbond` is valid.
_STATES_REQUIRING_UNBOND = (
    OnChainState.FINISHED_REGISTRATION,
    OnChainState.DEPLOYED,
    OnChainState.TERMINATED_BONDED,
)


class ServiceManager:
    """Service manager."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        path: Path,
        keys_manager: KeysManager,
        wallet_manager: MasterWalletManager,
        funding_manager: FundingManager,
        logger: logging.Logger,
        skip_dependency_check: t.Optional[bool] = False,
    ) -> None:
        """
        Initialze service manager

        :param path: Path to service storage.
        :param keys_manager: Keys manager.
        :param wallet_manager: Wallet manager instance.
        :param logger: logging.Logger object.
        """
        self.path = path
        self.keys_manager = keys_manager
        self.wallet_manager = wallet_manager
        self.funding_manager = funding_manager
        self.logger = logger
        self.skip_depencency_check = skip_dependency_check
        self._maintenance_lock = threading.Lock()

    def setup(self) -> None:
        """Setup service manager."""
        self.path.mkdir(exist_ok=True)

    def get_all_service_ids(self) -> t.List[str]:
        """
        Get all service ids.

        :return: List of service ids.
        """
        return [
            path.name
            for path in self.path.iterdir()
            if path.is_dir() and path.name.startswith(SERVICE_CONFIG_PREFIX)
        ]

    def get_all_services(self) -> t.Tuple[t.List[Service], bool]:
        """Get all services."""
        services = []
        success = True
        for path in self.path.iterdir():
            if not path.name.startswith(SERVICE_CONFIG_PREFIX):
                continue
            try:
                service = Service.load(path=path)
                if service.version != SERVICE_CONFIG_VERSION:
                    self.logger.warning(
                        f"Service {path.name} has an unsupported version: {service.version}."
                    )
                    success = False
                    continue

                services.append(service)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error(
                    f"Failed to load service: {path.name}. Exception {e}: {traceback.format_exc()}"
                )
                success = False

        return services, success

    def validate_services(self) -> bool:
        """
        Validate all services.

        :return: True if all services are valid, False otherwise.
        """
        _, success = self.get_all_services()
        return success

    @property
    def json(self) -> t.List[t.Dict]:
        """Returns the list of available services."""
        services, _ = self.get_all_services()
        return [service.json for service in services]

    def exists(self, service_config_id: str) -> bool:
        """Check if service exists."""
        return (self.path / service_config_id).exists()

    def get_eth_safe_tx_builder(self, ledger_config: LedgerConfig) -> EthSafeTxBuilder:
        """Get EthSafeTxBuilder instance."""
        return EthSafeTxBuilder(
            rpc=ledger_config.rpc,
            wallet=self.wallet_manager.load(ledger_config.chain.ledger_type),
            contracts=CONTRACTS[ledger_config.chain],
            chain_type=ChainType(ledger_config.chain.value),
        )

    def load_or_create(
        self,
        hash: str,
        service_template: t.Optional[ServiceTemplate] = None,
        agent_addresses: t.Optional[t.List[str]] = None,
    ) -> Service:
        """
        Create or load a service

        :param hash: Service hash
        :param service_template: Service template
        :param agent_addresses: Agents' addresses to be used for the service.
        :return: Service instance
        """
        path = self.path / hash
        if path.exists():
            service = Service.load(path=path)

            if service_template is not None:
                service.update_user_params_from_template(
                    service_template=service_template
                )

            return service

        if service_template is None:
            raise ValueError(
                "'service_template' cannot be None when creating a new service"
            )

        return self.create(
            service_template=service_template, agent_addresses=agent_addresses
        )

    def load(
        self,
        service_config_id: str,
    ) -> Service:
        """
        Load a service

        :param service_id: Service id
        :return: Service instance
        """
        path = self.path / service_config_id
        return Service.load(path=path)

    def create(
        self,
        service_template: ServiceTemplate,
        agent_addresses: t.Optional[t.List[str]] = None,
    ) -> Service:
        """
        Create a service

        :param service_template: Service template
        :param agent_addresses: Agents' addresses to be used for the service.
        :return: Service instance
        """
        service = Service.new(
            agent_addresses=agent_addresses or [],
            storage=self.path,
            service_template=service_template,
        )

        if not service.agent_addresses:
            service.agent_addresses = [
                self.keys_manager.create() for _ in range(NUM_LOCAL_AGENT_INSTANCES)
            ]
            service.store()

        return service

    def _get_on_chain_state(self, service: Service, chain: str) -> OnChainState:
        chain_config = service.chain_configs[chain]
        chain_data = chain_config.chain_data
        ledger_config = chain_config.ledger_config
        if chain_data.token == NON_EXISTENT_TOKEN:
            return OnChainState.NON_EXISTENT

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        info = sftxb.info(token_id=chain_data.token)
        return OnChainState(info["service_state"])

    def _get_on_chain_metadata(self, chain_config: ChainConfig) -> t.Dict:
        chain_data = chain_config.chain_data
        ledger_config = chain_config.ledger_config
        if chain_data.token == NON_EXISTENT_TOKEN:
            return {}

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        info = sftxb.info(token_id=chain_data.token)
        config_hash = info["config_hash"]
        url = IPFS_ADDRESS.format(hash=config_hash)
        self.logger.info(f"Fetching {url=}...")
        res = requests.get(url, timeout=30)
        if res.status_code == HTTPStatus.OK:
            return res.json()
        raise ValueError(
            f"Something went wrong while trying to get the on-chain metadata from IPFS: {res}"
        )

    def deploy_service_onchain_from_safe(  # pylint: disable=too-many-statements,too-many-locals  # pragma: no cover
        self,
        service_config_id: str,
    ) -> None:
        """Deploy as service on-chain"""

        service = self.load(service_config_id=service_config_id)
        for chain in service.chain_configs.keys():
            self._deploy_service_onchain_from_safe(
                service_config_id=service_config_id,
                chain=chain,
            )

    def get_mech_configs(
        self,
        chain: str,
        ledger_api: LedgerApi,
        staking_program_id: str | None = None,
    ) -> MechMarketplaceConfig:
        """Get the mech configs."""
        sftxb = self.get_eth_safe_tx_builder(
            ledger_config=LedgerConfig(
                chain=Chain(chain),
                rpc=ledger_api.api.provider.endpoint_uri,
            )
        )
        staking_contract = get_staking_contract(
            chain=chain,
            staking_program_id=staking_program_id,
        )
        if staking_contract is None:
            return MechMarketplaceConfig(
                use_mech_marketplace=False,
                mech_marketplace_address=ZERO_ADDRESS,
                priority_mech_address=ZERO_ADDRESS,
                priority_mech_service_id=0,
            )

        target_staking_params = sftxb.get_staking_params(
            staking_contract=get_staking_contract(
                chain=chain,
                staking_program_id=staking_program_id,
            ),
        )

        try:
            # Try if activity checker is a MechActivityChecker contract
            mech_activity_contract = t.cast(
                MechActivityContract,
                MechActivityContract.from_dir(
                    directory=str(DATA_DIR / "contracts" / "mech_activity")
                ),
            )

            priority_mech_address = (
                mech_activity_contract.get_instance(
                    ledger_api=ledger_api,
                    contract_address=target_staking_params["activity_checker"],
                )
                .functions.agentMech()
                .call()
            )
            use_mech_marketplace = False
            mech_marketplace_address = ZERO_ADDRESS
            priority_mech_service_id = 0

        except Exception:  # pylint: disable=broad-except
            # Try if activity checker is a RequesterActivityChecker contract
            try:
                requester_activity_checker = t.cast(
                    RequesterActivityCheckerContract,
                    RequesterActivityCheckerContract.from_dir(
                        directory=str(
                            DATA_DIR / "contracts" / "requester_activity_checker"
                        )
                    ),
                )

                mech_marketplace_address = (
                    requester_activity_checker.get_instance(
                        ledger_api=ledger_api,
                        contract_address=target_staking_params["activity_checker"],
                    )
                    .functions.mechMarketplace()
                    .call()
                )

                use_mech_marketplace = True
                priority_mech_address, priority_mech_service_id = DEFAULT_PRIORITY_MECH[
                    mech_marketplace_address
                ]

            except Exception as e:  # pylint: disable=broad-except
                self.logger.debug(f"{e}: {traceback.format_exc()}")
                self.logger.warning(
                    "Cannot determine type of activity checker contract. Using default parameters. "
                    "NOTE: This will be an exception in the future!"
                )
                priority_mech_address = "0x77af31De935740567Cf4fF1986D04B2c964A786a"
                use_mech_marketplace = False
                mech_marketplace_address = ZERO_ADDRESS
                priority_mech_service_id = 0

        return MechMarketplaceConfig(
            use_mech_marketplace=use_mech_marketplace,
            mech_marketplace_address=mech_marketplace_address,
            priority_mech_address=priority_mech_address,
            priority_mech_service_id=priority_mech_service_id,
        )

    def _deploy_service_onchain_from_safe(  # pylint: disable=too-many-statements,too-many-locals,too-many-branches  # pragma: no cover
        self,
        service_config_id: str,
        chain: str,
    ) -> None:
        """Deploy service on-chain"""

        self.logger.info(f"_deploy_service_onchain_from_safe {chain=}")
        service = self.load(service_config_id=service_config_id)
        service.remove_latest_healthcheck()
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        user_params = chain_config.chain_data.user_params
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        safe = wallet.safes[Chain(chain)]

        # TODO fix this
        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

        self._enable_recovery_module(service_config_id=service_config_id, chain=chain)

        current_agent_id = None
        on_chain_state = OnChainState.NON_EXISTENT
        if chain_data.token > -1:
            self.logger.info("Syncing service state")
            info = sftxb.info(token_id=chain_data.token)
            on_chain_state = OnChainState(info["service_state"])
            chain_data.instances = info["instances"]
            chain_data.multisig = info["multisig"]
            current_agent_id = info["canonical_agents"][0]  # TODO Allow multiple agents
            service.store()
        self.logger.info(f"Service state: {on_chain_state.name}")

        current_staking_program = self._get_current_staking_program(service, chain)
        fallback_params = dict(  # nosec
            staking_contract=ZERO_ADDRESS,
            agent_ids=[user_params.agent_id],
            service_registry="0x9338b5153AE39BB89f50468E608eD9d764B755fD",  # nosec
            staking_token=ZERO_ADDRESS,  # nosec
            service_registry_token_utility="0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8",  # nosec
            min_staking_deposit=20000000000000000000,
            activity_checker=ZERO_ADDRESS,  # nosec
        )

        current_staking_params = sftxb.get_staking_params(
            fallback_params=fallback_params,
            staking_contract=get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=current_staking_program,
            ),
        )
        target_staking_params = sftxb.get_staking_params(
            fallback_params=fallback_params,
            staking_contract=get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=user_params.staking_program_id,
            ),
        )

        # TODO A customized, arbitrary computation mechanism should be devised.
        env_var_to_value = {}
        if chain == service.home_chain:
            mech_configs: MechMarketplaceConfig = self.get_mech_configs(
                chain=chain,
                ledger_api=sftxb.ledger_api,
                staking_program_id=user_params.staking_program_id,
            )

            if (
                "PRIORITY_MECH_ADDRESS" in service.env_variables
                and service.env_variables["PRIORITY_MECH_ADDRESS"]["provision_type"]
                == ServiceEnvProvisionType.USER
            ):
                mech_configs.priority_mech_address = service.env_variables[
                    "PRIORITY_MECH_ADDRESS"
                ]["value"]

            if (
                "PRIORITY_MECH_SERVICE_ID" in service.env_variables
                and service.env_variables["PRIORITY_MECH_SERVICE_ID"]["provision_type"]
                == ServiceEnvProvisionType.USER
            ):
                mech_configs.priority_mech_service_id = service.env_variables[
                    "PRIORITY_MECH_SERVICE_ID"
                ]["value"]

            env_var_to_value.update(
                {
                    "ARBITRUM_ONE_LEDGER_RPC": get_default_rpc(Chain.ARBITRUM_ONE),
                    "BASE_LEDGER_RPC": get_default_rpc(Chain.BASE),
                    "CELO_LEDGER_RPC": get_default_rpc(Chain.CELO),
                    "ETHEREUM_LEDGER_RPC": get_default_rpc(Chain.ETHEREUM),
                    "GNOSIS_LEDGER_RPC": get_default_rpc(Chain.GNOSIS),
                    "MODE_LEDGER_RPC": get_default_rpc(Chain.MODE),
                    "OPTIMISM_LEDGER_RPC": get_default_rpc(Chain.OPTIMISM),
                    "POLYGON_LEDGER_RPC": get_default_rpc(Chain.POLYGON),
                    "SOLANA_LEDGER_RPC": get_default_rpc(Chain.SOLANA),
                    f"{chain.upper()}_LEDGER_RPC": ledger_config.rpc,
                    "STAKING_CONTRACT_ADDRESS": target_staking_params.get(
                        "staking_contract"
                    ),
                    "STAKING_TOKEN_CONTRACT_ADDRESS": target_staking_params.get(
                        "staking_contract"
                    ),
                    "MECH_MARKETPLACE_CONFIG": (
                        f'{{"mech_marketplace_address":"{mech_configs.mech_marketplace_address}",'
                        f'"priority_mech_address":"{mech_configs.priority_mech_address}",'
                        f'"priority_mech_staking_instance_address":"0x998dEFafD094817EF329f6dc79c703f1CF18bC90",'
                        f'"priority_mech_service_id":{mech_configs.priority_mech_service_id},'
                        f'"requester_staking_instance_address":"{target_staking_params.get("staking_contract")}",'
                        f'"response_timeout":300}}'
                    ),
                    "ACTIVITY_CHECKER_CONTRACT_ADDRESS": target_staking_params.get(
                        "activity_checker"
                    ),
                    "MECH_ACTIVITY_CHECKER_CONTRACT": target_staking_params.get(
                        "activity_checker"
                    ),
                    "MECH_CONTRACT_ADDRESS": mech_configs.priority_mech_address,
                    "MECH_REQUEST_PRICE": "10000000000000000",
                    "USE_MECH_MARKETPLACE": mech_configs.use_mech_marketplace,
                }
            )

        # Set environment variables for the service
        for dir_name, env_var_name in (
            (AGENT_PERSISTENT_STORAGE_DIR, AGENT_PERSISTENT_STORAGE_ENV_VAR),
            (AGENT_LOG_DIR, AGENT_LOG_ENV_VAR),
        ):
            dir_path = service.path / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)
            env_var_to_value.update({env_var_name: str(dir_path)})

        service.update_env_variables_values(env_var_to_value)

        if user_params.use_staking:
            self.logger.info("Checking staking compatibility")

            # TODO: Missing check when the service is currently staked in a program, but needs to be staked
            # in a different target program. The In this case, balance = currently staked balance + safe balance

            if on_chain_state in (
                OnChainState.NON_EXISTENT,
                OnChainState.PRE_REGISTRATION,
            ):
                full_requirements = self.funding_manager._compute_protocol_asset_requirements(  # pylint: disable=protected-access
                    service
                )
                protocol_asset_requirements = dict(
                    full_requirements.get(chain, {}).get(safe, {})
                )
            elif on_chain_state == OnChainState.ACTIVE_REGISTRATION:
                full_requirements = self.funding_manager._compute_protocol_asset_requirements(  # pylint: disable=protected-access
                    service
                )
                protocol_asset_requirements = dict(
                    full_requirements.get(chain, {}).get(safe, {})
                )
                protocol_asset_requirements[target_staking_params["staking_token"]] = (
                    target_staking_params["min_staking_deposit"]
                    * NUM_LOCAL_AGENT_INSTANCES
                )
            else:
                protocol_asset_requirements = {}

            for asset, amount in protocol_asset_requirements.items():
                balance = get_asset_balance(
                    ledger_api=sftxb.ledger_api,
                    asset_address=asset,
                    address=safe,
                )
                if balance < amount:
                    raise ValueError(
                        f"Address {safe} has insufficient balance for asset {asset}: "
                        f"required {amount}, available {balance}."
                    )

        # TODO Handle this in a more graceful way.
        agent_id = (
            target_staking_params["agent_ids"][0]
            if target_staking_params["agent_ids"]
            else user_params.agent_id
        )
        target_staking_params["agent_ids"] = [agent_id]

        on_chain_metadata = self._get_on_chain_metadata(chain_config=chain_config)
        on_chain_hash = on_chain_metadata.get("code_uri", "")[len(IPFS_URI_PREFIX) :]
        on_chain_description = on_chain_metadata.get("description")
        needs_update_agent_addresses = set(chain_data.instances) != set(
            service.agent_addresses
        )

        current_agent_bond = sftxb.get_agent_bond(
            service_id=chain_data.token, agent_id=target_staking_params["agent_ids"][0]
        )

        is_first_mint = (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.NON_EXISTENT
        )
        current_staking_program = self._get_current_staking_program(service, chain)

        is_update = (
            (not is_first_mint)
            and (on_chain_hash is not None)
            and (
                # TODO Discuss how to manage on-chain hash updates with staking programs.
                # on_chain_hash != service.hash or  # noqa
                current_agent_id != target_staking_params["agent_ids"][0]
                # TODO This has to be removed for Optimus (needs to be properly implemented). Needs to be put back for Trader!
                or (
                    user_params.use_staking
                    and current_agent_bond
                    != target_staking_params["min_staking_deposit"]
                )
                # TODO Missing complete this check for non-staked services it should compare the current_agent_bond from the protocol, now it's only read for the staking contract.
                or current_staking_params["staking_token"]
                != target_staking_params["staking_token"]
                or on_chain_description != service.description
                or needs_update_agent_addresses
            )
        )

        self.logger.info(f"{chain_data.token=}")
        self.logger.info(f"{user_params.use_staking=}")
        self.logger.info(f"{current_staking_program=}")
        self.logger.info(f"{user_params.staking_program_id=}")
        self.logger.info(f"{on_chain_hash=}")
        self.logger.info(f"{service.hash=}")
        self.logger.info(f"{current_agent_id=}")
        self.logger.info(f"{target_staking_params['agent_ids']=}")
        self.logger.info(f"{current_agent_bond=}")
        self.logger.info(f"{target_staking_params['min_staking_deposit']=}")
        self.logger.info(f"{is_first_mint=}")
        self.logger.info(f"{is_update=}")

        # For an update, prefer folding the teardown (unstake → terminate →
        # unbond → recover_access) into the update mega-batch below so the whole
        # update settles as one Master-Safe MultiSend. Falls back to the legacy
        # stepwise terminate + swap/recovery only when recover_access is needed
        # but cannot be performed in-batch.
        update_teardown_prefix: t.Optional[t.List[t.Tuple[t.Dict, str]]] = None
        if is_update:
            update_teardown_prefix = self._build_update_teardown_prefix(
                service=service,
                chain=chain,
                sftxb=sftxb,
                chain_data=chain_data,
                master_safe=safe,
            )
            if update_teardown_prefix is None:
                self.terminate_service_on_chain_from_safe(
                    service_config_id=service_config_id, chain=chain
                )
                if (
                    self._get_on_chain_state(service=service, chain=chain)
                    == OnChainState.PRE_REGISTRATION
                ):
                    self.logger.info("Execute recovery module operations")
                    self._execute_recovery_module_flow_from_safe(
                        service_config_id=service_config_id, chain=chain
                    )
                    # Update mint is included in the mega-batch below

        # Mint service
        if (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.NON_EXISTENT
        ):
            if user_params.use_staking and not sftxb.staking_slots_available(
                staking_contract=get_staking_contract(
                    chain=ledger_config.chain,
                    staking_program_id=user_params.staking_program_id,
                ),
            ):
                raise ValueError("No staking slots available")

            self.logger.info("Minting service")
            receipt = (
                sftxb.new_tx()
                .add(
                    sftxb.get_mint_tx_data(
                        package_path=service.package_absolute_path,
                        agent_id=agent_id,
                        number_of_slots=NUM_LOCAL_AGENT_INSTANCES,
                        cost_of_bond=(
                            target_staking_params["min_staking_deposit"]
                            if user_params.use_staking
                            else user_params.cost_of_bond
                        ),
                        threshold=len(service.agent_addresses),
                        nft=IPFSHash(user_params.nft),
                        update_token=None,
                        token=(
                            target_staking_params["staking_token"]
                            if user_params.use_staking
                            else None
                        ),
                        metadata_description=service.description,
                        skip_depencency_check=self.skip_depencency_check,
                    )
                )
                .settle()
            )
            event_data, *_ = t.cast(
                t.Tuple,
                registry_contracts.service_registry.process_receipt(
                    ledger_api=sftxb.ledger_api,
                    contract_address=target_staking_params["service_registry"],
                    event="CreateService",
                    receipt=receipt,
                ).get("events"),
            )
            chain_data.token = event_data["args"]["serviceId"]
            service.store()

        # ── Mega-batch happy path ─────────────────────────────────
        # When starting from PRE_REGISTRATION, batch the entire
        # activate → register → deploy (→ stake) cycle into one
        # Master Safe MultiSend transaction.
        is_initial_funding = False
        mega_batch_done = False

        # An update folds its teardown into this batch, so enter from the live
        # (pre-teardown) state too — the prepended sub-txs drive the registry to
        # PRE_REGISTRATION (via unbond, or terminate alone from
        # ACTIVE_REGISTRATION) before the update mint.
        in_batch_teardown = bool(update_teardown_prefix)
        teardown_labels = {label for _, label in update_teardown_prefix or []}
        # A re-stake into the same program frees its own slot via the in-batch
        # unstake, so the live slot count being full is not a blocker.
        teardown_frees_target_slot = (
            in_batch_teardown
            and current_staking_program == user_params.staking_program_id
            and "unstake" in teardown_labels
        )
        # recover_access (when present) transfers service-Safe control to the
        # Master Safe earlier in this batch, so the deploy payload's live
        # sole-owner pre-check must be skipped.
        skip_owner_check = "recover_access" in teardown_labels
        if (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.PRE_REGISTRATION
            or in_batch_teardown
        ):
            self.logger.info(
                "Mega-batch path: "
                + (
                    "teardown → update → "
                    if in_batch_teardown
                    else ("update → " if is_update else "")
                )
                + "activate → register → deploy"
                + (" → stake" if user_params.use_staking else "")
            )

            # Pre-flight: staking slot/reward availability
            include_staking = False
            target_staking_contract: t.Optional[str] = None
            if user_params.use_staking:
                target_staking_contract = get_staking_contract(
                    chain=ledger_config.chain,
                    staking_program_id=user_params.staking_program_id,
                )
                if not sftxb.staking_slots_available(
                    staking_contract=target_staking_contract,
                ):
                    # A re-stake into the same program frees its own slot via
                    # the in-batch unstake, so the live count being full is not
                    # a blocker in that case.
                    if not teardown_frees_target_slot:
                        raise ValueError("No staking slots available")
                    self.logger.info(
                        "Target staking slot occupied by this service; it will "
                        "be freed by the in-batch unstake."
                    )
                if sftxb.staking_rewards_available(target_staking_contract):
                    include_staking = True
                else:
                    self.logger.warning(
                        "No staking rewards available, omitting stake from mega-batch"
                    )

            mega_tx = sftxb.new_tx(gas_fallback=_MEGA_BATCH_GAS_FALLBACK)

            # --- In-batch teardown (update path): unstake → terminate →
            #     unbond → recover_access, as dictated by the live state ---
            if update_teardown_prefix:
                for tx_data, label in update_teardown_prefix:
                    mega_tx.add(tx_data, label=label)

            # --- Update mint (update path only) ---
            if is_update:
                self.logger.info("Including update mint in mega-batch")
                update_mint_data = sftxb.get_mint_tx_data(
                    package_path=service.package_absolute_path,
                    agent_id=agent_id,
                    number_of_slots=NUM_LOCAL_AGENT_INSTANCES,
                    cost_of_bond=(
                        target_staking_params["min_staking_deposit"]
                        if user_params.use_staking
                        else user_params.cost_of_bond
                    ),
                    threshold=len(service.agent_addresses),
                    nft=IPFSHash(user_params.nft),
                    update_token=chain_data.token,
                    token=(
                        target_staking_params["staking_token"]
                        if user_params.use_staking
                        else None
                    ),
                    metadata_description=service.description,
                    skip_depencency_check=self.skip_depencency_check,
                )
                mega_tx.add(update_mint_data, label="update_mint")

            # --- OLAS approval + activate ---
            # The OLAS bond equals the target program's min staking deposit:
            # the value update_mint writes and that activate/register will pull
            # from the token utility. Read it from target params (not an
            # on-chain get_agent_bond) because the update mint that sets it is a
            # pending sub-tx earlier in this same batch, so the chain still
            # reports the pre-update bond at build time.
            cost_of_bond = user_params.cost_of_bond
            if user_params.use_staking:
                token_utility = target_staking_params["service_registry_token_utility"]
                olas_token = target_staking_params["staking_token"]
                cost_of_bond_olas = target_staking_params["min_staking_deposit"]
                approve_act = sftxb.get_erc20_approval_data(
                    spender=token_utility,
                    amount=cost_of_bond_olas,
                    erc20_contract=olas_token,
                )
                mega_tx.add(approve_act, label="erc20_approve_activate")
                cost_of_bond = MIN_AGENT_BOND

            activate_data = sftxb.get_activate_data(
                service_id=chain_data.token,
                cost_of_bond=cost_of_bond,
            )
            mega_tx.add(activate_data, label="activate")

            # --- OLAS approval + register ---
            cost_of_bond_reg = user_params.cost_of_bond
            if user_params.use_staking:
                approve_reg = sftxb.get_erc20_approval_data(
                    spender=token_utility,
                    amount=cost_of_bond_olas,
                    erc20_contract=olas_token,
                )
                mega_tx.add(approve_reg, label="erc20_approve_register")
                cost_of_bond_reg = MIN_AGENT_BOND

            register_data = sftxb.get_register_instances_data(
                service_id=chain_data.token,
                instances=service.agent_addresses,
                agents=[agent_id for _ in service.agent_addresses],
                cost_of_bond=cost_of_bond_reg,
            )
            mega_tx.add(register_data, label="register_instances")

            # --- Deploy ---
            info = sftxb.info(token_id=chain_data.token)
            service_safe_address = info["multisig"]
            if service_safe_address == ZERO_ADDRESS:
                reuse_multisig = False
                is_initial_funding = True
                is_recovery_module_enabled = True
            else:
                reuse_multisig = True
                is_recovery_module_enabled = (
                    registry_contracts.gnosis_safe.is_module_enabled(
                        ledger_api=sftxb.ledger_api,
                        contract_address=service_safe_address,
                        module_address=CONTRACTS[Chain(chain)]["recovery_module"],
                    ).get("enabled")
                )
            self.logger.info(f"{reuse_multisig=}")

            service_public_id = PublicId.from_str(service.service_public_id())
            use_poly_safe = service_public_id.name in POLY_SAFE_SERVICE_NAMES
            deploy_messages = sftxb.get_deploy_data_from_safe(
                service_id=chain_data.token,
                reuse_multisig=reuse_multisig,
                master_safe=safe,
                use_recovery_module=is_recovery_module_enabled,
                use_poly_safe=use_poly_safe,
                agent_eoa_crypto=self.keys_manager.get_crypto_instance(
                    service.agent_addresses[0]
                ),
                skip_owner_check=skip_owner_check,
            )
            for msg in deploy_messages:
                mega_tx.add(msg, label="deploy")

            # --- Staking (if enabled and slots/rewards available) ---
            if include_staking and target_staking_contract is not None:
                # A re-stake into the same program is preceded by an in-batch
                # unstake, so the live "already staked"/slots guards are
                # premature — skip them when that teardown is present.
                nft_approve = sftxb.get_staking_approval_data(
                    service_id=chain_data.token,
                    service_registry=CONTRACTS[ledger_config.chain]["service_registry"],
                    staking_contract=target_staking_contract,
                    skip_compatibility_check=teardown_frees_target_slot,
                )
                mega_tx.add(nft_approve, label="staking_nft_approve")

                staking_params = sftxb.get_staking_params(
                    staking_contract=target_staking_contract
                )
                for token_contract, min_amount in staking_params[
                    "additional_staking_tokens"
                ].items():
                    token_appr = sftxb.get_erc20_approval_data(
                        spender=target_staking_contract,
                        amount=min_amount,
                        erc20_contract=token_contract,
                    )
                    mega_tx.add(
                        token_appr,
                        label=f"staking_token_approve_{token_contract[:10]}",
                    )

                stake_data = sftxb.get_staking_data(
                    service_id=chain_data.token,
                    staking_contract=target_staking_contract,
                    skip_compatibility_check=teardown_frees_target_slot,
                )
                mega_tx.add(stake_data, label="stake")

            # --- Settle ---
            try:
                mega_tx.settle()
            except Exception:
                self.logger.error("Mega-batch reverted, running revert attribution")
                try:
                    for label, sub_tx in mega_tx.labeled_txs:
                        error = simulate_safe_sub_tx(
                            ledger_api=sftxb.ledger_api,
                            safe=safe,
                            tx=sub_tx,
                        )
                        if error is not None:
                            self.logger.error(
                                f"Mega-batch sub-tx '{label}' would revert: " f"{error}"
                            )
                except Exception as attribution_error:  # pylint: disable=broad-except
                    # Diagnostics-only; never mask the original settle failure.
                    self.logger.warning(
                        "Revert attribution failed "
                        f"({type(attribution_error).__name__}: {attribution_error})"
                    )
                raise

            mega_batch_done = True

        if not mega_batch_done:
            # ── Stepwise resume / repair path ─────────────────
            # Services interrupted mid-cycle or left mid-state by
            # older versions enter at their actual on-chain state
            # and proceed step by step.

            # Activate service (approve + activate in one tx)
            if (
                self._get_on_chain_state(service=service, chain=chain)
                == OnChainState.PRE_REGISTRATION
            ):
                cost_of_bond = user_params.cost_of_bond
                activate_tx = sftxb.new_tx()
                if user_params.use_staking:
                    token_utility = target_staking_params[
                        "service_registry_token_utility"
                    ]
                    olas_token = target_staking_params["staking_token"]
                    self.logger.info(
                        f"Approving OLAS as bonding token from {safe} to {token_utility}"
                    )
                    cost_of_bond = registry_contracts.service_registry_token_utility.get_agent_bond(
                        ledger_api=sftxb.ledger_api,
                        contract_address=token_utility,
                        service_id=chain_data.token,
                        agent_id=agent_id,
                    ).get(
                        "bond"
                    )
                    activate_tx.add(
                        sftxb.get_erc20_approval_data(
                            spender=token_utility,
                            amount=cost_of_bond,
                            erc20_contract=olas_token,
                        )
                    )
                    cost_of_bond = MIN_AGENT_BOND

                self.logger.info("Activating service")

                native_balance = get_asset_balance(
                    ledger_api=sftxb.ledger_api,
                    asset_address=ZERO_ADDRESS,
                    address=safe,
                )

                if (
                    native_balance < cost_of_bond
                ):  # TODO check that this is the security deposit
                    message = f"Cannot activate service: address {safe} {native_balance=} < {cost_of_bond=}."
                    self.logger.error(message)
                    raise ValueError(message)

                activate_tx.add(
                    sftxb.get_activate_data(
                        service_id=chain_data.token,
                        cost_of_bond=cost_of_bond,
                    )
                ).settle()

            # Register agent instances (approve + register in one tx)
            if (
                self._get_on_chain_state(service=service, chain=chain)
                == OnChainState.ACTIVE_REGISTRATION
            ):
                cost_of_bond = user_params.cost_of_bond
                register_tx = sftxb.new_tx()
                if user_params.use_staking:
                    token_utility = target_staking_params[
                        "service_registry_token_utility"
                    ]
                    olas_token = target_staking_params["staking_token"]
                    self.logger.info(
                        f"Approving OLAS as bonding token from {safe} to {token_utility}"
                    )
                    cost_of_bond = registry_contracts.service_registry_token_utility.get_agent_bond(
                        ledger_api=sftxb.ledger_api,
                        contract_address=token_utility,
                        service_id=chain_data.token,
                        agent_id=agent_id,
                    ).get(
                        "bond"
                    )
                    register_tx.add(
                        sftxb.get_erc20_approval_data(
                            spender=token_utility,
                            amount=cost_of_bond,
                            erc20_contract=olas_token,
                        )
                    )
                    cost_of_bond = MIN_AGENT_BOND

                self.logger.info(
                    f"Registering agent instances: {chain_data.token} -> {service.agent_addresses}"
                )

                native_balance = get_asset_balance(
                    ledger_api=sftxb.ledger_api,
                    asset_address=ZERO_ADDRESS,
                    address=safe,
                )

                if native_balance < cost_of_bond * len(service.agent_addresses):
                    message = f"Cannot register agent instances: address {safe} {native_balance=} < {cost_of_bond=}."
                    self.logger.error(message)
                    raise ValueError(message)

                register_tx.add(
                    sftxb.get_register_instances_data(
                        service_id=chain_data.token,
                        instances=service.agent_addresses,
                        agents=[agent_id for _ in service.agent_addresses],
                        cost_of_bond=cost_of_bond,
                    )
                ).settle()

            # Deploy service
            if (
                self._get_on_chain_state(service=service, chain=chain)
                == OnChainState.FINISHED_REGISTRATION
            ):
                self.logger.info("Deploying service")

                info = sftxb.info(token_id=chain_data.token)
                service_safe_address = info["multisig"]
                if service_safe_address == ZERO_ADDRESS:
                    reuse_multisig = False
                    is_initial_funding = True
                    is_recovery_module_enabled = True
                else:
                    reuse_multisig = True
                    is_initial_funding = False
                    is_recovery_module_enabled = (
                        registry_contracts.gnosis_safe.is_module_enabled(
                            ledger_api=sftxb.ledger_api,
                            contract_address=service_safe_address,
                            module_address=CONTRACTS[Chain(chain)]["recovery_module"],
                        ).get("enabled")
                    )

                self.logger.info(f"{reuse_multisig=}")
                self.logger.info(f"{is_recovery_module_enabled=}")

                service_public_id = PublicId.from_str(service.service_public_id())
                use_poly_safe = service_public_id.name in POLY_SAFE_SERVICE_NAMES

                self.logger.info(f"{use_poly_safe=}")
                messages = sftxb.get_deploy_data_from_safe(
                    service_id=chain_data.token,
                    reuse_multisig=reuse_multisig,
                    master_safe=safe,
                    use_recovery_module=is_recovery_module_enabled,
                    use_poly_safe=use_poly_safe,
                    agent_eoa_crypto=self.keys_manager.get_crypto_instance(
                        service.agent_addresses[0]
                    ),
                )
                tx = sftxb.new_tx()
                for message in messages:
                    tx.add(message)
                tx.settle()

        # Update local Service
        info = sftxb.info(token_id=chain_data.token)
        chain_data.instances = info["instances"]
        chain_data.multisig = info["multisig"]
        service.store()

        if is_initial_funding:
            self.funding_manager.fund_service_initial(service)

        # Set ERC8004 agent wallet if not set already
        try:
            # Check if required contracts are available
            required_contracts = [
                "erc8004_identity_registry",
                "erc8004_identity_registry_bridger",
                "sign_message_lib",
            ]
            if not all(
                contract in CONTRACTS[Chain(chain)] for contract in required_contracts
            ):
                raise UnsupportedChainError("Missing ERC8004 contracts")

            identity_registry_bridger = (
                registry_contracts.erc8004_identity_registry_bridger.get_instance(
                    ledger_api=sftxb.ledger_api,
                    contract_address=CONTRACTS[Chain(chain)][
                        "erc8004_identity_registry_bridger"
                    ],
                )
            )
            erc8004_agent_id = identity_registry_bridger.functions.mapServiceIdAgentIds(
                chain_data.token
            ).call()

            # Get current registered agent wallet
            identity_registry = (
                registry_contracts.erc8004_identity_registry.get_instance(
                    ledger_api=sftxb.ledger_api,
                    contract_address=CONTRACTS[Chain(chain)][
                        "erc8004_identity_registry"
                    ],
                )
            )
            registered_wallet = identity_registry.functions.getAgentWallet(
                erc8004_agent_id
            ).call()

            # Check if agent wallet needs to be set (new multisig or unset wallet)
            if chain_data.multisig != registered_wallet:
                self.logger.info(
                    f"Agent wallet setup needed: "
                    f"service_id={chain_data.token}, "
                    f"erc8004_agent_id={erc8004_agent_id}, "
                    f"new_wallet={chain_data.multisig}, "
                    f"registered_wallet={registered_wallet}"
                )

                # Get current block timestamp and compute deadline (5 minutes = 300 seconds)
                latest_block = sftxb.ledger_api.api.eth.get_block("latest")
                deadline = (
                    latest_block["timestamp"] + 300
                )  # MAX_DEADLINE_DELAY = 5 minutes

                # Get required contract addresses
                ir_address = CONTRACTS[Chain(chain)]["erc8004_identity_registry"]
                irb_address = CONTRACTS[Chain(chain)][
                    "erc8004_identity_registry_bridger"
                ]
                sign_message_lib_address = CONTRACTS[Chain(chain)]["sign_message_lib"]

                # Get transaction data for agent wallet setup
                agent_wallet_txs, _ = sftxb.get_agent_wallet_setup_txs(
                    agent_id=erc8004_agent_id,
                    new_wallet=chain_data.multisig,
                    identity_registry_address=ir_address,
                    identity_registry_bridger_address=irb_address,
                    sign_message_lib_address=sign_message_lib_address,
                    deadline=deadline,
                )

                agent_crypto = self.keys_manager.get_crypto_instance(
                    service.agent_addresses[0]
                )
                asftx = sftxb.new_tx(crypto=agent_crypto, safe=chain_data.multisig)
                for agent_wallet_tx in agent_wallet_txs:
                    asftx.add(agent_wallet_tx)

                receipt = asftx.settle()
                if receipt["status"] != 1:
                    self.logger.error(
                        f"Agent wallet setup transaction failed: {receipt}"
                    )
                    raise RuntimeError("Agent wallet setup transaction failed")

                self.logger.info(
                    f"Agent wallet setup completed for service_id={chain_data.token}, "
                    f"erc8004_agent_id={erc8004_agent_id}"
                )
            else:
                self.logger.info(
                    f"ERC8004 Agent wallet already set for service_id={chain_data.token}, "
                    f"erc8004_agent_id={erc8004_agent_id}"
                )
        except UnsupportedChainError:
            self.logger.warning(
                f"Skipping ERC8004 agent wallet setup: contracts not configured for {chain}"
            )
        except Exception:  # pylint: disable=broad-except
            self.logger.error(
                f"Failed to set agent wallet for service_id={chain_data.token}: {traceback.format_exc()}"
            )

        # TODO: this is a patch for modius, to be standardized
        staking_chain = None
        for chain_, config in service.chain_configs.items():
            if config.chain_data.user_params.use_staking:
                staking_chain = chain_
                break

        service.update_env_variables_values(
            {
                "SAFE_CONTRACT_ADDRESSES": json.dumps(
                    {
                        chain: config.chain_data.multisig
                        for chain, config in service.chain_configs.items()
                    },
                    separators=(",", ":"),
                ),
                "STAKING_CHAIN": staking_chain,
            }
        )
        service.store()

        if user_params.use_staking and not mega_batch_done:
            self.stake_service_on_chain_from_safe(
                service_config_id=service_config_id, chain=chain
            )

    def _terminate_and_unbond(
        self,
        sftxb: EthSafeTxBuilder,
        service: Service,
        chain: str,
        chain_data: t.Any,
    ) -> None:
        """Batch terminate + unbond into one tx when applicable."""
        on_chain_state = self._get_on_chain_state(service=service, chain=chain)
        needs_unbond = on_chain_state == OnChainState.TERMINATED_BONDED

        if on_chain_state == OnChainState.ACTIVE_REGISTRATION:
            # ACTIVE_REGISTRATION → terminate transitions to PRE_REGISTRATION
            # (not TERMINATED_BONDED), so unbond must NOT be batched here.
            self.logger.info("Terminating from ACTIVE_REGISTRATION (no unbond)")
            sftxb.new_tx().add(
                sftxb.get_terminate_data(service_id=chain_data.token)
            ).settle()
        elif on_chain_state in (
            OnChainState.FINISHED_REGISTRATION,
            OnChainState.DEPLOYED,
        ):
            # These states transition through TERMINATED_BONDED, so
            # terminate + unbond can safely be batched in one MultiSend.
            self.logger.info("Batching terminate → unbond")
            (
                sftxb.new_tx()
                .add(sftxb.get_terminate_data(service_id=chain_data.token))
                .add(sftxb.get_unbond_data(service_id=chain_data.token))
                .settle()
            )
        elif needs_unbond:
            self.logger.info("Unbonding service")
            sftxb.new_tx().add(
                sftxb.get_unbond_data(
                    service_id=chain_data.token,
                )
            ).settle()

    def _build_update_teardown_prefix(  # pylint: disable=too-many-locals,too-many-return-statements  # pragma: no cover
        self,
        service: Service,
        chain: str,
        sftxb: EthSafeTxBuilder,
        chain_data: t.Any,
        master_safe: str,
    ) -> t.Optional[t.List[t.Tuple[t.Dict, str]]]:
        """Build the in-batch teardown prefix for an update mega-batch.

        Returns the ``(tx_data, label)`` pairs to prepend to the update
        mega-batch — unstake → terminate → unbond → recover_access as dictated
        by the live on-chain state — so the whole update settles as one
        Master-Safe MultiSend.

        Returns ``None`` when the combined path is not applicable and the
        caller must fall back to the legacy stepwise terminate + swap/recovery
        flow. That happens in three cases: there is no prior service Safe to
        reuse; the service is staked but cannot be unstaked yet; or
        ``recover_access`` is needed (the Master Safe is not the service Safe
        owner) but cannot be performed in-batch (recovery module not enabled, or
        the agent is not the sole service Safe owner). When ``recover_access``
        is not needed, the combined path proceeds without it.
        """
        state = self._get_on_chain_state(service=service, chain=chain)
        if chain_data.multisig in (None, ZERO_ADDRESS):
            # No service Safe to reuse; let the standard path handle minting.
            return None

        service_id = chain_data.token
        current_staking_program = self._get_current_staking_program(service, chain)
        is_staked = current_staking_program is not None
        staking_contract = (
            get_staking_contract(
                chain=Chain(chain),
                staking_program_id=current_staking_program,
            )
            if is_staked
            else None
        )

        if is_staked and not sftxb.can_unstake(
            service_id=service_id, staking_contract=staking_contract
        ):
            # Cannot unstake yet (e.g. still within the staking lock window) ->
            # the service cannot be torn down, so the update cannot proceed this
            # cycle. The legacy fallback only claims rewards and returns.
            self.logger.warning(
                "Update teardown: service is staked and cannot be unstaked yet; "
                "the update will not be applied until it becomes unstakeable."
            )
            return None

        # recover_access is only needed when the Master Safe is not already the
        # service Safe owner.
        service_safe_owners = sftxb.get_service_safe_owners(service_id=service_id)
        master_is_owner = service_safe_owners == [master_safe]
        agent_is_owner = service_safe_owners == [service.agent_addresses[0]]
        need_recover = not master_is_owner
        if need_recover:
            recovery_enabled = registry_contracts.gnosis_safe.is_module_enabled(
                ledger_api=sftxb.ledger_api,
                contract_address=chain_data.multisig,
                module_address=CONTRACTS[Chain(chain)]["recovery_module"],
            ).get("enabled")
            if not (agent_is_owner and recovery_enabled):
                self.logger.info(
                    "Update teardown: recover_access needed but not feasible "
                    f"({agent_is_owner=}, {recovery_enabled=}); using legacy path"
                )
                return None

        # Eligible for the combined path
        prefix: t.List[t.Tuple[t.Dict, str]] = []
        if is_staked:
            staking_state = sftxb.staking_status(
                service_id=service_id, staking_contract=staking_contract
            )
            if staking_state in {StakingState.STAKED, StakingState.EVICTED}:
                prefix.append(
                    (
                        sftxb.get_unstaking_data(
                            service_id=service_id,
                            staking_contract=staking_contract,
                        ),
                        "unstake",
                    )
                )

        if state in _STATES_REQUIRING_TERMINATE:
            prefix.append(
                (sftxb.get_terminate_data(service_id=service_id), "terminate")
            )
        # ACTIVE_REGISTRATION terminates straight to PRE_REGISTRATION (no
        # bonded state), so unbond is only valid from the states that pass
        # through TERMINATED_BONDED.
        if state in _STATES_REQUIRING_UNBOND:
            prefix.append((sftxb.get_unbond_data(service_id=service_id), "unbond"))

        if need_recover:
            # Valid once the service reaches PRE_REGISTRATION earlier in the
            # same MultiSend — via unbond (FINISHED_REGISTRATION / DEPLOYED /
            # TERMINATED_BONDED) or via terminate alone (ACTIVE_REGISTRATION,
            # which skips unbond). Recovers service Safe control to Master Safe.
            prefix.append(
                (
                    sftxb.get_recover_access_data(service_id=service_id),
                    "recover_access",
                )
            )

        return prefix

    def terminate_service_on_chain_from_safe(  # pylint: disable=too-many-locals,too-many-statements  # pragma: no cover
        self,
        service_config_id: str,
        chain: str,
    ) -> None:
        """Terminate service on-chain"""

        self.logger.info("terminate_service_on_chain_from_safe")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        master_safe = wallet.safes[Chain(chain)]  # type: ignore

        # TODO fixme
        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)

        # Determine if the service is staked in a known staking program
        current_staking_program = self._get_current_staking_program(
            service,
            chain,
        )
        is_staked = current_staking_program is not None

        can_unstake = False
        if current_staking_program is not None:
            can_unstake = sftxb.can_unstake(
                service_id=chain_data.token,
                staking_contract=get_staking_contract(
                    chain=ledger_config.chain,
                    staking_program_id=current_staking_program,
                ),
            )

        # Cannot unstake, terminate flow.
        if is_staked and not can_unstake:
            self.logger.warning(
                "Service cannot be terminated on-chain: cannot unstake yet."
            )
            return

        if is_staked and can_unstake:
            # Claim + reward transfer stays separate (different signer
            # for the reward transfer from service safe).
            self.claim_on_chain_from_safe(
                service_config_id=service_config_id,
                chain=chain,
            )

            # Batch unstake → terminate → unbond in one tx.
            # After unstake the service is DEPLOYED mid-tx, so
            # terminate is valid; after terminate it is
            # TERMINATED_BONDED, so unbond is valid.
            staking_contract = get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=current_staking_program,
            )
            state = sftxb.staking_status(
                service_id=chain_data.token,
                staking_contract=staking_contract,
            )
            if state in {StakingState.STAKED, StakingState.EVICTED}:
                self.logger.info("Batching unstake → terminate → unbond")
                (
                    sftxb.new_tx()
                    .add(
                        sftxb.get_unstaking_data(
                            service_id=chain_data.token,
                            staking_contract=staking_contract,
                        )
                    )
                    .add(
                        sftxb.get_terminate_data(
                            service_id=chain_data.token,
                        )
                    )
                    .add(
                        sftxb.get_unbond_data(
                            service_id=chain_data.token,
                        )
                    )
                    .settle()
                )
            else:
                self.logger.info(
                    f"Service not staked after claim (state={state}), "
                    "falling through to stepwise terminate"
                )
                # Fall through to stepwise terminate+unbond below
                self._terminate_and_unbond(sftxb, service, chain, chain_data)
        elif is_staked:
            # At least claim the rewards if we cannot unstake yet
            self.claim_on_chain_from_safe(
                service_config_id=service_config_id,
                chain=chain,
            )
            return
        else:
            # Not staked: batch terminate + unbond
            self._terminate_and_unbond(sftxb, service, chain, chain_data)

        # Swap service safe
        current_safe_owners = sftxb.get_service_safe_owners(service_id=chain_data.token)
        counter_current_safe_owners = Counter(s.lower() for s in current_safe_owners)
        counter_instances = Counter(s.lower() for s in service.agent_addresses)

        if counter_current_safe_owners == counter_instances:
            requirements = ChainAmounts(
                {
                    chain: {
                        current_safe_owners[0]: {
                            ZERO_ADDRESS: chain_data.user_params.fund_requirements[
                                ZERO_ADDRESS
                            ].agent
                        }
                    }
                }
            )
            balances = ChainAmounts(
                {
                    chain: {
                        current_safe_owners[0]: {
                            ZERO_ADDRESS: get_asset_balance(
                                ledger_api=sftxb.ledger_api,
                                asset_address=ZERO_ADDRESS,
                                address=service.agent_addresses[0],
                            )
                        }
                    }
                }
            )
            if balances < requirements * DEFAULT_EOA_THRESHOLD:
                self.logger.info("[SERVICE MANAGER] Funding agent EOA for Safe swap.")
                shortfalls = ChainAmounts.shortfalls(
                    requirements=requirements, balances=balances
                )
                try:
                    self.funding_manager.fund_chain_amounts(shortfalls)
                except InsufficientFundsException as e:
                    recovery_module_address = CONTRACTS[Chain(chain)]["recovery_module"]
                    is_recovery_module_enabled = (
                        registry_contracts.gnosis_safe.is_module_enabled(
                            ledger_api=sftxb.ledger_api,
                            contract_address=chain_data.multisig,
                            module_address=recovery_module_address,
                        ).get("enabled")
                    )
                    if is_recovery_module_enabled:
                        self.logger.info(
                            "[SERVICE MANAGER] Could not fund Agent EOA for service swap, but recovery module is enabled."
                        )
                        return
                    raise e

            self._enable_recovery_module(
                service_config_id=service_config_id, chain=chain
            )
            self.logger.info("[SERVICE MANAGER] Swapping Safe owners")
            owner_crypto = self.keys_manager.get_crypto_instance(
                address=current_safe_owners[0]
            )
            sftxb.swap(
                service_id=chain_data.token,
                multisig=chain_data.multisig,  # TODO this can be read from the registry
                owner_cryptos=[owner_crypto],  # TODO allow multiple owners
                new_owner_address=(
                    master_safe if master_safe else wallet.crypto.address
                ),  # TODO it should always be safe address
            )

    def _execute_recovery_module_flow_from_safe(  # pylint: disable=too-many-locals  # pragma: no cover
        self,
        service_config_id: str,
        chain: str,
    ) -> None:
        """Execute recovery module operations from Safe"""
        self.logger.info(f"_execute_recovery_module_operations_from_safe {chain=}")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        chain_data = chain_config.chain_data
        ledger_config = chain_config.ledger_config
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        safe = wallet.safes[Chain(chain)]

        if chain_data.token == NON_EXISTENT_TOKEN:
            self.logger.info("Service is not minted.")
            return

        info = sftxb.info(token_id=chain_data.token)
        service_safe_address = info["multisig"]
        on_chain_state = OnChainState(info["service_state"])

        if service_safe_address == ZERO_ADDRESS:
            self.logger.info("Service Safe is not deployed.")
            return

        recovery_module_address = CONTRACTS[Chain(chain)]["recovery_module"]
        is_recovery_module_enabled = registry_contracts.gnosis_safe.is_module_enabled(
            ledger_api=sftxb.ledger_api,
            contract_address=service_safe_address,
            module_address=recovery_module_address,
        ).get("enabled")

        service_safe_owners = sftxb.get_service_safe_owners(service_id=chain_data.token)
        master_safe_is_service_safe_owner = service_safe_owners == [safe]

        self.logger.info(f"{is_recovery_module_enabled=}")
        self.logger.info(f"{master_safe_is_service_safe_owner=}")

        if not is_recovery_module_enabled and not master_safe_is_service_safe_owner:
            self.logger.info(
                "Recovery module is not enabled and Master Safe is not service Safe owner. Skipping recovery operations."
            )
            return

        if not is_recovery_module_enabled:
            self._enable_recovery_module(
                service_config_id=service_config_id, chain=chain
            )

        if (
            not master_safe_is_service_safe_owner
            and on_chain_state == OnChainState.PRE_REGISTRATION
        ):
            self.logger.info("Recovering service Safe access through recovery module.")
            sftxb.new_tx().add(
                sftxb.get_recover_access_data(
                    service_id=chain_data.token,
                )
            ).settle()
            self.logger.info("Recovering service Safe done.")

    def _enable_recovery_module(  # pylint: disable=too-many-locals  # pragma: no cover
        self,
        service_config_id: str,
        chain: str,
    ) -> None:
        """Enable recovery module"""
        self.logger.info(f"_enable_recovery_module {chain=}")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        chain_data = chain_config.chain_data
        ledger_config = chain_config.ledger_config
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        safe = wallet.safes[Chain(chain)]

        if chain_data.token == NON_EXISTENT_TOKEN:
            self.logger.info("Service is not minted.")
            return

        info = sftxb.info(token_id=chain_data.token)
        service_safe_address = info["multisig"]

        if service_safe_address == ZERO_ADDRESS:
            self.logger.info("Service Safe is not deployed.")
            return

        recovery_module_address = CONTRACTS[Chain(chain)]["recovery_module"]
        is_recovery_module_enabled = registry_contracts.gnosis_safe.is_module_enabled(
            ledger_api=sftxb.ledger_api,
            contract_address=service_safe_address,
            module_address=recovery_module_address,
        ).get("enabled")

        if is_recovery_module_enabled:
            self.logger.info("Recovery module is already enabled in service Safe.")
            return

        self.logger.info("Recovery module is not enabled.")

        # NOTE Recovery from agent only works for single-agent services
        agent_address = service.agent_addresses[0]
        service_safe_owners = sftxb.get_service_safe_owners(service_id=chain_data.token)
        agent_is_service_safe_owner = service_safe_owners == [agent_address]
        master_safe_is_service_safe_owner = service_safe_owners == [safe]

        if agent_is_service_safe_owner:
            self.logger.info("(Agent) Enabling recovery module in service Safe.")
            try:
                crypto = self.keys_manager.get_crypto_instance(address=agent_address)
                EthSafeTxBuilder._new_tx(  # pylint: disable=protected-access
                    ledger_api=sftxb.ledger_api,
                    crypto=crypto,
                    chain_type=ChainType(chain),
                    safe=service_safe_address,
                ).add(
                    sftxb.get_enable_module_data(
                        module_address=recovery_module_address,
                        safe_address=service_safe_address,
                    )
                ).settle()
                self.logger.info(
                    "(Agent) Recovery module enabled successfully in service Safe."
                )
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error(
                    f"Failed to enable recovery module in service Safe. Exception {e}: {traceback.format_exc()}"
                )
        elif master_safe_is_service_safe_owner:
            # TODO Enable recovery module when Safe owner = master Safe.
            # This should be similar to the above code, but
            # requires implement a transaction where the owner is another Safe.
            self.logger.info(
                "(Service owner) Enabling recovery module in service Safe. [Not implemented]"
            )
        else:
            self.logger.error(
                f"Cannot enable recovery module. Safe {service_safe_address} has inconsistent owners."
            )

    def _get_current_staking_program(
        self, service: Service, chain: str
    ) -> t.Optional[str]:
        # Use service's custom RPC from chain_configs
        rpc = service.chain_configs[chain].ledger_config.rpc
        staking_manager = StakingManager(Chain(chain), rpc=rpc)
        return staking_manager.get_current_staking_program(
            service_id=service.chain_configs[chain].chain_data.token
        )

    def stake_service_on_chain_from_safe(  # pylint: disable=too-many-statements,too-many-locals  # pragma: no cover
        self, service_config_id: str, chain: str
    ) -> None:
        """Stake service on-chain"""
        self.logger.info("stake_service_on_chain_from_safe")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        user_params = chain_data.user_params
        target_staking_program = user_params.staking_program_id
        target_staking_contract = get_staking_contract(
            chain=ledger_config.chain,
            staking_program_id=target_staking_program,
        )
        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)

        # TODO fixme
        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

        on_chain_state = self._get_on_chain_state(service=service, chain=chain)
        if on_chain_state != OnChainState.DEPLOYED:
            self.logger.info(
                f"Cannot perform staking operations. Service {chain_config.chain_data.token} is not on DEPLOYED state"
            )
            return

        # Determine if the service is staked in a known staking program
        current_staking_program = self._get_current_staking_program(
            service,
            chain,
        )
        current_staking_contract = get_staking_contract(
            chain=ledger_config.chain,
            staking_program_id=current_staking_program,
        )

        # perform the unstaking flow if necessary
        staking_state = StakingState.UNSTAKED
        if current_staking_program is not None:
            can_unstake = sftxb.can_unstake(
                chain_config.chain_data.token, current_staking_contract
            )
            if not chain_config.chain_data.user_params.use_staking and can_unstake:
                self.logger.info(
                    f"Use staking is set to false, but service {chain_config.chain_data.token} is staked and can be unstaked. Unstaking..."
                )
                self.unstake_service_on_chain_from_safe(
                    service_config_id=service_config_id,
                    chain=chain,
                    staking_program_id=current_staking_program,
                )

            staking_state = sftxb.staking_status(
                service_id=chain_data.token,
                staking_contract=current_staking_contract,
            )

            if staking_state == StakingState.EVICTED and can_unstake:
                self.logger.info(
                    f"Service {chain_config.chain_data.token} has been evicted and can be unstaked. Unstaking..."
                )
                self.unstake_service_on_chain_from_safe(
                    service_config_id=service_config_id,
                    chain=chain,
                    staking_program_id=current_staking_program,
                )

            if (
                staking_state == StakingState.STAKED
                and can_unstake
                and not sftxb.staking_rewards_available(current_staking_contract)
            ):
                self.logger.info(
                    f"There are no rewards available, service {chain_config.chain_data.token} "
                    "is already staked and can be unstaked."
                )
                self.logger.info("Skipping unstaking for no rewards available.")

            if (
                staking_state == StakingState.STAKED
                and current_staking_program != target_staking_program
                and can_unstake
            ):
                self.logger.info(
                    f"{chain_config.chain_data.token} is staked in a different staking program. Unstaking..."
                )
                self.unstake_service_on_chain_from_safe(
                    service_config_id=service_config_id,
                    chain=chain,
                    staking_program_id=current_staking_program,
                )

            staking_state = sftxb.staking_status(
                service_id=chain_config.chain_data.token,
                staking_contract=current_staking_contract,
            )

        target_program_staking_state = sftxb.staking_status(
            service_id=chain_config.chain_data.token,
            staking_contract=target_staking_contract,
        )
        self.logger.info("Checking conditions to stake.")

        staking_rewards_available = sftxb.staking_rewards_available(
            target_staking_contract
        )
        staking_slots_available = sftxb.staking_slots_available(target_staking_contract)
        current_staking_program = self._get_current_staking_program(
            service,
            chain,
        )

        self.logger.info(
            f"use_staking={chain_config.chain_data.user_params.use_staking}"
        )
        self.logger.info(f"{on_chain_state=}")
        self.logger.info(f"{current_staking_program=}")
        self.logger.info(f"{staking_state=}")
        self.logger.info(f"{target_staking_program=}")
        self.logger.info(f"{target_program_staking_state=}")
        self.logger.info(f"{staking_rewards_available=}")
        self.logger.info(f"{staking_slots_available=}")

        if (
            chain_config.chain_data.user_params.use_staking  # pylint: disable=too-many-boolean-expressions
            and staking_state == StakingState.UNSTAKED
            and target_program_staking_state == StakingState.UNSTAKED
            and staking_rewards_available
            and staking_slots_available
            and on_chain_state == OnChainState.DEPLOYED
        ):
            # Batch all approvals + stake into one tx
            self.logger.info(f"Approving & staking: {chain_config.chain_data.token}")
            stake_tx = sftxb.new_tx()

            stake_tx.add(
                sftxb.get_staking_approval_data(
                    service_id=chain_config.chain_data.token,
                    service_registry=CONTRACTS[ledger_config.chain]["service_registry"],
                    staking_contract=target_staking_contract,
                )
            )

            staking_params = sftxb.get_staking_params(
                staking_contract=target_staking_contract
            )
            for token_contract, min_staking_amount in staking_params[
                "additional_staking_tokens"
            ].items():
                stake_tx.add(
                    sftxb.get_erc20_approval_data(
                        spender=target_staking_contract,
                        amount=min_staking_amount,
                        erc20_contract=token_contract,
                    )
                )

            stake_tx.add(
                sftxb.get_staking_data(
                    service_id=chain_config.chain_data.token,
                    staking_contract=target_staking_contract,
                )
            ).settle()

        current_staking_program = self._get_current_staking_program(
            service,
            chain,
        )
        self.logger.info(f"{target_staking_program=}")
        self.logger.info(f"{current_staking_program=}")

    def unstake_service_on_chain_from_safe(  # pragma: no cover
        self,
        service_config_id: str,
        chain: str,
        staking_program_id: t.Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Unstake service on-chain"""
        # Claim the rewards first so that they are moved to the Master Safe
        self.claim_on_chain_from_safe(
            service_config_id=service_config_id,
            chain=chain,
        )

        self.logger.info("unstake_service_on_chain_from_safe")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data

        if staking_program_id is None:
            self.logger.info(
                "Cannot unstake service, `staking_program_id` is set to None"
            )
            return

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        state = sftxb.staking_status(
            service_id=chain_data.token,
            staking_contract=get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=staking_program_id,
            ),
        )
        self.logger.info(f"Staking status for service {chain_data.token}: {state}")
        if state not in {StakingState.STAKED, StakingState.EVICTED}:
            self.logger.info("Cannot unstake service, it's not staked")
            return

        self.logger.info(f"Unstaking service: {chain_data.token}")
        sftxb.new_tx().add(
            sftxb.get_unstaking_data(
                service_id=chain_data.token,
                staking_contract=get_staking_contract(
                    chain=ledger_config.chain,
                    staking_program_id=staking_program_id,
                ),
                force=force,
            )
        ).settle()

    def claim_all_on_chain_from_safe(self) -> None:
        """Claim rewards from all services and chains"""
        self.logger.info("claim_all_on_chain_from_safe")
        services, _ = self.get_all_services()
        for service in services:
            self.claim_on_chain_from_safe(
                service_config_id=service.service_config_id,
                chain=service.home_chain,
            )

    def claim_on_chain_from_safe(  # pragma: no cover
        self,
        service_config_id: str,
        chain: str,
    ) -> int:
        """Claim rewards from staking and returns the claimed amount"""
        self.logger.info("claim_on_chain_from_safe")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        ledger_api = wallet.ledger_api(chain=ledger_config.chain, rpc=ledger_config.rpc)

        if (
            chain_config.chain_data.token == NON_EXISTENT_TOKEN
            or chain_config.chain_data.multisig == ZERO_ADDRESS
        ):
            self.logger.info("Service is not minted or Safe not deployed.")
            return 0

        self.logger.info(
            f"OLAS Balance on service Safe {chain_config.chain_data.multisig}: "
            f"{get_asset_balance(ledger_api, OLAS[Chain(chain)], chain_config.chain_data.multisig)}"
        )
        current_staking_program = self._get_current_staking_program(
            service=service, chain=chain
        )
        staking_contract = get_staking_contract(
            chain=ledger_config.chain,
            staking_program_id=current_staking_program,
        )
        if staking_contract is None:
            self.logger.warning(
                "No staking contract found for the "
                f"{current_staking_program=}. Not claiming the rewards."
            )
            return 0

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        if not sftxb.staking_rewards_claimable(
            service_id=chain_config.chain_data.token,
            staking_contract=staking_contract,
        ):
            self.logger.info("No staking rewards claimable")
            return 0

        receipt = (
            sftxb.new_tx()
            .add(
                sftxb.get_claiming_data(
                    service_id=chain_config.chain_data.token,
                    staking_contract=staking_contract,
                )
            )
            .settle()
        )

        if receipt.status != 1:
            self.logger.error(
                f"Failed to claim staking rewards. Tx hash: {receipt.tx_hash}"
            )
            return 0

        # transfer reward token balance from agents safe to master safe
        # TODO: remove after staking contract directly starts sending the rewards to master safe
        reward_token = receipt["logs"][0]["address"]
        amount_claimed = int(receipt["logs"][0]["data"].to_0x_hex(), 16)
        amount_to_transfer = get_asset_balance(
            ledger_api=ledger_api,
            asset_address=reward_token,
            address=chain_config.chain_data.multisig,
        )
        self.logger.info(f"Claimed amount: {amount_claimed}")
        self.logger.info(f"Reward token balance to transfer: {amount_to_transfer}")
        if amount_to_transfer == 0:
            return amount_claimed

        transfer_erc20_from_safe(
            ledger_api=ledger_api,
            crypto=self.keys_manager.get_crypto_instance(service.agent_addresses[0]),
            safe=chain_config.chain_data.multisig,
            token=reward_token,
            to=wallet.safes[Chain(chain)],
            amount=amount_to_transfer,
        )
        return amount_claimed

    def fund_service(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        service_config_id: str,
        amounts: ChainAmounts,
    ) -> None:
        """Fund service if required."""
        service = self.load(service_config_id=service_config_id)
        self.funding_manager.fund_service(service=service, amounts=amounts)

    def drain(
        self, service_config_id: str, chain_str: str, withdrawal_address: str
    ) -> None:
        """Drain service safe and agent EOAs.

        Serialized per (service, chain) with the same withdrawal lock that
        background maintenance holds, so a user-triggered withdrawal cannot run
        concurrently with a maintenance drain. Without it, the two read the
        safe's balances before either executes, then both batch transfers for
        those amounts — whichever lands second reverts on-chain (the safe is
        already empty), surfacing as a 500.
        """
        chain = Chain(chain_str)
        with self.funding_manager.get_withdrawal_lock(
            service_config_id=service_config_id, chain=chain
        ):
            self._drain_unlocked(
                service_config_id=service_config_id,
                chain_str=chain_str,
                withdrawal_address=withdrawal_address,
            )

    def _drain_unlocked(
        self, service_config_id: str, chain_str: str, withdrawal_address: str
    ) -> None:
        """Drain service safe and agent EOAs.

        The caller MUST hold the per-(service, chain) withdrawal lock (see
        ``drain``). Balances are read fresh here, so a drain that runs after a
        concurrent one already emptied the safe simply finds nothing to move.
        """
        service = self.load(service_config_id=service_config_id)
        chain = Chain(chain_str)
        self.funding_manager.drain_service_safe(
            service=service,
            withdrawal_address=withdrawal_address,
            chain=chain,
        )
        self.funding_manager.drain_agents_eoas(
            service=service,
            withdrawal_address=withdrawal_address,
            chain=chain,
        )

    def service_maintenance(self) -> t.Dict[str, t.List[str]]:
        """Maintenance of the service to sync it with on-chain data"""
        result: t.Dict[str, t.List[str]] = {
            "processed": [],
            "skipped": [],
            "failed": [],
        }
        if not self._maintenance_lock.acquire(  # pylint: disable=consider-using-with
            blocking=False
        ):
            self.logger.info("[Maintenance] Maintenance already in progress; skipping.")
            return result
        try:  # pylint: disable=too-many-nested-blocks
            services, _ = self.get_all_services()
            for service in services:
                if service.deployment.status in (
                    DeploymentStatus.DEPLOYING,
                    DeploymentStatus.DEPLOYED,
                    DeploymentStatus.STOPPING,
                ):
                    # A locally running/transitioning deployment must not race
                    # with maintenance transfers.
                    continue
                for chain_str, chain_config in service.chain_configs.items():
                    tag = f"{service.service_config_id}:{chain_str}"
                    try:
                        chain_data = chain_config.chain_data
                        if chain_data.token == NON_EXISTENT_TOKEN:
                            continue
                        multisig = chain_data.multisig
                        if not multisig or multisig in (
                            NON_EXISTENT_MULTISIG,
                            ZERO_ADDRESS,
                        ):
                            continue
                        chain = Chain(chain_str)
                        wallet = self.wallet_manager.load(chain.ledger_type)
                        if chain not in wallet.safes:
                            result["skipped"].append(tag)
                            continue
                        master_safe = wallet.safes[chain]
                        # Hold the same per-(service, chain) lock as user
                        # withdrawals, and read the on-chain state under it,
                        # right before transferring.
                        withdrawal_lock = self.funding_manager.get_withdrawal_lock(
                            service_config_id=service.service_config_id,
                            chain=chain,
                        )
                        if not withdrawal_lock.acquire(blocking=False):
                            result["skipped"].append(tag)
                            continue
                        try:
                            state = self._get_on_chain_state(
                                service=service, chain=chain_str
                            )
                            if state not in {
                                OnChainState.PRE_REGISTRATION,
                                OnChainState.ACTIVE_REGISTRATION,
                            }:
                                continue
                            self.logger.info(
                                f"[Maintenance] Maintaining service {multisig} -> "
                                f"{master_safe} ({tag}, state={state.name})."
                            )
                            # Already holding the withdrawal lock for this
                            # (service, chain) — use the unlocked drain to avoid
                            # re-acquiring (which would deadlock).
                            self._drain_unlocked(
                                service_config_id=service.service_config_id,
                                chain_str=chain_str,
                                withdrawal_address=master_safe,
                            )
                            result["processed"].append(tag)
                        finally:
                            withdrawal_lock.release()
                    except Exception as e:  # pylint: disable=broad-except
                        # Expected on transient conditions (RPC offline,
                        # gas-poor signer); warn without a traceback to keep
                        # login-time logs readable.
                        self.logger.warning(f"[Maintenance] Failed for {tag}: {e}")
                        result["failed"].append(tag)
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(f"[Maintenance] Aborted: {e}\n{traceback.format_exc()}")
        finally:
            self._maintenance_lock.release()
        return result

    def deploy_service_locally(  # pylint: disable=too-many-arguments
        self,
        service_config_id: str,
        chain: t.Optional[str] = None,
        use_docker: bool = False,
        use_kubernetes: bool = False,
        build_only: bool = False,
    ) -> Deployment:
        """
        Deploy service locally

        :param hash: Service hash
        :param chain: Chain to set runtime parameters on the deployment (home_chain if not provided).
        :param use_docker: Use a Docker Compose deployment (True) or Host deployment (False).
        :param use_kubernetes: Use Kubernetes for deployment
        :param build_only: Only build the deployment without starting it
        :return: Deployment instance
        """
        service = self.load(service_config_id=service_config_id)

        deployment = service.deployment
        deployment.build(
            use_docker=use_docker,
            use_kubernetes=use_kubernetes,
            force=True,
            chain=chain or service.home_chain,
            keys_manager=self.keys_manager,
        )
        if build_only:
            return deployment
        deployment.start(
            password=self.wallet_manager.password,
            use_docker=use_docker,
            is_aea=service.agent_release["is_aea"],
        )
        return deployment

    def stop_service_locally(
        self,
        service_config_id: str,
        delete: bool = False,
        use_docker: bool = False,
        force: bool = False,
    ) -> Deployment:
        """
        Stop service locally

        :param service_id: Service id
        :param delete: Delete local deployment.
        :return: Deployment instance
        """
        service = self.load(service_config_id=service_config_id)
        service.remove_latest_healthcheck()
        deployment = service.deployment
        deployment.stop(
            use_docker=use_docker,
            force=force,
            is_aea=service.agent_release["is_aea"],
        )
        if delete:
            deployment.delete()
        return deployment

    def update(
        self,
        service_config_id: str,
        service_template: ServiceTemplate,
        allow_different_service_public_id: bool = False,
        partial_update: bool = True,
    ) -> Service:
        """Update a service."""

        self.logger.info(f"Updating {service_config_id=}")
        service = self.load(service_config_id=service_config_id)
        service.update(
            service_template=service_template,
            allow_different_service_public_id=allow_different_service_public_id,
            partial_update=partial_update,
        )
        return service

    def funding_requirements(  # pylint: disable=too-many-locals,too-many-statements,too-many-nested-blocks
        self, service_config_id: str
    ) -> t.Dict:
        """Get the funding requirements for a service."""
        service = self.load(service_config_id=service_config_id)
        return self.funding_manager.funding_requirements(service)
