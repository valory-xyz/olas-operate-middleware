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

import asyncio
import json
import logging
import os
import shutil
import time
import traceback
import typing as t
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

import requests
from aea.helpers.base import IPFSHash
from aea.helpers.logging import setup_logger
from aea_ledger_ethereum import EthereumCrypto
from autonomy.chain.base import registry_contracts
from autonomy.chain.config import CHAIN_PROFILES, ChainType

from operate.constants import ZERO_ADDRESS
from operate.data import DATA_DIR
from operate.data.contracts.mech_activity.contract import MechActivityContract
from operate.data.contracts.requester_activity_checker.contract import (
    RequesterActivityCheckerContract,
)
from operate.data.contracts.staking_token.contract import StakingTokenContract
from operate.keys import Key, KeysManager
from operate.ledger import PUBLIC_RPCS, get_currency_denom
from operate.ledger.profiles import (
    CONTRACTS,
    DEFAULT_MECH_MARKETPLACE_PRIORITY_MECH,
    OLAS,
    STAKING,
    USDC,
    WRAPPED_NATIVE_ASSET,
    get_staking_contract,
)
from operate.operate_types import Chain, FundingValues, LedgerConfig, ServiceTemplate
from operate.services.protocol import EthSafeTxBuilder, OnChainManager, StakingState
from operate.services.service import (
    ChainConfig,
    DELETE_PREFIX,
    Deployment,
    NON_EXISTENT_MULTISIG,
    NON_EXISTENT_TOKEN,
    OnChainData,
    OnChainState,
    SERVICE_CONFIG_PREFIX,
    Service,
)
from operate.services.utils.mech import deploy_mech
from operate.utils.gnosis import (
    NULL_ADDRESS,
    drain_eoa,
    get_asset_balance,
    get_assets_balances,
)
from operate.utils.gnosis import transfer as transfer_from_safe
from operate.utils.gnosis import transfer_erc20_from_safe
from operate.wallet.master import MasterWalletManager


# pylint: disable=redefined-builtin

OPERATE = ".operate"
CONFIG = "config.json"
SERVICES = "services"
KEYS = "keys"
DEPLOYMENT = "deployment"
CONFIG = "config.json"
KEY = "master-key.txt"
KEYS_JSON = "keys.json"
DOCKER_COMPOSE_YAML = "docker-compose.yaml"
SERVICE_YAML = "service.yaml"
HTTP_OK = 200
URI_HASH_POSITION = 7
IPFS_GATEWAY = "https://gateway.autonolas.tech/ipfs/"
DEFAULT_TOPUP_THRESHOLD = 0.5


class ServiceManager:
    """Service manager."""

    def __init__(
        self,
        path: Path,
        keys_manager: KeysManager,
        wallet_manager: MasterWalletManager,
        logger: t.Optional[logging.Logger] = None,
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
        self.logger = logger or setup_logger(name="operate.manager")
        self.skip_depencency_check = skip_dependency_check

    def setup(self) -> None:
        """Setup service manager."""
        self.path.mkdir(exist_ok=True)

    def _get_all_services(self) -> t.List[Service]:
        services = []
        for path in self.path.iterdir():
            if not path.name.startswith(SERVICE_CONFIG_PREFIX):
                continue
            try:
                service = Service.load(path=path)
                services.append(service)
            except ValueError as e:
                raise e
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error(
                    f"Failed to load service: {path.name}. Exception {e}: {traceback.format_exc()}"
                )
                # Rename the invalid path
                timestamp = int(time.time())
                invalid_path = path.parent / f"invalid_{timestamp}_{path.name}"
                os.rename(path, invalid_path)
                self.logger.info(
                    f"Renamed invalid service: {path.name} to {invalid_path.name}"
                )

        return services

    @property
    def json(self) -> t.List[t.Dict]:
        """Returns the list of available services."""
        return [service.json for service in self._get_all_services()]

    def exists(self, service_config_id: str) -> bool:
        """Check if service exists."""
        return (self.path / service_config_id).exists()

    def get_on_chain_manager(self, ledger_config: LedgerConfig) -> OnChainManager:
        """Get OnChainManager instance."""
        return OnChainManager(
            rpc=ledger_config.rpc,
            wallet=self.wallet_manager.load(ledger_config.chain.ledger_type),
            contracts=CONTRACTS[ledger_config.chain],
            chain_type=ChainType(ledger_config.chain.value),
        )

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
        keys: t.Optional[t.List[Key]] = None,
    ) -> Service:
        """
        Create or load a service

        :param hash: Service hash
        :param service_template: Service template
        :param keys: Keys
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

        service = Service.new(
            keys=keys or [],
            storage=self.path,
            service_template=service_template,
        )

        if not service.keys:
            service.keys = [
                self.keys_manager.get(self.keys_manager.create())
                for _ in range(service.helper.config.number_of_agents)
            ]
            service.store()

        return service

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
        keys: t.Optional[t.List[Key]] = None,
    ) -> Service:
        """
        Create a service

        :param service_template: Service template
        :param keys: Keys
        :return: Service instance
        """
        service = Service.new(
            keys=keys or [],
            storage=self.path,
            service_template=service_template,
        )

        if not service.keys:
            service.keys = [
                self.keys_manager.get(self.keys_manager.create())
                for _ in range(service.helper.config.number_of_agents)
            ]
            service.store()

        return service

    def _get_on_chain_state(self, service: Service, chain: str) -> OnChainState:
        chain_config = service.chain_configs[chain]
        chain_data = chain_config.chain_data
        ledger_config = chain_config.ledger_config
        if chain_data.token == NON_EXISTENT_TOKEN:
            service_state = OnChainState.NON_EXISTENT
            chain_data.on_chain_state = service_state
            service.store()
            return service_state

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        info = sftxb.info(token_id=chain_data.token)
        service_state = OnChainState(info["service_state"])
        chain_data.on_chain_state = service_state
        service.store()
        return service_state

    def _get_on_chain_metadata(self, chain_config: ChainConfig) -> t.Dict:
        chain_data = chain_config.chain_data
        ledger_config = chain_config.ledger_config
        if chain_data.token == NON_EXISTENT_TOKEN:
            return {}

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        info = sftxb.info(token_id=chain_data.token)
        config_hash = info["config_hash"]
        url = f"{IPFS_GATEWAY}f01701220{config_hash}"
        self.logger.info(f"Fetching {url=}...")
        res = requests.get(url, timeout=30)
        if res.status_code == 200:
            return res.json()
        raise ValueError(
            f"Something went wrong while trying to get the on-chain metadata from IPFS: {res}"
        )

    def deploy_service_onchain(  # pylint: disable=too-many-statements,too-many-locals
        self,
        service_config_id: str,
    ) -> None:
        """Deploy service on-chain"""
        # TODO This method has not been thoroughly reviewed. Deprecated usage in favour of Safe version.

        service = self.load(service_config_id=service_config_id)
        for chain in service.chain_configs.keys():
            self._deploy_service_onchain(
                service_config_id=service_config_id,
                chain=chain,
            )

    def _deploy_service_onchain(  # pylint: disable=too-many-statements,too-many-locals
        self,
        service_config_id: str,
        chain: str,
    ) -> None:
        """Deploy as service on-chain"""
        # TODO This method has not been thoroughly reviewed. Deprecated usage in favour of Safe version.

        self.logger.info(f"_deploy_service_onchain {chain=}")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        user_params = chain_config.chain_data.user_params
        keys = service.keys
        instances = [key.address for key in keys]
        ocm = self.get_on_chain_manager(ledger_config=ledger_config)

        # TODO fix this
        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

        current_agent_id = None
        if chain_data.token > -1:
            self.logger.info("Syncing service state")
            info = ocm.info(token_id=chain_data.token)
            chain_data.on_chain_state = OnChainState(info["service_state"])
            chain_data.instances = info["instances"]
            chain_data.multisig = info["multisig"]
            service.store()
        self.logger.info(f"Service state: {chain_data.on_chain_state.name}")

        if user_params.use_staking:
            staking_params = ocm.get_staking_params(
                staking_contract=get_staking_contract(
                    chain=ledger_config.chain,
                    staking_program_id=user_params.staking_program_id,
                ),
            )
        else:  # TODO fix this - using pearl beta params
            staking_params = dict(  # nosec
                agent_ids=[25],
                service_registry="0x9338b5153AE39BB89f50468E608eD9d764B755fD",  # nosec
                staking_token="0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",  # nosec
                service_registry_token_utility="0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8",  # nosec
                min_staking_deposit=20000000000000000000,
                activity_checker="0x155547857680A6D51bebC5603397488988DEb1c8",  # nosec
            )

        if user_params.use_staking:
            self.logger.info("Checking staking compatibility")

            # TODO: Missing check when the service is currently staked in a program, but needs to be staked
            # in a different target program. The In this case, balance = currently staked balance + safe balance

            if chain_data.on_chain_state in (
                OnChainState.NON_EXISTENT,
                OnChainState.PRE_REGISTRATION,
            ):
                required_olas = (
                    staking_params["min_staking_deposit"]
                    + staking_params["min_staking_deposit"]  # bond = staking
                )
            elif chain_data.on_chain_state == OnChainState.ACTIVE_REGISTRATION:
                required_olas = staking_params["min_staking_deposit"]
            else:
                required_olas = 0

            balance = (
                registry_contracts.erc20.get_instance(
                    ledger_api=ocm.ledger_api,
                    contract_address=OLAS[ledger_config.chain],
                )
                .functions.balanceOf(ocm.crypto.address)
                .call()
            )
            if balance < required_olas:
                raise ValueError(
                    "You don't have enough olas to stake, "
                    f"required olas: {required_olas}; your balance {balance}"
                )

        on_chain_metadata = self._get_on_chain_metadata(chain_config=chain_config)
        on_chain_hash = on_chain_metadata.get("code_uri", "")[URI_HASH_POSITION:]
        on_chain_description = on_chain_metadata.get("description")

        current_agent_bond = staking_params[
            "min_staking_deposit"
        ]  # TODO fixme, read from service registry token utility contract
        is_first_mint = (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.NON_EXISTENT
        )
        is_update = (
            (not is_first_mint)
            and (on_chain_hash is not None)
            and (
                on_chain_hash != service.hash
                or current_agent_id != staking_params["agent_ids"][0]
                or current_agent_bond != staking_params["min_staking_deposit"]
                or on_chain_description != service.description
            )
        )
        current_staking_program = self._get_current_staking_program(service, chain)

        self.logger.info(f"{current_staking_program=}")
        self.logger.info(f"{user_params.staking_program_id=}")
        self.logger.info(f"{on_chain_hash=}")
        self.logger.info(f"{service.hash=}")
        self.logger.info(f"{current_agent_id=}")
        self.logger.info(f"{staking_params['agent_ids'][0]=}")
        self.logger.info(f"{is_first_mint=}")
        self.logger.info(f"{is_update=}")

        if chain_data.on_chain_state == OnChainState.NON_EXISTENT:
            self.logger.info("Minting service")
            chain_data.token = t.cast(
                int,
                ocm.mint(
                    package_path=service.package_absolute_path_absolute_path,
                    agent_id=staking_params["agent_ids"][0],
                    number_of_slots=service.helper.config.number_of_agents,
                    cost_of_bond=(
                        staking_params["min_staking_deposit"]
                        if user_params.use_staking
                        else user_params.cost_of_bond
                    ),
                    threshold=user_params.threshold,
                    nft=IPFSHash(user_params.nft),
                    update_token=chain_data.token if is_update else None,
                    token=(
                        OLAS[ledger_config.chain] if user_params.use_staking else None
                    ),
                    metadata_description=service.description,
                    skip_dependency_check=self.skip_depencency_check,
                ).get("token"),
            )
            chain_data.on_chain_state = OnChainState.PRE_REGISTRATION
            service.store()

        info = ocm.info(token_id=chain_data.token)
        chain_data.on_chain_state = OnChainState(info["service_state"])

        if chain_data.on_chain_state == OnChainState.PRE_REGISTRATION:
            self.logger.info("Activating service")
            ocm.activate(
                service_id=chain_data.token,
                token=(OLAS[ledger_config.chain] if user_params.use_staking else None),
            )
            chain_data.on_chain_state = OnChainState.ACTIVE_REGISTRATION
            service.store()

        info = ocm.info(token_id=chain_data.token)
        chain_data.on_chain_state = OnChainState(info["service_state"])

        if chain_data.on_chain_state == OnChainState.ACTIVE_REGISTRATION:
            self.logger.info("Registering agent instances")
            agent_id = staking_params["agent_ids"][0]
            ocm.register(
                service_id=chain_data.token,
                instances=instances,
                agents=[agent_id for _ in instances],
                token=(OLAS[ledger_config.chain] if user_params.use_staking else None),
            )
            chain_data.on_chain_state = OnChainState.FINISHED_REGISTRATION
            service.store()

        info = ocm.info(token_id=chain_data.token)
        chain_data.on_chain_state = OnChainState(info["service_state"])

        if chain_data.on_chain_state == OnChainState.FINISHED_REGISTRATION:
            self.logger.info("Deploying service")
            ocm.deploy(
                service_id=chain_data.token,
                reuse_multisig=is_update,
                token=(OLAS[ledger_config.chain] if user_params.use_staking else None),
            )
            chain_data.on_chain_state = OnChainState.DEPLOYED
            service.store()

        info = ocm.info(token_id=chain_data.token)
        chain_data = OnChainData(
            token=chain_data.token,
            instances=info["instances"],
            multisig=info["multisig"],
            staked=False,
            on_chain_state=chain_data.on_chain_state,
            user_params=chain_data.user_params,
        )
        service.store()

    def deploy_service_onchain_from_safe(  # pylint: disable=too-many-statements,too-many-locals
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

    def _deploy_service_onchain_from_safe(  # pylint: disable=too-many-statements,too-many-locals
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
        keys = service.keys
        instances = [key.address for key in keys]
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        safe = wallet.safes[Chain(chain)]

        # TODO fix this
        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

        current_agent_id = None
        if chain_data.token > -1:
            self.logger.info("Syncing service state")
            info = sftxb.info(token_id=chain_data.token)
            chain_data.on_chain_state = OnChainState(info["service_state"])
            chain_data.instances = info["instances"]
            chain_data.multisig = info["multisig"]
            current_agent_id = info["canonical_agents"][0]  # TODO Allow multiple agents
            service.store()
        self.logger.info(f"Service state: {chain_data.on_chain_state.name}")

        if user_params.use_staking:
            staking_params = sftxb.get_staking_params(
                staking_contract=get_staking_contract(
                    chain=ledger_config.chain,
                    staking_program_id=user_params.staking_program_id,
                ),
            )
        else:
            staking_params = dict(  # nosec
                staking_contract=NULL_ADDRESS,
                agent_ids=[user_params.agent_id],
                service_registry="0x9338b5153AE39BB89f50468E608eD9d764B755fD",  # nosec
                staking_token=NULL_ADDRESS,  # nosec
                service_registry_token_utility="0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8",  # nosec
                min_staking_deposit=20000000000000000000,
                activity_checker=NULL_ADDRESS,  # nosec
            )

        # TODO A customized, arbitrary computation mechanism should be devised.
        env_var_to_value = {}
        if chain == service.home_chain:
            # Try if activity checker is a MechActivityChecker contract
            try:
                mech_activity_contract = t.cast(
                    MechActivityContract,
                    MechActivityContract.from_dir(
                        directory=str(DATA_DIR / "contracts" / "mech_activity")
                    ),
                )

                agent_mech = (
                    mech_activity_contract.get_instance(
                        ledger_api=sftxb.ledger_api,
                        contract_address=staking_params["activity_checker"],
                    )
                    .functions.agentMech()
                    .call()
                )
                use_mech_marketplace = False
                mech_marketplace_address = ZERO_ADDRESS
                priority_mech_address = ZERO_ADDRESS

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
                            ledger_api=sftxb.ledger_api,
                            contract_address=staking_params["activity_checker"],
                        )
                        .functions.mechMarketplace()
                        .call()
                    )

                    use_mech_marketplace = True
                    agent_mech = DEFAULT_MECH_MARKETPLACE_PRIORITY_MECH
                    priority_mech_address = DEFAULT_MECH_MARKETPLACE_PRIORITY_MECH

                except Exception:  # pylint: disable=broad-except
                    self.logger.warning(
                        "Cannot determine type of activity checker contract. Using default parameters."
                    )
                    agent_mech = "0x77af31De935740567Cf4fF1986D04B2c964A786a"  # nosec
                    use_mech_marketplace = False
                    mech_marketplace_address = ZERO_ADDRESS
                    priority_mech_address = ZERO_ADDRESS

            env_var_to_value.update(
                {
                    "ETHEREUM_LEDGER_RPC": PUBLIC_RPCS[Chain.ETHEREUM],
                    "GNOSIS_LEDGER_RPC": PUBLIC_RPCS[Chain.GNOSIS],
                    "BASE_LEDGER_RPC": PUBLIC_RPCS[Chain.BASE],
                    "CELO_LEDGER_RPC": PUBLIC_RPCS[Chain.CELO],
                    "OPTIMISM_LEDGER_RPC": PUBLIC_RPCS[Chain.OPTIMISTIC],
                    "MODE_LEDGER_RPC": PUBLIC_RPCS[Chain.MODE],
                    f"{chain.upper()}_LEDGER_RPC": ledger_config.rpc,
                    "STAKING_CONTRACT_ADDRESS": staking_params.get("staking_contract"),
                    "STAKING_TOKEN_CONTRACT_ADDRESS": staking_params.get(
                        "staking_contract"
                    ),
                    "MECH_MARKETPLACE_CONFIG": (
                        f'{{"mech_marketplace_address":"{mech_marketplace_address}",'
                        f'"priority_mech_address":"{priority_mech_address}",'
                        f'"priority_mech_staking_instance_address":"0x998dEFafD094817EF329f6dc79c703f1CF18bC90",'
                        f'"priority_mech_service_id":975,'
                        f'"requester_staking_instance_address":"{staking_params.get("staking_contract")}",'
                        f'"response_timeout":300}}'
                    ),
                    "ACTIVITY_CHECKER_CONTRACT_ADDRESS": staking_params.get(
                        "activity_checker"
                    ),
                    "MECH_ACTIVITY_CHECKER_CONTRACT": staking_params.get(
                        "activity_checker"
                    ),
                    "MECH_CONTRACT_ADDRESS": agent_mech,
                    "MECH_REQUEST_PRICE": "10000000000000000",
                    "USE_MECH_MARKETPLACE": use_mech_marketplace,
                }
            )

        # TODO: yet another agent specific logic for memeooorr, which should be abstracted
        if all(
            var in service.env_variables
            for var in [
                "TWIKIT_USERNAME",
                "TWIKIT_EMAIL",
                "TWIKIT_PASSWORD",
            ]
        ):
            store_path = service.path / "persistent_data"
            store_path.mkdir(parents=True, exist_ok=True)
            env_var_to_value.update({"STORE_PATH": os.path.join(str(store_path), "")})

        # TODO yet another computed variable for modius
        if "optimus" in service.name.lower():
            store_path = service.path / "persistent_data"
            store_path.mkdir(parents=True, exist_ok=True)
            env_var_to_value.update({"STORE_PATH": os.path.join(str(store_path), "")})

        service.update_env_variables_values(env_var_to_value)

        if user_params.use_staking:
            self.logger.info("Checking staking compatibility")

            # TODO: Missing check when the service is currently staked in a program, but needs to be staked
            # in a different target program. The In this case, balance = currently staked balance + safe balance

            if chain_data.on_chain_state in (
                OnChainState.NON_EXISTENT,
                OnChainState.PRE_REGISTRATION,
            ):
                protocol_asset_requirements = self._compute_protocol_asset_requirements(
                    service_config_id, chain
                )
            elif chain_data.on_chain_state == OnChainState.ACTIVE_REGISTRATION:
                protocol_asset_requirements = self._compute_protocol_asset_requirements(
                    service_config_id, chain
                )
                protocol_asset_requirements[staking_params["staking_token"]] = (
                    staking_params["min_staking_deposit"]
                    * service.helper.config.number_of_agents
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
            staking_params["agent_ids"][0]
            if staking_params["agent_ids"]
            else user_params.agent_id
        )
        staking_params["agent_ids"] = [agent_id]

        on_chain_metadata = self._get_on_chain_metadata(chain_config=chain_config)
        on_chain_hash = on_chain_metadata.get("code_uri", "")[URI_HASH_POSITION:]
        on_chain_description = on_chain_metadata.get("description")

        current_agent_bond = sftxb.get_agent_bond(
            service_id=chain_data.token, agent_id=staking_params["agent_ids"][0]
        )

        is_first_mint = (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.NON_EXISTENT
        )

        is_update = (
            (not is_first_mint)
            and (on_chain_hash is not None)
            and (
                # TODO Discuss how to manage on-chain hash updates with staking programs.
                # on_chain_hash != service.hash or  # noqa
                current_agent_id != staking_params["agent_ids"][0]
                # TODO This has to be removed for Optimus (needs to be properly implemented). Needs to be put back for Trader!
                or current_agent_bond != staking_params["min_staking_deposit"]
                or on_chain_description != service.description
            )
        )
        current_staking_program = self._get_current_staking_program(service, chain)

        self.logger.info(f"{chain_data.token=}")
        self.logger.info(f"{current_staking_program=}")
        self.logger.info(f"{user_params.staking_program_id=}")
        self.logger.info(f"{on_chain_hash=}")
        self.logger.info(f"{service.hash=}")
        self.logger.info(f"{current_agent_id=}")
        self.logger.info(f"{staking_params['agent_ids'][0]=}")
        self.logger.info(f"{current_agent_bond=}")
        self.logger.info(f"{staking_params['min_staking_deposit']=}")
        self.logger.info(f"{is_first_mint=}")
        self.logger.info(f"{is_update=}")

        if is_update:
            self.terminate_service_on_chain_from_safe(
                service_config_id=service_config_id, chain=chain
            )
            # Update service
            if (
                self._get_on_chain_state(service=service, chain=chain)
                == OnChainState.PRE_REGISTRATION
            ):
                self.logger.info("Updating service")
                receipt = (
                    sftxb.new_tx()
                    .add(
                        sftxb.get_mint_tx_data(
                            package_path=service.package_absolute_path,
                            agent_id=agent_id,
                            number_of_slots=service.helper.config.number_of_agents,
                            cost_of_bond=(
                                staking_params["min_staking_deposit"]
                                if user_params.use_staking
                                else user_params.cost_of_bond
                            ),
                            threshold=user_params.threshold,
                            nft=IPFSHash(user_params.nft),
                            update_token=chain_data.token,
                            token=(
                                staking_params["staking_token"]
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
                        contract_address=staking_params["service_registry"],
                        event="UpdateService",
                        receipt=receipt,
                    ).get("events"),
                )
                chain_data.on_chain_state = OnChainState.PRE_REGISTRATION
                service.store()

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
                        number_of_slots=service.helper.config.number_of_agents,
                        cost_of_bond=(
                            staking_params["min_staking_deposit"]
                            if user_params.use_staking
                            else user_params.cost_of_bond
                        ),
                        threshold=user_params.threshold,
                        nft=IPFSHash(user_params.nft),
                        update_token=None,
                        token=(
                            staking_params["staking_token"]
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
                    contract_address=staking_params["service_registry"],
                    event="CreateService",
                    receipt=receipt,
                ).get("events"),
            )
            chain_data.token = event_data["args"]["serviceId"]
            chain_data.on_chain_state = OnChainState.PRE_REGISTRATION
            service.store()

        if (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.PRE_REGISTRATION
        ):
            # TODO Verify that this is incorrect: cost_of_bond = staking_params["min_staking_deposit"]
            cost_of_bond = user_params.cost_of_bond
            if user_params.use_staking:
                token_utility = staking_params["service_registry_token_utility"]
                olas_token = staking_params["staking_token"]
                self.logger.info(
                    f"Approving OLAS as bonding token from {safe} to {token_utility}"
                )
                cost_of_bond = (
                    registry_contracts.service_registry_token_utility.get_agent_bond(
                        ledger_api=sftxb.ledger_api,
                        contract_address=token_utility,
                        service_id=chain_data.token,
                        agent_id=agent_id,
                    ).get("bond")
                )
                sftxb.new_tx().add(
                    sftxb.get_erc20_approval_data(
                        spender=token_utility,
                        amount=cost_of_bond,
                        erc20_contract=olas_token,
                    )
                ).settle()
                token_utility_allowance = (
                    registry_contracts.erc20.get_instance(
                        ledger_api=sftxb.ledger_api,
                        contract_address=olas_token,
                    )
                    .functions.allowance(
                        safe,
                        token_utility,
                    )
                    .call()
                )
                self.logger.info(
                    f"Approved {token_utility_allowance} OLAS from {safe} to {token_utility}"
                )
                cost_of_bond = 1

            self.logger.info("Activating service")

            native_balance = get_asset_balance(
                ledger_api=sftxb.ledger_api,
                asset_address=ZERO_ADDRESS,
                address=safe,
            )

            if native_balance < cost_of_bond:
                message = f"Cannot activate service: address {safe} {native_balance=} < {cost_of_bond=}."
                self.logger.error(message)
                raise ValueError(message)

            sftxb.new_tx().add(
                sftxb.get_activate_data(
                    service_id=chain_data.token,
                    cost_of_bond=cost_of_bond,
                )
            ).settle()
            chain_data.on_chain_state = OnChainState.ACTIVE_REGISTRATION
            service.store()

        if (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.ACTIVE_REGISTRATION
        ):
            cost_of_bond = user_params.cost_of_bond
            if user_params.use_staking:
                token_utility = staking_params["service_registry_token_utility"]
                olas_token = staking_params["staking_token"]
                self.logger.info(
                    f"Approving OLAS as bonding token from {safe} to {token_utility}"
                )
                cost_of_bond = (
                    registry_contracts.service_registry_token_utility.get_agent_bond(
                        ledger_api=sftxb.ledger_api,
                        contract_address=token_utility,
                        service_id=chain_data.token,
                        agent_id=agent_id,
                    ).get("bond")
                )
                sftxb.new_tx().add(
                    sftxb.get_erc20_approval_data(
                        spender=token_utility,
                        amount=cost_of_bond,
                        erc20_contract=olas_token,
                    )
                ).settle()
                token_utility_allowance = (
                    registry_contracts.erc20.get_instance(
                        ledger_api=sftxb.ledger_api,
                        contract_address=olas_token,
                    )
                    .functions.allowance(
                        safe,
                        token_utility,
                    )
                    .call()
                )
                self.logger.info(
                    f"Approved {token_utility_allowance} OLAS from {safe} to {token_utility}"
                )
                cost_of_bond = 1 * len(instances)

            self.logger.info(
                f"Registering agent instances: {chain_data.token} -> {instances}"
            )

            native_balance = get_asset_balance(
                ledger_api=sftxb.ledger_api,
                asset_address=ZERO_ADDRESS,
                address=safe,
            )

            if native_balance < cost_of_bond:
                message = f"Cannot register agent instances: address {safe} {native_balance=} < {cost_of_bond=}."
                self.logger.error(message)
                raise ValueError(message)

            sftxb.new_tx().add(
                sftxb.get_register_instances_data(
                    service_id=chain_data.token,
                    instances=instances,
                    agents=[agent_id for _ in instances],
                    cost_of_bond=cost_of_bond,
                )
            ).settle()
            chain_data.on_chain_state = OnChainState.FINISHED_REGISTRATION
            service.store()

        if (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.FINISHED_REGISTRATION
        ):
            self.logger.info("Deploying service")

            reuse_multisig = True
            info = sftxb.info(token_id=chain_data.token)
            if info["multisig"] == NULL_ADDRESS:
                reuse_multisig = False

            self.logger.info(f"{reuse_multisig=}")

            messages = sftxb.get_deploy_data_from_safe(
                service_id=chain_data.token,
                reuse_multisig=reuse_multisig,
                master_safe=safe,
            )
            tx = sftxb.new_tx()
            for message in messages:
                tx.add(message)
            tx.settle()

            chain_data.on_chain_state = OnChainState.DEPLOYED
            service.store()

        # Update local Service
        info = sftxb.info(token_id=chain_data.token)
        chain_data.instances = info["instances"]
        chain_data.multisig = info["multisig"]
        chain_data.on_chain_state = OnChainState(info["service_state"])

        # TODO: yet another agent specific logic for mech, which should be abstracted
        if all(
            var in service.env_variables
            for var in [
                "AGENT_ID",
                "MECH_TO_CONFIG",
                "ON_CHAIN_SERVICE_ID",
                "GNOSIS_RPC_0",
            ]
        ):
            if (
                not service.env_variables["AGENT_ID"]["value"]
                or not service.env_variables["MECH_TO_CONFIG"]["value"]
            ):
                mech_address, agent_id = deploy_mech(sftxb=sftxb, service=service)
                service.update_env_variables_values(
                    {
                        "AGENT_ID": agent_id,
                        "MECH_TO_CONFIG": json.dumps(
                            {
                                mech_address: {
                                    "use_dynamic_pricing": False,
                                    "is_marketplace_mech": True,
                                }
                            },
                            separators=(",", ":"),
                        ),
                    }
                )

            service.update_env_variables_values(
                {
                    "ON_CHAIN_SERVICE_ID": chain_data.token,
                    "GNOSIS_RPC_0": service.env_variables["GNOSIS_LEDGER_RPC"]["value"],
                }
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

        if user_params.use_staking:
            self.stake_service_on_chain_from_safe(
                service_config_id=service_config_id, chain=chain
            )

    def terminate_service_on_chain(
        self, service_config_id: str, chain: t.Optional[str] = None
    ) -> None:
        """Terminate service on-chain"""
        # TODO This method has not been thoroughly reviewed. Deprecated usage in favour of Safe version.

        self.logger.info("terminate_service_on_chain")
        service = self.load(service_config_id=service_config_id)

        chain_config = service.chain_configs[chain or service.home_chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        ocm = self.get_on_chain_manager(ledger_config=ledger_config)
        info = ocm.info(token_id=chain_data.token)
        chain_data.on_chain_state = OnChainState(info["service_state"])

        if chain_data.on_chain_state != OnChainState.DEPLOYED:
            self.logger.info("Cannot terminate service")
            return

        self.logger.info("Terminating service")
        ocm.terminate(
            service_id=chain_data.token,
            token=(
                OLAS[ledger_config.chain]
                if chain_data.user_params.use_staking
                else None
            ),
        )
        chain_data.on_chain_state = OnChainState.TERMINATED_BONDED
        service.store()

    def terminate_service_on_chain_from_safe(  # pylint: disable=too-many-locals
        self,
        service_config_id: str,
        chain: str,
        withdrawal_address: t.Optional[str] = None,
    ) -> None:
        """Terminate service on-chain"""

        self.logger.info("terminate_service_on_chain_from_safe")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        keys = service.keys
        instances = [key.address for key in keys]
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        safe = wallet.safes[Chain(chain)]  # type: ignore

        # TODO fixme
        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        info = sftxb.info(token_id=chain_data.token)
        chain_data.on_chain_state = OnChainState(info["service_state"])

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
        if is_staked and not can_unstake and withdrawal_address is None:
            self.logger.info("Service cannot be terminated on-chain: cannot unstake.")
            return

        # Unstake the service if applies
        if is_staked and (can_unstake or withdrawal_address is not None):
            self.unstake_service_on_chain_from_safe(
                service_config_id=service_config_id,
                chain=chain,
                staking_program_id=current_staking_program,
            )

        if self._get_on_chain_state(service=service, chain=chain) in (
            OnChainState.ACTIVE_REGISTRATION,
            OnChainState.FINISHED_REGISTRATION,
            OnChainState.DEPLOYED,
        ):
            self.logger.info("Terminating service")
            sftxb.new_tx().add(
                sftxb.get_terminate_data(
                    service_id=chain_data.token,
                )
            ).settle()

        if (
            self._get_on_chain_state(service=service, chain=chain)
            == OnChainState.TERMINATED_BONDED
        ):
            self.logger.info("Unbonding service")
            sftxb.new_tx().add(
                sftxb.get_unbond_data(
                    service_id=chain_data.token,
                )
            ).settle()

        # Swap service safe
        current_safe_owners = sftxb.get_service_safe_owners(service_id=chain_data.token)
        counter_current_safe_owners = Counter(s.lower() for s in current_safe_owners)
        counter_instances = Counter(s.lower() for s in instances)

        if withdrawal_address is not None:
            # we don't drain signer yet, because the owner swapping tx may need to happen
            self.drain_service_safe(
                service_config_id=service_config_id,
                withdrawal_address=withdrawal_address,
                chain=Chain(chain),
            )

        if counter_current_safe_owners == counter_instances:
            if withdrawal_address is None:
                self.logger.info("Service funded for safe swap")
                self.fund_service(
                    service_config_id=service_config_id,
                    funding_values={
                        ZERO_ADDRESS: {
                            "agent": {
                                "topup": chain_data.user_params.fund_requirements[
                                    ZERO_ADDRESS
                                ].agent,
                                "threshold": chain_data.user_params.fund_requirements[
                                    ZERO_ADDRESS
                                ].agent,
                            },
                            "safe": {"topup": 0, "threshold": 0},
                        }
                    },
                )

            self.logger.info("Swapping Safe owners")
            sftxb.swap(  # noqa: E800
                service_id=chain_data.token,  # noqa: E800
                multisig=chain_data.multisig,  # TODO this can be read from the registry
                owner_key=str(
                    self.keys_manager.get(
                        key=current_safe_owners[0]
                    ).private_key  # TODO allow multiple owners
                ),  # noqa: E800
                new_owner_address=safe
                if safe
                else wallet.crypto.address,  # TODO it should always be safe address
            )  # noqa: E800

        if withdrawal_address is not None:
            # drain all native tokens from service signer key
            drain_eoa(
                ledger_api=self.wallet_manager.load(
                    ledger_config.chain.ledger_type
                ).ledger_api(chain=ledger_config.chain, rpc=ledger_config.rpc),
                crypto=EthereumCrypto(
                    private_key_path=service.path
                    / "deployment"
                    / "ethereum_private_key.txt",
                ),
                withdrawal_address=withdrawal_address,
                chain_id=ledger_config.chain.id,
            )
            self.logger.info(f"{service.name} signer drained")

    def _get_current_staking_program(
        self, service: Service, chain: str
    ) -> t.Optional[str]:
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        service_id = chain_config.chain_data.token
        ledger_api = sftxb.ledger_api

        if service_id == NON_EXISTENT_TOKEN:
            return None

        service_registry = registry_contracts.service_registry.get_instance(
            ledger_api=ledger_api,
            contract_address=CONTRACTS[ledger_config.chain]["service_registry"],
        )

        service_owner = service_registry.functions.ownerOf(service_id).call()

        # TODO Implement in Staking Manager. Implemented here for performance issues.
        staking_ctr = t.cast(
            StakingTokenContract,
            StakingTokenContract.from_dir(
                directory=str(DATA_DIR / "contracts" / "staking_token")
            ),
        )

        try:
            state = StakingState(
                staking_ctr.get_instance(
                    ledger_api=ledger_api,
                    contract_address=service_owner,
                )
                .functions.getStakingState(service_id)
                .call()
            )
        except Exception:  # pylint: disable=broad-except
            # Service owner is not a staking contract

            # TODO The exception caught here should be ContractLogicError.
            # This exception is typically raised when the contract reverts with
            # a reason string. However, in some cases, the error message
            # does not contain a reason string, which means web3.py raises
            # a generic ValueError instead. It should be properly analyzed
            # what exceptions might be raised by web3.py in this case. To
            # avoid any issues we are simply catching all exceptions.
            return None

        if state == StakingState.UNSTAKED:
            return None

        for staking_program_id, val in STAKING[ledger_config.chain].items():
            if val == service_owner:
                return staking_program_id

        # Fallback, if not possible to determine staking_program_id it means it's an "inner" staking contract
        # (e.g., in the case of DualStakingToken). Loop trough all the known contracts.
        for staking_program_id, staking_program_address in STAKING[
            ledger_config.chain
        ].items():
            state = StakingState(
                staking_ctr.get_instance(
                    ledger_api=ledger_api,
                    contract_address=staking_program_address,
                )
                .functions.getStakingState(service_id)
                .call()
            )

            if state in (StakingState.STAKED, StakingState.EVICTED):
                return staking_program_id

        # it's staked, but we don't know which staking program
        # so the staking_program_id should be an arbitrary staking contract
        return service_owner

    def unbond_service_on_chain(
        self, service_config_id: str, chain: t.Optional[str] = None
    ) -> None:
        """Unbond service on-chain"""
        # TODO This method has not been thoroughly reviewed. Deprecated usage in favour of Safe version.

        service = self.load(service_config_id=service_config_id)

        chain_config = service.chain_configs[chain or service.home_chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        ocm = self.get_on_chain_manager(ledger_config=ledger_config)
        info = ocm.info(token_id=chain_data.token)
        chain_data.on_chain_state = OnChainState(info["service_state"])

        if chain_data.on_chain_state != OnChainState.TERMINATED_BONDED:
            self.logger.info("Cannot unbond service")
            return

        self.logger.info("Unbonding service")
        ocm.unbond(
            service_id=chain_data.token,
            token=(
                OLAS[ledger_config.chain]
                if chain_data.user_params.use_staking
                else None
            ),
        )
        chain_data.on_chain_state = OnChainState.UNBONDED
        service.store()

    def stake_service_on_chain(self, hash: str) -> None:
        """
        Stake service on-chain

        :param hash: Service hash
        """
        raise NotImplementedError

    def stake_service_on_chain_from_safe(  # pylint: disable=too-many-statements,too-many-locals
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

            info = sftxb.info(token_id=chain_config.chain_data.token)
            chain_config.chain_data.on_chain_state = OnChainState(info["service_state"])
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
            self.logger.info(f"Approving staking: {chain_config.chain_data.token}")
            sftxb.new_tx().add(
                sftxb.get_staking_approval_data(
                    service_id=chain_config.chain_data.token,
                    service_registry=CONTRACTS[ledger_config.chain]["service_registry"],
                    staking_contract=target_staking_contract,
                )
            ).settle()

            # Approve additional_staking_tokens.
            staking_params = sftxb.get_staking_params(
                staking_contract=target_staking_contract
            )

            for token_contract, min_staking_amount in staking_params[
                "additional_staking_tokens"
            ].items():
                sftxb.new_tx().add(
                    sftxb.get_erc20_approval_data(
                        spender=target_staking_contract,
                        amount=min_staking_amount,
                        erc20_contract=token_contract,
                    )
                ).settle()
                staking_contract_allowance = (
                    registry_contracts.erc20.get_instance(
                        ledger_api=sftxb.ledger_api,
                        contract_address=token_contract,
                    )
                    .functions.allowance(
                        sftxb.safe,
                        target_staking_contract,
                    )
                    .call()
                )
                self.logger.info(
                    f"Approved {staking_contract_allowance} (token {token_contract}) from {sftxb.safe} to {target_staking_contract}"
                )

            self.logger.info(f"Staking service: {chain_config.chain_data.token}")
            sftxb.new_tx().add(
                sftxb.get_staking_data(
                    service_id=chain_config.chain_data.token,
                    staking_contract=target_staking_contract,
                )
            ).settle()
            chain_config.chain_data.staked = True
            service.store()

        current_staking_program = self._get_current_staking_program(
            service,
            chain,
        )
        self.logger.info(f"{target_staking_program=}")
        self.logger.info(f"{current_staking_program=}")

    def unstake_service_on_chain(
        self, service_config_id: str, chain: t.Optional[str] = None
    ) -> None:
        """Unbond service on-chain"""
        # TODO This method has not been thoroughly reviewed. Deprecated usage in favour of Safe version.

        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain or service.home_chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        ocm = self.get_on_chain_manager(ledger_config=ledger_config)

        state = ocm.staking_status(
            service_id=chain_data.token,
            staking_contract=get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=chain_data.user_params.staking_program_id,
            ),
        )
        self.logger.info(f"Staking status for service {chain_data.token}: {state}")
        if state not in {StakingState.STAKED, StakingState.EVICTED}:
            self.logger.info("Cannot unstake service, it's not staked")
            chain_data.staked = False
            service.store()
            return

        self.logger.info(f"Unstaking service: {chain_data.token}")
        ocm.unstake(
            service_id=chain_data.token,
            staking_contract=get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=chain_data.user_params.staking_program_id,
            ),
        )
        chain_data.staked = False
        service.store()

    def unstake_service_on_chain_from_safe(
        self,
        service_config_id: str,
        chain: str,
        staking_program_id: t.Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Unbond service on-chain"""

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
            chain_data.staked = False
            service.store()
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
        chain_data.staked = False
        service.store()

    def claim_on_chain_from_safe(
        self,
        service_config_id: str,
        chain: str,
    ) -> str:
        """Claim rewards from Safe and returns transaction hash"""
        self.logger.info("claim_on_chain_from_safe")
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        staking_program_id = chain_data.user_params.staking_program_id
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        ledger_api = wallet.ledger_api(chain=ledger_config.chain, rpc=ledger_config.rpc)
        print(
            f"OLAS Balance on service Safe {chain_data.multisig}: "
            f"{get_asset_balance(ledger_api, OLAS[Chain(chain)], chain_data.multisig)}"
        )
        if (
            get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=staking_program_id,
            )
            is None
        ):
            raise RuntimeError(
                "No staking contract found for the current staking_program_id: "
                f"{staking_program_id}. Not claiming the rewards."
            )

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        receipt = (
            sftxb.new_tx()
            .add(
                sftxb.get_claiming_data(
                    service_id=chain_data.token,
                    staking_contract=get_staking_contract(
                        chain=ledger_config.chain,
                        staking_program_id=staking_program_id,
                    ),
                )
            )
            .settle()
        )
        return receipt["transactionHash"]

    def fund_service(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        service_config_id: str,
        funding_values: t.Optional[FundingValues] = None,
        from_safe: bool = True,
        task_id: t.Optional[str] = None,
    ) -> None:
        """Fund service if required."""
        service = self.load(service_config_id=service_config_id)

        for chain in service.chain_configs.keys():
            self.logger.info(f"[FUNDING_JOB] [{task_id=}] Funding {chain=}")
            self.fund_service_single_chain(
                service_config_id=service_config_id,
                funding_values=funding_values,
                from_safe=from_safe,
                chain=chain,
            )

    def fund_service_single_chain(  # pylint: disable=too-many-arguments,too-many-locals,too-many-statements
        self,
        service_config_id: str,
        rpc: t.Optional[str] = None,
        funding_values: t.Optional[FundingValues] = None,
        from_safe: bool = True,
        chain: str = "gnosis",
    ) -> None:
        """Fund service if required."""

        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        ledger_api = wallet.ledger_api(
            chain=ledger_config.chain, rpc=rpc or ledger_config.rpc
        )

        for (
            asset_address,
            fund_requirements,
        ) in chain_data.user_params.fund_requirements.items():
            on_chain_operations_buffer = 0
            if asset_address == ZERO_ADDRESS:
                on_chain_state = self._get_on_chain_state(service=service, chain=chain)
                if on_chain_state != OnChainState.DEPLOYED:
                    if chain_data.user_params.use_staking:
                        on_chain_operations_buffer = 1 + len(service.keys)
                    else:
                        on_chain_operations_buffer = (
                            chain_data.user_params.cost_of_bond
                            * (1 + len(service.keys))
                        )

            asset_funding_values = (
                funding_values.get(asset_address)
                if funding_values is not None
                else None
            )
            agent_fund_threshold = (
                asset_funding_values["agent"]["threshold"]
                if asset_funding_values is not None
                else fund_requirements.agent
            )

            for key in service.keys:
                agent_balance = get_asset_balance(
                    ledger_api=ledger_api,
                    asset_address=asset_address,
                    address=key.address,
                )
                self.logger.info(
                    f"[FUNDING_JOB] Agent {key.address} Asset: {asset_address} balance: {agent_balance}"
                )
                if agent_fund_threshold > 0:
                    self.logger.info(
                        f"[FUNDING_JOB] Required balance: {agent_fund_threshold}"
                    )
                    if agent_balance < agent_fund_threshold:
                        self.logger.info(f"[FUNDING_JOB] Funding agent {key.address}")
                        target_balance = (
                            asset_funding_values["agent"]["topup"]
                            if asset_funding_values is not None
                            else fund_requirements.agent
                        )
                        available_balance = get_asset_balance(
                            ledger_api=ledger_api,
                            asset_address=asset_address,
                            address=wallet.safes[ledger_config.chain],
                        )
                        available_balance = max(
                            available_balance - on_chain_operations_buffer, 0
                        )
                        to_transfer = max(
                            min(available_balance, target_balance - agent_balance), 0
                        )
                        self.logger.info(
                            f"[FUNDING_JOB] Transferring {to_transfer} units (asset {asset_address}) to agent {key.address}"
                        )
                        wallet.transfer_asset(
                            asset=asset_address,
                            to=key.address,
                            amount=int(to_transfer),
                            chain=ledger_config.chain,
                            from_safe=from_safe,
                            rpc=rpc or ledger_config.rpc,
                        )

            if chain_data.multisig == NON_EXISTENT_MULTISIG:
                self.logger.info("[FUNDING_JOB] Service Safe not deployed")
                continue

            safe_balance = get_asset_balance(
                ledger_api=ledger_api,
                asset_address=asset_address,
                address=chain_data.multisig,
            )
            if asset_address == ZERO_ADDRESS and chain in WRAPPED_NATIVE_ASSET:
                # also count the balance of the wrapped native asset
                safe_balance += get_asset_balance(
                    ledger_api=ledger_api,
                    asset_address=WRAPPED_NATIVE_ASSET[Chain(chain)],
                    address=chain_data.multisig,
                )

            safe_fund_treshold = (
                asset_funding_values["safe"]["threshold"]
                if asset_funding_values is not None
                else fund_requirements.safe
            )
            self.logger.info(
                f"[FUNDING_JOB] Safe {chain_data.multisig} Asset: {asset_address} balance: {safe_balance}"
            )
            self.logger.info(f"[FUNDING_JOB] Required balance: {safe_fund_treshold}")
            if safe_balance < safe_fund_treshold:
                self.logger.info("[FUNDING_JOB] Funding safe")
                target_balance = (
                    asset_funding_values["safe"]["topup"]
                    if asset_funding_values is not None
                    else fund_requirements.safe
                )
                available_balance = get_asset_balance(
                    ledger_api=ledger_api,
                    asset_address=asset_address,
                    address=wallet.safes[ledger_config.chain],
                )
                available_balance = max(
                    available_balance - on_chain_operations_buffer, 0
                )
                to_transfer = max(
                    min(available_balance, target_balance - safe_balance), 0
                )

                # TODO Possibly remove this logging
                self.logger.info(f"{available_balance=}")
                self.logger.info(f"{target_balance=}")
                self.logger.info(f"{safe_balance=}")
                self.logger.info(f"{to_transfer=}")

                if to_transfer > 0:
                    self.logger.info(
                        f"[FUNDING_JOB] Transferring {to_transfer} units (asset {asset_address}) to {chain_data.multisig}"
                    )
                    # TODO: This is a temporary fix
                    # we avoid the error here because there is a seperate prompt on the UI
                    # when not enough funds are present, and the FE doesn't let the user to start the agent.
                    # Ideally this error should be allowed, and then the FE should ask the user for more funds.
                    with suppress(RuntimeError):
                        wallet.transfer_asset(
                            asset=asset_address,
                            to=t.cast(str, chain_data.multisig),
                            amount=int(to_transfer),
                            chain=ledger_config.chain,
                            rpc=rpc or ledger_config.rpc,
                        )

    # TODO This method is possibly not used anymore
    def fund_service_erc20(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        service_config_id: str,
        token: str,
        rpc: t.Optional[str] = None,
        agent_topup: t.Optional[float] = None,
        safe_topup: t.Optional[float] = None,
        agent_fund_threshold: t.Optional[float] = None,
        safe_fund_treshold: t.Optional[float] = None,
        from_safe: bool = True,
        chain: str = "gnosis",
    ) -> None:
        """Fund service if required."""
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        ledger_api = wallet.ledger_api(
            chain=ledger_config.chain, rpc=rpc or ledger_config.rpc
        )
        agent_fund_threshold = (
            agent_fund_threshold
            or chain_data.user_params.fund_requirements[ZERO_ADDRESS].agent
        )

        for key in service.keys:
            agent_balance = ledger_api.get_balance(address=key.address)
            self.logger.info(f"Agent {key.address} balance: {agent_balance}")
            self.logger.info(f"Required balance: {agent_fund_threshold}")
            if agent_balance < agent_fund_threshold:
                self.logger.info("Funding agents")
                to_transfer = (
                    agent_topup
                    or chain_data.user_params.fund_requirements[ZERO_ADDRESS].agent
                )
                self.logger.info(f"Transferring {to_transfer} units to {key.address}")
                wallet.transfer_erc20(
                    token=token,
                    to=key.address,
                    amount=int(to_transfer),
                    chain=ledger_config.chain,
                    from_safe=from_safe,
                    rpc=rpc or ledger_config.rpc,
                )

        safe_balance = (
            registry_contracts.erc20.get_instance(ledger_api, token)
            .functions.balanceOf(chain_data.multisig)
            .call()
        )
        safe_fund_treshold = (
            safe_fund_treshold
            or chain_data.user_params.fund_requirements[ZERO_ADDRESS].safe
        )
        self.logger.info(f"Safe {chain_data.multisig} balance: {safe_balance}")
        self.logger.info(f"Required balance: {safe_fund_treshold}")
        if safe_balance < safe_fund_treshold:
            self.logger.info("Funding safe")
            to_transfer = (
                safe_topup
                or chain_data.user_params.fund_requirements[ZERO_ADDRESS].safe
            )
            self.logger.info(
                f"Transferring {to_transfer} units to {chain_data.multisig}"
            )
            wallet.transfer_erc20(
                token=token,
                to=t.cast(str, chain_data.multisig),
                amount=int(to_transfer),
                chain=ledger_config.chain,
                rpc=rpc or ledger_config.rpc,
            )

    def drain_service_safe(
        self,
        service_config_id: str,
        withdrawal_address: str,
        chain: Chain,
    ) -> None:
        """Drain the funds out of the service safe."""
        self.logger.info(
            f"Draining the safe of service: {service_config_id} on chain {chain.value}"
        )
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain.value]
        ledger_config = chain_config.ledger_config
        chain_data = chain_config.chain_data
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        ledger_api = wallet.ledger_api(chain=ledger_config.chain, rpc=ledger_config.rpc)
        ethereum_crypto = EthereumCrypto(
            private_key_path=service.path / "deployment" / "ethereum_private_key.txt",
        )

        # drain ERC20 tokens from service safe
        for token_name, token_address in (
            ("OLAS", OLAS[chain]),
            (
                f"W{get_currency_denom(chain)}",
                WRAPPED_NATIVE_ASSET[chain],
            ),
            ("USDC", USDC[chain]),
        ):
            token_instance = registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=token_address,
            )
            balance = token_instance.functions.balanceOf(chain_data.multisig).call()
            if balance == 0:
                self.logger.info(
                    f"No {token_name} to drain from service safe: {chain_data.multisig}"
                )
                continue

            self.logger.info(
                f"Draining {balance} {token_name} out of service safe: {chain_data.multisig}"
            )
            transfer_erc20_from_safe(
                ledger_api=ledger_api,
                crypto=ethereum_crypto,
                safe=chain_data.multisig,
                token=token_address,
                to=withdrawal_address,
                amount=balance,
            )

        # drain native asset from service safe
        balance = ledger_api.get_balance(chain_data.multisig)
        if balance == 0:
            self.logger.info(
                f"No {get_currency_denom(chain)} to drain from service safe: {chain_data.multisig}"
            )
        else:
            self.logger.info(
                f"Draining {balance} {get_currency_denom(chain)} out of service safe: {chain_data.multisig}"
            )
            transfer_from_safe(
                ledger_api=ledger_api,
                crypto=ethereum_crypto,
                safe=chain_data.multisig,
                to=withdrawal_address,
                amount=balance,
            )

        self.logger.info(f"{service.name} safe drained ({service_config_id=})")

    async def funding_job(
        self,
        service_config_id: str,
        loop: t.Optional[asyncio.AbstractEventLoop] = None,
        from_safe: bool = True,
    ) -> None:
        """Start a background funding job."""
        loop = loop or asyncio.get_event_loop()
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[service.home_chain]
        task = asyncio.current_task()
        task_id = id(task) if task else "Unknown task_id"
        with ThreadPoolExecutor() as executor:
            while True:
                try:
                    await loop.run_in_executor(
                        executor,
                        self.fund_service,
                        service_config_id,  # Service id
                        {
                            asset_address: {
                                "agent": {
                                    "topup": fund_requirements.agent,
                                    "threshold": int(
                                        fund_requirements.agent
                                        * DEFAULT_TOPUP_THRESHOLD
                                    ),
                                },
                                "safe": {
                                    "topup": fund_requirements.safe,
                                    "threshold": int(
                                        fund_requirements.safe * DEFAULT_TOPUP_THRESHOLD
                                    ),
                                },
                            }
                            for asset_address, fund_requirements in chain_config.chain_data.user_params.fund_requirements.items()
                        },
                        from_safe,
                        task_id,
                    )
                except Exception:  # pylint: disable=broad-except
                    logging.info(
                        f"Error occured while funding the service\n{traceback.format_exc()}"
                    )
                await asyncio.sleep(60)

    def deploy_service_locally(
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
        )
        if build_only:
            return deployment
        deployment.start(use_docker=use_docker)
        return deployment

    def stop_service_locally(
        self, service_config_id: str, delete: bool = False, use_docker: bool = False
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
        deployment.stop(use_docker)
        if delete:
            deployment.delete()
        return deployment

    def log_directories(self) -> None:
        """Log directories."""
        directories = [f"  - {str(p)}" for p in self.path.iterdir() if p.is_dir()]
        directories_str = "\n".join(directories)
        self.logger.info(f"Directories in {self.path}\n: {directories_str}")

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

    def update_all_matching(
        self,
        service_template: ServiceTemplate,
    ) -> t.List[t.Dict]:
        """Update all services with service id matching the service id from the template hash."""

        self.logger.info("update_all_matching")
        self.logger.info(f"{service_template['hash']=}")
        updated_services: t.List[t.Dict] = []
        for service in self._get_all_services():
            try:
                service.update(service_template=service_template)
                updated_services.append(service.json)
                self.logger.info(
                    f"Updated service_config_id={service.service_config_id}"
                )
            except ValueError:
                self.logger.info(
                    f"Not updated service_config_id={service.service_config_id}"
                )

        return updated_services

    def migrate_service_configs(self) -> None:
        """Migrate old service config formats to new ones, if applies."""

        bafybei_count = sum(
            1 for path in self.path.iterdir() if path.name.startswith("bafybei")
        )
        if bafybei_count > 1:
            self.log_directories()
            raise RuntimeError(
                f"Your services folder contains {bafybei_count} folders starting with 'bafybei'. This is an unintended situation. Please contact support."
            )

        paths = list(self.path.iterdir())
        for path in paths:
            try:
                if path.name.startswith(DELETE_PREFIX):
                    shutil.rmtree(path)
                    self.logger.info(f"Deleted folder: {path.name}")

                if path.name.startswith(SERVICE_CONFIG_PREFIX) or path.name.startswith(
                    "bafybei"
                ):
                    self.logger.info(f"migrate_service_configs {str(path)}")
                    migrated = Service.migrate_format(path)
                    if migrated:
                        self.logger.info(f"Folder {str(path)} has been migrated.")
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error(
                    f"Failed to migrate service: {path.name}. Exception {e}: {traceback.format_exc()}"
                )
                # Rename the invalid path
                timestamp = int(time.time())
                invalid_path = path.parent / f"invalid_{timestamp}_{path.name}"
                os.rename(path, invalid_path)
                self.logger.info(
                    f"Renamed invalid service: {path.name} to {invalid_path.name}"
                )

    def refill_requirements(  # pylint: disable=too-many-locals,too-many-statements,too-many-nested-blocks
        self, service_config_id: str
    ) -> t.Dict:
        """Get user refill requirements for a service."""
        service = self.load(service_config_id=service_config_id)

        balances: t.Dict = {}
        bonded_assets: t.Dict = {}
        protocol_asset_requirements: t.Dict = {}
        refill_requirements: t.Dict = {}
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

            agent_addresses = {key.address for key in service.keys}
            service_safe = (
                chain_data.multisig
                if chain_data.multisig and chain_data.multisig != NON_EXISTENT_MULTISIG
                else "service_safe"
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

                if asset_address == ZERO_ADDRESS and any(
                    balances[chain][master_safe][asset_address] == 0
                    and balances[chain][address][asset_address] == 0
                    and agent_asset_funding_values[address]["threshold"] > 0
                    for address in agent_asset_funding_values
                ):
                    allow_start_agent = False

            # Remove placeholder value
            refill_requirements[chain].pop("master_safe", None)

            # Refill requirements for Master EOA
            eoa_funding_values = self._get_master_eoa_native_funding_values(
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

        is_refill_required = any(
            amount > 0
            for chain in refill_requirements.values()
            for asset in chain.values()
            for amount in asset.values()
        )

        return {
            "balances": balances,
            "bonded_assets": bonded_assets,
            "refill_requirements": refill_requirements,
            "protocol_asset_requirements": protocol_asset_requirements,
            "is_refill_required": is_refill_required,
            "allow_start_agent": allow_start_agent,
        }

    def _compute_bonded_assets(  # pylint: disable=too-many-locals
        self, service_config_id: str, chain: str
    ) -> t.Dict:
        """Computes the bonded tokens: current agent bonds and current security deposit"""

        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        ledger_config = chain_config.ledger_config
        user_params = chain_config.chain_data.user_params
        wallet = self.wallet_manager.load(ledger_config.chain.ledger_type)
        bonded_assets: defaultdict = defaultdict(int)

        if Chain(chain) not in wallet.safes:
            return dict(bonded_assets)

        master_safe = wallet.safes[Chain(chain)]

        ledger_api = wallet.ledger_api(chain=ledger_config.chain, rpc=ledger_config.rpc)

        service_id = chain_config.chain_data.token
        if service_id == NON_EXISTENT_TOKEN:
            return dict(bonded_assets)

        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc

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
        current_staking_program = self._get_current_staking_program(service, chain)

        if not current_staking_program:
            return dict(bonded_assets)

        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        staking_params = sftxb.get_staking_params(
            staking_contract=get_staking_contract(
                chain=ledger_config.chain,
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

        staking_state = sftxb.staking_status(
            service_id=service_id,
            staking_contract=staking_params["staking_contract"],
        )

        if staking_state in (StakingState.STAKED, StakingState.EVICTED):
            for token, amount in staking_params["additional_staking_tokens"].items():
                bonded_assets[token] += amount

        return dict(bonded_assets)

    def _compute_protocol_asset_requirements(  # pylint: disable=too-many-locals
        self, service_config_id: str, chain: str
    ) -> t.Dict:
        """Computes the protocol asset requirements to deploy on-chain and stake (if necessary)"""
        service = self.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain]
        user_params = chain_config.chain_data.user_params
        ledger_config = chain_config.ledger_config
        number_of_agents = service.helper.config.number_of_agents
        os.environ["CUSTOM_CHAIN_RPC"] = ledger_config.rpc
        sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
        service_asset_requirements: defaultdict = defaultdict(int)

        if not user_params.use_staking or not user_params.staking_program_id:
            agent_bonds = user_params.cost_of_bond * number_of_agents
            security_deposit = user_params.cost_of_bond
            service_asset_requirements[ZERO_ADDRESS] += agent_bonds
            service_asset_requirements[ZERO_ADDRESS] += security_deposit
            return dict(service_asset_requirements)

        agent_bonds = 1 * number_of_agents
        security_deposit = 1
        service_asset_requirements[ZERO_ADDRESS] += agent_bonds
        service_asset_requirements[ZERO_ADDRESS] += security_deposit

        staking_params = sftxb.get_staking_params(
            staking_contract=get_staking_contract(
                chain=ledger_config.chain,
                staking_program_id=user_params.staking_program_id,
            ),
        )

        # This computation assumes the service will be/has been minted with these
        # parameters. Otherwise, these values should be retrieved on-chain as follows:
        # - agent_bonds: by combining the output of ServiceRegistry .getAgentParams .getService
        #   and ServiceRegistryTokenUtility .getAgentBond
        # - security_deposit: as the maximum agent bond.
        agent_bonds = staking_params["min_staking_deposit"] * number_of_agents
        security_deposit = staking_params["min_staking_deposit"]
        service_asset_requirements[staking_params["staking_token"]] += agent_bonds
        service_asset_requirements[staking_params["staking_token"]] += security_deposit

        for token, amount in staking_params["additional_staking_tokens"].items():
            service_asset_requirements[token] = amount

        return dict(service_asset_requirements)

    @staticmethod
    def _compute_refill_requirement(
        asset_funding_values: t.Dict,
        sender_topup: int = 0,
        sender_threshold: int = 0,
        sender_balance: int = 0,
    ) -> t.Dict:
        """
        Compute refill requirement.

        The `asset_funding_values` dictionary specifies the funding obligations the sender must cover for other parties.
        Additionally, the sender must ensure its own balance remains above `sender_threshold` (minimum required balance)
        and ideally reaches `sender_topup` (recommended balance). If no funding is required for the sender after covering
        the obligations for other parties, set `sender_topup = sender_threshold = 0`.

        Args:
            asset_funding_values (dict): Maps parties (identifiers) to their funding details:
                - "topup": Recommended funding balance.
                - "threshold": Minimum required balance.
                - "balance": Current balance.
            sender_topup (int): Recommended balance for the sender after meeting obligations.
            sender_threshold (int): Minimum balance required for the sender after meeting obligations.
            sender_balance (int): Sender's current balance.

        Returns:
            dict: A dictionary with:
                - "minimum_refill": The minimum amount the sender needs to add.
                - "recommended_refill": The suggested amount the sender should add.
        """
        if 0 > sender_threshold or sender_threshold > sender_topup:
            raise ValueError(
                f"Arguments must satisfy 0 <= 'sender_threshold' <= 'sender_topup' ({sender_threshold=}, {sender_topup=})."
            )

        if 0 > sender_balance:
            raise ValueError(
                f"Argument 'sender_balance' must be >= 0 ({sender_balance=})."
            )

        minimum_obligations_shortfall = 0
        recommended_obligations_shortfall = 0

        for address, requirements in asset_funding_values.items():
            topup = requirements["topup"]
            threshold = requirements["threshold"]
            balance = requirements["balance"]

            if 0 > threshold or threshold > topup:
                raise ValueError(
                    f"Arguments must satisfy 0 <= 'threshold' <= 'topup' ({address=}, {threshold=}, {topup=}, {balance=})."
                )
            if 0 > balance:
                raise ValueError(
                    f"Argument 'balance' must be >= 0 ({address=}, {balance=})."
                )

            if balance < threshold:
                minimum_obligations_shortfall += threshold - balance
                recommended_obligations_shortfall += topup - balance

        # Compute sender's remaining balance after covering obligations
        remaining_balance_minimum = sender_balance - minimum_obligations_shortfall
        remaining_balance_recommended = (
            sender_balance - recommended_obligations_shortfall
        )

        # Determine if the sender needs additional refill
        minimum_refill = 0
        recommended_refill = 0
        if remaining_balance_minimum < sender_threshold:
            minimum_refill = sender_threshold - remaining_balance_minimum

        if remaining_balance_recommended < sender_threshold:
            recommended_refill = sender_topup - remaining_balance_recommended

        return {
            "minimum_refill": minimum_refill,
            "recommended_refill": recommended_refill,
        }

    @staticmethod
    def _get_master_eoa_native_funding_values(
        master_safe_exists: bool, chain: Chain, balance: int
    ) -> t.Dict:
        funding_values = {
            True: {
                Chain.ETHEREUM: {
                    "topup": 20000000000000000,
                    "threshold": 10000000000000000,
                },
                Chain.GNOSIS: {
                    "topup": 1500000000000000000,
                    "threshold": 750000000000000000,
                },
                Chain.OPTIMISTIC: {
                    "topup": 5000000000000000,
                    "threshold": 2500000000000000,
                },
                Chain.BASE: {"topup": 5000000000000000, "threshold": 2500000000000000},
                Chain.MODE: {"topup": 500000000000000, "threshold": 250000000000000},
            },
            False: {
                Chain.ETHEREUM: {
                    "topup": 20000000000000000,
                    "threshold": 20000000000000000,
                },
                Chain.GNOSIS: {
                    "topup": 1500000000000000000,
                    "threshold": 1500000000000000000,
                },
                Chain.OPTIMISTIC: {
                    "topup": 5000000000000000,
                    "threshold": 5000000000000000,
                },
                Chain.BASE: {"topup": 5000000000000000, "threshold": 5000000000000000},
                Chain.MODE: {"topup": 500000000000000, "threshold": 500000000000000},
            },
        }

        values = funding_values[master_safe_exists][chain]
        values["balance"] = balance
        return values
