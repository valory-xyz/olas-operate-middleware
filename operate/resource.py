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

import inspect
import json
import os
import platform
import shutil
import types
import typing as t
from pathlib import Path

from operate.serialization import deserialize, serialize
from operate.utils import safe_file_operation

# pylint: disable=too-many-return-statements,no-member


N_BACKUPS = 5


class LocalResource:
    """Initialize local resource."""

    _file: t.Optional[str] = None

    def __init__(self, path: t.Optional[Path] = None) -> None:
        """Initialize local resource."""
        self.path = path

    @classmethod
    def _annotations(cls) -> t.Dict[str, t.Any]:
        """Get class annotations in a Python-version-safe way.

        Uses eval_str=True so that Python 3.14's deferred-evaluation
        annotations (PEP 749) are resolved to actual type objects rather
        than ForwardRef or raw strings.  Falls back to __annotations__ if
        inspect.get_annotations is unavailable.
        """
        try:
            return dict(inspect.get_annotations(cls, eval_str=True))
        except Exception:  # pylint: disable=broad-except  # nosec
            return dict(getattr(cls, "__annotations__", {}))

    @property
    def json(self) -> t.Dict:
        """To dictionary object."""
        obj = {}
        for pname, _ in self._annotations().items():
            if pname.startswith("_") or pname == "path":
                continue
            obj[pname] = serialize(self.__dict__[pname])
        return obj

    @classmethod
    def from_json(cls, obj: t.Dict) -> "LocalResource":
        """Load LocalResource from json."""
        kwargs = {}
        for pname, ptype in cls._annotations().items():
            if pname.startswith("_"):
                continue
            # Use obj.get() (returns None if absent) only for Optional fields,
            # so that newly-added Optional fields (e.g. canonical_backup_owner)
            # load cleanly from legacy JSON without a value.
            # Required fields still use obj[pname] and raise KeyError if missing.
            # Handle both typing.Union (t.Optional[X]) and types.UnionType (X | None).
            _origin = t.get_origin(ptype)
            _args = t.get_args(ptype)
            is_optional = (_origin is t.Union and type(None) in _args) or (
                isinstance(ptype, types.UnionType) and type(None) in _args
            )
            if is_optional:
                kwargs[pname] = deserialize(obj=obj.get(pname), otype=ptype)
            else:
                kwargs[pname] = deserialize(obj=obj[pname], otype=ptype)
        return cls(**kwargs)

    @classmethod
    def exists_at(cls, path: Path) -> bool:
        """Verifies if local resource exists at specified path."""
        file = (
            path / cls._file
            if cls._file is not None and path.name != cls._file
            else path
        )
        return file.exists()

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
            safe_file_operation(shutil.copy2, path, bak0)

        tmp_path = path.parent / f".{path.name}.tmp"

        # Clean up any existing tmp file
        if tmp_path.exists():
            safe_file_operation(tmp_path.unlink)

        tmp_path.write_text(
            json.dumps(
                self.json,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Atomic replace to avoid corruption
        try:
            safe_file_operation(os.replace, tmp_path, path)
        except (PermissionError, FileNotFoundError):
            # On Windows, if the replace fails, clean up and skip
            if platform.system() == "Windows":
                safe_file_operation(tmp_path.unlink)

        self.load(self.path)  # Validate before making backup

        # Rotate backup files
        for i in reversed(range(N_BACKUPS - 1)):
            newer = path.with_name(f"{path.name}.{i}.bak")
            older = path.with_name(f"{path.name}.{i + 1}.bak")
            if newer.exists():
                if older.exists():
                    safe_file_operation(older.unlink)
                safe_file_operation(newer.rename, older)

        safe_file_operation(shutil.copy2, path, bak0)
