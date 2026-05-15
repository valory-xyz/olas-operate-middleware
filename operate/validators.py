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

"""Shared input-validation primitives used across the operate package.

Centralising the regex patterns here keeps the path-traversal and ID-format
contracts in one place so the two cannot drift between call sites.
"""

import re
from pathlib import Path

# Operator-supplied filesystem-path validator. Rejects any value containing a
# ``..`` traversal segment (anchored to a path-separator boundary) and any
# character outside the safe filesystem-path set. Used to gate values that
# arrive via environment variables before they reach ``Path``, ``shutil``, or
# similar APIs.
SAFE_FS_PATH_RE: re.Pattern[str] = re.compile(
    r"\A(?!.*(?:^|/|\\)\.\.(?:/|\\|\Z))[A-Za-z0-9_./:\\ -]+\Z"
)


class UnsafePathError(ValueError):
    """Raised when a path candidate fails ``SAFE_FS_PATH_RE`` validation."""


def safe_resolved_path(value: str) -> Path:
    """Return a resolved ``Path`` only if ``value`` is a safe filesystem path.

    A "safe" value matches :data:`SAFE_FS_PATH_RE` — no ``..`` traversal
    segments and only filesystem-safe characters. Unsafe inputs raise
    :class:`UnsafePathError` *before* any ``pathlib.Path`` or filesystem
    operation runs, giving static-analysis tools (CodeQL, SnykCode, etc.) a
    single, narrow sanitisation boundary to reason about.

    The barrier is intentionally inside this function so callers see one
    sanitisation point rather than a regex check spread across modules.
    """
    if not isinstance(value, str) or not SAFE_FS_PATH_RE.fullmatch(value):
        raise UnsafePathError(f"Unsafe filesystem path: {value!r}")
    return Path(value).resolve()
