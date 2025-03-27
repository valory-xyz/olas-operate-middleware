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


import logging
import time
import typing as t
import uuid
from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

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

    @abstractmethod
    def get_from_token(self, quote: dict) -> int:
        """Get the from_token of a quote"""
        raise NotImplementedError()

    @abstractmethod
    def get_from_amount(self, quote: dict) -> int:
        """Get the from_amount of a quote"""
        raise NotImplementedError()

    @abstractmethod
    def get_transaction_value(self, quote: dict) -> int:
        """Get the transaction value to execute a quote"""
        raise NotImplementedError()

    def get_quotes(self, from_chain: Chain, from_address: str, to: dict) -> dict:
        """Get bridge quotes (destinations specified in `to` dict)"""
        quotes = {}
        for to_chain_str in to:
            for to_address in to[to_chain_str]:
                for to_token, to_amount in to[to_chain_str][to_address].items():
                    to_chain = Chain(to_chain_str)
                    from_token = get_target_chain_asset_address(
                        source_chain=to_chain,
                        source_asset_address=to_token,
                        target_chain=from_chain,
                    )

                    quote = self.get_quote(
                        from_chain=from_chain,
                        from_address=from_address,
                        from_token=from_token,
                        to_chain=to_chain,
                        to_address=to_address,
                        to_token=to_token,
                        to_amount=to_amount,
                    )

                    if quote:
                        quotes[quote["id"]] = quote

        return quotes

    # TODO gas fees !
    def get_bridge_requirements(self, quotes: dict) -> dict:
        """Get bridge requirements given a collection of quotes"""
        bridge_requirements: defaultdict = defaultdict(int)

        for _, quote in quotes.items():
            from_token = self.get_from_token(quote)
            from_amount = self.get_from_amount(quote)
            transaction_value = self.get_transaction_value(quote)
            if from_token != ZERO_ADDRESS:
                bridge_requirements[from_token] += from_amount
            bridge_requirements[ZERO_ADDRESS] += transaction_value

        return dict(bridge_requirements)

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

    def get_from_token(self, quote: dict) -> int:
        """Get the from_token of a quote"""
        return quote["action"]["fromToken"]["address"]

    def get_from_amount(self, quote: dict) -> int:
        """Get the from_amount of a quote"""
        return int(quote["action"]["fromAmount"])

    def get_transaction_value(self, quote: dict) -> int:
        """Get the transaction value to execute a quote"""
        return int(quote["transactionRequest"]["value"], 16)

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


class BridgeManagerState(Enum):
    """BridgeManagerState"""

    QUOTE_BUNDLE_NOT_REQUESTED = 0
    QUOTE_BUNDLE_UP_TO_DATE = 1


@dataclass
class BridgeManagerData(LocalResource):
    """BridgeManagerData"""

    path: Path
    version: int = 1
    last_requested_quote_bundle: t.Dict = field(default_factory=dict)  # type: ignore
    state: BridgeManagerState = BridgeManagerState.QUOTE_BUNDLE_NOT_REQUESTED

    _file = "bridge.json"


class BridgeManager:
    """BridgeManager"""

    def __init__(
        self,
        path: Path,
        wallet_manager: MasterWalletManager,
        logger: t.Optional[logging.Logger] = None,
        bridge: t.Optional[Bridge] = None,
        quote_validity_period: t.Optional[int] = None,
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

        self.data: BridgeManagerData = t.cast(
            BridgeManagerData, BridgeManagerData.load(path)
        )
        self.data.state = BridgeManagerState.QUOTE_BUNDLE_NOT_REQUESTED
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

    def _get_valid_quote_bundle(self, from_: dict, to: dict) -> dict:
        """Ensures to return a valid (non expired) quote bundle for the given inputs."""
        from_chain, from_address = next(iter(from_.items()))
        from_chain = Chain(from_chain)

        wallet = self.wallet_manager.load(from_chain.ledger_type)

        from_safe = False
        if (
            wallet.safes
            and from_chain in wallet.safes
            and from_address == wallet.safes[from_chain]
        ):
            from_safe = True
        elif from_address == wallet.address:
            from_safe = False
        else:
            raise ValueError(
                f"[BRIDGE MANAGER] Invalid 'from_' input: Address does not match Master Safe nor Master EOA. {from_=}"
            )

        quote_bundle = self.data.last_requested_quote_bundle
        now = int(time.time())

        refresh_quote_bundle = False
        if not quote_bundle:
            self.logger.info("[BRIDGE MANAGER] No last_requested_quote_bundle.")
            refresh_quote_bundle = True
        elif DeepDiff(quote_bundle.get("from", {}), from_) or DeepDiff(
            quote_bundle.get("to", {}), to
        ):
            self.logger.info(
                "[BRIDGE MANAGER] Different quote bundle input parameters."
            )
            refresh_quote_bundle = True
        elif now > quote_bundle.get("expiration_timestamp", 0):
            self.logger.info("[BRIDGE MANAGER] Quote bundle expired.")
            refresh_quote_bundle = True

        if refresh_quote_bundle:
            self.logger.info("[BRIDGE MANAGER] Requesting new quote bundle.")
            quote_bundle = {}
            quote_bundle["id"] = f"{QUOTE_BUNDLE_PREFIX}{uuid.uuid4()}"
            quote_bundle["timestamp"] = now
            quote_bundle["expiration_timestamp"] = now + self.quote_validity_period
            quote_bundle["quotes"] = {}
            quote_bundle["from"] = from_
            quote_bundle["to"] = to
            quote_bundle["from_safe"] = from_safe
            quote_bundle["quotes"] = self.bridge.get_quotes(
                from_chain=from_chain, from_address=from_address, to=to
            )
            quote_bundle["bridge_requirements"] = self.bridge.get_bridge_requirements(
                quote_bundle["quotes"]
            )
            self.data.last_requested_quote_bundle = quote_bundle

        self.data.state = BridgeManagerState.QUOTE_BUNDLE_UP_TO_DATE
        self.data.store()
        return quote_bundle

    def bridge_refill_requirements(self, from_: dict, to: dict) -> dict:
        """Get bridge refill requirements."""

        if not isinstance(from_, dict) or len(from_) != 1:
            raise ValueError(
                f"[BRIDGE MANAGER] Invalid 'from_' input: Must contain exactly one chain mapping. {from_=}"
            )

        from_chain, from_address = next(iter(from_.items()))
        from_chain = Chain(from_chain)
        wallet = self.wallet_manager.load(from_chain.ledger_type)

        # TODO Purge empty addresses on 'to'

        quote_bundle = self._get_valid_quote_bundle(from_, to)

        balances = get_assets_balances(
            ledger_api=wallet.ledger_api(chain=from_chain),
            addresses={from_address},
            asset_addresses={ZERO_ADDRESS}
            | self._get_from_tokens(from_chain=from_chain, to=to),
            raise_on_invalid_address=False,
        )

        bridge_refill_requirements = {}
        bridge_refill_requirements[from_address] = {}
        for from_token, amount in quote_bundle["bridge_requirements"].items():
            bridge_refill_requirements[from_address][from_token] = max(
                amount - balances[from_address][from_token], 0
            )

        print(bridge_refill_requirements)
        is_refill_required = any(
            amount > 0
            for asset in bridge_refill_requirements.values()
            for amount in asset.values()
        )

        return {
            "id": quote_bundle["id"],
            "balances": {from_chain.value: balances},
            "bridge_requirements": {
                from_chain.value: quote_bundle["bridge_requirements"]
            },
            "bridge_refill_requirements": {
                from_chain.value: dict(bridge_refill_requirements)
            },
            "expiration_timestamp": quote_bundle["expiration_timestamp"],
            "is_refill_required": is_refill_required,
        }

    def execute_quote_bundle(self, quote_bundle_id: str) -> None:
        """Execute quote bundle"""

        if self.data.state != BridgeManagerState.QUOTE_BUNDLE_UP_TO_DATE:
            raise RuntimeError(
                "[BRIDGE MANAGER] You must retrieve a valid quote first."
            )

        if self.data.last_requested_quote_bundle["id"] != quote_bundle_id:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Id {quote_bundle_id} does not match latest requested quote bundle id {self.data.last_requested_quote_bundle['id']}."
            )

        from_ = self.data.last_requested_quote_bundle["from"]
        to = self.data.last_requested_quote_bundle["to"]

        reqs = self.bridge_refill_requirements(from_, to)

        if reqs["is_refill_required"]:
            raise RuntimeError(
                f"[BRIDGE MANAGER] Refill requirements not satisfied for quote bundle id {quote_bundle_id}."
            )

        for _, quote in self.data.last_requested_quote_bundle["quotes"].items():
            self.bridge.execute_quote(quote)

        print("[BRIDGE MANAGER] Executing quotes")
