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


import os
import time
import typing as t
from pathlib import Path

import pytest
from deepdiff import DeepDiff
from web3 import Web3

from operate.bridge.bridge import (  # MESSAGE_EXECUTION_SKIPPED,; MESSAGE_QUOTE_ZERO,
    BridgeRequest,
    LiFiBridgeProvider,
)
from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequestStatus,
    ExecutionData,
    MESSAGE_EXECUTION_FAILED,
    MESSAGE_EXECUTION_FAILED_QUOTE_FAILED,
    MESSAGE_EXECUTION_SKIPPED,
    MESSAGE_QUOTE_ZERO,
    QuoteData,
)
from operate.bridge.providers.native_bridge_provider import (
    NATIVE_BRIDGE_ENDPOINTS,
    NativeBridgeProvider,
)
from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger import DEFAULT_RPCS
from operate.ledger.profiles import OLAS
from operate.operate_types import Chain, LedgerType


ROOT_PATH = Path(__file__).resolve().parent
OPERATE = ".operate_test"
RUNNING_IN_CI = (
    os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    or os.getenv("CI", "").lower() == "true"
)


class TestLiFiBridge:
    """Tests for bridge.providers.LiFiBridgeProvider class."""

    def test_bridge_zero(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bridge_zero"""
        operate = OperateApp(
            home=tmp_path / OPERATE,
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
                "amount": 0,
            },
        }

        bridge = LiFiBridgeProvider(wallet_manager=operate.wallet_manager)
        bridge_request = BridgeRequest(
            params=params,
            bridge_provider_id=bridge.id(),
            id="test-id",
            quote_data=None,
            execution_data=None,
            status=BridgeRequestStatus.CREATED,
        )

        assert not bridge_request.quote_data, "Unexpected quote data."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        status1 = bridge_request.status
        bridge._update_execution_status(bridge_request)
        status2 = bridge_request.status
        assert status1 == BridgeRequestStatus.CREATED, "Wrong status."
        assert status2 == BridgeRequestStatus.CREATED, "Wrong status."

        for _ in range(2):
            timestamp = int(time.time())
            bridge.quote(bridge_request=bridge_request)
            qd = bridge_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time == 0, "Wrong quote data."
            assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
            assert qd.provider_data is None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        sj = bridge.status_json(bridge_request)
        expected_sj = {
            "message": MESSAGE_QUOTE_ZERO,
            "status": BridgeRequestStatus.QUOTE_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert bridge_request.quote_data is not None, "Missing quote data."

        br = bridge.bridge_requirements(bridge_request)
        expected_br = {
            "gnosis": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}}
        }
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge requirements."

        qd = bridge_request.quote_data
        assert qd is not None, "Missing quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time == 0, "Wrong quote data."
        assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
        assert qd.provider_data is None, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert bridge_request.status == BridgeRequestStatus.QUOTE_DONE, "Wrong status."

        status1 = bridge_request.status
        bridge._update_execution_status(bridge_request)
        status2 = bridge_request.status
        assert status1 == BridgeRequestStatus.QUOTE_DONE, "Wrong status."
        assert status2 == BridgeRequestStatus.QUOTE_DONE, "Wrong status."

        timestamp = int(time.time())
        bridge.execute(bridge_request=bridge_request)
        ed = bridge_request.execution_data
        assert ed is not None, "Missing execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.message is not None, "Wrong execution data."
        assert MESSAGE_EXECUTION_SKIPPED in ed.message, "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.from_tx_hash is None, "Wrong execution data."
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        bridge._update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        sj = bridge.status_json(bridge_request)
        assert MESSAGE_EXECUTION_SKIPPED in sj["message"], "Wrong execution data."
        expected_sj = {
            "explorer_link": sj["explorer_link"],
            "tx_hash": None,  # type: ignore
            "message": sj["message"],
            "status": BridgeRequestStatus.EXECUTION_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."

    def test_bridge_error(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bridge_error"""
        operate = OperateApp(
            home=tmp_path / OPERATE,
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

        bridge = LiFiBridgeProvider(wallet_manager=operate.wallet_manager)
        bridge_request = BridgeRequest(
            params=params,
            bridge_provider_id=bridge.id(),
            id="test-id",
            quote_data=None,
            execution_data=None,
            status=BridgeRequestStatus.CREATED,
        )

        assert not bridge_request.quote_data, "Unexpected quote data."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        status1 = bridge_request.status
        bridge._update_execution_status(bridge_request)
        status2 = bridge_request.status
        assert status1 == BridgeRequestStatus.CREATED, "Wrong status."
        assert status2 == BridgeRequestStatus.CREATED, "Wrong status."

        for _ in range(2):
            timestamp = int(time.time())
            bridge.quote(bridge_request=bridge_request)
            qd = bridge_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is not None, "Wrong quote data."
            assert qd.provider_data is not None, "Wrong quote data."
            assert qd.provider_data.get("response") is not None, "Wrong quote data."
            assert qd.provider_data.get("attempts", 0) > 0, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_FAILED
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge.status_json(bridge_request)
        expected_sj = {
            "message": bridge_request.quote_data.message,
            "status": BridgeRequestStatus.QUOTE_FAILED.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."

        br = bridge.bridge_requirements(bridge_request)
        expected_br = {
            "gnosis": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}}
        }
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge requirements."

        qd = bridge_request.quote_data
        assert qd is not None, "Missing quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is not None, "Wrong quote data."
        assert qd.provider_data is not None, "Wrong quote data."
        assert qd.provider_data.get("response") is not None, "Wrong quote data."
        assert qd.provider_data.get("attempts", 0) > 0, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert (
            bridge_request.status == BridgeRequestStatus.QUOTE_FAILED
        ), "Wrong status."

        status1 = bridge_request.status
        bridge._update_execution_status(bridge_request)
        status2 = bridge_request.status
        assert status1 == BridgeRequestStatus.QUOTE_FAILED, "Wrong status."
        assert status2 == BridgeRequestStatus.QUOTE_FAILED, "Wrong status."

        timestamp = int(time.time())
        bridge.execute(bridge_request=bridge_request)
        ed = bridge_request.execution_data
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
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        bridge._update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        sj = bridge.status_json(bridge_request)
        assert (
            MESSAGE_EXECUTION_FAILED_QUOTE_FAILED in sj["message"]
        ), "Wrong execution data."
        expected_sj = {
            "explorer_link": sj["explorer_link"],
            "tx_hash": None,
            "message": sj["message"],
            "status": BridgeRequestStatus.EXECUTION_FAILED.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."

    @pytest.mark.skipif(RUNNING_IN_CI, reason="Skip test on CI.")
    def test_bridge_quote(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bridge_quote"""
        operate = OperateApp(
            home=tmp_path / OPERATE,
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
                "amount": 1_000_000_000_000_000_000,
            },
        }

        bridge = LiFiBridgeProvider(wallet_manager=operate.wallet_manager)
        bridge_request = BridgeRequest(
            params=params,
            bridge_provider_id=bridge.id(),
            id="test-id",
            quote_data=None,
            execution_data=None,
            status=BridgeRequestStatus.CREATED,
        )

        assert not bridge_request.quote_data, "Unexpected quote data."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        status1 = bridge_request.status
        bridge._update_execution_status(bridge_request)
        status2 = bridge_request.status
        assert status1 == BridgeRequestStatus.CREATED, "Wrong status."
        assert status2 == BridgeRequestStatus.CREATED, "Wrong status."

        for _ in range(2):
            timestamp = int(time.time())
            bridge.quote(bridge_request=bridge_request)
            qd = bridge_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is None, "Wrong quote data."
            assert qd.provider_data is not None, "Wrong quote data."
            assert qd.provider_data.get("response") is not None, "Wrong quote data."
            assert qd.provider_data.get("attempts", 0) > 0, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge.status_json(bridge_request)
        expected_sj = {
            "message": bridge_request.quote_data.message,
            "status": BridgeRequestStatus.QUOTE_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert (
            bridge_request.quote_data.provider_data is not None
        ), "Missing quote data."

        quote = bridge_request.quote_data.provider_data.get("response")
        br = bridge.bridge_requirements(bridge_request)
        expected_br = {
            "gnosis": {
                wallet_address: {
                    ZERO_ADDRESS: br["gnosis"][wallet_address][ZERO_ADDRESS],
                    OLAS[Chain.GNOSIS]: int(quote["action"]["fromAmount"]),  # type: ignore
                }
            }
        }
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge requirements."

        qd = bridge_request.quote_data
        assert qd is not None, "Missing quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is None, "Wrong quote data."
        assert qd.provider_data is not None, "Wrong quote data."
        assert qd.provider_data.get("response") is not None, "Wrong quote data."
        assert qd.provider_data.get("attempts", 0) > 0, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert bridge_request.status == BridgeRequestStatus.QUOTE_DONE, "Wrong status."

        status1 = bridge_request.status
        bridge._update_execution_status(bridge_request)
        status2 = bridge_request.status
        assert status1 == BridgeRequestStatus.QUOTE_DONE, "Wrong status."
        assert status2 == BridgeRequestStatus.QUOTE_DONE, "Wrong status."


class TestNativeBridge:
    """Tests for bridge.providers.NativeBridgeProvider class."""

    # TODO: test existing executions: failed and done

    def test_bridge_zero(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bridge_zero"""
        operate = OperateApp(
            home=tmp_path / OPERATE,
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

        bridge = NativeBridgeProvider(wallet_manager=operate.wallet_manager)

        # Create
        bridge_request = bridge.create_request(params)
        expected_request = BridgeRequest(
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
            bridge_provider_id=NativeBridgeProvider.id(),
            id=bridge_request.id,
            status=BridgeRequestStatus.CREATED,
            quote_data=None,
            execution_data=None,
        )

        assert bridge_request == expected_request, "Wrong bridge request."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        assert bridge_request == expected_request, "Wrong bridge request."

        bridge._update_execution_status(bridge_request)

        assert bridge_request == expected_request, "Wrong bridge request."

        # Quote
        expected_quote_data = QuoteData(
            bridge_eta=NATIVE_BRIDGE_ENDPOINTS[Chain.ETHEREUM, Chain.BASE]["bridge_eta"],
            elapsed_time=0,
            message=MESSAGE_QUOTE_ZERO,
            provider_data=None,
            timestamp=int(time.time()),
        )
        expected_request.quote_data = expected_quote_data
        expected_request.status = BridgeRequestStatus.QUOTE_DONE

        for _ in range(2):
            bridge.quote(bridge_request=bridge_request)
            assert bridge_request.quote_data is not None, "Wrong bridge request."
            expected_quote_data.timestamp = bridge_request.quote_data.timestamp
            assert bridge_request == expected_request, "Wrong bridge request."
            sj = bridge.status_json(bridge_request)
            expected_sj = {
                "message": MESSAGE_QUOTE_ZERO,
                "status": BridgeRequestStatus.QUOTE_DONE.value,
            }
            diff = DeepDiff(sj, expected_sj)
            if diff:
                print(diff)

            assert not diff, "Wrong status."
            assert bridge_request == expected_request, "Wrong bridge request."

        # Get requirements
        br = bridge.bridge_requirements(bridge_request)
        expected_br = {
            "ethereum": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.ETHEREUM]: 0}}
        }
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge requirements."
        assert bridge_request == expected_request, "Wrong bridge request."

        # Execute
        expected_execution_data = ExecutionData(
            elapsed_time=0,
            message=f"{MESSAGE_EXECUTION_SKIPPED} (bridge_request.status=<BridgeRequestStatus.QUOTE_DONE: 'QUOTE_DONE'>)",
            timestamp=0,
            from_tx_hash=None,
            to_tx_hash=None,
        )
        expected_request.execution_data = expected_execution_data
        expected_request.status = BridgeRequestStatus.EXECUTION_DONE

        bridge.execute(bridge_request=bridge_request)
        assert bridge_request.execution_data is not None, "Wrong bridge request."
        expected_execution_data.timestamp = bridge_request.execution_data.timestamp

        assert bridge_request == expected_request, "Wrong bridge request."
        sj = bridge.status_json(bridge_request)
        assert MESSAGE_EXECUTION_SKIPPED in sj["message"], "Wrong execution data."
        expected_sj = {
            "explorer_link": sj["explorer_link"],
            "tx_hash": None,  # type: ignore
            "message": sj["message"],
            "status": BridgeRequestStatus.EXECUTION_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert bridge_request == expected_request, "Wrong bridge request."

    def test_bridge_execute_error(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bridge_execute_error"""

        DEFAULT_RPCS[Chain.ETHEREUM] = "https://rpc-gate.autonolas.tech/ethereum-rpc/"
        DEFAULT_RPCS[Chain.BASE] = "https://rpc-gate.autonolas.tech/base-rpc/"

        operate = OperateApp(
            home=tmp_path / OPERATE,
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

        bridge = NativeBridgeProvider(wallet_manager=operate.wallet_manager)

        # Create
        bridge_request = bridge.create_request(params)
        expected_request = BridgeRequest(
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
            bridge_provider_id=NativeBridgeProvider.id(),
            id=bridge_request.id,
            status=BridgeRequestStatus.CREATED,
            quote_data=None,
            execution_data=None,
        )

        assert bridge_request == expected_request, "Wrong bridge request."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        assert bridge_request == expected_request, "Wrong bridge request."

        bridge._update_execution_status(bridge_request)

        assert bridge_request == expected_request, "Wrong bridge request."

        # Quote
        expected_quote_data = QuoteData(
            bridge_eta=NATIVE_BRIDGE_ENDPOINTS[Chain.ETHEREUM, Chain.BASE]["bridge_eta"],
            elapsed_time=0,
            message=None,
            provider_data=None,
            timestamp=int(time.time()),
        )
        expected_request.quote_data = expected_quote_data
        expected_request.status = BridgeRequestStatus.QUOTE_DONE

        for _ in range(2):
            bridge.quote(bridge_request=bridge_request)
            assert bridge_request.quote_data is not None, "Wrong bridge request."
            expected_quote_data.timestamp = bridge_request.quote_data.timestamp
            assert bridge_request == expected_request, "Wrong bridge request."
            sj = bridge.status_json(bridge_request)
            expected_sj = {
                "message": None,
                "status": BridgeRequestStatus.QUOTE_DONE.value,
            }
            diff = DeepDiff(sj, expected_sj)
            if diff:
                print(diff)

            assert not diff, "Wrong status."
            assert bridge_request == expected_request, "Wrong bridge request."

        # Get requirements
        br = bridge.bridge_requirements(bridge_request)
        assert (
            br["ethereum"][wallet_address][ZERO_ADDRESS] > 0
        ), "Wrong bridge requirements."
        expected_br = {
            "ethereum": {
                wallet_address: {
                    ZERO_ADDRESS: br["ethereum"][wallet_address][ZERO_ADDRESS],
                    OLAS[Chain.ETHEREUM]: 1000000000000000000,
                }
            }
        }
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge requirements."
        assert bridge_request == expected_request, "Wrong bridge request."

        # Execute
        expected_execution_data = ExecutionData(
            elapsed_time=0,
            message=None,
            timestamp=0,
            from_tx_hash=None,
            to_tx_hash=None,
        )
        expected_request.execution_data = expected_execution_data
        expected_request.status = BridgeRequestStatus.EXECUTION_FAILED

        bridge.execute(bridge_request=bridge_request)
        assert bridge_request.execution_data is not None, "Wrong bridge request."
        expected_execution_data.message = bridge_request.execution_data.message
        expected_execution_data.elapsed_time = (
            bridge_request.execution_data.elapsed_time
        )
        expected_execution_data.timestamp = bridge_request.execution_data.timestamp

        assert bridge_request == expected_request, "Wrong bridge request."
        sj = bridge.status_json(bridge_request)
        assert MESSAGE_EXECUTION_FAILED in sj["message"], "Wrong execution data."
        expected_sj = {
            "explorer_link": sj["explorer_link"],
            "tx_hash": None,  # type: ignore
            "message": sj["message"],
            "status": BridgeRequestStatus.EXECUTION_FAILED.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert bridge_request == expected_request, "Wrong bridge request."

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


class TestBridgeProvider:
    """Tests for bridge.providers.BridgeProvider class."""

    @pytest.mark.parametrize(
        (
            "bridge_provider_class",
            "params",
            "request_id",
            "from_tx_hash",
            "expected_status",
            "expected_to_tx_hash",
            "expected_elapsed_time",
        ),
        [
            # LiFiBridgeProvider - EXECUTION_DONE tests
            (
                LiFiBridgeProvider,
                {
                    "from": {
                        "chain": "gnosis",
                        "address": "0xE95866Fa91ce81109aA900550133654A4795C20e",
                        "token": "0x0000000000000000000000000000000000000000",
                    },
                    "to": {
                        "chain": "base",
                        "address": "0xE95866Fa91ce81109aA900550133654A4795C20e",
                        "token": "0x0000000000000000000000000000000000000000",
                        "amount": 10000000000000,
                    },
                },
                "b-184035d4-18b4-42e1-8983-d30f7daff1b9",
                "0x333f5a51163576c9d90599bffa6b038dbec45f4f6f761b87e29ab59235403861",
                BridgeRequestStatus.EXECUTION_DONE,
                "0x6cd9176f1da953e4464adb8bdc81fbe4133ebcd1bb6aeac49946a38ff025e623",
                374,
            ),
            # NativeBridgeProvider - EXECUTION_DONE tests
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_DONE,
                "0xc97722c1310b94043fb37219285cb4f80ce4189f158033b84c935ec54166eb19",
                178,
            ),
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_DONE,
                "0x9b8f8998b1cd8f256914751606f772bee9ebbf459b3a1c8ca177838597464739",
                184,
            ),
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_DONE,
                "0x5718e6f0da2e0b1a02bcb53db239cef49a731f9f52cccf193f7d0abe62e971d4",
                198,
            ),
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_DONE,
                "0xf4ccb5f6547c188e638ac3d84f80158e3d7462211e15bc3657f8585b0bbffb68",
                186,
            ),
            # NativeBridgeProvider - EXECUTION_FAILED tests
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
            (
                NativeBridgeProvider,
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
                BridgeRequestStatus.EXECUTION_FAILED,
                None,
                0,
            ),
        ],
    )
    def test_update_execution_status(
        self,
        tmp_path: Path,
        password: str,
        bridge_provider_class: t.Type[BridgeProvider],
        params: dict,
        request_id: str,
        from_tx_hash: str,
        expected_status: BridgeRequestStatus,
        expected_to_tx_hash: str,
        expected_elapsed_time: int,
    ) -> None:
        """test_update_execution_status"""

        DEFAULT_RPCS[Chain.ETHEREUM] = "https://rpc-gate.autonolas.tech/ethereum-rpc/"
        DEFAULT_RPCS[Chain.BASE] = "https://rpc-gate.autonolas.tech/base-rpc/"

        operate = OperateApp(home=tmp_path / OPERATE)
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        bridge = bridge_provider_class(wallet_manager=operate.wallet_manager)

        quote_data = QuoteData(
            bridge_eta=0,
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
        )

        bridge_request = BridgeRequest(
            params=params,
            bridge_provider_id=bridge_provider_class.id(),
            id=request_id,
            status=BridgeRequestStatus.EXECUTION_PENDING,
            quote_data=quote_data,
            execution_data=execution_data,
        )

        bridge.status_json(bridge_request)

        assert bridge_request.status == expected_status, "Wrong execution status."
        assert execution_data.to_tx_hash == expected_to_tx_hash, "Wrong to_tx_hash."
        assert execution_data.elapsed_time == expected_elapsed_time, "Wrong timestamp."
