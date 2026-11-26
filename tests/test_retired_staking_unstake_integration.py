# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Integration test for the background unstake from a retired staking program."""

from unittest.mock import MagicMock

import pytest

from operate.ledger import get_default_ledger_api
from operate.operate_types import Chain, LedgerType
from operate.services.protocol import StakingState
from operate.utils.gnosis import get_owners

from tests.conftest import (
    OnFork,
    OperateTestEnv,
    TRADER_SERVICE_CHAIN,
    TRADER_STAKING_PROGRAM,
    deploy_and_stake_trader,
    fork_empty_reward_pool,
    fork_increase_time,
)


class TestRetiredProgramUnstakeIntegration(OnFork):
    """`unstake_services_on_retired_programs`, against a fork."""

    @pytest.mark.integration
    def test_unstakes_once_the_minimum_period_is_over(
        self, test_env: OperateTestEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inside the period nothing is sent; after it the service is unstaked.

        The reward pool is emptied first: the contract then allows an unstake
        inside the period, so only the middleware's own minimum-period check
        keeps the service staked. The unstake must leave the Safe owners and
        the local deployment alone.
        """
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = deploy_and_stake_trader(test_env)
        monkeypatch.setattr(
            "operate.ledger.profiles.RETIRED_STAKING_PROGRAMS",
            {Chain.GNOSIS: frozenset({TRADER_STAKING_PROGRAM})},
        )
        deployment_stop = MagicMock()
        deployment_start = MagicMock()
        monkeypatch.setattr("operate.services.service.Deployment.stop", deployment_stop)
        monkeypatch.setattr(
            "operate.services.service.Deployment.start", deployment_start
        )
        fork_empty_reward_pool(TRADER_SERVICE_CHAIN, staking_contract)

        ledger_api = get_default_ledger_api(TRADER_SERVICE_CHAIN)
        service = service_manager.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[TRADER_SERVICE_CHAIN.value]
        sftxb = service_manager.get_eth_safe_tx_builder(
            ledger_config=chain_config.ledger_config
        )
        service_safe = chain_config.chain_data.multisig
        owners_before = get_owners(ledger_api=ledger_api, safe=service_safe)
        # Every write in the staking flow is broadcast by the master EOA, so its
        # transaction count tells whether anything was sent.
        master_eoa = service_manager.wallet_manager.load(LedgerType.ETHEREUM).address
        nonce_before = ledger_api.api.eth.get_transaction_count(master_eoa)

        service_manager.unstake_services_on_retired_programs()

        assert (
            ledger_api.api.eth.get_transaction_count(master_eoa) == nonce_before
        ), "nothing may be sent inside the minimum staking period"
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.STAKED
        )

        # Default warp is minStakingDuration + 1.
        fork_increase_time(TRADER_SERVICE_CHAIN)
        service_manager.unstake_services_on_retired_programs()

        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.UNSTAKED
        )
        assert get_owners(ledger_api=ledger_api, safe=service_safe) == owners_before
        deployment_stop.assert_not_called()
        deployment_start.assert_not_called()
