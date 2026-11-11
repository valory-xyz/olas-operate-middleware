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

"""Fork test: the Master Safe re-enables the recovery module on an Agent Safe it owns."""

import pytest
from autonomy.chain.base import registry_contracts

from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import CONTRACTS
from operate.operate_types import Chain, LedgerType, OnChainState
from operate.utils.gnosis import MultiSendOperation

from tests.conftest import OnFork, OperateTestEnv, fork_increase_time

SERVICE_CHAIN = Chain.GNOSIS
# Head of a Safe's linked list of modules.
_SENTINEL_MODULES = "0x0000000000000000000000000000000000000001"


class TestMasterSafeEnablesRecoveryModule(OnFork):
    """The Master Safe enables the recovery module on an Agent Safe it owns."""

    @pytest.mark.integration
    def test_master_safe_enables_the_module_on_its_agent_safe(
        self, test_env: OperateTestEnv
    ) -> None:
        """Disable the module on a Master-Safe-owned Agent Safe; a redeploy re-enables and reuses it."""
        operate = test_env.operate
        operate.password = test_env.password
        service_manager = operate.service_manager()
        services, _ = service_manager.get_all_services()
        service_config_id = next(
            svc.service_config_id for svc in services if "trader" in svc.name.lower()
        )
        chain_str = SERVICE_CHAIN.value

        # Deploy, then terminate: the teardown swaps the Agent Safe to the Master Safe.
        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )
        fork_increase_time(SERVICE_CHAIN)
        service_manager.terminate_service_on_chain_from_safe(
            service_config_id=service_config_id, chain=chain_str
        )
        service = service_manager.load(service_config_id=service_config_id)
        chain_config = service.chain_configs[chain_str]
        token_id = chain_config.chain_data.token
        assert (
            service_manager._get_on_chain_state(  # noqa: SLF001
                service=service, chain=chain_str
            )
            == OnChainState.PRE_REGISTRATION
        )
        sftxb = service_manager.get_eth_safe_tx_builder(
            ledger_config=chain_config.ledger_config
        )
        master_safe = service_manager.wallet_manager.load(LedgerType.ETHEREUM).safes[
            SERVICE_CHAIN
        ]
        assert sftxb.get_service_safe_owners(service_id=token_id) == [master_safe]
        agent_safe = sftxb.info(token_id=token_id)["multisig"]
        ledger_api = get_default_ledger_api(SERVICE_CHAIN)
        recovery_module = CONTRACTS[SERVICE_CHAIN]["recovery_module"]

        def _module_enabled() -> bool:
            return bool(
                registry_contracts.gnosis_safe.is_module_enabled(
                    ledger_api=ledger_api,
                    contract_address=agent_safe,
                    module_address=recovery_module,
                ).get("enabled")
            )

        assert _module_enabled()

        # Disable it through the Master Safe, so the enable below has work to do.
        safe_instance = registry_contracts.gnosis_safe.get_instance(
            ledger_api=ledger_api, contract_address=agent_safe
        )
        modules, _ = safe_instance.functions.getModulesPaginated(
            _SENTINEL_MODULES, 10
        ).call()
        index = modules.index(recovery_module)
        previous = _SENTINEL_MODULES if index == 0 else modules[index - 1]
        disable_data = safe_instance.encode_abi(
            abi_element_identifier="disableModule", args=[previous, recovery_module]
        )
        tx = sftxb.new_tx()
        for message in sftxb.get_safe_b_exec_messages(
            safe_b_address=agent_safe,
            txs=[
                {
                    "to": agent_safe,
                    "data": disable_data[2:],
                    "operation": MultiSendOperation.CALL,
                    "value": 0,
                }
            ],
        ):
            tx.add(message)
        tx.settle()
        assert not _module_enabled()

        # Redeploy: the deploy must enable the module and reuse the same Agent Safe.
        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )

        assert _module_enabled()
        service = service_manager.load(service_config_id=service_config_id)
        assert (
            service_manager._get_on_chain_state(  # noqa: SLF001
                service=service, chain=chain_str
            )
            == OnChainState.DEPLOYED
        )
        assert sftxb.info(token_id=token_id)["multisig"] == agent_safe
