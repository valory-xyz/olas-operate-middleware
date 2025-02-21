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
from aea_ledger_ethereum import Web3

from operate.constants import MECH_MARKETPLACE_JSON_URL
from operate.operate_types import Chain
from operate.quickstart.utils import print_section, unit_to_wei
from operate.services.protocol import EthSafeTxBuilder
from operate.services.service import Service
from operate.utils.gnosis import SafeOperation


CHAIN_TO_MARKETPLACE = {
    Chain.GNOSIS: "0xad380C51cd5297FbAE43494dD5D407A2a3260b58",
}

CHAIN_TO_NATIVE_MECH_FACTORY = {
    Chain.GNOSIS: "0x42f43be9E5E50df51b86C5c6427223ff565f40C6",
}

CHAIN_TO_TOKEN_MECH_FACTORY = {
    Chain.GNOSIS: "0x161b862568E900Dd9d8c64364F3B83a43792e50f",
}

CHAIN_TO_NVM_MECH_FACTORY = {
    Chain.GNOSIS: "0xCB26B91B0E21ADb04FFB6e5f428f41858c64936A",
}


def deploy_mech(sftxb: EthSafeTxBuilder, service: Service) -> Tuple[str, str]:
    """Deploy the Mech service."""
    print_section("Creating a new Mech On Chain")

    # Get the mech type from service config
    mech_type = service.env_variables.get("MECH_TYPE", {}).get("value", "Native")

    abi = requests.get(MECH_MARKETPLACE_JSON_URL).json()["abi"]
    chain = Chain.from_string(service.home_chain)
    mech_marketplace_address = CHAIN_TO_MARKETPLACE[chain]
    # Get factory address based on mech type
    if mech_type == "Native":
        mech_factory_address = CHAIN_TO_NATIVE_MECH_FACTORY[chain]
    elif mech_type == "Token":
        mech_factory_address = CHAIN_TO_TOKEN_MECH_FACTORY[chain]
    elif mech_type == "Nevermined":
        mech_factory_address = CHAIN_TO_NVM_MECH_FACTORY[chain]
    else:
        raise ValueError(f"Unsupported mech type: {mech_type}")

    # 0.01xDAI hardcoded for price
    # better to be configurable and part of local config
    mech_request_price = unit_to_wei(0.01)
    contract = sftxb.ledger_api.api.eth.contract(
        address=Web3.to_checksum_address(mech_marketplace_address), abi=abi
    )
    data = contract.encodeABI(
        "create",
        args=[
            service.chain_configs[service.home_chain].chain_data.token,
            Web3.to_checksum_address(mech_factory_address),
            mech_request_price.to_bytes(32, byteorder="big"),
        ],
    )
    tx_dict = {
        "to": mech_marketplace_address,
        "data": data,
        "value": 0,
        "operation": SafeOperation.CALL,
    }
    receipt = sftxb.new_tx().add(tx_dict).settle()
    event = contract.events.CreateMech().process_receipt(receipt)[0]
    mech_address = event["args"]["mech"]
    agent_id = sftxb.info(token_id=event["args"]["serviceId"])["canonical_agents"][0]
    return mech_address, agent_id
