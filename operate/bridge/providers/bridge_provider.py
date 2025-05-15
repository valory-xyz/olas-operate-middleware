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
"""Bridge provider."""


import copy
import enum
import logging
import time
import typing as t
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from aea.crypto.base import LedgerApi
from aea.helpers.logging import setup_logger
from autonomy.chain.tx import TxSettler

from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.wallet.master import MasterWalletManager


PLACEHOLDER_NATIVE_TOKEN_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # nosec

DEFAULT_MAX_QUOTE_RETRIES = 3
BRIDGE_REQUEST_PREFIX = "b-"
MESSAGE_QUOTE_ZERO = "Zero-amount quote requested."
MESSAGE_EXECUTION_SKIPPED = "Execution skipped."
MESSAGE_EXECUTION_FAILED = "Execution failed:"
MESSAGE_EXECUTION_FAILED_ETA = f"{MESSAGE_EXECUTION_FAILED} ETA exceeded."
MESSAGE_EXECUTION_FAILED_QUOTE_FAILED = f"{MESSAGE_EXECUTION_FAILED} quote failed."
MESSAGE_EXECUTION_FAILED_REVERTED = (
    f"{MESSAGE_EXECUTION_FAILED} bridge transaction reverted."
)
MESSAGE_EXECUTION_FAILED_SETTLEMENT = (
    f"{MESSAGE_EXECUTION_FAILED} transaction settlement failed."
)

ERC20_APPROVE_SELECTOR = (
    "0x095ea7b3"  # 4 first bytes of Keccak('approve(address,uint256)')
)


@dataclass
class QuoteData(LocalResource):
    """QuoteData"""

    bridge_eta: t.Optional[int]
    elapsed_time: float
    message: t.Optional[str]
    timestamp: int
    provider_data: t.Optional[t.Dict]  # Provider-specific data


@dataclass
class ExecutionData(LocalResource):
    """ExecutionData"""

    elapsed_time: float
    message: t.Optional[str]
    timestamp: int
    from_tx_hash: t.Optional[str]
    to_tx_hash: t.Optional[str]


class BridgeRequestStatus(str, enum.Enum):
    """BridgeRequestStatus"""

    CREATED = "CREATED"
    QUOTE_DONE = "QUOTE_DONE"
    QUOTE_FAILED = "QUOTE_FAILED"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    EXECUTION_DONE = "EXECUTION_DONE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"

    def __str__(self) -> str:
        """__str__"""
        return self.value


@dataclass
class BridgeRequest(LocalResource):
    """BridgeRequest"""

    params: t.Dict
    bridge_provider_id: str
    id: str
    status: BridgeRequestStatus
    quote_data: t.Optional[QuoteData]
    execution_data: t.Optional[ExecutionData]


class BridgeProvider(ABC):
    """(Abstract) BridgeProvider.

    Expected usage:
        params = {...}

        1. request = bridge.create_request(params)
        2. bridge.quote(request)
        3. bridge.requirements(request)
        4. bridge.execute(request)
        5. bridge.status_json(request)

    Derived classes must implement the following methods:
        - description
        - quote
        - _update_execution_status
        - _get_transactions
        - _get_explorer_link
    """

    def __init__(
        self,
        wallet_manager: MasterWalletManager,
        logger: t.Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the bridge provider."""
        self.wallet_manager = wallet_manager
        self.logger = logger or setup_logger(name="operate.bridge.BridgeProvider")

    @classmethod
    def id(cls) -> str:
        """Get the id of the bridge provider."""
        return f"{cls.__module__}.{cls.__qualname__}"

    def description(self) -> str:
        """Get a human-readable description of the bridge provider."""
        return self.__class__.__name__

    def _validate(self, bridge_request: BridgeRequest) -> None:
        """Validate the bridge request."""
        if bridge_request.bridge_provider_id != self.id():
            raise ValueError(
                f"Bridge request provider id {bridge_request.bridge_provider_id} does not match the bridge provider id {self.id()}"
            )

    def create_request(self, params: t.Dict) -> BridgeRequest:
        """Create a bridge request."""
        if "from" not in params or "to" not in params:
            raise ValueError(
                "Invalid input: All requests must contain exactly one 'from' and one 'to' sender."
            )

        from_ = params["from"]
        to = params["to"]

        if (
            not isinstance(from_, t.Dict)
            or "chain" not in from_
            or "address" not in from_
            or "token" not in from_
        ):
            raise ValueError(
                "Invalid input: 'from' must contain 'chain', 'address', and 'token'."
            )

        if (
            not isinstance(to, t.Dict)
            or "chain" not in to
            or "address" not in to
            or "token" not in to
            or "amount" not in to
        ):
            raise ValueError(
                "Invalid input: 'to' must contain 'chain', 'address', 'token', and 'amount'."
            )

        params = copy.deepcopy(params)
        params["to"]["amount"] = int(params["to"]["amount"])

        return BridgeRequest(
            params=params,
            bridge_provider_id=self.id(),
            id=f"{BRIDGE_REQUEST_PREFIX}{uuid.uuid4()}",
            quote_data=None,
            execution_data=None,
            status=BridgeRequestStatus.CREATED,
        )

    def _from_ledger_api(self, bridge_request: BridgeRequest) -> LedgerApi:
        """Get the from ledger api."""
        from_chain = bridge_request.params["from"]["chain"]
        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)
        return ledger_api

    def _to_ledger_api(self, bridge_request: BridgeRequest) -> LedgerApi:
        """Get the from ledger api."""
        from_chain = bridge_request.params["to"]["chain"]
        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)
        return ledger_api

    @abstractmethod
    def quote(self, bridge_request: BridgeRequest) -> None:
        """Update the request with the quote."""
        raise NotImplementedError()

    @abstractmethod
    def _get_transactions(
        self, bridge_request: BridgeRequest
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the bridge request."""
        raise NotImplementedError()

    def bridge_requirements(self, bridge_request: BridgeRequest) -> t.Dict:
        """Gets the bridge requirements to execute the quote, with updated gas estimation."""
        self._validate(bridge_request)

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        from_ledger_api = self._from_ledger_api(bridge_request)

        transactions = self._get_transactions(bridge_request)
        if not transactions:
            return {
                from_chain: {
                    from_address: {
                        ZERO_ADDRESS: 0,
                        from_token: 0,
                    }
                }
            }

        total_native = 0
        total_token = 0

        for tx_label, tx in transactions:
            self.logger.debug(
                f"[BRIDGE PROVIDER] Processing transaction {tx_label} for bridge request {bridge_request.id}."
            )
            self._update_with_gas_pricing(tx, from_ledger_api)
            gas_key = "gasPrice" if "gasPrice" in tx else "maxFeePerGas"
            gas_fees = tx.get(gas_key, 0) * tx["gas"]
            tx_value = int(tx.get("value", 0))
            total_native += tx_value + gas_fees

            self.logger.debug(
                f"[BRIDGE PROVIDER] Transaction {gas_key}={tx.get(gas_key, 0)} maxPriorityFeePerGas={tx.get('maxPriorityFeePerGas', -1)} gas={tx['gas']} {gas_fees=} {tx_value=}"
            )
            self.logger.debug(f"[BRIDGE PROVIDER] {from_ledger_api.api.eth.gas_price=}")
            self.logger.debug(
                f"[BRIDGE PROVIDER] {from_ledger_api.api.eth.get_block('latest').baseFeePerGas=}"
            )

            if tx.get("to", "").lower() == from_token.lower() and tx.get(
                "data", ""
            ).startswith(ERC20_APPROVE_SELECTOR):
                try:
                    amount = int(tx["data"][-64:], 16)
                    total_token += amount
                except Exception as e:
                    raise RuntimeError("Malformed ERC20 approve transaction.") from e

        result = {
            from_chain: {
                from_address: {
                    ZERO_ADDRESS: total_native,
                }
            }
        }

        if from_token != ZERO_ADDRESS:
            result[from_chain][from_address][from_token] = total_token

        return result

    def execute(self, bridge_request: BridgeRequest) -> None:
        """Execute the quote."""
        self._validate(bridge_request)

        if bridge_request.status not in (
            BridgeRequestStatus.QUOTE_DONE,
            BridgeRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"Cannot execute bridge request {bridge_request.id} with status {bridge_request.status}."
            )
        if not bridge_request.quote_data:
            raise RuntimeError(
                f"Cannot execute bridge request {bridge_request.id}: quote data not present."
            )
        if bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot execute bridge request {bridge_request.id}: execution data already present."
            )

        timestamp = time.time()
        txs = self._get_transactions(bridge_request)

        if not txs:
            self.logger.info(
                f"[LI.FI BRIDGE] {MESSAGE_EXECUTION_SKIPPED} ({bridge_request.status=})"
            )
            execution_data = ExecutionData(
                elapsed_time=0,
                message=f"{MESSAGE_EXECUTION_SKIPPED} ({bridge_request.status=})",
                timestamp=int(timestamp),
                from_tx_hash=None,
                to_tx_hash=None,
            )
            bridge_request.execution_data = execution_data

            if bridge_request.status == BridgeRequestStatus.QUOTE_DONE:
                bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
            else:
                bridge_request.execution_data.message = (
                    MESSAGE_EXECUTION_FAILED_QUOTE_FAILED
                )
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
            return

        try:
            self.logger.info(f"[BRIDGE] Executing bridge request {bridge_request.id}.")
            chain = Chain(bridge_request.params["from"]["chain"])
            wallet = self.wallet_manager.load(chain.ledger_type)
            from_ledger_api = self._from_ledger_api(bridge_request)
            tx_settler = TxSettler(
                ledger_api=from_ledger_api,
                crypto=wallet.crypto,
                chain_type=Chain(bridge_request.params["from"]["chain"]),
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )
            tx_hashes = []

            for tx_label, tx in txs:
                self.logger.info(f"[BRIDGE] Executing transaction {tx_label}.")
                setattr(  # noqa: B010
                    tx_settler, "build", lambda *args, **kwargs: tx  # noqa: B023
                )
                tx_receipt = tx_settler.transact(
                    method=lambda: {},
                    contract="",
                    kwargs={},
                    dry_run=False,
                )
                self.logger.info(f"[BRIDGE] Transaction {tx_label} settled.")
                tx_hashes.append(tx_receipt.get("transactionHash", "").hex())

            execution_data = ExecutionData(
                elapsed_time=time.time() - timestamp,
                message=None,
                timestamp=int(timestamp),
                from_tx_hash=tx_hashes[-1],
                to_tx_hash=None,
            )
            bridge_request.execution_data = execution_data
            if len(tx_hashes) == len(txs):
                bridge_request.status = BridgeRequestStatus.EXECUTION_PENDING
            else:
                bridge_request.execution_data.message = (
                    MESSAGE_EXECUTION_FAILED_SETTLEMENT
                )
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED

        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(f"[BRIDGE] Error executing bridge request: {e}")
            execution_data = ExecutionData(
                elapsed_time=time.time() - timestamp,
                message=f"{MESSAGE_EXECUTION_FAILED} {str(e)}",
                timestamp=int(timestamp),
                from_tx_hash=None,
                to_tx_hash=None,
            )
            bridge_request.execution_data = execution_data
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED

    @abstractmethod
    def _update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status."""
        raise NotImplementedError()

    @abstractmethod
    def _get_explorer_link(self, tx_hash: str) -> str:
        """Get the explorer link for a transaction."""
        raise NotImplementedError()

    def status_json(self, bridge_request: BridgeRequest) -> t.Dict:
        """JSON representation of the status."""
        if bridge_request.execution_data:
            self._update_execution_status(bridge_request)
            tx_hash = None
            explorer_link = None
            if bridge_request.execution_data.from_tx_hash:
                tx_hash = bridge_request.execution_data.from_tx_hash
                explorer_link = self._get_explorer_link(tx_hash)

            return {
                "explorer_link": explorer_link,
                "message": bridge_request.execution_data.message,
                "status": bridge_request.status.value,
                "tx_hash": tx_hash,
            }
        if bridge_request.quote_data:
            return {
                "message": bridge_request.quote_data.message,
                "status": bridge_request.status.value,
            }

        return {"message": None, "status": bridge_request.status.value}

    # TODO backport to open aea/autonomy
    # TODO This gas pricing management should possibly be done at a lower level in the library
    @staticmethod
    def _update_with_gas_pricing(tx: t.Dict, ledger_api: LedgerApi) -> None:
        tx.pop("maxFeePerGas", None)
        tx.pop("gasPrice", None)
        tx.pop("maxPriorityFeePerGas", None)

        gas_pricing = ledger_api.try_get_gas_pricing()
        if gas_pricing is None:
            raise RuntimeError("Unable to retrieve gas pricing.")

        if "maxFeePerGas" in gas_pricing and "maxPriorityFeePerGas" in gas_pricing:
            tx["maxFeePerGas"] = gas_pricing["maxFeePerGas"]
            tx["maxPriorityFeePerGas"] = gas_pricing["maxPriorityFeePerGas"]
        elif "gasPrice" in gas_pricing:
            tx["gasPrice"] = gas_pricing["gasPrice"]
        else:
            raise RuntimeError("Retrieved invalid gas pricing.")

    # TODO backport to open aea/autonomy
    @staticmethod
    def _update_with_gas_estimate(tx: t.Dict, ledger_api: LedgerApi) -> None:
        original_gas = tx.get("gas", 1)
        tx["gas"] = 1
        ledger_api.update_with_gas_estimate(tx)

        if tx["gas"] > 1:
            return

        original_from = tx["from"]
        tx["from"] = PLACEHOLDER_NATIVE_TOKEN_ADDRESS
        ledger_api.update_with_gas_estimate(tx)
        tx["from"] = original_from

        if tx["gas"] > 1:
            return

        tx["gas"] = original_gas
