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
"""Test RPC connections and transaction sending/confirmation."""

import pytest
from autonomy.chain.base import registry_contracts

from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.ledger import get_default_rpc
from operate.operate_types import Chain, LedgerType
from operate.utils.gnosis import get_asset_balance

from tests.constants import RUNNING_IN_CI


@pytest.mark.skipif(RUNNING_IN_CI, reason="Requires real mainnet funds.")
@pytest.mark.parametrize("chain", [Chain.GNOSIS, Chain.OPTIMISM, Chain.BASE])
def test_rpc_sync(chain: Chain) -> None:
    """Test the following:

    1. One transaction is sent and confirmed to change a state of a contract.
    2. The state change is verified by calling a view function.
    """

    operate = OperateApp()
    operate.password = ""  # nosec
    wallet = operate.wallet_manager.load(ledger_type=LedgerType.ETHEREUM)
    ledger_api = wallet.ledger_api(chain=chain)
    if (
        get_asset_balance(
            ledger_api=ledger_api,
            asset_address=ZERO_ADDRESS,
            address=wallet.address,
        )
        < 520000
    ):
        pytest.fail(
            f"Insufficient funds in test wallet {wallet.address} on {chain.name} chain."
        )

    if chain not in wallet.safes:
        wallet.create_safe(chain=chain)

    safe_address = wallet.safes[chain]
    if (
        get_asset_balance(
            ledger_api=ledger_api,
            asset_address=ZERO_ADDRESS,
            address=safe_address,
        )
        == 0
    ):
        pytest.fail(
            f"Insufficient funds in test safe {safe_address} on {chain.name} chain."
        )

    safe_contract = registry_contracts.gnosis_safe.get_instance(
        ledger_api=ledger_api,
        contract_address=safe_address,
    )
    initial_nonce = safe_contract.functions.nonce().call()

    print(f"Using RPC: {get_default_rpc(chain=chain)}")
    wallet.transfer(
        to=safe_address,
        amount=1,
        chain=chain,
    )
    final_nonce = safe_contract.functions.nonce().call()
    assert final_nonce == initial_nonce + 1
