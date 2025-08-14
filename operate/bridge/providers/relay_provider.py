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
"""Relay provider."""


import enum
import json
import math
import time
import typing as t
from http import HTTPStatus
from urllib.parse import urlencode

import requests

from operate.bridge.providers.provider import (
    DEFAULT_MAX_QUOTE_RETRIES,
    MESSAGE_EXECUTION_FAILED,
    MESSAGE_QUOTE_ZERO,
    Provider,
    ProviderRequest,
    ProviderRequestStatus,
    QuoteData,
)
from operate.operate_types import Chain


GAS_ESTIMATE_FALLBACK_ADDRESS = "0x000000000000000000000000000000000000dEaD"

# The following constants were determined empirically (+ margin) from the Relay API/Dapp.
RELAY_DEFAULT_GAS = {
    Chain.ETHEREUM: {
        "deposit": 50_000,
        "approve": 200_000,
        "authorize": 1,
        "authorize1": 1,
        "authorize2": 1,
        "swap": 400_000,
        "send": 1,
    },
    Chain.BASE: {
        "deposit": 50_000,
        "approve": 200_000,
        "authorize": 1,
        "authorize1": 1,
        "authorize2": 1,
        "swap": 400_000,
        "send": 1,
    },
    Chain.CELO: {
        "deposit": 50_000,
        "approve": 200_000,
        "authorize": 1,
        "authorize1": 1,
        "authorize2": 1,
        "swap": 400_000,
        "send": 1,
    },
    Chain.GNOSIS: {
        "deposit": 350_000,
        "approve": 200_000,
        "authorize": 1,
        "authorize1": 1,
        "authorize2": 1,
        "swap": 500_000,
        "send": 1,
    },
    Chain.MODE: {
        "deposit": 50_000,
        "approve": 200_000,
        "authorize": 1,
        "authorize1": 1,
        "authorize2": 1,
        "swap": 1_500_000,
        "send": 1,
    },
    Chain.OPTIMISM: {
        "deposit": 50_000,
        "approve": 200_000,
        "authorize": 1,
        "authorize1": 1,
        "authorize2": 1,
        "swap": 400_000,
        "send": 1,
    },
}


# https://docs.relay.link/guides/bridging#status-values
class RelayExecutionStatus(str, enum.Enum):
    """Relay execution status."""

    REFUND = "refund"
    DELAYED = "delayed"
    WAITING = "waiting"
    FAILURE = "failure"
    PENDING = "pending"
    SUCCESS = "success"

    def __str__(self) -> str:
        """__str__"""
        return self.value


class RelayProvider(Provider):
    """Relay provider."""

    def description(self) -> str:
        """Get a human-readable description of the provider."""
        return "Relay Protocol https://www.relay.link/"

    def quote(self, provider_request: ProviderRequest) -> None:
        """Update the request with the quote."""
        self._validate(provider_request)

        if provider_request.status not in (
            ProviderRequestStatus.CREATED,
            ProviderRequestStatus.QUOTE_DONE,
            ProviderRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"Cannot quote request {provider_request.id} with status {provider_request.status}."
            )

        if provider_request.execution_data:
            raise RuntimeError(
                f"Cannot quote request {provider_request.id}: execution already present."
            )

        from_chain = provider_request.params["from"]["chain"]
        from_address = provider_request.params["from"]["address"]
        from_token = provider_request.params["from"]["token"]
        to_chain = provider_request.params["to"]["chain"]
        to_address = provider_request.params["to"]["address"]
        to_token = provider_request.params["to"]["token"]
        to_amount = provider_request.params["to"]["amount"]

        if to_amount == 0:
            self.logger.info(f"[RELAY PROVIDER] {MESSAGE_QUOTE_ZERO}")
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

        url = "https://api.relay.link/quote"
        headers = {"Content-Type": "application/json"}
        payload = {
            "originChainId": Chain(from_chain).id,
            "user": from_address,
            "originCurrency": from_token,
            "destinationChainId": Chain(to_chain).id,
            "recipient": to_address,
            "destinationCurrency": to_token,
            "amount": str(to_amount),
            "tradeType": "EXACT_OUTPUT",
            "enableTrueExactOutput": False,
        }
        for attempt in range(1, DEFAULT_MAX_QUOTE_RETRIES + 1):
            start = time.time()
            try:
                self.logger.info(f"[RELAY PROVIDER] POST {url}")
                self.logger.info(
                    f"[RELAY PROVIDER] BODY {json.dumps(payload, indent=2, sort_keys=True)}"
                )
                response = requests.post(
                    url=url, headers=headers, json=payload, timeout=30
                )
                response.raise_for_status()
                response_json = response.json()

                # Gas will be returned as 0 (unable to estimate) by the API endpoint when simulation fails.
                # This happens when 'from_address'
                #   * does not have enough funds/ERC20,
                #   * requires to approve an ERC20 before another transaction.
                # Call the API again using the default 'from_address' placeholder used by Relay DApp.
                gas_missing = any(
                    "gas" not in item.get("data", {})
                    for step in response_json.get("steps", [])
                    for item in step.get("items", [])
                )

                if gas_missing:
                    placeholder_payload = payload.copy()
                    placeholder_payload["user"] = GAS_ESTIMATE_FALLBACK_ADDRESS
                    self.logger.info(f"[RELAY PROVIDER] POST {url}")
                    self.logger.info(
                        f"[RELAY PROVIDER] BODY {json.dumps(placeholder_payload, indent=2, sort_keys=True)}"
                    )
                    placeholder_response = requests.post(
                        url=url, headers=headers, json=placeholder_payload, timeout=30
                    )
                    response_json_placeholder = placeholder_response.json()

                    for i, step in enumerate(response_json.get("steps", [])):
                        for j, item in enumerate(step.get("items", [])):
                            if "gas" not in item.get("data", {}):
                                placeholder_gas = (
                                    response_json_placeholder.get("steps", {i: {}})[i]
                                    .get("items", {j: {}})[j]
                                    .get("data", {})
                                    .get("gas")
                                )
                                item["data"]["gas"] = (
                                    placeholder_gas
                                    or RELAY_DEFAULT_GAS[Chain(from_chain)][step["id"]]
                                )

                quote_data = QuoteData(
                    eta=math.ceil(response_json["details"]["timeEstimate"]),
                    elapsed_time=time.time() - start,
                    message=None,
                    provider_data={
                        "attempts": attempt,
                        "response": response_json,
                        "response_status": response.status_code,
                    },
                    timestamp=int(time.time()),
                )
                provider_request.quote_data = quote_data
                provider_request.status = ProviderRequestStatus.QUOTE_DONE
                return
            except requests.Timeout as e:
                self.logger.warning(
                    f"[RELAY PROVIDER] Timeout request on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
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
                    f"[RELAY PROVIDER] Request failed on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                response_json = response.json()
                quote_data = QuoteData(
                    eta=None,
                    elapsed_time=time.time() - start,
                    message=response_json.get("message") or str(e),
                    provider_data={
                        "attempts": attempt,
                        "response": response_json,
                        "response_status": getattr(
                            response, "status_code", HTTPStatus.BAD_GATEWAY
                        ),
                    },
                    timestamp=int(time.time()),
                )
            except Exception as e:  # pylint:disable=broad-except
                self.logger.warning(
                    f"[RELAY PROVIDER] Request failed on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
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
                    f"[RELAY PROVIDER] Request failed after {DEFAULT_MAX_QUOTE_RETRIES} attempts."
                )
                provider_request.quote_data = quote_data
                provider_request.status = ProviderRequestStatus.QUOTE_FAILED
                return

            time.sleep(2)

    def _get_txs(
        self, provider_request: ProviderRequest, *args: t.Any, **kwargs: t.Any
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the quote."""

        if provider_request.params["to"]["amount"] == 0:
            return []

        quote_data = provider_request.quote_data
        if not quote_data:
            raise RuntimeError(
                f"Cannot get transaction builders {provider_request.id}: quote data not present."
            )

        provider_data = quote_data.provider_data
        if not provider_data:
            raise RuntimeError(
                f"Cannot get transaction builders {provider_request.id}: provider data not present."
            )

        txs: t.List[t.Tuple[str, t.Dict]] = []

        response = provider_data.get("response")
        if not response:
            return txs

        steps = response.get("steps", [])
        from_ledger_api = self._from_ledger_api(provider_request)

        for step in steps:
            for i, item in enumerate(step["items"]):
                tx = item["data"].copy()
                tx["to"] = from_ledger_api.api.to_checksum_address(tx["to"])
                tx["value"] = int(tx.get("value", 0))
                tx["gas"] = int(tx.get("gas", 1))
                tx["maxFeePerGas"] = int(tx.get("maxFeePerGas", 0))
                tx["maxPriorityFeePerGas"] = int(tx.get("maxPriorityFeePerGas", 0))
                tx["nonce"] = from_ledger_api.api.eth.get_transaction_count(tx["from"])
                Provider._update_with_gas_pricing(tx, from_ledger_api)
                Provider._update_with_gas_estimate(tx, from_ledger_api)
                txs.append((f"{step['id']}-{i}", tx))

        return txs

    def _update_execution_status(self, provider_request: ProviderRequest) -> None:
        """Update the execution status."""

        if provider_request.status not in (
            ProviderRequestStatus.EXECUTION_PENDING,
            ProviderRequestStatus.EXECUTION_UNKNOWN,
        ):
            return

        execution_data = provider_request.execution_data
        if not execution_data:
            raise RuntimeError(
                f"Cannot update request {provider_request.id}: execution data not present."
            )

        from_tx_hash = execution_data.from_tx_hash
        if not from_tx_hash:
            execution_data.message = (
                f"{MESSAGE_EXECUTION_FAILED} missing transaction hash."
            )
            provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
            return

        url = "https://api.relay.link/requests/v2"
        headers = {"accept": "application/json"}
        params = {
            "hash": from_tx_hash,
            "sortBy": "createdAt",
        }

        try:
            self.logger.info(f"[RELAY PROVIDER] GET {url}?{urlencode(params)}")
            response = requests.get(url=url, headers=headers, params=params, timeout=30)
            response_json = response.json()
            relay_requests = response_json.get("requests")
            if relay_requests:
                relay_status = relay_requests[0].get(
                    "status", str(RelayExecutionStatus.WAITING)
                )
                execution_data.message = str(relay_status)
            else:
                provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN
                return
            response.raise_for_status()
        except Exception as e:
            self.logger.error(
                f"[RELAY PROVIDER] Failed to update status for request {provider_request.id}: {e}"
            )
            provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN
            return

        if relay_status == RelayExecutionStatus.SUCCESS:
            self.logger.info(
                f"[RELAY PROVIDER] Execution done for {provider_request.id}."
            )
            from_ledger_api = self._from_ledger_api(provider_request)
            to_ledger_api = self._to_ledger_api(provider_request)

            if (
                response_json["requests"][0]["data"]["outTxs"][0]["chainId"]
                == response_json["requests"][0]["data"]["inTxs"][0]["chainId"]
            ):
                to_tx_hash = from_tx_hash  # Should match response_json["requests"][0]["data"]["inTxs"][0]["hash"]
            else:
                to_tx_hash = response_json["requests"][0]["data"]["outTxs"][0]["hash"]

            execution_data.message = response_json.get("details", None)
            execution_data.to_tx_hash = to_tx_hash
            execution_data.elapsed_time = Provider._tx_timestamp(
                to_tx_hash, to_ledger_api
            ) - Provider._tx_timestamp(from_tx_hash, from_ledger_api)
            provider_request.status = ProviderRequestStatus.EXECUTION_DONE
            execution_data.provider_data = {
                "response": response_json,
            }
        elif relay_status in (
            RelayExecutionStatus.FAILURE,
            RelayExecutionStatus.REFUND,
        ):
            provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
        elif relay_status in (
            RelayExecutionStatus.PENDING,
            RelayExecutionStatus.DELAYED,
            RelayExecutionStatus.WAITING,
        ):
            provider_request.status = ProviderRequestStatus.EXECUTION_PENDING
        else:
            provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN

    def _get_explorer_link(self, provider_request: ProviderRequest) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        if not provider_request.execution_data:
            return None

        quote_data = provider_request.quote_data
        if not quote_data:
            raise RuntimeError(
                f"Cannot get explorer link for request {provider_request.id}: quote data not present."
            )

        provider_data = quote_data.provider_data
        if not provider_data:
            return None

        steps = provider_data.get("response", {}).get("steps", [])
        if not steps:
            return None

        request_id = steps[-1].get("requestId")
        return f"https://relay.link/transaction/{request_id}"
