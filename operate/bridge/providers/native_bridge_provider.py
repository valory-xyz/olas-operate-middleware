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


import logging
import time
import typing as t
from abc import ABC, abstractmethod
from math import ceil

from aea.common import JSONLike
from aea.crypto.base import LedgerApi
from autonomy.chain.base import registry_contracts
from eth_typing import BlockIdentifier
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
from operate.data.contracts.foreign_omnibridge.contract import ForeignOmnibridge
from operate.data.contracts.home_omnibridge.contract import HomeOmnibridge
from operate.data.contracts.l1_standard_bridge.contract import (
    DEFAULT_BRIDGE_MIN_GAS_LIMIT,
    L1StandardBridge,
)
from operate.data.contracts.l2_standard_bridge.contract import L2StandardBridge
from operate.ledger.profiles import ERC20_TOKENS, OLAS, USDC, WRAPPED_NATIVE_ASSET
from operate.operate_types import Chain
from operate.wallet.master import MasterWalletManager


BLOCK_CHUNK_SIZE = 5000


class BridgeContractAdaptor(ABC):
    """Adaptor class for bridge contract packages."""

    BRIDGE_PARAMS: t.Dict

    def can_handle_request(self, params: t.Dict) -> bool:
        """Returns 'true' if the contract adaptor can handle a request for 'params'."""
        from_chain = Chain(params["from"]["chain"])
        from_token = params["from"]["token"]
        to_chain = Chain(params["to"]["chain"])
        to_token = params["to"]["token"]

        if (from_chain, to_chain) not in self.BRIDGE_PARAMS:
            return False

        bridge_params = self.BRIDGE_PARAMS[(from_chain, to_chain)]

        if from_token not in bridge_params["supported_from_tokens"]:
            return False

        for token_map in ERC20_TOKENS:
            if (
                from_chain in token_map
                and to_chain in token_map
                and token_map[from_chain].lower() == from_token.lower()
                and token_map[to_chain].lower() == to_token.lower()
            ):
                return True

        return False

    @abstractmethod
    def build_bridge_tx(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> JSONLike:
        """Build bridge transaction."""
        raise NotImplementedError()

    @abstractmethod
    def find_bridge_finalized_tx(
        self,
        from_ledger_api: LedgerApi,
        to_ledger_api: LedgerApi,
        bridge_request: BridgeRequest,
        from_block: BlockIdentifier,
        to_block: BlockIdentifier,
    ) -> t.Optional[str]:
        """Return the transaction hash of the event indicating bridge completion."""
        raise NotImplementedError()


class OptimismContractAdaptor(BridgeContractAdaptor):
    """Adaptor class for Optimism contract packages."""

    BRIDGE_PARAMS: t.Dict[t.Any, t.Dict[str, t.Any]] = {
        (Chain.ETHEREUM, Chain.BASE): {
            "from_bridge": "0x3154Cf16ccdb4C6d922629664174b904d80F2C35",
            "to_bridge": "0x4200000000000000000000000000000000000010",
            "bridge_eta": 5 * 60,
            "supported_from_tokens": (
                ZERO_ADDRESS,
                WRAPPED_NATIVE_ASSET[Chain.ETHEREUM],
                OLAS[Chain.ETHEREUM],
                USDC[Chain.ETHEREUM],
            ),
        },
        (Chain.ETHEREUM, Chain.MODE): {
            "from_bridge": "0x735aDBbE72226BD52e818E7181953f42E3b0FF21",
            "to_bridge": "0x4200000000000000000000000000000000000010",
            "bridge_eta": 5 * 60,
            "supported_from_tokens": (
                ZERO_ADDRESS,
                WRAPPED_NATIVE_ASSET[Chain.ETHEREUM],
                OLAS[Chain.ETHEREUM],
                USDC[Chain.ETHEREUM],
            ),
        },
        (Chain.ETHEREUM, Chain.OPTIMISTIC): {
            "from_bridge": "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1",
            "to_bridge": "0x4200000000000000000000000000000000000010",
            "bridge_eta": 5 * 60,
            "supported_from_tokens": (
                ZERO_ADDRESS,
                WRAPPED_NATIVE_ASSET[Chain.ETHEREUM],
                OLAS[Chain.ETHEREUM],
                USDC[Chain.ETHEREUM],
            ),
        },
    }

    _l1_standard_bridge_contract = t.cast(
        L1StandardBridge,
        L1StandardBridge.from_dir(
            directory=str(DATA_DIR / "contracts" / "l1_standard_bridge"),
        ),
    )
    _l2_standard_bridge_contract = t.cast(
        L2StandardBridge,
        L2StandardBridge.from_dir(
            directory=str(DATA_DIR / "contracts" / "l2_standard_bridge"),
        ),
    )

    def build_bridge_tx(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> JSONLike:
        """Build bridge transaction."""
        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = self.BRIDGE_PARAMS[(Chain(from_chain), Chain(to_chain))][
            "from_bridge"
        ]
        extra_data = Web3.keccak(text=bridge_request.id)

        if from_token == ZERO_ADDRESS:
            return self._l1_standard_bridge_contract.build_bridge_eth_to_tx(
                ledger_api=from_ledger_api,
                contract_address=from_bridge,
                sender=from_address,
                to=to_address,
                amount=int(to_amount),
                min_gas_limit=DEFAULT_BRIDGE_MIN_GAS_LIMIT,
                extra_data=extra_data,
            )

        return self._l1_standard_bridge_contract.build_bridge_erc20_to_tx(
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

    def find_bridge_finalized_tx(
        self,
        from_ledger_api: LedgerApi,
        to_ledger_api: LedgerApi,
        bridge_request: BridgeRequest,
        from_block: BlockIdentifier,
        to_block: BlockIdentifier,
    ) -> t.Optional[str]:
        """Return the transaction hash of the event indicating bridge completion."""
        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        to_bridge = self.BRIDGE_PARAMS[(Chain(from_chain), Chain(to_chain))][
            "to_bridge"
        ]
        extra_data = Web3.keccak(text=bridge_request.id)

        if from_token == ZERO_ADDRESS:
            return self._l2_standard_bridge_contract.find_eth_bridge_finalized_tx(
                ledger_api=to_ledger_api,
                contract_address=to_bridge,
                from_=from_address,
                to=to_address,
                amount=to_amount,
                extra_data=extra_data,
                from_block=from_block,
                to_block=to_block,
            )

        return self._l2_standard_bridge_contract.find_erc20_bridge_finalized_tx(
            ledger_api=to_ledger_api,
            contract_address=to_bridge,
            local_token=to_token,
            remote_token=from_token,
            from_=from_address,
            to=to_address,
            amount=to_amount,
            extra_data=extra_data,
            from_block=from_block,
            to_block=to_block,
        )


class OmnibridgeContractAdaptor(BridgeContractAdaptor):
    """Adaptor class for Omnibridge contract packages."""

    BRIDGE_PARAMS: t.Dict[t.Any, t.Dict[str, t.Any]] = {
        (Chain.ETHEREUM, Chain.GNOSIS): {
            "from_bridge": "0x88ad09518695c6c3712AC10a214bE5109a655671",
            "to_bridge": "0xf6A78083ca3e2a662D6dd1703c939c8aCE2e268d",
            "bridge_eta": 30 * 60,
            "supported_from_tokens": (
                WRAPPED_NATIVE_ASSET[Chain.ETHEREUM],
                OLAS[Chain.ETHEREUM],
                USDC[Chain.ETHEREUM],
            ),
        },
    }

    _foreign_omnibridge = t.cast(
        ForeignOmnibridge,
        ForeignOmnibridge.from_dir(
            directory=str(DATA_DIR / "contracts" / "foreign_omnibridge"),
        ),
    )

    _home_omnibridge = t.cast(
        HomeOmnibridge,
        HomeOmnibridge.from_dir(
            directory=str(DATA_DIR / "contracts" / "home_omnibridge"),
        ),
    )

    def build_bridge_tx(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> JSONLike:
        """Build bridge transaction."""
        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = self.BRIDGE_PARAMS[(Chain(from_chain), Chain(to_chain))][
            "from_bridge"
        ]

        if from_token == ZERO_ADDRESS:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not support bridge native tokens."
            )

        return self._foreign_omnibridge.build_relay_tokens_tx(
            ledger_api=from_ledger_api,
            contract_address=from_bridge,
            sender=from_address,
            token=from_token,
            receiver=to_address,
            amount=to_amount,
        )

    def find_bridge_finalized_tx(
        self,
        from_ledger_api: LedgerApi,
        to_ledger_api: LedgerApi,
        bridge_request: BridgeRequest,
        from_block: BlockIdentifier,
        to_block: BlockIdentifier,
    ) -> t.Optional[str]:
        """Return the transaction hash of the event indicating bridge completion."""
        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        from_tx_hash = bridge_request.execution_data.from_tx_hash
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = self.BRIDGE_PARAMS[(Chain(from_chain), Chain(to_chain))][
            "from_bridge"
        ]
        to_bridge = self.BRIDGE_PARAMS[(Chain(from_chain), Chain(to_chain))][
            "to_bridge"
        ]

        if from_token == ZERO_ADDRESS:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not support bridge native tokens."
            )

        message_id = self._foreign_omnibridge.get_tokens_bridging_initiated_message_id(
            ledger_api=from_ledger_api,
            contract_address=from_bridge,
            tx_hash=from_tx_hash,
            token=from_token,
            sender=from_address,
            value=to_amount,
        )

        if not message_id:
            raise RuntimeError(
                f"Cannot find 'messageId' in transaction {from_tx_hash}."
            )

        return self._home_omnibridge.find_tokens_bridged_tx(
            ledger_api=to_ledger_api,
            contract_address=to_bridge,
            token=to_token,
            recipient=to_address,
            value=to_amount,
            message_id=message_id,
            from_block=from_block,
            to_block=to_block,
        )


class NativeBridgeProvider(BridgeProvider):
    """Native bridge provider"""

    def __init__(
        self,
        bridge_contract_adaptor: BridgeContractAdaptor,
        provider_id: str,
        wallet_manager: MasterWalletManager,
        logger: t.Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the bridge provider."""
        self.bridge_contract_adaptor = bridge_contract_adaptor
        super().__init__(
            wallet_manager=wallet_manager, provider_id=provider_id, logger=logger
        )

    def can_handle_request(self, params: t.Dict) -> bool:
        """Returns 'true' if the bridge can handle a request for 'params'."""

        if not super().can_handle_request(params):
            return False

        if not self.bridge_contract_adaptor.can_handle_request(params):
            return False

        return True

    def description(self) -> str:
        """Get a human-readable description of the bridge provider."""
        return f"Native bridge provider ({self.bridge_contract_adaptor.__class__.__name__})."

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
        bridge_eta = self.bridge_contract_adaptor.BRIDGE_PARAMS[
            (Chain(from_chain), Chain(to_chain))
        ]["bridge_eta"]

        message = None
        if to_amount == 0:
            self.logger.info(f"[NATIVE BRIDGE] {MESSAGE_QUOTE_ZERO}")
            bridge_eta = 0
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

        from_ledger_api = self._from_ledger_api(bridge_request)
        bridge_tx = self.bridge_contract_adaptor.build_bridge_tx(
            from_ledger_api=from_ledger_api, bridge_request=bridge_request
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
        from_bridge = self.bridge_contract_adaptor.BRIDGE_PARAMS[
            (Chain(from_chain), Chain(to_chain))
        ]["from_bridge"]
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
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        bridge_eta = self.bridge_contract_adaptor.BRIDGE_PARAMS[
            (Chain(from_chain), Chain(to_chain))
        ]["bridge_eta"]

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

                to_tx_hash = (
                    self.bridge_contract_adaptor.find_bridge_finalized_tx(
                        from_ledger_api=from_ledger_api,
                        to_ledger_api=to_ledger_api,
                        bridge_request=bridge_request,
                        from_block=from_block,
                        to_block=to_block,
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
