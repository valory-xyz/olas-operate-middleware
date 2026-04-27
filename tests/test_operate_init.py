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

"""Unit tests for operate/__init__.py module-level code."""

import importlib
import logging
import os
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any
from unittest.mock import patch

import operate as operate_module


class TestOperateInitVersionFallbacks:
    """Tests for PackageNotFoundError fallback paths (lines 33-39)."""

    def _reload(self) -> None:
        importlib.reload(operate_module)

    def teardown_method(self) -> None:
        """Restore the operate module after each test."""
        importlib.reload(operate_module)

    def test_first_version_lookup_fails_uses_operate_fallback(self) -> None:
        """When 'olas-operate-middleware' is not found, falls back to 'operate' version."""

        def _version(name: str) -> str:
            if name == "olas-operate-middleware":
                raise PackageNotFoundError(name)
            return "1.2.3"

        with patch("importlib.metadata.version", side_effect=_version):
            importlib.reload(operate_module)

        assert operate_module.__version__ == "1.2.3"

    def test_both_version_lookups_fail_uses_local(self) -> None:
        """When both package names are not found, version is set to 0.0.0+local."""
        with patch(
            "importlib.metadata.version", side_effect=PackageNotFoundError("all")
        ):
            importlib.reload(operate_module)

        assert operate_module.__version__ == "0.0.0+local"


class TestOperateInitPlatformBranches:
    """Tests for platform-specific CA bundle branches (lines 56-72)."""

    def teardown_method(self) -> None:
        """Restore the operate module after each test."""
        importlib.reload(operate_module)

    def test_darwin_branch_with_system_bundle(self) -> None:
        """Darwin branch exports CA bundle for both requests and urllib clients."""
        darwin_bundle = "/etc/ssl/cert.pem"
        with patch("platform.system", return_value="Darwin"), patch(
            "os.path.exists", return_value=True
        ), patch.dict(os.environ, {}, clear=False):
            env_copy = dict(os.environ)
            env_copy.pop("REQUESTS_CA_BUNDLE", None)
            env_copy.pop("SSL_CERT_FILE", None)
            with patch.dict(os.environ, env_copy, clear=True):
                importlib.reload(operate_module)
                assert os.environ.get("REQUESTS_CA_BUNDLE") == darwin_bundle
                assert os.environ.get("SSL_CERT_FILE") == darwin_bundle

    def test_linux_branch_with_system_bundle(self) -> None:
        """Linux branch exports CA bundle for both requests and urllib clients."""
        linux_bundle = "/etc/ssl/certs/ca-certificates.crt"
        with patch("platform.system", return_value="Linux"), patch(
            "os.path.exists", return_value=True
        ), patch.dict(os.environ, {}, clear=False):
            env_copy = dict(os.environ)
            env_copy.pop("REQUESTS_CA_BUNDLE", None)
            env_copy.pop("SSL_CERT_FILE", None)
            with patch.dict(os.environ, env_copy, clear=True):
                importlib.reload(operate_module)
                assert os.environ.get("REQUESTS_CA_BUNDLE") == linux_bundle
                assert os.environ.get("SSL_CERT_FILE") == linux_bundle

    def test_windows_branch(self) -> None:
        """Windows branch sets bundle_set=True without reading a file (lines 61-64)."""
        with patch("platform.system", return_value="Windows"):
            importlib.reload(operate_module)
        # No exception means Windows branch executed correctly

    def test_unknown_os_branch_with_certifi_fallback(self) -> None:
        """Unknown OS branch uses certifi for both requests and urllib clients."""
        import certifi

        certifi_path = certifi.where()
        with patch("platform.system", return_value="FreeBSD"), patch(
            "os.path.exists", return_value=True
        ), patch.dict(os.environ, {}, clear=False):
            env_copy = dict(os.environ)
            env_copy.pop("REQUESTS_CA_BUNDLE", None)
            env_copy.pop("SSL_CERT_FILE", None)
            with patch.dict(os.environ, env_copy, clear=True):
                importlib.reload(operate_module)
                assert os.environ.get("REQUESTS_CA_BUNDLE") == certifi_path
                assert os.environ.get("SSL_CERT_FILE") == certifi_path

    def test_transient_certifi_bundle_is_materialized_to_stable_path(
        self, tmp_path: Path
    ) -> None:
        """A transient certifi bundle is copied to a stable Operate-owned path."""
        pyinstaller_dir = tmp_path / "_MEI123"
        pyinstaller_dir.mkdir()
        certifi_bundle = pyinstaller_dir / "cacert.pem"
        certifi_bundle.write_text("bundle-data", encoding="utf-8")
        operate_home = tmp_path / "operate-home"
        expected_bundle = operate_home / "certs" / "cacert.pem"

        with patch("platform.system", return_value="FreeBSD"), patch(
            "certifi.where", return_value=str(certifi_bundle)
        ), patch.dict(
            os.environ,
            {"OPERATE_HOME": str(operate_home)},
            clear=True,
        ):
            importlib.reload(operate_module)
            assert os.environ.get("REQUESTS_CA_BUNDLE") == str(expected_bundle)
            assert os.environ.get("SSL_CERT_FILE") == str(expected_bundle)
            assert expected_bundle.read_text(encoding="utf-8") == "bundle-data"

    def test_transient_inherited_bundle_falls_back_to_system_bundle(self) -> None:
        """A PyInstaller temp bundle path does not block fallback to a stable system bundle."""
        linux_bundle = "/etc/ssl/certs/ca-certificates.crt"  # nosec B108
        pyinstaller_bundle = "/tmp/_MEI123/cacert.pem"  # nosec B108

        def exists(path: str) -> bool:
            return path in {linux_bundle, pyinstaller_bundle}

        with patch("platform.system", return_value="Linux"), patch(
            "os.path.exists", side_effect=exists
        ), patch.dict(
            os.environ,
            {
                "REQUESTS_CA_BUNDLE": pyinstaller_bundle,
                "SSL_CERT_FILE": pyinstaller_bundle,
            },
            clear=True,
        ):
            importlib.reload(operate_module)
            assert os.environ.get("REQUESTS_CA_BUNDLE") == linux_bundle
            assert os.environ.get("SSL_CERT_FILE") == linux_bundle

    def test_windows_branch_leaves_file_based_bundle_env_unset(self) -> None:
        """Windows branch relies on the system trust store instead of bundle files."""
        with patch("platform.system", return_value="Windows"), patch.dict(
            os.environ, {}, clear=True
        ):
            importlib.reload(operate_module)
            assert "REQUESTS_CA_BUNDLE" not in os.environ
            assert "SSL_CERT_FILE" not in os.environ

    def test_windows_branch_clears_stale_file_based_bundle_env(self) -> None:
        """Windows branch removes stale file-based CA bundle env vars."""
        with patch("platform.system", return_value="Windows"), patch(
            "os.path.exists", return_value=False
        ), patch.dict(
            os.environ,
            {
                "REQUESTS_CA_BUNDLE": "/tmp/_MEI123/cacert.pem",  # nosec B108
                "SSL_CERT_FILE": "/tmp/_MEI123/cacert.pem",  # nosec B108
            },
            clear=True,
        ):
            importlib.reload(operate_module)
            assert "REQUESTS_CA_BUNDLE" not in os.environ
            assert "SSL_CERT_FILE" not in os.environ

    def test_valid_requests_bundle_is_used_when_ssl_cert_file_is_invalid(self) -> None:
        """A valid REQUESTS_CA_BUNDLE still wins when SSL_CERT_FILE is unusable."""
        linux_bundle = "/etc/ssl/certs/ca-certificates.crt"

        def exists(path: str) -> bool:
            return path == linux_bundle

        with patch("platform.system", return_value="Linux"), patch(
            "os.path.exists", side_effect=exists
        ), patch.dict(
            os.environ,
            {
                "REQUESTS_CA_BUNDLE": linux_bundle,
                "SSL_CERT_FILE": "/dead/_MEI123/cacert.pem",
            },
            clear=True,
        ):
            importlib.reload(operate_module)
            assert os.environ.get("REQUESTS_CA_BUNDLE") == linux_bundle
            assert os.environ.get("SSL_CERT_FILE") == linux_bundle

    def test_unknown_os_branch_no_bundle_logs_warning(self, caplog: Any) -> None:
        """Unknown OS branch logs warning when no CA bundle is available (lines 65-66, 72)."""
        with caplog.at_level(logging.WARNING, logger="operate"), patch(
            "platform.system", return_value="FreeBSD"
        ), patch("os.path.exists", return_value=False), patch.dict(
            os.environ, {}, clear=True
        ):
            importlib.reload(operate_module)
        assert "No CA certificate bundle available" in caplog.text

    def test_materialize_certifi_bundle_oserror_returns_none(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        """OS Error during bundle copy logs a warning and returns None (lines 85-89)."""
        pyinstaller_dir = tmp_path / "_MEI123"
        pyinstaller_dir.mkdir()
        certifi_bundle = pyinstaller_dir / "cacert.pem"
        certifi_bundle.write_text("bundle-data", encoding="utf-8")
        operate_home = tmp_path / "operate-home"

        with caplog.at_level(logging.WARNING, logger="operate"), patch(
            "platform.system", return_value="FreeBSD"
        ), patch("operate.certifi.where", return_value=str(certifi_bundle)), patch(
            "operate.shutil.copyfile", side_effect=OSError("disk full")
        ), patch.dict(
            os.environ,
            {"OPERATE_HOME": str(operate_home)},
            clear=True,
        ):
            importlib.reload(operate_module)
            assert "REQUESTS_CA_BUNDLE" not in os.environ
            assert "SSL_CERT_FILE" not in os.environ
        assert "Failed to materialize certifi CA bundle" in caplog.text

    def test_get_runtime_ca_bundle_env_returns_empty_when_no_bundle(self) -> None:
        """get_runtime_ca_bundle_env returns {} when no CA bundle is available (line 126)."""
        with patch("platform.system", return_value="FreeBSD"), patch(
            "operate.os.path.exists", return_value=False
        ), patch(
            "operate.certifi.where", return_value="/nonexistent/cacert.pem"
        ), patch.dict(
            os.environ, {}, clear=True
        ):
            result = operate_module.get_runtime_ca_bundle_env()
        assert result == {}
