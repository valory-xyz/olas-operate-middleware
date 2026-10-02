# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Fork-backed integration tests for the funding run.

Relay fills and Relay status happen off-fork, so cross-chain legs and
Relay-routed swaps cannot complete on a fork, and the ERC-4337 +
Circle Paymaster leg needs a real bundler. Those are verified by a manual
mainnet run (see the PR). What runs here is every on-chain step Pearl
itself signs: the same-chain run through Safe creation and transfer, and
the self-sponsored EIP-7702 clearing transaction on a paymaster chain.
"""

import logging
import time

import pytest
from web3 import Web3

from operate.cli import OperateApp
from operate.constants import ZERO_ADDRESS
from operate.funding_run.models import FundingRunStatus, FundingStepStatus
from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS, EIP7702_DELEGATE
from operate.operate_types import Chain, LedgerType
from operate.utils.gnosis import get_asset_balance
from operate.wallet.gas_abstraction import GasAbstractedSender

from tests.conftest import OnFork, fork_add_balance


@pytest.mark.integration
class TestFundingRunOnFork(OnFork):
    """Funding run steps Pearl signs itself, on forks."""

    def test_same_chain_native_deposit_creates_safe_and_transfers(
        self, test_operate: OperateApp
    ) -> None:
        """Gnosis xDAI to the Gnosis Pearl Wallet: receive, Safe, transfer."""
        chain = Chain.GNOSIS
        test_operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        wallet = test_operate.wallet_manager.load(LedgerType.ETHEREUM)
        backup_owner = test_operate.keys_manager.create()
        target = 10**18
        manager = test_operate.funding_run_manager

        run = manager.create_run(
            mode="deposit",
            source_chain=chain.value,
            source_token=ZERO_ADDRESS,
            destination_chain=chain.value,
            deposit_amounts={ZERO_ADDRESS: str(target)},
            backup_owner=backup_owner,
        )
        assert run.status == FundingRunStatus.AWAITING_DEPOSIT
        assert [s.id for s in run.steps] == ["receive", "safe"]

        fork_add_balance(chain, wallet.address, int(run.required_amount))
        for _ in range(10):
            manager.tick()
            run = manager.load(run.id)
            if run.status in (FundingRunStatus.COMPLETED, FundingRunStatus.FAILED):
                break
            time.sleep(1)

        assert run.status == FundingRunStatus.COMPLETED, run.error
        assert all(s.status == FundingStepStatus.DONE for s in run.steps)
        wallet = test_operate.wallet_manager.load(LedgerType.ETHEREUM)
        ledger_api = get_default_ledger_api(chain)
        safe_balance = get_asset_balance(ledger_api, ZERO_ADDRESS, wallet.safes[chain])
        eoa_balance = get_asset_balance(ledger_api, ZERO_ADDRESS, wallet.address)
        assert safe_balance >= target
        assert eoa_balance <= DEFAULT_EOA_TOPUPS[chain][ZERO_ADDRESS]

    def test_clear_delegation_leaves_no_code(self, test_operate: OperateApp) -> None:
        """The self-sponsored type-4 clearing tx is accepted by a real node."""
        chain = Chain.BASE
        test_operate.wallet_manager.create(ledger_type=LedgerType.ETHEREUM)
        wallet = test_operate.wallet_manager.load(LedgerType.ETHEREUM)
        fork_add_balance(chain, wallet.address, 10**17)
        w3 = get_default_ledger_api(chain).api
        account = wallet.crypto.entity

        # Delegate first, as the gas-abstracted source leg would.
        nonce = w3.eth.get_transaction_count(wallet.address)
        delegate_tx = {
            "chainId": chain.id,
            "nonce": nonce,
            "to": wallet.address,
            "value": 0,
            "data": "0x",
            "gas": 100_000,
            "maxFeePerGas": w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.eth.gas_price,
            "authorizationList": [
                account.sign_authorization(
                    {
                        "chainId": chain.id,
                        "address": EIP7702_DELEGATE,
                        "nonce": nonce + 1,
                    }
                )
            ],
        }
        tx_hash = w3.eth.send_raw_transaction(
            account.sign_transaction(delegate_tx).raw_transaction
        )
        w3.eth.wait_for_transaction_receipt(tx_hash)
        sender = GasAbstractedSender(wallet, logger=logging.getLogger(__name__))
        assert sender.delegation_of(chain) == Web3.to_checksum_address(EIP7702_DELEGATE)

        wallet.clear_delegation(chain)

        assert bytes(w3.eth.get_code(wallet.address)) == b""
        assert sender.delegation_of(chain) is None
