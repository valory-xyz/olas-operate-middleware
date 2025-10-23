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

import json
import os
import random
import string
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import pytest
import requests
from web3 import Web3

from operate.bridge.bridge_manager import BridgeManager
from operate.cli import OperateApp
from operate.constants import KEYS_DIR, ZERO_ADDRESS
from operate.keys import KeysManager
from operate.ledger import get_default_ledger_api, get_default_rpc  # noqa: E402
from operate.ledger.profiles import OLAS, USDC
from operate.operate_types import (
    Chain,
    ConfigurationTemplate,
    FundRequirementsTemplate,
    LedgerType,
    ServiceEnvProvisionType,
    ServiceTemplate,
)
from operate.services.manage import ServiceManager
from operate.utils.gnosis import get_asset_balance
from operate.wallet.master import MasterWalletManager

from tests.constants import LOGGER, OPERATE_TEST, RUNNING_IN_CI, TESTNET_RPCS


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


def tenderly_add_balance(
    chain: Chain,
    recipient: str,
    amount: int = 1000 * (10**18),
    token: str = ZERO_ADDRESS,
) -> None:
    """tenderly_add_balance"""
    rpc = get_default_rpc(chain)
    headers = {"Content-Type": "application/json"}

    if token == ZERO_ADDRESS:
        data = {
            "jsonrpc": "2.0",
            "method": "tenderly_addBalance",
            "params": [recipient, hex(amount)],
            "id": "1",
        }
    else:
        current_balance = get_asset_balance(
            ledger_api=get_default_ledger_api(chain),
            address=recipient,
            asset_address=token,
            raise_on_invalid_address=False,
        )
        data = {
            "jsonrpc": "2.0",
            "method": "tenderly_setErc20Balance",
            "params": [token, recipient, hex(amount + current_balance)],
            "id": "1",
        }

    response = requests.post(
        url=rpc, headers=headers, data=json.dumps(data), timeout=60
    )
    response.raise_for_status()


def tenderly_increase_time(chain: Chain, time: int = 3 * 24 * 3600 + 1) -> None:
    """tenderly_increase_time"""
    rpc = get_default_rpc(chain)
    headers = {"Content-Type": "application/json"}

    if time <= 0:
        return

    data = {
        "jsonrpc": "2.0",
        "method": "evm_increaseTime",
        "params": [hex(time)],
        "id": "1",
    }

    response = requests.post(rpc, headers=headers, data=json.dumps(data), timeout=30)
    response.raise_for_status()


@pytest.fixture
def password() -> str:
    """Password fixture"""
    return random_string(16)


@pytest.fixture
def temp_keys_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for keys."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


class OnTestnet:
    """TestOnTestnet"""

    # TODO: Remove this skip after optimizing tenderly usage
    pytestmark = pytest.mark.skipif(
        RUNNING_IN_CI, reason="To avoid exhausting tenderly limits."
    )

    @pytest.fixture(autouse=True)
    def _patch_rpcs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        required_envs = [
            "BASE_TESTNET_RPC",
            "ETHEREUM_TESTNET_RPC",
            "GNOSIS_TESTNET_RPC",
            "OPTIMISM_TESTNET_RPC",
            "POLYGON_TESTNET_RPC",
        ]
        missing = [var for var in required_envs if os.environ.get(var) is None]
        if missing:
            pytest.fail(f"Missing required environment variables: {', '.join(missing)}")
        monkeypatch.setattr("operate.ledger.DEFAULT_RPCS", TESTNET_RPCS)
        monkeypatch.setattr("operate.ledger.DEFAULT_LEDGER_APIS", {})


@dataclass
class OperateTestEnv:
    """Operate test environment."""

    tmp_path: Path
    password: str
    operate: OperateApp
    wallet_manager: MasterWalletManager
    service_manager: ServiceManager
    bridge_manager: BridgeManager
    keys_manager: KeysManager
    backup_owner: str
    backup_owner2: str


def _get_service_template_trader() -> ServiceTemplate:
    """Get the service template"""
    return ServiceTemplate(
        {
            "name": "Trader Agent",
            "hash": "bafybeifhxeoar5hdwilmnzhy6jf664zqp5lgrzi6lpbkc4qmoqrr24ow4q",
            "image": "https://operate.olas.network/_next/image?url=%2Fimages%2Fprediction-agent.png&w=3840&q=75",
            "description": "Trader agent for omen prediction markets",
            "service_version": "v0.26.1",
            "home_chain": "gnosis",
            "configurations": {
                "gnosis": ConfigurationTemplate(
                    {
                        "staking_program_id": "pearl_beta_2",
                        "nft": "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq",
                        "rpc": get_default_rpc(Chain.GNOSIS),
                        "agent_id": 14,
                        "cost_of_bond": 1000000000000000,
                        "fund_requirements": {
                            ZERO_ADDRESS: FundRequirementsTemplate(
                                {
                                    "agent": 2000000000000000000,
                                    "safe": 5000000000000000000,
                                }
                            )
                        },
                        "fallback_chain_params": None,
                    }
                ),
            },
            "env_variables": {
                "GNOSIS_LEDGER_RPC": {
                    "name": "Gnosis ledger RPC",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "STAKING_CONTRACT_ADDRESS": {
                    "name": "Staking contract address",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "MECH_MARKETPLACE_CONFIG": {
                    "name": "Mech marketplace configuration",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "MECH_ACTIVITY_CHECKER_CONTRACT": {
                    "name": "Mech activity checker contract",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "MECH_CONTRACT_ADDRESS": {
                    "name": "Mech contract address",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "MECH_REQUEST_PRICE": {
                    "name": "Mech request price",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "USE_MECH_MARKETPLACE": {
                    "name": "Use Mech marketplace",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "TOOLS_ACCURACY_HASH": {
                    "name": "Tools accuracy hash",
                    "description": "",
                    "value": "QmWgsqncF22hPLNTyWtDzVoKPJ9gmgR1jcuLL5t31xyzzr",
                    "provision_type": ServiceEnvProvisionType.FIXED,
                },
                "ACC_INFO_FIELDS_REQUESTS": {
                    "name": "Acc info fields requests",
                    "description": "",
                    "value": "nr_responses",
                    "provision_type": ServiceEnvProvisionType.FIXED,
                },
                "MECH_INTERACT_ROUND_TIMEOUT_SECONDS": {
                    "name": "Mech interact round timeout",
                    "description": "",
                    "value": "900",
                    "provision_type": ServiceEnvProvisionType.FIXED,
                },
                "STORE_PATH": {
                    "name": "Store path",
                    "description": "",
                    "value": "persistent_data/",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "LOG_DIR": {
                    "name": "Log directory",
                    "description": "",
                    "value": "benchmarks/",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "IRRELEVANT_TOOLS": {
                    "name": "Irrelevant tools",
                    "description": "",
                    "value": '["native-transfer","prediction-online-lite","claude-prediction-online-lite","prediction-online-sme-lite","prediction-request-reasoning-lite","prediction-request-reasoning-claude-lite","prediction-offline-sme","deepmind-optimization","deepmind-optimization-strong","openai-gpt-3.5-turbo","openai-gpt-3.5-turbo-instruct","openai-gpt-4","openai-text-davinci-002","openai-text-davinci-003","prediction-online-sum-url-content","prediction-online-summarized-info","stabilityai-stable-diffusion-512-v2-1","stabilityai-stable-diffusion-768-v2-1","stabilityai-stable-diffusion-v1-5","stabilityai-stable-diffusion-xl-beta-v2-2-2","prediction-url-cot-claude","prediction-url-cot"]',
                    "provision_type": ServiceEnvProvisionType.FIXED,
                },
            },
        }
    )


def _get_service_template_multichain_service() -> ServiceTemplate:
    """Get the service template"""
    return ServiceTemplate(
        {
            "name": "Test Multichain Service",
            "hash": "bafybeifhxeoar5hdwilmnzhy6jf664zqp5lgrzi6lpbkc4qmoqrr24ow4q",
            "image": "https://operate.olas.network/_next/image?url=%2Fimages%2Fprediction-agent.png&w=3840&q=75",
            "description": "Test Multichain Service",
            "service_version": "v0.0.1",
            "home_chain": "gnosis",
            "configurations": {
                "gnosis": ConfigurationTemplate(
                    {
                        "staking_program_id": "pearl_beta_2",
                        "nft": "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq",
                        "rpc": get_default_rpc(Chain.GNOSIS),
                        "agent_id": 14,
                        "cost_of_bond": 1000000000000000,
                        "fund_requirements": {
                            ZERO_ADDRESS: FundRequirementsTemplate(
                                {
                                    "agent": 2000000000000000000,
                                    "safe": 5000000000000000000,
                                }
                            )
                        },
                        "fallback_chain_params": None,
                    }
                ),
                "base": ConfigurationTemplate(
                    {
                        "staking_program_id": None,
                        "nft": "bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq",
                        "rpc": get_default_rpc(Chain.BASE),
                        "agent_id": 43,
                        "cost_of_bond": 100000000000000,
                        "fund_requirements": {
                            ZERO_ADDRESS: FundRequirementsTemplate(
                                {
                                    "agent": 5000000000000000,
                                    "safe": 10000000000000000,
                                },
                            ),
                            USDC[Chain.BASE]: FundRequirementsTemplate(
                                {
                                    "agent": 20000000,
                                    "safe": 50000000,
                                }
                            ),
                        },
                        "fallback_chain_params": None,
                    }
                ),
            },
            "env_variables": {
                "BASE_LEDGER_RPC": {
                    "name": "Base ledger RPC",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "GNOSIS_LEDGER_RPC": {
                    "name": "Gnosis ledger RPC",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "STAKING_CONTRACT_ADDRESS": {
                    "name": "Staking contract address",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "MECH_ACTIVITY_CHECKER_CONTRACT": {
                    "name": "Mech activity checker contract",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "MECH_CONTRACT_ADDRESS": {
                    "name": "Mech contract address",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "MECH_REQUEST_PRICE": {
                    "name": "Mech request price",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "USE_MECH_MARKETPLACE": {
                    "name": "Use Mech marketplace",
                    "description": "",
                    "value": "",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "LOG_DIR": {
                    "name": "Log directory",
                    "description": "",
                    "value": "benchmarks/",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
                "STORE_PATH": {
                    "name": "Store path",
                    "description": "",
                    "value": "persistent_data/",
                    "provision_type": ServiceEnvProvisionType.COMPUTED,
                },
            },
        }
    )


@pytest.fixture
def test_operate(tmp_path: Path, password: str) -> OperateApp:
    """Sets up a test operate app."""
    operate = OperateApp(
        home=tmp_path / OPERATE_TEST,
    )
    operate.setup()
    operate.create_user_account(password=password)
    operate.password = password
    operate.wallet_manager.setup()
    return operate


@pytest.fixture
def test_env(tmp_path: Path, password: str, test_operate: OperateApp) -> OperateTestEnv:
    """Sets up a test environment."""

    def _create_wallets(wallet_manager: MasterWalletManager) -> None:
        for ledger_type in [LedgerType.ETHEREUM]:  # TODO Add Solana when supported
            wallet_manager.create(ledger_type=ledger_type)

    def _create_safes(wallet_manager: MasterWalletManager, backup_owner: str) -> None:
        ledger_types = {wallet.ledger_type for wallet in wallet_manager}
        for chain in [Chain.GNOSIS, Chain.OPTIMISM]:
            ledger_type = chain.ledger_type
            if ledger_type in ledger_types:
                wallet = wallet_manager.load(ledger_type=ledger_type)
                tenderly_add_balance(chain, wallet.address)
                tenderly_add_balance(chain, backup_owner)
                wallet.create_safe(
                    chain=chain,
                    backup_owner=backup_owner,
                )
                tenderly_add_balance(chain, wallet.safes[chain])
                tenderly_add_balance(
                    chain=chain, recipient=wallet.safes[chain], token=OLAS[chain]
                )
                tenderly_add_balance(
                    chain=chain,
                    recipient=wallet.safes[chain],
                    token=USDC[chain],
                    amount=int(1000e6),
                )

    keys_manager = KeysManager(
        path=test_operate._path / KEYS_DIR,  # pylint: disable=protected-access
        logger=LOGGER,
    )
    backup_owner = keys_manager.create()
    backup_owner2 = keys_manager.create()

    assert backup_owner != backup_owner2

    _create_wallets(wallet_manager=test_operate.wallet_manager)
    _create_safes(
        wallet_manager=test_operate.wallet_manager,
        backup_owner=backup_owner,
    )
    test_operate.service_manager().create(
        service_template=_get_service_template_trader()
    )

    # Logout
    test_operate.password = None

    return OperateTestEnv(
        tmp_path=tmp_path,
        password=password,
        operate=test_operate,
        wallet_manager=test_operate.wallet_manager,
        service_manager=test_operate.service_manager(),
        bridge_manager=test_operate.bridge_manager,
        keys_manager=keys_manager,
        backup_owner=backup_owner,
        backup_owner2=backup_owner2,
    )
