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
import typing as t
import uuid
from abc import abstractmethod
from dataclasses import dataclass

from aea.helpers.logging import setup_logger

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
    bridge_provider_id: str
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

    @classmethod
    def id(cls) -> str:
        """Get the id of the bridge provider."""
        return f"{cls.__module__}.{cls.__qualname__}"

    def description(self) -> str:
        """Get a human-readable description of the bridge provider."""
        return self.__class__.__name__

    def _validate(self, bridge_request: BridgeRequest) -> None:
        """Validate the bridge request."""
        if bridge_request.bridge_provider_id != self.id():
            raise ValueError(
                f"Bridge request provider id {bridge_request.bridge_provider_id} does not match the bridge provider id {self.id()}"
            )

    def create_request(self, params: t.Dict) -> BridgeRequest:
        """Create a bridge request."""
        if "from" not in params or "to" not in params:
            raise ValueError(
                "Invalid input: All requests must contain exactly one 'from' and one 'to' sender."
            )

        from_ = params["from"]
        to = params["to"]

        if (
            not isinstance(from_, t.Dict)
            or "chain" not in from_
            or "address" not in from_
            or "token" not in from_
        ):
            raise ValueError(
                "Invalid input: 'from' must contain 'chain', 'address', and 'token'."
            )

        if (
            not isinstance(to, t.Dict)
            or "chain" not in to
            or "address" not in to
            or "token" not in to
            or "amount" not in to
        ):
            raise ValueError(
                "Invalid input: 'to' must contain 'chain', 'address', 'token', and 'amount'."
            )

        return BridgeRequest(
            params=params,
            bridge_provider_id=self.id(),
        )

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
