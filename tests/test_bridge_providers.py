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
from pathlib import Path

import pytest
from deepdiff import DeepDiff
from web3 import Web3

from operate.bridge.bridge import (  # MESSAGE_EXECUTION_SKIPPED,; MESSAGE_QUOTE_ZERO,
    BridgeRequest,
    LiFiBridgeProvider,
)
from operate.bridge.providers.bridge_provider import (
    BridgeRequestStatus,
    ExecutionData,
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
        bridge_request = BridgeRequest(params, bridge.id(), "test-id")

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
            assert qd.attempts == 0, "Wrong quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time == 0, "Wrong quote data."
            assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
            assert qd.response is None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        sj = bridge.get_status_json(bridge_request)
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
        assert qd.attempts == 0, "Wrong quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time == 0, "Wrong quote data."
        assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
        assert qd.response is None, "Wrong quote data."
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
        assert ed.bridge_status is None, "Wrong execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.message is not None, "Wrong execution data."
        assert MESSAGE_EXECUTION_SKIPPED in ed.message, "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.tx_hashes is None, "Wrong execution data."
        assert ed.tx_status is None, "Wrong execution data."
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        bridge._update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        sj = bridge.get_status_json(bridge_request)
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
        bridge_request = BridgeRequest(params, bridge.id(), "test-id")

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
            assert qd.attempts > 0, "Wrong quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is not None, "Wrong quote data."
            assert qd.response is not None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_FAILED
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge.get_status_json(bridge_request)
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
        assert qd.attempts > 0, "Wrong quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is not None, "Wrong quote data."
        assert qd.response is not None, "Wrong quote data."
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
        assert ed.bridge_status is None, "Wrong execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.message is not None, "Wrong execution data."
        assert MESSAGE_EXECUTION_SKIPPED in ed.message, "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.tx_hashes is None, "Wrong execution data."
        assert ed.tx_status is None, "Wrong execution data."
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        bridge._update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        sj = bridge.get_status_json(bridge_request)
        assert MESSAGE_EXECUTION_SKIPPED in sj["message"], "Wrong execution data."
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
        bridge_request = BridgeRequest(params, bridge.id(), "test-id")

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
            assert qd.attempts > 0, "Wrong quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is None, "Wrong quote data."
            assert qd.response is not None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge.get_status_json(bridge_request)
        expected_sj = {
            "message": bridge_request.quote_data.message,
            "status": BridgeRequestStatus.QUOTE_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert bridge_request.quote_data.response is not None, "Missing quote data."

        quote = bridge_request.quote_data.response
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
        assert qd.attempts > 0, "Wrong quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is None, "Wrong quote data."
        assert qd.response is not None, "Wrong quote data."
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

        for _ in range(2):
            timestamp = int(time.time())
            bridge.quote(bridge_request=bridge_request)
            qd = bridge_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.attempts == 0, "Wrong quote data."
            assert (
                qd.bridge_eta
                == NATIVE_BRIDGE_ENDPOINTS["ethereum", "base"]["bridge_eta"]
            ), "Wrong quote data."
            assert qd.elapsed_time == 0, "Wrong quote data."
            assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
            assert qd.response is None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        sj = bridge.get_status_json(bridge_request)
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
            "ethereum": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.ETHEREUM]: 0}}
        }
        diff = DeepDiff(br, expected_br)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge requirements."

        qd = bridge_request.quote_data
        assert qd is not None, "Missing quote data."
        assert qd.attempts == 0, "Wrong quote data."
        assert (
            qd.bridge_eta == NATIVE_BRIDGE_ENDPOINTS["ethereum", "base"]["bridge_eta"]
        ), "Wrong quote data."
        assert qd.elapsed_time == 0, "Wrong quote data."
        assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
        assert qd.response is None, "Wrong quote data."
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
        assert ed.bridge_status is None, "Wrong execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.message is not None, "Wrong execution data."
        assert MESSAGE_EXECUTION_SKIPPED in ed.message, "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.tx_hashes is None, "Wrong execution data."
        assert ed.tx_status is None, "Wrong execution data."
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        bridge._update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        sj = bridge.get_status_json(bridge_request)
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
                "chain": Chain.ETHEREUM.value,
                "address": wallet_address,
                "token": OLAS[Chain.ETHEREUM],
            },
            "to": {
                "chain": Chain.BASE.value,
                "address": wallet_address,
                "token": OLAS[Chain.BASE],
                "amount": 1,  # This will cause a quote error
            },
        }

        bridge = LiFiBridgeProvider(wallet_manager=operate.wallet_manager)
        bridge_request = BridgeRequest(params, bridge.id(), "test-id")

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
            assert qd.attempts > 0, "Wrong quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is not None, "Wrong quote data."
            assert qd.response is not None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_FAILED
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge.get_status_json(bridge_request)
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
        assert qd.attempts > 0, "Wrong quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is not None, "Wrong quote data."
        assert qd.response is not None, "Wrong quote data."
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
        assert ed.bridge_status is None, "Wrong execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.message is not None, "Wrong execution data."
        assert MESSAGE_EXECUTION_SKIPPED in ed.message, "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.tx_hashes is None, "Wrong execution data."
        assert ed.tx_status is None, "Wrong execution data."
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        bridge._update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        sj = bridge.get_status_json(bridge_request)
        assert MESSAGE_EXECUTION_SKIPPED in sj["message"], "Wrong execution data."
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
        bridge_request = BridgeRequest(params, bridge.id(), "test-id")

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
            assert qd.attempts > 0, "Wrong quote data."
            assert qd.bridge_eta is None, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is None, "Wrong quote data."
            assert qd.response is not None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge.get_status_json(bridge_request)
        expected_sj = {
            "message": bridge_request.quote_data.message,
            "status": BridgeRequestStatus.QUOTE_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert bridge_request.quote_data.response is not None, "Missing quote data."

        quote = bridge_request.quote_data.response
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
        assert qd.attempts > 0, "Wrong quote data."
        assert qd.bridge_eta is None, "Wrong quote data."
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is None, "Wrong quote data."
        assert qd.response is not None, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert bridge_request.status == BridgeRequestStatus.QUOTE_DONE, "Wrong status."

        status1 = bridge_request.status
        bridge._update_execution_status(bridge_request)
        status2 = bridge_request.status
        assert status1 == BridgeRequestStatus.QUOTE_DONE, "Wrong status."
        assert status2 == BridgeRequestStatus.QUOTE_DONE, "Wrong status."

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

    def test_update_execution_status(self, tmp_path: Path, password: str) -> None:
        """test_update_execution_status"""

        DEFAULT_RPCS[Chain.ETHEREUM] = "https://rpc-gate.autonolas.tech/ethereum-rpc/"
        DEFAULT_RPCS[Chain.BASE] = "https://rpc-gate.autonolas.tech/base-rpc/"

        operate = OperateApp(
            home=tmp_path / OPERATE,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        bridge = NativeBridgeProvider(wallet_manager=operate.wallet_manager)

        params = {
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
        }

        quote_data = QuoteData(
            attempts=0,
            bridge_eta=0,
            elapsed_time=0,
            message=None,
            response=None,
            response_status=0,
            timestamp=0,
        )

        execution_data = ExecutionData(
            bridge_status=None,
            elapsed_time=0,
            message=None,
            timestamp=0,
            tx_hashes=[
                "0xf649cdce0075a950ed031cc32775990facdcefc8d2bfff695a8023895dd47ebd"
            ],
            tx_status=[1],
        )

        bridge_request = BridgeRequest(
            params=params,
            bridge_provider_id=NativeBridgeProvider.id(),
            id="b-76a298b9-b243-4cfb-b48a-f59183ae0e85",
            status=BridgeRequestStatus.EXECUTION_PENDING,
            quote_data=quote_data,
            execution_data=execution_data,
        )

        bridge._update_execution_status(bridge_request)

        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong execution status."

        params = {
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
        }

        quote_data = QuoteData(
            attempts=0,
            bridge_eta=0,
            elapsed_time=0,
            message=None,
            response=None,
            response_status=0,
            timestamp=0,
        )

        execution_data = ExecutionData(
            bridge_status=None,
            elapsed_time=0,
            message=None,
            timestamp=0,
            tx_hashes=[
                "0x0b269344009722d1a8f7ee10c03117dc5e7f833d6ba403b140b580c1016645ff",
                "0xa1139bb4ba963d7979417f49fed03b365c1f1bfc31d0100257caed888a491c4c",
            ],
            tx_status=[1, 1],
        )

        bridge_request = BridgeRequest(
            params=params,
            bridge_provider_id=NativeBridgeProvider.id(),
            id="b-7221ece2-e15e-4aec-bac2-7fd4c4d4851a",
            status=BridgeRequestStatus.EXECUTION_PENDING,
            quote_data=quote_data,
            execution_data=execution_data,
        )

        bridge._update_execution_status(bridge_request)

        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong execution status."
