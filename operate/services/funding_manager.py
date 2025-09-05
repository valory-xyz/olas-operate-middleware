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

"""Funding manager"""


# pylint: disable=too-many-locals

from logging import Logger

from autonomy.chain.base import registry_contracts
from web3 import Web3

from operate.keys import KeysManager
from operate.ledger import get_currency_denom, get_default_ledger_api
from operate.ledger.profiles import OLAS, USDC, WRAPPED_NATIVE_ASSET
from operate.operate_types import Chain
from operate.services.service import Service
from operate.utils.gnosis import drain_eoa
from operate.utils.gnosis import transfer as transfer_from_safe
from operate.utils.gnosis import transfer_erc20_from_safe
from operate.wallet.master import MasterWalletManager


class FundingManager:
    """FundingManager"""

    def __init__(
        self,
        wallet_manager: MasterWalletManager,
        logger: Logger,
    ) -> None:
        """Initialize master wallet manager."""
        self.wallet_manager = wallet_manager
        self.logger = logger

    def drain_agents_eoas(
        self, service: Service, withdrawal_address: str, chain: Chain
    ) -> None:
        """Drain the funds out of the service agents EOAs."""
        service_config_id = service.service_config_id
        ledger_api = get_default_ledger_api(chain)
        self.logger.info(
            f"Draining service agents {service.name} ({service_config_id=})"
        )
        for agent_address in service.agent_addresses:
            ethereum_crypto = KeysManager().get_crypto_instance(agent_address)
            balance = ledger_api.get_balance(agent_address)
            self.logger.info(
                f"Draining {balance} (approx) {get_currency_denom(chain)} from {agent_address} (agent) to {withdrawal_address}"
            )
            drain_eoa(
                ledger_api=get_default_ledger_api(chain),
                crypto=ethereum_crypto,
                withdrawal_address=withdrawal_address,
                chain_id=chain.id,
            )
            self.logger.info(f"{service.name} signer drained")

    def drain_service_safe(  # pylint: disable=too-many-locals
        self,
        service: Service,
        withdrawal_address: str,
        chain: Chain,
    ) -> None:
        """Drain the funds out of the service safe."""
        service_config_id = service.service_config_id
        self.logger.info(f"Draining service safe {service.name} ({service_config_id=})")
        chain_config = service.chain_configs[chain.value]
        chain_data = chain_config.chain_data
        ledger_api = get_default_ledger_api(chain)
        ethereum_crypto = KeysManager().get_crypto_instance(service.agent_addresses[0])
        withdrawal_address = Web3.to_checksum_address(withdrawal_address)

        # drain ERC20 tokens from service safe
        for token_name, token_address in (
            ("OLAS", OLAS[chain]),
            (
                f"W{get_currency_denom(chain)}",
                WRAPPED_NATIVE_ASSET[chain],
            ),
            ("USDC", USDC[chain]),
        ):
            token_instance = registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=token_address,
            )
            balance = token_instance.functions.balanceOf(chain_data.multisig).call()
            if balance == 0:
                self.logger.info(
                    f"No {token_name} to drain from service safe: {chain_data.multisig}"
                )
                continue

            self.logger.info(
                f"Draining {balance} {token_name} from {chain_data.multisig} (service safe) to {withdrawal_address}"
            )
            transfer_erc20_from_safe(
                ledger_api=ledger_api,
                crypto=ethereum_crypto,
                safe=chain_data.multisig,
                token=token_address,
                to=withdrawal_address,
                amount=balance,
            )

        # drain native asset from service safe
        balance = ledger_api.get_balance(chain_data.multisig)
        if balance == 0:
            self.logger.info(
                f"No {get_currency_denom(chain)} to drain from service safe: {chain_data.multisig}"
            )
        else:
            self.logger.info(
                f"Draining {balance} {get_currency_denom(chain)} from {chain_data.multisig} (service safe) to {withdrawal_address}"
            )
            transfer_from_safe(
                ledger_api=ledger_api,
                crypto=ethereum_crypto,
                safe=chain_data.multisig,
                to=withdrawal_address,
                amount=balance,
            )

        self.logger.info(f"Service safe {service.name} drained ({service_config_id=})")
