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

from operate.operate_types import Version


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
