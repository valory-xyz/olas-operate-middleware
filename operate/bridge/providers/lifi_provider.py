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
"""LI.FI provider."""


import enum
import time
import typing as t
from http import HTTPStatus
from urllib.parse import urlencode

import requests
from autonomy.chain.base import registry_contracts

from operate.bridge.providers.provider import (
    DEFAULT_MAX_QUOTE_RETRIES,
    MESSAGE_QUOTE_ZERO,
    Provider,
    ProviderRequest,
    ProviderRequestStatus,
    QuoteData,
)
from operate.constants import ZERO_ADDRESS
from operate.operate_types import Chain


LIFI_DEFAULT_ETA = 5 * 60


class LiFiTransactionStatus(str, enum.Enum):
    """LI.FI transaction status."""

    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        """__str__"""
        return self.value


class LiFiProvider(Provider):
    """LI.FI provider."""

    def description(self) -> str:
        """Get a human-readable description of the provider."""
        return "LI.FI Bridge & DEX Aggregation Protocol https://li.fi/"

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
            self.logger.info(f"[LI.FI PROVIDER] {MESSAGE_QUOTE_ZERO}")
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

        url = "https://li.quest/v1/quote/toAmount"
        headers = {"accept": "application/json"}
        params = {
            "fromChain": Chain(from_chain).id,
            "fromAddress": from_address,
            "fromToken": from_token,
            "toChain": Chain(to_chain).id,
            "toAddress": to_address,
            "toToken": to_token,
            "toAmount": to_amount,
            "maxPriceImpact": 0.50,  # TODO determine correct value
        }
        for attempt in range(1, DEFAULT_MAX_QUOTE_RETRIES + 1):
            start = time.time()
            try:
                self.logger.info(f"[LI.FI PROVIDER] GET {url}?{urlencode(params)}")
                response = requests.get(
                    url=url, headers=headers, params=params, timeout=30
                )
                response.raise_for_status()
                response_json = response.json()
                quote_data = QuoteData(
                    eta=LIFI_DEFAULT_ETA,
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
                    f"[LI.FI PROVIDER] Timeout request on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
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
                    f"[LI.FI PROVIDER] Request failed on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
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
                    f"[LI.FI PROVIDER] Request failed on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
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
                    f"[LI.FI PROVIDER] Request failed after {DEFAULT_MAX_QUOTE_RETRIES} attempts."
                )
                provider_request.quote_data = quote_data
                provider_request.status = ProviderRequestStatus.QUOTE_FAILED
                return

            time.sleep(2)

    def _get_approve_tx(self, provider_request: ProviderRequest) -> t.Optional[t.Dict]:
        """Get the approve transaction."""
        self.logger.info(
            f"[LI.FI PROVIDER] Get appprove transaction for request {provider_request.id}."
        )

        if provider_request.params["to"]["amount"] == 0:
            return None

        quote_data = provider_request.quote_data
        if not quote_data:
            return None

        if not quote_data.provider_data:
            return None

        quote = quote_data.provider_data.get("response")
        if not quote:
            return None

        if "action" not in quote:
            return None

        from_token = quote["action"]["fromToken"]["address"]
        if from_token == ZERO_ADDRESS:
            return None

        transaction_request = quote.get("transactionRequest")
        if not transaction_request:
            return None

        from_amount = int(quote["action"]["fromAmount"])
        from_ledger_api = self._from_ledger_api(provider_request)

        approve_tx = registry_contracts.erc20.get_approve_tx(
            ledger_api=from_ledger_api,
            contract_address=from_token,
            spender=transaction_request["to"],
            sender=transaction_request["from"],
            amount=from_amount,
        )
        approve_tx["gas"] = 200_000  # TODO backport to ERC20 contract as default
        Provider._update_with_gas_pricing(approve_tx, from_ledger_api)
        Provider._update_with_gas_estimate(approve_tx, from_ledger_api)
        return approve_tx

    def _get_bridge_tx(self, provider_request: ProviderRequest) -> t.Optional[t.Dict]:
        """Get the bridge transaction."""
        self.logger.info(
            f"[LI.FI PROVIDER] Get bridge transaction for request {provider_request.id}."
        )

        if provider_request.params["to"]["amount"] == 0:
            return None

        quote_data = provider_request.quote_data
        if not quote_data:
            return None

        if not quote_data.provider_data:
            return None

        quote = quote_data.provider_data.get("response")
        if not quote:
            return None

        if "action" not in quote:
            return None

        transaction_request = quote.get("transactionRequest")
        if not transaction_request:
            return None

        from_ledger_api = self._from_ledger_api(provider_request)

        bridge_tx = {
            "value": int(transaction_request["value"], 16),
            "to": transaction_request["to"],
            "data": transaction_request["data"],  # TODO remove bytes?
            "from": transaction_request["from"],
            "chainId": transaction_request["chainId"],
            "gasPrice": int(transaction_request["gasPrice"], 16),
            "gas": int(transaction_request["gasLimit"], 16),
            "nonce": from_ledger_api.api.eth.get_transaction_count(
                transaction_request["from"]
            ),
        }
        Provider._update_with_gas_pricing(bridge_tx, from_ledger_api)
        Provider._update_with_gas_estimate(bridge_tx, from_ledger_api)
        return bridge_tx

    def _get_txs(
        self, provider_request: ProviderRequest, *args: t.Any, **kwargs: t.Any
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the quote."""
        txs = []
        approve_tx = self._get_approve_tx(provider_request)
        if approve_tx:
            txs.append(("approve_tx", approve_tx))
        bridge_tx = self._get_bridge_tx(provider_request)
        if bridge_tx:
            txs.append(("bridge_tx", bridge_tx))
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
            return

        lifi_status = LiFiTransactionStatus.UNKNOWN
        url = "https://li.quest/v1/status"
        headers = {"accept": "application/json"}
        params = {
            "txHash": from_tx_hash,
        }

        try:
            self.logger.info(f"[LI.FI PROVIDER] GET {url}?{urlencode(params)}")
            response = requests.get(url=url, headers=headers, params=params, timeout=30)
            response_json = response.json()
            lifi_status = response_json.get(
                "status", str(LiFiTransactionStatus.UNKNOWN)
            )
            execution_data.message = response_json.get(
                "substatusMessage", response_json.get("message")
            )
            response.raise_for_status()
        except Exception as e:
            self.logger.error(
                f"[LI.FI PROVIDER] Failed to update status for request {provider_request.id}: {e}"
            )

        if lifi_status == LiFiTransactionStatus.DONE:
            self.logger.info(
                f"[LI.FI PROVIDER] Execution done for {provider_request.id}."
            )
            from_ledger_api = self._from_ledger_api(provider_request)
            to_ledger_api = self._to_ledger_api(provider_request)
            to_tx_hash = response_json.get("receiving", {}).get("txHash")
            execution_data.message = None
            execution_data.to_tx_hash = to_tx_hash
            execution_data.elapsed_time = Provider._tx_timestamp(
                to_tx_hash, to_ledger_api
            ) - Provider._tx_timestamp(from_tx_hash, from_ledger_api)
            provider_request.status = ProviderRequestStatus.EXECUTION_DONE
        elif lifi_status == LiFiTransactionStatus.FAILED:
            provider_request.status = ProviderRequestStatus.EXECUTION_FAILED
        elif lifi_status == LiFiTransactionStatus.PENDING:
            provider_request.status = ProviderRequestStatus.EXECUTION_PENDING
        else:
            provider_request.status = ProviderRequestStatus.EXECUTION_UNKNOWN

    def _get_explorer_link(self, provider_request: ProviderRequest) -> t.Optional[str]:
        """Get the explorer link for a transaction."""
        if not provider_request.execution_data:
            return None

        tx_hash = provider_request.execution_data.from_tx_hash
        if not tx_hash:
            return None

        return f"https://scan.li.fi/tx/{tx_hash}"
