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

"""Unit tests for operate/services/agent_assets.py."""

import hashlib
import json
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
import requests

from operate.services.agent_assets import (
    AgentAssetManager,
    AgentRelease,
    clear_release_metadata_cache,
)

VALID_RELEASE_DATA = {
    "assets": [
        {
            "name": "agent.zip",
            "digest": "sha256:abc123",
            "browser_download_url": "https://example.com/agent.zip",
        }
    ]
}

SERVICE_CONFIG = {
    "agent_release": {
        "is_aea": True,
        "repository": {
            "owner": "valory-xyz",
            "name": "trader",
            "version": "v0.40.7",
        },
    }
}


@pytest.fixture(autouse=True)
def _clear_cache() -> Generator[None, None, None]:
    """Clear the release metadata cache before each test."""
    clear_release_metadata_cache()
    yield
    clear_release_metadata_cache()


class TestGetUrlAndHash:
    """Tests for AgentRelease.get_url_and_hash."""

    def _make_release(self) -> AgentRelease:
        return AgentRelease(
            owner="valory-xyz", repo="trader", release="v0.40.7", is_aea=True
        )

    @patch("operate.services.agent_assets.requests.get")
    def test_200_with_assets(self, mock_get: MagicMock) -> None:
        """200 response with valid assets list returns (url, hash)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = VALID_RELEASE_DATA
        mock_response.raise_for_status.return_value = None
        mock_response.text = json.dumps(VALID_RELEASE_DATA)
        mock_get.return_value = mock_response

        release = self._make_release()
        url, file_hash = release.get_url_and_hash("agent.zip")

        assert url == "https://example.com/agent.zip"
        assert file_hash == "sha256:abc123"

    @patch("operate.services.agent_assets.requests.get")
    def test_403_raises_http_error(self, mock_get: MagicMock) -> None:
        """403 response raises requests.HTTPError, not KeyError."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "403 rate limited", response=mock_response
        )
        mock_get.return_value = mock_response

        release = self._make_release()
        with pytest.raises(requests.HTTPError):
            release.get_url_and_hash("agent.zip")

    @patch("operate.services.agent_assets.requests.get")
    def test_200_missing_assets_key(self, mock_get: MagicMock) -> None:
        """200 with missing 'assets' key raises ValueError with status info."""
        malformed_body = {"message": "Not Found"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = malformed_body
        mock_response.raise_for_status.return_value = None
        mock_response.text = json.dumps(malformed_body)
        mock_get.return_value = mock_response

        release = self._make_release()
        with pytest.raises(ValueError, match="missing 'assets' key"):
            release.get_url_and_hash("agent.zip")

    @patch("operate.services.agent_assets.requests.get")
    def test_cache_hit(self, mock_get: MagicMock) -> None:
        """Second call with same (owner, repo, release) uses cache."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = VALID_RELEASE_DATA
        mock_response.raise_for_status.return_value = None
        mock_response.text = json.dumps(VALID_RELEASE_DATA)
        mock_get.return_value = mock_response

        release = self._make_release()
        release.get_url_and_hash("agent.zip")
        release.get_url_and_hash("agent.zip")

        assert mock_get.call_count == 1


class TestUpdateAgentReleaseAsset:
    """Tests for AgentAssetManager.update_agent_release_asset sidecar writes."""

    @patch.object(AgentAssetManager, "download_file")
    def test_sidecar_written_on_download(
        self, mock_download: MagicMock, tmp_path: Path
    ) -> None:
        """After a successful download, the .sha256 sidecar is written."""
        target_path = tmp_path / "agent.zip"
        sidecar_path = tmp_path / "agent.zip.sha256"
        fake_content = b"fake zip content"

        release = AgentRelease(
            owner="valory-xyz", repo="trader", release="v0.40.7", is_aea=True
        )

        def fake_download(url: str, save_path: Path) -> None:
            save_path.write_bytes(fake_content)

        mock_download.side_effect = fake_download

        # Pre-compute the hash of fake_content so we can pass it as the
        # "remote" hash and let get_local_file_sha256 run for real.
        # Using distinct values (real hash vs a constant) proves the
        # sidecar records the verified hash, not an arbitrary value.
        expected_hash = "sha256:" + hashlib.sha256(fake_content).hexdigest()

        with patch.object(
            release,
            "get_url_and_hash",
            return_value=("https://example.com/agent.zip", expected_hash),
        ):
            AgentAssetManager.update_agent_release_asset(
                target_path=target_path,
                agent_release_asset_name="agent.zip",
                target_filename="agent.zip",
                agent_release=release,
            )

        assert target_path.exists()
        assert sidecar_path.exists()
        assert sidecar_path.read_text(encoding="utf-8") == expected_hash

    @patch.object(AgentAssetManager, "get_local_file_sha256")
    def test_sidecar_written_on_hash_match(
        self, mock_sha256: MagicMock, tmp_path: Path
    ) -> None:
        """When hash already matches (early exit), sidecar is still written."""
        target_path = tmp_path / "agent.zip"
        target_path.write_bytes(b"existing zip")
        sidecar_path = tmp_path / "agent.zip.sha256"

        release = AgentRelease(
            owner="valory-xyz", repo="trader", release="v0.40.7", is_aea=True
        )

        with patch.object(
            release,
            "get_url_and_hash",
            return_value=("https://example.com/agent.zip", "sha256:abc123"),
        ):
            mock_sha256.return_value = "sha256:abc123"

            AgentAssetManager.update_agent_release_asset(
                target_path=target_path,
                agent_release_asset_name="agent.zip",
                target_filename="agent.zip",
                agent_release=release,
            )

        assert sidecar_path.exists()
        assert sidecar_path.read_text(encoding="utf-8") == "sha256:abc123"


class TestGetAgentCodePathFallback:
    """Tests for AgentAssetManager.get_agent_code_path offline fallback."""

    def _setup_service_dir(self, tmp_path: Path) -> Path:
        """Create a minimal service dir with config.json."""
        service_dir = tmp_path / "service"
        service_dir.mkdir()
        config_path = service_dir / "config.json"
        config_path.write_text(json.dumps(SERVICE_CONFIG))
        return service_dir

    @patch.object(AgentAssetManager, "update_agent_release_asset")
    def test_fallback_valid_sidecar(
        self, mock_update: MagicMock, tmp_path: Path
    ) -> None:
        """Fallback succeeds when zip and valid sidecar exist."""
        service_dir = self._setup_service_dir(tmp_path)
        agent_cache = service_dir / "agent_cache"
        agent_cache.mkdir()
        zip_path = agent_cache / "agent.zip"
        zip_path.write_bytes(b"valid zip content")
        sidecar_path = agent_cache / "agent.zip.sha256"

        # Write the correct hash
        real_hash = AgentAssetManager.get_local_file_sha256(zip_path)
        sidecar_path.write_text(real_hash, encoding="utf-8")

        mock_update.side_effect = requests.ConnectionError("network down")

        result = AgentAssetManager.get_agent_code_path(service_dir)
        assert result == str(zip_path)

    @patch.object(AgentAssetManager, "update_agent_release_asset")
    def test_fallback_no_zip(self, mock_update: MagicMock, tmp_path: Path) -> None:
        """Fallback re-raises original RequestException when no cached zip exists."""
        service_dir = self._setup_service_dir(tmp_path)

        mock_update.side_effect = requests.ConnectionError("network down")

        with pytest.raises(requests.ConnectionError):
            AgentAssetManager.get_agent_code_path(service_dir)

    @patch.object(AgentAssetManager, "update_agent_release_asset")
    def test_fallback_no_sidecar(self, mock_update: MagicMock, tmp_path: Path) -> None:
        """Fallback re-raises original RequestException when sidecar is absent."""
        service_dir = self._setup_service_dir(tmp_path)
        agent_cache = service_dir / "agent_cache"
        agent_cache.mkdir()
        zip_path = agent_cache / "agent.zip"
        zip_path.write_bytes(b"some content")

        mock_update.side_effect = requests.ConnectionError("network down")

        with pytest.raises(requests.ConnectionError):
            AgentAssetManager.get_agent_code_path(service_dir)

    @patch.object(AgentAssetManager, "update_agent_release_asset")
    def test_fallback_hash_mismatch(
        self, mock_update: MagicMock, tmp_path: Path
    ) -> None:
        """Fallback re-raises original RequestException when sidecar hash doesn't match."""
        service_dir = self._setup_service_dir(tmp_path)
        agent_cache = service_dir / "agent_cache"
        agent_cache.mkdir()
        zip_path = agent_cache / "agent.zip"
        zip_path.write_bytes(b"some content")
        sidecar_path = agent_cache / "agent.zip.sha256"
        sidecar_path.write_text("sha256:wrong_hash", encoding="utf-8")

        mock_update.side_effect = requests.ConnectionError("network down")

        with pytest.raises(requests.ConnectionError):
            AgentAssetManager.get_agent_code_path(service_dir)


class TestSidecarWriteFailures:
    """Tests for tolerating .sha256 sidecar I/O failures."""

    @staticmethod
    def _readonly_sidecar_write(original: Any) -> Any:
        """Patch Path.write_text so only sidecar writes fail."""

        def _write(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self.name.endswith(".sha256"):
                raise OSError(30, "Read-only file system")
            return original(self, *args, **kwargs)

        return _write

    @patch.object(AgentAssetManager, "get_local_file_sha256")
    def test_hash_match_survives_sidecar_oserror(
        self, mock_sha256: MagicMock, tmp_path: Path
    ) -> None:
        """An unwritable sidecar must not fail the already-up-to-date fast path."""
        target_path = tmp_path / "agent.zip"
        target_path.write_bytes(b"already current")
        mock_sha256.return_value = "sha256:abc123"

        release = AgentRelease(
            owner="valory-xyz", repo="trader", release="v0.40.7", is_aea=True
        )

        with (
            patch.object(
                release,
                "get_url_and_hash",
                return_value=("https://example.com/agent.zip", "sha256:abc123"),
            ),
            patch.object(
                Path, "write_text", self._readonly_sidecar_write(Path.write_text)
            ),
        ):
            AgentAssetManager.update_agent_release_asset(
                target_path=target_path,
                agent_release_asset_name="agent.zip",
                target_filename="agent.zip",
                agent_release=release,
            )

        assert target_path.read_bytes() == b"already current"


class TestGetAgentRunnerPathFallback:
    """Tests for the offline fallback on the agent runner binary."""

    def _setup_service_dir(self, tmp_path: Path) -> Path:
        """Create a minimal service dir with config.json."""
        service_dir = tmp_path / "service"
        service_dir.mkdir()
        (service_dir / "config.json").write_text(json.dumps(SERVICE_CONFIG))
        return service_dir

    @patch.object(AgentAssetManager, "update_agent_release_asset")
    def test_runner_fallback_valid_sidecar(
        self, mock_update: MagicMock, tmp_path: Path
    ) -> None:
        """A 403 with a sidecar-verified cached binary returns the cached path."""
        service_dir = self._setup_service_dir(tmp_path)
        runner_name = AgentAssetManager.get_agent_runner_executable_name()
        runner_path = service_dir / runner_name
        runner_path.write_bytes(b"cached runner binary")
        sidecar_path = service_dir / (runner_name + ".sha256")
        sidecar_path.write_text(
            AgentAssetManager.get_local_file_sha256(runner_path), encoding="utf-8"
        )

        response = MagicMock()
        response.status_code = 403
        mock_update.side_effect = requests.HTTPError(
            "403 rate limited", response=response
        )

        assert AgentAssetManager.get_agent_runner_path(service_dir) == str(runner_path)

    @patch.object(AgentAssetManager, "update_agent_release_asset")
    def test_runner_fallback_no_cache_preserves_403(
        self, mock_update: MagicMock, tmp_path: Path
    ) -> None:
        """Without a cached binary the original HTTPError (and its 403) propagates."""
        service_dir = self._setup_service_dir(tmp_path)

        response = MagicMock()
        response.status_code = 403
        mock_update.side_effect = requests.HTTPError(
            "403 rate limited", response=response
        )

        with pytest.raises(requests.HTTPError) as exc_info:
            AgentAssetManager.get_agent_runner_path(service_dir)

        assert exc_info.value.response.status_code == 403


class TestReleaseMetadataCacheInvalidation:
    """Tests for TTL expiry and explicit invalidation of cached release metadata."""

    def _make_release(self) -> AgentRelease:
        return AgentRelease(
            owner="valory-xyz", repo="trader", release="v0.40.7", is_aea=True
        )

    def _mock_response(self) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = VALID_RELEASE_DATA
        response.raise_for_status.return_value = None
        response.text = json.dumps(VALID_RELEASE_DATA)
        return response

    @patch("operate.services.agent_assets.requests.get")
    def test_cache_expires_after_ttl(self, mock_get: MagicMock) -> None:
        """A lookup past the TTL refetches instead of serving stale metadata."""
        mock_get.return_value = self._mock_response()
        release = self._make_release()

        with patch("operate.services.agent_assets.time.monotonic", return_value=0.0):
            release.get_url_and_hash("agent.zip")
        with patch(
            "operate.services.agent_assets.time.monotonic",
            return_value=1e9,
        ):
            release.get_url_and_hash("agent.zip")

        assert mock_get.call_count == 2

    @patch("operate.services.agent_assets.requests.get")
    def test_invalidate_cache_forces_refetch(self, mock_get: MagicMock) -> None:
        """Invalidating an entry refetches even inside the TTL window."""
        mock_get.return_value = self._mock_response()
        release = self._make_release()

        release.get_url_and_hash("agent.zip")
        release.invalidate_cache()
        release.get_url_and_hash("agent.zip")

        assert mock_get.call_count == 2

    @patch("operate.services.agent_assets.requests.get")
    def test_clear_cache_forces_refetch(self, mock_get: MagicMock) -> None:
        """The public clear helper drops entries for every release."""
        mock_get.return_value = self._mock_response()
        release = self._make_release()

        release.get_url_and_hash("agent.zip")
        clear_release_metadata_cache()
        release.get_url_and_hash("agent.zip")

        assert mock_get.call_count == 2

    @patch.object(AgentAssetManager, "download_file")
    @patch.object(AgentAssetManager, "get_local_file_sha256")
    def test_hash_mismatch_invalidates_cache(
        self, mock_sha256: MagicMock, mock_download: MagicMock, tmp_path: Path
    ) -> None:
        """A failed hash check drops the cached digest so a retry can refetch."""
        release = self._make_release()
        mock_sha256.return_value = "sha256:something-else"
        mock_download.side_effect = lambda url, save_path: save_path.write_bytes(b"x")

        with patch(
            "operate.services.agent_assets.requests.get",
            return_value=self._mock_response(),
        ) as mock_get:
            release.get_url_and_hash("agent.zip")
            with pytest.raises(ValueError, match="Hash verification failed"):
                AgentAssetManager.update_agent_release_asset(
                    target_path=tmp_path / "agent.zip",
                    agent_release_asset_name="agent.zip",
                    target_filename="agent.zip",
                    agent_release=release,
                )
            release.get_url_and_hash("agent.zip")

        assert mock_get.call_count == 2
