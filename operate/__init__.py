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
from importlib.metadata import PackageNotFoundError, version

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


# Ensure CA bundle is available for requests
# This prevents errors when PyInstaller temp directory is cleaned during long-running apps
# Set REQUESTS_CA_BUNDLE, preferring system CA bundle, falling back to bundled.
logger = logging.getLogger("operate")
system = platform.system()
bundle_set = False
if system == "Darwin":  # macOS
    system_bundle = "/etc/ssl/cert.pem"
    if os.path.exists(system_bundle):
        os.environ.setdefault("REQUESTS_CA_BUNDLE", system_bundle)
        bundle_set = True
elif system == "Linux":
    system_bundle = "/etc/ssl/certs/ca-certificates.crt"
    if os.path.exists(system_bundle):
        os.environ.setdefault("REQUESTS_CA_BUNDLE", system_bundle)
        bundle_set = True
elif system == "Windows":
    # Windows uses the system certificate store by default; no file needed
    logger.info("Using system certificate store on Windows.")
    bundle_set = True  # Considered set since system handles it
else:
    logger.warning(f"Unknown OS {system}; CA bundle handling not configured.")

# Fallback to bundled if system not available
if not bundle_set and os.path.exists(certifi.where()):
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
elif not bundle_set:
    logger.warning("No CA certificate bundle available.")
