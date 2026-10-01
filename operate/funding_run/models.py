# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Funding run persisted models."""

import enum
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

from operate.bridge.providers.provider import ProviderRequest
from operate.resource import LocalResource
from operate.serialization import BigInt

FUNDING_RUN_PREFIX = "fr-"
ACTIVE_POINTER_FILE = "active.json"


class FundingRunMode(str, enum.Enum):
    """What the run's target is."""

    ONBOARD = "onboard"  # the service's net shortfall
    DEPOSIT = "deposit"  # user-entered amounts to add to the Pearl Wallet
    SIGNER_GAS = "signer_gas"  # the Master EOA native reserve

    def __str__(self) -> str:
        """__str__"""
        return self.value


class FundingRunStatus(str, enum.Enum):
    """Run lifecycle."""

    AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
    QUOTE_FAILED = "QUOTE_FAILED"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    def __str__(self) -> str:
        """__str__"""
        return self.value

    @property
    def is_terminal(self) -> bool:
        """Whether the run can no longer change (bar hidden delegation clearing)."""
        return self in (FundingRunStatus.COMPLETED, FundingRunStatus.CANCELLED)


class FundingStepKind(str, enum.Enum):
    """Step kinds, in execution order."""

    RECEIVE = "RECEIVE"
    BRIDGE = "BRIDGE"
    NATIVE = "NATIVE"
    SWAP = "SWAP"
    SAFE_AND_TRANSFER = "SAFE_AND_TRANSFER"
    CLEAR_DELEGATION = "CLEAR_DELEGATION"

    def __str__(self) -> str:
        """__str__"""
        return self.value


class FundingStepStatus(str, enum.Enum):
    """Step lifecycle."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"

    def __str__(self) -> str:
        """__str__"""
        return self.value


@dataclass
class FundingRunStep(LocalResource):  # pylint: disable=too-many-instance-attributes
    """One entry of the run's step log."""

    id: str
    kind: FundingStepKind
    status: FundingStepStatus
    visible: bool
    token: t.Optional[str] = None
    amount: t.Optional[BigInt] = None
    # ProviderRequest ids this step tracks (a source leg can hold several).
    request_ids: t.List[str] = field(default_factory=list)
    tx_hash: t.Optional[str] = None
    explorer_link: t.Optional[str] = None
    message: t.Optional[str] = None
    started_at: t.Optional[int] = None
    finished_at: t.Optional[int] = None
    eta_seconds: t.Optional[int] = None
    is_slow: t.Optional[bool] = None


@dataclass
class FundingRun(LocalResource):  # pylint: disable=too-many-instance-attributes
    """A persisted, resumable funding run."""

    path: Path
    id: str
    mode: FundingRunMode
    status: FundingRunStatus
    source_chain: str
    source_token: str
    destination_chain: str
    created_at: int
    service_config_id: t.Optional[str] = None
    backup_owner: t.Optional[str] = None
    gross_targets: t.Dict[str, BigInt] = field(default_factory=dict)
    net_targets: t.Dict[str, BigInt] = field(default_factory=dict)
    # Frozen plan: the source leg (carrier, native and the delegation-clearing
    # reserve requests) and one swap per remaining target token.
    source_requests: t.List[ProviderRequest] = field(default_factory=list)
    swap_requests: t.List[ProviderRequest] = field(default_factory=list)
    required_amount: t.Optional[BigInt] = None
    received_amount: BigInt = field(default_factory=lambda: BigInt(0))
    # Same-chain runs only: the Master EOA source-token balance at creation
    # that the targets already netted. Only growth above it is "received".
    receive_baseline: t.Optional[BigInt] = None
    eta_seconds: t.Optional[int] = None
    quoted_at: t.Optional[int] = None
    quote_message: t.Optional[str] = None
    steps: t.List[FundingRunStep] = field(default_factory=list)
    error: t.Optional[t.Dict[str, str]] = None
    user_op_hash: t.Optional[str] = None
    # EntryPoint nonce of user_op_hash: once used, that UserOp can never land.
    user_op_nonce: t.Optional[int] = None
    # Block the UserOp was built at: its EntryPoint event cannot be earlier.
    user_op_block: t.Optional[int] = None
    source_tx_hash: t.Optional[str] = None
    # Stored before a native-source request is sent: if the process stops
    # mid-send, the request is reported as interrupted instead of resent.
    sending_request_ids: t.List[str] = field(default_factory=list)
    # EIP-7702 bookkeeping, both authorizations are bound to source_chain.
    delegation_auth_nonce: t.Optional[int] = None
    clear_delegation_tx_hash: t.Optional[str] = None
    delegation_cleared: t.Optional[bool] = None
    finished_at: t.Optional[int] = None
    version: int = 1

    def step(self, step_id: str) -> FundingRunStep:
        """Get a step by id."""
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def requests_of(self, step: FundingRunStep) -> t.List[ProviderRequest]:
        """The provider requests a step tracks."""
        by_id = {r.id: r for r in self.source_requests + self.swap_requests}
        return [by_id[request_id] for request_id in step.request_ids]


@dataclass
class FundingRunPointer(LocalResource):
    """`active.json`: which run is live, and which ran last."""

    path: Path
    version: int = 1
    active_run_id: t.Optional[str] = None
    last_run_id: t.Optional[str] = None
    # Terminal runs whose delegation clearing is still unconfirmed.
    pending_clear_run_ids: t.List[str] = field(default_factory=list)

    _file = ACTIVE_POINTER_FILE
