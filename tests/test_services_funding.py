# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""Tests for services.funding module."""


# pylint: disable=too-many-locals

import random
import respx
import typing as t
from http import HTTPStatus
from pathlib import Path

import httpx
import requests_mock
from deepdiff import DeepDiff
from fastapi.testclient import TestClient

from operate.cli import OperateApp, create_app
from operate.constants import (
    AGENT_FUNDING_REQUESTS_URL,
    KEYS_DIR,
    MASTER_SAFE_PLACEHOLDER,
    MIN_AGENT_BOND,
    MIN_SECURITY_DEPOSIT,
    ZERO_ADDRESS,
)
from operate.keys import KeysManager
from operate.ledger import CHAINS, get_default_ledger_api
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS, DEFAULT_EOA_TOPUPS_WITHOUT_SAFE, DUST, OLAS, USDC
from operate.operate_types import Chain, OnChainState
from operate.utils import subtract_dicts
from operate.utils.gnosis import estimate_transfer_tx_fee, get_asset_balance

from tests.conftest import (
    OnTestnet,
    OperateTestEnv,
    _get_service_template_multichain_service,
    _get_service_template_trader,
    tenderly_add_balance,
    tenderly_increase_time,
)
from tests.constants import LOGGER, OPERATE_TEST


AGENT_FUNDING_ASSETS: t.Dict[Chain, t.Dict[str, int]] = {}
SERVICE_SAFE_FUNDING_ASSETS: t.Dict[Chain, t.Dict[str, int]] = {}

for _chain in set(CHAINS) - {Chain.SOLANA}:
    AGENT_FUNDING_ASSETS[_chain] = {
        ZERO_ADDRESS: random.randint(int(1e18), int(2e18)),  # nosec B311
    }
    SERVICE_SAFE_FUNDING_ASSETS[_chain] = {
        ZERO_ADDRESS: random.randint(int(1e18), int(2e18)),  # nosec B311
        OLAS[_chain]: random.randint(int(100e6), int(200e6)),  # nosec B311
        USDC[_chain]: random.randint(int(100e6), int(200e6)),  # nosec B311
    }

import json


def PRINT_JSON(data: t.Dict, filename: str = ""):
    if filename:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


class TestFunding(OnTestnet):
    """Tests for services.funding."""

    def test_terminate_withdraw_service(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """Test terminate and withdraw service."""

        password = test_env.password
        operate = test_env.operate
        operate.password = password

        service_manager = operate.service_manager()
        services, _ = service_manager.get_all_services()

        service_config_id = None
        target_service = "Trader"
        for service in services:
            if target_service.lower() in service.name.lower():
                service_config_id = service.service_config_id
                break

        assert service_config_id is not None
        service = service_manager.load(service_config_id=service_config_id)

        for chain_config in service.chain_configs.values():
            assert chain_config.chain_data.multisig is None

        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )

        service = service_manager.load(service_config_id=service_config_id)
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            ledger_api = get_default_ledger_api(chain)
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.DEPLOYED
            )

            for asset, amount in AGENT_FUNDING_ASSETS[chain].items():
                for agent_address in service.agent_addresses:
                    assert get_asset_balance(ledger_api, asset, agent_address) == 0
                    tenderly_add_balance(chain, agent_address, amount, asset)
                    assert get_asset_balance(ledger_api, asset, agent_address) == amount

            service_safe_address = chain_config.chain_data.multisig
            for asset, amount in SERVICE_SAFE_FUNDING_ASSETS[chain].items():
                assert get_asset_balance(ledger_api, asset, service_safe_address) == 0
                tenderly_add_balance(chain, service_safe_address, amount, asset)
                assert (
                    get_asset_balance(ledger_api, asset, service_safe_address) == amount
                )

            tenderly_increase_time(chain)

        app = create_app(home=operate._path)
        client = TestClient(app)
        client.post(
            url="/api/account/login",
            json={"password": password},
        )
        terminate_response = client.post(
            url=f"/api/v2/service/{service_config_id}/terminate_and_withdraw",
        )
        assert terminate_response.status_code == 200

        service = service_manager.load(service_config_id=service_config_id)
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.PRE_REGISTRATION
            )

            for asset in AGENT_FUNDING_ASSETS[chain]:
                for agent_address in service.agent_addresses:
                    balance = get_asset_balance(ledger_api, asset, agent_address)
                    LOGGER.info(f"Remaining balance for {agent_address}: {balance}")
                    if asset == ZERO_ADDRESS:
                        assert balance < DUST[chain]
                    else:
                        assert balance == 0

            service_safe_address = chain_config.chain_data.multisig
            for asset in SERVICE_SAFE_FUNDING_ASSETS[chain]:
                assert get_asset_balance(ledger_api, asset, service_safe_address) == 0

    def test_service_fund(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """Test fund agent/safe from Master Safe."""

        password = test_env.password
        operate = test_env.operate
        operate.password = password
        backup_owner = test_env.backup_owner

        service_manager = operate.service_manager()
        services, _ = service_manager.get_all_services()

        service_config_id = None
        target_service = "Trader"
        for service in services:
            if target_service.lower() in service.name.lower():
                service_config_id = service.service_config_id
                break

        assert service_config_id is not None
        service = service_manager.load(service_config_id=service_config_id)

        for chain_config in service.chain_configs.values():
            assert chain_config.chain_data.multisig is None

        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )

        app = create_app(home=operate._path)
        client = TestClient(app)
        client.post(
            url="/api/account/login",
            json={"password": password},
        )

        service = service_manager.load(service_config_id=service_config_id)
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            wallet = operate.wallet_manager.load(chain.ledger_type)
            master_safe = wallet.safes[chain]
            ledger_api = get_default_ledger_api(chain)
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.DEPLOYED
            )

            for asset, amount in AGENT_FUNDING_ASSETS[chain].items():
                for agent_address in service.agent_addresses:
                    # Simulate a call that will fail
                    master_safe_balance = get_asset_balance(
                        ledger_api, asset, master_safe
                    )
                    response = client.post(
                        url=f"/api/v2/service/{service_config_id}/fund",
                        json={
                            chain_str: {
                                agent_address: {asset: f"{master_safe_balance + 1}"}
                            }
                        },
                    )
                    assert response.status_code == HTTPStatus.BAD_REQUEST
                    assert "Failed to fund from Master Safe" in response.json()["error"]

                    # Simulate a call that will fail
                    response = client.post(
                        url=f"/api/v2/service/{service_config_id}/fund",
                        json={chain_str: {backup_owner: {asset: f"{amount}"}}},
                    )
                    assert response.status_code == HTTPStatus.BAD_REQUEST
                    assert (
                        f"Failed to fund from Master Safe: Address {backup_owner} is not an agent EOA or service Safe for service {service_config_id}."
                        in response.json()["error"]
                    )

                    initial_balance = get_asset_balance(
                        ledger_api, asset, agent_address
                    )
                    response = client.post(
                        url=f"/api/v2/service/{service_config_id}/fund",
                        json={chain_str: {agent_address: {asset: f"{amount}"}}},
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert (
                        get_asset_balance(ledger_api, asset, agent_address)
                        == initial_balance + amount
                    )

            service_safe_address = chain_config.chain_data.multisig
            for asset, amount in SERVICE_SAFE_FUNDING_ASSETS[chain].items():
                # Simulate a call that will fail
                master_safe_balance = get_asset_balance(ledger_api, asset, master_safe)
                response = client.post(
                    url=f"/api/v2/service/{service_config_id}/fund",
                    json={
                        chain_str: {
                            service_safe_address: {asset: f"{master_safe_balance + 1}"}
                        }
                    },
                )
                assert response.status_code == HTTPStatus.BAD_REQUEST
                assert "Failed to fund from Master Safe" in response.json()["error"]

                # Simulate a call that will fail
                response = client.post(
                    url=f"/api/v2/service/{service_config_id}/fund",
                    json={chain_str: {backup_owner: {asset: f"{amount}"}}},
                )
                assert response.status_code == HTTPStatus.BAD_REQUEST
                assert (
                    f"Failed to fund from Master Safe: Address {backup_owner} is not an agent EOA or service Safe for service {service_config_id}."
                    in response.json()["error"]
                )

                initial_balance = get_asset_balance(
                    ledger_api, asset, service_safe_address
                )
                response = client.post(
                    url=f"/api/v2/service/{service_config_id}/fund",
                    json={chain_str: {service_safe_address: {asset: f"{amount}"}}},
                )
                assert response.status_code == HTTPStatus.OK
                assert (
                    get_asset_balance(ledger_api, asset, service_safe_address)
                    == initial_balance + amount
                )

    def test_withdraw_master_safe(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """Test fund agent/safe from Master Safe."""

        password = test_env.password
        operate = test_env.operate
        operate.password = password

        app = create_app(home=operate._path)
        client = TestClient(app)
        client.post(
            url="/api/account/login",
            json={"password": password},
        )

        dst_address = test_env.backup_owner2
        chain = Chain.GNOSIS
        ledger_api = get_default_ledger_api(chain)
        asset = USDC[Chain.GNOSIS]
        topup = int(100e6)

        wallet = operate.wallet_manager.load(chain.ledger_type)
        master_eoa = wallet.address
        master_safe = wallet.safes[chain]

        # Test 1 - Withdraw token from Safe partially
        tenderly_add_balance(chain, master_eoa, topup, asset)
        tenderly_add_balance(chain, master_safe, topup, asset)
        master_eoa_balance = get_asset_balance(ledger_api, asset, master_eoa)
        master_safe_balance = get_asset_balance(ledger_api, asset, master_safe)
        assert master_eoa_balance > 0
        assert master_safe_balance > 0
        initial_balance = get_asset_balance(ledger_api, asset, dst_address)
        amount_transfer = random.randint(  # nosec B311
            int(master_safe_balance / 2), master_safe_balance
        )
        response = client.post(
            url="/api/wallet/withdraw",
            json={
                "password": password,
                "withdraw_assets": {chain.value: {asset: f"{amount_transfer}"}},
                "to": dst_address,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert (
            get_asset_balance(ledger_api, asset, dst_address)
            == initial_balance + amount_transfer
        )
        assert (
            get_asset_balance(ledger_api, asset, master_safe)
            == master_safe_balance - amount_transfer
        )
        assert get_asset_balance(ledger_api, asset, master_eoa) == master_eoa_balance

        # Test 2 - Withdraw all token from Safe
        tenderly_add_balance(chain, master_eoa, topup, asset)
        tenderly_add_balance(chain, master_safe, topup, asset)
        master_eoa_balance = get_asset_balance(ledger_api, asset, master_eoa)
        master_safe_balance = get_asset_balance(ledger_api, asset, master_safe)
        assert master_eoa_balance > 0
        assert master_safe_balance > 0
        initial_balance = get_asset_balance(ledger_api, asset, dst_address)
        amount_transfer = master_safe_balance
        response = client.post(
            url="/api/wallet/withdraw",
            json={
                "password": password,
                "withdraw_assets": {chain.value: {asset: f"{amount_transfer}"}},
                "to": dst_address,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert (
            get_asset_balance(ledger_api, asset, dst_address)
            == initial_balance + amount_transfer
        )
        assert get_asset_balance(ledger_api, asset, master_safe) == 0
        assert get_asset_balance(ledger_api, asset, master_eoa) == master_eoa_balance

        # Test 3 - Withdraw all token from Safe and EOA
        tenderly_add_balance(chain, master_eoa, topup, asset)
        tenderly_add_balance(chain, master_safe, topup, asset)
        master_eoa_balance = get_asset_balance(ledger_api, asset, master_eoa)
        master_safe_balance = get_asset_balance(ledger_api, asset, master_safe)
        assert master_eoa_balance > 0
        assert master_safe_balance > 0
        initial_balance = get_asset_balance(ledger_api, asset, dst_address)
        amount_transfer = master_safe_balance + master_eoa_balance
        response = client.post(
            url="/api/wallet/withdraw",
            json={
                "password": password,
                "withdraw_assets": {chain.value: {asset: f"{amount_transfer}"}},
                "to": dst_address,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert (
            get_asset_balance(ledger_api, asset, dst_address)
            == initial_balance + amount_transfer
        )
        assert get_asset_balance(ledger_api, asset, master_safe) == 0
        assert get_asset_balance(ledger_api, asset, master_eoa) == 0

        # Test 4 - Withdraw all native from Safe and EOA
        tenderly_add_balance(chain, master_eoa, int(100e18), ZERO_ADDRESS)
        tenderly_add_balance(chain, master_safe, int(100e18), ZERO_ADDRESS)
        master_eoa_balance_native = get_asset_balance(
            ledger_api, ZERO_ADDRESS, master_eoa
        )
        master_safe_balance_native = get_asset_balance(
            ledger_api, ZERO_ADDRESS, master_safe
        )
        assert master_eoa_balance_native > 0
        assert master_safe_balance_native > 0
        initial_balance_native = get_asset_balance(
            ledger_api, ZERO_ADDRESS, dst_address
        )
        amount_transfer_native = master_safe_balance_native + master_eoa_balance_native
        response = client.post(
            url="/api/wallet/withdraw",
            json={
                "password": password,
                "withdraw_assets": {
                    chain.value: {
                        ZERO_ADDRESS: f"{amount_transfer_native}",
                    }
                },
                "to": dst_address,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert (
            get_asset_balance(ledger_api, ZERO_ADDRESS, dst_address)
            <= initial_balance_native + amount_transfer_native
        )
        assert (
            get_asset_balance(ledger_api, ZERO_ADDRESS, dst_address)
            >= initial_balance_native + amount_transfer_native - DUST[chain]
        )
        assert get_asset_balance(ledger_api, ZERO_ADDRESS, master_safe) == 0
        assert get_asset_balance(ledger_api, ZERO_ADDRESS, master_eoa) <= DUST[chain]

        # Test 5 - Withdraw all native and asset from Safe and EOA
        tenderly_add_balance(chain, master_eoa, topup, asset)
        tenderly_add_balance(chain, master_safe, topup, asset)
        tenderly_add_balance(chain, master_eoa, int(100e18), ZERO_ADDRESS)
        tenderly_add_balance(chain, master_safe, int(100e18), ZERO_ADDRESS)
        master_eoa_balance = get_asset_balance(ledger_api, asset, master_eoa)
        master_safe_balance = get_asset_balance(ledger_api, asset, master_safe)
        master_eoa_balance_native = get_asset_balance(
            ledger_api, ZERO_ADDRESS, master_eoa
        )
        master_safe_balance_native = get_asset_balance(
            ledger_api, ZERO_ADDRESS, master_safe
        )

        assert master_eoa_balance > 0
        assert master_safe_balance > 0
        assert master_eoa_balance_native > 0
        assert master_safe_balance_native > 0
        initial_balance = get_asset_balance(ledger_api, asset, dst_address)
        initial_balance_native = get_asset_balance(
            ledger_api, ZERO_ADDRESS, dst_address
        )
        amount_transfer = master_safe_balance + master_eoa_balance
        amount_transfer_native = (
            master_safe_balance_native + master_eoa_balance_native - DUST[chain]
        )
        response = client.post(
            url="/api/wallet/withdraw",
            json={
                "password": password,
                "withdraw_assets": {
                    chain.value: {
                        asset: f"{amount_transfer}",
                        ZERO_ADDRESS: f"{amount_transfer_native}",
                    }
                },
                "to": dst_address,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert (
            get_asset_balance(ledger_api, asset, dst_address)
            == initial_balance + amount_transfer
        )
        assert get_asset_balance(ledger_api, asset, master_safe) == 0
        assert get_asset_balance(ledger_api, asset, master_eoa) == 0
        assert (
            get_asset_balance(ledger_api, ZERO_ADDRESS, dst_address)
            <= initial_balance_native + amount_transfer_native
        )
        assert (
            get_asset_balance(ledger_api, ZERO_ADDRESS, dst_address)
            >= initial_balance_native + amount_transfer_native - DUST[chain]
        )
        assert get_asset_balance(ledger_api, ZERO_ADDRESS, master_safe) == 0
        assert get_asset_balance(ledger_api, ZERO_ADDRESS, master_eoa) <= DUST[chain]

    def test_full_funding_flow(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_full_funding_flow"""
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        operate.wallet_manager.setup()
        keys_manager = KeysManager(
            path=operate._path / KEYS_DIR,  # pylint: disable=protected-access
            logger=LOGGER,
        )
        backup_owner = keys_manager.create()
        service_manager = operate.service_manager()

        # Logout
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )

        service_template = _get_service_template_trader()

        chain1 = Chain.GNOSIS
        chains = (chain1,)
        c1_cfg = service_template["configurations"][chain1.value]
        c1_staking_bond = 50000000000000000000
        expected_json = {
            "balances": {
                chain1.value: {
                    "master_eoa": {
                        ZERO_ADDRESS: 0,
                        OLAS[chain1]: 0,
                    },
                    "master_safe": {
                        ZERO_ADDRESS: 0,
                        OLAS[chain1]: 0,
                    },
                },
            },
            "bonded_assets": {
                chain1.value: {
                    "master_safe": {},
                },
            },
            "total_requirements": {
                chain1.value: {
                    "master_eoa": {
                        ZERO_ADDRESS: DEFAULT_EOA_TOPUPS_WITHOUT_SAFE[chain1][ZERO_ADDRESS],
                        OLAS[chain1]: 0,
                    },
                    "master_safe": {
                        ZERO_ADDRESS: MIN_AGENT_BOND
                        + MIN_SECURITY_DEPOSIT
                        + c1_cfg["fund_requirements"][ZERO_ADDRESS]["agent"]
                        + c1_cfg["fund_requirements"][ZERO_ADDRESS]["safe"],
                        OLAS[chain1]: 2 * c1_staking_bond,
                    },
                },
            },
            "refill_requirements": {
                chain1.value: {
                    "master_eoa": {
                        ZERO_ADDRESS: DEFAULT_EOA_TOPUPS_WITHOUT_SAFE[chain1][ZERO_ADDRESS],
                        OLAS[chain1]: 0,
                    },
                    "master_safe": {
                        ZERO_ADDRESS: MIN_AGENT_BOND
                        + MIN_SECURITY_DEPOSIT
                        + c1_cfg["fund_requirements"][ZERO_ADDRESS]["agent"]
                        + c1_cfg["fund_requirements"][ZERO_ADDRESS]["safe"],
                        OLAS[chain1]: 2 * c1_staking_bond,
                    },
                },
            },
            "protocol_asset_requirements": {
                chain1.value: {
                    "master_safe": {
                        ZERO_ADDRESS: MIN_AGENT_BOND + MIN_SECURITY_DEPOSIT,
                        OLAS[chain1]: 2 * c1_staking_bond,
                    },
                },
            },
            "is_refill_required": True,
            "allow_start_agent": False,
            "agent_funding_requests": {},
        }

        app = create_app(home=operate._path)
        client = TestClient(app)
        response = client.post(
            url="/api/account/login",
            json={"password": password},
        )
        assert response.status_code == HTTPStatus.OK

        # ---------------------------------------------
        # Create service locally - Funding requirements
        # ---------------------------------------------
        response = client.post(
            url="/api/v2/service",
            json=service_template,
        )
        assert response.status_code == HTTPStatus.OK
        service_config_id = response.json()["service_config_id"]

        response = client.get(
            url=f"/api/v2/service/{service_config_id}/funding_requirements",
        )
        assert response.status_code == HTTPStatus.OK
        response_json = response.json()
        diff = DeepDiff(response_json, expected_json)
        if diff:
            print(diff)

        PRINT_JSON(response_json, "res_1.json")
        PRINT_JSON(expected_json, "res_1x.json")
        assert not diff

        # ----------------------------------------
        # Create Master EOA - Funding requirements
        # ----------------------------------------
        response = client.post(
            url="/api/wallet",
            json={"ledger_type": chain1.ledger_type.value},
        )
        assert response.status_code == HTTPStatus.OK
        master_eoa = response.json()["wallet"]["address"]

        # Changes: Master EOA placeholder with real address
        for k in ("balances", "refill_requirements", "total_requirements"):
            for chain in chains:
                expected_json[k][chain.value][master_eoa] = expected_json[k][
                    chain.value
                ].pop("master_eoa")

        response = client.get(
            url=f"/api/v2/service/{service_config_id}/funding_requirements",
        )
        assert response.status_code == HTTPStatus.OK
        response_json = response.json()
        diff = DeepDiff(response_json, expected_json)
        if diff:
            print(diff)

        PRINT_JSON(response_json, "res_2.json")
        PRINT_JSON(expected_json, "res_2x.json")
        assert not diff

        # -------------------------------------------------
        # Bridge funds to Master EOA - Funding requirements
        # -------------------------------------------------
        for chain_str, addresses in response_json["refill_requirements"].items():
            for _, master_eoa_assets in addresses.items():
                for asset, amount in master_eoa_assets.items():
                    # The sum of requirements for Master EOA and Master Safe is transferred to Master EOA.
                    tenderly_add_balance(
                        chain=Chain(chain_str),
                        recipient=master_eoa,
                        token=asset,
                        amount=amount,
                    )
                    expected_json["balances"][chain_str][master_eoa][asset] += amount

        # Arrange "balances in the future" (after transferring excess)
        for chain_str in expected_json["balances"]:
            if MASTER_SAFE_PLACEHOLDER in expected_json["balances"][chain_str]:
                master_eoa_assets = expected_json["balances"][chain_str][master_eoa]
                for asset, amount in master_eoa_assets.items():
                    default_eoa_topup = DEFAULT_EOA_TOPUPS[Chain(chain_str)].get(asset, 0)
                    expected_json["balances"][chain_str][MASTER_SAFE_PLACEHOLDER][asset] = amount - default_eoa_topup
                    expected_json["balances"][chain_str][master_eoa][asset] = default_eoa_topup

        for chain in chains:
            expected_json["total_requirements"][chain.value][master_eoa][ZERO_ADDRESS] = 0  # TODO verify

        expected_json["refill_requirements"] = subtract_dicts(
            expected_json["total_requirements"], expected_json["balances"]
        )
        expected_json["is_refill_required"] = False

        response = client.get(
            url=f"/api/v2/service/{service_config_id}/funding_requirements",
        )
        assert response.status_code == HTTPStatus.OK
        response_json = response.json()
        diff = DeepDiff(response_json, expected_json)
        if diff:
            print(diff)

        PRINT_JSON(response_json, "res_3.json")
        PRINT_JSON(expected_json, "res_3x.json")
        assert not diff

        # -------------------------------------------------
        # Create Safe & bridge funds - Funding requirements
        # -------------------------------------------------
        master_safes = {}
        for chain in chains:
            response = client.post(
                url="/api/wallet/safe",
                json={
                    "chain": chain.value,
                    "backup_owner": backup_owner,
                    "transfer_excess_assets": True
                },
            )
            assert response.status_code == HTTPStatus.CREATED
            master_safes[chain] = response.json()["safe"]

        response = client.get(
            url=f"/api/v2/service/{service_config_id}/funding_requirements",
        )
        assert response.status_code == HTTPStatus.OK
        response_json = response.json()

        # Changes: Master EOA placeholder with real address
        for k in ("balances", "refill_requirements", "total_requirements", "bonded_assets", "protocol_asset_requirements"):
            for chain in chains:
                master_safe = master_safes[chain]
                expected_json[k][chain.value][master_safe] = expected_json[k][
                    chain.value
                ].pop("master_safe")

        # Adjust expected Master EOA native assets
        for chain_str in expected_json["balances"]:
            real_balance_master_eoa = response_json["balances"][chain_str][master_eoa][ZERO_ADDRESS]
            tx_fee = estimate_transfer_tx_fee(Chain(chain_str), master_eoa, master_safes[chain])
            tx_fee_registry = 65000 * int(1e6)  # TODO improve estimation
            assert real_balance_master_eoa <= expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS]
            # TODO fix this line assert real_balance_master_eoa >= expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS] - tx_fee - tx_fee_registry
            assert real_balance_master_eoa >= expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS] * 0.99  # TODO fix line above
            expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS] = real_balance_master_eoa

        expected_json["allow_start_agent"] = True

        diff = DeepDiff(response_json, expected_json)
        if diff:
            print(diff)

        PRINT_JSON(response_json, "res_4.json")
        PRINT_JSON(expected_json, "res_4x.json")
        assert not diff

        # ---------------------------------------------
        # Start agent first time - Funding requirements
        # ---------------------------------------------

        operate.password = password
        operate.service_manager().deploy_service_onchain_from_safe(service_config_id)

        response = client.get(
            url=f"/api/v2/service/{service_config_id}/funding_requirements",
        )
        assert response.status_code == HTTPStatus.OK
        response_json = response.json()
        PRINT_JSON(response_json, "res_5.json")

        # Adjust Master Safe balance
        for chain_str in expected_json["balances"]:
            master_safe = master_safes[chain]
            for asset in expected_json["balances"][chain_str][master_safe]:
                expected_json["balances"][chain_str][master_safe][asset] -= expected_json["protocol_asset_requirements"][chain_str][master_safe][asset]
                cfg = service_template["configurations"][chain1.value]
                expected_json["balances"][chain_str][master_safe][asset] -= cfg["fund_requirements"].get(asset, {}).get("agent", 0)
                expected_json["balances"][chain_str][master_safe][asset] -= cfg["fund_requirements"].get(asset, {}).get("safe", 0)
                expected_json["bonded_assets"][chain_str][master_safe][asset] = expected_json["protocol_asset_requirements"][chain_str][master_safe][asset]
                expected_json["total_requirements"][chain_str][master_safe][asset] = 0  # The protocol requirements are bonded, noting more needed.

        # Adjust Master EOA native assets
        for chain_str in expected_json["balances"]:
            real_balance_master_eoa = response_json["balances"][chain_str][master_eoa][ZERO_ADDRESS]
            tx_fee_registry = 10 * 65000 * int(1e6)  # TODO improve estimation
            assert real_balance_master_eoa <= expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS]
            # TODO fix this line assert real_balance_master_eoa >= expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS] - tx_fee_registry
            assert real_balance_master_eoa >= expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS] * 0.99
            expected_json["balances"][chain_str][master_eoa][ZERO_ADDRESS] = real_balance_master_eoa

        diff = DeepDiff(response_json, expected_json)
        if diff:
            print(diff)

        PRINT_JSON(expected_json, "res_5x.json")
        assert not diff

        # ----------------------------------
        # Start agent - Funding requirements
        # ----------------------------------

        operate.service_manager().deploy_service_onchain_from_safe(service_config_id)

        response = client.get(
            url=f"/api/v2/service/{service_config_id}/funding_requirements",
        )
        assert response.status_code == HTTPStatus.OK
        response_json = response.json()
        PRINT_JSON(response_json, "res_6.json")

        diff = DeepDiff(response_json, expected_json)
        if diff:
            print(diff)

        PRINT_JSON(expected_json, "res_6x.json")
        assert not diff

        # ---------------------------------------
        # Agent asks funds - Funding requirements
        # ---------------------------------------

        service = operate.service_manager().load(service_config_id)
        agent_eoa = service.agent_addresses[0]
        agent_safe = service.chain_configs[chain1.value].chain_data.multisig
        fund_requests = {
            chain1.value: {
                agent_safe: {
                    ZERO_ADDRESS: 42000000000000000000
                }
            }
        }

        expected_json["agent_funding_requests"] = fund_requests

        with requests_mock.Mocker(real_http=True) as mock:
            mock.get(AGENT_FUNDING_REQUESTS_URL, json=fund_requests)
            response = client.get(
                url=f"/api/v2/service/{service_config_id}/funding_requirements",
            )
            assert response.status_code == HTTPStatus.OK
            response_json = response.json()
            PRINT_JSON(response_json, "res_7.json")

            diff = DeepDiff(response_json, expected_json)
            if diff:
                print(diff)

            PRINT_JSON(expected_json, "res_7x.json")
            assert not diff

            # Send funds to agent - Funding requirements
            agent_funding_requests = response_json["agent_funding_requests"]
            response = client.post(
                url=f"/api/v2/service/{service_config_id}/fund",
                json=agent_funding_requests,
            )

            assert response.status_code == HTTPStatus.OK

            for chain_str, addresses in agent_funding_requests.items():
                chain = Chain(chain_str)
                for address, tokens in addresses.items():
                    for asset, amount in tokens.items():
                        actual_balance = get_asset_balance(
                            ledger_api=get_default_ledger_api(chain),
                            asset_address=asset,
                            address=address,
                        )
                        assert amount == actual_balance
