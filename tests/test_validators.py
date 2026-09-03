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

"""Tests for operate/validators.py."""

import pytest

from operate.validators import validated_safe_id


def test_validated_safe_id_rejects_invalid_input() -> None:
    """validated_safe_id raises ValueError for IDs containing illegal chars."""
    with pytest.raises(ValueError, match="Unsafe identifier"):
        validated_safe_id("bad.id")
