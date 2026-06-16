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

"""Integration test for the combined update mega-batch on Tenderly.

Verifies that updating an already DEPLOYED + STAKED service folds the teardown
(unstake -> terminate -> unbond -> recover_access) and the re-deploy
(update_mint -> activate -> register -> deploy -> stake) into a single
Master-Safe MultiSend. The update also migrates the service to a *different*
staking program, which is the strongest end-to-end proof that every sub-tx in
the batch actually executed (not skipped): the service ends unstaked from the
old program and staked in the new one.
"""

from unittest.mock import patch

import pytest
from autonomy.chain.base import registry_contracts

from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import CONTRACTS, OLAS, get_staking_contract
from operate.operate_types import Chain, LedgerType, OnChainState
from operate.services.protocol import StakingState

from tests.conftest import (
    OnTestnet,
    OperateTestEnv,
    tenderly_add_balance,
    tenderly_increase_time,
)
from tests.constants import LOGGER

SERVICE_CHAIN = Chain.GNOSIS
_OLAS_TOPUP = int(1000e18)
_INITIAL_PROGRAM = "pearl_beta_2"  # set by the Trader template in conftest
# Candidate programs to migrate to (all Trader / agent-id 14 programs).
_TARGET_PROGRAM_CANDIDATES = [
    "pearl_beta_3",
    "pearl_beta_4",
    "pearl_beta_5",
    "pearl_beta_6",
    "pearl_beta",
]


class TestCombinedUpdateBatchIntegration(OnTestnet):
    """Combined update mega-batch against a live Tenderly fork."""

    @pytest.mark.integration
    def test_update_migrates_staking_program_via_combined_batch(
        self, test_env: OperateTestEnv
    ) -> None:
        """Update + staking-program migration through one combined batch."""
        operate = test_env.operate
        operate.password = test_env.password
        service_manager = operate.service_manager()

        services, _ = service_manager.get_all_services()
        service_config_id = next(
            svc.service_config_id for svc in services if "trader" in svc.name.lower()
        )
        chain_str = SERVICE_CHAIN.value

        # ── Initial deploy: DEPLOYED + staked in the initial program ─────────
        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )
        service = service_manager.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain_str]
        chain_data = chain_config.chain_data
        token_id = chain_data.token
        assert (
            service_manager._get_on_chain_state(  # noqa: SLF001
                service=service, chain=chain_str
            )
            == OnChainState.DEPLOYED
        )

        wallet = service_manager.wallet_manager.load(LedgerType.ETHEREUM)
        master_safe = wallet.safes[SERVICE_CHAIN]
        ledger_api = get_default_ledger_api(SERVICE_CHAIN)
        sftxb = service_manager.get_eth_safe_tx_builder(
            ledger_config=chain_config.ledger_config
        )

        old_contract = get_staking_contract(SERVICE_CHAIN, _INITIAL_PROGRAM)
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=old_contract)
            == StakingState.STAKED
        ), "service should be staked in the initial program after first deploy"

        # Precondition the combined path targets: the service Safe is owned by
        # the agent EOA (not the Master Safe) with the recovery module enabled,
        # so recover_access is both required and feasible.
        owners_before = sftxb.get_service_safe_owners(service_id=token_id)
        assert owners_before != [master_safe], owners_before
        assert (
            registry_contracts.gnosis_safe.is_module_enabled(
                ledger_api=ledger_api,
                contract_address=chain_data.multisig,
                module_address=CONTRACTS[SERVICE_CHAIN]["recovery_module"],
            ).get("enabled")
            is True
        )

        # ── Pick a different target program with free slots + live rewards ───
        tenderly_increase_time(SERVICE_CHAIN)  # clear staking lock for unstake
        target_program = None
        target_contract = None
        for candidate in _TARGET_PROGRAM_CANDIDATES:
            contract = get_staking_contract(SERVICE_CHAIN, candidate)
            if (
                contract
                and sftxb.staking_slots_available(contract)
                and sftxb.staking_rewards_available(contract)
            ):
                target_program = candidate
                target_contract = contract
                break
        assert target_program is not None, "no suitable target program found"
        LOGGER.info(
            "Migrating staking program %s -> %s", _INITIAL_PROGRAM, target_program
        )

        # ── Prepare the update: top up OLAS, switch program, change metadata ─
        tenderly_add_balance(
            SERVICE_CHAIN, master_safe, _OLAS_TOPUP, OLAS[SERVICE_CHAIN]
        )
        chain_data.user_params.staking_program_id = target_program
        service.description = service.description + " (updated)"
        service.store()

        # ── Run the combined update; poison the legacy entry point ───────────
        # Capture the teardown prefix and make the legacy stepwise terminate
        # fail loudly if reached — proving the combined path runs.
        captured: dict = {}
        real_build = service_manager._build_update_teardown_prefix  # noqa: SLF001

        def _capture_prefix(*args: object, **kwargs: object) -> object:
            result = real_build(*args, **kwargs)
            captured["prefix"] = result
            return result

        with (
            patch.object(
                service_manager,
                "_build_update_teardown_prefix",
                side_effect=_capture_prefix,
            ),
            patch.object(
                service_manager,
                "terminate_service_on_chain_from_safe",
                side_effect=AssertionError(
                    "legacy stepwise fallback was taken instead of the combined batch"
                ),
            ),
        ):
            service_manager.deploy_service_onchain_from_safe(
                service_config_id=service_config_id
            )
        service = service_manager.load(service_config_id=service_config_id)
        chain_data = service.chain_configs[chain_str].chain_data

        # ── The combined path ran with the full teardown folded in ───────────
        prefix = captured.get("prefix")
        assert prefix is not None
        assert [label for _, label in prefix] == [
            "unstake",
            "terminate",
            "unbond",
            "recover_access",
        ]

        # ── Every sub-tx in the batch demonstrably executed (not skipped) ────
        # deploy -> DEPLOYED, with the agent EOA re-established as Safe owner
        # (which also proves recover_access ran: otherwise the in-batch
        # deploy-reuse would have reverted).
        assert (
            service_manager._get_on_chain_state(  # noqa: SLF001
                service=service, chain=chain_str
            )
            == OnChainState.DEPLOYED
        )
        assert sftxb.get_service_safe_owners(service_id=token_id) == [
            service.agent_addresses[0]
        ]
        # update_mint ran: the new description is reflected on-chain.
        on_chain_metadata = service_manager._get_on_chain_metadata(  # noqa: SLF001
            chain_config=service.chain_configs[chain_str]
        )
        assert on_chain_metadata.get("description") == service.description
        # unstake(old) + stake(new) ran: the service moved staking programs.
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=old_contract)
            == StakingState.UNSTAKED
        ), "service should be unstaked from the old program"
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=target_contract)
            == StakingState.STAKED
        ), "service should be staked in the new program"
        assert (
            service_manager._get_current_staking_program(  # noqa: SLF001
                service, chain_str
            )
            == target_program
        )
