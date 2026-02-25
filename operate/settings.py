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
"""Settings for operate."""

from pathlib import Path
from typing import Any, Dict, Optional

from operate.constants import SETTINGS_JSON
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS
from operate.operate_types import Chain, LedgerType
from operate.resource import LocalResource, serialize
from operate.serialization import BigInt
from operate.utils import SingletonMeta
from operate.wallet.master import MasterWalletManager


SETTINGS_JSON_VERSION = 1
DEFAULT_SETTINGS = {
    "version": SETTINGS_JSON_VERSION,
    "eoa_topups": DEFAULT_EOA_TOPUPS,
}


class Settings(LocalResource, metaclass=SingletonMeta):
    """Settings for operate."""

    _file = SETTINGS_JSON

    version: int
    eoa_topups: Dict[str, Dict[str, BigInt]]

    def __init__(self, path: Optional[Path] = None, **kwargs: Any) -> None:
        """Initialize settings."""
        if "wallet_manager" not in kwargs:
            raise ValueError("wallet_manager is required to initialize Settings.")

        self.wallet_manager: MasterWalletManager = kwargs.pop("wallet_manager")
        super().__init__(path=path)
        if path is not None and (path / self._file).exists():
            self.load(path)

        for key, default_value in DEFAULT_SETTINGS.items():
            value = kwargs.get(key, default_value)
            if not hasattr(self, key):
                setattr(self, key, value)

        if self.version != SETTINGS_JSON_VERSION:
            raise ValueError(
                f"Settings version {self.version} is not supported. Expected version {SETTINGS_JSON_VERSION}."
            )

    @property
    def json(self) -> Dict[str, Any]:
        """Get the settings as a JSON serializable dictionary."""
        eoa_topups = self.get_eoa_topups()
        return serialize(
            {
                "version": self.version,
                "eoa_topups": eoa_topups,
                "eoa_thresholds": {
                    chain: {
                        asset: amount // 2 for asset, amount in asset_amount.items()
                    }
                    for chain, asset_amount in eoa_topups.items()
                },
            }
        )

    def get_eoa_topups(self) -> Dict[Chain, Dict[str, BigInt]]:
        """Get the EOA topups."""
        eth_master_wallet = self.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)
        return {
            chain: {
                asset: (
                    amount if chain in eth_master_wallet.safes else BigInt(amount * 2)
                )
                for asset, amount in asset_amount.items()
            }
            for chain, asset_amount in self.eoa_topups.items()
        }
