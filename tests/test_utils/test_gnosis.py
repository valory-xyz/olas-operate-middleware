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

"""Tests for operate/utils/gnosis.py."""

import pytest

from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import DUST
from operate.operate_types import Chain, LedgerType
from operate.utils.gnosis import drain_eoa

from tests.conftest import OnTestnet, tenderly_add_balance
from tests.constants import CHAINS_TO_TEST


class TestGnosisUtils(OnTestnet):
    """Tests for Gnosis utils."""

    @pytest.mark.parametrize("chain", CHAINS_TO_TEST)
    def test_drain_eoa(self, test_operate: OperateApp, chain: Chain) -> None:
        """Test draining an EOA wallet."""
        test_operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        wallet = test_operate.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)

        test_balance = 10**18
        ledger_api = wallet.ledger_api(chain)
        tenderly_add_balance(chain, wallet.address, test_balance)
        assert test_balance > DUST[chain]
        assert ledger_api.get_balance(wallet.address) == test_balance

        assert (
            drain_eoa(
                ledger_api=ledger_api,
                crypto=wallet.crypto,
                withdrawal_address=ZERO_ADDRESS,
                chain_id=chain.id,
            )
            is not None
        )
        assert ledger_api.get_balance(wallet.address) <= DUST[chain]
