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

"""Unit tests for operate/services/fund_recovery_manager.py – no blockchain required."""

import tempfile
import time
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.constants import ZERO_ADDRESS
from operate.operate_types import (
    FundRecoveryExecuteResponse,
    FundRecoveryScanResponse,
    GasWarningEntry,
    LedgerType,
    OnChainState,
)
from operate.services.fund_recovery_manager import (
    FundRecoveryManager,
    RECOVERY_CHAINS,
    _check_gas_warning,
    _enumerate_owned_services,
    _get_service_registry_contract,
    _get_service_state,
    _mnemonic_to_address,
    _mnemonic_to_private_key,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# BIP-39 test mnemonic (well-known all-zeros derivation – never use for real funds)
_TEST_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
# Checksummed address derived from the above mnemonic (m/44'/60'/0'/0/0)
_TEST_EOA_ADDRESS = "0x9858EfFD232B4033E47d90003D41EC34EcaedA94"

_SAFE_ADDR = "0x" + "b" * 40
_DEST_ADDR = "0x" + "d" * 40
_TOKEN_ADDR = "0x" + "e" * 40
_SERVICE_REGISTRY = "0x" + "f" * 40
_SERVICE_MANAGER = "0x" + "1" * 40
_RECOVERY_MODULE = "0x" + "2" * 40


# ---------------------------------------------------------------------------
# Helper: build a FundRecoveryManager with real logger
# ---------------------------------------------------------------------------


def _make_manager() -> FundRecoveryManager:
    """Return a FundRecoveryManager instance."""
    return FundRecoveryManager()


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


class TestMnemonicToAddress:
    """Tests for _mnemonic_to_address."""

    def test_returns_valid_evm_address(self) -> None:
        """Derived address has the expected format."""
        addr = _mnemonic_to_address(_TEST_MNEMONIC)
        assert addr.startswith("0x")
        assert len(addr) == 42

    def test_deterministic(self) -> None:
        """Calling twice with the same mnemonic always returns the same address."""
        assert _mnemonic_to_address(_TEST_MNEMONIC) == _mnemonic_to_address(
            _TEST_MNEMONIC
        )

    def test_known_mnemonic_derives_known_address(self) -> None:
        """The well-known 'abandon … about' mnemonic derives a known address."""
        addr = _mnemonic_to_address(_TEST_MNEMONIC)
        assert addr.lower() == _TEST_EOA_ADDRESS.lower()


class TestMnemonicToPrivateKey:
    """Tests for _mnemonic_to_private_key."""

    def test_returns_hex_string(self) -> None:
        """Private key is a 64-char hex string (no 0x prefix)."""
        pk = _mnemonic_to_private_key(_TEST_MNEMONIC)
        # The _private_key.hex() call returns a 64-char hex string without 0x
        assert len(pk) == 64
        int(pk, 16)  # must be valid hex

    def test_deterministic(self) -> None:
        """Calling twice yields the same key."""
        assert _mnemonic_to_private_key(_TEST_MNEMONIC) == _mnemonic_to_private_key(
            _TEST_MNEMONIC
        )


class TestGetServiceRegistryContract:
    """Tests for _get_service_registry_contract."""

    def test_calls_registry_contracts(self) -> None:
        """Delegates to registry_contracts.service_registry.get_instance."""
        mock_ledger = MagicMock()
        with patch(
            "operate.services.fund_recovery_manager.registry_contracts"
        ) as mock_reg:
            mock_reg.service_registry.get_instance.return_value = MagicMock()
            result = _get_service_registry_contract(mock_ledger, _SERVICE_REGISTRY)
        mock_reg.service_registry.get_instance.assert_called_once_with(
            ledger_api=mock_ledger,
            contract_address=_SERVICE_REGISTRY,
        )
        assert result is mock_reg.service_registry.get_instance.return_value


class TestGetServiceState:
    """Tests for _get_service_state."""

    def test_returns_deployed_state(self) -> None:
        """Parses state integer at index 6 of getService return value."""
        mock_ledger = MagicMock()
        contract_mock = MagicMock()
        contract_mock.functions.getService.return_value.call.return_value = [
            0,
            0,
            0,
            0,
            0,
            0,
            int(OnChainState.DEPLOYED),
        ]
        with patch(
            "operate.services.fund_recovery_manager._get_service_registry_contract",
            return_value=contract_mock,
        ):
            state = _get_service_state(mock_ledger, _SERVICE_REGISTRY, 42)
        assert state == OnChainState.DEPLOYED

    def test_returns_non_existent_when_getservice_raises(self) -> None:
        """Returns NON_EXISTENT when the getService() call raises."""
        mock_ledger = MagicMock()
        contract_mock = MagicMock()
        contract_mock.functions.getService.return_value.call.side_effect = RuntimeError(
            "call error"
        )
        with patch(
            "operate.services.fund_recovery_manager._get_service_registry_contract",
            return_value=contract_mock,
        ):
            state = _get_service_state(mock_ledger, _SERVICE_REGISTRY, 42)
        assert state == OnChainState.NON_EXISTENT


class TestCheckGasWarning:
    """Tests for _check_gas_warning."""

    def test_no_warning_when_balance_sufficient(self) -> None:
        """Returns insufficient=False when balance exceeds threshold."""
        mock_ledger = MagicMock()
        # Use a chain ID that has a threshold; inject a large balance.
        from operate.services.fund_recovery_manager import GAS_WARN_THRESHOLDS

        if not GAS_WARN_THRESHOLDS:
            pytest.skip("No chains with gas thresholds configured")
        chain_id = next(iter(GAS_WARN_THRESHOLDS))
        threshold = GAS_WARN_THRESHOLDS[chain_id]
        mock_ledger.api.eth.get_balance.return_value = threshold * 10

        result = _check_gas_warning(chain_id, _TEST_EOA_ADDRESS, mock_ledger)
        assert result.insufficient is False

    def test_warning_when_balance_below_threshold(self) -> None:
        """Returns insufficient=True when balance is below threshold."""
        mock_ledger = MagicMock()
        from operate.services.fund_recovery_manager import GAS_WARN_THRESHOLDS

        if not GAS_WARN_THRESHOLDS:
            pytest.skip("No chains with gas thresholds configured")
        chain_id = next(iter(GAS_WARN_THRESHOLDS))
        threshold = GAS_WARN_THRESHOLDS[chain_id]
        mock_ledger.api.eth.get_balance.return_value = max(0, threshold - 1)

        result = _check_gas_warning(chain_id, _TEST_EOA_ADDRESS, mock_ledger)
        assert result.insufficient is True

    def test_warning_on_exception(self) -> None:
        """Returns insufficient=True when the RPC call raises."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.get_balance.side_effect = Exception("rpc down")
        result = _check_gas_warning(100, _TEST_EOA_ADDRESS, mock_ledger)
        assert result.insufficient is True

    def test_unknown_chain_uses_zero_threshold(self) -> None:
        """An unknown chain_id uses a threshold of 0, so balance≥0 is sufficient."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.get_balance.return_value = 0
        result = _check_gas_warning(999999, _TEST_EOA_ADDRESS, mock_ledger)
        # balance (0) >= threshold (0), so NOT insufficient
        assert result.insufficient is False


class TestEnumerateOwnedServices:
    """Tests for _enumerate_owned_services."""

    def _make_log(self, token_id: int) -> dict:
        """Build a minimal fake Transfer log."""
        return {
            "topics": [
                b"\x00" * 32,  # topic0 (Transfer sig)
                b"\x00" * 32,  # topic1 (from)
                b"\x00" * 32,  # topic2 (to)
                token_id.to_bytes(32, "big"),  # topic3 (tokenId)
            ]
        }

    def test_returns_owned_service_ids(self) -> None:
        """Returns IDs where ownerOf matches the given owner."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.block_number = 100
        mock_ledger.api.eth.get_transaction_count.return_value = 0
        mock_ledger.api.eth.call.return_value = b""
        mock_ledger.api.eth.get_code.return_value = b""
        mock_ledger.api.eth.get_logs.return_value = [self._make_log(7)]
        contract_mock = MagicMock()
        contract_mock.functions.ownerOf.return_value.call.return_value = (
            _TEST_EOA_ADDRESS
        )

        with patch(
            "operate.services.fund_recovery_manager._get_service_registry_contract",
            return_value=contract_mock,
        ):
            result = _enumerate_owned_services(
                mock_ledger, _SERVICE_REGISTRY, _TEST_EOA_ADDRESS
            )
        assert 7 in result

    def test_filters_out_transferred_away_service(self) -> None:
        """Skips IDs where ownerOf returns a different address."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.block_number = 100
        mock_ledger.api.eth.get_transaction_count.return_value = 0
        mock_ledger.api.eth.call.return_value = b""
        mock_ledger.api.eth.get_code.return_value = b""
        mock_ledger.api.eth.get_logs.return_value = [self._make_log(5)]
        contract_mock = MagicMock()
        # ownerOf returns a *different* address
        contract_mock.functions.ownerOf.return_value.call.return_value = "0x" + "9" * 40

        with patch(
            "operate.services.fund_recovery_manager._get_service_registry_contract",
            return_value=contract_mock,
        ):
            result = _enumerate_owned_services(
                mock_ledger, _SERVICE_REGISTRY, _TEST_EOA_ADDRESS
            )
        assert 5 not in result

    def test_returns_empty_on_outer_exception(self) -> None:
        """Returns empty list when an outer exception is raised inside the try block."""
        mock_ledger = MagicMock()
        # Raising in block_number causes the outer try to catch it → returns []
        mock_ledger.api.eth.block_number = property(  # type: ignore[assignment]
            MagicMock(side_effect=Exception("block_number error"))
        )
        contract_mock = MagicMock()

        with patch(
            "operate.services.fund_recovery_manager._get_service_registry_contract",
            return_value=contract_mock,
        ):
            # block_number access raises inside the outer try block
            mock_ledger.api.eth.block_number = MagicMock(
                side_effect=Exception("block_number error")
            )
            # Access block_number as attribute (not call) — use __get__
            type(mock_ledger.api.eth).block_number = property(
                fget=MagicMock(side_effect=Exception("block_number error"))
            )
            result = _enumerate_owned_services(
                mock_ledger, _SERVICE_REGISTRY, _TEST_EOA_ADDRESS
            )
        assert result == []

    def test_skips_ownerof_exception(self) -> None:
        """Silently skips a token when ownerOf raises."""
        mock_ledger = MagicMock()
        mock_ledger.api.eth.block_number = 100
        mock_ledger.api.eth.get_transaction_count.return_value = 0
        mock_ledger.api.eth.call.return_value = b""
        mock_ledger.api.eth.get_code.return_value = b""
        mock_ledger.api.eth.get_logs.return_value = [self._make_log(3)]
        contract_mock = MagicMock()
        contract_mock.functions.ownerOf.return_value.call.side_effect = Exception(
            "call failed"
        )

        with patch(
            "operate.services.fund_recovery_manager._get_service_registry_contract",
            return_value=contract_mock,
        ):
            result = _enumerate_owned_services(
                mock_ledger, _SERVICE_REGISTRY, _TEST_EOA_ADDRESS
            )
        assert result == []

    def test_log_chunk_failure_is_swallowed(self) -> None:
        """A failed log chunk is swallowed; remaining chunks still processed."""
        mock_ledger = MagicMock()
        # block_number > chunk to force multiple iterations
        mock_ledger.api.eth.block_number = 15_000
        mock_ledger.api.eth.get_transaction_count.return_value = 0
        mock_ledger.api.eth.call.return_value = b""
        mock_ledger.api.eth.get_code.return_value = b""
        call_count = 0

        def _side_effect(*_a, **_kw):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("first chunk fails")
            return []

        mock_ledger.api.eth.get_logs.side_effect = _side_effect
        contract_mock = MagicMock()

        with patch(
            "operate.services.fund_recovery_manager._get_service_registry_contract",
            return_value=contract_mock,
        ):
            result = _enumerate_owned_services(
                mock_ledger, _SERVICE_REGISTRY, _TEST_EOA_ADDRESS
            )
        assert result == []


# ---------------------------------------------------------------------------
# FundRecoveryManager.scan
# ---------------------------------------------------------------------------

_MODULE = "operate.services.fund_recovery_manager"


class TestFundRecoveryManagerScan:
    """Tests for FundRecoveryManager.scan."""

    def test_scan_returns_correct_type(self) -> None:
        """scan() always returns FundRecoveryScanResponse."""
        manager = _make_manager()
        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)
        assert isinstance(result, FundRecoveryScanResponse)

    def test_scan_derives_eoa_address_from_mnemonic(self) -> None:
        """The master_eoa_address in the response matches the derived address."""
        manager = _make_manager()
        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)
        assert result.master_eoa_address.lower() == _TEST_EOA_ADDRESS.lower()

    def test_scan_records_eoa_native_balance(self) -> None:
        """Non-zero EOA native balance is recorded in the response."""
        manager = _make_manager()
        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(
                f"{_MODULE}.get_asset_balance",
                side_effect=lambda *, ledger_api, asset_address, address, **kw: (
                    1000 if asset_address == ZERO_ADDRESS else 0
                ),
            ),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # At least one chain should have recorded the EOA balance
        found = False
        for _chain_id_str, addresses in result.balances.items():
            if result.master_eoa_address in addresses:
                bal = addresses[result.master_eoa_address].get(ZERO_ADDRESS)
                if bal is not None and int(bal) == 1000:
                    found = True
                    break
        assert found, f"EOA native balance not recorded; balances={result.balances}"

    def test_scan_records_erc20_balance_when_nonzero(self) -> None:
        """Non-zero ERC-20 balances for EOA are included."""
        manager = _make_manager()

        def _bal(*, ledger_api, asset_address, address, **kw):  # type: ignore[no-untyped-def]
            if asset_address == ZERO_ADDRESS:
                return 0
            return 500

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", side_effect=_bal),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(
                f"{_MODULE}.ERC20_TOKENS_BY_CHAIN_ID",
                {chain.id: [_TOKEN_ADDR] for chain in RECOVERY_CHAINS},
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        token_found = False
        for _chain_id_str, addresses in result.balances.items():
            if result.master_eoa_address in addresses:
                if _TOKEN_ADDR in addresses[result.master_eoa_address]:
                    token_found = True
                    break
        assert token_found

    def test_scan_zero_erc20_balance_not_recorded(self) -> None:
        """ERC-20 balances of 0 are NOT included in the response."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(
                f"{_MODULE}.ERC20_TOKENS_BY_CHAIN_ID",
                {chain.id: [_TOKEN_ADDR] for chain in RECOVERY_CHAINS},
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        for _chain_id_str, addresses in result.balances.items():
            for addr_balances in addresses.values():
                assert _TOKEN_ADDR not in addr_balances

    def test_scan_records_safe_balances(self) -> None:
        """Safe addresses returned by fetch_safes_for_owner are scanned."""
        manager = _make_manager()
        safe = _SAFE_ADDR

        def _bal(*, ledger_api, asset_address, address, **kw):  # type: ignore[no-untyped-def]
            if address == safe and asset_address == ZERO_ADDRESS:
                return 9999
            return 0

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", side_effect=_bal),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[safe]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        safe_found = False
        for _chain_id_str, addresses in result.balances.items():
            if safe in addresses:
                if int(addresses[safe].get(ZERO_ADDRESS, 0)) == 9999:
                    safe_found = True
                    break
        assert safe_found

    def test_scan_enumerates_services_for_safe_owners(self) -> None:
        """Services owned by safes are returned in the services list."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[42]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        service_ids = [s.service_id for s in result.services]
        assert 42 in service_ids

    def test_scan_deduplicates_service_ids_across_safes(self) -> None:
        """Same service_id seen from two safes is only reported once."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}.fetch_safes_for_owner",
                return_value=[_SAFE_ADDR, "0x" + "3" * 40],
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[7]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Only one chain is checked at a time; per-chain deduplication
        ids_per_chain: t.Dict[int, t.List[int]] = {}
        for svc in result.services:
            ids_per_chain.setdefault(svc.chain_id, []).append(svc.service_id)
        for chain_id, ids in ids_per_chain.items():
            assert ids.count(7) == 1, f"Duplicate service 7 on chain {chain_id}"

    def test_scan_marks_deployed_service_as_can_unstake(self) -> None:
        """Services in DEPLOYED state have can_unstake=True."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[1]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        deployed_services = [s for s in result.services if s.service_id == 1]
        assert deployed_services, "Service 1 not found in results"
        assert deployed_services[0].can_unstake is True

    def test_scan_marks_terminated_bonded_service_as_can_unstake(self) -> None:
        """Services in TERMINATED_BONDED have can_unstake=True."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[2]),
            patch(
                f"{_MODULE}._get_service_state",
                return_value=OnChainState.TERMINATED_BONDED,
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        tb_services = [s for s in result.services if s.service_id == 2]
        assert tb_services
        assert tb_services[0].can_unstake is True

    def test_scan_marks_pre_registration_service_as_cannot_unstake(self) -> None:
        """Services in PRE_REGISTRATION have can_unstake=False."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[3]),
            patch(
                f"{_MODULE}._get_service_state",
                return_value=OnChainState.PRE_REGISTRATION,
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        pr_services = [s for s in result.services if s.service_id == 3]
        assert pr_services
        assert pr_services[0].can_unstake is False

    def test_scan_includes_gas_warning_per_chain(self) -> None:
        """gas_warning dict is keyed by chain_id string for every RECOVERY_CHAIN."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=True),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        for chain in RECOVERY_CHAINS:
            assert str(chain.id) in result.gas_warning
            assert result.gas_warning[str(chain.id)].insufficient is True

    def test_scan_chain_failure_sets_gas_warning_insufficient(self) -> None:
        """If get_default_ledger_api raises for a chain, gas warning is True."""
        manager = _make_manager()

        with patch(
            f"{_MODULE}.get_default_ledger_api", side_effect=Exception("rpc error")
        ):
            result = manager.scan(_TEST_MNEMONIC)

        for chain in RECOVERY_CHAINS:
            assert str(chain.id) in result.gas_warning
            assert result.gas_warning[str(chain.id)].insufficient is True

    def test_scan_no_services_when_no_service_registry(self) -> None:
        """When CONTRACTS has no service_registry for a chain, no services returned."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(f"{_MODULE}.CONTRACTS", {}),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        assert result.services == []

    def test_scan_service_enumeration_exception_swallowed(self) -> None:
        """Exceptions in the service-enumeration block don't crash scan()."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=RuntimeError("subgraph boom"),
            ),
            patch(
                f"{_MODULE}._enumerate_owned_services",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        assert isinstance(result, FundRecoveryScanResponse)


# ---------------------------------------------------------------------------
# FundRecoveryManager.execute
# ---------------------------------------------------------------------------


class TestFundRecoveryManagerExecute:
    """Tests for FundRecoveryManager.execute."""

    # ------------------------------------------------------------------
    # Basic happy-path
    # ------------------------------------------------------------------

    def test_execute_returns_correct_type(self) -> None:
        """execute() always returns FundRecoveryExecuteResponse."""
        manager = _make_manager()
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (MagicMock(), [])
        mock_app.service_manager.return_value = MagicMock()
        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                return_value=[],
            ),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)
        assert isinstance(result, FundRecoveryExecuteResponse)

    def test_execute_success_no_errors(self) -> None:
        """Happy path with no services and no funds produces success=True, errors=[]."""
        manager = _make_manager()
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (MagicMock(), [])
        mock_app.service_manager.return_value = MagicMock()
        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                return_value=[],
            ),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert result.success is True
        assert result.errors == []
        assert result.partial_failure is False

    def test_execute_records_moved_funds_from_eoa(self) -> None:
        """Funds moved from EOA drain are recorded in total_funds_moved."""
        manager = _make_manager()
        eoa = _mnemonic_to_address(_TEST_MNEMONIC)

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []

        def _drain(withdrawal_address, chain, from_safe):  # type: ignore[no-untyped-def]
            if not from_safe:
                return {ZERO_ADDRESS: 5000}
            return {}

        mock_wallet.drain.side_effect = _drain
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = MagicMock()

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
            patch(f"{_MODULE}._unstake_service"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        # At least one chain should have EOA funds moved
        found = False
        for _chain_id_str, addresses in result.total_funds_moved.items():
            if eoa in addresses and ZERO_ADDRESS in addresses[eoa]:
                found = True
        assert found

    def test_execute_records_moved_funds_from_safe(self) -> None:
        """Funds moved from Safe drain are recorded in total_funds_moved."""
        manager = _make_manager()

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []

        def _drain(withdrawal_address, chain, from_safe):  # type: ignore[no-untyped-def]
            if from_safe:
                return {ZERO_ADDRESS: 8000}
            return {}

        mock_wallet.drain.side_effect = _drain
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = MagicMock()

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
            patch(f"{_MODULE}._unstake_service"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        found = False
        for _chain_id_str, addresses in result.total_funds_moved.items():
            if _SAFE_ADDR in addresses and ZERO_ADDRESS in addresses[_SAFE_ADDR]:
                found = True
        assert found

    def test_execute_records_moved_funds_from_both_safe_and_eoa(self) -> None:
        """Funds moved from both Safe and EOA drain are recorded in total_funds_moved."""
        manager = _make_manager()
        eoa = _mnemonic_to_address(_TEST_MNEMONIC)

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []

        def _drain(withdrawal_address, chain, from_safe):  # type: ignore[no-untyped-def]
            if from_safe:
                return {ZERO_ADDRESS: 8000}
            return {ZERO_ADDRESS: 5000}

        mock_wallet.drain.side_effect = _drain
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = MagicMock()

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
            patch(f"{_MODULE}._unstake_service"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        eoa_found = False
        safe_found = False
        for _chain_id_str, addresses in result.total_funds_moved.items():
            if eoa in addresses and ZERO_ADDRESS in addresses[eoa]:
                eoa_found = True
            if _SAFE_ADDR in addresses and ZERO_ADDRESS in addresses[_SAFE_ADDR]:
                safe_found = True

        assert eoa_found, "EOA funds were not recorded"
        assert safe_found, "Safe funds were not recorded"

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    def test_execute_chain_error_recorded(self) -> None:
        """A chain-level exception is recorded in errors."""
        manager = _make_manager()
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (MagicMock(), [])
        mock_app.service_manager.return_value = MagicMock()
        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(
                f"{_MODULE}.get_default_ledger_api",
                side_effect=Exception("rpc down"),
            ),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert not result.success
        assert len(result.errors) > 0

    def test_execute_drain_eoa_error_recorded(self) -> None:
        """An exception from EOA drain is recorded in errors."""
        manager = _make_manager()

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []

        def _drain(withdrawal_address, chain, from_safe):  # type: ignore[no-untyped-def]
            if not from_safe:
                raise RuntimeError("drain fail")
            return {}

        mock_wallet.drain.side_effect = _drain
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = MagicMock()

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[]),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
            patch(f"{_MODULE}._unstake_service"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert not result.success
        assert any("drain_eoa" in e for e in result.errors)

    def test_execute_drain_safe_error_recorded(self) -> None:
        """An exception from Safe drain is recorded in errors."""
        manager = _make_manager()

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []

        def _drain(withdrawal_address, chain, from_safe):  # type: ignore[no-untyped-def]
            if from_safe:
                raise RuntimeError("safe drain fail")
            return {}

        mock_wallet.drain.side_effect = _drain
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = MagicMock()

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
            patch(f"{_MODULE}._unstake_service"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert not result.success
        assert any("drain_safe" in e for e in result.errors)

    def test_execute_service_recovery_error_recorded(self) -> None:
        """A service recovery failure is recorded in errors."""
        manager = _make_manager()

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []
        mock_wallet.drain.return_value = {}

        mock_svc_manager = MagicMock()
        mock_svc_manager.terminate_service_on_chain_from_safe.side_effect = (
            RuntimeError("svc fail")
        )

        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = mock_svc_manager

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(
                f"{_MODULE}.fetch_safes_for_owner",
                return_value=[_SAFE_ADDR],
            ),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[42]),
            patch(
                f"{_MODULE}._get_service_state",
                return_value=OnChainState.DEPLOYED,
            ),
            patch(f"{_MODULE}._unstake_service"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        # The terminate failure should bubble up and be caught at the per-service level
        # The service-level errors use format "chain=X service=Y: ExcType"
        assert any("service=42" in e for e in result.errors)

    def test_execute_partial_failure_when_some_funds_moved(self) -> None:
        """partial_failure=True when errors exist and some funds were moved."""
        manager = _make_manager()

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []

        drain_call_count = {"n": 0}

        def _drain(withdrawal_address, chain, from_safe):  # type: ignore[no-untyped-def]
            drain_call_count["n"] += 1
            if from_safe:
                raise RuntimeError("safe drain fail")
            # EOA drain succeeds and returns funds
            return {ZERO_ADDRESS: 1}

        mock_wallet.drain.side_effect = _drain
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = MagicMock()

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[_SAFE_ADDR]),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
            patch(f"{_MODULE}._unstake_service"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert result.partial_failure is True

    def test_execute_deduplicates_service_ids_within_chain(self) -> None:
        """The same service_id seen from subgraph is only recovered once per chain."""
        manager = _make_manager()

        mock_wallet = MagicMock()
        mock_wallet.safes = {}
        mock_wallet.safe_chains = []
        mock_wallet.drain.return_value = {}

        mock_svc_manager = MagicMock()
        mock_app = MagicMock()
        mock_app.wallet_manager.import_from_mnemonic.return_value = (mock_wallet, [])
        mock_app._services = Path(tempfile.mkdtemp()) / "services"
        mock_app._services.mkdir(parents=True)
        mock_app.service_manager.return_value = mock_svc_manager

        with (
            patch(f"{_MODULE}.OperateApp", return_value=mock_app),
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(
                f"{_MODULE}.fetch_safes_for_owner",
                return_value=[_SAFE_ADDR, "0x" + "4" * 40],
            ),
            # Return same service ID twice (simulating two safes owning same service)
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[99, 99]),
            patch(
                f"{_MODULE}._get_service_state",
                return_value=OnChainState.NON_EXISTENT,
            ),
            patch(f"{_MODULE}._unstake_service"),
        ):
            manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        # service 99 must be recovered exactly once per chain (4 chains × 1)
        # _execute_recovery_module_flow_from_safe is called once per unique service per chain
        assert (
            mock_svc_manager._execute_recovery_module_flow_from_safe.call_count
            == len(RECOVERY_CHAINS)
        )

    def test_execute_fatal_exception_sets_errors(self) -> None:
        """A top-level exception (e.g. bad destination) is caught and set in errors."""
        manager = _make_manager()
        with patch(
            "operate.services.fund_recovery_manager.Web3.to_checksum_address",
            side_effect=ValueError("bad address"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert not result.success
        assert any("fatal" in e or "ValueError" in e for e in result.errors)


# ---------------------------------------------------------------------------
# FundRecoveryManager.scan – safe ERC-20 balance branch (line 329)
# ---------------------------------------------------------------------------


class TestScanSafeErc20Balance:
    """Extra coverage: safe ERC-20 balance > 0 recorded (line 329)."""

    def test_scan_records_safe_erc20_balance_when_nonzero(self) -> None:
        """Non-zero ERC-20 balance for a safe is included in scan results."""
        manager = _make_manager()
        safe = _SAFE_ADDR

        def _bal(  # type: ignore[no-untyped-def]
            *, ledger_api, asset_address, address, **kw
        ):
            # Only return a balance for the safe + token combination
            if address == safe and asset_address == _TOKEN_ADDR:
                return 777
            return 0

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", side_effect=_bal),
            patch(f"{_MODULE}.fetch_safes_for_owner", return_value=[safe]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[]),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(
                f"{_MODULE}.ERC20_TOKENS_BY_CHAIN_ID",
                {chain.id: [_TOKEN_ADDR] for chain in RECOVERY_CHAINS},
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        token_found = False
        for _chain_id_str, addresses in result.balances.items():
            if safe in addresses and _TOKEN_ADDR in addresses[safe]:
                if int(addresses[safe][_TOKEN_ADDR]) == 777:
                    token_found = True
                    break
        assert (
            token_found
        ), f"Safe ERC-20 balance not recorded; balances={result.balances}"


class TestGetSafeDeployAndLastTxBlock:
    """Test the _get_safe_deploy_and_last_tx_block function."""

    def test_finds_deploy_block_and_last_tx_block(self) -> None:
        """Test happy path finding deploy and last tx block."""
        from unittest.mock import MagicMock

        from operate.services.fund_recovery_manager import (
            _get_safe_deploy_and_last_tx_block,
        )

        w3 = MagicMock()
        w3.to_checksum_address.return_value = "0xSafe"

        def mock_get_code(addr: str, block_identifier: int) -> bytes:
            if block_identifier >= 5:
                return b"123"
            return b""

        def mock_call(params: dict, block_identifier: int) -> bytes:
            if block_identifier == 10:
                return (42).to_bytes(32, "big")
            if block_identifier >= 8:
                return (42).to_bytes(32, "big")
            return (40).to_bytes(32, "big")

        w3.eth.get_code.side_effect = mock_get_code
        w3.eth.call.side_effect = mock_call

        deploy_block, last_tx = _get_safe_deploy_and_last_tx_block(w3, "0xSafe", 10)
        assert deploy_block == 5
        assert last_tx == 8

    def test_handles_exceptions_gracefully(self) -> None:
        """Test outer exceptions are handled gracefully."""
        from unittest.mock import MagicMock

        from operate.services.fund_recovery_manager import (
            _get_safe_deploy_and_last_tx_block,
        )

        w3 = MagicMock()
        w3.to_checksum_address.return_value = "0xSafe"
        w3.eth.get_code.side_effect = Exception("get_code fail")
        w3.eth.call.side_effect = Exception("call fail")

        deploy_block, last_tx = _get_safe_deploy_and_last_tx_block(w3, "0xSafe", 10)
        assert deploy_block == 10
        assert last_tx == 10

    def test_inner_search_exception(self) -> None:
        """Test inner search loop exceptions are handled."""
        from unittest.mock import MagicMock

        from operate.services.fund_recovery_manager import (
            _get_safe_deploy_and_last_tx_block,
        )

        w3 = MagicMock()
        w3.to_checksum_address.return_value = "0xSafe"

        def mock_get_code(addr: str, block_identifier: int) -> bytes:
            if block_identifier >= 5:
                return b"123"
            return b""

        def mock_call(params: dict, block_identifier: int) -> bytes:
            if block_identifier == 10:
                return (42).to_bytes(32, "big")
            if block_identifier == 7:
                raise ValueError("Inner search fail")
            if block_identifier > 7:
                return (42).to_bytes(32, "big")
            return (40).to_bytes(32, "big")

        w3.eth.get_code.side_effect = mock_get_code
        w3.eth.call.side_effect = mock_call

        deploy_block, last_tx = _get_safe_deploy_and_last_tx_block(w3, "0xSafe", 10)
        assert deploy_block == 5
        assert last_tx == 8


class TestFetchLogsInChunks:
    """Test the _fetch_logs_in_chunks function."""

    def test_chunk_size_reduces_and_warns_on_min_size(self) -> None:
        """Test chunk size reduces and warns on min size."""
        from unittest.mock import MagicMock

        from operate.services.fund_recovery_manager import _fetch_logs_in_chunks

        w3 = MagicMock()
        w3.to_checksum_address.return_value = "0xRegistry"

        def mock_get_logs(params: dict) -> list:
            # Fail every time
            raise Exception("Log failure")

        w3.eth.get_logs.side_effect = mock_get_logs

        # Will fail down to chunk_size=1, then warn and skip
        token_ids = _fetch_logs_in_chunks(w3, "0xRegistry", 0, 2, [None])
        assert token_ids == set()


class TestFetchServicesFromSubgraph:
    """Tests for _fetch_services_from_subgraph."""

    @patch("operate.services.fund_recovery_manager.requests.post")
    def test_returns_errors(self, mock_post: MagicMock) -> None:
        """Raises ValueError if 'errors' in response."""
        from operate.services.fund_recovery_manager import _fetch_services_from_subgraph

        mock_response = MagicMock()
        mock_response.json.return_value = {"errors": [{"message": "bad query"}]}
        mock_post.return_value = mock_response

        with pytest.raises(ValueError, match="GraphQL query returned errors"):
            _fetch_services_from_subgraph("http://url", "0xabc")

    @patch("operate.services.fund_recovery_manager.requests.post")
    def test_missing_data_field(self, mock_post: MagicMock) -> None:
        """Raises ValueError if 'data' is missing."""
        from operate.services.fund_recovery_manager import _fetch_services_from_subgraph

        mock_response = MagicMock()
        mock_response.json.return_value = {"not_data": []}
        mock_post.return_value = mock_response

        with pytest.raises(ValueError, match="No 'data' field in subgraph response"):
            _fetch_services_from_subgraph("http://url", "0xabc")

    @patch("operate.services.fund_recovery_manager.requests.post")
    def test_catch_all_exception(self, mock_post: MagicMock) -> None:
        """Exceptions are caught and re-raised."""
        from operate.services.fund_recovery_manager import _fetch_services_from_subgraph

        mock_post.side_effect = Exception("network failure")

        with pytest.raises(Exception, match="network failure"):
            _fetch_services_from_subgraph("http://url", "0xabc")

    @patch("operate.services.fund_recovery_manager.requests.post")
    def test_success(self, mock_post: MagicMock) -> None:
        """Returns service IDs."""
        from operate.services.fund_recovery_manager import _fetch_services_from_subgraph

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"services": [{"id": "1"}, {"id": "2"}]}
        }
        mock_post.return_value = mock_response

        result = _fetch_services_from_subgraph("http://url", "0xabc")
        assert result == [1, 2]


def test_build_synthetic_service_creates_minimal_service(tmp_path):
    """_build_synthetic_service creates a Service with correct chain_config."""
    from operate.operate_types import Chain
    from operate.services.fund_recovery_manager import _build_synthetic_service
    from operate.services.service import SERVICE_CONFIG_PREFIX

    svc_dir = tmp_path / "services"
    svc_dir.mkdir()

    service = _build_synthetic_service(
        storage=svc_dir,
        chain=Chain.GNOSIS,
        service_id=42,
        rpc="https://rpc.gnosis.example.com",
    )

    assert service.chain_configs[Chain.GNOSIS.value].chain_data.token == 42
    assert (
        service.chain_configs[Chain.GNOSIS.value].ledger_config.rpc
        == "https://rpc.gnosis.example.com"
    )
    assert service.chain_configs[Chain.GNOSIS.value].ledger_config.chain == Chain.GNOSIS
    assert service.home_chain == Chain.GNOSIS.value
    assert service.service_config_id.startswith(SERVICE_CONFIG_PREFIX)
    # Service JSON must be persisted so ServiceManager.load() can find it
    from operate.constants import CONFIG_JSON

    assert (svc_dir / service.service_config_id / CONFIG_JSON).exists()


def test_inject_safe_into_wallet(tmp_path):
    """_inject_safe_into_wallet sets wallet.safes[chain] and persists."""
    from unittest.mock import MagicMock

    from operate.operate_types import Chain
    from operate.services.fund_recovery_manager import _inject_safe_into_wallet

    mock_wallet = MagicMock()
    mock_wallet.safes = {}
    mock_wallet.safe_chains = []

    _inject_safe_into_wallet(
        wallet=mock_wallet,
        chain=Chain.GNOSIS,
        safe_address="0xDeadBeef00000000000000000000000000000001",
    )

    assert (
        mock_wallet.safes[Chain.GNOSIS] == "0xDeadBeef00000000000000000000000000000001"
    )
    mock_wallet.store.assert_called_once()


def test_inject_safe_into_wallet_idempotent(tmp_path):
    """_inject_safe_into_wallet does not duplicate chain in safe_chains."""
    from unittest.mock import MagicMock

    from operate.operate_types import Chain
    from operate.services.fund_recovery_manager import _inject_safe_into_wallet

    mock_wallet = MagicMock()
    mock_wallet.safes = {}
    mock_wallet.safe_chains = [Chain.GNOSIS]  # already present

    _inject_safe_into_wallet(
        wallet=mock_wallet,
        chain=Chain.GNOSIS,
        safe_address="0xDeadBeef00000000000000000000000000000001",
    )

    assert mock_wallet.safe_chains.count(Chain.GNOSIS) == 1
    mock_wallet.store.assert_called_once()


def test_execute_calls_service_manager_methods_for_deployed_service(tmp_path):
    """execute() calls terminate, unbond, recovery module, and drain for a DEPLOYED service."""
    mock_wallet = MagicMock()
    mock_wallet.drain.return_value = {}
    mock_wallet.safes = {}
    mock_wallet.safe_chains = []

    mock_wallet_manager = MagicMock()
    mock_wallet_manager.import_from_mnemonic.return_value = (mock_wallet, ["word1"])

    mock_svc_manager = MagicMock()

    mock_app = MagicMock()
    mock_app.wallet_manager = mock_wallet_manager
    mock_app._services = tmp_path / "services"
    mock_app._services.mkdir()
    mock_app.service_manager.return_value = mock_svc_manager

    with (
        patch(
            "operate.services.fund_recovery_manager.OperateApp",
            return_value=mock_app,
        ),
        patch(
            "operate.services.fund_recovery_manager.fetch_safes_for_owner",
            return_value=["0xSafe0000000000000000000000000000000000AA"],
        ),
        patch(
            "operate.services.fund_recovery_manager._fetch_services_from_subgraph",
            return_value=[7],
        ),
        patch(
            "operate.services.fund_recovery_manager._get_service_state",
            return_value=OnChainState.DEPLOYED,
        ),
        patch(
            "operate.services.fund_recovery_manager.get_default_ledger_api",
            return_value=MagicMock(),
        ),
        patch(
            "operate.services.fund_recovery_manager.get_default_rpc",
            return_value="https://rpc.test",
        ),
        patch(
            "operate.services.fund_recovery_manager._unstake_service",
            return_value=None,
        ),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(
            mnemonic="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
            destination_address="0x0000000000000000000000000000000000000001",
        )

    # terminate → unbond → recovery module → drain should all be called
    assert mock_svc_manager.terminate_service_on_chain_from_safe.call_count >= 1
    assert mock_svc_manager.unbond_service_on_chain.call_count >= 1
    assert mock_svc_manager._execute_recovery_module_flow_from_safe.call_count >= 1
    assert mock_svc_manager.drain.call_count >= 1
    # wallet.drain should be called for the safe and EOA on each chain
    assert mock_wallet.drain.call_count >= 1


def test_execute_creates_operate_app_and_imports_wallet(tmp_path):
    """execute() should instantiate OperateApp in a tempdir and import wallet."""
    mock_wallet = MagicMock()
    mock_wallet.drain.return_value = {}
    mock_wallet.safes = {}

    mock_wallet_manager = MagicMock()
    mock_wallet_manager.import_from_mnemonic.return_value = (mock_wallet, ["word1"])

    mock_app = MagicMock()
    mock_app.wallet_manager = mock_wallet_manager
    mock_app.service_manager.return_value = MagicMock()

    with (
        patch(
            "operate.services.fund_recovery_manager.OperateApp",
            return_value=mock_app,
        ) as mock_app_cls,
        patch(
            "operate.services.fund_recovery_manager.fetch_safes_for_owner",
            return_value=[],
        ),
        patch(
            "operate.services.fund_recovery_manager._fetch_services_from_subgraph",
            return_value=[],
        ),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(
            mnemonic="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
            destination_address="0x0000000000000000000000000000000000000001",
        )

    # OperateApp was constructed with a Path inside a temp dir
    assert mock_app_cls.call_count == 1
    constructed_path = mock_app_cls.call_args[1]["home"]
    assert isinstance(constructed_path, Path)

    # User account was created
    mock_app.create_user_account.assert_called_once()
    password_used = mock_app.create_user_account.call_args[1]["password"]
    assert len(password_used) >= 8

    # Wallet was imported with the mnemonic
    mock_wallet_manager.import_from_mnemonic.assert_called_once_with(
        LedgerType.ETHEREUM,
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
    )

    assert result.success is True
