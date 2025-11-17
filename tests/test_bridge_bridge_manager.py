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

"""Tests for bridge.bridge_manager module."""


import time
import typing as t
from functools import cache
from pathlib import Path

import pytest
import requests
from deepdiff import DeepDiff

from operate.bridge.providers.lifi_provider import LiFiProvider
from operate.bridge.providers.native_bridge_provider import (
    BridgeContractAdaptor,
    NativeBridgeProvider,
    OmnibridgeContractAdaptor,
    OptimismContractAdaptor,
)
from operate.bridge.providers.provider import (
    MESSAGE_QUOTE_ZERO,
    Provider,
    ProviderRequestStatus,
)
from operate.bridge.providers.relay_provider import RelayProvider
from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import OLAS, USDC
from operate.operate_types import Chain, ChainAmounts, LedgerType

from tests.constants import OPERATE_TEST


COINGECKO_PLATFORM_IDS = {
    "ethereum": "ethereum",
    "polygon": "polygon-pos",
    "arbitrum": "arbitrum-one",
    "optimism": "optimism-ethereum",
    "binance": "binance-smart-chain",
    "avalanche": "avalanche",
    "fantom": "fantom",
    "base": "base",
    "mode": "mode",
    "gnosis": "xdai",
}

COINGECKO_NATIVE_IDS = {
    "ethereum": "ethereum",
    "polygon": "matic-network",
    "arbitrum": "ethereum",
    "optimism": "ethereum",
    "binance": "binancecoin",
    "avalanche": "avalanche-2",
    "fantom": "fantom",
    "base": "ethereum",
    "mode": "ethereum",
    "gnosis": "xdai",
}


class TestBridgeManager:
    """Tests for bridge.bridge_manager.BridgeManager class."""

    @staticmethod
    @cache
    def _get_token_price_usd(
        chain: str, token_address: str, amount: t.Optional[int] = None
    ) -> t.Optional[float]:
        print(f"Calling _get_token_price_usd {chain=} {token_address=}")
        chain = chain.lower()

        if token_address in USDC.values():
            decimals = 6
            if amount is None:
                amount = 1000000
        else:
            decimals = 18
            if amount is None:
                amount = 1000000000000000000

        if token_address == ZERO_ADDRESS:
            coingecko_id = COINGECKO_NATIVE_IDS.get(chain)
            if not coingecko_id:
                return None
            url = "https://api.coingecko.com/api/v3/simple/price"
            print(f"Fetching {url}")
            params = {"ids": coingecko_id, "vs_currencies": "usd"}
            r = requests.get(url, params=params, timeout=30)
            if r.status_code != 200:
                return None
            data = r.json()
            print(r.json())
            price_usd = data.get(coingecko_id, {}).get("usd")
            if price_usd is None:
                return None
            return price_usd * amount / (10**decimals)

        platform_id = COINGECKO_PLATFORM_IDS.get(chain)
        if not platform_id:
            return None
        token_address = token_address.lower()
        url = f"https://api.coingecko.com/api/v3/simple/token_price/{platform_id}"
        params = {"contract_addresses": token_address, "vs_currencies": "usd"}
        print(f"Fetching {url}")
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            return None
        data = r.json()
        print(r.json())
        price_usd = data.get(token_address, {}).get("usd")
        if price_usd is None:
            return None
        return price_usd * amount / (10**decimals)

    def test_bundle_zero(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bundle"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        bridge_manager = operate.bridge_manager

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
                    "amount": 0,
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
                    "amount": 0,
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
            "balances": ChainAmounts(
                {"gnosis": {wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}}}
            ),
            "bridge_refill_requirements": brr["bridge_refill_requirements"],
            "bridge_request_status": [
                {
                    "eta": 0,
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": ProviderRequestStatus.QUOTE_DONE.value,
                },
                {
                    "eta": 0,
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": ProviderRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
            "expiration_timestamp": brr["expiration_timestamp"],
            "is_refill_required": False,
        }

        assert (
            brr["balances"]["gnosis"][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong refill requirements."
        assert (
            brr["balances"]["gnosis"][wallet_address][OLAS[Chain.GNOSIS]] == 0
        ), "Wrong refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][ZERO_ADDRESS]
            == 0
        ), "Wrong refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][
                OLAS[Chain.GNOSIS]
            ]
            == 0
        ), "Wrong refill requirements."
        assert not DeepDiff(
            brr["bridge_refill_requirements"], brr["bridge_total_requirements"]
        ), "Wrong refill requirements."
        assert brr["expiration_timestamp"] >= timestamp1, "Wrong refill requirements."
        assert (
            brr["expiration_timestamp"]
            <= timestamp2 + bridge_manager.bundle_validity_period
        ), "Wrong refill requirements."

        diff = DeepDiff(brr, expected_brr)
        if diff:
            print(diff)

        assert not diff, "Wrong refill requirements."

    def test_bundle_error(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bundle"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        bridge_manager = operate.bridge_manager

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address
        params = [
            {
                "from": {
                    "chain": Chain.ETHEREUM.value,
                    "address": wallet_address,
                    "token": USDC[Chain.ETHEREUM],
                },
                "to": {
                    "chain": Chain.OPTIMISM.value,
                    "address": wallet_address,
                    "token": USDC[Chain.OPTIMISM],
                    "amount": int(1000 * 1e18),
                },
            },
            {
                "from": {
                    "chain": Chain.GNOSIS.value,
                    "address": wallet_address,
                    "token": OLAS[Chain.GNOSIS],
                },
                "to": {
                    "chain": Chain.BASE.value,
                    "address": wallet_address,
                    "token": OLAS[Chain.BASE],
                    "amount": 0,
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
            "balances": ChainAmounts(
                {
                    "ethereum": {
                        wallet_address: {ZERO_ADDRESS: 0, USDC[Chain.ETHEREUM]: 0}
                    },
                    "gnosis": {
                        wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}
                    },
                }
            ),
            "bridge_refill_requirements": ChainAmounts(
                {
                    "ethereum": {
                        wallet_address: {ZERO_ADDRESS: 0, USDC[Chain.ETHEREUM]: 0}
                    },
                    "gnosis": {
                        wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.GNOSIS]: 0}
                    },
                }
            ),
            "bridge_request_status": [
                {
                    "eta": None,
                    "message": brr["bridge_request_status"][0]["message"],
                    "status": ProviderRequestStatus.QUOTE_FAILED.value,
                },
                {
                    "eta": 0,
                    "message": MESSAGE_QUOTE_ZERO,
                    "status": ProviderRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
            "expiration_timestamp": brr["expiration_timestamp"],
            "is_refill_required": False,
        }

        assert (
            brr["balances"]["gnosis"][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong refill requirements."
        assert (
            brr["balances"]["gnosis"][wallet_address][OLAS[Chain.GNOSIS]] == 0
        ), "Wrong refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][ZERO_ADDRESS]
            == 0
        ), "Wrong refill requirements."
        assert (
            brr["bridge_refill_requirements"]["gnosis"][wallet_address][
                OLAS[Chain.GNOSIS]
            ]
            == 0
        ), "Wrong refill requirements."
        assert not DeepDiff(
            brr["bridge_refill_requirements"], brr["bridge_total_requirements"]
        ), "Wrong refill requirements."
        assert brr["expiration_timestamp"] >= timestamp1, "Wrong refill requirements."
        assert (
            brr["expiration_timestamp"]
            <= timestamp2 + bridge_manager.bundle_validity_period
        ), "Wrong refill requirements."

        diff = DeepDiff(brr, expected_brr)
        if diff:
            print(diff)

        assert not diff, "Wrong refill requirements."

    def test_bundle_quote(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_bundle"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        bridge_manager = operate.bridge_manager

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

        request = bundle.provider_requests[0]
        bridge = bridge_manager._providers[request.provider_id]
        assert len(bridge._get_txs(request)) == 1, "Wrong number of transactions."

        request = bundle.provider_requests[1]
        bridge = bridge_manager._providers[request.provider_id]
        assert len(bridge._get_txs(request)) == 2, "Wrong number of transactions."

        expected_brr = {
            "id": brr["id"],
            "balances": ChainAmounts(
                {
                    "ethereum": {
                        wallet_address: {ZERO_ADDRESS: 0, OLAS[Chain.ETHEREUM]: 0}
                    }
                }
            ),
            "bridge_refill_requirements": brr["bridge_refill_requirements"],
            "bridge_request_status": [
                {
                    "eta": brr["bridge_request_status"][0]["eta"],
                    "message": None,
                    "status": ProviderRequestStatus.QUOTE_DONE.value,
                },
                {
                    "eta": brr["bridge_request_status"][1]["eta"],
                    "message": None,
                    "status": ProviderRequestStatus.QUOTE_DONE.value,
                },
            ],
            "bridge_total_requirements": brr["bridge_total_requirements"],
            "expiration_timestamp": brr["expiration_timestamp"],
            "is_refill_required": True,
        }

        assert (
            brr["balances"]["ethereum"][wallet_address][ZERO_ADDRESS] == 0
        ), "Wrong refill requirements."
        assert (
            brr["balances"]["ethereum"][wallet_address][OLAS[Chain.ETHEREUM]] == 0
        ), "Wrong refill requirements."
        assert (
            brr["bridge_refill_requirements"]["ethereum"][wallet_address][ZERO_ADDRESS]
            > 0
        ), "Wrong refill requirements."
        assert (
            brr["bridge_refill_requirements"]["ethereum"][wallet_address][
                OLAS[Chain.ETHEREUM]
            ]
            > 0
        ), "Wrong refill requirements."
        assert not DeepDiff(
            brr["bridge_refill_requirements"], brr["bridge_total_requirements"]
        ), "Wrong refill requirements."
        assert brr["expiration_timestamp"] >= timestamp1, "Wrong refill requirements."
        assert (
            brr["expiration_timestamp"]
            <= timestamp2 + bridge_manager.bundle_validity_period
        ), "Wrong refill requirements."

        diff = DeepDiff(brr, expected_brr)
        if diff:
            print(diff)

        assert not diff, "Wrong refill requirements."

    @pytest.mark.parametrize(
        ("to_chain_enum", "expected_provider_cls", "expected_contract_adaptor_cls"),
        [
            (Chain.ARBITRUM_ONE, RelayProvider, None),
            (Chain.BASE, NativeBridgeProvider, OptimismContractAdaptor),
            (Chain.CELO, RelayProvider, None),
            (Chain.GNOSIS, RelayProvider, None),
            pytest.param(
                Chain.MODE,
                NativeBridgeProvider,
                OptimismContractAdaptor,
                marks=pytest.mark.xfail(reason="MODE chain unstable"),
            ),
            (Chain.OPTIMISM, NativeBridgeProvider, OptimismContractAdaptor),
            (Chain.POLYGON, RelayProvider, None),
        ],
    )
    def test_correct_providers_native(
        self,
        tmp_path: Path,
        password: str,
        to_chain_enum: Chain,
        expected_provider_cls: t.Type[Provider],
        expected_contract_adaptor_cls: type[BridgeContractAdaptor],
    ) -> None:
        """test_correct_providers_bridge_native"""
        self._main_test_correct_providers(
            tmp_path=tmp_path,
            password=password,
            from_chain=Chain.ETHEREUM.value,
            from_token=ZERO_ADDRESS,
            to_chain=to_chain_enum.value,
            to_token=ZERO_ADDRESS,
            expected_provider_cls=expected_provider_cls,
            expected_contract_adaptor_cls=expected_contract_adaptor_cls,
        )

    @pytest.mark.parametrize(
        "to_chain_enum",
        [
            Chain.ARBITRUM_ONE,
            Chain.BASE,
            Chain.CELO,
            Chain.GNOSIS,
            pytest.param(
                Chain.MODE, marks=pytest.mark.xfail(reason="MODE chain unstable")
            ),
            Chain.OPTIMISM,
            Chain.POLYGON,
        ],
    )
    @pytest.mark.parametrize("token_dict", [OLAS, USDC])
    def test_correct_providers_token_bridge(
        self,
        tmp_path: Path,
        password: str,
        to_chain_enum: Chain,
        token_dict: t.Dict,
    ) -> None:
        """test_correct_providers_bridge_token"""
        expected_provider_cls: type[Provider] = NativeBridgeProvider
        expected_contract_adaptor_cls: t.Optional[
            t.Type[BridgeContractAdaptor]
        ] = OptimismContractAdaptor

        if to_chain_enum in [
            Chain.ARBITRUM_ONE,
            Chain.CELO,
            Chain.POLYGON,
        ]:  # Superbridge reports Relay instead of native bridge for CELO
            expected_provider_cls = RelayProvider
            expected_contract_adaptor_cls = None
        elif to_chain_enum == Chain.BASE and token_dict == USDC:
            expected_provider_cls = LiFiProvider
            expected_contract_adaptor_cls = None
        elif to_chain_enum == Chain.GNOSIS:
            expected_provider_cls = NativeBridgeProvider
            expected_contract_adaptor_cls = OmnibridgeContractAdaptor
        elif to_chain_enum == Chain.OPTIMISM and token_dict == USDC:
            expected_provider_cls = LiFiProvider
            expected_contract_adaptor_cls = None

        self._main_test_correct_providers(
            tmp_path=tmp_path,
            password=password,
            from_chain=Chain.ETHEREUM.value,
            from_token=token_dict[Chain.ETHEREUM],
            to_chain=to_chain_enum.value,
            to_token=token_dict[to_chain_enum],
            expected_provider_cls=expected_provider_cls,
            expected_contract_adaptor_cls=expected_contract_adaptor_cls,
        )

    @pytest.mark.flaky(reruns=3, reruns_delay=30)
    @pytest.mark.parametrize(
        "to_chain_enum",
        [
            Chain.ARBITRUM_ONE,
            Chain.BASE,
            Chain.CELO,
            Chain.GNOSIS,
            pytest.param(
                Chain.MODE, marks=pytest.mark.xfail(reason="MODE chain unstable")
            ),
            Chain.OPTIMISM,
            Chain.POLYGON,
        ],
    )
    @pytest.mark.parametrize("token_dict", [USDC, OLAS])
    def test_correct_providers_token_swap(
        self,
        tmp_path: Path,
        password: str,
        to_chain_enum: Chain,
        token_dict: t.Dict,
    ) -> None:
        """test_correct_providers_swap_token"""
        self._main_test_correct_providers(
            tmp_path=tmp_path,
            password=password,
            from_chain=Chain.ETHEREUM.value,
            from_token=ZERO_ADDRESS,
            to_chain=to_chain_enum.value,
            to_token=token_dict[to_chain_enum],
            expected_provider_cls=RelayProvider,
            expected_contract_adaptor_cls=None,
        )

    @pytest.mark.parametrize(
        "from_chain_enum",
        [
            Chain.ARBITRUM_ONE,
            Chain.BASE,
            Chain.OPTIMISM,
        ],
    )
    @pytest.mark.parametrize("token_dict", [USDC, OLAS])
    def test_correct_providers_token_swap_celo(
        self,
        tmp_path: Path,
        password: str,
        from_chain_enum: Chain,
        token_dict: t.Dict,
    ) -> None:
        """test_correct_providers_swap_token"""
        self._main_test_correct_providers(
            tmp_path=tmp_path,
            password=password,
            from_chain=from_chain_enum.value,
            from_token=ZERO_ADDRESS,
            to_chain=Chain.CELO.value,
            to_token=token_dict[Chain.CELO],
            expected_provider_cls=RelayProvider,
            expected_contract_adaptor_cls=None,
        )

    def _main_test_correct_providers(
        self,
        tmp_path: Path,
        password: str,
        from_chain: str,
        from_token: str,
        to_chain: str,
        to_token: str,
        expected_provider_cls: t.Type[Provider],
        expected_contract_adaptor_cls: t.Optional[t.Type[BridgeContractAdaptor]],
        check_price: bool = True,
        margin: float = 0.15,
    ) -> None:
        """_main_test_correct_providers"""
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        bridge_manager = operate.bridge_manager

        wallet_address = operate.wallet_manager.load(LedgerType.ETHEREUM).address

        amount_unit = 50
        if to_token in USDC.values():
            to_decimals = 6
        else:
            to_decimals = 18

        if from_token in USDC.values():
            from_decimals = 6
        else:
            from_decimals = 18

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
                    "amount": amount_unit * (10**to_decimals),
                },
            },
        ]

        bundle = bridge_manager.data.last_requested_bundle
        assert bundle is None, "Wrong bundle."
        refill_requirements = bridge_manager.bridge_refill_requirements(
            requests_params=params, force_update=False
        )

        for request_status in refill_requirements["bridge_request_status"]:
            if request_status["message"] == "no routes found":
                continue

            assert (
                request_status["status"] == ProviderRequestStatus.QUOTE_DONE
            ), f"Wrong bundle for params\n{params}"

        bundle = bridge_manager.data.last_requested_bundle
        assert bundle is not None, "Wrong bundle."
        assert len(bundle.provider_requests) == 1, "Wrong bundle."
        request = bundle.provider_requests[0]
        bridge = bridge_manager._providers[request.provider_id]

        assert isinstance(
            bridge, expected_provider_cls
        ), f"Expected provider {expected_provider_cls}, got {type(bridge)}"

        if isinstance(bridge, NativeBridgeProvider):
            assert expected_contract_adaptor_cls is not None, "Wrong contract adaptor."
            assert isinstance(
                bridge.bridge_contract_adaptor, expected_contract_adaptor_cls
            ), f"Expected adaptor {expected_contract_adaptor_cls}, got {type(bridge.bridge_contract_adaptor)}"

        if check_price:
            to_price_usd = self._get_token_price_usd(to_chain, to_token)
            from_price_usd = self._get_token_price_usd(from_chain, from_token)
            print(f"{to_price_usd=}")
            print(f"{from_price_usd=}")

            if to_price_usd is None or from_price_usd is None:
                pytest.skip("Token price could not be retrieved; skipping price check.")
                return

            refill_amount = refill_requirements["bridge_total_requirements"][
                from_chain
            ][wallet_address][from_token]

            print(f"{refill_amount=}")

            quoted_from_cost_usd = (
                refill_amount * from_price_usd / (10**from_decimals)
            )
            expected_to_cost_usd = amount_unit * to_price_usd
            print(f"Expected cost on {to_chain}: {expected_to_cost_usd}")
            print(f"Quoted cost on {from_chain}: {quoted_from_cost_usd}")

            overpaid_usd = max(quoted_from_cost_usd - expected_to_cost_usd, 0)
            overpaid_percent = (overpaid_usd / expected_to_cost_usd) * 100
            print(
                f"Overpaid {overpaid_usd:.2f} USD ({overpaid_percent:.2f}% < {margin*100:.2f}%)"
            )

            assert quoted_from_cost_usd <= expected_to_cost_usd * (
                1.0 + margin
            ), f"Quoted cost exceeds {margin * 100:.2f}% margin"
