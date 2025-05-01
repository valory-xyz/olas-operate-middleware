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
import typing as t
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from aea.helpers.logging import setup_logger
from deepdiff import DeepDiff

from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequest,
    BridgeRequestBundle,
)
from operate.bridge.providers.lifi_bridge_provider import LiFiBridgeProvider
from operate.constants import ZERO_ADDRESS
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.services.manage import get_assets_balances
from operate.wallet.master import MasterWalletManager


DEFAULT_QUOTE_VALIDITY_PERIOD = 3 * 60
EXECUTED_BUNDLES_PATH = "executed"
BRIDGE_REQUEST_BUNDLE_PREFIX = "br-"


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

        requirements = self.bridge_refill_requirements(bundle.requests_params)
        self.data.last_requested_bundle = None
        bundle_path = self.path / EXECUTED_BUNDLES_PATH / f"{bundle.id}.json"
        bundle.path = bundle_path
        bundle.store()

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
