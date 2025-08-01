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

from deepdiff import DeepDiff
from web3 import Web3

from operate.bridge.providers.lifi_provider import LiFiProvider
from operate.bridge.providers.native_bridge_provider import (
    NativeBridgeProvider,
    OmnibridgeContractAdaptor,
    OptimismContractAdaptor,
)
from operate.bridge.providers.provider import Provider, ProviderRequest
from operate.bridge.providers.relay_provider import RelayProvider
from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import USDC
from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.services.manage import get_assets_balances
from operate.utils import merge_sum_dicts, subtract_dicts
from operate.wallet.master import MasterWalletManager


DEFAULT_BUNDLE_VALIDITY_PERIOD = 3 * 60
EXECUTED_BUNDLES_PATH = "executed"
BRIDGE_REQUEST_BUNDLE_PREFIX = "rb-"

LIFI_PROVIDER_ID = "lifi-provider"
RELAY_PROVIDER_ID = "relay-provider"

NATIVE_BRIDGE_PROVIDER_CONFIGS: t.Dict[str, t.Any] = {
    "native-ethereum-to-base": {
        "from_chain": "ethereum",
        "from_bridge": "0x3154Cf16ccdb4C6d922629664174b904d80F2C35",
        "to_chain": "base",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "bridge_eta": 300,
        "bridge_contract_adaptor_class": OptimismContractAdaptor,
    },
    "native-ethereum-to-mode": {
        "from_chain": "ethereum",
        "from_bridge": "0x735aDBbE72226BD52e818E7181953f42E3b0FF21",
        "to_chain": "mode",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "bridge_eta": 300,
        "bridge_contract_adaptor_class": OptimismContractAdaptor,
    },
    "native-ethereum-to-optimism": {
        "from_chain": "ethereum",
        "from_bridge": "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1",
        "to_chain": "optimism",
        "to_bridge": "0x4200000000000000000000000000000000000010",
        "bridge_eta": 300,
        "bridge_contract_adaptor_class": OptimismContractAdaptor,
    },
    "native-ethereum-to-gnosis": {
        "from_chain": "ethereum",
        "from_bridge": "0x88ad09518695c6c3712AC10a214bE5109a655671",
        "to_chain": "gnosis",
        "to_bridge": "0xf6A78083ca3e2a662D6dd1703c939c8aCE2e268d",
        "bridge_eta": 1800,
        "bridge_contract_adaptor_class": OmnibridgeContractAdaptor,
    },
}


ROUTES = {
    (
        Chain.ETHEREUM,  # from_chain
        USDC[Chain.ETHEREUM],  # from_token
        Chain.OPTIMISM,  # to_chain
        USDC[Chain.OPTIMISM],  # to_token
    ): LIFI_PROVIDER_ID,
    (
        Chain.ETHEREUM,  # from_chain
        USDC[Chain.ETHEREUM],  # from_token
        Chain.BASE,  # to_chain
        USDC[Chain.BASE],  # to_token
    ): LIFI_PROVIDER_ID,
    (Chain.ETHEREUM, ZERO_ADDRESS, Chain.GNOSIS, ZERO_ADDRESS): RELAY_PROVIDER_ID,
}


@dataclass
class ProviderRequestBundle(LocalResource):
    """ProviderRequestBundle"""

    requests_params: t.List[t.Dict]
    provider_requests: t.List[ProviderRequest]
    timestamp: int
    id: str

    def get_from_chains(self) -> set[Chain]:
        """Get 'from' chains."""
        return {
            Chain(request.params["from"]["chain"]) for request in self.provider_requests
        }

    def get_from_addresses(self, chain: Chain) -> set[str]:
        """Get 'from' addresses."""
        chain_str = chain.value
        return {
            request.params["from"]["address"]
            for request in self.provider_requests
            if request.params["from"]["chain"] == chain_str
        }

    def get_from_tokens(self, chain: Chain) -> set[str]:
        """Get 'from' tokens."""
        chain_str = chain.value
        return {
            request.params["from"]["token"]
            for request in self.provider_requests
            if request.params["from"]["chain"] == chain_str
        }


@dataclass
class BridgeManagerData(LocalResource):
    """BridgeManagerData"""

    path: Path
    version: int = 1
    last_requested_bundle: t.Optional[ProviderRequestBundle] = None
    last_executed_bundle_id: t.Optional[str] = None

    _file = "bridge.json"

    # TODO Migrate to LocalResource?
    # It can be inconvenient that all local resources create an empty resource
    # if the file is corrupted. For example, if a service configuration is
    # corrupted, we might want to halt execution, because otherwise, the application
    # could continue as if the user is creating a service from scratch.
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

    def __init__(
        self,
        path: Path,
        wallet_manager: MasterWalletManager,
        logger: logging.Logger,
        quote_validity_period: int = DEFAULT_BUNDLE_VALIDITY_PERIOD,
    ) -> None:
        """Initialize bridge manager."""
        self.path = path
        self.wallet_manager = wallet_manager
        self.logger = logger
        self.quote_validity_period = quote_validity_period
        self.path.mkdir(exist_ok=True)
        (self.path / EXECUTED_BUNDLES_PATH).mkdir(exist_ok=True)
        self.data: BridgeManagerData = cast(
            BridgeManagerData, BridgeManagerData.load(path)
        )
        self._native_bridge_providers = {
            provider_id: NativeBridgeProvider(
                config["bridge_contract_adaptor_class"](
                    from_chain=config["from_chain"],
                    to_chain=config["to_chain"],
                    from_bridge=config["from_bridge"],
                    to_bridge=config["to_bridge"],
                    bridge_eta=config["bridge_eta"],
                ),
                provider_id,
                wallet_manager,
                logger,
            )
            for provider_id, config in NATIVE_BRIDGE_PROVIDER_CONFIGS.items()
        }

        self._providers: t.Dict[str, Provider] = {}
        self._providers.update(self._native_bridge_providers)
        self._providers[LIFI_PROVIDER_ID] = LiFiProvider(
            provider_id=LIFI_PROVIDER_ID,
            wallet_manager=wallet_manager,
            logger=logger,
        )
        self._providers[RELAY_PROVIDER_ID] = RelayProvider(
            provider_id=RELAY_PROVIDER_ID,
            wallet_manager=wallet_manager,
            logger=logger,
        )

    def _store_data(self) -> None:
        self.logger.info("[BRIDGE MANAGER] Storing data to file.")
        self.data.store()

    def _get_updated_bundle(
        self, requests_params: t.List[t.Dict], force_update: bool
    ) -> ProviderRequestBundle:
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
            self.quote_bundle(bundle)
            self._store_data()
        elif now > bundle.timestamp + self.quote_validity_period:
            self.logger.info("[BRIDGE MANAGER] Bundle expired.")
            self.quote_bundle(bundle)
            self._store_data()

        if not bundle or create_new_bundle:
            self.logger.info("[BRIDGE MANAGER] Creating new bridge request bundle.")

            provider_requests = []
            for params in requests_params:
                for provider in self._native_bridge_providers.values():
                    if provider.can_handle_request(params):
                        provider_requests.append(provider.create_request(params=params))
                        break
                else:
                    provider_id = ROUTES.get(
                        (
                            Chain(params["from"]["chain"]),
                            params["from"]["token"],
                            Chain(params["to"]["chain"]),
                            params["to"]["token"],
                        ),
                        RELAY_PROVIDER_ID,
                    )

                    provider_requests.append(
                        self._providers[provider_id].create_request(params=params)
                    )

            bundle = ProviderRequestBundle(
                id=f"{BRIDGE_REQUEST_BUNDLE_PREFIX}{uuid.uuid4()}",
                requests_params=requests_params,
                provider_requests=provider_requests,
                timestamp=now,
            )

            self.data.last_requested_bundle = bundle
            self.quote_bundle(bundle)
            self._store_data()

        return bundle

    def _sanitize(self, requests_params: t.List) -> None:
        """Sanitize quote requests."""
        w3 = Web3()
        for params in requests_params:
            params["from"]["address"] = w3.to_checksum_address(
                params["from"]["address"]
            )
            params["from"]["token"] = w3.to_checksum_address(params["from"]["token"])
            params["to"]["address"] = w3.to_checksum_address(params["to"]["address"])
            params["to"]["token"] = w3.to_checksum_address(params["to"]["token"])
            params["to"]["amount"] = int(params["to"]["amount"])

    def _raise_if_invalid(self, requests_params: t.List) -> None:
        """Preprocess quote requests."""

        for params in requests_params:
            from_chain = params["from"]["chain"]
            from_address = params["from"]["address"]

            wallet = self.wallet_manager.load(Chain(from_chain).ledger_type)
            wallet_address = wallet.address
            safe_address = wallet.safes.get(Chain(from_chain))

            if from_address is None or not (
                from_address == wallet_address or from_address == safe_address
            ):
                raise ValueError(
                    f"Invalid input: 'from' address {from_address} does not match Master EOA nor Master Safe on chain {Chain(from_chain).name}."
                )

    def bridge_refill_requirements(
        self, requests_params: t.List[t.Dict], force_update: bool = False
    ) -> t.Dict:
        """Get bridge refill requirements."""
        self._sanitize(requests_params)
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

        bridge_total_requirements = self.bridge_total_requirements(bundle)

        bridge_refill_requirements = cast(
            t.Dict[str, t.Dict[str, t.Dict[str, int]]],
            subtract_dicts(bridge_total_requirements, balances),
        )

        is_refill_required = any(
            amount > 0
            for from_addresses in bridge_refill_requirements.values()
            for from_tokens in from_addresses.values()
            for amount in from_tokens.values()
        )

        status_json = self.get_status_json(bundle.id)
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
        self.data.last_executed_bundle_id = bundle_id
        bundle_path = self.path / EXECUTED_BUNDLES_PATH / f"{bundle.id}.json"
        bundle.path = bundle_path
        self._store_data()
        bundle.store()

        if requirements["is_refill_required"]:
            self.logger.warning(
                f"[BRIDGE MANAGER] Refill requirements not satisfied for bundle id {bundle_id}."
            )

        self.logger.info("[BRIDGE MANAGER] Executing quotes.")

        for request in bundle.provider_requests:
            provider = self._providers[request.provider_id]
            provider.execute(request)
            self._store_data()

        self._store_data()
        bundle.store()
        self.logger.info(f"[BRIDGE MANAGER] Bundle id {bundle_id} executed.")
        return self.get_status_json(bundle_id)

    def get_status_json(self, bundle_id: str) -> t.Dict:
        """Get execution status of bundle."""
        bundle = self.data.last_requested_bundle

        if bundle is not None and bundle.id == bundle_id:
            pass
        else:
            bundle_path = self.path / EXECUTED_BUNDLES_PATH / f"{bundle_id}.json"
            if bundle_path.exists():
                bundle = cast(
                    ProviderRequestBundle, ProviderRequestBundle.load(bundle_path)
                )
                bundle.path = bundle_path  # TODO backport to resource.py ?
            else:
                raise FileNotFoundError(f"Bundle with ID {bundle_id} does not exist.")

        initial_status = [request.status for request in bundle.provider_requests]

        provider_request_status = []
        for request in bundle.provider_requests:
            provider = self._providers[request.provider_id]
            provider_request_status.append(provider.status_json(request))

        updated_status = [request.status for request in bundle.provider_requests]

        if initial_status != updated_status and bundle.path is not None:
            bundle.store()

        return {
            "id": bundle.id,
            "bridge_request_status": provider_request_status,
        }

    def bridge_total_requirements(self, bundle: ProviderRequestBundle) -> t.Dict:
        """Sum bridge requirements."""
        requirements = []
        for provider_request in bundle.provider_requests:
            provider = self._providers[provider_request.provider_id]
            requirements.append(provider.requirements(provider_request))

        return merge_sum_dicts(*requirements)

    def quote_bundle(self, bundle: ProviderRequestBundle) -> None:
        """Update the bundle with the quotes."""
        for provider_request in bundle.provider_requests:
            provider = self._providers[provider_request.provider_id]
            provider.quote(provider_request)
        bundle.timestamp = int(time.time())

    def last_executed_bundle_id(self) -> t.Optional[str]:
        """Get the last executed bundle id."""
        return self.data.last_executed_bundle_id
