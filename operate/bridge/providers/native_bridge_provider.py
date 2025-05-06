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
"""Native bridge provider."""


import time
import typing as t

import eth_abi
from aea.crypto.base import LedgerApi
from autonomy.chain.base import registry_contracts
from web3 import Web3

from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequest,
    BridgeRequestStatus,
    MESSAGE_QUOTE_ZERO,
    QuoteData,
)
from operate.constants import ZERO_ADDRESS
from operate.data import DATA_DIR
from operate.data.contracts.l1_standard_bridge.contract import L1StandardBridge
from operate.data.contracts.l2_standard_bridge.contract import L2StandardBridge
from operate.operate_types import Chain


BRIDGE_MIN_GAS_LIMIT = 300000
BLOCK_CHUNK_SIZE = 5000

NATIVE_BRIDGE_ENDPOINTS = {
    (Chain.ETHEREUM.value, Chain.BASE.value): {
        "from_bridge": "0x3154Cf16ccdb4C6d922629664174b904d80F2C35",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "duration": 5 * 60,
    }
}

L1_STANDARD_BRIDGE_CONTRACT = t.cast(
    L1StandardBridge,
    L1StandardBridge.from_dir(
        directory=str(DATA_DIR / "contracts" / "l1_standard_bridge"),
    ),
)
L2_STANDARD_BRIDGE_CONTRACT = t.cast(
    L2StandardBridge,
    L2StandardBridge.from_dir(
        directory=str(DATA_DIR / "contracts" / "l2_standard_bridge"),
    ),
)

ERC20_BRIDGE_FINALIZED_TOPIC0 = Web3.keccak(
    text="ERC20BridgeFinalized(address,address,address,address,uint256,bytes)"
).hex()
ETH_BRIDGE_FINALIZED_TOPIC0 = Web3.keccak(
    text="ETHBridgeFinalized(address,address,uint256,bytes)"
).hex()


class NativeBridgeProvider(BridgeProvider):
    """Native bridge provider."""

    def create_request(self, params: t.Dict) -> BridgeRequest:
        """Create a bridge request."""
        from_chain = params["from"]["chain"]
        to_chain = params["to"]["chain"]

        if (from_chain, to_chain) not in NATIVE_BRIDGE_ENDPOINTS:
            raise ValueError(f"Unsupported bridge from {from_chain} to {to_chain}.")

        return super().create_request(params)

    def description(self) -> str:
        """Get a human-readable description of the bridge provider."""
        return "Native bridge provider."

    def quote(self, bridge_request: BridgeRequest) -> None:
        """Update the request with the quote."""
        self._validate(bridge_request)

        if bridge_request.status not in (
            BridgeRequestStatus.CREATED,
            BridgeRequestStatus.QUOTE_DONE,
            BridgeRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"Cannot quote bridge request {bridge_request.id} with status {bridge_request.status}."
            )

        if bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot quote bridge request {bridge_request.id}: execution already present."
            )

        to_amount = bridge_request.params["to"]["amount"]

        message = None
        if to_amount == 0:
            self.logger.info(f"[NATIVE BRIDGE] {MESSAGE_QUOTE_ZERO}")
            message = MESSAGE_QUOTE_ZERO

        quote_data = QuoteData(
            attempts=0,
            elapsed_time=0,
            message=message,
            response=None,
            response_status=0,
            timestamp=int(time.time()),
        )
        bridge_request.quote_data = quote_data
        bridge_request.status = BridgeRequestStatus.QUOTE_DONE

    @staticmethod
    def _get_bridge_tx(
        bridge_request: BridgeRequest, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        quote_data = bridge_request.quote_data
        if not quote_data:
            return None

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = NATIVE_BRIDGE_ENDPOINTS[(from_chain, to_chain)]["from_bridge"]
        extra_data = Web3.keccak(text=bridge_request.id)

        if from_token == ZERO_ADDRESS:
            bridge_tx = L1_STANDARD_BRIDGE_CONTRACT.build_bridge_eth_to_tx(
                ledger_api=ledger_api,
                contract_address=from_bridge,
                sender=from_address,
                to=to_address,
                amount=int(to_amount),
                min_gas_limit=BRIDGE_MIN_GAS_LIMIT,
                extra_data=extra_data,
            )
        else:
            bridge_tx = L1_STANDARD_BRIDGE_CONTRACT.build_deposit_erc20_to_tx(
                ledger_api=ledger_api,
                contract_address=from_bridge,
                sender=from_address,
                l1_token=from_token,
                l2_token=to_token,
                to=to_address,
                amount=int(to_amount),
                min_gas_limit=BRIDGE_MIN_GAS_LIMIT,
                extra_data=extra_data,
            )

        # TODO: fix this, gas estimation fails.
        bridge_tx["gas"] = 1200000  # TODO remove
        ledger_api.update_with_gas_estimate(bridge_tx)

        # w3 = Web3(Web3.HTTPProvider("https://rpc-gate.autonolas.tech/ethereum-rpc/"))
        # estimated_gas = w3.eth.estimate_gas(bridge_tx)
        # print(f"Estimated gas: {estimated_gas}")
        # from icecream import ic
        # ic(bridge_tx)

        return NativeBridgeProvider._update_with_gas_pricing(bridge_tx, ledger_api)

    @staticmethod
    def _get_approve_tx(
        bridge_request: BridgeRequest, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        quote_data = bridge_request.quote_data
        if not quote_data:
            return None

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = NATIVE_BRIDGE_ENDPOINTS[(from_chain, to_chain)]["from_bridge"]

        if from_token == ZERO_ADDRESS:
            return None

        approve_tx = registry_contracts.erc20.get_approve_tx(
            ledger_api=ledger_api,
            contract_address=from_token,
            spender=from_bridge,
            sender=from_address,
            amount=to_amount,
        )

        ledger_api.update_with_gas_estimate(approve_tx)
        return NativeBridgeProvider._update_with_gas_pricing(approve_tx, ledger_api)

    def _get_transactions(
        self, bridge_request: BridgeRequest
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the bridge request."""
        self._validate(bridge_request)

        if not bridge_request.quote_data:
            return []

        from_chain = bridge_request.params["from"]["chain"]
        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)

        bridge_tx = self._get_bridge_tx(bridge_request, ledger_api)

        if not bridge_tx:
            return []

        approve_tx = self._get_approve_tx(bridge_request, ledger_api)

        if approve_tx:
            bridge_tx["nonce"] = approve_tx["nonce"] + 1
            return [
                ("ERC20 Approve transaction", approve_tx),
                ("Bridge transaction", bridge_tx),
            ]

        return [
            ("Bridge transaction", bridge_tx),
        ]

    def _update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status. Returns `True` if the status changed."""
        self._validate(bridge_request)

        self.logger.info(
            f"[NATIVE BRIDGE] Updating execution status for {bridge_request.id}..."
        )
        if bridge_request.status not in (
            BridgeRequestStatus.EXECUTION_PENDING,
            # BridgeRequestStatus.EXECUTION_UNKNOWN,
        ):
            return

        execution_data = bridge_request.execution_data
        if not execution_data:
            raise RuntimeError(
                f"Cannot update bridge request {bridge_request.id}: execution data not present."
            )

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_token = bridge_request.params["to"]["token"]
        to_address = bridge_request.params["to"]["address"]

        to_bridge = NATIVE_BRIDGE_ENDPOINTS[(from_chain, to_chain)]["to_bridge"]
        duration = int(NATIVE_BRIDGE_ENDPOINTS[(from_chain, to_chain)]["duration"])

        try:
            chain = Chain(to_chain)
            wallet = self.wallet_manager.load(chain.ledger_type)
            ledger_api = wallet.ledger_api(chain)
            w3 = ledger_api.api

            if from_token == ZERO_ADDRESS:
                topics = [
                    ETH_BRIDGE_FINALIZED_TOPIC0,
                    "0x" + from_address.lower()[2:].rjust(64, "0"),  # from
                    "0x" + to_address.lower()[2:].rjust(64, "0"),  # from
                ]
                non_indexed_types = ["uint256", "bytes"]
            else:
                topics = [
                    ERC20_BRIDGE_FINALIZED_TOPIC0,
                    "0x" + to_token.lower()[2:].rjust(64, "0"),  # localToken
                    "0x" + from_token.lower()[2:].rjust(64, "0"),  # remoteToken
                    "0x" + from_address.lower()[2:].rjust(64, "0"),  # from
                ]
                non_indexed_types = ["address", "uint256", "bytes"]

            target_extra_data = Web3.keccak(text=bridge_request.id).hex()

            starting_block = self._find_starting_block(bridge_request)
            starting_block_ts = w3.eth.get_block(starting_block).timestamp
            latest_block = w3.eth.block_number

            for from_block in range(starting_block, latest_block + 1, BLOCK_CHUNK_SIZE):
                to_block = min(from_block + BLOCK_CHUNK_SIZE - 1, latest_block)
                event_found = self._find_event_in_range(
                    w3,
                    to_bridge,
                    from_block,
                    to_block,
                    topics,
                    non_indexed_types,
                    target_extra_data,
                )
                if event_found:
                    bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
                    return

                last_block_ts = w3.eth.get_block(to_block).timestamp
                if last_block_ts > starting_block_ts + duration * 2:
                    bridge_request.status = BridgeRequestStatus.EXECUTION_UNKNOWN
                    return

        except Exception as e:
            self.logger.error(f"Error updating execution status: {e}")
            bridge_request.status = BridgeRequestStatus.EXECUTION_UNKNOWN

    def _find_event_in_range(
        self,
        w3,
        contract_address: str,
        from_block: int,
        to_block: int,
        topics: list[str],
        non_indexed_types: list[str],
        target_extra_data: str,
    ) -> bool:
        """Check for a finalized bridge event in the given block range."""
        logs = w3.eth.get_logs(
            {
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": contract_address,
                "topics": topics,
            }
        )

        from icecream import ic

        ic(logs)

        for log in logs:
            decoded = eth_abi.decode(non_indexed_types, log["data"])
            extra_data = "0x" + decoded[-1].hex()
            if extra_data.lower() == target_extra_data.lower():
                return True

        return False

    def _find_starting_block(self, bridge_request: BridgeRequest) -> int:
        """Find the starting block for the event log search on the destination chain.

        The starting block to search for the event log is the largest block on the
        destination chain so that its timestamp is less than the timestamp of the
        bridge transaction on the source chain.
        """
        self._validate(bridge_request)

        from_chain = bridge_request.params["from"]["chain"]
        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)
        w3_source = ledger_api.api

        to_chain = bridge_request.params["to"]["chain"]
        chain = Chain(to_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)
        w3_dest = ledger_api.api

        # 1. Get timestamp of the transaction on the source chain
        tx = w3_source.eth.get_transaction_receipt(
            bridge_request.execution_data.tx_hashes[-1]
        )
        block = w3_source.eth.get_block(tx.blockNumber)
        tx_timestamp = block.timestamp

        # 2. Binary search the destination chain for block just before this timestamp
        def find_block_before_timestamp(w3, timestamp: int) -> int:
            latest = w3.eth.block_number
            low, high = 0, latest
            best = 0
            while low <= high:
                mid = (low + high) // 2
                block = w3.eth.get_block(mid)
                if block.timestamp < timestamp:
                    best = mid
                    low = mid + 1
                else:
                    high = mid - 1
            return best

        return find_block_before_timestamp(w3_dest, tx_timestamp) - 1

    def _get_explorer_link(self, tx_hash: str) -> str:
        """Get the explorer link for a transaction."""
        return f"https://etherscan.io/tx/{tx_hash}"
