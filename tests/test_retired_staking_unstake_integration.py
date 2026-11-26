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

"""Fork tests for retired staking programs: the background unstake and the deploy guard."""

from unittest.mock import MagicMock

import pytest

from operate.constants import NO_STAKING_PROGRAM_ID
from operate.exceptions import RetiredStakingProgramError
from operate.ledger import get_default_ledger_api
from operate.operate_types import StakeFlowOutcome
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
    master_eoa_nonce,
    trader_sftxb,
    trader_staking_status,
)

#: A Gnosis program, other than the Trader's, to switch to.
OTHER_PROGRAM = "omenstrat_viii"


def _retire(monkeypatch: pytest.MonkeyPatch, staking_program_id: str) -> None:
    """Mark ``staking_program_id`` as the only retired program on the Trader's chain."""
    monkeypatch.setattr(
        "operate.ledger.profiles.RETIRED_STAKING_PROGRAMS",
        {TRADER_SERVICE_CHAIN: frozenset({staking_program_id})},
    )


def _retire_trader_program(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mark the program the Trader template stakes on as retired."""
    _retire(monkeypatch, TRADER_STAKING_PROGRAM)


def _logged(logger: MagicMock, level: str, fragment: str) -> bool:
    """Whether ``logger.<level>`` was called with a message containing ``fragment``."""
    return any(
        fragment in str(call.args[0]) for call in getattr(logger, level).call_args_list
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
        keeps the service staked. The logs prove it was that check, not an
        error the sweep swallowed. The unstake must leave the Safe owners and
        the local deployment alone.
        """
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = deploy_and_stake_trader(test_env)
        _retire_trader_program(monkeypatch)
        deployment_stop = MagicMock()
        deployment_start = MagicMock()
        monkeypatch.setattr("operate.services.service.Deployment.stop", deployment_stop)
        monkeypatch.setattr(
            "operate.services.service.Deployment.start", deployment_start
        )
        logger = MagicMock(wraps=service_manager.logger)
        monkeypatch.setattr(service_manager, "logger", logger)
        fork_empty_reward_pool(TRADER_SERVICE_CHAIN, staking_contract)

        ledger_api = get_default_ledger_api(TRADER_SERVICE_CHAIN)
        service = service_manager.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[TRADER_SERVICE_CHAIN.value]
        sftxb = trader_sftxb(service_manager, service_config_id)
        service_safe = chain_config.chain_data.multisig
        owners_before = get_owners(ledger_api=ledger_api, safe=service_safe)
        nonce_before = master_eoa_nonce(service_manager, TRADER_SERVICE_CHAIN)

        service_manager.unstake_services_on_retired_programs()

        logger.error.assert_not_called()
        assert _logged(logger, "info", "still inside its minimum staking period")
        assert (
            master_eoa_nonce(service_manager, TRADER_SERVICE_CHAIN) == nonce_before
        ), "nothing may be sent inside the minimum staking period"
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.STAKED
        )

        # Default warp is minStakingDuration + 1.
        fork_increase_time(TRADER_SERVICE_CHAIN)
        service_manager.unstake_services_on_retired_programs()

        logger.error.assert_not_called()
        assert _logged(logger, "info", "from the retired staking program")
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.UNSTAKED
        )
        assert get_owners(ledger_api=ledger_api, safe=service_safe) == owners_before
        deployment_stop.assert_not_called()
        deployment_start.assert_not_called()


class TestRetiredProgramDeployIntegration(OnFork):
    """The deploy guard and the stake flow on a retired program, against a fork."""

    @pytest.mark.integration
    def test_a_staked_deploy_is_refused_before_any_transaction(
        self, test_env: OperateTestEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Switching to a retired target program: refused, nothing sent.

        Past the minimum period with a new target, an unguarded deploy would
        unstake from the current program, so an unchanged nonce shows the
        refusal came before the first transaction.
        """
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = deploy_and_stake_trader(test_env)
        fork_increase_time(TRADER_SERVICE_CHAIN)
        service = service_manager.load(service_config_id=service_config_id)
        service.chain_configs[
            TRADER_SERVICE_CHAIN.value
        ].chain_data.user_params.staking_program_id = OTHER_PROGRAM
        service.store()
        _retire(monkeypatch, OTHER_PROGRAM)
        nonce_before = master_eoa_nonce(service_manager, TRADER_SERVICE_CHAIN)

        with pytest.raises(RetiredStakingProgramError) as exc_info:
            service_manager.deploy_service_onchain_from_safe(
                service_config_id=service_config_id
            )

        assert exc_info.value.staking_program_id == OTHER_PROGRAM
        assert master_eoa_nonce(service_manager, TRADER_SERVICE_CHAIN) == nonce_before
        assert (
            trader_staking_status(
                service_manager, service_config_id, token_id, staking_contract
            )
            == StakingState.STAKED
        )

    @pytest.mark.integration
    def test_a_no_staking_deploy_runs_and_unstakes_once_allowed(
        self, test_env: OperateTestEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The app's withdrawal-only payload: target ``no_staking`` deploys.

        Inside the period the contract keeps it staked; after it, the deploy
        unstakes it.
        """
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = deploy_and_stake_trader(test_env)
        _retire_trader_program(monkeypatch)
        service = service_manager.load(service_config_id=service_config_id)
        service.chain_configs[
            TRADER_SERVICE_CHAIN.value
        ].chain_data.user_params.staking_program_id = NO_STAKING_PROGRAM_ID
        service.store()

        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )
        assert (
            trader_staking_status(
                service_manager, service_config_id, token_id, staking_contract
            )
            == StakingState.STAKED
        )

        fork_increase_time(TRADER_SERVICE_CHAIN)
        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )
        assert (
            trader_staking_status(
                service_manager, service_config_id, token_id, staking_contract
            )
            == StakingState.UNSTAKED
        )

    @pytest.mark.integration
    def test_the_stake_flow_does_not_stake_on_a_retired_target(
        self, test_env: OperateTestEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unstaked service whose target is retired: the stake flow sends nothing."""
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = deploy_and_stake_trader(test_env)
        fork_increase_time(TRADER_SERVICE_CHAIN)
        service_manager.unstake_service_on_chain_from_safe(
            service_config_id=service_config_id,
            chain=TRADER_SERVICE_CHAIN.value,
            staking_program_id=TRADER_STAKING_PROGRAM,
        )
        assert (
            trader_staking_status(
                service_manager, service_config_id, token_id, staking_contract
            )
            == StakingState.UNSTAKED
        )
        _retire_trader_program(monkeypatch)
        nonce_before = master_eoa_nonce(service_manager, TRADER_SERVICE_CHAIN)

        outcome = service_manager.stake_service_on_chain_from_safe(
            service_config_id=service_config_id, chain=TRADER_SERVICE_CHAIN.value
        )

        assert outcome == StakeFlowOutcome.RETIRED_TARGET

        assert master_eoa_nonce(service_manager, TRADER_SERVICE_CHAIN) == nonce_before
        assert (
            trader_staking_status(
                service_manager, service_config_id, token_id, staking_contract
            )
            == StakingState.UNSTAKED
        )
