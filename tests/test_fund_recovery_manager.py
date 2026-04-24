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
    _get_master_safes_from_contracts,
    _get_service_registry_contract,
    _get_service_state,
    _mnemonic_to_address,
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
# _get_master_safes_from_contracts
# ---------------------------------------------------------------------------


class TestGetMasterSafesFromContracts:
    """Tests for _get_master_safes_from_contracts."""

    # Constants shared across tests in this class
    _EOA = _TEST_EOA_ADDRESS
    _MASTER_SAFE = "0x" + "a" * 40
    _MASTER_SAFE2 = "0x" + "c" * 40
    _STAKING_CONTRACT = "0x" + "5" * 40
    _PROGRAM_ID = "pearl_beta"

    def _mock_staking_manager(
        self,
        program_id: t.Optional[str] = None,
        staking_contract: str = "",
        svc_info_safe: str = "",
    ) -> MagicMock:
        """Return a StakingManager mock with sensible defaults."""
        m = MagicMock()
        m.get_current_staking_program.return_value = program_id
        m.get_staking_contract.return_value = staking_contract or self._STAKING_CONTRACT
        # service_info returns (multisig, owner, nonces, tsStart, reward, inactivity)
        m.service_info.return_value = (
            "0x" + "0" * 40,
            svc_info_safe or self._MASTER_SAFE,
            [],
            0,
            0,
            0,
        )
        return m

    def _call(
        self,
        *,
        ledger_api: t.Any = None,
        eoa_address: str = "",
        service_registry_address: str = _SERVICE_REGISTRY,
        subgraph_url: t.Optional[str] = None,
    ) -> t.List[str]:
        """Thin wrapper that calls _get_master_safes_from_contracts with test defaults."""
        from operate.operate_types import Chain

        return _get_master_safes_from_contracts(
            chain=Chain.GNOSIS,
            ledger_api=ledger_api or MagicMock(),
            service_registry_address=service_registry_address,
            eoa_address=eoa_address or self._EOA,
            subgraph_url=subgraph_url,
        )

    # ------------------------------------------------------------------
    # Service ID discovery
    # ------------------------------------------------------------------

    def test_subgraph_url_none_skips_subgraph(self) -> None:
        """When subgraph_url is None, _fetch_services_from_subgraph is never called."""
        with (
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=AssertionError("should not be called"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[]),
            patch(f"{_MODULE}.StakingManager", return_value=MagicMock()),
            patch(f"{_MODULE}.get_default_rpc"),
        ):
            result = self._call(subgraph_url=None)
        assert result == []

    def test_subgraph_fails_falls_back_to_rpc(self) -> None:
        """When subgraph raises, _enumerate_owned_services is used as fallback."""
        mock_sm = self._mock_staking_manager(
            program_id=None, svc_info_safe=self._MASTER_SAFE
        )
        registry_mock = MagicMock()
        registry_mock.functions.ownerOf.return_value.call.return_value = (
            self._MASTER_SAFE
        )
        with (
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[1]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
            patch(
                f"{_MODULE}._get_service_registry_contract",
                return_value=registry_mock,
            ),
            patch(
                f"{_MODULE}.get_owners",
                return_value=[self._EOA],
            ),
        ):
            result = self._call(subgraph_url="http://subgraph")
        from web3 import Web3

        assert Web3.to_checksum_address(self._MASTER_SAFE) in result

    def test_zero_services_returns_empty(self) -> None:
        """When no service IDs are found, an empty list is returned."""
        with (
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[]),
            patch(f"{_MODULE}.StakingManager", return_value=MagicMock()),
            patch(f"{_MODULE}.get_default_rpc"),
        ):
            result = self._call(subgraph_url="http://subgraph")
        assert result == []

    # ------------------------------------------------------------------
    # MasterSafe resolution — non-staked branch
    # ------------------------------------------------------------------

    def test_non_staked_service_get_current_returns_none(self) -> None:
        """When get_current_staking_program returns None, ownerOf() is used."""
        mock_sm = self._mock_staking_manager(program_id=None)
        registry_mock = MagicMock()
        registry_mock.functions.ownerOf.return_value.call.return_value = (
            self._MASTER_SAFE
        )
        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[42]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
            patch(
                f"{_MODULE}._get_service_registry_contract",
                return_value=registry_mock,
            ),
            patch(
                f"{_MODULE}.get_owners",
                return_value=[self._EOA],
            ),
        ):
            result = self._call()
        from web3 import Web3

        assert Web3.to_checksum_address(self._MASTER_SAFE) in result
        # service_info should NOT have been called
        mock_sm.service_info.assert_not_called()

    # ------------------------------------------------------------------
    # MasterSafe resolution — staked branch
    # ------------------------------------------------------------------

    def test_staked_service_uses_service_info_wrapper(self) -> None:
        """When get_current_staking_program returns a program ID, service_info is used."""
        mock_sm = self._mock_staking_manager(
            program_id=self._PROGRAM_ID,
            staking_contract=self._STAKING_CONTRACT,
            svc_info_safe=self._MASTER_SAFE,
        )
        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[7]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
            patch(
                f"{_MODULE}.get_owners",
                return_value=[self._EOA],
            ),
        ):
            result = self._call()
        from web3 import Web3

        assert Web3.to_checksum_address(self._MASTER_SAFE) in result
        mock_sm.service_info.assert_called_once_with(
            staking_contract=self._STAKING_CONTRACT,
            service_id=7,
        )

    # ------------------------------------------------------------------
    # Multiple services / mixed staking states
    # ------------------------------------------------------------------

    def test_mixed_staked_and_non_staked_services(self) -> None:
        """Mix of staked (svc 1) and non-staked (svc 2) resolves both safes."""
        safe_staked = self._MASTER_SAFE
        safe_nonstaked = self._MASTER_SAFE2

        mock_sm = MagicMock()
        mock_sm.get_current_staking_program.side_effect = [
            self._PROGRAM_ID,  # svc 1 → staked
            None,  # svc 2 → not staked
        ]
        mock_sm.get_staking_contract.return_value = self._STAKING_CONTRACT
        mock_sm.service_info.return_value = (
            "0x" + "0" * 40,
            safe_staked,
            [],
            0,
            0,
            0,
        )

        registry_mock = MagicMock()
        registry_mock.functions.ownerOf.return_value.call.return_value = safe_nonstaked

        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[1, 2]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
            patch(
                f"{_MODULE}._get_service_registry_contract",
                return_value=registry_mock,
            ),
            patch(
                f"{_MODULE}.get_owners",
                return_value=[self._EOA],
            ),
        ):
            result = self._call()

        from web3 import Web3

        assert Web3.to_checksum_address(safe_staked) in result
        assert Web3.to_checksum_address(safe_nonstaked) in result

    def test_multiple_master_safes(self) -> None:
        """Two different service IDs mapping to two different MasterSafes."""
        safe_a = self._MASTER_SAFE
        safe_b = self._MASTER_SAFE2

        mock_sm = MagicMock()
        mock_sm.get_current_staking_program.return_value = None
        registry_mock = MagicMock()
        registry_mock.functions.ownerOf.return_value.call.side_effect = [
            safe_a,
            safe_b,
        ]

        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[10, 20]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
            patch(
                f"{_MODULE}._get_service_registry_contract",
                return_value=registry_mock,
            ),
            patch(
                f"{_MODULE}.get_owners",
                return_value=[self._EOA],
            ),
        ):
            result = self._call()

        from web3 import Web3

        assert Web3.to_checksum_address(safe_a) in result
        assert Web3.to_checksum_address(safe_b) in result

    # ------------------------------------------------------------------
    # Ownership verification
    # ------------------------------------------------------------------

    def test_eoa_not_owner_of_safe_skipped(self) -> None:
        """Safe is skipped when the recovery EOA is not listed as an owner."""
        mock_sm = self._mock_staking_manager(program_id=None)
        registry_mock = MagicMock()
        registry_mock.functions.ownerOf.return_value.call.return_value = (
            self._MASTER_SAFE
        )
        other_owner = "0x" + "9" * 40
        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[5]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
            patch(
                f"{_MODULE}._get_service_registry_contract",
                return_value=registry_mock,
            ),
            # EOA is NOT in the owners list
            patch(f"{_MODULE}.get_owners", return_value=[other_owner]),
        ):
            result = self._call()
        assert result == []

    def test_ownership_check_raises_skips_safe(self) -> None:
        """Safe is skipped when get_owners raises an exception."""
        mock_sm = self._mock_staking_manager(program_id=None)
        registry_mock = MagicMock()
        registry_mock.functions.ownerOf.return_value.call.return_value = (
            self._MASTER_SAFE
        )
        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[5]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
            patch(
                f"{_MODULE}._get_service_registry_contract",
                return_value=registry_mock,
            ),
            patch(f"{_MODULE}.get_owners", side_effect=Exception("rpc failure")),
        ):
            result = self._call()
        assert result == []

    # ------------------------------------------------------------------
    # Zero-address filtering
    # ------------------------------------------------------------------

    def test_service_info_owner_zero_address_skipped(self) -> None:
        """Safe resolution returning a zero address is silently skipped."""
        mock_sm = self._mock_staking_manager(
            program_id=self._PROGRAM_ID,
            staking_contract=self._STAKING_CONTRACT,
            svc_info_safe=ZERO_ADDRESS,
        )
        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[3]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
        ):
            result = self._call()
        assert result == []

    def test_staking_manager_resolution_exception_skips_service(self) -> None:
        """When get_current_staking_program raises, the outer except fires and service is skipped."""
        mock_sm = MagicMock()
        mock_sm.get_current_staking_program.side_effect = RuntimeError(
            "staking rpc error"
        )
        with (
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[9]),
            patch(f"{_MODULE}.StakingManager", return_value=mock_sm),
            patch(f"{_MODULE}.get_default_rpc"),
        ):
            result = self._call()
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
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
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
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
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
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
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
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
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
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
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
        """Safe addresses returned by _get_master_safes_from_contracts are scanned."""
        manager = _make_manager()
        safe = _SAFE_ADDR

        def _bal(*, ledger_api, asset_address, address, **kw):  # type: ignore[no-untyped-def]
            if address == safe and asset_address == ZERO_ADDRESS:
                return 9999
            return 0

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", side_effect=_bal),
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[safe]),
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
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[42]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
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
                f"{_MODULE}._get_master_safes_from_contracts",
                return_value=[_SAFE_ADDR, "0x" + "3" * 40],
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[7]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
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
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[1]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
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
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
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
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
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
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
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
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
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
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
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
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
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

    def test_scan_staking_lookup_failure_is_swallowed(self) -> None:
        """When StakingManager.get_current_staking_program raises, scan() still succeeds."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[99]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(
                f"{_MODULE}.StakingManager",
                side_effect=RuntimeError("staking rpc error"),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # scan must still succeed and return the service
        assert isinstance(result, FundRecoveryScanResponse)
        service_ids = [s.service_id for s in result.services]
        assert 99 in service_ids

    def test_scan_records_staked_olas_in_balances(self) -> None:
        """When a service is staked, the staking contract appears in balances with OLAS amount."""
        manager = _make_manager()

        _staking_contract = "0x" + "a" * 40
        _olas_addr = "0x" + "c" * 40
        _min_deposit = 100

        mock_staking_manager = MagicMock()
        mock_staking_manager.get_current_staking_program.return_value = "pearl_beta"
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": _min_deposit
        }

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[77]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(f"{_MODULE}.StakingManager", return_value=mock_staking_manager),
            patch(
                f"{_MODULE}.STAKING",
                {chain: {"pearl_beta": _staking_contract} for chain in RECOVERY_CHAINS},
            ),
            patch(
                f"{_MODULE}.OLAS",
                {chain: _olas_addr for chain in RECOVERY_CHAINS},
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # At least one chain should have the staking contract with 2 * min_deposit OLAS
        from web3 import Web3

        staking_contract_cs = Web3.to_checksum_address(_staking_contract)
        found = False
        for _chain_id_str, addresses in result.balances.items():
            if staking_contract_cs in addresses:
                amount = int(addresses[staking_contract_cs].get(_olas_addr, 0))
                if amount == _min_deposit * 2:
                    found = True
                    break
        assert found, f"Staked OLAS not found in balances; balances={result.balances}"

    def test_scan_zero_staked_olas_logs_info(self) -> None:
        """When a service is staked but has zero min_staking_deposit, info is logged."""
        manager = _make_manager()

        _staking_contract = "0x" + "a" * 40
        _olas_addr = "0x" + "c" * 40

        mock_staking_manager = MagicMock()
        mock_staking_manager.get_current_staking_program.return_value = "pearl_beta"
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": 0
        }

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[77]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(f"{_MODULE}.StakingManager", return_value=mock_staking_manager),
            patch(
                f"{_MODULE}.STAKING",
                {chain: {"pearl_beta": _staking_contract} for chain in RECOVERY_CHAINS},
            ),
            patch(
                f"{_MODULE}.OLAS",
                {chain: _olas_addr for chain in RECOVERY_CHAINS},
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Verify scan completed (should succeed)
        assert isinstance(result, FundRecoveryScanResponse)
        service_ids = [s.service_id for s in result.services]
        assert 77 in service_ids

    def test_scan_no_subgraph_url_falls_back_to_rpc(self) -> None:
        """When no subgraph URL is configured, warning is logged and RPC enumeration is used."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(f"{_MODULE}.SUBGRAPH_URLS", {}),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[55]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Verify scan succeeded and used RPC enumeration
        assert isinstance(result, FundRecoveryScanResponse)
        service_ids = [s.service_id for s in result.services]
        assert 55 in service_ids

    def test_scan_get_service_state_is_called(self) -> None:
        """_get_service_state is called for each discovered service."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[88]),
            patch(
                f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED
            ) as mock_state,
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Verify _get_service_state was called
        assert mock_state.called
        service_ids = [s.service_id for s in result.services]
        assert 88 in service_ids

    def test_scan_agent_safe_zero_address_logs_warning(self) -> None:
        """When agent safe resolves to zero address, warning is logged and service is skipped for balances."""
        manager = _make_manager()

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[99]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Verify service is still included (but agent safe balances skipped)
        assert isinstance(result, FundRecoveryScanResponse)
        service_ids = [s.service_id for s in result.services]
        assert 99 in service_ids

    def test_scan_olas_token_not_found_logs_warning(self) -> None:
        """When OLAS token address is not found for chain, warning is logged."""
        manager = _make_manager()

        _staking_contract = "0x" + "a" * 40

        mock_staking_manager = MagicMock()
        mock_staking_manager.get_current_staking_program.return_value = "pearl_beta"
        mock_staking_manager.get_staking_params.return_value = {
            "min_staking_deposit": 100
        }

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[77]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(f"{_MODULE}.StakingManager", return_value=mock_staking_manager),
            patch(
                f"{_MODULE}.STAKING",
                {chain: {"pearl_beta": _staking_contract} for chain in RECOVERY_CHAINS},
            ),
            patch(
                f"{_MODULE}.OLAS",
                {chain: None for chain in RECOVERY_CHAINS},
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Verify scan completed despite missing OLAS token
        assert isinstance(result, FundRecoveryScanResponse)
        service_ids = [s.service_id for s in result.services]
        assert 77 in service_ids

    def test_scan_staking_contract_not_found_logs_warning(self) -> None:
        """When staking_program_id is set but not in STAKING dict, warning is logged."""
        manager = _make_manager()

        mock_staking_manager = MagicMock()
        # Service is staked with a program ID, but that ID has no entry in STAKING
        mock_staking_manager.get_current_staking_program.return_value = (
            "unknown_program"
        )

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[77]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(f"{_MODULE}.StakingManager", return_value=mock_staking_manager),
            # STAKING dict does not contain "unknown_program" for any chain
            patch(
                f"{_MODULE}.STAKING",
                {chain: {} for chain in RECOVERY_CHAINS},
            ),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Scan must complete successfully; the staking contract warning is just logged
        assert isinstance(result, FundRecoveryScanResponse)
        service_ids = [s.service_id for s in result.services]
        assert 77 in service_ids

    def test_scan_service_not_staked_logs_info(self) -> None:
        """When staking_program_id is None (service not staked), info is logged."""
        manager = _make_manager()

        mock_staking_manager = MagicMock()
        # get_current_staking_program returns None → service is not staked
        mock_staking_manager.get_current_staking_program.return_value = None

        with (
            patch(f"{_MODULE}.get_default_ledger_api"),
            patch(f"{_MODULE}.get_asset_balance", return_value=0),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[88]),
            patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
            patch(
                f"{_MODULE}._check_gas_warning",
                return_value=GasWarningEntry(insufficient=False),
            ),
            patch(f"{_MODULE}.StakingManager", return_value=mock_staking_manager),
        ):
            result = manager.scan(_TEST_MNEMONIC)

        # Scan must complete successfully and include the service
        assert isinstance(result, FundRecoveryScanResponse)
        service_ids = [s.service_id for s in result.services]
        assert 88 in service_ids


# ---------------------------------------------------------------------------
# FundRecoveryManager.execute
# ---------------------------------------------------------------------------


def _make_execute_mocks():  # type: ignore[no-untyped-def]
    """Return a standard set of mocks for execute() tests (no services, no safes)."""
    mock_wallet = MagicMock()
    mock_wallet.drain.return_value = {}
    mock_wallet.safes = {}
    mock_wallet.safe_chains = []
    mock_wallet.ledger_api.return_value = MagicMock()

    mock_wm_instance = MagicMock()
    mock_wm_instance.setup.return_value = mock_wm_instance
    mock_wm_instance.import_from_mnemonic.return_value = (mock_wallet, [])

    mock_sm_instance = MagicMock()
    mock_sm_instance.setup.return_value = mock_sm_instance

    return mock_wallet, mock_wm_instance, mock_sm_instance


class TestFundRecoveryManagerExecute:
    """Tests for FundRecoveryManager.execute."""

    # ------------------------------------------------------------------
    # Basic happy-path
    # ------------------------------------------------------------------

    def test_execute_returns_correct_type(self) -> None:
        """execute() always returns FundRecoveryExecuteResponse."""
        manager = _make_manager()
        mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
        with (
            patch(f"{_MODULE}.KeysManager"),
            patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
            patch(f"{_MODULE}.FundingManager"),
            patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)
        assert isinstance(result, FundRecoveryExecuteResponse)

    def test_execute_success_no_errors(self) -> None:
        """Happy path with no services and no funds produces success=True, errors=[]."""
        manager = _make_manager()
        mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
        with (
            patch(f"{_MODULE}.KeysManager"),
            patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
            patch(f"{_MODULE}.FundingManager"),
            patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        ):
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert result.success is True
        assert result.errors == []
        assert result.partial_failure is False


# ---------------------------------------------------------------------------
# Multisig on-chain fetch correctness
# ---------------------------------------------------------------------------


_AGENT_SAFE_ADDR = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"


class TestExecuteMultisigFetch:
    """Verify that chain_config.chain_data.multisig is set from on-chain data, not safe_addr."""

    def _make_mocks_with_service(self):  # type: ignore[no-untyped-def]
        """Return mocks set up with a service and safe."""
        mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()

        mock_chain_config = MagicMock()
        mock_service = MagicMock()
        mock_service.service_config_id = "test-id"
        # chain_configs[chain_str] returns mock_chain_config automatically via MagicMock
        mock_sm_instance.create.return_value = mock_service

        return (
            mock_wallet,
            mock_wm_instance,
            mock_sm_instance,
            mock_service,
            mock_chain_config,
        )

    def test_multisig_set_from_on_chain_when_nonzero(self) -> None:
        """When get_service_info returns a real address at index 1, multisig is set to it (checksummed)."""
        (
            mock_wallet,
            mock_wm_instance,
            mock_sm_instance,
            mock_service,
            mock_chain_config,
        ) = self._make_mocks_with_service()
        # Wire up chain_configs to return our mock_chain_config
        mock_service.chain_configs.__getitem__ = MagicMock(
            return_value=mock_chain_config
        )

        svc_info: t.Tuple[int, str, bytes, int, int, int, int, t.List[int]] = (
            0,
            _AGENT_SAFE_ADDR,
            b"",
            1,
            1,
            1,
            4,
            [],
        )

        with (
            patch(f"{_MODULE}.KeysManager"),
            patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
            patch(f"{_MODULE}.FundingManager"),
            patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[55]),
            patch(f"{_MODULE}.get_service_info", return_value=svc_info),
        ):
            manager = FundRecoveryManager()
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        # The multisig should have been set to the checksummed agent safe
        assigned_multisig = mock_chain_config.chain_data.multisig
        from web3 import Web3

        assert assigned_multisig == Web3.to_checksum_address(_AGENT_SAFE_ADDR)
        assert assigned_multisig != _SAFE_ADDR
        assert result.success is True

    def test_multisig_set_to_non_existent_when_zero_address(self) -> None:
        """When get_service_info returns ZERO_ADDRESS at index 1, multisig is NON_EXISTENT_MULTISIG."""
        from operate.services.service import NON_EXISTENT_MULTISIG

        (
            mock_wallet,
            mock_wm_instance,
            mock_sm_instance,
            mock_service,
            mock_chain_config,
        ) = self._make_mocks_with_service()
        mock_service.chain_configs.__getitem__ = MagicMock(
            return_value=mock_chain_config
        )

        svc_info: t.Tuple[int, str, bytes, int, int, int, int, t.List[int]] = (
            0,
            ZERO_ADDRESS,
            b"",
            1,
            1,
            0,
            1,
            [],
        )

        with (
            patch(f"{_MODULE}.KeysManager"),
            patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
            patch(f"{_MODULE}.FundingManager"),
            patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[56]),
            patch(f"{_MODULE}.get_service_info", return_value=svc_info),
        ):
            manager = FundRecoveryManager()
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert mock_chain_config.chain_data.multisig == NON_EXISTENT_MULTISIG
        assert result.success is True

    def test_multisig_set_to_non_existent_when_get_service_info_raises(self) -> None:
        """When get_service_info raises, multisig falls back to NON_EXISTENT_MULTISIG."""
        from operate.services.service import NON_EXISTENT_MULTISIG

        (
            mock_wallet,
            mock_wm_instance,
            mock_sm_instance,
            mock_service,
            mock_chain_config,
        ) = self._make_mocks_with_service()
        mock_service.chain_configs.__getitem__ = MagicMock(
            return_value=mock_chain_config
        )

        with (
            patch(f"{_MODULE}.KeysManager"),
            patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
            patch(f"{_MODULE}.FundingManager"),
            patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
            patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
            patch(
                f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]
            ),
            patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[58]),
            patch(f"{_MODULE}.get_service_info", side_effect=Exception("rpc error")),
        ):
            manager = FundRecoveryManager()
            result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

        assert mock_chain_config.chain_data.multisig == NON_EXISTENT_MULTISIG
        assert result.success is True

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
            patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[safe]),
            patch(
                f"{_MODULE}._fetch_services_from_subgraph",
                side_effect=Exception("network"),
            ),
            patch(f"{_MODULE}._enumerate_owned_services", return_value=[]),
            patch(
                f"{_MODULE}.get_service_info",
                return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
            ),
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


def test_inject_safe_into_wallet(tmp_path: Path) -> None:
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


def test_inject_safe_into_wallet_idempotent(tmp_path: Path) -> None:
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


def test_execute_calls_service_manager_methods_for_deployed_service() -> None:
    """execute() calls terminate, recovery module, and drain for a deployed service."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()

    mock_service = MagicMock()
    mock_service.service_config_id = "test-id-7"
    mock_sm_instance.create.return_value = mock_service

    svc_info: t.Tuple[t.Any, ...] = (
        0,
        "0xAbCdEf0000000000000000000000000000000001",
        b"",
        1,
        1,
        1,
        4,
        [],
    )

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[7]),
        patch(f"{_MODULE}.get_service_info", return_value=svc_info),
    ):
        manager = FundRecoveryManager()
        manager.execute(
            mnemonic=_TEST_MNEMONIC,
            destination_address=_DEST_ADDR,
        )

    # terminate → recovery module → drain should all be called
    assert mock_sm_instance.terminate_service_on_chain_from_safe.call_count >= 1
    assert mock_sm_instance._execute_recovery_module_flow_from_safe.call_count >= 1
    assert mock_sm_instance.drain.call_count >= 1
    # wallet.drain should be called for the safe and EOA
    assert mock_wallet.drain.call_count >= 1


def test_execute_creates_wallet_manager_and_imports_wallet() -> None:
    """execute() should instantiate MasterWalletManager in a tempdir and import the wallet."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()

    mock_wm_cls = MagicMock(return_value=mock_wm_instance)

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", mock_wm_cls),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(
            mnemonic=_TEST_MNEMONIC,
            destination_address=_DEST_ADDR,
        )

    # MasterWalletManager was constructed with a path argument
    assert mock_wm_cls.call_count == 1
    constructed_path = (
        mock_wm_cls.call_args[1].get("path") or mock_wm_cls.call_args[0][0]
    )
    assert isinstance(constructed_path, Path)

    # import_from_mnemonic was called with LedgerType.ETHEREUM and the mnemonic
    mock_wm_instance.import_from_mnemonic.assert_called_once_with(
        LedgerType.ETHEREUM,
        _TEST_MNEMONIC,
    )

    assert result.success is True


# ---------------------------------------------------------------------------
# Additional execute() branch coverage tests
# ---------------------------------------------------------------------------


def test_execute_chain_level_exception_adds_to_errors() -> None:
    """When wallet.ledger_api raises, the chain-level except fires and adds to errors."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
    mock_wallet.ledger_api.side_effect = RuntimeError("rpc unavailable")

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    # Each of the RECOVERY_CHAINS should have added an error entry
    assert len(result.errors) == len(RECOVERY_CHAINS)
    assert all("RuntimeError" in e for e in result.errors)
    assert result.success is False
    assert result.partial_failure is False


def test_execute_subgraph_fallback_calls_enumerate_owned_services() -> None:
    """When _fetch_services_from_subgraph raises in execute(), _enumerate_owned_services is called."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(
            f"{_MODULE}._fetch_services_from_subgraph",
            side_effect=Exception("subgraph down"),
        ),
        patch(
            f"{_MODULE}._enumerate_owned_services", return_value=[]
        ) as mock_enumerate,
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    # _enumerate_owned_services must have been called as fallback
    assert mock_enumerate.call_count >= 1
    assert result.success is True


def test_execute_svc_manager_create_exception_adds_to_errors() -> None:
    """When svc_manager.create() raises, the per-service except fires."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
    mock_sm_instance.create.side_effect = RuntimeError("create failed")

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[42]),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert any("RuntimeError" in e for e in result.errors)
    assert result.success is False


def test_execute_terminate_exception_adds_to_errors() -> None:
    """When terminate_service_on_chain_from_safe raises, errors are appended."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
    mock_sm_instance.create.return_value = MagicMock(service_config_id="test-id")
    mock_sm_instance.terminate_service_on_chain_from_safe.side_effect = RuntimeError(
        "terminate failed"
    )

    svc_info: t.Tuple[t.Any, ...] = (0, _AGENT_SAFE_ADDR, b"", 1, 1, 1, 4, [])

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[42]),
        patch(f"{_MODULE}.get_service_info", return_value=svc_info),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert any("terminate failed" in e for e in result.errors)
    assert result.success is False


def test_execute_recovery_module_exception_adds_to_errors() -> None:
    """When _execute_recovery_module_flow_from_safe raises, errors are appended."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
    mock_sm_instance.create.return_value = MagicMock(service_config_id="test-id")
    mock_sm_instance._execute_recovery_module_flow_from_safe.side_effect = RuntimeError(
        "recovery module failed"
    )

    svc_info: t.Tuple[t.Any, ...] = (0, _AGENT_SAFE_ADDR, b"", 1, 1, 1, 4, [])

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[42]),
        patch(f"{_MODULE}.get_service_info", return_value=svc_info),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert any("recovery module failed" in e for e in result.errors)
    assert result.success is False


def test_execute_agent_safe_drain_exception_adds_to_errors() -> None:
    """When svc_manager.drain raises, errors are appended."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
    mock_sm_instance.create.return_value = MagicMock(service_config_id="test-id")
    mock_sm_instance.drain.side_effect = RuntimeError("drain agent safe failed")

    svc_info: t.Tuple[t.Any, ...] = (0, _AGENT_SAFE_ADDR, b"", 1, 1, 1, 4, [])

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[42]),
        patch(f"{_MODULE}.get_service_info", return_value=svc_info),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert any("drain agent safe failed" in e for e in result.errors)
    assert result.success is False


def test_execute_safe_drain_exception_adds_to_errors() -> None:
    """When wallet.drain(from_safe=True) raises, the safe-level except fires."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()

    def _drain_side_effect(**kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("from_safe"):
            raise RuntimeError("safe drain failed")
        return {}

    mock_wallet.drain.side_effect = _drain_side_effect

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert any("drain_safe" in e for e in result.errors)
    assert result.success is False


def test_execute_eoa_drain_exception_adds_to_errors() -> None:
    """When wallet.drain(from_safe=False) raises, the EOA drain except fires."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()

    def _drain_side_effect(**kwargs):  # type: ignore[no-untyped-def]
        if not kwargs.get("from_safe"):
            raise RuntimeError("eoa drain failed")
        return {}

    mock_wallet.drain.side_effect = _drain_side_effect

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert any("drain_eoa" in e for e in result.errors)
    assert result.success is False


def test_execute_funds_moved_tracked_when_drain_returns_nonzero() -> None:
    """When wallet.drain returns a non-empty dict, total_funds_moved is populated."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
    # EOA drain returns a non-empty dict
    mock_wallet.drain.return_value = {ZERO_ADDRESS: 1000}

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert result.success is True
    # total_funds_moved should be non-empty since drain returned funds
    assert bool(result.total_funds_moved)


def test_execute_safe_funds_moved_tracked_when_drain_returns_nonzero() -> None:
    """When wallet.drain(from_safe=True) returns funds, total_funds_moved is populated."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()

    def _drain_side_effect(**kwargs):  # type: ignore[no-untyped-def]
        return {ZERO_ADDRESS: 500}

    mock_wallet.drain.side_effect = _drain_side_effect

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[]),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert result.success is True
    assert bool(result.total_funds_moved)


def test_execute_partial_failure_when_errors_and_funds_moved() -> None:
    """partial_failure=True when there are errors AND funds were moved."""
    mock_wallet, mock_wm_instance, mock_sm_instance = _make_execute_mocks()
    mock_sm_instance.create.return_value = MagicMock(service_config_id="test-id")
    # terminate fails → error is added
    mock_sm_instance.terminate_service_on_chain_from_safe.side_effect = RuntimeError(
        "terminate failed"
    )
    # wallet.drain(from_safe=False) succeeds and returns funds
    eoa_call_count = [0]

    def _drain_side_effect(**kwargs):  # type: ignore[no-untyped-def]
        if not kwargs.get("from_safe"):
            eoa_call_count[0] += 1
            return {ZERO_ADDRESS: 999}
        return {}

    mock_wallet.drain.side_effect = _drain_side_effect

    svc_info: t.Tuple[t.Any, ...] = (0, _AGENT_SAFE_ADDR, b"", 1, 1, 1, 4, [])

    with (
        patch(f"{_MODULE}.KeysManager"),
        patch(f"{_MODULE}.MasterWalletManager", return_value=mock_wm_instance),
        patch(f"{_MODULE}.FundingManager"),
        patch(f"{_MODULE}.ServiceManager", return_value=mock_sm_instance),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(f"{_MODULE}.get_default_rpc", return_value="https://rpc.test"),
        patch(f"{_MODULE}._fetch_services_from_subgraph", return_value=[42]),
        patch(f"{_MODULE}.get_service_info", return_value=svc_info),
    ):
        manager = FundRecoveryManager()
        result = manager.execute(_TEST_MNEMONIC, _DEST_ADDR)

    assert result.success is False
    assert bool(result.total_funds_moved)
    assert result.partial_failure is True


# ---------------------------------------------------------------------------
# New tests for agent-safe balance scanning
# ---------------------------------------------------------------------------

_AGENT_SAFE_SCAN_ADDR = "0xCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCc"


def test_scan_deduplicates_service_ids_via_continue() -> None:
    """Line 515: 'continue' fires when the same service_id appears twice in all_service_ids.

    This happens in the fallback path when two safes both own the same service.
    """
    manager = _make_manager()

    # Two safes that each return service ID 99 → all_service_ids = [99, 99]
    with (
        patch(f"{_MODULE}.get_default_ledger_api"),
        patch(f"{_MODULE}.get_asset_balance", return_value=0),
        patch(
            f"{_MODULE}._get_master_safes_from_contracts",
            return_value=[_SAFE_ADDR, "0x" + "4" * 40],
        ),
        patch(
            f"{_MODULE}._fetch_services_from_subgraph",
            side_effect=Exception("network"),
        ),
        # Both safes own service 99 → extend produces [99, 99]
        patch(f"{_MODULE}._enumerate_owned_services", return_value=[99]),
        patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
        patch(
            f"{_MODULE}.get_service_info",
            return_value=(0, ZERO_ADDRESS, b"", 1, 1, 0, 1, []),
        ),
        patch(
            f"{_MODULE}._check_gas_warning",
            return_value=GasWarningEntry(insufficient=False),
        ),
    ):
        result = manager.scan(_TEST_MNEMONIC)

    # Service 99 must appear exactly once per chain (deduplicated via continue)
    ids_per_chain: t.Dict[int, t.List[int]] = {}
    for svc in result.services:
        ids_per_chain.setdefault(svc.chain_id, []).append(svc.service_id)
    for chain_id, ids in ids_per_chain.items():
        assert ids.count(99) == 1, f"Duplicate service 99 on chain {chain_id}"


def test_scan_get_service_info_raises_is_swallowed() -> None:
    """Lines 544-551: Exception in get_service_info is caught; scan still succeeds."""
    manager = _make_manager()

    with (
        patch(f"{_MODULE}.get_default_ledger_api"),
        patch(f"{_MODULE}.get_asset_balance", return_value=0),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(
            f"{_MODULE}._fetch_services_from_subgraph",
            side_effect=Exception("network"),
        ),
        patch(f"{_MODULE}._enumerate_owned_services", return_value=[77]),
        patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
        # Force the inner except (lines 544-551) to fire
        patch(
            f"{_MODULE}.get_service_info",
            side_effect=Exception("rpc error"),
        ),
        patch(
            f"{_MODULE}._check_gas_warning",
            return_value=GasWarningEntry(insufficient=False),
        ),
    ):
        result = manager.scan(_TEST_MNEMONIC)

    # Exception must be swallowed; result is still valid
    assert isinstance(result, FundRecoveryScanResponse)
    service_ids = [s.service_id for s in result.services]
    assert 77 in service_ids


def test_scan_agent_safe_balance_included_when_nonzero() -> None:
    """Lines 560-577: Agent safe balances (native + ERC-20) are fetched and recorded."""
    manager = _make_manager()

    def _bal(  # type: ignore[no-untyped-def]
        *, ledger_api, asset_address, address, **kw
    ):
        # Non-zero native balance for the agent safe
        if (
            address.lower() == _AGENT_SAFE_SCAN_ADDR.lower()
            and asset_address == ZERO_ADDRESS
        ):
            return 5000
        # Non-zero ERC-20 balance for the agent safe
        if (
            address.lower() == _AGENT_SAFE_SCAN_ADDR.lower()
            and asset_address == _TOKEN_ADDR
        ):
            return 2500
        return 0

    with (
        patch(f"{_MODULE}.get_default_ledger_api"),
        patch(f"{_MODULE}.get_asset_balance", side_effect=_bal),
        patch(f"{_MODULE}._get_master_safes_from_contracts", return_value=[_SAFE_ADDR]),
        patch(
            f"{_MODULE}._fetch_services_from_subgraph",
            side_effect=Exception("network"),
        ),
        patch(f"{_MODULE}._enumerate_owned_services", return_value=[88]),
        patch(f"{_MODULE}._get_service_state", return_value=OnChainState.DEPLOYED),
        # Return a real (non-zero) agent safe address
        patch(
            f"{_MODULE}.get_service_info",
            return_value=(0, _AGENT_SAFE_SCAN_ADDR, b"", 1, 1, 1, 4, []),
        ),
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

    # Agent safe's checksummed address must appear in balances with native balance
    from web3 import Web3

    agent_safe_cs = Web3.to_checksum_address(_AGENT_SAFE_SCAN_ADDR)

    native_found = False
    token_found = False
    for _chain_id_str, addresses in result.balances.items():
        if agent_safe_cs in addresses:
            if int(addresses[agent_safe_cs].get(ZERO_ADDRESS, 0)) == 5000:
                native_found = True
            if int(addresses[agent_safe_cs].get(_TOKEN_ADDR, 0)) == 2500:
                token_found = True

    assert (
        native_found
    ), f"Agent safe native balance not recorded; balances={result.balances}"
    assert (
        token_found
    ), f"Agent safe ERC-20 balance not recorded; balances={result.balances}"
