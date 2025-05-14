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

"""Helper utilities."""

import shutil
import time
import typing as t
from pathlib import Path


def create_backup(path: Path) -> Path:
    """Creates a backup of the specified path.

    This function creates a backup of a file or directory by copying it and appending
    the current UNIX timestamp followed by the '.bak' suffix.
    """

    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    timestamp = int(time.time())
    backup_path = path.with_name(f"{path.name}.{timestamp}.bak")

    if path.is_dir():
        shutil.copytree(path, backup_path)
    else:
        shutil.copy2(path, backup_path)

    return backup_path


NestedDict = t.Union[int, t.Dict[str, "NestedDict"]]


def merge_sum_dicts(*dicts: t.List[t.Dict[str, NestedDict]]) -> t.Dict[str, NestedDict]:
    """
    Merge a list of nested dicts by summing all innermost `int` values.

    Supports arbitrary depth; keys not in all dicts are still included.
    Missing values are treated as 0.
    All `dicts` must follow the same nesting structure.
    """

    result: t.Dict[str, NestedDict] = {}
    for d in dicts:
        for k, v in d.items():  # type: ignore
            if isinstance(v, dict):
                result[k] = merge_sum_dicts(result.get(k, {}), v)  # type: ignore
            elif isinstance(v, int):
                result[k] = result.get(k, 0) + v  # type: ignore
    return result


def subtract_dicts(
    a: t.Dict[str, NestedDict], b: t.Dict[str, NestedDict]
) -> t.Dict[str, NestedDict]:
    """
    Recursively subtract values in `b` from `a`. Negative results are upper bounded at 0.

    Supports arbitrary depth; keys not in all dicts are still included.
    Missing values are treated as 0.
    All `dicts` must follow the same nesting structure.
    """

    result: t.Dict[str, NestedDict] = {}
    for key in a.keys() | b.keys():  # type: ignore
        va = a.get(key)  # type: ignore
        vb = b.get(key)  # type: ignore
        if isinstance(va, dict) or isinstance(vb, dict):
            result[key] = subtract_dicts(
                va if isinstance(va, dict) else {}, vb if isinstance(vb, dict) else {}
            )
        else:
            result[key] = max((va or 0) - (vb or 0), 0)  # type: ignore
    return result
