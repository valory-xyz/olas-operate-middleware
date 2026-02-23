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

"""Unit tests for operate/bridge/bridge_manager.py – no network calls required."""

import typing as t
from pathlib import Path
from unittest.mock import MagicMock

from operate.bridge.bridge_manager import BridgeManagerData, ProviderRequestBundle
from operate.operate_types import Chain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider_request(
    from_chain: str,
    from_address: str,
    from_token: str,
) -> MagicMock:
    """Create a minimal mock ProviderRequest with the required params structure."""
    mock_req = MagicMock()
    mock_req.params = {
        "from": {
            "chain": from_chain,
            "address": from_address,
            "token": from_token,
        },
        "to": {"chain": "gnosis"},
    }
    return mock_req


def _make_bundle(provider_requests: t.List) -> ProviderRequestBundle:
    """Create a ProviderRequestBundle with the given provider requests."""
    return ProviderRequestBundle(
        requests_params=[],
        provider_requests=provider_requests,
        timestamp=1000,
        id="rb-test",
    )


# ---------------------------------------------------------------------------
# ProviderRequestBundle.get_from_chains
# ---------------------------------------------------------------------------


class TestGetFromChains:
    """Tests for ProviderRequestBundle.get_from_chains (lines 128-132)."""

    def test_empty_requests_returns_empty_set(self) -> None:
        """Test that empty provider_requests returns an empty set."""
        bundle = _make_bundle([])
        result = bundle.get_from_chains()
        assert result == set()

    def test_single_request_returns_single_chain(self) -> None:
        """Test that a single request returns the correct chain."""
        req = _make_provider_request("gnosis", "0xAddr", "0x0000")
        bundle = _make_bundle([req])
        result = bundle.get_from_chains()
        assert result == {Chain.GNOSIS}

    def test_multiple_requests_different_chains(self) -> None:
        """Test that multiple requests from different chains returns correct set."""
        req1 = _make_provider_request("gnosis", "0xAddr1", "0x0001")
        req2 = _make_provider_request("base", "0xAddr2", "0x0002")
        bundle = _make_bundle([req1, req2])
        result = bundle.get_from_chains()
        assert result == {Chain.GNOSIS, Chain.BASE}

    def test_duplicate_chains_deduplicated(self) -> None:
        """Test that duplicate from-chains are deduplicated in the result set."""
        req1 = _make_provider_request("gnosis", "0xAddr1", "0x0001")
        req2 = _make_provider_request("gnosis", "0xAddr2", "0x0002")
        bundle = _make_bundle([req1, req2])
        result = bundle.get_from_chains()
        assert result == {Chain.GNOSIS}
        assert len(result) == 1


# ---------------------------------------------------------------------------
# ProviderRequestBundle.get_from_addresses
# ---------------------------------------------------------------------------


class TestGetFromAddresses:
    """Tests for ProviderRequestBundle.get_from_addresses (lines 134-141)."""

    def test_returns_addresses_for_matching_chain(self) -> None:
        """Test that only addresses on the given chain are returned."""
        req1 = _make_provider_request("gnosis", "0xAddr1", "0x0001")
        req2 = _make_provider_request("base", "0xAddr2", "0x0002")
        bundle = _make_bundle([req1, req2])
        result = bundle.get_from_addresses(Chain.GNOSIS)
        assert result == {"0xAddr1"}

    def test_returns_empty_set_for_non_matching_chain(self) -> None:
        """Test that no addresses are returned when chain doesn't match."""
        req = _make_provider_request("gnosis", "0xAddr1", "0x0001")
        bundle = _make_bundle([req])
        result = bundle.get_from_addresses(Chain.BASE)
        assert result == set()

    def test_multiple_addresses_same_chain(self) -> None:
        """Test that multiple addresses on the same chain are all returned."""
        req1 = _make_provider_request("gnosis", "0xAddr1", "0x0001")
        req2 = _make_provider_request("gnosis", "0xAddr2", "0x0002")
        bundle = _make_bundle([req1, req2])
        result = bundle.get_from_addresses(Chain.GNOSIS)
        assert result == {"0xAddr1", "0xAddr2"}


# ---------------------------------------------------------------------------
# ProviderRequestBundle.get_from_tokens
# ---------------------------------------------------------------------------


class TestGetFromTokens:
    """Tests for ProviderRequestBundle.get_from_tokens (lines 143-150)."""

    def test_returns_tokens_for_matching_chain(self) -> None:
        """Test that only tokens on the given chain are returned."""
        req1 = _make_provider_request("gnosis", "0xAddr1", "0xToken1")
        req2 = _make_provider_request("base", "0xAddr2", "0xToken2")
        bundle = _make_bundle([req1, req2])
        result = bundle.get_from_tokens(Chain.GNOSIS)
        assert result == {"0xToken1"}

    def test_returns_empty_set_for_non_matching_chain(self) -> None:
        """Test that no tokens are returned when chain doesn't match."""
        req = _make_provider_request("gnosis", "0xAddr1", "0xToken1")
        bundle = _make_bundle([req])
        result = bundle.get_from_tokens(Chain.BASE)
        assert result == set()

    def test_multiple_tokens_same_chain_deduplicated(self) -> None:
        """Test that duplicate tokens on same chain are deduplicated."""
        req1 = _make_provider_request("gnosis", "0xAddr1", "0xTokenA")
        req2 = _make_provider_request("gnosis", "0xAddr2", "0xTokenA")
        bundle = _make_bundle([req1, req2])
        result = bundle.get_from_tokens(Chain.GNOSIS)
        assert result == {"0xTokenA"}
        assert len(result) == 1


# ---------------------------------------------------------------------------
# BridgeManagerData.load
# ---------------------------------------------------------------------------


class TestBridgeManagerDataLoad:
    """Tests for BridgeManagerData.load (lines 171-186)."""

    def test_creates_default_file_when_missing(self, tmp_path: Path) -> None:
        """Test that a missing bridge.json is created with defaults."""
        assert not (tmp_path / "bridge.json").exists()
        data = t.cast(BridgeManagerData, BridgeManagerData.load(tmp_path))
        assert (tmp_path / "bridge.json").exists()
        assert data.version == 1
        assert data.last_requested_bundle is None
        assert data.last_executed_bundle_id is None

    def test_loads_valid_existing_file(self, tmp_path: Path) -> None:
        """Test that a valid bridge.json is loaded correctly."""
        BridgeManagerData(path=tmp_path).store()
        data = t.cast(BridgeManagerData, BridgeManagerData.load(tmp_path))
        assert data.version == 1
        assert data.last_requested_bundle is None

    def test_handles_invalid_json_by_creating_new(self, tmp_path: Path) -> None:
        """Test that an invalid bridge.json is renamed and a new default is created."""
        (tmp_path / "bridge.json").write_text("not-valid-json", encoding="utf-8")
        data = t.cast(BridgeManagerData, BridgeManagerData.load(tmp_path))
        assert data.version == 1
        # The bad file should have been renamed
        renamed = list(tmp_path.glob("invalid_*_bridge.json"))
        assert len(renamed) == 1
        # The new valid bridge.json should exist
        assert (tmp_path / "bridge.json").exists()

    def test_handles_missing_key_in_json(self, tmp_path: Path) -> None:
        """Test that a bridge.json with missing key triggers re-creation."""
        import json

        # Write valid JSON but missing required key
        (tmp_path / "bridge.json").write_text(
            json.dumps({"unexpected_key": 1}), encoding="utf-8"
        )
        data = t.cast(BridgeManagerData, BridgeManagerData.load(tmp_path))
        assert data.version == 1
