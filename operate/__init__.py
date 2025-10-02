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
from importlib.metadata import PackageNotFoundError, version


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
