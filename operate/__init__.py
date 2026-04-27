# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""Operate app."""

import logging
import os
import platform
import shutil
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Dict, Optional

import certifi

try:
    # Prefer the distribution name if installed; fall back to the module name
    __version__ = version("olas-operate-middleware")
except PackageNotFoundError:
    try:
        __version__ = version("operate")
    except PackageNotFoundError:
        logger = logging.getLogger("operate")
        logger.warning("Could not determine version, using 0.0.0+local")
        __version__ = "0.0.0+local"

logging.getLogger("aea").setLevel(logging.ERROR)
logging.getLogger("aea.ledger_apis.ethereum").setLevel(logging.WARNING)
logging.getLogger("autonomy.deploy.base").setLevel(logging.ERROR)


logger = logging.getLogger("operate")


def _is_transient_ca_bundle_path(bundle_path: str) -> bool:
    """Return whether the CA bundle path points to a transient PyInstaller extract dir."""
    return any(part.startswith("_MEI") for part in Path(bundle_path).parts)


def _is_usable_ca_bundle_path(bundle_path: Optional[str]) -> bool:
    """Return whether a CA bundle path is usable for long-running child processes."""
    return (
        bundle_path is not None
        and os.path.exists(bundle_path)
        and not _is_transient_ca_bundle_path(bundle_path)
    )


def _clear_invalid_runtime_ca_bundle_env() -> None:
    """Remove unusable CA bundle env vars so Python can fall back to the system trust store."""
    for key in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        current_value = os.environ.get(key)
        if current_value is not None and not _is_usable_ca_bundle_path(current_value):
            os.environ.pop(key, None)


def _get_stable_certifi_bundle_path() -> Path:
    """Return the stable on-disk location for the bundled certifi CA bundle."""
    operate_home_str = os.environ.get("OPERATE_HOME")
    operate_home = (
        Path(operate_home_str) if operate_home_str else Path.home() / ".operate"
    )
    return operate_home / "certs" / "cacert.pem"


def _materialize_certifi_bundle(certifi_bundle: str) -> Optional[str]:
    """Copy the bundled certifi CA bundle to a stable location when needed."""
    destination = _get_stable_certifi_bundle_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(certifi_bundle, destination)
    except OSError as exc:
        logger.warning(
            "Failed to materialize certifi CA bundle at %s: %s", destination, exc
        )
        return None
    return str(destination)


def get_runtime_ca_bundle_path() -> Optional[str]:
    """Return the CA bundle path to use for spawned Python runtimes."""
    system = platform.system()
    if system != "Windows":
        for configured_bundle in (
            os.environ.get("SSL_CERT_FILE"),
            os.environ.get("REQUESTS_CA_BUNDLE"),
        ):
            if _is_usable_ca_bundle_path(configured_bundle):
                return configured_bundle

    system_bundle = None
    if system == "Darwin":
        system_bundle = "/etc/ssl/cert.pem"
    elif system == "Linux":
        system_bundle = "/etc/ssl/certs/ca-certificates.crt"

    if system_bundle and os.path.exists(system_bundle):
        return system_bundle

    certifi_bundle = certifi.where()
    if _is_usable_ca_bundle_path(certifi_bundle):
        return certifi_bundle

    if os.path.exists(certifi_bundle):
        return _materialize_certifi_bundle(certifi_bundle)

    return None


def get_runtime_ca_bundle_env() -> Dict[str, str]:
    """Return environment variables that point Python TLS clients to a CA bundle."""
    if platform.system() == "Windows":
        return {}  # pragma: no cover - Can't mock platform.system() on linux

    bundle_path = get_runtime_ca_bundle_path()
    if bundle_path is None:
        return {}
    return {
        "REQUESTS_CA_BUNDLE": bundle_path,
        "SSL_CERT_FILE": bundle_path,
    }


def _set_runtime_ca_bundle_env(bundle_env: Dict[str, str]) -> None:
    """Set CA bundle env vars, replacing stale paths but preserving live overrides."""
    for key, value in bundle_env.items():
        current_value = os.environ.get(key)
        if not _is_usable_ca_bundle_path(current_value):
            os.environ[key] = value


def configure_runtime_ca_bundle() -> None:
    """Populate CA bundle environment variables for the current process."""
    system = platform.system()
    if system == "Windows":
        _clear_invalid_runtime_ca_bundle_env()
        logger.info("Using system certificate store on Windows.")
        return

    bundle_env = get_runtime_ca_bundle_env()
    if bundle_env:
        _set_runtime_ca_bundle_env(bundle_env)
        return

    if system not in ("Darwin", "Linux"):
        logger.warning(f"Unknown OS {system}; CA bundle handling not configured.")
    logger.warning("No CA certificate bundle available.")


configure_runtime_ca_bundle()
