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

"""This module contains the class to connect to the `L1StandardBridge` contract."""

from enum import Enum

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


class L1StandardBridge(Contract):
    """The Service Staking contract."""

    contract_id = PublicId.from_str("valory/l1_standard_bridge:0.1.0")

    @classmethod
    def build_deposit_erc20_to_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        l1_token: str,
        l2_token: str,
        to: str,
        amount: int,
        min_gas_limit: int,
        extra_data: bytes,
    ) -> JSONLike:
        """Build depositERC20To tx."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("depositERC20To", args=[l1_token, l2_token, to, amount, min_gas_limit, extra_data])
        return dict(data=bytes.fromhex(data[2:]))