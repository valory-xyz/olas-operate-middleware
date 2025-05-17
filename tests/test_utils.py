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

"""Tests for utils module."""

import typing as t

import pytest
from deepdiff import DeepDiff

from operate.utils import merge_sum_dicts, subtract_dicts


class TestUtils:
    """TestUtils"""

    @pytest.mark.parametrize(
        ("a", "b", "c", "d", "expected_result"),
        [
            ({}, {}, {}, {}, {}),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b1": {"c1": 3, "c2": 4}}},
                {},
                {},
                {"a1": {"b1": {"c1": 4, "c2": 6}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b1": {"c1": 3, "c3": 4}}},
                {},
                {},
                {"a1": {"b1": {"c1": 4, "c2": 2, "c3": 4}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b2": {"c1": 3, "c3": 4}}},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}, "b2": {"c1": 3, "c3": 4}}},
            ),
            (
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b2": 5}},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}, "b2": 5}},
            ),
            (
                {"a1": {"b2": 5}},
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {},
                {},
                {"a1": {"b1": {"c1": 1, "c2": 2}, "b2": 5}},
            ),
        ],
    )
    def test_merge_sum_dicts(
        self, a: t.Dict, b: t.Dict, c: t.Dict, d: t.Dict, expected_result: t.Dict
    ) -> None:
        """test_merge_sum_dicts"""
        result = merge_sum_dicts(a, b, c, d)
        diff = DeepDiff(result, expected_result)
        if diff:
            print(diff)
        assert not diff, "Test failed."

    @pytest.mark.parametrize(
        ("a", "b", "expected_result"),
        [
            ({}, {}, {}),
            (
                {"a1": {"b1": {"c1": 10, "c2": 20}}},
                {"a1": {"b1": {"c1": 1, "c2": 2}}},
                {"a1": {"b1": {"c1": 9, "c2": 18}}},
            ),
            (
                {"a1": {"b1": {"c1": 5, "c2": 20}}},
                {"a1": {"b1": {"c1": 10, "c2": 0}}},
                {"a1": {"b1": {"c1": 0, "c2": 20}}},
            ),
            (
                {"a1": {"b1": {"c1": 10, "c2": 20}, "b2": {"d1": 5, "d4": 20}}},
                {"a1": {"b1": {"c1": 5, "c2": 0}}},
                {"a1": {"b1": {"c1": 5, "c2": 20}, "b2": {"d1": 5, "d4": 20}}},
            ),
            (
                {"a1": {"b1": {"c1": 10, "c2": 20}}},
                {"a1": {"b1": {"c1": 1}}},
                {"a1": {"b1": {"c1": 9, "c2": 20}}},
            ),
            (
                {"a1": {"b1": {"c1": 10}}},
                {"a1": {"b1": {"c1": 1, "c2": 20}}},
                {"a1": {"b1": {"c1": 9, "c2": 0}}},
            ),
        ],
    )
    def test_subtract_dicts(
        self, a: t.Dict, b: t.Dict, expected_result: t.Dict
    ) -> None:
        """test_subtract_dicts"""
        result = subtract_dicts(a, b)
        diff = DeepDiff(result, expected_result)
        if diff:
            print(diff)
        assert not diff, "Test failed."
