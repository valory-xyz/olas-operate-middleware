# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""Shared exception classes for the operate package."""

import typing as t

from autonomy.chain.exceptions import ChainInteractionError

from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS
from operate.operate_types import Chain


class InsufficientFundsException(Exception):
    """Insufficient funds exception carrying the chain where gas is missing."""

    def __init__(self, msg: str, chain: str) -> None:
        """Initialise with message and the chain where gas was insufficient."""
        super().__init__(msg, chain)
        self.chain = chain

    def __str__(self) -> str:
        """Return only the human-readable message, not the full args tuple."""
        return self.args[0]

    def to_error_fields(self) -> t.Dict:
        """Return structured error fields for merging into a JSONResponse body."""
        return {
            "error_code": "INSUFFICIENT_SIGNER_GAS",
            "chain": self.chain,
            "prefill_amount_wei": str(
                DEFAULT_EOA_TOPUPS[Chain(self.chain)][ZERO_ADDRESS]
            ),
        }


class ServicePackageDownloadError(Exception):
    """The service package could not be downloaded from the IPFS registry."""

    def to_error_fields(self) -> t.Dict:
        """Return structured error fields for merging into a JSONResponse body."""
        return {"error_code": "SERVICE_PACKAGE_DOWNLOAD_FAILED"}


class RecoveryModuleNotEnabledError(Exception):
    """The service Safe still lacks the recovery module, so it cannot be reused."""

    error_code: t.ClassVar[str] = "RECOVERY_MODULE_NOT_ENABLED"

    def to_error_fields(self) -> t.Dict:
        """Return structured error fields for merging into a JSONResponse body."""
        return {"error_code": self.error_code}


class SafeTransactionWouldRevertError(ChainInteractionError):
    """A Safe transaction was simulated as reverting, so it was not sent."""

    error_code: t.ClassVar[str] = "TRANSACTION_WOULD_REVERT"

    def to_error_fields(self) -> t.Dict:
        """Return structured error fields for merging into a JSONResponse body."""
        return {"error_code": self.error_code}


class AgentCouldNotEnableRecoveryModuleError(RecoveryModuleNotEnabledError):
    """The Agent EOA owns the service Safe and its enableModule failed."""

    error_code = "AGENT_COULD_NOT_ENABLE_RECOVERY_MODULE"


class RetiredStakingProgramError(Exception):
    """The staking program is retired."""

    error_code: t.ClassVar[str] = "RETIRED_STAKING_PROGRAM"

    def __init__(self, staking_program_id: str) -> None:
        """Initialize the error."""
        super().__init__(self.message_for(staking_program_id))
        self.staking_program_id = staking_program_id

    @staticmethod
    def message_for(staking_program_id: str) -> str:
        """Return the message, shared by ``str(e)`` and the response body."""
        return f"Staking program {staking_program_id} is retired."

    def to_response_body(self) -> t.Dict:
        """Return the full response body, `error` included, unlike `to_error_fields`."""
        return {
            "error": self.message_for(self.staking_program_id),
            "error_code": self.error_code,
            "staking_program_id": self.staking_program_id,
        }
