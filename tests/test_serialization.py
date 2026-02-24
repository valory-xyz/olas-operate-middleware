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

"""Tests for operate.serialization module."""

import enum
import typing as t

from operate.serialization import BigInt, deserialize, serialize


class TestBigIntInPlaceOperators:
    """Tests for BigInt in-place arithmetic operators (lines 38, 42, 46, 50)."""

    def test_isub_returns_bigint(self) -> None:
        """Test __isub__ returns a new BigInt (line 38)."""
        x = BigInt(10)
        x -= 3
        assert x == BigInt(7)
        assert isinstance(x, BigInt)

    def test_imul_returns_bigint(self) -> None:
        """Test __imul__ returns a new BigInt (line 42)."""
        x = BigInt(4)
        x *= 5
        assert x == BigInt(20)
        assert isinstance(x, BigInt)

    def test_ifloordiv_returns_bigint(self) -> None:
        """Test __ifloordiv__ returns a new BigInt (line 46)."""
        x = BigInt(10)
        x //= 3
        assert x == BigInt(3)
        assert isinstance(x, BigInt)

    def test_itruediv_returns_bigint(self) -> None:
        """Test __itruediv__ returns a new BigInt (line 50)."""
        x = BigInt(10)
        x /= 2
        assert x == BigInt(5)
        assert isinstance(x, BigInt)


class TestSerialize:
    """Tests for serialize function edge cases."""

    def test_serialize_bytes_returns_hex_string(self) -> None:
        """Test serialize converts bytes to a hex string (line 66)."""
        result = serialize(b"\xde\xad\xbe\xef")
        assert result == "deadbeef"

    def test_serialize_bigint_returns_str(self) -> None:
        """Test serialize converts BigInt to string (line 68)."""
        result = serialize(BigInt(12345))
        assert result == "12345"
        assert isinstance(result, str)


class TestDeserialize:
    """Tests for deserialize function edge cases."""

    def test_deserialize_bytes_from_hex_string(self) -> None:
        """Test deserialize converts hex string to bytes (line 110)."""
        result = deserialize("deadbeef", bytes)
        assert result == b"\xde\xad\xbe\xef"

    def test_deserialize_bigint_from_string(self) -> None:
        """Test deserialize converts string to BigInt (lines 111-112)."""
        result = deserialize("999", BigInt)
        assert result == BigInt(999)
        assert isinstance(result, BigInt)

    def test_deserialize_optional_all_args_fail_returns_none(self) -> None:
        """Test Optional deserialization returns None when all args fail (lines 83, 86-88)."""

        class Color(enum.Enum):
            RED = 1

        # "not_a_color" cannot be deserialized as Color (raises ValueError),
        # so the loop exhausts all args and returns None.
        result = deserialize("not_a_color", t.Optional[Color])
        assert result is None

    def test_deserialize_generic_alias_three_args_returns_obj(self) -> None:
        """Test _GenericAlias with len(args) > 2 falls through to return obj (line 102)."""
        obj = [1, "a", 1.0]
        # Tuple[int, str, float] has 3 args → neither 1 nor 2 → return obj unchanged.
        result = deserialize(obj, t.Tuple[int, str, float])
        assert result == obj
