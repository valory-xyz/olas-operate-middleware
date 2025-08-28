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

"""This module contains the class to connect to the `ForeignOmnibridge` contract."""

from math import ceil
from typing import Optional

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


PLACEHOLDER_NATIVE_TOKEN_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # nosec

# DEFAULT_GAS_BRIDGE_ETH_TO = 800_000
DEFAULT_GAS_RELAY_TOKENS = 800_000

# By simulations, nonzero-ERC20-bridge gas ~ 1.05 zero-ERC20-bridge gas
NONZERO_ERC20_GAS_FACTOR = 1.15


class ForeignOmnibridge(Contract):
    """ForeignOmnibridge."""

    contract_id = PublicId.from_str("valory/foreign_omnibridge:0.1.0")

    @classmethod
    def build_relay_tokens_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender: str,
        token: str,
        receiver: str,
        amount: int,
        raise_on_try: bool = False,
    ) -> JSONLike:
        """Build bridgeERC20To tx."""
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        tx = contract_instance.functions.relayTokens(
            token, receiver, amount
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

        tx_zero = contract_instance.functions.relayTokens(
            token, receiver, 0
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

        tx["gas"] = DEFAULT_GAS_RELAY_TOKENS
        return tx

    @classmethod
    def get_tokens_bridging_initiated_message_id(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        tx_hash: str,
        token: str,
        sender: str,
        value: int,
        raise_on_try: bool = False,
    ) -> Optional[str]:
        """Get the 'messageId' for the matching 'TokensBridgingInitiated' within the transaction 'tx_hash'."""
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        receipt = ledger_api.api.eth.get_transaction_receipt(tx_hash)
        event = contract_instance.events.TokensBridgingInitiated()
        events = event.process_receipt(receipt)

        for e in events:
            args = e["args"]
            if (
                args["token"].lower() == token.lower()
                and args["sender"].lower() == sender.lower()
                and int(args["value"]) == value
            ):
                return "0x" + args["messageId"].hex()

        return None
