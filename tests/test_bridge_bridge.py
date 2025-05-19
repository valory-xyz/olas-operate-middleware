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

from operate.bridge.providers.bridge_provider import (
    BridgeRequestStatus,
    MESSAGE_QUOTE_ZERO,
)
from operate.bridge.providers.lifi_bridge_provider import LIFI_DEFAULT_ETA
from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import OLAS
from operate.operate_types import Chain, LedgerType


ROOT_PATH = Path(__file__).resolve().parent
OPERATE = ".operate_test"
RUNNING_IN_CI = (
    os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    or os.getenv("CI", "").lower() == "true"
)


class TestBridgeManager:
    """Tests for bridge.bridge.BridgeManager class."""

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
                    "eta": 0,
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
                {
                    "eta": 0,
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
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
                    "eta": None,
                    "message": brr["bridge_request_status"][0]["message"],
                    "status": BridgeRequestStatus.QUOTE_FAILED.value,
                },
                {
                    "eta": 0,
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
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

    @pytest.mark.skipif(RUNNING_IN_CI, reason="Skip test on CI.")
    def test_bundle_quote(
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
                    "chain": "ethereum",
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
                    "chain": "ethereum",
                    "address": wallet_address,
                    "token": OLAS[Chain.ETHEREUM],
                },
                "to": {
                    "chain": "base",
                    "address": wallet_address,
                    "token": OLAS[Chain.BASE],
                    "amount": 1_000_000_000_000_000_000,
                },
            },
        ]

        bundle = bridge_manager.data.last_requested_bundle
        assert bundle is None, "Unexpected bundle."
        timestamp1 = time.time()
        brr = bridge_manager.bridge_refill_requirements(
            requests_params=params, force_update=False
        )
        timestamp2 = time.time()

        bundle = bridge_manager.data.last_requested_bundle
        assert bundle is not None, "Unexpected bundle."

        request = bundle.bridge_requests[0]
        bridge = bridge_manager._bridge_providers[request.bridge_provider_id]
        assert (
            len(bridge._get_transactions(request)) == 1
        ), "Wrong number of transactions."
        request = bundle.bridge_requests[1]
        bridge = bridge_manager._bridge_providers[request.bridge_provider_id]
        assert (
            len(bridge._get_transactions(request)) == 2
        ), "Wrong number of transactions."

        expected_brr = {
            "id": brr["id"],
            "balances": {
                "ethereum": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.ETHEREUM]: 0}}
            },
            "bridge_refill_requirements": brr["bridge_refill_requirements"],
            "bridge_request_status": [
                {
                    "eta": LIFI_DEFAULT_ETA,
                    "message": None,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
                {
                    "eta": LIFI_DEFAULT_ETA,
                    "message": None,
                    "status": BridgeRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
            "expiration_timestamp": brr["expiration_timestamp"],
            "is_refill_required": True,
        }

        assert (
            brr["balances"]["ethereum"][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["balances"]["ethereum"][wallet_address][OLAS[Chain.ETHEREUM]] == 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["ethereum"][wallet_address][ZERO_ADDRESS]
            > 0
        ), "Wrong bridge refill requirements."
        assert (
            brr["bridge_refill_requirements"]["ethereum"][wallet_address][
                OLAS[Chain.ETHEREUM]
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
