import stat
import os
from pathlib import Path
import platform
import shutil
from tempfile import TemporaryDirectory
from aea.configurations.data_types import PublicId
from regex import A
import requests

AGENTS_SUPPORTED = {
    "valory": {
        "trader": "https://github.com/valory-xyz/trader/releases/download/v0.0.101/",
        "optimus": "https://github.com/valory-xyz/optimus/releases/download/v0.0.101/",
    },
    "dvilela": {"memeooorr": "https://github.com/valory-xyz/meme-ooorr-test/releases/download/v0.0.3/"},
}


def get_agent_runner_executable_name():

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


def parse_agent(public_id_str):
    public_id = PublicId.from_str(public_id_string=public_id_str)
    return (public_id.author, public_id.name)


def download_file(url, save_path):
    try:
        # Send a GET request to the URL
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an error for bad status codes (4xx or 5xx)

        # Open the file in binary write mode and save the content
        with open(save_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

        print(f"File downloaded and saved to {save_path}")
    except requests.exceptions.RequestException as e:
        print(f"Error downloading file: {e}")
        raise


def download_agent_runner(
    target_path: Path, agent_runner_name: str, agent_public_id_str: str
):
    agent_author, agent_name = parse_agent(public_id_str=agent_public_id_str)
    if not agent_author in AGENTS_SUPPORTED:
        raise ValueError(f"No agents supported for author {agent_author}")
    if not agent_name in AGENTS_SUPPORTED[agent_author]:
        raise ValueError(
            f"No agent named {agent_name} supported for author {agent_author}"
        )
    repo_url = AGENTS_SUPPORTED[agent_author][agent_name]
    download_url = f"{repo_url}{agent_runner_name}"
    try:
        with TemporaryDirectory() as tmp_dir:
            tmp_file = Path(tmp_dir) / "agent_runner"
            download_file(download_url, tmp_file)
            shutil.copy2(tmp_file, target_path)
            if os.name == "posix":
                target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC)
    except:
        # remove in cae of errors
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise


def get_agent_runner_path(service_dir: Path, agent_public_id_str: str) -> str:
    agent_runner_name = get_agent_runner_executable_name()
    agent_runner_path: Path = service_dir / agent_runner_name

    if agent_runner_path.exists():
        print(f"agent runner {agent_runner_path} already exists. dont download it.")
    else:
        print(f"agent runner {agent_runner_path} does not exists. downloading it.")
        download_agent_runner(
            target_path=agent_runner_path,
            agent_runner_name=agent_runner_name,
            agent_public_id_str=agent_public_id_str,
        )
    return str(agent_runner_path)
