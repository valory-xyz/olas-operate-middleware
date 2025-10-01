# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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
"""Test contracts."""

import importlib.util
import inspect
import pkgutil
from pathlib import Path


def test_data_contracts_sanity() -> None:
    """Sanity test for data contracts.

    Iterates through all modules under `operate/data/contracts`, dynamically imports
    the first class object defined in each `contract.py`, and ensures that
    `from_dir` can be called to instantiate it (meaning the contract package is well-formed).
    """

    root = Path(__file__).parent.parent / "operate" / "data" / "contracts"
    assert root.is_dir(), f"Contracts directory not found at: {root}"

    # Discover all immediate subpackages that contain a contract.py
    subpackages = [
        name
        for _, name, is_pkg in pkgutil.iter_modules([str(root)])
        if is_pkg and (root / name / "contract.py").is_file()
    ]

    assert (
        subpackages
    ), "No contract subpackages discovered; expected at least one for sanity test."

    for name in subpackages:
        contract_file = root / name / "contract.py"
        spec = importlib.util.spec_from_file_location(
            f"operate.data.contracts.{name}.contract", contract_file
        )
        assert spec and spec.loader, f"Unable to create spec for {contract_file}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore

        # Find the first class defined in this module (skip imported ones)
        classes = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__
        ]
        assert classes, f"No classes defined in {contract_file}"
        contract_class = classes[0]

        # Ensure it has from_dir. If not, skip with a helpful assertion message.
        assert hasattr(
            contract_class, "from_dir"
        ), f"Class {contract_class.__name__} missing from_dir() method"

        instance = contract_class.from_dir(str(root / name))  # type: ignore
        assert (
            instance is not None
        ), f"from_dir returned None for {contract_class.__name__} in {name}"

        # Basic attribute sanity checks (optional, but helpful)
        assert hasattr(
            instance, "contract_id"
        ), f"Instance of {contract_class.__name__} missing contract_id"
