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

from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import get_target_chain_asset_address
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.services.manage import get_assets_balances
from operate.wallet.master import MasterWalletManager


DEFAULT_MAX_RETRIES = 3
BRIDGE_PATH = "bridge"
QUOTE_VALIDITY_PERIOD = 3 * 60


class Bridge:
    """Abstract Bridge"""

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

                    quotes[quote["id"]] = quote

        return quotes

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
        return None

    def get_from_token(self, quote: dict) -> int:
        """Get the from_token of a quote"""
        return quote["action"]["fromToken"]["address"]

    def get_from_amount(self, quote: dict) -> int:
        """Get the from_amount of a quote"""
        return int(quote["action"]["fromAmount"])

    def get_transaction_value(self, quote: dict) -> int:
        """Get the transaction value to execute a quote"""
        return int(quote["transactionRequest"]["value"], 16)


class BridgeManagerState(Enum):
    """BridgeManagerState"""

    QUOTE_BUNDLE_NOT_REQUESTED = 0
    QUOTE_BUNDLE_REQUESTED = 1


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
    ) -> None:
        """Initialize bridge manager."""
        self.path = path
        self.wallet_manager = wallet_manager
        self.logger = logger or setup_logger(name="operate.master_wallet_manager")
        self.bridge = bridge or LiFiBridge()
        self.path.mkdir(exist_ok=True)

        # TODO Migrate to LocalResource
        data_file = path / BridgeManagerData._file
        if not data_file.exists():
            data = BridgeManagerData(path=path)
            data.store()
        # End migrate

        self.data = BridgeManagerData.load(path)

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

    def bridge_refill_requirements(self, from_: dict, to: dict) -> dict:
        """Get bridge refill requirements."""

        if not isinstance(from_, dict) or len(from_) != 1:
            raise ValueError(
                f"[BRIDGE MANAGER] Invalid 'from_' input: Must contain exactly one chain mapping. {from_=}"
            )

        from_chain, from_address = next(iter(from_.items()))
        from_chain = Chain(from_chain)

        wallet = self.wallet_manager.load(from_chain.ledger_type)

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

        bridge = self.bridge

        quote_bundle = self.data.last_requested_quote_bundle
        now = int(time.time())

        refresh_quote_bundle = (
            not quote_bundle
            or now > quote_bundle.get("expiration_timestamp", 0)
            or DeepDiff(quote_bundle.get("from", {}), from_)
            or DeepDiff(quote_bundle.get("to", {}), to)
        )

        if refresh_quote_bundle:
            self.logger.info("[BRIDGE MANAGER] Requesting new quote bundle.")
            quote_bundle = {}
            quote_bundle["id"] = f"{uuid.uuid4()}"
            quote_bundle["timestamp"] = now
            quote_bundle["expiration_timestamp"] = now + QUOTE_VALIDITY_PERIOD
            quote_bundle["quotes"] = {}
            quote_bundle["from"] = from_
            quote_bundle["to"] = to
            quote_bundle["from_safe"] = from_safe
            quote_bundle["quotes"] = bridge.get_quotes(
                from_chain=from_chain, from_address=from_address, to=to
            )
            quote_bundle["bridge_requirements"] = bridge.get_bridge_requirements(
                quote_bundle["quotes"]
            )
            self.data.last_requested_quote_bundle = quote_bundle

        self.data.state = BridgeManagerState.QUOTE_BUNDLE_REQUESTED
        self.data.store()

        balances = get_assets_balances(
            ledger_api=wallet.ledger_api(chain=from_chain),
            addresses={from_address},
            asset_addresses={ZERO_ADDRESS}
            | self._get_from_tokens(from_chain=from_chain, to=to),
            raise_on_invalid_address=False,
        )

        bridge_refill_requirements = {}
        for from_token, amount in quote_bundle["bridge_requirements"].items():
            bridge_refill_requirements[from_token] = max(
                amount - balances[from_address][from_token], 0
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
        }
