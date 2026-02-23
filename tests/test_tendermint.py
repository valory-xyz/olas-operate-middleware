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

"""Tests for operate/services/utils/tendermint.py."""

import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.services.utils.tendermint import (
    CONFIG_OVERRIDE,
    PeriodDumper,
    StoppableThread,
    TendermintNode,
    TendermintParams,
    get_defaults,
    load_genesis,
    override_config_toml,
    update_external_address,
    update_genesis_config,
    update_peers,
)


# ---------------------------------------------------------------------------
# StoppableThread
# ---------------------------------------------------------------------------


class TestStoppableThread:
    """Tests for StoppableThread."""

    def test_init_creates_stop_event(self) -> None:
        """Create thread, verify stopped() returns False and _stop_event exists."""
        thread = StoppableThread()
        assert hasattr(thread, "_stop_event")
        assert thread.stopped() is False

    def test_stop_sets_event(self) -> None:
        """After stop(), stopped() returns True."""
        thread = StoppableThread()
        thread.stop()
        assert thread.stopped() is True


# ---------------------------------------------------------------------------
# TendermintParams
# ---------------------------------------------------------------------------


class TestTendermintParams:
    """Tests for TendermintParams."""

    def test_init_defaults(self) -> None:
        """Check proxy_app stored, default rpc_laddr, p2p_laddr, p2p_seeds=None, use_grpc=False."""
        params = TendermintParams(proxy_app="tcp://localhost:26658")
        assert params.proxy_app == "tcp://localhost:26658"
        assert "26657" in params.rpc_laddr
        assert "26656" in params.p2p_laddr
        assert params.p2p_seeds is None
        assert params.use_grpc is False

    def test_init_custom_values(self) -> None:
        """All params set correctly when passed explicitly."""
        params = TendermintParams(
            proxy_app="tcp://myapp:1234",
            rpc_laddr="tcp://0.0.0.0:9999",
            p2p_laddr="tcp://0.0.0.0:8888",
            p2p_seeds=["seed1:26656", "seed2:26656"],
            consensus_create_empty_blocks=False,
            home="/tmp/tm_home",  # nosec B108
            use_grpc=True,
        )
        assert params.proxy_app == "tcp://myapp:1234"
        assert params.rpc_laddr == "tcp://0.0.0.0:9999"
        assert params.p2p_laddr == "tcp://0.0.0.0:8888"
        assert params.p2p_seeds == ["seed1:26656", "seed2:26656"]
        assert params.consensus_create_empty_blocks is False
        assert params.home == "/tmp/tm_home"  # nosec B108
        assert params.use_grpc is True

    def test_str_contains_proxy_app(self) -> None:
        """str(params) includes the proxy_app value."""
        params = TendermintParams(proxy_app="tcp://myproxy:26658")
        result = str(params)
        assert "tcp://myproxy:26658" in result

    def test_build_node_command_basic(self) -> None:
        """List includes proxy_app, rpc.laddr, p2p.laddr, abci=socket."""
        params = TendermintParams(proxy_app="tcp://localhost:26658")
        cmd = params.build_node_command()
        assert "tendermint" in cmd
        assert "node" in cmd
        assert any("tcp://localhost:26658" in arg for arg in cmd)
        assert any("rpc.laddr" in arg for arg in cmd)
        assert any("p2p.laddr" in arg for arg in cmd)
        assert any("abci=socket" in arg for arg in cmd)

    def test_build_node_command_debug(self) -> None:
        """Adds --log_level=debug when debug=True."""
        params = TendermintParams(proxy_app="tcp://localhost:26658")
        cmd = params.build_node_command(debug=True)
        assert "--log_level=debug" in cmd

    def test_build_node_command_without_debug(self) -> None:
        """Does not add --log_level=debug when debug=False."""
        params = TendermintParams(proxy_app="tcp://localhost:26658")
        cmd = params.build_node_command(debug=False)
        assert "--log_level=debug" not in cmd

    def test_build_node_command_with_seeds(self) -> None:
        """Seeds joined with comma in command."""
        params = TendermintParams(
            proxy_app="tcp://localhost:26658",
            p2p_seeds=["peer1@host1:26656", "peer2@host2:26656"],
        )
        cmd = params.build_node_command()
        seeds_args = [arg for arg in cmd if "p2p.seeds" in arg]
        assert len(seeds_args) == 1
        assert "peer1@host1:26656,peer2@host2:26656" in seeds_args[0]

    def test_build_node_command_grpc(self) -> None:
        """abci=grpc when use_grpc=True."""
        params = TendermintParams(proxy_app="tcp://localhost:26658", use_grpc=True)
        cmd = params.build_node_command()
        assert any("abci=grpc" in arg for arg in cmd)

    @pytest.mark.skipif(
        sys.platform == "win32", reason="os.setsid not available on Windows"
    )
    def test_get_node_command_kwargs_non_windows(self) -> None:
        """Includes preexec_fn, does NOT include creationflags on non-Windows."""
        with patch(
            "operate.services.utils.tendermint.platform.system", return_value="Linux"
        ):
            kwargs = TendermintParams.get_node_command_kwargs()
        assert "preexec_fn" in kwargs
        assert "creationflags" not in kwargs
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.STDOUT


# ---------------------------------------------------------------------------
# TendermintNode
# ---------------------------------------------------------------------------


class TestTendermintNode:
    """Tests for TendermintNode."""

    def _make_params(self) -> TendermintParams:
        """Return a minimal TendermintParams instance."""
        return TendermintParams(proxy_app="tcp://localhost:26658")

    def test_init_stores_params(self) -> None:
        """Stores params, _process=None, _monitoring=None, _stopping=False, write_to_log=False."""
        params = self._make_params()
        node = TendermintNode(params=params)
        assert node.params is params
        assert node._process is None  # pylint: disable=protected-access
        assert node._monitoring is None  # pylint: disable=protected-access
        assert node._stopping is False  # pylint: disable=protected-access
        assert node.write_to_log is False

    def test_init_write_to_log_true(self) -> None:
        """write_to_log is stored correctly when True."""
        params = self._make_params()
        node = TendermintNode(params=params, write_to_log=True)
        assert node.write_to_log is True

    def test_write_to_console_writes_to_stdout(self) -> None:
        """Call TendermintNode._write_to_console, verify sys.stdout.write called."""
        mock_stdout = MagicMock()
        with patch.object(sys, "stdout", mock_stdout):
            TendermintNode._write_to_console(
                "hello\n"
            )  # pylint: disable=protected-access
        mock_stdout.write.assert_called_once_with("hello\n")
        mock_stdout.flush.assert_called_once()

    def test_write_to_file_creates_file(self, tmp_path: Path) -> None:
        """Create node, call _write_to_file with tmp log_file, verify file content."""
        params = self._make_params()
        node = TendermintNode(params=params)
        log_file = tmp_path / "test_node.log"
        node.log_file = str(log_file)
        node._write_to_file("content line\n")  # pylint: disable=protected-access
        assert log_file.read_text(encoding="utf-8") == "content line\n"

    def test_write_to_file_appends(self, tmp_path: Path) -> None:
        """Multiple calls to _write_to_file append to the file."""
        params = self._make_params()
        node = TendermintNode(params=params)
        log_file = tmp_path / "test_node.log"
        node.log_file = str(log_file)
        node._write_to_file("line1\n")  # pylint: disable=protected-access
        node._write_to_file("line2\n")  # pylint: disable=protected-access
        content = log_file.read_text(encoding="utf-8")
        assert "line1\n" in content
        assert "line2\n" in content

    def test_log_only_console_when_write_to_log_false(self, tmp_path: Path) -> None:
        """write_to_log=False: log() calls _write_to_console but not _write_to_file."""
        params = self._make_params()
        node = TendermintNode(params=params, write_to_log=False)
        with patch.object(node, "_write_to_console") as mock_console, patch.object(
            node, "_write_to_file"
        ) as mock_file:
            node.log("test message\n")
        mock_console.assert_called_once_with(line="test message\n")
        mock_file.assert_not_called()

    def test_log_to_both_when_write_to_log_true(self) -> None:
        """write_to_log=True: log() calls both _write_to_console and _write_to_file."""
        params = self._make_params()
        node = TendermintNode(params=params, write_to_log=True)
        with patch.object(node, "_write_to_console") as mock_console, patch.object(
            node, "_write_to_file"
        ) as mock_file:
            node.log("test message\n")
        mock_console.assert_called_once_with(line="test message\n")
        mock_file.assert_called_once_with(line="test message\n")

    def test_prune_blocks_calls_subprocess(self, tmp_path: Path) -> None:
        """Verify subprocess.call is invoked with the expected tendermint args."""
        params = TendermintParams(
            proxy_app="tcp://localhost:26658",
            home=str(tmp_path),
        )
        node = TendermintNode(params=params)
        with patch(
            "operate.services.utils.tendermint.subprocess.call", return_value=0
        ) as mock_call:
            result = node.prune_blocks()
        assert result == 0
        mock_call.assert_called_once()
        call_args = mock_call.call_args[0][0]
        assert "tendermint" in call_args
        assert "unsafe-reset-all" in call_args
        assert str(tmp_path) in call_args

    def test_reset_genesis_file_updates_fields(self, tmp_path: Path) -> None:
        """Create genesis.json in tmp_path/config/, call reset_genesis_file, verify updated content."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        genesis_data = {
            "genesis_time": "2020-01-01T00:00:00Z",
            "chain_id": "old-chain",
            "initial_height": "0",
            "validators": [],
        }
        genesis_file = config_dir / "genesis.json"
        genesis_file.write_text(json.dumps(genesis_data), encoding="utf-8")

        params = TendermintParams(
            proxy_app="tcp://localhost:26658",
            home=str(tmp_path),
        )
        node = TendermintNode(params=params)
        node.reset_genesis_file(
            genesis_time="2021-06-01T12:00:00Z",
            initial_height="10",
            period_count="5",
        )

        updated = json.loads(genesis_file.read_text(encoding="utf-8"))
        assert updated["genesis_time"] == "2021-06-01T12:00:00Z"
        assert updated["initial_height"] == "10"
        assert updated["chain_id"] == "autonolas-5"


# ---------------------------------------------------------------------------
# load_genesis
# ---------------------------------------------------------------------------


class TestLoadGenesis:
    """Tests for load_genesis."""

    def test_load_genesis_reads_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set TMHOME env var pointing to tmp_path with config/genesis.json, verify result."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        genesis_data = {"genesis_time": "2021-01-01T00:00:00Z", "chain_id": "test"}
        (config_dir / "genesis.json").write_text(
            json.dumps(genesis_data), encoding="utf-8"
        )
        monkeypatch.setenv("TMHOME", str(tmp_path))
        result = load_genesis()
        assert result["genesis_time"] == "2021-01-01T00:00:00Z"
        assert result["chain_id"] == "test"


# ---------------------------------------------------------------------------
# get_defaults
# ---------------------------------------------------------------------------


class TestGetDefaults:
    """Tests for get_defaults."""

    def test_get_defaults_returns_genesis_time(self) -> None:
        """Verify get_defaults() returns genesis_time from load_genesis."""
        with patch(
            "operate.services.utils.tendermint.load_genesis",
            return_value={"genesis_time": "2021-01-01T00:00:00Z"},
        ):
            result = get_defaults()
        assert result == {"genesis_time": "2021-01-01T00:00:00Z"}

    def test_get_defaults_missing_key_returns_none(self) -> None:
        """When genesis_time key is absent, value is None."""
        with patch(
            "operate.services.utils.tendermint.load_genesis",
            return_value={},
        ):
            result = get_defaults()
        assert result["genesis_time"] is None


# ---------------------------------------------------------------------------
# override_config_toml
# ---------------------------------------------------------------------------


class TestOverrideConfigToml:
    """Tests for override_config_toml."""

    def test_overrides_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Create config.toml with old values, call override_config_toml(), verify replacements."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_toml = config_dir / "config.toml"

        # Write all the "old" strings that CONFIG_OVERRIDE replaces
        original_lines = "\n".join(old for old, _ in CONFIG_OVERRIDE)
        config_toml.write_text(original_lines, encoding="utf-8")

        monkeypatch.setenv("TMHOME", str(tmp_path))
        override_config_toml()

        updated = config_toml.read_text(encoding="utf-8")
        for old, new in CONFIG_OVERRIDE:
            assert old not in updated
            assert new in updated

    def test_specific_replacements(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify the three known CONFIG_OVERRIDE replacements."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_toml = config_dir / "config.toml"
        config_toml.write_text(
            "fast_sync = true\nmax_num_outbound_peers = 10\npex = true\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("TMHOME", str(tmp_path))
        override_config_toml()
        content = config_toml.read_text(encoding="utf-8")
        assert "fast_sync = false" in content
        assert "max_num_outbound_peers = 0" in content
        assert "pex = false" in content


# ---------------------------------------------------------------------------
# update_peers
# ---------------------------------------------------------------------------


class TestUpdatePeers:
    """Tests for update_peers."""

    def test_update_peers_basic(self, tmp_path: Path) -> None:
        """Create config.toml with persistent_peers, call update_peers, verify updated content."""
        config_toml = tmp_path / "config.toml"
        config_toml.write_text(
            'persistent_peers = ""\nother_setting = "value"\n', encoding="utf-8"
        )
        validators = [
            {
                "hostname": "node1.example.com",
                "peer_id": "aabbcc001122",
                "p2p_port": 26656,
            },
            {
                "hostname": "node2.example.com",
                "peer_id": "ddeeff334455",
                "p2p_port": 26656,
            },
        ]
        update_peers(validators=validators, config_path=config_toml)
        content = config_toml.read_text(encoding="utf-8")
        assert "aabbcc001122@node1.example.com:26656" in content
        assert "ddeeff334455@node2.example.com:26656" in content

    def test_update_peers_localhost_hostname_preserved(self, tmp_path: Path) -> None:
        """Validator with localhost hostname keeps localhost in peer string."""
        config_toml = tmp_path / "config.toml"
        config_toml.write_text('persistent_peers = ""\n', encoding="utf-8")
        validators = [
            {
                "hostname": "localhost",
                "peer_id": "aabb1122",
                "p2p_port": 26656,
            }
        ]
        update_peers(validators=validators, config_path=config_toml)
        content = config_toml.read_text(encoding="utf-8")
        assert "aabb1122@localhost:26656" in content

    def test_update_peers_zero_zero_hostname_replaced(self, tmp_path: Path) -> None:
        """Validator with 0.0.0.0 hostname is mapped to localhost in peer string."""
        config_toml = tmp_path / "config.toml"
        config_toml.write_text('persistent_peers = ""\n', encoding="utf-8")
        validators = [
            {
                "hostname": "0.0.0.0",  # nosec B104
                "peer_id": "ccdd5566",
                "p2p_port": 26657,
            }
        ]
        update_peers(validators=validators, config_path=config_toml)
        content = config_toml.read_text(encoding="utf-8")
        assert "ccdd5566@localhost:26657" in content


# ---------------------------------------------------------------------------
# update_external_address
# ---------------------------------------------------------------------------


class TestUpdateExternalAddress:
    """Tests for update_external_address."""

    def test_update_external_address(self, tmp_path: Path) -> None:
        """Create config.toml with old external_address, call update_external_address, verify."""
        config_toml = tmp_path / "config.toml"
        config_toml.write_text(
            'external_address = "old_addr:26656"\nother = "x"\n', encoding="utf-8"
        )
        update_external_address("new_addr:26656", config_toml)
        content = config_toml.read_text(encoding="utf-8")
        assert 'external_address = "new_addr:26656"' in content
        assert "old_addr" not in content

    def test_update_external_address_empty_value(self, tmp_path: Path) -> None:
        """Works when original external_address is empty string."""
        config_toml = tmp_path / "config.toml"
        config_toml.write_text('external_address = ""\n', encoding="utf-8")
        update_external_address("192.168.1.1:26656", config_toml)
        content = config_toml.read_text(encoding="utf-8")
        assert 'external_address = "192.168.1.1:26656"' in content


# ---------------------------------------------------------------------------
# update_genesis_config
# ---------------------------------------------------------------------------


class TestUpdateGenesisConfig:
    """Tests for update_genesis_config."""

    _SAMPLE_DATA = {
        "genesis_config": {
            "genesis_time": "2022-03-01T00:00:00Z",
            "chain_id": "test-chain-1",
            "consensus_params": {
                "block": {"max_bytes": "22020096"},
                "evidence": {"max_age_num_blocks": "100000"},
                "validator": {"pub_key_types": ["ed25519"]},
            },
        },
        "validators": [
            {
                "address": "ABCDEF0123456789",
                "pub_key": {"type": "tendermint/PubKeyEd25519", "value": "AAAA"},
                "power": "10",
                "name": "val1",
            }
        ],
        "external_address": "",
    }

    def test_update_genesis_config_writes_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set TMHOME env, create config/genesis.json, call update_genesis_config, verify content."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        genesis_file = config_dir / "genesis.json"
        genesis_file.write_text("{}", encoding="utf-8")

        monkeypatch.setenv("TMHOME", str(tmp_path))
        update_genesis_config(self._SAMPLE_DATA)

        written = json.loads(genesis_file.read_text(encoding="utf-8"))
        assert written["genesis_time"] == "2022-03-01T00:00:00Z"
        assert written["chain_id"] == "test-chain-1"
        assert written["initial_height"] == "0"
        assert written["app_hash"] == ""
        assert len(written["validators"]) == 1
        assert written["validators"][0]["address"] == "ABCDEF0123456789"
        assert written["validators"][0]["name"] == "val1"
        assert written["validators"][0]["power"] == "10"

    def test_update_genesis_config_multiple_validators(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple validators are all written to genesis.json."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "genesis.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("TMHOME", str(tmp_path))

        data = dict(self._SAMPLE_DATA)
        data["validators"] = [
            {
                "address": "ADDR1",
                "pub_key": {"type": "tendermint/PubKeyEd25519", "value": "AAAA"},
                "power": "10",
                "name": "val1",
            },
            {
                "address": "ADDR2",
                "pub_key": {"type": "tendermint/PubKeyEd25519", "value": "BBBB"},
                "power": "5",
                "name": "val2",
            },
        ]
        update_genesis_config(data)
        written = json.loads((config_dir / "genesis.json").read_text(encoding="utf-8"))
        assert len(written["validators"]) == 2
        addresses = [v["address"] for v in written["validators"]]
        assert "ADDR1" in addresses
        assert "ADDR2" in addresses


# ---------------------------------------------------------------------------
# PeriodDumper
# ---------------------------------------------------------------------------


class TestPeriodDumper:
    """Tests for PeriodDumper."""

    def _make_logger(self) -> MagicMock:
        """Return a mock logger."""
        return MagicMock()

    def test_init_creates_dump_dir(self, tmp_path: Path) -> None:
        """New dir created, resets=0."""
        dump_dir = tmp_path / "tm_dump"
        assert not dump_dir.exists()
        dumper = PeriodDumper(logger=self._make_logger(), dump_dir=dump_dir)
        assert dump_dir.is_dir()
        assert dumper.resets == 0

    def test_init_removes_existing_dir(self, tmp_path: Path) -> None:
        """Existing dump_dir removed and recreated (is empty after init)."""
        dump_dir = tmp_path / "tm_dump"
        dump_dir.mkdir()
        existing_file = dump_dir / "old_file.txt"
        existing_file.write_text("old content", encoding="utf-8")
        assert existing_file.exists()

        dumper = PeriodDumper(logger=self._make_logger(), dump_dir=dump_dir)
        assert dump_dir.is_dir()
        # The old file should have been wiped
        assert not existing_file.exists()
        assert dumper.resets == 0

    def test_readonly_handler_calls_func(self, tmp_path: Path) -> None:
        """Mock func is called after chmod."""
        target_file = tmp_path / "readonly.txt"
        target_file.write_text("data", encoding="utf-8")
        # Make the file writable so chmod won't fail; we just need to verify func called
        mock_func = MagicMock()
        PeriodDumper.readonly_handler(mock_func, str(target_file), None)
        mock_func.assert_called_once_with(str(target_file))

    def test_readonly_handler_ignores_file_not_found(self, tmp_path: Path) -> None:
        """Test that a raised FileNotFoundError by func is silently swallowed."""
        nonexistent = str(tmp_path / "nonexistent_file.txt")

        def _raising_func(path: str) -> None:
            raise FileNotFoundError(f"not found: {path}")

        # Should not raise
        PeriodDumper.readonly_handler(_raising_func, nonexistent, None)

    def test_readonly_handler_ignores_oserror(self, tmp_path: Path) -> None:
        """Test that a raised OSError by func is silently swallowed."""
        target_file = tmp_path / "somefile.txt"
        target_file.write_text("x", encoding="utf-8")

        def _raising_func(path: str) -> None:
            raise OSError(f"os error: {path}")

        # Should not raise
        PeriodDumper.readonly_handler(_raising_func, str(target_file), None)

    def test_dump_period_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set TMHOME/ID env, create source dir, call dump_period, verify copy and resets==1."""
        # Create the source TMHOME dir with some content
        tmhome = tmp_path / "tmhome"
        tmhome.mkdir()
        (tmhome / "data.txt").write_text("tm data", encoding="utf-8")

        dump_dir = tmp_path / "dump"

        monkeypatch.setenv("TMHOME", str(tmhome))
        monkeypatch.setenv("ID", "0")

        logger = self._make_logger()
        dumper = PeriodDumper(logger=logger, dump_dir=dump_dir)

        dumper.dump_period()

        assert dumper.resets == 1
        # The copy should exist at dump_dir/period_0/node0/
        copied_dir = dump_dir / "period_0" / "node0"
        assert copied_dir.is_dir()
        assert (copied_dir / "data.txt").read_text(encoding="utf-8") == "tm data"

    def test_dump_period_oserror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set TMHOME to nonexistent path, OSError caught, resets still increments."""
        nonexistent_tmhome = tmp_path / "nonexistent_tmhome"
        # deliberately do NOT create this directory

        dump_dir = tmp_path / "dump"

        monkeypatch.setenv("TMHOME", str(nonexistent_tmhome))
        monkeypatch.setenv("ID", "0")

        logger = self._make_logger()
        dumper = PeriodDumper(logger=logger, dump_dir=dump_dir)

        # Should not raise; OSError is caught internally
        dumper.dump_period()
        assert dumper.resets == 1

    def test_dump_period_increments_resets_multiple_times(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify resets counter increments on each call to dump_period."""
        tmhome = tmp_path / "tmhome"
        tmhome.mkdir()
        dump_dir = tmp_path / "dump"

        monkeypatch.setenv("TMHOME", str(tmhome))
        monkeypatch.setenv("ID", "1")

        logger = self._make_logger()
        dumper = PeriodDumper(logger=logger, dump_dir=dump_dir)

        dumper.dump_period()
        dumper.dump_period()
        assert dumper.resets == 2
