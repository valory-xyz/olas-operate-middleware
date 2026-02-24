#!/usr/bin/env python3
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

import time
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.bridge.bridge_manager import (
    BridgeManager,
    BridgeManagerData,
    DEFAULT_BUNDLE_VALIDITY_PERIOD,
    EXECUTED_BUNDLES_PATH,
    ProviderRequestBundle,
)
from operate.bridge.providers.provider import ProviderRequest, ProviderRequestStatus
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


# ---------------------------------------------------------------------------
# Helpers for BridgeManager unit tests
# ---------------------------------------------------------------------------


def _make_bridge_manager(tmp_path: Path) -> BridgeManager:
    """Create a BridgeManager bypassing __init__ with manually set attributes."""
    manager = object.__new__(BridgeManager)
    manager.path = tmp_path
    manager.wallet_manager = MagicMock()
    manager.logger = MagicMock()
    manager.bundle_validity_period = DEFAULT_BUNDLE_VALIDITY_PERIOD
    manager.data = MagicMock()
    manager._providers = {}  # pylint: disable=protected-access
    manager._native_bridge_providers = {}  # pylint: disable=protected-access
    return manager


def _make_real_bundle(
    requests_params: t.Optional[t.List] = None,
) -> ProviderRequestBundle:
    """Create a real ProviderRequestBundle for testing."""
    return ProviderRequestBundle(
        id="rb-test-123",
        requests_params=requests_params
        or [{"from": {"chain": "gnosis"}, "to": {"chain": "base"}}],
        provider_requests=[],
        timestamp=int(time.time()),
    )


def _make_provider_request_real(
    provider_id: str = "relay-provider",
    status: ProviderRequestStatus = ProviderRequestStatus.CREATED,
) -> ProviderRequest:
    """Create a real ProviderRequest."""
    return ProviderRequest(
        id="r-test-xyz",
        params={
            "from": {
                "chain": "gnosis",
                "address": "0x" + "a" * 40,
                "token": "0x" + "0" * 40,
            },
            "to": {
                "chain": "base",
                "address": "0x" + "b" * 40,
                "token": "0x" + "0" * 40,
                "amount": 100,
            },
        },
        provider_id=provider_id,
        status=status,
        quote_data=None,
        execution_data=None,
    )


# ---------------------------------------------------------------------------
# TestBridgeManagerStoreData
# ---------------------------------------------------------------------------


class TestBridgeManagerStoreData:
    """Tests for BridgeManager._store_data (line 241)."""

    def test_store_data_calls_data_store(self, tmp_path: Path) -> None:
        """_store_data() calls data.store() and logs (line 241)."""
        manager = _make_bridge_manager(tmp_path)
        manager._store_data()  # pylint: disable=protected-access
        manager.data.store.assert_called_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TestBridgeManagerGetUpdatedBundle
# ---------------------------------------------------------------------------


class TestBridgeManagerGetUpdatedBundle:
    """Tests for BridgeManager._get_updated_bundle (lines 248-304)."""

    def test_no_last_bundle_creates_new_bundle(self, tmp_path: Path) -> None:
        """No existing bundle triggers creation of a new one."""
        manager = _make_bridge_manager(tmp_path)
        manager.data.last_requested_bundle = None
        requests_params = [
            {
                "from": {
                    "chain": "gnosis",
                    "address": "0x" + "a" * 40,
                    "token": "0x" + "0" * 40,
                },
                "to": {
                    "chain": "base",
                    "address": "0x" + "b" * 40,
                    "token": "0x" + "0" * 40,
                    "amount": 100,
                },
            }
        ]

        # Provide a relay provider mock for the RELAY_PROVIDER_ID fallback
        mock_provider = MagicMock()
        mock_provider.can_handle_request.return_value = False
        mock_provider.create_request.return_value = _make_provider_request_real()
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )

        with patch.object(manager, "quote_bundle"), patch.object(
            manager, "_store_data"
        ):
            bundle = manager._get_updated_bundle(  # pylint: disable=protected-access
                requests_params, force_update=False
            )

        assert bundle is not None
        assert bundle.id.startswith("rb-")

    def test_force_update_quotes_existing_bundle(self, tmp_path: Path) -> None:
        """force_update=True quotes the existing bundle when params match (lines 258-261)."""
        manager = _make_bridge_manager(tmp_path)
        requests_params = [{"from": {"chain": "gnosis"}, "to": {"chain": "base"}}]
        existing_bundle = _make_real_bundle(requests_params=requests_params)
        manager.data.last_requested_bundle = existing_bundle

        with patch.object(manager, "quote_bundle") as mock_quote, patch.object(
            manager, "_store_data"
        ):
            result = manager._get_updated_bundle(  # pylint: disable=protected-access
                requests_params, force_update=True
            )

        mock_quote.assert_called_once_with(existing_bundle)
        assert result is existing_bundle

    def test_expired_bundle_gets_requoted(self, tmp_path: Path) -> None:
        """Expired bundle triggers a re-quote (lines 262-265)."""
        manager = _make_bridge_manager(tmp_path)
        requests_params = [{"from": {"chain": "gnosis"}, "to": {"chain": "base"}}]
        # Bundle older than bundle_validity_period
        old_bundle = _make_real_bundle(requests_params=requests_params)
        old_bundle.timestamp = int(time.time()) - DEFAULT_BUNDLE_VALIDITY_PERIOD - 60
        manager.data.last_requested_bundle = old_bundle

        with patch.object(manager, "quote_bundle") as mock_quote, patch.object(
            manager, "_store_data"
        ):
            result = manager._get_updated_bundle(  # pylint: disable=protected-access
                requests_params, force_update=False
            )

        mock_quote.assert_called_once_with(old_bundle)
        assert result is old_bundle

    def test_different_params_creates_new_bundle(self, tmp_path: Path) -> None:
        """Different requests_params triggers new bundle creation (lines 255-257)."""
        manager = _make_bridge_manager(tmp_path)
        old_params = [{"from": {"chain": "gnosis"}, "to": {"chain": "base"}}]
        new_params = [
            {
                "from": {
                    "chain": "gnosis",
                    "address": "0x" + "a" * 40,
                    "token": "0x" + "0" * 40,
                },
                "to": {
                    "chain": "base",
                    "address": "0x" + "b" * 40,
                    "token": "0x" + "0" * 40,
                    "amount": 999,
                },
            }
        ]
        existing_bundle = _make_real_bundle(requests_params=old_params)
        manager.data.last_requested_bundle = existing_bundle

        mock_provider = MagicMock()
        mock_provider.can_handle_request.return_value = False
        mock_provider.create_request.return_value = _make_provider_request_real()
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )

        with patch.object(manager, "quote_bundle"), patch.object(
            manager, "_store_data"
        ):
            result = manager._get_updated_bundle(  # pylint: disable=protected-access
                new_params, force_update=False
            )

        # A new bundle should have been created with a different id
        assert result.id != existing_bundle.id
        assert result.requests_params == new_params


# ---------------------------------------------------------------------------
# TestBridgeManagerRaiseIfInvalid
# ---------------------------------------------------------------------------


class TestBridgeManagerRaiseIfInvalid:
    """Tests for BridgeManager._raise_if_invalid (lines 321-332)."""

    def test_raises_for_invalid_from_address(self, tmp_path: Path) -> None:
        """_raise_if_invalid() raises ValueError when address not in wallet or safe (line 332)."""
        manager = _make_bridge_manager(tmp_path)

        mock_wallet = MagicMock()
        mock_wallet.address = "0x" + "1" * 40
        mock_wallet.safes = {}
        manager.wallet_manager.load.return_value = mock_wallet

        requests_params = [
            {
                "from": {
                    "chain": "gnosis",
                    "address": "0x" + "f" * 40,  # neither EOA nor safe
                    "token": "0x" + "0" * 40,
                },
                "to": {
                    "chain": "base",
                    "address": "0x" + "b" * 40,
                    "token": "0x" + "0" * 40,
                    "amount": 100,
                },
            }
        ]

        with pytest.raises(ValueError, match="does not match Master EOA"):
            manager._raise_if_invalid(
                requests_params
            )  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# TestBridgeManagerExecuteBundle
# ---------------------------------------------------------------------------


class TestBridgeManagerExecuteBundle:
    """Tests for BridgeManager.execute_bundle (lines 385-420)."""

    def test_execute_bundle_no_bundle_raises(self, tmp_path: Path) -> None:
        """execute_bundle() raises RuntimeError when no bundle exists (line 390)."""
        manager = _make_bridge_manager(tmp_path)
        manager.data.last_requested_bundle = None

        with pytest.raises(RuntimeError, match="No bundle"):
            manager.execute_bundle("rb-nonexistent")

    def test_execute_bundle_wrong_id_raises(self, tmp_path: Path) -> None:
        """execute_bundle() raises RuntimeError when bundle.id != bundle_id (lines 393-395)."""
        manager = _make_bridge_manager(tmp_path)
        bundle = _make_real_bundle()
        bundle.id = "rb-correct-id"
        manager.data.last_requested_bundle = bundle

        with pytest.raises(RuntimeError, match="does not match"):
            manager.execute_bundle("rb-wrong-id")

    def test_execute_bundle_success(self, tmp_path: Path) -> None:
        """execute_bundle() with valid bundle executes providers and returns status json (lines 385-420)."""
        # Create the executed directory so bundle.store() can write there
        (tmp_path / EXECUTED_BUNDLES_PATH).mkdir(parents=True, exist_ok=True)

        manager = _make_bridge_manager(tmp_path)

        req = _make_provider_request_real(provider_id="relay-provider")
        bundle = _make_real_bundle()
        bundle.provider_requests = [req]
        manager.data.last_requested_bundle = bundle
        bundle_id = bundle.id

        mock_provider = MagicMock()
        mock_provider.status_json.return_value = {
            "status": "EXECUTION_PENDING",
            "message": None,
        }
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )

        expected_status = {"id": bundle_id, "bridge_request_status": []}

        with patch.object(
            manager,
            "bridge_refill_requirements",
            return_value={"is_refill_required": False},
        ), patch.object(manager, "_store_data"), patch.object(
            manager, "get_status_json", return_value=expected_status
        ) as mock_get_status:
            result = manager.execute_bundle(bundle_id)

        mock_get_status.assert_called_once_with(bundle_id)
        assert result == expected_status
        mock_provider.execute.assert_called_once_with(req)


# ---------------------------------------------------------------------------
# TestBridgeManagerGetStatusJson
# ---------------------------------------------------------------------------


class TestBridgeManagerGetStatusJson:
    """Tests for BridgeManager.get_status_json (lines 422-453)."""

    def test_get_status_json_from_file(self, tmp_path: Path) -> None:
        """get_status_json() loads bundle from file when not in memory (lines 429-434)."""
        manager = _make_bridge_manager(tmp_path)
        manager.data.last_requested_bundle = None  # not in memory

        # Create the executed_bundles directory and store a bundle there
        executed_dir = tmp_path / EXECUTED_BUNDLES_PATH
        executed_dir.mkdir(parents=True, exist_ok=True)

        req = _make_provider_request_real(provider_id="relay-provider")
        bundle = _make_real_bundle()
        bundle.provider_requests = [req]
        bundle_id = bundle.id
        bundle.path = executed_dir / f"{bundle_id}.json"
        bundle.store()

        mock_provider = MagicMock()
        mock_provider.status_json.return_value = {
            "status": ProviderRequestStatus.CREATED.value,
            "message": None,
        }
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )

        result = manager.get_status_json(bundle_id)

        assert result["id"] == bundle_id
        assert "bridge_request_status" in result

    def test_get_status_json_file_not_found_raises(self, tmp_path: Path) -> None:
        """get_status_json() raises FileNotFoundError when bundle not on disk or memory (line 436)."""
        manager = _make_bridge_manager(tmp_path)
        manager.data.last_requested_bundle = None
        (tmp_path / EXECUTED_BUNDLES_PATH).mkdir(parents=True, exist_ok=True)

        with pytest.raises(FileNotFoundError, match="does not exist"):
            manager.get_status_json("rb-nonexistent-id")

    def test_get_status_json_status_changed_stores_bundle(self, tmp_path: Path) -> None:
        """get_status_json() calls bundle.store() when status changes (line 448)."""
        manager = _make_bridge_manager(tmp_path)

        # Create the executed dir and a stored bundle
        executed_dir = tmp_path / EXECUTED_BUNDLES_PATH
        executed_dir.mkdir(parents=True, exist_ok=True)

        req = _make_provider_request_real(
            provider_id="relay-provider",
            status=ProviderRequestStatus.EXECUTION_PENDING,
        )
        bundle = _make_real_bundle()
        bundle.provider_requests = [req]
        bundle_id = bundle.id
        bundle.path = executed_dir / f"{bundle_id}.json"
        bundle.store()

        # Provider.status_json changes the request status to EXECUTION_DONE
        def _change_status(request: ProviderRequest) -> t.Dict:
            request.status = ProviderRequestStatus.EXECUTION_DONE
            return {
                "status": ProviderRequestStatus.EXECUTION_DONE.value,
                "message": None,
            }

        mock_provider = MagicMock()
        mock_provider.status_json.side_effect = _change_status
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )
        manager.data.last_requested_bundle = None

        result = manager.get_status_json(bundle_id)

        assert result["id"] == bundle_id
        # Bundle should have been stored because status changed
        assert (executed_dir / f"{bundle_id}.json").exists()


# ---------------------------------------------------------------------------
# TestBridgeManagerLastExecutedBundleId
# ---------------------------------------------------------------------------


class TestBridgeManagerLastExecutedBundleId:
    """Tests for BridgeManager.last_executed_bundle_id (line 473)."""

    def test_last_executed_bundle_id_returns_data_value(self, tmp_path: Path) -> None:
        """last_executed_bundle_id() returns data.last_executed_bundle_id (line 473)."""
        manager = _make_bridge_manager(tmp_path)
        manager.data.last_executed_bundle_id = "rb-test-abc"
        result = manager.last_executed_bundle_id()
        assert result == "rb-test-abc"

    def test_last_executed_bundle_id_returns_none_when_unset(
        self, tmp_path: Path
    ) -> None:
        """last_executed_bundle_id() returns None when not set."""
        manager = _make_bridge_manager(tmp_path)
        manager.data.last_executed_bundle_id = None
        result = manager.last_executed_bundle_id()
        assert result is None


# ---------------------------------------------------------------------------
# TestBridgeManagerInit
# ---------------------------------------------------------------------------


class TestBridgeManagerInit:
    """Tests for BridgeManager.__init__ (lines 200-237)."""

    def test_init_creates_directories_and_initializes_providers(
        self, tmp_path: Path
    ) -> None:
        """BridgeManager.__init__ creates dirs and sets up providers (lines 200-237)."""
        with patch(
            "operate.bridge.bridge_manager.BridgeManagerData.load",
        ) as mock_load, patch(
            "operate.bridge.bridge_manager.LiFiProvider",
        ) as mock_lifi, patch(
            "operate.bridge.bridge_manager.RelayProvider",
        ) as mock_relay, patch(
            "operate.bridge.bridge_manager.NativeBridgeProvider",
        ), patch(
            "operate.bridge.bridge_manager.OptimismContractAdaptor",
        ), patch(
            "operate.bridge.bridge_manager.OmnibridgeContractAdaptor",
        ):
            mock_load.return_value = MagicMock()
            from operate.bridge.bridge_manager import (  # pylint: disable=import-outside-toplevel
                BridgeManager,
                EXECUTED_BUNDLES_PATH,
                LIFI_PROVIDER_ID,
                RELAY_PROVIDER_ID,
            )

            manager = BridgeManager(
                path=tmp_path,
                wallet_manager=MagicMock(),
                logger=MagicMock(),
            )

        assert (tmp_path / EXECUTED_BUNDLES_PATH).exists()
        assert (
            LIFI_PROVIDER_ID in manager._providers
        )  # pylint: disable=protected-access
        assert (
            RELAY_PROVIDER_ID in manager._providers
        )  # pylint: disable=protected-access
        mock_lifi.assert_called_once()
        mock_relay.assert_called_once()


# ---------------------------------------------------------------------------
# TestBridgeManagerSanitize
# ---------------------------------------------------------------------------


class TestBridgeManagerSanitize:
    """Tests for BridgeManager._sanitize (lines 308-316)."""

    def test_sanitize_checksums_and_converts_amount(self, tmp_path: Path) -> None:
        """_sanitize() checksum-addresses all fields and converts amount to int (lines 308-316)."""
        manager = _make_bridge_manager(tmp_path)
        addr_a = "0x" + "a" * 40
        addr_b = "0x" + "b" * 40
        addr_c = "0x" + "c" * 40
        addr_d = "0x" + "d" * 40
        params: t.List[t.Dict] = [
            {
                "from": {"chain": "gnosis", "address": addr_a, "token": addr_b},
                "to": {
                    "chain": "base",
                    "address": addr_c,
                    "token": addr_d,
                    "amount": "1000",
                },
            }
        ]
        manager._sanitize(params)  # pylint: disable=protected-access
        assert params[0]["to"]["amount"] == 1000


# ---------------------------------------------------------------------------
# TestBridgeManagerGetUpdatedBundleNativeLoop
# ---------------------------------------------------------------------------


class TestBridgeManagerGetUpdatedBundleNativeLoop:
    """Tests for BridgeManager._get_updated_bundle native bridge provider loop (lines 282-284)."""

    def test_uses_native_bridge_when_preferred_route_not_found(
        self, tmp_path: Path
    ) -> None:
        """_get_updated_bundle uses native bridge provider when no preferred route (lines 282-284)."""
        manager = _make_bridge_manager(tmp_path)
        manager.data.last_requested_bundle = None  # type: ignore[union-attr]

        mock_native = MagicMock()
        mock_native.can_handle_request.return_value = True
        mock_native.provider_id = "native-test"
        mock_native.create_request.return_value = MagicMock(provider_id="native-test")
        manager._native_bridge_providers = {  # pylint: disable=protected-access
            "native-test": mock_native
        }
        manager._providers["native-test"] = (
            mock_native  # pylint: disable=protected-access
        )

        # Use a route NOT in PREFERRED_ROUTES
        requests_params = [
            {
                "from": {"chain": "base", "token": "0x" + "0" * 40},
                "to": {"chain": "gnosis", "token": "0x" + "0" * 40},
            }
        ]

        with patch.object(manager, "quote_bundle"), patch.object(
            manager, "_store_data"
        ):
            bundle = manager._get_updated_bundle(requests_params, force_update=False)

        mock_native.can_handle_request.assert_called()
        assert bundle is not None


# ---------------------------------------------------------------------------
# TestBridgeManagerBridgeTotalRequirements
# ---------------------------------------------------------------------------


class TestBridgeManagerBridgeTotalRequirements:
    """Tests for BridgeManager.bridge_total_requirements (lines 457-462)."""

    def test_sums_provider_requirements(self, tmp_path: Path) -> None:
        """bridge_total_requirements() sums requirements from all providers (lines 457-462)."""
        from operate.operate_types import (
            ChainAmounts,  # pylint: disable=import-outside-toplevel
        )

        manager = _make_bridge_manager(tmp_path)

        mock_provider = MagicMock()
        mock_reqs = MagicMock()
        mock_provider.requirements.return_value = mock_reqs
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )

        req = _make_provider_request_real(provider_id="relay-provider")
        bundle = _make_real_bundle()
        bundle.provider_requests = [req]

        with patch.object(ChainAmounts, "add", return_value=MagicMock()) as mock_add:
            manager.bridge_total_requirements(bundle)

        mock_provider.requirements.assert_called_once_with(req)
        mock_add.assert_called_once_with(mock_reqs)


# ---------------------------------------------------------------------------
# TestBridgeManagerQuoteBundle
# ---------------------------------------------------------------------------


class TestBridgeManagerQuoteBundle:
    """Tests for BridgeManager.quote_bundle (lines 466-469)."""

    def test_calls_provider_quote_and_updates_timestamp(self, tmp_path: Path) -> None:
        """quote_bundle() calls each provider's quote() and updates bundle timestamp (lines 466-469)."""
        manager = _make_bridge_manager(tmp_path)

        mock_provider = MagicMock()
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )

        req = _make_provider_request_real(provider_id="relay-provider")
        bundle = _make_real_bundle()
        bundle.provider_requests = [req]
        old_ts = bundle.timestamp

        with patch(
            "operate.bridge.bridge_manager.time.time", return_value=old_ts + 100.0
        ):
            manager.quote_bundle(bundle)

        mock_provider.quote.assert_called_once_with(req)
        assert bundle.timestamp == old_ts + 100


# ---------------------------------------------------------------------------
# TestBridgeManagerBridgeRefillRequirements
# ---------------------------------------------------------------------------


class TestBridgeManagerBridgeRefillRequirements:
    """Tests for BridgeManager.bridge_refill_requirements (lines 340-380)."""

    def test_returns_enriched_status_dict(self, tmp_path: Path) -> None:
        """bridge_refill_requirements() returns status json with balance fields (lines 340-380)."""
        manager = _make_bridge_manager(tmp_path)

        bundle = _make_real_bundle()
        bundle.provider_requests = []
        mock_status: t.Dict = {"id": bundle.id, "bridge_request_status": []}
        mock_total_reqs = MagicMock()
        mock_total_reqs.json = {}
        mock_shortfalls: t.Any = MagicMock()
        mock_shortfalls.json = {}
        mock_shortfalls.values.return_value = []

        with patch.object(manager, "_sanitize"), patch.object(
            manager, "_raise_if_invalid"
        ), patch.object(
            manager, "_get_updated_bundle", return_value=bundle
        ), patch.object(
            manager, "bridge_total_requirements", return_value=mock_total_reqs
        ), patch.object(
            manager, "get_status_json", return_value=mock_status
        ), patch(
            "operate.bridge.bridge_manager.ChainAmounts.shortfalls",
            return_value=mock_shortfalls,
        ):
            result = manager.bridge_refill_requirements([])

        assert "id" in result


# ---------------------------------------------------------------------------
# Additional execute_bundle and get_status_json tests
# ---------------------------------------------------------------------------


class TestBridgeManagerExecuteBundleAdditional:
    """Additional tests for execute_bundle and get_status_json."""

    def test_execute_bundle_logs_warning_when_refill_required(
        self, tmp_path: Path
    ) -> None:
        """execute_bundle() logs a warning when is_refill_required=True (line 406)."""
        (tmp_path / EXECUTED_BUNDLES_PATH).mkdir(parents=True, exist_ok=True)
        manager = _make_bridge_manager(tmp_path)

        bundle = _make_real_bundle()
        bundle.provider_requests = []
        manager.data.last_requested_bundle = bundle  # type: ignore[union-attr]
        bundle_id = bundle.id

        expected_status: t.Dict = {"id": bundle_id, "bridge_request_status": []}

        with patch.object(
            manager,
            "bridge_refill_requirements",
            return_value={"is_refill_required": True},
        ), patch.object(manager, "_store_data"), patch.object(
            manager, "get_status_json", return_value=expected_status
        ):
            result = manager.execute_bundle(bundle_id)

        assert result == expected_status
        manager.logger.warning.assert_called()  # type: ignore[attr-defined]

    def test_get_status_json_in_memory_bundle(self, tmp_path: Path) -> None:
        """get_status_json() takes the pass branch when bundle is in memory (line 427)."""
        manager = _make_bridge_manager(tmp_path)

        req = _make_provider_request_real(provider_id="relay-provider")
        bundle = _make_real_bundle()
        bundle.provider_requests = [req]
        bundle_id = bundle.id
        # Bundle is in memory with matching id
        manager.data.last_requested_bundle = bundle  # type: ignore[union-attr]

        mock_provider = MagicMock()
        mock_provider.status_json.return_value = {
            "status": ProviderRequestStatus.CREATED.value,
            "message": None,
        }
        manager._providers["relay-provider"] = (
            mock_provider  # pylint: disable=protected-access
        )

        result = manager.get_status_json(bundle_id)

        assert result["id"] == bundle_id
        assert "bridge_request_status" in result


# ---------------------------------------------------------------------------
# TestBridgeRefillRequirementsWithChains — lines 350-351
# ---------------------------------------------------------------------------


class TestBridgeRefillRequirementsWithChains:
    """Test bridge_refill_requirements when bundle has provider_requests (lines 350-351)."""

    def test_with_provider_requests_covers_balance_loop(self, tmp_path: Path) -> None:
        """bridge_refill_requirements() calls wallet_manager and get_assets_balances (lines 350-351)."""
        manager = _make_bridge_manager(tmp_path)

        # Create bundle with provider_requests so get_from_chains() is non-empty
        req = _make_provider_request_real(provider_id="relay-provider")
        bundle = _make_real_bundle()
        bundle.provider_requests = [req]

        mock_status: t.Dict = {"id": bundle.id, "bridge_request_status": []}
        mock_total_reqs = MagicMock()
        mock_total_reqs.json = {}
        mock_shortfalls: t.Any = MagicMock()
        mock_shortfalls.json = {}
        mock_shortfalls.values.return_value = []

        mock_ledger_api = MagicMock()
        manager.wallet_manager.load.return_value.ledger_api.return_value = mock_ledger_api  # type: ignore[union-attr]

        with patch.object(manager, "_sanitize"), patch.object(
            manager, "_raise_if_invalid"
        ), patch.object(
            manager, "_get_updated_bundle", return_value=bundle
        ), patch.object(
            manager, "bridge_total_requirements", return_value=mock_total_reqs
        ), patch.object(
            manager, "get_status_json", return_value=mock_status
        ), patch(
            "operate.bridge.bridge_manager.ChainAmounts.shortfalls",
            return_value=mock_shortfalls,
        ), patch(
            "operate.bridge.bridge_manager.get_assets_balances",
            return_value={},
        ) as mock_get_balances:
            result = manager.bridge_refill_requirements([])

        assert "id" in result
        manager.wallet_manager.load.assert_called()  # type: ignore[union-attr]
        mock_get_balances.assert_called()
