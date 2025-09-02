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

"""
Fixtures for pytest

The conftest.py file serves as a means of providing fixtures for an entire
directory. Fixtures defined in a conftest.py can be used by any test in that
package without needing to import them (pytest will automatically discover them).

See https://docs.pytest.org/en/stable/reference/fixtures.html
"""

import json
import random
import string
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import pytest
import requests
from web3 import Web3

from operate.cli import OperateApp
from operate.constants import KEYS_DIR, ZERO_ADDRESS
from operate.keys import KeysManager
from operate.ledger import get_default_rpc  # noqa: E402
from operate.operate_types import Chain, LedgerType
from operate.wallet.master import MasterWalletManager

from tests.constants import LOGGER, OPERATE_TEST


def random_string(length: int = 16) -> str:
    """Random string"""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))  # nosec B311


def random_mnemonic(num_words: int = 12) -> str:
    """Generate a random BIP-39 mnemonic"""
    w3 = Web3()
    w3.eth.account.enable_unaudited_hdwallet_features()
    _, mnemonic = w3.eth.account.create_with_mnemonic(num_words=num_words)
    return mnemonic


def tenderly_add_balance(
    chain: Chain,
    recipient: str,
    amount: int = 1000 * (10**18),
    token: str = ZERO_ADDRESS,
) -> None:
    """tenderly_add_balance"""
    rpc = get_default_rpc(chain)
    headers = {"Content-Type": "application/json"}

    if token == ZERO_ADDRESS:
        data = {
            "jsonrpc": "2.0",
            "method": "tenderly_addBalance",
            "params": [recipient, hex(amount)],
            "id": "1",
        }
    else:
        data = {
            "jsonrpc": "2.0",
            "method": "tenderly_setErc20Balance",
            "params": [token, recipient, hex(amount)],
            "id": "1",
        }

    response = requests.post(
        url=rpc, headers=headers, data=json.dumps(data), timeout=30
    )
    response.raise_for_status()


@pytest.fixture
def password() -> str:
    """Password fixture"""
    return random_string(16)


@pytest.fixture
def temp_keys_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for keys."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@dataclass
class OperateTestEnv:
    """Operate test environment."""

    tmp_path: Path
    password: str
    operate: OperateApp
    wallet_manager: MasterWalletManager
    keys_manager: KeysManager
    backup_wallet: str
    backup_wallet2: str


@pytest.fixture
def test_env(tmp_path: Path, password: str) -> OperateTestEnv:
    """Sets up a test environment."""

    def _create_wallets(wallet_manager: MasterWalletManager) -> None:
        for ledger_type in [LedgerType.ETHEREUM]:  # TODO Add Solana when supported
            wallet_manager.create(ledger_type=ledger_type)

    def _create_safes(wallet_manager: MasterWalletManager, backup_owner: str) -> None:
        ledger_types = {wallet.ledger_type for wallet in wallet_manager}
        for chain in [Chain.GNOSIS, Chain.OPTIMISM]:
            ledger_type = chain.ledger_type
            if ledger_type in ledger_types:
                wallet = wallet_manager.load(ledger_type=ledger_type)
                tenderly_add_balance(chain, wallet.address)
                tenderly_add_balance(chain, backup_owner)
                wallet.create_safe(
                    chain=chain,
                    backup_owner=backup_owner,
                )

    operate = OperateApp(
        home=tmp_path / OPERATE_TEST,
    )
    operate.setup()
    operate.create_user_account(password=password)
    operate.password = password
    wallet_manager = operate.wallet_manager
    wallet_manager.setup()
    keys_manager = KeysManager(
        path=operate._path / KEYS_DIR,  # pylint: disable=protected-access
        logger=LOGGER,
    )
    backup_wallet = keys_manager.create()
    backup_wallet2 = keys_manager.create()

    assert backup_wallet != backup_wallet2

    _create_wallets(wallet_manager=wallet_manager)
    _create_safes(
        wallet_manager=wallet_manager,
        backup_owner=backup_wallet,
    )

    # Logout
    operate = OperateApp(
        home=tmp_path / OPERATE_TEST,
    )

    return OperateTestEnv(
        tmp_path=tmp_path,
        password=password,
        operate=operate,
        wallet_manager=wallet_manager,
        keys_manager=keys_manager,
        backup_wallet=backup_wallet,
        backup_wallet2=backup_wallet2,
    )
