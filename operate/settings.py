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
from operate.operate_types import ChainAmounts
from operate.resource import LocalResource


SETTINGS_JSON_VERSION = 1
DEFAULT_SETTINGS = {
    "version": SETTINGS_JSON_VERSION,
    "eoa_topups": DEFAULT_EOA_TOPUPS,
}


class Settings(LocalResource):
    """Settings for operate."""

    _file = SETTINGS_JSON

    version: int
    eoa_topups: Dict[str, Dict[str, int]]

    def __init__(self, path: Optional[Path] = None, **kwargs: Any) -> None:
        """Initialize settings."""
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

    def get_eoa_topups(self, with_safe: bool = False) -> ChainAmounts:
        """Get the EOA topups."""
        return (
            self.eoa_topups
            if with_safe
            else {
                chain: {asset: amount * 2 for asset, amount in asset_amount.items()}
                for chain, asset_amount in self.eoa_topups.items()
            }
        )

    def bigint2str_json(self) -> Dict:
        """Get the JSON representation with bigints as strings."""
        output = super().json
        output["eoa_topups"] = {
            chain: {asset: str(amount) for asset, amount in assets.items()}
            for chain, assets in self.eoa_topups.items()
        }
        return output
