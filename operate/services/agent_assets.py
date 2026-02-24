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
"""Source code to download agent assets from GitHub releases."""
import hashlib
import json
import os
import platform
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Tuple

import requests
from aea.configurations.data_types import PublicId
from aea.helpers.logging import setup_logger

from operate.constants import AGENT_RUNNER_PREFIX, CONFIG_JSON, DEFAULT_TIMEOUT


@dataclass
class AgentRelease:
    """Agent release dataclass."""

    owner: str
    repo: str
    release: str
    is_aea: bool

    @property
    def release_url(self) -> str:
        """Get release  api url."""
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/tags/{self.release}"

    def get_url_and_hash(self, asset_name: str) -> tuple[str, str]:
        """Get download url and asset sha256 hash."""
        release_data = requests.get(self.release_url, timeout=DEFAULT_TIMEOUT).json()

        assets_filtered = [i for i in release_data["assets"] if i["name"] == asset_name]
        if not assets_filtered:
            raise ValueError(
                f"Asset {asset_name} not found in release {self.release_url}"
            )
        asset = assets_filtered[0]
        file_hash = asset["digest"]
        file_url = asset["browser_download_url"]

        return file_url, file_hash


class AgentAssetManager:
    """Agent Asset Manager."""

    logger = setup_logger(name="operate.agent_asset_manager")

    @staticmethod
    def get_agent_runner_executable_name() -> str:
        """Get runner executable name by platform running."""
        if platform.system() == "Darwin":
            os_name = "macos"
        elif platform.system() == "Windows":
            os_name = "windows"
        elif platform.system() == "Linux":
            os_name = "linux"
        else:
            raise ValueError("Platform not supported!")

        if platform.machine().lower() in ("x86_64", "amd64"):
            arch = "x64"
        elif platform.machine().lower() == "arm64":
            arch = "arm64"
            if os_name in ["windows", "linux"]:
                raise ValueError("Windows arm64 is not supported!")
        else:
            raise ValueError(f"unsupported arch: {platform.machine()}")

        exec_name = f"{AGENT_RUNNER_PREFIX}_{os_name}_{arch}"
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
            response = requests.get(url, stream=True, timeout=DEFAULT_TIMEOUT)
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
    def get_agent_release_from_service_dir(cls, service_dir: Path) -> AgentRelease:
        """Get agent release object according to public id."""
        service_config_file = service_dir / CONFIG_JSON
        service_config = json.loads(service_config_file.read_text())
        if "agent_release" not in service_config:
            raise ValueError(f"Agent release details are not found in {service_config}")
        agent_release_data = service_config["agent_release"]
        agent_release = AgentRelease(
            is_aea=agent_release_data["is_aea"],
            owner=agent_release_data["repository"]["owner"],
            repo=agent_release_data["repository"]["name"],
            release=agent_release_data["repository"]["version"],
        )
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
    def update_agent_release_asset(
        cls,
        target_path: Path,
        agent_release_asset_name: str,
        target_filename: str,
        agent_release: AgentRelease,
    ) -> None:
        """Download agent release asset (e.g., agent_runner or agent.zip)."""
        download_url, remote_file_hash = agent_release.get_url_and_hash(
            agent_release_asset_name
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
                "local and remote files hashes does not match, go to download"
            )
        else:
            cls.logger.info("local file not found, go to download")

        try:
            with TemporaryDirectory() as tmp_dir:
                tmp_file = Path(tmp_dir) / target_filename
                cls.download_file(download_url, tmp_file)
                shutil.copy2(tmp_file, target_path)
                # Make executable only for agent runner (detect by filename pattern)
                if os.name == "posix" and "agent_runner" in target_filename:
                    target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC)
        except Exception:
            # remove in case of errors
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise

    @classmethod
    def get_agent_runner_path(cls, service_dir: Path) -> str:
        """Get path to the agent runner bin placed."""
        agent_runner_name = cls.get_agent_runner_executable_name()
        agent_runner_path: Path = service_dir / agent_runner_name
        agent_release = cls.get_agent_release_from_service_dir(service_dir=service_dir)

        cls.update_agent_release_asset(
            target_path=agent_runner_path,
            agent_release_asset_name=agent_runner_name,
            target_filename=agent_runner_name,
            agent_release=agent_release,
        )
        return str(agent_runner_path)

    @classmethod
    def get_agent_code_path(cls, service_dir: Path) -> str:
        """Get path to the agent code zip archive."""
        agent_cache_dir = service_dir / "agent_cache"
        agent_cache_dir.mkdir(exist_ok=True)
        agent_zip_path: Path = agent_cache_dir / "agent.zip"
        agent_release = cls.get_agent_release_from_service_dir(service_dir=service_dir)

        cls.update_agent_release_asset(
            target_path=agent_zip_path,
            agent_release_asset_name="agent.zip",
            target_filename="agent.zip",
            agent_release=agent_release,
        )
        return str(agent_zip_path)

    @staticmethod
    def extract_agent_zip(zip_path: Path, extract_dir: Path) -> None:
        """Extract agent zip archive to directory.

        Assumes the zip contains a root folder 'agent/' and extracts its contents
        directly into extract_dir (skipping the 'agent' folder level).
        """
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for member in zip_ref.namelist():
                # Skip directories
                if member.endswith("/"):
                    continue
                # Expect all files to be under 'agent/' folder
                if not member.startswith("agent/"):
                    raise ValueError(
                        f"Unexpected file in agent.zip: {member}. "
                        "Expected all files to be under 'agent/' folder."
                    )
                # Remove 'agent/' prefix from path
                target_path = extract_dir / member[6:]  # len('agent/') = 6
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zip_ref.open(member) as source, open(target_path, "wb") as target:
                    shutil.copyfileobj(source, target)
        AgentAssetManager.logger.info(f"Extracted {zip_path} to {extract_dir}")


def get_agent_runner_path(service_dir: Path) -> str:
    """Get path to the agent runner bin placed."""
    return AgentAssetManager.get_agent_runner_path(
        service_dir=service_dir,
    )


def get_agent_code_path(service_dir: Path) -> str:
    """Get path to the agent code zip archive."""
    return AgentAssetManager.get_agent_code_path(
        service_dir=service_dir,
    )
