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

from tests.conftest import OperateTestEnv, create_wallets
from tests.constants import CHAINS_TO_TEST


def test_settings_no_file(test_operate: OperateApp) -> None:
    """Test loading settings when no file is present."""
    create_wallets(wallet_manager=test_operate.wallet_manager)
    assert os.path.exists(test_operate._path / SETTINGS_JSON) is False
    settings: Settings = Settings()
    settings.store()
    assert os.path.exists(test_operate._path / SETTINGS_JSON) is True


def test_settings_default_values(test_env: OperateTestEnv) -> None:
    """Test settings default values."""
    test_env.operate.password = test_env.password
    settings: Settings = Settings()
    expected_eoa_topups = {
        chain: {
            asset: amount if chain in CHAINS_TO_TEST else amount * 2
            for asset, amount in asset_amount.items()
        }
        for chain, asset_amount in DEFAULT_EOA_TOPUPS.items()
    }
    assert settings.version == SETTINGS_JSON_VERSION
    assert settings.eoa_topups == DEFAULT_EOA_TOPUPS
    assert settings.get_eoa_topups() == expected_eoa_topups
    assert settings.json == {
        "version": SETTINGS_JSON_VERSION,
        "eoa_topups": serialize(expected_eoa_topups),
        "eoa_thresholds": serialize(
            {
                chain: {asset: amount // 2 for asset, amount in asset_amount.items()}
                for chain, asset_amount in expected_eoa_topups.items()
            }
        ),
    }


def test_settings_persistence(tmp_path: Path, test_operate: OperateApp) -> None:
    """Test settings persistence."""
    create_wallets(wallet_manager=test_operate.wallet_manager)
    existing_settings = test_operate.settings
    assert "new_chain" not in existing_settings.eoa_topups
    existing_settings.eoa_topups["new_chain"] = {"new_asset": 12345}
    existing_settings.store()

    del test_operate
    new_operate = OperateApp(home=tmp_path)

    loaded_settings = new_operate.settings
    assert loaded_settings.eoa_topups["new_chain"]["new_asset"] == 12345


def test_settings_version_mismatch(test_operate: OperateApp) -> None:
    """Test settings version mismatch."""
    create_wallets(wallet_manager=test_operate.wallet_manager)
    settings: Settings = Settings(path=test_operate._path)
    settings.store()

    with open(test_operate._path / SETTINGS_JSON) as f:
        data = json.load(f)

    data["version"] = 999  # incompatible version
    with open(test_operate._path / SETTINGS_JSON, "w") as f:
        json.dump(data, f)

    Settings._instances.clear()
    with pytest.raises(ValueError) as e:
        Settings(path=test_operate._path)
        assert str(e) == "Settings version 999 is not supported. Expected version 1."
