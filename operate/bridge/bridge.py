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
import shutil
import time
import typing as t
import uuid
from abc import abstractmethod
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import requests
from aea.helpers.logging import setup_logger
from autonomy.chain.base import registry_contracts
from autonomy.chain.tx import TxSettler
from deepdiff import DeepDiff
from web3 import Web3

from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.ledger import get_default_rpc
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.services.manage import get_assets_balances
from operate.wallet.master import MasterWalletManager


DEFAULT_MAX_RETRIES = 3
DEFAULT_QUOTE_VALIDITY_PERIOD = 3 * 60
BRIDGE_REQUEST_BUNDLE_PREFIX = "br-"
BRIDGE_REQUEST_PREFIX = "br-"



class BridgeRequestStatus(str, enum.Enum):
    """Bridge request status."""

    REQUEST_CREATED = "REQUEST_CREATED"
    QUOTE_DONE = "QUOTE_DONE"
    QUOTE_FAILED = "QUOTE_FAILED"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    EXECUTION_DONE = "EXECUTION_DONE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_NA = "EXECUTION_NA"


    def __str__(self) -> str:
        """__str__"""
        return self.value

@dataclass
class BridgeRequest(LocalResource):
    """BridgeRequest."""

    params: dict
    id: str = f"{BRIDGE_REQUEST_PREFIX}{uuid.uuid4()}"
    status: BridgeRequestStatus = BridgeRequestStatus.REQUEST_CREATED
    quote: dict | None = None
    execution: dict | None = None


@dataclass
class BridgeRequestBundle(LocalResource):
    pass


class BridgeProvider:
    """Abstract BridgeProvider."""

    def __init__(
        self,
        wallet_manager: MasterWalletManager,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the bridge provider."""
        self.wallet_manager = wallet_manager
        self.logger = logger or setup_logger(name="operate.bridge.BridgeProvider")

    def name(self) -> str:
        """Get the name of the bridge provider."""
        return self.__class__.__name__

    @abstractmethod
    def update_with_quote(self, bridge_request: BridgeRequest) -> None:
        """Update the request with the quote."""
        raise NotImplementedError()

    @abstractmethod
    def get_quote_requirements(self, bridge_request: BridgeRequest) -> dict:
        """Get bridge requirements for a single quote."""
        raise NotImplementedError()

    @abstractmethod
    def update_with_execution(self, bridge_request: dict) -> None:
        """Execute the quote."""
        raise NotImplementedError()

    @abstractmethod
    def update_execution_status(self, bridge_request: dict) -> bool:
        """Update the execution status."""
        raise NotImplementedError()

    @abstractmethod
    def is_execution_finished(self, bridge_request: dict) -> bool:
        """Check if the execution is finished."""
        raise NotImplementedError()


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

    def update_with_quote(self, bridge_request: BridgeRequest) -> None:
        """Update the request with the quote."""

        if bridge_request.execution:
            raise ValueError(
                f"[LI.FI BRIDGE] Cannot update bridge request {bridge_request.id} with quote: execution already present."
            )

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]

        if to_amount == 0:
            self.logger.info("[LI.FI BRIDGE] Zero-amount quote requested.")
            bridge_request.quote = new_quote(
                message="Zero-amount quote requested.",
            )
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
        for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
            start = time.time()
            try:
                self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
                response = requests.get(
                    url=url, headers=headers, params=params, timeout=30
                )
                response.raise_for_status()
                bridge_request.quote = {
                    "response": response.json(),
                    "attempts": attempt,
                    "elapsed_time": time.time() - start,
                    "error": False,
                    "message": None,
                    "response_status": response.status_code,
                    "timestamp": int(time.time()),
                }
                bridge_request.status = BridgeRequestStatus.QUOTE_DONE
                return
            except requests.Timeout as e:
                self.logger.warning(
                    f"[LI.FI BRIDGE] Timeout request on attempt {attempt}/{DEFAULT_MAX_RETRIES}: {e}."
                )
                output = {
                    "response": {},
                    "attempts": attempt,
                    "elapsed_time": time.time() - start,
                    "error": True,
                    "message": str(e),
                    "response_status": HTTPStatus.GATEWAY_TIMEOUT,
                    "timestamp": int(time.time()),
                }
                bridge_request.status = BridgeRequestStatus.QUOTE_FAILED
            except requests.RequestException as e:
                self.logger.warning(
                    f"[LI.FI BRIDGE] Request failed on attempt {attempt}/{DEFAULT_MAX_RETRIES}: {e}."
                )
                response_json = response.json()
                output = {
                    "response": response_json,
                    "attempts": attempt,
                    "elapsed_time": time.time() - start,
                    "error": True,
                    "message": response_json.get("message") or str(e),
                    "response_status": response.status_code,
                    "timestamp": int(time.time()),
                }
                bridge_request.status = BridgeRequestStatus.QUOTE_FAILED

            if attempt >= DEFAULT_MAX_RETRIES:
                self.logger.error(
                    f"[LI.FI BRIDGE] Request failed after {DEFAULT_MAX_RETRIES} attempts."
                )
                bridge_request.quote = output
                return

            time.sleep(2)

    # TODO gas fees !
    def get_quote_requirements(self, bridge_request: BridgeRequest) -> dict:
        """Get bridge requirements for a quote."""

        if not bridge_request.quote or not bridge_request.quote["response"] or not "action" in bridge_request.quote["response"]:
            from_chain = bridge_request.params["from"]["chain"]
            from_address = bridge_request.params["from"]["address"]
            from_token = bridge_request.params["from"]["token"]
            from_amount = 0
            transaction_value = 0
        else:
            quote = bridge_request.quote["response"]
            from_chain = Chain.from_id(quote["action"]["fromChainId"]).value
            from_address = quote["action"]["fromAddress"]
            from_token = quote["action"]["fromToken"]["address"]
            from_amount = int(quote["action"]["fromAmount"])
            transaction_value = int(quote["transactionRequest"]["value"], 16)

        if from_token == ZERO_ADDRESS:
            return {
                from_chain: {
                    from_address: {from_token: from_amount + transaction_value}
                }
            }
        else:
            return {
                from_chain: {
                    from_address: {
                        ZERO_ADDRESS: transaction_value,
                        from_token: from_amount,
                    }
                }
            }

    def update_with_execution(self, bridge_request: dict) -> None:
        """Execute the quote."""

        if "quote" not in bridge_request:
            raise ValueError(
                "[LI.FI BRIDGE] Cannot update bridge request with execution: quote not present."
            )

        if "execution" in bridge_request:
            self.logger.warning(
                f"[LI.FI BRIDGE] Execution already present on bridge request {bridge_request['id']}."
            )
            return

        quote = bridge_request["quote"]["response"]
        error = bridge_request["quote"].get("error", False)

        if error:
            self.logger.info("[LI.FI BRIDGE] Skipping quote execution (quote error).")
            bridge_request["execution"] = {
                "error": True,
                "explorer_link": None,
                "message": "Skipped execution (quote error).",
                "lifi_status": None,
                "timestamp": int(time.time()),
                "tx_hash": None,
                "tx_status": None,
            }
            bridge_request["status"] = BridgeRequestStatus.EXECUTION_DONE  # TODO alternative state?
            return
        if not quote:
            self.logger.info("[LI.FI BRIDGE] Skipping quote execution (empty quote).")
            bridge_request["execution"] = {
                "error": False,
                "explorer_link": None,
                "message": "Skipped execution (empty quote).",
                "lifi_status": None,
                "timestamp": int(time.time()),
                "tx_hash": None,
                "tx_status": None,
            }
            bridge_request["status"] = BridgeRequestStatus.EXECUTION_DONE  # TODO alternative state?
            return

        try:
            self.logger.info(f"[LI.FI BRIDGE] Executing quote {quote.get('id')}.")
            from_token = quote["action"]["fromToken"]["address"]
            from_amount = int(quote["action"]["fromAmount"])

            transaction_request = quote["transactionRequest"]
            from_chain = Chain.from_id(transaction_request["chainId"])
            wallet = self.wallet_manager.load(from_chain.ledger_type)

            tx_settler = TxSettler(
                ledger_api=wallet.ledger_api(from_chain),
                crypto=wallet.crypto,
                chain_type=from_chain,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )

            # Bridges from an asset other than native require an approval transaction.
            if from_token != ZERO_ADDRESS:
                self.logger.info(
                    f"[LI.FI BRIDGE] Preparing approve transaction for for quote {quote['id']} ({from_token=})."
                )

                # TODO Approval is done on several places. Consider exporting to a
                # higher-level layer (e.g., wallet?)
                def _build_approval_tx(  # pylint: disable=unused-argument
                    *args: t.Any, **kargs: t.Any
                ) -> dict:
                    return registry_contracts.erc20.get_approve_tx(
                        ledger_api=wallet.ledger_api(from_chain),
                        contract_address=from_token,
                        spender=transaction_request["to"],
                        sender=transaction_request["from"],
                        amount=from_amount,
                    )

                setattr(tx_settler, "build", _build_approval_tx)  # noqa: B010
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

            def _build_bridge_tx(  # pylint: disable=unused-argument
                *args: t.Any, **kargs: t.Any
            ) -> dict:
                w3 = Web3(Web3.HTTPProvider(get_default_rpc(chain=from_chain)))
                return {
                    "value": int(transaction_request["value"], 16),
                    "to": transaction_request["to"],
                    "data": bytes.fromhex(transaction_request["data"][2:]),
                    "from": transaction_request["from"],
                    "chainId": transaction_request["chainId"],
                    "gasPrice": int(transaction_request["gasPrice"], 16),
                    "gas": int(transaction_request["gasLimit"], 16),
                    "nonce": w3.eth.get_transaction_count(transaction_request["from"]),
                }

            setattr(tx_settler, "build", _build_bridge_tx)  # noqa: B010
            tx_receipt = tx_settler.transact(
                method=lambda: {},
                contract="",
                kwargs={},
                dry_run=False,
            )
            self.logger.info("[LI.FI BRIDGE] Bridge transaction settled.")
            tx_hash = tx_receipt.get("transactionHash", "").hex()

            bridge_request["execution"] = {
                "error": tx_receipt.get("status", 0) == 0,
                "explorer_link": f"https://scan.li.fi/tx/{tx_hash}",
                "message": None,
                "lifi_status": LiFiTransactionStatus.NOT_FOUND,
                "timestamp": int(time.time()),
                "tx_hash": tx_hash,
                "tx_status": tx_receipt.get("status", 0),
            }
            bridge_request["status"] = BridgeRequestStatus.EXECUTION_PENDING if tx_hash else BridgeRequestStatus.EXECUTION_FAILED

        except Exception as e:  # pylint: disable=broad-except
            bridge_request["execution"] = {
                "error": True,
                "explorer_link": None,
                "message": f"Error executing quote: {str(e)}",
                "lifi_status": LiFiTransactionStatus.FAILED,
                "status": BridgeRequestStatus.EXECUTION_FAILED,
                "timestamp": int(time.time()),
                "tx_hash": None,
                "tx_status": None,
            }
            bridge_request["status"] = BridgeRequestStatus.EXECUTION_FAILED

    def update_execution_status(self, bridge_request: dict) -> bool:
        """Update the execution status. Returns `True` if the status changed."""


        if "execution" not in bridge_request:
            return False

        execution = bridge_request["execution"]
        tx_hash = execution["tx_hash"]

        print("update_execution_status")
        print(f"{execution=}")

        if execution["status"] in (
            BridgeRequestStatus.EXECUTION_DONE,
            BridgeRequestStatus.EXECUTION_FAILED,
        ):
            return False

        url = "https://li.quest/v1/status"
        headers = {"accept": "application/json"}
        params = {
            "txHash": tx_hash,
        }
        self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
        response = requests.get(url=url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        lifi_status = response_json.get("lifi_status", str(LiFiTransactionStatus.UNKNOWN))
        execution["message"] = response_json.get("substatusMessage")

        if execution["lifi_status"] != lifi_status:
            execution["lifi_status"] = lifi_status
            if lifi_status in (
                LiFiTransactionStatus.DONE,
                LiFiTransactionStatus.FAILED,
            ):
                execution["status"] = BridgeRequestStatus.EXECUTION_DONE
            return True

        return False

    def is_execution_finished(self, bridge_request: dict) -> bool:
        """Check if the execution is finished."""

        if "execution" not in bridge_request:
            raise ValueError(
                "[LI.FI BRIDGE] Cannot update bridge request execution: execution not present."
            )

        self.update_execution_status(bridge_request)

        execution = bridge_request["execution"]
        tx_hash = execution["tx_hash"]

        if not tx_hash:
            return True

        return execution["status"] in (
            LiFiTransactionStatus.DONE,
            LiFiTransactionStatus.FAILED,
        )


class BridgeRequestBundleStatus(str, enum.Enum):
    """Bridge request bundle status."""

    CREATED = "CREATED"
    QUOTED = "QUOTED"
    SUBMITTED = "SUBMITTED"
    FINISHED = "FINISHED"  # All requests in the bundle are either done or failed.

    def __str__(self) -> str:
        """__str__"""
        return self.value


@dataclass
class BridgeManagerData(LocalResource):
    """BridgeManagerData"""

    path: Path
    version: int = 1
    last_requested_bundle: dict[str, BridgeRequest] | None = None
    executed_bundles: dict = field(default_factory=dict)

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


def new_bridge_request(request: dict) -> dict:
    """Create a new bridge request."""
    return {
        "id": f"{BRIDGE_REQUEST_PREFIX}{uuid.uuid4()}",
        "status": BridgeRequestStatus.REQUEST_CREATED,
        "request": request,
        "quote": None,
        "execution": None,
    }


def new_quote(  # pylint: disable=too-many-positional-arguments
    attempts: int = 0,
    elapsed_time: int = 0,
    message: str | None = None,
    response: dict | None = None,
    response_status: int = 0,
    timestamp: int = int(time.time()),
) -> dict:
    """Create a new quote."""
    return {
        "attempts": attempts,
        "elapsed_time": elapsed_time,
        "message": message,
        "response": response,
        "response_status": response_status,
        "timestamp": timestamp,
    }


def new_execution(  # pylint: disable=too-many-positional-arguments
    bridge_status: enum.Enum | None = None,
    elapsed_time: int = 0,
    explorer_link: str | None = None,
    message: str | None = None,
    timestamp: int = int(time.time()),
    tx_hash: str | None = None,
    tx_status: str | None = None,
) -> dict:
    """Create a new execution."""
    return {
        "bridge_status": bridge_status,
        "elapsed_time": elapsed_time,
        "explorer_link": explorer_link,
        "message": message,
        "timestamp": timestamp,
        "tx_hash": tx_hash,
        "tx_status": tx_status,
    }


class BridgeManager:
    """BridgeManager"""

    # TODO singleton

    _bundle_updated_on_session = False

    def __init__(
        self,
        path: Path,
        wallet_manager: MasterWalletManager,
        logger: logging.Logger | None = None,
        bridge_provider: BridgeProvider | None = None,
        quote_validity_period: int | None = None,
    ) -> None:
        """Initialize bridge manager."""
        self.path = path
        self.wallet_manager = wallet_manager
        self.logger = logger or setup_logger(name="operate.bridge.BridgeManager")
        self.bridge_provider = bridge_provider or LiFiBridgeProvider(
            wallet_manager, logger
        )
        self.quote_validity_period = (
            quote_validity_period or DEFAULT_QUOTE_VALIDITY_PERIOD
        )

        self.path.mkdir(exist_ok=True)
        self.data: BridgeManagerData = cast(
            BridgeManagerData, BridgeManagerData.load(path)
        )

    def _store_data(self) -> None:
        self.logger.info("[BRIDGE MANAGER] Storing data to file.")
        self.data.store()

    def _sum_quotes_requirements(self, bridge_requests: list) -> dict:
        """Get bridge requirements for a list of quotes."""

        bridge_total_requirements: dict = {}

        for request in bridge_requests:
            req = self.bridge_provider.get_quote_requirements(request)
            for from_chain, from_addresses in req.items():
                for from_address, from_tokens in from_addresses.items():
                    for from_token, from_amount in from_tokens.items():
                        bridge_total_requirements.setdefault(from_chain, {}).setdefault(
                            from_address, {}
                        ).setdefault(from_token, 0)
                        bridge_total_requirements[from_chain][from_address][
                            from_token
                        ] += from_amount

        return bridge_total_requirements

    def _get_updated_bundle(
        self, user_bridge_requests: list, force_update: bool
    ) -> dict:
        """Ensures to return a valid (non expired) bundle for the given inputs."""

        now = int(time.time())
        bundle = self.data.last_requested_bundle or {}
        bundle_id = bundle.get("id")
        create_new_bundle = False

        if not bundle:
            self.logger.info("[BRIDGE MANAGER] No last bundle.")
            create_new_bundle = True
            bundle_id = None
        elif bundle.get("status") not in (
            BridgeRequestBundleStatus.CREATED,
            BridgeRequestBundleStatus.QUOTED,
        ):
            raise RuntimeError("[BRIDGE MANAGER] Bundle inconsistent status.")
        elif DeepDiff(user_bridge_requests, bundle.get("bridge_requests", [])):
            self.logger.info("[BRIDGE MANAGER] Different quote requests.")
            create_new_bundle = True
            bundle_id = None
        elif force_update:
            self.logger.info("[BRIDGE MANAGER] Force quote update.")
            create_new_bundle = True
        elif now > bundle.get("timestamp", 0) + self.quote_validity_period:
            self.logger.info("[BRIDGE MANAGER] Bundle expired.")
            create_new_bundle = True

        if create_new_bundle:
            self.logger.info("[BRIDGE MANAGER] Requesting new bundle.")
            bundle = {}
            bundle["id"] = (
                bundle_id or f"{BRIDGE_REQUEST_BUNDLE_PREFIX}{uuid.uuid4()}"
            )
            bundle["bridge_provider"] = self.bridge_provider.name()
            bundle["status"] = str(BridgeRequestBundleStatus.CREATED)
            bundle["user_bridge_requests"] = user_bridge_requests
            bundle["bridge_requests"] = [
                BridgeRequest(params=request)
                for request in user_bridge_requests
            ]
            bundle["timestamp"] = now
            bundle["expiration_timestamp"] = now + self.quote_validity_period

            for request in bundle["bridge_requests"]:
                self.bridge_provider.update_with_quote(request)

            bundle["status"] = str(BridgeRequestBundleStatus.QUOTED)
            bundle[
                "bridge_total_requirements"
            ] = self._sum_quotes_requirements(bundle["bridge_requests"])

            self.data.last_requested_bundle = bundle
            self._store_data()

        return bundle

    def _update_bundle_status(self, bundle_id: str) -> None:
        bundle = self.data.executed_bundles.get(bundle_id)

        if not bundle:
            raise ValueError(
                f"[BRIDGE MANAGER] Bundle id {bundle_id} not found."
            )

        initial_status = bundle["status"]
        execution_status_changed = [
            self.bridge_provider.update_execution_status(request)
            for request in bundle["bridge_requests"]
        ]

        if any(execution_status_changed):
            self._store_data()

        is_execution_finished = all(
            self.bridge_provider.is_execution_finished(request)
            for request in bundle["bridge_requests"]
        )

        if is_execution_finished:
            bundle["status"] = str(BridgeRequestBundleStatus.FINISHED)
        else:
            bundle["status"] = str(BridgeRequestBundleStatus.SUBMITTED)

        if initial_status != bundle["status"]:
            self._store_data()

    def _raise_if_invalid(self, bridge_requests: list) -> None:
        """Preprocess quote requests."""

        seen: set = set()

        for request in bridge_requests:
            if (
                not isinstance(request, dict)
                or "from" not in request
                or "to" not in request
            ):
                raise ValueError(
                    "[BRIDGE MANAGER] Invalid input: All quote requests must contain exactly one 'from' and one 'to' sender."
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
                    "[BRIDGE MANAGER] Invalid input: 'from' must contain 'chain', 'address', and 'token'."
                )

            if (
                not isinstance(to, dict)
                or "chain" not in to
                or "address" not in to
                or "token" not in to
                or "amount" not in to
            ):
                raise ValueError(
                    "[BRIDGE MANAGER] Invalid input: 'to' must contain 'chain', 'address', 'token', and 'amount'."
                )

            from_chain = request["from"]["chain"]
            from_address = request["from"]["address"]

            wallet = self.wallet_manager.load(Chain(from_chain).ledger_type)
            wallet_address = wallet.address
            safe_address = wallet.safes.get(from_chain)

            if from_address is None or not (
                from_address == wallet_address or from_address == safe_address
            ):
                raise ValueError(
                    f"[BRIDGE MANAGER] Invalid input: 'from' address {from_address} does not match Master EOA nor Master Safe on chain {Chain(from_chain).name}."
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
                    "[BRIDGE MANAGER] Request contains duplicate entries with same 'from' and 'to'."
                )

    def bridge_refill_requirements(
        self, bridge_requests: list, force_update: bool = False
    ) -> dict:
        """Get bridge refill requirements."""

        self._raise_if_invalid(bridge_requests)
        self.logger.info(
            f"[BRIDGE MANAGER] Quote requests count: {len(bridge_requests)}."
        )

        bundle = self._get_updated_bundle(bridge_requests, force_update)

        chains = [request["from"]["chain"] for request in bridge_requests]
        balances = {}
        for chain in chains:
            ledger_api = self.wallet_manager.load(Chain(chain).ledger_type).ledger_api(
                Chain(chain)
            )
            balances[chain] = get_assets_balances(
                ledger_api=ledger_api,
                asset_addresses={ZERO_ADDRESS}
                | {
                    request["from"]["token"]
                    for request in bridge_requests
                    if request["from"]["chain"] == chain
                },
                addresses={
                    request["from"]["address"]
                    for request in bridge_requests
                    if request["from"]["chain"] == chain
                },
            )

        bridge_refill_requirements: dict = {}
        for from_chain, from_addresses in bundle[
            "bridge_total_requirements"
        ].items():
            for from_address, from_tokens in from_addresses.items():
                for from_token, from_amount in from_tokens.items():
                    balance = balances[from_chain][from_address][from_token]
                    bridge_refill_requirements.setdefault(from_chain, {}).setdefault(
                        from_address, {}
                    )
                    bridge_refill_requirements[from_chain][from_address][
                        from_token
                    ] = max(from_amount - balance, 0)

        is_refill_required = any(
            amount > 0
            for from_addresses in bridge_refill_requirements.values()
            for from_tokens in from_addresses.values()
            for amount in from_tokens.values()
        )

        bridge_request_status = [
            {
                "message": request.quote["message"],
                "status": request.status,
            }
            for request in bundle["bridge_requests"]
        ]
        error = any(
            request.status in (BridgeRequestStatus.QUOTE_FAILED, BridgeRequestStatus.EXECUTION_FAILED) for request in bundle["bridge_requests"]
        )
        self._bundle_updated_on_session = True

        return {
            "id": bundle["id"],
            "balances": balances,
            "bridge_total_requirements": bundle["bridge_total_requirements"],
            "bridge_refill_requirements": bridge_refill_requirements,
            "expiration_timestamp": bundle["expiration_timestamp"],
            "is_refill_required": is_refill_required,
            "bridge_request_status": bridge_request_status,
            "error": error,
        }

    def execute_bundle(self, bundle_id: str) -> dict:
        """Execute the bundle"""

        if not self._bundle_updated_on_session:
            raise RuntimeError(
                "[BRIDGE MANAGER] Cannot execute bundle if not updated on session."
            )

        bundle = self.data.last_requested_bundle

        if not bundle:
            raise RuntimeError("[BRIDGE MANAGER] No bundle.")

        if bundle.get("id") != bundle_id:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Quote bundle id {bundle_id} does not match last requested bundle id {bundle.get('id')}."
            )

        requirements = self.bridge_refill_requirements(bundle["bridge_requests"])

        if requirements["is_refill_required"]:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Refill requirements not satisfied for bundle id {bundle_id}."
            )

        self.logger.info("[BRIDGE MANAGER] Executing quotes.")
        bundle["status"] = str(BridgeRequestBundleStatus.SUBMITTED)

        for request in bundle["bridge_requests"]:
            self.bridge_provider.update_with_execution(request)
            self._store_data()

        self.data.last_requested_bundle = None
        self.data.executed_bundles[bundle["id"]] = bundle
        self._store_data()
        self._bundle_updated_on_session = False
        self.logger.info(
            f"[BRIDGE MANAGER] Bundle id {bundle_id} executed."
        )

        return self.get_execution_status(bundle_id)

    def get_execution_status(self, bundle_id: str) -> dict:
        """Get execution status of bundle."""

        bundle = self.data.executed_bundles.get(bundle_id)

        if not bundle:
            raise ValueError(
                f"[BRIDGE MANAGER] Bundle id {bundle_id} not found."
            )

        self._update_bundle_status(bundle_id)

        bridge_request_status = [
            {
                "explorer_link": request["execution"]["explorer_link"],
                "message": request["execution"]["message"],
                "status": request["execution"]["status"],
                "tx_hash": request["execution"]["tx_hash"],
            }
            for request in bundle["bridge_requests"]
        ]
        error = any(
            request["execution"]["error"]
            for request in bundle["bridge_requests"]
        )

        return {
            "id": bundle["id"],
            "status": bundle["status"],
            "bridge_request_status": bridge_request_status,
            "error": error,
        }
