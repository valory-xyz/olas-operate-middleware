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

from math import ceil

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


PLACEHOLDER_NATIVE_TOKEN_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # nosec

# Minimum gas required for L2 execution when bridging from L1.
# Prevents underfunded messages that could fail on L2.
DEFAULT_BRIDGE_MIN_GAS_LIMIT = 300_000

DEFAULT_GAS_BRIDGE_ETH_TO = 800_000
DEFAULT_GAS_BRIDGE_ERC20_TO = 800_000

# By simulations, nonzero-ERC20-bridge gas ~ 1.05 zero-ERC20-bridge gas
NONZERO_ERC20_GAS_FACTOR = 1.15


class L1StandardBridge(Contract):
    """Optimism L1StandardBridge."""

    contract_id = PublicId.from_str("valory/l1_standard_bridge:0.1.0")

    @classmethod
    def build_bridge_eth_to_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender: str,
        to: str,
        amount: int,
        min_gas_limit: int,
        extra_data: bytes,
        raise_on_try: bool = False,
    ) -> JSONLike:
        """Build bridgeETHTo tx."""
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        tx = contract_instance.functions.bridgeETHTo(
            to, min_gas_limit, extra_data
        ).build_transaction(
            {
                "from": sender,
                "value": amount,
                "gas": DEFAULT_GAS_BRIDGE_ETH_TO,
                "gasPrice": ledger_api.api.eth.gas_price,
                "nonce": ledger_api.api.eth.get_transaction_count(sender),
            }
        )
        return ledger_api.update_with_gas_estimate(
            transaction=tx,
            raise_on_try=raise_on_try,
        )

    @classmethod
    def build_bridge_erc20_to_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender: str,
        local_token: str,
        remote_token: str,
        to: str,
        amount: int,
        min_gas_limit: int,
        extra_data: bytes,
        raise_on_try: bool = False,
    ) -> JSONLike:
        """Build bridgeERC20To tx."""
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        tx = contract_instance.functions.bridgeERC20To(
            local_token, remote_token, to, amount, min_gas_limit, extra_data
        ).build_transaction(
            {
                "from": sender,
                "gas": 1,
                "gasPrice": ledger_api.api.eth.gas_price,
                "nonce": ledger_api.api.eth.get_transaction_count(sender),
            }
        )

        ledger_api.update_with_gas_estimate(
            transaction=tx,
            raise_on_try=raise_on_try,
        )

        if tx["gas"] > 1:
            return tx

        tx_zero = contract_instance.functions.bridgeERC20To(
            local_token, remote_token, to, 0, min_gas_limit, extra_data
        ).build_transaction(
            {
                "from": PLACEHOLDER_NATIVE_TOKEN_ADDRESS,
                "gas": 1,
                "gasPrice": ledger_api.api.eth.gas_price,
                "nonce": ledger_api.api.eth.get_transaction_count(sender),
            }
        )

        ledger_api.update_with_gas_estimate(
            transaction=tx_zero,
            raise_on_try=raise_on_try,
        )

        if tx_zero["gas"] > 1:
            tx["gas"] = ceil(tx_zero["gas"] * NONZERO_ERC20_GAS_FACTOR)
            return tx

        tx["gas"] = DEFAULT_GAS_BRIDGE_ERC20_TO
        return tx
