# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""Local resource representation."""

import enum
import json
import os
import platform
import shutil
import time
import types
import typing as t
from dataclasses import asdict, is_dataclass
from pathlib import Path


# pylint: disable=too-many-return-statements,no-member


N_BACKUPS = 5


def serialize(obj: t.Any) -> t.Any:
    """Serialize object."""
    if is_dataclass(obj):
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
    return obj


def deserialize(obj: t.Any, otype: t.Any) -> t.Any:
    """Desrialize a json object."""

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
    if is_dataclass(otype):
        return otype.from_json(obj)
    if otype is bytes:
        return bytes.fromhex(obj)
    return obj


def _safe_file_operation(operation: t.Callable, *args: t.Any, **kwargs: t.Any) -> None:
    """Safely perform file operation with retries on Windows."""
    max_retries = 3 if platform.system() == "Windows" else 1

    for attempt in range(max_retries):
        try:
            operation(*args, **kwargs)
            return
        except (PermissionError, FileNotFoundError, OSError) as e:
            if attempt == max_retries - 1:
                raise e

            if platform.system() == "Windows":
                # On Windows, wait a bit and retry
                time.sleep(0.1)


class LocalResource:
    """Initialize local resource."""

    _file: t.Optional[str] = None

    def __init__(self, path: t.Optional[Path] = None) -> None:
        """Initialize local resource."""
        self.path = path

    @property
    def json(self) -> t.Dict:
        """To dictionary object."""
        obj = {}
        for pname, _ in self.__annotations__.items():
            if pname.startswith("_") or pname == "path":
                continue
            obj[pname] = serialize(self.__dict__[pname])
        return obj

    @classmethod
    def from_json(cls, obj: t.Dict) -> "LocalResource":
        """Load LocalResource from json."""
        kwargs = {}
        for pname, ptype in cls.__annotations__.items():
            if pname.startswith("_"):
                continue
            kwargs[pname] = deserialize(obj=obj[pname], otype=ptype)
        return cls(**kwargs)

    @classmethod
    def load(cls, path: Path) -> "LocalResource":
        """Load local resource."""
        file = (
            path / cls._file
            if cls._file is not None and path.name != cls._file
            else path
        )
        data = json.loads(file.read_text(encoding="utf-8"))
        return cls.from_json(obj={**data, "path": path})

    def store(self) -> None:
        """Store local resource."""
        if self.path is None:
            raise RuntimeError(f"Cannot save {self}; Path value not provided.")

        path = self.path
        if self._file is not None:
            path = path / self._file

        bak0 = path.with_name(f"{path.name}.0.bak")

        if path.exists() and not bak0.exists():
            _safe_file_operation(shutil.copy2, path, bak0)

        tmp_path = path.parent / f".{path.name}.tmp"

        # Clean up any existing tmp file
        if tmp_path.exists():
            _safe_file_operation(tmp_path.unlink)

        tmp_path.write_text(
            json.dumps(
                self.json,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Atomic replace to avoid corruption
        try:
            _safe_file_operation(os.replace, tmp_path, path)
        except (PermissionError, FileNotFoundError):
            # On Windows, if the replace fails, clean up and skip
            if platform.system() == "Windows":
                _safe_file_operation(tmp_path.unlink)

        self.load(self.path)  # Validate before making backup

        # Rotate backup files
        for i in reversed(range(N_BACKUPS - 1)):
            newer = path.with_name(f"{path.name}.{i}.bak")
            older = path.with_name(f"{path.name}.{i + 1}.bak")
            if newer.exists():
                if older.exists():
                    _safe_file_operation(older.unlink)
                _safe_file_operation(newer.rename, older)

        _safe_file_operation(shutil.copy2, path, bak0)
