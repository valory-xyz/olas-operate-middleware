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
