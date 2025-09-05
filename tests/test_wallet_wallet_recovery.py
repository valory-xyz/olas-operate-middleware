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

import uuid

import pytest

from operate.cli import OperateApp
from operate.ledger import get_default_ledger_api
from operate.operate_types import Chain
from operate.utils.gnosis import add_owner, remove_owner, swap_owner
from operate.wallet.master import MasterWalletManager
from operate.wallet.wallet_recovery_manager import (
    RECOVERY_BUNDLE_PREFIX,
    RECOVERY_OLD_OBJECTS_DIR,
    WalletRecoveryError,
)

from tests.conftest import OperateTestEnv, random_string, tenderly_add_balance
from tests.constants import LOGGER, OPERATE_TEST, TESTNET_RPCS


class TestWalletRecovery:
    """Tests for wallet.wallet_recoverey_manager.WalletRecoveryManager class."""

    @pytest.fixture(autouse=True)
    def _patch_rpcs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("operate.ledger.DEFAULT_RPCS", TESTNET_RPCS)
        monkeypatch.setattr("operate.ledger.DEFAULT_LEDGER_APIS", {})

    @staticmethod
    def _assert_recovered(
        old_wallet_manager: MasterWalletManager, wallet_manager: MasterWalletManager
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
        step_1_output = operate.wallet_recoverey_manager.initiate_recovery(
            new_password=new_password
        )

        assert step_1_output.get("id") is not None
        assert step_1_output.get("wallets") is not None
        assert len(step_1_output["wallets"]) == len(wallet_manager.json)

        for item in step_1_output["wallets"]:
            assert item.get("current_wallet") is not None
            assert item["current_wallet"].get("safes") is not None
            assert len(set(item["current_wallet"]["safes"])) >= 2
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()

        bundle_id = step_1_output["id"]

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
        operate.wallet_recoverey_manager.complete_recovery(
            password=new_password,
            bundle_id=bundle_id,
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
            operate.wallet_recoverey_manager.path
            / bundle_id
            / RECOVERY_OLD_OBJECTS_DIR
            / "wallets"
        )
        old_wallet_manager = MasterWalletManager(
            path=old_wallet_manager_path,
            logger=LOGGER,
            password=password,
        )

        TestWalletRecovery._assert_recovered(old_wallet_manager, wallet_manager)

        # Attempt to do a recovery with the same bundle will result in error
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )
        with pytest.raises(
            ValueError, match=f"Recovery bundle {bundle_id} has been executed already."
        ):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=bundle_id
            )

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
        step_1_output = operate.wallet_recoverey_manager.initiate_recovery(
            new_password=new_password
        )

        assert step_1_output.get("id") is not None
        assert step_1_output.get("wallets") is not None
        assert len(step_1_output["wallets"]) == len(wallet_manager.json)

        for item in step_1_output["wallets"]:
            assert item.get("current_wallet") is not None
            assert item["current_wallet"].get("safes") is not None
            assert len(set(item["current_wallet"]["safes"])) >= 2
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()

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
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password,
                bundle_id=bundle_id,
            )

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

        # Recovery step 2
        operate.wallet_recoverey_manager.complete_recovery(
            password=new_password,
            bundle_id=bundle_id,
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
            operate.wallet_recoverey_manager.path
            / bundle_id
            / RECOVERY_OLD_OBJECTS_DIR
            / "wallets"
        )
        old_wallet_manager = MasterWalletManager(
            path=old_wallet_manager_path,
            logger=LOGGER,
            password=password,
        )

        TestWalletRecovery._assert_recovered(old_wallet_manager, wallet_manager)

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
            operate.wallet_recoverey_manager.initiate_recovery(
                new_password=new_password
            )

        # Logout
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )

        with pytest.raises(
            ValueError, match="'new_password' must be a non-empty string."
        ):
            operate.wallet_recoverey_manager.initiate_recovery(new_password="")  # nosec

        with pytest.raises(
            ValueError, match="'new_password' must be a non-empty string."
        ):
            operate.wallet_recoverey_manager.initiate_recovery(new_password=None)  # type: ignore

        # Recovery step 1
        step_1_output = operate.wallet_recoverey_manager.initiate_recovery(
            new_password=new_password
        )

        bundle_id = step_1_output["id"]

        # Log in
        operate.password = password

        with pytest.raises(
            WalletRecoveryError,
            match="Wallet recovery cannot be executed while logged in.",
        ):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=bundle_id
            )

        # Logout
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )

        random_bundle_id = f"{RECOVERY_BUNDLE_PREFIX}{str(uuid.uuid4())}"
        with pytest.raises(
            KeyError, match=f"Recovery bundle {random_bundle_id} does not exist."
        ):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=random_bundle_id
            )

        with pytest.raises(ValueError, match="'bundle_id' must be a non-empty string."):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=""
            )

        with pytest.raises(ValueError, match="'bundle_id' must be a non-empty string."):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=None  # type: ignore
            )

        random_password = random_string(16)
        with pytest.raises(ValueError, match="Password is not valid."):
            operate.wallet_recoverey_manager.complete_recovery(
                password=random_password, bundle_id=bundle_id
            )

        with pytest.raises(WalletRecoveryError, match="^Incorrect owners.*"):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password,
                bundle_id=bundle_id,
            )

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
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password,
                bundle_id=bundle_id,
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
                operate.wallet_recoverey_manager.complete_recovery(
                    password=new_password,
                    bundle_id=bundle_id,
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
        operate.wallet_recoverey_manager.complete_recovery(
            password=new_password,
            bundle_id=bundle_id,
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
            operate.wallet_recoverey_manager.path
            / bundle_id
            / RECOVERY_OLD_OBJECTS_DIR
            / "wallets"
        )
        old_wallet_manager = MasterWalletManager(
            path=old_wallet_manager_path,
            logger=LOGGER,
            password=password,
        )

        TestWalletRecovery._assert_recovered(old_wallet_manager, wallet_manager)

        # Attempt to do a recovery with the same bundle will result in error
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )
        with pytest.raises(
            ValueError, match=f"Recovery bundle {bundle_id} has been executed already."
        ):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=bundle_id
            )
