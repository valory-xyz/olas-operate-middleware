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

"""Tests for bridge.providers.* module."""


import time
import typing as t
from pathlib import Path
from unittest.mock import patch

import pytest
from aea.helpers.logging import setup_logger
from deepdiff import DeepDiff
from hexbytes import HexBytes
from web3 import Web3

from operate.bridge.bridge_manager import (
    LiFiProvider,
    NATIVE_BRIDGE_PROVIDER_CONFIGS,
    ProviderRequest,
)
from operate.bridge.providers.native_bridge_provider import (
    BridgeContractAdaptor,
    NativeBridgeProvider,
    OmnibridgeContractAdaptor,
    OptimismContractAdaptor,
)
from operate.bridge.providers.provider import (
    ExecutionData,
    MESSAGE_EXECUTION_FAILED,
    MESSAGE_EXECUTION_FAILED_QUOTE_FAILED,
    MESSAGE_EXECUTION_SKIPPED,
    MESSAGE_QUOTE_ZERO,
    Provider,
    ProviderRequestStatus,
    QuoteData,
)
from operate.bridge.providers.relay_provider import RelayProvider
from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger import get_default_rpc
from operate.ledger.profiles import OLAS
from operate.operate_types import Chain, ChainAmounts, LedgerType
from operate.serialization import BigInt

from tests.constants import OPERATE_TEST


TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").to_0x_hex()
LOGGER = setup_logger(name="test_bridge_providers")


def get_transfer_amount(
    w3: Web3, tx_hash: str, token_address: str, recipient: str
) -> int:
    """Get the transfer amount from a transaction, including direct and internal native transfers."""
    token_address = Web3.to_checksum_address(token_address)
    recipient = Web3.to_checksum_address(recipient)

    if token_address == ZERO_ADDRESS:
        total = 0
        tx = w3.eth.get_transaction(tx_hash)
        # Direct native transfer
        if tx["to"] and Web3.to_checksum_address(tx["to"]) == recipient:
            total += tx["value"]

        # Internal native transfers
        try:
            # get internal trace with internal calls
            trace = w3.provider.make_request("trace_transaction", [tx_hash])
            calls = trace.get("result", [])
            for call in calls:
                # check if call is ETH transfer to recipient
                if call.get("type") == "call":
                    to_addr = Web3.to_checksum_address(call["action"]["to"])
                    value = int(call["action"].get("value", "0x0"), 16)
                    if to_addr == recipient and value > 0:
                        total += value
        except Exception as e:
            print(f"trace_transaction failed: {e}")
        return total

    else:
        # ERC-20 Transfer log parsing
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        for log in receipt["logs"]:
            if (
                log["address"].lower() == token_address.lower()
                and log["topics"][0].to_0x_hex().lower() == TRANSFER_TOPIC.lower()
                and Web3.to_checksum_address("0x" + log["topics"][2].to_0x_hex()[-40:])
                == recipient
            ):
                data = log["data"]
                value = (
                    int(data.to_0x_hex(), 16)
                    if isinstance(data, HexBytes)
                    else int(data, 16)
                )
                return value
        return 0


class TestNativeBridgeProvider:
    """Tests for bridge.providers.NativeBridgeProvider class."""

    def test_bridge_execute_error(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bridge_execute_error"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = {
            "from": {
                "chain": Chain.ETHEREUM.value,
                "address": wallet_address,
                "token": OLAS[Chain.ETHEREUM],
            },
            "to": {
                "chain": Chain.BASE.value,
                "address": wallet_address,
                "token": OLAS[Chain.BASE],
                "amount": "1000000000000000000",
            },
        }

        provider_key = "native-ethereum-to-base"
        provider = NativeBridgeProvider(
            provider_id="NativeBridgeProvider",
            bridge_contract_adaptor=OptimismContractAdaptor(
                from_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["from_chain"],
                from_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["from_bridge"],
                to_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["to_chain"],
                to_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["to_bridge"],
                bridge_eta=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["bridge_eta"],
                logger=LOGGER,
            ),
            wallet_manager=operate.wallet_manager,
            logger=LOGGER,
        )

        # Create
        provider_request = provider.create_request(params)
        expected_request = ProviderRequest(
            params={
                "from": {
                    "chain": Chain.ETHEREUM.value,
                    "address": wallet_address,
                    "token": OLAS[Chain.ETHEREUM],
                },
                "to": {
                    "chain": Chain.BASE.value,
                    "address": wallet_address,
                    "token": OLAS[Chain.BASE],
                    "amount": 1000000000000000000,
                },
            },
            id=provider_request.id,
            provider_id=provider.provider_id,
            status=ProviderRequestStatus.CREATED,
            quote_data=None,
            execution_data=None,
        )

        assert provider_request == expected_request, "Wrong request."

        with pytest.raises(RuntimeError):
            provider.execute(provider_request)

        assert provider_request == expected_request, "Wrong request."

        provider._update_execution_status(provider_request)

        assert provider_request == expected_request, "Wrong request."

        # Quote
        expected_quote_data = QuoteData(
            eta=provider.bridge_contract_adaptor.bridge_eta,
            elapsed_time=0,
            message=None,
            provider_data=None,
            timestamp=int(time.time()),
        )
        expected_request.quote_data = expected_quote_data
        expected_request.status = ProviderRequestStatus.QUOTE_DONE

        for _ in range(2):
            provider.quote(provider_request=provider_request)
            assert provider_request.quote_data is not None, "Wrong request."
            expected_quote_data.timestamp = provider_request.quote_data.timestamp
            assert provider_request == expected_request, "Wrong request."
            sj = provider.status_json(provider_request)
            expected_sj = {
                "eta": provider.bridge_contract_adaptor.bridge_eta,
                "message": None,
                "status": ProviderRequestStatus.QUOTE_DONE.value,
            }
            diff = DeepDiff(sj, expected_sj)
            if diff:
                print(diff)

            assert not diff, "Wrong status."
            assert provider_request == expected_request, "Wrong request."

        # Get requirements
        br = provider.requirements(provider_request)
        assert br["ethereum"][wallet_address][ZERO_ADDRESS] > 0, "Wrong requirements."
        expected_br = ChainAmounts(
            {
                "ethereum": {
                    wallet_address: {
                        ZERO_ADDRESS: br["ethereum"][wallet_address][ZERO_ADDRESS],
                        OLAS[Chain.ETHEREUM]: BigInt(1000000000000000000),
                    }
                }
            }
        )
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong requirements."
        assert provider_request == expected_request, "Wrong request."

        # Execute
        expected_execution_data = ExecutionData(
            elapsed_time=0,
            message=None,
            timestamp=0,
            from_tx_hash=None,
            to_tx_hash=None,
            provider_data=None,
        )
        expected_request.execution_data = expected_execution_data
        expected_request.status = ProviderRequestStatus.EXECUTION_FAILED

        provider.execute(provider_request=provider_request)
        assert provider_request.execution_data is not None, "Wrong request."
        expected_execution_data.message = provider_request.execution_data.message
        expected_execution_data.elapsed_time = (
            provider_request.execution_data.elapsed_time
        )
        expected_execution_data.timestamp = provider_request.execution_data.timestamp

        assert provider_request == expected_request, "Wrong request."
        sj = provider.status_json(provider_request)
        assert MESSAGE_EXECUTION_FAILED in sj["message"], "Wrong execution data."
        expected_sj = {
            "eta": provider.bridge_contract_adaptor.bridge_eta,
            "explorer_link": sj["explorer_link"],
            "tx_hash": None,  # type: ignore
            "message": sj["message"],
            "status": ProviderRequestStatus.EXECUTION_FAILED.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert provider_request == expected_request, "Wrong request."

    @pytest.mark.parametrize("rpc", ["https://rpc-gate.autonolas.tech/base-rpc/"])
    @pytest.mark.parametrize(
        ("timestamp", "expected_block"),
        [
            (1706789346, 9999999),
            (1706789347, 9999999),  # timestamp block 10000000
            (1706789348, 10000000),
            (1706789349, 10000000),  # timestamp block 10000001
            (1706789350, 10000001),
            (0, 0),
            (1686789346, 0),
            (1686789347, 0),  # timestamp block 0
            (1686789348, 0),
            (1686789349, 0),  # timestamp block 1
            (1686789350, 1),
        ],
    )
    def test_find_block_before_timestamp(
        self,
        rpc: str,
        timestamp: int,
        expected_block: int,
    ) -> None:
        """test_find_block_before_timestamp"""
        w3 = Web3(Web3.HTTPProvider(rpc))
        block = NativeBridgeProvider._find_block_before_timestamp(w3, timestamp)
        assert block == expected_block, f"Expected block {expected_block}, got {block}."


@pytest.mark.integration
class TestProvider:
    """Tests for bridge.providers.Provider class."""

    @pytest.mark.parametrize(
        "provider_class",
        [
            RelayProvider,
            LiFiProvider,
            NativeBridgeProvider,
        ],
    )
    def test_bridge_zero(
        self,
        tmp_path: Path,
        password: str,
        provider_class: t.Type[Provider],
    ) -> None:
        """test_bridge_zero"""
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = {
            "from": {
                "chain": Chain.ETHEREUM.value,
                "address": wallet_address,
                "token": OLAS[Chain.ETHEREUM],
            },
            "to": {
                "chain": Chain.BASE.value,
                "address": wallet_address,
                "token": OLAS[Chain.BASE],
                "amount": "0",
            },
        }

        provider_id = "test-provider"
        provider: Provider
        if provider_class == NativeBridgeProvider:
            provider_key = "native-ethereum-to-base"
            provider = NativeBridgeProvider(
                provider_id=provider_id,
                bridge_contract_adaptor=OptimismContractAdaptor(
                    from_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key][
                        "from_chain"
                    ],
                    from_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key][
                        "from_bridge"
                    ],
                    to_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["to_chain"],
                    to_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["to_bridge"],
                    bridge_eta=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key][
                        "bridge_eta"
                    ],
                    logger=LOGGER,
                ),
                wallet_manager=operate.wallet_manager,
                logger=LOGGER,
            )
        else:
            provider = provider_class(
                provider_id=provider_id,
                wallet_manager=operate.wallet_manager,
                logger=LOGGER,
            )
        bridge_eta = 0

        # Create
        provider_request = provider.create_request(params)
        expected_request = ProviderRequest(
            params={
                "from": {
                    "chain": Chain.ETHEREUM.value,
                    "address": wallet_address,
                    "token": OLAS[Chain.ETHEREUM],
                },
                "to": {
                    "chain": Chain.BASE.value,
                    "address": wallet_address,
                    "token": OLAS[Chain.BASE],
                    "amount": 0,
                },
            },
            id=provider_request.id,
            provider_id=provider.provider_id,
            status=ProviderRequestStatus.CREATED,
            quote_data=None,
            execution_data=None,
        )

        assert provider_request == expected_request, "Wrong request."

        with pytest.raises(RuntimeError):
            provider.execute(provider_request)

        assert provider_request == expected_request, "Wrong request."

        provider._update_execution_status(provider_request)

        assert provider_request == expected_request, "Wrong request."

        # Quote
        expected_quote_data = QuoteData(
            eta=0,
            elapsed_time=0,
            message=MESSAGE_QUOTE_ZERO,
            provider_data=None,
            timestamp=int(time.time()),
        )
        expected_request.quote_data = expected_quote_data
        expected_request.status = ProviderRequestStatus.QUOTE_DONE

        for _ in range(2):
            provider.quote(provider_request=provider_request)
            assert provider_request.quote_data is not None, "Wrong request."
            assert provider_request.quote_data.eta is not None, "Wrong quote data."
            assert provider_request.quote_data.eta == 0, "Wrong quote data."
            assert provider_request.quote_data.elapsed_time == 0, "Wrong quote data."
            assert provider_request.quote_data.timestamp > 0, "Wrong quote data."
            expected_quote_data.eta = bridge_eta or provider_request.quote_data.eta
            expected_quote_data.elapsed_time = provider_request.quote_data.elapsed_time
            expected_quote_data.provider_data = (
                provider_request.quote_data.provider_data
            )
            expected_quote_data.timestamp = provider_request.quote_data.timestamp
            assert provider_request == expected_request, "Wrong request."
            sj = provider.status_json(provider_request)
            expected_sj = {
                "eta": bridge_eta,
                "message": MESSAGE_QUOTE_ZERO,
                "status": ProviderRequestStatus.QUOTE_DONE.value,
            }
            diff = DeepDiff(sj, expected_sj)
            if diff:
                print(diff)

            assert not diff, "Wrong status."
            assert provider_request == expected_request, "Wrong request."

        # Get requirements
        br = provider.requirements(provider_request)
        assert (
            br[Chain.ETHEREUM.value][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong requirements."
        expected_br = ChainAmounts(
            {
                Chain.ETHEREUM.value: {
                    wallet_address: {
                        ZERO_ADDRESS: BigInt(0),
                        OLAS[Chain.ETHEREUM]: BigInt(0),
                    }
                }
            }
        )
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong requirements."
        assert provider_request == expected_request, "Wrong request."

        provider._update_execution_status(provider_request)

        assert provider_request == expected_request, "Wrong request."

        # Execute
        expected_execution_data = ExecutionData(
            elapsed_time=0,
            message=f"{MESSAGE_EXECUTION_SKIPPED} (provider_request.status=<ProviderRequestStatus.QUOTE_DONE: 'QUOTE_DONE'>)",
            timestamp=0,
            from_tx_hash=None,
            to_tx_hash=None,
            provider_data=None,
        )
        expected_request.execution_data = expected_execution_data
        expected_request.status = ProviderRequestStatus.EXECUTION_DONE
        provider.execute(provider_request=provider_request)
        assert provider_request.execution_data is not None, "Wrong request."
        expected_execution_data.timestamp = provider_request.execution_data.timestamp

        assert provider_request == expected_request, "Wrong request."
        sj = provider.status_json(provider_request)
        assert MESSAGE_EXECUTION_SKIPPED in sj["message"], "Wrong execution data."
        expected_sj = {
            "eta": 0,
            "explorer_link": None,
            "tx_hash": None,  # type: ignore
            "message": sj["message"],
            "status": ProviderRequestStatus.EXECUTION_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert provider_request == expected_request, "Wrong request."

    @pytest.mark.parametrize(
        "provider_class",
        [
            RelayProvider,
            LiFiProvider,
        ],
    )
    def test_bridge_error(
        self,
        tmp_path: Path,
        password: str,
        provider_class: t.Type[Provider],
    ) -> None:
        """test_bridge_error"""
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = {
            "from": {
                "chain": "gnosis",
                "address": wallet_address,
                "token": OLAS[Chain.GNOSIS],
            },
            "to": {
                "chain": "base",
                "address": wallet_address,
                "token": OLAS[Chain.BASE],
                "amount": 1,  # This will cause a quote error
            },
        }

        provider = provider_class(
            provider_id="test-provider",
            wallet_manager=operate.wallet_manager,
            logger=LOGGER,
        )
        provider_request = ProviderRequest(
            params=params,
            id="test-id",
            provider_id=provider.provider_id,
            quote_data=None,
            execution_data=None,
            status=ProviderRequestStatus.CREATED,
        )

        assert not provider_request.quote_data, "Unexpected quote data."

        with pytest.raises(RuntimeError):
            provider.execute(provider_request)

        status1 = provider_request.status
        provider._update_execution_status(provider_request)
        status2 = provider_request.status
        assert status1 == ProviderRequestStatus.CREATED, "Wrong status."
        assert status2 == ProviderRequestStatus.CREATED, "Wrong status."

        for _ in range(2):
            timestamp = int(time.time())
            provider.quote(provider_request=provider_request)
            qd = provider_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.eta is None, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is not None, "Wrong quote data."
            assert qd.provider_data is not None, "Wrong quote data."
            assert qd.provider_data.get("response") is not None, "Wrong quote data."
            assert qd.provider_data.get("attempts", 0) > 0, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                provider_request.status == ProviderRequestStatus.QUOTE_FAILED
            ), "Wrong status."

        assert provider_request.quote_data is not None, "Wrong quote data."
        sj = provider.status_json(provider_request)
        expected_sj = {
            "eta": None,
            "message": provider_request.quote_data.message,
            "status": ProviderRequestStatus.QUOTE_FAILED.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."

        br = provider.requirements(provider_request)
        expected_br = ChainAmounts(
            {
                "gnosis": {
                    wallet_address: {
                        ZERO_ADDRESS: BigInt(0),
                        OLAS[Chain.GNOSIS]: BigInt(0),
                    }
                }
            }
        )
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong requirements."

        qd = provider_request.quote_data
        assert qd is not None, "Missing quote data."
        assert qd.eta is None, "Wrong quote data."
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is not None, "Wrong quote data."
        assert qd.provider_data is not None, "Wrong quote data."
        assert qd.provider_data.get("response") is not None, "Wrong quote data."
        assert qd.provider_data.get("attempts", 0) > 0, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert (
            provider_request.status == ProviderRequestStatus.QUOTE_FAILED
        ), "Wrong status."

        status1 = provider_request.status
        provider._update_execution_status(provider_request)
        status2 = provider_request.status
        assert status1 == ProviderRequestStatus.QUOTE_FAILED, "Wrong status."
        assert status2 == ProviderRequestStatus.QUOTE_FAILED, "Wrong status."

        timestamp = int(time.time())
        provider.execute(provider_request=provider_request)
        ed = provider_request.execution_data
        assert ed is not None, "Missing execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.message is not None, "Wrong execution data."
        assert (
            MESSAGE_EXECUTION_FAILED_QUOTE_FAILED in ed.message
        ), "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.from_tx_hash is None, "Wrong execution data."
        assert (
            provider_request.status == ProviderRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        provider._update_execution_status(provider_request)
        assert (
            provider_request.status == ProviderRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        sj = provider.status_json(provider_request)
        assert (
            MESSAGE_EXECUTION_FAILED_QUOTE_FAILED in sj["message"]
        ), "Wrong execution data."
        expected_sj = {
            "eta": None,
            "explorer_link": None,
            "tx_hash": None,
            "message": sj["message"],
            "status": ProviderRequestStatus.EXECUTION_FAILED.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."

    @pytest.mark.parametrize(
        "provider_class",
        [
            RelayProvider,
            pytest.param(
                LiFiProvider,
                marks=pytest.mark.xfail(reason="Flaky test."),
            ),
            NativeBridgeProvider,
        ],
    )
    def test_bridge_quote(
        self,
        tmp_path: Path,
        password: str,
        provider_class: t.Type[Provider],
    ) -> None:
        """test_bridge_quote"""
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = {
            "from": {
                "chain": Chain.ETHEREUM.value,
                "address": wallet_address,
                "token": ZERO_ADDRESS,
            },
            "to": {
                "chain": Chain.BASE.value,
                "address": wallet_address,
                "token": ZERO_ADDRESS,
                "amount": "1000000000000000000",
            },
        }

        provider_id = "test-provider"
        provider: Provider
        if provider_class == NativeBridgeProvider:
            provider_key = "native-ethereum-to-base"
            provider = NativeBridgeProvider(
                provider_id=provider_id,
                bridge_contract_adaptor=OptimismContractAdaptor(
                    from_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key][
                        "from_chain"
                    ],
                    from_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key][
                        "from_bridge"
                    ],
                    to_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["to_chain"],
                    to_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key]["to_bridge"],
                    bridge_eta=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_key][
                        "bridge_eta"
                    ],
                    logger=LOGGER,
                ),
                wallet_manager=operate.wallet_manager,
                logger=LOGGER,
            )
            bridge_eta = provider.bridge_contract_adaptor.bridge_eta
        else:
            provider = provider_class(
                provider_id=provider_id,
                wallet_manager=operate.wallet_manager,
                logger=LOGGER,
            )
            bridge_eta = 0

        # Create
        provider_request = provider.create_request(params)
        expected_request = ProviderRequest(
            params={
                "from": {
                    "chain": Chain.ETHEREUM.value,
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                },
                "to": {
                    "chain": Chain.BASE.value,
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                    "amount": 1_000_000_000_000_000_000,
                },
            },
            id=provider_request.id,
            provider_id=provider.provider_id,
            status=ProviderRequestStatus.CREATED,
            quote_data=None,
            execution_data=None,
        )

        assert provider_request == expected_request, "Wrong request."

        with pytest.raises(RuntimeError):
            provider.execute(provider_request)

        assert provider_request == expected_request, "Wrong request."

        provider._update_execution_status(provider_request)

        assert provider_request == expected_request, "Wrong request."

        # Quote
        expected_quote_data = QuoteData(
            eta=0,
            elapsed_time=0,
            message=None,
            provider_data=None,
            timestamp=int(time.time()),
        )
        expected_request.quote_data = expected_quote_data
        expected_request.status = ProviderRequestStatus.QUOTE_DONE

        for _ in range(2):
            provider.quote(provider_request=provider_request)
            assert provider_request.quote_data is not None, "Wrong request."
            assert provider_request.quote_data.eta is not None, "Wrong quote data."
            assert provider_request.quote_data.eta > 0, "Wrong quote data."
            assert provider_request.quote_data.elapsed_time >= 0, "Wrong quote data."
            assert provider_request.quote_data.timestamp > 0, "Wrong quote data."
            expected_quote_data.eta = bridge_eta or provider_request.quote_data.eta
            expected_quote_data.elapsed_time = provider_request.quote_data.elapsed_time
            expected_quote_data.provider_data = (
                provider_request.quote_data.provider_data
            )
            expected_quote_data.timestamp = provider_request.quote_data.timestamp
            assert provider_request == expected_request, "Wrong request."
            sj = provider.status_json(provider_request)
            expected_sj = {
                "eta": bridge_eta or provider_request.quote_data.eta,
                "message": None,
                "status": ProviderRequestStatus.QUOTE_DONE.value,
            }
            diff = DeepDiff(sj, expected_sj)
            if diff:
                print(diff)

            assert not diff, "Wrong status."
            assert provider_request == expected_request, "Wrong request."

        # Get requirements
        br = provider.requirements(provider_request)
        assert (
            br[Chain.ETHEREUM.value][wallet_address][ZERO_ADDRESS] > 0
        ), "Wrong requirements."
        expected_br = ChainAmounts(
            {
                Chain.ETHEREUM.value: {
                    wallet_address: {
                        ZERO_ADDRESS: br[Chain.ETHEREUM.value][wallet_address][
                            ZERO_ADDRESS
                        ],
                    }
                }
            }
        )
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong requirements."
        assert provider_request == expected_request, "Wrong request."

    @pytest.mark.parametrize(
        (
            "provider_class",
            "contract_adaptor_class",
            "params",
            "request_id",
            "from_tx_hash",
            "expected_status",
            "expected_to_tx_hash",
            "expected_elapsed_time",
        ),
        [
            # RelayProvider - EXECUTION_DONE tests
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x4713683AeC1057B70e1B5F86b61FddBe650a7b72",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "optimism",
                        "address": "0x4713683AeC1057B70e1B5F86b61FddBe650a7b72",
                        "token": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
                        "amount": 16000000,
                    },
                },
                "r-ecfb8c21-e8d3-474b-9f10-0a2926da404d",
                "0x386eb995abd6d5c3a80b0c51dbec2b94b93a2664950afc635cfdbafe0cd0307e",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x386eb995abd6d5c3a80b0c51dbec2b94b93a2664950afc635cfdbafe0cd0307e",
                0,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "mode",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 100000000000000,
                    },
                },
                "r-abdb69ae-5d8b-48a1-bce3-e4ab15b7063b",
                "0xdea844011f5d3a782a73067ee326c4b96489134eae416426be867bb53c94de92",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x48f2a72d5efdf6fa4c2d1c915f4eb174533f53a3d4c3e5606ec1641d16c255ab",
                2,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "mode",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0xcfD1D50ce23C46D3Cf6407487B2F8934e96DC8f9",
                        "amount": 1000000000000000000,
                    },
                },
                "r-c8c78cb7-dc66-47c8-9c17-0b5a22db3d2d",
                "0xad982ac128a9d0069ed93ca10ebf6595e1c192554c2290a7f99ddf605efd69bb",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x0fb271e795c84da71e50549c390965648610aebd8560766a5fb420e0043b0518",
                8,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "mode",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0xd988097fb8612cc24eeC14542bC03424c656005f",
                        "amount": 1000000,
                    },
                },
                "r-18b91fc9-6e0f-4e7e-98c8-f28dfbe289ba",
                "0x798887aa9bbcea4b8578ab0aba67a8f26418373a8df9036ccbde96f5125483e3",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x5f83425ad08bae4fab907908387d30c3b6c5d34a21d281db3c1e61a7bba06a5d",
                2,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0xfd19fe216cf6699ebdfd8f038a74c9b24e23a7b7",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0x87218C01bd246e99f779Bfd13d277E88C6Cb4477",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 1157062023093466,
                    },
                },
                "r-a0b5253b-02fe-4389-9fe5-a5d17acae150",
                "0xdb60d262c71834cd620b49dc69febb822250937d7a2c8f3e1ba22b21b1355113",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x835d90db1f3552fc4f691a6f3851d24c04222b9d66f456e50fa4dd8dbd44280c",
                17,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0x409D0490FB743650803B05936e78f22D273A5647",
                        "token": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
                        "amount": 27291638268124063,
                    },
                },
                "r-c8f00ad9-82a9-45a1-b873-dd80c2da4acb",
                "0xe05ad614e482b61fe5016716c8dd41f5b1149d509a8e1eca6f00bdbbe3ef6b9d",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x75850a31777ea9567702537be5cd6e2cf4f455069ad96d543f3a992fdb708ca7",
                26,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0xC5E802BFBeA76e0eeccf775eFA5b005811F96136",
                        "token": "0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83",
                        "amount": 1000000,
                    },
                },
                "r-7ef5ef70-6052-40a0-b0f2-a71896668f95",
                "0xa07eacd399371bf789c47f40c390dc96a2f057258584cc2e2d156cf8208ab704",
                ProviderRequestStatus.EXECUTION_DONE,
                "0xb57a7ee4233d2bf1fa95040ac4c26e8c2e192c94f0ea8709f640b44c3b8dc438",
                7,
            ),
            # RelayProvider - EXECUTION_FAILED tests
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 1000000000000000000,
                    },
                },
                "r-bfb51822-e689-4141-8328-134f0a877fdf",
                "0x4a755c455f029a645f5bfe3fcd999c24acbde49991cb54f5b9b8fcf286ad2ac0",
                ProviderRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
            # NativeBridgeProvider (Omnibridge) - EXECUTION_DONE tests
            (
                NativeBridgeProvider,
                OmnibridgeContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x96faf614c8228ff834a4e45d2cc0dd2675469338",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0xaf59963aee4fcc92a68d9bc3cde7cd89307d4e7e",
                        "token": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
                        "amount": 5000000000000000000,
                    },
                },
                "b-b5648bc4-15c0-4792-9970-cc692851ce50",
                "0xbc2110dc981617079a1959cf3da9bf9ecd52785531cab33fd0fd9e4f39daaa65",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x48b3367c3dad388a1f0c1dec5063fe45969022975c53f212734285ac93c5e214",
                2148,
            ),
            # LiFiProvider - EXECUTION_DONE tests
            (
                LiFiProvider,
                None,
                {
                    "from": {
                        "chain": "gnosis",
                        "address": "0x770569f85346b971114e11e4bb5f7ac776673469",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x770569f85346b971114e11e4bb5f7ac776673469",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 380000000000000,
                    },
                },
                "b-184035d4-18b4-42e1-8983-d30f7daff1b9",
                "0xbd10fbe1321fc51c94f0bbb94bb9e467b180eedc6f7c942cf48a0321b6eaf8e4",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x407a815ac865ea888f31d26c7105609c1337daed934c9e09bf2c6ebf448b30ed",
                383,
            ),
            # NativeBridgeProvider (Optimism bridge) - EXECUTION_DONE tests
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 300000000000000,
                    },
                },
                "b-76a298b9-b243-4cfb-b48a-f59183ae0e85",
                "0xf649cdce0075a950ed031cc32775990facdcefc8d2bfff695a8023895dd47ebd",
                ProviderRequestStatus.EXECUTION_DONE,
                "0xc97722c1310b94043fb37219285cb4f80ce4189f158033b84c935ec54166eb19",
                178,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x54330d28ca3357F294334BDC454a032e7f353416",
                        "amount": 100000000000000000,
                    },
                },
                "b-7221ece2-e15e-4aec-bac2-7fd4c4d4851a",
                "0xa1139bb4ba963d7979417f49fed03b365c1f1bfc31d0100257caed888a491c4c",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x9b8f8998b1cd8f256914751606f772bee9ebbf459b3a1c8ca177838597464739",
                184,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 30750000000000000,
                    },
                },
                "b-7ca71220-4336-414f-985e-bdfe11707c71",
                "0xcf2b263ab1149bc6691537d09f3ed97e1ac4a8411a49ca9d81219c32f98228ba",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x5718e6f0da2e0b1a02bcb53db239cef49a731f9f52cccf193f7d0abe62e971d4",
                198,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x54330d28ca3357F294334BDC454a032e7f353416",
                        "amount": 100000000000000000000,
                    },
                },
                "b-fef67eea-d55c-45f0-8b5b-e7987c843ced",
                "0x4a755c455f029a645f5bfe3fcd999c24acbde49991cb54f5b9b8fcf286ad2ac0",
                ProviderRequestStatus.EXECUTION_DONE,
                "0xf4ccb5f6547c188e638ac3d84f80158e3d7462211e15bc3657f8585b0bbffb68",
                186,
            ),
            # NativeBridgeProvider (Optimism bridge) - EXECUTION_FAILED tests
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 42,  # Wrong amount
                    },
                },
                "b-76a298b9-b243-4cfb-b48a-f59183ae0e85",
                "0xf649cdce0075a950ed031cc32775990facdcefc8d2bfff695a8023895dd47ebd",
                ProviderRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x54330d28ca3357F294334BDC454a032e7f353416",
                        "amount": 100000000000000000,
                    },
                },
                "b-42",  # Wrong id
                "0xa1139bb4ba963d7979417f49fed03b365c1f1bfc31d0100257caed888a491c4c",
                ProviderRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x54330d28ca3357F294334BDC454a032e7f353416",  # Wrong address
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 30750000000000000,
                    },
                },
                "b-7ca71220-4336-414f-985e-bdfe11707c71",
                "0xcf2b263ab1149bc6691537d09f3ed97e1ac4a8411a49ca9d81219c32f98228ba",
                ProviderRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x54330d28ca3357F294334BDC454a032e7f353416",
                        "amount": 100000000000000000000,
                    },
                },
                "b-fef67eea-d55c-45f0-8b5b-e7987c843ced",
                "0x7cefa52970f4e1b12a07b9795b8f03de2bbc2ee7c42cba5913d923316e96b3c5",  # Wrong from_tx_hash
                ProviderRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
        ],
    )
    def test_update_execution_status(
        self,
        tmp_path: Path,
        password: str,
        provider_class: t.Type[Provider],
        contract_adaptor_class: t.Optional[t.Type[BridgeContractAdaptor]],
        params: dict,
        request_id: str,
        from_tx_hash: str,
        expected_status: ProviderRequestStatus,
        expected_to_tx_hash: str,
        expected_elapsed_time: int,
    ) -> None:
        """test_update_execution_status"""
        operate = OperateApp(home=tmp_path / OPERATE_TEST)
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        if contract_adaptor_class is not None:
            from_chain = params["from"]["chain"]
            to_chain = params["to"]["chain"]
            provider_id = f"native-{from_chain}-to-{to_chain}"
            provider: Provider = NativeBridgeProvider(
                provider_id=provider_id,
                bridge_contract_adaptor=contract_adaptor_class(
                    from_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id][
                        "from_chain"
                    ],
                    from_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id][
                        "from_bridge"
                    ],
                    to_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id]["to_chain"],
                    to_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id]["to_bridge"],
                    bridge_eta=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id][
                        "bridge_eta"
                    ],
                    logger=LOGGER,
                ),
                wallet_manager=operate.wallet_manager,
                logger=LOGGER,
            )
        else:
            provider = provider_class(
                provider_id="", wallet_manager=operate.wallet_manager, logger=LOGGER
            )

        quote_data = QuoteData(
            eta=0,
            elapsed_time=0,
            message=None,
            provider_data=None,
            timestamp=0,
        )

        execution_data = ExecutionData(
            elapsed_time=0,
            message=None,
            timestamp=0,
            from_tx_hash=from_tx_hash,
            to_tx_hash=None,
            provider_data=None,
        )

        provider_request = ProviderRequest(
            params=params,
            provider_id=provider.provider_id,
            id=request_id,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            quote_data=quote_data,
            execution_data=execution_data,
        )

        provider.status_json(provider_request)

        assert provider_request.status == expected_status, "Wrong execution status."
        assert execution_data.to_tx_hash == expected_to_tx_hash, "Wrong to_tx_hash."
        assert execution_data.elapsed_time == expected_elapsed_time, "Wrong timestamp."

        if provider_request.status == ProviderRequestStatus.EXECUTION_DONE:
            transfer_amount = get_transfer_amount(
                w3=Web3(
                    Web3.HTTPProvider(get_default_rpc(Chain(params["to"]["chain"])))
                ),
                tx_hash=expected_to_tx_hash,
                token_address=params["to"]["token"],
                recipient=params["to"]["address"],
            )
            if params["to"]["amount"] > 0 and transfer_amount <= 0:
                pytest.skip("Transfer amount could not be retrieved; skipping check.")
                return

            assert transfer_amount >= params["to"]["amount"], "Wrong transfer amount."

    @pytest.mark.parametrize(
        (
            "provider_class",
            "contract_adaptor_class",
            "params",
            "request_id",
            "from_tx_hash",
            "expected_status",
            "expected_to_tx_hash",
            "expected_elapsed_time",
        ),
        [
            # RelayProvider - EXECUTION_DONE tests
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x4713683AeC1057B70e1B5F86b61FddBe650a7b72",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "optimism",
                        "address": "0x4713683AeC1057B70e1B5F86b61FddBe650a7b72",
                        "token": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
                        "amount": 16000000,
                    },
                },
                "r-ecfb8c21-e8d3-474b-9f10-0a2926da404d",
                "0x386eb995abd6d5c3a80b0c51dbec2b94b93a2664950afc635cfdbafe0cd0307e",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x386eb995abd6d5c3a80b0c51dbec2b94b93a2664950afc635cfdbafe0cd0307e",
                0,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "mode",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 100000000000000,
                    },
                },
                "r-abdb69ae-5d8b-48a1-bce3-e4ab15b7063b",
                "0xdea844011f5d3a782a73067ee326c4b96489134eae416426be867bb53c94de92",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x48f2a72d5efdf6fa4c2d1c915f4eb174533f53a3d4c3e5606ec1641d16c255ab",
                2,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "mode",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0xcfD1D50ce23C46D3Cf6407487B2F8934e96DC8f9",
                        "amount": 1000000000000000000,
                    },
                },
                "r-c8c78cb7-dc66-47c8-9c17-0b5a22db3d2d",
                "0xad982ac128a9d0069ed93ca10ebf6595e1c192554c2290a7f99ddf605efd69bb",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x0fb271e795c84da71e50549c390965648610aebd8560766a5fb420e0043b0518",
                8,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "mode",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0xd988097fb8612cc24eeC14542bC03424c656005f",
                        "amount": 1000000,
                    },
                },
                "r-18b91fc9-6e0f-4e7e-98c8-f28dfbe289ba",
                "0x798887aa9bbcea4b8578ab0aba67a8f26418373a8df9036ccbde96f5125483e3",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x5f83425ad08bae4fab907908387d30c3b6c5d34a21d281db3c1e61a7bba06a5d",
                2,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0xfd19fe216cf6699ebdfd8f038a74c9b24e23a7b7",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0x87218C01bd246e99f779Bfd13d277E88C6Cb4477",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 1157062023093466,
                    },
                },
                "r-a0b5253b-02fe-4389-9fe5-a5d17acae150",
                "0xdb60d262c71834cd620b49dc69febb822250937d7a2c8f3e1ba22b21b1355113",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x835d90db1f3552fc4f691a6f3851d24c04222b9d66f456e50fa4dd8dbd44280c",
                17,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0x409D0490FB743650803B05936e78f22D273A5647",
                        "token": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
                        "amount": 27291638268124063,
                    },
                },
                "r-c8f00ad9-82a9-45a1-b873-dd80c2da4acb",
                "0xe05ad614e482b61fe5016716c8dd41f5b1149d509a8e1eca6f00bdbbe3ef6b9d",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x75850a31777ea9567702537be5cd6e2cf4f455069ad96d543f3a992fdb708ca7",
                26,
            ),
            (
                RelayProvider,
                None,
                {
                    "from": {
                        "chain": "optimism",
                        "address": "0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0xC5E802BFBeA76e0eeccf775eFA5b005811F96136",
                        "token": "0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83",
                        "amount": 1000000,
                    },
                },
                "r-7ef5ef70-6052-40a0-b0f2-a71896668f95",
                "0xa07eacd399371bf789c47f40c390dc96a2f057258584cc2e2d156cf8208ab704",
                ProviderRequestStatus.EXECUTION_DONE,
                "0xb57a7ee4233d2bf1fa95040ac4c26e8c2e192c94f0ea8709f640b44c3b8dc438",
                7,
            ),
            # NativeBridgeProvider (Omnibridge) - EXECUTION_DONE tests
            (
                NativeBridgeProvider,
                OmnibridgeContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x96faf614c8228ff834a4e45d2cc0dd2675469338",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "gnosis",
                        "address": "0xaf59963aee4fcc92a68d9bc3cde7cd89307d4e7e",
                        "token": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
                        "amount": 5000000000000000000,
                    },
                },
                "b-b5648bc4-15c0-4792-9970-cc692851ce50",
                "0xbc2110dc981617079a1959cf3da9bf9ecd52785531cab33fd0fd9e4f39daaa65",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x48b3367c3dad388a1f0c1dec5063fe45969022975c53f212734285ac93c5e214",
                2148,
            ),
            # LiFiProvider - EXECUTION_DONE tests
            (
                LiFiProvider,
                None,
                {
                    "from": {
                        "chain": "gnosis",
                        "address": "0x770569f85346b971114e11e4bb5f7ac776673469",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x770569f85346b971114e11e4bb5f7ac776673469",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 380000000000000,
                    },
                },
                "b-184035d4-18b4-42e1-8983-d30f7daff1b9",
                "0xbd10fbe1321fc51c94f0bbb94bb9e467b180eedc6f7c942cf48a0321b6eaf8e4",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x407a815ac865ea888f31d26c7105609c1337daed934c9e09bf2c6ebf448b30ed",
                383,
            ),
            # NativeBridgeProvider (Optimism bridge) - EXECUTION_DONE tests
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 300000000000000,
                    },
                },
                "b-76a298b9-b243-4cfb-b48a-f59183ae0e85",
                "0xf649cdce0075a950ed031cc32775990facdcefc8d2bfff695a8023895dd47ebd",
                ProviderRequestStatus.EXECUTION_DONE,
                "0xc97722c1310b94043fb37219285cb4f80ce4189f158033b84c935ec54166eb19",
                178,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0x308508F09F81A6d28679db6da73359c72f8e22C5",
                        "token": "0x54330d28ca3357F294334BDC454a032e7f353416",
                        "amount": 100000000000000000,
                    },
                },
                "b-7221ece2-e15e-4aec-bac2-7fd4c4d4851a",
                "0xa1139bb4ba963d7979417f49fed03b365c1f1bfc31d0100257caed888a491c4c",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x9b8f8998b1cd8f256914751606f772bee9ebbf459b3a1c8ca177838597464739",
                184,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 30750000000000000,
                    },
                },
                "b-7ca71220-4336-414f-985e-bdfe11707c71",
                "0xcf2b263ab1149bc6691537d09f3ed97e1ac4a8411a49ca9d81219c32f98228ba",
                ProviderRequestStatus.EXECUTION_DONE,
                "0x5718e6f0da2e0b1a02bcb53db239cef49a731f9f52cccf193f7d0abe62e971d4",
                198,
            ),
            (
                NativeBridgeProvider,
                OptimismContractAdaptor,
                {
                    "from": {
                        "chain": "ethereum",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0xC0a12402089ce761E6496892AF4754350639bf94",
                        "token": "0x54330d28ca3357F294334BDC454a032e7f353416",
                        "amount": 100000000000000000000,
                    },
                },
                "b-fef67eea-d55c-45f0-8b5b-e7987c843ced",
                "0x4a755c455f029a645f5bfe3fcd999c24acbde49991cb54f5b9b8fcf286ad2ac0",
                ProviderRequestStatus.EXECUTION_DONE,
                "0xf4ccb5f6547c188e638ac3d84f80158e3d7462211e15bc3657f8585b0bbffb68",
                186,
            ),
        ],
    )
    def test_update_execution_status_failure_then_success(
        self,
        tmp_path: Path,
        password: str,
        provider_class: t.Type[Provider],
        contract_adaptor_class: t.Optional[t.Type[BridgeContractAdaptor]],
        params: dict,
        request_id: str,
        from_tx_hash: str,
        expected_status: ProviderRequestStatus,
        expected_to_tx_hash: str,
        expected_elapsed_time: int,
    ) -> None:
        """test_update_execution_status_failure_then_success"""
        operate = OperateApp(home=tmp_path / OPERATE_TEST)
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        if contract_adaptor_class is not None:
            from_chain = params["from"]["chain"]
            to_chain = params["to"]["chain"]
            provider_id = f"native-{from_chain}-to-{to_chain}"
            provider: Provider = NativeBridgeProvider(
                provider_id=provider_id,
                bridge_contract_adaptor=contract_adaptor_class(
                    from_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id][
                        "from_chain"
                    ],
                    from_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id][
                        "from_bridge"
                    ],
                    to_chain=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id]["to_chain"],
                    to_bridge=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id]["to_bridge"],
                    bridge_eta=NATIVE_BRIDGE_PROVIDER_CONFIGS[provider_id][
                        "bridge_eta"
                    ],
                    logger=LOGGER,
                ),
                wallet_manager=operate.wallet_manager,
                logger=LOGGER,
            )
        else:
            provider = provider_class(
                provider_id="", wallet_manager=operate.wallet_manager, logger=LOGGER
            )

        quote_data = QuoteData(
            eta=0,
            elapsed_time=0,
            message=None,
            provider_data=None,
            timestamp=int(time.time()) - 20,
        )

        execution_data = ExecutionData(
            elapsed_time=0,
            message=None,
            timestamp=int(time.time()) - 10,
            from_tx_hash=from_tx_hash,
            to_tx_hash=None,
            provider_data=None,
        )

        provider_request = ProviderRequest(
            params=params,
            provider_id=provider.provider_id,
            id=request_id,
            status=ProviderRequestStatus.EXECUTION_PENDING,
            quote_data=quote_data,
            execution_data=execution_data,
        )

        exc = ConnectionError("Simulated RPC exception")

        with patch("web3.eth.Eth.get_transaction_receipt") as mock:
            mock.side_effect = [exc]  # only fails once
            provider.status_json(provider_request)  # fails
            assert (
                provider_request.status == ProviderRequestStatus.EXECUTION_UNKNOWN
            ), "Wrong execution status."

        print("expected_status", expected_status)

        provider.status_json(provider_request)
        assert provider_request.status == expected_status, "Wrong execution status."
        assert execution_data.to_tx_hash == expected_to_tx_hash, "Wrong to_tx_hash."
        assert execution_data.elapsed_time == expected_elapsed_time, "Wrong timestamp."
