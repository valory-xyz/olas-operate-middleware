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
"""LI.FI Bridge provider."""


import enum
import time
import typing as t
from http import HTTPStatus
from urllib.parse import urlencode

import requests
from aea.crypto.base import LedgerApi
from autonomy.chain.base import registry_contracts

from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequest,
    BridgeRequestStatus,
    DEFAULT_MAX_QUOTE_RETRIES,
    MESSAGE_QUOTE_ZERO,
    QuoteData,
)
from operate.constants import ZERO_ADDRESS
from operate.operate_types import Chain


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


class LiFiBridgeProvider(BridgeProvider):
    """LI.FI Bridge provider."""

    def description(self) -> str:
        """Get a human-readable description of the bridge provider."""
        return "LI.FI Bridge & DEX Aggregation Protocol https://li.fi/"

    def quote(self, bridge_request: BridgeRequest) -> None:
        """Update the request with the quote."""
        self._validate(bridge_request)

        if bridge_request.status not in (
            BridgeRequestStatus.CREATED,
            BridgeRequestStatus.QUOTE_DONE,
            BridgeRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"Cannot quote bridge request {bridge_request.id} with status {bridge_request.status}."
            )

        if bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot quote bridge request {bridge_request.id}: execution already present."
            )

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]
        to_chain = bridge_request.params["to"]["chain"]
        to_address = bridge_request.params["to"]["address"]
        to_token = bridge_request.params["to"]["token"]
        to_amount = bridge_request.params["to"]["amount"]

        if to_amount == 0:
            self.logger.info(f"[LI.FI BRIDGE] {MESSAGE_QUOTE_ZERO}")
            quote_data = QuoteData(
                attempts=0,
                elapsed_time=0,
                message=MESSAGE_QUOTE_ZERO,
                response=None,
                response_status=0,
                timestamp=int(time.time()),
            )
            bridge_request.quote_data = quote_data
            bridge_request.status = BridgeRequestStatus.QUOTE_DONE
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
                self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
                response = requests.get(
                    url=url, headers=headers, params=params, timeout=30
                )
                response.raise_for_status()
                response_json = response.json()
                quote_data = QuoteData(
                    attempts=attempt,
                    elapsed_time=time.time() - start,
                    message=None,
                    response=response_json,
                    response_status=response.status_code,
                    timestamp=int(time.time()),
                )
                bridge_request.quote_data = quote_data
                bridge_request.status = BridgeRequestStatus.QUOTE_DONE
                return
            except requests.Timeout as e:
                self.logger.warning(
                    f"[LI.FI BRIDGE] Timeout request on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                quote_data = QuoteData(
                    attempts=attempt,
                    elapsed_time=time.time() - start,
                    message=str(e),
                    response=None,
                    response_status=HTTPStatus.GATEWAY_TIMEOUT,
                    timestamp=int(time.time()),
                )
            except requests.RequestException as e:
                self.logger.warning(
                    f"[LI.FI BRIDGE] Request failed on attempt {attempt}/{DEFAULT_MAX_QUOTE_RETRIES}: {e}."
                )
                response_json = response.json()
                quote_data = QuoteData(
                    attempts=attempt,
                    elapsed_time=time.time() - start,
                    message=response_json.get("message") or str(e),
                    response=response_json,
                    response_status=getattr(
                        response, "status_code", HTTPStatus.BAD_GATEWAY
                    ),
                    timestamp=int(time.time()),
                )
            if attempt >= DEFAULT_MAX_QUOTE_RETRIES:
                self.logger.error(
                    f"[LI.FI BRIDGE] Request failed after {DEFAULT_MAX_QUOTE_RETRIES} attempts."
                )
                bridge_request.quote_data = quote_data
                bridge_request.status = BridgeRequestStatus.QUOTE_FAILED
                return

            time.sleep(2)

    @staticmethod
    def _get_bridge_tx(
        bridge_request: BridgeRequest, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        quote_data = bridge_request.quote_data
        if not quote_data:
            return None

        quote = quote_data.response
        if not quote:
            return None

        if "action" not in quote:
            return None

        transaction_request = quote.get("transactionRequest")
        if not transaction_request:
            return None

        bridge_tx = {
            "value": int(transaction_request["value"], 16),
            "to": transaction_request["to"],
            "data": transaction_request["data"],  # TODO remove bytes?
            "from": transaction_request["from"],
            "chainId": transaction_request["chainId"],
            "gasPrice": int(transaction_request["gasPrice"], 16),
            "gas": int(transaction_request["gasLimit"], 16),
            "nonce": ledger_api.api.eth.get_transaction_count(
                transaction_request["from"]
            ),
        }
        ledger_api.update_with_gas_estimate(bridge_tx)
        return LiFiBridgeProvider._update_with_gas_pricing(bridge_tx, ledger_api)

    @staticmethod
    def _get_approve_tx(
        bridge_request: BridgeRequest, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
        quote_data = bridge_request.quote_data
        if not quote_data:
            return None

        quote = quote_data.response
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

        approve_tx = registry_contracts.erc20.get_approve_tx(
            ledger_api=ledger_api,
            contract_address=from_token,
            spender=transaction_request["to"],
            sender=transaction_request["from"],
            amount=from_amount,
        )
        ledger_api.update_with_gas_estimate(approve_tx)
        return LiFiBridgeProvider._update_with_gas_pricing(approve_tx, ledger_api)

    def _get_transactions(
        self, bridge_request: BridgeRequest
    ) -> t.List[t.Tuple[str, t.Dict]]:
        """Get the sorted list of transactions to execute the bridge request."""
        self._validate(bridge_request)

        if not bridge_request.quote_data:
            return []

        from_chain = bridge_request.params["from"]["chain"]
        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)

        bridge_tx = self._get_bridge_tx(bridge_request, ledger_api)

        if not bridge_tx:
            return []

        approve_tx = self._get_approve_tx(bridge_request, ledger_api)

        if approve_tx:
            bridge_tx["nonce"] = approve_tx["nonce"] + 1
            return [
                ("ERC20 Approve transaction", approve_tx),
                ("Bridge transaction", bridge_tx),
            ]

        return [
            ("Bridge transaction", bridge_tx),
        ]

    def _update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status. Returns `True` if the status changed."""
        self._validate(bridge_request)

        if bridge_request.status not in (
            BridgeRequestStatus.EXECUTION_PENDING,
            BridgeRequestStatus.EXECUTION_UNKNOWN,
        ):
            return

        if not bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot update bridge request {bridge_request.id}: execution data not present."
            )

        execution = bridge_request.execution_data
        if not execution.tx_hashes:
            return

        tx_hash = execution.tx_hashes[-1]

        url = "https://li.quest/v1/status"
        headers = {"accept": "application/json"}
        params = {
            "txHash": tx_hash,
        }

        try:
            self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
            response = requests.get(url=url, headers=headers, params=params, timeout=30)
            response_json = response.json()
            execution.bridge_status = response_json.get(
                "status", str(LiFiTransactionStatus.UNKNOWN)
            )
            execution.message = response_json.get(
                "substatusMessage", response_json.get("message")
            )
            response.raise_for_status()
        except Exception as e:
            self.logger.error(
                f"[LI.FI BRIDGE] Failed to update bridge status for {tx_hash}: {e}"
            )

        if execution.bridge_status == LiFiTransactionStatus.DONE:
            bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
        elif execution.bridge_status == LiFiTransactionStatus.FAILED:
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
        elif execution.bridge_status == LiFiTransactionStatus.PENDING:
            bridge_request.status = BridgeRequestStatus.EXECUTION_PENDING
        else:
            bridge_request.status = BridgeRequestStatus.EXECUTION_UNKNOWN

    def _get_explorer_link(self, tx_hash: str) -> str:
        """Get the explorer link for a transaction."""
        return f"https://scan.li.fi/tx/{tx_hash}"
