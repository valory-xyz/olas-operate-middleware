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

"""Safe helpers."""

import binascii
import itertools
import secrets
import typing as t
from enum import Enum

from aea.crypto.base import Crypto, LedgerApi
from aea.helpers.logging import setup_logger
from autonomy.chain.base import registry_contracts
from autonomy.chain.exceptions import ChainInteractionError
from autonomy.chain.tx import TxSettler
from web3 import Web3
from web3.exceptions import ContractLogicError

from operate.constants import (
    ON_CHAIN_INTERACT_RETRIES,
    ON_CHAIN_INTERACT_SLEEP,
    ON_CHAIN_INTERACT_TIMEOUT,
    ZERO_ADDRESS,
)
from operate.exceptions import InsufficientFundsException
from operate.ledger import (
    DEFAULT_GAS_ESTIMATE_MULTIPLIER,
    EOA_DRAIN_RETRY_GAS_MULTIPLIER_STEP,
    get_default_ledger_api,
    is_gas_spike_error,
    update_tx_with_gas_estimate,
    update_tx_with_gas_pricing,
)
from operate.operate_types import Chain
from operate.serialization import BigInt
from operate.utils.gas import wrap_gas_spike_as_insufficient_funds

logger = setup_logger(name="operate.utils.gnosis")
MAX_UINT256 = 2**256 - 1
SENTINEL_OWNERS = "0x0000000000000000000000000000000000000001"

# Bounded gas-limit fallback for an EOA ERC20 transfer when eth_estimateGas
# cannot produce an estimate (e.g. some RPC providers / forks where the
# gas-estimate fallback addresses hold no balance, so the binary search hits
# the balance allowance cap). Comfortably covers a standard ERC20 transfer
# (~37-65k gas), and stays within the native budget that
# ``FundingManager.drain_agents_eoas`` pre-checks before draining (3 × a native
# transfer per ERC20). Unused gas is refunded, so over-provisioning the limit
# is free.
_ERC20_TRANSFER_GAS_FALLBACK = 65_000


class SafeOperation(Enum):
    """Operation types."""

    CALL = 0
    DELEGATE_CALL = 1
    CREATE = 2


class MultiSendOperation(Enum):
    """Operation types."""

    CALL = 0
    DELEGATE_CALL = 1


class Transfer(t.NamedTuple):
    """A single transfer instruction; ``asset == ZERO_ADDRESS`` is native."""

    to: str
    asset: str
    amount: int


class BatchResult(t.NamedTuple):
    """Result of a batched Safe transfer.

    ``sent`` lists the transfers that were actually executed (pre-filtered
    entries excluded); empty with ``tx_hash is None`` when nothing survived.
    """

    tx_hash: t.Optional[str]
    sent: t.List[Transfer]


class _MultiSendSubTxRequired(t.TypedDict):
    """Required fields of a MultiSend sub-transaction."""

    to: str


class MultiSendSubTx(_MultiSendSubTxRequired, total=False):
    """A single sub-transaction of a MultiSend batch.

    ``to`` is required (the MultiSend encoder and ``simulate_safe_sub_tx``
    both subscript it unguarded); the rest default at the call sites.
    """

    value: int
    data: t.Union[str, bytes]
    operation: MultiSendOperation


def hash_payload_to_hex(  # pylint: disable=too-many-arguments,too-many-locals
    safe_tx_hash: str,
    ether_value: int,
    safe_tx_gas: int,
    to_address: str,
    data: bytes,
    operation: int = SafeOperation.CALL.value,
    base_gas: int = 0,
    safe_gas_price: int = 0,
    gas_token: str = ZERO_ADDRESS,
    refund_receiver: str = ZERO_ADDRESS,
    use_flashbots: bool = False,
    gas_limit: int = 0,
    raise_on_failed_simulation: bool = False,
) -> str:
    """Serialise to a hex string."""
    if len(safe_tx_hash) != 64:  # should be exactly 32 bytes!
        raise ValueError(
            "cannot encode safe_tx_hash of non-32 bytes"
        )  # pragma: nocover

    if len(to_address) != 42 or len(gas_token) != 42 or len(refund_receiver) != 42:
        raise ValueError("cannot encode address of non 42 length")  # pragma: nocover

    if (
        ether_value > MAX_UINT256
        or safe_tx_gas > MAX_UINT256
        or base_gas > MAX_UINT256
        or safe_gas_price > MAX_UINT256
        or gas_limit > MAX_UINT256
    ):
        raise ValueError(
            "Value is bigger than the max 256 bit value"
        )  # pragma: nocover

    if operation not in [v.value for v in SafeOperation]:
        raise ValueError("SafeOperation value is not valid")  # pragma: nocover

    if not isinstance(use_flashbots, bool):
        raise ValueError(
            f"`use_flashbots` value ({use_flashbots}) is not valid. A boolean value was expected instead"
        )

    ether_value_ = ether_value.to_bytes(32, "big").hex()
    safe_tx_gas_ = safe_tx_gas.to_bytes(32, "big").hex()
    operation_ = operation.to_bytes(1, "big").hex()
    base_gas_ = base_gas.to_bytes(32, "big").hex()
    safe_gas_price_ = safe_gas_price.to_bytes(32, "big").hex()
    use_flashbots_ = use_flashbots.to_bytes(32, "big").hex()
    gas_limit_ = gas_limit.to_bytes(32, "big").hex()
    raise_on_failed_simulation_ = raise_on_failed_simulation.to_bytes(32, "big").hex()

    concatenated = (
        safe_tx_hash
        + ether_value_
        + safe_tx_gas_
        + to_address
        + operation_
        + base_gas_
        + safe_gas_price_
        + gas_token
        + refund_receiver
        + use_flashbots_
        + gas_limit_
        + raise_on_failed_simulation_
        + data.hex()
    )
    return concatenated


def skill_input_hex_to_payload(payload: str) -> dict:
    """Decode payload."""
    tx_params = dict(
        safe_tx_hash=payload[:64],
        ether_value=int.from_bytes(bytes.fromhex(payload[64:128]), "big"),
        safe_tx_gas=int.from_bytes(bytes.fromhex(payload[128:192]), "big"),
        to_address=payload[192:234],
        operation=int.from_bytes(bytes.fromhex(payload[234:236]), "big"),
        base_gas=int.from_bytes(bytes.fromhex(payload[236:300]), "big"),
        safe_gas_price=int.from_bytes(bytes.fromhex(payload[300:364]), "big"),
        gas_token=payload[364:406],
        refund_receiver=payload[406:448],
        use_flashbots=bool.from_bytes(bytes.fromhex(payload[448:512]), "big"),
        gas_limit=int.from_bytes(bytes.fromhex(payload[512:576]), "big"),
        raise_on_failed_simulation=bool.from_bytes(
            bytes.fromhex(payload[576:640]), "big"
        ),
        data=bytes.fromhex(payload[640:]),
    )
    return tx_params


def _get_nonce() -> int:
    """Generate a nonce for the Safe deployment."""
    return secrets.SystemRandom().randint(0, 2**256 - 1)


def create_safe(
    ledger_api: LedgerApi,
    crypto: Crypto,
    salt_nonce: t.Optional[int] = None,
) -> t.Tuple[str, int, str]:
    """Create gnosis safe."""
    salt_nonce = salt_nonce or _get_nonce()

    def _build() -> t.Dict:
        tx = registry_contracts.gnosis_safe.get_deploy_transaction(
            ledger_api=ledger_api,
            deployer_address=crypto.address,
            owners=([crypto.address]),
            threshold=1,
            salt_nonce=salt_nonce,
        )
        del tx["contract_address"]
        return tx

    chain = Chain.from_id(ledger_api._chain_id)  # pylint: disable=protected-access
    with wrap_gas_spike_as_insufficient_funds(
        chain.value, "create Safe", ledger_api=ledger_api, signer_address=crypto.address
    ):
        tx_settler = (
            TxSettler(
                ledger_api=ledger_api,
                crypto=crypto,
                chain_type=chain,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
                gas_price_multiplier=(
                    1.125 if chain == Chain.POLYGON else 1.0
                ),  # TODO: remove after safe creation failure is recoverable
                tx_builder=_build,
            )
            .transact()
            .settle()
        )
    (event,) = tx_settler.get_events(
        contract=registry_contracts.gnosis_safe_proxy_factory.get_instance(
            ledger_api=ledger_api,
            contract_address="0xa6b71e26c5e0845f74c812102ca7114b6a896ab2",
        ),
        event_name="ProxyCreation",
    )
    safe_address = event["args"]["proxy"]
    return safe_address, salt_nonce, tx_settler.tx_hash


def get_owners(ledger_api: LedgerApi, safe: str) -> t.List[str]:
    """Get list of owners."""
    return registry_contracts.gnosis_safe.get_owners(
        ledger_api=ledger_api,
        contract_address=safe,
    ).get("owners", [])


def send_safe_txs(
    txd: bytes,
    safe: str,
    ledger_api: LedgerApi,
    crypto: Crypto,
    to: t.Optional[str] = None,
) -> str:
    """Send internal safe transaction."""
    owner = ledger_api.api.to_checksum_address(
        crypto.address,
    )
    to_address = to or safe

    def _build_tx() -> t.Optional[str]:
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=ledger_api,
            contract_address=safe,
            value=0,
            safe_tx_gas=0,
            to_address=to_address,
            data=txd,
            operation=SafeOperation.CALL.value,
        ).get("tx_hash")
        safe_tx_bytes = binascii.unhexlify(
            safe_tx_hash[2:],
        )
        signatures = {
            owner: crypto.sign_message(
                message=safe_tx_bytes,
                is_deprecated_mode=True,
            )[2:]
        }
        return registry_contracts.gnosis_safe.get_raw_safe_transaction(
            ledger_api=ledger_api,
            contract_address=safe,
            sender_address=owner,
            owners=(owner,),  # type: ignore
            to_address=to_address,
            value=0,
            data=txd,
            safe_tx_gas=0,
            signatures_by_owner=signatures,
            operation=SafeOperation.CALL.value,
            nonce=ledger_api.api.eth.get_transaction_count(owner),
        )

    chain = Chain.from_id(ledger_api._chain_id)  # pylint: disable=protected-access
    with wrap_gas_spike_as_insufficient_funds(
        chain.value,
        "send Safe transaction",
        ledger_api=ledger_api,
        signer_address=crypto.address,
    ):
        return (
            TxSettler(
                ledger_api=ledger_api,
                crypto=crypto,
                chain_type=chain,
                tx_builder=_build_tx,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )
            .transact()
            .settle()
            .tx_hash
        )


def add_owner(
    ledger_api: LedgerApi,
    crypto: Crypto,
    safe: str,
    owner: str,
) -> None:
    """Add owner to a safe."""
    instance = registry_contracts.gnosis_safe.get_instance(
        ledger_api=ledger_api,
        contract_address=safe,
    )
    txd = instance.encode_abi(
        abi_element_identifier="addOwnerWithThreshold",
        args=[
            owner,
            1,
        ],
    )
    send_safe_txs(
        txd=bytes.fromhex(txd[2:]),
        safe=safe,
        ledger_api=ledger_api,
        crypto=crypto,
    )


def get_prev_owner(ledger_api: LedgerApi, safe: str, owner: str) -> str:
    """Retrieve the previous owner in the owners list of the Safe."""

    owners = get_owners(ledger_api=ledger_api, safe=safe)

    try:
        index = owners.index(owner) - 1
    except ValueError as e:
        raise ValueError(
            f"Owner {owner} not found in the owners' list of the Safe."
        ) from e

    if index < 0:
        return SENTINEL_OWNERS
    return owners[index]


def swap_owner(
    ledger_api: LedgerApi,
    crypto: Crypto,
    safe: str,
    old_owner: str,
    new_owner: str,
) -> None:
    """Swap owner of a safe."""

    prev_owner = get_prev_owner(ledger_api=ledger_api, safe=safe, owner=old_owner)
    instance = registry_contracts.gnosis_safe.get_instance(
        ledger_api=ledger_api,
        contract_address=safe,
    )
    txd = instance.encode_abi(
        abi_element_identifier="swapOwner",
        args=[
            prev_owner,
            old_owner,
            new_owner,
        ],
    )
    send_safe_txs(
        txd=bytes.fromhex(txd[2:]),
        safe=safe,
        ledger_api=ledger_api,
        crypto=crypto,
    )


def remove_owner(
    ledger_api: LedgerApi,
    crypto: Crypto,
    safe: str,
    owner: str,
    threshold: int,
) -> None:
    """Remove owner from a safe."""

    prev_owner = get_prev_owner(ledger_api=ledger_api, safe=safe, owner=owner)
    instance = registry_contracts.gnosis_safe.get_instance(
        ledger_api=ledger_api,
        contract_address=safe,
    )
    txd = instance.encode_abi(
        abi_element_identifier="removeOwner",
        args=[
            prev_owner,
            owner,
            threshold,
        ],
    )
    send_safe_txs(
        txd=bytes.fromhex(txd[2:]),
        safe=safe,
        ledger_api=ledger_api,
        crypto=crypto,
    )


def transfer(
    ledger_api: LedgerApi,
    crypto: Crypto,
    safe: str,
    to: str,
    amount: t.Union[float, int],
) -> str:
    """Transfer assets from safe to given address."""
    amount = int(amount)
    owner = ledger_api.api.to_checksum_address(
        crypto.address,
    )

    def _build_tx() -> t.Optional[str]:
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=ledger_api,
            contract_address=safe,
            value=amount,
            safe_tx_gas=0,
            to_address=to,
            data=b"",
            operation=SafeOperation.CALL.value,
        ).get("tx_hash")
        safe_tx_bytes = binascii.unhexlify(
            safe_tx_hash[2:],
        )
        signatures = {
            owner: crypto.sign_message(
                message=safe_tx_bytes,
                is_deprecated_mode=True,
            )[2:]
        }
        return registry_contracts.gnosis_safe.get_raw_safe_transaction(
            ledger_api=ledger_api,
            contract_address=safe,
            sender_address=owner,
            owners=(owner,),  # type: ignore
            to_address=to,
            value=amount,
            data=b"",
            safe_tx_gas=0,
            signatures_by_owner=signatures,
            operation=SafeOperation.CALL.value,
            nonce=ledger_api.api.eth.get_transaction_count(owner),
        )

    chain = Chain.from_id(ledger_api._chain_id)  # pylint: disable=protected-access
    with wrap_gas_spike_as_insufficient_funds(
        chain.value,
        "transfer from Safe",
        ledger_api=ledger_api,
        signer_address=crypto.address,
    ):
        return (
            TxSettler(
                ledger_api=ledger_api,
                crypto=crypto,
                chain_type=chain,
                tx_builder=_build_tx,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )
            .transact()
            .settle()
            .tx_hash
        )


def transfer_erc20_from_safe(
    ledger_api: LedgerApi,
    crypto: Crypto,
    safe: str,
    token: str,
    to: str,
    amount: t.Union[float, int],
) -> t.Optional[str]:
    """Transfer ERC20 assets from safe to given address."""
    amount = int(amount)
    instance = registry_contracts.erc20.get_instance(
        ledger_api=ledger_api,
        contract_address=token,
    )
    txd = instance.encode_abi(
        abi_element_identifier="transfer",
        args=[
            to,
            amount,
        ],
    )
    return send_safe_txs(
        txd=bytes.fromhex(txd[2:]),
        safe=safe,
        ledger_api=ledger_api,
        crypto=crypto,
        to=token,
    )


def simulate_safe_sub_tx(
    ledger_api: LedgerApi,
    safe: str,
    tx: MultiSendSubTx,
) -> t.Optional[str]:
    """Simulate a MultiSend sub-transaction as the Safe via ``eth_call``.

    Returns ``None`` when the call succeeds, and the revert reason when the
    node reports that the call would fail. Used as the pre-filter before
    batching: failing entries are dropped instead of letting one bad sub-tx
    revert the whole batch. Transport-level errors (RPC down, timeouts) are
    deliberately NOT classified as reverts — they propagate, so callers fail
    loudly instead of silently dropping valid entries.
    """
    try:
        ledger_api.api.eth.call(
            {
                "from": ledger_api.api.to_checksum_address(safe),
                "to": ledger_api.api.to_checksum_address(tx["to"]),
                "value": int(tx.get("value", 0)),
                "data": tx.get("data", b""),
            }
        )
        return None
    except ContractLogicError as e:
        return str(e)


def normalize_tx_data_to_bytes(data: t.Union[str, bytes]) -> bytes:
    """Coerce a multisend tx ``data`` field to ``bytes``.

    ``Contract.encode_abi()`` returns ``HexStr`` (``str``) under web3 7.x /
    open-aea 2.2.x, but the multisend contract's ``encode_data()`` requires
    ``bytes`` for concatenation. This helper handles both ``"0x..."`` and
    raw-hex inputs as well as already-``bytes`` values.

    Used by ``send_safe_multisend_txs`` in this module and as the boundary
    normalization in ``GnosisSafeTransaction.build`` in
    ``operate.services.protocol``. Callers that build multisend tx dicts and
    bypass ``build()`` must call this helper explicitly before the multisend
    call (see ``get_safe_b_erc20_transfer_messages``).
    """
    if isinstance(data, bytes):
        return data
    hex_str = data[2:] if data.startswith("0x") else data
    return bytes.fromhex(hex_str)


def send_safe_multisend_txs(  # pylint: disable=too-many-locals
    txs: t.List[MultiSendSubTx],
    safe: str,
    multisend_address: str,
    ledger_api: LedgerApi,
    crypto: Crypto,
) -> str:
    """Send multiple sub-transactions as one Safe MultiSend transaction.

    Each entry in ``txs`` is a dict with keys ``to``, ``data`` (bytes or hex
    string), ``value`` and optionally ``operation`` (defaults to
    ``MultiSendOperation.CALL``). The batch executes as a single Safe
    transaction that DELEGATE_CALLs into the MultiSend contract, so every
    sub-transaction runs with the Safe as ``msg.sender`` and the batch
    succeeds or reverts atomically.
    """
    if not txs:
        raise ValueError("send_safe_multisend_txs called with an empty txs list")

    owner = ledger_api.api.to_checksum_address(crypto.address)

    normalized_txs = []
    for tx in txs:
        tx_copy = dict(tx)
        tx_copy["data"] = normalize_tx_data_to_bytes(tx.get("data", b""))
        tx_copy.setdefault("operation", MultiSendOperation.CALL)
        normalized_txs.append(tx_copy)

    multisend_payload = registry_contracts.multisend.get_tx_data(
        ledger_api=ledger_api,
        contract_address=multisend_address,
        multi_send_txs=normalized_txs,
    )
    data_hex = multisend_payload.get("data")
    if not data_hex:
        raise ChainInteractionError("multisend.get_tx_data returned no data")
    multisend_data = bytes.fromhex(data_hex[2:])

    def _build_tx() -> t.Optional[t.Dict]:
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=ledger_api,
            contract_address=safe,
            value=0,
            safe_tx_gas=0,
            to_address=multisend_address,
            data=multisend_data,
            operation=SafeOperation.DELEGATE_CALL.value,
        ).get("tx_hash")
        safe_tx_bytes = binascii.unhexlify(safe_tx_hash[2:])
        signatures = {
            owner: crypto.sign_message(
                message=safe_tx_bytes,
                is_deprecated_mode=True,
            )[2:]
        }
        tx = registry_contracts.gnosis_safe.get_raw_safe_transaction(
            ledger_api=ledger_api,
            contract_address=safe,
            sender_address=owner,
            owners=(owner,),  # type: ignore
            to_address=multisend_address,
            value=0,
            data=multisend_data,
            safe_tx_gas=0,
            signatures_by_owner=signatures,
            operation=SafeOperation.DELEGATE_CALL.value,
            nonce=ledger_api.api.eth.get_transaction_count(owner),
        )
        update_tx_with_gas_pricing(tx, ledger_api)
        update_tx_with_gas_estimate(tx, ledger_api)
        return tx

    chain = Chain.from_id(ledger_api._chain_id)  # pylint: disable=protected-access
    with wrap_gas_spike_as_insufficient_funds(
        chain.value,
        "send Safe MultiSend transaction",
        ledger_api=ledger_api,
        signer_address=crypto.address,
    ):
        settler = (
            TxSettler(
                ledger_api=ledger_api,
                crypto=crypto,
                chain_type=chain,
                tx_builder=_build_tx,
                timeout=ON_CHAIN_INTERACT_TIMEOUT,
                retries=ON_CHAIN_INTERACT_RETRIES,
                sleep=ON_CHAIN_INTERACT_SLEEP,
            )
            .transact()
            .settle()
        )

    # A Safe tx whose inner MultiSend reverts is mined with status 0 and
    # moves nothing; TxSettler does not raise on a reverted receipt.
    receipt = settler.tx_receipt
    if receipt is not None and receipt.get("status") == 0:
        raise ChainInteractionError(
            f"MultiSend batch transaction {settler.tx_hash} reverted on-chain."
        )
    return settler.tx_hash


def transfer_batch_from_safe(  # pylint: disable=too-many-locals
    ledger_api: LedgerApi,
    crypto: Crypto,
    safe: str,
    multisend_address: str,
    transfers: t.List[Transfer],
) -> BatchResult:
    """Transfer multiple ``(to, asset, amount)`` entries from a Safe in one tx.

    ``asset == ZERO_ADDRESS`` denotes the chain's native asset. Entries are
    pre-filtered before batching: non-positive amounts, amounts exceeding the
    Safe's remaining per-asset balance (cumulative across the batch), and
    sub-txs whose ``eth_call`` simulation reverts are dropped and logged
    instead of failing the whole batch. Returns a ``BatchResult`` whose
    ``sent`` lists exactly the executed transfers (the batch is atomic) —
    empty, with ``tx_hash is None``, when nothing survives the pre-filter.
    A single surviving transfer is routed to the single-tx path —
    ``transfer`` for native assets, ``transfer_erc20_from_safe`` for ERC20
    (no DELEGATECALL in either case).
    """
    sub_txs: t.List[MultiSendSubTx] = []
    kept: t.List[Transfer] = []
    spent_per_asset: t.Dict[str, int] = {}
    balance_per_asset: t.Dict[str, int] = {}

    for to, asset, amount in transfers:
        amount = int(amount)
        if amount <= 0:
            logger.warning(
                f"[BATCH TRANSFER] Skipping non-positive amount {amount} "
                f"of {asset} to {to} from {safe}"
            )
            continue

        if asset not in balance_per_asset:
            balance_per_asset[asset] = int(
                get_asset_balance(
                    ledger_api=ledger_api, asset_address=asset, address=safe
                )
            )
        spent = spent_per_asset.get(asset, 0)
        if spent + amount > balance_per_asset[asset]:
            logger.warning(
                f"[BATCH TRANSFER] Skipping transfer of {amount} of {asset} "
                f"to {to}: exceeds remaining Safe balance "
                f"({balance_per_asset[asset] - spent} of {balance_per_asset[asset]})"
            )
            continue

        if asset == ZERO_ADDRESS:
            sub_tx: MultiSendSubTx = {
                "to": to,
                "value": amount,
                "data": b"",
                "operation": MultiSendOperation.CALL,
            }
        else:
            instance = registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=asset,
            )
            txd = instance.encode_abi(
                abi_element_identifier="transfer",
                args=[to, amount],
            )
            sub_tx = {
                "to": asset,
                "value": 0,
                "data": normalize_tx_data_to_bytes(txd),
                "operation": MultiSendOperation.CALL,
            }

        error = simulate_safe_sub_tx(ledger_api=ledger_api, safe=safe, tx=sub_tx)
        if error is not None:
            logger.warning(
                f"[BATCH TRANSFER] Skipping transfer of {amount} of {asset} "
                f"to {to}: simulation failed: {error}"
            )
            continue

        spent_per_asset[asset] = spent + amount
        sub_txs.append(sub_tx)
        kept.append(Transfer(to=to, asset=asset, amount=amount))

    if not sub_txs:
        logger.warning(
            f"[BATCH TRANSFER] No transfer survived the pre-filter for Safe {safe}."
        )
        return BatchResult(tx_hash=None, sent=[])

    if len(sub_txs) == 1:
        to, asset, amount = kept[0]
        if asset == ZERO_ADDRESS:
            tx_hash: t.Optional[str] = transfer(
                ledger_api=ledger_api,
                crypto=crypto,
                safe=safe,
                to=to,
                amount=amount,
            )
        else:
            tx_hash = transfer_erc20_from_safe(
                ledger_api=ledger_api,
                crypto=crypto,
                safe=safe,
                token=asset,
                to=to,
                amount=amount,
            )
        return BatchResult(tx_hash=tx_hash, sent=kept if tx_hash else [])

    logger.info(
        f"[BATCH TRANSFER] Sending {len(sub_txs)} transfers from {safe} "
        f"in one MultiSend transaction."
    )
    tx_hash = send_safe_multisend_txs(
        txs=sub_txs,
        safe=safe,
        multisend_address=multisend_address,
        ledger_api=ledger_api,
        crypto=crypto,
    )
    return BatchResult(tx_hash=tx_hash, sent=kept)


def transfer_erc20_from_eoa(
    ledger_api: LedgerApi,
    crypto: Crypto,
    token: str,
    to: str,
    amount: t.Union[float, int],
) -> str:
    """Transfer ERC20 assets from an EOA to the given address."""
    amount = int(amount)
    sender_address = crypto.address

    def _build_transfer_tx() -> t.Dict:
        instance = registry_contracts.erc20.get_instance(
            ledger_api=ledger_api,
            contract_address=token,
        )
        tx = instance.functions.transfer(to, amount).build_transaction(
            {
                "from": sender_address,
                "gas": 1,
                "maxFeePerGas": 1,
                "maxPriorityFeePerGas": 1,
                "nonce": ledger_api.api.eth.get_transaction_count(sender_address),
            }
        )
        update_tx_with_gas_pricing(tx, ledger_api)
        update_tx_with_gas_estimate(tx, ledger_api)
        # eth_estimateGas can fail on some RPC providers (e.g. when the
        # gas-estimate fallback addresses hold no balance on the fork),
        # leaving update_tx_with_gas_estimate to restore the placeholder gas.
        # Submitting that tx is rejected as "intrinsic gas too low" and
        # TxSettler then reprices it (fee only, never gas) until it times out.
        # Apply a bounded ERC20-transfer fallback so the transfer is sent.
        if tx.get("gas", 0) < 21_000:
            tx["gas"] = _ERC20_TRANSFER_GAS_FALLBACK
        return tx

    chain = Chain.from_id(ledger_api._chain_id)  # pylint: disable=protected-access
    with wrap_gas_spike_as_insufficient_funds(
        chain.value,
        "transfer ERC20 from EOA",
        ledger_api=ledger_api,
        signer_address=crypto.address,
    ):
        return (
            TxSettler(
                ledger_api=ledger_api,
                crypto=crypto,
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


def gas_fees_spent_in_tx(
    ledger_api: LedgerApi,
    tx_hash: str,
) -> int:
    """Get gas fees spent in a transaction."""
    tx_receipt = ledger_api.api.eth.get_transaction_receipt(tx_hash)
    if tx_receipt:
        # Use effectiveGasPrice (EIP-1559) or fallback to gasPrice (legacy)
        gas_price = tx_receipt.get("effectiveGasPrice") or tx_receipt.get("gasPrice", 0)
        gas_fee = tx_receipt["gasUsed"] * gas_price
        return gas_fee

    raise ChainInteractionError(f"Cannot fetch transaction receipt for {tx_hash}.")


def estimate_transfer_tx_fee(
    chain: Chain,
    sender_address: str,
    to: str,
    ledger_api: t.Optional[LedgerApi] = None,
) -> int:
    """Estimate transfer transaction fee.

    If ``ledger_api`` is provided, it is used for the gas estimation RPC
    calls (this lets callers reuse a service-configured RPC instead of the
    chain's default public endpoint). Otherwise, the chain's default ledger
    API is used.
    """
    if ledger_api is None:
        ledger_api = get_default_ledger_api(chain)
    tx = ledger_api.get_transfer_transaction(
        sender_address=sender_address,
        destination_address=to,
        amount=0,
        tx_fee=0,
        tx_nonce="0x",
        chain_id=chain.id,
        raise_on_try=True,
    )
    tx = ledger_api.update_with_gas_estimate(
        transaction=tx,
        raise_on_try=False,
    )
    chain_fee = tx["gas"] * tx["maxFeePerGas"]
    if chain in (
        Chain.ARBITRUM_ONE,
        Chain.BASE,
        Chain.OPTIMISM,
        Chain.MODE,
    ):
        chain_fee += ledger_api.get_l1_data_fee(tx)
    return chain_fee


def drain_eoa(
    ledger_api: LedgerApi,
    crypto: Crypto,
    withdrawal_address: str,
    chain_id: int,
) -> str:
    """Drain all the native tokens from the crypto wallet.

    Raises ``InsufficientFundsException`` when the balance cannot cover gas
    at the current multiplier (immediate, before any RPC submission) or
    after exhausting all retry attempts on EIP-1559 gas-spike rejections.
    Callers that treat an empty EOA as a no-op should catch the exception
    explicitly (mirrors ``EthereumMasterWallet._drain_eoa_with_retry``).
    """
    chain = Chain.from_id(chain_id)

    # Retry with increasing gas buffer to handle EIP-1559 gas spikes
    # between fee estimation and transaction broadcast.
    _max_retries: int = 3
    multiplier = DEFAULT_GAS_ESTIMATE_MULTIPLIER
    last_exc: t.Optional[Exception] = None
    for attempt in range(_max_retries):
        chain_fee = estimate_transfer_tx_fee(
            chain=chain,
            sender_address=crypto.address,
            to=withdrawal_address,
            ledger_api=ledger_api,
        )
        balance = ledger_api.get_balance(crypto.address)
        amount = balance - int(chain_fee * multiplier)
        if amount <= 0:
            raise InsufficientFundsException(
                f"Cannot drain EOA {crypto.address} on {chain.name}: "
                f"balance {balance} insufficient to cover gas fee "
                f"{chain_fee} × {multiplier}.",
                chain=chain.value,
            )

        def _build_tx() -> t.Dict:  # noqa: B023  (consumed synchronously)
            """Build transaction"""
            tx = ledger_api.get_transfer_transaction(
                sender_address=crypto.address,
                destination_address=withdrawal_address,
                amount=amount,  # noqa: B023  # pylint: disable=cell-var-from-loop
                tx_fee=0,
                tx_nonce="0x",
                chain_id=chain_id,
                raise_on_try=True,
            )
            empty_tx = tx.copy()
            empty_tx["value"] = 0
            empty_tx = ledger_api.update_with_gas_estimate(
                transaction=empty_tx,
                raise_on_try=True,
            )
            tx["gas"] = empty_tx["gas"]

            logger.info(
                f"Draining {tx['value']} native units from wallet: {crypto.address}"
            )

            return tx

        try:
            return (
                TxSettler(
                    ledger_api=ledger_api,
                    crypto=crypto,
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
        except (ValueError, ChainInteractionError) as e:
            last_exc = e
            if not is_gas_spike_error(str(e)):
                raise
            logger.warning(
                "EOA drain attempt %d/%d failed (multiplier=%.2f): %s — retrying",
                attempt + 1,
                _max_retries,
                multiplier,
                e,
            )
            multiplier += EOA_DRAIN_RETRY_GAS_MULTIPLIER_STEP

    raise InsufficientFundsException(
        f"Failed to drain EOA {crypto.address} on chain {chain.name}: "
        f"insufficient funds for gas after {_max_retries} attempts.",
        chain=chain.value,
    ) from last_exc


def get_asset_balance(
    ledger_api: LedgerApi,
    asset_address: str,
    address: str,
    raise_on_invalid_address: bool = True,
) -> BigInt:
    """
    Get the balance of a native asset or ERC20 token.

    If contract address is a zero address, return the native balance.
    """
    if not Web3.is_address(address):
        if raise_on_invalid_address:
            raise ValueError(f"Invalid address: {address}")
        return BigInt(0)

    try:
        if asset_address == ZERO_ADDRESS:
            return BigInt(ledger_api.get_balance(address, raise_on_try=True))
        return BigInt(
            registry_contracts.erc20.get_instance(
                ledger_api=ledger_api,
                contract_address=asset_address,
            )
            .functions.balanceOf(address)
            .call()
        )
    except Exception as e:
        raise RuntimeError(
            f"Cannot get balance of {address=} {asset_address=} rpc={ledger_api._api.provider.endpoint_uri}."  # pylint: disable=protected-access
        ) from e


def get_assets_balances(
    ledger_api: LedgerApi,
    asset_addresses: t.Set[str],
    addresses: t.Set[str],
    raise_on_invalid_address: bool = True,
) -> t.Dict[str, t.Dict[str, BigInt]]:
    """
    Get the balances of a list of native assets or ERC20 tokens.

    If asset address is a zero address, return the native balance.
    """
    output: t.Dict[str, t.Dict[str, BigInt]] = {}

    for asset, address in itertools.product(asset_addresses, addresses):
        output.setdefault(address, {})[asset] = get_asset_balance(
            ledger_api=ledger_api,
            asset_address=asset,
            address=address,
            raise_on_invalid_address=raise_on_invalid_address,
        )

    return output
