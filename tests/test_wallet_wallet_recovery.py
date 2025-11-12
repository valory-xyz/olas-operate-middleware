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

"""Tests for wallet.wallet_recovery_manager module."""


# pylint: disable=too-many-locals

import typing as t

import pytest

from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger import get_default_ledger_api
from operate.operate_types import Chain, LedgerType
from operate.utils.gnosis import add_owner, remove_owner, swap_owner
from operate.wallet.master import MasterWalletManager
from operate.wallet.wallet_recovery_manager import (
    RECOVERY_OLD_OBJECTS_DIR,
    WalletRecoveryError,
)

from tests.conftest import OnTestnet, OperateTestEnv, tenderly_add_balance
from tests.constants import OPERATE_TEST


class TestWalletRecovery(OnTestnet):
    """Tests for wallet.wallet_recoverey_manager.WalletRecoveryManager class."""

    @staticmethod
    def _assert_recovered(
        old_wallet_manager: MasterWalletManager,
        wallet_manager: MasterWalletManager,
        password: str,
        mnemonics: t.Dict[LedgerType, t.List[str]],
    ) -> None:
        old_ledger_types = {item.ledger_type for item in old_wallet_manager}
        ledger_types = {item.ledger_type for item in wallet_manager}

        assert old_ledger_types == ledger_types

        for old_wallet in old_wallet_manager:
            wallet = next(
                (w for w in wallet_manager if w.ledger_type == old_wallet.ledger_type)
            )
            assert old_wallet.safes == wallet.safes
            assert old_wallet.safe_chains == wallet.safe_chains
            assert wallet.decrypt_mnemonic(password) == mnemonics[wallet.ledger_type]

    @staticmethod
    def _assert_recovery_requirements(
        wallet_manager: MasterWalletManager,
        backup_owner: str,
        recovery_requirements: t.Dict[str, t.Any],
        is_refill_required: bool = False,
    ) -> None:
        balances = recovery_requirements["balances"]
        total_requirements = recovery_requirements["total_requirements"]
        refill_requirements = recovery_requirements["refill_requirements"]

        assert recovery_requirements["is_refill_required"] == is_refill_required

        for wallet in wallet_manager:
            for chain in wallet.safes.keys():
                chain_str = chain.value
                assert chain_str in balances
                assert chain_str in total_requirements
                assert chain_str in refill_requirements
                assert backup_owner in balances[chain_str]
                assert backup_owner in total_requirements[chain_str]
                assert backup_owner in refill_requirements[chain_str]
                assert ZERO_ADDRESS in balances[chain_str][backup_owner]
                assert ZERO_ADDRESS in total_requirements[chain_str][backup_owner]
                assert ZERO_ADDRESS in refill_requirements[chain_str][backup_owner]

                balance = balances[chain_str][backup_owner][ZERO_ADDRESS]
                requirement = total_requirements[chain_str][backup_owner][ZERO_ADDRESS]
                shortfall = refill_requirements[chain_str][backup_owner][ZERO_ADDRESS]
                assert shortfall == max(requirement - balance, 0)

                if is_refill_required:
                    assert shortfall > 0
                else:
                    assert shortfall == 0

    def test_normal_flow(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """test_normal_flow"""
        operate = test_env.operate
        wallet_manager = test_env.wallet_manager
        keys_manager = test_env.keys_manager
        backup_owner = test_env.backup_owner
        password = test_env.password

        # Recovery step 1
        new_password = password[::-1]

        assert operate.wallet_recovery_manager.data.last_initiated_bundle_id is None

        step_1_output = operate.wallet_recovery_manager.initiate_recovery(
            new_password=new_password
        )

        assert operate.wallet_recovery_manager.data.last_initiated_bundle_id is not None
        assert (
            step_1_output.get("id")
            == operate.wallet_recovery_manager.data.last_initiated_bundle_id
        )
        assert step_1_output.get("wallets") is not None
        assert len(step_1_output["wallets"]) == len(wallet_manager.json)
        new_mnemonics: t.Dict[LedgerType, t.List[str]] = {}

        for item in step_1_output["wallets"]:
            assert item.get("current_wallet") is not None
            assert item["current_wallet"].get("safes") is not None
            assert len(set(item["current_wallet"]["safes"])) >= 2
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()
            current_ledger_type = LedgerType(item["current_wallet"].get("ledger_type"))
            new_ledger_type = LedgerType(item["new_wallet"].get("ledger_type"))
            assert current_ledger_type == new_ledger_type
            new_mnemonics[new_ledger_type] = item.get("new_mnemonic")

        bundle_id = step_1_output["id"]

        recovery_requirements = operate.funding_manager.recovery_requirements()
        TestWalletRecovery._assert_recovery_requirements(
            wallet_manager=wallet_manager,
            backup_owner=backup_owner,
            recovery_requirements=recovery_requirements,
            is_refill_required=False,
        )

        import pprint

        pprint.pprint(recovery_requirements)

        # Swap safe owners using backup wallet
        crypto = keys_manager.get_crypto_instance(backup_owner)
        for item in step_1_output["wallets"]:
            chains_str = list(item["current_wallet"]["safes"].keys())
            for chain_str in chains_str:
                chain = Chain(chain_str)
                ledger_api = get_default_ledger_api(chain)
                swap_owner(
                    ledger_api=ledger_api,
                    crypto=crypto,
                    safe=item["current_wallet"]["safes"][chain_str],
                    old_owner=item["current_wallet"]["address"],
                    new_owner=item["new_wallet"]["address"],
                )

        # Recovery step 2
        operate.wallet_recovery_manager.complete_recovery()

        # Test that recovery was successful
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )
        assert operate.user_account is not None
        assert operate.user_account.is_valid(new_password)
        operate.password = new_password
        wallet_manager = operate.wallet_manager
        old_wallet_manager_path = (
            operate.wallet_recovery_manager.path
            / bundle_id
            / RECOVERY_OLD_OBJECTS_DIR
            / "wallets"
        )
        old_wallet_manager = MasterWalletManager(
            path=old_wallet_manager_path,
            password=password,
        )

        TestWalletRecovery._assert_recovered(
            old_wallet_manager, wallet_manager, new_password, new_mnemonics
        )

        # Attempt to do a recovery with the same bundle will result in error
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )
        with pytest.raises(WalletRecoveryError, match="No initiated bundle found."):
            operate.wallet_recovery_manager.complete_recovery()

        assert operate.wallet_recovery_manager.data.last_initiated_bundle_id is None

    def test_resumed_flow(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """test_resumed_flow"""
        operate = test_env.operate
        wallet_manager = test_env.wallet_manager
        keys_manager = test_env.keys_manager
        backup_owner = test_env.backup_owner
        password = test_env.password

        # Recovery step 1
        new_password = password[::-1]

        assert operate.wallet_recovery_manager.data.last_initiated_bundle_id is None

        step_1_output = operate.wallet_recovery_manager.initiate_recovery(
            new_password=new_password
        )

        assert operate.wallet_recovery_manager.data.last_initiated_bundle_id is not None
        assert (
            step_1_output.get("id")
            == operate.wallet_recovery_manager.data.last_initiated_bundle_id
        )
        assert step_1_output.get("wallets") is not None
        assert len(step_1_output["wallets"]) == len(wallet_manager.json)
        new_mnemonics: t.Dict[LedgerType, t.List[str]] = {}

        for item in step_1_output["wallets"]:
            assert item.get("current_wallet") is not None
            assert item["current_wallet"].get("safes") is not None
            assert len(set(item["current_wallet"]["safes"])) >= 2
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()
            current_ledger_type = LedgerType(item["current_wallet"].get("ledger_type"))
            new_ledger_type = LedgerType(item["new_wallet"].get("ledger_type"))
            assert current_ledger_type == new_ledger_type
            new_mnemonics[new_ledger_type] = item.get("new_mnemonic")

        bundle_id = step_1_output["id"]

        # Incompletely swap safe owners using backup wallet
        crypto = keys_manager.get_crypto_instance(backup_owner)
        for item in step_1_output["wallets"]:
            chains_str = list(item["current_wallet"]["safes"].keys())
            mid = len(chains_str) // 2
            chains_str_1 = chains_str[:mid]
            for chain_str in chains_str_1:
                chain = Chain(chain_str)
                ledger_api = get_default_ledger_api(chain)
                swap_owner(
                    ledger_api=ledger_api,
                    crypto=crypto,
                    safe=item["current_wallet"]["safes"][chain_str],
                    old_owner=item["current_wallet"]["address"],
                    new_owner=item["new_wallet"]["address"],
                )

        # Recovery step 2 - fail
        with pytest.raises(WalletRecoveryError, match="^Incorrect owners.*"):
            operate.wallet_recovery_manager.complete_recovery()

        # Resume swapping safe owners using backup wallet
        crypto = keys_manager.get_crypto_instance(backup_owner)
        for item in step_1_output["wallets"]:
            chains_str = list(item["current_wallet"]["safes"].keys())
            mid = len(chains_str) // 2
            chains_str_2 = chains_str[mid:]
            for chain_str in chains_str_2:
                chain = Chain(chain_str)
                ledger_api = get_default_ledger_api(chain)
                swap_owner(
                    ledger_api=ledger_api,
                    crypto=crypto,
                    safe=item["current_wallet"]["safes"][chain_str],
                    old_owner=item["current_wallet"]["address"],
                    new_owner=item["new_wallet"]["address"],
                )

        # Recovery step 1 - resume incomplete bundle
        step_1_output_resumed = operate.wallet_recovery_manager.initiate_recovery(
            new_password=new_password
        )
        assert step_1_output_resumed["id"] == bundle_id

        # Recovery step 2
        operate.wallet_recovery_manager.complete_recovery()

        # Test that recovery was successful
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )
        assert operate.user_account is not None
        assert operate.user_account.is_valid(new_password)
        operate.password = new_password
        wallet_manager = operate.wallet_manager
        old_wallet_manager_path = (
            operate.wallet_recovery_manager.path
            / bundle_id
            / RECOVERY_OLD_OBJECTS_DIR
            / "wallets"
        )
        old_wallet_manager = MasterWalletManager(
            path=old_wallet_manager_path,
            password=password,
        )

        TestWalletRecovery._assert_recovered(
            old_wallet_manager, wallet_manager, new_password, new_mnemonics
        )

        # New recovery should have a different bundle_id
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )
        assert operate.wallet_recovery_manager.data.last_initiated_bundle_id is None

        step_1_output_resumed = operate.wallet_recovery_manager.initiate_recovery(
            new_password=new_password
        )
        assert operate.wallet_recovery_manager.data.last_initiated_bundle_id is not None
        assert (
            step_1_output_resumed["id"]
            == operate.wallet_recovery_manager.data.last_initiated_bundle_id
        )
        assert step_1_output_resumed["id"] != bundle_id

    @pytest.mark.parametrize("raise_if_inconsistent_owners", [True, False])
    def test_exceptions(
        self,
        test_env: OperateTestEnv,
        raise_if_inconsistent_owners: bool,
    ) -> None:
        """test_exceptions"""
        operate = test_env.operate
        wallet_manager = test_env.wallet_manager
        keys_manager = test_env.keys_manager
        backup_owner = test_env.backup_owner
        backup_owner2 = test_env.backup_owner2
        password = test_env.password

        # Log in
        operate.password = password

        new_password = password[::-1]
        with pytest.raises(
            WalletRecoveryError,
            match="Wallet recovery cannot be executed while logged in.",
        ):
            operate.wallet_recovery_manager.initiate_recovery(new_password=new_password)

        # Logout
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )

        with pytest.raises(WalletRecoveryError, match="No initiated bundle found."):
            operate.wallet_recovery_manager.complete_recovery()

        with pytest.raises(
            ValueError, match="'new_password' must be a non-empty string."
        ):
            operate.wallet_recovery_manager.initiate_recovery(new_password="")  # nosec

        with pytest.raises(
            ValueError, match="'new_password' must be a non-empty string."
        ):
            operate.wallet_recovery_manager.initiate_recovery(new_password=None)  # type: ignore

        # Remove backup owner for half of the chains
        for wallet in wallet_manager:
            wallet.password = password
            chains = list(wallet.safes.keys())
            mid = len(chains) // 2
            chains_1 = chains[:mid]
            for chain in chains_1:
                ledger_api = get_default_ledger_api(chain)
                remove_owner(
                    ledger_api=ledger_api,
                    crypto=wallet.crypto,
                    safe=wallet.safes[chain],
                    owner=backup_owner,
                    threshold=1,
                )

        with pytest.raises(WalletRecoveryError, match="has less than 2 owners\\.$"):
            operate.wallet_recovery_manager.initiate_recovery(new_password=new_password)

        # Restore backup owner for half of the chains
        for wallet in wallet_manager:
            wallet.password = password
            chains = list(wallet.safes.keys())
            mid = len(chains) // 2
            chains_1 = chains[:mid]
            for chain in chains_1:
                ledger_api = get_default_ledger_api(chain)
                add_owner(
                    ledger_api=ledger_api,
                    crypto=wallet.crypto,
                    safe=wallet.safes[chain],
                    owner=backup_owner,
                )

        # Recovery step 1
        step_1_output = operate.wallet_recovery_manager.initiate_recovery(
            new_password=new_password
        )

        assert step_1_output.get("id") is not None
        assert step_1_output.get("wallets") is not None
        assert len(step_1_output["wallets"]) == len(wallet_manager.json)
        new_mnemonics: t.Dict[LedgerType, t.List[str]] = {}

        for item in step_1_output["wallets"]:
            assert item.get("current_wallet") is not None
            assert item["current_wallet"].get("safes") is not None
            assert len(set(item["current_wallet"]["safes"])) >= 2
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()
            current_ledger_type = LedgerType(item["current_wallet"].get("ledger_type"))
            new_ledger_type = LedgerType(item["new_wallet"].get("ledger_type"))
            assert current_ledger_type == new_ledger_type
            new_mnemonics[new_ledger_type] = item.get("new_mnemonic")

        bundle_id = step_1_output["id"]

        # Log in
        operate.password = password

        with pytest.raises(
            WalletRecoveryError,
            match="Wallet recovery cannot be executed while logged in.",
        ):
            operate.wallet_recovery_manager.complete_recovery()

        # Logout
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )

        with pytest.raises(WalletRecoveryError, match="^Incorrect owners.*"):
            operate.wallet_recovery_manager.complete_recovery()

        # Add safe owners using backup wallet
        crypto = keys_manager.get_crypto_instance(backup_owner)
        for item in step_1_output["wallets"]:
            chains_str = list(item["current_wallet"]["safes"].keys())
            for chain_str in chains_str:
                chain = Chain(chain_str)
                ledger_api = get_default_ledger_api(chain)
                add_owner(
                    ledger_api=ledger_api,
                    crypto=crypto,
                    safe=item["current_wallet"]["safes"][chain_str],
                    owner=item["new_wallet"]["address"],
                )

        with pytest.raises(WalletRecoveryError, match="^Inconsistent owners.*"):
            operate.wallet_recovery_manager.complete_recovery(
                raise_if_inconsistent_owners=True,
            )

        if raise_if_inconsistent_owners:
            # Remove old MasterEOA
            crypto = keys_manager.get_crypto_instance(backup_owner)
            for item in step_1_output["wallets"]:
                chains_str = list(item["current_wallet"]["safes"].keys())
                for chain_str in chains_str:
                    chain = Chain(chain_str)
                    ledger_api = get_default_ledger_api(chain)
                    remove_owner(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=item["current_wallet"]["safes"][chain_str],
                        owner=item["current_wallet"]["address"],
                        threshold=1,
                    )

            # Use a different backup owner for half of the chains
            crypto = keys_manager.get_crypto_instance(backup_owner)
            for item in step_1_output["wallets"]:
                chains_str = list(item["current_wallet"]["safes"].keys())
                mid = len(chains_str) // 2
                chains_str_1 = chains_str[:mid]
                for chain_str in chains_str_1:
                    chain = Chain(chain_str)
                    ledger_api = get_default_ledger_api(chain)
                    swap_owner(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=item["current_wallet"]["safes"][chain_str],
                        old_owner=backup_owner,
                        new_owner=backup_owner2,
                    )

            with pytest.raises(
                WalletRecoveryError,
                match="^Inconsistent owners. Backup owners differ across Safes on chains.*",
            ):
                operate.wallet_recovery_manager.complete_recovery(
                    raise_if_inconsistent_owners=True,
                )

            # Revert original backup owner
            crypto = keys_manager.get_crypto_instance(backup_owner2)
            for item in step_1_output["wallets"]:
                chains_str = list(item["current_wallet"]["safes"].keys())
                mid = len(chains_str) // 2
                chains_str_1 = chains_str[:mid]
                for chain_str in chains_str_1:
                    chain = Chain(chain_str)
                    ledger_api = get_default_ledger_api(chain)
                    tenderly_add_balance(chain, backup_owner2)
                    swap_owner(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=item["current_wallet"]["safes"][chain_str],
                        old_owner=backup_owner2,
                        new_owner=backup_owner,
                    )

        # Recovery step 2
        operate.wallet_recovery_manager.complete_recovery(
            raise_if_inconsistent_owners=raise_if_inconsistent_owners,
        )

        # Test that recovery was successful
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )
        assert operate.user_account is not None
        assert operate.user_account.is_valid(new_password)
        operate.password = new_password
        wallet_manager = operate.wallet_manager
        old_wallet_manager_path = (
            operate.wallet_recovery_manager.path
            / bundle_id
            / RECOVERY_OLD_OBJECTS_DIR
            / "wallets"
        )
        old_wallet_manager = MasterWalletManager(
            path=old_wallet_manager_path,
            password=password,
        )

        TestWalletRecovery._assert_recovered(
            old_wallet_manager, wallet_manager, new_password, new_mnemonics
        )

        # Attempt to do a recovery without an initiated bundle will result in error
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )

        with pytest.raises(WalletRecoveryError, match="No initiated bundle found."):
            operate.wallet_recovery_manager.complete_recovery()
