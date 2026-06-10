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

from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EIP1559, get_default_gas_strategy
from autonomy.chain.exceptions import ChainInteractionError

from operate.exceptions import InsufficientFundsException
from operate.ledger import is_gas_spike_error
from operate.operate_types import Chain

# Assumed gas consumption of the cheapest realistic middleware transaction,
# used as the pre-flight affordability floor (signer must hold at least
# gas_price * MIN_GAS_UNITS). A plain transfer costs 21k gas, but the flows
# guarded here are Safe execTransaction calls (~60-120k), ERC20 transfers
# (~50-65k), Safe creation (~280k) and bridge txs (>100k). 100k is kept
# deliberately low to avoid false positives: it only needs to catch
# effectively-zero balances instantly; marginal balances still fail in
# TxSettler and are translated via the gas-spike message path. No upstream
# constant exists for this — aea-ledger-ethereum always estimates gas live
# and defines price constants only.
MIN_GAS_UNITS = 100_000


def _fallback_gas_price(chain: str) -> int:
    """Chain-aware fallback gas price, mirroring EthereumApi's own fallback estimate."""
    strategy = get_default_gas_strategy(Chain(chain).id)
    return strategy[EIP1559]["fallback_estimate"]["maxFeePerGas"]


def _preflight_signer_gas(ledger_api: LedgerApi, address: str, chain: str) -> None:
    """Raise InsufficientFundsException immediately if the signer EOA can't cover gas."""
    try:
        balance = ledger_api.get_balance(address)
        if not isinstance(balance, int):
            return
        if balance >= _fallback_gas_price(chain) * MIN_GAS_UNITS:
            # Comfortably funded under the chain's conservative fallback price;
            # skip the gas-pricing RPC entirely.
            return
        # Gray zone: confirm against live pricing. Nodes validate balance
        # against maxFeePerGas * gas_limit when accepting an EIP-1559 tx,
        # so maxFeePerGas is the correct price to threshold on.
        gas_pricing = ledger_api.try_get_gas_pricing()
        if gas_pricing is not None:
            gas_price = gas_pricing.get("maxFeePerGas") or gas_pricing.get("gasPrice")
        else:
            gas_price = None
        if gas_price is None:
            gas_price = _fallback_gas_price(chain)
        threshold = gas_price * MIN_GAS_UNITS
        if balance < threshold:
            raise InsufficientFundsException(
                f"Signer {address} has insufficient gas on {chain}: "
                f"balance {balance} wei < required {threshold} wei.",
                chain=chain,
            )
    except InsufficientFundsException:
        raise
    except Exception:  # pylint: disable=broad-except
        return  # swallow RPC errors — let TxSettler handle them naturally


@contextmanager
def wrap_gas_spike_as_insufficient_funds(
    chain: str,
    action: str,
    ledger_api: LedgerApi,
    signer_address: str,
) -> t.Iterator[None]:
    """Translate TxSettler gas-spike failures into InsufficientFundsException.

    Performs a pre-flight gas check on *signer_address* before entering the
    guarded block, raising InsufficientFundsException immediately when the
    signer cannot cover gas for even a minimal transaction.
    """
    _preflight_signer_gas(ledger_api, signer_address, chain)
    try:
        yield
    except (ValueError, ChainInteractionError) as exc:
        if is_gas_spike_error(str(exc)):
            raise InsufficientFundsException(
                f"Insufficient gas to {action}: {exc}", chain=chain
            ) from exc
        raise
