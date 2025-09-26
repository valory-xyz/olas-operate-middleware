"""Tests for ChainAmounts class operations."""

import copy

import pytest

from operate.operate_types import ChainAmounts


@pytest.fixture()
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


@pytest.fixture()
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


def test_truediv(sample_a: ChainAmounts) -> None:
    """Test division of a ChainAmounts instance by a scalar."""
    result = sample_a / 2
    assert result["chain1"]["addr1"]["tokenX"] == 5  # 10 / 2
    assert result["chain1"]["addr1"]["tokenY"] == 2.5  # 5 / 2
    assert result["chain1"]["addr2"]["tokenX"] == 1.5  # 3 / 2
    assert result["chain2"]["addr3"]["tokenZ"] == 50.0  # 100 / 2


def test_floordiv(sample_a: ChainAmounts) -> None:
    """Test floor division of a ChainAmounts instance by a scalar."""
    result = sample_a // 2
    assert result["chain1"]["addr1"]["tokenX"] == 5  # 10 // 2
    assert result["chain1"]["addr1"]["tokenY"] == 2  # 5 // 2
    assert result["chain1"]["addr2"]["tokenX"] == 1  # 3 // 2
    assert result["chain2"]["addr3"]["tokenZ"] == 50  # 100 // 2
    assert (
        type(result["chain1"]["addr1"]["tokenY"]) is int
    )  # floor division should yield int when both operands are int
    assert type(result["chain1"]["addr2"]["tokenX"]) is int


def test_sub(sample_a: ChainAmounts, sample_b: ChainAmounts) -> None:
    """Test subtraction of two ChainAmounts instances."""
    result = sample_a - sample_b
    assert result["chain1"]["addr1"]["tokenX"] == 8  # 10 - 2
    assert result["chain1"]["addr2"]["tokenX"] == -4  # 3 - 7
    assert result["chain1"]["addr2"]["tokenY"] == -4  # 0 - 4
    assert result["chain3"]["addr4"]["tokenX"] == -50  # 50 - 100


def test_division_by_zero(sample_a: ChainAmounts) -> None:
    """Test division by zero raises ValueError."""
    with pytest.raises(ValueError):
        _ = sample_a / 0
    with pytest.raises(ValueError):
        _ = sample_a // 0


def test_immutability(sample_a: ChainAmounts, sample_b: ChainAmounts) -> None:
    """Test that operations do not mutate the original instances."""
    original_a = copy.deepcopy(sample_a)
    _ = sample_a + sample_b
    _ = sample_a - sample_b
    _ = sample_a * 3
    _ = sample_a / 2
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
