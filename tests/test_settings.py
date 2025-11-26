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
"""Tests for settings."""

import json
import os
from pathlib import Path

import pytest

from operate.cli import OperateApp
from operate.constants import SETTINGS_JSON
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS
from operate.resource import serialize
from operate.settings import SETTINGS_JSON_VERSION, Settings


def test_settings_no_file(tmp_path: Path) -> None:
    """Test loading settings when no file is present."""
    assert os.path.exists(tmp_path / SETTINGS_JSON) is False
    settings = Settings(path=tmp_path)
    settings.store()
    assert os.path.exists(tmp_path / SETTINGS_JSON) is True


def test_settings_default_values() -> None:
    """Test settings default values."""
    settings = Settings()
    assert settings.version == SETTINGS_JSON_VERSION
    assert settings.eoa_topups == DEFAULT_EOA_TOPUPS
    assert settings.get_eoa_topups(with_safe=True) == DEFAULT_EOA_TOPUPS
    assert settings.get_eoa_topups() == {
        chain: {asset: amount * 2 for asset, amount in asset_amount.items()}
        for chain, asset_amount in DEFAULT_EOA_TOPUPS.items()
    }
    assert settings.json == {
        "version": SETTINGS_JSON_VERSION,
        "eoa_topups": serialize(DEFAULT_EOA_TOPUPS),
    }


def test_settings_persistence(tmp_path: Path, test_operate: OperateApp) -> None:
    """Test settings persistence."""
    existing_settings = test_operate.settings
    assert existing_settings.get_eoa_topups(with_safe=True) == DEFAULT_EOA_TOPUPS
    assert "new_chain" not in existing_settings.eoa_topups
    existing_settings.eoa_topups["new_chain"] = {"new_asset": 12345}
    existing_settings.store()

    del test_operate
    new_operate = OperateApp(home=tmp_path)

    loaded_settings = new_operate.settings
    assert loaded_settings.get_eoa_topups(with_safe=True) == DEFAULT_EOA_TOPUPS | {
        "new_chain": {"new_asset": 12345}
    }


def test_settings_version_mismatch(tmp_path: Path) -> None:
    """Test settings version mismatch."""
    settings = Settings(path=tmp_path)
    settings.store()

    with open(tmp_path / SETTINGS_JSON) as f:
        data = json.load(f)

    data["version"] = 999  # incompatible version
    with open(tmp_path / SETTINGS_JSON, "w") as f:
        json.dump(data, f)

    with pytest.raises(
        ValueError, match="Settings version 999 is not supported. Expected version 1."
    ):
        Settings(path=tmp_path)
