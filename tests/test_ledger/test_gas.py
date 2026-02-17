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
"""Test transactions in unusual gas conditions."""


from unittest.mock import patch

import pytest
from aea_ledger_ethereum import GWEI, get_base_fee_multiplier, to_wei

from operate.cli import OperateApp
from operate.operate_types import Chain, LedgerType

from tests.conftest import OnTestnet, tenderly_add_balance


@pytest.mark.integration
class TestGas(OnTestnet):
    """Test transactions in unusual gas conditions."""

    @pytest.mark.parametrize(
        ("chain", "base_fee_per_gas"),
        [
            (Chain.POLYGON, to_wei(4999, GWEI)),
        ],
    )
    def test_high_gas_price(
        self, test_operate: OperateApp, chain: Chain, base_fee_per_gas: int
    ) -> None:
        """Test that transactions are sent and confirmed even when the gas price is very high."""
        wallet_manager = test_operate.wallet_manager
        wallet, _ = wallet_manager.create(LedgerType.ETHEREUM)
        tenderly_add_balance(
            chain=chain,
            recipient=wallet.address,
        )

        with patch(
            "web3.eth.Eth.get_block",
            return_value={"baseFeePerGas": base_fee_per_gas, "number": 1},
        ):
            tx_hash = wallet.transfer(
                to=wallet.address,  # transfer to self
                amount=1,
                chain=chain,
                from_safe=False,
            )
        assert tx_hash is not None

        ledger_api = wallet.ledger_api(chain=chain)
        tx = ledger_api.api.eth.get_transaction(tx_hash)

        multiplier = get_base_fee_multiplier(base_fee_per_gas)
        assert tx.get("maxFeePerGas") == base_fee_per_gas * multiplier
