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
from operate.ledger.profiles import DUST, ERC20_TOKENS_BY_CHAIN_ID, OLAS, STAKING
from operate.operate_types import Chain, LedgerType, OnChainState
from operate.services.fund_recovery_manager import FundRecoveryManager
from operate.services.protocol import StakingManager
from operate.utils.gnosis import get_asset_balance

from tests.conftest import (
    OnTestnet,
    OperateTestEnv,
    tenderly_add_balance,
    tenderly_increase_time,
)
from tests.constants import LOGGER

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

        Note: One external call is patched because Tenderly virtual forks are
        not indexed by public APIs:
        - _fetch_services_from_subgraph: The subgraph doesn't index fork services.

        This test:
        1. Deploys the service on-chain.
        2. Funds agent addresses, service safe, and agent safe.
        3. Runs scan() (patched) and asserts discovered balances and service state.
        4. Records pre-execute balances: EOA, master safe, agent safe, destination
           for both native and all tracked ERC-20 tokens.
        5. Runs execute() (patched) and asserts success + funds moved to destination.
        6. Asserts EOA, master safe, and agent safe are drained on all chains.
        7. Native: destination increase ≈ EOA + master safe + agent safe totals
           (within a 5 % gas tolerance).
        8. ERC-20: destination increase == total pre-held exactly (no gas in tokens).
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

        # ── Step 6: Record pre-execute balances ───────────────────────────────
        # Capture native + ERC-20 balances for destination, EOA, master safe,
        # and agent safe(s) so we can verify conservation after execute().
        #
        # Native:  destination increase ≈ total held  (5 % gas tolerance)
        # ERC-20:  destination increase == total held  (exact — no gas in tokens)
        dest = test_env.backup_owner

        # Agent safe addresses per chain (chain_data.multisig from deployed service)
        # Only service chains (Gnosis) have an agent safe; assert it is set.
        agent_safes: t.Dict[Chain, str] = {}
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            multisig = chain_config.chain_data.multisig
            assert multisig is not None, f"Agent safe (multisig) not set for {chain}"
            agent_safes[chain] = multisig

        # Master-safe addresses — every tested chain must have one.
        for chain in SERVICE_CHAINS:
            assert chain in wallet.safes, f"No master safe for {chain}"

        # Staked/bonded OLAS per service chain: the recovery flow unstakes and
        # unbonds OLAS before draining, so these amounts flow to the destination
        # even though they are not held by the EOA/safe/agent-safe at pre-record
        # time.  We read min_staking_deposit from the on-chain staking contract;
        # the service bonds (security_deposit + agent_bond) = 2 * min_staking_deposit.
        staked_olas: t.Dict[Chain, int] = {}
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            staking_program_id = chain_config.chain_data.user_params.staking_program_id
            staking_contract = STAKING[chain].get(staking_program_id)
            assert (
                staking_contract is not None
            ), f"Staking contract not found for {chain} program id {staking_program_id}"
            staking_params = StakingManager(chain).get_staking_params(
                staking_contract=staking_contract,
            )
            min_deposit = staking_params["min_staking_deposit"]
            # Total bonded: security_deposit plus agent_bond, each equal to min_staking_deposit
            staked_olas[chain] = 2 * min_deposit
            LOGGER.info(
                "Staked OLAS on %s: min_deposit=%s bonded=%s",
                chain,
                min_deposit,
                staked_olas[chain],
            )

        # Keyed as pre[chain][token_address][wallet_label]
        # wallet_label is one of: "dest", "eoa", "master_safe", "agent_safe"
        pre: t.Dict[Chain, t.Dict[str, t.Dict[str, int]]] = {}

        for chain in SERVICE_CHAINS:
            ledger_api = get_default_ledger_api(chain)
            safe_addr = wallet.safes[chain]
            agent_safe_addr = agent_safes[chain]

            # All assets to track: native + ERC-20 tokens known on this chain
            all_tokens = [ZERO_ADDRESS] + ERC20_TOKENS_BY_CHAIN_ID[chain.id]

            pre[chain] = {}
            for token in all_tokens:
                pre[chain][token] = {
                    "dest": get_asset_balance(ledger_api, token, dest),
                    "eoa": get_asset_balance(ledger_api, token, wallet.address),
                    "master_safe": get_asset_balance(ledger_api, token, safe_addr),
                    "agent_safe": get_asset_balance(ledger_api, token, agent_safe_addr),
                }

            LOGGER.info(
                "Pre-execute on %s: dest=%s eoa=%s master_safe=%s agent_safe=%s",
                chain,
                pre[chain][ZERO_ADDRESS]["dest"],
                pre[chain][ZERO_ADDRESS]["eoa"],
                pre[chain][ZERO_ADDRESS]["master_safe"],
                pre[chain][ZERO_ADDRESS]["agent_safe"],
            )
            for token in ERC20_TOKENS_BY_CHAIN_ID[chain.id]:
                if any(
                    pre[chain][token][k] > 0
                    for k in ("eoa", "master_safe", "agent_safe")
                ):
                    LOGGER.info(
                        "Pre-execute ERC-20 %s on %s: dest=%s eoa=%s master_safe=%s agent_safe=%s",
                        token,
                        chain,
                        pre[chain][token]["dest"],
                        pre[chain][token]["eoa"],
                        pre[chain][token]["master_safe"],
                        pre[chain][token]["agent_safe"],
                    )

        # ── Step 7: Scan (with patched subgraph discovery) ────────────────────
        LOGGER.info("Running FundRecoveryManager.scan()...")
        with (
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
        for chain in SERVICE_CHAINS:
            chain_id_str = str(chain.id)
            assert (
                chain_id_str in scan_result.balances
            ), f"Chain {chain} (id={chain_id_str}) not found in scan balances"
            chain_balances = scan_result.balances[chain_id_str]

            # EOA balance must appear
            assert (
                wallet.address in chain_balances
            ), f"EOA {wallet.address} not in balances for chain {chain}"
            eoa_native = int(chain_balances[wallet.address][ZERO_ADDRESS])
            assert (
                eoa_native > 0
            ), f"EOA native balance on {chain} should be > 0, got {eoa_native}"

            # Master Safe balance must appear
            safe_addr = wallet.safes[chain]
            assert (
                safe_addr in chain_balances
            ), f"Master safe {safe_addr} not in balances for chain {chain}"
            safe_native = int(chain_balances[safe_addr][ZERO_ADDRESS])
            assert (
                safe_native > 0
            ), f"Master safe native balance on {chain} should be > 0, got {safe_native}"

            # ERC-20 balances: scan result must match pre-recorded balances exactly.
            # Agent safe exists only on service chains (Gnosis); assert it appears
            # in chain_balances when it holds non-zero ERC-20 tokens.
            agent_safe_addr = agent_safes[chain]
            for token in ERC20_TOKENS_BY_CHAIN_ID[chain.id]:
                pre_eoa = pre[chain][token]["eoa"]
                pre_master = pre[chain][token]["master_safe"]
                pre_agent = pre[chain][token]["agent_safe"]

                if pre_eoa > 0:
                    assert (
                        wallet.address in chain_balances
                    ), f"EOA {wallet.address} not in scan balances for chain {chain}"
                    assert int(chain_balances[wallet.address][token]) == pre_eoa, (
                        f"Scan EOA ERC-20 {token} on {chain}: "
                        f"got {int(chain_balances[wallet.address][token])}, "
                        f"expected {pre_eoa}"
                    )

                if pre_master > 0:
                    assert (
                        safe_addr in chain_balances
                    ), f"Master safe {safe_addr} not in scan balances for chain {chain}"
                    assert int(chain_balances[safe_addr][token]) == pre_master, (
                        f"Scan master safe ERC-20 {token} on {chain}: "
                        f"got {int(chain_balances[safe_addr][token])}, "
                        f"expected {pre_master}"
                    )

                if pre_agent > 0:
                    assert agent_safe_addr in chain_balances, (
                        f"Agent safe {agent_safe_addr} not in scan balances "
                        f"for chain {chain}"
                    )
                    assert int(chain_balances[agent_safe_addr][token]) == pre_agent, (
                        f"Scan agent safe ERC-20 {token} on {chain}: "
                        f"got {int(chain_balances[agent_safe_addr][token])}, "
                        f"expected {pre_agent}"
                    )

        # ── Step 9b: Assert staked OLAS appears in scan balances ─────────────
        # For each service chain, the staking contract address must appear as a
        # wallet key in chain_balances, with the OLAS token entry equal to
        # 2 * min_staking_deposit (the amount locked for security + agent bond).
        for chain_str, chain_config in service.chain_configs.items():
            chain = Chain(chain_str)
            chain_id_str = str(chain.id)
            chain_balances = scan_result.balances.get(chain_id_str, {})

            staking_program_id = chain_config.chain_data.user_params.staking_program_id
            staking_contract = STAKING[chain].get(staking_program_id)
            assert (
                staking_contract is not None
            ), f"Staking contract not found for {chain} program id {staking_program_id}"
            staking_contract_cs = staking_contract  # already checksummed in profiles

            olas_address = OLAS.get(chain)
            assert olas_address is not None, f"No OLAS address for chain {chain}"

            assert staking_contract_cs in chain_balances, (
                f"Staking contract {staking_contract_cs} not found in scan balances "
                f"for chain {chain}. Balances keys: {list(chain_balances.keys())}"
            )
            reported_staked = int(
                chain_balances[staking_contract_cs].get(olas_address, 0)
            )
            expected_staked = staked_olas[chain]
            assert reported_staked == expected_staked, (
                f"Scan staked OLAS on {chain}: got {reported_staked}, "
                f"expected {expected_staked} (2 * min_staking_deposit)"
            )
            LOGGER.info(
                "Scan correctly reported %s staked OLAS in contract %s on %s",
                reported_staked,
                staking_contract_cs,
                chain,
            )

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

        # ── Step 11: Execute (with patched subgraph discovery) ────────────────
        LOGGER.info("Running FundRecoveryManager.execute() to %s...", dest)
        with (
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
        # Native: allow up to 5 % of total pre-execute holdings as gas tolerance.
        # ERC-20: exact conservation — no gas is paid in tokens.
        _GAS_TOLERANCE_BPS = 500  # 5 % in basis points

        for chain in SERVICE_CHAINS:
            ledger_api = get_default_ledger_api(chain)
            safe_addr = wallet.safes[chain]
            agent_safe_addr = agent_safes[chain]
            dust_threshold = DUST[chain]
            all_tokens = [ZERO_ADDRESS] + ERC20_TOKENS_BY_CHAIN_ID[chain.id]

            for token in all_tokens:
                is_native = token == ZERO_ADDRESS

                # ── Source wallets must be drained ────────────────────────────
                eoa_post = get_asset_balance(ledger_api, token, wallet.address)
                if is_native:
                    assert eoa_post <= dust_threshold, (
                        f"EOA {wallet.address} native on {chain} not drained: "
                        f"{eoa_post} > dust={dust_threshold}"
                    )
                else:
                    assert (
                        eoa_post == 0
                    ), f"EOA {wallet.address} ERC-20 {token} on {chain} not drained: {eoa_post}"

                master_safe_post = get_asset_balance(ledger_api, token, safe_addr)
                assert master_safe_post == 0, (
                    f"Master safe {safe_addr} token={token} on {chain} not drained: "
                    f"{master_safe_post}"
                )

                agent_safe_post = get_asset_balance(ledger_api, token, agent_safe_addr)
                assert agent_safe_post == 0, (
                    f"Agent safe {agent_safe_addr} token={token} on {chain} not drained: "
                    f"{agent_safe_post}"
                )

                # ── Conservation check ────────────────────────────────────────
                total_pre_held = (
                    pre[chain][token]["eoa"]
                    + pre[chain][token]["master_safe"]
                    + pre[chain][token]["agent_safe"]
                )
                # For OLAS on service chains, add OLAS bonded/staked in the
                # staking contract — the recovery flow unstakes + unbonds these
                # before draining, so they also flow to the destination.
                if token == OLAS.get(chain) and staked_olas.get(chain, 0) > 0:
                    total_pre_held += staked_olas[chain]

                if total_pre_held == 0:
                    # Nothing to recover for this token on this chain
                    continue

                dest_post = get_asset_balance(ledger_api, token, dest)
                actual_increase = dest_post - pre[chain][token]["dest"]

                if is_native:
                    # Gas is paid in native — allow tolerance
                    gas_allowance = total_pre_held * _GAS_TOLERANCE_BPS // 10_000
                    min_expected = total_pre_held - gas_allowance
                    assert actual_increase >= min_expected, (
                        f"Destination {dest} native on {chain}: increase "
                        f"{actual_increase} < min_expected {min_expected} "
                        f"(total_pre_held={total_pre_held}, gas_allowance={gas_allowance})"
                    )
                    LOGGER.info(
                        "Destination %s native on %s: pre=%s post=%s "
                        "increase=%s total_pre_held=%s gas_allowance=%s",
                        dest,
                        chain,
                        pre[chain][token]["dest"],
                        dest_post,
                        actual_increase,
                        total_pre_held,
                        gas_allowance,
                    )
                else:
                    # ERC-20 transfers cost no gas in tokens.
                    # total_pre_held already includes staked OLAS, so we expect
                    # exact conservation.
                    assert actual_increase == total_pre_held, (
                        f"Destination {dest} ERC-20 {token} on {chain}: increase "
                        f"{actual_increase} != total_pre_held {total_pre_held}"
                    )
                    LOGGER.info(
                        "Destination %s ERC-20 %s on %s: pre=%s post=%s increase=%s "
                        "total_pre_held=%s",
                        dest,
                        token,
                        chain,
                        pre[chain][token]["dest"],
                        dest_post,
                        actual_increase,
                        total_pre_held,
                    )
