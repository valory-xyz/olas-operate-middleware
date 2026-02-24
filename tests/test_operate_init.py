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
        """Darwin branch sets REQUESTS_CA_BUNDLE when system bundle exists (lines 51-55)."""
        darwin_bundle = "/etc/ssl/cert.pem"
        with patch("platform.system", return_value="Darwin"), patch(
            "os.path.exists", return_value=True
        ), patch.dict(os.environ, {}, clear=False):
            env_copy = dict(os.environ)
            env_copy.pop("REQUESTS_CA_BUNDLE", None)
            with patch.dict(os.environ, env_copy, clear=True):
                importlib.reload(operate_module)
                assert os.environ.get("REQUESTS_CA_BUNDLE") == darwin_bundle

    def test_linux_branch_with_system_bundle(self) -> None:
        """Linux branch sets REQUESTS_CA_BUNDLE when system bundle exists (lines 56-60)."""
        linux_bundle = "/etc/ssl/certs/ca-certificates.crt"
        with patch("platform.system", return_value="Linux"), patch(
            "os.path.exists", return_value=True
        ), patch.dict(os.environ, {}, clear=False):
            env_copy = dict(os.environ)
            env_copy.pop("REQUESTS_CA_BUNDLE", None)
            with patch.dict(os.environ, env_copy, clear=True):
                importlib.reload(operate_module)
                assert os.environ.get("REQUESTS_CA_BUNDLE") == linux_bundle

    def test_windows_branch(self) -> None:
        """Windows branch sets bundle_set=True without reading a file (lines 61-64)."""
        with patch("platform.system", return_value="Windows"):
            importlib.reload(operate_module)
        # No exception means Windows branch executed correctly

    def test_unknown_os_branch_with_certifi_fallback(self) -> None:
        """Unknown OS branch uses certifi when available (lines 65-66, 70)."""
        import certifi

        certifi_path = certifi.where()
        with patch("platform.system", return_value="FreeBSD"), patch(
            "os.path.exists", return_value=True
        ), patch.dict(os.environ, {}, clear=False):
            env_copy = dict(os.environ)
            env_copy.pop("REQUESTS_CA_BUNDLE", None)
            with patch.dict(os.environ, env_copy, clear=True):
                importlib.reload(operate_module)
                assert os.environ.get("REQUESTS_CA_BUNDLE") == certifi_path

    def test_unknown_os_branch_no_bundle_logs_warning(
        self, caplog: Any
    ) -> None:
        """Unknown OS branch logs warning when no CA bundle is available (lines 65-66, 72)."""
        with caplog.at_level(logging.WARNING, logger="operate"), patch(
            "platform.system", return_value="FreeBSD"
        ), patch("os.path.exists", return_value=False):
            importlib.reload(operate_module)
        assert "No CA certificate bundle available" in caplog.text
