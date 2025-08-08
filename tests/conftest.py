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

"""
Fixtures for pytest

The conftest.py file serves as a means of providing fixtures for an entire
directory. Fixtures defined in a conftest.py can be used by any test in that
package without needing to import them (pytest will automatically discover them).

See https://docs.pytest.org/en/stable/reference/fixtures.html
"""

import os
import random
import string
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from web3 import Web3

from operate.operate_types import Chain


ROOT_PATH = Path(__file__).resolve().parent
OPERATE_TEST = ".operate_test"
RUNNING_IN_CI = (
    os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    or os.getenv("CI", "").lower() == "true"
)

TEST_RPCS = {
    Chain.ETHEREUM: "https://rpc-gate.autonolas.tech/ethereum-rpc/",
    Chain.BASE: "https://rpc-gate.autonolas.tech/base-rpc/",
    Chain.CELO: "https://forno.celo.org",
    Chain.GNOSIS: "https://rpc-gate.autonolas.tech/gnosis-rpc/",
    Chain.MODE: "https://mainnet.mode.network",
    Chain.OPTIMISM: "https://rpc-gate.autonolas.tech/optimism-rpc/",
}


def random_string(length: int = 16) -> str:
    """Random string"""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))  # nosec B311


def random_mnemonic(num_words: int = 12) -> str:
    """Generate a random BIP-39 mnemonic"""
    w3 = Web3()
    w3.eth.account.enable_unaudited_hdwallet_features()
    _, mnemonic = w3.eth.account.create_with_mnemonic(num_words=num_words)
    return mnemonic


@pytest.fixture
def password() -> str:
    """Password fixture"""
    return random_string(16)


@pytest.fixture
def temp_keys_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for keys."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)
