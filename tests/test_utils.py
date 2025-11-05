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

import threading
import time
import typing as t

import pytest
from deepdiff import DeepDiff

from operate.utils import SingletonMeta, merge_sum_dicts, subtract_dicts


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


class TestSingletonMeta:
    """Tests for SingletonMeta metaclass."""

    def test_singleton_instance_creation(self) -> None:
        """Test that singleton classes create only one instance."""

        class TestSingleton(metaclass=SingletonMeta):
            def __init__(self, value: int = 0) -> None:
                self.value = value

        # Create multiple instances
        instance1 = TestSingleton(42)
        instance2 = TestSingleton(100)  # This should be ignored
        instance3 = TestSingleton()

        # All should be the same instance
        assert instance1 is instance2
        assert instance2 is instance3
        assert instance1 is instance3

        # Value should be from first instantiation
        assert instance1.value == 42
        assert instance2.value == 42
        assert instance3.value == 42

    def test_different_singleton_classes_have_different_instances(self) -> None:
        """Test that different singleton classes maintain separate instances."""

        class SingletonA(metaclass=SingletonMeta):
            def __init__(self, name: str = "A") -> None:
                self.name = name

        class SingletonB(metaclass=SingletonMeta):
            def __init__(self, name: str = "B") -> None:
                self.name = name

        instance_a1 = SingletonA("First A")
        instance_b1 = SingletonB("First B")
        instance_a2 = SingletonA("Second A")
        instance_b2 = SingletonB("Second B")

        # Same class instances should be identical
        assert instance_a1 is instance_a2
        assert instance_b1 is instance_b2

        # Different class instances should be different
        assert instance_a1 is not instance_b1

        # Values should be from first instantiation
        assert instance_a1.name == "First A"
        assert instance_b1.name == "First B"

    def test_concurrent_singleton_instantiation(self) -> None:
        """Test that concurrent instantiation still results in a single instance."""

        class ConcurrentInstantiation(metaclass=SingletonMeta):
            def __init__(self, thread_id: int) -> None:
                self.thread_id = thread_id
                self.instantiation_time = time.time()

        instances = []
        threads = []
        num_threads = 5

        def create_instance(thread_id: int) -> None:
            instance = ConcurrentInstantiation(thread_id)
            instances.append(instance)

        # Create and start threads
        for i in range(num_threads):
            thread = threading.Thread(target=create_instance, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All instances should be the same object
        first_instance = instances[0]
        for instance in instances[1:]:
            assert instance is first_instance

        # Should have the thread_id from whichever thread got there first
        assert hasattr(first_instance, "thread_id")
        assert isinstance(first_instance.thread_id, int)

    def test_special_methods_not_wrapped(self) -> None:
        """Test that special methods (dunder methods) are not wrapped."""

        class SpecialMethodsSingleton(metaclass=SingletonMeta):
            def __init__(self, value: str = "test") -> None:
                self.value = value

            def __str__(self) -> str:
                return f"SpecialMethodsSingleton({self.value})"

            def __repr__(self) -> str:
                return f"SpecialMethodsSingleton(value='{self.value}')"

            def regular_method(self) -> str:
                return "regular"

        instance = SpecialMethodsSingleton("hello")

        # Special methods should work normally
        assert str(instance) == "SpecialMethodsSingleton(hello)"
        assert "SpecialMethodsSingleton(value='hello')" in repr(instance)

        # Regular methods should be wrapped (we can't easily test the wrapping itself,
        # but we can test that they still work)
        assert instance.regular_method() == "regular"

    def test_inheritance_with_singleton(self) -> None:
        """Test that inheritance works correctly with singleton metaclass."""

        class BaseSingleton(metaclass=SingletonMeta):
            def __init__(self, base_value: int = 1) -> None:
                self.base_value = base_value

            def base_method(self) -> str:
                return "base"

        class DerivedSingleton(BaseSingleton):
            def __init__(self, base_value: int = 1, derived_value: int = 2) -> None:
                super().__init__(base_value)
                self.derived_value = derived_value

            def derived_method(self) -> str:
                return "derived"

        # Each class should have its own singleton instance
        base1 = BaseSingleton(10)
        base2 = BaseSingleton(20)
        derived1 = DerivedSingleton(30, 40)
        derived2 = DerivedSingleton(50, 60)

        # Same class instances should be identical
        assert base1 is base2
        assert derived1 is derived2

        # Different class instances should be different
        assert base1 is not derived1

        # Check values from first instantiation
        assert base1.base_value == 10
        assert derived1.base_value == 30
        assert derived1.derived_value == 40

    def test_singleton_with_no_init_args(self) -> None:
        """Test singleton behavior with classes that have no __init__ arguments."""

        class NoArgsSingleton(metaclass=SingletonMeta):
            def __init__(self) -> None:
                self.created_at = time.time()

            def get_time(self) -> float:
                return self.created_at

        instance1 = NoArgsSingleton()
        time.sleep(0.001)  # Small delay
        instance2 = NoArgsSingleton()

        assert instance1 is instance2
        assert instance1.get_time() == instance2.get_time()
