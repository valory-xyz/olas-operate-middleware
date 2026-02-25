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

"""Unit tests for operate/data/contracts contract wrapper classes."""

import typing as t
from math import ceil
from unittest.mock import MagicMock, patch

from aea.contracts.base import Contract

from operate.data.contracts.dual_staking_token.contract import DualStakingTokenContract
from operate.data.contracts.foreign_omnibridge.contract import (
    DEFAULT_GAS_RELAY_TOKENS,
    ForeignOmnibridge,
)
from operate.data.contracts.home_omnibridge.contract import HomeOmnibridge
from operate.data.contracts.l1_standard_bridge.contract import (
    DEFAULT_GAS_BRIDGE_ERC20_TO,
    L1StandardBridge,
    NONZERO_ERC20_GAS_FACTOR,
)
from operate.data.contracts.l2_standard_bridge.contract import L2StandardBridge
from operate.data.contracts.mech_activity.contract import MechActivityContract
from operate.data.contracts.optimism_mintable_erc20.contract import (
    OptimismMintableERC20,
)
from operate.data.contracts.staking_token.contract import StakingTokenContract
from operate.data.contracts.uniswap_v2_erc20.contract import UniswapV2ERC20Contract


_ADDR = "0x" + "a" * 40
_CONTRACT_ADDR = "0x" + "b" * 40


def _ledger() -> MagicMock:
    return MagicMock()


def _instance() -> MagicMock:
    return MagicMock()


class TestDualStakingTokenContract:
    """Tests for DualStakingTokenContract methods (lines 41-132)."""

    def test_build_stake_tx(self) -> None:
        """build_stake_tx encodes ABI and returns bytes."""
        mock_instance = _instance()
        mock_instance.encode_abi.return_value = "0xdeadbeef"
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.build_stake_tx(
                _ledger(), _CONTRACT_ADDR, 1
            )
        assert result == {"data": bytes.fromhex("deadbeef")}

    def test_build_checkpoint_tx(self) -> None:
        """build_checkpoint_tx encodes checkpoint ABI and returns bytes."""
        mock_instance = _instance()
        mock_instance.encode_abi.return_value = "0xcafe"
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.build_checkpoint_tx(
                _ledger(), _CONTRACT_ADDR
            )
        assert result == {"data": bytes.fromhex("cafe")}

    def test_build_unstake_tx(self) -> None:
        """build_unstake_tx encodes unstake ABI and returns bytes."""
        mock_instance = _instance()
        mock_instance.encode_abi.return_value = "0xbabe"
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.build_unstake_tx(
                _ledger(), _CONTRACT_ADDR, 1
            )
        assert result == {"data": bytes.fromhex("babe")}

    def test_num_services(self) -> None:
        """num_services calls numServices().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.numServices.return_value.call.return_value = 7
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.num_services(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 7}

    def test_second_token(self) -> None:
        """second_token calls secondToken().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.secondToken.return_value.call.return_value = _ADDR
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.second_token(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": _ADDR}

    def test_second_token_amount(self) -> None:
        """second_token_amount calls secondTokenAmount().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.secondTokenAmount.return_value.call.return_value = 500
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.second_token_amount(
                _ledger(), _CONTRACT_ADDR
            )
        assert result == {"data": 500}

    def test_reward_ratio(self) -> None:
        """reward_ratio calls rewardRatio().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.rewardRatio.return_value.call.return_value = 8000
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.reward_ratio(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 8000}

    def test_stake_ratio(self) -> None:
        """stake_ratio calls stakeRatio().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.stakeRatio.return_value.call.return_value = 2000
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.stake_ratio(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 2000}

    def test_staking_instance(self) -> None:
        """staking_instance calls stakingInstance().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.stakingInstance.return_value.call.return_value = _ADDR
        with patch.object(
            DualStakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = DualStakingTokenContract.staking_instance(
                _ledger(), _CONTRACT_ADDR
            )
        assert result == {"data": _ADDR}


class TestForeignOmnibridge:
    """Tests for ForeignOmnibridge methods (lines 57-130)."""

    def test_build_relay_tokens_tx_gas_above_one(self) -> None:
        """build_relay_tokens_tx returns tx immediately when first gas estimate > 1."""
        mock_instance = _instance()
        tx: t.Dict[str, t.Any] = {"gas": 2}
        mock_instance.functions.relayTokens.return_value.build_transaction.return_value = (
            tx
        )
        with patch.object(
            ForeignOmnibridge, "get_instance", return_value=mock_instance
        ):
            result = ForeignOmnibridge.build_relay_tokens_tx(
                _ledger(), _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, 100
            )
        assert result is tx

    def test_build_relay_tokens_tx_zero_gas_above_one(self) -> None:
        """build_relay_tokens_tx uses zero-value gas estimate when first is 1."""
        mock_instance = _instance()
        tx: t.Dict[str, t.Any] = {"gas": 1}
        tx_zero: t.Dict[str, t.Any] = {"gas": 10}
        mock_instance.functions.relayTokens.return_value.build_transaction.side_effect = [
            tx,
            tx_zero,
        ]
        with patch.object(
            ForeignOmnibridge, "get_instance", return_value=mock_instance
        ):
            result = ForeignOmnibridge.build_relay_tokens_tx(
                _ledger(), _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, 100
            )
        assert result["gas"] == ceil(10 * NONZERO_ERC20_GAS_FACTOR)

    def test_build_relay_tokens_tx_default_gas(self) -> None:
        """build_relay_tokens_tx falls back to DEFAULT_GAS_RELAY_TOKENS when both gas are 1."""
        mock_instance = _instance()
        tx: t.Dict[str, t.Any] = {"gas": 1}
        tx_zero: t.Dict[str, t.Any] = {"gas": 1}
        mock_instance.functions.relayTokens.return_value.build_transaction.side_effect = [
            tx,
            tx_zero,
        ]
        with patch.object(
            ForeignOmnibridge, "get_instance", return_value=mock_instance
        ):
            result = ForeignOmnibridge.build_relay_tokens_tx(
                _ledger(), _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, 100
            )
        assert result["gas"] == DEFAULT_GAS_RELAY_TOKENS

    def test_get_tokens_bridging_initiated_message_id_found(self) -> None:
        """get_tokens_bridging_initiated_message_id returns hex message ID when event matches."""
        mock_ledger = _ledger()
        mock_instance = _instance()
        token = _ADDR
        sender = "0x" + "c" * 40
        value = 1000
        message_id_bytes = bytes.fromhex("ab" * 32)
        event_log: t.Dict[str, t.Any] = {
            "args": {
                "token": token,
                "sender": sender,
                "value": value,
                "messageId": message_id_bytes,
            }
        }
        mock_instance.events.TokensBridgingInitiated.return_value.process_receipt.return_value = [
            event_log
        ]
        with patch.object(
            ForeignOmnibridge, "get_instance", return_value=mock_instance
        ):
            result = ForeignOmnibridge.get_tokens_bridging_initiated_message_id(
                mock_ledger, _CONTRACT_ADDR, "0xtxhash", token, sender, value
            )
        assert result == "0x" + message_id_bytes.hex()

    def test_get_tokens_bridging_initiated_message_id_not_found(self) -> None:
        """get_tokens_bridging_initiated_message_id returns None when no event matches."""
        mock_ledger = _ledger()
        mock_instance = _instance()
        event_log: t.Dict[str, t.Any] = {
            "args": {
                "token": _ADDR,
                "sender": _ADDR,
                "value": 999,  # wrong value
                "messageId": bytes.fromhex("ab" * 32),
            }
        }
        mock_instance.events.TokensBridgingInitiated.return_value.process_receipt.return_value = [
            event_log
        ]
        with patch.object(
            ForeignOmnibridge, "get_instance", return_value=mock_instance
        ):
            result = ForeignOmnibridge.get_tokens_bridging_initiated_message_id(
                mock_ledger, _CONTRACT_ADDR, "0xtxhash", _ADDR, _ADDR, 1000
            )
        assert result is None


class TestHomeOmnibridge:
    """Tests for HomeOmnibridge.find_tokens_bridged_tx (lines 51-80)."""

    def _make_log(self, tx_hash_hex: str, decoded_value: int) -> t.Dict[str, t.Any]:
        mock_tx_hash = MagicMock()
        mock_tx_hash.to_0x_hex.return_value = tx_hash_hex
        return {"data": b"\x00" * 32, "transactionHash": mock_tx_hash}

    def test_find_tokens_bridged_tx_match_returns_hash(self) -> None:
        """find_tokens_bridged_tx returns tx hash when a matching log is found."""
        mock_ledger = _ledger()
        expected_hash = "0x" + "ab" * 32
        mock_tx_hash = MagicMock()
        mock_tx_hash.to_0x_hex.return_value = expected_hash
        log: t.Dict[str, t.Any] = {
            "data": b"\x00" * 32,
            "transactionHash": mock_tx_hash,
        }
        mock_ledger.api.eth.get_logs.return_value = [log]

        with patch("eth_abi.decode", return_value=(1000,)):
            result = HomeOmnibridge.find_tokens_bridged_tx(
                mock_ledger,
                _CONTRACT_ADDR,
                _ADDR,
                _ADDR,
                1000,
                "0x" + "00" * 32,
            )
        assert result == expected_hash

    def test_find_tokens_bridged_tx_no_match_returns_none(self) -> None:
        """find_tokens_bridged_tx returns None when decoded value doesn't match."""
        mock_ledger = _ledger()
        mock_tx_hash = MagicMock()
        mock_tx_hash.to_0x_hex.return_value = "0x" + "ab" * 32
        log: t.Dict[str, t.Any] = {
            "data": b"\x00" * 32,
            "transactionHash": mock_tx_hash,
        }
        mock_ledger.api.eth.get_logs.return_value = [log]

        with patch("eth_abi.decode", return_value=(999,)):  # wrong value
            result = HomeOmnibridge.find_tokens_bridged_tx(
                mock_ledger,
                _CONTRACT_ADDR,
                _ADDR,
                _ADDR,
                1000,
                "0x" + "00" * 32,
            )
        assert result is None

    def test_find_tokens_bridged_tx_empty_logs_returns_none(self) -> None:
        """find_tokens_bridged_tx returns None when no logs are found."""
        mock_ledger = _ledger()
        mock_ledger.api.eth.get_logs.return_value = []
        result = HomeOmnibridge.find_tokens_bridged_tx(
            mock_ledger,
            _CONTRACT_ADDR,
            _ADDR,
            _ADDR,
            1000,
            "0x" + "00" * 32,
        )
        assert result is None


class TestL1StandardBridge:
    """Tests for L1StandardBridge methods (lines 55-158)."""

    def test_supports_bridge_eth_to_returns_true(self) -> None:
        """supports_bridge_eth_to returns True when bridgeETHTo call succeeds."""
        mock_instance = _instance()
        mock_instance.functions.bridgeETHTo.return_value.call.return_value = True
        with patch.object(L1StandardBridge, "get_instance", return_value=mock_instance):
            result = L1StandardBridge.supports_bridge_eth_to(_ledger(), _CONTRACT_ADDR)
        assert result is True

    def test_supports_bridge_eth_to_returns_false_on_exception(self) -> None:
        """supports_bridge_eth_to returns False when bridgeETHTo call raises."""
        mock_instance = _instance()
        mock_instance.functions.bridgeETHTo.return_value.call.side_effect = Exception(
            "reverted"
        )
        with patch.object(L1StandardBridge, "get_instance", return_value=mock_instance):
            result = L1StandardBridge.supports_bridge_eth_to(_ledger(), _CONTRACT_ADDR)
        assert result is False

    def test_build_bridge_eth_to_tx(self) -> None:
        """build_bridge_eth_to_tx builds and returns the ETH bridge tx."""
        mock_ledger = _ledger()
        mock_instance = _instance()
        expected_tx: t.Dict[str, t.Any] = {"to": _ADDR, "value": 100}
        mock_instance.functions.bridgeETHTo.return_value.build_transaction.return_value = (
            expected_tx
        )
        mock_ledger.update_with_gas_estimate.return_value = expected_tx
        with patch.object(L1StandardBridge, "get_instance", return_value=mock_instance):
            result = L1StandardBridge.build_bridge_eth_to_tx(
                mock_ledger, _CONTRACT_ADDR, _ADDR, _ADDR, 100, 300000, b""
            )
        assert result is expected_tx

    def test_build_bridge_erc20_to_tx_gas_above_one(self) -> None:
        """build_bridge_erc20_to_tx returns tx when first gas estimate > 1."""
        mock_instance = _instance()
        tx: t.Dict[str, t.Any] = {"gas": 2}
        mock_instance.functions.bridgeERC20To.return_value.build_transaction.return_value = (
            tx
        )
        with patch.object(L1StandardBridge, "get_instance", return_value=mock_instance):
            result = L1StandardBridge.build_bridge_erc20_to_tx(
                _ledger(), _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, _ADDR, 100, 300000, b""
            )
        assert result is tx

    def test_build_bridge_erc20_to_tx_zero_gas_above_one(self) -> None:
        """build_bridge_erc20_to_tx uses zero-value gas when first estimate is 1."""
        mock_instance = _instance()
        tx: t.Dict[str, t.Any] = {"gas": 1}
        tx_zero: t.Dict[str, t.Any] = {"gas": 10}
        mock_instance.functions.bridgeERC20To.return_value.build_transaction.side_effect = [
            tx,
            tx_zero,
        ]
        with patch.object(L1StandardBridge, "get_instance", return_value=mock_instance):
            result = L1StandardBridge.build_bridge_erc20_to_tx(
                _ledger(), _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, _ADDR, 100, 300000, b""
            )
        assert result["gas"] == ceil(10 * NONZERO_ERC20_GAS_FACTOR)

    def test_build_bridge_erc20_to_tx_default_gas(self) -> None:
        """build_bridge_erc20_to_tx falls back to DEFAULT_GAS when both estimates are 1."""
        mock_instance = _instance()
        tx: t.Dict[str, t.Any] = {"gas": 1}
        tx_zero: t.Dict[str, t.Any] = {"gas": 1}
        mock_instance.functions.bridgeERC20To.return_value.build_transaction.side_effect = [
            tx,
            tx_zero,
        ]
        with patch.object(L1StandardBridge, "get_instance", return_value=mock_instance):
            result = L1StandardBridge.build_bridge_erc20_to_tx(
                _ledger(), _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, _ADDR, 100, 300000, b""
            )
        assert result["gas"] == DEFAULT_GAS_BRIDGE_ERC20_TO


class TestL2StandardBridge:
    """Tests for L2StandardBridge methods (lines 51-130)."""

    def _make_log(self, tx_hash_hex: str) -> t.Dict[str, t.Any]:
        mock_tx_hash = MagicMock()
        mock_tx_hash.to_0x_hex.return_value = tx_hash_hex
        return {"data": b"\x00" * 64, "transactionHash": mock_tx_hash}

    def test_find_eth_bridge_finalized_tx_match(self) -> None:
        """find_eth_bridge_finalized_tx returns hash when decoded values match."""
        mock_ledger = _ledger()
        expected = "0x" + "ab" * 32
        log = self._make_log(expected)
        mock_ledger.api.eth.get_logs.return_value = [log]
        with patch("eth_abi.decode", return_value=(100, b"")):
            result = L2StandardBridge.find_eth_bridge_finalized_tx(
                mock_ledger, _CONTRACT_ADDR, _ADDR, _ADDR, 100, b""
            )
        assert result == expected

    def test_find_eth_bridge_finalized_tx_no_match(self) -> None:
        """find_eth_bridge_finalized_tx returns None when decoded values don't match."""
        mock_ledger = _ledger()
        log = self._make_log("0x" + "ab" * 32)
        mock_ledger.api.eth.get_logs.return_value = [log]
        with patch("eth_abi.decode", return_value=(999, b"")):  # wrong amount
            result = L2StandardBridge.find_eth_bridge_finalized_tx(
                mock_ledger, _CONTRACT_ADDR, _ADDR, _ADDR, 100, b""
            )
        assert result is None

    def test_find_erc20_bridge_finalized_tx_match(self) -> None:
        """find_erc20_bridge_finalized_tx returns hash when decoded values match."""
        mock_ledger = _ledger()
        to_addr = "0x" + "d" * 40
        expected = "0x" + "ab" * 32
        log = self._make_log(expected)
        mock_ledger.api.eth.get_logs.return_value = [log]
        with patch("eth_abi.decode", return_value=(to_addr.lower(), 100, b"")):
            result = L2StandardBridge.find_erc20_bridge_finalized_tx(
                mock_ledger, _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, to_addr, 100, b""
            )
        assert result == expected

    def test_find_erc20_bridge_finalized_tx_no_match(self) -> None:
        """find_erc20_bridge_finalized_tx returns None when decoded values don't match."""
        mock_ledger = _ledger()
        to_addr = "0x" + "d" * 40
        log = self._make_log("0x" + "ab" * 32)
        mock_ledger.api.eth.get_logs.return_value = [log]
        with patch(
            "eth_abi.decode", return_value=(to_addr.lower(), 999, b"")
        ):  # wrong amount
            result = L2StandardBridge.find_erc20_bridge_finalized_tx(
                mock_ledger, _CONTRACT_ADDR, _ADDR, _ADDR, _ADDR, to_addr, 100, b""
            )
        assert result is None


class TestMechActivityContract:
    """Tests for MechActivityContract.liveness_ratio (lines 42-44)."""

    def test_liveness_ratio(self) -> None:
        """liveness_ratio calls livenessRatio().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.livenessRatio.return_value.call.return_value = 10
        with patch.object(
            MechActivityContract, "get_instance", return_value=mock_instance
        ):
            result = MechActivityContract.liveness_ratio(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 10}


class TestOptimismMintableERC20:
    """Tests for OptimismMintableERC20.l1_token (lines 41-45)."""

    def test_l1_token(self) -> None:
        """l1_token calls l1Token().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.l1Token.return_value.call.return_value = _ADDR
        with patch.object(
            OptimismMintableERC20, "get_instance", return_value=mock_instance
        ):
            result = OptimismMintableERC20.l1_token(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": _ADDR}


class TestStakingTokenContract:
    """Tests for StakingTokenContract methods (lines 43-192)."""

    def test_get_service_staking_state(self) -> None:
        """get_service_staking_state calls getStakingState and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.getStakingState.return_value.call.return_value = 1
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.get_service_staking_state(
                _ledger(), _CONTRACT_ADDR, 1
            )
        assert result == {"data": 1}

    def test_build_stake_tx(self) -> None:
        """build_stake_tx encodes stake ABI and returns bytes."""
        mock_instance = _instance()
        mock_instance.encode_abi.return_value = "0xdeadbeef"
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.build_stake_tx(_ledger(), _CONTRACT_ADDR, 1)
        assert result == {"data": bytes.fromhex("deadbeef")}

    def test_build_checkpoint_tx(self) -> None:
        """build_checkpoint_tx encodes checkpoint ABI and returns bytes."""
        mock_instance = _instance()
        mock_instance.encode_abi.return_value = "0xcafe"
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.build_checkpoint_tx(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": bytes.fromhex("cafe")}

    def test_build_unstake_tx(self) -> None:
        """build_unstake_tx encodes unstake ABI and returns bytes."""
        mock_instance = _instance()
        mock_instance.encode_abi.return_value = "0xbabe"
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.build_unstake_tx(_ledger(), _CONTRACT_ADDR, 1)
        assert result == {"data": bytes.fromhex("babe")}

    def test_available_rewards(self) -> None:
        """available_rewards calls availableRewards().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.availableRewards.return_value.call.return_value = 500
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.available_rewards(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 500}

    def test_get_staking_rewards(self) -> None:
        """get_staking_rewards calls calculateStakingReward and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.calculateStakingReward.return_value.call.return_value = (
            200
        )
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.get_staking_rewards(
                _ledger(), _CONTRACT_ADDR, 1
            )
        assert result == {"data": 200}

    def test_get_next_checkpoint_ts(self) -> None:
        """get_next_checkpoint_ts calls getNextRewardCheckpointTimestamp and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.getNextRewardCheckpointTimestamp.return_value.call.return_value = (
            9999
        )
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.get_next_checkpoint_ts(
                _ledger(), _CONTRACT_ADDR
            )
        assert result == {"data": 9999}

    def test_ts_checkpoint(self) -> None:
        """ts_checkpoint calls tsCheckpoint().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.tsCheckpoint.return_value.call.return_value = 12345
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.ts_checkpoint(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 12345}

    def test_liveness_ratio(self) -> None:
        """liveness_ratio calls livenessRatio().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.livenessRatio.return_value.call.return_value = 10
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.liveness_ratio(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 10}

    def test_get_liveness_period(self) -> None:
        """get_liveness_period calls livenessPeriod().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.livenessPeriod.return_value.call.return_value = 3600
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.get_liveness_period(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 3600}

    def test_get_service_info(self) -> None:
        """get_service_info calls getServiceInfo and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.getServiceInfo.return_value.call.return_value = {
            "id": 1
        }
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.get_service_info(_ledger(), _CONTRACT_ADDR, 1)
        assert result == {"data": {"id": 1}}

    def test_max_num_services(self) -> None:
        """max_num_services calls maxNumServices().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.maxNumServices.return_value.call.return_value = 100
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.max_num_services(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": 100}

    def test_get_service_ids(self) -> None:
        """get_service_ids calls getServiceIds().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.getServiceIds.return_value.call.return_value = [1, 2, 3]
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.get_service_ids(_ledger(), _CONTRACT_ADDR)
        assert result == {"data": [1, 2, 3]}

    def test_get_min_staking_duration(self) -> None:
        """get_min_staking_duration calls minStakingDuration().call() and returns data dict."""
        mock_instance = _instance()
        mock_instance.functions.minStakingDuration.return_value.call.return_value = (
            86400
        )
        with patch.object(
            StakingTokenContract, "get_instance", return_value=mock_instance
        ):
            result = StakingTokenContract.get_min_staking_duration(
                _ledger(), _CONTRACT_ADDR
            )
        assert result == {"data": 86400}


class TestUniswapV2ERC20Contract:
    """Tests for UniswapV2ERC20Contract methods (lines 53-224)."""

    def test_approve(self) -> None:
        """Call approve via ledger_api.build_transaction."""
        mock_ledger = MagicMock()
        mock_instance = _instance()
        mock_ledger.build_transaction.return_value = {"data": "0x"}
        with patch.object(
            UniswapV2ERC20Contract, "get_instance", return_value=mock_instance
        ):
            result = UniswapV2ERC20Contract.approve(
                mock_ledger, _CONTRACT_ADDR, _ADDR, 1000
            )
        assert result is not None
        mock_ledger.build_transaction.assert_called_once()

    def test_transfer(self) -> None:
        """Call transfer via ledger_api.build_transaction."""
        mock_ledger = MagicMock()
        mock_instance = _instance()
        mock_ledger.build_transaction.return_value = {"data": "0x"}
        with patch.object(
            UniswapV2ERC20Contract, "get_instance", return_value=mock_instance
        ):
            result = UniswapV2ERC20Contract.transfer(
                mock_ledger, _CONTRACT_ADDR, _ADDR, 500
            )
        assert result is not None
        mock_ledger.build_transaction.assert_called_once()

    def test_transfer_from(self) -> None:
        """transfer_from calls build_transaction via ledger_api.build_transaction."""
        mock_ledger = MagicMock()
        mock_instance = _instance()
        mock_ledger.build_transaction.return_value = {"data": "0x"}
        with patch.object(
            UniswapV2ERC20Contract, "get_instance", return_value=mock_instance
        ):
            result = UniswapV2ERC20Contract.transfer_from(
                mock_ledger, _CONTRACT_ADDR, _ADDR, _ADDR, 200
            )
        assert result is not None
        mock_ledger.build_transaction.assert_called_once()

    def test_permit(self) -> None:
        """Call permit via ledger_api.build_transaction."""
        mock_ledger = MagicMock()
        mock_instance = _instance()
        mock_ledger.build_transaction.return_value = {"data": "0x"}
        with patch.object(
            UniswapV2ERC20Contract, "get_instance", return_value=mock_instance
        ):
            result = UniswapV2ERC20Contract.permit(
                mock_ledger,
                _CONTRACT_ADDR,
                _ADDR,
                _ADDR,
                100,
                9999,
                27,
                b"\x00" * 32,
                b"\x00" * 32,
            )
        assert result is not None
        mock_ledger.build_transaction.assert_called_once()

    def test_allowance(self) -> None:
        """Call allowance via ledger_api.contract_method_call."""
        mock_ledger = MagicMock()
        mock_instance = _instance()
        mock_ledger.contract_method_call.return_value = {"data": 1000}
        with patch.object(
            UniswapV2ERC20Contract, "get_instance", return_value=mock_instance
        ):
            result = UniswapV2ERC20Contract.allowance(
                mock_ledger, _CONTRACT_ADDR, _ADDR, _ADDR
            )
        assert result == {"data": 1000}
        mock_ledger.contract_method_call.assert_called_once()

    def test_balance_of(self) -> None:
        """balance_of calls contract_method_call with 'balanceOf' method."""
        mock_ledger = MagicMock()
        mock_instance = _instance()
        mock_ledger.contract_method_call.return_value = {"data": 5000}
        with patch.object(
            UniswapV2ERC20Contract, "get_instance", return_value=mock_instance
        ):
            result = UniswapV2ERC20Contract.balance_of(
                mock_ledger, _CONTRACT_ADDR, _ADDR
            )
        assert result == {"data": 5000}
        mock_ledger.contract_method_call.assert_called_once()

    def test_get_transaction_transfer_logs_none_data(self) -> None:
        """get_transaction_transfer_logs returns empty logs when super returns None."""
        mock_ledger = MagicMock()
        with patch.object(Contract, "get_transaction_transfer_logs", return_value=None):
            result = UniswapV2ERC20Contract.get_transaction_transfer_logs(
                mock_ledger, _CONTRACT_ADDR, "0xtxhash"
            )
        assert result == {"logs": []}

    def test_get_transaction_transfer_logs_with_data_no_filter(self) -> None:
        """get_transaction_transfer_logs processes logs and returns all when no target."""
        mock_ledger = MagicMock()
        from_addr = "0x" + "c" * 40
        to_addr = "0x" + "d" * 40
        logs_data = {
            "logs": [
                {
                    "args": {"from": from_addr, "to": to_addr, "value": 100},
                    "address": _CONTRACT_ADDR,
                }
            ]
        }
        with patch.object(
            Contract, "get_transaction_transfer_logs", return_value=logs_data
        ):
            result = UniswapV2ERC20Contract.get_transaction_transfer_logs(
                mock_ledger, _CONTRACT_ADDR, "0xtxhash"
            )
        assert len(result["logs"]) == 1
        assert result["logs"][0]["from"] == from_addr

    def test_get_transaction_transfer_logs_with_target_filter(self) -> None:
        """get_transaction_transfer_logs filters logs by target_address."""
        mock_ledger = MagicMock()
        from_addr = "0x" + "c" * 40
        to_addr = "0x" + "d" * 40
        other_addr = "0x" + "e" * 40
        logs_data = {
            "logs": [
                {
                    "args": {"from": from_addr, "to": to_addr, "value": 100},
                    "address": _CONTRACT_ADDR,
                },
                {
                    "args": {"from": other_addr, "to": other_addr, "value": 50},
                    "address": _CONTRACT_ADDR,
                },
            ]
        }
        with patch.object(
            Contract, "get_transaction_transfer_logs", return_value=logs_data
        ):
            result = UniswapV2ERC20Contract.get_transaction_transfer_logs(
                mock_ledger, _CONTRACT_ADDR, "0xtxhash", target_address=from_addr
            )
        assert len(result["logs"]) == 1
        assert result["logs"][0]["from"] == from_addr
