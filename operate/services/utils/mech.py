# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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
"""Utilities for the Mech service."""


from typing import Tuple

import requests
import web3
from aea_ledger_ethereum import Web3

from operate.constants import MECH_AGENT_FACTORY_JSON_URL
from operate.operate_types import Chain
from operate.services.protocol import EthSafeTxBuilder
from operate.services.service import Service
from operate.utils.common import print_section, unit_to_wei
from operate.utils.gnosis import SafeOperation


CHAIN_TO_MARKETPLACE = {
    Chain.GNOSIS.value: "0x4554fE75c1f5576c1d7F765B2A036c199Adae329",
}

CHAIN_TO_AGENT_FACTORY = {
    Chain.GNOSIS.value: "0x6D8CbEbCAD7397c63347D44448147Db05E7d17B0",
}


def deploy_mech(sftxb: EthSafeTxBuilder, service: Service) -> Tuple[str, str]:
    """Deploy the Mech service."""
    print_section("Creating a new Mech On Chain")
    abi = requests.get(MECH_AGENT_FACTORY_JSON_URL).json()["abi"]
    instance = web3.Web3()

    mech_marketplace_address = CHAIN_TO_MARKETPLACE[service.home_chain]
    # 0.01xDAI hardcoded for price
    # better to be configurable and part of local config
    mech_request_price = unit_to_wei(0.01)
    contract = instance.eth.contract(
        address=Web3.to_checksum_address(mech_marketplace_address), abi=abi
    )
    data = contract.encodeABI(
        "create",
        args=[
            service.chain_configs[service.home_chain].chain_data.multisig,
            bytes.fromhex(
                service.env_variables["METADATA_HASH"]["value"].replace("f01701220", "")
            ),
            mech_request_price,
            mech_marketplace_address,
        ],
    )
    tx_dict = {
        "to": CHAIN_TO_AGENT_FACTORY[service.home_chain],
        "data": data,
        "value": 0,
        "operation": SafeOperation.CALL,
    }
    receipt = sftxb.new_tx().add(tx_dict).settle()
    event = contract.events.CreateMech().process_receipt(receipt)[0]
    mech_address, agent_id = event["args"]["mech"], event["args"]["agentId"]
    print(f"Mech address: {mech_address}")
    print(f"Agent ID: {agent_id}")

    return mech_address, agent_id
