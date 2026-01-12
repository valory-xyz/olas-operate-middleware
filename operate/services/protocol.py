#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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
"""This module implements the onchain manager."""

import binascii
import contextlib
import io
import json
import logging
import os
import tempfile
import typing as t
from enum import Enum
from functools import cache, cached_property
from pathlib import Path
from typing import Optional, Union, cast

from aea.configurations.data_types import PackageType
from aea.crypto.base import Crypto, LedgerApi
from aea.helpers.base import IPFSHash, cd
from autonomy.chain.base import registry_contracts
from autonomy.chain.config import ChainConfigs, ChainType, ContractConfigs
from autonomy.chain.constants import (
    GNOSIS_SAFE_PROXY_FACTORY_CONTRACT,
    GNOSIS_SAFE_SAME_ADDRESS_MULTISIG_CONTRACT,
    MULTISEND_CONTRACT,
    RECOVERY_MODULE_CONTRACT,
    SAFE_MULTISIG_WITH_RECOVERY_MODULE_CONTRACT,
    POLY_SAFE_CREATOR_WITH_RECOVERY_MODULE_CONTRACT,
)
from autonomy.chain.metadata import publish_metadata
from autonomy.chain.service import (
    get_agent_instances,
    get_deployment_payload,
    get_deployment_with_recovery_payload,
    get_poly_safe_deployment_payload,
    get_service_info,
    get_token_deposit_amount,
)
from autonomy.chain.tx import TxSettler
from autonomy.cli.helpers.chain import MintHelper, OnChainHelper
from autonomy.cli.helpers.chain import ServiceHelper as ServiceManager
from eth_utils import to_bytes
from hexbytes import HexBytes
from web3.contract import Contract
from web3.types import TxReceipt

from operate.constants import (
    NO_STAKING_PROGRAM_ID,
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.data import DATA_DIR
from operate.data.contracts.dual_staking_token.contract import DualStakingTokenContract
from operate.data.contracts.recovery_module.contract import RecoveryModule
from operate.data.contracts.staking_token.contract import StakingTokenContract
from operate.ledger import (
    get_default_ledger_api,
    update_tx_with_gas_estimate,
    update_tx_with_gas_pricing,
)
from operate.ledger.profiles import CONTRACTS, STAKING
from operate.operate_types import Chain as OperateChain
from operate.operate_types import ContractAddresses
from operate.services.service import NON_EXISTENT_TOKEN
from operate.utils import concurrent_execute
from operate.utils.gnosis import (
    MultiSendOperation,
    SafeOperation,
    hash_payload_to_hex,
    skill_input_hex_to_payload,
)
from operate.wallet.master import MasterWallet


ETHEREUM_ERC20 = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


class StakingState(Enum):
    """Staking state enumeration for the staking."""

    UNSTAKED = 0
    STAKED = 1
    EVICTED = 2


class GnosisSafeTransaction:
    """Safe transaction"""

    def __init__(
        self,
        ledger_api: LedgerApi,
        crypto: Crypto,
        chain_type: ChainType,
        safe: str,
    ) -> None:
        """Initiliaze a Gnosis safe tx"""
        self.ledger_api = ledger_api
        self.crypto = crypto
        self.chain_type = chain_type
        self.safe = safe
        self._txs: t.List[t.Dict] = []

    def add(self, tx: t.Dict) -> "GnosisSafeTransaction":
        """Add a transaction"""
        self._txs.append(tx)
        return self

    def build(self) -> t.Dict:
        """Build the transaction."""
        multisend_data = bytes.fromhex(
            registry_contracts.multisend.get_tx_data(
                ledger_api=self.ledger_api,
                contract_address=ContractConfigs.multisend.contracts[self.chain_type],
                multi_send_txs=self._txs,
            ).get("data")[2:]
        )
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=self.ledger_api,
            contract_address=self.safe,
            value=0,
            safe_tx_gas=0,
            to_address=ContractConfigs.multisend.contracts[self.chain_type],
            data=multisend_data,
            operation=SafeOperation.DELEGATE_CALL.value,
        ).get("tx_hash")[2:]
        payload_data = hash_payload_to_hex(
            safe_tx_hash=safe_tx_hash,
            ether_value=0,
            safe_tx_gas=0,
            to_address=ContractConfigs.multisend.contracts[self.chain_type],
            operation=SafeOperation.DELEGATE_CALL.value,
            data=multisend_data,
        )
        owner = self.ledger_api.api.to_checksum_address(self.crypto.address)
        tx_params = skill_input_hex_to_payload(payload=payload_data)
        safe_tx_bytes = binascii.unhexlify(tx_params["safe_tx_hash"])
        signatures = {
            owner: self.crypto.sign_message(
                message=safe_tx_bytes,
                is_deprecated_mode=True,
            )[2:]
        }
        tx = registry_contracts.gnosis_safe.get_raw_safe_transaction(
            ledger_api=self.ledger_api,
            contract_address=self.safe,
            sender_address=owner,
            owners=(owner,),  # type: ignore
            to_address=tx_params["to_address"],
            value=tx_params["ether_value"],
            data=tx_params["data"],
            safe_tx_gas=tx_params["safe_tx_gas"],
            signatures_by_owner=signatures,
            operation=SafeOperation.DELEGATE_CALL.value,
            nonce=self.ledger_api.api.eth.get_transaction_count(owner),
        )
        update_tx_with_gas_pricing(tx, self.ledger_api)
        update_tx_with_gas_estimate(tx, self.ledger_api)
        return t.cast(t.Dict, tx)

    def settle(self) -> TxReceipt:
        """Settle the transaction."""
        return (
            TxSettler(
                ledger_api=self.ledger_api,
                crypto=self.crypto,
                chain_type=self.chain_type,
                tx_builder=self.build,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )
            .transact()
            .settle()
            .tx_receipt
        )


class StakingManager:
    """Helper class for staking a service."""

    staking_ctr = t.cast(
        StakingTokenContract,
        StakingTokenContract.from_dir(
            directory=str(DATA_DIR / "contracts" / "staking_token")
        ),
    )

    dual_staking_ctr = t.cast(
        DualStakingTokenContract,
        DualStakingTokenContract.from_dir(
            directory=str(DATA_DIR / "contracts" / "dual_staking_token")
        ),
    )

    def __init__(
        self,
        chain: OperateChain,
    ) -> None:
        """Initialize object."""
        self.chain = chain

    @property
    def ledger_api(self) -> LedgerApi:
        """Get ledger api."""
        return get_default_ledger_api(OperateChain(self.chain.value))

    @staticmethod
    @cache
    def _get_staking_params(chain: OperateChain, staking_contract: str) -> t.Dict:
        """Get staking params"""
        ledger_api = get_default_ledger_api(chain=chain)

        second_token_func = (
            lambda: None  # pylint: disable=unnecessary-lambda-assignment  # noqa: E731
        )
        second_token_amount_func = (
            lambda: None  # pylint: disable=unnecessary-lambda-assignment  # noqa: E731
        )
        try:
            instance = StakingManager.dual_staking_ctr.get_instance(
                ledger_api=ledger_api,
                contract_address=staking_contract,
            )
            second_token_func = instance.functions.secondToken().call
            second_token_amount_func = instance.functions.secondTokenAmount().call
        except Exception:  # pylint: disable=broad-except # nosec
            # Contract is not a dual staking contract

            # TODO The exception caught here should be ContractLogicError.
            # This exception is typically raised when the contract reverts with
            # a reason string. However, in some cases, the error message
            # does not contain a reason string, which means web3.py raises
            # a generic ValueError instead. It should be properly analyzed
            # what exceptions might be raised by web3.py in this case. To
            # avoid any issues we are simply catching all exceptions.
            pass

        instance = StakingManager.staking_ctr.get_instance(
            ledger_api=ledger_api,
            contract_address=staking_contract,
        )
        (
            agent_ids,
            service_registry,
            staking_token,
            service_registry_token_utility,
            min_staking_deposit,
            activity_checker,
            second_token,
            second_token_amount,
        ) = concurrent_execute(
            (instance.functions.getAgentIds().call, ()),
            (instance.functions.serviceRegistry().call, ()),
            (instance.functions.stakingToken().call, ()),
            (instance.functions.serviceRegistryTokenUtility().call, ()),
            (instance.functions.minStakingDeposit().call, ()),
            (instance.functions.activityChecker().call, ()),
            (second_token_func, ()),
            (second_token_amount_func, ()),
            ignore_exceptions=True,
        )

        output = {
            "staking_contract": staking_contract,
            "agent_ids": agent_ids,
            "service_registry": service_registry,
            "staking_token": staking_token,
            "service_registry_token_utility": service_registry_token_utility,
            "min_staking_deposit": min_staking_deposit,
            "activity_checker": activity_checker,
            "additional_staking_tokens": (
                {second_token: second_token_amount}
                if second_token and second_token_amount
                else {}
            ),
        }
        return output

    def get_staking_params(self, staking_contract: str) -> t.Dict:
        """Get staking params"""
        return StakingManager._get_staking_params(
            chain=self.chain,
            staking_contract=staking_contract,
        )

    def staking_state(self, service_id: int, staking_contract: str) -> StakingState:
        """Is the service staked?"""
        return StakingState(
            self.staking_ctr.get_instance(
                ledger_api=self.ledger_api,
                contract_address=staking_contract,
            )
            .functions.getStakingState(service_id)
            .call()
        )

    def slots_available(self, staking_contract: str) -> bool:
        """Check if there are available slots on the staking contract"""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        available = instance.functions.maxNumServices().call() - len(
            instance.functions.getServiceIds().call()
        )
        return available > 0

    def available_rewards(self, staking_contract: str) -> int:
        """Get the available staking rewards on the staking contract"""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        available_rewards = instance.functions.availableRewards().call()
        return available_rewards

    def claimable_rewards(self, staking_contract: str, service_id: int) -> int:
        """Get the claimable staking rewards on the staking contract"""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        claimable_rewards = instance.functions.calculateStakingReward(service_id).call()
        return claimable_rewards

    def service_info(self, staking_contract: str, service_id: int) -> dict:
        """Get the service onchain info"""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        service_info = instance.functions.getServiceInfo(service_id).call()
        return service_info

    def agent_ids(self, staking_contract: str) -> t.List[int]:
        """Get a list of agent IDs for the given staking contract."""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        return instance.functions.getAgentIds().call()

    def service_registry(self, staking_contract: str) -> str:
        """Retrieve the service registry address for the given staking contract."""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        return instance.functions.serviceRegistry().call()

    def staking_token(self, staking_contract: str) -> str:
        """Get the staking token address for the staking contract."""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        return instance.functions.stakingToken().call()

    def service_registry_token_utility(self, staking_contract: str) -> str:
        """Get the service registry token utility address for the staking contract."""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        return instance.functions.serviceRegistryTokenUtility().call()

    def min_staking_deposit(self, staking_contract: str) -> int:
        """Retrieve the minimum staking deposit required for the staking contract."""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        return instance.functions.minStakingDeposit().call()

    def activity_checker(self, staking_contract: str) -> str:
        """Retrieve the activity checker address for the staking contract."""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        return instance.functions.activityChecker().call()

    def check_staking_compatibility(
        self,
        service_id: int,
        staking_contract: str,
    ) -> None:
        """Check if service can be staked."""
        status = self.staking_state(service_id, staking_contract)
        if status == StakingState.STAKED:
            raise ValueError("Service already staked")

        if status == StakingState.EVICTED:
            raise ValueError("Service is evicted")

        if not self.slots_available(staking_contract):
            raise ValueError("No sataking slots available.")

    # TODO To be deprecated, only used in on-chain manager
    def stake(
        self,
        service_id: int,
        service_registry: str,
        staking_contract: str,
        key: Path,
        password: str,
    ) -> str:
        """Stake the service"""
        och = OnChainHelper(
            key=key, chain_type=ChainType(self.chain.value), password=password
        )

        self.check_staking_compatibility(
            service_id=service_id, staking_contract=staking_contract
        )

        # we make use of the ERC20 contract to build the approval transaction
        # since it has the same interface as ERC721 we might want to create
        # a ERC721 contract package
        # this is very bad way to do it but it works because the ERC721 contract expects two arguments
        # for approve call (spender, token_id), and the ERC20 contract wrapper used here from open-autonomy
        # passes the amount as the second argument.
        TxSettler(
            ledger_api=och.ledger_api,
            crypto=och.crypto,
            chain_type=och.chain_type,
            timeout=ON_CHAIN_INTERACT_TIMEOUT,
            retries=ON_CHAIN_INTERACT_RETRIES,
            sleep=ON_CHAIN_INTERACT_SLEEP,
            tx_builder=lambda: registry_contracts.erc20.get_approve_tx(
                ledger_api=och.ledger_api,
                contract_address=service_registry,
                spender=staking_contract,
                sender=och.crypto.address,
                amount=service_id,  # TODO: This is a workaround and it should be fixed
            ),
        ).transact().settle()

        return (
            TxSettler(
                ledger_api=och.ledger_api,
                crypto=och.crypto,
                chain_type=och.chain_type,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
                tx_builder=lambda: och.ledger_api.build_transaction(
                    contract_instance=self.staking_ctr.get_instance(
                        ledger_api=och.ledger_api,
                        contract_address=staking_contract,
                    ),
                    method_name="stake",
                    method_args={"serviceId": service_id},
                    tx_args={
                        "sender_address": och.crypto.address,
                    },
                    raise_on_try=True,
                ),
            )
            .transact()
            .settle()
            .tx_hash
        )

    def check_if_unstaking_possible(
        self,
        service_id: int,
        staking_contract: str,
    ) -> None:
        """Check unstaking availability"""
        if self.staking_state(
            service_id=service_id, staking_contract=staking_contract
        ) not in {StakingState.STAKED, StakingState.EVICTED}:
            raise ValueError("Service not staked.")

        ts_start = t.cast(int, self.service_info(staking_contract, service_id)[3])
        available_rewards = t.cast(
            int,
            self.staking_ctr.available_rewards(self.ledger_api, staking_contract).get(
                "data"
            ),
        )
        minimum_staking_duration = t.cast(
            int,
            self.staking_ctr.get_min_staking_duration(
                self.ledger_api, staking_contract
            ).get("data"),
        )
        current_block = self.ledger_api.api.eth.get_block("latest")
        current_timestamp = current_block.timestamp
        staked_duration = current_timestamp - ts_start
        if staked_duration < minimum_staking_duration and available_rewards > 0:
            raise ValueError("Service cannot be unstaked yet.")

    # TODO To be deprecated, only used in on-chain manager
    def unstake(
        self,
        service_id: int,
        staking_contract: str,
        key: Path,
        password: str,
    ) -> str:
        """Unstake the service"""
        och = OnChainHelper(
            key=key, chain_type=ChainType(self.chain.value), password=password
        )

        return (
            TxSettler(
                ledger_api=och.ledger_api,
                crypto=och.crypto,
                chain_type=och.chain_type,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
                tx_builder=lambda: och.ledger_api.build_transaction(
                    contract_instance=self.staking_ctr.get_instance(
                        ledger_api=och.ledger_api,
                        contract_address=staking_contract,
                    ),
                    method_name="unstake",
                    method_args={"serviceId": service_id},
                    tx_args={
                        "sender_address": och.crypto.address,
                    },
                    raise_on_try=True,
                ),
            )
            .transact()
            .settle()
            .tx_hash
        )

    def get_stake_approval_tx_data(
        self,
        service_id: int,
        service_registry: str,
        staking_contract: str,
    ) -> bytes:
        """Get stake approval tx data."""
        self.check_staking_compatibility(
            service_id=service_id,
            staking_contract=staking_contract,
        )
        return registry_contracts.erc20.get_instance(
            ledger_api=self.ledger_api,
            contract_address=service_registry,
        ).encode_abi(
            abi_element_identifier="approve",
            args=[
                staking_contract,
                service_id,
            ],
        )

    def get_stake_tx_data(self, service_id: int, staking_contract: str) -> bytes:
        """Get stake approval tx data."""
        self.check_staking_compatibility(
            service_id=service_id,
            staking_contract=staking_contract,
        )
        return self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        ).encode_abi(
            abi_element_identifier="stake",
            args=[service_id],
        )

    def get_unstake_tx_data(self, service_id: int, staking_contract: str) -> bytes:
        """Unstake the service"""
        self.check_if_unstaking_possible(
            service_id=service_id,
            staking_contract=staking_contract,
        )
        return self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        ).encode_abi(
            abi_element_identifier="unstake",
            args=[service_id],
        )

    def get_claim_tx_data(self, service_id: int, staking_contract: str) -> bytes:
        """Claim rewards for the service"""
        return self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        ).encode_abi(
            abi_element_identifier="claim",
            args=[service_id],
        )

    def get_forced_unstake_tx_data(
        self, service_id: int, staking_contract: str
    ) -> bytes:
        """Forced unstake the service"""
        return self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        ).encode_abi(
            abi_element_identifier="forcedUnstake",
            args=[service_id],
        )

    def get_staking_contract(
        self, staking_program_id: t.Optional[str]
    ) -> t.Optional[str]:
        """Get staking contract based on the config and the staking program."""
        if staking_program_id == NO_STAKING_PROGRAM_ID or staking_program_id is None:
            return None

        return STAKING[self.chain].get(
            staking_program_id,
            staking_program_id,
        )

    def get_current_staking_program(self, service_id: int) -> t.Optional[str]:
        """Get the current staking program of a service"""
        ledger_api = self.ledger_api

        if service_id == NON_EXISTENT_TOKEN:
            return None

        service_registry = registry_contracts.service_registry.get_instance(
            ledger_api=ledger_api,
            contract_address=CONTRACTS[self.chain]["service_registry"],
        )

        service_owner = service_registry.functions.ownerOf(service_id).call()

        try:
            state = self.staking_state(
                service_id=service_id, staking_contract=service_owner
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

        for staking_program_id, val in STAKING[self.chain].items():
            if val == service_owner:
                return staking_program_id

        # Fallback, if not possible to determine staking_program_id it means it's an "inner" staking contract
        # (e.g., in the case of DualStakingToken). Loop trough all the known contracts.
        for staking_program_id, staking_program_address in STAKING[self.chain].items():
            state = self.staking_state(
                service_id=service_id, staking_contract=staking_program_address
            )
            if state in (StakingState.STAKED, StakingState.EVICTED):
                return staking_program_id

        # it's staked, but we don't know which staking program
        # so the staking_program_id should be an arbitrary staking contract
        return service_owner


# TODO Backport this to Open Autonomy MintHelper class
# MintHelper should support passing custom 'description', 'name' and 'attributes'.
# If some of these fields are not defined, then it can take the current default values.
# (Version is included as an attribute.)
# The current code here is a workaround and just addresses the description,
# because modifying the name and attributes requires touching lower-level code.
# A proper refactor of this should be done in Open Autonomy.
class MintManager(MintHelper):
    """MintManager"""

    metadata_description: t.Optional[str] = None
    metadata_name: t.Optional[str] = None
    metadata_attributes: t.Optional[t.Dict[str, str]] = None

    def set_metadata_fields(
        self,
        name: t.Optional[str] = None,
        description: t.Optional[str] = None,
        attributes: t.Optional[t.Dict[str, str]] = None,
    ) -> "MintManager":
        """Set metadata fields."""
        self.metadata_name = (
            name  # Not used currently, just an indication for the OA refactor
        )
        self.metadata_description = description
        self.metadata_attributes = (
            attributes  # Not used currently, just an indication for the OA refactor
        )
        return self

    def publish_metadata(self) -> "MintManager":
        """Publish metadata."""
        self.metadata_hash, self.metadata_string = publish_metadata(
            package_id=self.package_configuration.package_id,
            package_path=self.package_path,
            nft=cast(str, self.nft),
            description=self.metadata_description
            or self.package_configuration.description,
        )
        return self


# End Backport


class _ChainUtil:
    """On chain service management."""

    def __init__(
        self,
        rpc: str,
        wallet: MasterWallet,
        contracts: ContractAddresses,
        chain_type: t.Optional[ChainType] = None,
    ) -> None:
        """On chain manager."""
        self.rpc = rpc
        self.wallet = wallet
        self.contracts = contracts
        self.chain_type = chain_type or ChainType.CUSTOM
        os.environ[f"{self.chain_type.name}_CHAIN_RPC"] = self.rpc

    def _patch(self) -> None:
        """Patch contract and chain config."""
        ChainConfigs.get(self.chain_type).rpc = self.rpc
        for name, address in self.contracts.items():
            ContractConfigs.get(name=name).contracts[self.chain_type] = address

    @property
    def safe(self) -> str:
        """Get safe address."""
        chain_id = self.ledger_api.api.eth.chain_id
        chain = OperateChain.from_id(chain_id)
        if self.wallet.safes is None:
            raise ValueError("Safes not initialized")
        if chain not in self.wallet.safes:
            raise ValueError(f"Safe for chain type {chain} not found")
        return self.wallet.safes[chain]

    @property
    def crypto(self) -> Crypto:
        """Load crypto object."""
        self._patch()
        _, crypto = OnChainHelper.get_ledger_and_crypto_objects(
            chain_type=self.chain_type,
            key=self.wallet.key_path,
            password=self.wallet.password,
        )
        return crypto

    @property
    def ledger_api(self) -> LedgerApi:
        """Load ledger api object."""
        self._patch()
        return self.wallet.ledger_api(
            chain=OperateChain.from_string(self.chain_type.value),
            rpc=self.rpc,
        )

    @cached_property
    def service_manager_address(self) -> str:
        """Get service manager contract address."""
        return ContractConfigs.service_manager.contracts[self.chain_type]

    @property
    def service_manager_instance(self) -> Contract:
        """Load service manager contract instance."""
        contract_interface = registry_contracts.service_manager.contract_interface.get(
            self.ledger_api.identifier, {}
        )
        instance = self.ledger_api.get_contract_instance(
            contract_interface,
            self.service_manager_address,
        )
        return instance

    def info(self, token_id: int) -> t.Dict:
        """Get service info."""
        self._patch()
        ledger_api, _ = OnChainHelper.get_ledger_and_crypto_objects(
            chain_type=self.chain_type
        )
        (
            security_deposit,
            multisig_address,
            config_hash,
            threshold,
            max_agents,
            number_of_agent_instances,
            service_state,
            canonical_agents,
        ) = get_service_info(
            ledger_api=ledger_api,
            chain_type=self.chain_type,
            token_id=token_id,
        )
        instances = get_agent_instances(
            ledger_api=ledger_api,
            chain_type=self.chain_type,
            token_id=token_id,
        ).get("agentInstances", [])
        return dict(
            security_deposit=security_deposit,
            multisig=multisig_address,
            config_hash=config_hash.hex(),
            threshold=threshold,
            max_agents=max_agents,
            number_of_agent_instances=number_of_agent_instances,
            service_state=service_state,
            canonical_agents=canonical_agents,
            instances=instances,
        )

    def get_agent_bond(self, service_id: int, agent_id: int) -> int:
        """Get the agent bond for a given service"""
        self._patch()

        if service_id <= 0 or agent_id <= 0:
            return 0

        ledger_api, _ = OnChainHelper.get_ledger_and_crypto_objects(
            chain_type=self.chain_type
        )
        bond = get_token_deposit_amount(
            ledger_api=ledger_api,
            chain_type=self.chain_type,
            service_id=service_id,
            agent_id=agent_id,
        )
        return bond

    def get_service_safe_owners(self, service_id: int) -> t.List[str]:
        """Get list of owners."""
        ledger_api, _ = OnChainHelper.get_ledger_and_crypto_objects(
            chain_type=self.chain_type
        )
        (
            _,
            multisig_address,
            _,
            _,
            _,
            _,
            _,
            _,
        ) = get_service_info(
            ledger_api=ledger_api,
            chain_type=self.chain_type,
            token_id=service_id,
        )

        if multisig_address == ZERO_ADDRESS:
            return []

        return registry_contracts.gnosis_safe.get_owners(
            ledger_api=ledger_api,
            contract_address=multisig_address,
        ).get("owners", [])

    def swap(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        service_id: int,
        multisig: str,
        owner_cryptos: t.List[Crypto],
        new_owner_address: str,
    ) -> None:
        """Swap safe owner."""
        logging.info(f"Swapping safe for service {service_id} [{multisig}]...")
        self._patch()
        manager = ServiceManager(
            service_id=service_id,
            chain_type=self.chain_type,
            key=self.wallet.key_path,
            password=self.wallet.password,
            timeout=ON_CHAIN_INTERACT_TIMEOUT,
            retries=ON_CHAIN_INTERACT_RETRIES,
            sleep=ON_CHAIN_INTERACT_SLEEP,
        )
        owners = [
            manager.ledger_api.api.to_checksum_address(owner_crypto.address)
            for owner_crypto in owner_cryptos
        ]
        owner_to_swap = owners[0]
        multisend_txs = []
        txd = registry_contracts.gnosis_safe.get_swap_owner_data(
            ledger_api=manager.ledger_api,
            contract_address=multisig,
            old_owner=manager.ledger_api.api.to_checksum_address(owner_to_swap),
            new_owner=manager.ledger_api.api.to_checksum_address(new_owner_address),
        ).get("data")
        multisend_txs.append(
            {
                "operation": MultiSendOperation.CALL,
                "to": multisig,
                "value": 0,
                "data": HexBytes(txd[2:]),
            }
        )
        multisend_txd = registry_contracts.multisend.get_tx_data(  # type: ignore
            ledger_api=manager.ledger_api,
            contract_address=ContractConfigs.multisend.contracts[self.chain_type],
            multi_send_txs=multisend_txs,
        ).get("data")
        multisend_data = bytes.fromhex(multisend_txd[2:])
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=manager.ledger_api,
            contract_address=multisig,
            to_address=ContractConfigs.multisend.contracts[self.chain_type],
            value=0,
            data=multisend_data,
            safe_tx_gas=0,
            operation=SafeOperation.DELEGATE_CALL.value,
        ).get("tx_hash")[2:]
        payload_data = hash_payload_to_hex(
            safe_tx_hash=safe_tx_hash,
            ether_value=0,
            safe_tx_gas=0,
            to_address=ContractConfigs.multisend.contracts[self.chain_type],
            data=multisend_data,
        )
        tx_params = skill_input_hex_to_payload(payload=payload_data)
        safe_tx_bytes = binascii.unhexlify(tx_params["safe_tx_hash"])
        owner_to_signature = {}
        for owner_crypto in owner_cryptos:
            signature = owner_crypto.sign_message(
                message=safe_tx_bytes,
                is_deprecated_mode=True,
            )
            owner_to_signature[
                manager.ledger_api.api.to_checksum_address(owner_crypto.address)
            ] = signature[2:]
        tx = registry_contracts.gnosis_safe.get_raw_safe_transaction(
            ledger_api=manager.ledger_api,
            contract_address=multisig,
            sender_address=owner_cryptos[0].address,
            owners=tuple(owners),  # type: ignore
            to_address=tx_params["to_address"],
            value=tx_params["ether_value"],
            data=tx_params["data"],
            safe_tx_gas=tx_params["safe_tx_gas"],
            signatures_by_owner=owner_to_signature,
            operation=SafeOperation.DELEGATE_CALL.value,
        )
        stx = owner_cryptos[0].sign_transaction(tx)
        tx_digest = manager.ledger_api.send_signed_transaction(stx)
        receipt = manager.ledger_api.api.eth.wait_for_transaction_receipt(tx_digest)
        if receipt["status"] != 1:
            raise RuntimeError("Error swapping owners")

    def staking_slots_available(self, staking_contract: str) -> bool:
        """Check if there are available slots on the staking contract"""
        self._patch()
        return StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).slots_available(
            staking_contract=staking_contract,
        )

    def staking_rewards_available(self, staking_contract: str) -> bool:
        """Check if there are available staking rewards on the staking contract"""
        self._patch()
        available_rewards = StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).available_rewards(
            staking_contract=staking_contract,
        )
        return available_rewards > 0

    def staking_rewards_claimable(self, staking_contract: str, service_id: int) -> bool:
        """Check if there are claimable staking rewards on the staking contract"""
        self._patch()
        claimable_rewards = StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).claimable_rewards(
            staking_contract=staking_contract,
            service_id=service_id,
        )
        return claimable_rewards > 0

    def staking_status(self, service_id: int, staking_contract: str) -> StakingState:
        """Stake the service"""
        self._patch()
        return StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).staking_state(
            service_id=service_id,
            staking_contract=staking_contract,
        )

    def get_staking_params(
        self, staking_contract: str, fallback_params: t.Optional[t.Dict] = None
    ) -> t.Dict:
        """Get agent IDs for the staking contract"""
        if staking_contract is None and fallback_params is not None:
            return fallback_params
        self._patch()
        staking_manager = StakingManager(
            chain=OperateChain(self.chain_type.value),
        )
        return staking_manager.get_staking_params(
            staking_contract=staking_contract,
        )


class OnChainManager(_ChainUtil):
    """On chain service management."""

    def mint(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        package_path: Path,
        agent_id: int,
        number_of_slots: int,
        cost_of_bond: int,
        threshold: int,
        nft: Optional[Union[Path, IPFSHash]],
        update_token: t.Optional[int] = None,
        token: t.Optional[str] = None,
        metadata_description: t.Optional[str] = None,
        skip_dependency_check: t.Optional[bool] = False,
    ) -> t.Dict:
        """Mint service."""
        # TODO: Support for update
        self._patch()
        manager = MintManager(
            chain_type=self.chain_type,
            key=self.wallet.key_path,
            password=self.wallet.password,
            update_token=update_token,
            timeout=ON_CHAIN_INTERACT_TIMEOUT,
            retries=ON_CHAIN_INTERACT_RETRIES,
            sleep=ON_CHAIN_INTERACT_SLEEP,
        )

        # Prepare for minting
        (
            manager.load_package_configuration(
                package_path=package_path, package_type=PackageType.SERVICE
            )
            .load_metadata()
            .set_metadata_fields(description=metadata_description)
            .verify_nft(nft=nft)
        )

        if skip_dependency_check is False:
            logging.warning("Skipping depencencies check")
            manager.verify_service_dependencies(agent_id=agent_id)

        manager.publish_metadata()

        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(
            io.StringIO()
        ):
            with cd(temp):
                kwargs = dict(
                    number_of_slots=number_of_slots,
                    cost_of_bond=cost_of_bond,
                    threshold=threshold,
                    token=token,
                )
                # TODO: Enable after consulting smart contracts team re a safe
                # being a service owner
                # if update_token is None:
                #     kwargs["owner"] = self.wallet.safe # noqa: F401
                method = (
                    manager.mint_service
                    if update_token is None
                    else manager.update_service
                )
                method(**kwargs)
                (metadata,) = Path(temp).glob("*.json")
                published = {
                    "token": int(Path(metadata).name.replace(".json", "")),
                    "metadata": json.loads(Path(metadata).read_text(encoding="utf-8")),
                }
        return published

    def activate(
        self,
        service_id: int,
        token: t.Optional[str] = None,
    ) -> None:
        """Activate service."""
        logging.info(f"Activating service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.wallet.key_path,
                password=self.wallet.password,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            ).check_is_service_token_secured(
                token=token,
            ).activate_service()

    def register(
        self,
        service_id: int,
        instances: t.List[str],
        agents: t.List[int],
        token: t.Optional[str] = None,
    ) -> None:
        """Register instance."""
        logging.info(f"Registering service {service_id}...")
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.wallet.key_path,
                password=self.wallet.password,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            ).check_is_service_token_secured(
                token=token,
            ).register_instance(
                instances=instances,
                agent_ids=agents,
            )

    def deploy(
        self,
        service_id: int,
        reuse_multisig: bool = False,
        token: t.Optional[str] = None,
    ) -> None:
        """Deploy service."""
        logging.info(f"Deploying service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.wallet.key_path,
                password=self.wallet.password,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            ).check_is_service_token_secured(
                token=token,
            ).deploy_service(
                reuse_multisig=reuse_multisig,
            )

    def terminate(self, service_id: int, token: t.Optional[str] = None) -> None:
        """Terminate service."""
        logging.info(f"Terminating service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.wallet.key_path,
                password=self.wallet.password,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            ).check_is_service_token_secured(
                token=token,
            ).terminate_service()

    def unbond(self, service_id: int, token: t.Optional[str] = None) -> None:
        """Unbond service."""
        logging.info(f"Unbonding service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.wallet.key_path,
                password=self.wallet.password,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            ).check_is_service_token_secured(
                token=token,
            ).unbond_service()

    def stake(
        self,
        service_id: int,
        service_registry: str,
        staking_contract: str,
    ) -> None:
        """Stake service."""
        self._patch()
        StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).stake(
            service_id=service_id,
            service_registry=service_registry,
            staking_contract=staking_contract,
            key=self.wallet.key_path,
            password=self.wallet.password,
        )

    def unstake(self, service_id: int, staking_contract: str) -> None:
        """Unstake service."""
        self._patch()
        StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).unstake(
            service_id=service_id,
            staking_contract=staking_contract,
            key=self.wallet.key_path,
            password=self.wallet.password,
        )

    def staking_status(self, service_id: int, staking_contract: str) -> StakingState:
        """Stake the service"""
        self._patch()
        return StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).staking_state(
            service_id=service_id,
            staking_contract=staking_contract,
        )


class EthSafeTxBuilder(_ChainUtil):
    """Safe Transaction builder."""

    @classmethod
    def _new_tx(
        cls, ledger_api: LedgerApi, crypto: Crypto, chain_type: ChainType, safe: str
    ) -> GnosisSafeTransaction:
        """Create a new GnosisSafeTransaction instance."""
        return GnosisSafeTransaction(
            ledger_api=ledger_api,
            crypto=crypto,
            chain_type=chain_type,
            safe=safe,
        )

    def new_tx(self) -> GnosisSafeTransaction:
        """Create a new GnosisSafeTransaction instance."""
        return EthSafeTxBuilder._new_tx(
            ledger_api=self.wallet.ledger_api(
                chain=OperateChain.from_string(self.chain_type.value),
                rpc=self.rpc,
            ),
            crypto=self.crypto,
            chain_type=self.chain_type,
            safe=t.cast(str, self.safe),
        )

    def get_mint_tx_data(  # pylint: disable=too-many-arguments
        self,
        package_path: Path,
        agent_id: int,
        number_of_slots: int,
        cost_of_bond: int,
        threshold: int,
        nft: Optional[Union[Path, IPFSHash]],
        update_token: t.Optional[int] = None,
        token: t.Optional[str] = None,
        metadata_description: t.Optional[str] = None,
        skip_depencency_check: t.Optional[bool] = False,
    ) -> t.Dict:
        """Build mint transaction."""
        # TODO: Support for update
        self._patch()
        manager = MintManager(
            chain_type=self.chain_type,
            key=self.wallet.key_path,
            password=self.wallet.password,
            update_token=update_token,
            timeout=ON_CHAIN_INTERACT_TIMEOUT,
            retries=ON_CHAIN_INTERACT_RETRIES,
            sleep=ON_CHAIN_INTERACT_SLEEP,
        )
        # Prepare for minting

        (
            manager.load_package_configuration(
                package_path=package_path, package_type=PackageType.SERVICE
            )
            .load_metadata()
            .set_metadata_fields(description=metadata_description)
            .verify_nft(nft=nft)
        )

        if skip_depencency_check is False:
            logging.warning("Skipping depencencies check")
            manager.verify_service_dependencies(agent_id=agent_id)

        manager.publish_metadata()

        instance = self.service_manager_instance
        if update_token is None:
            safe = self.safe
            txd = instance.encode_abi(
                abi_element_identifier="create",
                args=[
                    safe,
                    token or ETHEREUM_ERC20,
                    manager.metadata_hash,
                    [agent_id],
                    [[number_of_slots, cost_of_bond]],
                    threshold,
                ],
            )
        else:
            txd = instance.encode_abi(
                abi_element_identifier="update",
                args=[
                    token or ETHEREUM_ERC20,
                    manager.metadata_hash,
                    [agent_id],
                    [[number_of_slots, cost_of_bond]],
                    threshold,
                    update_token,
                ],
            )

        return {
            "to": self.service_manager_address,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_erc20_approval_data(
        self,
        spender: str,
        amount: int,
        erc20_contract: str,
    ) -> t.Dict:
        """Get activate tx data."""
        instance = registry_contracts.erc20.get_instance(
            ledger_api=self.ledger_api,
            contract_address=erc20_contract,
        )
        txd = instance.encode_abi(
            abi_element_identifier="approve",
            args=[spender, amount],
        )
        return {
            "to": erc20_contract,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_activate_data(self, service_id: int, cost_of_bond: int) -> t.Dict:
        """Get activate tx data."""
        txd = self.service_manager_instance.encode_abi(
            abi_element_identifier="activateRegistration",
            args=[service_id],
        )
        return {
            "from": self.safe,
            "to": self.service_manager_address,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": cost_of_bond,
        }

    def get_register_instances_data(
        self,
        service_id: int,
        instances: t.List[str],
        agents: t.List[int],
        cost_of_bond: int,
    ) -> t.Dict:
        """Get register instances tx data."""
        txd = self.service_manager_instance.encode_abi(
            abi_element_identifier="registerAgents",
            args=[
                service_id,
                instances,
                agents,
            ],
        )
        return {
            "from": self.safe,
            "to": self.service_manager_address,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": cost_of_bond,
        }

    def get_deploy_data_from_safe(
        self,
        service_id: int,
        master_safe: str,
        reuse_multisig: bool = False,
        use_recovery_module: bool = True,
    ) -> t.List[t.Dict[str, t.Any]]:
        """Get the deploy data instructions for a safe"""
        approve_hash_message = None
        if reuse_multisig:
            if not use_recovery_module:
                (
                    _deployment_payload,
                    approve_hash_message,
                    error,
                ) = get_reuse_multisig_from_safe_payload(
                    ledger_api=self.ledger_api,
                    chain_type=self.chain_type,
                    service_id=service_id,
                    master_safe=master_safe,
                )
                if _deployment_payload is None:
                    raise ValueError(error)
                deployment_payload = _deployment_payload
                gnosis_safe_multisig = ContractConfigs.get(
                    GNOSIS_SAFE_SAME_ADDRESS_MULTISIG_CONTRACT.name
                ).contracts[self.chain_type]
            else:
                (
                    _deployment_payload,
                    error,
                ) = get_reuse_multisig_with_recovery_from_safe_payload(
                    ledger_api=self.ledger_api,
                    chain_type=self.chain_type,
                    service_id=service_id,
                    master_safe=master_safe,
                )
                if _deployment_payload is None:
                    raise ValueError(error)
                deployment_payload = _deployment_payload
                gnosis_safe_multisig = ContractConfigs.get(
                    RECOVERY_MODULE_CONTRACT.name
                ).contracts[self.chain_type]
        else:  # Deploy a new multisig
            if not use_recovery_module:
                deployment_payload = get_deployment_payload()
                gnosis_safe_multisig = ContractConfigs.get(
                    GNOSIS_SAFE_PROXY_FACTORY_CONTRACT.name
                ).contracts[self.chain_type]
            else:
                deployment_payload = get_deployment_with_recovery_payload()
                gnosis_safe_multisig = ContractConfigs.get(
                    SAFE_MULTISIG_WITH_RECOVERY_MODULE_CONTRACT.name
                ).contracts[self.chain_type]

        deploy_data = self.service_manager_instance.encode_abi(
            abi_element_identifier="deploy",
            args=[
                service_id,
                gnosis_safe_multisig,
                deployment_payload,
            ],
        )
        deploy_message = {
            "to": self.service_manager_address,
            "data": deploy_data[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }
        if approve_hash_message is None:
            return [deploy_message]
        return [approve_hash_message, deploy_message]

    def get_deploy_poly_safe_data_from_safe(
        self,
        service_id: int,
        master_safe: str,
        crypto: Crypto,
        reuse_multisig: bool = False,
    ) -> t.List[t.Dict[str, t.Any]]:
        approve_hash_message = None
        if reuse_multisig:
            (
                _deployment_payload,
                error,
            ) = get_reuse_multisig_with_recovery_from_safe_payload(
                ledger_api=self.ledger_api,
                chain_type=self.chain_type,
                service_id=service_id,
                master_safe=master_safe,
            )
            if _deployment_payload is None:
                raise ValueError(error)
            deployment_payload = _deployment_payload
            gnosis_safe_multisig = ContractConfigs.get(
                RECOVERY_MODULE_CONTRACT.name  # Do not use POLY_SAFE_SAME_ADDRESS_WITH_RECOVERY_MODULE_CONTRACT here
            ).contracts[self.chain_type]
        else:
            deployment_payload = get_poly_safe_deployment_payload(
                ledger_api=self.ledger_api,
                chain_type=self.chain_type,
                crypto=crypto,
            )
            gnosis_safe_multisig = ContractConfigs.get(
                POLY_SAFE_CREATOR_WITH_RECOVERY_MODULE_CONTRACT.name
            ).contracts[self.chain_type]

        deploy_data = self.service_manager_instance.encode_abi(
            abi_element_identifier="deploy",
            args=[
                service_id,
                gnosis_safe_multisig,
                deployment_payload,
            ],
        )
        deploy_message = {
            "to": self.service_manager_address,
            "data": deploy_data[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }
        if approve_hash_message is None:
            return [deploy_message]
        return [approve_hash_message, deploy_message]

    def get_safe_b_native_transfer_messages(  # pylint: disable=too-many-locals
        self,
        safe_b_address: str,
        to: str,
        amount: int,
    ) -> t.Tuple[t.Dict, t.Dict]:
        """
        Build the two messages (Safe calls) to withdraw native ETH from Safe B via this Safe (owner of Safe B).

        Builds the messages to be settled by this Safe:
        1) approveHash(inner_tx_hash)
        2) execTransaction(...) to transfer ETH
        """
        safe_b_instance = registry_contracts.gnosis_safe.get_instance(
            ledger_api=self.ledger_api,
            contract_address=safe_b_address,
        )

        txs = []
        txs.append(
            {
                "to": to,
                "data": b"",
                "operation": MultiSendOperation.CALL,
                "value": amount,
            }
        )

        multisend_address = ContractConfigs.get(MULTISEND_CONTRACT.name).contracts[
            self.chain_type
        ]
        multisend_tx = registry_contracts.multisend.get_multisend_tx(
            ledger_api=self.ledger_api,
            contract_address=multisend_address,
            txs=txs,
        )

        # Compute inner Safe transaction hash
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=self.ledger_api,
            contract_address=safe_b_address,
            to_address=multisend_address,
            value=multisend_tx["value"],
            data=multisend_tx["data"],
            operation=SafeOperation.CALL.value,
        ).get("tx_hash")

        # Build approveHash message
        approve_hash_data = safe_b_instance.encode_abi(
            abi_element_identifier="approveHash",
            args=[safe_tx_hash],
        )
        approve_hash_message = {
            "to": safe_b_address,
            "data": approve_hash_data[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

        # Build execTransaction message
        exec_data = safe_b_instance.encode_abi(
            abi_element_identifier="execTransaction",
            args=[
                multisend_address,
                multisend_tx["value"],
                multisend_tx["data"],
                SafeOperation.DELEGATE_CALL.value,
                0,  # safeTxGas
                0,  # baseGas
                0,  # gasPrice
                ZERO_ADDRESS,  # gasToken
                ZERO_ADDRESS,  # refundReceiver
                get_packed_signature_for_approved_hash(owners=(self.safe,)),
            ],
        )
        exec_message = {
            "to": safe_b_address,
            "data": exec_data[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

        return approve_hash_message, exec_message

    def get_safe_b_erc20_transfer_messages(  # pylint: disable=too-many-locals
        self,
        safe_b_address: str,
        token: str,
        to: str,
        amount: int,
    ) -> t.Tuple[t.Dict, t.Dict]:
        """
        Build the two messages (Safe calls) to withdraw ERC20 from Safe B via this Safe (owner of Safe B).

        Builds the messages to be settled by this Safe:
        1) approveHash(inner_tx_hash)
        2) execTransaction(...) to transfer ERC20 tokens
        """
        safe_b_instance = registry_contracts.gnosis_safe.get_instance(
            ledger_api=self.ledger_api,
            contract_address=safe_b_address,
        )
        erc20_instance = registry_contracts.erc20.get_instance(
            ledger_api=self.ledger_api,
            contract_address=token,
        )

        txs = []
        txs.append(
            {
                "to": token,
                "data": erc20_instance.encode_abi(
                    abi_element_identifier="transfer",
                    args=[to, amount],
                ),
                "operation": MultiSendOperation.CALL,
                "value": 0,
            }
        )

        multisend_address = ContractConfigs.get(MULTISEND_CONTRACT.name).contracts[
            self.chain_type
        ]
        multisend_tx = registry_contracts.multisend.get_multisend_tx(
            ledger_api=self.ledger_api,
            contract_address=multisend_address,
            txs=txs,
        )

        # Compute inner Safe transaction hash
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=self.ledger_api,
            contract_address=safe_b_address,
            to_address=multisend_address,
            value=multisend_tx["value"],
            data=multisend_tx["data"],
            operation=SafeOperation.CALL.value,
        ).get("tx_hash")

        # Build approveHash message
        approve_hash_data = safe_b_instance.encode_abi(
            abi_element_identifier="approveHash",
            args=[safe_tx_hash],
        )
        approve_hash_message = {
            "to": safe_b_address,
            "data": approve_hash_data[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

        # Build execTransaction message
        exec_data = safe_b_instance.encode_abi(
            abi_element_identifier="execTransaction",
            args=[
                multisend_address,
                multisend_tx["value"],
                multisend_tx["data"],
                SafeOperation.DELEGATE_CALL.value,
                0,  # safeTxGas
                0,  # baseGas
                0,  # gasPrice
                ZERO_ADDRESS,  # gasToken
                ZERO_ADDRESS,  # refundReceiver
                get_packed_signature_for_approved_hash(owners=(self.safe,)),
            ],
        )
        exec_message = {
            "to": safe_b_address,
            "data": exec_data[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

        return approve_hash_message, exec_message

    def get_terminate_data(self, service_id: int) -> t.Dict:
        """Get terminate tx data."""
        txd = self.service_manager_instance.encode_abi(
            abi_element_identifier="terminate",
            args=[service_id],
        )
        return {
            "to": self.service_manager_address,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_unbond_data(self, service_id: int) -> t.Dict:
        """Get unbond tx data."""
        txd = self.service_manager_instance.encode_abi(
            abi_element_identifier="unbond",
            args=[service_id],
        )
        return {
            "to": self.service_manager_address,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_staking_approval_data(
        self,
        service_id: int,
        service_registry: str,
        staking_contract: str,
    ) -> t.Dict:
        """Get staking approval data"""
        self._patch()
        txd = StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).get_stake_approval_tx_data(
            service_id=service_id,
            service_registry=service_registry,
            staking_contract=staking_contract,
        )
        return {
            "from": self.safe,
            "to": self.contracts["service_registry"],
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_staking_data(
        self,
        service_id: int,
        staking_contract: str,
    ) -> t.Dict:
        """Get staking tx data"""
        self._patch()
        txd = StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).get_stake_tx_data(
            service_id=service_id,
            staking_contract=staking_contract,
        )
        return {
            "to": staking_contract,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_unstaking_data(
        self,
        service_id: int,
        staking_contract: str,
        force: bool = False,
    ) -> t.Dict:
        """Get unstaking tx data"""
        self._patch()
        staking_manager = StakingManager(
            chain=OperateChain(self.chain_type.value),
        )
        txd = (
            staking_manager.get_forced_unstake_tx_data(
                service_id=service_id,
                staking_contract=staking_contract,
            )
            if force
            else staking_manager.get_unstake_tx_data(
                service_id=service_id,
                staking_contract=staking_contract,
            )
        )
        return {
            "to": staking_contract,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_claiming_data(
        self,
        service_id: int,
        staking_contract: str,
    ) -> t.Dict:
        """Get claiming tx data"""
        self._patch()
        staking_manager = StakingManager(
            chain=OperateChain(self.chain_type.value),
        )
        txd = staking_manager.get_claim_tx_data(
            service_id=service_id,
            staking_contract=staking_contract,
        )
        return {
            "to": staking_contract,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def staking_slots_available(self, staking_contract: str) -> bool:
        """Stake service."""
        self._patch()
        return StakingManager(
            chain=OperateChain(self.chain_type.value),
        ).slots_available(
            staking_contract=staking_contract,
        )

    def can_unstake(self, service_id: int, staking_contract: str) -> bool:
        """Can unstake the service?"""
        self._patch()
        try:
            StakingManager(
                chain=OperateChain(self.chain_type.value),
            ).check_if_unstaking_possible(
                service_id=service_id,
                staking_contract=staking_contract,
            )
            return True
        except ValueError:
            return False

    def get_swap_data(self, service_id: int, multisig: str, owner_key: str) -> t.Dict:
        """Swap safe owner."""
        # TODO: Discuss implementation
        raise NotImplementedError()

    def get_recover_access_data(self, service_id: int) -> t.Dict:
        """Get recover access tx data."""
        instance = t.cast(
            RecoveryModule,
            RecoveryModule.from_dir(
                directory=str(DATA_DIR / "contracts" / "recovery_module"),
            ),
        ).get_instance(
            ledger_api=self.ledger_api,
            contract_address=self.contracts["recovery_module"],
        )
        # TODO Replace the line above by this one once the recovery_module is
        # included in the release of OpenAutonomy.
        # instance = registry_contracts.recovery_module.get_instance(  # noqa: E800
        #     ledger_api=self.ledger_api,  # noqa: E800
        #     contract_address=self.contracts["recovery_module"],  # noqa: E800
        # )  # noqa: E800
        txd = instance.encode_abi(
            abi_element_identifier="recoverAccess",
            args=[service_id],
        )
        return {
            "to": self.contracts["recovery_module"],
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }

    def get_enable_module_data(
        self,
        safe_address: str,
        module_address: str,
    ) -> t.Dict:
        """Get enable module tx data"""
        self._patch()
        instance = registry_contracts.gnosis_safe.get_instance(
            ledger_api=self.ledger_api,
            contract_address=safe_address,
        )
        txd = instance.encode_abi(
            abi_element_identifier="enableModule",
            args=[module_address],
        )
        return {
            "to": safe_address,
            "data": txd[2:],
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }


def get_packed_signature_for_approved_hash(owners: t.Tuple[str]) -> bytes:
    """Get the packed signatures."""
    sorted_owners = sorted(owners, key=str.lower)
    signatures = b""
    for owner in sorted_owners:
        # Convert address to bytes and ensure it is 32 bytes long (left-padded with zeros)
        r_bytes = to_bytes(hexstr=owner[2:].rjust(64, "0"))

        # `s` as 32 zero bytes
        s_bytes = b"\x00" * 32

        # `v` as a single byte
        v_bytes = to_bytes(1)

        # Concatenate r, s, and v to form the packed signature
        packed_signature = r_bytes + s_bytes + v_bytes
        signatures += packed_signature

    return signatures


def get_reuse_multisig_from_safe_payload(  # pylint: disable=too-many-locals
    ledger_api: LedgerApi,
    chain_type: ChainType,
    service_id: int,
    master_safe: str,
) -> t.Tuple[Optional[str], Optional[t.Dict[str, t.Any]], Optional[str]]:
    """Reuse multisig."""
    _, multisig_address, _, threshold, *_ = get_service_info(
        ledger_api=ledger_api,
        chain_type=chain_type,
        token_id=service_id,
    )
    if multisig_address == ZERO_ADDRESS:
        return None, None, "Cannot reuse multisig, No previous deployment exist!"

    multisend_address = ContractConfigs.get(MULTISEND_CONTRACT.name).contracts[
        chain_type
    ]
    multisig_instance = registry_contracts.gnosis_safe.get_instance(
        ledger_api=ledger_api,
        contract_address=multisig_address,
    )

    # Verify if the service was terminated properly or not
    old_owners = multisig_instance.functions.getOwners().call()
    if len(old_owners) != 1 or master_safe not in old_owners:
        return (
            None,
            None,
            "Service was not terminated properly, the service owner should be the only owner of the safe",
        )

    # Build multisend tx to add new instances as owners
    txs = []
    new_owners = t.cast(
        t.List[str],
        get_agent_instances(
            ledger_api=ledger_api,
            chain_type=chain_type,
            token_id=service_id,
        ).get("agentInstances"),
    )

    for _owner in new_owners:
        txs.append(
            {
                "to": multisig_address,
                "data": HexBytes(
                    bytes.fromhex(
                        multisig_instance.encode_abi(
                            abi_element_identifier="addOwnerWithThreshold",
                            args=[_owner, 1],
                        )[2:]
                    )
                ),
                "operation": MultiSendOperation.CALL,
                "value": 0,
            }
        )

    txs.append(
        {
            "to": multisig_address,
            "data": HexBytes(
                bytes.fromhex(
                    multisig_instance.encode_abi(
                        abi_element_identifier="removeOwner",
                        args=[new_owners[0], master_safe, 1],
                    )[2:]
                )
            ),
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }
    )

    txs.append(
        {
            "to": multisig_address,
            "data": HexBytes(
                bytes.fromhex(
                    multisig_instance.encode_abi(
                        abi_element_identifier="changeThreshold",
                        args=[threshold],
                    )[2:]
                )
            ),
            "operation": MultiSendOperation.CALL,
            "value": 0,
        }
    )

    multisend_tx = registry_contracts.multisend.get_multisend_tx(
        ledger_api=ledger_api,
        contract_address=multisend_address,
        txs=txs,
    )
    signature_bytes = get_packed_signature_for_approved_hash(owners=(master_safe,))

    safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
        ledger_api=ledger_api,
        contract_address=multisig_address,
        to_address=multisend_address,
        value=multisend_tx["value"],
        data=multisend_tx["data"],
        operation=1,
    ).get("tx_hash")
    approve_hash_data = multisig_instance.encode_abi(
        abi_element_identifier="approveHash",
        args=[
            safe_tx_hash,
        ],
    )
    approve_hash_message = {
        "to": multisig_address,
        "data": approve_hash_data[2:],
        "operation": MultiSendOperation.CALL,
        "value": 0,
    }

    safe_exec_data = multisig_instance.encode_abi(
        abi_element_identifier="execTransaction",
        args=[
            multisend_address,  # to address
            multisend_tx["value"],  # value
            multisend_tx["data"],  # data
            1,  # operation
            0,  # safe tx gas
            0,  # bas gas
            0,  # safe gas price
            ZERO_ADDRESS,  # gas token
            ZERO_ADDRESS,  # refund receiver
            signature_bytes,  # signatures
        ],
    )
    payload = multisig_address + safe_exec_data[2:]
    return payload, approve_hash_message, None


def get_reuse_multisig_with_recovery_from_safe_payload(  # pylint: disable=too-many-locals
    ledger_api: LedgerApi,
    chain_type: ChainType,
    service_id: int,
    master_safe: str,
) -> t.Tuple[Optional[str], Optional[str]]:
    """Reuse multisig."""
    _, multisig_address, _, _, *_ = get_service_info(
        ledger_api=ledger_api,
        chain_type=chain_type,
        token_id=service_id,
    )
    if multisig_address == ZERO_ADDRESS:
        return None, "Cannot reuse multisig, No previous deployment exist!"

    service_owner = master_safe

    multisig_instance = registry_contracts.gnosis_safe.get_instance(
        ledger_api=ledger_api,
        contract_address=multisig_address,
    )

    # Verify if the service was terminated properly or not
    old_owners = multisig_instance.functions.getOwners().call()
    if len(old_owners) != 1 or service_owner not in old_owners:
        return (
            None,
            "Service was not terminated properly, the service owner should be the only owner of the safe",
        )

    payload = "0x" + int(service_id).to_bytes(32, "big").hex()
    return payload, None
