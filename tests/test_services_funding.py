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
import typing as t
from http import HTTPStatus

from fastapi.testclient import TestClient

from operate.cli import create_app
from operate.constants import ZERO_ADDRESS
from operate.ledger import CHAINS, get_default_ledger_api
from operate.ledger.profiles import DUST, OLAS, USDC
from operate.operate_types import Chain, OnChainState
from operate.utils.gnosis import get_asset_balance

from tests.conftest import (
    OnTestnet,
    OperateTestEnv,
    tenderly_add_balance,
    tenderly_increase_time,
)
from tests.constants import LOGGER


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

        initial_balances = {
            chain_str: {
                agent_address: {
                    asset: get_asset_balance(
                        get_default_ledger_api(Chain(chain_str)), asset, agent_address
                    )
                    for asset in AGENT_FUNDING_ASSETS[Chain(chain_str)]
                }
                for agent_address in service.agent_addresses
            }
            | {
                chain_config.chain_data.multisig: {
                    asset: get_asset_balance(
                        get_default_ledger_api(Chain(chain_str)),
                        asset,
                        chain_config.chain_data.multisig,
                    )
                    for asset in SERVICE_SAFE_FUNDING_ASSETS[Chain(chain_str)]
                }
            }
            for chain_str, chain_config in service.chain_configs.items()
        }

        response = client.post(
            url=f"/api/v2/service/{service_config_id}/fund",
            json={
                chain_str: {
                    agent_address: {
                        asset: f"{amount}"
                        for asset, amount in AGENT_FUNDING_ASSETS[
                            Chain(chain_str)
                        ].items()
                    }
                    for agent_address in service.agent_addresses
                }
                | {
                    chain_config.chain_data.multisig: {
                        asset: f"{amount}"
                        for asset, amount in SERVICE_SAFE_FUNDING_ASSETS[
                            Chain(chain_str)
                        ].items()
                    }
                }
                for chain_str, chain_config in service.chain_configs.items()
            },
        )
        assert response.status_code == HTTPStatus.OK
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            ledger_api = get_default_ledger_api(chain)
            for agent_address in service.agent_addresses:
                for asset, amount in AGENT_FUNDING_ASSETS[chain].items():
                    assert (
                        get_asset_balance(ledger_api, asset, agent_address)
                        == initial_balances[chain_str][agent_address][asset] + amount
                    )

            service_safe_address = chain_config.chain_data.multisig
            for asset, amount in SERVICE_SAFE_FUNDING_ASSETS[chain].items():
                assert (
                    get_asset_balance(ledger_api, asset, service_safe_address)
                    == initial_balances[chain_str][service_safe_address][asset] + amount
                )

    def test_withdraw(
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
        amount_transfer_native = (
            master_safe_balance_native + master_eoa_balance_native - 1
        )  # - 1 to check dust handling
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
