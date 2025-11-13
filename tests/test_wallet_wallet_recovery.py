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

from operate.ledger.profiles import DEFAULT_RECOVERY_TOPUPS
import pytest
from deepdiff import DeepDiff

from operate.cli import OperateApp
from operate.constants import MSG_INVALID_PASSWORD, ZERO_ADDRESS
from operate.ledger import get_default_ledger_api
from operate.operate_types import Chain, ChainAmounts, LedgerType
from operate.utils.gnosis import add_owner, get_owners, remove_owner, swap_owner
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
        prepare_json: t.Dict,
        backup_owner: str,
        recovery_requirements: t.Dict[str, t.Any],
        is_refill_required: bool = False,
    ) -> None:
        balances = recovery_requirements["balances"]
        total_requirements = recovery_requirements["total_requirements"]
        refill_requirements = recovery_requirements["refill_requirements"]

        expected_balances = {}
        expected_requirements = ChainAmounts()

        for wallet in wallet_manager:
            new_wallet_json = next(
                (w for w in prepare_json["wallets"] if w["new_wallet"]["ledger_type"] == wallet.ledger_type.value)
            )["new_wallet"]
            for chain, safe in wallet.safes.items():
                chain_str = chain.value
                expected_balances.setdefault(chain_str, {}).setdefault(backup_owner, {}).setdefault(ZERO_ADDRESS, 0)
                expected_balances[chain_str][backup_owner][ZERO_ADDRESS] = recovery_requirements["balances"][chain_str][backup_owner][ZERO_ADDRESS]
                expected_requirements.setdefault(chain_str, {}).setdefault(backup_owner, {}).setdefault(ZERO_ADDRESS, 0)                

                ledger_api = get_default_ledger_api(chain)
                owners = get_owners(ledger_api=ledger_api, safe=safe)
                if new_wallet_json["address"] not in owners:
                    expected_requirements[chain_str][backup_owner][ZERO_ADDRESS] += DEFAULT_RECOVERY_TOPUPS[chain][ZERO_ADDRESS]

                balance = balances[chain_str][backup_owner][ZERO_ADDRESS]
                requirement = total_requirements[chain_str][backup_owner][ZERO_ADDRESS]
                shortfall = refill_requirements[chain_str][backup_owner][ZERO_ADDRESS]
                assert shortfall == max(requirement - balance, 0)

                if is_refill_required:
                    assert shortfall > 0
                else:
                    assert shortfall == 0

        expected_refill_requirements = ChainAmounts.shortfalls(
            requirements=expected_requirements, balances=expected_balances
        )

        expected_recovery_requirements = {
            "balances": dict(expected_balances),
            "total_requirements": dict(expected_requirements),
            "refill_requirements": dict(expected_refill_requirements),
            "is_refill_required": is_refill_required,
        }

        assert not DeepDiff(recovery_requirements, expected_recovery_requirements)

    @staticmethod
    def _assert_different_prepare_bundles(
        prepare_json_1: t.Dict,
        prepare_json_2: t.Dict,
    ) -> None:
        assert prepare_json_1.get("id") != prepare_json_2.get("id")
        wallets_1 = prepare_json_1.get("wallets", [])
        wallets_2 = prepare_json_2.get("wallets", [])
        assert len(wallets_1) == len(wallets_2)
        assert len(wallets_1) > 0

        for item_1, item_2 in zip(wallets_1, wallets_2):
            assert not DeepDiff(
                item_1.get("current_wallet"), item_2.get("current_wallet")
            )
            assert (
                item_1.get("new_wallet")["address"]
                != item_2.get("new_wallet")["address"]
            )
            assert item_1.get("new_mnemonic") != item_2.get("new_mnemonic")

    def test_normal_flow(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """test_normal_flow"""
        operate = test_env.operate
        operate_client = test_env.operate_client
        wallet_manager = test_env.wallet_manager
        keys_manager = test_env.keys_manager
        backup_owner = test_env.backup_owner
        password = test_env.password

        # Prepare recovery
        new_password = password[::-1]

        assert operate.wallet_recovery_manager.data.last_prepared_bundle_id is None

        prepare_response = operate_client.post(
            url="/api/wallet/recovery/prepare",
            json={"new_password": new_password},
        )
        assert prepare_response.status_code == 200
        prepare_json = prepare_response.json()

        assert operate.wallet_recovery_manager.data.last_prepared_bundle_id is not None
        assert (
            prepare_json.get("id")
            == operate.wallet_recovery_manager.data.last_prepared_bundle_id
        )
        assert prepare_json.get("wallets") is not None
        assert len(prepare_json["wallets"]) == len(wallet_manager.json)
        new_mnemonics: t.Dict[LedgerType, t.List[str]] = {}

        for item in prepare_json["wallets"]:
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

        bundle_id = prepare_json["id"]

        # Check recovery funding requirements
        recovery_requirements_response = operate_client.get(
            url="/api/wallet/recovery/funding_requirements",
        )
        assert recovery_requirements_response.status_code == 200
        recovery_requirements = recovery_requirements_response.json()
        TestWalletRecovery._assert_recovery_requirements(
            wallet_manager=wallet_manager,
            prepare_json=prepare_json,
            backup_owner=backup_owner,
            recovery_requirements=recovery_requirements,
            is_refill_required=False,
        )

        # Swap safe owners using backup wallet
        crypto = keys_manager.get_crypto_instance(backup_owner)
        for item in prepare_json["wallets"]:
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

        # Check recovery funding requirements
        recovery_requirements_response = operate_client.get(
            url="/api/wallet/recovery/funding_requirements",
        )
        assert recovery_requirements_response.status_code == 200
        recovery_requirements = recovery_requirements_response.json()
        TestWalletRecovery._assert_recovery_requirements(
            wallet_manager=wallet_manager,
            prepare_json=prepare_json,
            backup_owner=backup_owner,
            recovery_requirements=recovery_requirements,
            is_refill_required=False,
        )

        # Complete recovery
        complete_response = operate_client.post(
            url="/api/wallet/recovery/complete",
        )
        assert complete_response.status_code == 200

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
        with pytest.raises(WalletRecoveryError, match="No prepared bundle found."):
            operate.wallet_recovery_manager.complete_recovery()

        assert operate.wallet_recovery_manager.data.last_prepared_bundle_id is None

    def test_resumed_flow(
        self,
        test_env: OperateTestEnv,
    ) -> None:
        """test_resumed_flow"""
        operate = test_env.operate
        operate_client = test_env.operate_client
        wallet_manager = test_env.wallet_manager
        keys_manager = test_env.keys_manager
        backup_owner = test_env.backup_owner
        password = test_env.password

        # Prepare recovery
        new_password = password[::-1]

        assert operate.wallet_recovery_manager.data.last_prepared_bundle_id is None

        prepare_json_unused = operate.wallet_recovery_manager.prepare_recovery(
            new_password=new_password
        )
        prepare_json = operate.wallet_recovery_manager.prepare_recovery(
            new_password=new_password
        )

        TestWalletRecovery._assert_different_prepare_bundles(
            prepare_json_unused, prepare_json
        )

        assert operate.wallet_recovery_manager.data.last_prepared_bundle_id is not None
        assert (
            prepare_json.get("id")
            == operate.wallet_recovery_manager.data.last_prepared_bundle_id
        )
        assert prepare_json.get("wallets") is not None
        assert len(prepare_json["wallets"]) == len(wallet_manager.json)
        new_mnemonics: t.Dict[LedgerType, t.List[str]] = {}

        for item in prepare_json["wallets"]:
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

        bundle_id = prepare_json["id"]

        # Check recovery funding requirements
        recovery_requirements_response = operate_client.get(
            url="/api/wallet/recovery/funding_requirements",
        )
        assert recovery_requirements_response.status_code == 200
        recovery_requirements = recovery_requirements_response.json()
        TestWalletRecovery._assert_recovery_requirements(
            wallet_manager=wallet_manager,
            backup_owner=backup_owner,
            recovery_requirements=recovery_requirements,
            is_refill_required=False,
        )

        # Incompletely swap safe owners using backup wallet
        crypto = keys_manager.get_crypto_instance(backup_owner)
        for item in prepare_json["wallets"]:
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

        # Check recovery funding requirements
        recovery_requirements_response = operate_client.get(
            url="/api/wallet/recovery/funding_requirements",
        )
        assert recovery_requirements_response.status_code == 200
        recovery_requirements = recovery_requirements_response.json()
        TestWalletRecovery._assert_recovery_requirements(
            wallet_manager=wallet_manager,
            backup_owner=backup_owner,
            recovery_requirements=recovery_requirements,
            is_refill_required=False,
        )

        # Complete recovery - fail
        with pytest.raises(WalletRecoveryError, match="^Incorrect owners.*"):
            operate.wallet_recovery_manager.complete_recovery()

        # Resume swapping safe owners using backup wallet
        crypto = keys_manager.get_crypto_instance(backup_owner)
        for item in prepare_json["wallets"]:
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

        # Prepare recovery - resume incomplete bundle
        with pytest.raises(ValueError, match=MSG_INVALID_PASSWORD):
            operate.wallet_recovery_manager.prepare_recovery(
                new_password=new_password + "foo"
            )

        prepare_resumed_json = operate.wallet_recovery_manager.prepare_recovery(
            new_password=new_password
        )
        assert not DeepDiff(prepare_json, prepare_resumed_json)

        # Complete recovery
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
        assert operate.wallet_recovery_manager.data.last_prepared_bundle_id is None

        prepare_resumed_json = operate.wallet_recovery_manager.prepare_recovery(
            new_password=new_password
        )
        assert operate.wallet_recovery_manager.data.last_prepared_bundle_id is not None
        assert (
            prepare_resumed_json["id"]
            == operate.wallet_recovery_manager.data.last_prepared_bundle_id
        )
        assert prepare_resumed_json["id"] != bundle_id

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
            operate.wallet_recovery_manager.prepare_recovery(new_password=new_password)

        # Logout
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )

        with pytest.raises(WalletRecoveryError, match="No prepared bundle found."):
            operate.wallet_recovery_manager.complete_recovery()

        with pytest.raises(
            ValueError, match="'new_password' must be a non-empty string."
        ):
            operate.wallet_recovery_manager.prepare_recovery(new_password="")  # nosec

        with pytest.raises(
            ValueError, match="'new_password' must be a non-empty string."
        ):
            operate.wallet_recovery_manager.prepare_recovery(new_password=None)  # type: ignore

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
            operate.wallet_recovery_manager.prepare_recovery(new_password=new_password)

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

        # Prepare recovery
        prepare_json = operate.wallet_recovery_manager.prepare_recovery(
            new_password=new_password
        )

        assert prepare_json.get("id") is not None
        assert prepare_json.get("wallets") is not None
        assert len(prepare_json["wallets"]) == len(wallet_manager.json)
        new_mnemonics: t.Dict[LedgerType, t.List[str]] = {}

        for item in prepare_json["wallets"]:
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

        bundle_id = prepare_json["id"]

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
        for item in prepare_json["wallets"]:
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
            for item in prepare_json["wallets"]:
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
            for item in prepare_json["wallets"]:
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
            for item in prepare_json["wallets"]:
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

        # Complete recovery
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

        # Attempt to do a recovery without an prepared bundle will result in error
        operate = OperateApp(
            home=test_env.tmp_path / OPERATE_TEST,
        )

        with pytest.raises(WalletRecoveryError, match="No prepared bundle found."):
            operate.wallet_recovery_manager.complete_recovery()
