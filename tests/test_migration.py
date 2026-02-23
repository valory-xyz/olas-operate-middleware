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

"""Tests for operate.migration module."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from operate.keys import KeysManager
from operate.migration import MigrationManager
from operate.operate_types import LedgerType
from operate.services.service import SERVICE_CONFIG_PREFIX, SERVICE_CONFIG_VERSION


class TestMigrateWallets:
    """Tests for MigrationManager.migrate_wallets."""

    def test_migrate_wallets_skips_when_wallet_class_is_none(
        self, tmp_path: Path
    ) -> None:
        """Test that migrate_wallets skips ledger types without a wallet class."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.path = tmp_path

        # Patch LEDGER_TYPE_TO_WALLET_CLASS to be empty so wallet_class is None
        with patch("operate.migration.LEDGER_TYPE_TO_WALLET_CLASS", {}):
            manager.migrate_wallets(mock_wallet_manager)

        info_calls = str(manager.logger.info.call_args_list)  # type: ignore[attr-defined]
        assert "has been migrated" not in info_calls

    def test_migrate_wallets_logs_info_on_successful_migration(
        self, tmp_path: Path
    ) -> None:
        """Test that migrate_wallets logs info when a wallet migration succeeds."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        mock_wallet_class = MagicMock()
        mock_wallet_class.migrate_format.return_value = True

        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = True
        mock_wallet_manager.path = tmp_path

        with patch(
            "operate.migration.LEDGER_TYPE_TO_WALLET_CLASS",
            {LedgerType.ETHEREUM: mock_wallet_class},
        ):
            manager.migrate_wallets(mock_wallet_manager)

        info_calls = str(manager.logger.info.call_args_list)  # type: ignore[attr-defined]
        assert "has been migrated" in info_calls

    def test_migrate_wallets_skips_nonexistent_ledger(self, tmp_path: Path) -> None:
        """Test that migrate_wallets skips ledger types that do not exist in wallet_manager."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        mock_wallet_manager = MagicMock()
        mock_wallet_manager.exists.return_value = False  # No ledger type exists

        manager.migrate_wallets(mock_wallet_manager)

        info_calls = str(manager.logger.info.call_args_list)  # type: ignore[attr-defined]
        assert "has been migrated" not in info_calls


class TestMigrateService:
    """Tests for MigrationManager._migrate_service."""

    def test_migrate_service_not_a_directory_returns_false(
        self, tmp_path: Path
    ) -> None:
        """Test _migrate_service returns False when path is not a directory."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        # Create a file (not a directory)
        not_a_dir = tmp_path / "not_a_dir.txt"
        not_a_dir.write_text("content", encoding="utf-8")

        result = manager._migrate_service(not_a_dir)  # pylint: disable=protected-access

        assert result is False
        manager.logger.warning.assert_called()  # type: ignore[attr-defined]
        warning_str = str(manager.logger.warning.call_args)  # type: ignore[attr-defined]
        assert "not a directory" in warning_str.lower()

    def test_migrate_service_invalid_prefix_returns_false(self, tmp_path: Path) -> None:
        """Test _migrate_service returns False when path has an invalid prefix."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        # Create a directory with invalid prefix
        invalid_dir = tmp_path / "invalid_prefix_dir"
        invalid_dir.mkdir()

        result = manager._migrate_service(
            invalid_dir
        )  # pylint: disable=protected-access

        assert result is False
        manager.logger.warning.assert_called()  # type: ignore[attr-defined]
        warning_str = str(manager.logger.warning.call_args)  # type: ignore[attr-defined]
        assert "valid service config" in warning_str.lower()

    def test_migrate_service_newer_version_raises_runtime_error(
        self, tmp_path: Path
    ) -> None:
        """Test _migrate_service raises RuntimeError for service configs with newer version."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        service_dir = tmp_path / f"{SERVICE_CONFIG_PREFIX}test"
        service_dir.mkdir()

        config_data = {
            "name": "test_service",
            "version": SERVICE_CONFIG_VERSION + 1,
        }
        (service_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )

        with pytest.raises(RuntimeError, match="newer version"):
            manager._migrate_service(service_dir)  # pylint: disable=protected-access

    def test_migrate_service_trader_adds_missing_env_vars(self, tmp_path: Path) -> None:
        """Test _migrate_service adds missing env vars for trader services."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        service_dir = tmp_path / f"{SERVICE_CONFIG_PREFIX}trader"
        service_dir.mkdir()

        config_data = {
            "name": "Trader Agent",
            "version": SERVICE_CONFIG_VERSION,  # Already current
            "env_variables": {},  # Missing env vars
        }
        config_file = service_dir / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = manager._migrate_service(
            service_dir
        )  # pylint: disable=protected-access

        # Already at current version, so returns False after adding env vars
        assert result is False

        # Env vars should have been written to disk
        updated = json.loads(config_file.read_text(encoding="utf-8"))
        assert "GNOSIS_LEDGER_RPC" in updated["env_variables"]
        assert "MECH_REQUEST_PRICE" in updated["env_variables"]

    def test_migrate_service_trader_does_not_overwrite_existing_env_vars(
        self, tmp_path: Path
    ) -> None:
        """Test _migrate_service does not overwrite existing env vars for trader services."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        service_dir = tmp_path / f"{SERVICE_CONFIG_PREFIX}trader2"
        service_dir.mkdir()

        existing_rpc = "https://my-custom-rpc.example.com"
        config_data = {
            "name": "Trader Pearl",
            "version": SERVICE_CONFIG_VERSION,
            "env_variables": {
                "GNOSIS_LEDGER_RPC": {
                    "name": "Gnosis RPC",
                    "description": "",
                    "value": existing_rpc,
                    "provision_type": "computed",
                }
            },
        }
        config_file = service_dir / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        manager._migrate_service(service_dir)  # pylint: disable=protected-access

        updated = json.loads(config_file.read_text(encoding="utf-8"))
        # Existing value should not be overwritten
        assert updated["env_variables"]["GNOSIS_LEDGER_RPC"]["value"] == existing_rpc


class TestMigrateServices:
    """Tests for MigrationManager.migrate_services."""

    def test_migrate_services_multiple_bafybei_raises_runtime_error(
        self, tmp_path: Path
    ) -> None:
        """Test migrate_services raises RuntimeError when multiple bafybei folders exist."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        services_dir = tmp_path / "services"
        services_dir.mkdir()

        # Create two bafybei folders
        (services_dir / "bafybei123abc").mkdir()
        (services_dir / "bafybei456def").mkdir()

        mock_service_manager = MagicMock()
        mock_service_manager.path = services_dir

        with pytest.raises(RuntimeError, match="bafybei"):
            manager.migrate_services(mock_service_manager)


class TestMigrateQsConfigs:
    """Tests for MigrationManager.migrate_qs_configs."""

    def test_migrate_qs_configs_renames_optimistic_to_optimism(
        self, tmp_path: Path
    ) -> None:
        """Test migrate_qs_configs renames 'optimistic' to 'optimism' in rpc and principal_chain."""
        config_data = {
            "rpc": {"optimistic": "https://optimism-rpc.example.com"},
            "principal_chain": "optimistic",
            "other_key": "unchanged",
        }
        config_file = tmp_path / "test-quickstart-config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_qs_configs()

        updated = json.loads(config_file.read_text(encoding="utf-8"))
        assert "optimism" in updated["rpc"]
        assert "optimistic" not in updated["rpc"]
        assert updated["principal_chain"] == "optimism"
        assert updated["other_key"] == "unchanged"

        manager.logger.info.assert_called()  # type: ignore[attr-defined]

    def test_migrate_qs_configs_no_migration_when_already_correct(
        self, tmp_path: Path
    ) -> None:
        """Test migrate_qs_configs does not modify file when no migration is needed."""
        config_data = {
            "rpc": {"optimism": "https://optimism-rpc.example.com"},
            "principal_chain": "optimism",
        }
        config_file = tmp_path / "service-quickstart-config.json"
        original_content = json.dumps(config_data)
        config_file.write_text(original_content, encoding="utf-8")

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_qs_configs()

        # File should be unchanged
        assert config_file.read_text(encoding="utf-8") == original_content

    def test_migrate_qs_configs_only_principal_chain(self, tmp_path: Path) -> None:
        """Test migrate_qs_configs handles case where only principal_chain needs renaming."""
        config_data = {
            "rpc": {"optimism": "https://rpc.example.com"},
            "principal_chain": "optimistic",
        }
        config_file = tmp_path / "myservice-quickstart-config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_qs_configs()

        updated = json.loads(config_file.read_text(encoding="utf-8"))
        assert updated["principal_chain"] == "optimism"
        # rpc should be unchanged
        assert "optimism" in updated["rpc"]


class TestMigrateKeys:
    """Tests for MigrationManager.migrate_keys."""

    def test_migrate_keys_skips_bak_files(self, tmp_path: Path) -> None:
        """Test migrate_keys skips .bak files without processing them."""
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()

        # Create a .bak file
        bak_file = keys_dir / "0xaabbccddeeff00112233445566778899aabbccdd.bak"
        bak_file.write_text('{"ledger": "ethereum"}', encoding="utf-8")

        mock_keys_manager = MagicMock()
        mock_keys_manager.path = keys_dir
        mock_keys_manager.password = None

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_keys(mock_keys_manager)

        # .bak file should not be read for migration (no error logged)
        error_calls = str(manager.logger.error.call_args_list)  # type: ignore[attr-defined]
        assert "Failed to read key file" not in error_calls

    def test_migrate_keys_malformed_json_raises(self, tmp_path: Path) -> None:
        """Test migrate_keys raises on malformed JSON key file."""
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()

        # Valid Ethereum address as filename but invalid JSON content
        address = "0x" + "a" * 40
        invalid_key = keys_dir / address
        invalid_key.write_text("not valid json at all {{{", encoding="utf-8")

        mock_keys_manager = MagicMock()
        mock_keys_manager.path = keys_dir
        mock_keys_manager.password = None

        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        with pytest.raises(json.JSONDecodeError):
            manager.migrate_keys(mock_keys_manager)

        manager.logger.error.assert_called()  # type: ignore[attr-defined]

    def test_migrate_keys_encrypts_unencrypted_key_when_password_set(
        self, tmp_path: Path
    ) -> None:
        """Test migrate_keys encrypts plain-text private keys when password is configured."""
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()

        password = "testpassword123"  # nosec B105
        km = KeysManager(
            path=keys_dir, logger=MagicMock(spec=logging.Logger), password=password
        )
        address = km.create()

        # Retrieve the raw (decrypted) private key
        crypto = km.get_crypto_instance(address)
        raw_private_key = crypto.private_key

        # Write unencrypted version of the key
        with open(keys_dir / address, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ledger": "ethereum",
                    "address": address,
                    "private_key": raw_private_key,
                },
                f,
            )

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_keys(km)

        # Key should now be encrypted (no longer starts with 0x)
        with open(keys_dir / address, "r", encoding="utf-8") as f:
            updated = json.load(f)

        assert not updated["private_key"].startswith(
            "0x"
        ), "Private key should be encrypted after migration"

    def test_migrate_keys_creates_backup_when_missing(self, tmp_path: Path) -> None:
        """Test migrate_keys creates a .bak file if one does not exist."""
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()

        km = KeysManager(
            path=keys_dir, logger=MagicMock(spec=logging.Logger), password=None
        )
        address = km.create()

        # Remove the .bak file
        bak = keys_dir / f"{address}.bak"
        if bak.exists():
            bak.unlink()

        assert not bak.exists()

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_keys(km)

        # .bak file should be re-created
        assert bak.exists()


class TestMigrateServiceBafybei:
    """Tests for _migrate_service with bafybei-prefixed paths."""

    def test_migrate_service_bafybei_removes_deployment_dir_from_backup(
        self, tmp_path: Path
    ) -> None:
        """Test _migrate_service removes the deployment dir from bafybei backup (line 189)."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        bafybei_dir = tmp_path / "bafybeitest"
        bafybei_dir.mkdir()

        # The bafybei dir has a 'deployment' subdir
        deployment_dir = bafybei_dir / "deployment"
        deployment_dir.mkdir()

        # Provide a config.json at current version so migration returns False immediately
        config_data = {
            "name": "some_service",
            "version": SERVICE_CONFIG_VERSION,
            "env_variables": {},
        }
        (bafybei_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )

        result = manager._migrate_service(
            bafybei_dir
        )  # pylint: disable=protected-access

        assert result is False

        # A backup directory should have been created
        backups = list(tmp_path.glob("backup_*"))
        assert len(backups) == 1, "Exactly one backup should be created"

        # The backup should NOT contain the deployment subdir (it was removed)
        backup_deployment = backups[0] / "deployment"
        assert not backup_deployment.exists()


class TestMigrateServiceV9UnsupportedPackagePath:
    """Tests for _migrate_service with an unsupported package_path in v<9 configs."""

    def test_migrate_service_v9_unsupported_package_path_raises(
        self, tmp_path: Path
    ) -> None:
        """Test _migrate_service raises RuntimeError for unknown package_path (lines 391-392)."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        service_dir = tmp_path / f"{SERVICE_CONFIG_PREFIX}v9test"
        service_dir.mkdir()

        # version=8 triggers the v<9 block; "unknown_package" is not in agents_supported
        config_data = {
            "name": "Test Service",
            "version": 8,
            "hash": "bafybeiXXX",
            "package_path": "unknown_package",
            "agent_addresses": ["0x1234567890123456789012345678901234567890"],
            "home_chain": "gnosis",
            "chain_configs": {
                "gnosis": {
                    "ledger_config": {"chain": "gnosis"},
                    "chain_data": {
                        "instances": [],
                        "token": 1,
                        "multisig": "0xmultisig",
                        "staked": False,
                        "on_chain_state": 3,
                        "user_params": {
                            "staking_program_id": "no_staking",
                            "nft": "QmXXX",
                            "cost_of_bond": 10000000000000000,
                            "fund_requirements": {
                                "0x0000000000000000000000000000000000000000": 10000000000000000
                            },
                        },
                    },
                }
            },
            "env_variables": {},
        }
        (service_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )

        with pytest.raises(RuntimeError, match="Found unsupported"):
            manager._migrate_service(service_dir)  # pylint: disable=protected-access


class TestMigrateKeysNonKeyFile:
    """Tests for migrate_keys non-key file handling (line 504)."""

    def test_migrate_keys_non_key_non_bak_file_logs_warning(
        self, tmp_path: Path
    ) -> None:
        """Test migrate_keys logs a warning for files that are not addresses and not .bak (line 504)."""
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()

        # Create a file with a non-address name and no .bak extension
        (keys_dir / "readme.txt").write_text("not a key", encoding="utf-8")

        mock_keys_manager = MagicMock()
        mock_keys_manager.path = keys_dir
        mock_keys_manager.password = None

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_keys(mock_keys_manager)

        warning_calls = str(
            manager.logger.warning.call_args_list  # type: ignore[attr-defined]
        )
        assert "Skipping non-key file" in warning_calls


class TestMigrateServiceVersionMigrationPaths:
    """Tests for _migrate_service version migration paths with IPFSTool mocked."""

    def test_migrate_service_v7_replaces_0xm_multisig(self, tmp_path: Path) -> None:
        """Test v<7 migration replaces '0xm' multisig with NON_EXISTENT_MULTISIG (line 347)."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        service_dir = tmp_path / f"{SERVICE_CONFIG_PREFIX}v6test"
        service_dir.mkdir()

        config_data = {
            "name": "Test Service",
            "version": 6,
            "hash": "bafybeiFakeHash",
            "package_path": "trader_pearl",
            "keys": [{"address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1"}],
            "home_chain": "gnosis",
            "chain_configs": {
                "gnosis": {
                    "ledger_config": {"chain": "gnosis"},
                    "chain_data": {
                        "multisig": "0xm",
                        "instances": [],
                        "token": 1,
                        "staked": False,
                        "on_chain_state": 3,
                        "user_params": {
                            "staking_program_id": "no_staking",
                            "nft": "QmXXX",
                            "cost_of_bond": 10000000000000000,
                            "fund_requirements": {
                                "0x0000000000000000000000000000000000000000": 10000000000000000
                            },
                        },
                    },
                }
            },
            "env_variables": {},
        }
        (service_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )

        mock_pkg = service_dir / "trader_pearl"
        mock_pkg.mkdir(exist_ok=True)

        with patch("operate.migration.IPFSTool") as mock_ipfs_cls:
            mock_ipfs_cls.return_value.download.return_value = str(mock_pkg)
            result = manager._migrate_service(  # pylint: disable=protected-access
                service_dir
            )

        assert result is True
        updated = json.loads((service_dir / "config.json").read_text(encoding="utf-8"))
        # multisig should have been replaced (no longer "0xm")
        assert updated["chain_configs"]["gnosis"]["chain_data"]["multisig"] != "0xm"

    def test_migrate_service_v8_replaces_0xm_and_migrates_keys(
        self, tmp_path: Path
    ) -> None:
        """Test v<8 migration replaces '0xm' multisig (line 355) and migrates keys (lines 358-359)."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        service_dir = tmp_path / f"{SERVICE_CONFIG_PREFIX}v7test"
        service_dir.mkdir()

        config_data = {
            "name": "Test Service",
            "version": 7,
            "hash": "bafybeiFakeHash",
            "package_path": "trader_pearl",
            "keys": [{"address": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}],
            "home_chain": "gnosis",
            "chain_configs": {
                "gnosis": {
                    "ledger_config": {"chain": "gnosis"},
                    "chain_data": {
                        "multisig": "0xm",
                        "instances": [],
                        "token": 1,
                        "staked": False,
                        "on_chain_state": 3,
                        "user_params": {
                            "staking_program_id": "no_staking",
                            "nft": "QmXXX",
                            "cost_of_bond": 10000000000000000,
                            "fund_requirements": {
                                "0x0000000000000000000000000000000000000000": 10000000000000000
                            },
                        },
                    },
                }
            },
            "env_variables": {},
        }
        (service_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )

        mock_pkg = service_dir / "trader_pearl"
        mock_pkg.mkdir(exist_ok=True)

        with patch("operate.migration.IPFSTool") as mock_ipfs_cls:
            mock_ipfs_cls.return_value.download.return_value = str(mock_pkg)
            result = manager._migrate_service(  # pylint: disable=protected-access
                service_dir
            )

        assert result is True
        updated = json.loads((service_dir / "config.json").read_text(encoding="utf-8"))
        # multisig "0xm" replaced (line 355)
        assert updated["chain_configs"]["gnosis"]["chain_data"]["multisig"] != "0xm"
        # keys migrated to agent_addresses (lines 358-359)
        assert "agent_addresses" in updated
        assert "keys" not in updated

    def test_migrate_service_service_path_in_final_cleanup_and_rmtree(
        self, tmp_path: Path
    ) -> None:
        """Test final cleanup uses service_path (lines 410-411) and removes existing pkg dir (line 416)."""
        manager = MigrationManager(home=tmp_path, logger=MagicMock())

        service_dir = tmp_path / f"{SERVICE_CONFIG_PREFIX}v8sptest"
        service_dir.mkdir()

        config_data = {
            "name": "Test Service",
            "version": 8,
            "hash": "bafybeiFakeHash",
            "package_path": "trader_pearl",
            "service_path": "old/path/to/trader_pearl",
            "agent_addresses": ["0xcccccccccccccccccccccccccccccccccccccccc"],
            "home_chain": "gnosis",
            "chain_configs": {},
            "env_variables": {},
        }
        (service_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )

        # Create a pre-existing package dir to trigger shutil.rmtree (line 416)
        existing_pkg = service_dir / "trader_pearl"
        existing_pkg.mkdir()

        mock_new_pkg = service_dir / "trader_pearl_new"
        mock_new_pkg.mkdir()

        with patch("operate.migration.IPFSTool") as mock_ipfs_cls:
            mock_ipfs_cls.return_value.download.return_value = str(mock_new_pkg)
            result = manager._migrate_service(  # pylint: disable=protected-access
                service_dir
            )

        assert result is True
        # The old existing package dir should have been removed (line 416)
        assert not existing_pkg.exists()


class TestMigrateKeysIntegerLedger:
    """Tests for migrate_keys integer-ledger-type migration (lines 524-528)."""

    def test_migrate_keys_converts_integer_ledger_to_string(
        self, tmp_path: Path
    ) -> None:
        """Test migrate_keys converts integer ledger type (0→'ethereum') in old key files (lines 524-528)."""
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()

        # Create a key file with an integer ledger type (old format: 0 = ethereum)
        address = "0x" + "a" * 40
        key_data = {
            "ledger": 0,
            "address": address,
            "private_key": "0xdeadbeef",
        }
        (keys_dir / address).write_text(json.dumps(key_data), encoding="utf-8")

        mock_keys_manager = MagicMock()
        mock_keys_manager.path = keys_dir
        mock_keys_manager.password = None  # no encryption path

        manager = MigrationManager(home=tmp_path, logger=MagicMock())
        manager.migrate_keys(mock_keys_manager)

        updated = json.loads((keys_dir / address).read_text(encoding="utf-8"))
        assert updated["ledger"] == "ethereum"
