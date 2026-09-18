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

"""Integration test for the staking reconciliation the health checker performs.

`ServiceManager.reconcile_staking_for_restart` is a new caller of the on-chain
staking flow, reached from the health checker's restart loop rather than from a
user-initiated deploy. These tests drive it directly against a Tenderly fork —
not through the health-check loop, which would make them wall-clock bound.

The two sub-cases the middleware must tell apart are both exercised:

* past `minStakingDuration`, the eviction is cleared and the service ends staked;
* inside it with rewards outstanding, nothing is sent on-chain and the outcome
  is the one the API reports as `evicted_cannot_restake`.
"""

import typing as t

import pytest
from autonomy.chain.tx import TxSettler
from web3 import Web3

from operate.data import DATA_DIR
from operate.data.contracts.staking_token.contract import StakingTokenContract
from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import get_staking_contract
from operate.operate_types import (
    Chain,
    LedgerType,
    OnChainState,
    StakingReconcileOutcome,
)
from operate.services.protocol import StakingState

from tests.conftest import OnTestnet, OperateTestEnv, tenderly_increase_time
from tests.constants import LOGGER

SERVICE_CHAIN = Chain.GNOSIS
# The Trader template in conftest stakes here on first deploy.
STAKING_PROGRAM = "pearl_beta_2"
# Eviction needs maxNumInactivityPeriods consecutive misses; allow a couple of
# spare rounds so a contract that counts differently still converges.
MAX_CHECKPOINTS = 8

_STAKING_CTR = t.cast(
    StakingTokenContract,
    StakingTokenContract.from_dir(
        directory=str(DATA_DIR / "contracts" / "staking_token")
    ),
)


def _staking_params(ledger_api: t.Any, staking_contract: str) -> t.Dict[str, int]:
    """Read the eviction-relevant parameters off the staking contract."""
    instance = _STAKING_CTR.get_instance(
        ledger_api=ledger_api, contract_address=staking_contract
    )
    return {
        "liveness_period": instance.functions.livenessPeriod().call(),
        "max_inactivity_periods": instance.functions.maxNumInactivityPeriods().call(),
        "min_staking_duration": instance.functions.minStakingDuration().call(),
        "available_rewards": instance.functions.availableRewards().call(),
    }


def _send_checkpoint(service_manager: t.Any, staking_contract: str) -> None:
    """Call the permissionless `checkpoint()` from the master EOA."""
    ledger_api = get_default_ledger_api(SERVICE_CHAIN)
    wallet = service_manager.wallet_manager.load(LedgerType.ETHEREUM)
    calldata = t.cast(
        bytes,
        _STAKING_CTR.build_checkpoint_tx(
            ledger_api=ledger_api, contract_address=staking_contract
        )["data"],
    )

    def _build_tx() -> t.Dict:
        tx = {
            "from": wallet.crypto.address,
            "to": Web3.to_checksum_address(staking_contract),
            "data": "0x" + calldata.hex(),
            "value": 0,
            "chainId": SERVICE_CHAIN.id,
            "nonce": ledger_api.api.eth.get_transaction_count(wallet.crypto.address),
            # `update_with_gas_estimate` drops this key before estimating and
            # raises `KeyError` if it is absent, so it has to be seeded.
            "gas": 0,
        }
        return ledger_api.update_with_gas_estimate(transaction=tx, raise_on_try=True)

    TxSettler(
        ledger_api=ledger_api,
        crypto=wallet.crypto,
        chain_type=SERVICE_CHAIN,
        tx_builder=_build_tx,
    ).transact().settle()


def _deploy_and_stake(test_env: OperateTestEnv) -> t.Tuple[t.Any, str, int, str]:
    """Deploy the Trader service on-chain and return its staking handles."""
    operate = test_env.operate
    operate.password = test_env.password
    service_manager = operate.service_manager()

    services, _ = service_manager.get_all_services()
    service_config_id = next(
        svc.service_config_id for svc in services if "trader" in svc.name.lower()
    )
    service_manager.deploy_service_onchain_from_safe(
        service_config_id=service_config_id
    )

    service = service_manager.load(service_config_id=service_config_id)
    chain_str = SERVICE_CHAIN.value
    token_id = service.chain_configs[chain_str].chain_data.token
    staking_contract = get_staking_contract(SERVICE_CHAIN, STAKING_PROGRAM)

    assert (
        service_manager._get_on_chain_state(  # noqa: SLF001
            service=service, chain=chain_str
        )
        == OnChainState.DEPLOYED
    )
    sftxb = service_manager.get_eth_safe_tx_builder(
        ledger_config=service.chain_configs[chain_str].ledger_config
    )
    assert (
        sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
        == StakingState.STAKED
    ), "service should be staked after the first deploy"

    return service_manager, service_config_id, token_id, staking_contract


def _evict(
    service_manager: t.Any,
    sftxb: t.Any,
    token_id: int,
    staking_contract: str,
    ledger_api: t.Any,
) -> int:
    """Warp past liveness periods and checkpoint until the service is evicted.

    :return: The number of seconds warped before the service was evicted.
    """
    params = _staking_params(ledger_api, staking_contract)
    warped = 0
    for _ in range(MAX_CHECKPOINTS):
        tenderly_increase_time(SERVICE_CHAIN, params["liveness_period"] + 1)
        warped += params["liveness_period"] + 1
        _send_checkpoint(service_manager, staking_contract)
        if (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.EVICTED
        ):
            LOGGER.info("Service %s evicted after %s seconds", token_id, warped)
            return warped

    raise AssertionError(
        f"service {token_id} was not evicted after {MAX_CHECKPOINTS} checkpoints "
        f"({warped}s warped); staking parameters: {params}"
    )


class TestHealthCheckerRestakeIntegration(OnTestnet):
    """The reconciliation the health checker runs, against a live Tenderly fork."""

    @pytest.mark.integration
    def test_reconciles_an_eviction_it_can_clear(
        self, test_env: OperateTestEnv
    ) -> None:
        """Past minStakingDuration, the eviction is unstaked and re-staked."""
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = _deploy_and_stake(test_env)
        ledger_api = get_default_ledger_api(SERVICE_CHAIN)
        service = service_manager.load(service_config_id=service_config_id)
        sftxb = service_manager.get_eth_safe_tx_builder(
            ledger_config=service.chain_configs[SERVICE_CHAIN.value].ledger_config
        )

        _evict(service_manager, sftxb, token_id, staking_contract, ledger_api)
        # Default warp is minStakingDuration + 1, so unstaking becomes possible.
        tenderly_increase_time(SERVICE_CHAIN)

        outcome = service_manager.reconcile_staking_for_restart(
            service_config_id=service_config_id
        )

        assert outcome == StakingReconcileOutcome.RECONCILED
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.STAKED
        ), "the service should be staked again, so the agent can boot and stay up"

    @pytest.mark.integration
    def test_reports_an_eviction_it_cannot_clear_without_transacting(
        self, test_env: OperateTestEnv
    ) -> None:
        """Inside minStakingDuration, nothing is sent and the state is unchanged.

        This is what pins the API's `evicted_cannot_restake` to a real on-chain
        condition rather than to a code path.
        """
        (
            service_manager,
            service_config_id,
            token_id,
            staking_contract,
        ) = _deploy_and_stake(test_env)
        ledger_api = get_default_ledger_api(SERVICE_CHAIN)
        service = service_manager.load(service_config_id=service_config_id)
        sftxb = service_manager.get_eth_safe_tx_builder(
            ledger_config=service.chain_configs[SERVICE_CHAIN.value].ledger_config
        )

        warped = _evict(service_manager, sftxb, token_id, staking_contract, ledger_api)
        params = _staking_params(ledger_api, staking_contract)
        if warped >= params["min_staking_duration"] or not params["available_rewards"]:
            pytest.skip(
                "this contract cannot be evicted while unstaking is still locked: "
                f"{params}, evicted after {warped}s"
            )

        # Every write in the staking flow is broadcast by the master EOA, and
        # this test's EOA is created fresh by the fixture, so its transaction
        # count is a counter only this test advances. The block number is not:
        # the integration suite runs under xdist against one shared Tenderly
        # testnet per chain, so other workers' transactions move it too.
        master_eoa = service_manager.wallet_manager.load(LedgerType.ETHEREUM).address
        nonce_before = ledger_api.api.eth.get_transaction_count(master_eoa)
        outcome = service_manager.reconcile_staking_for_restart(
            service_config_id=service_config_id
        )

        assert outcome == StakingReconcileOutcome.EVICTED_CANNOT_RESTAKE
        assert (
            ledger_api.api.eth.get_transaction_count(master_eoa) == nonce_before
        ), "no transaction should be sent for an eviction that cannot be cleared"
        assert (
            sftxb.staking_status(service_id=token_id, staking_contract=staking_contract)
            == StakingState.EVICTED
        )
