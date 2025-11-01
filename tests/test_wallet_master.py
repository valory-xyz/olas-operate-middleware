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

"""Test for wallet.master module."""


# pylint: disable=too-many-locals

import random
import typing as t
from pathlib import Path
from unittest.mock import patch

import pytest

from operate.cli import OperateApp
from operate.constants import KEYS_DIR, WALLETS_DIR, ZERO_ADDRESS
from operate.keys import KeysManager
from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import DUST, ERC20_TOKENS, USDC, format_asset_amount
from operate.operate_types import Chain, LedgerType
from operate.utils.gnosis import estimate_transfer_tx_fee, get_asset_balance, get_owners
from operate.wallet.master import (
    EthereumMasterWallet,
    InsufficientFundsException,
    MasterWallet,
)

from tests.conftest import OnTestnet, create_wallets, tenderly_add_balance
from tests.constants import LOGGER, RUNNING_IN_CI


TX_FEE_TOLERANCE = 2


class TestMasterWalletOnTestnet(OnTestnet):
    """Tests for wallet.wallet_recoverey_manager.WalletRecoveryManager class."""

    @staticmethod
    def _assert_transfer_partial(
        chain: Chain,
        wallet: MasterWallet,
        receiver_addr: str,
        asset: str,
        from_safe: bool,
    ) -> None:
        initial_balance_sender = wallet.get_balance(
            chain=chain, asset=asset, from_safe=from_safe
        )
        amount = random.randint(  # nosec B311
            int(initial_balance_sender / 4), int(initial_balance_sender / 2)
        )
        assert amount > 0
        assert amount < initial_balance_sender
        TestMasterWalletOnTestnet._assert_transfer(
            chain=chain,
            wallet=wallet,
            receiver_addr=receiver_addr,
            asset=asset,
            amount=amount,
            from_safe=from_safe,
        )

    @staticmethod
    def _assert_transfer_full(
        chain: Chain,
        wallet: MasterWallet,
        receiver_addr: str,
        asset: str,
        from_safe: bool,
    ) -> None:
        initial_balance_sender = wallet.get_balance(
            chain=chain, asset=asset, from_safe=from_safe
        )
        amount = initial_balance_sender
        TestMasterWalletOnTestnet._assert_transfer(
            chain=chain,
            wallet=wallet,
            receiver_addr=receiver_addr,
            asset=asset,
            amount=amount,
            from_safe=from_safe,
        )

    @staticmethod
    def _assert_transfer(
        chain: Chain,
        wallet: MasterWallet,
        receiver_addr: str,
        asset: str,
        amount: int,
        from_safe: bool,
    ) -> None:
        ledger_api = get_default_ledger_api(chain)
        tx_fee = estimate_transfer_tx_fee(chain, wallet.address, receiver_addr)
        initial_balance_receiver = get_asset_balance(ledger_api, asset, receiver_addr)
        initial_balance_sender = wallet.get_balance(
            chain=chain, asset=asset, from_safe=from_safe
        )
        wallet.transfer(
            to=receiver_addr,
            amount=amount,
            chain=chain,
            asset=asset,
            from_safe=from_safe,
        )
        final_balance_sender = wallet.get_balance(
            chain=chain, asset=asset, from_safe=from_safe
        )
        final_balance_receiver = get_asset_balance(ledger_api, asset, receiver_addr)
        if not from_safe and asset == ZERO_ADDRESS:  # Transfer native from EOA
            if amount == initial_balance_sender:  # Drain native from EOA
                assert 0 <= final_balance_sender <= TX_FEE_TOLERANCE * tx_fee
                assert (
                    initial_balance_receiver + amount - TX_FEE_TOLERANCE * tx_fee
                    <= final_balance_receiver
                    <= initial_balance_receiver + amount
                )
            else:
                assert (
                    min(initial_balance_sender - amount - TX_FEE_TOLERANCE * tx_fee, 0)
                    <= final_balance_sender
                    <= initial_balance_sender - amount
                )
                assert final_balance_receiver == initial_balance_receiver + amount
        else:
            assert final_balance_sender == initial_balance_sender - amount
            assert final_balance_receiver == initial_balance_receiver + amount

    @pytest.mark.parametrize(
        "chain",
        [
            pytest.param(
                Chain.BASE,
                marks=pytest.mark.skipif(RUNNING_IN_CI, reason="Skipped on CI"),
            ),
            pytest.param(
                Chain.ETHEREUM,
                marks=pytest.mark.skipif(RUNNING_IN_CI, reason="Skipped on CI"),
            ),
            Chain.GNOSIS,
            pytest.param(
                Chain.OPTIMISM,
                marks=pytest.mark.skipif(RUNNING_IN_CI, reason="Skipped on CI"),
            ),
        ],
    )
    @pytest.mark.parametrize(
        "wallet_class",
        [EthereumMasterWallet],
    )
    def test_transfer(
        self,
        tmp_path: Path,
        password: str,
        chain: Chain,
        wallet_class: t.Type[MasterWallet],
    ) -> None:
        """test_transfer"""

        keys_manager = KeysManager(
            path=tmp_path / KEYS_DIR,  # pylint: disable=protected-access
            logger=LOGGER,
        )
        receiver_addr = keys_manager.create()

        wallet, _ = wallet_class.new(password=password, path=tmp_path / WALLETS_DIR)
        eoa_address = wallet.address

        topup = int(10e18)
        tenderly_add_balance(chain, eoa_address, topup, ZERO_ADDRESS)
        wallet.create_safe(chain, receiver_addr)
        safe_address = wallet.safes[chain]
        tenderly_add_balance(chain, safe_address, topup, ZERO_ADDRESS)

        tokens = [token[chain] for token in ERC20_TOKENS.values()]
        for token in tokens:
            topup = int(10e18)
            if token == USDC[chain]:
                topup = int(10e6)
            tenderly_add_balance(chain, eoa_address, topup, token)
            tenderly_add_balance(chain, safe_address, topup, token)

        assets = [token[chain] for token in ERC20_TOKENS.values()] + [ZERO_ADDRESS]

        # Test 1 - Remove partial amount of all assets
        for asset in assets:
            for from_safe in (True, False):
                self._assert_transfer_partial(
                    chain=chain,
                    wallet=wallet,
                    receiver_addr=receiver_addr,
                    asset=asset,
                    from_safe=from_safe,
                )

        # Test 2 - Remove all amount of all assets
        for asset in assets:
            for from_safe in (True, False):
                self._assert_transfer_full(
                    chain=chain,
                    wallet=wallet,
                    receiver_addr=receiver_addr,
                    asset=asset,
                    from_safe=from_safe,
                )

    @pytest.mark.parametrize(
        "chain",
        [
            pytest.param(
                Chain.BASE,
                marks=pytest.mark.skipif(RUNNING_IN_CI, reason="Skipped on CI"),
            ),
            pytest.param(
                Chain.ETHEREUM,
                marks=pytest.mark.skipif(RUNNING_IN_CI, reason="Skipped on CI"),
            ),
            Chain.GNOSIS,
            pytest.param(
                Chain.OPTIMISM,
                marks=pytest.mark.skipif(RUNNING_IN_CI, reason="Skipped on CI"),
            ),
        ],
    )
    @pytest.mark.parametrize(
        "wallet_class",
        [EthereumMasterWallet],
    )
    def test_transfer_error_funds(
        self,
        tmp_path: Path,
        password: str,
        chain: Chain,
        wallet_class: t.Type[MasterWallet],
    ) -> None:
        """test_transfer_error_funds"""

        keys_manager = KeysManager(
            path=tmp_path / KEYS_DIR,  # pylint: disable=protected-access
            logger=LOGGER,
        )
        receiver_addr = keys_manager.create()

        wallet, _ = wallet_class.new(password=password, path=tmp_path / WALLETS_DIR)
        eoa_address = wallet.address

        topup = int(10e18)
        tenderly_add_balance(chain, eoa_address, topup, ZERO_ADDRESS)
        wallet.create_safe(chain, receiver_addr)
        safe_address = wallet.safes[chain]
        tenderly_add_balance(chain, safe_address, topup, ZERO_ADDRESS)

        tokens = [token[chain] for token in ERC20_TOKENS.values()]
        for token in tokens:
            topup = int(10e18)
            if token == USDC[chain]:
                topup = int(10e6)
            tenderly_add_balance(chain, eoa_address, topup, token)
            tenderly_add_balance(chain, safe_address, topup, token)

        assets = [token[chain] for token in ERC20_TOKENS.values()] + [ZERO_ADDRESS]

        for asset in assets:
            for from_safe in (True, False):
                balance = wallet.get_balance(
                    chain=chain, asset=asset, from_safe=from_safe
                )
                assert balance > 0
                amount = balance + 1  # Raises exception
                if asset == ZERO_ADDRESS and not from_safe:
                    amount += DUST[chain]

                with pytest.raises(
                    InsufficientFundsException,
                    match=f"^Cannot transfer {format_asset_amount(chain, asset, amount)}.*",
                ):
                    wallet.transfer(
                        to=receiver_addr,
                        amount=amount,
                        chain=chain,
                        asset=asset,
                        from_safe=from_safe,
                    )

    @pytest.mark.parametrize(
        "wallet_class",
        [EthereumMasterWallet],
    )
    def test_transfer_error_safes(
        self,
        tmp_path: Path,
        password: str,
        wallet_class: t.Type[MasterWallet],
    ) -> None:
        """test_transfer_error_safes"""

        keys_manager = KeysManager(
            path=tmp_path / KEYS_DIR,  # pylint: disable=protected-access
            logger=LOGGER,
        )
        receiver_addr = keys_manager.create()

        wallet, _ = wallet_class.new(password=password, path=tmp_path / WALLETS_DIR)

        chain = Chain.POLYGON  # Chain not funded
        assets = [token[chain] for token in ERC20_TOKENS.values()] + [ZERO_ADDRESS]
        for asset in assets:
            assert wallet.get_balance(chain=chain, asset=asset, from_safe=False) == 0
            with pytest.raises(
                ValueError,
                match=f"Wallet does not have a Safe on chain {chain}.",
            ):
                wallet.get_balance(chain=chain, asset=asset, from_safe=True)

            amount = DUST[chain] + 1

            with pytest.raises(
                InsufficientFundsException,
                match=f"^Cannot transfer {format_asset_amount(chain, asset, amount)}.*",
            ):
                wallet.transfer(
                    to=receiver_addr,
                    amount=amount,
                    chain=chain,
                    asset=asset,
                    from_safe=False,
                )

            with pytest.raises(
                ValueError,
                match=f"Wallet does not have a Safe on chain {chain}.",
            ):
                wallet.transfer(
                    to=receiver_addr,
                    amount=amount,
                    chain=chain,
                    asset=asset,
                    from_safe=True,
                )

    def test_create_gnosis_safe(self, test_operate: OperateApp) -> None:
        """Test creating gnosis safe."""
        # Setup
        wallet_manager = test_operate.wallet_manager
        wallet, _ = wallet_manager.create(LedgerType.ETHEREUM)
        chain1 = Chain.GNOSIS
        chain2 = Chain.OPTIMISM
        backup_owner = KeysManager().create()
        for chain in (chain1, chain2):
            assert chain not in wallet.safes
            assert chain not in wallet.safe_chains
            tenderly_add_balance(
                chain=chain,
                recipient=wallet.address,
            )

        # Try creating the first safe but fail
        with patch(
            "operate.wallet.master.TxSettler.transact",
            side_effect=Exception("Simulated failure"),
        ):
            assert wallet.create_safe(chain=chain1, backup_owner=backup_owner) is None

        assert chain1 not in wallet.safes
        assert chain1 not in wallet.safe_chains
        assert wallet.safe_nonce is not None
        created_nonce = wallet.safe_nonce

        # Create the first safe
        tx_hash = wallet.create_safe(
            chain=chain1,
            backup_owner=backup_owner,
        )
        assert tx_hash is not None
        assert chain1 in wallet.safes
        assert chain1 in wallet.safe_chains
        assert created_nonce is not None
        assert set(
            get_owners(
                ledger_api=wallet.ledger_api(chain1),
                safe=wallet.safes[chain1],
            )
        ) == {wallet.address, backup_owner}

        # Try creating safe on another chain but fail
        with patch(
            "operate.wallet.master.TxSettler.transact",
            side_effect=Exception("Simulated failure"),
        ):
            assert wallet.create_safe(chain=chain2, backup_owner=backup_owner) is None

        assert chain2 not in wallet.safes
        assert chain2 not in wallet.safe_chains
        assert wallet.safe_nonce == created_nonce

        # Create safe on another chain, but fail while adding backup owner
        with patch(
            "operate.wallet.master.add_owner",
            side_effect=Exception("Simulated failure"),
        ):
            assert (
                wallet.create_safe(chain=chain2, backup_owner=backup_owner) is not None
            )

        assert wallet.safe_nonce == created_nonce
        assert wallet.safes[chain1] == wallet.safes[chain2]  # Same safe deployed
        for chain in (chain1, chain2):
            assert chain in wallet.safes
            assert chain in wallet.safe_chains

        assert backup_owner not in get_owners(
            ledger_api=wallet.ledger_api(chain2),
            safe=wallet.safes[chain2],
        )

        # Again try creating safe on another chain and this time backup owner should be added
        wallet.create_safe(chain=chain2, backup_owner=backup_owner)
        for chain in (chain1, chain2):
            assert chain in wallet.safes
            assert chain in wallet.safe_chains
            assert wallet.safes[chain1] == wallet.safes[chain2]  # Same safe deployed
            assert set(
                get_owners(
                    ledger_api=wallet.ledger_api(chain),
                    safe=wallet.safes[chain],
                )
            ) == {wallet.address, backup_owner}


class TestMasterWallet:
    """Tests for wallet.wallet_recoverey_manager.WalletRecoveryManager class."""

    def test_decrypt_mnemonic(
        self,
        test_operate: OperateApp,
    ) -> None:
        """test_decrypt_mnemonic"""
        password = test_operate.password
        wallet_manager = test_operate.wallet_manager
        mnemonics = create_wallets(wallet_manager)

        assert len(wallet_manager.json) > 0
        for wallet_json in wallet_manager.json:
            ledger_type = LedgerType(wallet_json["ledger_type"])
            wallet = wallet_manager.load(ledger_type)
            decrypted_mnemonic = wallet.decrypt_mnemonic(password)
            assert mnemonics[ledger_type] == decrypted_mnemonic
