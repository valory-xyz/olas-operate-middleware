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

import pytest

from operate.constants import KEYS_DIR, WALLETS_DIR, ZERO_ADDRESS
from operate.keys import KeysManager
from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import DUST, ERC20_TOKENS, USDC, format_asset_amount
from operate.operate_types import Chain
from operate.utils.gnosis import estimate_transfer_tx_fee, get_asset_balance
from operate.wallet.master import (
    EthereumMasterWallet,
    InsufficientFundsException,
    MasterWallet,
)

from tests.conftest import OnTestnet, tenderly_add_balance
from tests.constants import LOGGER, RUNNING_IN_CI


TX_FEE_TOLERANCE = 2


class TestMasterWallet(OnTestnet):
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
        TestMasterWallet._assert_transfer(
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
        TestMasterWallet._assert_transfer(
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
