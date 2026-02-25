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

"""Unit tests for operate/services/funding_manager.py – no blockchain required."""

from unittest.mock import MagicMock, patch

import pytest

from operate.constants import (
    MASTER_EOA_PLACEHOLDER,
    MASTER_SAFE_PLACEHOLDER,
    ZERO_ADDRESS,
)
from operate.ledger.profiles import DEFAULT_EOA_TOPUPS
from operate.operate_types import Chain, ChainAmounts
from operate.serialization import BigInt
from operate.services.funding_manager import FundingInProgressError, FundingManager
from operate.wallet.master import InsufficientFundsException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EOA_ADDR = "0x" + "a" * 40
SAFE_ADDR = "0x" + "b" * 40
BACKUP_ADDR = "0x" + "c" * 40
ERC20_TOKEN = "0x" + "d" * 40

# GNOSIS native topup; used to derive the "critical" threshold
_GNOSIS_NATIVE_TOPUP = int(DEFAULT_EOA_TOPUPS[Chain.GNOSIS][ZERO_ADDRESS])
_GNOSIS_CRITICAL_THRESHOLD = int(_GNOSIS_NATIVE_TOPUP / 4)


def _make_manager(
    wallet_manager: MagicMock = None,  # type: ignore[assignment]
    cooldown: int = 5,
) -> FundingManager:
    """Create a FundingManager with all external deps mocked."""
    return FundingManager(
        keys_manager=MagicMock(),
        wallet_manager=wallet_manager or MagicMock(),
        logger=MagicMock(),
        funding_requests_cooldown_seconds=cooldown,
    )


# ---------------------------------------------------------------------------
# FundingInProgressError
# ---------------------------------------------------------------------------


class TestFundingInProgressError:
    """Tests for the FundingInProgressError exception class."""

    def test_is_runtime_error(self) -> None:
        """Test that FundingInProgressError is a RuntimeError subclass."""
        assert issubclass(FundingInProgressError, RuntimeError)

    def test_can_be_raised_and_caught(self) -> None:
        """Test that FundingInProgressError can be raised and caught."""
        with pytest.raises(FundingInProgressError, match="already in progress"):
            raise FundingInProgressError("already in progress")


# ---------------------------------------------------------------------------
# FundingManager.__init__
# ---------------------------------------------------------------------------


class TestFundingManagerInit:
    """Tests for FundingManager.__init__ (lines 94-101)."""

    def test_default_attributes_are_set(self) -> None:
        """Test that __init__ sets all expected attributes with correct defaults."""
        manager = _make_manager()
        assert manager.funding_requests_cooldown_seconds == 5
        assert manager._funding_in_progress == {}
        assert manager._funding_requests_cooldown_until == {}
        assert manager.is_for_quickstart is False

    def test_custom_cooldown_is_stored(self) -> None:
        """Test that a custom cooldown value is stored."""
        manager = _make_manager(cooldown=120)
        assert manager.funding_requests_cooldown_seconds == 120


# ---------------------------------------------------------------------------
# compute shortfalls (static method)
# ---------------------------------------------------------------------------


class TestComputeShortfalls:
    """Tests for FundingManager._compute_shortfalls (lines 500-521)."""

    def test_balance_below_threshold_uses_topup(self) -> None:
        """Test shortfall = topup - balance when balance < threshold."""
        balances = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(100)}}})
        thresholds = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(200)}}})
        topups = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(300)}}})
        result = FundingManager._compute_shortfalls(balances, thresholds, topups)
        # balance 100 < threshold 200 → shortfall = max(300 - 100, 0) = 200
        assert result["gnosis"]["0xAddr1"][ZERO_ADDRESS] == BigInt(200)

    def test_balance_equals_threshold_is_zero(self) -> None:
        """Test shortfall is 0 when balance exactly meets threshold."""
        balances = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(200)}}})
        thresholds = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(200)}}})
        topups = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(300)}}})
        result = FundingManager._compute_shortfalls(balances, thresholds, topups)
        assert result["gnosis"]["0xAddr1"][ZERO_ADDRESS] == BigInt(0)

    def test_balance_above_threshold_is_zero(self) -> None:
        """Test shortfall is 0 when balance exceeds threshold."""
        balances = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(500)}}})
        thresholds = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(200)}}})
        topups = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(300)}}})
        result = FundingManager._compute_shortfalls(balances, thresholds, topups)
        assert result["gnosis"]["0xAddr1"][ZERO_ADDRESS] == BigInt(0)

    def test_topup_less_than_balance_gives_zero(self) -> None:
        """Test that max(topup - balance, 0) clamps to 0 when topup <= balance."""
        # balance < threshold so we enter the shortfall branch, but topup < balance
        balances = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(50)}}})
        thresholds = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(100)}}})
        topups = ChainAmounts({"gnosis": {"0xAddr1": {ZERO_ADDRESS: BigInt(30)}}})
        result = FundingManager._compute_shortfalls(balances, thresholds, topups)
        # max(30 - 50, 0) = 0
        assert result["gnosis"]["0xAddr1"][ZERO_ADDRESS] == BigInt(0)

    def test_multiple_chains_and_assets(self) -> None:
        """Test shortfalls across multiple chains and addresses."""
        balances = ChainAmounts(
            {
                "gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}},
                "base": {SAFE_ADDR: {ERC20_TOKEN: BigInt(0)}},
            }
        )
        thresholds = ChainAmounts(
            {
                "gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(500)}},
                "base": {SAFE_ADDR: {ERC20_TOKEN: BigInt(200)}},
            }
        )
        topups = ChainAmounts(
            {
                "gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(600)}},
                "base": {SAFE_ADDR: {ERC20_TOKEN: BigInt(250)}},
            }
        )
        result = FundingManager._compute_shortfalls(balances, thresholds, topups)
        assert result["gnosis"][EOA_ADDR][ZERO_ADDRESS] == BigInt(500)  # 600-100
        assert result["base"][SAFE_ADDR][ERC20_TOKEN] == BigInt(250)  # 250-0

    def test_empty_inputs_return_empty(self) -> None:
        """Test that empty inputs return an empty ChainAmounts."""
        result = FundingManager._compute_shortfalls(
            ChainAmounts(), ChainAmounts(), ChainAmounts()
        )
        assert result == ChainAmounts()


# ---------------------------------------------------------------------------
# split critical EOA shortfalls (static method)
# ---------------------------------------------------------------------------


class TestSplitCriticalEoaShortfalls:
    """Tests for FundingManager._split_critical_eoa_shortfalls (lines 583-614)."""

    def test_critical_native_shortfall_when_balance_very_low(self) -> None:
        """Test that a native balance well below threshold/4 is marked critical."""
        low_balance = BigInt(_GNOSIS_CRITICAL_THRESHOLD - 1)  # just under threshold
        shortfall_amount = BigInt(1_000_000_000_000_000)
        balances = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: low_balance}}})
        shortfalls = ChainAmounts(
            {"gnosis": {EOA_ADDR: {ZERO_ADDRESS: shortfall_amount}}}
        )
        critical, remaining = FundingManager._split_critical_eoa_shortfalls(
            balances, shortfalls
        )
        assert critical["gnosis"][EOA_ADDR][ZERO_ADDRESS] == shortfall_amount
        assert remaining["gnosis"][EOA_ADDR][ZERO_ADDRESS] == BigInt(0)

    def test_non_critical_native_shortfall_when_balance_above_threshold_quarter(
        self,
    ) -> None:
        """Test that a native balance above threshold/4 is NOT marked critical."""
        high_balance = BigInt(_GNOSIS_CRITICAL_THRESHOLD + 1)  # just above threshold
        shortfall_amount = BigInt(1_000_000_000_000_000)
        balances = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: high_balance}}})
        shortfalls = ChainAmounts(
            {"gnosis": {EOA_ADDR: {ZERO_ADDRESS: shortfall_amount}}}
        )
        critical, remaining = FundingManager._split_critical_eoa_shortfalls(
            balances, shortfalls
        )
        assert critical["gnosis"][EOA_ADDR][ZERO_ADDRESS] == BigInt(0)
        assert remaining["gnosis"][EOA_ADDR][ZERO_ADDRESS] == shortfall_amount

    def test_erc20_asset_always_goes_to_remaining(self) -> None:
        """Test that ERC20 shortfalls (non-native) always go to remaining, not critical."""
        balances = ChainAmounts({"gnosis": {EOA_ADDR: {ERC20_TOKEN: BigInt(0)}}})
        shortfalls = ChainAmounts({"gnosis": {EOA_ADDR: {ERC20_TOKEN: BigInt(500)}}})
        critical, remaining = FundingManager._split_critical_eoa_shortfalls(
            balances, shortfalls
        )
        # ERC20 is not ZERO_ADDRESS, so always goes to remaining
        assert critical["gnosis"][EOA_ADDR][ERC20_TOKEN] == BigInt(0)
        assert remaining["gnosis"][EOA_ADDR][ERC20_TOKEN] == BigInt(500)

    def test_empty_shortfalls_returns_empty_dicts(self) -> None:
        """Test that empty shortfalls returns empty dicts."""
        critical, remaining = FundingManager._split_critical_eoa_shortfalls(
            ChainAmounts(), ChainAmounts()
        )
        assert critical == ChainAmounts()
        assert remaining == ChainAmounts()


# ---------------------------------------------------------------------------
# _resolve_master_eoa
# ---------------------------------------------------------------------------


class TestResolveMasterEoa:
    """Tests for FundingManager._resolve_master_eoa (lines 523-527)."""

    def test_returns_address_when_wallet_exists(self) -> None:
        """Test that the wallet address is returned when a wallet exists."""
        mock_wallet = MagicMock()
        mock_wallet.address = EOA_ADDR
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        result = manager._resolve_master_eoa(Chain.GNOSIS)
        assert result == EOA_ADDR

    def test_returns_placeholder_when_no_wallet(self) -> None:
        """Test that MASTER_EOA_PLACEHOLDER is returned when no wallet exists."""
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = False

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        result = manager._resolve_master_eoa(Chain.GNOSIS)
        assert result == MASTER_EOA_PLACEHOLDER


# ---------------------------------------------------------------------------
# _resolve_master_safe
# ---------------------------------------------------------------------------


class TestResolveMasterSafe:
    """Tests for FundingManager._resolve_master_safe (lines 529-534)."""

    def test_returns_safe_address_when_wallet_has_safe_for_chain(self) -> None:
        """Test that the safe address is returned when the wallet has a safe."""
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: SAFE_ADDR}
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        result = manager._resolve_master_safe(Chain.GNOSIS)
        assert result == SAFE_ADDR

    def test_returns_placeholder_when_no_safe_for_chain(self) -> None:
        """Test that MASTER_SAFE_PLACEHOLDER is returned when no safe on chain."""
        mock_wallet = MagicMock()
        mock_wallet.safes = {}  # No safe for gnosis
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        result = manager._resolve_master_safe(Chain.GNOSIS)
        assert result == MASTER_SAFE_PLACEHOLDER

    def test_returns_placeholder_when_no_wallet(self) -> None:
        """Test that MASTER_SAFE_PLACEHOLDER is returned when no wallet exists."""
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = False

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        result = manager._resolve_master_safe(Chain.GNOSIS)
        assert result == MASTER_SAFE_PLACEHOLDER


# ---------------------------------------------------------------------------
# _aggregate_as_master_safe_amounts
# ---------------------------------------------------------------------------


class TestAggregateAsMasterSafeAmounts:
    """Tests for FundingManager._aggregate_as_master_safe_amounts (lines 536-551)."""

    def test_aggregates_single_amount(self) -> None:
        """Test that a single ChainAmounts is re-keyed under the master safe."""
        amounts = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(500)}}})
        mock_wallet_manager = MagicMock()
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: SAFE_ADDR}
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        result = manager._aggregate_as_master_safe_amounts(amounts)
        assert SAFE_ADDR in result["gnosis"]
        assert result["gnosis"][SAFE_ADDR][ZERO_ADDRESS] == BigInt(500)

    def test_aggregates_multiple_addresses_under_same_safe(self) -> None:
        """Test that multiple addresses on same chain aggregate under one safe."""
        amounts = ChainAmounts(
            {
                "gnosis": {
                    EOA_ADDR: {ZERO_ADDRESS: BigInt(100)},
                    BACKUP_ADDR: {ZERO_ADDRESS: BigInt(200)},
                }
            }
        )
        mock_wallet_manager = MagicMock()
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: SAFE_ADDR}
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        result = manager._aggregate_as_master_safe_amounts(amounts)
        # Both addresses aggregated into safe
        assert result["gnosis"][SAFE_ADDR][ZERO_ADDRESS] == BigInt(300)


# ---------------------------------------------------------------------------
# _split_excess_assets_master_eoa_balances
# ---------------------------------------------------------------------------


class TestSplitExcessAssetsMasterEoaBalances:
    """Tests for FundingManager._split_excess_assets_master_eoa_balances (lines 553-581)."""

    def test_without_safe_splits_into_topup_and_excess(self) -> None:
        """Test that without a master safe, EOA balance is split into topup and excess."""
        # No safe → MASTER_SAFE_PLACEHOLDER
        gnosis_topup = int(DEFAULT_EOA_TOPUPS[Chain.GNOSIS][ZERO_ADDRESS])
        large_balance = BigInt(gnosis_topup * 3)

        balances = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: large_balance}}})
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = False  # No wallet → placeholder

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        excess, remaining = manager._split_excess_assets_master_eoa_balances(balances)

        # remaining ≤ topup; excess = balance - remaining
        expected_remaining = gnosis_topup
        expected_excess = int(large_balance) - expected_remaining
        assert int(remaining["gnosis"][EOA_ADDR][ZERO_ADDRESS]) == expected_remaining
        assert (
            int(excess["gnosis"][MASTER_SAFE_PLACEHOLDER][ZERO_ADDRESS])
            == expected_excess
        )

    def test_with_safe_all_balance_stays_as_remaining(self) -> None:
        """Test that with a master safe, all EOA balance stays as remaining (no excess)."""
        gnosis_topup = int(DEFAULT_EOA_TOPUPS[Chain.GNOSIS][ZERO_ADDRESS])
        large_balance = BigInt(gnosis_topup * 3)

        balances = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: large_balance}}})
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: SAFE_ADDR}
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)
        excess, remaining = manager._split_excess_assets_master_eoa_balances(balances)

        assert int(remaining["gnosis"][EOA_ADDR][ZERO_ADDRESS]) == int(large_balance)
        assert int(excess["gnosis"][SAFE_ADDR][ZERO_ADDRESS]) == 0


# ---------------------------------------------------------------------------
# fund_service – locking and validation
# ---------------------------------------------------------------------------


class TestFundService:
    """Tests for FundingManager.fund_service (lines 975-1009)."""

    def test_raises_when_funding_already_in_progress(self) -> None:
        """Test FundingInProgressError is raised when funding is already running."""
        manager = _make_manager()
        service_id = "svc-123"
        manager._funding_in_progress[service_id] = True  # simulate in-progress

        mock_service = MagicMock()
        mock_service.service_config_id = service_id
        amounts = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}}})

        with pytest.raises(FundingInProgressError, match="already in progress"):
            manager.fund_service(mock_service, amounts)

    def test_raises_value_error_for_unknown_address(self) -> None:
        """Test ValueError when amounts reference an address not in service."""
        manager = _make_manager()
        mock_service = MagicMock()
        mock_service.service_config_id = "svc-456"
        mock_service.agent_addresses = [EOA_ADDR]
        chain_data_mock = MagicMock()
        chain_data_mock.chain_data.multisig = SAFE_ADDR
        mock_service.chain_configs = {"gnosis": chain_data_mock}

        unknown_addr = "0x" + "f" * 40
        amounts = ChainAmounts({"gnosis": {unknown_addr: {ZERO_ADDRESS: BigInt(1)}}})

        with pytest.raises(ValueError, match="not an agent EOA or service Safe"):
            manager.fund_service(mock_service, amounts)

    def test_raises_value_error_for_malformed_address(self) -> None:
        """Test ValueError when amounts contain a malformed (non-hex) address."""
        manager = _make_manager()
        mock_service = MagicMock()
        mock_service.service_config_id = "svc-bad"
        mock_service.agent_addresses = [EOA_ADDR]
        chain_data_mock = MagicMock()
        chain_data_mock.chain_data.multisig = SAFE_ADDR
        mock_service.chain_configs = {"gnosis": chain_data_mock}

        amounts = ChainAmounts({"gnosis": {"not_an_address": {ZERO_ADDRESS: BigInt(1)}}})

        with pytest.raises(ValueError, match="not a valid Ethereum address"):
            manager.fund_service(mock_service, amounts)

    def test_funding_in_progress_cleared_after_success(self) -> None:
        """Test that _funding_in_progress is cleared after successful fund_chain_amounts."""
        manager = _make_manager()
        service_id = "svc-789"
        mock_service = MagicMock()
        mock_service.service_config_id = service_id
        mock_service.agent_addresses = [EOA_ADDR]
        chain_data_mock = MagicMock()
        chain_data_mock.chain_data.multisig = SAFE_ADDR
        mock_service.chain_configs = {"gnosis": chain_data_mock}

        amounts = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}}})

        with patch.object(manager, "fund_chain_amounts"):
            manager.fund_service(mock_service, amounts)

        assert manager._funding_in_progress.get(service_id) is False

    def test_funding_in_progress_cleared_after_exception(self) -> None:
        """Test that _funding_in_progress is cleared even when fund_chain_amounts raises."""
        manager = _make_manager()
        service_id = "svc-error"
        mock_service = MagicMock()
        mock_service.service_config_id = service_id
        mock_service.agent_addresses = [EOA_ADDR]
        chain_data_mock = MagicMock()
        chain_data_mock.chain_data.multisig = SAFE_ADDR
        mock_service.chain_configs = {"gnosis": chain_data_mock}

        amounts = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}}})

        with patch.object(
            manager, "fund_chain_amounts", side_effect=RuntimeError("rpc down")
        ):
            with pytest.raises(RuntimeError, match="rpc down"):
                manager.fund_service(mock_service, amounts)

        assert manager._funding_in_progress.get(service_id) is False


# ---------------------------------------------------------------------------
# fund_chain_amounts – InsufficientFunds path
# ---------------------------------------------------------------------------


class TestFundChainAmounts:
    """Tests for FundingManager.fund_chain_amounts (lines 944-973)."""

    def test_raises_when_master_safe_has_insufficient_funds(self) -> None:
        """Test InsufficientFundsException when the master safe balance is too low."""
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: SAFE_ADDR}
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)

        # Balance in safe is 0; we need 1000
        amounts = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(1_000)}}})

        with patch.object(
            manager,
            "_get_master_safe_balances",
            return_value=ChainAmounts(
                {"gnosis": {SAFE_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
            ),
        ):
            with pytest.raises(InsufficientFundsException, match="Insufficient funds"):
                manager.fund_chain_amounts(amounts)

    def test_skips_zero_amount_transfers(self) -> None:
        """Test that zero-amount entries are skipped (no wallet.transfer called)."""
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: SAFE_ADDR}
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)

        amounts = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(0)}}})

        # Sufficient balance
        with patch.object(
            manager,
            "_get_master_safe_balances",
            return_value=ChainAmounts(
                {"gnosis": {SAFE_ADDR: {ZERO_ADDRESS: BigInt(1_000)}}}
            ),
        ):
            manager.fund_chain_amounts(amounts)

        mock_wallet.transfer.assert_not_called()

    def test_non_positive_amount_logs_warning(self) -> None:
        """fund_chain_amounts logs a warning (not silently skips) for non-positive amounts."""
        mock_wallet = MagicMock()
        mock_wallet.safes = {Chain.GNOSIS: SAFE_ADDR}
        mock_wallet_manager = MagicMock()
        mock_wallet_manager.load.return_value = mock_wallet

        manager = _make_manager(wallet_manager=mock_wallet_manager)

        amounts = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(0)}}})

        with patch.object(
            manager,
            "_get_master_safe_balances",
            return_value=ChainAmounts(
                {"gnosis": {SAFE_ADDR: {ZERO_ADDRESS: BigInt(1_000)}}}
            ),
        ):
            manager.fund_chain_amounts(amounts)

        manager.logger.warning.assert_called_once()  # type: ignore[attr-defined]
        mock_wallet.transfer.assert_not_called()


# ---------------------------------------------------------------------------
# compute_service_initial_shortfalls / fund_service_initial / topup_service_initial
# ---------------------------------------------------------------------------


class TestDelegatingMethods:
    """Tests for delegation wrappers (lines 925-942)."""

    def test_compute_service_initial_shortfalls_delegates(self) -> None:
        """Test compute_service_initial_shortfalls delegates to _compute_shortfalls."""
        manager = _make_manager()
        mock_service = MagicMock()
        funding_amounts = ChainAmounts(
            {"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(200)}}}
        )
        balances = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(50)}}})
        mock_service.get_initial_funding_amounts.return_value = funding_amounts
        mock_service.get_balances.return_value = balances

        result = manager.compute_service_initial_shortfalls(mock_service)
        # balance 50 < threshold 200 → shortfall = max(200 - 50, 0) = 150
        assert result["gnosis"][EOA_ADDR][ZERO_ADDRESS] == BigInt(150)

    def test_fund_service_initial_calls_fund_chain_amounts(self) -> None:
        """Test fund_service_initial calls fund_chain_amounts with initial amounts."""
        manager = _make_manager()
        mock_service = MagicMock()
        initial_amounts = ChainAmounts(
            {"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(100)}}}
        )
        mock_service.get_initial_funding_amounts.return_value = initial_amounts

        with patch.object(manager, "fund_chain_amounts") as mock_fund:
            manager.fund_service_initial(mock_service)

        mock_fund.assert_called_once_with(initial_amounts, service=mock_service)

    def test_topup_service_initial_calls_fund_chain_amounts(self) -> None:
        """Test topup_service_initial computes shortfalls then calls fund_chain_amounts."""
        manager = _make_manager()
        mock_service = MagicMock()
        funding_amounts = ChainAmounts(
            {"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(200)}}}
        )
        balances = ChainAmounts({"gnosis": {EOA_ADDR: {ZERO_ADDRESS: BigInt(50)}}})
        mock_service.get_initial_funding_amounts.return_value = funding_amounts
        mock_service.get_balances.return_value = balances

        with patch.object(manager, "fund_chain_amounts") as mock_fund:
            manager.topup_service_initial(mock_service)

        # Shortfall is 150 (200-50), fund_chain_amounts should be called with it
        call_amounts = mock_fund.call_args[0][0]
        assert call_amounts["gnosis"][EOA_ADDR][ZERO_ADDRESS] == BigInt(150)
