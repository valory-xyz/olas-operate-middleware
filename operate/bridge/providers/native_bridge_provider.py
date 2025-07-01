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

from aea.common import JSONLike
from aea.crypto.base import LedgerApi
from autonomy.chain.base import registry_contracts
from eth_typing import BlockIdentifier
from web3 import Web3

from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequest,
    BridgeRequestStatus,
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
from operate.data.contracts.optimism_mintable_erc20.contract import (
    OptimismMintableERC20,
)
from operate.ledger.profiles import ERC20_TOKENS, EXPLORER_URL
from operate.operate_types import Chain
from operate.wallet.master import MasterWalletManager


BLOCK_CHUNK_SIZE = 5000


class BridgeContractAdaptor(ABC):
    """Adaptor class for bridge contract packages."""

    def __init__(
        self,
        from_chain: str,
        from_bridge: str,
        to_chain: str,
        to_bridge: str,
        bridge_eta: int,
    ) -> None:
        """Initialize the bridge contract adaptor."""
        super().__init__()
        self.from_chain = from_chain
        self.from_bridge = from_bridge
        self.to_chain = to_chain
        self.to_bridge = to_bridge
        self.bridge_eta = bridge_eta

    def can_handle_request(self, to_ledger_api: LedgerApi, params: t.Dict) -> bool:
        """Returns 'true' if the contract adaptor can handle a request for 'params'."""
        from_chain = params["from"]["chain"]
        from_token = Web3.to_checksum_address(params["from"]["token"])
        to_chain = params["to"]["chain"]
        to_token = Web3.to_checksum_address(params["to"]["token"])

        if from_chain != self.from_chain:
            return False

        if to_chain != self.to_chain:
            return False

        if from_token == ZERO_ADDRESS and to_token == ZERO_ADDRESS:
            return True

        for token_map in ERC20_TOKENS:
            if (
                Chain(from_chain) in token_map
                and Chain(to_chain) in token_map
                and token_map[Chain(from_chain)].lower() == from_token.lower()
                and token_map[Chain(to_chain)].lower() == to_token.lower()
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

    @abstractmethod
    def get_explorer_link(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        raise NotImplementedError()


class OptimismContractAdaptor(BridgeContractAdaptor):
    """Adaptor class for Optimism contract packages."""

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

    _optimism_mintable_erc20_contract = t.cast(
        OptimismMintableERC20,
        OptimismMintableERC20.from_dir(
            directory=str(DATA_DIR / "contracts" / "optimism_mintable_erc20"),
        ),
    )

    def can_handle_request(self, to_ledger_api: LedgerApi, params: t.Dict) -> bool:
        """Returns 'true' if the contract adaptor can handle a request for 'params'."""

        from_token = Web3.to_checksum_address(params["from"]["token"])
        to_token = Web3.to_checksum_address(params["to"]["token"])

        if to_token != ZERO_ADDRESS:
            try:
                l1_token = self._optimism_mintable_erc20_contract.l1_token(
                    ledger_api=to_ledger_api,
                    contract_address=to_token,
                )["data"]

                if l1_token != from_token:
                    return False
            except Exception:  # pylint: disable=broad-except
                return False

        return super().can_handle_request(to_ledger_api, params)

    def build_bridge_tx(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> JSONLike:
        """Build bridge transaction."""
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = self.from_bridge
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
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        to_bridge = self.to_bridge
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

    def get_explorer_link(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        if not bridge_request.execution_data:
            return None

        tx_hash = bridge_request.execution_data.from_tx_hash
        if not tx_hash:
            return None

        chain = Chain(bridge_request.params["from"]["chain"])
        url = EXPLORER_URL[chain]["tx"]
        return url.format(tx_hash=tx_hash)


class OmnibridgeContractAdaptor(BridgeContractAdaptor):
    """Adaptor class for Omnibridge contract packages."""

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

    def can_handle_request(self, to_ledger_api: LedgerApi, params: t.Dict) -> bool:
        """Returns 'true' if the contract adaptor can handle a request for 'params'."""
        from_token = Web3.to_checksum_address(params["from"]["token"])
        if from_token == ZERO_ADDRESS:
            return False

        return super().can_handle_request(to_ledger_api, params)

    def build_bridge_tx(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> JSONLike:
        """Build bridge transaction."""
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_address = bridge_request.params["to"]["address"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = self.from_bridge

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
        from_token = bridge_request.params["from"]["token"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        to_bridge = self.to_bridge

        if from_token == ZERO_ADDRESS:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not support bridge native tokens."
            )

        message_id = self.get_message_id(
            from_ledger_api=from_ledger_api,
            bridge_request=bridge_request,
        )

        if not message_id:
            raise RuntimeError(
                f"Cannot find 'messageId' for bridge request {bridge_request.id}."
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

    def get_message_id(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> t.Optional[str]:
        """Get the bridge message id."""
        if not bridge_request.execution_data:
            return None

        if not bridge_request.execution_data.from_tx_hash:
            return None

        if (
            bridge_request.execution_data.provider_data
            and "message_id" in bridge_request.execution_data.provider_data
        ):
            return bridge_request.execution_data.provider_data.get("message_id", None)

        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        from_tx_hash = bridge_request.execution_data.from_tx_hash
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = self.from_bridge

        message_id = self._foreign_omnibridge.get_tokens_bridging_initiated_message_id(
            ledger_api=from_ledger_api,
            contract_address=from_bridge,
            tx_hash=from_tx_hash,
            token=from_token,
            sender=from_address,
            value=to_amount,
        )

        if not bridge_request.execution_data.provider_data:
            bridge_request.execution_data.provider_data = {}

        bridge_request.execution_data.provider_data["message_id"] = message_id
        return message_id

    def get_explorer_link(
        self, from_ledger_api: LedgerApi, bridge_request: BridgeRequest
    ) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        message_id = self.get_message_id(from_ledger_api, bridge_request)
        if not message_id:
            return None
        return (
            f"https://bridge.gnosischain.com/bridge-explorer/transaction/{message_id}"
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

        to_chain = params["to"]["chain"]
        chain = Chain(to_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        to_ledger_api = wallet.ledger_api(chain)

        if not self.bridge_contract_adaptor.can_handle_request(to_ledger_api, params):
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

        to_amount = bridge_request.params["to"]["amount"]
        bridge_eta = self.bridge_contract_adaptor.bridge_eta

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

    def _get_approve_tx(self, bridge_request: BridgeRequest) -> t.Optional[t.Dict]:
        """Get the approve transaction."""
        self.logger.info(
            f"[NATIVE BRIDGE] Get appprove transaction for bridge request {bridge_request.id}."
        )

        if bridge_request.params["to"]["amount"] == 0:
            return None

        quote_data = bridge_request.quote_data
        if not quote_data:
            return None

        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_amount = bridge_request.params["to"]["amount"]
        from_bridge = self.bridge_contract_adaptor.from_bridge
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
        return approve_tx

    def _get_bridge_tx(self, bridge_request: BridgeRequest) -> t.Optional[t.Dict]:
        """Get the bridge transaction."""
        self.logger.info(
            f"[NATIVE BRIDGE] Get bridge transaction for bridge request {bridge_request.id}."
        )

        if bridge_request.params["to"]["amount"] == 0:
            return None

        quote_data = bridge_request.quote_data
        if not quote_data:
            return None

        from_ledger_api = self._from_ledger_api(bridge_request)
        bridge_tx = self.bridge_contract_adaptor.build_bridge_tx(
            from_ledger_api=from_ledger_api, bridge_request=bridge_request
        )

        BridgeProvider._update_with_gas_pricing(bridge_tx, from_ledger_api)
        BridgeProvider._update_with_gas_estimate(bridge_tx, from_ledger_api)
        return bridge_tx

    def _get_txs(
        self, bridge_request: BridgeRequest, *args: t.Any, **kwargs: t.Any
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the quote."""
        txs = []
        approve_tx = self._get_approve_tx(bridge_request)
        if approve_tx:
            txs.append(("approve_tx", approve_tx))
        bridge_tx = self._get_bridge_tx(bridge_request)
        if bridge_tx:
            txs.append(("bridge_tx", bridge_tx))
        return txs

    def _update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status."""

        if bridge_request.status != BridgeRequestStatus.EXECUTION_PENDING:
            return

        self.logger.info(
            f"[NATIVE BRIDGE] Updating execution status for bridge request {bridge_request.id}."
        )

        execution_data = bridge_request.execution_data
        if not execution_data:
            raise RuntimeError(
                f"Cannot update bridge request {bridge_request.id}: execution data not present."
            )

        from_tx_hash = execution_data.from_tx_hash
        if not from_tx_hash:
            execution_data.message = (
                f"{MESSAGE_EXECUTION_FAILED} missing transaction hash."
            )
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
            return

        bridge_eta = self.bridge_contract_adaptor.bridge_eta

        try:
            from_ledger_api = self._from_ledger_api(bridge_request)
            from_w3 = from_ledger_api.api

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

                to_tx_hash = self.bridge_contract_adaptor.find_bridge_finalized_tx(
                    from_ledger_api=from_ledger_api,
                    to_ledger_api=to_ledger_api,
                    bridge_request=bridge_request,
                    from_block=from_block,
                    to_block=to_block,
                )

                if to_tx_hash:
                    self.logger.info(
                        f"[NATIVE BRIDGE] Execution done for {bridge_request.id}."
                    )
                    execution_data.message = None
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
            import traceback

            traceback.print_exc()
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
            if block["timestamp"] < timestamp:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return best

    def _get_explorer_link(self, bridge_request: BridgeRequest) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        from_ledger_api = self._from_ledger_api(bridge_request)
        return self.bridge_contract_adaptor.get_explorer_link(
            from_ledger_api=from_ledger_api, bridge_request=bridge_request
        )
