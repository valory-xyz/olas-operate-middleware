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

"""Unit tests for operate/wallet/gas_abstraction.py (no network)."""

import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from eth_account import Account

from operate.constants import ZERO_ADDRESS
from operate.ledger.profiles import (
    CIRCLE_PAYMASTER,
    EIP7702_DELEGATE,
    ERC4337_ENTRYPOINT,
    GAS_ABSTRACTION_USDC_CAP,
    USDC,
)
from operate.operate_types import Chain
from operate.wallet.gas_abstraction import (
    Call,
    EIP7702_INITCODE_MARKER,
    EIP7702_INITCODE_MARKER_PADDED,
    GasAbstractedSender,
    GasAbstractionError,
    LOG_BLOCK_CHUNK_SIZE,
    PERMIT_DEADLINE,
    RECEIPT_POLL_INTERVAL,
    USER_OPERATION_EVENT_TOPIC,
    UserOperationReverted,
    is_gas_abstracted,
)
from operate.wallet.master import EthereumMasterWallet

MODULE = "operate.wallet.gas_abstraction"
USER_OP_HASH = "0x" + "ab" * 32
HANDLE_OPS_TX = "0x" + "cd" * 32


def _wallet(tmp_path: Path) -> t.Tuple[EthereumMasterWallet, t.Any]:
    account = Account.create()
    wallet = EthereumMasterWallet(path=tmp_path, address=account.address)
    crypto = MagicMock()
    crypto.entity = account
    crypto.address = account.address
    wallet._crypto = crypto  # pylint: disable=protected-access
    return wallet, account


def _sender(tmp_path: Path) -> t.Tuple[GasAbstractedSender, t.Any]:
    wallet, account = _wallet(tmp_path)
    return (
        GasAbstractedSender(wallet, logger=MagicMock(), sleep=lambda _: None),
        account,
    )


def _bundler_response(
    result: t.Any = None, error: t.Optional[t.Dict] = None
) -> MagicMock:
    response = MagicMock()
    body: t.Dict[str, t.Any] = {"jsonrpc": "2.0", "id": 1}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    response.json.return_value = body
    return response


class TestIsGasAbstracted:
    """Only USDC on a Circle Paymaster chain is gas-abstracted."""

    @pytest.mark.parametrize(
        "chain",
        [Chain.ETHEREUM, Chain.BASE, Chain.OPTIMISM, Chain.POLYGON, Chain.ARBITRUM_ONE],
    )
    def test_usdc_on_paymaster_chains(self, chain: Chain) -> None:
        """USDC sources on the five paymaster chains take the UserOp path."""
        assert is_gas_abstracted(chain, USDC[chain])
        assert not is_gas_abstracted(chain, ZERO_ADDRESS)

    @pytest.mark.parametrize(
        "chain", [Chain.GNOSIS, Chain.ROBINHOOD, Chain.CELO, Chain.MODE]
    )
    def test_no_paymaster_means_no_gas_abstraction(self, chain: Chain) -> None:
        """Chains without a CIRCLE_PAYMASTER entry never gas-abstract."""
        assert chain not in CIRCLE_PAYMASTER
        assert not is_gas_abstracted(chain, USDC.get(chain, ZERO_ADDRESS))


class TestDelegationOf:
    """delegation_of parses the 0xef0100 indicator."""

    def test_parses_delegation_indicator(self, tmp_path: Path) -> None:
        """Delegated code yields the checksummed delegate."""
        sender, _ = _sender(tmp_path)
        w3 = MagicMock()
        w3.eth.get_code.return_value = bytes.fromhex("ef0100" + EIP7702_DELEGATE[2:])
        with patch.object(GasAbstractedSender, "_w3", return_value=w3):
            assert sender.delegation_of(Chain.BASE) == EIP7702_DELEGATE

    def test_empty_code_means_not_delegated(self, tmp_path: Path) -> None:
        """No code means no delegation (e.g. after clearing)."""
        sender, _ = _sender(tmp_path)
        w3 = MagicMock()
        w3.eth.get_code.return_value = b""
        with patch.object(GasAbstractedSender, "_w3", return_value=w3):
            assert sender.delegation_of(Chain.BASE) is None

    def test_other_code_raises(self, tmp_path: Path) -> None:
        """Code that is not a delegation indicator is an error."""
        sender, _ = _sender(tmp_path)
        w3 = MagicMock()
        w3.eth.get_code.return_value = bytes.fromhex("6080604052")
        with patch.object(GasAbstractedSender, "_w3", return_value=w3):
            with pytest.raises(GasAbstractionError, match="non-delegation code"):
                sender.delegation_of(Chain.BASE)


class TestPaymasterData:
    """Circle Paymaster v0.8 permit-mode paymasterData."""

    @pytest.mark.parametrize(
        ("chain", "cap"), [(Chain.BASE, 1_000_000), (Chain.ETHEREUM, 10_000_000)]
    )
    def test_layout_and_cap(self, chain: Chain, cap: int) -> None:
        """Layout: mode byte, token, the chain's permit amount, permit signature."""
        signature = "0x" + "11" * 65
        data = bytes.fromhex(GasAbstractedSender.paymaster_data(chain, signature)[2:])

        assert data[0] == 0
        assert "0x" + data[1:21].hex() == USDC[chain].lower()
        assert int.from_bytes(data[21:53], "big") == cap
        assert data[53:] == bytes.fromhex("11" * 65)

    def test_every_paymaster_chain_has_a_cap(self) -> None:
        """A gas-abstracted chain without a cap would fail at quote time."""
        assert set(GAS_ABSTRACTION_USDC_CAP) == set(CIRCLE_PAYMASTER)


class TestPermitTypedData:
    """The EIP-2612 permit signed for the paymaster."""

    def test_domain_spender_value_and_deadline(self, tmp_path: Path) -> None:
        """Domain is the chain's USDC; the permit caps the paymaster at $1."""
        sender, account = _sender(tmp_path)
        w3 = MagicMock()
        token = w3.eth.contract.return_value
        token.functions.name.return_value.call.return_value = "USD Coin"
        token.functions.version.return_value.call.return_value = "2"
        token.functions.nonces.return_value.call.return_value = 4

        with patch.object(GasAbstractedSender, "_w3", return_value=w3):
            typed = sender.permit_typed_data(Chain.BASE)

        assert typed["domain"] == {
            "name": "USD Coin",
            "version": "2",
            "chainId": Chain.BASE.id,
            "verifyingContract": USDC[Chain.BASE],
        }
        assert typed["message"] == {
            "owner": account.address,
            "spender": CIRCLE_PAYMASTER[Chain.BASE],
            "value": 1_000_000,
            "nonce": 4,
            "deadline": PERMIT_DEADLINE,
        }


class TestPackUserOperation:
    """PackedUserOperation packing for getUserOpHash."""

    def test_packs_gas_fields_and_7702_initcode(self) -> None:
        """uint128 pairs are packed high||low; the 7702 marker becomes initCode."""
        user_op = {
            "sender": "0x" + "aa" * 20,
            "nonce": "0x5",
            "factory": EIP7702_INITCODE_MARKER,
            "callData": "0x1234",
            "callGasLimit": "0x2",
            "verificationGasLimit": "0x1",
            "preVerificationGas": "0x3",
            "maxFeePerGas": "0x5",
            "maxPriorityFeePerGas": "0x4",
            "paymaster": "0x" + "bb" * 20,
            "paymasterVerificationGasLimit": "0x6",
            "paymasterPostOpGasLimit": "0x7",
            "paymasterData": "0x99",
        }

        packed = GasAbstractedSender.pack_user_operation(user_op)

        assert packed[1] == 5
        assert packed[2] == bytes.fromhex(EIP7702_INITCODE_MARKER_PADDED[2:])
        assert packed[4] == (1).to_bytes(16, "big") + (2).to_bytes(16, "big")
        assert packed[6] == (4).to_bytes(16, "big") + (5).to_bytes(16, "big")
        assert packed[7] == (
            bytes.fromhex("bb" * 20)
            + (6).to_bytes(16, "big")
            + (7).to_bytes(16, "big")
            + b"\x99"
        )

    def test_no_initcode_when_already_delegated(self) -> None:
        """Without the marker the initCode is empty."""
        user_op = {
            "sender": "0x" + "aa" * 20,
            "nonce": "0x0",
            "factory": None,
            "callData": "0x",
            "callGasLimit": "0x0",
            "verificationGasLimit": "0x0",
            "preVerificationGas": "0x0",
            "maxFeePerGas": "0x0",
            "maxPriorityFeePerGas": "0x0",
            "paymaster": None,
        }
        packed = GasAbstractedSender.pack_user_operation(user_op)
        assert packed[2] == b""
        assert packed[7] == b""


class TestSendBatch:
    """End-to-end UserOperation build/sign/submit with mocked RPCs."""

    @staticmethod
    def _run(
        tmp_path: Path,
        receipt: t.Dict,
        code: bytes = b"",
        tx_count: int = 12,
    ) -> t.Tuple[t.Any, t.Any, t.List[t.Dict], t.Any]:
        sender, account = _sender(tmp_path)
        w3 = MagicMock()
        w3.eth.get_code.return_value = code
        w3.eth.get_transaction_count.return_value = tx_count
        contract = w3.eth.contract.return_value
        contract.functions.getNonce.return_value.call.return_value = 0
        contract.functions.getUserOpHash.return_value.call.return_value = bytes.fromhex(
            USER_OP_HASH[2:]
        )
        ledger_api = MagicMock()
        ledger_api.try_get_gas_pricing.return_value = {
            "maxFeePerGas": 100,
            "maxPriorityFeePerGas": 10,
        }
        sent: t.List[t.Dict] = []

        def _post(url: str, json: t.Dict, timeout: int) -> MagicMock:
            sent.append({"url": url, **json})
            method = json["method"]
            if method == "eth_estimateUserOperationGas":
                return _bundler_response(
                    {
                        "callGasLimit": "0x100",
                        "verificationGasLimit": "0x200",
                        "preVerificationGas": "0x300",
                    }
                )
            if method == "eth_sendUserOperation":
                return _bundler_response(USER_OP_HASH)
            return _bundler_response(receipt)

        with (
            patch.object(GasAbstractedSender, "_w3", return_value=w3),
            patch(f"{MODULE}.get_default_ledger_api", return_value=ledger_api),
            patch.object(
                GasAbstractedSender,
                "permit_typed_data",
                return_value={
                    "types": {
                        "EIP712Domain": [{"name": "name", "type": "string"}],
                        "Ping": [{"name": "v", "type": "uint256"}],
                    },
                    "primaryType": "Ping",
                    "domain": {"name": "x"},
                    "message": {"v": 1},
                },
            ),
            patch(f"{MODULE}.requests.post", side_effect=_post),
        ):
            try:
                result: t.Any = sender.send_batch(
                    Chain.BASE, [Call(target="0x" + "12" * 20, value=0, data="0xabcd")]
                )
            except GasAbstractionError as e:
                result = e
        return result, account, sent, contract

    def test_first_operation_carries_chain_bound_authorization(
        self, tmp_path: Path
    ) -> None:
        """The 7702 auth targets Simple7702Account on the source chain id, never 0."""
        result, account, sent, _ = self._run(
            tmp_path,
            receipt={"success": True, "receipt": {"transactionHash": HANDLE_OPS_TX}},
        )

        assert result.user_op_hash == USER_OP_HASH
        assert result.tx_hash == HANDLE_OPS_TX
        assert result.authorization_nonce == 12
        send = next(r for r in sent if r["method"] == "eth_sendUserOperation")
        user_op, entrypoint = send["params"]
        assert entrypoint == ERC4337_ENTRYPOINT
        assert send["url"] == f"https://api.candide.dev/public/v3/{Chain.BASE.id}"
        auth = user_op["eip7702Auth"]
        assert int(auth["chainId"], 16) == Chain.BASE.id != 0
        assert auth["address"] == EIP7702_DELEGATE
        assert int(auth["nonce"], 16) == 12
        assert user_op["factory"] == EIP7702_INITCODE_MARKER
        assert user_op["paymaster"] == CIRCLE_PAYMASTER[Chain.BASE]
        # verification gas carries the first-delegation buffer
        assert int(user_op["verificationGasLimit"], 16) == 0x200 + 55_000

    def test_user_op_signature_recovers_over_raw_hash(self, tmp_path: Path) -> None:
        """Signed with no EIP-191 prefix over EntryPoint.getUserOpHash."""
        _, account, sent, _ = self._run(
            tmp_path,
            receipt={"success": True, "receipt": {"transactionHash": HANDLE_OPS_TX}},
        )

        send = next(r for r in sent if r["method"] == "eth_sendUserOperation")
        signature = send["params"][0]["signature"]
        assert (
            Account._recover_hash(  # pylint: disable=protected-access
                bytes.fromhex(USER_OP_HASH[2:]), signature=bytes.fromhex(signature[2:])
            )
            == account.address
        )

    def test_already_delegated_skips_authorization(self, tmp_path: Path) -> None:
        """A live delegation to the same delegate is reused without re-authorizing."""
        result, _, sent, contract = self._run(
            tmp_path,
            receipt={"success": True, "receipt": {"transactionHash": HANDLE_OPS_TX}},
            code=bytes.fromhex("ef0100" + EIP7702_DELEGATE[2:]),
        )

        send = next(r for r in sent if r["method"] == "eth_sendUserOperation")
        assert "eip7702Auth" not in send["params"][0]
        assert send["params"][0]["factory"] is None
        assert result.authorization_nonce is None
        contract.functions.getUserOpHash.return_value.call.assert_called_once_with()

    def test_hash_uses_delegation_state_override_before_first_delegation(
        self, tmp_path: Path
    ) -> None:
        """The EntryPoint sees the delegation the bundler is about to install."""
        _, account, _, contract = self._run(
            tmp_path,
            receipt={"success": True, "receipt": {"transactionHash": HANDLE_OPS_TX}},
        )
        kwargs = contract.functions.getUserOpHash.return_value.call.call_args.kwargs
        assert kwargs["state_override"] == {
            account.address: {"code": "0xef0100" + EIP7702_DELEGATE[2:].lower()}
        }

    def test_reverted_user_operation_raises(self, tmp_path: Path) -> None:
        """A receipt with success=false is surfaced as an error."""
        result, _, _, _ = self._run(
            tmp_path,
            receipt={
                "success": False,
                "reason": "AA33 reverted",
                "receipt": {"transactionHash": HANDLE_OPS_TX},
            },
        )
        assert isinstance(result, UserOperationReverted)
        assert "AA33 reverted" in str(result)

    def test_no_paymaster_chain_is_rejected(self, tmp_path: Path) -> None:
        """Gnosis/Robinhood never build a UserOperation."""
        sender, _ = _sender(tmp_path)
        with pytest.raises(GasAbstractionError, match="No Circle Paymaster"):
            sender.build_user_operation(Chain.GNOSIS, [])


class TestBundlerErrors:
    """Bundler JSON-RPC error mapping."""

    def test_json_rpc_error_is_mapped(self, tmp_path: Path) -> None:
        """A JSON-RPC error body becomes a GasAbstractionError with its message."""
        sender, _ = _sender(tmp_path)
        with patch(
            f"{MODULE}.requests.post",
            return_value=_bundler_response(
                error={"code": -32602, "message": "invalid UserOperation"}
            ),
        ):
            with pytest.raises(
                GasAbstractionError, match="-32602: invalid UserOperation"
            ):
                sender.get_user_op_receipt(Chain.BASE, USER_OP_HASH)

    def test_transport_error_is_mapped(self, tmp_path: Path) -> None:
        """Network failures are wrapped too."""
        sender, _ = _sender(tmp_path)
        with patch(
            f"{MODULE}.requests.post", side_effect=requests.ConnectionError("down")
        ):
            with pytest.raises(GasAbstractionError, match="down"):
                sender.get_user_op_receipt(Chain.BASE, USER_OP_HASH)

    def test_receipt_polling_times_out(self, tmp_path: Path) -> None:
        """No receipt before RECEIPT_TIMEOUT fails the send."""
        sender, _ = _sender(tmp_path)
        with (
            patch(f"{MODULE}.requests.post", return_value=_bundler_response(None)),
            patch(f"{MODULE}.RECEIPT_TIMEOUT", 0),
        ):
            with pytest.raises(GasAbstractionError, match="not included"):
                sender._wait_for_receipt(  # pylint: disable=protected-access
                    Chain.BASE, USER_OP_HASH
                )

    def test_receipt_polling_sleeps_between_empty_polls(self, tmp_path: Path) -> None:
        """An empty poll sleeps RECEIPT_POLL_INTERVAL, then the next poll's receipt returns."""
        wallet, _ = _wallet(tmp_path)
        sleeps: t.List[float] = []
        sender = GasAbstractedSender(wallet, logger=MagicMock(), sleep=sleeps.append)
        receipt = {"success": True, "receipt": {"transactionHash": HANDLE_OPS_TX}}
        with patch(
            f"{MODULE}.requests.post",
            side_effect=[_bundler_response(None), _bundler_response(receipt)],
        ):
            assert (
                sender._wait_for_receipt(  # pylint: disable=protected-access
                    Chain.BASE, USER_OP_HASH
                )
                == receipt
            )
        assert sleeps == [RECEIPT_POLL_INTERVAL]


class TestW3:
    """_w3 resolves the chain's default ledger API."""

    def test_uses_default_ledger_api(self) -> None:
        """The Web3 instance is the default ledger API's `.api` for that chain."""
        with patch(f"{MODULE}.get_default_ledger_api") as get_api:
            w3 = GasAbstractedSender._w3(Chain.BASE)  # pylint: disable=protected-access
        get_api.assert_called_once_with(Chain.BASE)
        assert w3 is get_api.return_value.api


class TestPrepareBatch:
    """prepare_batch signs without submitting, so the hash can be persisted first."""

    def test_prepare_does_not_submit(self, tmp_path: Path) -> None:
        """Only estimation reaches the bundler; the hash matches getUserOpHash."""
        sender, _ = _sender(tmp_path)
        w3 = MagicMock()
        w3.eth.get_code.return_value = b""
        w3.eth.get_transaction_count.return_value = 1
        w3.eth.block_number = 900
        contract = w3.eth.contract.return_value
        contract.functions.getNonce.return_value.call.return_value = 7
        contract.functions.getUserOpHash.return_value.call.return_value = bytes.fromhex(
            USER_OP_HASH[2:]
        )
        ledger_api = MagicMock()
        ledger_api.try_get_gas_pricing.return_value = {"gasPrice": 50}
        methods: t.List[str] = []

        def _post(url: str, json: t.Dict, timeout: int) -> MagicMock:
            methods.append(json["method"])
            return _bundler_response(
                {
                    "callGasLimit": "0x1",
                    "verificationGasLimit": "0x1",
                    "preVerificationGas": "0x1",
                }
            )

        with (
            patch.object(GasAbstractedSender, "_w3", return_value=w3),
            patch(f"{MODULE}.get_default_ledger_api", return_value=ledger_api),
            patch.object(GasAbstractedSender, "permit_typed_data") as mock_permit,
            patch.object(
                EthereumMasterWallet, "sign_typed_data", return_value="0x" + "22" * 65
            ),
            patch(f"{MODULE}.requests.post", side_effect=_post),
        ):
            mock_permit.return_value = {}
            prepared = sender.prepare_batch(Chain.BASE, [])

        assert methods == ["eth_estimateUserOperationGas"]
        assert prepared.user_op_hash == USER_OP_HASH
        assert prepared.authorization_nonce == 1
        assert prepared.nonce == 7
        assert prepared.block_number == 900


class TestUserOpLookups:
    """Where a UserOperation without a bundler receipt stands."""

    @pytest.mark.parametrize(("entrypoint_nonce", "used"), [(4, False), (5, True)])
    def test_nonce_used_once_the_entrypoint_moved_past_it(
        self, tmp_path: Path, entrypoint_nonce: int, used: bool
    ) -> None:
        """The EntryPoint nonce of the Master EOA says whether the op's nonce is spent."""
        sender, account = _sender(tmp_path)
        w3 = MagicMock()
        contract = w3.eth.contract.return_value
        contract.functions.getNonce.return_value.call.return_value = entrypoint_nonce

        with patch.object(GasAbstractedSender, "_w3", return_value=w3):
            assert sender.user_op_nonce_used(Chain.BASE, 4) is used

        contract.functions.getNonce.assert_called_once_with(account.address, 0)

    @pytest.mark.parametrize(
        ("by_hash", "known"), [({"userOperation": {}}, True), (None, False)]
    )
    def test_known_while_the_bundler_lists_it(
        self, tmp_path: Path, by_hash: t.Optional[t.Dict], known: bool
    ) -> None:
        """eth_getUserOperationByHash returning null means the bundler dropped it."""
        sender, _ = _sender(tmp_path)
        sent: t.List[t.Dict] = []

        def _post(url: str, json: t.Dict, timeout: int) -> MagicMock:
            sent.append(json)
            return _bundler_response(by_hash)

        with patch(f"{MODULE}.requests.post", side_effect=_post):
            assert sender.user_op_known(Chain.BASE, USER_OP_HASH) is known

        assert [(j["method"], j["params"]) for j in sent] == [
            ("eth_getUserOperationByHash", [USER_OP_HASH])
        ]

    @staticmethod
    def _event_log(success: bool) -> t.Dict:
        data = b"".join(v.to_bytes(32, "big") for v in (4, int(success), 1_000, 90_000))
        return {"data": data, "transactionHash": bytes.fromhex(HANDLE_OPS_TX[2:])}

    @pytest.mark.parametrize("success", [True, False])
    def test_event_becomes_a_bundler_style_receipt(
        self, tmp_path: Path, success: bool
    ) -> None:
        """The EntryPoint event gives the handleOps tx and the op's success flag."""
        sender, _ = _sender(tmp_path)
        w3 = MagicMock()
        w3.eth.block_number = 120
        w3.eth.get_logs.return_value = [self._event_log(success)]

        with patch.object(GasAbstractedSender, "_w3", return_value=w3):
            receipt = sender.find_user_op_event(Chain.BASE, USER_OP_HASH, 100)

        assert receipt is not None
        assert receipt["success"] is success
        if success:
            assert GasAbstractedSender.tx_hash_of(receipt) == HANDLE_OPS_TX
        else:
            with pytest.raises(UserOperationReverted):
                GasAbstractedSender.tx_hash_of(receipt)
        (query,) = [c.args[0] for c in w3.eth.get_logs.call_args_list]
        assert query == {
            "address": ERC4337_ENTRYPOINT,
            "topics": [USER_OPERATION_EVENT_TOPIC, USER_OP_HASH],
            "fromBlock": 100,
            "toBlock": 120,
        }

    def test_event_search_walks_the_range_in_chunks(self, tmp_path: Path) -> None:
        """Ranges wider than one chunk are searched chunk by chunk, up to latest."""
        sender, _ = _sender(tmp_path)
        w3 = MagicMock()
        w3.eth.block_number = 100 + 2 * LOG_BLOCK_CHUNK_SIZE
        w3.eth.get_logs.return_value = []

        with patch.object(GasAbstractedSender, "_w3", return_value=w3):
            assert sender.find_user_op_event(Chain.BASE, USER_OP_HASH, 100) is None

        ranges = [
            (c.args[0]["fromBlock"], c.args[0]["toBlock"])
            for c in w3.eth.get_logs.call_args_list
        ]
        assert ranges == [
            (100, 99 + LOG_BLOCK_CHUNK_SIZE),
            (100 + LOG_BLOCK_CHUNK_SIZE, 99 + 2 * LOG_BLOCK_CHUNK_SIZE),
            (100 + 2 * LOG_BLOCK_CHUNK_SIZE, 100 + 2 * LOG_BLOCK_CHUNK_SIZE),
        ]

    def test_event_topic_is_the_entrypoint_user_operation_event(self) -> None:
        """The topic is EntryPoint v0.8's UserOperationEvent signature hash."""
        assert USER_OPERATION_EVENT_TOPIC == (
            "0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f"
        )
