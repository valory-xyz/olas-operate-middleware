# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""Ledger helpers."""

import os

from operate.operate_types import Chain


ETHEREUM_PUBLIC_RPC = os.environ.get("ETHEREUM_RPC", "https://ethereum.publicnode.com")
GNOSIS_PUBLIC_RPC = os.environ.get("GNOSIS_RPC", "https://gnosis-rpc.publicnode.com")
SOLANA_PUBLIC_RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
BASE_PUBLIC_RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")
CELO_PUBLIC_RPC = os.environ.get("CELO_RPC", "https://forno.celo.org")
OPTIMISM_PUBLIC_RPC = os.environ.get("OPTIMISM_RPC", "https://mainnet.optimism.io")
MODE_PUBLIC_RPC = os.environ.get("MODE_RPC", "https://mainnet.mode.network/")

ETHEREUM_RPC = os.environ.get("ETHEREUM_RPC", "https://ethereum.publicnode.com")
GNOSIS_RPC = os.environ.get("GNOSIS_RPC", "https://rpc-gate.autonolas.tech/gnosis-rpc/")
SOLANA_RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
BASE_RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")
CELO_RPC = os.environ.get("CELO_RPC", "https://forno.celo.org")
OPTIMISM_RPC = os.environ.get("OPTIMISM_RPC", "https://mainnet.optimism.io")
MODE_RPC = os.environ.get("MODE_RPC", "https://mainnet.mode.network/")

PUBLIC_RPCS = {
    Chain.ETHEREUM: ETHEREUM_PUBLIC_RPC,
    Chain.GNOSIS: GNOSIS_PUBLIC_RPC,
    Chain.SOLANA: SOLANA_PUBLIC_RPC,
    Chain.BASE: BASE_PUBLIC_RPC,
    Chain.CELO: CELO_PUBLIC_RPC,
    Chain.OPTIMISM: OPTIMISM_PUBLIC_RPC,
    Chain.MODE: MODE_PUBLIC_RPC,
}

DEFAULT_RPCS = {
    Chain.ETHEREUM: ETHEREUM_RPC,
    Chain.GNOSIS: GNOSIS_RPC,
    Chain.SOLANA: SOLANA_RPC,
    Chain.BASE: BASE_RPC,
    Chain.CELO: CELO_RPC,
    Chain.OPTIMISM: OPTIMISM_RPC,
    Chain.MODE: MODE_RPC,
}

# Base currency for each chain
CURRENCY_DENOMS = {
    Chain.ETHEREUM: "ETH",
    Chain.GNOSIS: "xDAI",
    Chain.SOLANA: "SOL",
    Chain.BASE: "ETH",
    Chain.CELO: "CELO",
    Chain.OPTIMISM: "ETH",
    Chain.MODE: "ETH",
}

# Smallest denomination for each chain
CURRENCY_SMALLEST_UNITS = {
    Chain.ETHEREUM: "Wei",
    Chain.GNOSIS: "Wei",
    Chain.SOLANA: "Lamport",
    Chain.BASE: "Wei",
    Chain.CELO: "Wei",
    Chain.OPTIMISM: "Wei",
    Chain.MODE: "Wei",
}


def get_default_rpc(chain: Chain) -> str:
    """Get default RPC chain type."""
    return DEFAULT_RPCS.get(chain, ETHEREUM_RPC)


def get_currency_denom(chain: Chain) -> str:
    """Get currency denom by chain type."""
    return CURRENCY_DENOMS.get(chain, "ETH")


def get_currency_smallest_unit(chain: Chain) -> str:
    """Get currency denom by chain type."""
    return CURRENCY_SMALLEST_UNITS.get(chain, "Wei")
