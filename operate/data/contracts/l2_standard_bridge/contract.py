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

import eth_abi
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi
from web3 import Web3
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
        """Return the transaction hash of the matching ETHBridgeFinalized event in the given block range."""
        ledger_api = cast(EthereumApi, ledger_api)
        event_signature = "ETHBridgeFinalized(address,address,uint256,bytes)"
        event_signature_hash = Web3.keccak(text=event_signature).hex()

        topics = [
            event_signature_hash,  # ETHBridgeFinalized
            "0x" + from_.lower()[2:].rjust(64, "0"),  # from
            "0x" + to.lower()[2:].rjust(64, "0"),  # to
        ]
        non_indexed_types = ["uint256", "bytes"]
        non_indexed_values = [
            amount,  # amount
            extra_data,  # extraData
        ]

        logs = ledger_api.api.eth.get_logs(
            {
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": contract_address,
                "topics": topics,
            }
        )

        for log in logs:
            decoded = eth_abi.decode(non_indexed_types, log["data"])
            if all(a == b for a, b in zip(decoded, non_indexed_values)):
                return log["transactionHash"].hex()

        return None

    @classmethod
    def find_erc20_bridge_finalized_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        local_token: str,
        remote_token: str,
        from_: str,
        to: str,
        amount: int,
        extra_data: bytes,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> Optional[str]:
        """Return the transaction hash of the matching ERC20BridgeFinalized event in the given block range."""
        ledger_api = cast(EthereumApi, ledger_api)
        event_signature = (
            "ERC20BridgeFinalized(address,address,address,address,uint256,bytes)"
        )
        event_signature_hash = Web3.keccak(text=event_signature).hex()

        topics = [
            event_signature_hash,  # ERC20BridgeFinalized
            "0x" + local_token.lower()[2:].rjust(64, "0"),  # localToken
            "0x" + remote_token.lower()[2:].rjust(64, "0"),  # remoteToken
            "0x" + from_.lower()[2:].rjust(64, "0"),  # from
        ]
        non_indexed_types = ["address", "uint256", "bytes"]
        non_indexed_values = [
            to.lower(),  # to
            amount,  # amount
            extra_data,  # extraData
        ]

        logs = ledger_api.api.eth.get_logs(
            {
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": contract_address,
                "topics": topics,
            }
        )

        for log in logs:
            decoded = eth_abi.decode(non_indexed_types, log["data"])
            if all(a == b for a, b in zip(decoded, non_indexed_values)):
                return log["transactionHash"].hex()

        return None
