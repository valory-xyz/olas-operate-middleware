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
"""Balancer V2 same-chain swap provider."""

import time
import typing as t

from web3 import Web3
from web3.exceptions import ContractLogicError, TransactionNotFound

from operate.bridge.providers.provider import (
    MESSAGE_EXECUTION_FAILED_REVERTED,
    Provider,
    ProviderRequest,
    ProviderRequestStatus,
    QuoteData,
)
from operate.constants import BRIDGE_GAS_ESTIMATE_MULTIPLIER, ZERO_ADDRESS
from operate.ledger import update_tx_with_gas_estimate, update_tx_with_gas_pricing
from operate.ledger.profiles import EXPLORER_URL, OLAS
from operate.operate_types import Chain

BALANCER_VAULT = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
#: (chain, token out) -> pool id of a pool bought into with native: it is
#: sent as value, and the Vault wraps it and refunds what the swap leaves.
BALANCER_POOLS: t.Dict[t.Tuple[Chain, str], str] = {
    (chain, Web3.to_checksum_address(token_out)): pool_id
    for (chain, token_out), pool_id in {
        (
            Chain.GNOSIS,
            OLAS[Chain.GNOSIS],
        ): "0x79c872ed3acb3fc5770dd8a0cd9cd5db3b3ac985000200000000000000000067",
    }.items()
}
SWAP_KIND_GIVEN_OUT = 1
SLIPPAGE_BPS = 100
SWAP_GAS = 250_000
SWAP_ETA = 30
SWAP_DEADLINE = 3600

_FUNDS = {
    "name": "funds",
    "type": "tuple",
    "components": [
        {"name": "sender", "type": "address"},
        {"name": "fromInternalBalance", "type": "bool"},
        {"name": "recipient", "type": "address"},
        {"name": "toInternalBalance", "type": "bool"},
    ],
}
_VAULT_ABI = [
    {
        "name": "queryBatchSwap",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "kind", "type": "uint8"},
            {
                "name": "swaps",
                "type": "tuple[]",
                "components": [
                    {"name": "poolId", "type": "bytes32"},
                    {"name": "assetInIndex", "type": "uint256"},
                    {"name": "assetOutIndex", "type": "uint256"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "userData", "type": "bytes"},
                ],
            },
            {"name": "assets", "type": "address[]"},
            _FUNDS,
        ],
        "outputs": [{"name": "assetDeltas", "type": "int256[]"}],
    },
    {
        "name": "swap",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "singleSwap",
                "type": "tuple",
                "components": [
                    {"name": "poolId", "type": "bytes32"},
                    {"name": "kind", "type": "uint8"},
                    {"name": "assetIn", "type": "address"},
                    {"name": "assetOut", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "userData", "type": "bytes"},
                ],
            },
            _FUNDS,
            {"name": "limit", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amountCalculated", "type": "uint256"}],
    },
]


def _pool_key(chain: Chain, token_out: str) -> t.Tuple[Chain, str]:
    return chain, Web3.to_checksum_address(token_out)


def has_native_pool(chain: Chain, token_out: str) -> bool:
    """Whether native on `chain` swaps into `token_out` through a configured pool."""
    return _pool_key(chain, token_out) in BALANCER_POOLS


class BalancerProvider(Provider):
    """Exact-output swaps through a single Balancer V2 pool."""

    def can_handle_request(self, params: t.Dict) -> bool:
        """Returns 'true' if the provider can handle a request for 'params'."""
        if not super().can_handle_request(params):
            return False
        return (
            params["from"]["chain"] == params["to"]["chain"]
            and Web3.to_checksum_address(params["from"]["token"]) == ZERO_ADDRESS
            and has_native_pool(Chain(params["from"]["chain"]), params["to"]["token"])
        )

    def description(self) -> str:
        """Get a human-readable description of the provider."""
        return "Balancer V2 swap provider."

    def quote(self, provider_request: ProviderRequest) -> None:
        """Update the request with the quote."""
        self._check_quotable(provider_request)

        params = provider_request.params
        to_amount = params["to"]["amount"]
        if to_amount == 0:
            self._set_zero_quote(provider_request)
            return

        start = time.time()
        pool_id = BALANCER_POOLS[
            _pool_key(Chain(params["from"]["chain"]), params["to"]["token"])
        ]
        vault = self._from_ledger_api(provider_request).api.eth.contract(
            address=BALANCER_VAULT, abi=_VAULT_ABI
        )
        try:
            amount_in = int(
                vault.functions.queryBatchSwap(
                    SWAP_KIND_GIVEN_OUT,
                    [(pool_id, 0, 1, to_amount, b"")],
                    [ZERO_ADDRESS, params["to"]["token"]],
                    (params["from"]["address"], False, params["to"]["address"], False),
                ).call()[0]
            )
            if amount_in <= 0:
                raise ValueError(f"Non-positive amount in {amount_in}.")
        except Exception as e:  # pylint: disable=broad-except
            self.logger.warning(
                f"[BALANCER PROVIDER] Quote failed for {provider_request.id}: {e}",
                exc_info=True,
            )
            provider_request.quote_data = self._failed_quote_data(start, str(e))
            provider_request.status = ProviderRequestStatus.QUOTE_FAILED
            return

        provider_request.quote_data = QuoteData(
            eta=SWAP_ETA,
            elapsed_time=time.time() - start,
            message=None,
            provider_data={
                "pool_id": pool_id,
                "amount_in": amount_in,
                "max_amount_in": amount_in * (10_000 + SLIPPAGE_BPS) // 10_000,
            },
            timestamp=int(time.time()),
        )
        provider_request.status = ProviderRequestStatus.QUOTE_DONE

    def _get_txs(
        self, provider_request: ProviderRequest, *args: t.Any, **kwargs: t.Any
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the quote."""
        params = provider_request.params
        if params["to"]["amount"] == 0:
            return []

        quote_data = provider_request.quote_data
        if not quote_data or not quote_data.provider_data:
            raise RuntimeError(
                f"Cannot get transactions for {provider_request.id}: quote data not present."
            )

        provider_data = quote_data.provider_data
        from_address = params["from"]["address"]
        max_amount_in = int(provider_data["max_amount_in"])
        from_ledger_api = self._from_ledger_api(provider_request)
        vault = from_ledger_api.api.eth.contract(address=BALANCER_VAULT, abi=_VAULT_ABI)
        data = vault.encode_abi(
            "swap",
            args=[
                (
                    provider_data["pool_id"],
                    SWAP_KIND_GIVEN_OUT,
                    ZERO_ADDRESS,
                    params["to"]["token"],
                    params["to"]["amount"],
                    b"",
                ),
                (from_address, False, params["to"]["address"], False),
                max_amount_in,
                int(time.time()) + SWAP_DEADLINE,
            ],
        )
        tx = {
            "from": from_address,
            "to": BALANCER_VAULT,
            "data": data,
            "value": max_amount_in,
            "chainId": Chain(params["from"]["chain"]).id,
            "gas": SWAP_GAS,
        }
        update_tx_with_gas_pricing(tx, from_ledger_api)
        update_tx_with_gas_estimate(tx, from_ledger_api, BRIDGE_GAS_ESTIMATE_MULTIPLIER)
        return [("swap_tx", tx)]

    def _precheck(
        self, provider_request: ProviderRequest, txs: t.List[t.Tuple[str, t.Dict]]
    ) -> t.Optional[str]:
        """Simulate the swap, so one that would revert is not sent."""
        # The gas estimate falls back to a preset limit, so it never catches a revert.
        w3 = self._from_ledger_api(provider_request).api
        for _, tx in txs:
            try:
                w3.eth.call({key: tx[key] for key in ("from", "to", "data", "value")})
            except ContractLogicError as e:
                self.logger.warning(
                    f"[BALANCER PROVIDER] Swap {provider_request.id} would revert: {e}"
                )
                return str(e)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.warning(
                    f"[BALANCER PROVIDER] Cannot simulate swap {provider_request.id}: {e}"
                )
        return None

    def _update_execution_status(self, provider_request: ProviderRequest) -> None:
        """Update the execution status."""
        pending = self._begin_status_update(provider_request)
        if pending is None:
            return
        execution_data, tx_hash = pending

        try:
            receipt = self._from_ledger_api(
                provider_request
            ).api.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            if self._bridge_tx_likely_failed(provider_request):
                provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
            return
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(
                f"[BALANCER PROVIDER] Failed to update status for request {provider_request.id}: {e}"
            )
            provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN
            if self._bridge_tx_likely_failed(provider_request):
                provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
            return

        if receipt["status"] != 1:
            execution_data.message = MESSAGE_EXECUTION_FAILED_REVERTED
            provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
            return
        execution_data.message = None
        execution_data.to_tx_hash = tx_hash
        provider_request.status = ProviderRequestStatus.EXECUTION_DONE

    def _get_explorer_link(self, provider_request: ProviderRequest) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        execution_data = provider_request.execution_data
        if not execution_data or not execution_data.from_tx_hash:
            return None
        chain = Chain(provider_request.params["from"]["chain"])
        return EXPLORER_URL[chain]["tx"].format(tx_hash=execution_data.from_tx_hash)
