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

# Safe-identifier pattern for free-form URL path parameters such as
# ``service_config_id`` and ``achievement_id``. Both originate from different
# producers (service_config_id is an internally-generated ``sc-<uuid4>``;
# achievement_id is a free-form key from ``agent_performance.json``) but
# share the same security contract: the value reaches filesystem paths and
# subprocess argument lists, so it must contain no path-traversal segments,
# shell metacharacters, scheme/host components, or whitespace. Exported as
# both a string (for ``fastapi.Path(pattern=...)`` declarations that CodeQL
# recognises as a taint sanitiser) and a compiled :class:`re.Pattern` (for
# pre-dispatch validation in ``ValidatedServiceRoute``).
SAFE_ID_PATTERN: str = r"^[A-Za-z0-9_-]{1,128}$"
SAFE_ID_RE: re.Pattern[str] = re.compile(SAFE_ID_PATTERN)


class UnsafeIdError(ValueError):
    """Raised when an identifier fails ``SAFE_ID_RE`` validation."""


def validate_safe_id(value: str) -> str:
    """Validate a service/achievement identifier and return the sanitised value.

    Raises :class:`UnsafeIdError` if *value* does not match :data:`SAFE_ID_RE`.
    The return value is ``match.group(0)`` so downstream code operates on a
    string that static-analysis tools (SnykCode, CodeQL) can trace back to a
    regex sanitisation boundary — breaking the taint chain from the original
    HTTP parameter.
    """
    match = SAFE_ID_RE.fullmatch(value)
    if match is None:
        raise UnsafeIdError(f"Invalid identifier: {value!r}")
    return match.group(0)


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
