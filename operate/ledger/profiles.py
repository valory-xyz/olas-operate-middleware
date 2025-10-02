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

"""Chain profiles."""

import typing as t

from autonomy.chain.constants import CHAIN_PROFILES, DEFAULT_MULTISEND

from operate.constants import NO_STAKING_PROGRAM_ID, ZERO_ADDRESS
from operate.ledger import CHAINS
from operate.operate_types import Chain, ContractAddresses


# TODO: Refactor, remove the usage of CONTRACTS and use CHAIN_PROFILES from Open Autonomy instead.
CONTRACTS: t.Dict[Chain, ContractAddresses] = {}
for _chain in CHAINS:
    if _chain.value in CHAIN_PROFILES:
        profile = CHAIN_PROFILES[_chain.value]
        CONTRACTS[_chain] = ContractAddresses(
            {
                "service_registry": profile["service_registry"],
                "service_registry_token_utility": profile[
                    "service_registry_token_utility"
                ],
                "service_manager": profile["service_manager_token"],
                "gnosis_safe_proxy_factory": profile["gnosis_safe_proxy_factory"],
                "gnosis_safe_same_address_multisig": profile[
                    "gnosis_safe_same_address_multisig"
                ],
                "safe_multisig_with_recovery_module": profile[
                    "safe_multisig_with_recovery_module"
                ],
                "recovery_module": profile["recovery_module"],
                "multisend": DEFAULT_MULTISEND,
            }
        )

STAKING: t.Dict[Chain, t.Dict[str, str]] = {
    Chain.ARBITRUM_ONE: {},
    Chain.GNOSIS: {
        "pearl_alpha": "0xEE9F19b5DF06c7E8Bfc7B28745dcf944C504198A",
        "pearl_beta": "0xeF44Fb0842DDeF59D37f85D61A1eF492bbA6135d",
        "pearl_beta_2": "0x1c2F82413666d2a3fD8bC337b0268e62dDF67434",
        "pearl_beta_3": "0xBd59Ff0522aA773cB6074ce83cD1e4a05A457bc1",
        "pearl_beta_4": "0x3052451e1eAee78e62E169AfdF6288F8791F2918",
        "pearl_beta_5": "0x4Abe376Fda28c2F43b84884E5f822eA775DeA9F4",
        "pearl_beta_6": "0x6C6D01e8eA8f806eF0c22F0ef7ed81D868C1aB39",
        "pearl_beta_mech_marketplace": "0xDaF34eC46298b53a3d24CBCb431E84eBd23927dA",
        "quickstart_beta_hobbyist": "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C",
        "quickstart_beta_hobbyist_2": "0x238EB6993b90a978ec6AAD7530d6429c949C08DA",
        "quickstart_beta_expert": "0x5344B7DD311e5d3DdDd46A4f71481bD7b05AAA3e",
        "quickstart_beta_expert_2": "0xb964e44c126410df341ae04B13aB10A985fE3513",
        "quickstart_beta_expert_3": "0x80faD33Cadb5F53f9D29F02Db97D682E8b101618",
        "quickstart_beta_expert_4": "0xaD9d891134443B443D7F30013c7e14Fe27F2E029",
        "quickstart_beta_expert_5": "0xE56dF1E563De1B10715cB313D514af350D207212",
        "quickstart_beta_expert_6": "0x2546214aEE7eEa4bEE7689C81231017CA231Dc93",
        "quickstart_beta_expert_7": "0xD7A3C8b975f71030135f1a66e9e23164d54fF455",
        "quickstart_beta_expert_8": "0x356C108D49C5eebd21c84c04E9162de41933030c",
        "quickstart_beta_expert_9": "0x17dBAe44BC5618Cc254055b386A29576b4F87015",
        "quickstart_beta_expert_10": "0xB0ef657b8302bd2c74B6E6D9B2b4b39145b19c6f",
        "quickstart_beta_expert_11": "0x3112c1613eAC3dBAE3D4E38CeF023eb9E2C91CF7",
        "quickstart_beta_expert_12": "0xF4a75F476801B3fBB2e7093aCDcc3576593Cc1fc",
        "quickstart_beta_expert_15_mech_marketplace": "0x88eB38FF79fBa8C19943C0e5Acfa67D5876AdCC1",
        "quickstart_beta_expert_16_mech_marketplace": "0x6c65430515c70a3f5E62107CC301685B7D46f991",
        "quickstart_beta_expert_17_mech_marketplace": "0x1430107A785C3A36a0C1FC0ee09B9631e2E72aFf",
        "quickstart_beta_expert_18_mech_marketplace": "0x041e679d04Fc0D4f75Eb937Dea729Df09a58e454",
        "pearl_beta_mech_marketplace_1": "0xAb10188207Ea030555f53C8A84339A92f473aa5e",
        "pearl_beta_mech_marketplace_2": "0x8d7bE092d154b01d404f1aCCFA22Cef98C613B5D",
        "pearl_beta_mech_marketplace_3": "0x9D00A0551F20979080d3762005C9B74D7Aa77b85",
        "pearl_beta_mech_marketplace_4": "0xE2f80659dB1069f3B6a08af1A62064190c119543",
        "quickstart_beta_mech_marketplace_expert_3": "0x75EECA6207be98cAc3fDE8a20eCd7B01e50b3472",
        "quickstart_beta_mech_marketplace_expert_4": "0x9c7F6103e3a72E4d1805b9C683Ea5B370Ec1a99f",
        "quickstart_beta_mech_marketplace_expert_5": "0xcdC603e0Ee55Aae92519f9770f214b2Be4967f7d",
        "quickstart_beta_mech_marketplace_expert_6": "0x22D6cd3d587D8391C3aAE83a783f26c67ab54A85",
        "quickstart_beta_mech_marketplace_expert_7": "0xaaEcdf4d0CBd6Ca0622892Ac6044472f3912A5f3",
        "quickstart_beta_mech_marketplace_expert_8": "0x168aED532a0CD8868c22Fc77937Af78b363652B1",
        "mech_marketplace": "0x998dEFafD094817EF329f6dc79c703f1CF18bC90",
        "marketplace_supply_alpha": "0xCAbD0C941E54147D40644CF7DA7e36d70DF46f44",
        "marketplace_demand_alpha_1": "0x9d6e7aB0B5B48aE5c146936147C639fEf4575231",
        "marketplace_demand_alpha_2": "0x9fb17E549FefcCA630dd92Ea143703CeE4Ea4340",
    },
    Chain.OPTIMISM: {
        "optimus_alpha_1": "0x88996bbdE7f982D93214881756840cE2c77C4992",
        "optimus_alpha_2": "0xBCA056952D2A7a8dD4A002079219807CFDF9fd29",
        "optimus_alpha_3": "0x0f69f35652B1acdbD769049334f1AC580927E139",
        "optimus_alpha_4": "0x6891Cf116f9a3bDbD1e89413118eF81F69D298C3",
    },
    Chain.ETHEREUM: {},
    Chain.BASE: {
        "meme_base_alpha_2": "0xc653622FD75026a020995a1d8c8651316cBBc4dA",
        "meme_base_beta": "0x6011E09e7c095e76980b22498d69dF18EB62BeD8",
        "meme_base_beta_2": "0xfb7669c3AdF673b3A545Fa5acd987dbfdA805e22",
        "meme_base_beta_3": "0xCA61633b03c54F64b6A7F1f9A9C0A6Feb231Cc4D",
        "marketplace_supply_alpha": "0xB14Cd66c6c601230EA79fa7Cc072E5E0C2F3A756",
        "marketplace_demand_alpha_1": "0x38Eb3838Dab06932E7E1E965c6F922aDfE494b88",
        "marketplace_demand_alpha_2": "0xBE6E12364B549622395999dB0dB53f163994D7AF",
        "agents_fun_1": "0x2585e63df7BD9De8e058884D496658a030b5c6ce",
        "agents_fun_2": "0x26FA75ef9Ccaa60E58260226A71e9d07564C01bF",
        "agents_fun_3": "0x4D4233EBF0473Ca8f34d105A6256A2389176F0Ce",
    },
    Chain.CELO: {
        "meme_celo_alpha_2": "0x95D12D193d466237Bc1E92a1a7756e4264f574AB",
    },
    Chain.MODE: {
        "optimus_alpha": "0x5fc25f50E96857373C64dC0eDb1AbCBEd4587e91",
        "modius_alpha": "0x534C0A05B6d4d28d5f3630D6D74857B253cf8332",
        "modius_alpha_2": "0xeC013E68FE4B5734643499887941eC197fd757D0",
        "modius_alpha_3": "0x9034D0413D122015710f1744A19eFb1d7c2CEB13",
        "modius_alpha_4": "0x8BcAdb2c291C159F9385964e5eD95a9887302862",
    },
    Chain.POLYGON: {},
}


DEFAULT_PRIORITY_MECH = {  # maps mech marketplace address to its default priority mech address and service id
    "0x4554fE75c1f5576c1d7F765B2A036c199Adae329": (
        "0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053",
        975,
    ),
    "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB": (
        "0xC05e7412439bD7e91730a6880E18d5D5873F632C",
        2182,
    ),
}


# ERC20 token addresses
OLAS: t.Dict[Chain, str] = {
    Chain.ARBITRUM_ONE: "0x064F8B858C2A603e1b106a2039f5446D32dc81c1",
    Chain.BASE: "0x54330d28ca3357F294334BDC454a032e7f353416",
    Chain.CELO: "0xaCFfAe8e57Ec6E394Eb1b41939A8CF7892DbDc51",
    Chain.ETHEREUM: "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0",
    Chain.GNOSIS: "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
    Chain.MODE: "0xcfD1D50ce23C46D3Cf6407487B2F8934e96DC8f9",
    Chain.OPTIMISM: "0xFC2E6e6BCbd49ccf3A5f029c79984372DcBFE527",
    Chain.POLYGON: "0xFEF5d947472e72Efbb2E388c730B7428406F2F95",
}

USDC: t.Dict[Chain, str] = {
    Chain.ARBITRUM_ONE: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    Chain.BASE: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    Chain.CELO: "0xcebA9300f2b948710d2653dD7B07f33A8B32118C",
    Chain.ETHEREUM: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    Chain.GNOSIS: "0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83",
    Chain.MODE: "0xd988097fb8612cc24eeC14542bC03424c656005f",
    Chain.OPTIMISM: "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
    Chain.POLYGON: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
}

WRAPPED_NATIVE_ASSET = {
    Chain.ARBITRUM_ONE: "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    Chain.BASE: "0x4200000000000000000000000000000000000006",
    Chain.CELO: "0x471EcE3750Da237f93B8E339c536989b8978a438",  # Dual token
    Chain.ETHEREUM: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    Chain.GNOSIS: "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d",
    Chain.MODE: "0x4200000000000000000000000000000000000006",
    Chain.OPTIMISM: "0x4200000000000000000000000000000000000006",
    Chain.POLYGON: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
}

ERC20_TOKENS = [OLAS, USDC, WRAPPED_NATIVE_ASSET]

DEFAULT_NEW_SAFE_FUNDS: t.Dict[Chain, t.Dict[str, int]] = {
    Chain.ARBITRUM_ONE: {
        ZERO_ADDRESS: int(1e15 / 4),
    },
    Chain.BASE: {
        ZERO_ADDRESS: int(1e15 / 4),
    },
    Chain.CELO: {
        ZERO_ADDRESS: int(1e18),
    },
    Chain.ETHEREUM: {
        ZERO_ADDRESS: int(1e15 / 4),
    },
    Chain.GNOSIS: {
        ZERO_ADDRESS: int(1e18),
    },
    Chain.MODE: {
        ZERO_ADDRESS: int(1e15 / 4),
    },
    Chain.OPTIMISM: {
        ZERO_ADDRESS: int(1e15 / 4),
    },
    Chain.POLYGON: {
        ZERO_ADDRESS: int(1e18),
    },
}

DEFAULT_MASTER_EOA_FUNDS = {
    Chain.ARBITRUM_ONE: {ZERO_ADDRESS: 5_000_000_000_000_000},
    Chain.BASE: {ZERO_ADDRESS: 5_000_000_000_000_000},
    Chain.CELO: {ZERO_ADDRESS: 1_500_000_000_000_000_000},
    Chain.ETHEREUM: {ZERO_ADDRESS: 20_000_000_000_000_000},
    Chain.GNOSIS: {ZERO_ADDRESS: 1_500_000_000_000_000_000},
    Chain.MODE: {ZERO_ADDRESS: 500_000_000_000_000},
    Chain.OPTIMISM: {ZERO_ADDRESS: 5_000_000_000_000_000},
    Chain.POLYGON: {ZERO_ADDRESS: 1_500_000_000_000_000_000},
}

EXPLORER_URL = {
    Chain.ARBITRUM_ONE: {
        "tx": "https://arbiscan.io/tx/{tx_hash}",
        "address": "https://arbiscan.io/address/{address}",
    },
    Chain.BASE: {
        "tx": "https://basescan.org/tx/{tx_hash}",
        "address": "https://basescan.org/address/{address}",
    },
    Chain.CELO: {
        "tx": "https://celoscan.io/tx/{tx_hash}",
        "address": "https://celoscan.io/address/{address}",
    },
    Chain.ETHEREUM: {
        "tx": "https://etherscan.io/tx/{tx_hash}",
        "address": "https://etherscan.io/address/{address}",
    },
    Chain.GNOSIS: {
        "tx": "https://gnosisscan.io/tx/{tx_hash}",
        "address": "https://gnosisscan.io/address/{address}",
    },
    Chain.MODE: {
        "tx": "https://explorer.mode.network/tx/{tx_hash}",
        "address": "https://explorer.mode.network/address/{address}",
    },
    Chain.OPTIMISM: {
        "tx": "https://optimistic.etherscan.io/tx/{tx_hash}",
        "address": "https://optimistic.etherscan.io/address/{address}",
    },
    Chain.POLYGON: {
        "tx": "https://polygonscan.com/tx/{tx_hash}",
        "address": "https://polygonscan.com/address/{address}",
    },
}


def get_staking_contract(
    chain: str, staking_program_id: t.Optional[str]
) -> t.Optional[str]:
    """Get staking contract based on the config and the staking program."""
    if staking_program_id == NO_STAKING_PROGRAM_ID or staking_program_id is None:
        return None

    return STAKING[Chain(chain)].get(
        staking_program_id,
        staking_program_id,
    )
