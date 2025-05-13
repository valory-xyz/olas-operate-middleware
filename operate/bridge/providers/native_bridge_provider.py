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
from operate.data.contracts.l1_standard_bridge.contract import (
    DEFAULT_BRIDGE_MIN_GAS_LIMIT,
    L1StandardBridge,
)
from operate.data.contracts.l2_standard_bridge.contract import L2StandardBridge
from operate.operate_types import Chain


BLOCK_CHUNK_SIZE = 5000

NATIVE_BRIDGE_ENDPOINTS: t.Dict[t.Any, t.Dict[str, t.Any]] = {
    (Chain.ETHEREUM.value, Chain.BASE.value): {
        "from_bridge": "0x3154Cf16ccdb4C6d922629664174b904d80F2C35",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "bridge_eta": 5 * 60,
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

ETH_BRIDGE_FINALIZED_TOPIC0 = Web3.keccak(
    text="ETHBridgeFinalized(address,address,uint256,bytes)"
).hex()
ETH_BRIDGE_FINALIZED_NON_INDEXED_TYPES = ["uint256", "bytes"]
ERC20_BRIDGE_FINALIZED_TOPIC0 = Web3.keccak(
    text="ERC20BridgeFinalized(address,address,address,address,uint256,bytes)"
).hex()
ERC20_BRIDGE_FINALIZED_NON_INDEXED_TYPES = ["address", "uint256", "bytes"]


class NativeBridgeProvider(BridgeProvider):
    """Native bridge provider."""

    def _validate(self, bridge_request: BridgeRequest) -> None:
        """Validate the bridge request."""
        from_chain = bridge_request.params["from"]["chain"]
        to_chain = bridge_request.params["to"]["chain"]

        if (from_chain, to_chain) not in NATIVE_BRIDGE_ENDPOINTS:
            raise ValueError(f"Unsupported bridge from {from_chain} to {to_chain}.")

        super()._validate(bridge_request)

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

        from_chain = bridge_request.params["from"]["chain"]
        to_chain = bridge_request.params["to"]["chain"]
        to_amount = bridge_request.params["to"]["amount"]
        bridge_eta = NATIVE_BRIDGE_ENDPOINTS[(from_chain, to_chain)]["bridge_eta"]

        message = None
        if to_amount == 0:
            self.logger.info(f"[NATIVE BRIDGE] {MESSAGE_QUOTE_ZERO}")
            message = MESSAGE_QUOTE_ZERO

        quote_data = QuoteData(
            attempts=0,
            bridge_eta=bridge_eta,
            elapsed_time=0,
            message=message,
            response=None,
            response_status=0,
            timestamp=int(time.time()),
        )
        bridge_request.quote_data = quote_data
        bridge_request.status = BridgeRequestStatus.QUOTE_DONE

    def _get_bridge_tx(
        self, bridge_request: BridgeRequest, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        self.logger.info(
            f"[NATIVE BRIDGE] Get bridge transaction for bridge request {bridge_request.id}."
        )

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
                min_gas_limit=DEFAULT_BRIDGE_MIN_GAS_LIMIT,
                extra_data=extra_data,
            )
        else:
            bridge_tx = L1_STANDARD_BRIDGE_CONTRACT.build_bridge_erc20_to_tx(
                ledger_api=ledger_api,
                contract_address=from_bridge,
                sender=from_address,
                local_token=from_token,
                remote_token=to_token,
                to=to_address,
                amount=int(to_amount),
                min_gas_limit=DEFAULT_BRIDGE_MIN_GAS_LIMIT,
                extra_data=extra_data,
            )
        self.logger.info(f"[NATIVE BRIDGE] Gas before updating {bridge_tx.get('gas')}.")
        ledger_api.update_with_gas_estimate(bridge_tx)
        self.logger.info(f"[NATIVE BRIDGE] Gas after updating {bridge_tx.get('gas')}.")
        return NativeBridgeProvider._update_with_gas_pricing(bridge_tx, ledger_api)

    def _get_approve_tx(
        self, bridge_request: BridgeRequest, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        self.logger.info(
            f"[NATIVE BRIDGE] Get appprove transaction for bridge request {bridge_request.id}."
        )

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
        approve_tx["gas"] = 200_000  # TODO backport to ERC20 contract as default
        self.logger.info(
            f"[NATIVE BRIDGE] Gas before updating {approve_tx.get('gas')}."
        )
        ledger_api.update_with_gas_estimate(approve_tx)
        self.logger.info(f"[NATIVE BRIDGE] Gas after updating {approve_tx.get('gas')}.")
        return NativeBridgeProvider._update_with_gas_pricing(approve_tx, ledger_api)

    def _get_transactions(
        self, bridge_request: BridgeRequest
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the bridge request."""
        self.logger.info(
            f"[NATIVE BRIDGE] Get transactions for bridge request {bridge_request.id}."
        )

        self._validate(bridge_request)

        if not bridge_request.quote_data:
            return []

        if bridge_request.params["to"]["amount"] == 0:
            return []

        from_ledger_api = self._from_ledger_api(bridge_request)

        bridge_tx = self._get_bridge_tx(bridge_request, from_ledger_api)

        if not bridge_tx:
            return []

        approve_tx = self._get_approve_tx(bridge_request, from_ledger_api)

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

        if bridge_request.status not in (
            BridgeRequestStatus.EXECUTION_PENDING,
            # BridgeRequestStatus.EXECUTION_UNKNOWN,
        ):
            return

        self.logger.info(
            f"[NATIVE BRIDGE] Updating execution status for bridge request {bridge_request.id}."
        )

        if not bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot update bridge request {bridge_request.id}: execution data not present."
            )

        if not bridge_request.execution_data.from_tx_hash:
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
            return

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]

        to_bridge = NATIVE_BRIDGE_ENDPOINTS[(from_chain, to_chain)]["to_bridge"]
        bridge_eta = int(NATIVE_BRIDGE_ENDPOINTS[(from_chain, to_chain)]["bridge_eta"])

        try:
            from_w3 = self._from_ledger_api(bridge_request).api

            from_tx_hash = bridge_request.execution_data.from_tx_hash
            receipt = from_w3.eth.get_transaction_receipt(from_tx_hash)
            if receipt.status == 0:
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
                return

            # Get the timestamp of the bridge_tx on the 'from' chain
            bridge_tx_receipt = from_w3.eth.get_transaction_receipt(
                from_tx_hash
            )
            bridge_tx_block = from_w3.eth.get_block(bridge_tx_receipt.blockNumber)
            bridge_tx_ts = bridge_tx_block.timestamp

            # Prepare the event data
            if from_token == ZERO_ADDRESS:
                topics = [
                    ETH_BRIDGE_FINALIZED_TOPIC0,  # ETHBridgeFinalized
                    "0x" + from_address.lower()[2:].rjust(64, "0"),  # from
                    "0x" + to_address.lower()[2:].rjust(64, "0"),  # from
                ]
                non_indexed_types = ETH_BRIDGE_FINALIZED_NON_INDEXED_TYPES
                non_indexed_values = [
                    to_amount,  # amount
                    Web3.keccak(text=bridge_request.id),  # extraData
                ]
            else:
                topics = [
                    ERC20_BRIDGE_FINALIZED_TOPIC0,  # ERC20BridgeFinalized
                    "0x" + to_token.lower()[2:].rjust(64, "0"),  # localToken
                    "0x" + from_token.lower()[2:].rjust(64, "0"),  # remoteToken
                    "0x" + from_address.lower()[2:].rjust(64, "0"),  # from
                ]
                non_indexed_types = ERC20_BRIDGE_FINALIZED_NON_INDEXED_TYPES
                non_indexed_values = [
                    to_address.lower(),  # to
                    to_amount,  # amount
                    Web3.keccak(text=bridge_request.id),  # extraData
                ]

            # Find the event on the 'to' chain
            to_w3 = self._to_ledger_api(bridge_request).api
            starting_block = self._find_block_before_timestamp(to_w3, bridge_tx_ts)
            starting_block_ts = to_w3.eth.get_block(starting_block).timestamp
            latest_block = to_w3.eth.block_number

            for from_block in range(starting_block, latest_block + 1, BLOCK_CHUNK_SIZE):
                to_block = min(from_block + BLOCK_CHUNK_SIZE - 1, latest_block)
                to_tx_hash = self._find_transaction_in_range(
                    w3=to_w3,
                    contract_address=to_bridge,
                    from_block=from_block,
                    to_block=to_block,
                    topics=topics,
                    non_indexed_types=non_indexed_types,
                    non_indexed_values=non_indexed_values,
                )
                if to_tx_hash:
                    self.logger.info(
                        f"[NATIVE BRIDGE] Execution done for {bridge_request.id}."
                    )
                    bridge_request.execution_data.to_tx_hash = to_tx_hash
                    bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
                    return

                last_block_ts = to_w3.eth.get_block(to_block).timestamp
                if last_block_ts > starting_block_ts + bridge_eta * 2:
                    self.logger.info(
                        f"[NATIVE BRIDGE] Execution failed for {bridge_request.id}: bridge exceeds 2*ETA."
                    )
                    bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
                    return

        except Exception as e:
            self.logger.error(f"Error updating execution status: {e}")
            bridge_request.status = (
                BridgeRequestStatus.EXECUTION_FAILED
            )  # TODO EXECUTION_UNKNOWN ?

    @staticmethod
    def _find_transaction_in_range(
        w3: Web3,
        contract_address: str,
        from_block: int,
        to_block: int,
        topics: list[str],
        non_indexed_types: list[str],
        non_indexed_values: list[t.Any],
    ) -> t.Optional[str]:
        """Return the transaction hash of a matching event in the given block range, if any."""
        logs = w3.eth.get_logs(
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

    @staticmethod
    def _find_block_before_timestamp(w3: Web3, timestamp: int) -> int:
        """Returns the largest block number of the block before `timestamp`."""
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

    def _get_explorer_link(self, tx_hash: str) -> str:
        """Get the explorer link for a transaction."""
        return f"https://etherscan.io/tx/{tx_hash}"  # TODO this bridge should return None here - discuss with FE
