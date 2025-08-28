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
"""Provider."""


import copy
import enum
import logging
import time
import typing as t
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import ceil

from aea.crypto.base import LedgerApi
from autonomy.chain.tx import TxSettler
from web3 import Web3
from web3.middleware import geth_poa_middleware

from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.wallet.master import MasterWalletManager


GAS_ESTIMATE_FALLBACK_ADDRESSES = [
    "0x000000000000000000000000000000000000dEaD",
    "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",  # nosec
]

DEFAULT_MAX_QUOTE_RETRIES = 3
PROVIDER_REQUEST_PREFIX = "r-"
MESSAGE_QUOTE_ZERO = "Zero-amount quote requested."
MESSAGE_EXECUTION_SKIPPED = "Execution skipped."
MESSAGE_EXECUTION_FAILED = "Execution failed:"
MESSAGE_EXECUTION_FAILED_ETA = f"{MESSAGE_EXECUTION_FAILED} ETA exceeded."
MESSAGE_EXECUTION_FAILED_QUOTE_FAILED = f"{MESSAGE_EXECUTION_FAILED} quote failed."
MESSAGE_EXECUTION_FAILED_REVERTED = f"{MESSAGE_EXECUTION_FAILED} transaction reverted."
MESSAGE_EXECUTION_FAILED_SETTLEMENT = (
    f"{MESSAGE_EXECUTION_FAILED} transaction settlement failed."
)
MESSAGE_REQUIREMENTS_QUOTE_FAILED = "Cannot compute requirements for failed quote."

ERC20_APPROVE_SELECTOR = "0x095ea7b3"  # First 4 bytes of Web3.keccak(text='approve(address,uint256)').hex()[:10]

GAS_ESTIMATE_BUFFER = 1.10


@dataclass
class QuoteData(LocalResource):
    """QuoteData"""

    eta: t.Optional[int]
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
    provider_data: t.Optional[t.Dict]  # Provider-specific data


class ProviderRequestStatus(str, enum.Enum):
    """ProviderRequestStatus"""

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
class ProviderRequest(LocalResource):
    """ProviderRequest"""

    params: t.Dict
    provider_id: str
    id: str
    status: ProviderRequestStatus
    quote_data: t.Optional[QuoteData]
    execution_data: t.Optional[ExecutionData]


class Provider(ABC):
    """(Abstract) Provider.

    Expected usage:
        params = {...}

        1. request = provider.create_request(params)
        2. provider.quote(request)
        3. provider.requirements(request)
        4. provider.execute(request)
        5. provider.status_json(request)

    Derived classes must implement the following methods:
        - description
        - quote
        - _update_execution_status
        - _get_txs
        - _get_explorer_link
    """

    def __init__(
        self,
        wallet_manager: MasterWalletManager,
        provider_id: str,
        logger: logging.Logger,
    ) -> None:
        """Initialize the provider."""
        self.wallet_manager = wallet_manager
        self.provider_id = provider_id
        self.logger = logger

    def description(self) -> str:
        """Get a human-readable description of the provider."""
        return self.__class__.__name__

    def _validate(self, provider_request: ProviderRequest) -> None:
        """Validate that the request was created by this provider."""
        if provider_request.provider_id != self.provider_id:
            raise ValueError(
                f"Request provider id {provider_request.provider_id} does not match the provider id {self.provider_id}"
            )

    def can_handle_request(self, params: t.Dict) -> bool:
        """Returns 'true' if the provider can handle a request for 'params'."""

        if "from" not in params or "to" not in params:
            self.logger.error(
                "[PROVIDER] Invalid input: All requests must contain exactly one 'from' and one 'to' sender."
            )
            return False

        from_ = params["from"]
        to = params["to"]

        if (
            not isinstance(from_, t.Dict)
            or "chain" not in from_
            or "address" not in from_
            or "token" not in from_
        ):
            self.logger.error(
                "[PROVIDER] Invalid input: 'from' must contain 'chain', 'address', and 'token'."
            )
            return False

        if (
            not isinstance(to, t.Dict)
            or "chain" not in to
            or "address" not in to
            or "token" not in to
            or "amount" not in to
        ):
            self.logger.error(
                "[PROVIDER] Invalid input: 'to' must contain 'chain', 'address', 'token', and 'amount'."
            )
            return False

        return True

    def create_request(self, params: t.Dict) -> ProviderRequest:
        """Create a request."""

        if not self.can_handle_request(params):
            raise ValueError("Invalid input: Cannot process request.")

        w3 = Web3()
        params = copy.deepcopy(params)
        params["from"]["address"] = w3.to_checksum_address(params["from"]["address"])
        params["from"]["token"] = w3.to_checksum_address(params["from"]["token"])
        params["to"]["address"] = w3.to_checksum_address(params["to"]["address"])
        params["to"]["token"] = w3.to_checksum_address(params["to"]["token"])
        params["to"]["amount"] = int(params["to"]["amount"])

        return ProviderRequest(
            params=params,
            provider_id=self.provider_id,
            id=f"{PROVIDER_REQUEST_PREFIX}{uuid.uuid4()}",
            quote_data=None,
            execution_data=None,
            status=ProviderRequestStatus.CREATED,
        )

    def _from_ledger_api(self, provider_request: ProviderRequest) -> LedgerApi:
        """Get the from ledger api."""
        from_chain = provider_request.params["from"]["chain"]
        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)

        # TODO: Backport to open aea/autonomy
        if chain == Chain.OPTIMISM:
            ledger_api.api.middleware_onion.inject(geth_poa_middleware, layer=0)

        return ledger_api

    def _to_ledger_api(self, provider_request: ProviderRequest) -> LedgerApi:
        """Get the from ledger api."""
        from_chain = provider_request.params["to"]["chain"]
        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)

        # TODO: Backport to open aea/autonomy
        if chain == Chain.OPTIMISM:
            ledger_api.api.middleware_onion.inject(geth_poa_middleware, layer=0)

        return ledger_api

    @abstractmethod
    def quote(self, provider_request: ProviderRequest) -> None:
        """Update the request with the quote."""
        raise NotImplementedError()

    @abstractmethod
    def _get_txs(
        self, provider_request: ProviderRequest, *args: t.Any, **kwargs: t.Any
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the quote."""
        raise NotImplementedError()

    def requirements(self, provider_request: ProviderRequest) -> t.Dict:
        """Gets the requirements to execute the quote, with updated gas estimation."""
        self.logger.info(f"[PROVIDER] Requirements for request {provider_request.id}.")

        self._validate(provider_request)

        from_chain = provider_request.params["from"]["chain"]
        from_address = provider_request.params["from"]["address"]
        from_token = provider_request.params["from"]["token"]
        from_ledger_api = self._from_ledger_api(provider_request)

        txs = self._get_txs(provider_request)

        if not txs:
            return {
                from_chain: {
                    from_address: {
                        ZERO_ADDRESS: 0,
                        from_token: 0,
                    }
                }
            }

        total_native = 0
        total_gas_fees = 0
        total_token = 0

        for tx_label, tx in txs:
            self.logger.debug(
                f"[PROVIDER] Processing transaction {tx_label} for request {provider_request.id}."
            )
            self._update_with_gas_pricing(tx, from_ledger_api)
            gas_key = "gasPrice" if "gasPrice" in tx else "maxFeePerGas"
            gas_fees = tx.get(gas_key, 0) * tx["gas"]
            tx_value = int(tx.get("value", 0))
            total_gas_fees += gas_fees
            total_native += tx_value + gas_fees

            self.logger.debug(
                f"[PROVIDER] Transaction {gas_key}={tx.get(gas_key, 0)} maxPriorityFeePerGas={tx.get('maxPriorityFeePerGas', -1)} gas={tx['gas']} {gas_fees=} {tx_value=}"
            )
            self.logger.debug(f"[PROVIDER] {from_ledger_api.api.eth.gas_price=}")
            self.logger.debug(
                f"[PROVIDER] {from_ledger_api.api.eth.get_block('latest').baseFeePerGas=}"
            )

            if tx.get("to", "").lower() == from_token.lower() and tx.get(
                "data", ""
            ).startswith(ERC20_APPROVE_SELECTOR):
                try:
                    amount = int(tx["data"][-64:], 16)
                    total_token += amount
                except Exception as e:
                    raise RuntimeError("Malformed ERC20 approve transaction.") from e

        self.logger.info(
            f"[PROVIDER] Total gas fees for request {provider_request.id}: {total_gas_fees} native units."
        )

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

    def execute(self, provider_request: ProviderRequest) -> None:
        """Execute the request."""
        self.logger.info(f"[PROVIDER] Executing request {provider_request.id}.")

        self._validate(provider_request)

        if provider_request.status in (ProviderRequestStatus.QUOTE_FAILED):
            self.logger.info(f"[PROVIDER] {MESSAGE_EXECUTION_FAILED_QUOTE_FAILED}.")
            execution_data = ExecutionData(
                elapsed_time=0,
                message=f"{MESSAGE_EXECUTION_FAILED_QUOTE_FAILED}",
                timestamp=int(time.time()),
                from_tx_hash=None,
                to_tx_hash=None,
                provider_data=None,
            )
            provider_request.execution_data = execution_data
            provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
            return

        if provider_request.status not in (ProviderRequestStatus.QUOTE_DONE,):
            raise RuntimeError(
                f"Cannot execute request {provider_request.id} with status {provider_request.status}."
            )
        if not provider_request.quote_data:
            raise RuntimeError(
                f"Cannot execute request {provider_request.id}: quote data not present."
            )
        if provider_request.execution_data:
            raise RuntimeError(
                f"Cannot execute request {provider_request.id}: execution data already present."
            )

        txs = self._get_txs(provider_request)

        if not txs:
            self.logger.info(
                f"[PROVIDER] {MESSAGE_EXECUTION_SKIPPED} ({provider_request.status=})"
            )
            execution_data = ExecutionData(
                elapsed_time=0,
                message=f"{MESSAGE_EXECUTION_SKIPPED} ({provider_request.status=})",
                timestamp=int(time.time()),
                from_tx_hash=None,
                to_tx_hash=None,
                provider_data=None,
            )
            provider_request.execution_data = execution_data
            provider_request.status = ProviderRequestStatus.EXECUTION_DONE
            return

        try:
            self.logger.info(f"[PROVIDER] Executing request {provider_request.id}.")
            timestamp = time.time()
            chain = Chain(provider_request.params["from"]["chain"])
            from_address = provider_request.params["from"]["address"]
            wallet = self.wallet_manager.load(chain.ledger_type)
            from_ledger_api = self._from_ledger_api(provider_request)
            tx_settler = TxSettler(
                ledger_api=from_ledger_api,
                crypto=wallet.crypto,
                chain_type=Chain(provider_request.params["from"]["chain"]),
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )
            tx_hashes = []

            for tx_label, tx in txs:
                self.logger.info(f"[PROVIDER] Executing transaction {tx_label}.")
                nonce = from_ledger_api.api.eth.get_transaction_count(from_address)
                tx["nonce"] = nonce  # TODO: backport to TxSettler
                setattr(  # noqa: B010
                    tx_settler, "build", lambda *args, **kwargs: tx  # noqa: B023
                )
                tx_receipt = tx_settler.transact(
                    method=lambda: {},
                    contract="",
                    kwargs={},
                    dry_run=False,
                )
                self.logger.info(f"[PROVIDER] Transaction {tx_label} settled.")
                tx_hashes.append(tx_receipt.get("transactionHash", "").hex())

            execution_data = ExecutionData(
                elapsed_time=time.time() - timestamp,
                message=None,
                timestamp=int(timestamp),
                from_tx_hash=tx_hashes[-1],
                to_tx_hash=None,
                provider_data=None,
            )
            provider_request.execution_data = execution_data
            if len(tx_hashes) == len(txs):
                provider_request.status = ProviderRequestStatus.EXECUTION_PENDING
            else:
                provider_request.execution_data.message = (
                    MESSAGE_EXECUTION_FAILED_SETTLEMENT
                )
                provider_request.status = ProviderRequestStatus.EXECUTION_FAILED

        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(f"[PROVIDER] Error executing request: {e}")
            execution_data = ExecutionData(
                elapsed_time=time.time() - timestamp,
                message=f"{MESSAGE_EXECUTION_FAILED} {str(e)}",
                timestamp=int(time.time()),
                from_tx_hash=None,
                to_tx_hash=None,
                provider_data=None,
            )
            provider_request.execution_data = execution_data
            provider_request.status = ProviderRequestStatus.EXECUTION_FAILED

    @abstractmethod
    def _update_execution_status(self, provider_request: ProviderRequest) -> None:
        """Update the execution status."""
        raise NotImplementedError()

    @abstractmethod
    def _get_explorer_link(self, provider_request: ProviderRequest) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        raise NotImplementedError()

    def status_json(self, provider_request: ProviderRequest) -> t.Dict:
        """JSON representation of the status."""
        self._validate(provider_request)

        if provider_request.execution_data and provider_request.quote_data:
            self._update_execution_status(provider_request)
            tx_hash = None
            if provider_request.execution_data.from_tx_hash:
                tx_hash = provider_request.execution_data.from_tx_hash

            return {
                "eta": provider_request.quote_data.eta,
                "explorer_link": self._get_explorer_link(provider_request),
                "message": provider_request.execution_data.message,
                "status": provider_request.status.value,
                "tx_hash": tx_hash,
            }
        if provider_request.quote_data:
            return {
                "eta": provider_request.quote_data.eta,
                "message": provider_request.quote_data.message,
                "status": provider_request.status.value,
            }

        return {"message": None, "status": provider_request.status.value}

    @staticmethod
    def _tx_timestamp(tx_hash: str, ledger_api: LedgerApi) -> int:
        receipt = ledger_api.api.eth.get_transaction_receipt(tx_hash)
        block = ledger_api.api.eth.get_block(receipt.blockNumber)
        return block.timestamp

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
        print(
            f"[PROVIDER] Trying to update transaction gas {tx['from']=} {tx['gas']=}."
        )
        original_from = tx["from"]
        original_gas = tx.get("gas", 1)

        for address in [original_from] + GAS_ESTIMATE_FALLBACK_ADDRESSES:
            tx["from"] = address
            tx["gas"] = 1
            ledger_api.update_with_gas_estimate(tx)
            if tx["gas"] > 1:
                print(
                    f"[PROVIDER] Gas estimated successfully {tx['from']=} {tx['gas']=}."
                )
                break

        tx["from"] = original_from
        if tx["gas"] == 1:
            tx["gas"] = original_gas
            print(f"[PROVIDER] Unable to estimate gas. Restored {tx['gas']=}.")
        tx["gas"] = ceil(tx["gas"] * GAS_ESTIMATE_BUFFER)
