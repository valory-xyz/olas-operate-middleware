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

"""Wallet recoverer"""

import shutil
import typing as t
import uuid
from logging import Logger
from pathlib import Path

from operate.account.user import UserAccount
from operate.utils.gnosis import get_owners
from operate.wallet.master import MasterWalletManager


RECOVERY_BUNDLE_PREFIX = "eb-"
NEW_OBJECTS_SUBPATH = "temp"
OLD_OBJECTS_SUBPATH = "old"


class WalletRecoverer:
    """WalletRecoverer"""

    def __init__(
        self,
        path: Path,
        logger: Logger,
        wallet_manager: MasterWalletManager,
    ) -> None:
        """Initialize master wallet manager."""
        self.path = path
        self.logger = logger
        self.wallet_manager = wallet_manager

    def recovery_step_1(self, new_password: str) -> t.Dict:
        """Recovery step 1"""
        self.logger.info("[WALLET RECOVERER] Recovery step 1")
        bundle_id = f"{RECOVERY_BUNDLE_PREFIX}{str(uuid.uuid4())}"
        new_root = self.path / bundle_id / NEW_OBJECTS_SUBPATH
        new_root.mkdir(parents=True, exist_ok=False)
        UserAccount.new(new_password, new_root / "user.json")

        new_wallets_path = new_root / "wallets"
        new_wallet_manager = MasterWalletManager(
            path=new_wallets_path, logger=self.logger, password=new_password
        )
        new_wallet_manager.setup()

        output = []
        for wallet in self.wallet_manager:
            ledger_type = wallet.ledger_type
            new_wallet, new_mnemonic = new_wallet_manager.create(
                ledger_type=ledger_type
            )
            self.logger.info(
                f"[WALLET RECOVERER] Created new wallet {new_wallet.address}"
            )
            output.append(
                {
                    "wallet": wallet.json,
                    "new_wallet": new_wallet.json,
                    "new_mnemonic": new_mnemonic,
                }
            )

        self.logger.info("[WALLET RECOVERER] Recovery step 1 done")

        return {
            "id": bundle_id,
            "wallets": output,
        }

    def recovery_step_2(self, password: str, bundle_id: str) -> None:
        """Recovery step 2"""
        self.logger.info("[WALLET RECOVERER] Recovery step 2")

        root = self.path.parent
        wallets_path = root / "wallets"
        new_root = self.path / bundle_id / NEW_OBJECTS_SUBPATH
        new_wallets_path = new_root / "wallets"
        old_root = self.path / bundle_id / OLD_OBJECTS_SUBPATH

        try:
            _ = self.wallet_manager.password
        except ValueError:
            pass
        else:
            raise RuntimeError("Wallet recovery cannot be executed while logged in.")

        if not new_root.exists() or not new_root.is_dir():
            raise ValueError(f"Recovery bundle {bundle_id} does not exist.")

        if old_root.exists() and old_root.is_dir():
            raise ValueError(f"Recovery bundle {bundle_id} has been executed already.")

        new_user_account = UserAccount.load(new_root / "user.json")
        if not new_user_account.is_valid(password=password):
            raise ValueError("New password is not valid.")

        new_wallet_manager = MasterWalletManager(
            path=new_wallets_path, logger=self.logger, password=password
        )

        ledger_types = {item.ledger_type for item in self.wallet_manager}
        new_ledger_types = {item.ledger_type for item in new_wallet_manager}

        if ledger_types != new_ledger_types:
            raise RuntimeError(
                f"Ledger type mismatch: {ledger_types=}, {new_ledger_types=}."
            )

        for wallet in self.wallet_manager:
            new_wallet = next(
                (w for w in new_wallet_manager if w.ledger_type == wallet.ledger_type)
            )

            for chain, safe in wallet.safes.items():
                ledger_api = wallet.ledger_api(chain=chain)
                owners = get_owners(ledger_api=ledger_api, safe=safe)
                if new_wallet.address not in owners:
                    raise RuntimeError(
                        f"Wallet {new_wallet.address} is not an owner of {safe} on {chain}."
                    )

            new_wallet.safes = wallet.safes.copy()
            new_wallet.safe_chains = wallet.safe_chains.copy()
            new_wallet.store()

        # Do recovery
        try:
            old_root.mkdir(parents=True, exist_ok=False)
            shutil.move(str(wallets_path), str(old_root))
            for file in root.glob("user.json*"):
                shutil.move(str(file), str(old_root / file.name))

            shutil.move(str(new_wallets_path), str(root))
            for file in new_root.glob("user.json*"):
                shutil.move(str(file), str(root / file.name))

        except Exception as e:
            raise RuntimeError from e

        self.logger.info("[WALLET RECOVERER] Recovery step 2 done")
