# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""Tests for wallet.wallet_recoverey_manager module."""

import json
import tempfile
import uuid
from pathlib import Path

import pytest
import requests
from aea.crypto.base import Crypto
from aea_ledger_ethereum import EthereumCrypto
from dotenv import load_dotenv
from eth_account.signers.local import LocalAccount
from web3 import Account

from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.operate_types import Chain, LedgerType
from operate.utils.gnosis import add_owner, remove_owner, swap_owner
from operate.wallet.master import MasterWalletManager
from operate.wallet.wallet_recovery_manager import (
    RECOVERY_BUNDLE_PREFIX,
    RECOVERY_OLD_OBJECTS_DIR,
    WalletRecoveryError,
)

from tests.conftest import OPERATE_TEST, RUNNING_IN_CI, random_string


load_dotenv()

# TODO operate.ledger must be loaded after load_dotenv() due to RPC env vars.
from operate.ledger import get_default_rpc  # noqa: E402


LEDGER_TO_CHAINS = {LedgerType.ETHEREUM: [Chain.GNOSIS, Chain.BASE]}


def tenderly_add_balance(
    chain: Chain,
    recipient: str,
    amount: int = 1000 * (10**18),
    token: str = ZERO_ADDRESS,
) -> None:
    """tenderly_add_balance"""
    rpc = get_default_rpc(chain)
    headers = {"Content-Type": "application/json"}

    if token == ZERO_ADDRESS:
        data = {
            "jsonrpc": "2.0",
            "method": "tenderly_addBalance",
            "params": [recipient, hex(amount)],
            "id": "1",
        }
    else:
        data = {
            "jsonrpc": "2.0",
            "method": "tenderly_setErc20Balance",
            "params": [token, recipient, hex(amount)],
            "id": "1",
        }

    response = requests.post(
        url=rpc, headers=headers, data=json.dumps(data), timeout=30
    )
    response.raise_for_status()


def create_crypto(ledger_type: LedgerType, private_key: str) -> Crypto:
    """create_crypto"""
    with tempfile.NamedTemporaryFile(mode="w", delete=True) as tmp_file:
        tmp_file.write(private_key)
        tmp_file.flush()
        if ledger_type == LedgerType.ETHEREUM:
            crypto = EthereumCrypto(private_key_path=tmp_file.name)
        else:
            raise NotImplementedError()
    return crypto


# TODO enable test once Tenderly RPCs are set up on CI.
@pytest.mark.skipif(RUNNING_IN_CI, reason="Skip test on CI.")
class TestWalletRecovery:
    """Tests for wallet.wallet_recoverey_manager.WalletRecoveryManager class."""

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

    @staticmethod
    def _create_wallets(wallet_manager: MasterWalletManager) -> None:
        for ledger_type in LEDGER_TO_CHAINS:
            wallet_manager.create(ledger_type=ledger_type)

    @staticmethod
    def _create_safes(wallet_manager: MasterWalletManager, backup_owner: str) -> None:
        for ledger_type, chains in LEDGER_TO_CHAINS.items():
            wallet = wallet_manager.load(ledger_type=ledger_type)
            for chain in chains:
                tenderly_add_balance(chain, wallet.address)
                tenderly_add_balance(chain, backup_owner)
                wallet.create_safe(
                    chain=chain,
                    backup_owner=backup_owner,
                )

    def test_normal_flow(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_normal_flow"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        wallet_manager = operate.wallet_manager
        wallet_manager.setup()
        backup_wallet: LocalAccount = Account().create()
        TestWalletRecovery._create_wallets(wallet_manager=wallet_manager)
        TestWalletRecovery._create_safes(
            wallet_manager=wallet_manager,
            backup_owner=backup_wallet.address,
        )

        # Logout
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )

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
            assert set(item["current_wallet"]["safes"]) == {
                c.value
                for c in LEDGER_TO_CHAINS[
                    LedgerType(item["current_wallet"]["ledger_type"])
                ]
            }
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()

        bundle_id = step_1_output["id"]

        # Swap safe owners using backup wallet
        for item in step_1_output["wallets"]:
            crypto = create_crypto(
                ledger_type=LedgerType(item["current_wallet"]["ledger_type"]),
                private_key=backup_wallet.key.hex(),
            )

            for ledger_type, chains in LEDGER_TO_CHAINS.items():
                wallet = wallet_manager.load(ledger_type=ledger_type)
                for chain in chains:
                    ledger_api = wallet.ledger_api(chain)
                    swap_owner(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=item["current_wallet"]["safes"][chain.value],
                        old_owner=wallet.address,
                        new_owner=item["new_wallet"]["address"],
                    )

        # Recovery step 2
        operate.wallet_recoverey_manager.complete_recovery(
            password=new_password,
            bundle_id=bundle_id,
        )

        # Test that recovery was successful
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
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
            logger=operate.logger,
            password=password,
        )

        TestWalletRecovery._assert_recovered(old_wallet_manager, wallet_manager)

        # Attempt to do a recovery with the same bundle will result in error
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        with pytest.raises(
            ValueError, match=f"Recovery bundle {bundle_id} has been executed already."
        ):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=bundle_id
            )

    def test_resumed_flow(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_incomplete_flow"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        wallet_manager = operate.wallet_manager
        wallet_manager.setup()
        backup_wallet: LocalAccount = Account().create()
        TestWalletRecovery._create_wallets(wallet_manager=wallet_manager)
        TestWalletRecovery._create_safes(
            wallet_manager=wallet_manager,
            backup_owner=backup_wallet.address,
        )

        # Logout
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )

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
            assert set(item["current_wallet"]["safes"]) == {
                c.value
                for c in LEDGER_TO_CHAINS[
                    LedgerType(item["current_wallet"]["ledger_type"])
                ]
            }
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()

        bundle_id = step_1_output["id"]

        # Incompletely swap safe owners using backup wallet
        ledger_to_chains_1 = {}
        ledger_to_chains_2 = {}

        for ledger, chains in LEDGER_TO_CHAINS.items():
            mid = len(chains) // 2
            ledger_to_chains_1[ledger] = chains[:mid]
            ledger_to_chains_2[ledger] = chains[mid:]

        for item in step_1_output["wallets"]:
            crypto = create_crypto(
                ledger_type=LedgerType(item["current_wallet"]["ledger_type"]),
                private_key=backup_wallet.key.hex(),
            )

            for ledger_type, chains in ledger_to_chains_1.items():
                wallet = wallet_manager.load(ledger_type=ledger_type)
                for chain in chains:
                    ledger_api = wallet.ledger_api(chain)
                    swap_owner(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=item["current_wallet"]["safes"][chain.value],
                        old_owner=wallet.address,
                        new_owner=item["new_wallet"]["address"],
                    )

        # Recovery step 2 - fail
        with pytest.raises(WalletRecoveryError, match="^Incorrect owners.*"):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password,
                bundle_id=bundle_id,
            )

        # Resume swapping safe owners using backup wallet
        for item in step_1_output["wallets"]:
            crypto = create_crypto(
                ledger_type=LedgerType(item["current_wallet"]["ledger_type"]),
                private_key=backup_wallet.key.hex(),
            )

            for ledger_type, chains in ledger_to_chains_2.items():
                wallet = wallet_manager.load(ledger_type=ledger_type)
                for chain in chains:
                    ledger_api = wallet.ledger_api(chain)
                    swap_owner(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=item["current_wallet"]["safes"][chain.value],
                        old_owner=wallet.address,
                        new_owner=item["new_wallet"]["address"],
                    )

        # Recovery step 2
        operate.wallet_recoverey_manager.complete_recovery(
            password=new_password,
            bundle_id=bundle_id,
        )

        # Test that recovery was successful
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
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
            logger=operate.logger,
            password=password,
        )

        TestWalletRecovery._assert_recovered(old_wallet_manager, wallet_manager)

    @pytest.mark.parametrize("raise_if_inconsistent_owners", [True, False])
    def test_exceptions(
        self,
        tmp_path: Path,
        password: str,
        raise_if_inconsistent_owners: bool,
    ) -> None:
        """test_exceptions"""

        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        wallet_manager = operate.wallet_manager
        wallet_manager.setup()
        backup_wallet: LocalAccount = Account().create()
        backup_wallet2: LocalAccount = Account().create()
        TestWalletRecovery._create_wallets(wallet_manager=wallet_manager)
        TestWalletRecovery._create_safes(
            wallet_manager=wallet_manager,
            backup_owner=backup_wallet.address,
        )

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
            home=tmp_path / OPERATE_TEST,
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
            home=tmp_path / OPERATE_TEST,
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
        for item in step_1_output["wallets"]:
            crypto = create_crypto(
                ledger_type=LedgerType(item["current_wallet"]["ledger_type"]),
                private_key=backup_wallet.key.hex(),
            )

            for ledger_type, chains in LEDGER_TO_CHAINS.items():
                wallet = wallet_manager.load(ledger_type=ledger_type)
                for chain in chains:
                    ledger_api = wallet.ledger_api(chain)
                    add_owner(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=item["current_wallet"]["safes"][chain.value],
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
            for item in step_1_output["wallets"]:
                crypto = create_crypto(
                    ledger_type=LedgerType(item["current_wallet"]["ledger_type"]),
                    private_key=backup_wallet.key.hex(),
                )

                for ledger_type, chains in LEDGER_TO_CHAINS.items():
                    wallet = wallet_manager.load(ledger_type=ledger_type)
                    for chain in chains:
                        ledger_api = wallet.ledger_api(chain)
                        remove_owner(
                            ledger_api=ledger_api,
                            crypto=crypto,
                            safe=item["current_wallet"]["safes"][chain.value],
                            owner=wallet.address,
                            threshold=1,
                        )

            ledger_to_chains_1 = {}
            ledger_to_chains_2 = {}

            for ledger, chains in LEDGER_TO_CHAINS.items():
                mid = len(chains) // 2
                ledger_to_chains_1[ledger] = chains[:mid]
                ledger_to_chains_2[ledger] = chains[mid:]

            # Use a different backup owner for half of the chains
            for item in step_1_output["wallets"]:
                crypto = create_crypto(
                    ledger_type=LedgerType(item["current_wallet"]["ledger_type"]),
                    private_key=backup_wallet.key.hex(),
                )

                for ledger_type, chains in ledger_to_chains_1.items():
                    wallet = wallet_manager.load(ledger_type=ledger_type)
                    for chain in chains:
                        ledger_api = wallet.ledger_api(chain)
                        swap_owner(
                            ledger_api=ledger_api,
                            crypto=crypto,
                            safe=item["current_wallet"]["safes"][chain.value],
                            old_owner=backup_wallet.address,
                            new_owner=backup_wallet2.address,
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
            for item in step_1_output["wallets"]:
                crypto = create_crypto(
                    ledger_type=LedgerType(item["current_wallet"]["ledger_type"]),
                    private_key=backup_wallet2.key.hex(),
                )

                for ledger_type, chains in ledger_to_chains_1.items():
                    wallet = wallet_manager.load(ledger_type=ledger_type)
                    for chain in chains:
                        tenderly_add_balance(chain, backup_wallet2.address)
                        ledger_api = wallet.ledger_api(chain)
                        swap_owner(
                            ledger_api=ledger_api,
                            crypto=crypto,
                            safe=item["current_wallet"]["safes"][chain.value],
                            old_owner=backup_wallet2.address,
                            new_owner=backup_wallet.address,
                        )

        # Recovery step 2
        operate.wallet_recoverey_manager.complete_recovery(
            password=new_password,
            bundle_id=bundle_id,
            raise_if_inconsistent_owners=raise_if_inconsistent_owners,
        )

        # Test that recovery was successful
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
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
            logger=operate.logger,
            password=password,
        )

        TestWalletRecovery._assert_recovered(old_wallet_manager, wallet_manager)

        # Attempt to do a recovery with the same bundle will result in error
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        with pytest.raises(
            ValueError, match=f"Recovery bundle {bundle_id} has been executed already."
        ):
            operate.wallet_recoverey_manager.complete_recovery(
                password=new_password, bundle_id=bundle_id
            )
