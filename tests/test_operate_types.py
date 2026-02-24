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

"""Tests for operate.operate_types module."""

import copy

import pytest

from operate.constants import NO_STAKING_PROGRAM_ID
from operate.operate_types import ChainAmounts, OnChainUserParams, Version
from operate.serialization import BigInt


def test_version() -> None:
    """Test Version class."""
    v1 = Version("")
    v2 = Version("1")
    v3 = Version("1.2")
    v4 = Version("1.2.3")
    v5 = Version("1.2.3")
    v6 = Version("2.0.0")

    assert v1 < v2
    assert v2 < v3
    assert v3 < v4
    assert v4 == v5
    assert v6 > v5
    assert str(v1) == "0.0.0"


@pytest.fixture
def sample_a() -> ChainAmounts:
    """Sample ChainAmounts instance A."""
    return ChainAmounts(
        {
            "chain1": {
                "addr1": {"tokenX": 10, "tokenY": 5},
                "addr2": {"tokenX": 3},
            },
            "chain2": {"addr3": {"tokenZ": 100}},
        }
    )


@pytest.fixture
def sample_b() -> ChainAmounts:
    """Sample ChainAmounts instance B."""
    return ChainAmounts(
        {
            "chain1": {
                "addr1": {"tokenX": 2, "tokenY": 1},
                "addr2": {"tokenX": 7, "tokenY": 4},
            },
            "chain3": {"addr4": {"tokenX": 50}},
        }
    )


def test_add(sample_a: ChainAmounts, sample_b: ChainAmounts) -> None:
    """Test addition of two ChainAmounts instances."""
    result = sample_a + sample_b
    assert result["chain1"]["addr1"]["tokenX"] == 12  # 10 + 2
    assert result["chain1"]["addr1"]["tokenY"] == 6  # 5 + 1
    assert result["chain1"]["addr2"]["tokenX"] == 10  # 3 + 7
    assert result["chain1"]["addr2"]["tokenY"] == 4  # introduced
    assert result["chain2"]["addr3"]["tokenZ"] == 100
    assert result["chain3"]["addr4"]["tokenX"] == 50
    assert sample_a + sample_b == sample_b + sample_a  # commutative


def test_mul(sample_a: ChainAmounts) -> None:
    """Test multiplication of a ChainAmounts instance by a scalar."""
    result = sample_a * 2
    assert result["chain1"]["addr1"]["tokenX"] == 20
    assert result["chain1"]["addr1"]["tokenY"] == 10
    assert result["chain1"]["addr2"]["tokenX"] == 6
    assert result["chain2"]["addr3"]["tokenZ"] == 200


def test_floordiv(sample_a: ChainAmounts) -> None:
    """Test floor division of a ChainAmounts instance by a scalar."""
    result = sample_a // 2
    assert result["chain1"]["addr1"]["tokenX"] == 5  # 10 // 2
    assert result["chain1"]["addr1"]["tokenY"] == 2  # 5 // 2
    assert result["chain1"]["addr2"]["tokenX"] == 1  # 3 // 2
    assert result["chain2"]["addr3"]["tokenZ"] == 50  # 100 // 2
    assert isinstance(
        result["chain1"]["addr1"]["tokenY"], int
    )  # floor division should yield int when both operands are int
    assert isinstance(result["chain1"]["addr2"]["tokenX"], int)


def test_sub(sample_a: ChainAmounts, sample_b: ChainAmounts) -> None:
    """Test subtraction of two ChainAmounts instances."""
    result = sample_a - sample_b
    assert result["chain1"]["addr1"]["tokenX"] == 8  # 10 - 2
    assert result["chain1"]["addr2"]["tokenX"] == -4  # 3 - 7
    assert result["chain1"]["addr2"]["tokenY"] == -4  # 0 - 4
    assert result["chain3"]["addr4"]["tokenX"] == -50  # 50 - 100


def test_division_by_zero(sample_a: ChainAmounts) -> None:
    """Test division by zero raises ValueError."""
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        _ = sample_a // 0


def test_immutability(sample_a: ChainAmounts, sample_b: ChainAmounts) -> None:
    """Test that operations do not mutate the original instances."""
    original_a = copy.deepcopy(sample_a)
    _ = sample_a + sample_b
    _ = sample_a - sample_b
    _ = sample_a * 3
    _ = sample_a // 2
    # original data unchanged
    assert sample_a == original_a


def test_chained_operations(sample_a: ChainAmounts, sample_b: ChainAmounts) -> None:
    """Test chained operations."""
    result = ((sample_a + sample_b) - sample_a) * 3 // 2
    # ((a + b) - a) == b; arithmetic keeps zero balances for tokens/addresses present only in a
    expected = sample_b * 3 // 2

    def prune_zeros(data: ChainAmounts) -> ChainAmounts:
        out: ChainAmounts = ChainAmounts({})
        for chain, addresses in data.items():
            for address, balances in addresses.items():
                for token, amount in balances.items():
                    if amount != 0:
                        out.setdefault(chain, {}).setdefault(address, {})[
                            token
                        ] = amount
        return out

    assert prune_zeros(result) == prune_zeros(expected)


def test_negative_results_and_presence(
    sample_a: ChainAmounts, sample_b: ChainAmounts
) -> None:
    """Test that subtraction can yield negative results and they are preserved."""
    # Force negatives by subtracting larger structure
    result = sample_b - sample_a
    assert result["chain1"]["addr1"]["tokenX"] == -8  # 2 - 10
    assert result["chain2"]["addr3"]["tokenZ"] == -100


def test_version_eq_not_implemented() -> None:
    """Test Version.__eq__ returns NotImplemented for non-Version objects."""
    v = Version("1.0.0")
    result = v.__eq__("1.0.0")
    assert result is NotImplemented


def test_on_chain_user_params_use_staking_none() -> None:
    """Test use_staking returns False when staking_program_id is None."""
    params = OnChainUserParams(
        staking_program_id=None,  # type: ignore[arg-type]
        nft="bafybei_test",
        agent_id=14,
        cost_of_bond=BigInt(1000),
        fund_requirements={},
    )
    assert params.use_staking is False


def test_on_chain_user_params_use_staking_no_staking_id() -> None:
    """Test use_staking returns False when staking_program_id is NO_STAKING_PROGRAM_ID."""
    params = OnChainUserParams(
        staking_program_id=NO_STAKING_PROGRAM_ID,
        nft="bafybei_test",
        agent_id=14,
        cost_of_bond=BigInt(1000),
        fund_requirements={},
    )
    assert params.use_staking is False


def test_on_chain_user_params_use_staking_real_program() -> None:
    """Test use_staking returns True when staking_program_id is a real staking program."""
    params = OnChainUserParams(
        staking_program_id="pearl_alpha",
        nft="bafybei_test",
        agent_id=14,
        cost_of_bond=BigInt(1000),
        fund_requirements={},
    )
    assert params.use_staking is True


def test_chain_amounts_json_round_trip() -> None:
    """Test ChainAmounts.json property serializes amounts and from_json deserializes them."""
    original = ChainAmounts(
        {"chain1": {"addr1": {"tokenX": BigInt(100), "tokenY": BigInt(50)}}}
    )
    json_repr = original.json
    restored = ChainAmounts.from_json(json_repr)
    assert restored["chain1"]["addr1"]["tokenX"] == BigInt(100)
    assert restored["chain1"]["addr1"]["tokenY"] == BigInt(50)


def test_chain_amounts_from_json_nested_structure() -> None:
    """Test ChainAmounts.from_json handles nested chain/address/asset structure."""
    obj = {
        "chain1": {
            "addr1": {"tokenX": "999999999999999999"},
            "addr2": {"tokenZ": "200"},
        },
        "chain2": {"addr3": {"tokenA": "0"}},
    }
    result = ChainAmounts.from_json(obj)
    assert result["chain1"]["addr1"]["tokenX"] == BigInt(999999999999999999)
    assert result["chain1"]["addr2"]["tokenZ"] == BigInt(200)
    assert result["chain2"]["addr3"]["tokenA"] == BigInt(0)


def test_chain_amounts_shortfalls_with_shortfall() -> None:
    """Test ChainAmounts.shortfalls returns positive shortfall when balance is below requirement."""
    requirements = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(100)}}})
    balances = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(40)}}})
    shortfalls = ChainAmounts.shortfalls(requirements, balances)
    assert shortfalls["chain1"]["addr1"]["tokenX"] == BigInt(60)


def test_chain_amounts_shortfalls_no_shortfall() -> None:
    """Test ChainAmounts.shortfalls returns zero when balance exceeds requirement."""
    requirements = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(100)}}})
    balances = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(200)}}})
    shortfalls = ChainAmounts.shortfalls(requirements, balances)
    assert shortfalls["chain1"]["addr1"]["tokenX"] == BigInt(0)


def test_chain_amounts_shortfalls_missing_chain() -> None:
    """Test ChainAmounts.shortfalls returns full requirement when chain is absent from balances."""
    requirements = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(100)}}})
    balances = ChainAmounts({})
    shortfalls = ChainAmounts.shortfalls(requirements, balances)
    assert shortfalls["chain1"]["addr1"]["tokenX"] == BigInt(100)


def test_chain_amounts_lt_all_strictly_less() -> None:
    """Test ChainAmounts.__lt__ returns True when all amounts are strictly less."""
    low = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(1)}}})
    high = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(10)}}})
    assert (low < high) is True


def test_chain_amounts_lt_equal_is_not_strictly_less() -> None:
    """Test ChainAmounts.__lt__ returns False when an amount equals the other."""
    equal_a = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(5)}}})
    equal_b = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(5)}}})
    assert (equal_a < equal_b) is False


def test_chain_amounts_lt_one_amount_greater() -> None:
    """Test ChainAmounts.__lt__ returns False when one amount is greater."""
    mixed = ChainAmounts(
        {"chain1": {"addr1": {"tokenX": BigInt(10), "tokenY": BigInt(1)}}}
    )
    other = ChainAmounts(
        {"chain1": {"addr1": {"tokenX": BigInt(5), "tokenY": BigInt(5)}}}
    )
    # tokenX (10) >= tokenX in other (5) => returns False
    assert (mixed < other) is False


def test_chain_amounts_lt_empty_is_vacuously_true() -> None:
    """Test ChainAmounts.__lt__ returns True when self is empty (vacuous truth)."""
    empty = ChainAmounts({})
    other = ChainAmounts({"chain1": {"addr1": {"tokenX": BigInt(1)}}})
    assert (empty < other) is True
