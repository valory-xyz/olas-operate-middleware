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

from typing import Optional, cast

from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi
from web3.types import BlockIdentifier


class HomeOmnibridge(Contract):
    """HomeOmnibridge."""

    contract_id = PublicId.from_str("valory/home_omnibridge:0.1.0")

    @classmethod
    def find_tokens_bridged_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        token: str,
        recipient: str,
        value: int,
        message_id: bytes,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> Optional[str]:
        """Return the transaction hash of the matching TokensBridged event in the given block range."""
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        entries = contract_instance.events.TokensBridged.create_filter(
            fromBlock=from_block,
            toBlock=to_block,
            argument_filters={
                "token": token,
                "recipient": recipient,
                "messageId": message_id,
            },
        ).get_all_entries()

        for entry in entries:
            args = entry["args"]
            if args["value"] == value:
                return entry["transactionHash"].hex()
        return None
