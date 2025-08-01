# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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
"""Quickstart script to run log analysis."""


import json
import os
import subprocess  # nosec
import sys
from pathlib import Path
from typing import List, TYPE_CHECKING, Union

from operate.constants import DEPLOYMENT_DIR


if TYPE_CHECKING:
    from operate.cli import OperateApp


def find_build_directory(config_file: Path, operate: "OperateApp") -> Path:
    """Find the appropriate build directory of the configured service."""
    with open(config_file, "r") as f:
        config = json.load(f)
        config_service_hash = config.get("hash")

    services = operate.service_manager().get_all_services()
    for service in services:
        if service.hash == config_service_hash:
            build_dir = service.path / DEPLOYMENT_DIR
            if not build_dir.exists():
                print(f"{config.get('name')} not deployed.")
                sys.exit(1)
            return build_dir

    print(f"{config.get('name')} not found.")
    sys.exit(1)


def run_analysis(logs_dir: Path, **kwargs: str) -> None:
    """Run the log analysis command."""
    command: List[Union[str, Path]] = [
        "poetry",
        "run",
        "autonomy",
        "analyse",
        "logs",
        "--from-dir",
        logs_dir,
    ]
    if "agent" in kwargs and kwargs["agent"]:
        command.extend(["--agent", kwargs["agent"]])
    if "reset_db" in kwargs and kwargs["reset_db"]:
        command.extend(["--reset-db"])
    if "start_time" in kwargs and kwargs["start_time"]:
        command.extend(["--start-time", kwargs["start_time"]])
    if "end_time" in kwargs and kwargs["end_time"]:
        command.extend(["--end-time", kwargs["end_time"]])
    if "log_level" in kwargs and kwargs["log_level"]:
        command.extend(["--log-level", kwargs["log_level"]])
    if "period" in kwargs and kwargs["period"]:
        command.extend(["--period", kwargs["period"]])
    if "round" in kwargs and kwargs["round"]:
        command.extend(["--round", kwargs["round"]])
    if "behaviour" in kwargs and kwargs["behaviour"]:
        command.extend(["--behaviour", kwargs["behaviour"]])
    if "fsm" in kwargs and kwargs["fsm"]:
        command.extend(["--fsm"])
    if "include_regex" in kwargs and kwargs["include_regex"]:
        command.extend(["--include-regex", kwargs["include_regex"]])
    if "exclude_regex" in kwargs and kwargs["exclude_regex"]:
        command.extend(["--exclude-regex", kwargs["exclude_regex"]])

    try:
        subprocess.run(command, check=True)  # nosec
        print("Analysis completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("Poetry or autonomy not found. Ensure they are installed and accessible.")
        sys.exit(1)


def analyse_logs(
    operate: "OperateApp",
    config_path: str,
    **kwargs: str,
) -> None:
    """Run the log analysis command."""
    config_file = Path(config_path)
    if not config_file.exists():
        print(f"Config file '{config_file}' not found.")
        sys.exit(1)

    # Auto-detect the logs directory
    build_dir = find_build_directory(config_file, operate)
    logs_dir = build_dir / "persistent_data" / "logs"
    if not os.path.exists(logs_dir):
        print(f"Logs directory '{logs_dir}' not found.")
        sys.exit(1)

    # Run the analysis
    run_analysis(logs_dir, **kwargs)
