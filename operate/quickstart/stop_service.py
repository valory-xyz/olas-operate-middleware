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
"""Quickstop script."""

import json
import warnings
from typing import TYPE_CHECKING, cast

from operate.quickstart.run_service import (
    ask_password_if_needed,
    configure_local_config,
    get_service,
    load_local_config,
)
from operate.quickstart.utils import print_section, print_title


if TYPE_CHECKING:
    from operate.cli import OperateApp

warnings.filterwarnings("ignore", category=UserWarning)


def stop_service(operate: "OperateApp", config_path: str) -> None:
    """Stop service."""

    with open(config_path, "r") as config_file:
        template = json.load(config_file)

    print_title(f"Stop {template['name']} Quickstart")

    # check if agent was started before
    config = load_local_config(
        operate=operate, service_name=cast(str, template["name"])
    )
    if not config.path.exists():
        print("No previous agent setup found. Exiting.")
        return

    ask_password_if_needed(operate)
    configure_local_config(template, operate)
    manager = operate.service_manager()
    service = get_service(manager, template)
    manager.stop_service_locally(
        service_config_id=service.service_config_id, use_docker=True, force=True
    )

    print()
    print_section(f"{template['name']} service stopped")
