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
import time
import uuid
from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import cast

import requests
from aea.helpers.logging import setup_logger
from deepdiff import DeepDiff
from web3 import Web3

from operate.constants import ZERO_ADDRESS
from operate.ledger import get_default_rpc
from operate.ledger.profiles import get_target_chain_asset_address
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.services.manage import get_assets_balances
from operate.utils.gnosis import get_asset_balance
from operate.wallet.master import MasterWalletManager


DEFAULT_MAX_RETRIES = 3
DEFAULT_QUOTE_VALIDITY_PERIOD = 3 * 60
QUOTE_BUNDLE_PREFIX = "qb-"


class Bridge:
    """Abstract Bridge"""

    def __init__(self, wallet_manager: MasterWalletManager) -> None:
        """Initialize the bridge"""
        self.wallet_manager = wallet_manager

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
        """Get bridge quote"""
        raise NotImplementedError()

    def get_quotes(self, quote_requests: list) -> dict:
        """Get bridge quotes (destinations specified in `to` dict)"""
        quotes = {}

        for quote_request in quote_requests:
            quote = self.get_quote(
                from_chain=Chain(quote_request["from_chain"]),
                from_address=quote_request["from_address"],
                from_token=quote_request["from_token"],
                to_chain=Chain(quote_request["to_chain"]),
                to_address=quote_request["to_address"],
                to_token=quote_request["to_token"],
                to_amount=quote_request["to_amount"],
            )

            if quote:
                quotes[quote["id"]] = quote

        return quotes

    @abstractmethod
    def get_quote_requirements(self, quote: dict) -> dict:
        """Get bridge requirements given a collection of quotes"""
        raise NotImplementedError()

    def sum_quotes_requirements(self, quotes: dict) -> dict:
        """Get bridge requirements given a collection of quotes"""

        bridge_requirements = {}

        for _, quote in quotes.items():
            req = self.get_quote_requirements(quote)
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
        """Execute the quote"""
        raise NotImplementedError()


class LiFiBridge(Bridge):
    """LI.FI Bridge"""

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
        """Get bridge quote"""

        if to_amount == 0:
            return {}

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
                return response.json()
            except requests.RequestException as e:
                print(
                    f"[BRIDGE MANAGER] Request quote failed with code {response.status_code} (attempt {attempt}/{DEFAULT_MAX_RETRIES}): {e}"
                )

                if attempt >= DEFAULT_MAX_RETRIES:
                    print(
                        f"[BRIDGE MANAGER]Request quote failed with code {response.status_code} after {DEFAULT_MAX_RETRIES} attempts: {e}"
                    )
                    raise
        return {}

    # TODO gas fees !
    def get_quote_requirements(self, quote: dict) -> dict:
        """Get bridge requirements given a collection of quotes"""

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

    def execute_quote(self, quote) -> None:
        """Execute the quote"""

        print("Execute_quote")
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
            print(f"Approve transaction for token {from_token}")
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
            print(f"Approve transaction {tx_hash=}")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            print(f"Approve transaction {receipt=}")

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
    requested_quote_bundles: dict = field(default_factory=dict)

    _file = "bridge.json"


class BridgeManager:
    """BridgeManager"""

    def __init__(
        self,
        path: Path,
        wallet_manager: MasterWalletManager,
        logger: logging.Logger | None = None,
        bridge: Bridge | None = None,
        quote_validity_period: int | None = None,
    ) -> None:
        """Initialize bridge manager."""
        self.path = path
        self.wallet_manager = wallet_manager
        self.logger = logger or setup_logger(name="operate.master_wallet_manager")
        self.bridge = bridge or LiFiBridge(wallet_manager)
        self.quote_validity_period = (
            quote_validity_period or DEFAULT_QUOTE_VALIDITY_PERIOD
        )

        self.path.mkdir(exist_ok=True)

        # TODO Migrate to LocalResource
        data_file = path / BridgeManagerData._file
        if not data_file.exists():
            data = BridgeManagerData(path=path)
            data.store()
        # End migrate

        self.data: BridgeManagerData = cast(
            BridgeManagerData, BridgeManagerData.load(path)
        )
        self.data.store()

    @staticmethod
    def _get_from_tokens(from_chain: Chain, to: dict) -> set:
        from_tokens = set()
        for to_chain_str in to:
            for to_address in to[to_chain_str]:
                for to_token in to[to_chain_str][to_address]:
                    to_chain = Chain(to_chain_str)
                    from_tokens.add(
                        get_target_chain_asset_address(
                            source_chain=to_chain,
                            source_asset_address=to_token,
                            target_chain=from_chain,
                        )
                    )
        return from_tokens
    
    @staticmethod
    def _get_quote_bundle_id(quote_requests: list) -> str
        """Generate a deterministic id based on the content of quote_requests."""

        json_list = [json.dumps(obj, sort_keys=True, separators=(",", ":")) for obj in quote_requests]
        
        # Sort the JSON string representations
        json_list.sort()




    def _get_valid_quote_bundle(self, quote_requests: list) -> dict:
        """Ensures to return a valid (non expired) quote bundle for the given inputs."""
        quote_bundle = self.data.requested_quote_bundles
        now = int(time.time())

        refresh_quote_bundle = False
        if not quote_bundle:
            self.logger.info("[BRIDGE MANAGER] No last_requested_quote_bundle.")
            refresh_quote_bundle = True
            quote_bundle = {}
            quote_bundle["id"] = f"{QUOTE_BUNDLE_PREFIX}{uuid.uuid4()}"
            quote_bundle["quote_requests"] = quote_requests
        elif DeepDiff(quote_requests, quote_bundle.get("quote_requests", {})):
            self.logger.info("[BRIDGE MANAGER] Different quote requests.")
            refresh_quote_bundle = True
        elif now > quote_bundle.get("expiration_timestamp", 0):
            self.logger.info("[BRIDGE MANAGER] Quote bundle expired.")
            refresh_quote_bundle = True

        if refresh_quote_bundle:
            self.logger.info("[BRIDGE MANAGER] Requesting new quote bundle.")
            quote_bundle["timestamp"] = now
            quote_bundle["expiration_timestamp"] = now + self.quote_validity_period
            quote_bundle["quotes"] = self.bridge.get_quotes(quote_requests)
            quote_bundle["bridge_requirements"] = self.bridge.sum_quotes_requirements(
                quote_bundle["quotes"]
            )
            self.data.requested_quote_bundles[quote_bundle["id"]] = quote_bundle

        self.data.state = BridgeManagerState.QUOTE_BUNDLE_UP_TO_DATE
        self.data.store()
        return quote_bundle

    @staticmethod
    def _has_duplicates(quote_requests: list) -> bool:
        """Check if there are duplicate quote requests (excluding to_amount value)."""

        seen = set()
        for request in quote_requests:
            key = (
                request["from_chain"],
                request["from_address"],
                request["from_token"],
                request["to_chain"],
                request["to_address"],
                request["to_token"],
            )

            if key in seen:
                return True
            seen.add(key)

        return False

    @staticmethod
    def _flatten_quote_requests(quote_requests: list) -> list:
        """Flatten quote requests into an internal format.

        {
            from_chain: value,
            from_address: value,
            from_token: value,
            to_chain: value,
            to_address: value,
            to_token: value,
            to_amount: value
        }
        """
        flattened = []

        for request in quote_requests:
            if len(request["from"]) != 1:
                raise ValueError(
                    "[BRIDGE MANAGER] Invalid input: All quote requests must contain exactly one sender and one token."
                )

            from_chain, from_addresses = next(iter(request["from"].items()))

            if len(from_addresses) != 1:
                raise ValueError(
                    "[BRIDGE MANAGER] Invalid input: All quote requests must contain exactly one sender and one token."
                )

            from_address, from_token = next(iter(from_addresses.items()))

            for to_chain, to_details in request["to"].items():
                to_address, to_address_details = next(iter(to_details.items()))
                for to_token, amount in to_address_details.items():
                    flattened.append(
                        {
                            "from_address": from_address,
                            "from_token": from_token,
                            "from_chain": from_chain,
                            "to_address": to_address,
                            "to_token": to_token,
                            "to_chain": to_chain,
                            "to_amount": amount,
                        }
                    )

        return flattened

    def bridge_refill_requirements(self, request: dict) -> dict:
        """Get bridge refill requirements."""

        # TODO Purge empty addresses on 'to'
        # TODO store flattened vs user input

        quote_requests = self._flatten_quote_requests(request["quote_requests"])

        if self._has_duplicates(quote_requests):
            raise ValueError(
                "[BRIDGE MANAGER] Input contains duplicate quote requests."
            )

        self.logger.info(f"[BRIDGE MANAGER] {len(quote_requests)} quotes requested.")
        quote_bundle = self._get_valid_quote_bundle(quote_requests)

        bridge_requirements = self.bridge.sum_quotes_requirements(
            quote_bundle["quotes"]
        )

        balances = {}
        bridge_refill_requirements = {}
        for from_chain, from_addresses in bridge_requirements.items():
            ledger_api = self.wallet_manager.load(
                Chain(from_chain).ledger_type
            ).ledger_api(Chain(from_chain))
            for from_address, from_tokens in from_addresses.items():
                for from_token, from_amount in from_tokens.items():
                    balance = get_asset_balance(
                        ledger_api=ledger_api,
                        address=from_address,
                        asset_address=from_token,
                    )
                    balances.setdefault(from_chain, {}).setdefault(from_address, {})
                    balances[from_chain][from_address][from_token] = balance
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

        return {
            "id": quote_bundle["id"],
            "balances": balances,
            "bridge_requirements": bridge_requirements,
            "bridge_refill_requirements": bridge_refill_requirements,
            "expiration_timestamp": quote_bundle["expiration_timestamp"],
            "is_refill_required": is_refill_required,
        }

    def execute_quote_bundle(self, quote_bundle_id: str) -> None:
        """Execute quote bundle"""

        quote_bundle = self.data.requested_quote_bundles.get(quote_bundle_id)
        if not quote_bundle:
            raise ValueError(f"[BRIDGE MANAGER] Id {quote_bundle_id} not found.")

        quote_requests = quote_bundle["quote_requests"]

        requirements = self.bridge_refill_requirements(quote_requests)

        if requirements["is_refill_required"]:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Refill requirements not satisfied for quote bundle id {quote_bundle_id}."
            )

        print("[BRIDGE MANAGER] Executing quotes")
        for _, quote in self.data.requested_quote_bundles["quotes"].items():
            self.bridge.execute_quote(quote)
