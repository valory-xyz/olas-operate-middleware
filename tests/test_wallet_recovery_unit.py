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

"""Unit tests for operate/wallet/wallet_recovery_manager.py – no blockchain required."""

import typing as t
from logging import getLogger
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from operate.constants import KEYS_DIR
from operate.operate_types import Chain, LedgerType
from operate.wallet.wallet_recovery_manager import (
    WalletRecoveryError,
    WalletRecoveryManager,
    WalletRecoveryStatus,
)


CHAIN = Chain.GNOSIS
EOA_ADDR = "0x" + "a" * 40
SAFE_ADDR = "0x" + "b" * 40
BACKUP_ADDR = "0x" + "c" * 40
NEW_EOA_ADDR = "0x" + "d" * 40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> WalletRecoveryManager:
    """Create a WalletRecoveryManager in *tmp_path* with mock dependencies."""
    recovery_path = tmp_path / "recovery"
    logger = getLogger("test")
    wallet_manager = MagicMock()
    service_manager = MagicMock()
    return WalletRecoveryManager(
        path=recovery_path,
        logger=logger,
        wallet_manager=wallet_manager,
        service_manager=service_manager,
    )


def _make_wallet_mock(
    address: str = EOA_ADDR,
    safes: t.Optional[t.Dict] = None,
    ledger_type: LedgerType = LedgerType.ETHEREUM,
) -> MagicMock:
    """Return a mock wallet with sensible defaults."""
    w = MagicMock()
    w.address = address
    w.safes = safes if safes is not None else {CHAIN: SAFE_ADDR}
    w.ledger_type = ledger_type
    w.json = {"safes": {CHAIN.value: SAFE_ADDR}}
    return w


# ---------------------------------------------------------------------------
# WalletRecoveryStatus
# ---------------------------------------------------------------------------


class TestWalletRecoveryStatus:
    """Tests for WalletRecoveryStatus enum."""

    def test_str_returns_value(self) -> None:
        """Test __str__ returns the enum value string (line 64)."""
        assert str(WalletRecoveryStatus.NOT_PREPARED) == "NOT_PREPARED"
        assert str(WalletRecoveryStatus.PREPARED) == "PREPARED"
        assert str(WalletRecoveryStatus.IN_PROGRESS) == "IN_PROGRESS"
        assert str(WalletRecoveryStatus.COMPLETED) == "COMPLETED"


# ---------------------------------------------------------------------------
# WalletRecoveryManager – __init__
# ---------------------------------------------------------------------------


class TestWalletRecoveryManagerInit:
    """Tests for WalletRecoveryManager.__init__ (lines 94-106)."""

    def test_init_creates_directory_and_data_file(self, tmp_path: Path) -> None:
        """Test that __init__ creates directory and data file when not existing."""
        recovery_path = tmp_path / "recovery"
        manager = _make_manager(tmp_path)

        assert recovery_path.exists()
        assert (recovery_path / "wallet_recovery.json").exists()
        assert manager.data is not None

    def test_init_loads_existing_data_file(self, tmp_path: Path) -> None:
        """Test that __init__ loads existing data file without overwriting."""
        # First creation writes the file
        manager1 = _make_manager(tmp_path)
        manager1.data.last_prepared_bundle_id = "eb-existing-id"
        manager1.data.store()

        # Second creation should load the same file
        manager2 = _make_manager(tmp_path)
        assert manager2.data.last_prepared_bundle_id == "eb-existing-id"


# ---------------------------------------------------------------------------
# WalletRecoveryManager – status
# ---------------------------------------------------------------------------


class TestWalletRecoveryManagerStatus:
    """Tests for WalletRecoveryManager.status (lines 362-395)."""

    def test_status_no_bundle_returns_not_prepared(self, tmp_path: Path) -> None:
        """Test status returns NOT_PREPARED info when no bundle exists (lines 364-393)."""
        manager = _make_manager(tmp_path)

        mock_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_wallet])
        )

        with patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[EOA_ADDR, BACKUP_ADDR],
        ):
            result = manager.status()

        assert result["status"] == WalletRecoveryStatus.NOT_PREPARED
        assert result["id"] is None
        assert result["prepared"] is False
        assert result["has_swaps"] is False
        assert result["num_safes"] == 0

    def test_status_with_bundle_calls_load_bundle(self, tmp_path: Path) -> None:
        """Test that status delegates to _load_bundle when bundle_id exists (line 395)."""
        manager = _make_manager(tmp_path)
        manager.data.last_prepared_bundle_id = "eb-some-bundle"

        expected = {
            "status": WalletRecoveryStatus.PREPARED,
            "num_safes_with_new_wallet": 0,
        }
        with patch.object(manager, "_load_bundle", return_value=expected) as mock_load:
            result = manager.status()

        mock_load.assert_called_once_with(bundle_id="eb-some-bundle")
        assert result == expected


# ---------------------------------------------------------------------------
# WalletRecoveryManager – prepare_recovery
# ---------------------------------------------------------------------------


class TestPrepareRecovery:
    """Tests for WalletRecoveryManager.prepare_recovery (lines 108-190)."""

    def test_raises_when_logged_in(self, tmp_path: Path) -> None:
        """Test WalletRecoveryError when wallet_manager.password does not raise (lines 114-121)."""
        manager = _make_manager(tmp_path)
        type(manager.wallet_manager).password = PropertyMock(
            return_value="logged_in_pw"
        )  # nosec B105

        with pytest.raises(WalletRecoveryError, match="while logged in"):
            manager.prepare_recovery("new_pass")  # nosec B106

    def test_raises_on_empty_new_password(self, tmp_path: Path) -> None:
        """Test ValueError when new_password is empty (lines 123-124)."""
        manager = _make_manager(tmp_path)
        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )
        manager.wallet_manager.__iter__ = MagicMock(side_effect=lambda: iter([]))

        with pytest.raises(ValueError, match="non-empty string"):
            manager.prepare_recovery("")

    def test_raises_when_no_backup_owners(self, tmp_path: Path) -> None:
        """Test WalletRecoveryError when safe has no backup owners (lines 136-140)."""
        manager = _make_manager(tmp_path)
        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_wallet])
        )

        with patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[EOA_ADDR],  # Only master, no backup owner
        ):
            with pytest.raises(WalletRecoveryError, match="backup owner"):
                manager.prepare_recovery("new_pass")  # nosec B106

    def test_logs_warning_when_wallet_not_in_owners(self, tmp_path: Path) -> None:
        """Test that a warning is logged when wallet address is not in safe owners (lines 131-134)."""
        manager = _make_manager(tmp_path)
        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        logger_mock = MagicMock()
        manager.logger = logger_mock

        # Wallet address is "0xfff..." which is NOT in owners list
        # Owners = [BACKUP_ADDR, NEW_EOA_ADDR]: backup_owners = {BACKUP_ADDR, NEW_EOA_ADDR} len=2 >= 1
        # → warning logged (wallet.address absent), no error on backup count
        mock_wallet = _make_wallet_mock(address="0x" + "f" * 40)
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.create.return_value = (mock_new_wallet, None)

        manager.service_manager.get_all_services.return_value = ([], None)

        with patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[BACKUP_ADDR, NEW_EOA_ADDR],  # wallet.address absent → warning
        ), patch(
            "operate.wallet.wallet_recovery_manager.UserAccount"
        ), patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.KeysManager"
        ), patch.object(
            manager.data, "store"
        ), patch.object(
            manager,
            "_load_bundle",
            return_value={"status": WalletRecoveryStatus.PREPARED},
        ):
            result = manager.prepare_recovery("new_pass")  # nosec B106

        logger_mock.warning.assert_called()
        assert result is not None

    def test_returns_existing_bundle_when_has_pending_swaps(
        self, tmp_path: Path
    ) -> None:
        """Test that an existing in-progress bundle is returned (lines 142-152)."""
        manager = _make_manager(tmp_path)
        manager.data.last_prepared_bundle_id = "eb-existing-id"

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_wallet])
        )

        with patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[EOA_ADDR, BACKUP_ADDR],
        ), patch.object(
            manager,
            "status",
            return_value={"num_safes_with_new_wallet": 1},
        ), patch.object(
            manager,
            "_load_bundle",
            return_value={"status": WalletRecoveryStatus.IN_PROGRESS},
        ) as mock_load:
            result = manager.prepare_recovery("new_pass")  # nosec B106

        mock_load.assert_called_once_with(
            bundle_id="eb-existing-id", new_password="new_pass"  # nosec B106
        )
        assert result["status"] == WalletRecoveryStatus.IN_PROGRESS

    def test_creates_new_bundle_with_wallets_and_keys(self, tmp_path: Path) -> None:
        """Test that prepare_recovery creates a new bundle with wallet and key setup (lines 154-190)."""
        manager = _make_manager(tmp_path)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_wallet = _make_wallet_mock()
        mock_wallet.agent_addresses = []
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.create.return_value = (mock_new_wallet, None)

        # Service with agent_addresses → covers lines 179-183 (new agent key creation loop)
        mock_service = MagicMock()
        mock_service.service_config_id = "svc-id"
        mock_service.agent_addresses = [EOA_ADDR]
        manager.service_manager.get_all_services.return_value = ([mock_service], None)

        with patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[EOA_ADDR, BACKUP_ADDR],
        ), patch(
            "operate.wallet.wallet_recovery_manager.UserAccount"
        ), patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.KeysManager"
        ), patch.object(
            manager.data, "store"
        ), patch.object(
            manager,
            "_load_bundle",
            return_value={"status": WalletRecoveryStatus.PREPARED},
        ) as mock_load:
            result = manager.prepare_recovery("new_pass")  # nosec B106

        mock_load.assert_called_once()
        assert result["status"] == WalletRecoveryStatus.PREPARED


# ---------------------------------------------------------------------------
# WalletRecoveryManager – _load_bundle
# ---------------------------------------------------------------------------


class TestLoadBundle:
    """Tests for WalletRecoveryManager._load_bundle (lines 192-288)."""

    def test_invalid_password_raises(self, tmp_path: Path) -> None:
        """Test that a wrong password raises ValueError (lines 197-201)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"

        mock_user_account = MagicMock()
        mock_user_account.is_valid.return_value = False

        with patch(
            "operate.wallet.wallet_recovery_manager.UserAccount"
        ) as mock_ua_cls, patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager"
        ):
            mock_ua_cls.load.return_value = mock_user_account
            with pytest.raises(ValueError, match="Password"):
                manager._load_bundle(
                    bundle_id, new_password="wrong"
                )  # pylint: disable=protected-access  # nosec B106

    def test_returns_bundle_dict_prepared(self, tmp_path: Path) -> None:
        """Test _load_bundle returns dict with status PREPARED when no safes have new wallet (lines 208-288)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)

        mock_user_account = MagicMock()
        mock_user_account.is_valid.return_value = True

        mock_old_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM
        mock_new_wallet.json = {"safes": {CHAIN.value: {}}}
        mock_new_wallet.decrypt_mnemonic.return_value = ["word1", "word2"]

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        with patch(
            "operate.wallet.wallet_recovery_manager.UserAccount"
        ) as mock_ua_cls, patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            # EOA_ADDR is old wallet, NEW_EOA_ADDR is new wallet, BACKUP_ADDR is backup
            # new_wallet.address NOT in [EOA_ADDR, BACKUP_ADDR] → num_safes_with_new_wallet = 0
            return_value=[EOA_ADDR, BACKUP_ADDR],
        ):
            mock_ua_cls.load.return_value = mock_user_account
            result = manager._load_bundle(
                bundle_id, new_password="pass"
            )  # pylint: disable=protected-access  # nosec B106

        assert result["id"] == bundle_id
        assert result["num_safes"] == 1
        assert result["num_safes_with_new_wallet"] == 0
        assert result["status"] == WalletRecoveryStatus.PREPARED

    def test_returns_bundle_dict_in_progress(self, tmp_path: Path) -> None:
        """Test _load_bundle returns IN_PROGRESS when some (not all) safes have new wallet."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)

        # Two wallets: one safe with new wallet, one without → IN_PROGRESS
        mock_old_wallet1 = _make_wallet_mock(address=EOA_ADDR, safes={CHAIN: SAFE_ADDR})
        mock_old_wallet1.json = {"safes": {CHAIN.value: SAFE_ADDR}}
        other_safe = "0x" + "9" * 40
        mock_old_wallet2 = _make_wallet_mock(
            address=EOA_ADDR, safes={Chain.BASE: other_safe}
        )
        mock_old_wallet2.json = {"safes": {Chain.BASE.value: other_safe}}

        mock_user_account = MagicMock()
        mock_user_account.is_valid.return_value = True

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM
        mock_new_wallet.json = {"safes": {}}
        mock_new_wallet.decrypt_mnemonic.return_value = None

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        # First safe: new wallet in owners → num_safes_with_new_wallet = 1
        # Second safe: new wallet not in owners → num_safes_with_new_wallet stays 1
        # Total num_safes = 2 → 0 < 1 < 2 → IN_PROGRESS
        call_count: t.List[int] = [0]

        def owners_side_effect(**_kwargs: t.Any) -> t.List[str]:
            count = call_count[0]
            call_count[0] += 1
            if count == 0:
                return [EOA_ADDR, NEW_EOA_ADDR]  # new wallet present
            return [EOA_ADDR, BACKUP_ADDR]  # new wallet absent

        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet1, mock_old_wallet2])
        )

        with patch(
            "operate.wallet.wallet_recovery_manager.UserAccount"
        ) as mock_ua_cls, patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            side_effect=owners_side_effect,
        ):
            mock_ua_cls.load.return_value = mock_user_account
            result = manager._load_bundle(
                bundle_id, new_password=None
            )  # pylint: disable=protected-access

        assert result["num_safes"] == 2
        assert result["num_safes_with_new_wallet"] == 1
        assert result["status"] == WalletRecoveryStatus.IN_PROGRESS

    def test_returns_bundle_dict_completed(self, tmp_path: Path) -> None:
        """Test _load_bundle returns COMPLETED when all safes have new wallet."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)

        mock_user_account = MagicMock()
        mock_user_account.is_valid.return_value = True

        mock_old_wallet = _make_wallet_mock()
        mock_old_wallet.json = {"safes": {CHAIN.value: SAFE_ADDR}}
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM
        mock_new_wallet.json = {"safes": {}}
        mock_new_wallet.decrypt_mnemonic.return_value = None

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        with patch(
            "operate.wallet.wallet_recovery_manager.UserAccount"
        ) as mock_ua_cls, patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[EOA_ADDR, NEW_EOA_ADDR, BACKUP_ADDR],  # new wallet present
        ):
            mock_ua_cls.load.return_value = mock_user_account
            result = manager._load_bundle(
                bundle_id, new_password=None
            )  # pylint: disable=protected-access

        assert result["num_safes_with_new_wallet"] == 1
        assert result["status"] == WalletRecoveryStatus.COMPLETED


# ---------------------------------------------------------------------------
# WalletRecoveryManager – recovery_requirements
# ---------------------------------------------------------------------------


class TestRecoveryRequirements:
    """Tests for WalletRecoveryManager.recovery_requirements (lines 290-360)."""

    def test_returns_empty_when_no_bundle(self, tmp_path: Path) -> None:
        """Test that recovery_requirements returns {} when no bundle (lines 295-297)."""
        manager = _make_manager(tmp_path)
        result = manager.recovery_requirements()
        assert result == {}

    def test_returns_requirements_with_bundle(self, tmp_path: Path) -> None:
        """Test recovery_requirements computes balances and requirements (lines 299-359)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        mock_old_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            # new_wallet not in owners → pending swap
            return_value=[EOA_ADDR, BACKUP_ADDR],
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_asset_balance",
            return_value=0,
        ):
            result = manager.recovery_requirements()

        assert "balances" in result
        assert "total_requirements" in result
        assert "refill_requirements" in result
        assert "is_refill_required" in result
        assert "pending_backup_owner_swaps" in result

    def test_recovery_requirements_logs_warning_on_unexpected_backup_count(
        self, tmp_path: Path
    ) -> None:
        """Test warning logged when backup owner count != 1 (lines 320-323)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        logger_mock = MagicMock()
        manager.logger = logger_mock

        mock_old_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            # EOA_ADDR only → backup_owners = {} (len=0, not 1) → warning
            return_value=[EOA_ADDR],
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_asset_balance",
            return_value=0,
        ):
            manager.recovery_requirements()

        logger_mock.warning.assert_called()


# ---------------------------------------------------------------------------
# WalletRecoveryManager – complete_recovery
# ---------------------------------------------------------------------------


class TestCompleteRecovery:
    """Tests for WalletRecoveryManager.complete_recovery (lines 397-510)."""

    def test_raises_when_logged_in(self, tmp_path: Path) -> None:
        """Test WalletRecoveryError raised when wallet_manager.password does not raise (lines 408-415)."""
        manager = _make_manager(tmp_path)
        type(manager.wallet_manager).password = PropertyMock(
            return_value="pw"
        )  # nosec B105

        with pytest.raises(WalletRecoveryError, match="while logged in"):
            manager.complete_recovery()

    def test_raises_when_no_bundle(self, tmp_path: Path) -> None:
        """Test WalletRecoveryError when no bundle exists (lines 417-420)."""
        manager = _make_manager(tmp_path)
        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        with pytest.raises(WalletRecoveryError, match="No prepared bundle"):
            manager.complete_recovery()

    def test_raises_when_new_root_missing(self, tmp_path: Path) -> None:
        """Test RuntimeError when recovery bundle directory does not exist (lines 429-430)."""
        manager = _make_manager(tmp_path)
        manager.data.last_prepared_bundle_id = "eb-test-id"
        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        with pytest.raises(RuntimeError):
            manager.complete_recovery()

    def test_raises_when_old_root_already_exists(self, tmp_path: Path) -> None:
        """Test RuntimeError when recovery has been executed already (lines 432-435)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)
        old_root = manager.path / bundle_id / "old"
        old_root.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        with pytest.raises(RuntimeError, match="already"):
            manager.complete_recovery()

    def test_raises_on_ledger_type_mismatch(self, tmp_path: Path) -> None:
        """Test WalletRecoveryError when ledger types mismatch (lines 442-445)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        mock_old_wallet.ledger_type = LedgerType.ETHEREUM
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        # Different ledger type set for new wallets
        mock_new_wm = MagicMock()
        # Make ledger_types set contain something different via __iter__
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([]))

        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ):
            with pytest.raises(WalletRecoveryError, match="mismatch"):
                manager.complete_recovery()

    def test_raises_when_new_wallet_not_in_owners(self, tmp_path: Path) -> None:
        """Test WalletRecoveryError when new wallet is not an owner of safe (lines 456-459)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[EOA_ADDR, BACKUP_ADDR],  # new wallet NOT in owners
        ):
            with pytest.raises(WalletRecoveryError, match="Incorrect owners"):
                manager.complete_recovery()

    def test_complete_recovery_success(self, tmp_path: Path) -> None:
        """Test complete_recovery succeeds with proper setup (lines 476-510)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)
        new_keys_path = new_root / KEYS_DIR
        new_keys_path.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        mock_old_wallet.safe_chains = [CHAIN]
        mock_old_wallet.safe_nonce = 42
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        manager.data.new_agent_keys = {}
        manager.service_manager.get_all_services.return_value = ([], None)

        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            # new_wallet in owners, old wallet NOT in owners → no inconsistency
            return_value=[NEW_EOA_ADDR, BACKUP_ADDR],
        ), patch(
            "shutil.move"
        ), patch(
            "shutil.copytree"
        ), patch(
            "shutil.copy2"
        ), patch.object(
            manager.data, "store"
        ):
            manager.complete_recovery()

        assert manager.data.last_prepared_bundle_id is None

    def test_complete_recovery_success_with_files_and_services(
        self, tmp_path: Path
    ) -> None:
        """Test complete_recovery with real files and services to cover lines 486, 492, 494, 498-503."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)
        new_keys_path = new_root / KEYS_DIR
        new_keys_path.mkdir(parents=True, exist_ok=True)

        # Create user.json in root (tmp_path) → covers line 486 (root.glob loop body)
        (tmp_path / "user.json").write_text("{}", encoding="utf-8")
        # Create user.json in new_root → covers line 492 (new_root.glob loop body)
        (new_root / "user.json").write_text("{}", encoding="utf-8")
        # Create a key file in new_keys_path → covers line 494 (new_keys_path.iterdir loop body)
        (new_keys_path / "key1.json").write_text("{}", encoding="utf-8")

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        mock_old_wallet.safe_chains = [CHAIN]
        mock_old_wallet.safe_nonce = 42
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        # Service with agent_addresses → covers lines 498-503
        mock_service = MagicMock()
        mock_service.service_config_id = "svc-id"
        mock_service.agent_addresses = [EOA_ADDR]
        manager.data.new_agent_keys = {"svc-id": {EOA_ADDR: NEW_EOA_ADDR}}
        manager.service_manager.get_all_services.return_value = ([mock_service], None)

        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[NEW_EOA_ADDR, BACKUP_ADDR],
        ), patch(
            "shutil.move"
        ), patch(
            "shutil.copytree"
        ), patch(
            "shutil.copy2"
        ), patch.object(
            manager.data, "store"
        ):
            manager.complete_recovery()

        assert manager.data.last_prepared_bundle_id is None

    def test_complete_recovery_raises_when_owners_inconsistent_flag_true(
        self, tmp_path: Path
    ) -> None:
        """Test _report_issue raises WalletRecoveryError when raise_if_inconsistent_owners=True (line 406)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        # new_wallet in owners, old wallet also in owners → inconsistent (raises by default)
        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[NEW_EOA_ADDR, EOA_ADDR],  # old wallet still in owners
        ):
            with pytest.raises(WalletRecoveryError, match="Inconsistent owners"):
                manager.complete_recovery()  # default raise_if_inconsistent_owners=True

    def test_complete_recovery_len_owners_not_two_logged(self, tmp_path: Path) -> None:
        """Test _report_issue for len(owners) != 2 and len(backup_owners) != 1 (lines 465, 471) with raise=False."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)
        new_keys_path = new_root / KEYS_DIR
        new_keys_path.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        mock_old_wallet.safe_chains = [CHAIN]
        mock_old_wallet.safe_nonce = 42
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        manager.data.new_agent_keys = {}
        manager.service_manager.get_all_services.return_value = ([], None)

        logger_mock = MagicMock()
        manager.logger = logger_mock

        # 3 owners: new_wallet + EOA_ADDR (old wallet) + BACKUP_ADDR
        # len(3) != 2 → triggers line 465 (_report_issue for len != 2)
        # wallet.address (EOA_ADDR) in owners → triggers line 461 (_report_issue for inconsistent)
        # all_backup_owners = {EOA_ADDR, BACKUP_ADDR} (len=2 != 1) → triggers line 471
        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[NEW_EOA_ADDR, EOA_ADDR, BACKUP_ADDR],  # 3 owners
        ), patch(
            "shutil.move"
        ), patch(
            "shutil.copytree"
        ), patch(
            "shutil.copy2"
        ), patch.object(
            manager.data, "store"
        ):
            manager.complete_recovery(raise_if_inconsistent_owners=False)

        assert logger_mock.warning.call_count >= 3  # lines 461, 465, 471 all trigger

    def test_complete_recovery_exception_in_try_raises_runtime(
        self, tmp_path: Path
    ) -> None:
        """Test that an exception in the try block is re-raised as RuntimeError (lines 507-508)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)
        new_keys_path = new_root / KEYS_DIR
        new_keys_path.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        mock_old_wallet.safe_chains = [CHAIN]
        mock_old_wallet.safe_nonce = 42
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        manager.data.new_agent_keys = {}
        manager.service_manager.get_all_services.return_value = ([], None)

        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[NEW_EOA_ADDR, BACKUP_ADDR],
        ), patch(
            "shutil.move", side_effect=OSError("disk error")
        ):
            with pytest.raises(RuntimeError):
                manager.complete_recovery()

    def test_complete_recovery_inconsistent_owners_logged_not_raised(
        self, tmp_path: Path
    ) -> None:
        """Test _report_issue logs warning when raise_if_inconsistent_owners=False (lines 403-406, 461-463)."""
        manager = _make_manager(tmp_path)
        bundle_id = "eb-test-id"
        manager.data.last_prepared_bundle_id = bundle_id

        new_root = manager.path / bundle_id / "new"
        new_root.mkdir(parents=True, exist_ok=True)
        new_keys_path = new_root / KEYS_DIR
        new_keys_path.mkdir(parents=True, exist_ok=True)

        type(manager.wallet_manager).password = PropertyMock(
            side_effect=ValueError("not logged in")
        )

        mock_old_wallet = _make_wallet_mock()
        mock_old_wallet.safe_chains = [CHAIN]
        mock_old_wallet.safe_nonce = 42
        manager.wallet_manager.__iter__ = MagicMock(
            side_effect=lambda: iter([mock_old_wallet])
        )

        mock_new_wallet = MagicMock()
        mock_new_wallet.address = NEW_EOA_ADDR
        mock_new_wallet.ledger_type = LedgerType.ETHEREUM

        mock_new_wm = MagicMock()
        mock_new_wm.__iter__ = MagicMock(side_effect=lambda: iter([mock_new_wallet]))

        manager.data.new_agent_keys = {}
        manager.service_manager.get_all_services.return_value = ([], None)

        logger_mock = MagicMock()
        manager.logger = logger_mock

        # old wallet address is still in owners → inconsistent
        with patch(
            "operate.wallet.wallet_recovery_manager.MasterWalletManager",
            return_value=mock_new_wm,
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_default_ledger_api"
        ), patch(
            "operate.wallet.wallet_recovery_manager.get_owners",
            return_value=[NEW_EOA_ADDR, EOA_ADDR],  # old wallet still in owners
        ), patch(
            "shutil.move"
        ), patch(
            "shutil.copytree"
        ), patch(
            "shutil.copy2"
        ), patch.object(
            manager.data, "store"
        ):
            manager.complete_recovery(raise_if_inconsistent_owners=False)

        logger_mock.warning.assert_called()
