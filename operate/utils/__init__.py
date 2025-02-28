# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""Helper utilities."""

import shutil
import time
from pathlib import Path


def create_backup(path: Path) -> Path:
    """Creates a backup of the specified path.

    This function creates a backup of a file or directory by copying it and appending
    the current UNIX timestamp followed by the '.bak' suffix.
    """

    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    timestamp = int(time.time())
    backup_path = path.with_name(f"{path.name}.{timestamp}.bak")

    if path.is_dir():
        shutil.copytree(path, backup_path)
    else:
        shutil.copy2(path, backup_path)

    return backup_path
