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

"""Tests for the cassette matchers in tests/vcr_matchers.py."""

import json
import typing as t

import pytest
from vcr.request import Request

from tests.vcr_matchers import infer_chain, rpc_body, rpc_uri

ETH = "https://rpc-gate.autonolas.tech/ethereum-rpc/"
ETH_OTHER_HOST = "https://eth-mainnet.g.alchemy.com/v2/key"
OPTIMISM = "https://mainnet.optimism.io"
RELAY = "https://api.relay.link/quote"


def _rpc(uri: str, method: str, params: t.Any, request_id: int = 1) -> Request:
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    return Request("POST", uri, json.dumps(body).encode(), {})


def _batch(uri: str, *calls: t.Tuple[str, t.Any]) -> Request:
    body = [
        {"jsonrpc": "2.0", "id": i, "method": m, "params": p}
        for i, (m, p) in enumerate(calls)
    ]
    return Request("POST", uri, json.dumps(body).encode(), {})


@pytest.mark.parametrize(
    ("uri", "chain"),
    [
        (ETH, "ethereum"),
        (ETH_OTHER_HOST, "ethereum"),
        (OPTIMISM, "optimism"),
        ("https://opt-mainnet.g.alchemy.com/v2/key", "optimism"),
        ("https://arb1.arbitrum.io/rpc", "arbitrum"),
        ("https://mainnet.base.org", "base"),
        ("https://gnosis-rpc.publicnode.com", "gnosis"),
        ("https://polygon-rpc.com", "polygon"),
        ("https://mainnet.mode.network", "mode"),
        ("https://rpc.mainnet.chain.robinhood.com", "robinhood"),
        ("https://developer.alchemy.com/v2/key", None),
        ("https://database.example.com", None),
        ("https://automatic.example.com", None),
        ("http://127.0.0.1:8545", None),
        ("https://eth.base.example.com", None),
    ],
)
def test_infer_chain_matches_whole_tokens_only(
    uri: str, chain: t.Optional[str]
) -> None:
    """A chain is read from whole host/path tokens, never from substrings."""
    assert infer_chain(uri) == chain


class TestRpcUri:
    """Tests for rpc_uri."""

    def test_same_chain_on_another_host_matches(self) -> None:
        """Cassettes replay against whichever RPC provider the developer uses."""
        assert (
            rpc_uri(
                _rpc(ETH, "eth_chainId", []), _rpc(ETH_OTHER_HOST, "eth_chainId", [])
            )
            is True
        )

    def test_other_chain_does_not_match(self) -> None:
        """The same call on another chain is another request."""
        assert (
            rpc_uri(_rpc(ETH, "eth_chainId", []), _rpc(OPTIMISM, "eth_chainId", []))
            is False
        )

    def test_unknown_host_requires_the_exact_uri(self) -> None:
        """A host that names no chain only matches itself."""
        unknown = "https://developer.alchemy.com/v2/key"
        assert (
            rpc_uri(_rpc(unknown, "eth_chainId", []), _rpc(OPTIMISM, "eth_chainId", []))
            is False
        )
        assert (
            rpc_uri(_rpc(unknown, "eth_chainId", []), _rpc(unknown, "eth_chainId", []))
            is True
        )

    def test_non_rpc_requests_match_on_the_exact_uri(self) -> None:
        """Bridge API calls compare the full URI, query included."""
        quote = Request("POST", RELAY, b'{"user":"0xabc"}', {})
        assert rpc_uri(quote, Request("POST", RELAY, b'{"user":"0xabc"}', {})) is True
        assert (
            rpc_uri(quote, Request("POST", RELAY + "?v=2", b'{"user":"0xabc"}', {}))
            is False
        )


class TestRpcBody:
    """Tests for rpc_body."""

    def test_matches_on_method_and_params_and_ignores_the_id(self) -> None:
        """The JSON-RPC id is a counter, not part of what is requested."""
        call = _rpc(ETH, "eth_getBalance", ["0xabc", "latest"], request_id=7)
        same = _rpc(ETH, "eth_getBalance", ["0xabc", "latest"], request_id=99)
        assert rpc_body(call, same) is True

    @pytest.mark.parametrize(
        "other",
        [
            _rpc(ETH, "eth_getCode", ["0xabc", "latest"]),
            _rpc(ETH, "eth_getBalance", ["0xdef", "latest"]),
            _batch(ETH, ("eth_getBalance", ["0xabc", "latest"])),
        ],
        ids=["method", "params", "batch-vs-single"],
    )
    def test_rejects_a_different_call(self, other: Request) -> None:
        """Any difference in what is requested is a mismatch."""
        assert (
            rpc_body(_rpc(ETH, "eth_getBalance", ["0xabc", "latest"]), other) is False
        )

    def test_batches_match_call_by_call(self) -> None:
        """A batch matches a batch with the same calls in the same order."""
        batch = _batch(ETH, ("eth_chainId", []), ("eth_blockNumber", []))
        assert (
            rpc_body(batch, _batch(ETH, ("eth_chainId", []), ("eth_blockNumber", [])))
            is True
        )
        assert (
            rpc_body(batch, _batch(ETH, ("eth_blockNumber", []), ("eth_chainId", [])))
            is False
        )

    def test_non_rpc_bodies_match_exactly_up_to_address_casing(self) -> None:
        """Bridge API bodies compare byte for byte, with addresses case-folded."""
        address = "0x" + "ab" * 20
        body = Request("POST", RELAY, f'{{"user":"{address}"}}'.encode(), {})
        checksummed = Request(
            "POST",
            RELAY,
            f'{{"user":"{address.upper().replace("0X", "0x")}"}}'.encode(),
            {},
        )
        other_user = Request(
            "POST", RELAY, f'{{"user":"{"0x" + "cd" * 20}"}}'.encode(), {}
        )
        assert rpc_body(body, checksummed) is True
        assert rpc_body(body, other_user) is False

    def test_rpc_and_non_rpc_bodies_never_match(self) -> None:
        """A JSON-RPC call is not the same request as a JSON API call."""
        assert (
            rpc_body(_rpc(ETH, "eth_chainId", []), Request("POST", ETH, b'{"a":1}', {}))
            is False
        )

    def test_returns_booleans(self) -> None:
        """Only bools are safe: vcrpy treats any truthy return as a match."""
        a, b = _rpc(ETH, "eth_chainId", []), _rpc(OPTIMISM, "eth_call", [{}])
        assert rpc_uri(a, b) is False
        assert rpc_body(a, b) is False
        assert rpc_uri(a, a) is True
        assert rpc_body(a, a) is True
