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

"""Types module."""

import base64
import copy
import enum
import os
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

import argon2
from aea_ledger_ethereum import cast
from autonomy.chain.config import ChainType
from autonomy.chain.config import LedgerType as LedgerTypeOA
from cryptography.fernet import Fernet
from typing_extensions import TypedDict

from operate.constants import FERNET_KEY_LENGTH, NO_STAKING_PROGRAM_ID
from operate.resource import LocalResource
from operate.serialization import BigInt, serialize


LedgerType = LedgerTypeOA
Chain = ChainType


class DeploymentStatus(enum.IntEnum):
    """Status payload."""

    CREATED = 0
    BUILT = 1
    DEPLOYING = 2
    DEPLOYED = 3
    STOPPING = 4
    STOPPED = 5
    DELETED = 6


# TODO defined in aea.chain.base.OnChainState
class OnChainState(enum.IntEnum):
    """On-chain state."""

    NON_EXISTENT = 0
    PRE_REGISTRATION = 1
    ACTIVE_REGISTRATION = 2
    FINISHED_REGISTRATION = 3
    DEPLOYED = 4
    TERMINATED_BONDED = 5
    UNBONDED = 6  # TODO this is not an on-chain state https://github.com/valory-xyz/autonolas-registries/blob/main/contracts/ServiceRegistryL2.sol


class ContractAddresses(TypedDict):
    """Contracts templates."""

    service_manager: str
    service_registry: str
    service_registry_token_utility: str
    gnosis_safe_proxy_factory: str
    gnosis_safe_same_address_multisig: str
    safe_multisig_with_recovery_module: str
    recovery_module: str
    multisend: str


@dataclass
class LedgerConfig(LocalResource):
    """Ledger config."""

    rpc: str
    chain: Chain


LedgerConfigs = t.Dict[str, LedgerConfig]


class DeploymentConfig(TypedDict):
    """Deployments template."""

    volumes: t.Dict[str, str]


class FundRequirementsTemplate(TypedDict):
    """Fund requirement template."""

    agent: int
    safe: int


class ConfigurationTemplate(TypedDict):
    """Configuration template."""

    staking_program_id: str
    nft: str
    rpc: str
    agent_id: int
    cost_of_bond: int
    fund_requirements: t.Dict[str, FundRequirementsTemplate]
    fallback_chain_params: t.Optional[t.Dict]


class ServiceEnvProvisionType(str, enum.Enum):
    """Service environment variable provision type."""

    FIXED = "fixed"
    USER = "user"
    COMPUTED = "computed"


class EnvVariableAttributes(TypedDict):
    """Service environment variable template."""

    name: str
    description: str
    value: str
    provision_type: ServiceEnvProvisionType


class AgentReleaseRepo(TypedDict):
    """Agent release repo template."""

    owner: str
    name: str
    version: str


class AgentRelease(TypedDict):
    """Agent release template."""

    is_aea: bool
    repository: AgentReleaseRepo


ConfigurationTemplates = t.Dict[str, ConfigurationTemplate]
EnvVariables = t.Dict[str, EnvVariableAttributes]


class ServiceTemplate(TypedDict, total=False):
    """Service template."""

    name: str
    hash: str
    image: str
    description: str
    service_version: str
    agent_release: AgentRelease
    home_chain: str
    configurations: ConfigurationTemplates
    env_variables: EnvVariables


@dataclass
class DeployedNodes(LocalResource):
    """Deployed nodes type."""

    agent: t.List[str]
    tendermint: t.List[str]


@dataclass
class OnChainFundRequirements(LocalResource):
    """On-chain fund requirements."""

    agent: BigInt
    safe: BigInt


OnChainTokenRequirements = t.Dict[str, OnChainFundRequirements]


@dataclass
class OnChainUserParams(LocalResource):
    """On-chain user params."""

    staking_program_id: str
    nft: str
    agent_id: int
    cost_of_bond: BigInt
    fund_requirements: OnChainTokenRequirements

    @property
    def use_staking(self) -> bool:
        """Check if staking is used."""
        return (
            self.staking_program_id is not None
            and self.staking_program_id != NO_STAKING_PROGRAM_ID
        )

    @classmethod
    def from_json(cls, obj: t.Dict) -> "OnChainUserParams":
        """Load a service"""
        return super().from_json(obj)  # type: ignore


@dataclass
class OnChainData(LocalResource):
    """On-chain data"""

    instances: t.List[str]  # Agent instances registered as safe owners
    token: int
    multisig: str
    user_params: OnChainUserParams


@dataclass
class ChainConfig(LocalResource):
    """Chain config."""

    ledger_config: LedgerConfig
    chain_data: OnChainData

    @classmethod
    def from_json(cls, obj: t.Dict) -> "ChainConfig":
        """Load the chain config."""
        return super().from_json(obj)  # type: ignore


ChainConfigs = t.Dict[str, ChainConfig]


class FundingConfig(TypedDict):
    """Funding config."""

    topup: int
    threshold: int


class AssetFundingValues(TypedDict):
    """Asset Funding values."""

    agent: FundingConfig
    safe: FundingConfig


FundingValues = t.Dict[str, AssetFundingValues]  # str is the asset address


@dataclass
class MechMarketplaceConfig:
    """Mech Marketplace config."""

    use_mech_marketplace: bool
    mech_marketplace_address: str
    priority_mech_address: str
    priority_mech_service_id: int


class Version:
    """Version class."""

    def __init__(self, version: str) -> None:
        """Initialize the version."""
        version = version.strip()
        version_parts = version.split(".") if version else []
        self.major = int(version_parts[0]) if len(version_parts) > 0 else 0
        self.minor = int(version_parts[1]) if len(version_parts) > 1 else 0
        self.patch = int(version_parts[2]) if len(version_parts) > 2 else 0

    def __str__(self) -> str:
        """String representation of the version."""
        return f"{self.major}.{self.minor}.{self.patch}"

    def __eq__(self, other: object) -> bool:
        """Equality comparison."""
        if not isinstance(other, Version):
            return NotImplemented
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
        )

    def __lt__(self, other: "Version") -> bool:
        """Less than comparison."""
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        return self.patch < other.patch


class ChainAmounts(dict[str, dict[str, dict[str, BigInt]]]):
    """
    Class that represents chain amounts as a dictionary

    The standard format follows the convention {chain: {address: {token: amount}}}
    """

    @property
    def json(self) -> dict:
        """Return JSON representation with amounts as strings."""
        return serialize(self)

    @staticmethod
    def from_json(obj: dict) -> "ChainAmounts":
        """Create ChainAmounts from JSON representation."""
        result: dict[str, dict[str, dict[str, BigInt]]] = {}

        for chain, addresses in obj.items():
            for address, assets in addresses.items():
                for asset, amount in assets.items():
                    result.setdefault(chain, {}).setdefault(address, {})[asset] = (
                        BigInt(amount)
                    )

        return ChainAmounts(result)

    @classmethod
    def shortfalls(
        cls, requirements: "ChainAmounts", balances: "ChainAmounts"
    ) -> "ChainAmounts":
        """Return the shortfalls between requirements and balances."""
        result: dict[str, dict[str, dict[str, BigInt]]] = {}

        for chain, addresses in requirements.items():
            for address, assets in addresses.items():
                for asset, required_amount in assets.items():
                    available = balances.get(chain, {}).get(address, {}).get(asset, 0)
                    shortfall = max(required_amount - available, 0)
                    result.setdefault(chain, {}).setdefault(address, {})[asset] = (
                        BigInt(shortfall)
                    )

        return cls(result)

    @classmethod
    def add(cls, *chainamounts: "ChainAmounts") -> "ChainAmounts":
        """Add multiple ChainAmounts"""
        result: dict[str, dict[str, dict[str, BigInt]]] = {}

        for ca in chainamounts:
            for chain, addresses in ca.items():
                result_addresses = result.setdefault(chain, {})
                for address, assets in addresses.items():
                    result_assets = result_addresses.setdefault(address, {})
                    for asset, amount in assets.items():
                        result_assets[asset] = BigInt(
                            result_assets.get(asset, 0) + amount
                        )

        return cls(result)

    def __add__(self, other: "ChainAmounts") -> "ChainAmounts":
        """Add two ChainAmounts"""
        return ChainAmounts.add(self, other)

    def __mul__(self, multiplier: float) -> "ChainAmounts":
        """Multiply all amounts by the specified multiplier"""
        output = copy.deepcopy(self)
        for _, addresses in output.items():
            for _, balances in addresses.items():
                for asset, amount in balances.items():
                    balances[asset] = BigInt(int(amount * multiplier))
        return output

    def __sub__(self, other: "ChainAmounts") -> "ChainAmounts":
        """Subtract two ChainAmounts"""
        return self + (other * -1)

    def __floordiv__(self, divisor: float) -> "ChainAmounts":
        """Divide all amounts by the specified divisor"""
        if divisor == 0:
            raise ValueError("Cannot divide by zero")

        output = copy.deepcopy(self)
        for _, addresses in output.items():
            for _, balances in addresses.items():
                for asset, amount in balances.items():
                    balances[asset] = BigInt(int(amount // divisor))
        return output

    def __lt__(self, other: "ChainAmounts") -> bool:
        """Return True if all amounts in self are strictly less than the corresponding amounts in other."""
        for chain, addresses in self.items():
            for address, assets in addresses.items():
                for asset, amount in assets.items():
                    if amount >= other.get(chain, {}).get(address, {}).get(asset, 0):
                        return False
        return True


@dataclass
class EncryptedData(LocalResource):
    """EncryptedData type."""

    path: Path
    version: int
    cipher: str
    cipherparams: t.Dict[str, t.Union[int, str]] = field(repr=False)
    ciphertext: str = field(repr=False)
    kdf: str
    kdfparams: t.Dict[str, t.Union[int, str]] = field(repr=False)

    @classmethod
    def new(cls, path: Path, password: str, plaintext_bytes: bytes) -> "EncryptedData":
        """Creates a new EncryptedData"""
        ph = argon2.PasswordHasher()
        salt = os.urandom(ph.salt_len)
        time_cost = ph.time_cost
        memory_cost = ph.memory_cost
        parallelism = ph.parallelism
        hash_len = FERNET_KEY_LENGTH
        argon2_type = argon2.Type.ID
        key = argon2.low_level.hash_secret_raw(
            secret=password.encode(),
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_len,
            type=argon2_type,
        )

        fernet_key = base64.urlsafe_b64encode(key)
        fernet = Fernet(fernet_key)
        ciphertext_bytes = fernet.encrypt(plaintext_bytes)

        return cls(
            path=path,
            version=1,
            cipher=f"{fernet.__class__.__module__}.{fernet.__class__.__qualname__}",
            cipherparams={  # Fernet token (ciphertext variable) already stores them
                "version": ciphertext_bytes[0]
            },
            ciphertext=ciphertext_bytes.hex(),
            kdf=f"{ph.__class__.__module__}.{ph.__class__.__qualname__}",
            kdfparams={
                "salt": salt.hex(),
                "time_cost": time_cost,
                "memory_cost": memory_cost,
                "parallelism": parallelism,
                "hash_len": hash_len,
                "type": argon2_type.name,
            },
        )

    def decrypt(self, password: str) -> bytes:
        """Decrypts the EncryptedData"""
        kdfparams = self.kdfparams
        key = argon2.low_level.hash_secret_raw(
            secret=password.encode(),
            salt=bytes.fromhex(kdfparams["salt"]),
            time_cost=kdfparams["time_cost"],
            memory_cost=kdfparams["memory_cost"],
            parallelism=kdfparams["parallelism"],
            hash_len=kdfparams["hash_len"],
            type=argon2.Type[kdfparams["type"]],
        )
        fernet_key = base64.urlsafe_b64encode(key)
        fernet = Fernet(fernet_key)
        ciphertext_bytes = bytes.fromhex(self.ciphertext)
        plaintext_bytes = fernet.decrypt(ciphertext_bytes)
        return plaintext_bytes

    @classmethod
    def load(cls, path: Path) -> "EncryptedData":
        """Load EncryptedData."""
        return cast(EncryptedData, super().load(path))
