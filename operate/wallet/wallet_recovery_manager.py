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
from dataclasses import dataclass
from logging import Logger
from pathlib import Path

from operate.account.user import UserAccount
from operate.constants import MSG_INVALID_PASSWORD, USER_JSON, WALLETS_DIR
from operate.resource import LocalResource
from operate.utils.gnosis import get_owners
from operate.wallet.master import MasterWalletManager


RECOVERY_BUNDLE_PREFIX = "eb-"
RECOVERY_NEW_OBJECTS_DIR = "new"
RECOVERY_OLD_OBJECTS_DIR = "old"


class WalletRecoveryError(Exception):
    """WalletRecoveryError"""


@dataclass
class WalletRecoveryManagerData(LocalResource):
    """BridgeManagerData"""

    path: Path
    version: int = 1
    last_prepared_bundle_id: t.Optional[str] = None

    _file = "wallet_recovery.json"


class WalletRecoveryManager:
    """WalletRecoveryManager"""

    def __init__(
        self,
        path: Path,
        logger: Logger,
        wallet_manager: MasterWalletManager,
    ) -> None:
        """Initialize wallet recovery manager."""
        self.path = path
        self.logger = logger
        self.wallet_manager = wallet_manager

        path.mkdir(parents=True, exist_ok=True)
        file = path / WalletRecoveryManagerData._file
        if not file.exists():
            WalletRecoveryManagerData(path=path).store()

        self.data: WalletRecoveryManagerData = t.cast(
            WalletRecoveryManagerData, WalletRecoveryManagerData.load(path)
        )

    def prepare_recovery(  # pylint: disable=too-many-locals
        self, new_password: str
    ) -> t.Dict:
        """Prepare recovery"""
        self.logger.info("[WALLET RECOVERY MANAGER] Prepare recovery started.")

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

        for wallet in self.wallet_manager:
            for chain, safe in wallet.safes.items():
                ledger_api = wallet.ledger_api(chain=chain)
                owners = get_owners(ledger_api=ledger_api, safe=safe)

                if wallet.address not in owners:
                    self.logger.warning(
                        f"Wallet {wallet.address} is not an owner of Safe {safe} on {chain.value}. (Interrupted swapping of Safe owners?)"
                    )

                if len(owners) < 2:
                    raise WalletRecoveryError(
                        f"Safe {safe} on {chain.value} has less than 2 owners."
                    )

        last_prepared_bundle_id = self.data.last_prepared_bundle_id
        if last_prepared_bundle_id is not None:
            if self._bundle_has_safes_with_new_wallet(last_prepared_bundle_id):
                self.logger.info(
                    f"[WALLET RECOVERY MANAGER] Existing bundle {last_prepared_bundle_id} has Safes with new wallet."
                )

                new_root = (
                    self.path / last_prepared_bundle_id / RECOVERY_NEW_OBJECTS_DIR
                )
                new_user_account = UserAccount.load(new_root / USER_JSON)
                if not new_user_account.is_valid(password=new_password):
                    raise ValueError(MSG_INVALID_PASSWORD)

                new_wallets_path = new_root / WALLETS_DIR
                new_wallet_manager = MasterWalletManager(
                    path=new_wallets_path, password=new_password
                )

                wallets = []
                for wallet in self.wallet_manager:
                    ledger_type = wallet.ledger_type
                    new_wallet = new_wallet_manager.load(ledger_type=ledger_type)
                    new_mnemonic = new_wallet.decrypt_mnemonic(password=new_password)
                    wallets.append(
                        {
                            "current_wallet": wallet.json,
                            "new_wallet": new_wallet.json,
                            "new_mnemonic": new_mnemonic,
                        }
                    )

                self.logger.info(
                    "[WALLET RECOVERY MANAGER] Prepare recovery finished with existing bundle."
                )
                return {
                    "id": last_prepared_bundle_id,
                    "wallets": wallets,
                }

        bundle_id = f"{RECOVERY_BUNDLE_PREFIX}{str(uuid.uuid4())}"
        new_root = self.path / bundle_id / RECOVERY_NEW_OBJECTS_DIR
        new_root.mkdir(parents=True, exist_ok=False)
        UserAccount.new(new_password, new_root / USER_JSON)

        new_wallets_path = new_root / WALLETS_DIR
        new_wallet_manager = MasterWalletManager(
            path=new_wallets_path, password=new_password
        )
        new_wallet_manager.setup()

        wallets = []
        for wallet in self.wallet_manager:
            ledger_type = wallet.ledger_type
            new_wallet, new_mnemonic = new_wallet_manager.create(
                ledger_type=ledger_type
            )
            self.logger.info(
                f"[WALLET RECOVERY MANAGER] Created new wallet {ledger_type=} {new_wallet.address=}"
            )
            wallets.append(
                {
                    "current_wallet": wallet.json,
                    "new_wallet": new_wallet.json,
                    "new_mnemonic": new_mnemonic,
                }
            )

        self.data.last_prepared_bundle_id = bundle_id
        self.data.store()
        self.logger.info(
            "[WALLET RECOVERY MANAGER] Prepare recovery finished with new bundle."
        )
        return {
            "id": bundle_id,
            "wallets": wallets,
        }

    def _bundle_has_safes_with_new_wallet(self, bundle_id: str) -> bool:
        new_root = self.path / bundle_id / RECOVERY_NEW_OBJECTS_DIR
        new_wallets_path = new_root / WALLETS_DIR
        new_wallet_manager = MasterWalletManager(path=new_wallets_path, password=None)

        for wallet in self.wallet_manager:
            new_wallet = next(
                (w for w in new_wallet_manager if w.ledger_type == wallet.ledger_type)
            )
            for chain, safe in wallet.safes.items():
                ledger_api = wallet.ledger_api(chain=chain)
                owners = get_owners(ledger_api=ledger_api, safe=safe)

                if new_wallet.address in owners:
                    return True

        return False

    def complete_recovery(  # pylint: disable=too-many-locals,too-many-statements
        self, raise_if_inconsistent_owners: bool = True
    ) -> None:
        """Complete recovery"""
        self.logger.info("[WALLET RECOVERY MANAGER] Complete recovery started.")

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

        bundle_id = self.data.last_prepared_bundle_id

        if not bundle_id:
            raise WalletRecoveryError("No prepared bundle found.")

        root = self.path.parent  # .operate root
        wallets_path = root / WALLETS_DIR
        new_root = self.path / bundle_id / RECOVERY_NEW_OBJECTS_DIR
        new_wallets_path = new_root / WALLETS_DIR
        old_root = self.path / bundle_id / RECOVERY_OLD_OBJECTS_DIR

        if not new_root.exists() or not new_root.is_dir():
            raise RuntimeError(f"Recovery bundle {bundle_id} does not exist.")

        if old_root.exists() and old_root.is_dir():
            raise RuntimeError(
                f"Recovery bundle {bundle_id} has been executed already."
            )

        new_wallet_manager = MasterWalletManager(path=new_wallets_path, password=None)

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

            self.data.last_prepared_bundle_id = None
            self.data.store()
        except Exception as e:
            raise RuntimeError from e

        self.logger.info("[WALLET RECOVERY MANAGER] Complete recovery finished.")
