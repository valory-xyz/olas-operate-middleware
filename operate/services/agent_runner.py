#!/usr/bin/env python3
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
# -------------------------------------------------------------
"""Source dode to download and run agent from the repos."""
import hashlib
import os
import platform
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Tuple

import requests
from aea.configurations.data_types import PublicId
from aea.helpers.logging import setup_logger


@dataclass
class AgentRelease:
    """Agent release dataclass."""

    owner: str
    repo: str
    release: str

    @property
    def release_url(self) -> str:
        """Get release  api url."""
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/tags/{self.release}"

    def get_url_and_hash(self, asset_name: str) -> tuple[str, str]:
        """Get download url and asset sha256 hash."""
        release_data = requests.get(self.release_url).json()

        assets_filtered = [i for i in release_data["assets"] if i["name"] == asset_name]
        if not assets_filtered:
            raise ValueError(
                f"Asset {asset_name} not found in release {self.release_url}"
            )
        asset = assets_filtered[0]
        file_hash = asset["digest"]
        file_url = asset["browser_download_url"]

        return file_url, file_hash


# list of agents releases supported
AGENTS_SUPPORTED = {
    "valory/trader": AgentRelease(
        owner="valory-xyz", repo="trader", release="v0.0.101"
    ),
    "valory/optimus": AgentRelease(
        owner="valory-xyz", repo="optimus", release="v0.0.103"
    ),
    "dvilela/memeooorr": AgentRelease(
        owner="valory-xyz", repo="meme-ooorr", release="v0.0.101"
    ),
}


class AgentRunnerManager:
    """Agent Runner Manager."""

    logger = setup_logger(name="operate.agent_runner_manager")
    AGENTS = AGENTS_SUPPORTED

    @staticmethod
    def get_agent_runner_executable_name() -> str:
        """Get runner executable name by platform running."""
        if platform.system() == "Darwin":
            os_name = "macos"
        elif platform.system() == "Windows":
            os_name = "windows"
        else:
            raise ValueError("Platform not supported!")

        if platform.machine().lower() in ("x86_64", "amd64"):
            arch = "x64"
        elif platform.machine().lower() == "arm64":
            arch = "arm64"
            if os_name == "windows":
                raise ValueError("Windows arm64 is not supported!")
        else:
            raise ValueError(f"unsupported arch: {platform.machine()}")

        exec_name = f"agent_runner_{os_name}_{arch}"
        if platform.system() == "Windows":
            exec_name += ".exe"
        return exec_name

    @staticmethod
    def parse_agent(public_id_str: str) -> Tuple[str, str]:
        """Get authorn and name from agent public string id."""
        public_id = PublicId.from_str(public_id_string=public_id_str)
        return (public_id.author, public_id.name)

    @classmethod
    def download_file(cls, url: str, save_path: Path) -> None:
        """Download file of agent runner."""
        try:
            # Send a GET request to the URL
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an error for bad status codes (4xx or 5xx)

            # Open the file in binary write mode and save the content
            with open(save_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

            cls.logger.info(f"File downloaded and saved to {save_path}")
        except requests.exceptions.RequestException as e:
            cls.logger.error(f"Error downloading file: {e}")
            raise

    @classmethod
    def get_agent_release_by_public_id(cls, agent_public_id_str: str) -> AgentRelease:
        """Get agent release object according to public id."""
        agent_author, agent_name = cls.parse_agent(public_id_str=agent_public_id_str)

        agent_name = f"{agent_author}/{agent_name}"
        agent_release = cls.AGENTS.get(agent_name, None)
        if agent_release is None:
            raise ValueError(f"{agent_name} is not supported!")
        return agent_release

    @staticmethod
    def get_local_file_sha256(path: Path) -> str:
        """Get local file sha256."""
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return "sha256:" + sha256_hash.hexdigest()

    @classmethod
    def update_agent_runner(
        cls, target_path: Path, agent_runner_name: str, agent_release: AgentRelease
    ) -> None:
        """Download agent runner."""
        download_url, remote_file_hash = agent_release.get_url_and_hash(
            agent_runner_name
        )

        if target_path.exists():
            # check sha
            current_file_hash = cls.get_local_file_sha256(target_path)
            if remote_file_hash == current_file_hash:
                cls.logger.info(
                    "local and remote files hashes are match, nothing to download"
                )
                return
            cls.logger.info(
                "local and remote files hashes does not  match, go to download"
            )
        else:
            cls.logger.info("local file not found, go to download")

        try:
            with TemporaryDirectory() as tmp_dir:
                tmp_file = Path(tmp_dir) / "agent_runner"
                cls.download_file(download_url, tmp_file)
                shutil.copy2(tmp_file, target_path)
                if os.name == "posix":
                    target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC)
        except Exception:
            # remove in caae of errors
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise

    @classmethod
    def get_agent_runner_path(cls, service_dir: Path, agent_public_id_str: str) -> str:
        """Get path to the agent runner bin palced."""
        agent_runner_name = cls.get_agent_runner_executable_name()
        agent_runner_path: Path = service_dir / agent_runner_name
        agent_release = cls.get_agent_release_by_public_id(
            agent_public_id_str=agent_public_id_str
        )

        cls.update_agent_runner(
            target_path=agent_runner_path,
            agent_runner_name=agent_runner_name,
            agent_release=agent_release,
        )
        return str(agent_runner_path)


def get_agent_runner_path(service_dir: Path, agent_public_id_str: str) -> str:
    """Get path to the agent runner bin placed."""
    return AgentRunnerManager.get_agent_runner_path(
        service_dir=service_dir, agent_public_id_str=agent_public_id_str
    )
