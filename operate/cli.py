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

"""Operate app CLI module."""
import asyncio
import atexit
import enum
import multiprocessing
import os
import shutil
import signal
import traceback
import typing as t
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from http import HTTPStatus
from pathlib import Path
from time import time
from types import FrameType

import autonomy.chain.tx
from aea.helpers.logging import setup_logger
from clea import group, params, run
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing_extensions import Annotated
from uvicorn.config import Config
from uvicorn.server import Server

from operate import __version__, services
from operate.account.user import UserAccount
from operate.bridge.bridge_manager import BridgeManager
from operate.constants import (
    AGENT_RUNNER_PREFIX,
    DEPLOYMENT_DIR,
    KEYS_DIR,
    MIN_PASSWORD_LENGTH,
    MSG_INVALID_MNEMONIC,
    MSG_INVALID_PASSWORD,
    MSG_NEW_PASSWORD_MISSING,
    MSG_SAFE_CREATED_TRANSFER_COMPLETED,
    MSG_SAFE_CREATED_TRANSFER_FAILED,
    MSG_SAFE_CREATION_FAILED,
    MSG_SAFE_EXISTS_AND_FUNDED,
    MSG_SAFE_EXISTS_TRANSFER_COMPLETED,
    MSG_SAFE_EXISTS_TRANSFER_FAILED,
    OPERATE,
    OPERATE_HOME,
    SERVICES_DIR,
    USER_JSON,
    VERSION_FILE,
    WALLETS_DIR,
    WALLET_RECOVERY_DIR,
    ZERO_ADDRESS,
)
from operate.keys import KeysManager
from operate.ledger.profiles import (
    DEFAULT_EOA_TOPUPS,
    DEFAULT_NEW_SAFE_FUNDS,
    ERC20_TOKENS,
)
from operate.migration import MigrationManager
from operate.operate_types import (
    Chain,
    ChainAmounts,
    DeploymentStatus,
    LedgerType,
    Version,
)
from operate.quickstart.analyse_logs import analyse_logs
from operate.quickstart.claim_staking_rewards import claim_staking_rewards
from operate.quickstart.reset_configs import reset_configs
from operate.quickstart.reset_password import reset_password
from operate.quickstart.reset_staking import reset_staking
from operate.quickstart.run_service import run_service
from operate.quickstart.stop_service import stop_service
from operate.quickstart.terminate_on_chain_service import terminate_service
from operate.services.deployment_runner import stop_deployment_manager
from operate.services.funding_manager import FundingInProgressError, FundingManager
from operate.services.health_checker import HealthChecker
from operate.settings import Settings
from operate.utils import subtract_dicts
from operate.utils.gnosis import gas_fees_spent_in_tx, get_assets_balances
from operate.utils.single_instance import AppSingleInstance, ParentWatchdog
from operate.wallet.master import InsufficientFundsException, MasterWalletManager
from operate.wallet.wallet_recovery_manager import (
    WalletRecoveryError,
    WalletRecoveryManager,
)


# TODO Backport to Open Autonomy
autonomy.chain.tx.ERRORS_TO_RETRY |= {"replacement transaction underpriced"}


DEFAULT_MAX_RETRIES = 3
USER_NOT_LOGGED_IN_ERROR = JSONResponse(
    content={"error": "User not logged in."}, status_code=HTTPStatus.UNAUTHORIZED
)
USER_LOGGED_IN_ERROR = JSONResponse(
    content={"error": "User must be logged out to perform this operation."},
    status_code=HTTPStatus.FORBIDDEN,
)
ACCOUNT_NOT_FOUND_ERROR = JSONResponse(
    content={"error": "User account not found."},
    status_code=HTTPStatus.NOT_FOUND,
)
TRY_TO_SHUTDOWN_PREVIOUS_INSTANCE = True

logger = setup_logger(name="operate")


def service_not_found_error(service_config_id: str) -> JSONResponse:
    """Service not found error response"""
    return JSONResponse(
        content={"error": f"Service {service_config_id} not found"},
        status_code=HTTPStatus.NOT_FOUND,
    )


class CreateSafeStatus(str, enum.Enum):
    """ProviderRequestStatus"""

    SAFE_CREATED_TRANSFER_COMPLETED = "SAFE_CREATED_TRANSFER_COMPLETED"
    SAFE_CREATED_TRANSFER_FAILED = "SAFE_CREATED_TRANSFER_FAILED"
    SAFE_EXISTS_TRANSFER_COMPLETED = "SAFE_EXISTS_TRANSFER_COMPLETED"
    SAFE_EXISTS_TRANSFER_FAILED = "SAFE_EXISTS_TRANSFER_FAILED"
    SAFE_CREATION_FAILED = "SAFE_CREATION_FAILED"
    SAFE_EXISTS_ALREADY_FUNDED = "SAFE_EXISTS_ALREADY_FUNDED"

    def __str__(self) -> str:
        """__str__"""
        return self.value


class OperateApp:  # pylint: disable=too-many-instance-attributes
    """Operate app."""

    def __init__(
        self,
        home: t.Optional[Path] = None,
    ) -> None:
        """Initialize object."""
        self._path = (home or OPERATE_HOME).resolve()
        self._services = self._path / SERVICES_DIR
        self._keys = self._path / KEYS_DIR
        self.setup()
        self._backup_operate_if_new_version()

        self._password: t.Optional[str] = os.environ.get("OPERATE_USER_PASSWORD")
        self._keys_manager: KeysManager = KeysManager(
            path=self._keys,
            logger=logger,
            password=self._password,
        )
        self.settings = Settings(path=self._path)

        self._wallet_manager = MasterWalletManager(
            path=self._path / WALLETS_DIR,
            password=self.password,
        )
        self._wallet_manager.setup()
        self._funding_manager = FundingManager(
            keys_manager=self._keys_manager,
            wallet_manager=self._wallet_manager,
            logger=logger,
        )

        self._migration_manager = MigrationManager(self._path, logger)
        self._migration_manager.migrate_user_account()
        self._migration_manager.migrate_services(self.service_manager())
        self._migration_manager.migrate_wallets(self.wallet_manager)
        self._migration_manager.migrate_qs_configs()

    @property
    def password(self) -> t.Optional[str]:
        """Get the password."""
        return self._password

    @password.setter
    def password(self, value: t.Optional[str]) -> None:
        """Set the password."""
        self._password = value
        self._keys_manager.password = value
        self._wallet_manager.password = value
        self._migration_manager.migrate_keys(self._keys_manager)

    def _backup_operate_if_new_version(self) -> None:
        """Backup .operate directory if this is a new version."""
        current_version = Version(__version__)
        backup_required = False
        version_file = self._path / VERSION_FILE
        if not version_file.exists():
            backup_required = True
            found_version = "0.10.21"  # first version with version file
        else:
            found_version = Version(version_file.read_text())
            if current_version.major > found_version.major or (
                current_version.major == found_version.major
                and current_version.minor > found_version.minor
            ):
                backup_required = True

        if not backup_required:
            return

        backup_path = self._path.parent / f"{OPERATE}_v{found_version}_bak"
        if backup_path.exists():
            logger.info(f"Backup directory {backup_path} already exists.")
            backup_path = (
                self._path.parent / f"{OPERATE}_v{found_version}_bak_{int(time())}"
            )

        logger.info(f"Backing up existing {OPERATE} directory to {backup_path}")
        shutil.copytree(self._path, backup_path, ignore_dangling_symlinks=True)
        version_file.write_text(str(current_version))

        # remove recoverable files from the backup to save space
        service_dir = backup_path / SERVICES_DIR
        for service_path in service_dir.iterdir():
            deployment_dir = service_path / DEPLOYMENT_DIR
            if deployment_dir.exists():
                shutil.rmtree(deployment_dir)

            for agent_runner_path in service_path.glob(f"{AGENT_RUNNER_PREFIX}*"):
                agent_runner_path.unlink()

        logger.info("Backup completed.")

    def create_user_account(self, password: str) -> UserAccount:
        """Create a user account."""
        self.password = password
        return UserAccount.new(
            password=password,
            path=self._path / USER_JSON,
        )

    def update_password(self, old_password: str, new_password: str) -> None:
        """Updates current password"""

        if not new_password:
            raise ValueError(MSG_NEW_PASSWORD_MISSING)

        if not (
            self.user_account.is_valid(old_password)
            and self.wallet_manager.is_password_valid(old_password)
        ):
            raise ValueError(MSG_INVALID_PASSWORD)

        wallet_manager = self.wallet_manager
        wallet_manager.password = old_password
        wallet_manager.update_password(new_password)
        self._keys_manager.update_password(new_password)
        self.user_account.update(old_password, new_password)

    def update_password_with_mnemonic(self, mnemonic: str, new_password: str) -> None:
        """Updates current password using the mnemonic"""

        if not new_password:
            raise ValueError(MSG_NEW_PASSWORD_MISSING)

        mnemonic = mnemonic.strip().lower()
        if not self.wallet_manager.is_mnemonic_valid(mnemonic):
            raise ValueError(MSG_INVALID_MNEMONIC)

        wallet_manager = self.wallet_manager
        wallet_manager.update_password_with_mnemonic(mnemonic, new_password)
        self.user_account.force_update(new_password)

    def service_manager(
        self, skip_dependency_check: t.Optional[bool] = False
    ) -> services.manage.ServiceManager:
        """Load service manager."""
        return services.manage.ServiceManager(
            path=self._services,
            keys_manager=self.keys_manager,
            wallet_manager=self.wallet_manager,
            funding_manager=self.funding_manager,
            logger=logger,
            skip_dependency_check=skip_dependency_check,
        )

    @property
    def funding_manager(self) -> FundingManager:
        """Load funding manager."""
        return self._funding_manager

    @property
    def user_account(self) -> t.Optional[UserAccount]:
        """Load user account."""
        if (self._path / USER_JSON).exists():
            return UserAccount.load(self._path / USER_JSON)
        return None

    @property
    def keys_manager(self) -> KeysManager:
        """Load keys manager."""
        return self._keys_manager

    @property
    def wallet_manager(self) -> MasterWalletManager:
        """Load wallet manager."""
        return self._wallet_manager

    @property
    def wallet_recovery_manager(self) -> WalletRecoveryManager:
        """Load wallet recovery manager."""
        manager = WalletRecoveryManager(
            path=self._path / WALLET_RECOVERY_DIR,
            wallet_manager=self.wallet_manager,
            service_manager=self.service_manager(),
            logger=logger,
        )
        return manager

    @property
    def bridge_manager(self) -> BridgeManager:
        """Load bridge manager."""
        manager = BridgeManager(
            path=self._path / "bridge",
            wallet_manager=self.wallet_manager,
            logger=logger,
        )
        return manager

    def setup(self) -> None:
        """Make the root directory."""
        self._path.mkdir(exist_ok=True)
        self._services.mkdir(exist_ok=True)
        self._keys.mkdir(exist_ok=True)

    @property
    def json(self) -> dict:
        """Json representation of the app."""
        return {
            "name": "Operate HTTP server",
            "version": (__version__),
            "home": str(self._path),
        }


def create_app(  # pylint: disable=too-many-locals, unused-argument, too-many-statements
    home: t.Optional[Path] = None,
) -> FastAPI:
    """Create FastAPI object."""
    HEALTH_CHECKER_OFF = os.environ.get("HEALTH_CHECKER_OFF", "0") == "1"
    number_of_fails = int(
        os.environ.get(
            "HEALTH_CHECKER_TRIES", str(HealthChecker.NUMBER_OF_FAILS_DEFAULT)
        )
    )

    if HEALTH_CHECKER_OFF:
        logger.warning("Healthchecker is off!!!")
    operate = OperateApp(home=home)

    funding_job: t.Optional[asyncio.Task] = None
    health_checker = HealthChecker(
        operate.service_manager(), number_of_fails=number_of_fails, logger=logger
    )
    # Create shutdown endpoint
    shutdown_endpoint = uuid.uuid4().hex
    (operate._path / "operate.kill").write_text(  # pylint: disable=protected-access
        shutdown_endpoint
    )
    thread_pool_executor = ThreadPoolExecutor(max_workers=12)

    async def run_in_executor(fn: t.Callable, *args: t.Any) -> t.Any:
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(thread_pool_executor, fn, *args)
        res = await future
        exception = future.exception()
        if exception is not None:
            raise exception
        return res

    def schedule_healthcheck_job(
        service_config_id: str,
    ) -> None:
        """Schedule a healthcheck job."""
        if not HEALTH_CHECKER_OFF:
            # dont start health checker if it's switched off
            health_checker.start_for_service(service_config_id)

    def schedule_funding_job() -> None:
        """Schedule the funding job."""
        cancel_funding_job()  # cancel previous job if any
        logger.info("Starting the funding job")

        loop = asyncio.get_event_loop()
        nonlocal funding_job
        funding_job = loop.create_task(
            operate.funding_manager.funding_job(
                service_manager=operate.service_manager(),
                loop=loop,
            )
        )

    def cancel_funding_job() -> None:
        """Cancel funding job."""
        nonlocal funding_job
        if funding_job is None:
            return

        status = funding_job.cancel()
        if status:
            funding_job = None
        else:
            logger.info("Funding job cancellation failed")

    def pause_all_services_on_startup() -> None:
        logger.info("Stopping services on startup...")
        pause_all_services()
        logger.info("Stopping services on startup done.")

    def pause_all_services() -> None:
        service_manager = operate.service_manager()
        if not service_manager.validate_services():
            logger.error(
                "Some services are not valid. Only pausing the valid services."
            )

        service_config_ids = [
            i["service_config_id"] for i in operate.service_manager().json
        ]

        for service_config_id in service_config_ids:
            logger.info(f"Stopping service {service_config_id=}")
            if not operate.service_manager().exists(
                service_config_id=service_config_id
            ):
                continue
            deployment = (
                operate.service_manager()
                .load(service_config_id=service_config_id)
                .deployment
            )
            if deployment.status == DeploymentStatus.DELETED:
                continue
            logger.info(f"stopping service {service_config_id}")
            try:
                deployment.stop(force=True)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    f"Deployment {service_config_id} stopping failed. but continue"
                )
            logger.info(f"Cancelling funding job for {service_config_id}")
            health_checker.stop_for_service(service_config_id=service_config_id)

    def pause_all_services_on_exit(signum: int, frame: t.Optional[FrameType]) -> None:
        logger.info("Stopping services on exit...")
        pause_all_services()
        logger.info("Stopping services on exit done.")

    signal.signal(signal.SIGINT, pause_all_services_on_exit)
    signal.signal(signal.SIGTERM, pause_all_services_on_exit)

    # on backend app started we assume there are now started agents, so we force to pause all
    pause_all_services_on_startup()

    # stop all services at  middleware exit
    atexit.register(pause_all_services)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def stop_app():
            logger.info("Stopping services due to parent death...")
            stop_deployment_manager()
            await run_in_executor(pause_all_services)
            app._server.should_exit = True  # pylint: disable=protected-access
            logger.info("App stopped due to parent death.")

        watchdog = ParentWatchdog(on_parent_exit=stop_app)
        watchdog.start()

        yield  # --- app is running ---

        with suppress(Exception):
            cancel_funding_job()

        with suppress(Exception):
            await watchdog.stop()

    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )

    @app.middleware("http")
    async def handle_internal_server_error(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Error {str(e)}\n{traceback.format_exc()}")
            return JSONResponse(
                content={"error": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return response

    @app.get(f"/{shutdown_endpoint}")
    async def _kill_server(request: Request) -> JSONResponse:
        """Kill backend server from inside."""
        os.kill(os.getpid(), signal.SIGINT)
        return JSONResponse(content={})

    @app.get("/shutdown")
    async def _shutdown(request: Request) -> JSONResponse:
        """Kill backend server from inside."""
        logger.info("Stopping services on demand...")
        await run_in_executor(pause_all_services)
        logger.info("Stopping services on demand done.")
        app._server.should_exit = True  # pylint: disable=protected-access
        await asyncio.sleep(0.3)
        return JSONResponse(content={"stopped": True})

    @app.get("/api")
    async def _get_api(request: Request) -> JSONResponse:
        """Get API info."""
        return JSONResponse(content=operate.json)

    @app.get("/api/settings")
    async def _get_settings(request: Request) -> JSONResponse:
        """Get settings."""
        return JSONResponse(content=operate.settings.json)

    @app.get("/api/account")
    async def _get_account(request: Request) -> t.Dict:
        """Get account information."""
        return {"is_setup": operate.user_account is not None}

    @app.post("/api/account")
    async def _setup_account(request: Request) -> t.Dict:
        """Setup account."""
        if operate.user_account is not None:
            return JSONResponse(
                content={"error": "Account already exists."},
                status_code=HTTPStatus.CONFLICT,
            )

        password = (await request.json()).get("password")
        if not password or len(password) < MIN_PASSWORD_LENGTH:
            return JSONResponse(
                content={
                    "error": f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        operate.create_user_account(password=password)
        return JSONResponse(content={"error": None})

    @app.put("/api/account")
    async def _update_password(  # pylint: disable=too-many-return-statements
        request: Request,
    ) -> t.Dict:
        """Update password."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        data = await request.json()
        old_password = data.get("old_password")
        new_password = data.get("new_password")
        mnemonic = data.get("mnemonic")

        if not old_password and not mnemonic:
            return JSONResponse(
                content={
                    "error": "Exactly one of 'old_password' or 'mnemonic' (seed phrase) is required.",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        if old_password and mnemonic:
            return JSONResponse(
                content={
                    "error": "Exactly one of 'old_password' or 'mnemonic' (seed phrase) is required.",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        if not new_password or len(new_password) < MIN_PASSWORD_LENGTH:
            return JSONResponse(
                content={
                    "error": f"New password must be at least {MIN_PASSWORD_LENGTH} characters long."
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            if old_password:
                operate.update_password(old_password, new_password)
                return JSONResponse(
                    content={"error": None, "message": "Password updated successfully."}
                )
            if mnemonic:
                operate.update_password_with_mnemonic(mnemonic, new_password)
                return JSONResponse(
                    content={
                        "error": None,
                        "message": "Password updated successfully using seed phrase.",
                    }
                )

            return JSONResponse(
                content={"error": "Password update failed."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except ValueError as e:
            logger.error(f"Password update error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={"error": f"Failed to update password: {str(e)}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Password update error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={"error": "Failed to update password. Please check the logs."},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.post("/api/account/login")
    async def _validate_password(request: Request) -> t.Dict:
        """Validate password."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        data = await request.json()
        if not operate.user_account.is_valid(password=data["password"]):
            return JSONResponse(
                content={"error": MSG_INVALID_PASSWORD},
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        operate.password = data["password"]
        schedule_funding_job()
        return JSONResponse(
            content={"message": "Login successful."},
            status_code=HTTPStatus.OK,
        )

    @app.get("/api/wallet")
    async def _get_wallets(request: Request) -> t.List[t.Dict]:
        """Get wallets."""
        wallets = []
        for wallet in operate.wallet_manager:
            wallets.append(wallet.json)
        return JSONResponse(content=wallets)

    @app.post("/api/wallet")
    async def _create_wallet(request: Request) -> t.List[t.Dict]:
        """Create wallet"""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        data = await request.json()
        ledger_type = LedgerType(data["ledger_type"])
        manager = operate.wallet_manager
        if manager.exists(ledger_type=ledger_type):
            return JSONResponse(
                content={
                    "wallet": manager.load(ledger_type=ledger_type).json,
                    "mnemonic": None,
                }
            )
        wallet, mnemonic = manager.create(ledger_type=ledger_type)
        return JSONResponse(content={"wallet": wallet.json, "mnemonic": mnemonic})

    @app.post("/api/wallet/private_key")
    async def _get_private_key(request: Request) -> t.List[t.Dict]:
        """Get Master EOA private key."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        data = await request.json()
        password = data.get("password")
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR
        if operate.password != password:
            return JSONResponse(
                content={"error": MSG_INVALID_PASSWORD},
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        # TODO Should fail if not provided
        ledger_type = data.get("ledger_type", LedgerType.ETHEREUM.value)
        wallet = operate.wallet_manager.load(ledger_type=LedgerType(ledger_type))
        return JSONResponse(content={"private_key": wallet.crypto.private_key})

    @app.post("/api/wallet/mnemonic")
    async def _get_mnemonic(request: Request) -> t.List[t.Dict]:
        """Get Master EOA mnemonic."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        data = await request.json()
        password = data.get("password")
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR
        if operate.password != password:
            return JSONResponse(
                content={"error": "Password is not valid."},
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        try:
            ledger_type = LedgerType(data.get("ledger_type"))
            wallet = operate.wallet_manager.load(ledger_type=ledger_type)
            mnemonic = wallet.decrypt_mnemonic(password=password)
            if mnemonic is None:
                return JSONResponse(
                    content={"error": "Mnemonic file does not exist."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            return JSONResponse(content={"mnemonic": mnemonic})
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Failed to retrieve mnemonic: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={
                    "error": "Failed to retrieve mnemonic. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.get("/api/wallet/extended")
    async def _get_wallet_safe(request: Request) -> t.List[t.Dict]:
        """Get wallets."""
        wallets = []
        for wallet in operate.wallet_manager:
            wallets.append(wallet.extended_json)
        return JSONResponse(content=wallets)

    @app.get("/api/wallet/safe")
    async def _get_safes(request: Request) -> t.List[t.Dict]:
        """Create wallet safe"""
        all_safes = []
        for wallet in operate.wallet_manager:
            safes = []
            if wallet.safes is not None:
                safes = list(wallet.safes.values())
            all_safes.append({wallet.ledger_type: safes})
        return JSONResponse(content=all_safes)

    @app.get("/api/wallet/safe/{chain}")
    async def _get_safe(request: Request) -> t.List[t.Dict]:
        """Get safe address"""
        chain = Chain.from_string(request.path_params["chain"])
        ledger_type = chain.ledger_type
        manager = operate.wallet_manager
        if not manager.exists(ledger_type=ledger_type):
            return JSONResponse(
                content={"error": "No Master EOA found for this chain."},
                status_code=HTTPStatus.NOT_FOUND,
            )
        safes = manager.load(ledger_type=ledger_type).safes
        if safes is None or safes.get(chain) is None:
            return JSONResponse(
                content={"error": "No Master Safe found for this chain."},
                status_code=HTTPStatus.NOT_FOUND,
            )

        return JSONResponse(
            content={
                "safe": safes[chain],
            },
        )

    @app.post("/api/wallet/safe")
    async def _create_safe(  # pylint: disable=too-many-return-statements
        request: Request,
    ) -> t.List[t.Dict]:
        """Create wallet safe"""

        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        data = await request.json()

        if "initial_funds" in data and "transfer_excess_assets" in data:
            return JSONResponse(
                content={
                    "error": "Only specify one of 'initial_funds' or 'transfer_excess_assets', but not both."
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        logger.info(f"POST /api/wallet/safe {data=}")

        chain = Chain(data["chain"])
        ledger_type = chain.ledger_type
        manager = operate.wallet_manager
        if not manager.exists(ledger_type=ledger_type):
            return JSONResponse(
                content={"error": "No Master EOA found for this chain."},
                status_code=HTTPStatus.NOT_FOUND,
            )

        wallet = manager.load(ledger_type=ledger_type)
        ledger_api = wallet.ledger_api(chain=chain)

        # 1. Ensure Safe exists (create if missing)
        safe_address = None
        create_tx = None

        if wallet.safes is None or chain not in wallet.safes:
            backup_owner = data.get("backup_owner")
            if backup_owner:
                backup_owner = ledger_api.api.to_checksum_address(backup_owner)

            try:
                create_tx = wallet.create_safe(
                    chain=chain,
                    backup_owner=backup_owner,
                )
                # After creation the safe should be in wallet.safes
                wallet = manager.load(ledger_type=ledger_type)  # reload
                safe_address = wallet.safes[chain]
            except Exception as e:  # pylint: disable=broad-except
                logger.error(f"Safe creation failed: {e}\n{traceback.format_exc()}")
                return JSONResponse(
                    content={
                        "status": CreateSafeStatus.SAFE_CREATION_FAILED,
                        "safe": None,
                        "create_tx": None,
                        "transfer_txs": {},
                        "transfer_errors": {},
                        "message": MSG_SAFE_CREATION_FAILED,
                    },
                    status_code=HTTPStatus.OK,
                )
        else:
            safe_address = wallet.safes[chain]
            logger.info(f"Safe already exists: {safe_address}")

        # 2. Determine what should be transferred
        # A default nonzero balance might be required on the Safe after creation.
        # This is possibly required to estimate gas in protocol transactions.
        transfer_excess_assets = (
            str(data.get("transfer_excess_assets", "false")).lower() == "true"
        )

        if transfer_excess_assets:
            asset_addresses = {ZERO_ADDRESS} | {
                token[chain] for token in ERC20_TOKENS.values() if chain in token
            }
            master_eoa_balances = get_assets_balances(
                ledger_api=ledger_api,
                addresses={wallet.address},
                asset_addresses=asset_addresses,
                raise_on_invalid_address=False,
            )[wallet.address]
            initial_funds = subtract_dicts(
                master_eoa_balances, DEFAULT_EOA_TOPUPS[chain]
            )
        else:
            initial_funds = data.get("initial_funds", DEFAULT_NEW_SAFE_FUNDS[chain])
            safe_balances = get_assets_balances(
                ledger_api=ledger_api,
                addresses={safe_address},
                asset_addresses=set(initial_funds.keys()) | {ZERO_ADDRESS},
                raise_on_invalid_address=False,
            )[safe_address]
            initial_funds = subtract_dicts(initial_funds, safe_balances)

        logger.info(f"_create_safe Computed {initial_funds=}")

        transfer_txs = {}
        transfer_errors = {}
        for asset, amount in initial_funds.items():
            try:
                if amount <= 0:
                    continue

                logger.info(
                    f"_create_safe Transfer to={safe_address} {amount=} {chain} {asset=}"
                )
                tx_hash = wallet.transfer(
                    to=safe_address,
                    amount=int(amount),
                    chain=chain,
                    asset=asset,
                    from_safe=False,
                )
                transfer_txs[asset] = tx_hash
            except Exception as e:  # pylint: disable=broad-except
                logger.error(f"Safe funding failed: {e}\n{traceback.format_exc()}")
                transfer_errors[asset] = str(e)

        if create_tx:
            if transfer_errors:
                status = CreateSafeStatus.SAFE_CREATED_TRANSFER_FAILED
                message = MSG_SAFE_CREATED_TRANSFER_FAILED
            else:  # If there are no transfer_txs, it means the Safe is sufficiently funded.
                status = CreateSafeStatus.SAFE_CREATED_TRANSFER_COMPLETED
                message = MSG_SAFE_CREATED_TRANSFER_COMPLETED
        elif transfer_txs:
            if transfer_errors:
                status = CreateSafeStatus.SAFE_EXISTS_TRANSFER_FAILED
                message = MSG_SAFE_EXISTS_TRANSFER_FAILED
            else:
                status = CreateSafeStatus.SAFE_EXISTS_TRANSFER_COMPLETED
                message = MSG_SAFE_EXISTS_TRANSFER_COMPLETED
        else:  # No create_tx and no transfer_txs means the Safe already exists and is sufficiently funded.
            status = CreateSafeStatus.SAFE_EXISTS_ALREADY_FUNDED
            message = MSG_SAFE_EXISTS_AND_FUNDED

        return JSONResponse(
            content={
                "status": status,
                "safe": safe_address,
                "create_tx": create_tx,
                "transfer_txs": transfer_txs,
                "transfer_errors": transfer_errors,
                "message": message,
            },
            status_code=HTTPStatus.OK,
        )

    @app.put("/api/wallet/safe")
    async def _update_safe(request: Request) -> t.List[t.Dict]:
        """Update wallet safe"""
        # TODO: Extract login check as decorator
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        data = await request.json()

        if "chain" not in data:
            return JSONResponse(
                content={"error": "'chain' is required."},
                status_code=HTTPStatus.BAD_REQUEST,
            )

        chain = Chain(data["chain"])
        ledger_type = chain.ledger_type
        manager = operate.wallet_manager
        if not manager.exists(ledger_type=ledger_type):
            return JSONResponse(
                content={"error": "No Master EOA found for this chain."},
                status_code=HTTPStatus.BAD_REQUEST,
            )

        wallet = manager.load(ledger_type=ledger_type)
        ledger_api = wallet.ledger_api(chain=chain)

        backup_owner = data.get("backup_owner")
        if backup_owner:
            backup_owner = ledger_api.api.to_checksum_address(backup_owner)

        backup_owner_updated = wallet.update_backup_owner(
            chain=chain,
            backup_owner=backup_owner,
        )
        message = (
            "Backup owner updated successfully"
            if backup_owner_updated
            else "Backup owner is already set to this address"
        )
        return JSONResponse(
            content={
                "wallet": wallet.json,
                "chain": chain.value,
                "backup_owner_updated": backup_owner_updated,
                "message": message,
            }
        )

    @app.post("/api/wallet/withdraw")
    async def _wallet_withdraw(request: Request) -> JSONResponse:
        """Withdraw from Master Safe / master eoa"""

        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        data = await request.json()
        if not operate.user_account.is_valid(password=data["password"]):
            return JSONResponse(
                content={"error": MSG_INVALID_PASSWORD},
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        try:
            withdraw_assets = data.get("withdraw_assets", {})
            to = data["to"]
            wallet_manager = operate.wallet_manager
            transfer_txs: t.Dict[str, t.Dict[str, t.List[str]]] = {}

            # TODO: Ensure master wallet has enough funding.
            for chain_str, tokens in withdraw_assets.items():
                chain = Chain(chain_str)
                wallet = wallet_manager.load(chain.ledger_type)
                transfer_txs[chain_str] = {}

                # Process ERC20 first
                gas_fee_spent = 0
                for asset, amount in tokens.items():
                    if asset != ZERO_ADDRESS:
                        txs = wallet.transfer_from_safe_then_eoa(
                            to=to,
                            amount=int(amount),
                            chain=chain,
                            asset=asset,
                        )
                        transfer_txs[chain_str][asset] = txs
                        for tx in txs:
                            gas_fee_spent += gas_fees_spent_in_tx(
                                ledger_api=wallet.ledger_api(chain=chain),
                                tx_hash=tx,
                            )

                # Process native last
                if ZERO_ADDRESS in tokens:
                    asset = ZERO_ADDRESS
                    amount = int(tokens[asset]) - gas_fee_spent
                    txs = wallet.transfer_from_safe_then_eoa(
                        to=to,
                        amount=int(amount),
                        chain=chain,
                        asset=asset,
                    )
                    transfer_txs[chain_str][asset] = txs

        except InsufficientFundsException as e:
            logger.error(f"Insufficient funds: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={
                    "error": f"Failed to withdraw funds. Insufficient funds: {e}",
                    "transfer_txs": transfer_txs,
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Failed to withdraw funds: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content={
                    "error": "Failed to withdraw funds. Please check the logs.",
                    "transfer_txs": transfer_txs,
                },
            )

        return JSONResponse(
            content={
                "error": None,
                "message": "Funds withdrawn successfully.",
                "transfer_txs": transfer_txs,
            }
        )

    @app.get("/api/v2/services")
    async def _get_services(request: Request) -> JSONResponse:
        """Get all services."""
        return JSONResponse(content=operate.service_manager().json)

    @app.get("/api/v2/services/validate")
    async def _validate_services(request: Request) -> JSONResponse:
        """Validate all services."""
        service_manager = operate.service_manager()
        service_ids = service_manager.get_all_service_ids()
        _services = [
            service.service_config_id
            for service in service_manager.get_all_services()[0]
        ]

        return JSONResponse(
            content={service_id: service_id in _services for service_id in service_ids}
        )

    @app.get("/api/v2/services/deployment")
    async def _get_services_deployment(request: Request) -> JSONResponse:
        """Get a service deployment."""
        service_manager = operate.service_manager()
        output = {}
        for service in service_manager.get_all_services()[0]:
            deployment_json = service.deployment.json
            deployment_json["healthcheck"] = service.get_latest_healthcheck()
            output[service.service_config_id] = deployment_json

        return JSONResponse(content=output)

    @app.get("/api/v2/service/{service_config_id}")
    async def _get_service(request: Request) -> JSONResponse:
        """Get a service."""
        service_config_id = request.path_params["service_config_id"]

        if not operate.service_manager().exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)
        return JSONResponse(
            content=(
                operate.service_manager()
                .load(
                    service_config_id=service_config_id,
                )
                .json
            )
        )

    @app.get("/api/v2/service/{service_config_id}/deployment")
    async def _get_service_deployment(request: Request) -> JSONResponse:
        """Get a service deployment."""
        service_config_id = request.path_params["service_config_id"]

        if not operate.service_manager().exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        service = operate.service_manager().load(service_config_id=service_config_id)
        deployment_json = service.deployment.json
        deployment_json["healthcheck"] = service.get_latest_healthcheck()
        return JSONResponse(content=deployment_json)

    @app.get("/api/v2/service/{service_config_id}/achievements")
    async def _get_service_achievements(
        request: Request, include_acknowledged: bool = Query(False)  # noqa: B008
    ) -> JSONResponse:
        """Get the service achievements."""
        service_config_id = request.path_params["service_config_id"]

        if not operate.service_manager().exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        service = operate.service_manager().load(service_config_id=service_config_id)

        achievements_json = service.get_achievements_notifications(
            include_acknowledged=include_acknowledged,
        )

        return JSONResponse(content=achievements_json)

    @app.post(
        "/api/v2/service/{service_config_id}/achievement/{achievement_id}/acknowledge"
    )
    async def _acknowledge_achievement(request: Request) -> JSONResponse:
        """Update a service."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        service_config_id = request.path_params["service_config_id"]
        manager = operate.service_manager()

        if not manager.exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        service = operate.service_manager().load(service_config_id=service_config_id)

        achievement_id = request.path_params["achievement_id"]

        try:
            service.acknowledge_achievement(
                achievement_id=achievement_id,
            )
        except KeyError:
            return JSONResponse(
                content={
                    "error": f"Achievement {achievement_id} does not exist for service {service_config_id}."
                },
                status_code=HTTPStatus.NOT_FOUND,
            )
        except ValueError:
            return JSONResponse(
                content={
                    "error": f"Achievement {achievement_id} was already acknowledged for service {service_config_id}."
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        return JSONResponse(
            content={
                "error": None,
                "message": f"Acknowledged achievement_id {achievement_id} for service {service_config_id} successfully.",
            }
        )

    @app.get("/api/v2/service/{service_config_id}/agent_performance")
    async def _get_agent_performance(request: Request) -> JSONResponse:
        """Get the service refill requirements."""
        service_config_id = request.path_params["service_config_id"]

        if not operate.service_manager().exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        return JSONResponse(
            content=operate.service_manager()
            .load(service_config_id=service_config_id)
            .get_agent_performance()
        )

    @app.get("/api/v2/service/{service_config_id}/funding_requirements")
    async def _get_funding_requirements(request: Request) -> JSONResponse:
        """Get the service refill requirements."""
        service_config_id = request.path_params["service_config_id"]

        if not operate.service_manager().exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        return JSONResponse(
            content=operate.service_manager().funding_requirements(
                service_config_id=service_config_id
            )
        )

    # TODO deprecate
    @app.get("/api/v2/service/{service_config_id}/refill_requirements")
    async def _get_refill_requirements(request: Request) -> JSONResponse:
        """Get the service refill requirements."""
        service_config_id = request.path_params["service_config_id"]

        if not operate.service_manager().exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        return JSONResponse(
            content=operate.service_manager().refill_requirements(
                service_config_id=service_config_id
            )
        )

    @app.post("/api/v2/service")
    async def _create_services_v2(request: Request) -> JSONResponse:
        """Create a service."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR
        template = await request.json()
        manager = operate.service_manager()
        output = manager.create(service_template=template)

        return JSONResponse(content=output.json)

    @app.post("/api/v2/service/{service_config_id}")
    async def _deploy_and_run_service(request: Request) -> JSONResponse:
        """Deploy a service."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        pause_all_services()
        service_config_id = request.path_params["service_config_id"]
        manager = operate.service_manager()

        if not manager.exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        def _fn() -> None:
            # deploy_service_onchain_from_safe includes stake_service_on_chain_from_safe
            manager.deploy_service_onchain_from_safe(
                service_config_id=service_config_id
            )
            manager.deploy_service_locally(service_config_id=service_config_id)

        await run_in_executor(_fn)
        schedule_healthcheck_job(service_config_id=service_config_id)

        return JSONResponse(
            content=(
                operate.service_manager().load(service_config_id=service_config_id).json
            )
        )

    @app.put("/api/v2/service/{service_config_id}")
    @app.patch("/api/v2/service/{service_config_id}")
    async def _update_service(request: Request) -> JSONResponse:
        """Update a service."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        service_config_id = request.path_params["service_config_id"]
        manager = operate.service_manager()

        if not manager.exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        template = await request.json()
        allow_different_service_public_id = template.get(
            "allow_different_service_public_id", False
        )

        if request.method == "PUT":
            partial_update = False
        else:
            partial_update = True

        logger.info(
            f"_update_service {partial_update=} {allow_different_service_public_id=}"
        )

        output = manager.update(
            service_config_id=service_config_id,
            service_template=template,
            allow_different_service_public_id=allow_different_service_public_id,
            partial_update=partial_update,
        )

        return JSONResponse(content=output.json)

    @app.post("/api/v2/service/{service_config_id}/deployment/stop")
    async def _stop_service_locally(request: Request) -> JSONResponse:
        """Stop a service deployment."""

        # No authentication required to stop services.

        service_config_id = request.path_params["service_config_id"]
        manager = operate.service_manager()

        if not manager.exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        service = operate.service_manager().load(service_config_id=service_config_id)
        service.remove_latest_healthcheck()
        deployment = service.deployment
        health_checker.stop_for_service(service_config_id=service_config_id)

        await run_in_executor(deployment.stop)
        logger.info(f"Cancelling funding job for {service_config_id}")
        return JSONResponse(content=deployment.json)

    # TODO Deprecate
    @app.post("/api/v2/service/{service_config_id}/onchain/withdraw")
    async def _withdraw_onchain(request: Request) -> JSONResponse:
        """Withdraw all the funds from a service."""

        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        service_config_id = request.path_params["service_config_id"]
        service_manager = operate.service_manager()

        if not service_manager.exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        withdrawal_address = (await request.json()).get("withdrawal_address")
        if withdrawal_address is None:
            return JSONResponse(
                content={"error": "'withdrawal_address' is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            pause_all_services()
            service = service_manager.load(service_config_id=service_config_id)

            # terminate the service on chain
            for chain, chain_config in service.chain_configs.items():
                service_manager.terminate_service_on_chain_from_safe(
                    service_config_id=service_config_id,
                    chain=chain,
                )
                service_manager.drain(
                    service_config_id=service_config_id,
                    chain_str=chain,
                    withdrawal_address=withdrawal_address,
                )

                # drain the Master Safe and master signer for the home chain
                chain = Chain(service.home_chain)
                master_wallet = service_manager.wallet_manager.load(
                    ledger_type=chain.ledger_type
                )

                # drain the Master Safe
                logger.info(
                    f"Draining the Master Safe {master_wallet.safes[chain]} on chain {chain.value} (withdrawal address {withdrawal_address})."
                )
                master_wallet.drain(
                    withdrawal_address=withdrawal_address,
                    chain=chain,
                    from_safe=True,
                    rpc=chain_config.ledger_config.rpc,
                )

                # drain the master signer
                logger.info(
                    f"Draining the Master Signer {master_wallet.address} on chain {chain.value} (withdrawal address {withdrawal_address})."
                )
                master_wallet.drain(
                    withdrawal_address=withdrawal_address,
                    chain=chain,
                    from_safe=False,
                    rpc=chain_config.ledger_config.rpc,
                )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Withdrawal failed: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content={"error": "Failed to withdraw funds. Please check the logs."},
            )

        return JSONResponse(content={"error": None, "message": "Withdrawal successful"})

    @app.post("/api/v2/service/{service_config_id}/terminate_and_withdraw")
    async def _terminate_and_withdraw(request: Request) -> JSONResponse:
        """Terminate the service and withdraw all the funds to Master Safe"""

        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        service_config_id = request.path_params["service_config_id"]
        service_manager = operate.service_manager()
        wallet_manager = operate.wallet_manager

        if not service_manager.exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        try:
            pause_all_services()
            service = service_manager.load(service_config_id=service_config_id)
            for chain in service.chain_configs:
                wallet = wallet_manager.load(Chain(chain).ledger_type)
                master_safe = wallet.safes[Chain(chain)]
                service_manager.terminate_service_on_chain_from_safe(
                    service_config_id=service_config_id,
                    chain=chain,
                )
                service_manager.drain(
                    service_config_id=service_config_id,
                    chain_str=chain,
                    withdrawal_address=master_safe,
                )

        except InsufficientFundsException as e:
            logger.error(
                f"Failed to terminate service and withdraw funds. Insufficient funds: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                content={
                    "error": f"Failed to terminate service and withdraw funds. Insufficient funds: {e}"
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                f"Terminate service and withdraw funds failed: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content={
                    "error": "Failed to terminate service and withdraw funds. Please check the logs."
                },
            )

        return JSONResponse(
            content={
                "error": None,
                "message": "Terminate service and withdraw funds successful",
            }
        )

    @app.post("/api/v2/service/{service_config_id}/fund")
    async def fund_service(  # pylint: disable=too-many-return-statements
        request: Request,
    ) -> JSONResponse:
        """Fund agent or service safe via Master Safe"""

        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        service_config_id = request.path_params["service_config_id"]
        service_manager = operate.service_manager()

        if not service_manager.exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        try:
            data = await request.json()
            service_manager.fund_service(
                service_config_id=service_config_id,
                amounts=ChainAmounts(
                    {
                        chain_str: {
                            address: {
                                asset: int(amount) for asset, amount in assets.items()
                            }
                            for address, assets in addresses.items()
                        }
                        for chain_str, addresses in data.items()
                    }
                ),
            )
        except ValueError as e:
            logger.error(
                f"Failed to fund from Master Safe: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                content={"error": str(e)},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except InsufficientFundsException as e:
            logger.error(
                f"Failed to fund from Master Safe. Insufficient funds: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                content={
                    "error": f"Failed to fund from Master Safe. Insufficient funds: {e}"
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except FundingInProgressError as e:
            logger.error(
                f"Failed to fund from Master Safe: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                content={"error": str(e)},
                status_code=HTTPStatus.CONFLICT,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                f"Failed to fund from Master Safe: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content={
                    "error": "Failed to fund from Master Safe. Please check the logs."
                },
            )

        return JSONResponse(
            content={"error": None, "message": "Funded from Master Safe successfully"}
        )

    @app.post("/api/bridge/bridge_refill_requirements")
    async def _bridge_refill_requirements(request: Request) -> JSONResponse:
        """Get the bridge refill requirements."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        try:
            data = await request.json()
            output = operate.bridge_manager.bridge_refill_requirements(
                requests_params=data["bridge_requests"],
                force_update=data.get("force_update", False),
            )

            return JSONResponse(
                content=output,
                status_code=HTTPStatus.OK,
            )
        except ValueError as e:
            logger.error(f"Bridge refill requirements error: {e}")
            return JSONResponse(
                content={"error": "Invalid bridge request parameters."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                f"Bridge refill requirements error: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                content={
                    "error": "Failed to get bridge requirements. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.post("/api/bridge/execute")
    async def _bridge_execute(request: Request) -> JSONResponse:
        """Execute bridge transaction."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        try:
            data = await request.json()
            output = operate.bridge_manager.execute_bundle(bundle_id=data["id"])

            return JSONResponse(
                content=output,
                status_code=HTTPStatus.OK,
            )
        except ValueError as e:
            logger.error(f"Bridge execute error: {e}")
            return JSONResponse(
                content={"error": "Invalid bundle ID or transaction failed."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Bridge execute error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={
                    "error": "Failed to execute bridge transaction. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.get("/api/bridge/last_executed_bundle_id")
    async def _bridge_last_executed_bundle_id(request: Request) -> t.List[t.Dict]:
        """Get last executed bundle id."""
        content = {"id": operate.bridge_manager.last_executed_bundle_id()}
        return JSONResponse(content=content, status_code=HTTPStatus.OK)

    @app.get("/api/bridge/status/{id}")
    async def _bridge_status(request: Request) -> JSONResponse:
        """Get bridge transaction status."""

        quote_bundle_id = request.path_params["id"]

        try:
            output = operate.bridge_manager.get_status_json(bundle_id=quote_bundle_id)

            return JSONResponse(
                content=output,
                status_code=HTTPStatus.OK,
            )
        except ValueError as e:
            logger.error(f"Bridge status error: {e}")
            return JSONResponse(
                content={"error": "Invalid bundle ID."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Bridge status error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={
                    "error": "Failed to get bridge status. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.post("/api/wallet/recovery/prepare")
    async def _wallet_recovery_prepare(request: Request) -> JSONResponse:
        """Prepare wallet recovery."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        if operate.password:
            return USER_LOGGED_IN_ERROR

        data = await request.json()
        new_password = data.get("new_password")

        if not new_password or len(new_password) < MIN_PASSWORD_LENGTH:
            return JSONResponse(
                content={
                    "error": f"New password must be at least {MIN_PASSWORD_LENGTH} characters long."
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            output = operate.wallet_recovery_manager.prepare_recovery(
                new_password=new_password
            )
            return JSONResponse(
                content=output,
                status_code=HTTPStatus.OK,
            )
        except (ValueError, WalletRecoveryError) as e:
            logger.error(f"_recovery_prepare error: {e}")
            return JSONResponse(
                content={"error": f"Failed to prepare recovery: {e}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"_recovery_prepare error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={"error": "Failed to prepare recovery. Please check the logs."},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.get("/api/wallet/recovery/funding_requirements")
    async def _get_recovery_funding_requirements(request: Request) -> JSONResponse:
        """Get recovery funding requirements."""

        try:
            output = operate.wallet_recovery_manager.recovery_requirements()
            return JSONResponse(
                content=output,
                status_code=HTTPStatus.OK,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                f"_recovery_funding_requirements error: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                content={
                    "error": "Failed to retrieve recovery funding requirements. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.get("/api/wallet/recovery/status")
    async def _get_recovery_status(request: Request) -> JSONResponse:
        """Get recovery status."""

        try:
            output = operate.wallet_recovery_manager.status()
            return JSONResponse(
                content=output,
                status_code=HTTPStatus.OK,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"_recovery_status error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={
                    "error": "Failed to retrieve recovery status. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.post("/api/wallet/recovery/complete")
    async def _wallet_recovery_complete(request: Request) -> JSONResponse:
        """Complete wallet recovery."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        if operate.password:
            return USER_LOGGED_IN_ERROR

        data = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.body()
            if body:
                data = await request.json()

        raise_if_inconsistent_owners = data.get("require_consistent_owners", True)

        try:
            operate.wallet_recovery_manager.complete_recovery(
                raise_if_inconsistent_owners=raise_if_inconsistent_owners,
            )
            return JSONResponse(
                content=operate.wallet_manager.json,
                status_code=HTTPStatus.OK,
            )
        except KeyError as e:
            logger.error(f"_recovery_complete error: {e}")
            return JSONResponse(
                content={"error": f"Failed to complete recovery: {e}"},
                status_code=HTTPStatus.NOT_FOUND,
            )
        except (ValueError, WalletRecoveryError) as e:
            logger.error(f"_recovery_complete error: {e}")
            return JSONResponse(
                content={"error": f"Failed to complete recovery: {e}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"_recovery_complete error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={
                    "error": "Failed to complete recovery. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    return app


@group(name="operate")
def _operate() -> None:
    """Operate - deploy autonomous services."""
    logger.info(f"Operate version: {__version__}")


@_operate.command(name="daemon")
def _daemon(
    host: Annotated[str, params.String(help="HTTP server host string")] = "localhost",
    port: Annotated[int, params.Integer(help="HTTP server port")] = 8000,
    ssl_keyfile: Annotated[str, params.String(help="Path to SSL key file")] = "",
    ssl_certfile: Annotated[
        str, params.String(help="Path to SSL certificate file")
    ] = "",
    home: Annotated[
        t.Optional[Path], params.Directory(long_flag="--home", help="Home directory")
    ] = None,
) -> None:
    """Launch operate daemon."""
    # try automatically shutdown previous instance before creating the app
    if TRY_TO_SHUTDOWN_PREVIOUS_INSTANCE:
        app_single_instance = AppSingleInstance(port)
        app_single_instance.shutdown_previous_instance()

    app = create_app(home=home)

    config_kwargs = {
        "app": app,
        "host": host,
        "port": port,
    }

    # Use SSL certificates if ssl_keyfile and ssl_certfile are provided
    if ssl_keyfile and ssl_certfile:
        logger.info(f"Using SSL certificates: {ssl_certfile}")
        config_kwargs.update(
            {
                "ssl_keyfile": ssl_keyfile,
                "ssl_certfile": ssl_certfile,
                "ssl_version": 2,
            }
        )

    server = Server(Config(**config_kwargs))
    app._server = server  # pylint: disable=protected-access
    server.run()


@_operate.command(name="quickstart")
def qs_start(
    config: Annotated[str, params.String(help="Quickstart config file path")],
    attended: Annotated[
        str, params.String(help="Run in attended/unattended mode (default: true")
    ] = "true",
    build_only: Annotated[
        bool, params.Boolean(help="Only build the service without running it")
    ] = False,
    skip_dependency_check: Annotated[
        bool,
        params.Boolean(help="Will skip the dependencies check for minting the service"),
    ] = False,
    use_binary: Annotated[
        bool,
        params.Boolean(help="Will use the released binary to run the service"),
    ] = False,
    rpc: Annotated[
        t.List[str],
        params.StringList(
            long_flag="--rpc",
            help="RPC override as chain=url (repeatable)",
        ),
    ] = None,
    staking: Annotated[
        t.Optional[str],
        params.String(
            long_flag="--staking",
            help="Staking program ID (e.g. 'no_staking')",
        ),
    ] = None,
    env: Annotated[
        t.List[str],
        params.StringList(
            long_flag="--env",
            help="User env var as KEY=VALUE (repeatable)",
        ),
    ] = None,
    no_docker: Annotated[
        bool,
        params.Boolean(
            long_flag="--no-docker",
            help="Run in host mode (no Docker)",
        ),
    ] = False,
) -> None:
    """Quickstart."""
    os.environ["ATTENDED"] = attended.lower()

    # Parse rpc overrides: ["gnosis=https://...", "base=https://..."] -> dict
    rpc_overrides = None
    if rpc:
        rpc_overrides = {}
        for entry in rpc:
            chain_name, url = entry.split("=", 1)
            rpc_overrides[chain_name.strip()] = url.strip()

    # Parse env overrides: ["KEY=VALUE", ...] -> dict
    user_provided_args = None
    if env:
        user_provided_args = {}
        for entry in env:
            key, value = entry.split("=", 1)
            user_provided_args[key.strip()] = value.strip()

    use_docker_val = False if no_docker else None  # None = derive from use_binary

    operate = OperateApp()
    operate.setup()
    run_service(
        operate=operate,
        config_path=config,
        build_only=build_only,
        skip_dependency_check=skip_dependency_check,
        use_binary=use_binary,
        rpc_overrides=rpc_overrides,
        staking_program_id=staking,
        user_provided_args=user_provided_args,
        use_docker=use_docker_val,
    )


@_operate.command(name="quickstop")
def qs_stop(
    config: Annotated[str, params.String(help="Quickstart config file path")],
    use_binary: Annotated[
        bool,
        params.Boolean(help="Will use the released binary to run the service"),
    ] = False,
    attended: Annotated[
        str, params.String(help="Run in attended/unattended mode (default: true")
    ] = "true",
) -> None:
    """Quickstop."""
    os.environ["ATTENDED"] = attended.lower()
    operate = OperateApp()
    operate.setup()
    stop_service(operate=operate, config_path=config, use_binary=use_binary)


@_operate.command(name="terminate")
def qs_terminate(
    config: Annotated[str, params.String(help="Quickstart config file path")],
    attended: Annotated[
        str, params.String(help="Run in attended/unattended mode (default: true")
    ] = "true",
) -> None:
    """Terminate service."""
    os.environ["ATTENDED"] = attended.lower()
    operate = OperateApp()
    operate.setup()
    terminate_service(operate=operate, config_path=config)


@_operate.command(name="claim")
def qs_claim(
    config: Annotated[str, params.String(help="Quickstart config file path")],
    attended: Annotated[
        str, params.String(help="Run in attended/unattended mode (default: true")
    ] = "true",
) -> None:
    """Quickclaim staking rewards."""
    os.environ["ATTENDED"] = attended.lower()
    operate = OperateApp()
    operate.setup()
    claim_staking_rewards(operate=operate, config_path=config)


@_operate.command(name="reset-configs")
def qs_reset_configs(
    config: Annotated[str, params.String(help="Quickstart config file path")],
    attended: Annotated[
        str, params.String(help="Run in attended/unattended mode (default: true")
    ] = "true",
) -> None:
    """Reset configs."""
    os.environ["ATTENDED"] = attended.lower()
    operate = OperateApp()
    operate.setup()
    reset_configs(operate=operate, config_path=config)


@_operate.command(name="reset-staking")
def qs_reset_staking(
    config: Annotated[str, params.String(help="Quickstart config file path")],
    attended: Annotated[
        str, params.String(help="Run in attended/unattended mode (default: true")
    ] = "true",
) -> None:
    """Reset staking."""
    os.environ["ATTENDED"] = attended.lower()
    operate = OperateApp()
    operate.setup()
    reset_staking(operate=operate, config_path=config)


@_operate.command(name="reset-password")
def qs_reset_password(
    attended: Annotated[
        str, params.String(help="Run in attended/unattended mode (default: true")
    ] = "true",
) -> None:
    """Reset password."""
    os.environ["ATTENDED"] = attended.lower()
    operate = OperateApp()
    operate.setup()
    reset_password(operate=operate)


@_operate.command(name="analyse-logs")
def qs_analyse_logs(  # pylint: disable=too-many-arguments
    config: Annotated[str, params.String(help="Quickstart config file path")],
    from_dir: Annotated[
        str,
        params.String(
            help="Path to the logs directory. If not provided, it is auto-detected.",
            default="",
        ),
    ],
    agent: Annotated[
        str,
        params.String(
            help="The agent name to analyze (default: 'aea_0').", default="aea_0"
        ),
    ],
    reset_db: Annotated[
        bool,
        params.Boolean(
            help="Use this flag to disable resetting the log database.", default=False
        ),
    ],
    start_time: Annotated[
        str,
        params.String(help="Start time in `YYYY-MM-DD H:M:S,MS` format.", default=""),
    ],
    end_time: Annotated[
        str, params.String(help="End time in `YYYY-MM-DD H:M:S,MS` format.", default="")
    ],
    log_level: Annotated[
        str,
        params.String(
            help="Logging level. (INFO, DEBUG, WARNING, ERROR, CRITICAL)",
            default="INFO",
        ),
    ],
    period: Annotated[int, params.Integer(help="Period ID.", default="")],
    round: Annotated[  # pylint: disable=redefined-builtin
        str, params.String(help="Round name.", default="")
    ],
    behaviour: Annotated[str, params.String(help="Behaviour name filter.", default="")],
    fsm: Annotated[
        bool, params.Boolean(help="Print only the FSM execution path.", default=False)
    ],
    include_regex: Annotated[
        str, params.String(help="Regex pattern to include in the result.", default="")
    ],
    exclude_regex: Annotated[
        str, params.String(help="Regex pattern to exclude from the result.", default="")
    ],
) -> None:
    """Analyse the logs of an agent."""
    operate = OperateApp()
    operate.setup()
    analyse_logs(
        operate=operate,
        config_path=config,
        from_dir=from_dir,
        agent=agent,
        reset_db=reset_db,
        start_time=start_time,
        end_time=end_time,
        log_level=log_level,
        period=period,
        round=round,
        behaviour=behaviour,
        fsm=fsm,
        include_regex=include_regex,
        exclude_regex=exclude_regex,
    )


def main() -> None:
    """CLI entry point."""
    if "freeze_support" in multiprocessing.__dict__:
        multiprocessing.freeze_support()
    run(cli=_operate)


if __name__ == "__main__":
    main()
