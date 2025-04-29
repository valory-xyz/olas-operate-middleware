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
"""Bridge manager."""


import enum
import json
import logging
import time
import typing as t
import uuid
from abc import abstractmethod
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import requests
from aea.crypto.base import LedgerApi
from aea.helpers.logging import setup_logger
from autonomy.chain.base import registry_contracts
from autonomy.chain.tx import TxSettler
from deepdiff import DeepDiff

from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.services.manage import get_assets_balances
from operate.wallet.master import MasterWalletManager


DEFAULT_MAX_QUOTE_RETRIES = 3
DEFAULT_QUOTE_VALIDITY_PERIOD = 3 * 60
EXECUTED_BUNDLES_PATH = "executed"
BRIDGE_REQUEST_BUNDLE_PREFIX = "br-"
BRIDGE_REQUEST_PREFIX = "b-"
MESSAGE_QUOTE_ZERO = "Zero-amount quote requested."
MESSAGE_EXECUTION_SKIPPED = "Execution skipped."


@dataclass
class QuoteData(LocalResource):
    """QuoteData"""

    attempts: int
    elapsed_time: float
    message: t.Optional[str]
    response: t.Optional[t.Dict]
    response_status: int
    timestamp: int


@dataclass
class ExecutionData(LocalResource):
    """ExecutionData"""

    bridge_status: t.Optional[enum.Enum]
    elapsed_time: float
    explorer_link: t.Optional[str]
    message: t.Optional[str]
    timestamp: int
    tx_hash: t.Optional[str]
    tx_status: int


class BridgeRequestStatus(str, enum.Enum):
    """BridgeRequestStatus"""

    CREATED = "CREATED"
    QUOTE_DONE = "QUOTE_DONE"
    QUOTE_FAILED = "QUOTE_FAILED"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    EXECUTION_DONE = "EXECUTION_DONE"
    EXECUTION_FAILED = "EXECUTION_FAILED"

    def __str__(self) -> str:
        """__str__"""
        return self.value


@dataclass
class BridgeRequest(LocalResource):
    """BridgeRequest"""

    params: t.Dict
    id: str = f"{BRIDGE_REQUEST_PREFIX}{uuid.uuid4()}"
    status: BridgeRequestStatus = BridgeRequestStatus.CREATED
    quote_data: t.Optional[QuoteData] = None
    execution_data: t.Optional[ExecutionData] = None

    def get_status_json(self) -> t.Dict:
        """JSON representation of the status."""
        if self.execution_data:
            return {
                "explorer_link": self.execution_data.explorer_link,
                "message": self.execution_data.message,
                "status": self.status.value,
                "tx_hash": self.execution_data.tx_hash,
            }
        if self.quote_data:
            return {"message": self.quote_data.message, "status": self.status.value}

        return {"message": None, "status": self.status.value}


@dataclass
class BridgeRequestBundle(LocalResource):
    """BridgeRequestBundle"""

    bridge_provider: str
    requests_params: t.List[t.Dict]
    bridge_requests: t.List[BridgeRequest]
    timestamp: int
    id: str

    def get_from_chains(self) -> set[Chain]:
        """Get 'from' chains."""
        return {
            Chain(request.params["from"]["chain"]) for request in self.bridge_requests
        }

    def get_from_addresses(self, chain: Chain) -> set[str]:
        """Get 'from' addresses."""
        chain_str = chain.value
        return {
            request.params["from"]["address"]
            for request in self.bridge_requests
            if request.params["from"]["chain"] == chain_str
        }

    def get_from_tokens(self, chain: Chain) -> set[str]:
        """Get 'from' tokens."""
        chain_str = chain.value
        return {
            request.params["from"]["token"]
            for request in self.bridge_requests
            if request.params["from"]["chain"] == chain_str
        }


class BridgeProvider:
    """(Abstract) BridgeProvider"""

    def __init__(
        self,
        wallet_manager: MasterWalletManager,
        logger: t.Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the bridge provider."""
        self.wallet_manager = wallet_manager
        self.logger = logger or setup_logger(name="operate.bridge.BridgeProvider")

    def name(self) -> str:
        """Get the name of the bridge provider."""
        return self.__class__.__name__

    @abstractmethod
    def quote(self, bridge_request: BridgeRequest) -> None:
        """Update the request with the quote."""
        raise NotImplementedError()

    @abstractmethod
    def bridge_requirements(self, bridge_request: BridgeRequest) -> t.Dict:
        """Gets the bridge requirements to execute the quote, with updated gas estimation."""
        raise NotImplementedError()

    @abstractmethod
    def execute(self, bridge_request: BridgeRequest) -> None:
        """Execute the quote."""
        raise NotImplementedError()

    @abstractmethod
    def update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status."""
        raise NotImplementedError()

    def quote_bundle(self, bundle: BridgeRequestBundle) -> None:
        """Update the bundle with the quotes."""
        for bridge_request in bundle.bridge_requests:
            self.quote(bridge_request=bridge_request)

        bundle.timestamp = int(time.time())

    def bridge_total_requirements(self, bundle: BridgeRequestBundle) -> t.Dict:
        """Sum bridge requirements."""

        bridge_total_requirements: t.Dict = {}

        for request in bundle.bridge_requests:
            if not request.quote_data:
                continue

            bridge_requirements = self.bridge_requirements(request)
            for from_chain, from_addresses in bridge_requirements.items():
                for from_address, from_tokens in from_addresses.items():
                    for from_token, from_amount in from_tokens.items():
                        bridge_total_requirements.setdefault(from_chain, {}).setdefault(
                            from_address, {}
                        ).setdefault(from_token, 0)
                        bridge_total_requirements[from_chain][from_address][
                            from_token
                        ] += from_amount

        return bridge_total_requirements

    def execute_bundle(self, bundle: BridgeRequestBundle) -> None:
        """Update the bundle with the quotes."""
        for bridge_request in bundle.bridge_requests:
            self.execute(bridge_request=bridge_request)

    def get_status_json(self, bundle: BridgeRequestBundle) -> t.Dict:
        """JSON representation of the status."""
        initial_status = [request.status for request in bundle.bridge_requests]

        for request in bundle.bridge_requests:
            self.update_execution_status(request)

        updated_status = [request.status for request in bundle.bridge_requests]

        if initial_status != updated_status and bundle.path is not None:
            bundle.store()

        bridge_request_status = [
            request.get_status_json() for request in bundle.bridge_requests
        ]

        return {
            "id": bundle.id,
            "bridge_request_status": bridge_request_status,
        }


class LiFiTransactionStatus(str, enum.Enum):
    """LI.FI transaction status."""

    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        """__str__"""
        return self.value


class LiFiBridgeProvider(BridgeProvider):
    """LI.FI Bridge provider."""

    @staticmethod
    def _build_approve_tx(
        quote_data: QuoteData, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        quote = quote_data.response
        if not quote:
            return None

        if "action" not in quote:
            return None

        from_token = quote["action"]["fromToken"]["address"]
        if from_token == ZERO_ADDRESS:
            return None

        transaction_request = quote.get("transactionRequest")
        if not transaction_request:
            return None

        from_amount = int(quote["action"]["fromAmount"])

        approve_tx = registry_contracts.erc20.get_approve_tx(
            ledger_api=ledger_api,
            contract_address=from_token,
            spender=transaction_request["to"],
            sender=transaction_request["from"],
            amount=from_amount,
        )
        return LiFiBridgeProvider._update_tx_gas_pricing(approve_tx, ledger_api)

    @staticmethod
    def _get_bridge_tx(
        quote_data: QuoteData, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        quote = quote_data.response
        if not quote:
            return None

        if "action" not in quote:
            return None

        transaction_request = quote.get("transactionRequest")
        if not transaction_request:
            return None

        bridge_tx = {
            "value": int(transaction_request["value"], 16),
            "to": transaction_request["to"],
            "data": bytes.fromhex(transaction_request["data"][2:]),
            "from": transaction_request["from"],
            "chainId": transaction_request["chainId"],
            "gasPrice": int(transaction_request["gasPrice"], 16),
            "gas": int(transaction_request["gasLimit"], 16),
            "nonce": ledger_api.api.eth.get_transaction_count(
                transaction_request["from"]
            ),
        }

        return LiFiBridgeProvider._update_tx_gas_pricing(bridge_tx, ledger_api)

    # TODO This gas pricing management should possibly be done at a lower level in the library
    @staticmethod
    def _update_tx_gas_pricing(tx: t.Dict, ledger_api: LedgerApi) -> t.Dict:
        output_tx = tx.copy()
        output_tx.pop("maxFeePerGas", None)
        output_tx.pop("gasPrice", None)
        output_tx.pop("maxPriorityFeePerGas", None)

        gas_pricing = ledger_api.try_get_gas_pricing()
        if gas_pricing is None:
            raise RuntimeError("[LI.FI BRIDGE] Unable to retrieve gas pricing.")

        if "maxFeePerGas" in gas_pricing and "maxPriorityFeePerGas" in gas_pricing:
            output_tx["maxFeePerGas"] = gas_pricing["maxFeePerGas"]
            output_tx["maxPriorityFeePerGas"] = gas_pricing["maxPriorityFeePerGas"]
        elif "gasPrice" in gas_pricing:
            output_tx["gasPrice"] = gas_pricing["gasPrice"]
        else:
            raise RuntimeError("[LI.FI BRIDGE] Retrieved invalid gas pricing.")

        return output_tx

    @staticmethod
    def _calculate_gas_fees(tx: t.Dict) -> int:
        gas_key = "gasPrice" if "gasPrice" in tx else "maxFeePerGas"
        return tx.get(gas_key, 0) * tx["gas"]

    def quote(self, bridge_request: BridgeRequest) -> None:
        """Update the request with the quote."""

        if bridge_request.status not in (
            BridgeRequestStatus.CREATED,
            BridgeRequestStatus.QUOTE_DONE,
            BridgeRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"[LI.FI BRIDGE] Cannot quote bridge request {bridge_request.id} with status {bridge_request.status}."
            )

        if bridge_request.execution_data:
            raise RuntimeError(
                f"[LI.FI BRIDGE] Cannot quote bridge request {bridge_request.id}: execution already present."
            )

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]

        if to_amount == 0:
            self.logger.info(f"[LI.FI BRIDGE] {MESSAGE_QUOTE_ZERO}")
            quote_data = QuoteData(
                attempts=0,
                elapsed_time=0,
                message=MESSAGE_QUOTE_ZERO,
                response=None,
                response_status=0,
                timestamp=int(time.time()),
            )
            bridge_request.quote_data = quote_data
            bridge_request.status = BridgeRequestStatus.QUOTE_DONE
            return

        url = "https://li.quest/v1/quote/toAmount"
        headers = {"accept": "application/json"}
        params = {
            "fromChain": Chain(from_chain).id,
            "fromAddress": from_address,
            "fromToken": from_token,
            "toChain": Chain(to_chain).id,
            "toAddress": to_address,
            "toToken": to_token,
            "toAmount": to_amount,
            "maxPriceImpact": 0.20,  # TODO determine correct value
        }
        for attempt in range(1, DEFAULT_MAX_QUOTE_RETRIES + 1):
            start = time.time()
            try:
                self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
                response = requests.get(
                    url=url, headers=headers, params=params, timeout=30
                )
                response.raise_for_status()
                response_json = response.json()
                quote_data = QuoteData(
                    attempts=attempt,
                    elapsed_time=time.time() - start,
                    message=None,
                    response=response_json,
                    response_status=response.status_code,
                    timestamp=int(time.time()),
                )
                bridge_request.quote_data = quote_data
                bridge_request.status = BridgeRequestStatus.QUOTE_DONE
                return
            except requests.Timeout as e:
                self.logger.warning(
                    f"[LI.FI BRIDGE] Timeout request on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                quote_data = QuoteData(
                    attempts=attempt,
                    elapsed_time=time.time() - start,
                    message=str(e),
                    response=None,
                    response_status=HTTPStatus.GATEWAY_TIMEOUT,
                    timestamp=int(time.time()),
                )
            except requests.RequestException as e:
                self.logger.warning(
                    f"[LI.FI BRIDGE] Request failed on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                response_json = response.json()
                quote_data = QuoteData(
                    attempts=attempt,
                    elapsed_time=time.time() - start,
                    message=response_json.get("message") or str(e),
                    response=response_json,
                    response_status=getattr(
                        response, "status_code", HTTPStatus.BAD_GATEWAY
                    ),
                    timestamp=int(time.time()),
                )
            if attempt >= DEFAULT_MAX_QUOTE_RETRIES:
                self.logger.error(
                    f"[LI.FI BRIDGE] Request failed after {DEFAULT_MAX_QUOTE_RETRIES} attempts."
                )
                bridge_request.quote_data = quote_data
                bridge_request.status = BridgeRequestStatus.QUOTE_FAILED
                return

            time.sleep(2)

    def bridge_requirements(self, bridge_request: BridgeRequest) -> t.Dict:
        """Gets the fund requirements to execute the quote, with updated gas estimation."""

        quote_data = bridge_request.quote_data
        if not quote_data:
            raise RuntimeError(
                f"[LI.FI BRIDGE] Cannot compute requirements for bridge request {bridge_request.id}: quote not present."
            )

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]

        zero_requirements = {
            from_chain: {
                from_address: {
                    ZERO_ADDRESS: 0,
                    from_token: 0,
                }
            }
        }

        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)

        approve_tx = self._build_approve_tx(quote_data, ledger_api)
        bridge_tx = self._get_bridge_tx(quote_data, ledger_api)
        if not bridge_tx:
            return zero_requirements

        bridge_tx_value = bridge_tx["value"]
        bridge_tx_gas_fees = self._calculate_gas_fees(bridge_tx)

        if approve_tx:
            approve_tx_gas_fees = self._calculate_gas_fees(approve_tx)
            return {
                from_chain: {
                    from_address: {
                        ZERO_ADDRESS: bridge_tx_value
                        + bridge_tx_gas_fees
                        + approve_tx_gas_fees,
                        from_token: int(quote_data.response["action"]["fromAmount"]),  # type: ignore
                    }
                }
            }

        return {
            from_chain: {
                from_address: {from_token: bridge_tx_value + bridge_tx_gas_fees}
            }
        }

    def execute(self, bridge_request: BridgeRequest) -> None:
        """Execute the quote."""

        if bridge_request.status not in (
            BridgeRequestStatus.QUOTE_DONE,
            BridgeRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"[LI.FI BRIDGE] Cannot execute bridge request {bridge_request.id} with status {bridge_request.status}."
            )

        if not bridge_request.quote_data:
            raise RuntimeError(
                f"[LI.FI BRIDGE] Cannot execute bridge request {bridge_request.id}: quote data not present."
            )

        if bridge_request.execution_data:
            raise RuntimeError(
                f"[LI.FI BRIDGE] Cannot execute bridge request {bridge_request.id}: execution data already present."
            )

        timestamp = time.time()
        quote = bridge_request.quote_data.response

        if not quote or "action" not in quote:
            self.logger.info(
                f"[LI.FI BRIDGE] {MESSAGE_EXECUTION_SKIPPED} ({bridge_request.status=})"
            )
            execution_data = ExecutionData(
                bridge_status=None,
                elapsed_time=0,
                explorer_link=None,
                message=f"{MESSAGE_EXECUTION_SKIPPED} ({bridge_request.status=})",
                timestamp=int(timestamp),
                tx_hash=None,
                tx_status=0,
            )
            bridge_request.execution_data = execution_data

            if bridge_request.status == BridgeRequestStatus.QUOTE_DONE:
                bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
            else:
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
            return

        try:
            self.logger.info(f"[LI.FI BRIDGE] Executing quote {quote.get('id')}.")
            from_token = quote["action"]["fromToken"]["address"]

            transaction_request = quote["transactionRequest"]
            chain = Chain.from_id(transaction_request["chainId"])
            wallet = self.wallet_manager.load(chain.ledger_type)
            ledger_api = wallet.ledger_api(chain)

            tx_settler = TxSettler(
                ledger_api=ledger_api,
                crypto=wallet.crypto,
                chain_type=chain,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )

            # Bridges from an asset other than native require an approval transaction.
            approve_tx = self._build_approve_tx(bridge_request.quote_data, ledger_api)
            if approve_tx:
                self.logger.info(
                    f"[LI.FI BRIDGE] Preparing approve transaction for for quote {quote['id']} ({from_token=})."
                )
                setattr(  # noqa: B010
                    tx_settler, "build", lambda *args, **kwargs: approve_tx
                )
                tx_settler.transact(
                    method=lambda: {},
                    contract="",
                    kwargs={},
                    dry_run=False,
                )
                self.logger.info("[LI.FI BRIDGE] Approve transaction settled.")

            self.logger.info(
                f"[LI.FI BRIDGE] Preparing bridge transaction for quote {quote['id']}."
            )
            bridge_tx = self._get_bridge_tx(bridge_request.quote_data, ledger_api)
            setattr(  # noqa: B010
                tx_settler, "build", lambda *args, **kwargs: bridge_tx
            )
            tx_receipt = tx_settler.transact(
                method=lambda: {},
                contract="",
                kwargs={},
                dry_run=False,
            )
            self.logger.info("[LI.FI BRIDGE] Bridge transaction settled.")
            tx_hash = tx_receipt.get("transactionHash", "").hex()

            execution_data = ExecutionData(
                bridge_status=LiFiTransactionStatus.NOT_FOUND,
                elapsed_time=time.time() - timestamp,
                explorer_link=f"https://scan.li.fi/tx/{tx_hash}",
                message=None,
                timestamp=int(timestamp),
                tx_hash=tx_hash,
                tx_status=tx_receipt.get("status", 0),
            )
            bridge_request.execution_data = execution_data
            if tx_hash:
                bridge_request.status = BridgeRequestStatus.EXECUTION_PENDING
            else:
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED

        except Exception as e:  # pylint: disable=broad-except
            execution_data = ExecutionData(
                bridge_status=LiFiTransactionStatus.UNKNOWN,
                elapsed_time=time.time() - timestamp,
                explorer_link=None,
                message=f"Error executing quote: {str(e)}",
                timestamp=int(timestamp),
                tx_hash=None,
                tx_status=0,
            )
            bridge_request.execution_data = execution_data
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED

    def update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status. Returns `True` if the status changed."""

        if bridge_request.status not in (BridgeRequestStatus.EXECUTION_PENDING):
            return

        if not bridge_request.execution_data:
            raise RuntimeError(
                f"[LI.FI BRIDGE] Cannot update bridge request {bridge_request.id}: execution data not present."
            )

        execution = bridge_request.execution_data
        tx_hash = execution.tx_hash

        url = "https://li.quest/v1/status"
        headers = {"accept": "application/json"}
        params = {
            "txHash": tx_hash,
        }
        self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
        response = requests.get(url=url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        lifi_status = response_json.get("status", str(LiFiTransactionStatus.UNKNOWN))
        execution.message = response_json.get("substatusMessage")

        if execution.bridge_status != lifi_status:
            execution.bridge_status = lifi_status
            if lifi_status == LiFiTransactionStatus.DONE:
                bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
            elif lifi_status == LiFiTransactionStatus.FAILED:
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED


@dataclass
class BridgeManagerData(LocalResource):
    """BridgeManagerData"""

    path: Path
    version: int = 1
    last_requested_bundle: t.Optional[BridgeRequestBundle] = None

    _file = "bridge.json"

    # TODO Migrate to LocalResource?
    # It can be inconvenient that all local resources create an empty resource
    # if the file is corrupted. For example, if a service configuration is
    # corrupted, we might want to halt execution, because otherwise, the application
    # could continue as if the user is creatig a service from scratch.
    # For the bridge manager data, it's harmless, because its memory
    # is limited to the process of getting and executing a quote.
    @classmethod  # Overrides from LocalResource
    def load(cls, path: Path) -> "LocalResource":
        """Load local resource."""

        file = path / cls._file
        if not file.exists():
            BridgeManagerData(path=path).store()

        try:
            super().load(path=file)
        except (json.JSONDecodeError, KeyError):
            new_file = path / f"invalid_{int(time.time())}_{cls._file}"
            file.rename(new_file)
            BridgeManagerData(path=path).store()

        return super().load(path)


class BridgeManager:
    """BridgeManager"""

    # TODO singleton

    def __init__(
        self,
        path: Path,
        wallet_manager: MasterWalletManager,
        logger: t.Optional[logging.Logger] = None,
        bridge_provider: t.Optional[BridgeProvider] = None,
        quote_validity_period: int = DEFAULT_QUOTE_VALIDITY_PERIOD,
    ) -> None:
        """Initialize bridge manager."""
        self.path = path
        self.wallet_manager = wallet_manager
        self.logger = logger or setup_logger(name="operate.bridge.BridgeManager")
        self.bridge_provider = bridge_provider or LiFiBridgeProvider(
            wallet_manager, logger
        )
        self.quote_validity_period = quote_validity_period
        self.path.mkdir(exist_ok=True)
        (self.path / EXECUTED_BUNDLES_PATH).mkdir(exist_ok=True)
        self.data: BridgeManagerData = cast(
            BridgeManagerData, BridgeManagerData.load(path)
        )

    def _store_data(self) -> None:
        self.logger.info("[BRIDGE MANAGER] Storing data to file.")
        self.data.store()

    def _get_updated_bundle(
        self, requests_params: t.List[t.Dict], force_update: bool
    ) -> BridgeRequestBundle:
        """Ensures to return a valid (non expired) bundle for the given inputs."""

        now = int(time.time())
        bundle = self.data.last_requested_bundle
        create_new_bundle = False

        if not bundle:
            self.logger.info("[BRIDGE MANAGER] No last bundle.")
            create_new_bundle = True
        elif DeepDiff(requests_params, bundle.requests_params):
            self.logger.info("[BRIDGE MANAGER] Different requests params.")
            create_new_bundle = True
        elif force_update:
            self.logger.info("[BRIDGE MANAGER] Force bundle update.")
            self.bridge_provider.quote_bundle(bundle)
            self._store_data()
        elif now > bundle.timestamp + self.quote_validity_period:
            self.logger.info("[BRIDGE MANAGER] Bundle expired.")
            self.bridge_provider.quote_bundle(bundle)
            self._store_data()

        if not bundle or create_new_bundle:
            self.logger.info("[BRIDGE MANAGER] Creating new bridge request bundle.")

            bundle = BridgeRequestBundle(
                id=f"{BRIDGE_REQUEST_BUNDLE_PREFIX}{uuid.uuid4()}",
                bridge_provider=self.bridge_provider.name(),
                requests_params=requests_params,
                bridge_requests=[
                    BridgeRequest(params=params) for params in requests_params
                ],
                timestamp=now,
            )

            self.data.last_requested_bundle = bundle
            self.bridge_provider.quote_bundle(bundle)
            self._store_data()

        return bundle

    def _raise_if_invalid(self, bridge_requests: t.List) -> None:
        """Preprocess quote requests."""

        seen: set = set()

        for request in bridge_requests:
            if (
                not isinstance(request, dict)
                or "from" not in request
                or "to" not in request
            ):
                raise ValueError(
                    "Invalid input: All quote requests must contain exactly one 'from' and one 'to' sender."
                )

            from_ = request["from"]
            to = request["to"]

            if (
                not isinstance(from_, dict)
                or "chain" not in from_
                or "address" not in from_
                or "token" not in from_
            ):
                raise ValueError(
                    "Invalid input: 'from' must contain 'chain', 'address', and 'token'."
                )

            if (
                not isinstance(to, dict)
                or "chain" not in to
                or "address" not in to
                or "token" not in to
                or "amount" not in to
            ):
                raise ValueError(
                    "Invalid input: 'to' must contain 'chain', 'address', 'token', and 'amount'."
                )

            from_chain = request["from"]["chain"]
            from_address = request["from"]["address"]

            wallet = self.wallet_manager.load(Chain(from_chain).ledger_type)
            wallet_address = wallet.address
            safe_address = wallet.safes.get(Chain(from_chain))

            if from_address is None or not (
                from_address == wallet_address or from_address == safe_address
            ):
                raise ValueError(
                    f"Invalid input: 'from' address {from_address} does not match Master EOA nor Master Safe on chain {Chain(from_chain).name}."
                )

            key = (
                request["from"]["chain"],
                request["from"]["address"],
                request["from"]["token"],
                request["to"]["chain"],
                request["to"]["address"],
                request["to"]["token"],
            )

            if key in seen:
                raise ValueError(
                    "Request contains duplicate entries with same 'from' and 'to'."
                )

    def bridge_refill_requirements(
        self, requests_params: t.List[t.Dict], force_update: bool = False
    ) -> t.Dict:
        """Get bridge refill requirements."""

        self._raise_if_invalid(requests_params)
        self.logger.info(
            f"[BRIDGE MANAGER] Quote requests count: {len(requests_params)}."
        )

        bundle = self._get_updated_bundle(requests_params, force_update)

        balances = {}
        for chain in bundle.get_from_chains():
            ledger_api = self.wallet_manager.load(chain.ledger_type).ledger_api(chain)
            balances[chain.value] = get_assets_balances(
                ledger_api=ledger_api,
                asset_addresses={ZERO_ADDRESS} | bundle.get_from_tokens(chain),
                addresses=bundle.get_from_addresses(chain),
            )

        bridge_total_requirements = self.bridge_provider.bridge_total_requirements(
            bundle
        )

        bridge_refill_requirements: t.Dict = {}
        for from_chain, from_addresses in bridge_total_requirements.items():
            for from_address, from_tokens in from_addresses.items():
                for from_token, from_amount in from_tokens.items():
                    balance = balances[from_chain][from_address][from_token]
                    bridge_refill_requirements.setdefault(from_chain, {}).setdefault(
                        from_address, {}
                    )[from_token] = max(from_amount - balance, 0)

        is_refill_required = any(
            amount > 0
            for from_addresses in bridge_refill_requirements.values()
            for from_tokens in from_addresses.values()
            for amount in from_tokens.values()
        )

        status_json = self.bridge_provider.get_status_json(bundle)
        status_json.update(
            {
                "balances": balances,
                "bridge_refill_requirements": bridge_refill_requirements,
                "bridge_total_requirements": bridge_total_requirements,
                "expiration_timestamp": bundle.timestamp + self.quote_validity_period,
                "is_refill_required": is_refill_required,
            }
        )
        return status_json

    def execute_bundle(self, bundle_id: str) -> t.Dict:
        """Execute the bundle"""

        bundle = self.data.last_requested_bundle

        if not bundle:
            raise RuntimeError("[BRIDGE MANAGER] No bundle.")

        if bundle.id != bundle_id:
            raise RuntimeError(
                f"Quote bundle id {bundle_id} does not match last requested bundle id {bundle.id}."
            )

        self.data.last_requested_bundle = None
        bundle_path = self.path / EXECUTED_BUNDLES_PATH / f"{bundle.id}.json"
        bundle.path = bundle_path
        bundle.store()

        requirements = self.bridge_refill_requirements(bundle.requests_params)

        if requirements["is_refill_required"]:
            self.logger.warning(
                f"[BRIDGE MANAGER] Refill requirements not satisfied for bundle id {bundle_id}."
            )

        self.logger.info("[BRIDGE MANAGER] Executing quotes.")

        for request in bundle.bridge_requests:
            self.bridge_provider.execute(request)
            self._store_data()

        self._store_data()
        bundle.store()
        self.logger.info(f"[BRIDGE MANAGER] Bundle id {bundle_id} executed.")
        return self.get_status(bundle_id)

    def get_status(self, bundle_id: str) -> t.Dict:
        """Get execution status of bundle."""
        bundle = self.data.last_requested_bundle
        if bundle is not None and bundle.id == bundle_id:
            return self.bridge_provider.get_status_json(bundle)

        bundle_path = self.path / EXECUTED_BUNDLES_PATH / f"{bundle_id}.json"
        bundle = cast(BridgeRequestBundle, BridgeRequestBundle.load(bundle_path))
        bundle.path = bundle_path  # TODO backport to resource.py ?
        return self.bridge_provider.get_status_json(bundle)
