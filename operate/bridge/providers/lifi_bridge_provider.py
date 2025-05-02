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
from autonomy.chain.tx import TxSettler

from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequest,
    BridgeRequestStatus,
    DEFAULT_MAX_QUOTE_RETRIES,
    ExecutionData,
    MESSAGE_EXECUTION_SKIPPED,
    MESSAGE_QUOTE_ZERO,
    QuoteData,
)
from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
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

    @staticmethod
    def _build_approve_tx(
        quote_data: QuoteData, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
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
        return LiFiBridgeProvider._update_tx_gas_pricing(approve_tx, ledger_api)

    @staticmethod
    def _get_bridge_tx(
        quote_data: QuoteData, ledger_api: LedgerApi
    ) -> t.Optional[t.Dict]:
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
            "data": bytes.fromhex(transaction_request["data"][2:]),
            "from": transaction_request["from"],
            "chainId": transaction_request["chainId"],
            "gasPrice": int(transaction_request["gasPrice"], 16),
            "gas": int(transaction_request["gasLimit"], 16),
            "nonce": ledger_api.api.eth.get_transaction_count(
                transaction_request["from"]
            ),
        }

        return LiFiBridgeProvider._update_tx_gas_pricing(bridge_tx, ledger_api)

    # TODO This gas pricing management should possibly be done at a lower level in the library
    @staticmethod
    def _update_tx_gas_pricing(tx: t.Dict, ledger_api: LedgerApi) -> t.Dict:
        output_tx = tx.copy()
        output_tx.pop("maxFeePerGas", None)
        output_tx.pop("gasPrice", None)
        output_tx.pop("maxPriorityFeePerGas", None)

        gas_pricing = ledger_api.try_get_gas_pricing()
        if gas_pricing is None:
            raise RuntimeError("Unable to retrieve gas pricing.")

        if "maxFeePerGas" in gas_pricing and "maxPriorityFeePerGas" in gas_pricing:
            output_tx["maxFeePerGas"] = gas_pricing["maxFeePerGas"]
            output_tx["maxPriorityFeePerGas"] = gas_pricing["maxPriorityFeePerGas"]
        elif "gasPrice" in gas_pricing:
            output_tx["gasPrice"] = gas_pricing["gasPrice"]
        else:
            raise RuntimeError("Retrieved invalid gas pricing.")

        return output_tx

    @staticmethod
    def _calculate_gas_fees(tx: t.Dict) -> int:
        gas_key = "gasPrice" if "gasPrice" in tx else "maxFeePerGas"
        return tx.get(gas_key, 0) * tx["gas"]

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

    def bridge_requirements(self, bridge_request: BridgeRequest) -> t.Dict:
        """Gets the fund requirements to execute the quote, with updated gas estimation."""
        self._validate(bridge_request)

        quote_data = bridge_request.quote_data
        if not quote_data:
            raise RuntimeError(
                f"Cannot compute requirements for bridge request {bridge_request.id}: quote not present."
            )

        from_chain = bridge_request.params["from"]["chain"]
        from_address = bridge_request.params["from"]["address"]
        from_token = bridge_request.params["from"]["token"]

        zero_requirements = {
            from_chain: {
                from_address: {
                    ZERO_ADDRESS: 0,
                    from_token: 0,
                }
            }
        }

        chain = Chain(from_chain)
        wallet = self.wallet_manager.load(chain.ledger_type)
        ledger_api = wallet.ledger_api(chain)

        approve_tx = self._build_approve_tx(quote_data, ledger_api)
        bridge_tx = self._get_bridge_tx(quote_data, ledger_api)
        if not bridge_tx:
            return zero_requirements

        bridge_tx_value = bridge_tx["value"]
        bridge_tx_gas_fees = self._calculate_gas_fees(bridge_tx)

        if approve_tx:
            approve_tx_gas_fees = self._calculate_gas_fees(approve_tx)
            return {
                from_chain: {
                    from_address: {
                        ZERO_ADDRESS: bridge_tx_value
                        + bridge_tx_gas_fees
                        + approve_tx_gas_fees,
                        from_token: int(quote_data.response["action"]["fromAmount"]),  # type: ignore
                    }
                }
            }

        return {
            from_chain: {
                from_address: {from_token: bridge_tx_value + bridge_tx_gas_fees}
            }
        }

    def execute(self, bridge_request: BridgeRequest) -> None:
        """Execute the quote."""
        self._validate(bridge_request)

        if bridge_request.status not in (
            BridgeRequestStatus.QUOTE_DONE,
            BridgeRequestStatus.QUOTE_FAILED,
        ):
            raise RuntimeError(
                f"Cannot execute bridge request {bridge_request.id} with status {bridge_request.status}."
            )

        if not bridge_request.quote_data:
            raise RuntimeError(
                f"Cannot execute bridge request {bridge_request.id}: quote data not present."
            )

        if bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot execute bridge request {bridge_request.id}: execution data already present."
            )

        timestamp = time.time()
        quote = bridge_request.quote_data.response

        if not quote or "action" not in quote:
            self.logger.info(
                f"[LI.FI BRIDGE] {MESSAGE_EXECUTION_SKIPPED} ({bridge_request.status=})"
            )
            execution_data = ExecutionData(
                bridge_status=None,
                elapsed_time=0,
                explorer_link=None,
                message=f"{MESSAGE_EXECUTION_SKIPPED} ({bridge_request.status=})",
                timestamp=int(timestamp),
                tx_hash=None,
                tx_status=0,
            )
            bridge_request.execution_data = execution_data

            if bridge_request.status == BridgeRequestStatus.QUOTE_DONE:
                bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
            else:
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
            return

        try:
            self.logger.info(f"[LI.FI BRIDGE] Executing quote {quote.get('id')}.")
            from_token = quote["action"]["fromToken"]["address"]

            transaction_request = quote["transactionRequest"]
            chain = Chain.from_id(transaction_request["chainId"])
            wallet = self.wallet_manager.load(chain.ledger_type)
            ledger_api = wallet.ledger_api(chain)

            tx_settler = TxSettler(
                ledger_api=ledger_api,
                crypto=wallet.crypto,
                chain_type=chain,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )

            # Bridges from an asset other than native require an approval transaction.
            approve_tx = self._build_approve_tx(bridge_request.quote_data, ledger_api)
            if approve_tx:
                self.logger.info(
                    f"[LI.FI BRIDGE] Preparing approve transaction for for quote {quote['id']} ({from_token=})."
                )
                setattr(  # noqa: B010
                    tx_settler, "build", lambda *args, **kwargs: approve_tx
                )
                tx_settler.transact(
                    method=lambda: {},
                    contract="",
                    kwargs={},
                    dry_run=False,
                )
                self.logger.info("[LI.FI BRIDGE] Approve transaction settled.")

            self.logger.info(
                f"[LI.FI BRIDGE] Preparing bridge transaction for quote {quote['id']}."
            )
            bridge_tx = self._get_bridge_tx(bridge_request.quote_data, ledger_api)
            setattr(  # noqa: B010
                tx_settler, "build", lambda *args, **kwargs: bridge_tx
            )
            tx_receipt = tx_settler.transact(
                method=lambda: {},
                contract="",
                kwargs={},
                dry_run=False,
            )
            self.logger.info("[LI.FI BRIDGE] Bridge transaction settled.")
            tx_hash = tx_receipt.get("transactionHash", "").hex()

            execution_data = ExecutionData(
                bridge_status=LiFiTransactionStatus.NOT_FOUND,
                elapsed_time=time.time() - timestamp,
                explorer_link=f"https://scan.li.fi/tx/{tx_hash}",
                message=None,
                timestamp=int(timestamp),
                tx_hash=tx_hash,
                tx_status=tx_receipt.get("status", 0),
            )
            bridge_request.execution_data = execution_data
            if tx_hash:
                bridge_request.status = BridgeRequestStatus.EXECUTION_PENDING
            else:
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED

        except Exception as e:  # pylint: disable=broad-except
            execution_data = ExecutionData(
                bridge_status=LiFiTransactionStatus.UNKNOWN,
                elapsed_time=time.time() - timestamp,
                explorer_link=None,
                message=f"Error executing quote: {str(e)}",
                timestamp=int(timestamp),
                tx_hash=None,
                tx_status=0,
            )
            bridge_request.execution_data = execution_data
            bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED

    def update_execution_status(self, bridge_request: BridgeRequest) -> None:
        """Update the execution status. Returns `True` if the status changed."""
        self._validate(bridge_request)

        if bridge_request.status not in (BridgeRequestStatus.EXECUTION_PENDING):
            return

        if not bridge_request.execution_data:
            raise RuntimeError(
                f"Cannot update bridge request {bridge_request.id}: execution data not present."
            )

        execution = bridge_request.execution_data
        tx_hash = execution.tx_hash

        url = "https://li.quest/v1/status"
        headers = {"accept": "application/json"}
        params = {
            "txHash": tx_hash,
        }
        self.logger.info(f"[LI.FI BRIDGE] GET {url}?{urlencode(params)}")
        response = requests.get(url=url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        lifi_status = response_json.get("status", str(LiFiTransactionStatus.UNKNOWN))
        execution.message = response_json.get("substatusMessage")

        if execution.bridge_status != lifi_status:
            execution.bridge_status = lifi_status
            if lifi_status == LiFiTransactionStatus.DONE:
                bridge_request.status = BridgeRequestStatus.EXECUTION_DONE
            elif lifi_status == LiFiTransactionStatus.FAILED:
                bridge_request.status = BridgeRequestStatus.EXECUTION_FAILED
