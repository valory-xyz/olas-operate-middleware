# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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
"""Unit tests for operate/services/protocol.py."""
import typing as t
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from autonomy.chain.config import ChainType

from operate.operate_types import Chain as OperateChain
from operate.services.protocol import (
    EthSafeTxBuilder,
    GnosisSafeTransaction,
    StakingManager,
    StakingState,
    _ChainUtil,
    get_packed_signature_for_approved_hash,
)
from operate.services.service import NON_EXISTENT_TOKEN


_STAKING_CONTRACT = "0xaaaa000000000000000000000000000000000001"
_SERVICE_REGISTRY = "0xbbbb000000000000000000000000000000000002"
_SAFE_ADDRESS = "0xcccc000000000000000000000000000000000003"
_MASTER_SAFE = "0xdddd000000000000000000000000000000000004"
_ENCODED = "0x" + "ab" * 32
_CONTRACTS: t.Dict[str, str] = {
    "service_manager": "0x0000000000000000000000000000000000000001",
    "service_registry": "0x0000000000000000000000000000000000000002",
    "service_registry_token_utility": "0x0000000000000000000000000000000000000003",
    "gnosis_safe_proxy_factory": "0x0000000000000000000000000000000000000004",
    "gnosis_safe_same_address_multisig": "0x0000000000000000000000000000000000000005",
    "safe_multisig_with_recovery_module": "0x0000000000000000000000000000000000000006",
    "recovery_module": "0x0000000000000000000000000000000000000007",
    "multisend": "0x0000000000000000000000000000000000000008",
}


def _make_chain_util(
    chain_type: ChainType = ChainType.GNOSIS,
    contracts: t.Optional[t.Dict[str, str]] = None,
) -> _ChainUtil:
    """Create a _ChainUtil with a mock wallet."""
    mock_wallet = MagicMock()
    mock_wallet.safes = {}
    return _ChainUtil(
        rpc="http://localhost:8545",
        wallet=mock_wallet,
        contracts=contracts if contracts is not None else _CONTRACTS,
        chain_type=chain_type,
    )


def _make_eth_safe_tx_builder(
    chain_type: ChainType = ChainType.GNOSIS,
    contracts: t.Optional[t.Dict[str, str]] = None,
) -> EthSafeTxBuilder:
    """Create an EthSafeTxBuilder with a mock wallet."""
    mock_wallet = MagicMock()
    mock_wallet.safes = {}
    return EthSafeTxBuilder(
        rpc="http://localhost:8545",
        wallet=mock_wallet,
        contracts=contracts if contracts is not None else _CONTRACTS,
        chain_type=chain_type,
    )


# ---------------------------------------------------------------------------
# tests for get_packed_signature_for_approved_hash
# ---------------------------------------------------------------------------


class TestGetPackedSignatureForApprovedHash:
    """Tests for get_packed_signature_for_approved_hash."""

    def test_single_owner_returns_65_bytes(self) -> None:
        """Single owner produces a 65-byte packed signature."""
        owner = "0xAbCd1234" + "00" * 18
        result = get_packed_signature_for_approved_hash(owners=(owner,))
        # Each sig = 32 (r) + 32 (s) + 1 (v) = 65 bytes
        assert len(result) == 65

    def test_two_owners_returns_130_bytes(self) -> None:
        """Two owners produce a 130-byte packed signature."""
        owner_a = "0x" + "aa" * 20
        owner_b = "0x" + "bb" * 20
        result = get_packed_signature_for_approved_hash(owners=(owner_a, owner_b))
        assert len(result) == 130

    def test_owners_sorted_case_insensitively(self) -> None:
        """Owners are sorted in case-insensitive order."""
        low = "0x" + "11" * 20
        high = "0x" + "ff" * 20
        # Call twice in different order; result should be the same
        r1 = get_packed_signature_for_approved_hash(owners=(high, low))
        r2 = get_packed_signature_for_approved_hash(owners=(low, high))
        assert r1 == r2

    def test_v_byte_is_one(self) -> None:
        """The v byte of each signature is 0x01."""
        owner = "0x" + "cc" * 20
        result = get_packed_signature_for_approved_hash(owners=(owner,))
        # v is the last byte of the 65-byte sig
        assert result[-1] == 1

    def test_s_bytes_are_zero(self) -> None:
        """The s portion (bytes 32-63) of the signature is all zeros."""
        owner = "0x" + "dd" * 20
        result = get_packed_signature_for_approved_hash(owners=(owner,))
        s_portion = result[32:64]
        assert s_portion == b"\x00" * 32


# ---------------------------------------------------------------------------
# tests for StakingManager._get_staking_params
# ---------------------------------------------------------------------------


class TestStakingManagerGetStakingParams:
    """Tests for StakingManager._get_staking_params (the static cached method)."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test."""
        StakingManager._get_staking_params.cache_clear()

    def _make_concurrent_execute_return(
        self,
        second_token: t.Optional[str] = None,
        second_token_amount: t.Optional[int] = None,
    ) -> t.Tuple[t.Any, ...]:
        """Return a tuple matching what concurrent_execute produces."""
        return (
            [1],
            _SERVICE_REGISTRY,
            "0xToken",
            "0xSRTU",
            1000,
            "0xChecker",
            second_token,
            second_token_amount,
        )

    def test_uses_default_ledger_api_when_no_rpc(self) -> None:
        """Uses get_default_ledger_api when rpc is None."""
        mock_ledger = MagicMock()
        mock_dual_instance = MagicMock()
        mock_staking_instance = MagicMock()

        with patch(
            "operate.services.protocol.get_default_ledger_api", return_value=mock_ledger
        ) as mock_default, patch.object(
            StakingManager, "dual_staking_ctr"
        ) as mock_dual_ctr, patch.object(
            StakingManager, "staking_ctr"
        ) as mock_staking_ctr, patch(
            "operate.services.protocol.concurrent_execute",
            return_value=self._make_concurrent_execute_return(),
        ):
            mock_dual_ctr.get_instance.return_value = mock_dual_instance
            mock_staking_ctr.get_instance.return_value = mock_staking_instance
            result = StakingManager._get_staking_params(
                OperateChain.GNOSIS, "0xContract_a1"
            )

        mock_default.assert_called_once()
        assert result["staking_contract"] == "0xContract_a1"

    def test_uses_make_chain_ledger_api_when_rpc_provided(self) -> None:
        """Uses make_chain_ledger_api when rpc is given."""
        mock_ledger = MagicMock()
        mock_dual_instance = MagicMock()
        mock_staking_instance = MagicMock()

        with patch(
            "operate.services.protocol.make_chain_ledger_api", return_value=mock_ledger
        ) as mock_make, patch.object(
            StakingManager, "dual_staking_ctr"
        ) as mock_dual_ctr, patch.object(
            StakingManager, "staking_ctr"
        ) as mock_staking_ctr, patch(
            "operate.services.protocol.concurrent_execute",
            return_value=self._make_concurrent_execute_return(),
        ):
            mock_dual_ctr.get_instance.return_value = mock_dual_instance
            mock_staking_ctr.get_instance.return_value = mock_staking_instance
            result = StakingManager._get_staking_params(
                OperateChain.GNOSIS, "0xContract_a2", rpc="http://rpc"
            )

        mock_make.assert_called_once()
        assert result["agent_ids"] == [1]

    def test_dual_staking_exception_falls_back_gracefully(self) -> None:
        """When dual_staking_ctr raises, the function continues with None lambdas."""
        mock_staking_instance = MagicMock()

        with patch("operate.services.protocol.get_default_ledger_api"), patch.object(
            StakingManager, "dual_staking_ctr"
        ) as mock_dual_ctr, patch.object(
            StakingManager, "staking_ctr"
        ) as mock_staking_ctr, patch(
            "operate.services.protocol.concurrent_execute",
            return_value=self._make_concurrent_execute_return(),
        ):
            mock_dual_ctr.get_instance.side_effect = Exception("not dual staking")
            mock_staking_ctr.get_instance.return_value = mock_staking_instance
            result = StakingManager._get_staking_params(
                OperateChain.GNOSIS, "0xContract_a3"
            )

        assert result["additional_staking_tokens"] == {}

    def test_second_token_included_when_both_non_none(self) -> None:
        """additional_staking_tokens populated when second_token and amount are non-None."""
        mock_dual_instance = MagicMock()
        mock_staking_instance = MagicMock()

        with patch("operate.services.protocol.get_default_ledger_api"), patch.object(
            StakingManager, "dual_staking_ctr"
        ) as mock_dual_ctr, patch.object(
            StakingManager, "staking_ctr"
        ) as mock_staking_ctr, patch(
            "operate.services.protocol.concurrent_execute",
            return_value=self._make_concurrent_execute_return("0xSecondToken", 500),
        ):
            mock_dual_ctr.get_instance.return_value = mock_dual_instance
            mock_staking_ctr.get_instance.return_value = mock_staking_instance
            result = StakingManager._get_staking_params(
                OperateChain.GNOSIS, "0xContract_a4"
            )

        assert result["additional_staking_tokens"] == {"0xSecondToken": 500}

    def test_second_token_empty_when_second_token_none(self) -> None:
        """additional_staking_tokens is empty when second_token is None."""
        mock_dual_instance = MagicMock()
        mock_staking_instance = MagicMock()

        with patch("operate.services.protocol.get_default_ledger_api"), patch.object(
            StakingManager, "dual_staking_ctr"
        ) as mock_dual_ctr, patch.object(
            StakingManager, "staking_ctr"
        ) as mock_staking_ctr, patch(
            "operate.services.protocol.concurrent_execute",
            return_value=self._make_concurrent_execute_return(None, 500),
        ):
            mock_dual_ctr.get_instance.return_value = mock_dual_instance
            mock_staking_ctr.get_instance.return_value = mock_staking_instance
            result = StakingManager._get_staking_params(
                OperateChain.GNOSIS, "0xContract_a5"
            )

        assert result["additional_staking_tokens"] == {}


# ---------------------------------------------------------------------------
# tests for StakingManager.check_staking_compatibility
# ---------------------------------------------------------------------------


class TestCheckStakingCompatibility:
    """Tests for StakingManager.check_staking_compatibility."""

    def _make_manager(self) -> StakingManager:
        """Create a StakingManager for testing."""
        return StakingManager(chain=OperateChain.GNOSIS)

    def test_raises_when_already_staked(self) -> None:
        """Raises ValueError when service is already STAKED."""
        mgr = self._make_manager()
        with patch.object(mgr, "staking_state", return_value=StakingState.STAKED):
            with pytest.raises(ValueError, match="Service already staked"):
                mgr.check_staking_compatibility(
                    service_id=1, staking_contract=_STAKING_CONTRACT
                )

    def test_raises_when_evicted(self) -> None:
        """Raises ValueError when service is EVICTED."""
        mgr = self._make_manager()
        with patch.object(mgr, "staking_state", return_value=StakingState.EVICTED):
            with pytest.raises(ValueError, match="Service is evicted"):
                mgr.check_staking_compatibility(
                    service_id=1, staking_contract=_STAKING_CONTRACT
                )

    def test_raises_when_no_slots_available(self) -> None:
        """Raises ValueError when no staking slots are available."""
        mgr = self._make_manager()
        with patch.object(
            mgr, "staking_state", return_value=StakingState.UNSTAKED
        ), patch.object(mgr, "slots_available", return_value=False):
            with pytest.raises(ValueError, match="No sataking slots"):
                mgr.check_staking_compatibility(
                    service_id=1, staking_contract=_STAKING_CONTRACT
                )

    def test_passes_when_unstaked_and_slots_available(self) -> None:
        """Does not raise when service is UNSTAKED and slots are available."""
        mgr = self._make_manager()
        with patch.object(
            mgr, "staking_state", return_value=StakingState.UNSTAKED
        ), patch.object(mgr, "slots_available", return_value=True):
            mgr.check_staking_compatibility(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )


# ---------------------------------------------------------------------------
# tests for StakingManager.check_if_unstaking_possible
# ---------------------------------------------------------------------------


class TestCheckIfUnstakingPossible:
    """Tests for StakingManager.check_if_unstaking_possible."""

    def _make_manager(self) -> StakingManager:
        """Create a StakingManager for testing."""
        return StakingManager(chain=OperateChain.GNOSIS)

    def _setup_mocks(
        self,
        mgr: StakingManager,
        state: StakingState = StakingState.STAKED,
        ts_start: int = 1000,
        current_ts: int = 9999,
        available_rewards: int = 0,
        min_duration: int = 100,
    ) -> MagicMock:
        """Set up mocks for check_if_unstaking_possible dependencies."""
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.get_block.return_value.timestamp = current_ts

        with patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ):
            pass  # just configure for later use

        mock_staking_ctr = MagicMock()
        mock_staking_ctr.available_rewards.return_value = {"data": available_rewards}
        mock_staking_ctr.get_min_staking_duration.return_value = {"data": min_duration}

        return mock_ledger_api

    def test_raises_when_not_staked_or_evicted(self) -> None:
        """Raises ValueError when service is not STAKED or EVICTED."""
        mgr = self._make_manager()
        with patch.object(mgr, "staking_state", return_value=StakingState.UNSTAKED):
            with pytest.raises(ValueError, match="Service not staked"):
                mgr.check_if_unstaking_possible(
                    service_id=1, staking_contract=_STAKING_CONTRACT
                )

    def test_raises_when_staked_too_short_and_rewards_available(self) -> None:
        """Raises when staking duration is less than minimum and rewards exist."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.get_block.return_value.timestamp = 1100

        mock_staking_ctr_instance = MagicMock()
        mock_staking_ctr_instance.available_rewards.return_value = {"data": 1000}
        mock_staking_ctr_instance.get_min_staking_duration.return_value = {"data": 500}

        with patch.object(
            mgr, "staking_state", return_value=StakingState.STAKED
        ), patch.object(
            mgr, "service_info", return_value=[None, None, None, 1000]
        ), patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch.object(
            type(mgr),
            "staking_ctr",
            new_callable=PropertyMock,
            return_value=mock_staking_ctr_instance,
        ):
            with pytest.raises(ValueError, match="cannot be unstaked yet"):
                mgr.check_if_unstaking_possible(
                    service_id=1, staking_contract=_STAKING_CONTRACT
                )

    def test_passes_when_duration_sufficient(self) -> None:
        """Does not raise when staked long enough."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.get_block.return_value.timestamp = 2000

        mock_staking_ctr_instance = MagicMock()
        mock_staking_ctr_instance.available_rewards.return_value = {"data": 1000}
        mock_staking_ctr_instance.get_min_staking_duration.return_value = {"data": 100}

        with patch.object(
            mgr, "staking_state", return_value=StakingState.STAKED
        ), patch.object(
            mgr, "service_info", return_value=[None, None, None, 1000]
        ), patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch.object(
            type(mgr),
            "staking_ctr",
            new_callable=PropertyMock,
            return_value=mock_staking_ctr_instance,
        ):
            # staked_duration = 2000 - 1000 = 1000 >= min_duration 100 -> ok
            mgr.check_if_unstaking_possible(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

    def test_passes_when_no_rewards_available(self) -> None:
        """Does not raise when rewards == 0, even if staked too short."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.get_block.return_value.timestamp = 1001

        mock_staking_ctr_instance = MagicMock()
        mock_staking_ctr_instance.available_rewards.return_value = {"data": 0}
        mock_staking_ctr_instance.get_min_staking_duration.return_value = {"data": 9999}

        with patch.object(
            mgr, "staking_state", return_value=StakingState.STAKED
        ), patch.object(
            mgr, "service_info", return_value=[None, None, None, 1000]
        ), patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch.object(
            type(mgr),
            "staking_ctr",
            new_callable=PropertyMock,
            return_value=mock_staking_ctr_instance,
        ):
            # available_rewards == 0 -> condition False -> no raise
            mgr.check_if_unstaking_possible(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )


# ---------------------------------------------------------------------------
# tests for StakingManager get_stake/unstake/claim tx data methods
# ---------------------------------------------------------------------------


class TestStakingManagerTxDataMethods:
    """Tests for get_stake_approval_tx_data, get_stake_tx_data, etc."""

    def _make_manager(self) -> StakingManager:
        """Create a StakingManager."""
        return StakingManager(chain=OperateChain.GNOSIS)

    def _mock_staking_ctr(self, mgr: StakingManager) -> MagicMock:
        """Return a mock staking_ctr instance with encode_abi."""
        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = _ENCODED
        mock_ctr = MagicMock()
        mock_ctr.get_instance.return_value = mock_instance
        return mock_ctr

    def test_get_stake_approval_tx_data_calls_check_then_encode(self) -> None:
        """get_stake_approval_tx_data calls check_staking_compatibility and encodes."""
        mgr = self._make_manager()
        mock_erc20_instance = MagicMock()
        mock_erc20_instance.encode_abi.return_value = _ENCODED
        mock_erc20_ctr = MagicMock()
        mock_erc20_ctr.get_instance.return_value = mock_erc20_instance

        with patch.object(mgr, "check_staking_compatibility"), patch(
            "operate.services.protocol.registry_contracts"
        ) as mock_rc:
            mock_rc.erc20.get_instance.return_value = mock_erc20_instance
            result = mgr.get_stake_approval_tx_data(
                service_id=1,
                service_registry=_SERVICE_REGISTRY,
                staking_contract=_STAKING_CONTRACT,
            )

        assert result == _ENCODED
        mock_erc20_instance.encode_abi.assert_called_once()

    def test_get_stake_approval_tx_data_propagates_compatibility_error(self) -> None:
        """get_stake_approval_tx_data propagates ValueError from check."""
        mgr = self._make_manager()
        with patch.object(
            mgr, "check_staking_compatibility", side_effect=ValueError("already staked")
        ):
            with pytest.raises(ValueError, match="already staked"):
                mgr.get_stake_approval_tx_data(
                    service_id=1,
                    service_registry=_SERVICE_REGISTRY,
                    staking_contract=_STAKING_CONTRACT,
                )

    def test_get_stake_tx_data_calls_check_then_encode(self) -> None:
        """get_stake_tx_data calls check_staking_compatibility and encodes."""
        mgr = self._make_manager()
        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = _ENCODED
        mock_ctr = self._mock_staking_ctr(mgr)
        mock_ctr.get_instance.return_value = mock_instance

        with patch.object(mgr, "check_staking_compatibility"), patch.object(
            type(mgr), "staking_ctr", new_callable=PropertyMock, return_value=mock_ctr
        ), patch.object(
            type(mgr), "ledger_api", new_callable=PropertyMock, return_value=MagicMock()
        ):
            result = mgr.get_stake_tx_data(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        assert result == _ENCODED

    def test_get_unstake_tx_data_calls_check_then_encode(self) -> None:
        """get_unstake_tx_data calls check_if_unstaking_possible and encodes."""
        mgr = self._make_manager()
        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = _ENCODED
        mock_ctr = self._mock_staking_ctr(mgr)
        mock_ctr.get_instance.return_value = mock_instance

        with patch.object(mgr, "check_if_unstaking_possible"), patch.object(
            type(mgr), "staking_ctr", new_callable=PropertyMock, return_value=mock_ctr
        ), patch.object(
            type(mgr), "ledger_api", new_callable=PropertyMock, return_value=MagicMock()
        ):
            result = mgr.get_unstake_tx_data(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        assert result == _ENCODED

    def test_get_claim_tx_data_encodes(self) -> None:
        """get_claim_tx_data encodes the claim call."""
        mgr = self._make_manager()
        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = _ENCODED
        mock_ctr = MagicMock()
        mock_ctr.get_instance.return_value = mock_instance

        with patch.object(
            type(mgr), "staking_ctr", new_callable=PropertyMock, return_value=mock_ctr
        ), patch.object(
            type(mgr), "ledger_api", new_callable=PropertyMock, return_value=MagicMock()
        ):
            result = mgr.get_claim_tx_data(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        assert result == _ENCODED
        mock_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="claim", args=[1]
        )

    def test_get_forced_unstake_tx_data_encodes(self) -> None:
        """get_forced_unstake_tx_data encodes the forcedUnstake call."""
        mgr = self._make_manager()
        mock_instance = MagicMock()
        mock_instance.encode_abi.return_value = _ENCODED
        mock_ctr = MagicMock()
        mock_ctr.get_instance.return_value = mock_instance

        with patch.object(
            type(mgr), "staking_ctr", new_callable=PropertyMock, return_value=mock_ctr
        ), patch.object(
            type(mgr), "ledger_api", new_callable=PropertyMock, return_value=MagicMock()
        ):
            result = mgr.get_forced_unstake_tx_data(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        assert result == _ENCODED
        mock_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="forcedUnstake", args=[1]
        )


# ---------------------------------------------------------------------------
# tests for StakingManager.get_current_staking_program
# ---------------------------------------------------------------------------


class TestGetCurrentStakingProgram:
    """Tests for StakingManager.get_current_staking_program."""

    def _make_manager(self) -> StakingManager:
        """Create a StakingManager for GNOSIS."""
        return StakingManager(chain=OperateChain.GNOSIS)

    def test_returns_none_for_non_existent_token(self) -> None:
        """Returns None when service_id equals NON_EXISTENT_TOKEN."""
        mgr = self._make_manager()
        result = mgr.get_current_staking_program(service_id=NON_EXISTENT_TOKEN)
        assert result is None

    def test_returns_none_when_staking_state_raises(self) -> None:
        """Returns None when staking_state raises (service owner not a staking contract)."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_sr_instance = MagicMock()
        mock_sr_instance.functions.ownerOf.return_value.call.return_value = "0xOwner"

        with patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.registry_contracts") as mock_rc, patch(
            "operate.services.protocol.CONTRACTS",
            {OperateChain.GNOSIS: {"service_registry": "0xSR"}},
        ), patch.object(
            mgr, "staking_state", side_effect=Exception("not staking")
        ):
            mock_rc.service_registry.get_instance.return_value = mock_sr_instance
            result = mgr.get_current_staking_program(service_id=1)

        assert result is None

    def test_returns_none_when_unstaked(self) -> None:
        """Returns None when staking state is UNSTAKED."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_sr_instance = MagicMock()
        mock_sr_instance.functions.ownerOf.return_value.call.return_value = "0xOwner"

        with patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.registry_contracts") as mock_rc, patch(
            "operate.services.protocol.CONTRACTS",
            {OperateChain.GNOSIS: {"service_registry": "0xSR"}},
        ), patch.object(
            mgr, "staking_state", return_value=StakingState.UNSTAKED
        ):
            mock_rc.service_registry.get_instance.return_value = mock_sr_instance
            result = mgr.get_current_staking_program(service_id=1)

        assert result is None

    def test_returns_program_id_when_owner_matches_staking_dict(self) -> None:
        """Returns matching staking program ID when service owner is in STAKING dict."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_sr_instance = MagicMock()
        mock_sr_instance.functions.ownerOf.return_value.call.return_value = "0xProgram1"

        staking = {OperateChain.GNOSIS: {"my_program": "0xProgram1"}}

        with patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.registry_contracts") as mock_rc, patch(
            "operate.services.protocol.CONTRACTS",
            {OperateChain.GNOSIS: {"service_registry": "0xSR"}},
        ), patch(
            "operate.services.protocol.STAKING", staking
        ), patch.object(
            mgr, "staking_state", return_value=StakingState.STAKED
        ):
            mock_rc.service_registry.get_instance.return_value = mock_sr_instance
            result = mgr.get_current_staking_program(service_id=1)

        assert result == "my_program"

    def test_fallback_loop_finds_staked_program(self) -> None:
        """Fallback loop returns the staking program when inner contract is STAKED."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_sr_instance = MagicMock()
        # Owner is NOT directly in STAKING keys
        mock_sr_instance.functions.ownerOf.return_value.call.return_value = "0xInner"

        staking = {OperateChain.GNOSIS: {"outer_program": "0xOuter"}}

        call_count = [0]

        def _staking_state(service_id: int, staking_contract: str) -> StakingState:
            call_count[0] += 1
            if staking_contract == "0xInner":
                return StakingState.STAKED  # First call: service_owner check
            return StakingState.STAKED  # Fallback call

        with patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.registry_contracts") as mock_rc, patch(
            "operate.services.protocol.CONTRACTS",
            {OperateChain.GNOSIS: {"service_registry": "0xSR"}},
        ), patch(
            "operate.services.protocol.STAKING", staking
        ), patch.object(
            mgr, "staking_state", side_effect=_staking_state
        ):
            mock_rc.service_registry.get_instance.return_value = mock_sr_instance
            result = mgr.get_current_staking_program(service_id=1)

        # Outer_program maps to 0xOuter != 0xInner, so falls to fallback loop
        # Fallback: staking_state(1, "0xOuter") returns STAKED -> "outer_program"
        assert result == "outer_program"

    def test_returns_service_owner_when_no_match_in_staking(self) -> None:
        """Returns service_owner as fallback when no known staking program matches."""
        mgr = self._make_manager()
        mock_ledger_api = MagicMock()
        mock_sr_instance = MagicMock()
        mock_sr_instance.functions.ownerOf.return_value.call.return_value = "0xUnknown"

        staking = {OperateChain.GNOSIS: {"prog": "0xKnown"}}

        def _staking_state(service_id: int, staking_contract: str) -> StakingState:
            if staking_contract == "0xUnknown":
                return StakingState.STAKED
            return StakingState.UNSTAKED  # fallback loop: prog -> 0xKnown -> UNSTAKED

        with patch.object(
            type(mgr),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.registry_contracts") as mock_rc, patch(
            "operate.services.protocol.CONTRACTS",
            {OperateChain.GNOSIS: {"service_registry": "0xSR"}},
        ), patch(
            "operate.services.protocol.STAKING", staking
        ), patch.object(
            mgr, "staking_state", side_effect=_staking_state
        ):
            mock_rc.service_registry.get_instance.return_value = mock_sr_instance
            result = mgr.get_current_staking_program(service_id=1)

        assert result == "0xUnknown"


# ---------------------------------------------------------------------------
# tests for _ChainUtil._patch
# ---------------------------------------------------------------------------


class TestChainUtilPatch:
    """Tests for _ChainUtil._patch."""

    def test_patch_updates_chain_config_rpc(self) -> None:
        """_patch sets ChainConfigs rpc to self.rpc."""
        cu = _make_chain_util(contracts={"service_manager": "0xSM"})
        mock_chain_cfg = MagicMock()
        mock_contract_cfg = MagicMock()
        mock_contract_cfg.contracts = {}

        with patch("operate.services.protocol.ChainConfigs") as mock_cc, patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_ccc:
            mock_cc.get.return_value = mock_chain_cfg
            mock_ccc.get.return_value = mock_contract_cfg
            cu._patch()

        mock_cc.get.assert_called_once_with(cu.chain_type)
        assert mock_chain_cfg.rpc == cu.rpc

    def test_patch_updates_contract_configs(self) -> None:
        """_patch updates ContractConfigs for each contract."""
        contracts = {"service_manager": "0xSM", "multisend": "0xMS"}
        cu = _make_chain_util(contracts=contracts)
        mock_chain_cfg = MagicMock()

        contract_cfg_map: t.Dict[str, MagicMock] = {}

        def _get_contract(name: str) -> MagicMock:
            if name not in contract_cfg_map:
                m = MagicMock()
                m.contracts = {}
                contract_cfg_map[name] = m
            return contract_cfg_map[name]

        with patch("operate.services.protocol.ChainConfigs") as mock_cc, patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_ccc:
            mock_cc.get.return_value = mock_chain_cfg
            mock_ccc.get.side_effect = _get_contract
            cu._patch()

        assert contract_cfg_map["service_manager"].contracts[cu.chain_type] == "0xSM"
        assert contract_cfg_map["multisend"].contracts[cu.chain_type] == "0xMS"


# ---------------------------------------------------------------------------
# tests for _ChainUtil.safe property
# ---------------------------------------------------------------------------


class TestChainUtilSafe:
    """Tests for _ChainUtil.safe property."""

    def test_safe_returns_address_for_matching_chain(self) -> None:
        """Returns safe address when chain matches wallet.safes."""
        mock_wallet = MagicMock()
        mock_chain = MagicMock()
        mock_wallet.safes = {mock_chain: _SAFE_ADDRESS}

        cu = _ChainUtil(
            rpc="http://rpc",
            wallet=mock_wallet,
            contracts={},
            chain_type=ChainType.GNOSIS,
        )
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.chain_id = 100

        with patch.object(
            type(cu),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.OperateChain") as mock_oc:
            mock_oc.from_id.return_value = mock_chain
            result = cu.safe

        assert result == _SAFE_ADDRESS

    def test_safe_raises_when_safes_none(self) -> None:
        """Raises ValueError when wallet.safes is None."""
        mock_wallet = MagicMock()
        mock_wallet.safes = None

        cu = _ChainUtil(
            rpc="http://rpc",
            wallet=mock_wallet,
            contracts={},
            chain_type=ChainType.GNOSIS,
        )
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.chain_id = 100

        with patch.object(
            type(cu),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.OperateChain"):
            with pytest.raises(ValueError, match="Safes not initialized"):
                cu.safe  # pylint: disable=pointless-statement

    def test_safe_raises_when_chain_not_in_safes(self) -> None:
        """Raises ValueError when wallet.safes does not contain the chain."""
        mock_wallet = MagicMock()
        mock_chain = MagicMock()
        mock_wallet.safes = {}  # chain not in safes

        cu = _ChainUtil(
            rpc="http://rpc",
            wallet=mock_wallet,
            contracts={},
            chain_type=ChainType.GNOSIS,
        )
        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.chain_id = 100

        with patch.object(
            type(cu),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=mock_ledger_api,
        ), patch("operate.services.protocol.OperateChain") as mock_oc:
            mock_oc.from_id.return_value = mock_chain
            with pytest.raises(ValueError, match="Safe for chain type"):
                cu.safe  # pylint: disable=pointless-statement


# ---------------------------------------------------------------------------
# tests for _ChainUtil.service_manager_address cached property
# ---------------------------------------------------------------------------


class TestChainUtilServiceManagerAddress:
    """Tests for _ChainUtil.service_manager_address."""

    def test_service_manager_address_returns_config_value(self) -> None:
        """service_manager_address reads from ContractConfigs."""
        cu = _make_chain_util()
        mock_cc = MagicMock()
        mock_cc.service_manager.contracts = {cu.chain_type: "0xServiceMgr"}

        with patch("operate.services.protocol.ContractConfigs", mock_cc):
            result = cu.service_manager_address

        assert result == "0xServiceMgr"


# ---------------------------------------------------------------------------
# tests for _ChainUtil staking delegation methods
# ---------------------------------------------------------------------------


class TestChainUtilStakingMethods:
    """Tests for _ChainUtil staking delegation methods."""

    def test_staking_slots_available_delegates_and_returns_true(self) -> None:
        """staking_slots_available patches and delegates to StakingManager."""
        cu = _make_chain_util()
        mock_sm = MagicMock()
        mock_sm.slots_available.return_value = True

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = cu.staking_slots_available(_STAKING_CONTRACT)

        assert result is True

    def test_staking_rewards_available_true_when_rewards_nonzero(self) -> None:
        """staking_rewards_available returns True when available_rewards > 0."""
        cu = _make_chain_util()
        mock_sm = MagicMock()
        mock_sm.available_rewards.return_value = 500

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = cu.staking_rewards_available(_STAKING_CONTRACT)

        assert result is True

    def test_staking_rewards_available_false_when_zero(self) -> None:
        """staking_rewards_available returns False when available_rewards == 0."""
        cu = _make_chain_util()
        mock_sm = MagicMock()
        mock_sm.available_rewards.return_value = 0

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = cu.staking_rewards_available(_STAKING_CONTRACT)

        assert result is False

    def test_staking_rewards_claimable_true_when_nonzero(self) -> None:
        """staking_rewards_claimable returns True when claimable_rewards > 0."""
        cu = _make_chain_util()
        mock_sm = MagicMock()
        mock_sm.claimable_rewards.return_value = 100

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = cu.staking_rewards_claimable(_STAKING_CONTRACT, service_id=1)

        assert result is True

    def test_staking_rewards_claimable_false_when_zero(self) -> None:
        """staking_rewards_claimable returns False when claimable_rewards == 0."""
        cu = _make_chain_util()
        mock_sm = MagicMock()
        mock_sm.claimable_rewards.return_value = 0

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = cu.staking_rewards_claimable(_STAKING_CONTRACT, service_id=1)

        assert result is False

    def test_staking_status_delegates_to_staking_manager(self) -> None:
        """staking_status patches and delegates to StakingManager.staking_state."""
        cu = _make_chain_util()
        mock_sm = MagicMock()
        mock_sm.staking_state.return_value = StakingState.STAKED

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = cu.staking_status(service_id=1, staking_contract=_STAKING_CONTRACT)

        assert result == StakingState.STAKED

    def test_get_staking_params_returns_fallback_when_no_contract(self) -> None:
        """get_staking_params returns fallback_params when staking_contract is None."""
        cu = _make_chain_util()
        fallback = {"agent_ids": [1], "min_staking_deposit": 1000}
        result = cu.get_staking_params(staking_contract=None, fallback_params=fallback)
        assert result == fallback

    def test_get_staking_params_calls_staking_manager_when_contract_given(self) -> None:
        """get_staking_params delegates to StakingManager when contract is provided."""
        cu = _make_chain_util()
        mock_sm = MagicMock()
        mock_sm.get_staking_params.return_value = {
            "staking_contract": _STAKING_CONTRACT
        }

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = cu.get_staking_params(staking_contract=_STAKING_CONTRACT)

        assert result["staking_contract"] == _STAKING_CONTRACT

    def test_get_agent_bond_returns_zero_for_nonpositive_ids(self) -> None:
        """get_agent_bond returns 0 when service_id or agent_id <= 0."""
        cu = _make_chain_util()
        with patch.object(cu, "_patch"):
            assert cu.get_agent_bond(service_id=0, agent_id=1) == 0
            assert cu.get_agent_bond(service_id=1, agent_id=0) == 0
            assert cu.get_agent_bond(service_id=-1, agent_id=-1) == 0

    def test_get_agent_bond_calls_external_functions_for_positive_ids(self) -> None:
        """get_agent_bond calls OnChainHelper and get_token_deposit_amount for valid IDs."""
        cu = _make_chain_util()
        mock_ledger_api = MagicMock()

        with patch.object(cu, "_patch"), patch(
            "operate.services.protocol.OnChainHelper"
        ) as mock_och, patch(
            "operate.services.protocol.get_token_deposit_amount", return_value=5000
        ):
            mock_och.get_ledger_and_crypto_objects.return_value = (
                mock_ledger_api,
                MagicMock(),
            )
            result = cu.get_agent_bond(service_id=1, agent_id=2)

        assert result == 5000


# ---------------------------------------------------------------------------
# tests for EthSafeTxBuilder._new_tx and new_tx
# ---------------------------------------------------------------------------


class TestEthSafeTxBuilderNewTx:
    """Tests for EthSafeTxBuilder._new_tx and new_tx."""

    def test_new_tx_classmethod_creates_gnosis_safe_transaction(self) -> None:
        """_new_tx classmethod creates a GnosisSafeTransaction."""
        mock_ledger_api = MagicMock()
        mock_crypto = MagicMock()

        tx = EthSafeTxBuilder._new_tx(
            ledger_api=mock_ledger_api,
            crypto=mock_crypto,
            chain_type=ChainType.GNOSIS,
            safe=_SAFE_ADDRESS,
        )

        assert isinstance(tx, GnosisSafeTransaction)
        assert tx.ledger_api is mock_ledger_api
        assert tx.crypto is mock_crypto
        assert tx.safe == _SAFE_ADDRESS

    def test_new_tx_uses_provided_crypto_and_safe(self) -> None:
        """new_tx passes provided crypto and safe to _new_tx."""
        builder = _make_eth_safe_tx_builder()
        mock_crypto = MagicMock()

        with patch(
            "operate.services.protocol.EthSafeTxBuilder._new_tx"
        ) as mock_inner, patch("operate.services.protocol.OperateChain"):
            mock_inner.return_value = MagicMock(spec=GnosisSafeTransaction)
            builder.new_tx(crypto=mock_crypto, safe=_SAFE_ADDRESS)

        assert mock_inner.called
        call_kwargs = mock_inner.call_args.kwargs
        assert call_kwargs["crypto"] is mock_crypto
        assert call_kwargs["safe"] == _SAFE_ADDRESS

    def test_new_tx_falls_back_to_self_crypto_when_not_provided(self) -> None:
        """new_tx uses self.crypto when crypto argument is None."""
        builder = _make_eth_safe_tx_builder()
        mock_self_crypto = MagicMock()

        with patch(
            "operate.services.protocol.EthSafeTxBuilder._new_tx"
        ) as mock_inner, patch.object(
            type(builder),
            "crypto",
            new_callable=PropertyMock,
            return_value=mock_self_crypto,
        ), patch(
            "operate.services.protocol.OperateChain"
        ):
            mock_inner.return_value = MagicMock(spec=GnosisSafeTransaction)
            builder.new_tx(safe=_SAFE_ADDRESS)

        call_kwargs = mock_inner.call_args.kwargs
        assert call_kwargs["crypto"] is mock_self_crypto


# ---------------------------------------------------------------------------
# tests for EthSafeTxBuilder.get_deploy_data_from_safe
# ---------------------------------------------------------------------------


class TestGetDeployDataFromSafe:
    """Tests for EthSafeTxBuilder.get_deploy_data_from_safe."""

    def _setup_builder_mocks(
        self, builder: EthSafeTxBuilder
    ) -> t.Tuple[MagicMock, MagicMock]:
        """Patch _patch, service_manager_instance, service_manager_address."""
        mock_smi = MagicMock()
        mock_smi.encode_abi.return_value = _ENCODED
        return mock_smi, MagicMock()

    def test_new_multisig_no_recovery_no_poly(self) -> None:
        """Default path: deploys new multisig without recovery module or poly safe."""
        builder = _make_eth_safe_tx_builder()
        mock_smi = MagicMock()
        mock_smi.encode_abi.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=mock_smi,
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ), patch(
            "operate.services.protocol.get_deployment_payload", return_value="payload"
        ), patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_cc:
            mock_cc.get.return_value.contracts = {builder.chain_type: "0xGSPF"}
            result = builder.get_deploy_data_from_safe(
                service_id=1,
                master_safe=_MASTER_SAFE,
                reuse_multisig=False,
                use_recovery_module=False,
                use_poly_safe=False,
            )

        assert len(result) == 1
        assert result[0]["to"] == "0xSM"

    def test_new_multisig_with_recovery_no_poly(self) -> None:
        """Deploys new multisig with recovery module but no poly safe."""
        builder = _make_eth_safe_tx_builder()
        mock_smi = MagicMock()
        mock_smi.encode_abi.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=mock_smi,
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ), patch(
            "operate.services.protocol.get_deployment_with_recovery_payload",
            return_value="payload_recovery",
        ), patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_cc:
            mock_cc.get.return_value.contracts = {builder.chain_type: "0xSMRM"}
            result = builder.get_deploy_data_from_safe(
                service_id=1,
                master_safe=_MASTER_SAFE,
                reuse_multisig=False,
                use_recovery_module=True,
                use_poly_safe=False,
            )

        assert len(result) == 1

    def test_new_poly_safe_raises_when_no_crypto(self) -> None:
        """Raises ValueError when poly safe requested but no agent_eoa_crypto."""
        builder = _make_eth_safe_tx_builder()

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ):
            with pytest.raises(ValueError, match="Crypto object must be provided"):
                builder.get_deploy_data_from_safe(
                    service_id=1,
                    master_safe=_MASTER_SAFE,
                    reuse_multisig=False,
                    use_recovery_module=True,
                    use_poly_safe=True,
                    agent_eoa_crypto=None,
                )

    def test_new_poly_safe_raises_without_recovery(self) -> None:
        """Raises ValueError when poly safe without recovery module."""
        builder = _make_eth_safe_tx_builder()

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ):
            with pytest.raises(
                ValueError, match="without recovery module is not supported"
            ):
                builder.get_deploy_data_from_safe(
                    service_id=1,
                    master_safe=_MASTER_SAFE,
                    reuse_multisig=False,
                    use_recovery_module=False,
                    use_poly_safe=True,
                )

    def test_new_poly_safe_with_recovery_and_crypto(self) -> None:
        """Deploys poly safe when recovery=True, poly=True, crypto provided."""
        builder = _make_eth_safe_tx_builder()
        mock_smi = MagicMock()
        mock_smi.encode_abi.return_value = _ENCODED
        mock_crypto = MagicMock()

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=mock_smi,
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ), patch.object(
            type(builder),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch(
            "operate.services.protocol.get_poly_safe_deployment_payload",
            return_value="poly_payload",
        ), patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_cc:
            mock_cc.get.return_value.contracts = {builder.chain_type: "0xPolySafe"}
            result = builder.get_deploy_data_from_safe(
                service_id=1,
                master_safe=_MASTER_SAFE,
                reuse_multisig=False,
                use_recovery_module=True,
                use_poly_safe=True,
                agent_eoa_crypto=mock_crypto,
            )

        assert len(result) == 1

    def test_reuse_multisig_without_recovery_returns_two_messages(self) -> None:
        """Reuse multisig path without recovery returns [approve_hash, deploy] messages."""
        builder = _make_eth_safe_tx_builder()
        mock_smi = MagicMock()
        mock_smi.encode_abi.return_value = _ENCODED
        approve_hash_msg = {
            "to": "0xMultisig",
            "data": "aaaa",
            "operation": 0,
            "value": 0,
        }

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=mock_smi,
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ), patch.object(
            type(builder),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch(
            "operate.services.protocol.get_reuse_multisig_from_safe_payload",
            return_value=("some_payload", approve_hash_msg, None),
        ), patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_cc:
            mock_cc.get.return_value.contracts = {builder.chain_type: "0xGSSAM"}
            result = builder.get_deploy_data_from_safe(
                service_id=1,
                master_safe=_MASTER_SAFE,
                reuse_multisig=True,
                use_recovery_module=False,
            )

        assert len(result) == 2
        assert result[0] is approve_hash_msg

    def test_reuse_multisig_raises_when_payload_none(self) -> None:
        """Raises ValueError when get_reuse_multisig_from_safe_payload returns None payload."""
        builder = _make_eth_safe_tx_builder()

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ), patch.object(
            type(builder),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch(
            "operate.services.protocol.get_reuse_multisig_from_safe_payload",
            return_value=(None, None, "No previous deployment"),
        ), patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_cc:
            mock_cc.get.return_value.contracts = {builder.chain_type: "0xGSSAM"}
            with pytest.raises(ValueError, match="No previous deployment"):
                builder.get_deploy_data_from_safe(
                    service_id=1,
                    master_safe=_MASTER_SAFE,
                    reuse_multisig=True,
                    use_recovery_module=False,
                )

    def test_reuse_multisig_with_recovery(self) -> None:
        """Reuse multisig path with recovery module returns one message."""
        builder = _make_eth_safe_tx_builder()
        mock_smi = MagicMock()
        mock_smi.encode_abi.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=mock_smi,
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ), patch.object(
            type(builder),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch(
            "operate.services.protocol.get_reuse_multisig_with_recovery_from_safe_payload",
            return_value=("recovery_payload", None),
        ), patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_cc:
            mock_cc.get.return_value.contracts = {builder.chain_type: "0xRM"}
            result = builder.get_deploy_data_from_safe(
                service_id=1,
                master_safe=_MASTER_SAFE,
                reuse_multisig=True,
                use_recovery_module=True,
            )

        assert len(result) == 1

    def test_reuse_multisig_with_recovery_raises_when_payload_none(self) -> None:
        """Raises ValueError when recovery payload is None."""
        builder = _make_eth_safe_tx_builder()

        with patch.object(builder, "_patch"), patch.object(
            type(builder),
            "service_manager_instance",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch.object(
            type(builder),
            "service_manager_address",
            new_callable=PropertyMock,
            return_value="0xSM",
        ), patch.object(
            type(builder),
            "ledger_api",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch(
            "operate.services.protocol.get_reuse_multisig_with_recovery_from_safe_payload",
            return_value=(None, "not terminated"),
        ), patch(
            "operate.services.protocol.ContractConfigs"
        ) as mock_cc:
            mock_cc.get.return_value.contracts = {builder.chain_type: "0xRM"}
            with pytest.raises(ValueError, match="not terminated"):
                builder.get_deploy_data_from_safe(
                    service_id=1,
                    master_safe=_MASTER_SAFE,
                    reuse_multisig=True,
                    use_recovery_module=True,
                )


# ---------------------------------------------------------------------------
# tests for EthSafeTxBuilder staking data methods
# ---------------------------------------------------------------------------


class TestEthSafeTxBuilderStakingDataMethods:
    """Tests for EthSafeTxBuilder staking approval, staking, unstaking, claiming."""

    def _builder(self) -> EthSafeTxBuilder:
        """Create an EthSafeTxBuilder."""
        return _make_eth_safe_tx_builder()

    def _mock_safe(self, builder: EthSafeTxBuilder) -> MagicMock:
        """Return a PropertyMock for safe."""
        return PropertyMock(return_value=_SAFE_ADDRESS)

    def test_get_staking_approval_data_delegates_to_staking_manager(self) -> None:
        """get_staking_approval_data calls StakingManager and returns dict."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.get_stake_approval_tx_data.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch.object(
            type(builder), "safe", new_callable=PropertyMock, return_value=_SAFE_ADDRESS
        ), patch("operate.services.protocol.StakingManager", return_value=mock_sm):
            result = builder.get_staking_approval_data(
                service_id=1,
                service_registry=_SERVICE_REGISTRY,
                staking_contract=_STAKING_CONTRACT,
            )

        assert result["to"] == _CONTRACTS["service_registry"]
        assert result["from"] == _SAFE_ADDRESS

    def test_get_staking_data_delegates_to_staking_manager(self) -> None:
        """get_staking_data calls StakingManager and returns dict."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.get_stake_tx_data.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = builder.get_staking_data(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        assert result["to"] == _STAKING_CONTRACT

    def test_get_unstaking_data_normal_path(self) -> None:
        """get_unstaking_data calls get_unstake_tx_data when force=False."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.get_unstake_tx_data.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = builder.get_unstaking_data(
                service_id=1, staking_contract=_STAKING_CONTRACT, force=False
            )

        mock_sm.get_unstake_tx_data.assert_called_once()
        mock_sm.get_forced_unstake_tx_data.assert_not_called()
        assert result["to"] == _STAKING_CONTRACT

    def test_get_unstaking_data_force_path(self) -> None:
        """get_unstaking_data calls get_forced_unstake_tx_data when force=True."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.get_forced_unstake_tx_data.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = builder.get_unstaking_data(
                service_id=1, staking_contract=_STAKING_CONTRACT, force=True
            )

        mock_sm.get_forced_unstake_tx_data.assert_called_once()
        mock_sm.get_unstake_tx_data.assert_not_called()
        assert result["to"] == _STAKING_CONTRACT

    def test_get_claiming_data_delegates_to_staking_manager(self) -> None:
        """get_claiming_data calls get_claim_tx_data and returns dict."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.get_claim_tx_data.return_value = _ENCODED

        with patch.object(builder, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = builder.get_claiming_data(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        mock_sm.get_claim_tx_data.assert_called_once()
        assert result["to"] == _STAKING_CONTRACT

    def test_staking_slots_available_delegates(self) -> None:
        """staking_slots_available patches and delegates to StakingManager."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.slots_available.return_value = False

        with patch.object(builder, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = builder.staking_slots_available(_STAKING_CONTRACT)

        assert result is False

    def test_can_unstake_returns_true_when_check_passes(self) -> None:
        """can_unstake returns True when check_if_unstaking_possible succeeds."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.check_if_unstaking_possible.return_value = None  # no exception

        with patch.object(builder, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = builder.can_unstake(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        assert result is True

    def test_can_unstake_returns_false_when_check_raises_value_error(self) -> None:
        """can_unstake returns False when check_if_unstaking_possible raises ValueError."""
        builder = self._builder()
        mock_sm = MagicMock()
        mock_sm.check_if_unstaking_possible.side_effect = ValueError("not ready")

        with patch.object(builder, "_patch"), patch(
            "operate.services.protocol.StakingManager", return_value=mock_sm
        ):
            result = builder.can_unstake(
                service_id=1, staking_contract=_STAKING_CONTRACT
            )

        assert result is False
