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

from operate.operate_types import Chain


OPERATE = ".operate"
OPERATE_HOME = Path.cwd() / OPERATE
CONFIG = "config.json"
SERVICES = "services"
KEYS = "keys"
DEPLOYMENT = "deployment"
DEPLOYMENT_JSON = "deployment.json"
CONFIG = "config.json"
KEY = "key"
KEYS = "keys"
KEYS_JSON = "keys.json"
DOCKER_COMPOSE_YAML = "docker-compose.yaml"
SERVICE_YAML = "service.yaml"
STAKED_BONDING_TOKEN = "OLAS"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

ON_CHAIN_INTERACT_TIMEOUT = 120.0
ON_CHAIN_INTERACT_RETRIES = 40
ON_CHAIN_INTERACT_SLEEP = 3.0

HEALTH_CHECK_URL = "http://127.0.0.1:8716/healthcheck"  # possible DNS issues on windows so use IP address
SAFE_WEBAPP_URL = "https://app.safe.global/home?safe=gno:"
TM_CONTROL_URL = "http://localhost:8080"
IPFS_ADDRESS = "https://gateway.autonolas.tech/ipfs/f01701220{hash}"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

WRAPPED_NATIVE_ASSET = {
    Chain.ETHEREUM.value: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    Chain.POLYGON.value: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    Chain.GNOSIS.value: "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d",
    Chain.ARBITRUM_ONE.value: "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    Chain.OPTIMISTIC.value: "0x4200000000000000000000000000000000000006",
    Chain.MODE.value: "0x4200000000000000000000000000000000000006",
    Chain.BASE.value: "0x4200000000000000000000000000000000000006",
}

MECH_CONTRACT_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/mech/refs/heads/main/packages/valory/contracts/agent_mech/build/AgentMech.json"
STAKING_TOKEN_INSTANCE_ABI_PATH = 'https://raw.githubusercontent.com/valory-xyz/trader/refs/heads/main/packages/valory/contracts/staking_token/build/StakingToken.json'
STAKING_TOKEN_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/trader/refs/heads/main/packages/valory/contracts/service_staking_token/build/ServiceStakingToken.json"
SERVICE_REGISTRY_TOKEN_UTILITY_JSON_URL = "https://raw.githubusercontent.com/valory-xyz/open-autonomy/refs/heads/main/packages/valory/contracts/service_registry_token_utility/build/ServiceRegistryTokenUtility.json"
