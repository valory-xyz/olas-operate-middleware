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

"""Unit tests for operate/validators.py."""

import pytest

from operate.validators import UnsafeIdError, validate_safe_id


class TestValidateSafeId:
    """Tests for the validate_safe_id function."""

    def test_valid_simple_id(self) -> None:
        """A simple alphanumeric ID passes validation and is returned."""
        assert validate_safe_id("sc-abc123") == "sc-abc123"

    def test_valid_id_with_underscores(self) -> None:
        """An ID with underscores passes validation."""
        assert validate_safe_id("my_service_config") == "my_service_config"

    def test_invalid_id_with_dot_raises(self) -> None:
        """An ID containing a dot is rejected."""
        with pytest.raises(UnsafeIdError, match="Invalid identifier"):
            validate_safe_id("bad.id")

    def test_invalid_id_with_path_traversal_raises(self) -> None:
        """An ID containing path traversal is rejected."""
        with pytest.raises(UnsafeIdError, match="Invalid identifier"):
            validate_safe_id("../etc/passwd")

    def test_empty_string_raises(self) -> None:
        """An empty string is rejected."""
        with pytest.raises(UnsafeIdError, match="Invalid identifier"):
            validate_safe_id("")

    def test_id_exceeding_max_length_raises(self) -> None:
        """An ID longer than 128 characters is rejected."""
        with pytest.raises(UnsafeIdError, match="Invalid identifier"):
            validate_safe_id("a" * 129)

    def test_id_at_max_length_passes(self) -> None:
        """An ID at exactly 128 characters passes."""
        long_id = "a" * 128
        assert validate_safe_id(long_id) == long_id
