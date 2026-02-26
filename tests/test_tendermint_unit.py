# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""Tests for TendermintNode methods and Flask routes in utils/tendermint.py."""

import json
import subprocess  # nosec B404
from pathlib import Path
from typing import Generator, Tuple
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from operate.services.utils.tendermint import (
    PeriodDumper,
    StoppableThread,
    TendermintNode,
    TendermintParams,
    create_app,
)


class TestTendermintNodeMethods:
    """Tests for TendermintNode methods not covered by test_tendermint.py."""

    def _make_node(self) -> TendermintNode:
        """Return a minimal TendermintNode instance."""
        params = TendermintParams(proxy_app="tcp://localhost:26658")
        return TendermintNode(params=params)

    def test_build_init_command_no_home(self) -> None:
        """_build_init_command returns ['tendermint', 'init'] when home is None."""
        node = self._make_node()
        cmd = node._build_init_command()  # pylint: disable=protected-access
        assert cmd == ["tendermint", "init"]

    def test_init_calls_subprocess_call(self) -> None:
        """init() calls subprocess.call with the init command."""
        node = self._make_node()
        with patch("operate.services.utils.tendermint.subprocess.call") as mock_call:
            node.init()
        mock_call.assert_called_once_with(["tendermint", "init"])

    def test_monitor_none_monitoring_raises(self) -> None:
        """_monitor_tendermint_process raises ValueError when _monitoring is None."""
        node = self._make_node()
        node._monitoring = None  # pylint: disable=protected-access
        with pytest.raises(ValueError, match="Monitoring is not running"):
            node._monitor_tendermint_process()  # pylint: disable=protected-access

    def test_monitor_already_stopped(self) -> None:
        """_monitor_tendermint_process exits immediately when monitoring already stopped."""
        node = self._make_node()
        mock_monitoring = MagicMock()
        mock_monitoring.stopped.return_value = True
        node._monitoring = mock_monitoring  # pylint: disable=protected-access
        # Should exit the while loop immediately without reading
        node._monitor_tendermint_process()  # pylint: disable=protected-access

    def test_monitor_process_none_exits_cleanly(self) -> None:
        """_monitor_tendermint_process handles _process=None without error."""
        node = self._make_node()
        mock_monitoring = MagicMock()
        mock_monitoring.stopped.side_effect = [False, True]
        node._monitoring = mock_monitoring  # pylint: disable=protected-access
        node._process = None  # pylint: disable=protected-access
        node._monitor_tendermint_process()  # pylint: disable=protected-access

    def test_monitor_trigger_rpc_server_stopped_restarts(self) -> None:
        """When 'RPC HTTP server stopped' found in output, stop/start are called."""
        node = self._make_node()
        mock_monitoring = MagicMock()
        # stopped() calls: [while, inner-for trigger#1, inner-for trigger#2, while]
        mock_monitoring.stopped.side_effect = [False, False, True, True]
        node._monitoring = mock_monitoring  # pylint: disable=protected-access

        mock_process = MagicMock()
        mock_process.stdout.readline.return_value = "RPC HTTP server stopped\n"
        node._process = mock_process  # pylint: disable=protected-access

        with patch.object(node, "_stop_tm_process") as mock_stop:
            with patch.object(node, "_start_tm_process") as mock_start:
                node._monitor_tendermint_process()  # pylint: disable=protected-access

        mock_stop.assert_called_once()
        mock_start.assert_called_once()

    def test_monitor_trigger_abci_error_restarts(self) -> None:
        """When 'Stopping abci.socketClient' found in output, stop/start are called."""
        node = self._make_node()
        mock_monitoring = MagicMock()
        # stopped(): [while, trigger#1 (no match), trigger#2 (match), while]
        mock_monitoring.stopped.side_effect = [False, False, False, True]
        node._monitoring = mock_monitoring  # pylint: disable=protected-access

        mock_process = MagicMock()
        mock_process.stdout.readline.return_value = (
            "Stopping abci.socketClient for error: read message: EOF\n"
        )
        node._process = mock_process  # pylint: disable=protected-access

        with patch.object(node, "_stop_tm_process") as mock_stop:
            with patch.object(node, "_start_tm_process") as mock_start:
                node._monitor_tendermint_process()  # pylint: disable=protected-access

        mock_stop.assert_called()
        mock_start.assert_called()

    def test_monitor_exception_in_reading_is_caught(self) -> None:
        """Exception during readline is caught and logged, does not propagate."""
        node = self._make_node()
        mock_monitoring = MagicMock()
        mock_monitoring.stopped.side_effect = [False, True]
        node._monitoring = mock_monitoring  # pylint: disable=protected-access

        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = Exception("read error")
        node._process = mock_process  # pylint: disable=protected-access

        # Should not raise - exception is caught internally
        node._monitor_tendermint_process()  # pylint: disable=protected-access

    def test_start_tm_process_spawns_popen(self) -> None:
        """_start_tm_process creates a subprocess and stores it in _process."""
        node = self._make_node()
        with patch("operate.services.utils.tendermint.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            node._start_tm_process()  # pylint: disable=protected-access
        assert node._process is not None  # pylint: disable=protected-access
        mock_popen.assert_called_once()

    def test_start_tm_process_debug_flag(self) -> None:
        """_start_tm_process with debug=True includes --log_level=debug."""
        node = self._make_node()
        with patch("operate.services.utils.tendermint.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            node._start_tm_process(debug=True)  # pylint: disable=protected-access
        call_args = mock_popen.call_args[0][0]
        assert "--log_level=debug" in call_args

    def test_start_monitoring_thread_creates_and_starts(self) -> None:
        """_start_monitoring_thread creates a StoppableThread and starts it."""
        node = self._make_node()
        with patch.object(StoppableThread, "start") as mock_start:
            node._start_monitoring_thread()  # pylint: disable=protected-access
        mock_start.assert_called_once()
        assert node._monitoring is not None  # pylint: disable=protected-access

    def test_start_calls_both_helpers(self) -> None:
        """start() calls _start_tm_process and _start_monitoring_thread."""
        node = self._make_node()
        with patch.object(node, "_start_tm_process") as mock_tm:
            with patch.object(node, "_start_monitoring_thread") as mock_mon:
                node.start()
        mock_tm.assert_called_once_with(False)
        mock_mon.assert_called_once()

    def test_start_debug_flag_forwarded(self) -> None:
        """start(debug=True) forwards debug flag to _start_tm_process."""
        node = self._make_node()
        with patch.object(node, "_start_tm_process") as mock_tm:
            with patch.object(node, "_start_monitoring_thread"):
                node.start(debug=True)
        mock_tm.assert_called_once_with(True)

    def test_stop_tm_process_process_none_returns_early(self) -> None:
        """_stop_tm_process returns early when _process is None."""
        node = self._make_node()
        node._process = None  # pylint: disable=protected-access
        node._stop_tm_process()  # pylint: disable=protected-access
        assert node._process is None  # pylint: disable=protected-access

    def test_stop_tm_process_stopping_returns_early(self) -> None:
        """_stop_tm_process returns early when _stopping is True."""
        node = self._make_node()
        node._process = MagicMock()  # pylint: disable=protected-access
        node._stopping = True  # pylint: disable=protected-access
        node._stop_tm_process()  # pylint: disable=protected-access
        # _stopping is not reset and _process is not cleared
        assert node._stopping is True  # pylint: disable=protected-access
        assert node._process is not None  # pylint: disable=protected-access

    def test_stop_tm_process_unix_path(self) -> None:
        """_stop_tm_process calls _unix_stop_tm on Linux and clears _process."""
        node = self._make_node()
        node._process = MagicMock()  # pylint: disable=protected-access
        with patch(
            "operate.services.utils.tendermint.platform.system", return_value="Linux"
        ):
            with patch.object(node, "_unix_stop_tm") as mock_unix:
                node._stop_tm_process()  # pylint: disable=protected-access
        mock_unix.assert_called_once()
        assert node._process is None  # pylint: disable=protected-access
        assert node._stopping is False  # pylint: disable=protected-access

    def test_stop_tm_process_windows_path(self) -> None:
        """_stop_tm_process calls _win_stop_tm on Windows."""
        node = self._make_node()
        node._process = MagicMock()  # pylint: disable=protected-access
        with patch(
            "operate.services.utils.tendermint.platform.system",
            return_value="Windows",
        ):
            with patch.object(node, "_win_stop_tm") as mock_win:
                node._stop_tm_process()  # pylint: disable=protected-access
        mock_win.assert_called_once()
        assert node._process is None  # pylint: disable=protected-access

    def test_unix_stop_tm_graceful(self) -> None:
        """_unix_stop_tm: when process stops in time, terminate() is not called."""
        node = self._make_node()
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # process already exited
        node._process = mock_process  # pylint: disable=protected-access

        node._unix_stop_tm()  # pylint: disable=protected-access

        mock_process.send_signal.assert_called_once()
        mock_process.wait.assert_called_once_with(timeout=5)
        mock_process.terminate.assert_not_called()

    def test_unix_stop_tm_timeout_process_still_running(self) -> None:
        """_unix_stop_tm: when TimeoutExpired and process still running, terminate() called."""
        node = self._make_node()
        mock_process = MagicMock()
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        mock_process.poll.return_value = None  # still running after timeout
        node._process = mock_process  # pylint: disable=protected-access

        node._unix_stop_tm()  # pylint: disable=protected-access

        mock_process.terminate.assert_called_once()

    def test_unix_stop_tm_timeout_process_exits_after_timeout(self) -> None:
        """_unix_stop_tm: when TimeoutExpired but process exits (poll non-None), no terminate."""
        node = self._make_node()
        mock_process = MagicMock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_process.poll.return_value = 1  # exited after timeout
        node._process = mock_process  # pylint: disable=protected-access

        node._unix_stop_tm()  # pylint: disable=protected-access

        mock_process.terminate.assert_not_called()

    def test_stop_monitoring_thread_when_none(self) -> None:
        """_stop_monitoring_thread does nothing when _monitoring is None."""
        node = self._make_node()
        node._monitoring = None  # pylint: disable=protected-access
        # Should not raise
        node._stop_monitoring_thread()  # pylint: disable=protected-access

    def test_stop_monitoring_thread_stops_and_joins(self) -> None:
        """_stop_monitoring_thread calls stop() and join() on the monitoring thread."""
        node = self._make_node()
        mock_monitoring = MagicMock()
        node._monitoring = mock_monitoring  # pylint: disable=protected-access

        node._stop_monitoring_thread()  # pylint: disable=protected-access

        mock_monitoring.stop.assert_called_once()
        mock_monitoring.join.assert_called_once_with(timeout=20)

    def test_stop_calls_both_helpers(self) -> None:
        """stop() calls _stop_monitoring_thread and _stop_tm_process."""
        node = self._make_node()
        with patch.object(node, "_stop_monitoring_thread") as mock_mon:
            with patch.object(node, "_stop_tm_process") as mock_tm:
                node.stop()
        mock_mon.assert_called_once()
        mock_tm.assert_called_once()


class TestCreateAppFlaskRoutes:
    """Tests for Flask routes created inside create_app()."""

    @pytest.fixture
    def flask_app_and_node(
        self, tmp_path: Path
    ) -> Generator[Tuple[Flask, TendermintNode], None, None]:
        """Create Flask app with all subprocess calls mocked out."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        env = {
            "PROXY_APP": "tcp://localhost:26658",
            "P2P_LADDR": "tcp://0.0.0.0:26656",
            "RPC_LADDR": "tcp://0.0.0.0:26657",
            "CREATE_EMPTY_BLOCKS": "true",
            "TMHOME": str(tmp_path),
            "USE_GRPC": "false",
            "TMSTATE": str(state_dir),
            "WRITE_TO_LOG": "false",
        }

        with patch.dict("os.environ", env):
            with patch.object(TendermintNode, "init"):
                with patch("operate.services.utils.tendermint.override_config_toml"):
                    with patch.object(TendermintNode, "start"):
                        app, node = create_app()
            # Keep os.environ patch active for route handler env access
            yield app, node

    def test_get_params_success(
        self, flask_app_and_node: Tuple[Flask, TendermintNode], tmp_path: Path
    ) -> None:
        """GET /params returns params and status=True when key file exists."""
        app, _ = flask_app_and_node

        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        priv_key_data = {
            "address": "ABCDEF1234",
            "pub_key": {"type": "tendermint/PubKeyEd25519", "value": "AAAA"},
            "priv_key": {"type": "tendermint/PrivKeyEd25519", "value": "SECRET"},
        }
        (config_dir / "priv_validator_key.json").write_text(
            json.dumps(priv_key_data), encoding="utf-8"
        )

        mock_status = MagicMock()
        mock_status.json.return_value = {"result": {"node_info": {"id": "peer123"}}}

        with patch(
            "operate.services.utils.tendermint.requests.get",
            return_value=mock_status,
        ):
            client = app.test_client()
            response = client.get("/params")

        data = json.loads(response.data)
        assert data["status"] is True
        assert data["error"] is None
        assert data["params"]["address"] == "ABCDEF1234"
        assert "priv_key" not in data["params"]
        assert data["params"]["peer_id"] == "peer123"

    def test_get_params_file_not_found(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /params returns status=False when key file does not exist."""
        app, _ = flask_app_and_node
        # No priv_validator_key.json created → FileNotFoundError caught
        client = app.test_client()
        response = client.get("/params")
        data = json.loads(response.data)
        assert data["status"] is False
        assert data["params"] == {}
        assert data["error"] is not None

    def test_post_params_success(
        self, flask_app_and_node: Tuple[Flask, TendermintNode], tmp_path: Path
    ) -> None:
        """POST /params returns status=True when config files exist."""
        app, _ = flask_app_and_node

        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "genesis.json").write_text("{}", encoding="utf-8")
        (config_dir / "config.toml").write_text(
            'persistent_peers = ""\nexternal_address = ""\n', encoding="utf-8"
        )

        post_data = {
            "genesis_config": {
                "genesis_time": "2021-01-01T00:00:00Z",
                "chain_id": "test-chain-1",
                "consensus_params": {},
            },
            "validators": [
                {
                    "hostname": "node1.example.com",
                    "peer_id": "aabb1122",
                    "p2p_port": 26656,
                    "address": "ADDR1",
                    "pub_key": {"type": "tendermint/PubKeyEd25519", "value": "AAAA"},
                    "power": "10",
                    "name": "validator1",
                }
            ],
            "external_address": "1.2.3.4:26656",
        }

        client = app.test_client()
        response = client.post(
            "/params",
            data=json.dumps(post_data),
            content_type="application/json",
        )
        result = json.loads(response.data)
        assert result["status"] is True
        assert result["error"] is None

    def test_post_params_file_not_found(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """POST /params returns status=False when config directory does not exist."""
        app, _ = flask_app_and_node
        # No config directory → FileNotFoundError caught
        post_data = {
            "genesis_config": {
                "genesis_time": "t",
                "chain_id": "c",
                "consensus_params": {},
            },
            "validators": [],
            "external_address": "",
        }
        client = app.test_client()
        response = client.post(
            "/params",
            data=json.dumps(post_data),
            content_type="application/json",
        )
        result = json.loads(response.data)
        assert result["status"] is False

    def test_gentle_reset_success(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /gentle_reset returns status=True when stop/start succeed."""
        app, node = flask_app_and_node
        with patch.object(node, "stop"):
            with patch.object(node, "start"):
                client = app.test_client()
                response = client.get("/gentle_reset")
        result = json.loads(response.data)
        assert result["status"] is True

    def test_gentle_reset_exception(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /gentle_reset returns status=False when stop raises an exception."""
        app, node = flask_app_and_node
        with patch.object(node, "stop", side_effect=Exception("stop failed")):
            client = app.test_client()
            response = client.get("/gentle_reset")
        result = json.loads(response.data)
        assert result["status"] is False

    def test_gentle_reset_on_exit_returns_500(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /gentle_reset returns 500 when app._is_on_exit is True."""
        app, _ = flask_app_and_node
        app._is_on_exit = True  # type: ignore[attr-defined]
        client = app.test_client()
        response = client.get("/gentle_reset")
        assert response.status_code == 500
        app._is_on_exit = False  # type: ignore[attr-defined]

    def test_app_hash_success(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /app_hash returns the app hash from the block endpoint."""
        app, _ = flask_app_and_node
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {"block": {"header": {"app_hash": "abc123hash"}}}
        }
        mock_response.status_code = 200

        with patch(
            "operate.services.utils.tendermint.requests.get",
            return_value=mock_response,
        ):
            client = app.test_client()
            response = client.get("/app_hash")

        data = json.loads(response.data)
        assert data["app_hash"] == "abc123hash"

    def test_app_hash_with_height_param(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /app_hash?height=100 passes height param to the RPC endpoint."""
        app, _ = flask_app_and_node
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {"block": {"header": {"app_hash": "heighthash"}}}
        }
        mock_response.status_code = 200

        with patch(
            "operate.services.utils.tendermint.requests.get",
            return_value=mock_response,
        ) as mock_get:
            client = app.test_client()
            response = client.get("/app_hash?height=100")

        data = json.loads(response.data)
        assert data["app_hash"] == "heighthash"
        # height param should have been passed
        call_args = mock_get.call_args
        assert call_args[0][1] == {"height": "100"}

    def test_app_hash_exception(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /app_hash returns error message when request raises exception."""
        app, _ = flask_app_and_node
        with patch(
            "operate.services.utils.tendermint.requests.get",
            side_effect=Exception("network error"),
        ):
            client = app.test_client()
            response = client.get("/app_hash")

        data = json.loads(response.data)
        assert "error" in data
        assert response.status_code == 200

    def test_hard_reset_success(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /hard_reset returns status=True when all operations succeed."""
        app, node = flask_app_and_node
        with patch.object(node, "stop"):
            with patch.object(node, "prune_blocks", return_value=0):
                with patch.object(node, "reset_genesis_file"):
                    with patch.object(node, "start"):
                        with patch(
                            "operate.services.utils.tendermint.get_defaults",
                            return_value={"genesis_time": "2021-01-01T00:00:00Z"},
                        ):
                            client = app.test_client()
                            response = client.get("/hard_reset")
        data = json.loads(response.data)
        assert data["status"] is True

    def test_hard_reset_prune_fails(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /hard_reset returns status=False when prune_blocks returns non-zero."""
        app, node = flask_app_and_node
        with patch.object(node, "stop"):
            with patch.object(node, "prune_blocks", return_value=1):
                with patch.object(node, "start"):
                    client = app.test_client()
                    response = client.get("/hard_reset")
        data = json.loads(response.data)
        assert data["status"] is False

    def test_hard_reset_on_exit_returns_500(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /hard_reset returns 500 when app._is_on_exit is True."""
        app, _ = flask_app_and_node
        app._is_on_exit = True  # type: ignore[attr-defined]
        client = app.test_client()
        response = client.get("/hard_reset")
        assert response.status_code == 500
        app._is_on_exit = False  # type: ignore[attr-defined]

    def test_hard_reset_dev_mode(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /hard_reset calls period_dumper.dump_period() when IS_DEV_MODE is True."""
        app, node = flask_app_and_node
        with patch.object(node, "stop"):
            with patch.object(node, "prune_blocks", return_value=0):
                with patch.object(node, "reset_genesis_file"):
                    with patch.object(node, "start"):
                        with patch(
                            "operate.services.utils.tendermint.get_defaults",
                            return_value={"genesis_time": "2021-01-01T00:00:00Z"},
                        ):
                            with patch(
                                "operate.services.utils.tendermint.IS_DEV_MODE",
                                True,
                            ):
                                with patch.object(
                                    PeriodDumper, "dump_period"
                                ) as mock_dump:
                                    client = app.test_client()
                                    response = client.get("/hard_reset")
        data = json.loads(response.data)
        assert data["status"] is True
        mock_dump.assert_called_once()

    def test_hard_reset_with_query_params(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """GET /hard_reset passes query params to reset_genesis_file."""
        app, node = flask_app_and_node
        with patch.object(node, "stop"):
            with patch.object(node, "prune_blocks", return_value=0):
                with patch.object(node, "reset_genesis_file") as mock_reset:
                    with patch.object(node, "start"):
                        with patch(
                            "operate.services.utils.tendermint.get_defaults",
                            return_value={"genesis_time": "default_time"},
                        ):
                            client = app.test_client()
                            response = client.get(
                                "/hard_reset?genesis_time=custom_time&initial_height=5&period_count=2"
                            )
        data = json.loads(response.data)
        assert data["status"] is True
        mock_reset.assert_called_once_with("custom_time", "5", "2")

    def test_404_handler(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """Requesting a non-existent route returns 404 with 'Not Found' in body."""
        app, _ = flask_app_and_node
        client = app.test_client()
        response = client.get("/this_route_does_not_exist")
        assert response.status_code == 404
        assert b"Not Found" in response.data

    def test_500_handler(
        self, flask_app_and_node: Tuple[Flask, TendermintNode]
    ) -> None:
        """Unhandled RuntimeError in route returns 500 with error body."""
        app, _ = flask_app_and_node
        app._is_on_exit = True  # type: ignore[attr-defined]
        client = app.test_client()
        response = client.get("/gentle_reset")
        assert response.status_code == 500
        assert b"Error Closing Node" in response.data
        app._is_on_exit = False  # type: ignore[attr-defined]
