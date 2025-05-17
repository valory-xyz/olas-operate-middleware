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
from math import ceil

from autonomy.chain.base import registry_contracts
from web3 import Web3

from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequest,
    BridgeRequestStatus,
    GAS_ESTIMATE_BUFFER,
    MESSAGE_EXECUTION_FAILED,
    MESSAGE_EXECUTION_FAILED_ETA,
    MESSAGE_EXECUTION_FAILED_REVERTED,
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
from operate.ledger.profiles import ERC20_TOKENS
from operate.operate_types import Chain


BLOCK_CHUNK_SIZE = 5000

NATIVE_BRIDGE_ENDPOINTS: t.Dict[t.Any, t.Dict[str, t.Any]] = {
    (Chain.ETHEREUM, Chain.BASE): {
        "from_bridge": "0x3154Cf16ccdb4C6d922629664174b904d80F2C35",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "bridge_eta": 5 * 60,
    },
    (Chain.ETHEREUM, Chain.MODE): {
        "from_bridge": "0x735aDBbE72226BD52e818E7181953f42E3b0FF21",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "bridge_eta": 5 * 60,
    },
    (Chain.ETHEREUM, Chain.OPTIMISTIC): {
        "from_bridge": "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "bridge_eta": 5 * 60,
    },
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


class NativeBridgeProvider(BridgeProvider):
    """Native bridge provider."""

    def can_handle_request(self, params: t.Dict) -> bool:
        """Returns 'true' if the bridge can handle a request for 'params'."""

        if not super().can_handle_request(params):
            return False

        from_chain = Chain(params["from"]["chain"])
        from_token = params["from"]["token"]
        to_chain = Chain(params["to"]["chain"])
        to_token = params["to"]["token"]

        if (from_chain, to_chain) not in NATIVE_BRIDGE_ENDPOINTS:
            self.logger.warning(
                f"[NATIVE BRIDGE] Unsupported bridge from {from_chain} to {to_chain}."
            )
            return False

        if from_token == ZERO_ADDRESS and to_token == ZERO_ADDRESS:
            return True

        for token_map in ERC20_TOKENS:
            if (
                from_chain in token_map
                and to_chain in token_map
                and token_map[from_chain].lower() == from_token.lower()
                and token_map[to_chain].lower() == to_token.lower()
            ):
                return True

        self.logger.warning(
            f"[NATIVE BRIDGE] Unsupported token pair: {from_chain} {from_token} -> {to_chain} {to_token}"
        )
        return False

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
        bridge_eta = NATIVE_BRIDGE_ENDPOINTS[(Chain(from_chain), Chain(to_chain))][
            "bridge_eta"
        ]

        message = None
        if to_amount == 0:
            self.logger.info(f"[NATIVE BRIDGE] {MESSAGE_QUOTE_ZERO}")
            message = MESSAGE_QUOTE_ZERO

        quote_data = QuoteData(
            bridge_eta=bridge_eta,
            elapsed_time=0,
            message=message,
            provider_data=None,
            timestamp=int(time.time()),
        )
        bridge_request.quote_data = quote_data
        bridge_request.status = BridgeRequestStatus.QUOTE_DONE

    def _get_bridge_tx(self, bridge_request: BridgeRequest) -> t.Optional[t.Dict]:
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
        from_bridge = NATIVE_BRIDGE_ENDPOINTS[(Chain(from_chain), Chain(to_chain))][
            "from_bridge"
        ]
        from_ledger_api = self._from_ledger_api(bridge_request)

        extra_data = Web3.keccak(text=bridge_request.id)

        if from_token == ZERO_ADDRESS:
            bridge_tx = L1_STANDARD_BRIDGE_CONTRACT.build_bridge_eth_to_tx(
                ledger_api=from_ledger_api,
                contract_address=from_bridge,
                sender=from_address,
                to=to_address,
                amount=int(to_amount),
                min_gas_limit=DEFAULT_BRIDGE_MIN_GAS_LIMIT,
                extra_data=extra_data,
            )
        else:
            bridge_tx = L1_STANDARD_BRIDGE_CONTRACT.build_bridge_erc20_to_tx(
                ledger_api=from_ledger_api,
                contract_address=from_bridge,
                sender=from_address,
                local_token=from_token,
                remote_token=to_token,
                to=to_address,
                amount=int(to_amount),
                min_gas_limit=DEFAULT_BRIDGE_MIN_GAS_LIMIT,
                extra_data=extra_data,
            )
        BridgeProvider._update_with_gas_pricing(bridge_tx, from_ledger_api)
        BridgeProvider._update_with_gas_estimate(bridge_tx, from_ledger_api)
        bridge_tx["gas"] = ceil(bridge_tx["gas"] * GAS_ESTIMATE_BUFFER)
        return bridge_tx

    def _get_approve_tx(self, bridge_request: BridgeRequest) -> t.Optional[t.Dict]:
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
        from_bridge = NATIVE_BRIDGE_ENDPOINTS[(Chain(from_chain), Chain(to_chain))][
            "from_bridge"
        ]
        from_ledger_api = self._from_ledger_api(bridge_request)

        if from_token == ZERO_ADDRESS:
            return None

        approve_tx = registry_contracts.erc20.get_approve_tx(
            ledger_api=from_ledger_api,
            contract_address=from_token,
            spender=from_bridge,
            sender=from_address,
            amount=to_amount,
        )
        approve_tx["gas"] = 200_000  # TODO backport to ERC20 contract as default
        BridgeProvider._update_with_gas_pricing(approve_tx, from_ledger_api)
        BridgeProvider._update_with_gas_estimate(approve_tx, from_ledger_api)
        approve_tx["gas"] = ceil(approve_tx["gas"] * GAS_ESTIMATE_BUFFER)
        return approve_tx

    def _get_transactions(
        self, bridge_request: BridgeRequest
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the bridge request."""
        self.logger.info(
            f"[NATIVE BRIDGE] Get transactions for bridge request {bridge_request.id}."
        )

        if not bridge_request.quote_data:
            return []

        if bridge_request.params["to"]["amount"] == 0:
            return []

        bridge_tx = self._get_bridge_tx(bridge_request)

        if not bridge_tx:
            return []

        approve_tx = self._get_approve_tx(bridge_request)

        if not approve_tx:
            return [
                ("bridge_tx", bridge_tx),
            ]

        bridge_tx["nonce"] = approve_tx["nonce"] + 1
        return [
            ("approve_tx", approve_tx),
            ("bridge_tx", bridge_tx),
        ]

    def _update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status. Returns `True` if the status changed."""

        if bridge_request.status not in (BridgeRequestStatus.EXECUTION_PENDING,):
            return

        self.logger.info(
            f"[NATIVE BRIDGE] Updating execution status for bridge request {bridge_request.id}."
        )

        if not bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot update bridge request {bridge_request.id}: execution data not present."
            )

        execution_data = bridge_request.execution_data
        if not execution_data.from_tx_hash:
            execution_data.message = (
                f"{MESSAGE_EXECUTION_FAILED} missing transaction hash."
            )
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
            return

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]

        to_bridge = NATIVE_BRIDGE_ENDPOINTS[(Chain(from_chain), Chain(to_chain))][
            "to_bridge"
        ]
        bridge_eta = NATIVE_BRIDGE_ENDPOINTS[(Chain(from_chain), Chain(to_chain))][
            "bridge_eta"
        ]

        try:
            from_ledger_api = self._from_ledger_api(bridge_request)
            from_w3 = from_ledger_api.api

            from_tx_hash = execution_data.from_tx_hash
            receipt = from_w3.eth.get_transaction_receipt(from_tx_hash)
            if receipt.status == 0:
                execution_data.message = MESSAGE_EXECUTION_FAILED_REVERTED
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
                return

            # Get the timestamp of the bridge_tx on the 'from' chain
            bridge_tx_receipt = from_w3.eth.get_transaction_receipt(from_tx_hash)
            bridge_tx_block = from_w3.eth.get_block(bridge_tx_receipt.blockNumber)
            bridge_tx_ts = bridge_tx_block.timestamp

            # Find the event on the 'to' chain
            to_ledger_api = self._to_ledger_api(bridge_request)
            to_w3 = to_ledger_api.api
            starting_block = self._find_block_before_timestamp(to_w3, bridge_tx_ts)
            starting_block_ts = to_w3.eth.get_block(starting_block).timestamp
            latest_block = to_w3.eth.block_number

            for from_block in range(starting_block, latest_block + 1, BLOCK_CHUNK_SIZE):
                to_block = min(from_block + BLOCK_CHUNK_SIZE - 1, latest_block)

                if from_token == ZERO_ADDRESS:
                    to_tx_hash = (
                        L2_STANDARD_BRIDGE_CONTRACT.find_eth_bridge_finalized_tx(
                            ledger_api=to_ledger_api,
                            contract_address=to_bridge,
                            from_block=from_block,
                            to_block=to_block,
                            from_=from_address,
                            to=to_address,
                            amount=to_amount,
                            extra_data=Web3.keccak(text=bridge_request.id),
                        )
                    )
                else:
                    to_tx_hash = (
                        L2_STANDARD_BRIDGE_CONTRACT.find_erc20_bridge_finalized_tx(
                            ledger_api=to_ledger_api,
                            contract_address=to_bridge,
                            from_block=from_block,
                            to_block=to_block,
                            local_token=to_token,
                            remote_token=from_token,
                            from_=from_address,
                            to=to_address,
                            amount=to_amount,
                            extra_data=Web3.keccak(text=bridge_request.id),
                        )
                    )

                if to_tx_hash:
                    self.logger.info(
                        f"[NATIVE BRIDGE] Execution done for {bridge_request.id}."
                    )
                    execution_data.to_tx_hash = to_tx_hash
                    execution_data.elapsed_time = BridgeProvider._tx_timestamp(
                        to_tx_hash, to_ledger_api
                    ) - BridgeProvider._tx_timestamp(from_tx_hash, from_ledger_api)
                    bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
                    return

                last_block_ts = to_w3.eth.get_block(to_block).timestamp
                if last_block_ts > starting_block_ts + bridge_eta * 2:
                    self.logger.info(
                        f"[NATIVE BRIDGE] Execution failed for {bridge_request.id}: bridge exceeds 2*ETA."
                    )
                    execution_data.message = MESSAGE_EXECUTION_FAILED_ETA
                    bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
                    return

        except Exception as e:
            self.logger.error(f"Error updating execution status: {e}")
            execution_data.message = f"{MESSAGE_EXECUTION_FAILED} {str(e)}"
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED

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
