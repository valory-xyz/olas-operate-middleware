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


CHAINS = [
    Chain.ARBITRUM_ONE,
    Chain.BASE,
    Chain.CELO,
    Chain.ETHEREUM,
    Chain.GNOSIS,
    Chain.MODE,
    Chain.OPTIMISM,
    Chain.POLYGON,
    Chain.SOLANA,
]

ARBITRUM_ONE_RPC = os.environ.get("ARBITRUM_ONE_RPC", "https://arb1.arbitrum.io/rpc")
BASE_RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")
CELO_RPC = os.environ.get("CELO_RPC", "https://forno.celo.org")
ETHEREUM_RPC = os.environ.get("ETHEREUM_RPC", "https://ethereum.publicnode.com")
GNOSIS_RPC = os.environ.get("GNOSIS_RPC", "https://gnosis-rpc.publicnode.com")
MODE_RPC = os.environ.get("MODE_RPC", "https://mainnet.mode.network")
OPTIMISM_RPC = os.environ.get("OPTIMISM_RPC", "https://mainnet.optimism.io")
POLYGON_RPC = os.environ.get("POLYGON_RPC", "https://polygon-rpc.com")
SOLANA_RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")


DEFAULT_RPCS = {
    Chain.ARBITRUM_ONE: ARBITRUM_ONE_RPC,
    Chain.BASE: BASE_RPC,
    Chain.CELO: CELO_RPC,
    Chain.ETHEREUM: ETHEREUM_RPC,
    Chain.GNOSIS: GNOSIS_RPC,
    Chain.MODE: MODE_RPC,
    Chain.OPTIMISM: OPTIMISM_RPC,
    Chain.POLYGON: POLYGON_RPC,
    Chain.SOLANA: SOLANA_RPC,
}

# Base currency for each chain
CURRENCY_DENOMS = {
    Chain.ARBITRUM_ONE: "ETH",
    Chain.BASE: "ETH",
    Chain.CELO: "CELO",
    Chain.ETHEREUM: "ETH",
    Chain.GNOSIS: "xDAI",
    Chain.MODE: "ETH",
    Chain.OPTIMISM: "ETH",
    Chain.POLYGON: "POL",
    Chain.SOLANA: "SOL",
}

# Smallest denomination for each chain
CURRENCY_SMALLEST_UNITS = {
    Chain.ARBITRUM_ONE: "Wei",
    Chain.BASE: "Wei",
    Chain.CELO: "Wei",
    Chain.ETHEREUM: "Wei",
    Chain.GNOSIS: "Wei",
    Chain.MODE: "Wei",
    Chain.OPTIMISM: "Wei",
    Chain.POLYGON: "Wei",
    Chain.SOLANA: "Lamport",
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
