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

"""Service as HTTP resource."""

import json
import os
import platform
import shutil
import subprocess  # nosec
import sys
import tempfile
import time
import typing as t
import uuid
from copy import copy
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from traceback import print_exc

from aea.configurations.constants import (
    DEFAULT_LEDGER,
    LEDGER,
    PRIVATE_KEY,
    PRIVATE_KEY_PATH_SCHEMA,
    SKILL,
)
from aea.helpers.yaml_utils import yaml_dump, yaml_load, yaml_load_all
from aea_cli_ipfs.ipfs_utils import IPFSTool
from autonomy.cli.helpers.deployment import run_deployment, stop_deployment
from autonomy.configurations.constants import DEFAULT_SERVICE_CONFIG_FILE
from autonomy.configurations.loader import apply_env_variables, load_service_config
from autonomy.constants import DEFAULT_KEYS_FILE, DOCKER_COMPOSE_YAML
from autonomy.deploy.base import BaseDeploymentGenerator
from autonomy.deploy.base import ServiceBuilder as BaseServiceBuilder
from autonomy.deploy.constants import (
    AGENT_KEYS_DIR,
    BENCHMARKS_DIR,
    DEFAULT_ENCODING,
    LOG_DIR,
    PERSISTENT_DATA_DIR,
    TM_STATE_DIR,
    VENVS_DIR,
)
from autonomy.deploy.generators.docker_compose.base import DockerComposeGenerator
from autonomy.deploy.generators.kubernetes.base import KubernetesGenerator
from docker import from_env

from operate.constants import (
    AGENT_PERSISTENT_STORAGE_ENV_VAR,
    CONFIG_JSON,
    DEPLOYMENT_DIR,
    DEPLOYMENT_JSON,
    HEALTHCHECK_JSON,
)
from operate.keys import KeysManager
from operate.operate_http.exceptions import NotAllowed
from operate.operate_types import (
    Chain,
    ChainConfig,
    ChainConfigs,
    DeployedNodes,
    DeploymentConfig,
    DeploymentStatus,
    EnvVariables,
    LedgerConfig,
    LedgerConfigs,
    OnChainData,
    OnChainUserParams,
    ServiceEnvProvisionType,
    ServiceTemplate,
)
from operate.resource import LocalResource
from operate.services.deployment_runner import run_host_deployment, stop_host_deployment
from operate.services.utils import tendermint
from operate.utils.ssl import create_ssl_certificate


# pylint: disable=no-member,redefined-builtin,too-many-instance-attributes,too-many-locals

SAFE_CONTRACT_ADDRESS = "safe_contract_address"
ALL_PARTICIPANTS = "all_participants"
CONSENSUS_THRESHOLD = "consensus_threshold"
SERVICE_CONFIG_VERSION = 8
SERVICE_CONFIG_PREFIX = "sc-"

NON_EXISTENT_MULTISIG = None
NON_EXISTENT_TOKEN = -1

AGENT_TYPE_IDS = {"mech": 37, "optimus": 40, "modius": 40, "trader": 25}


def mkdirs(build_dir: Path) -> None:
    """Build necessary directories."""
    build_dir.mkdir(exist_ok=True)
    for dir_path in [
        (PERSISTENT_DATA_DIR,),
        (PERSISTENT_DATA_DIR, LOG_DIR),
        (PERSISTENT_DATA_DIR, TM_STATE_DIR),
        (PERSISTENT_DATA_DIR, BENCHMARKS_DIR),
        (PERSISTENT_DATA_DIR, VENVS_DIR),
        (AGENT_KEYS_DIR,),
    ]:
        path = Path(build_dir, *dir_path)
        path.mkdir()
        try:
            os.chown(path, 1000, 1000)
        except (PermissionError, AttributeError):
            continue


def remove_service_network(service_name: str, force: bool = True) -> None:
    """Remove service network cache."""
    client = from_env()
    network_names = (
        f"deployment_service_{service_name}_localnet",
        f"abci_build_service_{service_name}_localnet",
    )
    for network in client.networks.list(greedy=True):
        if network.attrs["Name"] not in network_names:
            continue

        if force:
            for container in network.attrs["Containers"]:
                print(f"Killing {container}")
                client.api.kill(container=container)

        print("Deleting network: " + network.attrs["Name"])
        client.api.remove_network(net_id=network.attrs["Id"])


# TODO: Backport to autonomy
class ServiceBuilder(BaseServiceBuilder):
    """Service builder patch."""

    def try_update_runtime_params(
        self,
        multisig_address: t.Optional[str] = None,
        agent_instances: t.Optional[t.List[str]] = None,
        consensus_threshold: t.Optional[int] = None,
        service_id: t.Optional[int] = None,
    ) -> None:
        """Try and update setup parameters."""

        param_overrides: t.List[t.Tuple[str, t.Any]] = []
        if multisig_address is not None:
            param_overrides.append(
                (SAFE_CONTRACT_ADDRESS, multisig_address),
            )

        if agent_instances is not None:
            param_overrides.append(
                (ALL_PARTICIPANTS, agent_instances),
            )

        if consensus_threshold is not None:
            param_overrides.append(
                (CONSENSUS_THRESHOLD, consensus_threshold),
            )

        overrides = copy(self.service.overrides)
        for override in overrides:
            (
                override,
                component_id,
                has_multiple_overrides,
            ) = self.service.process_metadata(
                configuration=override,
            )

            if component_id.component_type.value == SKILL:
                self._try_update_setup_data(
                    data=param_overrides,
                    override=override,
                    skill_id=component_id.public_id,
                    has_multiple_overrides=has_multiple_overrides,
                )
                self._try_update_tendermint_params(
                    override=override,
                    skill_id=component_id.public_id,
                    has_multiple_overrides=has_multiple_overrides,
                )
                if service_id is not None:
                    if has_multiple_overrides:
                        os.environ["ON_CHAIN_SERVICE_ID"] = str(service_id)
                    else:
                        override["models"]["params"]["args"][
                            "on_chain_service_id"
                        ] = service_id

            override["type"] = component_id.package_type.value
            override["public_id"] = str(component_id.public_id)

        self.service.overrides = overrides


class ServiceHelper:
    """Service config helper."""

    def __init__(self, path: Path) -> None:
        """Initialize object."""
        self.path = path
        self.config = load_service_config(service_path=path)
        self.config.overrides = apply_env_variables(
            self.config.overrides, os.environ.copy()
        )

    def ledger_configs(self) -> LedgerConfigs:
        """Get ledger configs."""
        ledger_configs = {}
        for override in self.config.overrides:
            if (
                override["type"] == "connection"
                and "valory/ledger" in override["public_id"]
            ):
                if 0 in override:  # take the values from the first config
                    override = override[0]

                for _, config in override["config"]["ledger_apis"].items():
                    # TODO chain name is inferred from the chain_id. The actual id provided on service.yaml is ignored.
                    chain = Chain.from_id(chain_id=config["chain_id"])  # type: ignore
                    ledger_configs[chain.value] = LedgerConfig(
                        rpc=config["address"],
                        chain=chain,
                    )
        return ledger_configs

    def deployment_config(self) -> DeploymentConfig:
        """Returns deployment config."""
        return DeploymentConfig(self.config.json.get("deployment", {}))  # type: ignore


# TODO: Port back to open-autonomy
class HostDeploymentGenerator(BaseDeploymentGenerator):
    """Host deployment."""

    output_name: str = "runtime.json"
    deployment_type: str = "host"

    def generate_config_tendermint(self) -> "HostDeploymentGenerator":
        """Generate tendermint configuration."""
        tmhome = str(self.build_dir / "node")
        tendermint_executable = str(
            shutil.which("tendermint"),
        )
        env = {}
        env["PATH"] = os.path.dirname(sys.executable) + ":" + os.environ["PATH"]
        tendermint_executable = str(
            Path(os.path.dirname(sys.executable)) / "tendermint"
        )

        if platform.system() == "Windows":
            env["PATH"] = os.path.dirname(sys.executable) + ";" + os.environ["PATH"]
            tendermint_executable = str(
                Path(os.path.dirname(sys.executable)) / "tendermint.exe"
            )

        if not (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")):
            # we dont run inside pyinstaller, mean DEV mode!
            tendermint_executable = "tendermint"
            if platform.system() == "Windows":
                tendermint_executable = "tendermint.exe"

        subprocess.run(  # pylint: disable=subprocess-run-check # nosec
            args=[
                tendermint_executable,
                "--home",
                tmhome,
                "init",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # TODO: Dynamic port allocation
        params = {
            "TMHOME": tmhome,
            "TMSTATE": str(self.build_dir / "tm_state"),
            "P2P_LADDR": "tcp://localhost:26656",
            "RPC_LADDR": "tcp://localhost:26657",
            "PROXY_APP": "tcp://localhost:26658",
            "CREATE_EMPTY_BLOCKS": "true",
            "USE_GRPC": "false",
            "FLASK_APP": "tendermint:create_server",
        }
        (self.build_dir / "tendermint.json").write_text(
            json.dumps(params, indent=2),
            encoding="utf-8",
        )
        shutil.copy(
            tendermint.__file__.replace(".pyc", ".py"),
            self.build_dir / "tendermint.py",
        )
        return self

    def generate(
        self,
        image_version: t.Optional[str] = None,
        use_hardhat: bool = False,
        use_acn: bool = False,
    ) -> "HostDeploymentGenerator":
        """Generate agent and tendermint configurations"""
        agent = self.service_builder.generate_agent(agent_n=0)
        agent = {key: f"{value}" for key, value in agent.items()}
        (self.build_dir / "agent.json").write_text(
            json.dumps(agent, indent=2),
            encoding="utf-8",
        )
        return self

    def _populate_keys(self) -> None:
        """Populate the keys directory"""
        # TODO: Add multiagent support
        kp, *_ = t.cast(t.List[t.Dict[str, str]], self.service_builder.keys)
        key = kp[PRIVATE_KEY]
        ledger = kp.get(LEDGER, DEFAULT_LEDGER)
        keys_file = self.build_dir / PRIVATE_KEY_PATH_SCHEMA.format(ledger)
        keys_file.write_text(key, encoding=DEFAULT_ENCODING)

    def _populate_keys_multiledger(self) -> None:
        """Populate the keys directory with multiple set of keys"""

    def populate_private_keys(self) -> "DockerComposeGenerator":
        """Populate the private keys to the build directory for host mapping."""
        if self.service_builder.multiledger:
            self._populate_keys_multiledger()
        else:
            self._populate_keys()
        return self


@dataclass
class Deployment(LocalResource):
    """Deployment resource for a service."""

    status: DeploymentStatus
    nodes: DeployedNodes
    path: Path

    _file = DEPLOYMENT_JSON

    @staticmethod
    def new(path: Path) -> "Deployment":
        """
        Create a new deployment

        :param path: Path to service
        :return: Deployment object
        """
        deployment = Deployment(
            status=DeploymentStatus.CREATED,
            nodes=DeployedNodes(agent=[], tendermint=[]),
            path=path,
        )
        deployment.store()
        return deployment

    @classmethod
    def load(cls, path: Path) -> "Deployment":
        """Load a service"""
        return super().load(path)  # type: ignore

    def copy_previous_agent_run_logs(self) -> None:
        """Copy previous agent logs."""
        source_path = self.path / DEPLOYMENT_DIR / "agent" / "log.txt"
        destination_path = self.path / "prev_log.txt"
        if source_path.exists():
            shutil.copy(source_path, destination_path)

    def _build_kubernetes(self, force: bool = True) -> None:
        """Build kubernetes deployment."""
        k8s_build = self.path / DEPLOYMENT_DIR / "abci_build_k8s"
        if k8s_build.exists() and force:
            shutil.rmtree(k8s_build)
        mkdirs(build_dir=k8s_build)

        service = Service.load(path=self.path)
        builder = ServiceBuilder.from_dir(
            path=service.package_absolute_path,
            keys_file=self.path / DEFAULT_KEYS_FILE,
            number_of_agents=len(service.agent_addresses),
        )
        builder.deplopyment_type = KubernetesGenerator.deployment_type
        (
            KubernetesGenerator(
                service_builder=builder,
                build_dir=k8s_build.resolve(),
                use_tm_testnet_setup=True,
                image_author=builder.service.author,
            )
            .generate()
            .generate_config_tendermint()
            .write_config()
            .populate_private_keys()
        )
        print(f"Kubernetes deployment built on {k8s_build.resolve()}\n")

    def _build_docker(
        self,
        force: bool = True,
        chain: t.Optional[str] = None,
    ) -> None:
        """Build docker deployment."""
        service = Service.load(path=self.path)
        # Remove network from cache if exists, this will raise an error
        # if the service is still running so we can do an early exit
        remove_service_network(
            service_name=service.helper.config.name,
            force=force,
        )

        build = self.path / DEPLOYMENT_DIR
        if build.exists() and not force:
            return
        if build.exists() and force:
            self.copy_previous_agent_run_logs()
            shutil.rmtree(build)
        mkdirs(build_dir=build)

        keys_file = self.path / DEFAULT_KEYS_FILE
        keys_file.write_text(
            json.dumps(
                [
                    KeysManager().get(address).json
                    for address in service.agent_addresses
                ],
                indent=4,
            ),
            encoding="utf-8",
        )
        try:
            builder = ServiceBuilder.from_dir(
                path=service.package_absolute_path,
                keys_file=keys_file,
                number_of_agents=len(service.agent_addresses),
            )
            builder.deplopyment_type = DockerComposeGenerator.deployment_type
            builder.try_update_abci_connection_params()

            if not chain:
                chain = service.home_chain

            chain_config = service.chain_configs[chain]
            chain_data = chain_config.chain_data

            builder.try_update_runtime_params(
                multisig_address=chain_data.multisig,
                agent_instances=chain_data.instances,
                service_id=chain_data.token,
                consensus_threshold=None,
            )

            # build docker-compose deployment
            (
                DockerComposeGenerator(
                    service_builder=builder,
                    build_dir=build.resolve(),
                    use_tm_testnet_setup=True,
                    image_author=builder.service.author,
                )
                .generate()
                .generate_config_tendermint()
                .write_config()
                .populate_private_keys()
            )
            print(f"Docker Compose deployment built on {build.resolve()} \n")

        except Exception as e:
            shutil.rmtree(build)
            raise e

        with (build / DOCKER_COMPOSE_YAML).open("r", encoding="utf-8") as stream:
            deployment = yaml_load(stream=stream)

        self.nodes = DeployedNodes(
            agent=[
                service for service in deployment["services"] if "_abci_" in service
            ],
            tendermint=[
                service for service in deployment["services"] if "_tm_" in service
            ],
        )

        _volumes = []
        for volume, mount in (
            service.helper.deployment_config().get("volumes", {}).items()
        ):
            (build / volume).mkdir(exist_ok=True)
            _volumes.append(f"./{volume}:{mount}:Z")

        for node in deployment["services"]:
            if "abci" in node:
                deployment["services"][node]["volumes"].extend(_volumes)
                new_mappings = []
                for mapping in deployment["services"][node]["volumes"]:
                    if mapping.startswith("./data"):
                        (self.path / "persistent_data").mkdir(
                            exist_ok=True, parents=True
                        )
                        mapping = mapping.replace("./data", "../persistent_data")

                    new_mappings.append(mapping)

                deployment["services"][node]["volumes"] = new_mappings

        with (build / DOCKER_COMPOSE_YAML).open("w", encoding="utf-8") as stream:
            yaml_dump(data=deployment, stream=stream)

        self.status = DeploymentStatus.BUILT
        self.store()

    def _build_host(self, force: bool = True, chain: t.Optional[str] = None) -> None:
        """Build host depployment."""
        build = self.path / DEPLOYMENT_DIR
        if build.exists() and not force:
            return

        if build.exists() and force:
            stop_host_deployment(build_dir=build)
            try:
                # sleep needed to ensure all processes closed/killed otherwise it will block directory removal on windows
                time.sleep(3)
                self.copy_previous_agent_run_logs()
                shutil.rmtree(build)
            except:  # noqa  # pylint: disable=bare-except
                # sleep and try again. exception if fails
                print_exc()
                time.sleep(3)
                shutil.rmtree(build)

        service = Service.load(path=self.path)
        if service.helper.config.number_of_agents > 1:
            raise RuntimeError(
                "Host deployment currently only supports single agent deployments"
            )

        if not chain:
            chain = service.home_chain

        chain_config = service.chain_configs[chain]
        chain_data = chain_config.chain_data

        keys_file = self.path / DEFAULT_KEYS_FILE
        keys_file.write_text(
            json.dumps(
                [
                    KeysManager().get(address).json
                    for address in service.agent_addresses
                ],
                indent=4,
            ),
            encoding="utf-8",
        )
        try:
            builder = ServiceBuilder.from_dir(
                path=service.package_absolute_path,
                keys_file=keys_file,
                number_of_agents=len(service.agent_addresses),
            )
            builder.deplopyment_type = HostDeploymentGenerator.deployment_type
            builder.try_update_abci_connection_params()
            builder.try_update_runtime_params(
                multisig_address=chain_data.multisig,
                agent_instances=chain_data.instances,
                service_id=chain_data.token,
                consensus_threshold=None,
            )

            (
                HostDeploymentGenerator(
                    service_builder=builder,
                    build_dir=build.resolve(),
                    use_tm_testnet_setup=True,
                )
                .generate_config_tendermint()
                .generate()
                .populate_private_keys()
            )

        except Exception as e:
            if build.exists():
                shutil.rmtree(build)
            raise e

        self.status = DeploymentStatus.BUILT
        self.store()

    def build(
        self,
        use_docker: bool = False,
        use_kubernetes: bool = False,
        force: bool = True,
        chain: t.Optional[str] = None,
    ) -> None:
        """
        Build a deployment

        :param use_docker: Use a Docker Compose deployment. If True, then no host deployment.
        :param use_kubernetes: Build Kubernetes deployment. If True, then no host deployment.
        :param force: Remove existing deployment and build a new one
        :param chain: Chain to set runtime parameters on the deployment (home_chain if not provided).
        :return: Deployment object
        """
        # TODO: Maybe remove usage of chain and use home_chain always?
        original_env = os.environ.copy()
        service = Service.load(path=self.path)

        if use_docker or use_kubernetes:
            ssl_key_path, ssl_cert_path = create_ssl_certificate(
                ssl_dir=service.path / PERSISTENT_DATA_DIR / "ssl"
            )
            service.update_env_variables_values(
                {
                    "STORE_PATH": "/data",
                    "SSL_KEY_PATH": (
                        Path("/data") / "ssl" / ssl_key_path.name
                    ).as_posix(),
                    "SSL_CERT_PATH": (
                        Path("/data") / "ssl" / ssl_cert_path.name
                    ).as_posix(),
                }
            )
            service.consume_env_variables()
            if use_docker:
                self._build_docker(force=force, chain=chain)
            if use_kubernetes:
                self._build_kubernetes(force=force)
        else:
            ssl_key_path, ssl_cert_path = create_ssl_certificate(
                ssl_dir=service.path / DEPLOYMENT_DIR / "ssl"
            )
            service.update_env_variables_values(
                {
                    "SSL_KEY_PATH": str(ssl_key_path),
                    "SSL_CERT_PATH": str(ssl_cert_path),
                }
            )
            service.consume_env_variables()
            self._build_host(force=force, chain=chain)

        os.environ.clear()
        os.environ.update(original_env)

    def start(self, use_docker: bool = False) -> None:
        """Start the service"""
        if self.status != DeploymentStatus.BUILT:
            raise NotAllowed(
                f"The deployment is in {self.status}; It needs to be in {DeploymentStatus.BUILT} status"
            )

        self.status = DeploymentStatus.DEPLOYING
        self.store()

        try:
            if use_docker:
                run_deployment(
                    build_dir=self.path / "deployment",
                    detach=True,
                    project_name=self.path.name,
                )
            else:
                run_host_deployment(build_dir=self.path / "deployment")
        except Exception:
            self.status = DeploymentStatus.BUILT
            self.store()
            raise

        self.status = DeploymentStatus.DEPLOYED
        self.store()

    def stop(self, use_docker: bool = False, force: bool = False) -> None:
        """Stop the deployment."""
        if self.status != DeploymentStatus.DEPLOYED and not force:
            return

        self.status = DeploymentStatus.STOPPING
        self.store()

        if use_docker:
            stop_deployment(
                build_dir=self.path / "deployment",
                project_name=self.path.name,
            )
        else:
            stop_host_deployment(build_dir=self.path / "deployment")

        self.status = DeploymentStatus.BUILT
        self.store()

    def delete(self) -> None:
        """Delete the deployment."""
        build = self.path / DEPLOYMENT_DIR
        shutil.rmtree(build)
        self.status = DeploymentStatus.DELETED
        self.store()


@dataclass
class Service(LocalResource):
    """Service class."""

    version: int
    service_config_id: str
    hash: str
    hash_history: t.Dict[int, str]
    agent_addresses: t.List[str]
    home_chain: str
    chain_configs: ChainConfigs
    description: str
    env_variables: EnvVariables

    path: Path
    package_path: Path

    name: t.Optional[str] = None

    _helper: t.Optional[ServiceHelper] = None
    _deployment: t.Optional[Deployment] = None

    _file = CONFIG_JSON

    @staticmethod
    def determine_agent_id(service_name: str) -> int:
        """Determine the appropriate agent ID based on service name."""
        service_name_lower = service_name.lower()
        if "mech" in service_name_lower:
            return AGENT_TYPE_IDS["mech"]
        if "optimus" in service_name_lower:
            return AGENT_TYPE_IDS["optimus"]
        if "modius" in service_name_lower:
            return AGENT_TYPE_IDS["modius"]
        return AGENT_TYPE_IDS["trader"]

    @classmethod
    def load(cls, path: Path) -> "Service":
        """Load a service"""
        return super().load(path)  # type: ignore

    @property
    def helper(self) -> ServiceHelper:
        """Get service helper."""
        if self._helper is None:
            self._helper = ServiceHelper(path=self.package_absolute_path)
        return t.cast(ServiceHelper, self._helper)

    @property
    def deployment(self) -> Deployment:
        """Load deployment object for the service."""
        if not (self.path / DEPLOYMENT_JSON).exists():
            self._deployment = Deployment.new(path=self.path)
        try:
            self._deployment = Deployment.load(path=self.path)
        except JSONDecodeError:
            self._deployment = Deployment.new(path=self.path)
        return t.cast(Deployment, self._deployment)

    @property
    def package_absolute_path(self) -> Path:
        """Get the package_absolute_path."""
        self._ensure_package_exists()
        package_absolute_path = self.path / self.package_path
        return package_absolute_path

    def _ensure_package_exists(self) -> None:
        package_absolute_path = self.path / self.package_path
        if (
            not package_absolute_path.exists()
            or not (package_absolute_path / DEFAULT_SERVICE_CONFIG_FILE).exists()
        ):
            with tempfile.TemporaryDirectory(dir=self.path) as temp_dir:
                package_temp_path = Path(
                    IPFSTool().download(
                        hash_id=self.hash,
                        target_dir=temp_dir,
                    )
                )
                target_path = self.path / package_temp_path.name

                if target_path.exists():
                    shutil.rmtree(target_path)

                shutil.move(package_temp_path, target_path)
                self.package_path = Path(target_path.name)
                self.store()

    @staticmethod
    def new(  # pylint: disable=too-many-locals
        agent_addresses: t.List[str],
        service_template: ServiceTemplate,
        storage: Path,
    ) -> "Service":
        """Create a new service."""

        service_config_id = Service.get_new_service_config_id(storage)
        path = storage / service_config_id
        path.mkdir()
        package_absolute_path = Path(
            IPFSTool().download(
                hash_id=service_template["hash"],
                target_dir=path,
            )
        )

        ledger_configs = ServiceHelper(path=package_absolute_path).ledger_configs()

        chain_configs = {}
        for chain, config in service_template["configurations"].items():
            ledger_config = ledger_configs[chain]
            ledger_config.rpc = config["rpc"]

            chain_data = OnChainData(
                instances=[],
                token=NON_EXISTENT_TOKEN,
                multisig=NON_EXISTENT_MULTISIG,
                user_params=OnChainUserParams.from_json(config),  # type: ignore
            )

            chain_configs[chain] = ChainConfig(
                ledger_config=ledger_config,
                chain_data=chain_data,
            )

        current_timestamp = int(time.time())
        service = Service(
            version=SERVICE_CONFIG_VERSION,
            service_config_id=service_config_id,
            name=service_template["name"],
            description=service_template["description"],
            hash=service_template["hash"],
            agent_addresses=agent_addresses,
            home_chain=service_template["home_chain"],
            hash_history={current_timestamp: service_template["hash"]},
            chain_configs=chain_configs,
            path=package_absolute_path.parent,
            package_path=Path(package_absolute_path.name),
            env_variables=service_template["env_variables"],
        )
        service.store()
        return service

    def service_public_id(self, include_version: bool = True) -> str:
        """Get the public id (based on the service hash)."""
        with (self.package_absolute_path / DEFAULT_SERVICE_CONFIG_FILE).open(
            "r", encoding="utf-8"
        ) as fp:
            service_yaml, *_ = yaml_load_all(fp)

        public_id = f"{service_yaml['author']}/{service_yaml['name']}"

        if include_version:
            public_id += f":{service_yaml['version']}"

        return public_id

    @staticmethod
    def get_service_public_id(
        hash: str, temp_dir: t.Optional[Path] = None, include_version: bool = True
    ) -> str:
        """
        Get the service public ID from IPFS based on the hash.

        :param hash: The IPFS hash of the service.
        :param dir: Optional directory path where the temporary download folder will be created.
                    If None, a system-default temporary directory will be used.
        :return: The public ID of the service in the format "author/name:version".
        """
        with tempfile.TemporaryDirectory(dir=temp_dir) as path:
            package_path = Path(
                IPFSTool().download(
                    hash_id=hash,
                    target_dir=path,
                )
            )

            with (package_path / DEFAULT_SERVICE_CONFIG_FILE).open(
                "r", encoding="utf-8"
            ) as fp:
                service_yaml, *_ = yaml_load_all(fp)

            public_id = f"{service_yaml['author']}/{service_yaml['name']}"

            if include_version:
                public_id += f":{service_yaml['version']}"

            return public_id

    @staticmethod
    def get_new_service_config_id(path: Path) -> str:
        """Get a new service config id that does not clash with any directory in path."""
        while True:
            service_config_id = f"{SERVICE_CONFIG_PREFIX}{uuid.uuid4()}"
            new_path = path.parent / service_config_id
            if not new_path.exists():
                return service_config_id

    def get_latest_healthcheck(self) -> t.Dict:
        """Return the latest stored healthcheck.json"""
        healthcheck_json_path = self.path / HEALTHCHECK_JSON

        if not healthcheck_json_path.exists():
            return {}

        try:
            with open(healthcheck_json_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (IOError, json.JSONDecodeError) as e:
            return {"error": f"Error reading healthcheck.json: {e}"}

    def remove_latest_healthcheck(self) -> None:
        """Remove the latest healthcheck.json, if it exists"""
        healthcheck_json_path = self.path / HEALTHCHECK_JSON

        if healthcheck_json_path.exists():
            try:
                healthcheck_json_path.unlink()
            except Exception as e:  # pylint: disable=broad-except
                print(f"Exception deleting {healthcheck_json_path}: {e}")

    def get_agent_performance(self) -> t.Dict:
        """Return the agent activity"""

        # Default values
        agent_performance: t.Dict[str, t.Any] = {
            "timestamp": None,
            "metrics": [],
            "last_activity": None,
            "last_chat_message": None,
        }

        agent_performance_json_path = (
            Path(
                self.env_variables.get(
                    AGENT_PERSISTENT_STORAGE_ENV_VAR, {"value": "."}
                ).get("value", ".")
            )
            / "agent_performance.json"
        )

        if agent_performance_json_path.exists():
            try:
                with open(agent_performance_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    agent_performance.update(data)
            except (json.JSONDecodeError, OSError) as e:
                # Keep default values if file is invalid
                print(
                    f"Error reading file 'agent_performance.json': {e}"
                )  # TODO Use logger

        return dict(sorted(agent_performance.items()))

    def update(
        self,
        service_template: ServiceTemplate,
        allow_different_service_public_id: bool = False,
        partial_update: bool = False,
    ) -> None:
        """Update service."""

        target_hash = service_template.get("hash")
        if target_hash:
            target_service_public_id = Service.get_service_public_id(
                target_hash, self.path
            )

            if not allow_different_service_public_id and (
                self.service_public_id() != target_service_public_id
            ):
                raise ValueError(
                    f"Trying to update a service with a different public id: {self.service_public_id()=} {self.hash=} {target_service_public_id=} {target_hash=}."
                )

        self.hash = service_template.get("hash", self.hash)

        # hash_history - Only update if latest inserted hash is different
        if self.hash_history[max(self.hash_history.keys())] != self.hash:
            current_timestamp = int(time.time())
            self.hash_history[current_timestamp] = self.hash

        self.home_chain = service_template.get("home_chain", self.home_chain)
        self.description = service_template.get("description", self.description)
        self.name = service_template.get("name", self.name)

        package_absolute_path = self.path / self.package_path
        if package_absolute_path.exists():
            shutil.rmtree(package_absolute_path)

        package_absolute_path = Path(
            IPFSTool().download(
                hash_id=self.hash,
                target_dir=self.path,
            )
        )
        self.package_path = Path(package_absolute_path.name)

        # env_variables
        if partial_update:
            for var, attrs in service_template.get("env_variables", {}).items():
                self.env_variables.setdefault(var, {}).update(attrs)
        else:
            self.env_variables = service_template["env_variables"]

        # chain_configs
        # TODO support remove chains for non-partial updates
        # TODO ensure all and only existing chains are passed for non-partial updates
        ledger_configs = ServiceHelper(path=self.package_absolute_path).ledger_configs()
        for chain, new_config in service_template.get("configurations", {}).items():
            if chain in self.chain_configs:
                # The template is providing a chain configuration that already
                # exists in this service - update only the user parameters.
                # This is to avoid losing on-chain data like safe, token, etc.
                if partial_update:
                    config = self.chain_configs[chain].chain_data.user_params.json
                    config.update(new_config)
                else:
                    config = new_config

                self.chain_configs[
                    chain
                ].chain_data.user_params = OnChainUserParams.from_json(
                    config  # type: ignore
                )
            else:
                # The template is providing a chain configuration that does
                # not currently exist in this service - copy all config as
                # when creating a new service.
                ledger_config = ledger_configs[chain]
                ledger_config.rpc = new_config["rpc"]

                chain_data = OnChainData(
                    instances=[],
                    token=NON_EXISTENT_TOKEN,
                    multisig=NON_EXISTENT_MULTISIG,
                    user_params=OnChainUserParams.from_json(new_config),  # type: ignore
                )

                self.chain_configs[chain] = ChainConfig(
                    ledger_config=ledger_config,
                    chain_data=chain_data,
                )

        self.store()

    def update_user_params_from_template(
        self, service_template: ServiceTemplate
    ) -> None:
        """Update user params from template."""
        for chain, config in service_template["configurations"].items():
            self.chain_configs[
                chain
            ].chain_data.user_params = OnChainUserParams.from_json(
                config  # type: ignore
            )

            self.chain_configs[chain].ledger_config.rpc = config["rpc"]

        self.store()

    def consume_env_variables(self) -> None:
        """Consume (apply) environment variables.

        Note that this method modifies os.environ. Consider if you need a backup of os.environ before using this method.
        """
        for env_var, attributes in self.env_variables.items():
            os.environ[env_var] = str(attributes["value"])

    def update_env_variables_values(
        self, env_var_to_value: t.Dict[str, t.Any], except_if_undefined: bool = False
    ) -> None:
        """
        Updates and stores the values of the env variables to override service.yaml on the deployment.

        This method does not apply the variables to the environment. Use consume_env_variables to apply the
        env variables.
        """

        updated = False
        for var, value in env_var_to_value.items():
            value_str = str(value)
            attributes = self.env_variables.get(var)
            if (
                attributes
                and self.env_variables[var]["provision_type"]
                == ServiceEnvProvisionType.COMPUTED
                and attributes["value"] != value_str
            ):
                attributes["value"] = value_str
                updated = True
            elif except_if_undefined:
                raise ValueError(
                    f"Trying to set value for an environment variable ({var}) not present on service configuration {self.service_config_id}."
                )

        if updated:
            self.store()
