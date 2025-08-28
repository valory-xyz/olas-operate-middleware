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

"""This module contains the class to connect to the `OptimismMintableERC20` contract."""


from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


class OptimismMintableERC20(Contract):
    """Optimism OptimismMintableERC20."""

    contract_id = PublicId.from_str("valory/optimism_mintable_erc20:0.1.0")

    @classmethod
    def l1_token(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """l1Token"""
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        l1_token = contract_instance.functions.l1Token().call()
        return dict(data=l1_token)
