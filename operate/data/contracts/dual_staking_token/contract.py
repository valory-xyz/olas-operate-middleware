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

"""This module contains the class to connect to the `DualStakingToken` contract."""

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


class DualStakingTokenContract(Contract):
    """The Staking Token contract."""

    contract_id = PublicId.from_str("valory/dual_staking_token:0.1.0")

    @classmethod
    def build_stake_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        service_id: int,
    ) -> JSONLike:
        """Build stake tx."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("stake", args=[service_id])
        return dict(data=bytes.fromhex(data[2:]))

    @classmethod
    def build_checkpoint_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Build checkpoint tx."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("checkpoint")
        return dict(data=bytes.fromhex(data[2:]))

    @classmethod
    def build_unstake_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        service_id: int,
    ) -> JSONLike:
        """Build unstake tx."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("unstake", args=[service_id])
        return dict(data=bytes.fromhex(data[2:]))

    @classmethod
    def num_services(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the number of services."""
        contract = cls.get_instance(ledger_api, contract_address)
        num_services = contract.functions.numServices().call()
        return dict(data=num_services)

    @classmethod
    def second_token(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the second token."""
        contract = cls.get_instance(ledger_api, contract_address)
        second_token = contract.functions.secondToken().call()
        return dict(data=second_token)

    @classmethod
    def second_token_amount(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the second token amount."""
        contract = cls.get_instance(ledger_api, contract_address)
        second_token_amount = contract.functions.secondTokenAmount().call()
        return dict(data=second_token_amount)

    @classmethod
    def reward_ratio(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the reward ratio."""
        contract = cls.get_instance(ledger_api, contract_address)
        reward_ratio = contract.functions.rewardRatio().call()
        return dict(data=reward_ratio)

    @classmethod
    def stake_ratio(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the stake ratio."""
        contract = cls.get_instance(ledger_api, contract_address)
        stake_ratio = contract.functions.stakeRatio().call()
        return dict(data=stake_ratio)

    @classmethod
    def staking_instance(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the staking instance."""
        contract = cls.get_instance(ledger_api, contract_address)
        staking_instance = contract.functions.stakingInstance().call()
        return dict(data=staking_instance)
