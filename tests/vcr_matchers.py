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

"""Cassette matchers that ignore the RPC host but check what is requested."""

import json
import re
import typing as t
from urllib.parse import urlsplit

MATCH_ON = ["method", "rpc_uri", "rpc_body"]

# Matched as whole tokens of the host and path, so "developer" is not Optimism.
_CHAIN_TOKENS = {
    "arbitrum": {"arbitrum", "arb"},
    "base": {"base"},
    "celo": {"celo"},
    "ethereum": {"ethereum", "eth"},
    "gnosis": {"gnosis", "xdai"},
    "mode": {"mode"},
    "optimism": {"optimism", "op", "opt"},
    "polygon": {"polygon", "matic"},
    "robinhood": {"robinhood"},
    "solana": {"solana"},
}
_TOKEN = re.compile(r"[a-z0-9]+")
_EVM_ADDRESS = re.compile(rb"0x[0-9a-fA-F]{40}")


def infer_chain(uri: str) -> t.Optional[str]:
    """The chain an RPC URI serves, or None when it is not recognisable."""
    parts = urlsplit(uri.lower())
    tokens = set(_TOKEN.findall(f"{parts.netloc}/{parts.path}"))
    chains = {chain for chain, names in _CHAIN_TOKENS.items() if tokens & names}
    return chains.pop() if len(chains) == 1 else None


def _rpc_calls(
    request: t.Any,
) -> t.Optional[t.Tuple[bool, t.List[t.Tuple[t.Any, t.Any]]]]:
    """Whether the body is a batch and its (method, params); None if not JSON-RPC."""
    try:
        payload = json.loads(request.body)
    except (TypeError, ValueError):
        return None
    batch = isinstance(payload, list)
    calls = payload if batch else [payload]
    if not calls or not all(
        isinstance(call, dict) and call.get("jsonrpc") == "2.0" for call in calls
    ):
        return None
    return batch, [(call.get("method"), call.get("params")) for call in calls]


def _fold_addresses(body: t.Optional[bytes]) -> bytes:
    """Make the comparison insensitive to address checksum casing."""
    return _EVM_ADDRESS.sub(lambda match: match.group().lower(), body or b"")


def rpc_uri(request_1: t.Any, request_2: t.Any) -> bool:
    """JSON-RPC requests match on chain, any other request on the exact URI."""
    if _rpc_calls(request_1) is not None and _rpc_calls(request_2) is not None:
        chain_1, chain_2 = infer_chain(request_1.uri), infer_chain(request_2.uri)
        if chain_1 is not None and chain_2 is not None:
            return chain_1 == chain_2
    return bool(request_1.uri == request_2.uri)


def rpc_body(request_1: t.Any, request_2: t.Any) -> bool:
    """JSON-RPC requests match on method and params, any other on the body."""
    calls_1, calls_2 = _rpc_calls(request_1), _rpc_calls(request_2)
    if calls_1 is not None and calls_2 is not None:
        return calls_1 == calls_2
    return _fold_addresses(request_1.body) == _fold_addresses(request_2.body)
