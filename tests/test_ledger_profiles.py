# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""Tests for operate.ledger.profiles module."""

import json
import re
import sys
import typing as t
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
from autonomy.chain.base import registry_contracts
from web3 import Web3

from operate.constants import NO_STAKING_PROGRAM_ID, ZERO_ADDRESS
from operate.ledger import NATIVE_CURRENCY_DECIMALS, get_default_rpc
from operate.ledger.profiles import (
    ERC20_TOKENS,
    ERC20_TOKENS_BY_CHAIN_ID,
    OLAS,
    PUSD,
    STAKING,
    WRAPPED_NATIVE_ASSET,
    format_asset_amount,
    get_asset_decimals,
    get_asset_name,
    get_staking_contract,
)
from operate.operate_types import Chain


class TestGetAssetName:
    """Tests for get_asset_name function (lines 338-348)."""

    def test_zero_address_returns_native_denom(self) -> None:
        """Test ZERO_ADDRESS returns the chain's native currency denom (line 339)."""
        result = get_asset_name(Chain.GNOSIS, ZERO_ADDRESS)
        assert result == "xDAI"

    def test_wrapped_native_asset_returns_w_prefixed(self) -> None:
        """Test wrapped native asset address returns 'W{denom}' (line 342)."""
        wrapped_address = WRAPPED_NATIVE_ASSET[Chain.GNOSIS]
        result = get_asset_name(Chain.GNOSIS, wrapped_address)
        assert result == "WxDAI"

    def test_known_erc20_returns_symbol(self) -> None:
        """Test a known ERC20 token address returns its symbol (lines 344-346)."""
        olas_address = OLAS[Chain.ETHEREUM]
        result = get_asset_name(Chain.ETHEREUM, olas_address)
        assert result == "OLAS"

    def test_unknown_address_returns_address_itself(self) -> None:
        """Test an unknown address is returned unchanged (line 348)."""
        unknown = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        result = get_asset_name(Chain.GNOSIS, unknown)
        assert result == unknown


class TestGetAssetDecimals:
    """Tests for get_asset_decimals function (lines 354-360)."""

    def test_zero_address_returns_native_decimals(self) -> None:
        """Test ZERO_ADDRESS returns NATIVE_CURRENCY_DECIMALS without RPC call (line 355)."""
        result = get_asset_decimals(Chain.BASE, ZERO_ADDRESS)
        assert result == NATIVE_CURRENCY_DECIMALS

    def test_erc20_address_calls_contract_decimals(self) -> None:
        """Test ERC20 address triggers on-chain decimals() call (lines 356-360)."""
        mock_instance = MagicMock()
        mock_instance.functions.decimals.return_value.call.return_value = 6

        # Use a unique fake address so the @cache does not return a previously stored result
        fake_erc20 = "0xFAKEERC20TOKENADDRESS0000000000000000001"

        with patch.object(
            registry_contracts.erc20,
            "get_instance",
            return_value=mock_instance,
        ):
            result = get_asset_decimals(Chain.GNOSIS, fake_erc20)

        assert result == 6


class TestFormatAssetAmount:
    """Tests for format_asset_amount function (lines 367-370)."""

    def test_format_native_amount_gnosis(self) -> None:
        """Test format_asset_amount returns human-readable string for native token."""
        # 1.5 xDAI = 1.5 * 10^18 wei
        amount = int(1.5 * 10**18)
        result = format_asset_amount(Chain.GNOSIS, ZERO_ADDRESS, amount)
        assert "1.5000" in result
        assert "xDAI" in result


class TestGetStakingContract:
    """Tests for get_staking_contract function (lines 378-384)."""

    def test_none_staking_program_id_returns_none(self) -> None:
        """Test None staking_program_id returns None (line 379)."""
        result = get_staking_contract("gnosis", None)
        assert result is None

    def test_no_staking_program_id_returns_none(self) -> None:
        """Test NO_STAKING_PROGRAM_ID returns None (line 379)."""
        result = get_staking_contract("gnosis", NO_STAKING_PROGRAM_ID)
        assert result is None

    def test_known_staking_program_returns_contract_address(self) -> None:
        """Test a known staking program ID returns its contract address (lines 381-383)."""
        result = get_staking_contract("gnosis", "pearl_alpha")
        assert result == "0xEE9F19b5DF06c7E8Bfc7B28745dcf944C504198A"

    def test_unknown_staking_program_returns_program_id(self) -> None:
        """Test an unknown staking program ID is returned unchanged (line 383)."""
        result = get_staking_contract("gnosis", "not_a_real_program_xyz")
        assert result == "not_a_real_program_xyz"


PUSD_ADDRESS = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"


class TestPUSDRegistration:
    """Tests for pUSD token registration in profiles."""

    def test_pusd_constant_has_polygon_entry(self) -> None:
        """PUSD dict must contain the Polygon address."""
        assert PUSD[Chain.POLYGON] == PUSD_ADDRESS

    def test_pusd_registered_in_erc20_tokens(self) -> None:
        """The 'pUSD' key must appear in ERC20_TOKENS."""
        assert "pUSD" in ERC20_TOKENS

    def test_pusd_erc20_tokens_value_matches_constant(self) -> None:
        """ERC20_TOKENS['pUSD'] must be the same dict as the PUSD constant."""
        assert ERC20_TOKENS["pUSD"] is PUSD

    def test_get_asset_name_resolves_pusd_on_polygon(self) -> None:
        """get_asset_name must return 'pUSD' for the Polygon pUSD address."""
        # get_asset_name is @cached; call with a fresh address to avoid cache collision
        result = get_asset_name(Chain.POLYGON, PUSD_ADDRESS)
        assert result == "pUSD"

    def test_pusd_address_in_erc20_tokens_by_chain_id(self) -> None:
        """The pUSD address must appear in ERC20_TOKENS_BY_CHAIN_ID for the Polygon chain ID."""
        polygon_id = Chain.POLYGON.id
        assert PUSD_ADDRESS in ERC20_TOKENS_BY_CHAIN_ID[polygon_id]


# --- staking_program_id convention (see the STAKING docstring in profiles.py) ---

#: Matches a well-formed lower_snake_case id: lowercase alphanumerics in groups
#: joined by single underscores, with no leading/trailing/double underscores.
_STAKING_ID_FORMAT = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")

#: Existing ids whose slug does not equal their on-chain metadata name. These
#: predate the convention and are frozen for backward compatibility (the id is
#: hardcoded in the frontend and persisted on users' machines), so they are
#: grandfathered out of the slug-matches-name check. Do NOT add new entries
#: here: a new contract should instead be given an id that matches its slug.
_LEGACY_STAKING_ID_EXCEPTIONS: t.Dict[Chain, t.Set[str]] = {
    Chain.GNOSIS: {
        "quickstart_beta_expert_15_mech_marketplace",
        "quickstart_beta_expert_16_mech_marketplace",
        "quickstart_beta_expert_17_mech_marketplace",
        "quickstart_beta_expert_18_mech_marketplace",
        "pearl_beta_mech_marketplace_1",
        "pearl_beta_mech_marketplace_2",
        "pearl_beta_mech_marketplace_3",
        "pearl_beta_mech_marketplace_4",
        "pearl_beta_mech_marketplace_5",
        "pearl_beta_mech_marketplace_6",
        "pearl_beta_mech_marketplace_7",
        "pearl_beta_mech_marketplace_8",
        "mech_marketplace",
    },
    Chain.OPTIMISM: {
        "optimus_alpha_1",
        "optimus_alpha_2",
        "optimus_alpha_3",
        "optimus_alpha_4",
    },
    Chain.BASE: {
        "meme_base_alpha_2",
        "meme_base_beta",
        "meme_base_beta_2",
        "meme_base_beta_3",
        "pett_ai_agent_1",
        "pett_ai_agent_2",
        "pett_ai_agent_3",
        "pett_ai_agent_4",
    },
    Chain.CELO: {
        "meme_celo_alpha_2",
    },
    Chain.MODE: {
        "modius_alpha_2",
        "modius_alpha_3",
        "modius_alpha_4",
    },
    Chain.POLYGON: {
        "polygon_beta_1",
        "polygon_beta_2",
        "polygon_beta_3",
    },
}

_METADATA_HASH_ABI = [
    {
        "inputs": [],
        "name": "metadataHash",
        "outputs": [{"type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    }
]

_IPFS_GATEWAYS = (
    "https://gateway.autonolas.tech/ipfs/",
    "https://ipfs.io/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
    "https://dweb.link/ipfs/",
)


class _MetadataUnavailable(Exception):
    """Raised when on-chain/IPFS metadata cannot be retrieved (transient)."""


_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

#: Flattened (chain, staking_program_id, address) triples across every chain.
_STAKING_ENTRIES = [
    (chain, program_id, address)
    for chain, programs in STAKING.items()
    for program_id, address in programs.items()
]


def _slugify(name: str) -> str:
    """Lower_snake_case slug of a metadata name (the documented convention)."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _base58(data: bytes) -> str:
    """Minimal base58 (btc alphabet) encoder for building an IPFS CIDv0."""
    number = int.from_bytes(data, "big")
    encoded = ""
    while number > 0:
        number, remainder = divmod(number, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * leading_zeros + encoded


def _onchain_metadata_name(chain: Chain, address: str) -> str:
    """Read metadataHash() on-chain and resolve the metadata's ``name`` via IPFS.

    Tries several gateways for endpoint diversity; raises _MetadataUnavailable
    on RPC/IPFS failure so the caller can skip rather than fail CI when a
    public endpoint is unreachable or blocked.
    """
    try:
        w3 = Web3(Web3.HTTPProvider(get_default_rpc(chain)))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(address), abi=_METADATA_HASH_ABI
        )
        metadata_hash = contract.functions.metadataHash().call()
    except Exception as error:  # pylint: disable=broad-except
        raise _MetadataUnavailable(
            f"RPC metadataHash() failed for {chain.value} {address}: {error}"
        )
    # bytes32 sha2-256 digest -> CIDv0 (prepend the 0x1220 multihash prefix).
    cid = _base58(b"\x12\x20" + metadata_hash)
    last_error: t.Optional[Exception] = None
    for gateway in _IPFS_GATEWAYS:
        try:
            # Gateways are fixed https:// constants, so the scheme is safe.
            with urllib.request.urlopen(  # nosec B310
                gateway + cid, timeout=30
            ) as response:
                return json.loads(response.read())["name"]
        except (OSError, ValueError, KeyError) as error:
            # Gateway/parse failure -> try the next gateway.
            last_error = error
    raise _MetadataUnavailable(
        f"Could not fetch staking metadata for {chain.value} {address} "
        f"(cid {cid}): {last_error}"
    )


class TestStakingProgramIdConvention:
    """Enforce the staking_program_id naming convention documented on STAKING."""

    def test_ids_are_lower_snake_case(self) -> None:
        """Every staking_program_id must be well-formed lower_snake_case (offline)."""
        malformed = [
            f"{chain.value}:{program_id}"
            for chain, program_id, _ in _STAKING_ENTRIES
            if not _STAKING_ID_FORMAT.match(program_id)
        ]
        assert not malformed, f"staking ids are not lower_snake_case: {malformed}"

    def test_legacy_exceptions_reference_real_ids(self) -> None:
        """The grandfathering allowlist must not contain stale/unknown ids (offline)."""
        for chain, exceptions in _LEGACY_STAKING_ID_EXCEPTIONS.items():
            known = set(STAKING.get(chain, {}))
            unknown = exceptions - known
            assert (
                not unknown
            ), f"{chain.value} legacy exceptions reference unknown ids: {sorted(unknown)}"

    @pytest.mark.integration
    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="OS-independent on-chain/IPFS check; run once on Linux",
    )
    @pytest.mark.parametrize(
        ("chain", "program_id", "address"),
        _STAKING_ENTRIES,
        ids=[
            f"{chain.value}-{program_id}" for chain, program_id, _ in _STAKING_ENTRIES
        ],
    )
    def test_id_matches_onchain_metadata_name(
        self, chain: Chain, program_id: str, address: str
    ) -> None:
        """A staking_program_id must equal the slug of its on-chain metadata name.

        Existing divergent ids are frozen for backward compatibility and are
        grandfathered via _LEGACY_STAKING_ID_EXCEPTIONS; any newly added
        contract must satisfy ``id == lower_snake_case(metadata["name"])``.

        Skips (rather than fails) when the public RPC/IPFS endpoint is
        unreachable or blocked (e.g. CI runners get HTTP 401 from some public
        RPCs), so the convention is enforced whenever the data is reachable
        without redding CI on infrastructure we do not control.
        """
        if program_id in _LEGACY_STAKING_ID_EXCEPTIONS.get(chain, set()):
            pytest.skip(f"{program_id} is a grandfathered legacy id")

        try:
            name = _onchain_metadata_name(chain, address)
        except _MetadataUnavailable as error:
            pytest.skip(str(error))
        slug = _slugify(name)
        if not slug:
            # An empty/non-alphanumeric on-chain name yields an empty slug; skip
            # with a clear reason instead of a confusing `program_id == ""` assert.
            pytest.skip(
                f"on-chain metadata name is empty for {chain.value} {address!r}"
            )
        assert program_id == slug, (
            f"{chain.value} staking id {program_id!r} does not match the slug "
            f"{slug!r} of its on-chain metadata name {name!r}. Either fix the id "
            f"or (only for a pre-existing frozen id) add it to "
            f"_LEGACY_STAKING_ID_EXCEPTIONS."
        )
