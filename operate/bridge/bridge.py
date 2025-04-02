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
QUOTE_BUNDLE_PREFIX = "qb-"


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
    def update_with_quote(self, bridge_workflow: dict) -> None:
        """Update the request with the quote."""
        raise NotImplementedError()

    @abstractmethod
    def get_quote_requirements(self, bridge_workflow: dict) -> dict | None:
        """Get bridge requirements for a single quote."""
        raise NotImplementedError()

    def sum_quotes_requirements(self, bridge_workflows: list) -> dict:
        """Get bridge requirements for a list of quotes."""

        bridge_requirements: dict = {}

        for workflow in bridge_workflows:
            req = self.get_quote_requirements(workflow)

            if not req:
                continue

            for from_chain, from_addresses in req.items():
                for from_address, from_tokens in from_addresses.items():
                    for from_token, from_amount in from_tokens.items():
                        bridge_requirements.setdefault(from_chain, {}).setdefault(
                            from_address, {}
                        ).setdefault(from_token, 0)
                        bridge_requirements[from_chain][from_address][
                            from_token
                        ] += from_amount

        return bridge_requirements

    @abstractmethod
    def update_with_execution(self, bridge_workflow: dict) -> None:
        """Execute the quote."""
        raise NotImplementedError()

    @abstractmethod
    def update_execution_status(self, bridge_workflow: dict) -> None:
        """Update the execution status."""
        raise NotImplementedError()

    @abstractmethod
    def is_execution_finished(self, bridge_workflow: dict) -> bool:
        """Check if the execution is finished."""
        raise NotImplementedError()


class LiFiTransactionStatus(str, enum.Enum):
    """LI.FI transaction status."""

    NOT_FOUND = "not_found"
    INVALID = "invalid"
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"

    def __str__(self) -> str:
        """__str__"""
        return self.value


class LiFiBridgeProvider(BridgeProvider):
    """LI.FI Bridge provider."""

    def update_with_quote(self, bridge_workflow: dict) -> None:
        """Update the request with the quote."""

        if "execution" in bridge_workflow:
            raise ValueError(
                "[LI.FI BRIDGE] Cannot update workflow with quote: execution already present."
            )

        from_chain = bridge_workflow["request"]["from"]["chain"]
        from_address = bridge_workflow["request"]["from"]["address"]
        from_token = bridge_workflow["request"]["from"]["token"]
        to_chain = bridge_workflow["request"]["to"]["chain"]
        to_address = bridge_workflow["request"]["to"]["address"]
        to_token = bridge_workflow["request"]["to"]["token"]
        to_amount = bridge_workflow["request"]["to"]["amount"]

        if to_amount == 0:
            self.logger.info("[LI.FI BRIDGE] Zero-amount quote requested")
            bridge_workflow["quote"] = {
                "response": {},
                "attempts": 0,
                "elapsed_time": 0,
                "error": False,
                "message": "Zero-amount quote requested",
                "status": HTTPStatus.OK,
                "timestamp": int(time.time()),
            }
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
        }
        for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
            start = time.time()
            try:
                self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
                response = requests.get(
                    url=url, headers=headers, params=params, timeout=30
                )
                response.raise_for_status()
                bridge_workflow["quote"] = {
                    "response": response.json(),
                    "attempts": attempt,
                    "elapsed_time": time.time() - start,
                    "error": False,
                    "message": "",
                    "status": response.status_code,
                    "timestamp": int(time.time()),
                }
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
                    "status": HTTPStatus.GATEWAY_TIMEOUT,
                    "timestamp": int(time.time()),
                }
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
                    "status": response.status_code,
                    "timestamp": int(time.time()),
                }

            if attempt >= DEFAULT_MAX_RETRIES:
                self.logger.error(
                    f"[LI.FI BRIDGE] Request failed after {DEFAULT_MAX_RETRIES} attempts."
                )
                bridge_workflow["quote"] = output
                return

            time.sleep(2)

    # TODO gas fees !
    def get_quote_requirements(self, bridge_workflow: dict) -> dict | None:
        """Get bridge requirements for a quote."""

        quote = bridge_workflow["quote"]["response"]
        error = bridge_workflow["quote"].get("error", False)

        if error or "action" not in quote:
            return None

        from_chain = Chain.from_id(quote["action"]["fromChainId"])
        from_address = quote["action"]["fromAddress"]
        from_token = quote["action"]["fromToken"]["address"]
        from_amount = int(quote["action"]["fromAmount"])
        transaction_value = int(quote["transactionRequest"]["value"], 16)

        if from_token == ZERO_ADDRESS:
            return {
                from_chain.value: {
                    from_address: {from_token: from_amount + transaction_value}
                }
            }
        else:
            return {
                from_chain.value: {
                    from_address: {
                        ZERO_ADDRESS: transaction_value,
                        from_token: from_amount,
                    }
                }
            }

    def update_with_execution(self, bridge_workflow: dict) -> None:
        """Execute the quote."""

        if "quote" not in bridge_workflow:
            raise ValueError(
                "[LI.FI BRIDGE] Cannot update workflow with execution: quote not present."
            )

        if "execution" in bridge_workflow:
            raise ValueError(
                "[LI.FI BRIDGE] Cannot update workflow with quote: execution already present."
            )

        quote = bridge_workflow["quote"]["response"]
        error = bridge_workflow["quote"].get("error", False)

        if error:
            self.logger.info("[LI.FI BRIDGE] Skipping quote execution (quote error).")
            bridge_workflow["execution"] = {
                "error": True,
                "explorer_link": None,
                "message": "Skipped quote execution (quote error).",
                "status": None,
                "timestamp": int(time.time()),
                "tx_hash": None,
                "tx_status": None,
            }
            return
        if not quote:
            self.logger.info("[LI.FI BRIDGE] Skipping quote execution (empty quote).")
            bridge_workflow["execution"] = {
                "error": False,
                "explorer_link": None,
                "message": "Skipped quote execution (empty quote).",
                "status": None,
                "timestamp": int(time.time()),
                "tx_hash": None,
                "tx_status": None,
            }
            return

        self.logger.info(f"[LI.FI BRIDGE] Executing quote {quote.get('id')}.")
        from_token = quote["action"]["fromToken"]["address"]
        from_amount = int(quote["action"]["fromAmount"])

        transaction_request = quote["transactionRequest"]
        from_chain = Chain.from_id(transaction_request["chainId"])
        wallet = self.wallet_manager.load(from_chain.ledger_type)

        # Bridges from an asset other than native require an approval transaction.
        if from_token != ZERO_ADDRESS:
            self.logger.info(
                f"[LI.FI BRIDGE] Preparing approve transaction for for quote {quote['id']} ({from_token}=)."
            )

            # TODO Approval is done on several places. Consider exporting to a
            # higher-level layer (e.g., wallet?)
            tx_settler = TxSettler(
                ledger_api=wallet.ledger_api(from_chain),
                crypto=wallet.crypto,
                chain_type=from_chain,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )

            def _build_approval_tx(  # pylint: disable=unused-argument
                *args: t.Any, **kargs: t.Any
            ) -> dict:
                return registry_contracts.erc20.get_approve_tx(
                    ledger_api=wallet.ledger_api(from_chain),
                    contract_address=from_token,
                    spender=transaction_request["to"],
                    sender=wallet.address,
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

        # TODO rewrite with framework methods
        self.logger.info(
            f"[LI.FI BRIDGE] Preparing bridge transaction for quote {quote['id']}."
        )
        private_key = wallet.crypto.private_key
        w3 = Web3(Web3.HTTPProvider(get_default_rpc(chain=from_chain)))
        account = w3.eth.account.from_key(private_key)

        transaction = {
            "value": w3.to_wei(int(transaction_request["value"], 16), "wei"),
            "to": transaction_request["to"],
            "data": bytes.fromhex(transaction_request["data"][2:]),
            "from": account.address,
            "gasPrice": w3.to_wei(int(transaction_request["gasPrice"], 16), "wei"),
            "chainId": transaction_request["chainId"],
            "nonce": w3.eth.get_transaction_count(account.address),
        }

        gas_estimate = w3.eth.estimate_gas(transaction)
        transaction["gas"] = gas_estimate
        signed_transaction = w3.eth.account.sign_transaction(transaction, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_transaction.rawTransaction)
        self.logger.info(f"[LI.FI BRIDGE] Bridge transaction tx_hash={tx_hash.hex()}.")

        # TODO remove?
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        self.logger.info("[LI.FI BRIDGE] Bridge transaction settled.")

        bridge_workflow["execution"] = {
            "error": receipt.get("status", 0) == 0,
            "explorer_link": f"https://scan.li.fi/tx/{tx_hash.hex()}",
            "message": "",
            "status": None,
            "timestamp": int(time.time()),
            "tx_hash": tx_hash.hex(),
            "tx_status": receipt.get("status", 0),
        }

    def update_execution_status(self, bridge_workflow: dict) -> None:
        """Update the execution status."""

        if "execution" not in bridge_workflow:
            raise ValueError(
                "[LI.FI BRIDGE] Cannot update workflow execution: execution not present."
            )

        execution = bridge_workflow["execution"]
        tx_hash = execution["tx_hash"]

        if not tx_hash:
            execution["status"] = None
            return

        url = "https://li.quest/v1/status"
        headers = {"accept": "application/json"}
        params = {
            "txHash": tx_hash,
        }
        response = requests.get(url=url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        status = response_json.get("status", "unknown").lower()
        execution["status"] = status

    def is_execution_finished(self, bridge_workflow: dict) -> bool:
        """Check if the execution is finished."""

        if "execution" not in bridge_workflow:
            raise ValueError(
                "[LI.FI BRIDGE] Cannot update workflow execution: execution not present."
            )

        execution = bridge_workflow["execution"]

        if execution["tx_hash"] is None:
            execution["status"] = None
            return True

        if execution["status"] in (
            LiFiTransactionStatus.DONE,
            LiFiTransactionStatus.FAILED,
        ):
            return True

        self.update_execution_status(bridge_workflow)

        execution = bridge_workflow["execution"]
        if execution["status"] in (
            LiFiTransactionStatus.DONE,
            LiFiTransactionStatus.FAILED,
        ):
            return True

        return False


class QuoteBundleStatus(str, enum.Enum):
    """Quote bundle status."""

    CREATED = "created"
    QUOTED = "quoted"
    SUBMITTED = "submitted"
    FINISHED = "finished"  # All requests in the bundle are either done or failed.

    def __str__(self) -> str:
        """__str__"""
        return self.value


@dataclass
class BridgeManagerData(LocalResource):
    """BridgeManagerData"""

    path: Path
    version: int = 1
    last_requested_quote_bundle: dict | None = None
    executed_quotes: dict = field(default_factory=dict)

    _file = "bridge.json"

    # TODO Migrate to LocalResource?
    def store(self) -> None:
        """Store local resource."""

        file_path = self.path / self._file
        backup_path = file_path.with_name(file_path.name + ".bak")

        try:
            if file_path.exists():
                json.loads(file_path.read_text(encoding="utf-8"))
                if backup_path.exists():
                    backup_path.unlink()
                shutil.copy2(file_path, backup_path)
        except json.JSONDecodeError:
            pass

        super().store()

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

    _quote_bundle_updated_on_session = False

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
        self.data.store()

    def _get_updated_quote_bundle(
        self, bridge_requests: list, force_update: bool
    ) -> dict:
        """Ensures to return a valid (non expired) quote bundle for the given inputs."""

        now = int(time.time())
        quote_bundle = self.data.last_requested_quote_bundle or {}
        quote_bundle_id = quote_bundle.get("id")
        create_new_quote_bundle = False

        if not quote_bundle:
            self.logger.info("[BRIDGE MANAGER] No last quote bundle.")
            create_new_quote_bundle = True
            quote_bundle_id = None
        elif quote_bundle.get("status") != QuoteBundleStatus.QUOTED:
            raise RuntimeError("[BRIDGE MANAGER] Quote bundle inconsistent status.")
        elif DeepDiff(bridge_requests, quote_bundle.get("bridge_requests", [])):
            self.logger.info("[BRIDGE MANAGER] Different quote requests.")
            create_new_quote_bundle = True
            quote_bundle_id = None
        elif force_update:
            self.logger.info("[BRIDGE MANAGER] Force quote update.")
            create_new_quote_bundle = True
        elif now > quote_bundle.get("timestamp", 0) + self.quote_validity_period:
            self.logger.info("[BRIDGE MANAGER] Quote bundle expired.")
            create_new_quote_bundle = True

        if create_new_quote_bundle:
            self.logger.info("[BRIDGE MANAGER] Requesting new quote bundle.")
            quote_bundle = {}
            quote_bundle["id"] = (
                quote_bundle_id or f"{QUOTE_BUNDLE_PREFIX}{uuid.uuid4()}"
            )
            quote_bundle["bridge_provider"] = self.bridge_provider.name()
            quote_bundle["status"] = str(QuoteBundleStatus.CREATED)
            quote_bundle["bridge_requests"] = bridge_requests
            quote_bundle["bridge_workflows"] = [
                {"request": request} for request in bridge_requests
            ]
            quote_bundle["timestamp"] = now
            quote_bundle["expiration_timestamp"] = now + self.quote_validity_period

            for workflow in quote_bundle["bridge_workflows"]:
                self.bridge_provider.update_with_quote(workflow)

            quote_bundle["status"] = str(QuoteBundleStatus.QUOTED)
            quote_bundle[
                "bridge_requirements"
            ] = self.bridge_provider.sum_quotes_requirements(
                quote_bundle["bridge_workflows"]
            )

            self.data.last_requested_quote_bundle = quote_bundle
            self.data.store()

        return quote_bundle

    def _update_quote_bundle_status(self, quote_bundle_id: str) -> None:
        quote_bundle = self.data.executed_quotes.get(quote_bundle_id)

        if not quote_bundle:
            raise ValueError(
                f"[BRIDGE MANAGER] Quote bundle id {quote_bundle_id} not found."
            )

        initial_status = quote_bundle["status"]
        is_execution_finished = all(
            self.bridge_provider.is_execution_finished(workflow)
            for workflow in quote_bundle["bridge_workflows"]
        )

        if is_execution_finished:
            quote_bundle["status"] = str(QuoteBundleStatus.FINISHED)
        else:
            quote_bundle["status"] = str(QuoteBundleStatus.SUBMITTED)

        if initial_status != quote_bundle["status"]:
            self.data.store()

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

        quote_bundle = self._get_updated_quote_bundle(bridge_requests, force_update)

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
        for from_chain, from_addresses in quote_bundle["bridge_requirements"].items():
            ledger_api = self.wallet_manager.load(
                Chain(from_chain).ledger_type
            ).ledger_api(Chain(from_chain))
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

        quote_response_status = [
            {
                "message": response["quote"]["message"],
                "error": response["quote"]["error"],
            }
            for response in quote_bundle["bridge_workflows"]
        ]
        errors = any(
            workflow["quote"]["error"] for workflow in quote_bundle["bridge_workflows"]
        )
        self._quote_bundle_updated_on_session = True

        return {
            "id": quote_bundle["id"],
            "balances": balances,
            "bridge_requirements": quote_bundle["bridge_requirements"],
            "bridge_refill_requirements": bridge_refill_requirements,
            "expiration_timestamp": quote_bundle["expiration_timestamp"],
            "expiration_timeout": int(
                quote_bundle["expiration_timestamp"] - time.time()
            ),
            "is_refill_required": is_refill_required,
            "quote_response_status": quote_response_status,
            "errors": errors,
        }

    def execute_quote_bundle(self, quote_bundle_id: str) -> dict:
        """Execute quote bundle"""

        if not self._quote_bundle_updated_on_session:
            raise RuntimeError(
                "[BRIDGE MANAGER] Cannot call 'execute_quote_bundle' before 'bridge_refill_requirements'."
            )

        quote_bundle = self.data.last_requested_quote_bundle

        if not quote_bundle:
            raise RuntimeError("[BRIDGE MANAGER] No quote bundle.")

        if quote_bundle.get("id") != quote_bundle_id:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Quote bundle id {quote_bundle_id} does not match last requested quote bundle id {quote_bundle.get('id')}."
            )

        requirements = self.bridge_refill_requirements(quote_bundle["bridge_requests"])

        if requirements["is_refill_required"]:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Refill requirements not satisfied for quote bundle id {quote_bundle_id}."
            )

        self.logger.info("[BRIDGE MANAGER] Executing quotes.")
        for bridge_workflow in quote_bundle["bridge_workflows"]:
            self.bridge_provider.update_with_execution(bridge_workflow)

        quote_bundle["status"] = str(QuoteBundleStatus.SUBMITTED)

        self.data.last_requested_quote_bundle = None
        self.data.executed_quotes[quote_bundle["id"]] = quote_bundle
        self.data.store()
        self._quote_bundle_updated_on_session = False
        self.logger.info(
            f"[BRIDGE MANAGER] Quote bundle id {quote_bundle_id} executed."
        )

        return self.get_execution_status(quote_bundle_id)

    def get_execution_status(self, quote_bundle_id: str) -> dict:
        """Get execution status of quote bundle."""

        quote_bundle = self.data.executed_quotes.get(quote_bundle_id)

        if not quote_bundle:
            raise ValueError(
                f"[BRIDGE MANAGER] Quote bundle id {quote_bundle_id} not found."
            )

        self._update_quote_bundle_status(quote_bundle_id)

        executions = [
            workflow["execution"] for workflow in quote_bundle["bridge_workflows"]
        ]
        errors = any(
            workflow["execution"]["error"]
            for workflow in quote_bundle["bridge_workflows"]
        )

        return {
            "id": quote_bundle["id"],
            "status": quote_bundle["status"],
            "executions": executions,
            "errors": errors,
        }
