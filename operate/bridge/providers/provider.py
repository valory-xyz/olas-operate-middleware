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

from aea.crypto.base import LedgerApi
from autonomy.chain.tx import TxSettler
from web3 import Web3
from web3.exceptions import TimeExhausted, TransactionNotFound

from operate.constants import (
    BRIDGE_GAS_ESTIMATE_MULTIPLIER,
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.ledger import (
    DEFAULT_GAS_ESTIMATE_MULTIPLIER,
    get_default_ledger_api,
    update_tx_with_gas_pricing,
)
from operate.operate_types import Chain, ChainAmounts
from operate.resource import LocalResource
from operate.serialization import BigInt
from operate.wallet.master import MasterWalletManager


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

# ERC-20 function selectors (first 4 bytes of the Keccak-256 hash of the function signature)
ERC20_APPROVE_SELECTOR = "0x095ea7b3"
ERC20_TRANSFER_SELECTOR = "0xa9059cbb"


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
        return get_default_ledger_api(Chain(from_chain))

    def _to_ledger_api(self, provider_request: ProviderRequest) -> LedgerApi:
        """Get the from ledger api."""
        to_chain = provider_request.params["to"]["chain"]
        return get_default_ledger_api(Chain(to_chain))

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

    def requirements(self, provider_request: ProviderRequest) -> ChainAmounts:
        """Gets the requirements to execute the quote, with updated gas estimation."""
        self.logger.info(f"[PROVIDER] Requirements for request {provider_request.id}.")

        self._validate(provider_request)

        from_chain = provider_request.params["from"]["chain"]
        from_address = provider_request.params["from"]["address"]
        from_token = provider_request.params["from"]["token"]
        from_ledger_api = self._from_ledger_api(provider_request)

        txs = self._get_txs(provider_request)

        if not txs:
            return ChainAmounts(
                {
                    from_chain: {
                        from_address: {
                            ZERO_ADDRESS: BigInt(0),
                            from_token: BigInt(0),
                        }
                    }
                }
            )

        total_native = BigInt(0)
        total_gas_fees = BigInt(0)
        total_token = BigInt(0)

        for tx_label, tx in txs:
            self.logger.debug(
                f"[PROVIDER] Processing transaction {tx_label} for request {provider_request.id}."
            )
            update_tx_with_gas_pricing(tx, from_ledger_api)
            gas_key = "gasPrice" if "gasPrice" in tx else "maxFeePerGas"
            gas_fees = BigInt(tx.get(gas_key, 0) * tx["gas"])
            tx_value = BigInt(int(tx.get("value", 0)))
            total_gas_fees += gas_fees
            total_native += tx_value + gas_fees

            self.logger.debug(
                f"[PROVIDER] Transaction {gas_key}={tx.get(gas_key, 0)} maxPriorityFeePerGas={tx.get('maxPriorityFeePerGas', -1)} gas={tx['gas']} {gas_fees=} {tx_value=}"
            )
            self.logger.debug(f"[PROVIDER] {from_ledger_api.api.eth.gas_price=}")
            self.logger.debug(
                f"[PROVIDER] {from_ledger_api.api.eth.get_block('latest').baseFeePerGas=}"
            )

            # TODO Move the requirements logic to be implemented by each provider.
            #
            # The following code parses the required ERC20 token amount. The typical case is that the bridge
            # transactions fall into one of these cases:
            #     a. ERC20.approve + Bridge.deposit (bridge-specific tx), or
            #     b. ERC20.transfer
            #
            # Thus, the logic below assumes that there is only either an ERC20.approve OR ERC20.transfer (but not both).
            # However, since the set of transactions is bridge-dependent, this might not always be the case, and
            # is suggested that the requirements() logic be implemented per-provider.
            if tx.get("to", "").lower() == from_token.lower():
                data = tx.get("data", "").lower()
                try:
                    if data.startswith(ERC20_APPROVE_SELECTOR):
                        amount_hex = data[-64:]
                        amount = BigInt(amount_hex, 16)
                        total_token += amount
                    elif data.startswith(ERC20_TRANSFER_SELECTOR):
                        amount_hex = data[10 + 64 : 10 + 64 + 64]
                        amount = BigInt(amount_hex, 16)
                        total_token += amount
                except Exception as e:
                    raise RuntimeError("Malformed ERC20 transaction.") from e

        self.logger.info(
            f"[PROVIDER] Total gas fees for request {provider_request.id}: {total_gas_fees} native units."
        )

        result = ChainAmounts(
            {
                from_chain: {
                    from_address: {
                        ZERO_ADDRESS: total_native,
                    }
                }
            }
        )

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

            for tx_label, tx in txs:
                self.logger.info(f"[PROVIDER] Executing transaction {tx_label}.")
                tx_settler = TxSettler(
                    ledger_api=from_ledger_api,
                    crypto=wallet.crypto,
                    chain_type=Chain(provider_request.params["from"]["chain"]),
                    timeout=ON_CHAIN_INTERACT_TIMEOUT,
                    retries=ON_CHAIN_INTERACT_RETRIES,
                    sleep=ON_CHAIN_INTERACT_SLEEP,
                    tx_builder=lambda: {
                        **tx,  # noqa: B023
                        "nonce": from_ledger_api.api.eth.get_transaction_count(
                            from_address
                        ),
                    },
                    gas_multiplier=BRIDGE_GAS_ESTIMATE_MULTIPLIER,
                ).transact()

                try:
                    tx_settler.settle()
                    self.logger.info(f"[PROVIDER] Transaction {tx_label} settled.")
                except TimeExhausted as e:
                    self.logger.warning(
                        f"[PROVIDER] Transaction {tx_label} settlement timed out: {e}."
                    )

            execution_data = ExecutionData(
                elapsed_time=time.time() - timestamp,
                message=None,
                timestamp=int(timestamp),
                from_tx_hash=tx_settler.tx_hash,
                to_tx_hash=None,
                provider_data=None,
            )
            provider_request.execution_data = execution_data
            provider_request.status = ProviderRequestStatus.EXECUTION_PENDING

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

    def _bridge_tx_likely_failed(self, provider_request: ProviderRequest) -> bool:
        """Check if the bridge transaction likely failed and is not going to settle."""

        execution_data = provider_request.execution_data
        if not execution_data or not execution_data.from_tx_hash:
            return True

        from_tx_hash = execution_data.from_tx_hash
        now = time.time()
        age_seconds = now - execution_data.timestamp

        eta = provider_request.quote_data.eta if provider_request.quote_data else None

        MIN_SOFT_TIMEOUT = 600
        HARD_TIMEOUT = 1200
        ETA_MULTIPLIER = 10
        ETA_MIN_THRESHOLD = 60

        eta_timeout = (
            (eta * ETA_MULTIPLIER) if (eta and eta >= ETA_MIN_THRESHOLD) else 0
        )
        soft_timeout = max(MIN_SOFT_TIMEOUT, eta_timeout)

        if age_seconds > HARD_TIMEOUT:
            self.logger.warning(
                f"[PROVIDER] Transaction {from_tx_hash} age {age_seconds//60} > HARD_TIMEOUT."
            )
            return True

        if age_seconds <= soft_timeout:
            return False

        from_ledger_api = self._from_ledger_api(provider_request)
        w3 = from_ledger_api.api

        try:
            receipt = w3.eth.get_transaction_receipt(from_tx_hash)

            if receipt is None:
                raise TransactionNotFound("Receipt not found")

            if receipt["status"] == 1:
                # Unusual corner case - succeeded but bridge doesn't know yet?
                self.logger.info(
                    f"[PROVIDER] Transaction {from_tx_hash} was mined and succeeded — waiting for provider sync"
                )
                return False
            else:
                self.logger.warning(
                    f"[PROVIDER] Transaction {from_tx_hash} mined but reverted."
                )
                return True
        except TransactionNotFound:
            self.logger.warning(
                f"[PROVIDER] Transaction {from_tx_hash} not seen after {age_seconds//60} min - likely dropped."
            )
            return True
        except Exception as e:  # pylint: disable=broad-except
            self.logger.warning(
                f"[PROVIDER] Error retrieving tx {from_tx_hash}: {e} - likely dropped."
            )
            return True
