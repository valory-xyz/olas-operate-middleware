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

"""Tests for wallet.wallet_recoverer module."""

from dotenv import load_dotenv


load_dotenv()

import json
import tempfile
from pathlib import Path

import pytest
import requests
from aea.crypto.base import Crypto
from aea_ledger_ethereum import EthereumCrypto
from eth_account.signers.local import LocalAccount
from web3 import Account

from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger import get_default_rpc
from operate.operate_types import Chain, LedgerType
from operate.utils.gnosis import add_owner
from operate.wallet.master import MasterWalletManager
from operate.wallet.wallet_recoverer import OLD_OBJECTS_SUBPATH

from tests.conftest import OPERATE_TEST, RUNNING_IN_CI


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


def create_crypto(ledger_type: LedgerType, private_key: str) -> Crypto:
    """create_crypto"""
    with tempfile.NamedTemporaryFile(mode="w", delete=True) as tmp_file:
        tmp_file.write(private_key)
        tmp_file.flush()
        if ledger_type == LedgerType.ETHEREUM:
            crypto = EthereumCrypto(private_key_path=tmp_file.name)
        else:
            raise NotImplementedError()
    return crypto


class TestWalletRecovery:
    """Tests for wallet.wallet_recoverer.WalletRecoverer class."""

    def test_normal_flow(
        self,
        tmp_path: Path,
        password: str,
    ) -> None:
        """test_normal_flow"""

        # tmp_path = Path(__file__).resolve().parent
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        operate.setup()
        operate.create_user_account(password=password)
        operate.password = password
        wallet_manager = operate.wallet_manager
        wallet_manager.setup()
        wallet_manager.create(ledger_type=LedgerType.ETHEREUM)

        backup_wallet: LocalAccount = Account().create()
        wallet = wallet_manager.load(LedgerType.ETHEREUM)

        chains = [Chain.GNOSIS, Chain.BASE]
        for chain in chains:
            tenderly_add_balance(chain, backup_wallet.address)
            tenderly_add_balance(chain, wallet.address)
            wallet.create_safe(
                chain=chain,
                backup_owner=backup_wallet.address,
            )

        # Logout
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )

        # Recovery step 1
        new_password = password[::-1]
        step_1_output = operate.wallet_recoverer.recovery_step_1(
            new_password=new_password
        )

        assert step_1_output.get("id") is not None
        assert step_1_output.get("wallets") is not None
        assert len(step_1_output["wallets"]) == len(wallet_manager.json)

        for item in step_1_output["wallets"]:
            assert item.get("wallet") is not None
            assert item["wallet"].get("safes") is not None
            assert set(item["wallet"]["safes"]) == {c.value for c in chains}
            assert item.get("new_wallet") is not None
            assert item.get("new_mnemonic") is not None
            assert item["new_wallet"].get("safes") is not None
            assert set(item["new_wallet"]["safes"]) == set()

        bundle_id = step_1_output["id"]

        # Swap safe owners using backup wallet
        for item in step_1_output["wallets"]:
            crypto = create_crypto(
                ledger_type=LedgerType(item["wallet"]["ledger_type"]),
                private_key=backup_wallet.key.hex(),
            )
            for chain in chains:
                ledger_api = wallet.ledger_api(chain)
                add_owner(
                    ledger_api=ledger_api,
                    crypto=crypto,
                    safe=item["wallet"]["safes"][chain.value],
                    owner=item["new_wallet"]["address"],
                )

        # Recovery step 2
        operate.wallet_recoverer.recovery_step_2(
            password=new_password,
            bundle_id=bundle_id,
        )

        # Test that recovery was successful
        operate = OperateApp(
            home=tmp_path / OPERATE_TEST,
        )
        assert operate.user_account is not None
        assert operate.user_account.is_valid(new_password)
        operate.password = new_password
        wallet_manager = operate.wallet_manager
        old_wallet_manager = MasterWalletManager(
            path=operate.wallet_recoverer.path
            / bundle_id
            / OLD_OBJECTS_SUBPATH
            / "wallets",
            logger=operate.logger,
            password=password,
        )

        old_ledger_types = {item.ledger_type for item in old_wallet_manager}
        ledger_types = {item.ledger_type for item in wallet_manager}

        assert old_ledger_types == ledger_types

        for old_wallet in old_wallet_manager:
            wallet = next(
                (w for w in wallet_manager if w.ledger_type == old_wallet.ledger_type)
            )
            assert old_wallet.safes == wallet.safes
            assert old_wallet.safe_chains == wallet.safe_chains

        # Attempt to do a recovery with the same bundle will result in error
        with pytest.raises(
            ValueError, match=f"Recovery bundle {bundle_id} has been executed already."
        ):
            operate = OperateApp(
                home=tmp_path / OPERATE_TEST,
            )
            operate.wallet_recoverer.recovery_step_2(
                password=new_password, bundle_id=bundle_id
            )
