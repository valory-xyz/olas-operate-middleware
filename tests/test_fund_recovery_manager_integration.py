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

"""Integration tests for FundRecoveryManager scan() and execute()."""

import typing as t
from unittest.mock import patch

import pytest

from operate.constants import ZERO_ADDRESS
from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import DUST, OLAS
from operate.operate_types import Chain, LedgerType, OnChainState
from operate.services.fund_recovery_manager import FundRecoveryManager
from operate.utils.gnosis import get_asset_balance

from tests.conftest import (
    OnTestnet,
    OperateTestEnv,
    tenderly_add_balance,
    tenderly_increase_time,
)
from tests.constants import CHAINS_TO_TEST, LOGGER

# Chains that the Trader service template covers (gnosis-only).
# CHAINS_TO_TEST includes Optimism but the template has no Optimism config,
# so only Gnosis will have an on-chain deployed service.
SERVICE_CHAINS = [Chain.GNOSIS]

# Amount to fund agent addresses and service safes (1 ETH-equivalent)
_FUND_AMOUNT = int(1e18)

# Module path for patching in FundRecoveryManager
_RECOVERY_MODULE = "operate.services.fund_recovery_manager"


class TestFundRecoveryManagerIntegration(OnTestnet):
    """Integration tests for FundRecoveryManager against live Tenderly forks."""

    @pytest.mark.integration
    @pytest.mark.flaky(reruns=2)
    def test_scan_and_execute_with_service(self, test_env: OperateTestEnv) -> None:
        """Full scan → execute round-trip with a deployed Trader service on Gnosis.

        The test_env fixture provides:
        - Funded Master EOA + Master Safe on Gnosis and Optimism
        - A Trader service created (not yet deployed) — gnosis chain only

        Note: Two external calls are patched because Tenderly virtual forks are
        not indexed by public APIs:
        - fetch_safes_for_owner: Safe TX Service API doesn't see fork safes.
        - _fetch_services_from_subgraph: The subgraph doesn't index fork services.

        This test:
        1. Deploys the service on-chain.
        2. Funds agent addresses and service safe.
        3. Runs scan() (patched) and asserts discovered balances and service state.
        4. Records pre-execute destination balance.
        5. Runs execute() (patched) and asserts success + funds moved to destination.
        6. Asserts EOA and Master Safe are drained on all chains.
        """
        # ── Setup ──────────────────────────────────────────────────────────────
        password = test_env.password
        operate = test_env.operate
        operate.password = password

        mnemonic = " ".join(test_env.mnemonics[LedgerType.ETHEREUM])
        wallet = test_env.wallet_manager.load(LedgerType.ETHEREUM)
        service_manager = operate.service_manager()

        # Find the Trader service created by test_env fixture
        services, _ = service_manager.get_all_services()
        service_config_id: t.Optional[str] = None
        for svc in services:
            if "trader" in svc.name.lower():
                service_config_id = svc.service_config_id
                break
        assert service_config_id is not None, "Trader service not found in test_env"

        # ── Step 4: Deploy service on-chain ────────────────────────────────────
        LOGGER.info("Deploying Trader service on-chain...")
        service_manager.deploy_service_onchain_from_safe(
            service_config_id=service_config_id
        )

        service = service_manager.load(service_config_id=service_config_id)

        # Collect on-chain token IDs per chain (needed for subgraph mock)
        known_service_ids: t.Dict[int, t.List[int]] = {}
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            token_id = chain_config.chain_data.token
            if token_id and token_id > 0:
                known_service_ids.setdefault(chain.id, []).append(token_id)
                LOGGER.info("On-chain service id=%s on chain %s", token_id, chain)

        # ── Step 5: Fund agent addresses and service safe, advance time ────────
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            ledger_api = get_default_ledger_api(chain)

            # Assert service is now deployed
            assert (
                service_manager._get_on_chain_state(  # pylint: disable=protected-access
                    service, chain_str
                )
                == OnChainState.DEPLOYED
            ), f"Expected DEPLOYED state on {chain}, got something else"

            # Fund each agent address with native
            for agent_address in service.agent_addresses:
                tenderly_add_balance(chain, agent_address, _FUND_AMOUNT, ZERO_ADDRESS)
                LOGGER.info(
                    "Funded agent %s on %s: %s wei",
                    agent_address,
                    chain,
                    get_asset_balance(ledger_api, ZERO_ADDRESS, agent_address),
                )

            # Fund service safe with native + OLAS
            service_safe = chain_config.chain_data.multisig
            assert service_safe is not None, f"Service safe not set for {chain}"
            tenderly_add_balance(chain, service_safe, _FUND_AMOUNT, ZERO_ADDRESS)
            tenderly_add_balance(chain, service_safe, _FUND_AMOUNT, OLAS[chain])
            LOGGER.info("Funded service safe %s on %s", service_safe, chain)

            # Advance time to clear staking lock periods
            tenderly_increase_time(chain)

        # ── Build known safe mapping (chain_id -> [safe_address]) ─────────────
        # The public Safe TX service cannot discover safes on Tenderly forks.
        known_safes: t.Dict[int, t.List[str]] = {}
        for chain in CHAINS_TO_TEST:
            safe_addr = wallet.safes.get(chain)
            if safe_addr:
                known_safes[chain.id] = [safe_addr]
                LOGGER.info(
                    "Registered safe %s for chain %s (id=%s)",
                    safe_addr,
                    chain,
                    chain.id,
                )

        def _mock_fetch_safes(chain_id: int, owner_address: str) -> t.List[str]:
            """Return pre-registered safe addresses for Tenderly fork testing."""
            return known_safes.get(chain_id, [])

        def _mock_fetch_subgraph(url: str, eoa_address: str) -> t.List[int]:
            """Return known on-chain service IDs for Tenderly fork testing.

            The real Gnosis subgraph doesn't index services minted on a Tenderly
            virtual fork.  We look up the chain by matching the subgraph URL.
            """
            from operate.services.fund_recovery_manager import SUBGRAPH_URLS

            for chain, subgraph_url in SUBGRAPH_URLS.items():
                if subgraph_url == url:
                    return known_service_ids.get(chain.id, [])
            return []

        # ── Step 6: Record pre-execute destination balances ────────────────────
        dest = test_env.backup_owner
        pre_balances: t.Dict[Chain, int] = {}
        for chain in CHAINS_TO_TEST:
            ledger_api = get_default_ledger_api(chain)
            pre_balances[chain] = get_asset_balance(ledger_api, ZERO_ADDRESS, dest)
            LOGGER.info(
                "Pre-execute dest balance on %s: %s", chain, pre_balances[chain]
            )

        # ── Step 7: Scan (with patched safe + subgraph discovery) ──────────────
        LOGGER.info("Running FundRecoveryManager.scan()...")
        with (
            patch(f"{_RECOVERY_MODULE}.fetch_safes_for_owner", _mock_fetch_safes),
            patch(
                f"{_RECOVERY_MODULE}._fetch_services_from_subgraph",
                _mock_fetch_subgraph,
            ),
        ):
            scan_result = FundRecoveryManager().scan(mnemonic)

        # ── Step 8: Assert master EOA address ─────────────────────────────────
        assert scan_result.master_eoa_address == wallet.address, (
            f"master_eoa_address mismatch: got {scan_result.master_eoa_address}, "
            f"expected {wallet.address}"
        )

        # ── Step 9: Assert non-zero balances on both chains ────────────────────
        for chain in CHAINS_TO_TEST:
            chain_id_str = str(chain.id)
            assert (
                chain_id_str in scan_result.balances
            ), f"Chain {chain} (id={chain_id_str}) not found in scan balances"
            chain_balances = scan_result.balances[chain_id_str]

            # EOA balance must appear
            assert (
                wallet.address in chain_balances
            ), f"EOA {wallet.address} not in balances for chain {chain}"
            eoa_native = int(chain_balances[wallet.address].get(ZERO_ADDRESS, 0))
            assert (
                eoa_native > 0
            ), f"EOA native balance on {chain} should be > 0, got {eoa_native}"

            # Master Safe balance must appear
            safe_addr = wallet.safes.get(chain)
            assert safe_addr is not None, f"No master safe set for {chain} in wallet"
            assert (
                safe_addr in chain_balances
            ), f"Master safe {safe_addr} not in balances for chain {chain}"
            safe_native = int(chain_balances[safe_addr].get(ZERO_ADDRESS, 0))
            assert (
                safe_native > 0
            ), f"Master safe native balance on {chain} should be > 0, got {safe_native}"

        # ── Step 10: Assert deployed service appears (Gnosis only) ────────────
        # The Trader template only configures Gnosis; Optimism has no service.
        deployed_chain_ids = {
            svc.chain_id
            for svc in scan_result.services
            if svc.state == OnChainState.DEPLOYED
        }
        for chain in SERVICE_CHAINS:
            assert chain.id in deployed_chain_ids, (
                f"Expected DEPLOYED service on chain {chain} (id={chain.id}), "
                f"found deployed chain ids: {deployed_chain_ids}"
            )

        # ── Step 11: Execute (with patched safe + subgraph discovery) ──────────
        LOGGER.info("Running FundRecoveryManager.execute() to %s...", dest)
        with (
            patch(f"{_RECOVERY_MODULE}.fetch_safes_for_owner", _mock_fetch_safes),
            patch(
                f"{_RECOVERY_MODULE}._fetch_services_from_subgraph",
                _mock_fetch_subgraph,
            ),
        ):
            result = FundRecoveryManager().execute(mnemonic, dest)

        # ── Step 12-14: Assert execute result ──────────────────────────────────
        assert (
            result.success is True
        ), f"execute() returned success=False; errors: {result.errors}"
        assert (
            result.errors == []
        ), f"execute() returned non-empty errors: {result.errors}"
        assert (
            result.total_funds_moved
        ), "execute() returned empty total_funds_moved — no funds were moved"

        # ── Step 15-18: Post-execute on-chain balance assertions ───────────────
        for chain in CHAINS_TO_TEST:
            ledger_api = get_default_ledger_api(chain)
            safe_addr = wallet.safes.get(chain)
            dust_threshold = DUST.get(chain, 0)

            # EOA native balance should be ≤ DUST
            eoa_balance = get_asset_balance(ledger_api, ZERO_ADDRESS, wallet.address)
            assert eoa_balance <= dust_threshold, (
                f"EOA {wallet.address} on {chain} not drained: "
                f"{eoa_balance} > dust={dust_threshold}"
            )

            if safe_addr:
                # Master Safe native balance should be 0
                safe_native = get_asset_balance(ledger_api, ZERO_ADDRESS, safe_addr)
                assert (
                    safe_native == 0
                ), f"Master safe {safe_addr} native on {chain} not drained: {safe_native}"

                # Master Safe OLAS balance should be 0
                olas_addr = OLAS.get(chain)
                if olas_addr:
                    safe_olas = get_asset_balance(ledger_api, olas_addr, safe_addr)
                    assert (
                        safe_olas == 0
                    ), f"Master safe {safe_addr} OLAS on {chain} not drained: {safe_olas}"

            # Destination balance must have increased (funds arrived)
            post_balance = get_asset_balance(ledger_api, ZERO_ADDRESS, dest)
            assert post_balance > pre_balances[chain], (
                f"Destination {dest} balance on {chain} did not increase: "
                f"pre={pre_balances[chain]}, post={post_balance}"
            )
            LOGGER.info(
                "Destination %s on %s: pre=%s, post=%s",
                dest,
                chain,
                pre_balances[chain],
                post_balance,
            )
