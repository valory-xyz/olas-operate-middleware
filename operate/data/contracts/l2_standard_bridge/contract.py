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

"""This module contains the class to connect to the `L2StandardBridge` contract."""

from typing import Optional, cast

from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi
from web3.types import BlockIdentifier


class L2StandardBridge(Contract):
    """Optimism L2StandardBridge."""

    contract_id = PublicId.from_str("valory/l2_standard_bridge:0.1.0")

    @classmethod
    def find_eth_bridge_finalized_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_: str,
        to: str,
        amount: int,
        extra_data: bytes,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> Optional[str]:
        """Return the transaction hash for the matching ETHBridgeFinalized event in the given block range."""
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        entries = contract_instance.events.ETHBridgeFinalized.create_filter(
            fromBlock=from_block,
            toBlock=to_block,
            argument_filters={
                "from": from_,
                "to": to,
            },
        ).get_all_entries()

        for entry in entries:
            args = entry["args"]
            if args["amount"] == amount and args["extraData"] == extra_data:
                return entry["transactionHash"].hex()
        return None

    @classmethod
    def find_erc20_bridge_finalized_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: int,
        to_block: int,
        local_token: str,
        remote_token: str,
        from_: str,
        to: str,
        amount: int,
        extra_data: bytes,
    ) -> Optional[str]:
        """Return the transaction hash for the matching ERC20BridgeFinalized event in the given block range."""
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        entries = contract_instance.events.ERC20BridgeFinalized.create_filter(
            fromBlock=from_block,
            toBlock=to_block,
            argument_filters={
                "localToken": local_token,
                "remoteToken": remote_token,
                "from": from_,
            },
        ).get_all_entries()

        for entry in entries:
            args = entry["args"]
            if (
                args["to"].lower() == to.lower()
                and args["amount"] == amount
                and args["extraData"] == extra_data
            ):
                return entry["transactionHash"].hex()
        return None
