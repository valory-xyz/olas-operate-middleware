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
"""Bridge provider."""


import enum
import logging
import time
import typing as t
import uuid
from abc import abstractmethod
from dataclasses import dataclass

from aea.helpers.logging import setup_logger

from operate.operate_types import Chain
from operate.resource import LocalResource
from operate.wallet.master import MasterWalletManager


DEFAULT_MAX_QUOTE_RETRIES = 3
DEFAULT_QUOTE_VALIDITY_PERIOD = 3 * 60
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
