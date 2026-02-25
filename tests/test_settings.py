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
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from operate.cli import OperateApp
from operate.constants import SETTINGS_JSON
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS
from operate.operate_types import Chain
from operate.resource import serialize
from operate.serialization import BigInt
from operate.settings import SETTINGS_JSON_VERSION, Settings

from tests.conftest import OperateTestEnv, create_wallets
from tests.constants import CHAINS_TO_TEST


@pytest.fixture(autouse=True)
def _clear_settings_singleton() -> Iterator[None]:
    """Clear the Settings singleton before and after every test."""
    Settings._instances.clear()
    yield
    Settings._instances.clear()


# ---------------------------------------------------------------------------
# Integration tests (require test_operate / test_env fixtures)
# ---------------------------------------------------------------------------


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

    Settings._instances.clear()
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
    with pytest.raises(
        ValueError,
        match="Settings version 999 is not supported. Expected version 1.",
    ):
        Settings(
            wallet_manager=test_operate.wallet_manager,
            path=test_operate._path,
        )


# ---------------------------------------------------------------------------
# Unit tests (mock-based, no fixtures needed)
# ---------------------------------------------------------------------------


class TestSettingsInit:
    """Tests for Settings.__init__ validation."""

    def test_missing_wallet_manager_raises(self) -> None:
        """Test that omitting wallet_manager raises ValueError."""
        with pytest.raises(ValueError, match="wallet_manager is required"):
            Settings(path=Path("/tmp/nonexistent"))  # nosec B108

    def test_singleton_returns_same_instance(self, tmp_path: Path) -> None:
        """Test that Settings is a singleton — second call returns the same object."""
        wm = MagicMock()
        first = Settings(wallet_manager=wm, path=tmp_path)
        second = Settings(wallet_manager=wm, path=tmp_path)
        assert first is second


class TestGetEoaTopups:
    """Tests for Settings.get_eoa_topups with mocked wallet."""

    def _make_settings(self, tmp_path: Path, safes: dict) -> Settings:  # type: ignore[type-arg]
        """Create a Settings with a mocked wallet_manager."""
        mock_wallet = MagicMock()
        mock_wallet.safes = safes
        mock_wm = MagicMock()
        mock_wm.load.return_value = mock_wallet
        settings = Settings(wallet_manager=mock_wm, path=tmp_path)
        settings.eoa_topups = {
            Chain.GNOSIS: {"0x0": BigInt(100)},
            Chain.BASE: {"0x0": BigInt(200)},
        }
        return settings

    def test_chains_with_safe_get_original_amount(self, tmp_path: Path) -> None:
        """Chains that have a Safe should return the original topup amount."""
        settings = self._make_settings(
            tmp_path, safes={Chain.GNOSIS: "0xSafe", Chain.BASE: "0xSafe2"}
        )
        result = settings.get_eoa_topups()
        assert result[Chain.GNOSIS]["0x0"] == 100
        assert result[Chain.BASE]["0x0"] == 200

    def test_chains_without_safe_get_doubled_amount(self, tmp_path: Path) -> None:
        """Chains without a Safe should return 2x the topup amount."""
        settings = self._make_settings(tmp_path, safes={Chain.GNOSIS: "0xSafe"})
        result = settings.get_eoa_topups()
        assert result[Chain.GNOSIS]["0x0"] == 100  # has safe
        assert result[Chain.BASE]["0x0"] == 400  # no safe → doubled

    def test_no_safes_doubles_all(self, tmp_path: Path) -> None:
        """When wallet has no safes, all topups are doubled."""
        settings = self._make_settings(tmp_path, safes={})
        result = settings.get_eoa_topups()
        assert result[Chain.GNOSIS]["0x0"] == 200
        assert result[Chain.BASE]["0x0"] == 400

    def test_missing_wallet_file_doubles_all(self, tmp_path: Path) -> None:
        """When wallet file does not exist, all topups are doubled."""
        mock_wm = MagicMock()
        mock_wm.load.side_effect = FileNotFoundError("ethereum.json not found")
        settings = Settings(wallet_manager=mock_wm, path=tmp_path)
        settings.eoa_topups = {
            Chain.GNOSIS: {"0x0": BigInt(100)},
            Chain.BASE: {"0x0": BigInt(200)},
        }
        result = settings.get_eoa_topups()
        assert result[Chain.GNOSIS]["0x0"] == 200
        assert result[Chain.BASE]["0x0"] == 400


class TestSettingsJson:
    """Tests for Settings.json property."""

    def test_json_contains_thresholds(self, tmp_path: Path) -> None:
        """Test that json includes eoa_thresholds as topups // 2."""
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: "0xSafe"}
        mock_wm = MagicMock()
        mock_wm.load.return_value = mock_wallet
        settings = Settings(wallet_manager=mock_wm, path=tmp_path)
        settings.eoa_topups = {Chain.GNOSIS: {"0x0": BigInt(1000)}}

        result = settings.json
        assert "eoa_thresholds" in result
        assert "eoa_topups" in result
        assert "version" in result
        # Threshold should be topup // 2
        gnosis_key = str(Chain.GNOSIS.value)
        assert result["eoa_thresholds"][gnosis_key]["0x0"] == 500
