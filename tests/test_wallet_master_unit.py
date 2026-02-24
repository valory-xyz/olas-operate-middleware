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

"""Unit tests for operate/wallet/master.py – no blockchain required."""

import json
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.constants import ZERO_ADDRESS
from operate.operate_types import Chain, LedgerType
from operate.wallet.master import (
    EthereumMasterWallet,
    InsufficientFundsException,
    MasterWallet,
    MasterWalletManager,
)


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

EOA_ADDR = "0x" + "a" * 40  # valid lowercase 40-hex-char Ethereum address
SAFE_ADDR = "0x" + "b" * 40
BACKUP_ADDR = "0x" + "c" * 40
TOKEN_ADDR = "0x" + "d" * 40


def _make_wallet(
    tmp_path: Path,
    safes: t.Optional[t.Dict] = None,
    safe_chains: t.Optional[t.List] = None,
) -> EthereumMasterWallet:
    """Create a minimal EthereumMasterWallet without real key files."""
    wallet = EthereumMasterWallet(
        path=tmp_path,
        address=EOA_ADDR,
        safes=safes or {},
        safe_chains=safe_chains or [],
    )
    wallet._password = "password123"  # pylint: disable=protected-access  # nosec B105
    return wallet


def _write_ethereum_json(path: Path, data: dict) -> None:
    """Write ethereum.json into *path*."""
    (path / "ethereum.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# MasterWallet base class – password property
# ---------------------------------------------------------------------------


class TestMasterWalletPassword:
    """Tests for MasterWallet.password property."""

    def test_raises_when_not_set(self, tmp_path: Path) -> None:
        """Test that accessing password raises when _password is None."""
        wallet = _make_wallet(tmp_path)
        wallet._password = None  # pylint: disable=protected-access
        with pytest.raises(ValueError, match="Password not set"):
            _ = wallet.password

    def test_getter_returns_value(self, tmp_path: Path) -> None:
        """Test that getter returns the stored password."""
        wallet = _make_wallet(tmp_path)
        assert wallet.password == "password123"  # nosec B105

    def test_setter_updates_value(self, tmp_path: Path) -> None:
        """Test that setter updates stored password."""
        wallet = _make_wallet(tmp_path)
        wallet.password = "new_password"  # nosec B105
        assert wallet.password == "new_password"  # nosec B105


# ---------------------------------------------------------------------------
# MasterWallet – ledger_api static method
# ---------------------------------------------------------------------------


class TestMasterWalletLedgerApi:
    """Tests for MasterWallet.ledger_api static method (lines 129-131)."""

    def test_no_rpc_calls_get_default_ledger_api(self, tmp_path: Path) -> None:
        """Test that calling without rpc delegates to get_default_ledger_api."""
        wallet = _make_wallet(tmp_path)
        mock_api = MagicMock()
        with patch(
            "operate.wallet.master.get_default_ledger_api", return_value=mock_api
        ) as mock_fn:
            result = wallet.ledger_api(Chain.GNOSIS)
        mock_fn.assert_called_once_with(chain=Chain.GNOSIS)
        assert result is mock_api

    def test_with_rpc_calls_make_chain_ledger_api(self, tmp_path: Path) -> None:
        """Test that calling with rpc delegates to make_chain_ledger_api."""
        wallet = _make_wallet(tmp_path)
        mock_api = MagicMock()
        with patch(
            "operate.wallet.master.make_chain_ledger_api", return_value=mock_api
        ) as mock_fn:
            result = wallet.ledger_api(Chain.GNOSIS, rpc="http://rpc.test")
        mock_fn.assert_called_once_with(chain=Chain.GNOSIS, rpc="http://rpc.test")
        assert result is mock_api


# ---------------------------------------------------------------------------
# MasterWallet – abstract / unimplemented base-class methods
# ---------------------------------------------------------------------------


class TestMasterWalletAbstractMethods:
    """Test that MasterWallet stub methods raise NotImplementedError."""

    def _base(self) -> MasterWallet:
        """Return a bare MasterWallet instance (bypassing __init__)."""
        return object.__new__(MasterWallet)

    def test_transfer_raises(self) -> None:
        """Test that base transfer() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().transfer("0x", 1, Chain.GNOSIS)

    def test_transfer_from_safe_then_eoa_raises(self) -> None:
        """Test that base transfer_from_safe_then_eoa() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().transfer_from_safe_then_eoa("0x", 1, Chain.GNOSIS)

    def test_drain_raises(self) -> None:
        """Test that base drain() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().drain("0x", Chain.GNOSIS)

    def test_new_raises(self, tmp_path: Path) -> None:
        """Test that base new() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().new("pw", tmp_path)  # type: ignore[attr-defined]

    def test_decrypt_mnemonic_raises(self) -> None:
        """Test that base decrypt_mnemonic() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().decrypt_mnemonic("pw")  # type: ignore[attr-defined]

    def test_create_safe_raises(self) -> None:
        """Test that base create_safe() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().create_safe(Chain.GNOSIS)

    def test_update_backup_owner_raises(self) -> None:
        """Test that base update_backup_owner() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().update_backup_owner(Chain.GNOSIS)

    def test_update_password_raises(self) -> None:
        """Test that base update_password() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().update_password("new")  # type: ignore[attr-defined]

    def test_is_mnemonic_valid_raises(self) -> None:
        """Test that base is_mnemonic_valid() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().is_mnemonic_valid("word1 word2")  # type: ignore[attr-defined]

    def test_update_password_with_mnemonic_raises(self) -> None:
        """Test that base update_password_with_mnemonic() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().update_password_with_mnemonic(  # type: ignore[attr-defined]
                "mnemonic", "pw"
            )

    def test_extended_json_raises(self) -> None:
        """Test that base extended_json raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            _ = self._base().extended_json  # type: ignore[attr-defined]

    def test_migrate_format_raises(self, tmp_path: Path) -> None:
        """Test that base migrate_format() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            self._base().migrate_format(tmp_path)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# MasterWallet – get_balance
# ---------------------------------------------------------------------------


class TestMasterWalletGetBalance:
    """Tests for MasterWallet.get_balance (lines 213-248)."""

    def test_from_safe_no_safe_on_chain_raises(self, tmp_path: Path) -> None:
        """Test that querying safe balance without a safe raises ValueError."""
        wallet = _make_wallet(tmp_path)
        with pytest.raises(ValueError, match="does not have a Safe"):
            wallet.get_balance(Chain.GNOSIS, from_safe=True)

    def test_from_safe_uses_safe_address(self, tmp_path: Path) -> None:
        """Test that safe balance query uses the safe address."""
        wallet = _make_wallet(tmp_path, safes={Chain.GNOSIS: SAFE_ADDR})
        mock_api = MagicMock()
        with patch(
            "operate.wallet.master.get_default_ledger_api", return_value=mock_api
        ), patch(
            "operate.wallet.master.get_asset_balance", return_value=999
        ) as mock_bal:
            result = wallet.get_balance(Chain.GNOSIS, from_safe=True)
        mock_bal.assert_called_once_with(
            ledger_api=mock_api, asset_address=ZERO_ADDRESS, address=SAFE_ADDR
        )
        assert result == 999

    def test_from_eoa_uses_eoa_address(self, tmp_path: Path) -> None:
        """Test that EOA balance query uses the EOA address."""
        wallet = _make_wallet(tmp_path)
        mock_api = MagicMock()
        with patch(
            "operate.wallet.master.get_default_ledger_api", return_value=mock_api
        ), patch(
            "operate.wallet.master.get_asset_balance", return_value=42
        ) as mock_bal:
            result = wallet.get_balance(Chain.GNOSIS, from_safe=False)
        mock_bal.assert_called_once_with(
            ledger_api=mock_api, asset_address=ZERO_ADDRESS, address=EOA_ADDR
        )
        assert result == 42

    def test_custom_rpc_uses_make_chain_ledger_api(self, tmp_path: Path) -> None:
        """Test that providing rpc uses make_chain_ledger_api."""
        wallet = _make_wallet(tmp_path, safes={Chain.GNOSIS: SAFE_ADDR})
        mock_api = MagicMock()
        with patch(
            "operate.wallet.master.make_chain_ledger_api", return_value=mock_api
        ) as mock_fn, patch("operate.wallet.master.get_asset_balance", return_value=0):
            wallet.get_balance(Chain.GNOSIS, from_safe=True, rpc="http://custom-rpc")
        mock_fn.assert_called_once_with(Chain.GNOSIS, "http://custom-rpc")


# ---------------------------------------------------------------------------
# EthereumMasterWallet – _pre_transfer_checks
# ---------------------------------------------------------------------------


class TestPreTransferChecks:
    """Tests for EthereumMasterWallet._pre_transfer_checks (lines 287-305)."""

    def test_zero_amount_raises(self, tmp_path: Path) -> None:
        """Test that amount=0 raises ValueError."""
        wallet = _make_wallet(tmp_path)
        with pytest.raises(ValueError, match="greater than zero"):
            wallet._pre_transfer_checks(  # pylint: disable=protected-access
                EOA_ADDR, 0, Chain.GNOSIS, from_safe=False
            )

    def test_negative_amount_raises(self, tmp_path: Path) -> None:
        """Test that negative amount raises ValueError."""
        wallet = _make_wallet(tmp_path)
        with pytest.raises(ValueError, match="greater than zero"):
            wallet._pre_transfer_checks(  # pylint: disable=protected-access
                EOA_ADDR, -1, Chain.GNOSIS, from_safe=False
            )

    def test_from_safe_no_safe_raises(self, tmp_path: Path) -> None:
        """Test that from_safe with missing safe raises ValueError."""
        wallet = _make_wallet(tmp_path)
        with pytest.raises(ValueError, match="does not have a Safe"):
            wallet._pre_transfer_checks(  # pylint: disable=protected-access
                EOA_ADDR, 100, Chain.GNOSIS, from_safe=True
            )

    def test_insufficient_balance_raises(self, tmp_path: Path) -> None:
        """Test that insufficient balance raises InsufficientFundsException."""
        wallet = _make_wallet(
            tmp_path,
            safes={Chain.GNOSIS: SAFE_ADDR},
            safe_chains=[Chain.GNOSIS],
        )
        with patch.object(wallet, "get_balance", return_value=50):
            with pytest.raises(InsufficientFundsException):
                wallet._pre_transfer_checks(  # pylint: disable=protected-access
                    EOA_ADDR, 100, Chain.GNOSIS, from_safe=True
                )

    def test_success_returns_checksummed_address(self, tmp_path: Path) -> None:
        """Test that valid transfer returns checksummed destination address."""
        wallet = _make_wallet(
            tmp_path,
            safes={Chain.GNOSIS: SAFE_ADDR},
            safe_chains=[Chain.GNOSIS],
        )
        with patch.object(wallet, "get_balance", return_value=500):
            result = wallet._pre_transfer_checks(  # pylint: disable=protected-access
                EOA_ADDR, 100, Chain.GNOSIS, from_safe=True
            )
        assert result.startswith("0x")
        assert len(result) == 42


# ---------------------------------------------------------------------------
# EthereumMasterWallet – _transfer_from_safe / _transfer_erc20_from_safe
# ---------------------------------------------------------------------------


class TestTransferFromSafe:
    """Tests for _transfer_from_safe and _transfer_erc20_from_safe."""

    def test_transfer_from_safe_calls_gnosis_transfer(self, tmp_path: Path) -> None:
        """Test that _transfer_from_safe delegates to transfer_from_safe gnosis util."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        wallet._crypto = MagicMock()  # pylint: disable=protected-access
        mock_api = MagicMock()
        with patch.object(
            wallet, "_pre_transfer_checks", return_value=EOA_ADDR
        ), patch.object(wallet, "ledger_api", return_value=mock_api), patch(
            "operate.wallet.master.transfer_from_safe", return_value="0xtxhash"
        ) as mock_transfer:
            result = wallet._transfer_from_safe(  # pylint: disable=protected-access
                EOA_ADDR, 100, Chain.GNOSIS
            )
        mock_transfer.assert_called_once()
        assert result == "0xtxhash"

    def test_transfer_erc20_from_safe_delegates(self, tmp_path: Path) -> None:
        """Test that _transfer_erc20_from_safe delegates to gnosis util."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        wallet._crypto = MagicMock()  # pylint: disable=protected-access
        mock_api = MagicMock()
        with patch.object(
            wallet, "_pre_transfer_checks", return_value=EOA_ADDR
        ), patch.object(wallet, "ledger_api", return_value=mock_api), patch(
            "operate.wallet.master.transfer_erc20_from_safe", return_value="0xtxerc"
        ) as mock_erc:
            result = (
                wallet._transfer_erc20_from_safe(  # pylint: disable=protected-access
                    TOKEN_ADDR, EOA_ADDR, 100, Chain.GNOSIS
                )
            )
        mock_erc.assert_called_once()
        assert result == "0xtxerc"


# ---------------------------------------------------------------------------
# EthereumMasterWallet – transfer() routing
# ---------------------------------------------------------------------------


class TestEthereumTransferRouting:
    """Tests for EthereumMasterWallet.transfer() routing (lines 467-498)."""

    def test_from_safe_native_calls_transfer_from_safe(self, tmp_path: Path) -> None:
        """Test that from_safe + ZERO_ADDRESS routes to _transfer_from_safe."""
        wallet = _make_wallet(tmp_path)
        with patch.object(wallet, "_transfer_from_safe", return_value="0xtx1") as mock:
            result = wallet.transfer(
                EOA_ADDR, 100, Chain.GNOSIS, asset=ZERO_ADDRESS, from_safe=True
            )
        mock.assert_called_once_with(
            to=EOA_ADDR, amount=100, chain=Chain.GNOSIS, rpc=None
        )
        assert result == "0xtx1"

    def test_from_safe_erc20_calls_transfer_erc20_from_safe(
        self, tmp_path: Path
    ) -> None:
        """Test that from_safe + erc20 routes to _transfer_erc20_from_safe."""
        wallet = _make_wallet(tmp_path)
        with patch.object(
            wallet, "_transfer_erc20_from_safe", return_value="0xtx2"
        ) as mock:
            result = wallet.transfer(
                EOA_ADDR, 100, Chain.GNOSIS, asset=TOKEN_ADDR, from_safe=True
            )
        mock.assert_called_once_with(
            token=TOKEN_ADDR, to=EOA_ADDR, amount=100, chain=Chain.GNOSIS, rpc=None
        )
        assert result == "0xtx2"

    def test_from_eoa_native_calls_transfer_from_eoa(self, tmp_path: Path) -> None:
        """Test that from_eoa + ZERO_ADDRESS routes to _transfer_from_eoa."""
        wallet = _make_wallet(tmp_path)
        with patch.object(wallet, "_transfer_from_eoa", return_value="0xtx3") as mock:
            result = wallet.transfer(
                EOA_ADDR, 100, Chain.GNOSIS, asset=ZERO_ADDRESS, from_safe=False
            )
        mock.assert_called_once_with(
            to=EOA_ADDR, amount=100, chain=Chain.GNOSIS, rpc=None
        )
        assert result == "0xtx3"

    def test_from_eoa_erc20_calls_transfer_erc20_from_eoa(self, tmp_path: Path) -> None:
        """Test that from_eoa + erc20 routes to _transfer_erc20_from_eoa."""
        wallet = _make_wallet(tmp_path)
        with patch.object(
            wallet, "_transfer_erc20_from_eoa", return_value="0xtx4"
        ) as mock:
            result = wallet.transfer(
                EOA_ADDR, 100, Chain.GNOSIS, asset=TOKEN_ADDR, from_safe=False
            )
        mock.assert_called_once_with(
            token=TOKEN_ADDR, to=EOA_ADDR, amount=100, chain=Chain.GNOSIS, rpc=None
        )
        assert result == "0xtx4"


# ---------------------------------------------------------------------------
# EthereumMasterWallet – transfer_from_safe_then_eoa
# ---------------------------------------------------------------------------


class TestTransferFromSafeThenEoa:
    """Tests for EthereumMasterWallet.transfer_from_safe_then_eoa (lines 513-563)."""

    def test_insufficient_combined_balance_raises(self, tmp_path: Path) -> None:
        """Test that insufficient total balance raises InsufficientFundsException."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        # Use ERC20 (no DUST added). safe=5, eoa=5, total=10 < 100.
        with patch.object(wallet, "get_balance", side_effect=[5, 5]), patch(
            "operate.wallet.master.format_asset_amount", return_value="100 TOKEN"
        ):
            with pytest.raises(InsufficientFundsException):
                wallet.transfer_from_safe_then_eoa(
                    EOA_ADDR, 100, Chain.GNOSIS, asset=TOKEN_ADDR
                )

    def test_safe_covers_full_amount(self, tmp_path: Path) -> None:
        """Test that when safe covers all, only one transfer is made from safe."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        # safe_balance=200 >= amount=100; eoa not needed for initial check
        with patch.object(wallet, "get_balance", return_value=200), patch.object(
            wallet, "transfer", return_value="0xtx_safe"
        ) as mock_transfer:
            result = wallet.transfer_from_safe_then_eoa(
                EOA_ADDR, 100, Chain.GNOSIS, asset=TOKEN_ADDR
            )
        assert "0xtx_safe" in result
        # Should have transferred from safe only
        first_call_kwargs = mock_transfer.call_args_list[0][1]
        assert first_call_kwargs["from_safe"] is True

    def test_safe_and_eoa_both_used(self, tmp_path: Path) -> None:
        """Test that when safe balance insufficient, EOA also used."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        # safe=40, eoa=80, total=120 >= 100; safe < 100 so both used
        # get_balance called: once for safe, once for eoa in initial check,
        # then again for eoa after safe transfer (3 calls total)
        with patch.object(
            wallet, "get_balance", side_effect=[40, 80, 80]
        ), patch.object(wallet, "transfer", return_value="0xtx") as mock_transfer:
            result = wallet.transfer_from_safe_then_eoa(
                EOA_ADDR, 100, Chain.GNOSIS, asset=TOKEN_ADDR
            )
        assert len(result) == 2
        # First transfer from safe, second from eoa
        assert mock_transfer.call_args_list[0][1]["from_safe"] is True
        assert mock_transfer.call_args_list[1][1]["from_safe"] is False


# ---------------------------------------------------------------------------
# EthereumMasterWallet – drain
# ---------------------------------------------------------------------------


class TestEthereumDrain:
    """Tests for EthereumMasterWallet.drain (lines 573-588)."""

    def test_drain_skips_zero_balance_assets(self, tmp_path: Path) -> None:
        """Test that drain skips assets with zero balance."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        with patch.object(wallet, "get_balance", return_value=0), patch.object(
            wallet, "transfer"
        ) as mock_transfer:
            wallet.drain("0xWithdrawal", Chain.GNOSIS)
        mock_transfer.assert_not_called()

    def test_drain_transfers_non_zero_assets(self, tmp_path: Path) -> None:
        """Test that drain calls transfer for assets with positive balance."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        # Return 100 for first asset, 0 for everything else
        balance_side_effect = [100] + [0] * 20
        with patch.object(
            wallet, "get_balance", side_effect=balance_side_effect
        ), patch.object(wallet, "transfer") as mock_transfer:
            wallet.drain("0xWithdrawal", Chain.GNOSIS)
        assert mock_transfer.call_count == 1
        call_kwargs = mock_transfer.call_args[1]
        assert call_kwargs["to"] == "0xWithdrawal"
        assert call_kwargs["amount"] == 100


# ---------------------------------------------------------------------------
# EthereumMasterWallet – new() error paths
# ---------------------------------------------------------------------------


class TestEthereumMasterWalletNew:
    """Tests for EthereumMasterWallet.new() FileExistsError paths."""

    def test_raises_when_wallet_file_exists(self, tmp_path: Path) -> None:
        """Test FileExistsError raised when ethereum.txt already exists."""
        (tmp_path / "ethereum.txt").write_text("existing", encoding="utf-8")
        with pytest.raises(FileExistsError, match="Wallet file already exists"):
            EthereumMasterWallet.new("password", tmp_path)

    def test_raises_when_mnemonic_file_exists(self, tmp_path: Path) -> None:
        """Test FileExistsError raised when mnemonic file already exists."""
        (tmp_path / "ethereum.mnemonic.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError, match="Mnemonic file already exists"):
            EthereumMasterWallet.new("password", tmp_path)


# ---------------------------------------------------------------------------
# EthereumMasterWallet – decrypt_mnemonic
# ---------------------------------------------------------------------------


class TestDecryptMnemonic:
    """Tests for EthereumMasterWallet.decrypt_mnemonic."""

    def test_returns_none_when_mnemonic_path_missing(self, tmp_path: Path) -> None:
        """Test that None is returned when the mnemonic file does not exist."""
        wallet = _make_wallet(tmp_path)
        result = wallet.decrypt_mnemonic("any_password")
        assert result is None

    def test_returns_word_list_when_mnemonic_exists(self, tmp_path: Path) -> None:
        """Test that mnemonic is decrypted and returned as a list of words."""
        wallet = _make_wallet(tmp_path)
        mock_encrypted = MagicMock()
        mock_encrypted.decrypt.return_value = b"word1 word2 word3"
        with patch(
            "operate.wallet.master.EncryptedData.load", return_value=mock_encrypted
        ), patch.object(
            type(wallet),
            "mnemonic_path",
            new_callable=lambda: property(lambda self: tmp_path / "fake.json"),
        ):
            # Create the fake mnemonic file so the exists() check passes
            (tmp_path / "fake.json").write_text("{}", encoding="utf-8")
            result = wallet.decrypt_mnemonic("password")
        assert result == ["word1", "word2", "word3"]


# ---------------------------------------------------------------------------
# EthereumMasterWallet – is_mnemonic_valid
# ---------------------------------------------------------------------------


class TestIsMnemonicValid:
    """Tests for EthereumMasterWallet.is_mnemonic_valid."""

    def test_returns_false_on_invalid_mnemonic(self, tmp_path: Path) -> None:
        """Test that invalid mnemonic returns False without raising."""
        wallet = _make_wallet(tmp_path)
        # No key file exists — will raise internally and return False
        result = wallet.is_mnemonic_valid("invalid mnemonic phrase here")
        assert result is False

    def test_returns_false_on_exception(self, tmp_path: Path) -> None:
        """Test that any exception during mnemonic check returns False."""
        wallet = _make_wallet(tmp_path)
        with patch("operate.wallet.master.Web3") as mock_web3_cls:
            mock_web3_cls.return_value.eth.account.from_mnemonic.side_effect = (
                Exception("boom")
            )
            result = wallet.is_mnemonic_valid("word " * 12)
        assert result is False


# ---------------------------------------------------------------------------
# EthereumMasterWallet – update_password_with_mnemonic
# ---------------------------------------------------------------------------


class TestUpdatePasswordWithMnemonic:
    """Tests for EthereumMasterWallet.update_password_with_mnemonic."""

    def test_invalid_mnemonic_raises_value_error(self, tmp_path: Path) -> None:
        """Test that an invalid mnemonic raises ValueError."""
        wallet = _make_wallet(tmp_path)
        with patch.object(wallet, "is_mnemonic_valid", return_value=False):
            with pytest.raises(ValueError, match="mnemonic is not valid"):
                wallet.update_password_with_mnemonic("bad mnemonic", "new_pass")


# ---------------------------------------------------------------------------
# EthereumMasterWallet – migrate_format
# ---------------------------------------------------------------------------


class TestMigrateFormat:
    """Tests for EthereumMasterWallet.migrate_format (lines 857-918)."""

    def _base_data(self) -> dict:
        return {
            "address": EOA_ADDR,
            "safes": {"gnosis": SAFE_ADDR},
            "safe_chains": ["gnosis"],
            "ledger_type": "ethereum",
        }

    def test_migrates_old_safe_key_to_safes_dict(self, tmp_path: Path) -> None:
        """Test migration of old 'safe' key into 'safes' dict."""
        data = {
            "address": EOA_ADDR,
            "safe": SAFE_ADDR,
            "safe_chains": ["gnosis"],
            "ledger_type": "ethereum",
        }
        _write_ethereum_json(tmp_path, data)
        migrated = EthereumMasterWallet.migrate_format(tmp_path)
        assert migrated is True
        result = json.loads((tmp_path / "ethereum.json").read_text())
        assert "safes" in result
        assert result["safes"]["gnosis"] == SAFE_ADDR
        assert "safe" not in result

    def test_migrates_integer_chain_in_safe_chains(self, tmp_path: Path) -> None:
        """Test migration of integer chain index to string name in safe_chains."""
        data = self._base_data()
        data["safe_chains"] = [2]  # index 2 = "gnosis" in old_to_new_chains
        _write_ethereum_json(tmp_path, data)
        migrated = EthereumMasterWallet.migrate_format(tmp_path)
        assert migrated is True
        result = json.loads((tmp_path / "ethereum.json").read_text())
        assert "gnosis" in result["safe_chains"]

    def test_migrates_integer_ledger_type(self, tmp_path: Path) -> None:
        """Test migration of integer ledger_type to string."""
        data = self._base_data()
        data["ledger_type"] = 0  # index 0 = "ethereum"
        _write_ethereum_json(tmp_path, data)
        migrated = EthereumMasterWallet.migrate_format(tmp_path)
        assert migrated is True
        result = json.loads((tmp_path / "ethereum.json").read_text())
        assert result["ledger_type"] == "ethereum"

    def test_migrates_numeric_chain_key_in_safes(self, tmp_path: Path) -> None:
        """Test migration of numeric string chain key to chain name."""
        data = self._base_data()
        data["safes"] = {"2": SAFE_ADDR}  # "2" is numeric → "gnosis"
        _write_ethereum_json(tmp_path, data)
        migrated = EthereumMasterWallet.migrate_format(tmp_path)
        assert migrated is True
        result = json.loads((tmp_path / "ethereum.json").read_text())
        assert "gnosis" in result["safes"]
        assert "2" not in result["safes"]

    def test_migrates_optimistic_to_optimism_in_safes(self, tmp_path: Path) -> None:
        """Test migration of 'optimistic' key to 'optimism' in safes."""
        data = self._base_data()
        data["safes"] = {"optimistic": SAFE_ADDR, "gnosis": SAFE_ADDR}
        _write_ethereum_json(tmp_path, data)
        migrated = EthereumMasterWallet.migrate_format(tmp_path)
        assert migrated is True
        result = json.loads((tmp_path / "ethereum.json").read_text())
        assert "optimism" in result["safes"]
        assert "optimistic" not in result["safes"]

    def test_migrates_optimistic_to_optimism_in_safe_chains(
        self, tmp_path: Path
    ) -> None:
        """Test migration of 'optimistic' entry to 'optimism' in safe_chains."""
        data = self._base_data()
        data["safe_chains"] = ["gnosis", "optimistic"]
        _write_ethereum_json(tmp_path, data)
        migrated = EthereumMasterWallet.migrate_format(tmp_path)
        assert migrated is True
        result = json.loads((tmp_path / "ethereum.json").read_text())
        assert "optimism" in result["safe_chains"]
        assert "optimistic" not in result["safe_chains"]

    def test_no_migration_needed_returns_false(self, tmp_path: Path) -> None:
        """Test that already-current format returns False (no migration)."""
        data = self._base_data()
        _write_ethereum_json(tmp_path, data)
        migrated = EthereumMasterWallet.migrate_format(tmp_path)
        assert migrated is False


# ---------------------------------------------------------------------------
# EthereumMasterWallet – load (chain key normalisation)
# ---------------------------------------------------------------------------


class TestEthereumMasterWalletLoad:
    """Tests for EthereumMasterWallet.load (line 851 – chain normalisation)."""

    def test_load_normalises_chain_keys_to_enum(self, tmp_path: Path) -> None:
        """Test that load converts string chain keys to Chain enum."""
        data = {
            "address": EOA_ADDR,
            "safes": {"gnosis": SAFE_ADDR},
            "safe_chains": ["gnosis"],
            "ledger_type": "ethereum",
            "safe_nonce": None,
        }
        _write_ethereum_json(tmp_path, data)
        wallet = EthereumMasterWallet.load(tmp_path)
        assert Chain.GNOSIS in wallet.safes
        assert wallet.safes[Chain.GNOSIS] == SAFE_ADDR


# ---------------------------------------------------------------------------
# EthereumMasterWallet – create_safe
# ---------------------------------------------------------------------------


class TestCreateSafe:
    """Tests for EthereumMasterWallet.create_safe (lines 704-727)."""

    def test_chain_already_in_safes_returns_none(self, tmp_path: Path) -> None:
        """Test that no safe is created when chain already in safes."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        mock_api = MagicMock()
        with patch.object(wallet, "ledger_api", return_value=mock_api), patch(
            "operate.wallet.master.create_gnosis_safe"
        ) as mock_create:
            result = wallet.create_safe(Chain.GNOSIS)
        mock_create.assert_not_called()
        assert result is None

    def test_new_chain_creates_safe(self, tmp_path: Path) -> None:
        """Test that a new safe is created for a new chain."""
        wallet = _make_wallet(tmp_path)
        wallet._crypto = MagicMock()  # pylint: disable=protected-access
        mock_api = MagicMock()
        with patch.object(wallet, "ledger_api", return_value=mock_api), patch(
            "operate.wallet.master.create_gnosis_safe",
            return_value=(SAFE_ADDR, 42, "0xtxhash"),
        ) as mock_create, patch.object(wallet, "store"):
            result = wallet.create_safe(Chain.GNOSIS)
        mock_create.assert_called_once()
        assert result == "0xtxhash"
        assert Chain.GNOSIS in wallet.safes
        assert wallet.safes[Chain.GNOSIS] == SAFE_ADDR

    def test_backup_owner_triggers_add_owner(self, tmp_path: Path) -> None:
        """Test that providing backup_owner calls add_owner."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        wallet._crypto = MagicMock()  # pylint: disable=protected-access
        mock_api = MagicMock()
        with patch.object(wallet, "ledger_api", return_value=mock_api), patch(
            "operate.wallet.master.add_owner"
        ) as mock_add:
            wallet.create_safe(Chain.GNOSIS, backup_owner=BACKUP_ADDR)
        mock_add.assert_called_once()
        assert mock_add.call_args[1]["owner"] == BACKUP_ADDR


# ---------------------------------------------------------------------------
# EthereumMasterWallet – update_backup_owner
# ---------------------------------------------------------------------------


class TestUpdateBackupOwner:
    """Tests for EthereumMasterWallet.update_backup_owner (lines 736-791)."""

    def _patch_ledger_api(self, wallet: EthereumMasterWallet) -> MagicMock:
        """Return a patched ledger_api mock."""
        mock_api = MagicMock()
        wallet.ledger_api = MagicMock(return_value=mock_api)  # type: ignore[method-assign]
        return mock_api

    def test_chain_not_in_safes_raises(self, tmp_path: Path) -> None:
        """Test ValueError raised when chain has no safe."""
        wallet = _make_wallet(tmp_path)
        self._patch_ledger_api(wallet)
        with pytest.raises(ValueError, match="does not have a Safe"):
            wallet.update_backup_owner(Chain.GNOSIS)

    def test_more_than_two_owners_raises(self, tmp_path: Path) -> None:
        """Test RuntimeError raised when safe has more than 2 owners."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        self._patch_ledger_api(wallet)
        with patch(
            "operate.wallet.master.get_owners",
            return_value=["0xA", "0xB", "0xC"],
        ):
            with pytest.raises(RuntimeError, match="more than 2 owners"):
                wallet.update_backup_owner(Chain.GNOSIS)

    def test_backup_owner_equal_to_safe_raises(self, tmp_path: Path) -> None:
        """Test ValueError when backup_owner == safe address."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        self._patch_ledger_api(wallet)
        with patch(
            "operate.wallet.master.get_owners",
            return_value=[wallet.address, BACKUP_ADDR],
        ):
            with pytest.raises(ValueError, match="cannot be set as the Safe backup"):
                wallet.update_backup_owner(Chain.GNOSIS, backup_owner=SAFE_ADDR)

    def test_backup_owner_equal_to_master_raises(self, tmp_path: Path) -> None:
        """Test ValueError when backup_owner == master wallet address."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        self._patch_ledger_api(wallet)
        with patch(
            "operate.wallet.master.get_owners",
            return_value=[wallet.address],
        ):
            with pytest.raises(ValueError, match="master wallet cannot be set"):
                wallet.update_backup_owner(Chain.GNOSIS, backup_owner=wallet.address)

    def test_master_not_in_owners_returns_false(self, tmp_path: Path) -> None:
        """Test False returned when master address not in owners list."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        self._patch_ledger_api(wallet)
        with patch(
            "operate.wallet.master.get_owners",
            return_value=["0x" + "e" * 40],  # master address absent
        ):
            result = wallet.update_backup_owner(Chain.GNOSIS, backup_owner=BACKUP_ADDR)
        assert result is False

    def test_same_backup_owner_returns_false(self, tmp_path: Path) -> None:
        """Test False returned when backup_owner already matches current one."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        self._patch_ledger_api(wallet)
        with patch(
            "operate.wallet.master.get_owners",
            return_value=[wallet.address, BACKUP_ADDR],
        ):
            result = wallet.update_backup_owner(Chain.GNOSIS, backup_owner=BACKUP_ADDR)
        assert result is False

    def test_add_new_backup_owner_returns_true(self, tmp_path: Path) -> None:
        """Test that adding a new backup owner calls add_owner and returns True."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        wallet._crypto = MagicMock()  # pylint: disable=protected-access
        self._patch_ledger_api(wallet)
        # Only master as owner → no existing backup
        with patch(
            "operate.wallet.master.get_owners", return_value=[wallet.address]
        ), patch("operate.wallet.master.add_owner") as mock_add:
            result = wallet.update_backup_owner(Chain.GNOSIS, backup_owner=BACKUP_ADDR)
        mock_add.assert_called_once()
        assert result is True

    def test_remove_backup_owner_returns_true(self, tmp_path: Path) -> None:
        """Test that removing backup owner calls remove_owner and returns True."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        wallet._crypto = MagicMock()  # pylint: disable=protected-access
        self._patch_ledger_api(wallet)
        with patch(
            "operate.wallet.master.get_owners",
            return_value=[wallet.address, BACKUP_ADDR],
        ), patch("operate.wallet.master.remove_owner") as mock_remove:
            result = wallet.update_backup_owner(
                Chain.GNOSIS, backup_owner=None
            )  # remove
        mock_remove.assert_called_once()
        assert result is True

    def test_swap_backup_owner_returns_true(self, tmp_path: Path) -> None:
        """Test that swapping backup owner calls swap_owner and returns True."""
        wallet = _make_wallet(
            tmp_path, safes={Chain.GNOSIS: SAFE_ADDR}, safe_chains=[Chain.GNOSIS]
        )
        wallet._crypto = MagicMock()  # pylint: disable=protected-access
        self._patch_ledger_api(wallet)
        new_backup = "0x" + "f" * 40
        with patch(
            "operate.wallet.master.get_owners",
            return_value=[wallet.address, BACKUP_ADDR],
        ), patch("operate.wallet.master.swap_owner") as mock_swap:
            result = wallet.update_backup_owner(Chain.GNOSIS, backup_owner=new_backup)
        mock_swap.assert_called_once()
        assert result is True


# ---------------------------------------------------------------------------
# MasterWalletManager
# ---------------------------------------------------------------------------


class TestMasterWalletManager:
    """Tests for MasterWalletManager (lines 926-1048)."""

    def test_password_raises_when_none(self, tmp_path: Path) -> None:
        """Test that password property raises ValueError when not set."""
        manager = MasterWalletManager(path=tmp_path)
        with pytest.raises(ValueError, match="Password not set"):
            _ = manager.password

    def test_password_getter_returns_value(self, tmp_path: Path) -> None:
        """Test that password getter returns stored value."""
        manager = MasterWalletManager(path=tmp_path, password="secret")  # nosec B106
        assert manager.password == "secret"  # nosec B105

    def test_password_setter(self, tmp_path: Path) -> None:
        """Test that password setter updates value."""
        manager = MasterWalletManager(path=tmp_path)
        manager.password = "new_secret"  # nosec B105
        assert manager.password == "new_secret"  # nosec B105

    def test_setup_creates_directory(self, tmp_path: Path) -> None:
        """Test that setup() creates the wallet directory."""
        wallet_dir = tmp_path / "wallets"
        manager = MasterWalletManager(path=wallet_dir)
        result = manager.setup()
        assert wallet_dir.exists()
        assert result is manager  # returns self

    def test_create_unsupported_ledger_raises(self, tmp_path: Path) -> None:
        """Test that create() raises ValueError for unsupported ledger type."""
        manager = MasterWalletManager(path=tmp_path, password="pass")  # nosec B106
        with pytest.raises(ValueError, match="is not supported"):
            manager.create("not_a_real_ledger_type")  # type: ignore[arg-type]

    def test_exists_returns_false_when_files_missing(self, tmp_path: Path) -> None:
        """Test that exists() returns False when wallet files are absent."""
        manager = MasterWalletManager(path=tmp_path)
        assert manager.exists(LedgerType.ETHEREUM) is False

    def test_exists_returns_true_when_files_present(self, tmp_path: Path) -> None:
        """Test that exists() returns True when both config and key files exist."""
        (tmp_path / "ethereum.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ethereum.txt").write_text("{}", encoding="utf-8")
        manager = MasterWalletManager(path=tmp_path)
        assert manager.exists(LedgerType.ETHEREUM) is True

    def test_load_unsupported_ledger_raises(self, tmp_path: Path) -> None:
        """Test that load() raises ValueError for unsupported ledger type."""
        manager = MasterWalletManager(path=tmp_path, password="pass")  # nosec B106
        with pytest.raises(ValueError, match="is not supported"):
            manager.load("not_a_real_ledger_type")  # type: ignore[arg-type]

    def test_load_sets_password_on_wallet(self, tmp_path: Path) -> None:
        """Test that load() sets the manager password on the loaded wallet."""
        test_password = "mgr_pass"  # nosec B105
        data = {
            "address": EOA_ADDR,
            "safes": {"gnosis": SAFE_ADDR},
            "safe_chains": ["gnosis"],
            "ledger_type": "ethereum",
            "safe_nonce": None,
        }
        _write_ethereum_json(tmp_path, data)
        manager = MasterWalletManager(
            path=tmp_path, password=test_password
        )  # nosec B106
        wallet = manager.load(LedgerType.ETHEREUM)
        assert wallet.password == test_password
