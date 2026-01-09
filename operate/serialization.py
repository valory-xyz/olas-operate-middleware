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

"""Serialization utilities."""

import enum
import types
import typing as t
from dataclasses import asdict, is_dataclass
from pathlib import Path


class BigInt(int):
    """BigInt class for large integers that serialize as strings."""

    def __iadd__(self, other: t.Union[int, str]) -> "BigInt":
        """In-place addition."""
        return BigInt(int(self) + int(other))

    def __isub__(self, other: t.Union[int, str]) -> "BigInt":
        """In-place subtraction."""
        return BigInt(int(self) - int(other))

    def __imul__(self, other: t.Union[int, str]) -> "BigInt":
        """In-place multiplication."""
        return BigInt(int(self) * int(other))

    def __ifloordiv__(self, other: t.Union[int, str]) -> "BigInt":
        """In-place floor division."""
        return BigInt(int(self) // int(other))

    def __itruediv__(self, other: t.Union[int, str]) -> "BigInt":
        """In-place true division."""
        return BigInt(int(self) / int(other))


def serialize(obj: t.Any) -> t.Any:  # pylint: disable=too-many-return-statements
    """Serialize object."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return serialize(asdict(obj))
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {serialize(key): serialize(obj=value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [serialize(obj=value) for value in obj]
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, bytes):
        return obj.hex()
    if hasattr(obj, "__class__") and obj.__class__.__name__ == "BigInt":
        return str(obj)
    return obj


def deserialize(  # pylint: disable=too-many-return-statements
    obj: t.Any, otype: t.Any
) -> t.Any:
    """Deserialize a json object."""

    origin = getattr(otype, "__origin__", None)

    # Handle Union and Optional
    if origin is t.Union or isinstance(otype, types.UnionType):
        for arg in t.get_args(otype):
            if arg is type(None):  # noqa: E721
                continue
            try:
                return deserialize(obj, arg)
            except Exception:  # pylint: disable=broad-except  # nosec
                continue
        return None

    base = getattr(otype, "__class__")  # noqa: B009
    if base.__name__ == "_GenericAlias":  # type: ignore
        args = otype.__args__  # type: ignore
        if len(args) == 1:
            (atype,) = args
            return [deserialize(arg, atype) for arg in obj]
        if len(args) == 2:
            (ktype, vtype) = args
            return {
                deserialize(key, ktype): deserialize(val, vtype)
                for key, val in obj.items()
            }
        return obj
    if base is enum.EnumMeta:
        return otype(obj)
    if otype is Path:
        return Path(obj)
    if is_dataclass(otype) and hasattr(otype, "from_json"):
        return otype.from_json(obj)
    if otype is bytes:
        return bytes.fromhex(obj)
    if hasattr(otype, "__name__") and otype.__name__ == "BigInt":
        return BigInt(obj)
    return obj
