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

"""Constants."""

from pathlib import Path


OPERATE = ".operate"
OPERATE_HOME = Path.cwd() / OPERATE
SERVICES_DIR = "services"
KEYS_DIR = "keys"
WALLETS_DIR = "wallets"
WALLET_RECOVERY_DIR = "wallet_recovery"
DEPLOYMENT_DIR = "deployment"
DEPLOYMENT_JSON = "deployment.json"
CONFIG_JSON = "config.json"
USER_JSON = "user.json"
HEALTHCHECK_JSON = "healthcheck.json"

AGENT_PERSISTENT_STORAGE_DIR = "persistent_data"
AGENT_PERSISTENT_STORAGE_ENV_VAR = "STORE_PATH"
AGENT_LOG_DIR = "benchmarks"
AGENT_LOG_ENV_VAR = "LOG_DIR"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

ON_CHAIN_INTERACT_TIMEOUT = 120.0
ON_CHAIN_INTERACT_RETRIES = 10
ON_CHAIN_INTERACT_SLEEP = 3.0
MIN_PASSWORD_LENGTH = 8

HEALTH_CHECK_URL = "http://127.0.0.1:8716/healthcheck"  # possible DNS issues on windows so use IP address
SAFE_WEBAPP_URL = "https://app.safe.global/home?safe=gno:"
TM_CONTROL_URL = "http://localhost:8080"
IPFS_ADDRESS = "https://gateway.autonolas.tech/ipfs/f01701220{hash}"

# TODO: These links may break in the future, use a more robust approach
MECH_CONTRACT_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/mech/refs/tags/v0.8.0/packages/valory/contracts/agent_mech/build/AgentMech.json"
STAKING_TOKEN_INSTANCE_ABI_PATH = "https://raw.githubusercontent.com/valory-xyz/trader/refs/tags/v0.23.0/packages/valory/contracts/staking_token/build/StakingToken.json"  # nosec
MECH_ACTIVITY_CHECKER_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/autonolas-staking-programmes/refs/heads/main/abis/0.8.25/SingleMechActivityChecker.json"
SERVICE_REGISTRY_TOKEN_UTILITY_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/open-autonomy/refs/tags/v0.18.4/packages/valory/contracts/service_registry_token_utility/build/ServiceRegistryTokenUtility.json"  # nosec
MECH_AGENT_FACTORY_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/ai-registry-mech/main/abis/0.8.25/AgentFactory.json"
MECH_MARKETPLACE_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/mech-quickstart/refs/heads/main/contracts/MechMarketplace.json"
NO_STAKING_PROGRAM_ID = "no_staking"


DEPLOYMENT_START_TRIES_NUM = 3
IPFS_CHECK_URL = "https://gateway.autonolas.tech/ipfs/bafybeigcllaxn4ycjjvika3zd6eicksuriez2wtg67gx7pamhcazl3tv54/echo/README.md"
