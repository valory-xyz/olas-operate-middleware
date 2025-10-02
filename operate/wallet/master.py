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

"""Master key implementation"""

import json
import logging
import os
import typing as t
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from aea.crypto.base import Crypto, LedgerApi
from aea.crypto.registries import make_ledger_api
from aea_ledger_ethereum import DEFAULT_GAS_PRICE_STRATEGIES, EIP1559, GWEI, to_wei
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from autonomy.chain.base import registry_contracts
from autonomy.chain.config import ChainType as ChainProfile
from autonomy.chain.tx import TxSettler
from web3 import Account, Web3

from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.ledger import get_default_rpc
from operate.ledger.profiles import ERC20_TOKENS, OLAS, USDC
from operate.operate_types import Chain, LedgerType
from operate.resource import LocalResource
from operate.utils import create_backup
from operate.utils.gnosis import add_owner
from operate.utils.gnosis import create_safe as create_gnosis_safe
from operate.utils.gnosis import (
    drain_eoa,
    get_asset_balance,
    get_owners,
    remove_owner,
    swap_owner,
)
from operate.utils.gnosis import transfer as transfer_from_safe
from operate.utils.gnosis import transfer_erc20_from_safe


# TODO Organize exceptions definition
class InsufficientFundsException(Exception):
    """Insufficient funds exception."""


class MasterWallet(LocalResource):
    """Master wallet."""

    path: Path
    address: str

    safes: t.Dict[Chain, str] = field(default_factory=dict)
    safe_chains: t.List[Chain] = field(default_factory=list)
    ledger_type: LedgerType
    safe_nonce: t.Optional[int] = None

    _key: str
    _crypto: t.Optional[Crypto] = None
    _password: t.Optional[str] = None
    _crypto_cls: t.Type[Crypto]

    @property
    def password(self) -> str:
        """Password string."""
        if self._password is None:
            raise ValueError("Password not set.")
        return self._password

    @password.setter
    def password(self, value: str) -> None:
        """Set password value."""
        self._password = value

    @property
    def crypto(self) -> Crypto:
        """Load crypto object."""
        if self._crypto is None:
            self._crypto = self._crypto_cls(self.path / self._key, self.password)
        return self._crypto

    @property
    def key_path(self) -> Path:
        """Key path."""
        return self.path / self._key

    def ledger_api(
        self,
        chain: Chain,
        rpc: t.Optional[str] = None,
    ) -> LedgerApi:
        """Get ledger api object."""
        gas_price_strategies = deepcopy(DEFAULT_GAS_PRICE_STRATEGIES)
        if chain in (Chain.BASE, Chain.MODE, Chain.OPTIMISM):
            gas_price_strategies[EIP1559]["fallback_estimate"]["maxFeePerGas"] = to_wei(
                5, GWEI
            )

        return make_ledger_api(
            self.ledger_type.name.lower(),
            address=(rpc or get_default_rpc(chain=chain)),
            chain_id=chain.id,
            gas_price_strategies=gas_price_strategies,
        )

    def transfer(
        self,
        to: str,
        amount: int,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer funds to the given account."""
        raise NotImplementedError()

    # pylint: disable=too-many-arguments
    def transfer_erc20(
        self,
        token: str,
        to: str,
        amount: int,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer funds to the given account."""
        raise NotImplementedError()

    def transfer_asset(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: str = ZERO_ADDRESS,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer erc20/native assets to the given account."""
        raise NotImplementedError()

    def drain(
        self,
        withdrawal_address: str,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> None:
        """Drain all erc20/native assets to the given account."""
        raise NotImplementedError()

    @classmethod
    def new(cls, password: str, path: Path) -> t.Tuple["MasterWallet", t.List[str]]:
        """Create a new master wallet."""
        raise NotImplementedError()

    def create_safe(
        self,
        chain: Chain,
        backup_owner: t.Optional[str] = None,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Create safe."""
        raise NotImplementedError()

    def update_backup_owner(
        self,
        chain: Chain,
        backup_owner: t.Optional[str] = None,
        rpc: t.Optional[str] = None,
    ) -> bool:
        """Update backup owner."""
        raise NotImplementedError()

    def is_password_valid(self, password: str) -> bool:
        """Verifies if the provided password is valid."""
        try:
            self._crypto_cls(self.path / self._key, password)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def update_password(self, new_password: str) -> None:
        """Update password."""
        raise NotImplementedError()

    def is_mnemonic_valid(self, mnemonic: str) -> bool:
        """Is mnemonic valid."""
        raise NotImplementedError()

    def update_password_with_mnemonic(self, mnemonic: str, new_password: str) -> None:
        """Updates password using the mnemonic."""
        raise NotImplementedError()

    # TODO move to resource.py if used in more resources similarly
    @property
    def extended_json(self) -> t.Dict:
        """Get JSON representation with extended information (e.g., safe owners)."""
        raise NotImplementedError

    @classmethod
    def migrate_format(cls, path: Path) -> bool:
        """Migrate the JSON file format if needed."""
        raise NotImplementedError


@dataclass
class EthereumMasterWallet(MasterWallet):
    """Master wallet manager."""

    path: Path
    address: str

    safes: t.Dict[Chain, str] = field(default_factory=dict)
    safe_chains: t.List[Chain] = field(default_factory=list)
    ledger_type: LedgerType = LedgerType.ETHEREUM
    safe_nonce: t.Optional[int] = None  # For cross-chain reusability

    _file = ledger_type.config_file
    _key = ledger_type.key_file
    _crypto_cls = EthereumCrypto

    def _transfer_from_eoa(
        self, to: str, amount: int, chain: Chain, rpc: t.Optional[str] = None
    ) -> t.Optional[str]:
        """Transfer funds from EOA wallet."""
        ledger_api = t.cast(EthereumApi, self.ledger_api(chain=chain, rpc=rpc))
        tx_helper = TxSettler(
            ledger_api=ledger_api,
            crypto=self.crypto,
            chain_type=ChainProfile.CUSTOM,
            timeout=ON_CHAIN_INTERACT_TIMEOUT,
            retries=ON_CHAIN_INTERACT_RETRIES,
            sleep=ON_CHAIN_INTERACT_SLEEP,
        )

        def _build_tx(  # pylint: disable=unused-argument
            *args: t.Any, **kwargs: t.Any
        ) -> t.Dict:
            """Build transaction"""
            max_priority_fee_per_gas = os.getenv("MAX_PRIORITY_FEE_PER_GAS", None)
            max_fee_per_gas = os.getenv("MAX_FEE_PER_GAS", None)
            tx = ledger_api.get_transfer_transaction(
                sender_address=self.crypto.address,
                destination_address=to,
                amount=amount,
                tx_fee=50000,
                tx_nonce="0x",
                chain_id=chain.id,
                raise_on_try=True,
                max_fee_per_gas=int(max_fee_per_gas) if max_fee_per_gas else None,
                max_priority_fee_per_gas=(
                    int(max_priority_fee_per_gas) if max_priority_fee_per_gas else None
                ),
            )
            return ledger_api.update_with_gas_estimate(
                transaction=tx,
                raise_on_try=True,
            )

        setattr(tx_helper, "build", _build_tx)  # noqa: B010
        tx_receipt = tx_helper.transact(lambda x: x, "", kwargs={})
        tx_hash = tx_receipt.get("transactionHash", "").hex()
        return tx_hash

    def _transfer_from_safe(
        self, to: str, amount: int, chain: Chain, rpc: t.Optional[str] = None
    ) -> t.Optional[str]:
        """Transfer funds from safe wallet."""
        if self.safes is None:
            raise ValueError("Safes not initialized")

        return transfer_from_safe(
            ledger_api=self.ledger_api(chain=chain, rpc=rpc),
            crypto=self.crypto,
            safe=t.cast(str, self.safes[chain]),
            to=to,
            amount=amount,
        )

    def _transfer_erc20_from_safe(
        self,
        token: str,
        to: str,
        amount: int,
        chain: Chain,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer erc20 from safe wallet."""
        if self.safes is None:
            raise ValueError("Safes not initialized")

        return transfer_erc20_from_safe(
            ledger_api=self.ledger_api(chain=chain, rpc=rpc),
            crypto=self.crypto,
            token=token,
            safe=t.cast(str, self.safes[chain]),  # type: ignore
            to=to,
            amount=amount,
        )

    def _transfer_erc20_from_eoa(
        self,
        token: str,
        to: str,
        amount: int,
        chain: Chain,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer erc20 from EOA wallet."""
        wallet_address = self.address
        ledger_api = t.cast(EthereumApi, self.ledger_api(chain=chain, rpc=rpc))
        tx_settler = TxSettler(
            ledger_api=ledger_api,
            crypto=self.crypto,
            chain_type=ChainProfile.CUSTOM,
            timeout=ON_CHAIN_INTERACT_TIMEOUT,
            retries=ON_CHAIN_INTERACT_RETRIES,
            sleep=ON_CHAIN_INTERACT_SLEEP,
        )

        def _build_transfer_tx(  # pylint: disable=unused-argument
            *args: t.Any, **kargs: t.Any
        ) -> t.Dict:
            # TODO Backport to OpenAEA
            instance = registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=token,
            )
            tx = instance.functions.transfer(to, amount).build_transaction(
                {
                    "from": wallet_address,
                    "gas": 1,
                    "gasPrice": ledger_api.api.eth.gas_price,
                    "nonce": ledger_api.api.eth.get_transaction_count(wallet_address),
                }
            )
            return ledger_api.update_with_gas_estimate(
                transaction=tx,
                raise_on_try=False,
            )

        setattr(tx_settler, "build", _build_transfer_tx)  # noqa: B010
        tx_receipt = tx_settler.transact(lambda x: x, "", kwargs={})
        tx_hash = tx_receipt.get("transactionHash", "").hex()
        return tx_hash

    def transfer(
        self,
        to: str,
        amount: int,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer funds to the given account."""
        if amount <= 0:
            return None

        if from_safe:
            sender = t.cast(str, self.safes[chain])
            sender_str = f"Safe {sender}"
        else:
            sender = self.crypto.address
            sender_str = f"EOA {sender}"

        ledger_api = self.ledger_api(chain=chain, rpc=rpc)
        to = ledger_api.api.to_checksum_address(to)
        balance = ledger_api.get_balance(address=sender)

        if balance < amount:
            raise InsufficientFundsException(
                f"Cannot transfer {amount} native units from {sender_str} to {to} on chain {chain.value.capitalize()}. "
                f"Balance of {sender_str} is {balance} native units on chain {chain.value.capitalize()}."
            )

        if from_safe:
            return self._transfer_from_safe(
                to=to,
                amount=amount,
                chain=chain,
                rpc=rpc,
            )
        return self._transfer_from_eoa(
            to=to,
            amount=amount,
            chain=chain,
            rpc=rpc,
        )

    # pylint: disable=too-many-arguments
    def transfer_erc20(
        self,
        token: str,
        to: str,
        amount: int,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer funds to the given account."""
        if amount <= 0:
            return None

        if from_safe:
            sender = t.cast(str, self.safes[chain])
            sender_str = f"Safe {sender}"
        else:
            sender = self.crypto.address
            sender_str = f"EOA {sender}"

        ledger_api = self.ledger_api(chain=chain, rpc=rpc)
        to = ledger_api.api.to_checksum_address(to)
        balance = (
            registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=token,
            )
            .functions.balanceOf(sender)
            .call()
        )

        tokens = {OLAS[chain]: "OLAS", USDC[chain]: "USDC"}
        token_name = tokens.get(token, token)

        if balance < amount:
            raise InsufficientFundsException(
                f"Cannot transfer {amount} {token_name} from {sender_str} to {to} on chain {chain.value.capitalize()}. "
                f"Balance of {sender_str} is {balance} {token_name} on chain {chain.value.capitalize()}."
            )

        if from_safe:
            return self._transfer_erc20_from_safe(
                token=token,
                to=to,
                amount=amount,
                chain=chain,
                rpc=rpc,
            )
        return self._transfer_erc20_from_eoa(
            token=token,
            to=to,
            amount=amount,
            chain=chain,
            rpc=rpc,
        )

    def transfer_asset(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: str = ZERO_ADDRESS,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """
        Transfer assets to the given account.

        If asset is a zero address, transfer native currency.
        """
        if asset == ZERO_ADDRESS:
            return self.transfer(
                to=to,
                amount=amount,
                chain=chain,
                from_safe=from_safe,
                rpc=rpc,
            )
        return self.transfer_erc20(
            token=asset,
            to=to,
            amount=amount,
            chain=chain,
            from_safe=from_safe,
            rpc=rpc,
        )

    def drain(
        self,
        withdrawal_address: str,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> None:
        """Drain all erc20/native assets to the given account."""

        ledger_api = self.ledger_api(chain=chain, rpc=rpc)
        assets = {token[chain] for token in ERC20_TOKENS}

        if from_safe:
            assets.add(ZERO_ADDRESS)

        for asset in assets:
            balance = get_asset_balance(
                ledger_api=ledger_api,
                asset_address=asset,
                address=self.safes[chain] if from_safe else self.crypto.address,
            )
            if balance <= 0:
                continue

            self.transfer_asset(
                to=withdrawal_address,
                amount=balance,
                chain=chain,
                asset=asset,
                from_safe=from_safe,
                rpc=rpc,
            )

        if not from_safe:
            drain_eoa(
                ledger_api=ledger_api,
                crypto=self.crypto,
                withdrawal_address=withdrawal_address,
                chain_id=chain.id,
            )

    @classmethod
    def new(
        cls, password: str, path: Path
    ) -> t.Tuple["EthereumMasterWallet", t.List[str]]:
        """Create a new master wallet."""
        # Backport support on aea

        eoa_wallet_path = path / cls._key
        if eoa_wallet_path.exists():
            raise FileExistsError(f"Wallet file already exists at {eoa_wallet_path}.")

        account = Account()
        account.enable_unaudited_hdwallet_features()
        crypto, mnemonic = account.create_with_mnemonic()
        eoa_wallet_path.write_text(
            data=json.dumps(
                Account.encrypt(
                    private_key=crypto._private_key,  # pylint: disable=protected-access
                    password=password,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )

        # Create wallet
        wallet = EthereumMasterWallet(path=path, address=crypto.address, safe_chains=[])
        wallet.store()
        wallet.password = password
        return wallet, mnemonic.split()

    def update_password(self, new_password: str) -> None:
        """Updates password."""
        create_backup(self.path / self._key)
        self._crypto = None
        (self.path / self._key).write_text(
            data=json.dumps(
                Account.encrypt(
                    private_key=self.crypto.private_key,  # pylint: disable=protected-access
                    password=new_password,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        self.password = new_password

    def is_mnemonic_valid(self, mnemonic: str) -> bool:
        """Verifies if the provided BIP-39 mnemonic is valid."""
        try:
            w3 = Web3()
            w3.eth.account.enable_unaudited_hdwallet_features()
            new_account = w3.eth.account.from_mnemonic(mnemonic)
            keystore_data = json.loads(
                Path(self.path / self._key).read_text(encoding="utf-8")
            )
            stored_address = keystore_data["address"].removeprefix("0x").lower()
            return stored_address == new_account.address.removeprefix("0x").lower()
        except Exception:  # pylint: disable=broad-except
            return False

    def update_password_with_mnemonic(self, mnemonic: str, new_password: str) -> None:
        """Updates password using the mnemonic."""
        if not self.is_mnemonic_valid(mnemonic):
            raise ValueError("The provided mnemonic is not valid")

        path = self.path / EthereumMasterWallet._key
        create_backup(path)

        w3 = Web3()
        w3.eth.account.enable_unaudited_hdwallet_features()
        crypto = Web3().eth.account.from_mnemonic(mnemonic)
        (path).write_text(
            data=json.dumps(
                Account.encrypt(
                    private_key=crypto._private_key,  # pylint: disable=protected-access
                    password=new_password,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        self.password = new_password

    def create_safe(
        self,
        chain: Chain,
        backup_owner: t.Optional[str] = None,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Create safe."""
        if chain in self.safe_chains:
            return None
        safe, self.safe_nonce, tx_hash = create_gnosis_safe(
            ledger_api=self.ledger_api(chain=chain, rpc=rpc),
            crypto=self.crypto,
            backup_owner=backup_owner,
            salt_nonce=self.safe_nonce,
        )
        self.safe_chains.append(chain)
        if self.safes is None:
            self.safes = {}
        self.safes[chain] = safe
        self.store()
        return tx_hash

    def update_backup_owner(
        self,
        chain: Chain,
        backup_owner: t.Optional[str] = None,
        rpc: t.Optional[str] = None,
    ) -> bool:
        """Adds a backup owner if not present, or updates it by the provided backup owner. Setting a None backup owner will remove the current one, if any."""
        ledger_api = self.ledger_api(chain=chain, rpc=rpc)
        if chain not in self.safes:  # type: ignore
            raise ValueError(f"Safes not created for chain {chain}!")
        safe = t.cast(str, self.safes[chain])  # type: ignore
        owners = get_owners(ledger_api=ledger_api, safe=safe)

        if len(owners) > 2:
            raise RuntimeError(
                f"Safe {safe} on chain {chain} has more than 2 owners: {owners}."
            )

        if backup_owner == safe:
            raise ValueError("The Safe address cannot be set as the Safe backup owner.")

        if backup_owner == self.address:
            raise ValueError(
                "The master wallet cannot be set as the Safe backup owner."
            )

        owners.remove(self.address)
        old_backup_owner = owners[0] if owners else None

        if old_backup_owner == backup_owner:
            return False

        if not old_backup_owner and backup_owner:
            add_owner(
                ledger_api=ledger_api,
                safe=safe,
                owner=backup_owner,
                crypto=self.crypto,
            )
            return True
        if old_backup_owner and not backup_owner:
            remove_owner(
                ledger_api=ledger_api,
                safe=safe,
                owner=old_backup_owner,
                crypto=self.crypto,
                threshold=1,
            )
            return True
        if old_backup_owner and backup_owner:
            swap_owner(
                ledger_api=ledger_api,
                safe=safe,
                old_owner=old_backup_owner,
                new_owner=backup_owner,
                crypto=self.crypto,
            )
            return True

        return False

    @property
    def extended_json(self) -> t.Dict:
        """Get JSON representation with extended information (e.g., safe owners)."""
        rpc = None
        tokens = (OLAS, USDC)
        wallet_json = self.json

        if not self.safes:
            return wallet_json

        owner_sets = set()
        for chain, safe in self.safes.items():
            ledger_api = self.ledger_api(chain=chain, rpc=rpc)
            owners = get_owners(ledger_api=ledger_api, safe=safe)
            owners.remove(self.address)

            balances: t.Dict[str, int] = {}
            balances[ZERO_ADDRESS] = ledger_api.get_balance(safe) or 0
            for token in tokens:
                balance = (
                    registry_contracts.erc20.get_instance(
                        ledger_api=ledger_api,
                        contract_address=token[chain],
                    )
                    .functions.balanceOf(safe)
                    .call()
                )
                balances[token[chain]] = balance

            wallet_json["safes"][chain.value] = {
                wallet_json["safes"][chain.value]: {
                    "backup_owners": owners,
                    "balances": balances,
                }
            }
            owner_sets.add(frozenset(owners))

        wallet_json["extended_json"] = True
        wallet_json["consistent_safe_address"] = len(set(self.safes.values())) == 1
        wallet_json["consistent_backup_owner"] = len(owner_sets) == 1
        wallet_json["consistent_backup_owner_count"] = all(
            len(owner) == 1 for owner in owner_sets
        )
        return wallet_json

    @classmethod
    def load(cls, path: Path) -> "EthereumMasterWallet":
        """Load master wallet."""
        # TODO: This is a complex way to read the 'safes' dictionary.
        # The reason for that is that wallet.safes[chain] would fail
        # (for example in service manager) when passed a ChainType key.

        raw_ethereum_wallet = t.cast(EthereumMasterWallet, super().load(path))  # type: ignore
        safes = {}
        for chain, safe_address in raw_ethereum_wallet.safes.items():
            safes[Chain(chain)] = safe_address

        raw_ethereum_wallet.safes = safes
        return raw_ethereum_wallet

    @classmethod
    def migrate_format(cls, path: Path) -> bool:
        """Migrate the JSON file format if needed."""
        wallet_path = path / cls._file
        with open(wallet_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        migrated = False
        if "safes" not in data:
            safes = {}
            for chain in data["safe_chains"]:
                safes[chain] = data["safe"]
            data.pop("safe")
            data["safes"] = safes
            migrated = True

        old_to_new_chains = [
            "ethereum",
            "goerli",
            "gnosis",
            "solana",
            "optimism",
            "base",
            "mode",
        ]
        safe_chains = []
        for chain in data["safe_chains"]:
            if isinstance(chain, int):
                safe_chains.append(old_to_new_chains[chain])
                migrated = True
            else:
                safe_chains.append(chain)
        data["safe_chains"] = safe_chains

        if isinstance(data["ledger_type"], int):
            old_to_new_ledgers = [ledger_type.value for ledger_type in LedgerType]
            data["ledger_type"] = old_to_new_ledgers[data["ledger_type"]]
            migrated = True

        safes = {}
        for chain, address in data["safes"].items():
            if str(chain).isnumeric():
                safes[old_to_new_chains[int(chain)]] = address
                migrated = True
            else:
                safes[chain] = address
        data["safes"] = safes

        if "optimistic" in data.get("safes", {}):
            data["safes"]["optimism"] = data["safes"].pop("optimistic")
            migrated = True

        if "optimistic" in data.get("safe_chains"):
            data["safe_chains"] = [
                "optimism" if chain == "optimistic" else chain
                for chain in data["safe_chains"]
            ]
            migrated = True

        with open(wallet_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

        return migrated


LEDGER_TYPE_TO_WALLET_CLASS = {
    LedgerType.ETHEREUM: EthereumMasterWallet,
}


class MasterWalletManager:
    """Master wallet manager."""

    def __init__(
        self,
        path: Path,
        logger: logging.Logger,
        password: t.Optional[str] = None,
    ) -> None:
        """Initialize master wallet manager."""
        self.path = path
        self.logger = logger
        self._password = password

    @property
    def json(self) -> t.List[t.Dict]:
        """List of wallets"""
        return [wallet.json for wallet in self]

    @property
    def password(self) -> str:
        """Password string."""
        if self._password is None:
            raise ValueError("Password not set.")
        return self._password

    @password.setter
    def password(self, value: str) -> None:
        """Set password value."""
        self._password = value

    def setup(self) -> "MasterWalletManager":
        """Setup wallet manager."""
        self.path.mkdir(exist_ok=True)
        return self

    def create(self, ledger_type: LedgerType) -> t.Tuple[MasterWallet, t.List[str]]:
        """
        Create a master wallet

        :param ledger_type: Ledger type for the wallet.
        :return: Tuple of master wallet and mnemonic
        """
        if ledger_type == LedgerType.ETHEREUM:
            return EthereumMasterWallet.new(password=self.password, path=self.path)
        raise ValueError(f"{ledger_type} is not supported.")

    def exists(self, ledger_type: LedgerType) -> bool:
        """
        Check if a wallet exists or not

        :param ledger_type: Ledger type for the wallet.
        :return: True if wallet exists, False otherwise.
        """
        return (self.path / ledger_type.config_file).exists() and (
            self.path / ledger_type.key_file
        ).exists()

    def load(self, ledger_type: LedgerType) -> MasterWallet:
        """
        Load master wallet

        :param ledger_type: Ledger type for the wallet.
        :return: Master wallet object
        """
        if ledger_type == LedgerType.ETHEREUM:
            wallet = EthereumMasterWallet.load(path=self.path)
        else:
            raise ValueError(f"{ledger_type} is not supported.")
        wallet.password = self.password
        return wallet

    def is_password_valid(self, password: str) -> bool:
        """Verifies if the provided password is valid."""
        for wallet in self:
            if not wallet.is_password_valid(password):
                return False

        return True

    def update_password(self, new_password: str) -> None:
        """Updates password of manager and wallets."""
        for wallet in self:
            wallet.password = self.password
            wallet.update_password(new_password)

        self.password = new_password

    def is_mnemonic_valid(self, mnemonic: str) -> bool:
        """Verifies if the provided BIP-39 mnemonic is valid."""
        for wallet in self:
            if not wallet.is_mnemonic_valid(mnemonic):
                return False
        return True

    def update_password_with_mnemonic(self, mnemonic: str, new_password: str) -> None:
        """Updates password using the mnemonic."""
        for wallet in self:
            wallet.update_password_with_mnemonic(mnemonic, new_password)

        self.password = new_password

    def __iter__(self) -> t.Iterator[MasterWallet]:
        """Iterate over master wallets."""
        for ledger_type in LedgerType:
            if not self.exists(ledger_type=ledger_type):
                continue
            yield LEDGER_TYPE_TO_WALLET_CLASS[ledger_type].load(path=self.path)
