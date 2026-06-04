# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""Gas-spike error handling utilities."""

import typing as t
from contextlib import contextmanager

from autonomy.chain.exceptions import ChainInteractionError

from operate.exceptions import InsufficientFundsException
from operate.ledger import is_gas_spike_error


@contextmanager
def wrap_gas_spike_as_insufficient_funds(chain: str, action: str) -> t.Iterator[None]:
    """Translate TxSettler gas-spike failures into InsufficientFundsException."""
    try:
        yield
    except (ValueError, ChainInteractionError) as exc:
        if is_gas_spike_error(str(exc)):
            raise InsufficientFundsException(
                f"Insufficient gas to {action}: {exc}", chain=chain
            ) from exc
        raise
