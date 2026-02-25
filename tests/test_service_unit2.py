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

"""Unit tests for operate/services/service.py (coverage completion)."""

import json
import os
import time
import typing as t
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.constants import (
    DEPLOYMENT_DIR,
    DEPLOYMENT_JSON,
    HEALTHCHECK_JSON,
    ZERO_ADDRESS,
)
from operate.operate_http.exceptions import NotAllowed
from operate.operate_types import (
    Chain,
    ChainAmounts,
    DeployedNodes,
    DeploymentStatus,
    LedgerConfig,
    ServiceEnvProvisionType,
)
from operate.serialization import BigInt
from operate.services.service import (
    Deployment,
    HostDeploymentGenerator,
    Service,
    ServiceHelper,
    remove_service_network,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_ADDR = "0x" + "a" * 40
_MULTISIG_ADDR = "0x" + "b" * 40
_HASH = "bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u"


def _write_service_config(service_dir: Path, **overrides: t.Any) -> None:
    """Write a minimal v9 service config.json to service_dir."""
    cfg: t.Dict[str, t.Any] = {
        "version": 9,
        "service_config_id": "sc-00000000-0000-0000-0000-000000000000",
        "hash": _HASH,
        "hash_history": {str(int(time.time())): _HASH},
        "agent_addresses": [_AGENT_ADDR],
        "home_chain": "gnosis",
        "chain_configs": {
            "gnosis": {
                "ledger_config": {"rpc": "https://rpc.gnosis.io", "chain": "gnosis"},
                "chain_data": {
                    "instances": [_AGENT_ADDR],
                    "token": -1,
                    "multisig": None,
                    "staked": False,
                    "on_chain_state": 1,
                    "user_params": {
                        "staking_program_id": "no_staking",
                        "nft": "bafybeinft",
                        "agent_id": 25,
                        "cost_of_bond": 10000000000000000,
                        "fund_requirements": {
                            ZERO_ADDRESS: {
                                "agent": 100000000000000000,
                                "safe": 5000000000000000000,
                            }
                        },
                    },
                },
            }
        },
        "description": "Test service",
        "env_variables": {},
        "package_path": "trader_pearl",
        "name": "Test",
        "agent_release": {
            "is_aea": True,
            "repository": {
                "owner": "valory-xyz",
                "name": "trader",
                "version": "v0.0.1",
            },
        },
    }
    cfg.update(overrides)
    (service_dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def _make_service(tmp_path: Path, **overrides: t.Any) -> Service:
    """Create a Service on disk and load it."""
    service_dir = tmp_path / "sc-test"
    service_dir.mkdir(parents=True)
    _write_service_config(service_dir, **overrides)
    return Service.load(path=service_dir)


def _make_deployment(tmp_path: Path, status: DeploymentStatus) -> Deployment:
    """Create a Deployment with given status, stored on disk."""
    depl = Deployment(
        status=status,
        nodes=DeployedNodes(agent=[], tendermint=[]),
        path=tmp_path,
    )
    depl.store()
    return depl


# ---------------------------------------------------------------------------
# tests for remove_service_network
# ---------------------------------------------------------------------------


class TestRemoveServiceNetwork:
    """Tests for remove_service_network()."""

    def test_matching_network_force_kills_and_removes(self) -> None:
        """Matching network with force=True calls kill() and remove_network()."""
        mock_network = MagicMock()
        mock_network.attrs = {
            "Name": "deployment_service_myservice_localnet",
            "Containers": {"container1": {}},
            "Id": "net123",
        }
        mock_client = MagicMock()
        mock_client.networks.list.return_value = [mock_network]

        with patch("operate.services.service.from_env", return_value=mock_client):
            remove_service_network("myservice", force=True)

        mock_client.api.kill.assert_called_once_with(container="container1")
        mock_client.api.remove_network.assert_called_once_with(net_id="net123")

    def test_matching_network_no_force_skips_kill(self) -> None:
        """Matching network with force=False skips kill() but still removes."""
        mock_network = MagicMock()
        mock_network.attrs = {
            "Name": "abci_build_service_myservice_localnet",
            "Containers": {"container1": {}},
            "Id": "net456",
        }
        mock_client = MagicMock()
        mock_client.networks.list.return_value = [mock_network]

        with patch("operate.services.service.from_env", return_value=mock_client):
            remove_service_network("myservice", force=False)

        mock_client.api.kill.assert_not_called()
        mock_client.api.remove_network.assert_called_once_with(net_id="net456")

    def test_non_matching_network_not_removed(self) -> None:
        """Network with a different name is not removed."""
        mock_network = MagicMock()
        mock_network.attrs = {
            "Name": "some_other_network",
            "Containers": {},
            "Id": "net789",
        }
        mock_client = MagicMock()
        mock_client.networks.list.return_value = [mock_network]

        with patch("operate.services.service.from_env", return_value=mock_client):
            remove_service_network("myservice", force=True)

        mock_client.api.kill.assert_not_called()
        mock_client.api.remove_network.assert_not_called()

    def test_multiple_containers_all_killed(self) -> None:
        """All containers in a matching network are killed."""
        mock_network = MagicMock()
        mock_network.attrs = {
            "Name": "deployment_service_svc_localnet",
            "Containers": {"c1": {}, "c2": {}, "c3": {}},
            "Id": "netabc",
        }
        mock_client = MagicMock()
        mock_client.networks.list.return_value = [mock_network]

        with patch("operate.services.service.from_env", return_value=mock_client):
            remove_service_network("svc", force=True)

        assert mock_client.api.kill.call_count == 3
        mock_client.api.remove_network.assert_called_once()


# ---------------------------------------------------------------------------
# tests for ServiceHelper
# ---------------------------------------------------------------------------


class TestServiceHelper:
    """Tests for ServiceHelper.__init__, ledger_configs, deployment_config."""

    def test_init_loads_config(self, tmp_path: Path) -> None:
        """ServiceHelper.__init__ calls load_service_config and apply_env_variables."""
        mock_config = MagicMock()
        mock_config.overrides = []

        with patch(
            "operate.services.service.load_service_config", return_value=mock_config
        ) as mock_load, patch(
            "operate.services.service.apply_env_variables", return_value=[]
        ) as mock_apply:
            helper = ServiceHelper(path=tmp_path)

        mock_load.assert_called_once_with(service_path=tmp_path)
        mock_apply.assert_called_once()
        assert helper.config is mock_config

    def test_ledger_configs_returns_chain_rpc(self, tmp_path: Path) -> None:
        """ledger_configs() parses valory/ledger overrides and returns LedgerConfigs."""
        mock_config = MagicMock()
        mock_config.overrides = [
            {
                "type": "connection",
                "public_id": "valory/ledger:0.19.0",
                "config": {
                    "ledger_apis": {
                        "gnosis": {"chain_id": 100, "address": "https://rpc.gnosis.io"}
                    }
                },
            }
        ]

        with patch(
            "operate.services.service.load_service_config", return_value=mock_config
        ), patch(
            "operate.services.service.apply_env_variables",
            return_value=mock_config.overrides,
        ):
            helper = ServiceHelper(path=tmp_path)

        result = helper.ledger_configs()
        assert "gnosis" in result
        assert result["gnosis"].rpc == "https://rpc.gnosis.io"
        assert result["gnosis"].chain == Chain.GNOSIS

    def test_ledger_configs_override_index_zero_format(self, tmp_path: Path) -> None:
        """ledger_configs() handles the override[0] dict format (multi-override)."""
        inner_override = {
            "type": "connection",
            "public_id": "valory/ledger:0.19.0",
            "config": {
                "ledger_apis": {
                    "gnosis": {"chain_id": 100, "address": "https://rpc2.gnosis.io"}
                }
            },
        }
        # override has an integer key 0 -- triggers the "take values from first config" branch
        outer_override = {
            0: inner_override,
            "type": "connection",
            "public_id": "valory/ledger:0.19.0",
        }
        mock_config = MagicMock()
        mock_config.overrides = [outer_override]

        with patch(
            "operate.services.service.load_service_config", return_value=mock_config
        ), patch(
            "operate.services.service.apply_env_variables",
            return_value=mock_config.overrides,
        ):
            helper = ServiceHelper(path=tmp_path)

        result = helper.ledger_configs()
        assert "gnosis" in result
        assert result["gnosis"].rpc == "https://rpc2.gnosis.io"

    def test_ledger_configs_non_ledger_override_skipped(self, tmp_path: Path) -> None:
        """ledger_configs() ignores overrides that are not valory/ledger connections."""
        mock_config = MagicMock()
        mock_config.overrides = [
            {"type": "skill", "public_id": "valory/abstract_round_abci:0.1.0"}
        ]

        with patch(
            "operate.services.service.load_service_config", return_value=mock_config
        ), patch(
            "operate.services.service.apply_env_variables",
            return_value=mock_config.overrides,
        ):
            helper = ServiceHelper(path=tmp_path)

        result = helper.ledger_configs()
        assert result == {}

    def test_deployment_config_returns_deployment_dict(self, tmp_path: Path) -> None:
        """deployment_config() returns DeploymentConfig from config.json 'deployment' key."""
        mock_config = MagicMock()
        mock_config.overrides = []
        mock_config.json = {"deployment": {"image": "myimage:latest"}}

        with patch(
            "operate.services.service.load_service_config", return_value=mock_config
        ), patch("operate.services.service.apply_env_variables", return_value=[]):
            helper = ServiceHelper(path=tmp_path)

        result = helper.deployment_config()
        assert result == {"image": "myimage:latest"}

    def test_deployment_config_missing_key_returns_empty(self, tmp_path: Path) -> None:
        """deployment_config() returns empty DeploymentConfig when no 'deployment' key."""
        mock_config = MagicMock()
        mock_config.overrides = []
        mock_config.json = {}

        with patch(
            "operate.services.service.load_service_config", return_value=mock_config
        ), patch("operate.services.service.apply_env_variables", return_value=[]):
            helper = ServiceHelper(path=tmp_path)

        result = helper.deployment_config()
        assert result == {}


# ---------------------------------------------------------------------------
# tests for HostDeploymentGenerator (generate, _populate_keys, populate_private_keys)
# ---------------------------------------------------------------------------


class TestHostDeploymentGenerator:
    """Tests for HostDeploymentGenerator methods."""

    def _make_generator(self, tmp_path: Path) -> HostDeploymentGenerator:
        """Create a HostDeploymentGenerator with a mocked service_builder."""
        mock_sb = MagicMock()
        mock_sb.generate_agent.return_value = {"key1": "val1", "key2": 42}
        mock_sb.keys = [{"private_key": "0xdeadbeef", "ledger": "ethereum"}]
        mock_sb.multiledger = False

        gen = HostDeploymentGenerator.__new__(HostDeploymentGenerator)
        gen.service_builder = mock_sb  # type: ignore[attr-defined]
        gen.build_dir = tmp_path / "build"  # type: ignore[attr-defined]
        return gen

    def test_generate_creates_agent_json(self, tmp_path: Path) -> None:
        """generate() writes agent.json with all values converted to strings."""
        gen = self._make_generator(tmp_path)
        gen.generate()

        agent_json_path = tmp_path / "build" / "agent.json"
        assert agent_json_path.exists()
        data = json.loads(agent_json_path.read_text(encoding="utf-8"))
        assert data == {"key1": "val1", "key2": "42"}

    def test_generate_creates_agent_subdir(self, tmp_path: Path) -> None:
        """generate() creates the 'agent' subdirectory."""
        gen = self._make_generator(tmp_path)
        gen.generate()

        assert (tmp_path / "build" / "agent").is_dir()

    def test_generate_returns_self(self, tmp_path: Path) -> None:
        """generate() returns self for chaining."""
        gen = self._make_generator(tmp_path)
        result = gen.generate()
        assert result is gen

    def test_populate_keys_writes_private_key_file(self, tmp_path: Path) -> None:
        """_populate_keys() writes the private key to the correct file path."""
        gen = self._make_generator(tmp_path)
        gen.build_dir.mkdir(parents=True)
        gen._populate_keys()

        key_file = gen.build_dir / "ethereum_private_key.txt"
        assert key_file.exists()
        assert key_file.read_text(encoding="utf-8") == "0xdeadbeef"

    def test_populate_keys_default_ledger(self, tmp_path: Path) -> None:
        """_populate_keys() uses DEFAULT_LEDGER when ledger key is missing."""
        gen = self._make_generator(tmp_path)
        gen.service_builder.keys = [{"private_key": "0xabcdef"}]
        gen.build_dir.mkdir(parents=True)
        gen._populate_keys()

        # DEFAULT_LEDGER is 'ethereum'
        key_file = gen.build_dir / "ethereum_private_key.txt"
        assert key_file.exists()

    def test_populate_private_keys_calls_populate_keys_when_not_multiledger(
        self, tmp_path: Path
    ) -> None:
        """populate_private_keys() calls _populate_keys() when multiledger=False."""
        gen = self._make_generator(tmp_path)
        gen.build_dir.mkdir(parents=True)

        with patch.object(gen, "_populate_keys") as mock_pk, patch.object(
            gen, "_populate_keys_multiledger"
        ) as mock_pkm:
            gen.populate_private_keys()

        mock_pk.assert_called_once()
        mock_pkm.assert_not_called()

    def test_populate_private_keys_calls_multiledger_when_multiledger(
        self, tmp_path: Path
    ) -> None:
        """populate_private_keys() calls _populate_keys_multiledger() when multiledger=True."""
        gen = self._make_generator(tmp_path)
        gen.service_builder.multiledger = True

        with patch.object(gen, "_populate_keys") as mock_pk, patch.object(
            gen, "_populate_keys_multiledger"
        ) as mock_pkm:
            gen.populate_private_keys()

        mock_pkm.assert_called_once()
        mock_pk.assert_not_called()


# ---------------------------------------------------------------------------
# tests for Deployment (new, load, copy_previous_agent_run_logs, start, stop, delete)
# ---------------------------------------------------------------------------


class TestDeploymentNew:
    """Tests for Deployment.new()."""

    def test_new_creates_deployment_json(self, tmp_path: Path) -> None:
        """Deployment.new() creates deployment.json with CREATED status."""
        depl = Deployment.new(path=tmp_path)

        assert (tmp_path / DEPLOYMENT_JSON).exists()
        assert depl.status == DeploymentStatus.CREATED

    def test_new_returns_deployment_instance(self, tmp_path: Path) -> None:
        """Deployment.new() returns a Deployment object."""
        depl = Deployment.new(path=tmp_path)
        assert isinstance(depl, Deployment)

    def test_new_has_empty_nodes(self, tmp_path: Path) -> None:
        """Deployment.new() creates nodes with empty agent and tendermint lists."""
        depl = Deployment.new(path=tmp_path)
        assert depl.nodes.agent == []
        assert depl.nodes.tendermint == []


class TestDeploymentLoad:
    """Tests for Deployment.load()."""

    def test_load_returns_deployment(self, tmp_path: Path) -> None:
        """Deployment.load() loads a previously stored deployment."""
        Deployment.new(path=tmp_path)
        loaded = Deployment.load(path=tmp_path)
        assert isinstance(loaded, Deployment)
        assert loaded.status == DeploymentStatus.CREATED


class TestDeploymentCopyLogs:
    """Tests for Deployment.copy_previous_agent_run_logs()."""

    def test_copies_log_when_source_exists(self, tmp_path: Path) -> None:
        """copy_previous_agent_run_logs() copies log.txt when it exists."""
        depl = Deployment.new(path=tmp_path)
        source_dir = tmp_path / DEPLOYMENT_DIR / "agent"
        source_dir.mkdir(parents=True)
        source_log = source_dir / "log.txt"
        source_log.write_text("log data", encoding="utf-8")

        depl.copy_previous_agent_run_logs()

        dest = tmp_path / "prev_log.txt"
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "log data"

    def test_no_error_when_source_missing(self, tmp_path: Path) -> None:
        """copy_previous_agent_run_logs() does nothing when log.txt doesn't exist."""
        depl = Deployment.new(path=tmp_path)
        # No source log file created
        depl.copy_previous_agent_run_logs()  # should not raise

        assert not (tmp_path / "prev_log.txt").exists()


class TestDeploymentStart:
    """Tests for Deployment.start()."""

    def test_start_raises_not_allowed_when_not_built(self, tmp_path: Path) -> None:
        """start() raises NotAllowed when status != BUILT."""
        depl = _make_deployment(tmp_path, DeploymentStatus.DEPLOYED)

        with pytest.raises(NotAllowed):
            depl.start(password="pw")  # nosec B106

    def test_start_docker_mode_calls_run_deployment(self, tmp_path: Path) -> None:
        """start() calls run_deployment when use_docker=True."""
        depl = _make_deployment(tmp_path, DeploymentStatus.BUILT)

        with patch("operate.services.service.run_deployment") as mock_run:
            depl.start(password="pw", use_docker=True)  # nosec B106

        mock_run.assert_called_once()
        assert depl.status == DeploymentStatus.DEPLOYED

    def test_start_host_mode_calls_run_host_deployment(self, tmp_path: Path) -> None:
        """start() calls run_host_deployment when use_docker=False."""
        depl = _make_deployment(tmp_path, DeploymentStatus.BUILT)

        with patch("operate.services.service.run_host_deployment") as mock_run:
            depl.start(password="mypassword", use_docker=False)  # nosec B106

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("password") == "mypassword" or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == "mypassword"
        )
        assert depl.status == DeploymentStatus.DEPLOYED

    def test_start_exception_resets_status_to_built(self, tmp_path: Path) -> None:
        """start() resets status to BUILT and re-raises when run fails."""
        depl = _make_deployment(tmp_path, DeploymentStatus.BUILT)

        with patch(
            "operate.services.service.run_host_deployment",
            side_effect=RuntimeError("fail"),
        ):
            with pytest.raises(RuntimeError):
                depl.start(password="pw")  # nosec B106

        assert depl.status == DeploymentStatus.BUILT

    def test_start_sets_deploying_then_deployed(self, tmp_path: Path) -> None:
        """start() transitions through DEPLOYING to DEPLOYED on success."""
        depl = _make_deployment(tmp_path, DeploymentStatus.BUILT)
        states: t.List[DeploymentStatus] = []

        original_store = depl.store

        def _capture_store() -> None:
            states.append(depl.status)
            original_store()

        depl.store = _capture_store  # type: ignore[method-assign]

        with patch("operate.services.service.run_host_deployment"):
            depl.start(password="pw")  # nosec B106

        assert DeploymentStatus.DEPLOYING in states
        assert depl.status == DeploymentStatus.DEPLOYED


class TestDeploymentStop:
    """Tests for Deployment.stop()."""

    def test_stop_returns_early_if_not_deployed_and_no_force(
        self, tmp_path: Path
    ) -> None:
        """stop() returns early if status != DEPLOYED and force=False."""
        depl = _make_deployment(tmp_path, DeploymentStatus.BUILT)

        with patch("operate.services.service.stop_deployment") as mock_stop, patch(
            "operate.services.service.stop_host_deployment"
        ) as mock_hstop:
            depl.stop(force=False)

        mock_stop.assert_not_called()
        mock_hstop.assert_not_called()
        # Status unchanged
        assert depl.status == DeploymentStatus.BUILT

    def test_stop_force_proceeds_even_if_not_deployed(self, tmp_path: Path) -> None:
        """stop() proceeds when force=True even if status != DEPLOYED."""
        depl = _make_deployment(tmp_path, DeploymentStatus.BUILT)

        with patch("operate.services.service.stop_host_deployment") as mock_hstop:
            depl.stop(force=True)

        mock_hstop.assert_called_once()
        assert depl.status == DeploymentStatus.BUILT

    def test_stop_docker_mode_calls_stop_deployment(self, tmp_path: Path) -> None:
        """stop() calls stop_deployment when use_docker=True."""
        depl = _make_deployment(tmp_path, DeploymentStatus.DEPLOYED)

        with patch("operate.services.service.stop_deployment") as mock_stop:
            depl.stop(use_docker=True)

        mock_stop.assert_called_once()
        assert depl.status == DeploymentStatus.BUILT

    def test_stop_host_mode_calls_stop_host_deployment(self, tmp_path: Path) -> None:
        """stop() calls stop_host_deployment when use_docker=False."""
        depl = _make_deployment(tmp_path, DeploymentStatus.DEPLOYED)

        with patch("operate.services.service.stop_host_deployment") as mock_hstop:
            depl.stop(use_docker=False, is_aea=True)

        mock_hstop.assert_called_once()
        assert depl.status == DeploymentStatus.BUILT


class TestDeploymentDelete:
    """Tests for Deployment.delete()."""

    def test_delete_removes_build_dir(self, tmp_path: Path) -> None:
        """delete() removes the build directory and sets status to DELETED."""
        depl = _make_deployment(tmp_path, DeploymentStatus.BUILT)
        build_dir = tmp_path / DEPLOYMENT_DIR
        build_dir.mkdir(parents=True)

        depl.delete()

        assert not build_dir.exists()
        assert depl.status == DeploymentStatus.DELETED


# ---------------------------------------------------------------------------
# tests for Deployment.build() routing logic
# ---------------------------------------------------------------------------


class TestDeploymentBuild:
    """Tests for Deployment.build() routing logic."""

    def _make_mock_service(self) -> MagicMock:
        """Return a MagicMock mimicking Service."""
        mock_service = MagicMock()
        mock_service.path = Path("/fake/path")
        mock_service.agent_release = {"is_aea": True}
        mock_service.update_env_variables_values = MagicMock()
        mock_service.consume_env_variables = MagicMock()
        return mock_service

    def test_build_docker_mode_calls_build_docker(self, tmp_path: Path) -> None:
        """build() with use_docker=True calls _build_docker()."""
        depl = Deployment.new(path=tmp_path)
        mock_service = self._make_mock_service()
        mock_km = MagicMock()

        with patch(
            "operate.services.service.Service.load", return_value=mock_service
        ), patch(
            "operate.services.service.create_ssl_certificate",
            return_value=(Path("/ssl/key.pem"), Path("/ssl/cert.pem")),
        ), patch.object(
            depl, "_build_docker"
        ) as mock_bd, patch.object(
            depl, "_build_kubernetes"
        ) as mock_bk:
            depl.build(keys_manager=mock_km, use_docker=True)

        mock_bd.assert_called_once_with(keys_manager=mock_km, force=True, chain=None)
        mock_bk.assert_not_called()

    def test_build_kubernetes_mode_calls_build_kubernetes(self, tmp_path: Path) -> None:
        """build() with use_kubernetes=True calls _build_kubernetes()."""
        depl = Deployment.new(path=tmp_path)
        mock_service = self._make_mock_service()
        mock_km = MagicMock()

        with patch(
            "operate.services.service.Service.load", return_value=mock_service
        ), patch(
            "operate.services.service.create_ssl_certificate",
            return_value=(Path("/ssl/key.pem"), Path("/ssl/cert.pem")),
        ), patch.object(
            depl, "_build_docker"
        ) as mock_bd, patch.object(
            depl, "_build_kubernetes"
        ) as mock_bk:
            depl.build(keys_manager=mock_km, use_kubernetes=True)

        mock_bk.assert_called_once_with(keys_manager=mock_km, force=True)
        mock_bd.assert_not_called()

    def test_build_host_mode_aea_calls_build_host_with_tm_true(
        self, tmp_path: Path
    ) -> None:
        """build() host mode with is_aea=True calls _build_host(with_tm=True)."""
        depl = Deployment.new(path=tmp_path)
        mock_service = self._make_mock_service()
        mock_service.agent_release = {"is_aea": True}
        mock_km = MagicMock()

        with patch(
            "operate.services.service.Service.load", return_value=mock_service
        ), patch(
            "operate.services.service.create_ssl_certificate",
            return_value=(Path("/ssl/key.pem"), Path("/ssl/cert.pem")),
        ), patch.object(
            depl, "_build_host"
        ) as mock_bh:
            depl.build(keys_manager=mock_km, use_docker=False, use_kubernetes=False)

        mock_bh.assert_called_once_with(
            keys_manager=mock_km, force=True, chain=None, with_tm=True
        )

    def test_build_host_mode_non_aea_calls_build_host_with_tm_false(
        self, tmp_path: Path
    ) -> None:
        """build() host mode with is_aea=False calls _build_host(with_tm=False)."""
        depl = Deployment.new(path=tmp_path)
        mock_service = self._make_mock_service()
        mock_service.agent_release = {"is_aea": False}
        mock_km = MagicMock()

        with patch(
            "operate.services.service.Service.load", return_value=mock_service
        ), patch(
            "operate.services.service.create_ssl_certificate",
            return_value=(Path("/ssl/key.pem"), Path("/ssl/cert.pem")),
        ), patch.object(
            depl, "_build_host"
        ) as mock_bh:
            depl.build(keys_manager=mock_km, use_docker=False, use_kubernetes=False)

        mock_bh.assert_called_once_with(
            keys_manager=mock_km, force=True, chain=None, with_tm=False
        )

    def test_build_restores_env_on_success(self, tmp_path: Path) -> None:
        """build() restores os.environ even after successful run."""
        depl = Deployment.new(path=tmp_path)
        mock_service = self._make_mock_service()
        mock_km = MagicMock()

        original_key = "BUILD_TEST_VAR"
        os.environ[original_key] = "original"

        with patch(
            "operate.services.service.Service.load", return_value=mock_service
        ), patch(
            "operate.services.service.create_ssl_certificate",
            return_value=(Path("/ssl/key.pem"), Path("/ssl/cert.pem")),
        ), patch.object(
            depl, "_build_host"
        ):
            # Simulate service.consume_env_variables adding to env
            def _add_env_var() -> None:
                os.environ[original_key] = "changed_by_service"

            mock_service.consume_env_variables = _add_env_var
            depl.build(keys_manager=mock_km)

        assert os.environ.get(original_key) == "original"
        del os.environ[original_key]


# ---------------------------------------------------------------------------
# tests for Service.helper and Service.deployment properties
# ---------------------------------------------------------------------------


class TestServiceHelperProperty:
    """Tests for Service.helper lazy property."""

    def test_helper_created_on_first_access(self, tmp_path: Path) -> None:
        """Service.helper creates ServiceHelper on first access."""
        service = _make_service(tmp_path)
        mock_helper = MagicMock()

        with patch(
            "operate.services.service.ServiceHelper", return_value=mock_helper
        ), patch.object(service, "_ensure_package_exists"):
            result = service.helper

        assert result is mock_helper

    def test_helper_cached_after_first_access(self, tmp_path: Path) -> None:
        """Service.helper returns the same instance on repeated access."""
        service = _make_service(tmp_path)
        mock_helper = MagicMock()

        with patch(
            "operate.services.service.ServiceHelper", return_value=mock_helper
        ) as mock_sh_cls, patch.object(service, "_ensure_package_exists"):
            first = service.helper
            second = service.helper

        assert first is second
        # ServiceHelper constructor called only once
        assert mock_sh_cls.call_count == 1


class TestServiceDeploymentProperty:
    """Tests for Service.deployment property."""

    def test_deployment_creates_new_if_missing(self, tmp_path: Path) -> None:
        """Deployment property calls Deployment.new() when deployment.json missing."""
        service = _make_service(tmp_path)
        # Ensure no deployment.json
        depl_json = service.path / DEPLOYMENT_JSON
        if depl_json.exists():
            depl_json.unlink()

        depl = service.deployment
        assert isinstance(depl, Deployment)
        assert depl_json.exists()

    def test_deployment_loads_existing(self, tmp_path: Path) -> None:
        """Deployment property loads existing deployment.json."""
        service = _make_service(tmp_path)
        # Create a deployment first
        Deployment.new(path=service.path)

        depl = service.deployment
        assert depl.status == DeploymentStatus.CREATED

    def test_deployment_handles_json_decode_error(self, tmp_path: Path) -> None:
        """Deployment property falls back to Deployment.new() on JSONDecodeError."""
        service = _make_service(tmp_path)
        depl_json = service.path / DEPLOYMENT_JSON
        depl_json.write_text("not valid json", encoding="utf-8")

        depl = service.deployment
        assert isinstance(depl, Deployment)


# ---------------------------------------------------------------------------
# tests for Service._ensure_package_exists
# ---------------------------------------------------------------------------


class TestServiceEnsurePackageExists:
    """Tests for Service._ensure_package_exists()."""

    def test_no_download_when_package_exists(self, tmp_path: Path) -> None:
        """_ensure_package_exists() does not call IPFSTool when package dir exists."""
        service = _make_service(tmp_path)
        # Create the package directory with service.yaml
        pkg_dir = service.path / service.package_path
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "service.yaml").touch()

        with patch("operate.services.service.IPFSTool") as mock_ipfs:
            service._ensure_package_exists()

        mock_ipfs.assert_not_called()

    def test_downloads_when_package_missing(self, tmp_path: Path) -> None:
        """_ensure_package_exists() downloads via IPFSTool when package dir missing."""
        service = _make_service(tmp_path)
        # Don't create the package directory

        # Mock IPFSTool; the download path is inside a subdir so target != source
        temp_subdir = service.path / ".tmp_download"
        temp_subdir.mkdir(parents=True)
        downloaded_dir = temp_subdir / "downloaded_pkg"
        downloaded_dir.mkdir(parents=True)

        mock_ipfs_instance = MagicMock()
        mock_ipfs_instance.download.return_value = str(downloaded_dir)

        with patch(
            "operate.services.service.IPFSTool", return_value=mock_ipfs_instance
        ), patch("operate.services.service.shutil.move"), patch.object(
            service, "store"
        ), patch.object(
            service, "service_public_id", return_value="v/t:1.0.0"
        ):
            service._ensure_package_exists()

        mock_ipfs_instance.download.assert_called_once()
        call_kwargs = mock_ipfs_instance.download.call_args.kwargs
        assert call_kwargs["hash_id"] == _HASH

    def test_removes_existing_target_before_move(self, tmp_path: Path) -> None:
        """_ensure_package_exists() removes existing target dir before move."""
        service = _make_service(tmp_path)

        # Create a downloaded dir inside a subdir (simulating temp_dir/pkg)
        temp_subdir = service.path / ".tmp_download2"
        temp_subdir.mkdir(parents=True)
        downloaded_dir = temp_subdir / "already_exists"
        downloaded_dir.mkdir(parents=True)
        # Also create the target path (same name at service.path level)
        target_path = service.path / downloaded_dir.name
        target_path.mkdir(parents=True)

        mock_ipfs_instance = MagicMock()
        mock_ipfs_instance.download.return_value = str(downloaded_dir)

        with patch(
            "operate.services.service.IPFSTool", return_value=mock_ipfs_instance
        ), patch("operate.services.service.shutil.rmtree") as mock_rmtree, patch(
            "operate.services.service.shutil.move"
        ), patch.object(
            service, "store"
        ), patch.object(
            service, "service_public_id", return_value="v/t:1.0.0"
        ):
            service._ensure_package_exists()

        mock_rmtree.assert_any_call(target_path)


# ---------------------------------------------------------------------------
# tests for Service.get_service_public_id (static)
# ---------------------------------------------------------------------------


class TestGetServicePublicId:
    """Tests for Service.get_service_public_id()."""

    def _make_download_dir(self, tmp_path: Path) -> t.Tuple[MagicMock, Path]:
        """Create a fake download directory with service.yaml and return (mock_ipfs, pkg_path)."""
        download_path = tmp_path / "pkg"
        download_path.mkdir()
        # Write a minimal service.yaml so the real file open works
        service_yaml = "author: valory\nname: trader\nversion: 0.1.0\n"
        (download_path / "service.yaml").write_text(service_yaml, encoding="utf-8")
        mock_ipfs = MagicMock()
        mock_ipfs.download.return_value = str(download_path)
        return mock_ipfs, download_path

    def test_returns_public_id_with_version(self, tmp_path: Path) -> None:
        """get_service_public_id() returns 'author/name:version' by default."""
        mock_ipfs, _ = self._make_download_dir(tmp_path)

        with patch("operate.services.service.IPFSTool", return_value=mock_ipfs):
            result = Service.get_service_public_id(
                hash="fakehash", temp_dir=tmp_path, include_version=True
            )

        assert result == "valory/trader:0.1.0"

    def test_returns_public_id_without_version(self, tmp_path: Path) -> None:
        """get_service_public_id() returns 'author/name' when include_version=False."""
        mock_ipfs, _ = self._make_download_dir(tmp_path)

        with patch("operate.services.service.IPFSTool", return_value=mock_ipfs):
            result = Service.get_service_public_id(
                hash="fakehash", temp_dir=tmp_path, include_version=False
            )

        assert result == "valory/trader"
        assert ":" not in result


# ---------------------------------------------------------------------------
# tests for Service.remove_latest_healthcheck
# ---------------------------------------------------------------------------


class TestRemoveLatestHealthcheck:
    """Tests for Service.remove_latest_healthcheck()."""

    def test_removes_healthcheck_file_when_exists(self, tmp_path: Path) -> None:
        """remove_latest_healthcheck() deletes HEALTHCHECK_JSON when it exists."""
        service = _make_service(tmp_path)
        hc_path = service.path / HEALTHCHECK_JSON
        hc_path.write_text("{}", encoding="utf-8")

        service.remove_latest_healthcheck()

        assert not hc_path.exists()

    def test_no_error_when_healthcheck_missing(self, tmp_path: Path) -> None:
        """remove_latest_healthcheck() does nothing when file doesn't exist."""
        service = _make_service(tmp_path)
        # File doesn't exist
        service.remove_latest_healthcheck()  # should not raise

    def test_exception_during_unlink_prints_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """remove_latest_healthcheck() prints an exception message on unlink failure."""
        service = _make_service(tmp_path)
        hc_path = service.path / HEALTHCHECK_JSON
        hc_path.write_text("{}", encoding="utf-8")

        with patch.object(
            hc_path.__class__, "unlink", side_effect=OSError("cannot delete")
        ):
            service.remove_latest_healthcheck()

        captured = capsys.readouterr()
        assert "Exception" in captured.out or "cannot delete" in captured.out


# ---------------------------------------------------------------------------
# tests for Service.update
# ---------------------------------------------------------------------------


class TestServiceUpdate:
    """Tests for Service.update()."""

    _CURRENT_PUBLIC_ID = "valory/test_service:1.0.0"

    def _patch_update_deps(
        self, service: Service, public_id: str = _CURRENT_PUBLIC_ID
    ) -> t.Any:
        """Return a context manager that patches all update() dependencies."""
        mock_helper = MagicMock()
        mock_helper.ledger_configs.return_value = {
            "gnosis": LedgerConfig(rpc="https://rpc.gnosis.io", chain=Chain.GNOSIS),
            "base": LedgerConfig(rpc="https://rpc.base.io", chain=Chain.BASE),
        }
        mock_ipfs = MagicMock()
        mock_ipfs.download.return_value = str(service.path / "new_pkg")

        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(
            patch(
                "operate.services.service.Service.get_service_public_id",
                return_value=public_id,
            )
        )
        stack.enter_context(
            patch.object(service, "service_public_id", return_value=public_id)
        )
        stack.enter_context(patch.object(service, "_ensure_package_exists"))
        stack.enter_context(patch.object(service, "store"))
        stack.enter_context(
            patch("operate.services.service.ServiceHelper", return_value=mock_helper)
        )
        stack.enter_context(
            patch("operate.services.service.IPFSTool", return_value=mock_ipfs)
        )
        stack.enter_context(patch("operate.services.service.shutil.rmtree"))
        stack.enter_context(patch("operate.services.service.shutil.move"))
        return stack

    def _base_template(
        self, service: Service, **overrides: t.Any
    ) -> t.Dict[str, t.Any]:
        """Return a minimal update template."""
        tpl: t.Dict[str, t.Any] = {
            "hash": _HASH,
            "name": "Test",
            "description": "desc",
            "home_chain": "gnosis",
            "env_variables": {},
            "configurations": {},
            "agent_release": service.agent_release,
        }
        tpl.update(overrides)
        return tpl

    def test_update_raises_on_different_public_id(self, tmp_path: Path) -> None:
        """update() raises ValueError when public IDs differ and allow=False."""
        service = _make_service(tmp_path)

        with patch(
            "operate.services.service.Service.get_service_public_id",
            return_value="different/service:1.0.0",
        ), patch.object(
            service, "service_public_id", return_value=self._CURRENT_PUBLIC_ID
        ), patch.object(
            service, "_ensure_package_exists"
        ), patch(
            "operate.services.service.IPFSTool"
        ), patch(
            "operate.services.service.ServiceHelper"
        ), patch.object(
            service, "store"
        ):
            with pytest.raises(ValueError, match="different public id"):
                service.update(
                    self._base_template(service, hash="newHash123"),
                    allow_different_service_public_id=False,
                )

    def test_update_allows_different_public_id_when_flag_set(
        self, tmp_path: Path
    ) -> None:
        """update() succeeds when allow_different_service_public_id=True."""
        service = _make_service(tmp_path)

        with patch(
            "operate.services.service.Service.get_service_public_id",
            return_value="different/service:1.0.0",
        ), patch.object(
            service, "service_public_id", return_value=self._CURRENT_PUBLIC_ID
        ), patch.object(
            service, "_ensure_package_exists"
        ), patch.object(
            service, "store"
        ), patch(
            "operate.services.service.IPFSTool"
        ), patch(
            "operate.services.service.ServiceHelper"
        ), patch(
            "operate.services.service.shutil.rmtree"
        ), patch(
            "operate.services.service.shutil.move"
        ):
            service.update(
                self._base_template(service, hash="newHash123"),
                allow_different_service_public_id=True,
            )

    def test_update_adds_new_hash_to_history(self, tmp_path: Path) -> None:
        """update() appends new hash to hash_history when hash changes."""
        service = _make_service(tmp_path)
        original_history_len = len(service.hash_history)

        with self._patch_update_deps(service):
            service.update(self._base_template(service, hash="brandNewHash456"))

        assert len(service.hash_history) == original_history_len + 1
        assert "brandNewHash456" in service.hash_history.values()

    def test_update_does_not_duplicate_hash_in_history(self, tmp_path: Path) -> None:
        """update() does not append to hash_history when hash is unchanged."""
        service = _make_service(tmp_path)
        original_history_len = len(service.hash_history)

        with self._patch_update_deps(service):
            service.update(self._base_template(service, hash=_HASH))

        assert len(service.hash_history) == original_history_len

    def test_update_partial_env_variables_uses_setdefault(self, tmp_path: Path) -> None:
        """update() with partial_update=True merges env_variables via setdefault."""
        service = _make_service(tmp_path)
        service.env_variables = {
            "EXISTING": {
                "value": "old",
                "provision_type": "fixed",
                "name": "X",
                "description": "X",
            }
        }

        template = self._base_template(
            service,
            env_variables={
                "NEW_VAR": {
                    "value": "new",
                    "provision_type": "fixed",
                    "name": "Y",
                    "description": "Y",
                }
            },
        )

        with self._patch_update_deps(service):
            service.update(template, partial_update=True)

        assert "EXISTING" in service.env_variables
        assert "NEW_VAR" in service.env_variables

    def test_update_full_env_variables_replaces_completely(
        self, tmp_path: Path
    ) -> None:
        """update() with partial_update=False replaces env_variables entirely."""
        service = _make_service(tmp_path)
        service.env_variables = {
            "EXISTING": {
                "value": "old",
                "provision_type": "fixed",
                "name": "X",
                "description": "X",
            }
        }

        template = self._base_template(
            service,
            env_variables={
                "ONLY_NEW": {
                    "value": "new",
                    "provision_type": "fixed",
                    "name": "Y",
                    "description": "Y",
                }
            },
        )

        with self._patch_update_deps(service):
            service.update(template, partial_update=False)

        assert "EXISTING" not in service.env_variables
        assert "ONLY_NEW" in service.env_variables

    def test_update_existing_chain_updates_user_params_only(
        self, tmp_path: Path
    ) -> None:
        """update() updates only user_params for existing chains (preserves on-chain data)."""
        service = _make_service(tmp_path)
        service.chain_configs["gnosis"].chain_data.token = 999

        template = self._base_template(
            service,
            configurations={
                "gnosis": {
                    "rpc": "https://new-rpc.io",
                    "staking_program_id": "new_staking",
                    "nft": "bafybeinewnft",
                    "agent_id": 25,
                    "cost_of_bond": 1000,
                    "fund_requirements": {ZERO_ADDRESS: {"agent": 100, "safe": 500}},
                }
            },
        )

        with self._patch_update_deps(service):
            service.update(template)

        assert service.chain_configs["gnosis"].chain_data.token == 999

    def test_update_new_chain_adds_full_config(self, tmp_path: Path) -> None:
        """update() adds full chain config for chains not in existing chain_configs."""
        service = _make_service(tmp_path)

        template = self._base_template(
            service,
            configurations={
                "base": {
                    "rpc": "https://rpc.base.io",
                    "staking_program_id": "no_staking",
                    "nft": "bafybeinewnft",
                    "agent_id": 25,
                    "cost_of_bond": 1000,
                    "fund_requirements": {ZERO_ADDRESS: {"agent": 100, "safe": 500}},
                }
            },
        )

        with self._patch_update_deps(service):
            service.update(template)

        assert "base" in service.chain_configs

    def test_update_removes_old_package_when_it_exists(self, tmp_path: Path) -> None:
        """update() calls shutil.rmtree on existing package dir before downloading."""
        service = _make_service(tmp_path)
        # Create the package directory so exists() returns True
        old_pkg_dir = service.path / service.package_path
        old_pkg_dir.mkdir(parents=True)

        with self._patch_update_deps(service), patch(
            "operate.services.service.shutil.rmtree"
        ) as mock_rmtree:
            service.update(self._base_template(service))

        mock_rmtree.assert_any_call(old_pkg_dir)

    def test_update_partial_existing_chain_merges_user_params(
        self, tmp_path: Path
    ) -> None:
        """update() with partial_update=True merges existing chain's user_params."""
        service = _make_service(tmp_path)
        original_staking = service.chain_configs[
            "gnosis"
        ].chain_data.user_params.staking_program_id

        template = self._base_template(
            service,
            configurations={
                "gnosis": {
                    "rpc": "https://new-rpc.io",
                    "staking_program_id": "updated_staking_partial",
                    "nft": "bafybeinewnft",
                    "agent_id": 25,
                    "cost_of_bond": 1000,
                    "fund_requirements": {ZERO_ADDRESS: {"agent": 100, "safe": 500}},
                }
            },
        )

        with self._patch_update_deps(service):
            service.update(template, partial_update=True)

        # staking_program_id should be updated via partial merge
        new_staking = service.chain_configs[
            "gnosis"
        ].chain_data.user_params.staking_program_id
        assert new_staking != original_staking
        assert new_staking == "updated_staking_partial"


# ---------------------------------------------------------------------------
# tests for Service.update_user_params_from_template
# ---------------------------------------------------------------------------


class TestUpdateUserParamsFromTemplate:
    """Tests for Service.update_user_params_from_template()."""

    def test_updates_rpc_and_user_params(self, tmp_path: Path) -> None:
        """update_user_params_from_template() updates rpc and user_params for each chain."""
        service = _make_service(tmp_path)
        original_rpc = service.chain_configs["gnosis"].ledger_config.rpc

        template: t.Dict[str, t.Any] = {
            "configurations": {
                "gnosis": {
                    "rpc": "https://new-rpc.gnosis.io",
                    "staking_program_id": "updated_staking",
                    "nft": "bafybeinewnft",
                    "agent_id": 99,
                    "cost_of_bond": 9999,
                    "fund_requirements": {ZERO_ADDRESS: {"agent": 1, "safe": 2}},
                }
            }
        }

        service.update_user_params_from_template(template)

        assert (
            service.chain_configs["gnosis"].ledger_config.rpc
            == "https://new-rpc.gnosis.io"
        )
        assert service.chain_configs["gnosis"].ledger_config.rpc != original_rpc
        assert (
            service.chain_configs["gnosis"].chain_data.user_params.staking_program_id
            == "updated_staking"
        )


# ---------------------------------------------------------------------------
# tests for Service.consume_env_variables
# ---------------------------------------------------------------------------


class TestConsumeEnvVariables:
    """Tests for Service.consume_env_variables()."""

    def test_sets_env_variables_from_service(self, tmp_path: Path) -> None:
        """consume_env_variables() sets each env_variable into os.environ."""
        service = _make_service(tmp_path)
        service.env_variables = {
            "MY_TEST_VAR_UNIT2": {
                "value": "hello_world",
                "provision_type": "fixed",
                "name": "MY_TEST_VAR_UNIT2",
                "description": "test",
            }
        }

        service.consume_env_variables()

        try:
            assert os.environ["MY_TEST_VAR_UNIT2"] == "hello_world"
        finally:
            del os.environ["MY_TEST_VAR_UNIT2"]

    def test_converts_non_string_value_to_string(self, tmp_path: Path) -> None:
        """consume_env_variables() converts non-string values to strings."""
        service = _make_service(tmp_path)
        service.env_variables = {
            "INT_VAR_UNIT2": {
                "value": 42,
                "provision_type": "fixed",
                "name": "INT_VAR_UNIT2",
                "description": "test",
            }
        }

        service.consume_env_variables()

        try:
            assert os.environ["INT_VAR_UNIT2"] == "42"
        finally:
            del os.environ["INT_VAR_UNIT2"]

    def test_missing_value_key_sets_empty_string(self, tmp_path: Path) -> None:
        """consume_env_variables() sets empty string when 'value' key is absent."""
        service = _make_service(tmp_path)
        service.env_variables = {
            "EMPTY_VAR_UNIT2": {
                "provision_type": "computed",
                "name": "EMPTY_VAR_UNIT2",
                "description": "test",
            }
        }

        service.consume_env_variables()

        try:
            assert os.environ["EMPTY_VAR_UNIT2"] == ""
        finally:
            del os.environ["EMPTY_VAR_UNIT2"]


# ---------------------------------------------------------------------------
# tests for Service.update_env_variables_values
# ---------------------------------------------------------------------------


class TestUpdateEnvVariablesValues:
    """Tests for Service.update_env_variables_values()."""

    def _make_service_with_computed_var(self, tmp_path: Path) -> Service:
        """Return a Service with a COMPUTED env variable."""
        service = _make_service(tmp_path)
        service.env_variables = {
            "COMPUTED_VAR": {
                "value": "oldval",
                "provision_type": ServiceEnvProvisionType.COMPUTED,
                "name": "COMPUTED_VAR",
                "description": "test",
            }
        }
        return service

    def test_updates_computed_var_with_different_value(self, tmp_path: Path) -> None:
        """update_env_variables_values() updates a COMPUTED variable with new value."""
        service = self._make_service_with_computed_var(tmp_path)

        service.update_env_variables_values({"COMPUTED_VAR": "newval"})

        assert service.env_variables["COMPUTED_VAR"]["value"] == "newval"

    def test_does_not_update_when_value_unchanged(self, tmp_path: Path) -> None:
        """update_env_variables_values() does not store when value is unchanged."""
        service = self._make_service_with_computed_var(tmp_path)

        with patch.object(service, "store") as mock_store:
            service.update_env_variables_values({"COMPUTED_VAR": "oldval"})

        mock_store.assert_not_called()

    def test_does_not_update_fixed_provision_type(self, tmp_path: Path) -> None:
        """update_env_variables_values() ignores FIXED variables."""
        service = _make_service(tmp_path)
        service.env_variables = {
            "FIXED_VAR": {
                "value": "fixedval",
                "provision_type": ServiceEnvProvisionType.FIXED,
                "name": "FIXED_VAR",
                "description": "test",
            }
        }

        with patch.object(service, "store") as mock_store:
            service.update_env_variables_values({"FIXED_VAR": "newval"})

        mock_store.assert_not_called()
        assert service.env_variables["FIXED_VAR"]["value"] == "fixedval"

    def test_raises_when_undefined_var_and_except_flag(self, tmp_path: Path) -> None:
        """update_env_variables_values() raises ValueError for undefined var when except_if_undefined=True."""
        service = _make_service(tmp_path)

        with pytest.raises(ValueError, match="not present on service configuration"):
            service.update_env_variables_values(
                {"NONEXISTENT_VAR": "value"}, except_if_undefined=True
            )

    def test_silent_when_undefined_var_and_no_except_flag(self, tmp_path: Path) -> None:
        """update_env_variables_values() is silent for undefined var when except_if_undefined=False."""
        service = _make_service(tmp_path)

        service.update_env_variables_values(
            {"NONEXISTENT_VAR": "value"}, except_if_undefined=False
        )
        # No exception raised


# ---------------------------------------------------------------------------
# tests for Service.get_balances (fallback and wrapped-token branches)
# ---------------------------------------------------------------------------


class TestServiceGetBalances:
    """Tests for Service.get_balances() wrapped-token and fallback branches."""

    def test_fallback_chain_uses_default_ledger_api(self, tmp_path: Path) -> None:
        """get_balances() uses get_default_ledger_api for chains not in chain_configs."""
        service = _make_service(tmp_path)

        # Override get_initial_funding_amounts to return a chain not in chain_configs
        service.chain_configs = {}  # Clear chain_configs
        mock_amounts = ChainAmounts(
            {"gnosis": {_AGENT_ADDR: {ZERO_ADDRESS: BigInt(0)}}}
        )

        mock_ledger_api = MagicMock()
        mock_ledger_api.api.eth.get_balance.return_value = 0

        with patch.object(
            service, "get_initial_funding_amounts", return_value=mock_amounts
        ), patch(
            "operate.services.service.get_default_ledger_api",
            return_value=mock_ledger_api,
        ) as mock_default_api, patch(
            "operate.services.service.get_asset_balance", return_value=0
        ), patch(
            "operate.services.service.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: "0x" + "e" * 40},
        ):
            service.get_balances(unify_wrapped_native_tokens=False)

        mock_default_api.assert_called_once()

    def test_wrapped_token_zero_address_initialized_and_deleted(
        self, tmp_path: Path
    ) -> None:
        """get_balances() initializes ZERO_ADDRESS to 0 and deletes wrapped asset."""
        wrapped_asset = "0x" + "e" * 40
        service = _make_service(tmp_path)

        mock_amounts = ChainAmounts(
            {"gnosis": {_AGENT_ADDR: {wrapped_asset: BigInt(500)}}}
        )

        mock_ledger_api = MagicMock()

        with patch.object(
            service, "get_initial_funding_amounts", return_value=mock_amounts
        ), patch(
            "operate.services.service.make_chain_ledger_api",
            return_value=mock_ledger_api,
        ), patch(
            "operate.services.service.get_asset_balance", return_value=500
        ), patch(
            "operate.services.service.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: wrapped_asset},
        ):
            result = service.get_balances(unify_wrapped_native_tokens=True)

        # wrapped_asset should be removed, ZERO_ADDRESS should have 500 (0 + 500)
        gnosis_assets = result["gnosis"][_AGENT_ADDR]
        assert wrapped_asset not in gnosis_assets
        assert ZERO_ADDRESS in gnosis_assets
        assert gnosis_assets[ZERO_ADDRESS] == 500

    def test_wrapped_token_combined_when_both_present(self, tmp_path: Path) -> None:
        """get_balances() adds wrapped asset to ZERO_ADDRESS when both present."""
        wrapped_asset = "0x" + "e" * 40
        service = _make_service(tmp_path)

        # Both ZERO_ADDRESS and wrapped_asset in initial amounts
        mock_amounts = ChainAmounts(
            {
                "gnosis": {
                    _AGENT_ADDR: {ZERO_ADDRESS: BigInt(100), wrapped_asset: BigInt(200)}
                }
            }
        )

        mock_ledger_api = MagicMock()

        with patch.object(
            service, "get_initial_funding_amounts", return_value=mock_amounts
        ), patch(
            "operate.services.service.make_chain_ledger_api",
            return_value=mock_ledger_api,
        ), patch(
            "operate.services.service.get_asset_balance",
            side_effect=[100, 200],  # First call returns native, second wrapped
        ), patch(
            "operate.services.service.WRAPPED_NATIVE_ASSET",
            {Chain.GNOSIS: wrapped_asset},
        ):
            result = service.get_balances(unify_wrapped_native_tokens=True)

        gnosis_assets = result["gnosis"][_AGENT_ADDR]
        assert wrapped_asset not in gnosis_assets
        # 100 (ZERO_ADDRESS) + 200 (wrapped) = 300
        assert gnosis_assets[ZERO_ADDRESS] == 300


# ---------------------------------------------------------------------------
# tests for Service.get_funding_requests
# ---------------------------------------------------------------------------


class TestServiceGetFundingRequests:
    """Tests for Service.get_funding_requests()."""

    def test_returns_empty_when_not_deployed(self, tmp_path: Path) -> None:
        """get_funding_requests() returns empty ChainAmounts when not DEPLOYED."""
        service = _make_service(tmp_path)

        with patch.object(
            type(service),
            "deployment",
            new_callable=lambda: property(
                lambda self: MagicMock(status=DeploymentStatus.BUILT)
            ),
        ):
            result = service.get_funding_requests()

        assert result == {}

    def test_http_exception_returns_empty(self, tmp_path: Path) -> None:
        """get_funding_requests() returns empty ChainAmounts on HTTP exception."""
        service = _make_service(tmp_path)

        mock_deployment = MagicMock()
        mock_deployment.status = DeploymentStatus.DEPLOYED

        with patch.object(
            type(service),
            "deployment",
            new_callable=lambda: property(lambda self: mock_deployment),
        ), patch(
            "operate.services.service.requests.get",
            side_effect=ConnectionError("timeout"),
        ):
            result = service.get_funding_requests()

        assert result == {}

    def test_http_success_populates_funding_requests(self, tmp_path: Path) -> None:
        """get_funding_requests() parses HTTP response into ChainAmounts."""
        service = _make_service(tmp_path)
        service.chain_configs["gnosis"].chain_data.multisig = _MULTISIG_ADDR

        mock_deployment = MagicMock()
        mock_deployment.status = DeploymentStatus.DEPLOYED

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "gnosis": {_AGENT_ADDR: {ZERO_ADDRESS: {"deficit": "5000000000000000000"}}}
        }

        with patch.object(
            type(service),
            "deployment",
            new_callable=lambda: property(lambda self: mock_deployment),
        ), patch("operate.services.service.requests.get", return_value=mock_resp):
            result = service.get_funding_requests()

        assert "gnosis" in result
        assert _AGENT_ADDR in result["gnosis"]
        assert ZERO_ADDRESS in result["gnosis"][_AGENT_ADDR]

    def test_unknown_chain_raises_value_error(self, tmp_path: Path) -> None:
        """get_funding_requests() raises ValueError for unknown chain in response."""
        service = _make_service(tmp_path)

        mock_deployment = MagicMock()
        mock_deployment.status = DeploymentStatus.DEPLOYED

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ethereum": {_AGENT_ADDR: {ZERO_ADDRESS: {"deficit": "1000"}}}
        }

        with patch.object(
            type(service),
            "deployment",
            new_callable=lambda: property(lambda self: mock_deployment),
        ), patch("operate.services.service.requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="unknown chain"):
                service.get_funding_requests()

    def test_unknown_address_raises_value_error(self, tmp_path: Path) -> None:
        """get_funding_requests() raises ValueError for unknown address in response."""
        service = _make_service(tmp_path)
        unknown_addr = "0x" + "f" * 40

        mock_deployment = MagicMock()
        mock_deployment.status = DeploymentStatus.DEPLOYED

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "gnosis": {unknown_addr: {ZERO_ADDRESS: {"deficit": "1000"}}}
        }

        with patch.object(
            type(service),
            "deployment",
            new_callable=lambda: property(lambda self: mock_deployment),
        ), patch("operate.services.service.requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="unknown address"):
                service.get_funding_requests()

    def test_invalid_deficit_logs_warning_and_sets_zero(self, tmp_path: Path) -> None:
        """get_funding_requests() sets deficit to 0 and logs warning on invalid value."""
        service = _make_service(tmp_path)
        service.chain_configs["gnosis"].chain_data.multisig = _MULTISIG_ADDR

        mock_deployment = MagicMock()
        mock_deployment.status = DeploymentStatus.DEPLOYED

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "gnosis": {_AGENT_ADDR: {ZERO_ADDRESS: {"deficit": "NOT_A_NUMBER"}}}
        }

        with patch.object(
            type(service),
            "deployment",
            new_callable=lambda: property(lambda self: mock_deployment),
        ), patch("operate.services.service.requests.get", return_value=mock_resp):
            result = service.get_funding_requests()

        # Should not raise; deficit set to 0
        assert result["gnosis"][_AGENT_ADDR][ZERO_ADDRESS] == 0
