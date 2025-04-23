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

"""Tests for bridge.bridge module."""


import os
import time
from pathlib import Path

import pytest
from deepdiff import DeepDiff

from operate.bridge.bridge import (  # MESSAGE_EXECUTION_SKIPPED,; MESSAGE_QUOTE_ZERO,
    BridgeRequest,
    BridgeRequestStatus,
    LiFiBridgeProvider,
    MESSAGE_EXECUTION_SKIPPED,
    MESSAGE_QUOTE_ZERO,
)
from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import OLAS
from operate.operate_types import Chain, LedgerType


ROOT_PATH = Path(__file__).resolve().parent
OPERATE = ".operate_test"


class TestLiFiBridge:
    """Tests for bridge.bridge.BridgeWorkflow class."""

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
        bridge_request = BridgeRequest(params)

        assert not bridge_request.quote_data, "Unexpected quote data."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        with pytest.raises(RuntimeError):
            bridge.update_execution_status(bridge_request)

        for _ in range(2):
            timestamp = int(time.time())
            bridge.quote(bridge_request=bridge_request)
            qd = bridge_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.attempts == 0, "Wrong quote data."
            assert qd.elapsed_time == 0, "Wrong quote data."
            assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
            assert qd.response is None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        sj = bridge_request.get_status_json()
        expected_sj = {
            "message": MESSAGE_QUOTE_ZERO,
            "status": BridgeRequestStatus.QUOTE_DONE.value,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert bridge_request.quote_data is not None, "Missing quote data."

        br = bridge_request.quote_data.requirements
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
        assert qd.elapsed_time == 0, "Wrong quote data."
        assert qd.message == MESSAGE_QUOTE_ZERO, "Wrong quote data."
        assert qd.response is None, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert bridge_request.status == BridgeRequestStatus.QUOTE_DONE, "Wrong status."

        with pytest.raises(RuntimeError):
            bridge.update_execution_status(bridge_request)

        timestamp = int(time.time())
        bridge.execute(bridge_request=bridge_request)
        ed = bridge_request.execution_data
        assert ed is not None, "Missing execution data."
        assert ed.bridge_status is None, "Wrong execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.explorer_link is None, "Wrong execution data."
        assert ed.message == MESSAGE_EXECUTION_SKIPPED, "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.tx_hash is None, "Wrong execution data."
        assert ed.tx_status == 0, "Wrong execution data."
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        bridge.update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_DONE
        ), "Wrong status."

        sj = bridge_request.get_status_json()
        expected_sj = {
            "message": MESSAGE_EXECUTION_SKIPPED,
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
        bridge_request = BridgeRequest(params)

        assert not bridge_request.quote_data, "Unexpected quote data."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        with pytest.raises(RuntimeError):
            bridge.update_execution_status(bridge_request)

        for _ in range(2):
            timestamp = int(time.time())
            bridge.quote(bridge_request=bridge_request)
            qd = bridge_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.attempts > 0, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is not None, "Wrong quote data."
            assert qd.response is not None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_FAILED
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge_request.get_status_json()
        expected_sj = {
            "message": bridge_request.quote_data.message,
            "status": BridgeRequestStatus.QUOTE_FAILED,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."

        br = bridge_request.quote_data.requirements
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
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is not None, "Wrong quote data."
        assert qd.response is not None, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert (
            bridge_request.status == BridgeRequestStatus.QUOTE_FAILED
        ), "Wrong status."

        with pytest.raises(RuntimeError):
            bridge.update_execution_status(bridge_request)

        timestamp = int(time.time())
        bridge.execute(bridge_request=bridge_request)
        ed = bridge_request.execution_data
        assert ed is not None, "Missing execution data."
        assert ed.bridge_status is None, "Wrong execution data."
        assert ed.elapsed_time == 0, "Wrong execution data."
        assert ed.explorer_link is None, "Wrong execution data."
        assert ed.message == MESSAGE_EXECUTION_SKIPPED, "Wrong execution data."
        assert timestamp <= ed.timestamp, "Wrong quote data."
        assert ed.timestamp <= int(time.time()), "Wrong quote data."
        assert ed.tx_hash is None, "Wrong execution data."
        assert ed.tx_status == 0, "Wrong execution data."
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        bridge.update_execution_status(bridge_request)
        assert (
            bridge_request.status == BridgeRequestStatus.EXECUTION_FAILED
        ), "Wrong status."

        sj = bridge_request.get_status_json()
        expected_sj = {
            "message": ed.message,
            "status": BridgeRequestStatus.EXECUTION_FAILED,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."

    @pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test on CI.")
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
        bridge_request = BridgeRequest(params)

        assert not bridge_request.quote_data, "Unexpected quote data."

        with pytest.raises(RuntimeError):
            bridge.execute(bridge_request)

        with pytest.raises(RuntimeError):
            bridge.update_execution_status(bridge_request)

        for _ in range(2):
            timestamp = int(time.time())
            bridge.quote(bridge_request=bridge_request)
            qd = bridge_request.quote_data
            assert qd is not None, "Missing quote data."
            assert qd.attempts > 0, "Wrong quote data."
            assert qd.elapsed_time > 0, "Wrong quote data."
            assert qd.message is None, "Wrong quote data."
            assert qd.response is not None, "Wrong quote data."
            assert timestamp <= qd.timestamp, "Wrong quote data."
            assert qd.timestamp <= int(time.time()), "Wrong quote data."
            assert (
                bridge_request.status == BridgeRequestStatus.QUOTE_DONE
            ), "Wrong status."

        assert bridge_request.quote_data is not None, "Wrong quote data."
        sj = bridge_request.get_status_json()
        expected_sj = {
            "message": bridge_request.quote_data.message,
            "status": BridgeRequestStatus.QUOTE_DONE,
        }
        diff = DeepDiff(sj, expected_sj)
        if diff:
            print(diff)

        assert not diff, "Wrong status."
        assert bridge_request.quote_data.response is not None, "Missing quote data."

        quote = bridge_request.quote_data.response
        br = bridge_request.quote_data.requirements
        expected_br = {
            "gnosis": {
                wallet_address: {
                    ZERO_ADDRESS: int(quote["transactionRequest"]["value"], 16),
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
        assert qd.elapsed_time > 0, "Wrong quote data."
        assert qd.message is None, "Wrong quote data."
        assert qd.response is not None, "Wrong quote data."
        assert qd.timestamp <= int(time.time()), "Wrong quote data."
        assert bridge_request.status == BridgeRequestStatus.QUOTE_DONE, "Wrong status."

        with pytest.raises(RuntimeError):
            bridge.update_execution_status(bridge_request)

    def test_bundle_zero(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bundle"""

        operate = OperateApp(
            home=tmp_path / OPERATE,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        bridge_manager = operate.bridge_manager()

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = [
            {
                "from": {
                    "chain": "gnosis",
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                },
                "to": {
                    "chain": "base",
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                    "amount": 0,  # 1_000_000_000_000_000,
                },
            },
            {
                "from": {
                    "chain": "gnosis",
                    "address": wallet_address,
                    "token": OLAS[Chain.GNOSIS],
                },
                "to": {
                    "chain": "base",
                    "address": wallet_address,
                    "token": OLAS[Chain.BASE],
                    "amount": 0,  # 1_000_000_000_000_000_000,
                },
            },
        ]

        timestamp1 = time.time()
        brr = bridge_manager.bridge_refill_requirements(
            requests_params=params, force_update=False
        )
        timestamp2 = time.time()
        expected_brr = {
            "id": brr["id"],
            "balances": {
                "gnosis": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}}
            },
            "bridge_refill_requirements": brr["bridge_refill_requirements"],
            "bridge_request_status": [
                {
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
                {
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
            "error": False,
            "expiration_timestamp": brr["expiration_timestamp"],
            "is_refill_required": False,
        }

        assert (
            brr["balances"]["gnosis"][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["balances"]["gnosis"][wallet_address][OLAS[Chain.GNOSIS]] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][ZERO_ADDRESS]
            == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][
                OLAS[Chain.GNOSIS]
            ]
            == 0
        ), "Wrong bridge refill requirements."
        assert not DeepDiff(
            brr["bridge_refill_requirements"], brr["bridge_total_requirements"]
        ), "Wrong bridge refill requirements."
        assert (
            brr["expiration_timestamp"] >= timestamp1
        ), "Wrong bridge refill requirements."
        assert (
            brr["expiration_timestamp"]
            <= timestamp2 + bridge_manager.quote_validity_period
        ), "Wrong bridge refill requirements."

        diff = DeepDiff(brr, expected_brr)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge refill requirements."

    def test_bundle_error(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bundle"""

        operate = OperateApp(
            home=tmp_path / OPERATE,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        bridge_manager = operate.bridge_manager()

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = [
            {
                "from": {
                    "chain": "gnosis",
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                },
                "to": {
                    "chain": "base",
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                    "amount": 1,
                },
            },
            {
                "from": {
                    "chain": "gnosis",
                    "address": wallet_address,
                    "token": OLAS[Chain.GNOSIS],
                },
                "to": {
                    "chain": "base",
                    "address": wallet_address,
                    "token": OLAS[Chain.BASE],
                    "amount": 0,  # 1_000_000_000_000_000_000,
                },
            },
        ]

        timestamp1 = time.time()
        brr = bridge_manager.bridge_refill_requirements(
            requests_params=params, force_update=False
        )
        timestamp2 = time.time()
        expected_brr = {
            "id": brr["id"],
            "balances": {
                "gnosis": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}}
            },
            "bridge_refill_requirements": brr["bridge_refill_requirements"],
            "bridge_request_status": [
                {
                    "message": brr["bridge_request_status"][0]["message"],
                    "status": BridgeRequestStatus.QUOTE_FAILED.value,
                },
                {
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
            "error": False,
            "expiration_timestamp": brr["expiration_timestamp"],
            "is_refill_required": False,
        }

        assert (
            brr["balances"]["gnosis"][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["balances"]["gnosis"][wallet_address][OLAS[Chain.GNOSIS]] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][ZERO_ADDRESS]
            == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][
                OLAS[Chain.GNOSIS]
            ]
            == 0
        ), "Wrong bridge refill requirements."
        assert not DeepDiff(
            brr["bridge_refill_requirements"], brr["bridge_total_requirements"]
        ), "Wrong bridge refill requirements."
        assert (
            brr["expiration_timestamp"] >= timestamp1
        ), "Wrong bridge refill requirements."
        assert (
            brr["expiration_timestamp"]
            <= timestamp2 + bridge_manager.quote_validity_period
        ), "Wrong bridge refill requirements."

        diff = DeepDiff(brr, expected_brr)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge refill requirements."

    @pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test on CI.")
    def test_bundle(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bundle"""

        operate = OperateApp(
            home=tmp_path / OPERATE,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        bridge_manager = operate.bridge_manager()

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = [
            {
                "from": {
                    "chain": "gnosis",
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                },
                "to": {
                    "chain": "base",
                    "address": wallet_address,
                    "token": ZERO_ADDRESS,
                    "amount": 1_000_000_000_000_000,
                },
            },
            {
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
            },
        ]

        timestamp1 = time.time()
        brr = bridge_manager.bridge_refill_requirements(
            requests_params=params, force_update=False
        )
        timestamp2 = time.time()
        expected_brr = {
            "id": brr["id"],
            "balances": {
                "gnosis": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}}
            },
            "bridge_refill_requirements": brr["bridge_refill_requirements"],
            "bridge_request_status": [
                {"message": None, "status": BridgeRequestStatus.QUOTE_DONE.value},
                {"message": None, "status": BridgeRequestStatus.QUOTE_DONE.value},
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
            "error": False,
            "expiration_timestamp": brr["expiration_timestamp"],
            "is_refill_required": True,
        }

        assert (
            brr["balances"]["gnosis"][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["balances"]["gnosis"][wallet_address][OLAS[Chain.GNOSIS]] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][ZERO_ADDRESS]
            > 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][
                OLAS[Chain.GNOSIS]
            ]
            > 0
        ), "Wrong bridge refill requirements."
        assert not DeepDiff(
            brr["bridge_refill_requirements"], brr["bridge_total_requirements"]
        ), "Wrong bridge refill requirements."
        assert (
            brr["expiration_timestamp"] >= timestamp1
        ), "Wrong bridge refill requirements."
        assert (
            brr["expiration_timestamp"]
            <= timestamp2 + bridge_manager.quote_validity_period
        ), "Wrong bridge refill requirements."

        diff = DeepDiff(brr, expected_brr)
        if diff:
            print(diff)

        assert not diff, "Wrong bridge refill requirements."
