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
import typing as t
from pathlib import Path

import pytest
from deepdiff import DeepDiff

from operate.bridge.providers.bridge_provider import (
    BridgeProvider,
    BridgeRequestStatus,
    MESSAGE_QUOTE_ZERO,
)
from operate.bridge.providers.lifi_bridge_provider import (
    LIFI_DEFAULT_ETA,
    LiFiBridgeProvider,
)
from operate.bridge.providers.native_bridge_provider import (
    BridgeContractAdaptor,
    NativeBridgeProvider,
    OmnibridgeContractAdaptor,
    OptimismContractAdaptor,
)
from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import OLAS, USDC
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
        bridge = bridge_manager._get_bridge_provider(request)
        assert bridge._get_approve_tx() is not None, "Wrong number of transactions."
        request = bundle.bridge_requests[1]
        bridge = bridge_manager._get_bridge_provider(request)
        assert bridge._get_approve_tx() is not None, "Wrong number of transactions."

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

    @pytest.mark.parametrize(
        (
            "from_chain",
            "from_token",
            "to_chain",
            "to_token",
            "expected_provider_cls",
            "expected_contract_adaptor_cls",
        ),
        [
            # Base
            (
                Chain.ETHEREUM.value,
                ZERO_ADDRESS,
                "base",
                ZERO_ADDRESS,
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            (
                Chain.ETHEREUM.value,
                OLAS[Chain.ETHEREUM],
                "base",
                OLAS[Chain.BASE],
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            (
                Chain.ETHEREUM.value,
                USDC[Chain.ETHEREUM],
                "base",
                USDC[Chain.BASE],
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            # Mode
            (
                Chain.ETHEREUM.value,
                ZERO_ADDRESS,
                Chain.MODE.value,
                ZERO_ADDRESS,
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            (
                Chain.ETHEREUM.value,
                OLAS[Chain.ETHEREUM],
                Chain.MODE.value,
                OLAS[Chain.MODE],
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            (
                Chain.ETHEREUM.value,
                USDC[Chain.ETHEREUM],
                Chain.MODE.value,
                USDC[Chain.MODE],
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            # Optimism
            (
                Chain.ETHEREUM.value,
                ZERO_ADDRESS,
                Chain.OPTIMISTIC.value,
                ZERO_ADDRESS,
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            (
                Chain.ETHEREUM.value,
                OLAS[Chain.ETHEREUM],
                Chain.OPTIMISTIC.value,
                OLAS[Chain.OPTIMISTIC],
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            (
                Chain.ETHEREUM.value,
                USDC[Chain.ETHEREUM],
                Chain.OPTIMISTIC.value,
                USDC[Chain.OPTIMISTIC],
                NativeBridgeProvider,
                OptimismContractAdaptor,
            ),
            # Gnosis
            (
                Chain.ETHEREUM.value,
                ZERO_ADDRESS,
                Chain.GNOSIS.value,
                ZERO_ADDRESS,
                LiFiBridgeProvider,
                None,
            ),
            (
                Chain.ETHEREUM.value,
                OLAS[Chain.ETHEREUM],
                Chain.GNOSIS.value,
                OLAS[Chain.GNOSIS],
                NativeBridgeProvider,
                OmnibridgeContractAdaptor,
            ),
            (
                Chain.ETHEREUM.value,
                USDC[Chain.ETHEREUM],
                Chain.GNOSIS.value,
                USDC[Chain.GNOSIS],
                NativeBridgeProvider,
                OmnibridgeContractAdaptor,
            ),
        ],
    )
    def test_correct_providers(
        self,
        tmp_path: Path,
        password: str,
        from_chain: str,
        from_token: str,
        to_chain: str,
        to_token: str,
        expected_provider_cls: t.Type[BridgeProvider],
        expected_contract_adaptor_cls: t.Type[BridgeContractAdaptor],
    ) -> None:
        """test_correct_providers"""
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
                    "chain": from_chain,
                    "address": wallet_address,
                    "token": from_token,
                },
                "to": {
                    "chain": to_chain,
                    "address": wallet_address,
                    "token": to_token,
                    "amount": 0,
                },
            },
        ]

        bundle = bridge_manager.data.last_requested_bundle
        assert bundle is None, "Wrong bundle."
        bridge_manager.bridge_refill_requirements(
            requests_params=params, force_update=False
        )

        bundle = bridge_manager.data.last_requested_bundle
        assert bundle is not None, "Wrong bundle."
        assert len(bundle.bridge_requests) == 1, "Wrong bundle."
        bridge_request = bundle.bridge_requests[0]
        bridge = bridge_manager._get_bridge_provider(bridge_request)

        assert isinstance(
            bridge, expected_provider_cls
        ), f"Expected provider {expected_provider_cls}, got {type(bridge)}"

        if isinstance(bridge, NativeBridgeProvider):
            assert isinstance(
                bridge.bridge_contract_adaptor, expected_contract_adaptor_cls
            ), f"Expected adaptor {expected_contract_adaptor_cls}, got {type(bridge.bridge_contract_adaptor)}"
