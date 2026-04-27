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
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

from aea.crypto.base import Crypto, LedgerApi
from aea.helpers.logging import setup_logger
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from autonomy.chain.base import registry_contracts
from autonomy.chain.tx import TxSettler
from web3 import Account, Web3

from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.ledger import (
    DEFAULT_GAS_ESTIMATE_MULTIPLIER,
    get_default_ledger_api,
    make_chain_ledger_api,
    update_tx_with_gas_estimate,
    update_tx_with_gas_pricing,
)
from operate.ledger.profiles import DUST, ERC20_TOKENS, format_asset_amount
from operate.operate_types import Chain, EncryptedData, LedgerType
from operate.resource import LocalResource
from operate.serialization import BigInt
from operate.utils import create_backup
from operate.utils.gnosis import (
    add_owner,
)
from operate.utils.gnosis import create_safe as create_gnosis_safe
from operate.utils.gnosis import (
    estimate_transfer_tx_fee,
    gas_fees_spent_in_tx,
    get_asset_balance,
    get_owners,
    remove_owner,
    swap_owner,
)
from operate.utils.gnosis import transfer as transfer_from_safe
from operate.utils.gnosis import (
    transfer_erc20_from_safe,
)

logger = setup_logger(name="master_wallet")


# TODO Organize exceptions definition
class InsufficientFundsException(Exception):
    """Insufficient funds exception."""


class MasterWallet(LocalResource):
    """Master wallet."""

    path: Path
    address: str
    safes: t.Dict[Chain, str]
    safe_chains: t.List[Chain]
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

    @classmethod
    def mnemonic_filename(cls) -> str:
        """Return deterministic mnemonic filename per ledger type."""
        return f"{cls.ledger_type.value.lower()}.mnemonic.json"

    @property
    def mnemonic_path(self) -> Path:
        """Mnemonic path."""
        return self.path / self.__class__.mnemonic_filename()

    @staticmethod
    def ledger_api(
        chain: Chain,
        rpc: t.Optional[str] = None,
    ) -> LedgerApi:
        """Get ledger api object."""
        if not rpc:
            return get_default_ledger_api(chain=chain)
        return make_chain_ledger_api(chain=chain, rpc=rpc)

    def transfer(  # pylint: disable=too-many-arguments
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: str = ZERO_ADDRESS,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer funds to the given account."""
        raise NotImplementedError()

    def transfer_from_safe_then_eoa(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: str = ZERO_ADDRESS,
        rpc: t.Optional[str] = None,
    ) -> t.List[str]:
        """Transfer assets to the given account using Safe balance first, and EOA balance for leftover."""
        raise NotImplementedError()

    def drain(
        self,
        withdrawal_address: str,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Dict[str, int]:
        """Drain all erc20/native assets to the given account.

        Returns a mapping of asset address to amount transferred.
        """
        raise NotImplementedError()

    @classmethod
    def new(cls, password: str, path: Path) -> t.Tuple["MasterWallet", t.List[str]]:
        """Create a new master wallet."""
        raise NotImplementedError()

    def decrypt_mnemonic(self, password: str) -> t.Optional[t.List[str]]:
        """Retrieve the mnemonic"""
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

    def get_balance(
        self,
        chain: Chain,
        asset: str = ZERO_ADDRESS,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> BigInt:
        """Get wallet balance on a given chain.

        Args:
            chain: The chain to check balance on
            asset: Asset address (ZERO_ADDRESS for native token)
            from_safe: Whether to check Safe balance (True) or EOA balance (False)
            rpc: Optional custom RPC endpoint. If not provided, uses default RPC.

        Returns:
            Balance as BigInt
        """
        if from_safe:
            if chain not in self.safes:
                raise ValueError(f"Wallet does not have a Safe on chain {chain}.")

            address = self.safes[chain]
        else:
            address = self.address

        # Use custom RPC if provided, otherwise fall back to default
        ledger_api = (
            make_chain_ledger_api(chain, rpc) if rpc else get_default_ledger_api(chain)
        )

        return get_asset_balance(
            ledger_api=ledger_api,
            asset_address=asset,
            address=address,
        )

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
class EthereumMasterWallet(
    MasterWallet
):  # pylint: disable=too-many-instance-attributes
    """Master wallet manager."""

    path: Path
    address: str

    safes: t.Dict[Chain, str] = field(default_factory=dict)
    safe_chains: t.List[Chain] = field(default_factory=list)
    ledger_type: LedgerType = LedgerType.ETHEREUM
    safe_nonce: t.Optional[int] = None  # For cross-chain reusability
    canonical_backup_owner: t.Optional[str] = (
        None  # Canonical backup owner across all chains
    )

    _file = ledger_type.config_file
    _key = ledger_type.key_file
    _crypto_cls = EthereumCrypto

    def _pre_transfer_checks(
        self,
        to: str,
        amount: int,
        chain: Chain,
        from_safe: bool,
        asset: str = ZERO_ADDRESS,
    ) -> str:
        """Checks conditions before transfer. Returns the to address checksummed."""
        if amount <= 0:
            raise ValueError(
                "Transfer amount must be greater than zero, not transferring."
            )

        to = Web3().to_checksum_address(to)
        if from_safe and chain not in self.safes:
            raise ValueError(f"Wallet does not have a Safe on chain {chain}.")

        balance = self.get_balance(chain=chain, asset=asset, from_safe=from_safe)
        if balance < amount:
            source = "Master Safe" if from_safe else " Master EOA"
            source_address = self.safes[chain] if from_safe else self.address
            raise InsufficientFundsException(
                f"Cannot transfer {format_asset_amount(chain, asset, amount)} from {source} {source_address} to {to} on chain {chain.name}. "
                f"Balance: {format_asset_amount(chain, asset, balance)}. Missing: {format_asset_amount(chain, asset, amount - balance)}."
            )

        return to

    def _transfer_from_eoa(
        self, to: str, amount: int, chain: Chain, rpc: t.Optional[str] = None
    ) -> str:
        """Transfer funds from EOA wallet."""
        balance = self.get_balance(chain=chain, from_safe=False)
        tx_fee = estimate_transfer_tx_fee(
            chain=chain, sender_address=self.address, to=to
        )
        if balance - tx_fee <= amount <= balance:
            # we assume that the user wants to drain the EOA
            # we also account for dust here because withdraw call use some EOA balance to drain the safes first
            amount = int(balance - tx_fee * DEFAULT_GAS_ESTIMATE_MULTIPLIER)
            if amount <= 0:
                logger.warning(
                    f"Not enough balance to cover gas fees for transfer of {amount} on chain {chain} from EOA {self.address}. "
                    f"Balance is {balance}, estimated fee is {tx_fee}. Not transferring."
                )
                return None

        to = self._pre_transfer_checks(
            to=to, amount=amount, chain=chain, from_safe=False
        )

        ledger_api = t.cast(EthereumApi, self.ledger_api(chain=chain, rpc=rpc))

        def _build_tx() -> t.Dict:
            """Build transaction"""
            tx = ledger_api.get_transfer_transaction(
                sender_address=self.crypto.address,
                destination_address=to,
                amount=amount,
                tx_fee=0,
                tx_nonce="0x",
                chain_id=chain.id,
                raise_on_try=True,
            )
            return ledger_api.update_with_gas_estimate(
                transaction=tx,
                raise_on_try=True,
            )

        return (
            TxSettler(
                ledger_api=ledger_api,
                crypto=self.crypto,
                chain_type=chain,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
                tx_builder=_build_tx,
            )
            .transact()
            .settle()
            .tx_hash
        )

    def _transfer_from_safe(
        self, to: str, amount: int, chain: Chain, rpc: t.Optional[str] = None
    ) -> t.Optional[str]:
        """Transfer funds from safe wallet."""
        to = self._pre_transfer_checks(
            to=to, amount=amount, chain=chain, from_safe=True
        )

        return transfer_from_safe(
            ledger_api=self.ledger_api(chain=chain, rpc=rpc),
            crypto=self.crypto,
            safe=self.safes[chain],
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
        to = self._pre_transfer_checks(
            to=to, amount=amount, chain=chain, from_safe=True, asset=token
        )

        return transfer_erc20_from_safe(
            ledger_api=self.ledger_api(chain=chain, rpc=rpc),
            crypto=self.crypto,
            token=token,
            safe=self.safes[chain],
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
    ) -> str:
        """Transfer erc20 from EOA wallet."""
        to = self._pre_transfer_checks(
            to=to, amount=amount, chain=chain, from_safe=False, asset=token
        )

        wallet_address = self.address
        ledger_api = t.cast(EthereumApi, self.ledger_api(chain=chain, rpc=rpc))

        def _build_transfer_tx() -> t.Dict:
            # TODO Backport to OpenAEA
            instance = registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=token,
            )
            tx = instance.functions.transfer(to, amount).build_transaction(
                {
                    "from": wallet_address,
                    "gas": 1,
                    "maxFeePerGas": 1,
                    "maxPriorityFeePerGas": 1,
                    "nonce": ledger_api.api.eth.get_transaction_count(wallet_address),
                }
            )
            update_tx_with_gas_pricing(tx, ledger_api)
            update_tx_with_gas_estimate(tx, ledger_api)
            return tx

        return (
            TxSettler(
                ledger_api=ledger_api,
                crypto=self.crypto,
                chain_type=chain,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
                tx_builder=_build_transfer_tx,
            )
            .transact()
            .settle()
            .tx_hash
        )

    def transfer(  # pylint: disable=too-many-arguments
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: str = ZERO_ADDRESS,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Optional[str]:
        """Transfer funds to the given account."""
        if from_safe:
            if asset == ZERO_ADDRESS:
                return self._transfer_from_safe(
                    to=to,
                    amount=amount,
                    chain=chain,
                    rpc=rpc,
                )

            return self._transfer_erc20_from_safe(
                token=asset,
                to=to,
                amount=amount,
                chain=chain,
                rpc=rpc,
            )

        if asset == ZERO_ADDRESS:
            return self._transfer_from_eoa(
                to=to,
                amount=amount,
                chain=chain,
                rpc=rpc,
            )

        return self._transfer_erc20_from_eoa(
            token=asset,
            to=to,
            amount=amount,
            chain=chain,
            rpc=rpc,
        )

    def transfer_from_safe_then_eoa(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: str = ZERO_ADDRESS,
        rpc: t.Optional[str] = None,
    ) -> t.List[str]:
        """
        Transfer assets to the given account using Safe balance first, and EOA balance for leftover.

        If asset is a zero address, transfer native currency.
        """
        safe_balance = self.get_balance(chain=chain, asset=asset, from_safe=True)
        eoa_balance = self.get_balance(chain=chain, asset=asset, from_safe=False)
        balance = safe_balance + eoa_balance
        if asset == ZERO_ADDRESS:
            # to account for gas fees burned in previous txs
            # in this case we will set the amount = eoa_balance below
            balance += DUST[chain]

        if balance < amount:
            raise InsufficientFundsException(
                f"Cannot transfer {format_asset_amount(chain, asset, amount)} to {to} on chain {chain.name}. "
                f"Balance of Master Safe {self.safes[chain]}: {format_asset_amount(chain, asset, safe_balance)}. "
                f"Balance of Master EOA {self.address}: {format_asset_amount(chain, asset, eoa_balance)}. "
                f"Missing: {format_asset_amount(chain, asset, amount - balance)}."
            )

        tx_hashes = []
        from_safe_amount = min(safe_balance, amount)
        if from_safe_amount > 0:
            tx_hash = self.transfer(
                to=to,
                amount=from_safe_amount,
                chain=chain,
                asset=asset,
                from_safe=True,
                rpc=rpc,
            )
            if tx_hash:
                tx_hashes.append(tx_hash)
        amount -= from_safe_amount

        # Subtract gas fees from remaining amount if this was a native currency transfer
        if from_safe_amount > 0 and asset == ZERO_ADDRESS and tx_hash:
            amount -= gas_fees_spent_in_tx(
                ledger_api=self.ledger_api(chain=chain, rpc=rpc),
                tx_hash=tx_hash,
            )

        if amount > 0:
            eoa_balance = self.get_balance(chain=chain, asset=asset, from_safe=False)
            if asset == ZERO_ADDRESS and eoa_balance <= amount:
                # to make the internal function drain the EOA
                amount = eoa_balance

            tx_hash = self.transfer(
                to=to, amount=amount, chain=chain, asset=asset, from_safe=False, rpc=rpc
            )
            if tx_hash:
                tx_hashes.append(tx_hash)

        return tx_hashes

    def drain(
        self,
        withdrawal_address: str,
        chain: Chain,
        from_safe: bool = True,
        rpc: t.Optional[str] = None,
    ) -> t.Dict[str, int]:
        """Drain all erc20/native assets to the given account.

        Returns a mapping of asset address to amount transferred.
        """
        assets = [token[chain] for token in ERC20_TOKENS.values() if chain in token] + [
            ZERO_ADDRESS
        ]
        moved: t.Dict[str, int] = {}
        for asset in assets:
            balance = self.get_balance(chain=chain, asset=asset, from_safe=from_safe)
            if balance <= 0:
                continue

            try:
                self.transfer(
                    to=withdrawal_address,
                    amount=balance,
                    chain=chain,
                    asset=asset,
                    from_safe=from_safe,
                    rpc=rpc,
                )
                moved[asset] = int(balance)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to transfer asset %s on chain %s: %s",
                    asset,
                    chain,
                    str(exc),
                )

        return moved

    @classmethod
    def new(
        cls, password: str, path: Path
    ) -> t.Tuple["EthereumMasterWallet", t.List[str]]:
        """Create a new master wallet."""
        # Backport support on aea

        eoa_wallet_path = path / cls._key
        eoa_mnemonic_path = path / cls.mnemonic_filename()

        if eoa_wallet_path.exists():
            raise FileExistsError(f"Wallet file already exists at {eoa_wallet_path}.")

        if eoa_mnemonic_path.exists():
            raise FileExistsError(
                f"Mnemonic file already exists at {eoa_mnemonic_path}."
            )

        eoa_wallet_path.parent.mkdir(parents=True, exist_ok=True)

        # Store private key (Ethereum V3 keystore JSON) and encrypted mnemonic
        account = Account()
        account.enable_unaudited_hdwallet_features()
        crypto, mnemonic = account.create_with_mnemonic()
        encrypted_mnemonic = EncryptedData.new(
            path=eoa_mnemonic_path, password=password, plaintext_bytes=mnemonic.encode()
        )
        encrypted_mnemonic.store()
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

    @classmethod
    def import_from_mnemonic(
        cls, mnemonic: str, password: str, path: Path
    ) -> t.Tuple["EthereumMasterWallet", t.List[str]]:
        """Import a wallet from a BIP-39 mnemonic.

        SECURITY: The mnemonic and derived private key are never persisted beyond
        the encrypted keystore files.  The plain-text private key only exists in
        memory for the duration of this call.
        """
        eoa_wallet_path = path / cls._key
        eoa_mnemonic_path = path / cls.mnemonic_filename()

        if eoa_wallet_path.exists():
            raise FileExistsError(f"Wallet file already exists at {eoa_wallet_path}.")

        if eoa_mnemonic_path.exists():
            raise FileExistsError(
                f"Mnemonic file already exists at {eoa_mnemonic_path}."
            )

        eoa_wallet_path.parent.mkdir(parents=True, exist_ok=True)

        w3 = Web3()
        w3.eth.account.enable_unaudited_hdwallet_features()
        account = w3.eth.account.from_mnemonic(mnemonic)

        encrypted_mnemonic = EncryptedData.new(
            path=eoa_mnemonic_path,
            password=password,
            plaintext_bytes=mnemonic.encode(),
        )
        encrypted_mnemonic.store()

        eoa_wallet_path.write_text(
            data=json.dumps(
                Account.encrypt(
                    private_key=account._private_key,  # pylint: disable=protected-access
                    password=password,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )

        wallet = EthereumMasterWallet(
            path=path, address=account.address, safe_chains=[]
        )
        wallet.store()
        wallet.password = password
        return wallet, mnemonic.split()

    def decrypt_mnemonic(self, password: str) -> t.Optional[t.List[str]]:
        """Retrieve the mnemonic"""
        if not self.mnemonic_path.exists():
            return None

        encrypted_mnemonic = EncryptedData.load(self.mnemonic_path)
        mnemonic = encrypted_mnemonic.decrypt(password).decode("utf-8")
        return mnemonic.split()

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
        tx_hash = None
        ledger_api = self.ledger_api(chain=chain, rpc=rpc)
        if self.safes is None:
            self.safes = {}

        if chain not in self.safe_chains and chain not in self.safes:
            safe, self.safe_nonce, tx_hash = create_gnosis_safe(
                ledger_api=ledger_api,
                crypto=self.crypto,
                salt_nonce=self.safe_nonce,
            )
            self.safe_chains.append(chain)
            self.safes[chain] = safe
            self.store()

        # Prefer explicitly provided backup_owner; fall back to canonical
        effective_backup_owner = (
            backup_owner if backup_owner is not None else self.canonical_backup_owner
        )
        if effective_backup_owner is not None:
            add_owner(
                ledger_api=ledger_api,
                crypto=self.crypto,
                safe=self.safes[chain],
                owner=effective_backup_owner,
            )

        return tx_hash

    def update_backup_owner(
        self,
        chain: Chain,
        backup_owner: t.Optional[str] = None,
        rpc: t.Optional[str] = None,
    ) -> bool:
        """Adds a backup owner if not present, or updates it by the provided backup owner. Setting a None backup owner will remove the current one, if any."""
        ledger_api = self.ledger_api(chain=chain, rpc=rpc)
        if chain not in self.safes:
            raise ValueError(f"Wallet does not have a Safe on chain {chain}.")
        safe = t.cast(str, self.safes[chain])
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

        if self.address not in owners:
            return False

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

        return False  # pragma: no cover

    def sync_backup_owner(self) -> t.Dict:
        """Sync the canonical backup owner to all chains that diverge from it.

        Only updates chains whose current on-chain backup owner differs from
        ``self.canonical_backup_owner``.  Chains without a Safe are skipped.

        Returns a dict with keys:
            - ``canonical_backup_owner`` (str): the canonical address used.
            - ``results`` (list): per-chain result dicts.
            - ``all_succeeded`` (bool): True when every attempted update succeeded.
        """
        if not self.canonical_backup_owner:
            raise ValueError("No canonical backup owner is set.")

        results = []
        all_succeeded = True
        for chain, safe in self.safes.items():
            ledger_api = self.ledger_api(chain=chain)
            owners = get_owners(ledger_api=ledger_api, safe=safe)
            current_owners = [o for o in owners if o != self.address]

            if self.canonical_backup_owner in current_owners:
                results.append(
                    {
                        "chain": chain.value,
                        "updated": False,
                        "message": "Already in sync",
                    }
                )
                continue

            try:
                self.update_backup_owner(
                    chain=chain,
                    backup_owner=self.canonical_backup_owner,
                )
                results.append(
                    {
                        "chain": chain.value,
                        "updated": True,
                        "message": "Synced successfully",
                    }
                )
            except Exception as exc:  # pylint: disable=broad-except
                results.append(
                    {
                        "chain": chain.value,
                        "updated": False,
                        "message": f"Failed: {exc}",
                    }
                )
                all_succeeded = False

        return {
            "canonical_backup_owner": self.canonical_backup_owner,
            "results": results,
            "all_succeeded": all_succeeded,
        }

    def backup_owner_status(self) -> t.Dict:
        """Return per-chain backup owner status relative to the canonical value.

        Returns a dict with keys:
            - ``canonical_backup_owner`` (str | None)
            - ``all_chains_synced`` (bool): True when every Safe's backup matches
              the canonical.
            - ``any_backup_missing`` (bool): True when at least one Safe has no
              backup owner at all (on-chain owners list has no entry besides the
              master EOA).
            - ``existing_backup_on_any_chain`` (bool): True when at least one Safe
              has any backup owner set on-chain, even if ``canonical_backup_owner``
              is not yet set.  Lets the frontend distinguish "never had a backup"
              from "had one but canonical not yet assigned".
            - ``chains`` (list): per-chain status dicts, each with ``is_synced``.
            - ``chains_without_safe`` (list): chain values for chains in
              ``safe_chains`` that don't have a safe address yet.
        """
        chains_status = []
        chains_without_safe = []
        all_chains_synced = True
        any_backup_missing = False
        existing_backup_on_any_chain = False

        for chain in self.safe_chains:
            if chain not in self.safes:
                chains_without_safe.append(chain.value)
                continue

            safe = self.safes[chain]
            ledger_api = self.ledger_api(chain=chain)
            owners = get_owners(ledger_api=ledger_api, safe=safe)
            backup_owners = [o for o in owners if o != self.address]
            current_backup = backup_owners[0] if backup_owners else None

            is_synced = self.canonical_backup_owner in backup_owners
            if not is_synced:
                all_chains_synced = False
            if not backup_owners:
                any_backup_missing = True
            else:
                existing_backup_on_any_chain = True

            chains_status.append(
                {
                    "chain": chain.value,
                    "safe": safe,
                    "current_backup_owner": current_backup,
                    "is_synced": is_synced,
                }
            )

        return {
            "canonical_backup_owner": self.canonical_backup_owner,
            "all_chains_synced": all_chains_synced,
            "any_backup_missing": any_backup_missing,
            "existing_backup_on_any_chain": existing_backup_on_any_chain,
            "chains": chains_status,
            "chains_without_safe": chains_without_safe,
        }

    @property
    def extended_json(self) -> t.Dict:
        """Get JSON representation with extended information (e.g., safe owners)."""
        rpc = None
        wallet_json = self.json

        balances: t.Dict[str, t.Dict[str, t.Dict[str, BigInt]]] = {}
        owner_sets = set()
        for chain, safe in self.safes.items():
            chain_str = chain.value
            ledger_api = self.ledger_api(chain=chain, rpc=rpc)
            owners = get_owners(ledger_api=ledger_api, safe=safe)

            if self.address in owners:
                owners.remove(self.address)

            balances[chain_str] = {self.address: {}, safe: {}}

            assets = [
                token[chain] for token in ERC20_TOKENS.values() if chain in token
            ] + [ZERO_ADDRESS]
            for asset in assets:
                balances[chain_str][self.address][asset] = str(
                    self.get_balance(chain=chain, asset=asset, from_safe=False)
                )
                balances[chain_str][safe][asset] = str(
                    self.get_balance(chain=chain, asset=asset, from_safe=True)
                )
            wallet_json["safes"][chain_str] = {
                safe: {
                    "backup_owners": owners,
                    "balances": balances[chain_str][safe],
                }
            }
            owner_sets.add(frozenset(owners))

        wallet_json["balances"] = balances
        wallet_json["extended_json"] = True
        wallet_json["all_safes_have_backup_owner"] = all(
            len(owners) > 0 for owners in owner_sets
        )
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
    def _infer_canonical_backup_owner(cls, data: t.Dict) -> t.Optional[str]:
        """Infer a shared backup owner when every Safe matches the same topology."""
        master_eoa_address = data["address"]
        backup_owners = set()
        all_safes_valid = True

        for chain, safe in data["safes"].items():
            chain_type = Chain(chain)
            ledger_api = get_default_ledger_api(chain=chain_type)
            owners = get_owners(ledger_api=ledger_api, safe=safe)
            if master_eoa_address not in owners:
                all_safes_valid = False
                continue

            non_master_owners = [
                owner for owner in owners if owner != master_eoa_address
            ]
            if len(non_master_owners) != 1:
                all_safes_valid = False
                continue

            backup_owners.add(non_master_owners[0])

        if not all_safes_valid or len(backup_owners) != 1:
            return None

        return next(iter(backup_owners))

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

        if "canonical_backup_owner" not in data:
            try:
                data["canonical_backup_owner"] = cls._infer_canonical_backup_owner(
                    data=data
                )
            except Exception:  # pylint: disable=broad-except
                data["canonical_backup_owner"] = None
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
        password: t.Optional[str] = None,
    ) -> None:
        """Initialize master wallet manager."""
        self.path = path
        self._password = password

    @property
    def json(self) -> t.List[t.Dict]:
        """List of wallets"""
        return [wallet.json for wallet in self]

    @property
    def password(self) -> t.Optional[str]:
        """Password string."""
        if self._password is None:
            raise ValueError("Password not set.")
        return self._password

    @password.setter
    def password(self, value: t.Optional[str]) -> None:
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

    def import_from_mnemonic(
        self, ledger_type: LedgerType, mnemonic: str
    ) -> t.Tuple[MasterWallet, t.List[str]]:
        """
        Import a wallet from a BIP-39 mnemonic.

        Derives the Ethereum address from *mnemonic* and writes the encrypted
        keystores into this manager's ``path``.  The password currently set on
        this manager is used to encrypt the key material.

        :param ledger_type: Ledger type (only ``LedgerType.ETHEREUM`` supported).
        :param mnemonic: BIP-39 seed phrase (12, 15, 18, 21, or 24 words).
        :return: Tuple of (wallet, mnemonic word list).
        :raises ValueError: If ledger type is not supported.
        """
        if ledger_type == LedgerType.ETHEREUM:
            return EthereumMasterWallet.import_from_mnemonic(
                mnemonic=mnemonic,
                password=self.password,
                path=self.path,
            )
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

    @staticmethod
    def is_valid_bip39_mnemonic(mnemonic: str) -> bool:
        """Check that *mnemonic* is a syntactically valid BIP-39 phrase.

        This validates only word count and derivability — it does NOT cross-check
        against an existing stored key.  Use this for the fund-recovery flow where
        no Pearl account may exist on the current device.
        """
        try:
            w3 = Web3()
            w3.eth.account.enable_unaudited_hdwallet_features()
            w3.eth.account.from_mnemonic(mnemonic)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

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
