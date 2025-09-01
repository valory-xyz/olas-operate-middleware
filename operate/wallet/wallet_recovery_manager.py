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

"""Wallet recovery manager"""

import shutil
import typing as t
import uuid
from logging import Logger
from pathlib import Path

from operate.account.user import UserAccount
from operate.constants import USER_JSON, WALLETS_DIR
from operate.utils.gnosis import get_owners
from operate.wallet.master import MasterWalletManager


RECOVERY_BUNDLE_PREFIX = "eb-"
RECOVERY_NEW_OBJECTS_DIR = "tmp"
RECOVERY_OLD_OBJECTS_DIR = "old"


class WalletRecoveryError(Exception):
    """WalletRecoveryError"""


class WalletRecoveryManager:
    """WalletRecoveryManager"""

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

    def initiate_recovery(self, new_password: str) -> t.Dict:
        """Recovery step 1"""
        self.logger.info("[WALLET RECOVERY MANAGER] Recovery step 1 start")

        try:
            _ = self.wallet_manager.password
        except ValueError:
            pass
        else:
            raise WalletRecoveryError(
                "Wallet recovery cannot be executed while logged in."
            )

        if not new_password:
            raise ValueError("'new_password' must be a non-empty string.")

        bundle_id = f"{RECOVERY_BUNDLE_PREFIX}{str(uuid.uuid4())}"
        new_root = self.path / bundle_id / RECOVERY_NEW_OBJECTS_DIR
        new_root.mkdir(parents=True, exist_ok=False)
        UserAccount.new(new_password, new_root / USER_JSON)

        new_wallets_path = new_root / WALLETS_DIR
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
                f"[WALLET RECOVERY MANAGER] Created new wallet {ledger_type=} {new_wallet.address=}"
            )
            output.append(
                {
                    "current_wallet": wallet.json,
                    "new_wallet": new_wallet.json,
                    "new_mnemonic": new_mnemonic,
                }
            )

        self.logger.info("[WALLET RECOVERY MANAGER] Recovery step 1 finish")

        return {
            "id": bundle_id,
            "wallets": output,
        }

    def complete_recovery(  # pylint: disable=too-many-locals,too-many-statements
        self, bundle_id: str, password: str, raise_if_inconsistent_owners: bool = True
    ) -> None:
        """Recovery step 2"""
        self.logger.info("[WALLET RECOVERY MANAGER] Recovery step 2 start")

        def _report_issue(msg: str) -> None:
            self.logger.warning(f"[WALLET RECOVERY MANAGER] {msg}")
            if raise_if_inconsistent_owners:
                raise WalletRecoveryError(f"{msg}")

        try:
            _ = self.wallet_manager.password
        except ValueError:
            pass
        else:
            raise WalletRecoveryError(
                "Wallet recovery cannot be executed while logged in."
            )

        if not password:
            raise ValueError("'password' must be a non-empty string.")

        if not bundle_id:
            raise ValueError("'bundle_id' must be a non-empty string.")

        root = self.path.parent  # .operate root
        wallets_path = root / WALLETS_DIR
        new_root = self.path / bundle_id / RECOVERY_NEW_OBJECTS_DIR
        new_wallets_path = new_root / WALLETS_DIR
        old_root = self.path / bundle_id / RECOVERY_OLD_OBJECTS_DIR

        if not new_root.exists() or not new_root.is_dir():
            raise KeyError(f"Recovery bundle {bundle_id} does not exist.")

        if old_root.exists() and old_root.is_dir():
            raise ValueError(f"Recovery bundle {bundle_id} has been executed already.")

        new_user_account = UserAccount.load(new_root / USER_JSON)
        if not new_user_account.is_valid(password=password):
            raise ValueError("Password is not valid.")

        new_wallet_manager = MasterWalletManager(
            path=new_wallets_path, logger=self.logger, password=password
        )

        ledger_types = {item.ledger_type for item in self.wallet_manager}
        new_ledger_types = {item.ledger_type for item in new_wallet_manager}

        if ledger_types != new_ledger_types:
            raise WalletRecoveryError(
                f"Ledger type mismatch: {ledger_types=}, {new_ledger_types=}."
            )

        for wallet in self.wallet_manager:
            new_wallet = next(
                (w for w in new_wallet_manager if w.ledger_type == wallet.ledger_type)
            )

            all_backup_owners = set()
            for chain, safe in wallet.safes.items():
                ledger_api = wallet.ledger_api(chain=chain)
                owners = get_owners(ledger_api=ledger_api, safe=safe)
                if new_wallet.address not in owners:
                    raise WalletRecoveryError(
                        f"Incorrect owners. Wallet {new_wallet.address} is not an owner of Safe {safe} on {chain}."
                    )
                if wallet.address in owners:
                    _report_issue(
                        f"Inconsistent owners. Current wallet {wallet.address} is still an owner of Safe {safe} on {chain}."
                    )
                if len(owners) != 2:
                    _report_issue(
                        f"Inconsistent owners. Safe {safe} on {chain} has {len(owners)} != 2 owners."
                    )
                all_backup_owners.update(set(owners) - {new_wallet.address})

            if len(all_backup_owners) != 1:
                _report_issue(
                    f"Inconsistent owners. Backup owners differ across Safes on chains {', '.join(chain.value for chain in wallet.safes.keys())}. "
                    f"Found backup owners: {', '.join(map(str, all_backup_owners))}."
                )

            new_wallet.safes = wallet.safes.copy()
            new_wallet.safe_chains = wallet.safe_chains.copy()
            new_wallet.safe_nonce = wallet.safe_nonce
            new_wallet.store()

        # Update configuration recovery
        try:
            old_root.mkdir(parents=True, exist_ok=False)
            shutil.move(str(wallets_path), str(old_root))
            for file in root.glob(f"{USER_JSON}*"):
                shutil.move(str(file), str(old_root / file.name))

            shutil.move(str(new_wallets_path), str(root))
            for file in new_root.glob(f"{USER_JSON}*"):
                shutil.move(str(file), str(root / file.name))

        except Exception as e:
            raise RuntimeError from e

        self.logger.info("[WALLET RECOVERY MANAGER] Recovery step 2 finish")
