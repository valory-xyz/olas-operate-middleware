# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Gas-abstracted sending from the Master EOA (EIP-7702 + ERC-4337 + Circle Paymaster).

The Master EOA delegates to ``Simple7702Account`` for one operation, batches
its calls into a single UserOperation and pays the bundler in USDC through
Circle Paymaster v0.8. It works from a zero native balance, and the deposit
address is still the Master EOA because 7702 keeps the address unchanged.
"""

import time
import typing as t
from dataclasses import dataclass
from logging import Logger

import requests
from web3 import Web3

from operate.ledger import get_default_ledger_api
from operate.ledger.profiles import (
    BUNDLER_URL_TEMPLATE,
    CIRCLE_PAYMASTER,
    EIP7702_DELEGATE,
    ERC4337_ENTRYPOINT,
    GAS_ABSTRACTION_USDC_CAP,
    USDC,
)
from operate.operate_types import Chain
from operate.wallet.master import EthereumMasterWallet

# EIP-7702 delegation indicator: code = 0xef0100 || delegate address.
DELEGATION_PREFIX = bytes.fromhex("ef0100")
# EntryPoint v0.8 reads the delegate from the sender's code when initCode
# starts with this marker, so the UserOp hash commits to the delegate.
EIP7702_INITCODE_MARKER = "0x7702"
EIP7702_INITCODE_MARKER_PADDED = "0x7702" + "00" * 18
# The paymaster data carries no deadline, so Circle's paymaster calls
# `permit` with the maximum one; the signature must match it.
PERMIT_DEADLINE = 2**256 - 1
CIRCLE_PAYMASTER_PERMIT_MODE = 0
# Values from Circle's Paymaster v0.8 integration guide.
PAYMASTER_VERIFICATION_GAS_LIMIT = 200_000
PAYMASTER_POST_OP_GAS_LIMIT = 35_000
# Extra verification gas for the first (delegating) operation, as in
# Candide's abstractionkit for 7702 accounts.
EIP7702_VERIFICATION_GAS_BUFFER = 55_000
GAS_PRICE_MULTIPLIER = 1.2
# Well-formed estimation signature (a throwaway key over a zero hash):
# Simple7702Account's ECDSA.recover reverts on malformed signatures.
PLACEHOLDER_SIGNATURE = (
    "0xe0a180fdd0fe38037cc878c03832861b40a29d32bd7b40b10c9e1efc8c1468a0"
    "5ae06d1624896d0d29f4b31e32772ea3cb1b4d7ed4e077e5da28dcc33c0e78121c"
)
BUNDLER_TIMEOUT = 30
RECEIPT_TIMEOUT = 300
RECEIPT_POLL_INTERVAL = 3.0
USER_OPERATION_EVENT_TOPIC = Web3.to_hex(
    Web3.keccak(
        text="UserOperationEvent(bytes32,address,address,uint256,bool,uint256,uint256)"
    )
)
LOG_BLOCK_CHUNK_SIZE = 5000

_ENTRYPOINT_ABI = [
    {
        "name": "getNonce",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "sender", "type": "address"},
            {"name": "key", "type": "uint192"},
        ],
        "outputs": [{"name": "nonce", "type": "uint256"}],
    },
    {
        "name": "getUserOpHash",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {
                "name": "userOp",
                "type": "tuple",
                "components": [
                    {"name": "sender", "type": "address"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "initCode", "type": "bytes"},
                    {"name": "callData", "type": "bytes"},
                    {"name": "accountGasLimits", "type": "bytes32"},
                    {"name": "preVerificationGas", "type": "uint256"},
                    {"name": "gasFees", "type": "bytes32"},
                    {"name": "paymasterAndData", "type": "bytes"},
                    {"name": "signature", "type": "bytes"},
                ],
            }
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
]

_SIMPLE_7702_ACCOUNT_ABI = [
    {
        "name": "executeBatch",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "calls",
                "type": "tuple[]",
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "data", "type": "bytes"},
                ],
            }
        ],
        "outputs": [],
    }
]

_EIP2612_ABI = [
    {
        "name": fn,
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    }
    for fn in ("name", "version")
] + [
    {
        "name": "nonces",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]


class GasAbstractionError(RuntimeError):
    """A gas-abstracted operation could not be built, sent or confirmed."""


class UserOperationReverted(GasAbstractionError):
    """A UserOperation was included on-chain and reverted."""


@dataclass
class Call:
    """One call inside ``Simple7702Account.executeBatch``."""

    target: str
    value: int
    data: str


@dataclass
class PreparedUserOperation:
    """A signed UserOperation that has not been submitted yet."""

    user_op: t.Dict[str, t.Any]
    user_op_hash: str
    authorization_nonce: t.Optional[int]
    nonce: int
    # The UserOp cannot be included before this block.
    block_number: int


@dataclass
class UserOperationResult:
    """Outcome of a submitted UserOperation."""

    user_op_hash: str
    tx_hash: str
    authorization_nonce: t.Optional[int]


def _hex(value: int) -> str:
    return hex(value)


def _pack_uint128_pair(high: int, low: int) -> bytes:
    return high.to_bytes(16, "big") + low.to_bytes(16, "big")


def is_gas_abstracted(chain: Chain, token: str) -> bool:
    """Whether a `token` source on `chain` can pay its own gas via the paymaster."""
    return chain in CIRCLE_PAYMASTER and USDC.get(chain) == token


class GasAbstractedSender:
    """Build, sign and submit Master EOA UserOperations paid in USDC."""

    def __init__(
        self,
        wallet: EthereumMasterWallet,
        logger: Logger,
        sleep: t.Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the sender."""
        self.wallet = wallet
        self.logger = logger
        self._sleep = sleep

    # --- read-only helpers -------------------------------------------------

    @staticmethod
    def _w3(chain: Chain) -> Web3:
        return get_default_ledger_api(chain).api

    def delegation_of(self, chain: Chain) -> t.Optional[str]:
        """Return the Master EOA's current EIP-7702 delegate on `chain`, if any."""
        code = bytes(self._w3(chain).eth.get_code(self.wallet.address))
        if not code:
            return None
        if len(code) != 23 or not code.startswith(DELEGATION_PREFIX):
            raise GasAbstractionError(
                f"Master EOA {self.wallet.address} on {chain.name} has non-delegation code."
            )
        return Web3.to_checksum_address(code[len(DELEGATION_PREFIX) :])

    @staticmethod
    def paymaster_data(chain: Chain, permit_signature: str) -> str:
        """Circle Paymaster v0.8 `paymasterData` in permit mode."""
        return (
            "0x"
            + (
                CIRCLE_PAYMASTER_PERMIT_MODE.to_bytes(1, "big")
                + bytes.fromhex(USDC[chain][2:])
                + GAS_ABSTRACTION_USDC_CAP[chain].to_bytes(32, "big")
                + bytes.fromhex(permit_signature[2:])
            ).hex()
        )

    def permit_typed_data(self, chain: Chain) -> t.Dict[str, t.Any]:
        """EIP-2612 permit letting the paymaster take up to the USDC gas cap."""
        w3 = self._w3(chain)
        token = w3.eth.contract(address=USDC[chain], abi=_EIP2612_ABI)
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Permit": [
                    {"name": "owner", "type": "address"},
                    {"name": "spender", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                ],
            },
            "primaryType": "Permit",
            "domain": {
                "name": token.functions.name().call(),
                "version": token.functions.version().call(),
                "chainId": chain.id,
                "verifyingContract": USDC[chain],
            },
            "message": {
                "owner": self.wallet.address,
                "spender": CIRCLE_PAYMASTER[chain],
                "value": GAS_ABSTRACTION_USDC_CAP[chain],
                "nonce": token.functions.nonces(self.wallet.address).call(),
                "deadline": PERMIT_DEADLINE,
            },
        }

    @staticmethod
    def execute_batch_calldata(calls: t.List[Call]) -> str:
        """`Simple7702Account.executeBatch(Call[])` calldata."""
        account = Web3().eth.contract(abi=_SIMPLE_7702_ACCOUNT_ABI)
        return account.encode_abi(
            "executeBatch",
            args=[
                [
                    (Web3.to_checksum_address(c.target), int(c.value), c.data)
                    for c in calls
                ]
            ],
        )

    @staticmethod
    def pack_user_operation(user_op: t.Dict[str, t.Any]) -> t.Tuple:
        """The on-chain PackedUserOperation tuple for a bundler-format UserOp."""
        init_code = b""
        if user_op.get("factory") == EIP7702_INITCODE_MARKER:
            init_code = bytes.fromhex(EIP7702_INITCODE_MARKER_PADDED[2:])
        paymaster_and_data = b""
        if user_op.get("paymaster"):
            paymaster_and_data = (
                bytes.fromhex(user_op["paymaster"][2:])
                + _pack_uint128_pair(
                    int(user_op["paymasterVerificationGasLimit"], 16),
                    int(user_op["paymasterPostOpGasLimit"], 16),
                )
                + bytes.fromhex(user_op["paymasterData"][2:])
            )
        return (
            user_op["sender"],
            int(user_op["nonce"], 16),
            init_code,
            bytes.fromhex(user_op["callData"][2:]),
            _pack_uint128_pair(
                int(user_op["verificationGasLimit"], 16),
                int(user_op["callGasLimit"], 16),
            ),
            int(user_op["preVerificationGas"], 16),
            _pack_uint128_pair(
                int(user_op["maxPriorityFeePerGas"], 16),
                int(user_op["maxFeePerGas"], 16),
            ),
            paymaster_and_data,
            b"",
        )

    def user_op_hash(
        self, chain: Chain, user_op: t.Dict[str, t.Any], delegated: bool
    ) -> bytes:
        """Ask the EntryPoint for the UserOp hash rather than re-encoding it.

        Before the first delegation lands, the EntryPoint cannot read the
        delegate from the sender's code, so the call overrides that code
        with the delegation the bundler is about to install.
        """
        w3 = self._w3(chain)
        entrypoint = w3.eth.contract(address=ERC4337_ENTRYPOINT, abi=_ENTRYPOINT_ABI)
        call = entrypoint.functions.getUserOpHash(self.pack_user_operation(user_op))
        if delegated:
            return bytes(call.call())
        state_override = {
            self.wallet.address: {
                "code": "0x"
                + (DELEGATION_PREFIX + bytes.fromhex(EIP7702_DELEGATE[2:])).hex()
            }
        }
        return bytes(call.call(state_override=state_override))

    # --- bundler -----------------------------------------------------------

    def _bundler(self, chain: Chain, method: str, params: t.List) -> t.Any:
        url = BUNDLER_URL_TEMPLATE.format(chain_id=chain.id)
        self.logger.info(f"[GAS ABSTRACTION] {method} -> {url}")
        try:
            response = requests.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=BUNDLER_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as e:
            raise GasAbstractionError(f"Bundler {method} failed: {e}") from e
        if body.get("error"):
            error = body["error"]
            raise GasAbstractionError(
                f"Bundler {method} error {error.get('code')}: {error.get('message')}"
            )
        return body.get("result")

    def _wait_for_receipt(self, chain: Chain, user_op_hash: str) -> t.Dict:
        deadline = time.time() + RECEIPT_TIMEOUT
        while time.time() < deadline:
            receipt = self._bundler(
                chain, "eth_getUserOperationReceipt", [user_op_hash]
            )
            if receipt:
                return receipt
            self._sleep(RECEIPT_POLL_INTERVAL)
        raise GasAbstractionError(
            f"UserOperation {user_op_hash} not included after {RECEIPT_TIMEOUT}s."
        )

    # --- sending -----------------------------------------------------------

    def build_user_operation(  # pylint: disable=too-many-locals
        self, chain: Chain, calls: t.List[Call]
    ) -> t.Tuple[t.Dict[str, t.Any], bool, t.Optional[int]]:
        """Build an unsigned, gas-estimated UserOperation.

        Returns the UserOp, whether the Master EOA was already delegated, and
        the nonce of the authorization carried in it (None when reused).
        """
        if chain not in CIRCLE_PAYMASTER:
            raise GasAbstractionError(f"No Circle Paymaster on {chain.name}.")

        w3 = self._w3(chain)
        sender = self.wallet.address
        delegated = self.delegation_of(chain) == EIP7702_DELEGATE
        entrypoint = w3.eth.contract(address=ERC4337_ENTRYPOINT, abi=_ENTRYPOINT_ABI)
        gas_pricing = get_default_ledger_api(chain).try_get_gas_pricing() or {}
        max_fee = int(
            gas_pricing.get("maxFeePerGas", gas_pricing.get("gasPrice", 0))
            * GAS_PRICE_MULTIPLIER
        )
        max_priority_fee = int(
            gas_pricing.get("maxPriorityFeePerGas", max_fee) * GAS_PRICE_MULTIPLIER
        )

        permit_signature = self.wallet.sign_typed_data(self.permit_typed_data(chain))
        user_op: t.Dict[str, t.Any] = {
            "sender": sender,
            "nonce": _hex(entrypoint.functions.getNonce(sender, 0).call()),
            "factory": None,
            "factoryData": None,
            "callData": self.execute_batch_calldata(calls),
            "callGasLimit": _hex(0),
            "verificationGasLimit": _hex(0),
            "preVerificationGas": _hex(0),
            "maxFeePerGas": _hex(max_fee),
            "maxPriorityFeePerGas": _hex(max_priority_fee),
            "paymaster": CIRCLE_PAYMASTER[chain],
            "paymasterVerificationGasLimit": _hex(PAYMASTER_VERIFICATION_GAS_LIMIT),
            "paymasterPostOpGasLimit": _hex(PAYMASTER_POST_OP_GAS_LIMIT),
            "paymasterData": self.paymaster_data(chain, permit_signature),
            "signature": PLACEHOLDER_SIGNATURE,
        }

        authorization_nonce: t.Optional[int] = None
        if not delegated:
            # The bundler sends the type-4 tx, so the authorization uses the
            # EOA's current nonce (not +1 as in a self-sponsored one).
            authorization_nonce = w3.eth.get_transaction_count(sender)
            authorization = self.wallet.sign_authorization(
                chain=chain, address=EIP7702_DELEGATE, nonce=authorization_nonce
            )
            user_op["factory"] = EIP7702_INITCODE_MARKER
            user_op["eip7702Auth"] = {
                "chainId": _hex(authorization.chain_id),
                "address": EIP7702_DELEGATE,
                "nonce": _hex(authorization.nonce),
                "yParity": _hex(authorization.y_parity),
                "r": _hex(authorization.r),
                "s": _hex(authorization.s),
            }

        estimate = self._bundler(
            chain, "eth_estimateUserOperationGas", [user_op, ERC4337_ENTRYPOINT]
        )
        verification_gas = int(estimate["verificationGasLimit"], 16)
        if not delegated:
            verification_gas += EIP7702_VERIFICATION_GAS_BUFFER
        user_op["callGasLimit"] = estimate["callGasLimit"]
        user_op["verificationGasLimit"] = _hex(verification_gas)
        user_op["preVerificationGas"] = estimate["preVerificationGas"]
        return user_op, delegated, authorization_nonce

    def prepare_batch(self, chain: Chain, calls: t.List[Call]) -> PreparedUserOperation:
        """Build and sign `calls` as one UserOperation, without sending it.

        The hash is known before submission, so a caller can persist it first
        and reconcile after a crash instead of resending.
        """
        block_number = self._w3(chain).eth.block_number
        user_op, delegated, authorization_nonce = self.build_user_operation(
            chain, calls
        )
        op_hash = self.user_op_hash(chain, user_op, delegated)
        user_op["signature"] = self.wallet.unsafe_sign_hash(op_hash)
        return PreparedUserOperation(
            user_op=user_op,
            user_op_hash="0x" + op_hash.hex(),
            authorization_nonce=authorization_nonce,
            nonce=int(user_op["nonce"], 16),
            block_number=block_number,
        )

    def submit(self, chain: Chain, prepared: PreparedUserOperation) -> str:
        """Hand a prepared UserOperation to the bundler."""
        return self._bundler(
            chain, "eth_sendUserOperation", [prepared.user_op, ERC4337_ENTRYPOINT]
        )

    @staticmethod
    def tx_hash_of(receipt: t.Dict) -> str:
        """The bundler's handleOps tx hash, or an error if the UserOp reverted."""
        tx_hash = receipt.get("receipt", {}).get("transactionHash")
        if not receipt.get("success"):
            raise UserOperationReverted(
                f"UserOperation {receipt.get('userOpHash')} reverted: {receipt.get('reason') or 'no reason'} (tx {tx_hash})."
            )
        return tx_hash

    def wait_for_tx_hash(self, chain: Chain, user_op_hash: str) -> str:
        """Wait for a submitted UserOperation and return its handleOps tx hash."""
        return self.tx_hash_of(self._wait_for_receipt(chain, user_op_hash))

    def send_batch(self, chain: Chain, calls: t.List[Call]) -> UserOperationResult:
        """Submit `calls` as one gas-abstracted UserOperation and wait for it."""
        prepared = self.prepare_batch(chain, calls)
        user_op_hash = self.submit(chain, prepared)
        return UserOperationResult(
            user_op_hash=user_op_hash,
            tx_hash=self.wait_for_tx_hash(chain, user_op_hash),
            authorization_nonce=prepared.authorization_nonce,
        )

    def get_user_op_receipt(
        self, chain: Chain, user_op_hash: str
    ) -> t.Optional[t.Dict]:
        """Look up a previously submitted UserOperation (restart reconciliation)."""
        return self._bundler(chain, "eth_getUserOperationReceipt", [user_op_hash])

    def user_op_nonce_used(self, chain: Chain, nonce: int) -> bool:
        """Whether the EntryPoint nonce of a UserOperation has been used."""
        entrypoint = self._w3(chain).eth.contract(
            address=ERC4337_ENTRYPOINT, abi=_ENTRYPOINT_ABI
        )
        return entrypoint.functions.getNonce(self.wallet.address, 0).call() > nonce

    def user_op_known(self, chain: Chain, user_op_hash: str) -> bool:
        """Whether the bundler it was sent to still knows a UserOperation."""
        return (
            self._bundler(chain, "eth_getUserOperationByHash", [user_op_hash])
            is not None
        )

    def find_user_op_event(
        self, chain: Chain, user_op_hash: str, from_block: int
    ) -> t.Optional[t.Dict]:
        """Find a UserOperation's EntryPoint event over RPC, as a bundler-style receipt.

        For when the bundler has no receipt, e.g. because it only searches
        recent blocks.
        """
        w3 = self._w3(chain)
        latest = w3.eth.block_number
        for start in range(from_block, latest + 1, LOG_BLOCK_CHUNK_SIZE):
            logs = w3.eth.get_logs(
                {
                    "address": ERC4337_ENTRYPOINT,
                    "topics": [USER_OPERATION_EVENT_TOPIC, user_op_hash],
                    "fromBlock": start,
                    "toBlock": min(start + LOG_BLOCK_CHUNK_SIZE - 1, latest),
                }
            )
            if logs:
                # Data: nonce, success, actualGasCost, actualGasUsed.
                data = bytes(logs[0]["data"])
                return {
                    "userOpHash": user_op_hash,
                    "success": bool(int.from_bytes(data[32:64], "big")),
                    "receipt": {
                        "transactionHash": Web3.to_hex(logs[0]["transactionHash"])
                    },
                }
        return None
