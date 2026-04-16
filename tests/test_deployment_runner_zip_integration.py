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

"""Integration tests for zip functionality in deployment_runner."""

import json
from pathlib import Path
from platform import system
from typing import Any
from unittest.mock import patch

import pytest

from operate.services.agent_assets import AgentAssetManager
from operate.services.deployment_runner import HostPythonHostDeploymentRunner

from tests.constants import RUNNING_IN_CI


def _create_test_service_config(service_dir: Path, version: str = "v0.31.3") -> None:
    """Create a minimal service config.json."""
    config = {
        "agent_release": {
            "is_aea": True,
            "repository": {
                "owner": "valory-xyz",
                "name": "trader",
                "version": version,
            },
        },
    }
    (service_dir / "config.json").write_text(json.dumps(config))


def test_setup_agent_uses_zip(tmp_path: Path) -> None:
    """Test that _setup_agent uses zip extraction instead of aea fetch."""
    # Arrange
    working_dir = tmp_path / "deployment"
    working_dir.mkdir()
    service_dir = working_dir.parent

    # Create complete file structure
    (working_dir / "agent.json").write_text('{"AEA_AGENT": "valory/trader:0.1.0"}')
    (working_dir / "ethereum_private_key.txt").write_text("private_key")
    _create_test_service_config(service_dir)

    # Create agent_cache directory and dummy zip file
    agent_cache_dir = service_dir / "agent_cache"
    agent_cache_dir.mkdir()
    dummy_zip_path = agent_cache_dir / "agent.zip"
    dummy_zip_path.write_bytes(b"dummy zip content")

    # Create a concrete runner
    runner = HostPythonHostDeploymentRunner(working_dir, is_aea=True)

    # Mock only network dependencies, let file operations work normally
    with patch.object(
        AgentAssetManager, "get_agent_code_path"
    ) as mock_get_path, patch.object(
        AgentAssetManager, "extract_agent_zip"
    ) as mock_extract, patch.object(
        runner, "_run_aea_command"
    ) as mock_aea_cmd, patch.object(
        runner, "_prepare_agent_env"
    ) as mock_prepare_env:

        # Setup mocks
        mock_get_path.return_value = str(dummy_zip_path)
        mock_extract.return_value = None
        mock_prepare_env.return_value = {"AEA_AGENT": "valory/trader:0.1.0"}

        # Create agent directory after extraction mock with aea-config.yaml
        def create_agent_dir(*args: Any, **kwargs: Any) -> None:
            agent_dir = working_dir / "agent"
            agent_dir.mkdir(exist_ok=True)
            # Create minimal aea-config.yaml to avoid "aea-config.yaml not found" error
            (agent_dir / "aea-config.yaml").write_text("agent_name: test_agent\n")
            return None

        mock_extract.side_effect = create_agent_dir

        # Also mock _run_cmd to avoid actual aea install command
        with patch.object(runner, "_run_cmd"):
            # Act
            runner._setup_agent(password="test")  # nosec B106

            # Assert
            # 1. get_agent_code_path called with service_dir (check keyword argument)
            mock_get_path.assert_called_once()
            call_args = mock_get_path.call_args
            assert "service_dir" in call_args.kwargs
            assert call_args.kwargs["service_dir"] == service_dir

            # 2. extract_agent_zip called with correct args
            mock_extract.assert_called_once()
            call_args = mock_extract.call_args
            assert str(call_args[0][0]) == str(dummy_zip_path)
            assert str(call_args[0][1]) == str(working_dir / "agent")

            # 3. No aea fetch command
            fetch_calls = [
                c
                for c in mock_aea_cmd.call_args_list
                if len(c[0]) > 1 and c[0][1] == "fetch"
            ]
            assert len(fetch_calls) == 0

            # 4. Check remove-key calls (tolerant to errors)
            remove_key_calls = [
                c
                for c in mock_aea_cmd.call_args_list
                if len(c[0]) > 1 and c[0][1] == "remove-key"
            ]
            assert len(remove_key_calls) >= 2  # ethereum and ethereum --connection

            # 5. Check add-key calls
            add_key_calls = [
                c
                for c in mock_aea_cmd.call_args_list
                if len(c[0]) > 1 and c[0][1] == "add-key"
            ]
            assert len(add_key_calls) == 2


@pytest.mark.skipif(
    RUNNING_IN_CI and system() == "Darwin",
    reason="GitHub API download tests make live HTTP requests that are unreliable from macOS CI runners.",
)
class TestRealGitHubDownload:
    """Tests with real GitHub API and zip downloads."""

    @pytest.mark.integration
    @pytest.mark.github
    def test_real_github_download_and_extract(self, tmp_path: Path) -> None:
        """Test real GitHub download and extraction of agent.zip."""
        # Arrange
        service_dir = tmp_path / "service"
        service_dir.mkdir()
        _create_test_service_config(service_dir, version="v0.31.3")

        # Act - get agent code path (will download from GitHub)
        agent_zip_path = AgentAssetManager.get_agent_code_path(service_dir)

        # Assert - file exists
        agent_zip_path_obj = Path(agent_zip_path)
        assert (
            agent_zip_path_obj.exists()
        ), f"Agent zip not downloaded: {agent_zip_path}"
        assert agent_zip_path_obj.stat().st_size > 0, "Downloaded file is empty"

        # Test extraction
        extract_dir = tmp_path / "extracted"
        AgentAssetManager.extract_agent_zip(agent_zip_path_obj, extract_dir)

        # Assert - files extracted
        assert extract_dir.exists(), "Extraction directory not created"
        assert (extract_dir / "aea-config.yaml").exists(), "aea-config.yaml not found"

        # Check some expected files
        aea_config = (extract_dir / "aea-config.yaml").read_text()
        assert "agent_name" in aea_config, "aea-config.yaml doesn't contain agent_name"

    @pytest.mark.integration
    @pytest.mark.github
    def test_sha256_verification_and_redownload(self, tmp_path: Path) -> None:
        """Test that changing a byte triggers redownload."""
        # Arrange
        service_dir = tmp_path / "service"
        service_dir.mkdir()
        _create_test_service_config(service_dir, version="v0.31.3")

        # First download
        agent_zip_path = AgentAssetManager.get_agent_code_path(service_dir)
        agent_zip_path_obj = Path(agent_zip_path)

        # Get original hash and size
        original_size = agent_zip_path_obj.stat().st_size
        original_hash = AgentAssetManager.get_local_file_sha256(agent_zip_path_obj)

        # Corrupt the file (change one byte)
        with open(agent_zip_path_obj, "r+b") as f:
            f.seek(0)
            f.write(b"X")  # Change first byte

        # Second call should redownload
        agent_zip_path2 = AgentAssetManager.get_agent_code_path(service_dir)

        # Get new hash
        new_hash = AgentAssetManager.get_local_file_sha256(Path(agent_zip_path2))
        new_size = Path(agent_zip_path2).stat().st_size

        # Assert - file should be redownloaded (hash should match original)
        assert new_hash == original_hash, "File was not redownloaded after corruption"
        assert new_size == original_size, "File size doesn't match after redownload"

    @pytest.mark.integration
    @pytest.mark.github
    @pytest.mark.slow
    def test_full_setup_agent_with_real_download(self, tmp_path: Path) -> None:
        """Full integration test with real GitHub download."""
        # Arrange
        working_dir = tmp_path / "deployment"
        working_dir.mkdir()
        service_dir = working_dir.parent

        # Create complete file structure
        (working_dir / "agent.json").write_text('{"AEA_AGENT": "valory/trader:0.1.0"}')
        (working_dir / "ethereum_private_key.txt").write_text("private_key")
        _create_test_service_config(service_dir, version="v0.31.3")

        # Create a concrete runner
        runner = HostPythonHostDeploymentRunner(working_dir, is_aea=True)

        # Mock only aea commands to avoid real installations
        with patch.object(runner, "_run_aea_command") as mock_aea_cmd, patch.object(
            runner, "_run_cmd"
        ), patch.object(runner, "_prepare_agent_env") as mock_prepare_env:

            mock_prepare_env.return_value = {"AEA_AGENT": "valory/trader:0.1.0"}

            # Act - this will do real GitHub download and extraction
            runner._setup_agent(password="test")  # nosec B106

            # Assert
            # 1. Check agent.zip was downloaded
            agent_cache_dir = service_dir / "agent_cache"
            agent_zip_path = agent_cache_dir / "agent.zip"
            assert agent_zip_path.exists(), "agent.zip not downloaded"

            # 2. Check agent directory was created
            agent_dir = working_dir / "agent"
            assert agent_dir.exists(), "agent directory not created"

            # 3. Check aea-config.yaml exists
            assert (
                agent_dir / "aea-config.yaml"
            ).exists(), "aea-config.yaml not extracted"

            # 4. Check no aea fetch command
            fetch_calls = [
                c
                for c in mock_aea_cmd.call_args_list
                if len(c[0]) > 1 and c[0][1] == "fetch"
            ]
            assert (
                len(fetch_calls) == 0
            ), "aea fetch was called (should use zip instead)"

            # 5. Check remove-key and add-key calls
            remove_key_calls = [
                c
                for c in mock_aea_cmd.call_args_list
                if len(c[0]) > 1 and c[0][1] == "remove-key"
            ]
            assert len(remove_key_calls) >= 2

            add_key_calls = [
                c
                for c in mock_aea_cmd.call_args_list
                if len(c[0]) > 1 and c[0][1] == "add-key"
            ]
            assert len(add_key_calls) == 2
