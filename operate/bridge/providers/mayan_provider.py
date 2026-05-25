#!/usr/bin/env python3
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
"""Mayan bridge provider."""

import json
import math
import secrets
import time
import typing as t
from http import HTTPStatus
from pathlib import Path

import requests
from web3 import Web3

from operate.bridge.providers.provider import (
    DEFAULT_MAX_QUOTE_RETRIES,
    MESSAGE_EXECUTION_FAILED,
    MESSAGE_QUOTE_ZERO,
    Provider,
    ProviderRequest,
    ProviderRequestStatus,
    QuoteData,
)
from operate.constants import BRIDGE_GAS_ESTIMATE_MULTIPLIER, ZERO_ADDRESS
from operate.ledger import update_tx_with_gas_estimate, update_tx_with_gas_pricing
from operate.ledger.profiles import WRAPPED_NATIVE_ASSET
from operate.operate_types import Chain

MAYAN_QUOTE_API_URL = "https://price-api.mayan.finance/v3/quote"
MAYAN_EXPLORER_API_URL = "https://explorer-api.mayan.finance/v3/swap/trx"
MAYAN_EXPLORER_URL = "https://explorer.mayan.finance/tx"

MAYAN_FORWARDER_ADDRESS = "0x337685fdaB40D39bd02028545a4FfA7D287cC3E2"
MAYAN_SLIPPAGE_BUFFER = 0.02  # 200 bps over-delivery buffer

# Wormhole chain IDs for EVM chains
WORMHOLE_CHAIN_IDS: t.Dict[str, int] = {
    Chain.ETHEREUM.value: 2,
    Chain.POLYGON.value: 5,
    Chain.ARBITRUM_ONE.value: 23,
    Chain.OPTIMISM.value: 24,
    Chain.BASE.value: 30,
}

# Mayan API chain names (lowercase strings matching their API)
MAYAN_CHAIN_NAMES: t.Dict[str, str] = {
    Chain.ETHEREUM.value: "ethereum",
    Chain.POLYGON.value: "polygon",
    Chain.OPTIMISM.value: "optimism",
    Chain.BASE.value: "base",
    Chain.ARBITRUM_ONE.value: "arbitrum",
}

# Default gas estimates per chain when the API/estimation fails
MAYAN_DEFAULT_GAS: t.Dict[Chain, t.Dict[str, int]] = {
    Chain.ETHEREUM: {"approve": 50_000, "forwarder": 350_000},
    Chain.BASE: {"approve": 50_000, "forwarder": 350_000},
    Chain.OPTIMISM: {"approve": 50_000, "forwarder": 350_000},
    Chain.POLYGON: {"approve": 50_000, "forwarder": 350_000},
    Chain.ARBITRUM_ONE: {"approve": 50_000, "forwarder": 350_000},
}

_ABI_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "contracts"


def _load_abi(contract_dir: str, contract_name: str) -> t.List[t.Dict]:
    """Load contract ABI from the data/contracts directory."""
    abi_path = _ABI_DIR / contract_dir / "build" / f"{contract_name}.json"
    with open(abi_path, "r", encoding="utf-8") as f:
        return json.load(f)["abi"]


class MayanProvider(Provider):
    """Mayan bridge provider.

    Quotes via the Mayan REST Quote API, encodes EVM transactions via
    Python web3.py ABI encoding of the Mayan Forwarder contract, and
    polls the Mayan Explorer API for execution status.
    """

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        """Initialize the Mayan provider."""
        super().__init__(*args, **kwargs)
        self._w3 = Web3()
        self._forwarder_abi = _load_abi("mayan_forwarder", "MayanForwarder")
        self._swift_abi = _load_abi("mayan_swift", "MayanSwift")
        self._forwarder_contract = self._w3.eth.contract(
            address=self._w3.to_checksum_address(MAYAN_FORWARDER_ADDRESS),
            abi=self._forwarder_abi,
        )
        self._swift_contract = self._w3.eth.contract(
            abi=self._swift_abi,
        )

    def description(self) -> str:
        """Get a human-readable description of the provider."""
        return "Mayan Protocol https://mayan.finance/"

    def quote(  # pylint: disable=too-many-locals,too-many-statements,too-many-branches
        self, provider_request: ProviderRequest
    ) -> None:
        """Update the request with the quote from Mayan Quote API.

        Uses a two-step approach:
        1. Probe: call Quote API with amountIn = to.amount to discover exchange rate
        2. Scale: compute amountIn_final with slippage buffer, re-quote, verify over-delivery
        """
        self._validate(provider_request)

        if provider_request.status not in (
            ProviderRequestStatus.CREATED,
            ProviderRequestStatus.QUOTE_DONE,
            ProviderRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"Cannot quote request {provider_request.id} "
                f"with status {provider_request.status}."
            )

        if provider_request.execution_data:
            raise RuntimeError(
                f"Cannot quote request {provider_request.id}: "
                "execution already present."
            )

        from_chain = provider_request.params["from"]["chain"]
        from_token = provider_request.params["from"]["token"]
        to_chain = provider_request.params["to"]["chain"]
        to_token = provider_request.params["to"]["token"]
        to_amount = provider_request.params["to"]["amount"]

        if to_amount == 0:
            self.logger.info(f"[MAYAN PROVIDER] {MESSAGE_QUOTE_ZERO}")
            quote_data = QuoteData(
                eta=0,
                elapsed_time=0,
                message=MESSAGE_QUOTE_ZERO,
                provider_data=None,
                timestamp=int(time.time()),
            )
            provider_request.quote_data = quote_data
            provider_request.status = ProviderRequestStatus.QUOTE_DONE
            return

        from_chain_name = MAYAN_CHAIN_NAMES.get(from_chain)
        to_chain_name = MAYAN_CHAIN_NAMES.get(to_chain)

        if not from_chain_name or not to_chain_name:
            self.logger.warning(
                f"[MAYAN PROVIDER] Unsupported chain pair: "
                f"{from_chain} -> {to_chain}."
            )
            quote_data = QuoteData(
                eta=None,
                elapsed_time=0,
                message=f"Unsupported chain: {from_chain} or {to_chain}",
                provider_data=None,
                timestamp=int(time.time()),
            )
            provider_request.quote_data = quote_data
            provider_request.status = ProviderRequestStatus.QUOTE_FAILED
            return

        # Use native null address for Mayan when from_token is ZERO_ADDRESS
        mayan_from_token = (
            "0x0000000000000000000000000000000000000000"
            if from_token == ZERO_ADDRESS
            else from_token
        )
        mayan_to_token = (
            "0x0000000000000000000000000000000000000000"
            if to_token == ZERO_ADDRESS
            else to_token
        )

        for attempt in range(1, DEFAULT_MAX_QUOTE_RETRIES + 1):
            start = time.time()
            try:
                # Step 1 — Probe quote to discover exchange rate
                probe_response = self._call_quote_api(
                    from_chain=from_chain_name,
                    from_token=mayan_from_token,
                    to_chain=to_chain_name,
                    to_token=mayan_to_token,
                    amount_in64=str(to_amount),
                    to_address=provider_request.params["to"]["address"],
                )

                if not probe_response:
                    raise ValueError("No quotes returned from Mayan API (probe)")

                # Use base-unit fields to avoid decimal mismatch across tokens
                probe_amount_in = int(probe_response["effectiveAmountIn64"])
                probe_amount_out = int(probe_response.get("minAmountOutBaseUnits", "0"))

                if probe_amount_out <= 0:
                    raise ValueError(f"Invalid probe output: {probe_amount_out}")

                # Step 2 — Scale up to guarantee over-delivery
                # Both probe values are in base units, so the ratio is unit-safe
                scale_factor = probe_amount_in / probe_amount_out
                amount_in_final = math.ceil(
                    to_amount * scale_factor * (1 + MAYAN_SLIPPAGE_BUFFER)
                )

                final_response = self._call_quote_api(
                    from_chain=from_chain_name,
                    from_token=mayan_from_token,
                    to_chain=to_chain_name,
                    to_token=mayan_to_token,
                    amount_in64=str(amount_in_final),
                    to_address=provider_request.params["to"]["address"],
                )

                if not final_response:
                    raise ValueError("No quotes returned from Mayan API (final)")

                expected_out_raw = final_response.get("expectedAmountOut", 0)
                min_amount_out = int(final_response.get("minAmountOutBaseUnits", "0"))

                # Verify over-delivery guarantee
                # minAmountOutBaseUnits is in base units (same as to_amount)
                if min_amount_out < to_amount:
                    self.logger.warning(
                        f"[MAYAN PROVIDER] Under-delivery: "
                        f"minAmountOutBaseUnits={min_amount_out} < {to_amount}. "
                        f"expectedAmountOut={expected_out_raw}."
                    )
                    raise ValueError(
                        f"Under-delivery: minAmountOutBaseUnits={min_amount_out} "
                        f"< required={to_amount}"
                    )

                eta_seconds = int(final_response.get("etaSeconds", 120))

                quote_data = QuoteData(
                    eta=eta_seconds,
                    elapsed_time=time.time() - start,
                    message=None,
                    provider_data={
                        "attempts": attempt,
                        "response": final_response,
                        "amount_in_final": amount_in_final,
                    },
                    timestamp=int(time.time()),
                )
                provider_request.quote_data = quote_data
                provider_request.status = ProviderRequestStatus.QUOTE_DONE
                return

            except requests.Timeout as e:
                self.logger.warning(
                    f"[MAYAN PROVIDER] Timeout on attempt "
                    f"{attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                quote_data = QuoteData(
                    eta=None,
                    elapsed_time=time.time() - start,
                    message=str(e),
                    provider_data={
                        "attempts": attempt,
                        "response": None,
                        "response_status": HTTPStatus.GATEWAY_TIMEOUT,
                    },
                    timestamp=int(time.time()),
                )
            except requests.RequestException as e:
                self.logger.warning(
                    f"[MAYAN PROVIDER] Request failed on attempt "
                    f"{attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                quote_data = QuoteData(
                    eta=None,
                    elapsed_time=time.time() - start,
                    message=str(e),
                    provider_data={
                        "attempts": attempt,
                        "response": None,
                        "response_status": HTTPStatus.BAD_GATEWAY,
                    },
                    timestamp=int(time.time()),
                )
            except Exception as e:  # pylint: disable=broad-except
                self.logger.warning(
                    f"[MAYAN PROVIDER] Request failed on attempt "
                    f"{attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                quote_data = QuoteData(
                    eta=None,
                    elapsed_time=time.time() - start,
                    message=str(e),
                    provider_data={
                        "attempts": attempt,
                        "response": None,
                        "response_status": HTTPStatus.INTERNAL_SERVER_ERROR,
                    },
                    timestamp=int(time.time()),
                )

            if attempt >= DEFAULT_MAX_QUOTE_RETRIES:
                self.logger.error(
                    f"[MAYAN PROVIDER] Request failed after "
                    f"{DEFAULT_MAX_QUOTE_RETRIES} attempts."
                )
                provider_request.quote_data = quote_data
                provider_request.status = ProviderRequestStatus.QUOTE_FAILED
                return

            time.sleep(2)

    def _call_quote_api(  # pylint: disable=too-many-arguments
        self,
        from_chain: str,
        from_token: str,
        to_chain: str,
        to_token: str,
        amount_in64: str,
        to_address: str,
    ) -> t.Optional[t.Dict]:
        """Call the Mayan Quote API and return the best quote (first in list)."""
        params: t.Dict[str, t.Any] = {
            "amountIn64": amount_in64,
            "fromToken": from_token,
            "fromChain": from_chain,
            "toToken": to_token,
            "toChain": to_chain,
            "slippageBps": 300,
            "swift": "true",
            "mctp": "false",
            "fastMctp": "false",
            "wormhole": "false",
            "gasless": "false",
            "forwarderAddress": MAYAN_FORWARDER_ADDRESS,
            "destinationAddress": to_address,
            "sdkVersion": "13_0_0",
        }

        self.logger.info(
            f"[MAYAN PROVIDER] GET {MAYAN_QUOTE_API_URL} "
            f"fromChain={from_chain} toChain={to_chain} "
            f"amountIn64={amount_in64}"
        )

        response = requests.get(
            url=MAYAN_QUOTE_API_URL,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        # The API returns {"minimumSdkVersion": ..., "quotes": [...]}
        quotes = payload.get("quotes", []) if isinstance(payload, dict) else []
        if not quotes:
            return None

        return quotes[0]

    def _get_txs(  # pylint: disable=too-many-locals,too-many-statements
        self, provider_request: ProviderRequest, *args: t.Any, **kwargs: t.Any
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Build transaction list from Mayan quote response.

        Returns an ERC-20 approve tx (if needed) followed by the
        Forwarder call (forwardEth or forwardERC20).
        """
        if provider_request.params["to"]["amount"] == 0:
            return []

        quote_data = provider_request.quote_data
        if not quote_data:
            raise RuntimeError(
                f"Cannot get transactions for {provider_request.id}: "
                "quote data not present."
            )

        provider_data = quote_data.provider_data
        if not provider_data:
            raise RuntimeError(
                f"Cannot get transactions for {provider_request.id}: "
                "provider_data not present in quote_data."
            )

        response = provider_data.get("response")
        if not response:
            raise RuntimeError(
                f"Cannot get transactions for {provider_request.id}: "
                "response not present in provider_data."
            )

        amount_in_final = provider_data.get("amount_in_final", 0)
        if not amount_in_final:
            raise RuntimeError(
                f"Cannot get transactions for {provider_request.id}: "
                "amount_in_final is zero or missing."
            )

        from_chain = provider_request.params["from"]["chain"]
        from_address = provider_request.params["from"]["address"]
        from_token = provider_request.params["from"]["token"]
        to_chain = provider_request.params["to"]["chain"]
        to_address = provider_request.params["to"]["address"]
        from_ledger_api = self._from_ledger_api(provider_request)
        w3 = from_ledger_api.api

        is_native = from_token == ZERO_ADDRESS
        route_type = response.get("type", "SWIFT")

        # Determine the inner protocol contract address
        mayan_protocol = self._get_mayan_protocol_address(response, route_type)
        if not mayan_protocol:
            raise RuntimeError(
                f"Cannot get transactions for {provider_request.id}: "
                f"unknown route type '{route_type}'."
            )

        mayan_protocol = w3.to_checksum_address(mayan_protocol)

        # Build protocolData (ABI-encoded inner protocol call)
        protocol_data = self._build_protocol_data(
            response=response,
            from_address=from_address,
            from_token=from_token,
            to_address=to_address,
            to_chain=to_chain,
            amount_in_final=amount_in_final,
            from_chain=from_chain,
        )

        txs: t.List[t.Tuple[str, t.Dict]] = []
        forwarder_address = w3.to_checksum_address(MAYAN_FORWARDER_ADDRESS)
        bridge_fee = int(response.get("bridgeFee", 0))

        if is_native:
            # forwardEth: send native ETH as msg.value
            tx_data = self._forwarder_contract.encode_abi(
                "forwardEth",
                args=[mayan_protocol, protocol_data],
            )
            tx = {
                "to": forwarder_address,
                "from": from_address,
                "data": tx_data,
                "value": amount_in_final,
                "gas": MAYAN_DEFAULT_GAS.get(Chain(from_chain), {"forwarder": 350_000})[
                    "forwarder"
                ],
            }
            update_tx_with_gas_pricing(tx, from_ledger_api)
            update_tx_with_gas_estimate(
                tx, from_ledger_api, BRIDGE_GAS_ESTIMATE_MULTIPLIER
            )
            txs.append(("forwardEth", tx))
        else:
            # ERC-20 path: approve + forwardERC20
            from_token_checksum = w3.to_checksum_address(from_token)

            # Build approve tx
            erc20 = w3.eth.contract(
                address=from_token_checksum,
                abi=[
                    {
                        "inputs": [
                            {"name": "spender", "type": "address"},
                            {"name": "amount", "type": "uint256"},
                        ],
                        "name": "approve",
                        "outputs": [{"name": "", "type": "bool"}],
                        "stateMutability": "nonpayable",
                        "type": "function",
                    }
                ],
            )
            approve_data = erc20.encode_abi(
                "approve",
                args=[forwarder_address, amount_in_final],
            )
            approve_tx = {
                "to": from_token_checksum,
                "from": from_address,
                "data": approve_data,
                "value": 0,
                "gas": MAYAN_DEFAULT_GAS.get(Chain(from_chain), {"approve": 50_000})[
                    "approve"
                ],
            }
            update_tx_with_gas_pricing(approve_tx, from_ledger_api)
            update_tx_with_gas_estimate(
                approve_tx, from_ledger_api, BRIDGE_GAS_ESTIMATE_MULTIPLIER
            )
            txs.append(("approve", approve_tx))

            # Build forwardERC20 tx
            zero_permit = (0, 0, 0, b"\x00" * 32, b"\x00" * 32)
            forward_data = self._forwarder_contract.encode_abi(
                "forwardERC20",
                args=[
                    from_token_checksum,
                    amount_in_final,
                    zero_permit,
                    mayan_protocol,
                    protocol_data,
                ],
            )
            forward_tx = {
                "to": forwarder_address,
                "from": from_address,
                "data": forward_data,
                "value": bridge_fee,
                "gas": MAYAN_DEFAULT_GAS.get(Chain(from_chain), {"forwarder": 350_000})[
                    "forwarder"
                ],
            }
            update_tx_with_gas_pricing(forward_tx, from_ledger_api)
            update_tx_with_gas_estimate(
                forward_tx, from_ledger_api, BRIDGE_GAS_ESTIMATE_MULTIPLIER
            )
            txs.append(("forwardERC20", forward_tx))

        return txs

    @staticmethod
    def _get_mayan_protocol_address(
        response: t.Dict, route_type: str
    ) -> t.Optional[str]:
        """Get the inner Mayan protocol contract address from the quote response."""
        if route_type == "SWIFT":
            return response.get("swiftMayanContract")
        if route_type == "MCTP":
            return response.get("mctpMayanContract")
        if route_type == "FAST_MCTP":
            return response.get("fastMctpMayanContract")
        return None

    def _build_protocol_data(  # pylint: disable=too-many-locals,too-many-arguments
        self,
        response: t.Dict,
        from_address: str,
        from_token: str,
        to_address: str,
        to_chain: str,
        amount_in_final: int,
        from_chain: str,
    ) -> bytes:
        """Build the ABI-encoded protocolData for the inner Mayan protocol call.

        Currently supports SWIFT V2 routes via createOrderWithToken.
        """
        dest_chain_id = WORMHOLE_CHAIN_IDS.get(to_chain)
        if dest_chain_id is None:
            raise ValueError(f"Unsupported destination chain for Mayan: {to_chain}")

        # Pad addresses to bytes32 (left-pad with zeros for EVM addresses)
        trader_bytes32 = self._address_to_bytes32(from_address)
        dest_addr_bytes32 = self._address_to_bytes32(to_address)
        referrer_bytes32 = b"\x00" * 32

        # Token out: use the output token identifier from the quote
        to_token_info = response.get("toToken", {})
        to_token_contract = to_token_info.get("contract", ZERO_ADDRESS)
        token_out_bytes32 = self._address_to_bytes32(to_token_contract)

        min_amount_out_64 = int(response.get("minAmountOutBaseUnits") or 0)
        gas_drop_64 = int(response.get("gasDrop") or 0)
        cancel_fee_64 = int(response.get("cancelRelayerFee64") or 0)
        refund_fee_64 = int(response.get("submitRelayerFee64") or 0)
        deadline_64 = int(response.get("deadline64") or 0)
        referrer_bps = int(response.get("referrerBps") or 0)
        auction_mode = int(response.get("swiftAuctionMode") or 1)
        random_bytes32 = secrets.token_bytes(32)

        # Determine the input token for the SWIFT contract
        is_native = from_token == ZERO_ADDRESS
        if is_native:
            # For native ETH, the Forwarder wraps to WETH; use wrapped native addr
            swift_input_contract = response.get("swiftInputContract")
            if not swift_input_contract:
                swift_input_contract = WRAPPED_NATIVE_ASSET.get(
                    Chain(from_chain), ZERO_ADDRESS
                )
        else:
            swift_input_contract = from_token

        order_params = (
            1,  # payloadType (1 = standard)
            trader_bytes32,
            dest_addr_bytes32,
            dest_chain_id,
            referrer_bytes32,
            token_out_bytes32,
            min_amount_out_64,
            gas_drop_64,
            cancel_fee_64,
            refund_fee_64,
            deadline_64,
            referrer_bps,
            auction_mode,
            random_bytes32,
        )

        # Encode createOrderWithToken(tokenIn, amountIn, orderParams, customPayload)
        protocol_data = self._swift_contract.encode_abi(
            "createOrderWithToken",
            args=[
                self._w3.to_checksum_address(swift_input_contract),
                amount_in_final,
                order_params,
                b"",  # empty customPayload
            ],
        )

        return bytes.fromhex(protocol_data[2:])  # strip 0x prefix

    @staticmethod
    def _address_to_bytes32(address: str) -> bytes:
        """Convert an EVM address to a left-padded bytes32."""
        if not address.startswith("0x") or len(address) != 42:
            raise ValueError(f"Expected 20-byte hex address, got {address!r}")
        addr_bytes = bytes.fromhex(address[2:])  # strip 0x, decode hex
        return b"\x00" * 12 + addr_bytes

    def _update_execution_status(self, provider_request: ProviderRequest) -> None:
        """Poll the Mayan Explorer API for execution status."""
        if provider_request.status not in (
            ProviderRequestStatus.EXECUTION_PENDING,
            ProviderRequestStatus.EXECUTION_UNKNOWN,
        ):
            return

        execution_data = provider_request.execution_data
        if not execution_data:
            raise RuntimeError(
                f"Cannot update request {provider_request.id}: "
                "execution data not present."
            )

        from_tx_hash = execution_data.from_tx_hash
        if not from_tx_hash:
            execution_data.message = (
                f"{MESSAGE_EXECUTION_FAILED} missing transaction hash."
            )
            provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
            return

        try:
            url = f"{MAYAN_EXPLORER_API_URL}/{from_tx_hash}"
            self.logger.info(f"[MAYAN PROVIDER] GET {url}")
            response = requests.get(url=url, timeout=30)

            if response.status_code == 404:
                # Transaction not yet indexed by Mayan Explorer
                provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN
                if self._bridge_tx_likely_failed(provider_request):
                    provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
                return

            response.raise_for_status()
            response_json = response.json()

            client_status = response_json.get("clientStatus", "").upper()
            execution_data.message = client_status

            if client_status == "COMPLETED":
                self.logger.info(
                    f"[MAYAN PROVIDER] Execution done for {provider_request.id}."
                )
                dest_tx = response_json.get("fulfillTxHash")
                if dest_tx:
                    execution_data.to_tx_hash = dest_tx
                    from_ledger_api = self._from_ledger_api(provider_request)
                    to_ledger_api = self._to_ledger_api(provider_request)
                    try:
                        execution_data.elapsed_time = Provider._tx_timestamp(
                            dest_tx, to_ledger_api
                        ) - Provider._tx_timestamp(from_tx_hash, from_ledger_api)
                    except Exception:  # pylint: disable=broad-except  # nosec B110
                        pass  # Best-effort elapsed_time; non-critical if RPC fails

                provider_request.status = ProviderRequestStatus.EXECUTION_DONE

            elif client_status in ("REFUNDED", "FAILED"):
                execution_data.message = (
                    f"{MESSAGE_EXECUTION_FAILED} Mayan status: {client_status}"
                )
                provider_request.status = ProviderRequestStatus.EXECUTION_FAILED

            elif client_status in ("INPROGRESS", "PENDING", ""):
                provider_request.status = ProviderRequestStatus.EXECUTION_PENDING

            else:
                # Unknown status — log and treat as UNKNOWN so
                # _bridge_tx_likely_failed engages sooner than HARD_TIMEOUT
                self.logger.warning(
                    f"[MAYAN PROVIDER] Unknown clientStatus '{client_status}' "
                    f"for request {provider_request.id} — treating as UNKNOWN."
                )
                provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN
                if self._bridge_tx_likely_failed(provider_request):
                    provider_request.status = ProviderRequestStatus.EXECUTION_FAILED

        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(
                f"[MAYAN PROVIDER] Failed to update status for "
                f"request {provider_request.id}: {e}"
            )
            provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN
            if self._bridge_tx_likely_failed(provider_request):
                provider_request.status = ProviderRequestStatus.EXECUTION_FAILED

    def _get_explorer_link(self, provider_request: ProviderRequest) -> t.Optional[str]:
        """Get the Mayan Explorer link for a transaction."""
        if not provider_request.execution_data:
            return None

        from_tx_hash = provider_request.execution_data.from_tx_hash
        if not from_tx_hash:
            return None

        return f"{MAYAN_EXPLORER_URL}/SWIFT_V2_{from_tx_hash}"
