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

"""Constants for tests."""

import os
from pathlib import Path

from operate.ledger import DEFAULT_RPCS
from operate.operate_types import Chain


ROOT_PATH = Path(__file__).resolve().parent
OPERATE_TEST = ".operate_test"
RUNNING_IN_CI = (
    os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    or os.getenv("CI", "").lower() == "true"
)

ARBITRUM_ONE_TESTNET_RPC = os.environ.get(
    "ARBITRUM_ONE_TESTNET_RPC", DEFAULT_RPCS[Chain.ARBITRUM_ONE]
)
BASE_TESTNET_RPC = os.environ.get("BASE_TESTNET_RPC", DEFAULT_RPCS[Chain.BASE])
CELO_TESTNET_RPC = os.environ.get("CELO_TESTNET_RPC", DEFAULT_RPCS[Chain.CELO])
ETHEREUM_TESTNET_RPC = os.environ.get(
    "ETHEREUM_TESTNET_RPC", DEFAULT_RPCS[Chain.ETHEREUM]
)
GNOSIS_TESTNET_RPC = os.environ.get("GNOSIS_TESTNET_RPC", DEFAULT_RPCS[Chain.GNOSIS])
MODE_TESTNET_RPC = os.environ.get("MODE_TESTNET_RPC", DEFAULT_RPCS[Chain.MODE])
OPTIMISM_TESTNET_RPC = os.environ.get(
    "OPTIMISM_TESTNET_RPC", DEFAULT_RPCS[Chain.OPTIMISM]
)
POLYGON_TESTNET_RPC = os.environ.get("POLYGON_TESTNET_RPC", DEFAULT_RPCS[Chain.POLYGON])
SOLANA_TESTNET_RPC = os.environ.get("SOLANA_TESTNET_RPC", DEFAULT_RPCS[Chain.SOLANA])


TESTNET_RPCS = {
    Chain.ARBITRUM_ONE: ARBITRUM_ONE_TESTNET_RPC,
    Chain.BASE: BASE_TESTNET_RPC,
    Chain.CELO: CELO_TESTNET_RPC,
    Chain.ETHEREUM: ETHEREUM_TESTNET_RPC,
    Chain.GNOSIS: GNOSIS_TESTNET_RPC,
    Chain.MODE: MODE_TESTNET_RPC,
    Chain.OPTIMISM: OPTIMISM_TESTNET_RPC,
    Chain.POLYGON: POLYGON_TESTNET_RPC,
    Chain.SOLANA: SOLANA_TESTNET_RPC,
}
