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

import pytest
from fastapi.testclient import TestClient

from operate.cli import create_app
from operate.constants import ZERO_ADDRESS
from operate.ledger import CHAINS
from operate.ledger.profiles import DUST, OLAS, USDC
from operate.operate_types import Chain, OnChainState

from tests.conftest import (
    OperateTestEnv,
    get_balance,
    tenderly_add_balance,
    tenderly_increase_time,
)
from tests.constants import LOGGER, TESTNET_RPCS


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


class TestFunding:
    """Tests for services.funding."""

    @pytest.fixture(autouse=True)
    def _patch_rpcs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("operate.ledger.DEFAULT_RPCS", TESTNET_RPCS)
        monkeypatch.setattr("operate.ledger.DEFAULT_LEDGER_APIS", {})

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
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.DEPLOYED
            )

            for asset, amount in AGENT_FUNDING_ASSETS[chain].items():
                for agent_address in service.agent_addresses:
                    assert get_balance(chain, agent_address, asset) == 0
                    tenderly_add_balance(chain, agent_address, amount, asset)
                    assert get_balance(chain, agent_address, asset) == amount

            service_safe_address = chain_config.chain_data.multisig
            for asset, amount in SERVICE_SAFE_FUNDING_ASSETS[chain].items():
                assert get_balance(chain, service_safe_address, asset) == 0
                tenderly_add_balance(chain, service_safe_address, amount, asset)
                assert get_balance(chain, service_safe_address, asset) == amount

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
                    balance = get_balance(chain, agent_address, asset)
                    LOGGER.info(f"Remaining balance for {agent_address}: {balance}")
                    if asset == ZERO_ADDRESS:
                        assert balance < DUST[chain]
                    else:
                        assert balance == 0

            service_safe_address = chain_config.chain_data.multisig
            for asset in SERVICE_SAFE_FUNDING_ASSETS[chain]:
                assert get_balance(chain, service_safe_address, asset) == 0
