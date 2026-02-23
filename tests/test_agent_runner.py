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

"""Tests for agent runner module."""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from operate.services.agent_runner import (
    AgentRelease,
    AgentRunnerManager,
    get_agent_runner_path,
)


class TestAgentRelease:
    """Tests for AgentRelease dataclass."""

    def test_release_url(self) -> None:
        """Test release URL construction."""
        ar = AgentRelease(
            owner="valory", repo="open-aea", release="v1.0.0", is_aea=True
        )
        assert ar.release_url == (
            "https://api.github.com/repos/valory/open-aea/releases/tags/v1.0.0"
        )

    def test_get_url_and_hash_success(self) -> None:
        """Test get_url_and_hash returns correct url and hash."""
        ar = AgentRelease(owner="valory", repo="repo", release="v1.0.0", is_aea=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "assets": [
                {
                    "name": "agent_runner_linux_x64",
                    "digest": "sha256:abc123",
                    "browser_download_url": "http://example.com/runner",
                },
                {
                    "name": "other_file",
                    "digest": "sha256:other",
                    "browser_download_url": "http://example.com/other",
                },
            ]
        }
        with patch(
            "operate.services.agent_runner.requests.get",
            return_value=mock_response,
        ):
            url, hash_ = ar.get_url_and_hash("agent_runner_linux_x64")
        assert url == "http://example.com/runner"
        assert hash_ == "sha256:abc123"

    def test_get_url_and_hash_not_found(self) -> None:
        """Test get_url_and_hash raises ValueError when asset not found."""
        ar = AgentRelease(owner="valory", repo="repo", release="v1.0.0", is_aea=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"assets": []}
        with patch(
            "operate.services.agent_runner.requests.get",
            return_value=mock_response,
        ):
            with pytest.raises(ValueError, match="missing_file not found"):
                ar.get_url_and_hash("missing_file")


class TestAgentRunnerManagerExecutableName:
    """Tests for AgentRunnerManager.get_agent_runner_executable_name."""

    def test_darwin_arm64(self) -> None:
        """Test executable name for macOS arm64."""
        with patch("platform.system", return_value="Darwin"), patch(
            "platform.machine", return_value="arm64"
        ):
            name = AgentRunnerManager.get_agent_runner_executable_name()
        assert "macos" in name
        assert "arm64" in name

    def test_darwin_x86_64(self) -> None:
        """Test executable name for macOS x86_64."""
        with patch("platform.system", return_value="Darwin"), patch(
            "platform.machine", return_value="x86_64"
        ):
            name = AgentRunnerManager.get_agent_runner_executable_name()
        assert "macos" in name
        assert "x64" in name

    def test_linux_x86_64(self) -> None:
        """Test executable name for Linux x86_64."""
        with patch("platform.system", return_value="Linux"), patch(
            "platform.machine", return_value="x86_64"
        ):
            name = AgentRunnerManager.get_agent_runner_executable_name()
        assert "linux" in name
        assert "x64" in name

    def test_windows_x86_64(self) -> None:
        """Test executable name for Windows x86_64."""
        with patch("platform.system", return_value="Windows"), patch(
            "platform.machine", return_value="x86_64"
        ):
            name = AgentRunnerManager.get_agent_runner_executable_name()
        assert "windows" in name
        assert "x64" in name
        assert name.endswith(".exe")

    def test_unsupported_platform_raises(self) -> None:
        """Test that an unsupported platform raises ValueError."""
        with patch("platform.system", return_value="FreeBSD"), patch(
            "platform.machine", return_value="x86_64"
        ):
            with pytest.raises(ValueError, match="Platform not supported"):
                AgentRunnerManager.get_agent_runner_executable_name()

    def test_linux_arm64_raises(self) -> None:
        """Test that Linux arm64 raises ValueError."""
        with patch("platform.system", return_value="Linux"), patch(
            "platform.machine", return_value="arm64"
        ):
            with pytest.raises(ValueError, match="not supported"):
                AgentRunnerManager.get_agent_runner_executable_name()

    def test_unsupported_arch_raises(self) -> None:
        """Test that an unsupported architecture raises ValueError."""
        with patch("platform.system", return_value="Linux"), patch(
            "platform.machine", return_value="mips"
        ):
            with pytest.raises(ValueError, match="unsupported arch"):
                AgentRunnerManager.get_agent_runner_executable_name()


class TestAgentRunnerManagerMethods:
    """Tests for other AgentRunnerManager methods."""

    def test_parse_agent(self) -> None:
        """Test parsing an agent public ID string."""
        author, name = AgentRunnerManager.parse_agent("valory/my_agent:0.1.0")
        assert author == "valory"
        assert name == "my_agent"

    def test_download_file_writes_chunks(self, tmp_path: Path) -> None:
        """Test that download_file writes all chunks to disk."""
        save_path = tmp_path / "downloaded"
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        with patch(
            "operate.services.agent_runner.requests.get",
            return_value=mock_response,
        ):
            AgentRunnerManager.download_file("http://example.com/file", save_path)
        assert save_path.read_bytes() == b"chunk1chunk2"

    def test_download_file_raises_on_request_error(self, tmp_path: Path) -> None:
        """Test that download_file propagates request exceptions."""
        save_path = tmp_path / "downloaded"
        with patch(
            "operate.services.agent_runner.requests.get",
            side_effect=requests.exceptions.ConnectionError("failed"),
        ):
            with pytest.raises(requests.exceptions.ConnectionError):
                AgentRunnerManager.download_file(
                    "http://example.com/file", save_path
                )

    def test_get_local_file_sha256(self, tmp_path: Path) -> None:
        """Test SHA-256 hashing of a local file."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"hello world")
        result = AgentRunnerManager.get_local_file_sha256(test_file)
        expected = "sha256:" + hashlib.sha256(b"hello world").hexdigest()
        assert result == expected

    def test_get_agent_release_from_service_dir(self, tmp_path: Path) -> None:
        """Test loading agent release config from service directory."""
        config = {
            "agent_release": {
                "is_aea": True,
                "repository": {
                    "owner": "valory",
                    "name": "my_repo",
                    "version": "v2.0.0",
                },
            }
        }
        (tmp_path / "config.json").write_text(json.dumps(config))
        release = AgentRunnerManager.get_agent_release_from_service_dir(tmp_path)
        assert isinstance(release, AgentRelease)
        assert release.owner == "valory"
        assert release.repo == "my_repo"
        assert release.release == "v2.0.0"
        assert release.is_aea is True

    def test_get_agent_release_missing_key_raises(self, tmp_path: Path) -> None:
        """Test that a missing agent_release key raises ValueError."""
        config = {"other_key": "value"}
        (tmp_path / "config.json").write_text(json.dumps(config))
        with pytest.raises(ValueError, match="Agent release details are not found"):
            AgentRunnerManager.get_agent_release_from_service_dir(tmp_path)

    def test_update_agent_runner_hash_match_skips_download(
        self, tmp_path: Path
    ) -> None:
        """Test that a matching hash skips the download."""
        target = tmp_path / "runner"
        target.write_bytes(b"binary content")
        mock_release = MagicMock()
        mock_release.get_url_and_hash.return_value = (
            "http://example.com/runner",
            "sha256:HASH",
        )
        with patch.object(
            AgentRunnerManager, "get_local_file_sha256", return_value="sha256:HASH"
        ), patch.object(AgentRunnerManager, "download_file") as mock_dl:
            AgentRunnerManager.update_agent_runner(target, "runner", mock_release)
        mock_dl.assert_not_called()

    def test_update_agent_runner_hash_mismatch_triggers_download(
        self, tmp_path: Path
    ) -> None:
        """Test that a hash mismatch triggers a download."""
        target = tmp_path / "runner"
        target.write_bytes(b"old content")
        mock_release = MagicMock()
        mock_release.get_url_and_hash.return_value = (
            "http://example.com/runner",
            "sha256:NEW",
        )
        # shutil.copy2 is mocked; target already exists so chmod works on POSIX
        with patch.object(
            AgentRunnerManager, "get_local_file_sha256", return_value="sha256:OLD"
        ), patch.object(AgentRunnerManager, "download_file") as mock_dl, patch(
            "operate.services.agent_runner.shutil.copy2"
        ):
            AgentRunnerManager.update_agent_runner(target, "runner", mock_release)
        mock_dl.assert_called_once()

    def test_update_agent_runner_file_missing_triggers_download(
        self, tmp_path: Path
    ) -> None:
        """Test that a missing target file triggers a download."""
        target = tmp_path / "runner"  # does not exist
        mock_release = MagicMock()
        mock_release.get_url_and_hash.return_value = (
            "http://example.com/runner",
            "sha256:HASH",
        )

        # shutil.copy2 side-effect creates the target so that chmod succeeds
        def _create_target(src: Path, dst: Path) -> None:
            dst.write_bytes(b"downloaded")

        with patch.object(AgentRunnerManager, "download_file") as mock_dl, patch(
            "operate.services.agent_runner.shutil.copy2",
            side_effect=_create_target,
        ):
            AgentRunnerManager.update_agent_runner(target, "runner", mock_release)
        mock_dl.assert_called_once()

    def test_update_agent_runner_download_error_removes_target(
        self, tmp_path: Path
    ) -> None:
        """Test that a download error causes the target file to be removed."""
        target = tmp_path / "runner"
        target.write_bytes(b"old content")
        mock_release = MagicMock()
        mock_release.get_url_and_hash.return_value = (
            "http://example.com/runner",
            "sha256:NEW",
        )
        with patch.object(
            AgentRunnerManager, "get_local_file_sha256", return_value="sha256:OLD"
        ), patch.object(
            AgentRunnerManager,
            "download_file",
            side_effect=RuntimeError("download failed"),
        ):
            with pytest.raises(RuntimeError, match="download failed"):
                AgentRunnerManager.update_agent_runner(
                    target, "runner", mock_release
                )
        assert not target.exists()

    def test_get_agent_runner_path_class_method(self, tmp_path: Path) -> None:
        """Test AgentRunnerManager.get_agent_runner_path returns the correct path."""
        config = {
            "agent_release": {
                "is_aea": True,
                "repository": {
                    "owner": "valory",
                    "name": "repo",
                    "version": "v1.0.0",
                },
            }
        }
        (tmp_path / "config.json").write_text(json.dumps(config))
        with patch.object(
            AgentRunnerManager,
            "get_agent_runner_executable_name",
            return_value="runner_linux_x64",
        ), patch.object(AgentRunnerManager, "update_agent_runner"):
            result = AgentRunnerManager.get_agent_runner_path(tmp_path)
        assert result == str(tmp_path / "runner_linux_x64")

    def test_get_agent_runner_path_module_function(self, tmp_path: Path) -> None:
        """Test module-level get_agent_runner_path delegates correctly."""
        config = {
            "agent_release": {
                "is_aea": True,
                "repository": {
                    "owner": "valory",
                    "name": "repo",
                    "version": "v1.0.0",
                },
            }
        }
        (tmp_path / "config.json").write_text(json.dumps(config))
        with patch.object(
            AgentRunnerManager,
            "get_agent_runner_executable_name",
            return_value="runner_linux_x64",
        ), patch.object(AgentRunnerManager, "update_agent_runner"):
            result = get_agent_runner_path(tmp_path)
        assert result == str(tmp_path / "runner_linux_x64")
