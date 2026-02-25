"""
Error path tests for service operations.

Part of Phase 2.3: Error Path Testing - Tests verify that ACTUAL implementations
handle errors gracefully. Only includes tests of real implementation error handling.
"""

import json
from pathlib import Path

import pytest


class TestServiceLoadErrors:
    """Test Service.load() with various error conditions."""

    def test_service_load_corrupted_json(self, tmp_path: Path) -> None:
        """Test Service.load() handles corrupted config.json."""
        from operate.services.service import Service

        # Service.load() expects config.json
        service_dir = tmp_path / "sc-test-service-id"
        service_dir.mkdir()
        config_json = service_dir / "config.json"
        config_json.write_text("{invalid json content", encoding="utf-8")

        # Loading should raise JSONDecodeError
        with pytest.raises(json.JSONDecodeError):
            Service.load(service_dir)

    def test_service_load_missing_config_file(self, tmp_path: Path) -> None:
        """Test Service.load() handles missing config.json."""
        from operate.services.service import Service

        service_dir = tmp_path / "sc-test-service-id"
        service_dir.mkdir()
        # Don't create config.json

        # Loading should raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            Service.load(service_dir)

    def test_service_load_missing_required_fields(self, tmp_path: Path) -> None:
        """Test Service.load() handles config with missing required fields."""
        from operate.services.service import Service

        service_dir = tmp_path / "sc-test-service-id"
        service_dir.mkdir()
        config_json = service_dir / "config.json"

        # Write config with missing required fields
        config_json.write_text(
            json.dumps({"name": "test_service"}),  # Missing many required fields
            encoding="utf-8",
        )

        # Loading should raise KeyError for missing fields
        with pytest.raises(KeyError):
            Service.load(service_dir)
