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

import pytest

from operate.ledger import get_default_ledger_api
from operate.operate_types import Chain
from operate.services.protocol import StakingState
from operate.utils.gnosis import get_owners

from tests.conftest import OnFork, OperateTestEnv, fork_increase_time
from tests.test_health_checker_restake_integration import (
    SERVICE_CHAIN,
    STAKING_PROGRAM,
    _deploy_and_stake,
)


class TestRetiredProgramUnstakeIntegration(OnFork):
    """`unstake_services_on_retired_programs`, against a fork."""

    @pytest.mark.integration
    def test_unstakes_once_the_minimum_period_is_over(
        self, test_env: OperateTestEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inside the period nothing moves; after it the service is unstaked.

        The unstake must leave the Safe owners and the local deployment as they were.
        """
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = _deploy_and_stake(test_env)
        monkeypatch.setattr(
            "operate.ledger.profiles.RETIRED_STAKING_PROGRAMS",
            {Chain.GNOSIS: frozenset({STAKING_PROGRAM})},
        )
        ledger_api = get_default_ledger_api(SERVICE_CHAIN)
        service = service_manager.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[SERVICE_CHAIN.value]
        sftxb = service_manager.get_eth_safe_tx_builder(
            ledger_config=chain_config.ledger_config
        )
        service_safe = chain_config.chain_data.multisig
        owners_before = get_owners(ledger_api=ledger_api, safe=service_safe)
        deployment_status_before = service.deployment.status

        service_manager.unstake_services_on_retired_programs()

        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.STAKED
        ), "a service inside its minimum staking period must stay staked"

        # Default warp is minStakingDuration + 1.
        fork_increase_time(SERVICE_CHAIN)
        service_manager.unstake_services_on_retired_programs()

        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.UNSTAKED
        )
        assert get_owners(ledger_api=ledger_api, safe=service_safe) == owners_before
        reloaded = service_manager.load(service_config_id=service_config_id)
        assert reloaded.deployment.status == deployment_status_before
