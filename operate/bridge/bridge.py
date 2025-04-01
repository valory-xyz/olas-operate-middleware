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


import json
import logging
import shutil
import time
import uuid
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import requests
from aea.helpers.logging import setup_logger
from deepdiff import DeepDiff
from web3 import Web3

from operate.constants import ZERO_ADDRESS
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
    def get_quote(
        self,
        from_chain: Chain,
        from_address: str,
        from_token: str,
        to_chain: Chain,
        to_token: str,
        to_address: str,
        to_amount: int,
    ) -> dict:
        """Get bridge quote."""
        raise NotImplementedError()

    def get_quote_responses(self, quote_requests: list) -> list:
        """Get bridge quotes."""
        bridge_quote_responses = []

        for quote_request in quote_requests:
            bridge_quote_response = self.get_quote(
                from_chain=Chain(quote_request["from"]["chain"]),
                from_address=quote_request["from"]["address"],
                from_token=quote_request["from"]["token"],
                to_chain=Chain(quote_request["to"]["chain"]),
                to_address=quote_request["to"]["address"],
                to_token=quote_request["to"]["token"],
                to_amount=quote_request["to"]["amount"],
            )

            # TODO remove 0 - transfer quotes on sanitize input?
            bridge_quote_responses.append(bridge_quote_response)

        return bridge_quote_responses

    @abstractmethod
    def get_quote_requirements(self, bridge_quote_response: dict) -> dict | None:
        """Get bridge requirements for a single quote."""
        raise NotImplementedError()

    def sum_quotes_requirements(self, bridge_quote_responses: list) -> dict:
        """Get bridge requirements for a list of quotes."""

        bridge_requirements: dict = {}

        for bridge_quote_response in bridge_quote_responses:
            req = self.get_quote_requirements(bridge_quote_response)

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
    def execute_quote(self, quote: dict) -> None:
        """Execute the quote."""
        raise NotImplementedError()


class LiFiBridgeProvider(BridgeProvider):
    """LI.FI Bridge provider."""

    def get_quote(
        self,
        from_chain: Chain,
        from_address: str,
        from_token: str,
        to_chain: Chain,
        to_token: str,
        to_address: str,
        to_amount: int,
    ) -> dict:
        """Get bridge quote."""

        now = int(time.time())
        if to_amount == 0:
            self.logger.info("[LI.FI BRIDGE] Zero-amount quote requested")
            return {
                "quote": {},
                "metadata": {
                    "attempts": 0,
                    "error": False,
                    "message": "Zero-amount quote requested",
                    "request_status": 0,
                    "timestamp": now,
                },
            }

        url = "https://li.quest/v1/quote/toAmount"
        headers = {"accept": "application/json"}
        params = {
            "fromChain": from_chain.id,
            "fromAddress": from_address,
            "fromToken": from_token,
            "toChain": to_chain.id,
            "toAddress": to_address,
            "toToken": to_token,
            "toAmount": to_amount,
        }
        for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
            try:
                response = requests.get(
                    url=url, headers=headers, params=params, timeout=30
                )
                response.raise_for_status()
                return {
                    "quote": response.json(),
                    "metadata": {
                        "attempts": attempt,
                        "error": False,
                        "message": "",
                        "request_status": response.status_code,
                        "timestamp": now,
                    },
                }
            except requests.RequestException as e:
                self.logger.warning(
                    f"[LI.FI BRIDGE] Request quote failed with code {response.status_code} (attempt {attempt}/{DEFAULT_MAX_RETRIES}): {e}"
                )

                if attempt >= DEFAULT_MAX_RETRIES:
                    self.logger.error(
                        f"[LI.FI BRIDGE]Request quote failed with code {response.status_code} after {DEFAULT_MAX_RETRIES} attempts: {e}"
                    )
                    response_json = response.json()
                    return {
                        "quote": response_json,
                        "metadata": {
                            "attempts": attempt,
                            "error": True,
                            "message": response_json["message"],
                            "request_status": response.status_code,
                            "timestamp": now,
                        },
                    }
                else:
                    time.sleep(2)

        return {}

    # TODO gas fees !
    def get_quote_requirements(self, bridge_quote_response: dict) -> dict | None:
        """Get bridge requirements for a quote."""

        quote = bridge_quote_response["quote"]
        metadata = bridge_quote_response["metadata"]

        if metadata.get("error", False) or "action" not in quote:
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

    def execute_quote(self, quote: dict) -> None:
        """Execute the quote."""

        self.logger.info("[LI.FI BRIDGE] Execute quote.")
        from_token = quote["action"]["fromToken"]["address"]
        from_amount = int(quote["action"]["fromAmount"])

        transaction_request = quote["transactionRequest"]
        from_chain = Chain.from_id(transaction_request["chainId"])
        wallet = self.wallet_manager.load(from_chain.ledger_type)

        # TODO rewrite with framework methods
        private_key = wallet.crypto.private_key
        w3 = Web3(Web3.HTTPProvider(get_default_rpc(chain=from_chain)))
        account = w3.eth.account.from_key(private_key)

        if from_token != ZERO_ADDRESS:
            self.logger.info(f"[LI.FI BRIDGE] Approve transaction for token {from_token}.")
            from_token_contract = w3.eth.contract(
                address=from_token,
                abi=[
                    {
                        "constant": False,
                        "inputs": [
                            {"name": "spender", "type": "address"},
                            {"name": "amount", "type": "uint256"},
                        ],
                        "name": "approve",
                        "outputs": [{"name": "", "type": "bool"}],
                        "payable": False,
                        "stateMutability": "nonpayable",
                        "type": "function",
                    }
                ],
            )

            transaction = from_token_contract.functions.approve(
                transaction_request["to"], from_amount
            ).build_transaction(
                {
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "gasPrice": w3.to_wei("20", "gwei"),
                }
            )

            gas_estimate = w3.eth.estimate_gas(transaction)
            transaction["gas"] = gas_estimate
            signed_transaction = w3.eth.account.sign_transaction(
                transaction, private_key
            )
            tx_hash = w3.eth.send_raw_transaction(signed_transaction.rawTransaction)
            self.logger.info(f"[LI.FI BRIDGE] Approve transaction {tx_hash=}.")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            self.logger.info(f"[LI.FI BRIDGE] Approve transaction {receipt=}.")

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
        print(f"Quote transaction {tx_hash=}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"Quote transaction {receipt=}")


@dataclass
class BridgeManagerData(LocalResource):
    """BridgeManagerData"""

    path: Path
    version: int = 1
    last_requested_quote_bundle: dict | None = None

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

    def _get_valid_quote_bundle(
        self, quote_requests: list, force_update_quotes: bool
    ) -> dict:
        """Ensures to return a valid (non expired) quote bundle for the given inputs."""

        now = int(time.time())
        quote_bundle = self.data.last_requested_quote_bundle or {}
        create_new_quote_bundle = False
        update_quotes = False

        if not quote_bundle:
            self.logger.info("[BRIDGE MANAGER] No last quote bundle.")
            create_new_quote_bundle = True
        elif DeepDiff(quote_requests, quote_bundle.get("quote_requests", [])):
            self.logger.info("[BRIDGE MANAGER] Different quote requests.")
            create_new_quote_bundle = True
        elif force_update_quotes:
            self.logger.info("[BRIDGE MANAGER] Force quote update.")
            update_quotes = True
        elif now > quote_bundle.get("expiration_timestamp", 0):
            self.logger.info("[BRIDGE MANAGER] Quote bundle expired.")
            update_quotes = True

        if create_new_quote_bundle:
            quote_bundle["id"] = f"{QUOTE_BUNDLE_PREFIX}{uuid.uuid4()}"
            quote_bundle["quote_requests"] = quote_requests
            quote_bundle["executions"] = []
            quote_bundle["execution_status"] = []
            update_quotes = True

        if update_quotes:
            self.logger.info("[BRIDGE MANAGER] Requesting new quote bundle.")
            quote_bundle["timestamp"] = now
            quote_bundle["expiration_timestamp"] = now + self.quote_validity_period
            quote_bundle["bridge_provider"] = self.bridge_provider.name()
            quote_bundle[
                "bridge_quote_responses"
            ] = self.bridge_provider.get_quote_responses(quote_requests)
            quote_bundle[
                "bridge_requirements"
            ] = self.bridge_provider.sum_quotes_requirements(
                quote_bundle["bridge_quote_responses"]
            )

            self.data.last_requested_quote_bundle = quote_bundle
            self.data.store()

        return quote_bundle

    @staticmethod
    def _validate_input(bridge_requests: list) -> None:
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

    def bridge_refill_requirements(self, client_input: dict) -> dict:
        """Get bridge refill requirements."""

        # TODO check if destination is EOA or Safe.

        quote_requests = client_input.get("quote_requests", [])
        force_update_quotes = client_input.get("force_update_quotes", False)
        self._validate_input(quote_requests)
        self.logger.info(
            f"[BRIDGE MANAGER] Num. quote requests: {len(quote_requests)}."
        )
        quote_bundle = self._get_valid_quote_bundle(quote_requests, force_update_quotes)

        bridge_requirements = self.bridge_provider.sum_quotes_requirements(
            quote_bundle["bridge_quote_responses"]
        )

        chains = [request["from"]["chain"] for request in quote_requests]
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
                    for request in quote_requests
                    if request["from"]["chain"] == chain
                },
                addresses={
                    request["from"]["address"]
                    for request in quote_requests
                    if request["from"]["chain"] == chain
                },
            )

        bridge_refill_requirements: dict = {}
        for from_chain, from_addresses in bridge_requirements.items():
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
            response["metadata"] for response in quote_bundle["bridge_quote_responses"]
        ]
        errors = any(status["error"] for status in quote_response_status)

        return {
            "id": quote_bundle["id"],
            "balances": balances,
            "bridge_requirements": bridge_requirements,
            "bridge_refill_requirements": bridge_refill_requirements,
            "expiration_timestamp": quote_bundle["expiration_timestamp"],
            "expiration_timeout": int(
                quote_bundle["expiration_timestamp"] - time.time()
            ),
            "is_refill_required": is_refill_required,
            "quote_response_status": quote_response_status,
            "errors": errors,
        }

    def execute_quote_bundle(self, quote_bundle_id: str) -> None:
        """Execute quote bundle"""

        quote_bundle = self.data.last_requested_quote_bundle
        if not quote_bundle:
            raise ValueError(f"[BRIDGE MANAGER] Id {quote_bundle_id} not found.")

        quote_requests = quote_bundle["quote_requests"]

        requirements = self.bridge_refill_requirements(quote_requests)

        if requirements["is_refill_required"]:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Refill requirements not satisfied for quote bundle id {quote_bundle_id}."
            )

        self.logger.info("[BRIDGE MANAGER] Executing quotes.")
        for quote in quote_bundle["bridge_quote_responses"]:
            self.bridge_provider.execute_quote(quote)
