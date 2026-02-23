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

"""Unit tests for operate/services/service.py – no IPFS / Docker / blockchain required."""

import json
import typing as t
from pathlib import Path

import pytest
from autonomy.deploy.constants import (
    AGENT_KEYS_DIR,
    BENCHMARKS_DIR,
    LOG_DIR,
    PERSISTENT_DATA_DIR,
    TM_STATE_DIR,
    VENVS_DIR,
)

from operate.constants import AGENT_PERSISTENT_STORAGE_ENV_VAR, HEALTHCHECK_JSON
from operate.services.service import (
    AGENT_TYPE_IDS,
    SERVICE_CONFIG_PREFIX,
    Service,
    mkdirs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(path: Path, env_variables: t.Optional[t.Dict] = None) -> Service:
    """Create a minimal Service instance without loading from disk."""
    svc = object.__new__(Service)
    svc.path = path
    svc.env_variables = env_variables or {}
    return svc  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# mkdirs
# ---------------------------------------------------------------------------


class TestMkdirs:
    """Tests for the mkdirs() helper function (lines 132-146)."""

    def test_creates_build_directory(self, tmp_path: Path) -> None:
        """Test that mkdirs creates the top-level build directory."""
        build_dir = tmp_path / "build"
        mkdirs(build_dir)
        assert build_dir.exists()

    def test_creates_persistent_data_subdirectories(self, tmp_path: Path) -> None:
        """Test that mkdirs creates all required persistent data sub-directories."""
        build_dir = tmp_path / "build"
        mkdirs(build_dir)
        assert (build_dir / PERSISTENT_DATA_DIR).exists()
        assert (build_dir / PERSISTENT_DATA_DIR / LOG_DIR).exists()
        assert (build_dir / PERSISTENT_DATA_DIR / TM_STATE_DIR).exists()
        assert (build_dir / PERSISTENT_DATA_DIR / BENCHMARKS_DIR).exists()
        assert (build_dir / PERSISTENT_DATA_DIR / VENVS_DIR).exists()
        assert (build_dir / AGENT_KEYS_DIR).exists()

    def test_accepts_existing_build_directory(self, tmp_path: Path) -> None:
        """Test that mkdirs works when the build directory already exists."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        mkdirs(build_dir)  # should not raise
        assert build_dir.exists()


# ---------------------------------------------------------------------------
# Service.determine_agent_id
# ---------------------------------------------------------------------------


class TestDetermineAgentId:
    """Tests for Service.determine_agent_id (lines 812-821)."""

    def test_mech_name_returns_mech_id(self) -> None:
        """Test that service names containing 'mech' return mech agent ID."""
        assert Service.determine_agent_id("Mech Agent") == AGENT_TYPE_IDS["mech"]
        assert Service.determine_agent_id("MECH_SERVICE") == AGENT_TYPE_IDS["mech"]

    def test_optimus_name_returns_optimus_id(self) -> None:
        """Test that service names containing 'optimus' return optimus agent ID."""
        assert Service.determine_agent_id("Optimus Prime") == AGENT_TYPE_IDS["optimus"]
        assert (
            Service.determine_agent_id("OPTIMUS_SERVICE") == AGENT_TYPE_IDS["optimus"]
        )

    def test_modius_name_returns_modius_id(self) -> None:
        """Test that service names containing 'modius' return modius agent ID."""
        assert Service.determine_agent_id("Modius Service") == AGENT_TYPE_IDS["modius"]

    def test_unknown_name_falls_back_to_trader_id(self) -> None:
        """Test that unrecognised names return the trader agent ID."""
        assert Service.determine_agent_id("My Custom Agent") == AGENT_TYPE_IDS["trader"]
        assert Service.determine_agent_id("") == AGENT_TYPE_IDS["trader"]


# ---------------------------------------------------------------------------
# Service.get_new_service_config_id
# ---------------------------------------------------------------------------


class TestGetNewServiceConfigId:
    """Tests for Service.get_new_service_config_id (lines 979-985)."""

    def test_returns_string_with_prefix(self, tmp_path: Path) -> None:
        """Test that the returned ID starts with the expected prefix."""
        service_id = Service.get_new_service_config_id(tmp_path / "dummy_id")
        assert service_id.startswith(SERVICE_CONFIG_PREFIX)

    def test_returned_path_does_not_exist(self, tmp_path: Path) -> None:
        """Test that the returned ID corresponds to a non-existent path."""
        dummy = tmp_path / "dummy_id"
        service_id = Service.get_new_service_config_id(dummy)
        assert not (dummy.parent / service_id).exists()

    def test_unique_ids_across_calls(self, tmp_path: Path) -> None:
        """Test that successive calls return different IDs."""
        dummy = tmp_path / "dummy_id"
        ids = {Service.get_new_service_config_id(dummy) for _ in range(5)}
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# Service.get_latest_healthcheck
# ---------------------------------------------------------------------------


class TestGetLatestHealthcheck:
    """Tests for Service.get_latest_healthcheck (lines 988-998)."""

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        """Test that an empty dict is returned when healthcheck.json is absent."""
        svc = _make_service(tmp_path)
        result = svc.get_latest_healthcheck()
        assert result == {}

    def test_returns_parsed_json_when_file_exists(self, tmp_path: Path) -> None:
        """Test that the healthcheck JSON is returned when the file exists."""
        payload = {"status": "healthy", "count": 3}
        (tmp_path / HEALTHCHECK_JSON).write_text(
            json.dumps(payload), encoding="utf-8"
        )
        svc = _make_service(tmp_path)
        result = svc.get_latest_healthcheck()
        assert result == payload

    def test_returns_error_dict_on_invalid_json(self, tmp_path: Path) -> None:
        """Test that an error dict is returned when healthcheck.json is malformed."""
        (tmp_path / HEALTHCHECK_JSON).write_text("not-valid-json", encoding="utf-8")
        svc = _make_service(tmp_path)
        result = svc.get_latest_healthcheck()
        assert "error" in result


# ---------------------------------------------------------------------------
# Service.remove_latest_healthcheck
# ---------------------------------------------------------------------------


class TestRemoveLatestHealthcheck:
    """Tests for Service.remove_latest_healthcheck (lines 1001-1008)."""

    def test_deletes_existing_healthcheck_file(self, tmp_path: Path) -> None:
        """Test that an existing healthcheck.json is deleted."""
        hc_path = tmp_path / HEALTHCHECK_JSON
        hc_path.write_text("{}", encoding="utf-8")
        assert hc_path.exists()
        svc = _make_service(tmp_path)
        svc.remove_latest_healthcheck()
        assert not hc_path.exists()

    def test_no_error_when_file_absent(self, tmp_path: Path) -> None:
        """Test that no error is raised when healthcheck.json does not exist."""
        svc = _make_service(tmp_path)
        svc.remove_latest_healthcheck()  # should not raise


# ---------------------------------------------------------------------------
# Service.get_agent_performance
# ---------------------------------------------------------------------------


class TestGetAgentPerformance:
    """Tests for Service.get_agent_performance (lines 1010-1043)."""

    def test_returns_default_dict_when_no_file(self, tmp_path: Path) -> None:
        """Test that defaults are returned when agent_performance.json is absent."""
        svc = _make_service(
            tmp_path,
            env_variables={
                AGENT_PERSISTENT_STORAGE_ENV_VAR: {"value": str(tmp_path)}
            },
        )
        result = svc.get_agent_performance()
        assert result["timestamp"] is None
        assert result["metrics"] == []
        assert result["last_activity"] is None
        assert result["last_chat_message"] is None

    def test_reads_and_merges_performance_file(self, tmp_path: Path) -> None:
        """Test that agent_performance.json data is merged into the defaults."""
        perf_data = {"timestamp": 1234567890, "metrics": [{"name": "trades", "value": 5}]}
        (tmp_path / "agent_performance.json").write_text(
            json.dumps(perf_data), encoding="utf-8"
        )
        svc = _make_service(
            tmp_path,
            env_variables={
                AGENT_PERSISTENT_STORAGE_ENV_VAR: {"value": str(tmp_path)}
            },
        )
        result = svc.get_agent_performance()
        assert result["timestamp"] == 1234567890
        assert result["metrics"] == [{"name": "trades", "value": 5}]

    def test_returns_defaults_on_invalid_json(self, tmp_path: Path) -> None:
        """Test that defaults are returned when agent_performance.json is malformed."""
        (tmp_path / "agent_performance.json").write_text(
            "invalid-json", encoding="utf-8"
        )
        svc = _make_service(
            tmp_path,
            env_variables={
                AGENT_PERSISTENT_STORAGE_ENV_VAR: {"value": str(tmp_path)}
            },
        )
        result = svc.get_agent_performance()
        assert result["timestamp"] is None

    def test_returns_defaults_on_non_dict_root(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that defaults are returned when agent_performance.json root is not dict."""
        (tmp_path / "agent_performance.json").write_text(
            json.dumps([1, 2, 3]), encoding="utf-8"
        )
        svc = _make_service(
            tmp_path,
            env_variables={
                AGENT_PERSISTENT_STORAGE_ENV_VAR: {"value": str(tmp_path)}
            },
        )
        result = svc.get_agent_performance()
        assert result["timestamp"] is None

    def test_env_variable_missing_uses_cwd_fallback(self, tmp_path: Path) -> None:
        """Test that missing STORE_PATH env var falls back to current directory."""
        svc = _make_service(tmp_path, env_variables={})
        result = svc.get_agent_performance()
        # Should not raise; just returns defaults if file not found in cwd
        assert "timestamp" in result
        assert "metrics" in result
