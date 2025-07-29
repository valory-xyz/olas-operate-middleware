# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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
"""Common utilities."""


import getpass
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP
from pathlib import Path
from typing import Dict, Optional, Union, get_args, get_origin

import requests
from halo import Halo  # type: ignore[import]  # pylint: disable=import-error

from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import OLAS, USDC
from operate.operate_types import Chain
from operate.resource import LocalResource, deserialize


def print_box(text: str, margin: int = 1, character: str = "=") -> None:
    """Print text centered within a box."""

    lines = text.split("\n")
    text_length = max(len(line) for line in lines)
    length = text_length + 2 * margin

    border = character * length
    margin_str = " " * margin

    print()
    print(border)
    print(f"{margin_str}{text}{margin_str}")
    print(border)
    print()


def print_title(text: str) -> None:
    """Print title."""
    print_box(text, 4, "=")


def print_section(text: str) -> None:
    """Print section."""
    print_box(text, 1, "-")


def unit_to_wei(unit: float) -> int:
    """Convert unit to Wei."""
    return int(unit * 1e18)


CHAIN_TO_METADATA = {
    "gnosis": {
        "name": "Gnosis",
        "gasFundReq": unit_to_wei(0.5),  # fund for master EOA
        "staking_bonding_token": OLAS[Chain.GNOSIS],
        "token_data": {
            ZERO_ADDRESS: {
                "symbol": "xDAI",
                "decimals": 18,
            },
            USDC[Chain.GNOSIS]: {
                "symbol": "USDC",
                "decimals": 6,
            },
            OLAS[Chain.GNOSIS]: {
                "symbol": "OLAS",
                "decimals": 18,
            },
        },
        "gasParams": {
            # this means default values will be used
            "MAX_PRIORITY_FEE_PER_GAS": "",
            "MAX_FEE_PER_GAS": "",
        },
    },
    "mode": {
        "name": "Mode",
        "gasFundReq": unit_to_wei(0.005),  # fund for master EOA
        "staking_bonding_token": OLAS[Chain.MODE],
        "token_data": {
            ZERO_ADDRESS: {
                "symbol": "ETH",
                "decimals": 18,
            },
            USDC[Chain.MODE]: {
                "symbol": "USDC",
                "decimals": 6,
            },
            OLAS[Chain.MODE]: {
                "symbol": "OLAS",
                "decimals": 18,
            },
        },
        "gasParams": {
            # this means default values will be used
            "MAX_PRIORITY_FEE_PER_GAS": "",
            "MAX_FEE_PER_GAS": "",
        },
    },
    "optimism": {
        "name": "Optimism",
        "gasFundReq": unit_to_wei(0.005),  # fund for master EOA
        "staking_bonding_token": OLAS[Chain.OPTIMISM],
        "token_data": {
            ZERO_ADDRESS: {
                "symbol": "ETH",
                "decimals": 18,
            },
            USDC[Chain.OPTIMISM]: {
                "symbol": "USDC",
                "decimals": 6,
            },
            OLAS[Chain.OPTIMISM]: {
                "symbol": "OLAS",
                "decimals": 18,
            },
        },
        "gasParams": {
            # this means default values will be used
            "MAX_PRIORITY_FEE_PER_GAS": "",
            "MAX_FEE_PER_GAS": "",
        },
    },
    "base": {
        "name": "Base",
        "gasFundReq": unit_to_wei(0.005),  # fund for master EOA
        "staking_bonding_token": OLAS[Chain.BASE],
        "token_data": {
            ZERO_ADDRESS: {
                "symbol": "ETH",
                "decimals": 18,
            },
            USDC[Chain.BASE]: {
                "symbol": "USDC",
                "decimals": 6,
            },
            OLAS[Chain.BASE]: {
                "symbol": "OLAS",
                "decimals": 18,
            },
        },
        "gasParams": {
            # this means default values will be used
            "MAX_PRIORITY_FEE_PER_GAS": "",
            "MAX_FEE_PER_GAS": "",
        },
    },
}


def wei_to_unit(wei: int, chain: str, token_address: str = ZERO_ADDRESS) -> Decimal:
    """Convert Wei to unit."""
    unit: Decimal = (
        Decimal(str(wei))
        / 10 ** CHAIN_TO_METADATA[chain]["token_data"][token_address]["decimals"]
    )
    return unit.quantize(Decimal("0.000001"), rounding=ROUND_UP)


def wei_to_token(wei: int, chain: str, token_address: str = ZERO_ADDRESS) -> str:
    """Convert Wei to token."""
    return f"{wei_to_unit(wei, chain, token_address)} {CHAIN_TO_METADATA[chain]['token_data'][token_address]['symbol']}"


def ask_yes_or_no(question: str) -> bool:
    """Ask a yes/no question."""
    if os.environ.get("ATTENDED", "true").lower() != "true":
        return True
    while True:
        response = input(f"{question} (yes/no): ").strip().lower()
        if response.lower() in ("yes", "y"):
            return True
        if response.lower() in ("no", "n"):
            return False


def ask_or_get_from_env(
    prompt: str, is_pass: bool, env_var_name: str, raise_if_missing: bool = True
) -> str:
    """Get user input either interactively or from environment variables."""
    if os.getenv("ATTENDED", "true").lower() == "true":
        if is_pass:
            return getpass.getpass(prompt).strip()
        return input(prompt).strip()
    if env_var_name in os.environ:
        return os.environ[env_var_name].strip()
    if raise_if_missing:
        raise ValueError(f"{env_var_name} env var required in unattended mode")
    return ""


def check_rpc(rpc_url: Optional[str] = None) -> bool:
    """Check RPC."""
    if rpc_url is None:
        return False

    spinner = Halo(text="Checking RPC...", spinner="dots")
    spinner.start()

    rpc_data = {
        "jsonrpc": "2.0",
        "method": "eth_newFilter",
        "params": ["invalid"],
        "id": 1,
    }

    try:
        response = requests.post(
            rpc_url, json=rpc_data, headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        rpc_response = response.json()
    except (requests.exceptions.RequestException, ValueError, TypeError) as e:
        spinner.fail(f"Error: Failed to send RPC request: {e}")
        return False

    rpc_error_message = (
        rpc_response.get("error", {})
        .get("message", "exception processing rpc response")
        .lower()
    )

    if rpc_error_message == "exception processing rpc response":
        print(
            "Error: The received rpc response is malformed. Please verify the RPC address and/or rpc behavior."
        )
        print("  Received response:")
        print("  ", rpc_response)
        print("")
        spinner.fail("Terminating script.")
    elif rpc_error_message == "out of requests":
        print("Error: The provided rpc is out of requests.")
        spinner.fail("Terminating script.")
    elif (
        rpc_error_message == "the method eth_newfilter does not exist/is not available"
    ):
        print("Error: The provided RPC does not support 'eth_newFilter'.")
        spinner.fail("Terminating script.")
    elif "invalid" in rpc_error_message or "params" in rpc_error_message:
        spinner.succeed("RPC checks passed.")
        return True
    else:
        print("Error: Unknown rpc error.")
        print("  Received response:")
        print("  ", rpc_response)
        print("")
        spinner.fail("Terminating script.")

    return False


@dataclass
class QuickstartConfig(LocalResource):
    """Local configuration."""

    path: Path
    rpc: Optional[Dict[str, str]] = None
    staking_program_id: Optional[str] = None
    principal_chain: Optional[str] = None
    user_provided_args: Optional[Dict[str, str]] = None

    @classmethod
    def from_json(cls, obj: Dict) -> "LocalResource":
        """Load LocalResource from json."""
        kwargs = {}
        for pname, ptype in cls.__annotations__.items():
            if pname.startswith("_"):
                continue

            # allow for optional types
            is_optional_type = get_origin(ptype) is Union and type(None) in get_args(
                ptype
            )
            value = obj.get(pname, None)
            if is_optional_type and value is None:
                continue

            kwargs[pname] = deserialize(obj=obj[pname], otype=ptype)
        return cls(**kwargs)
