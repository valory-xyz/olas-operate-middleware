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
import multiprocessing
import os
import signal
import traceback
import typing as t
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from http import HTTPStatus
from pathlib import Path
from types import FrameType

import psutil
import requests
from aea.helpers.logging import setup_logger
from clea import group, params, run
from compose.project import ProjectError
from docker.errors import APIError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing_extensions import Annotated
from uvicorn.config import Config
from uvicorn.server import Server

from operate import __version__, services
from operate.account.user import UserAccount
from operate.bridge.bridge_manager import BridgeManager
from operate.constants import (
    KEYS_DIR,
    MIN_PASSWORD_LENGTH,
    OPERATE_HOME,
    SERVICES_DIR,
    USER_JSON,
    WALLETS_DIR,
    WALLET_RECOVERY_DIR,
    ZERO_ADDRESS,
)
from operate.ledger.profiles import (
    DEFAULT_MASTER_EOA_FUNDS,
    DEFAULT_NEW_SAFE_FUNDS,
    ERC20_TOKENS,
)
from operate.migration import MigrationManager
from operate.operate_types import Chain, DeploymentStatus, LedgerType
from operate.quickstart.analyse_logs import analyse_logs
from operate.quickstart.claim_staking_rewards import claim_staking_rewards
from operate.quickstart.reset_configs import reset_configs
from operate.quickstart.reset_password import reset_password
from operate.quickstart.reset_staking import reset_staking
from operate.quickstart.run_service import run_service
from operate.quickstart.stop_service import stop_service
from operate.quickstart.terminate_on_chain_service import terminate_service
from operate.services.deployment_runner import stop_deployment_manager
from operate.services.health_checker import HealthChecker
from operate.utils import subtract_dicts
from operate.utils.gnosis import get_assets_balances
from operate.wallet.master import MasterWalletManager
from operate.wallet.wallet_recovery_manager import (
    WalletRecoveryError,
    WalletRecoveryManager,
)


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


class OperateApp:
    """Operate app."""

    def __init__(
        self,
        home: t.Optional[Path] = None,
    ) -> None:
        """Initialize object."""
        super().__init__()
        self._path = (home or OPERATE_HOME).resolve()
        self._services = self._path / SERVICES_DIR
        self._keys = self._path / KEYS_DIR
        self.setup()

        services.manage.KeysManager(
            path=self._keys,
            logger=logger,
        )
        self.password: t.Optional[str] = os.environ.get("OPERATE_USER_PASSWORD")

        mm = MigrationManager(self._path, logger)
        mm.migrate_user_account()
        mm.migrate_services(self.service_manager())
        mm.migrate_wallets(self.wallet_manager)
        mm.migrate_qs_configs()

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
            raise ValueError("'new_password' is required.")

        if not (
            self.user_account.is_valid(old_password)
            and self.wallet_manager.is_password_valid(old_password)
        ):
            raise ValueError("Password is not valid.")

        wallet_manager = self.wallet_manager
        wallet_manager.password = old_password
        wallet_manager.update_password(new_password)
        self.user_account.update(old_password, new_password)

    def update_password_with_mnemonic(self, mnemonic: str, new_password: str) -> None:
        """Updates current password using the mnemonic"""

        if not new_password:
            raise ValueError("'new_password' is required.")

        mnemonic = mnemonic.strip().lower()
        if not self.wallet_manager.is_mnemonic_valid(mnemonic):
            raise ValueError("Seed phrase is not valid.")

        wallet_manager = self.wallet_manager
        wallet_manager.update_password_with_mnemonic(mnemonic, new_password)
        self.user_account.force_update(new_password)

    def service_manager(
        self, skip_dependency_check: t.Optional[bool] = False
    ) -> services.manage.ServiceManager:
        """Load service manager."""
        return services.manage.ServiceManager(
            path=self._services,
            wallet_manager=self.wallet_manager,
            logger=logger,
            skip_dependency_check=skip_dependency_check,
        )

    @property
    def user_account(self) -> t.Optional[UserAccount]:
        """Load user account."""
        if (self._path / USER_JSON).exists():
            return UserAccount.load(self._path / USER_JSON)
        return None

    @property
    def wallet_manager(self) -> MasterWalletManager:
        """Load wallet manager."""
        manager = MasterWalletManager(
            path=self._path / WALLETS_DIR,
            password=self.password,
            logger=logger,
        )
        manager.setup()
        return manager

    @property
    def wallet_recoverey_manager(self) -> WalletRecoveryManager:
        """Load wallet recovery manager."""
        manager = WalletRecoveryManager(
            path=self._path / WALLET_RECOVERY_DIR,
            wallet_manager=self.wallet_manager,
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
            "version": "0.1.0.rc0",
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

    funding_jobs: t.Dict[str, asyncio.Task] = {}
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

    def schedule_funding_job(
        service_config_id: str,
        from_safe: bool = True,
    ) -> None:
        """Schedule a funding job."""
        logger.info(f"Starting funding job for {service_config_id}")
        if service_config_id in funding_jobs:
            logger.info(f"Cancelling existing funding job for {service_config_id}")
            cancel_funding_job(service_config_id=service_config_id)

        loop = asyncio.get_running_loop()
        funding_jobs[service_config_id] = loop.create_task(
            operate.service_manager().funding_job(
                service_config_id=service_config_id,
                loop=loop,
                from_safe=from_safe,
            )
        )

    def schedule_healthcheck_job(
        service_config_id: str,
    ) -> None:
        """Schedule a healthcheck job."""
        if not HEALTH_CHECKER_OFF:
            # dont start health checker if it's switched off
            health_checker.start_for_service(service_config_id)

    def cancel_funding_job(service_config_id: str) -> None:
        """Cancel funding job."""
        if service_config_id not in funding_jobs:
            return
        status = funding_jobs[service_config_id].cancel()
        if not status:
            logger.info(f"Funding job cancellation for {service_config_id} failed")

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
            cancel_funding_job(service_config_id=service_config_id)
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
        # Load the ML model
        watchdog_task = set_parent_watchdog(app)
        yield
        # Clean up the ML models and release the resources

        with suppress(Exception):
            watchdog_task.cancel()

        with suppress(Exception):
            await watchdog_task

    app = FastAPI(lifespan=lifespan)

    def set_parent_watchdog(app):
        async def stop_app():
            logger.info("Stopping services on demand...")

            stop_deployment_manager()  # TODO: make it async?
            await run_in_executor(pause_all_services)

            logger.info("Stopping services on demand done.")
            app._server.should_exit = True  # pylint: disable=protected-access
            logger.info("Stopping app.")

        async def check_parent_alive():
            try:
                logger.info(
                    f"Parent alive check task started: ppid is {os.getppid()} and own pid is {os.getpid()}"
                )
                while True:
                    parent = psutil.Process(os.getpid()).parent()
                    if not parent:
                        logger.info("Parent is not alive, going to stop")
                        await stop_app()
                        return
                    await asyncio.sleep(3)

            except Exception:  # pylint: disable=broad-except
                logger.exception("Parent alive check crashed!")

        loop = asyncio.get_running_loop()
        task = loop.create_task(check_parent_alive())
        return task

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )

    def with_retries(f: t.Callable) -> t.Callable:
        """Retries decorator."""

        async def _call(request: Request) -> JSONResponse:
            """Call the endpoint."""
            logger.info(f"Calling `{f.__name__}` with retries enabled")
            retries = 0
            while retries < DEFAULT_MAX_RETRIES:
                try:
                    return await f(request)
                except (APIError, ProjectError) as e:
                    logger.error(f"Error {e}\n{traceback.format_exc()}")
                    if "has active endpoints" in str(e):
                        error_msg = "Service is already running."
                    else:
                        error_msg = "Service deployment failed. Please check the logs."
                    return JSONResponse(
                        content={"error": error_msg},
                        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(f"Error {str(e)}\n{traceback.format_exc()}")
                retries += 1
            return JSONResponse(
                content={
                    "error": "Operation failed after multiple attempts. Please try again later."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return _call

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
    @with_retries
    async def _get_api(request: Request) -> JSONResponse:
        """Get API info."""
        return JSONResponse(content=operate.json)

    @app.get("/api/account")
    @with_retries
    async def _get_account(request: Request) -> t.Dict:
        """Get account information."""
        return {"is_setup": operate.user_account is not None}

    @app.post("/api/account")
    @with_retries
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
    @with_retries
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
    @with_retries
    async def _validate_password(request: Request) -> t.Dict:
        """Validate password."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        data = await request.json()
        if not operate.user_account.is_valid(password=data["password"]):
            return JSONResponse(
                content={"error": "Password is not valid."},
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        operate.password = data["password"]
        return JSONResponse(
            content={"message": "Login successful."},
            status_code=HTTPStatus.OK,
        )

    @app.get("/api/wallet")
    @with_retries
    async def _get_wallets(request: Request) -> t.List[t.Dict]:
        """Get wallets."""
        wallets = []
        for wallet in operate.wallet_manager:
            wallets.append(wallet.json)
        return JSONResponse(content=wallets)

    @app.post("/api/wallet")
    @with_retries
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
    @with_retries
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
                content={"error": "Password is not valid."},
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        ledger_type = data.get("ledger_type", LedgerType.ETHEREUM.value)
        wallet = operate.wallet_manager.load(ledger_type=LedgerType(ledger_type))
        return JSONResponse(content={"private_key": wallet.crypto.private_key})

    @app.get("/api/extended/wallet")
    @with_retries
    async def _get_wallet_safe(request: Request) -> t.List[t.Dict]:
        """Get wallets."""
        wallets = []
        for wallet in operate.wallet_manager:
            wallets.append(wallet.extended_json)
        return JSONResponse(content=wallets)

    @app.get("/api/wallet/safe")
    @with_retries
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
    @with_retries
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
        if wallet.safes is not None and wallet.safes.get(chain) is not None:
            return JSONResponse(
                content={
                    "safe": wallet.safes.get(chain),
                    "message": "Safe already exists for this chain.",
                }
            )

        ledger_api = wallet.ledger_api(chain=chain)
        safes = t.cast(t.Dict[Chain, str], wallet.safes)

        backup_owner = data.get("backup_owner")
        if backup_owner:
            backup_owner = ledger_api.api.to_checksum_address(backup_owner)

        # A default nonzero balance might be required on the Safe after creation.
        # This is possibly required to estimate gas in protocol transactions.
        initial_funds = data.get("initial_funds", DEFAULT_NEW_SAFE_FUNDS[chain])
        transfer_excess_assets = (
            str(data.get("transfer_excess_assets", "false")).lower() == "true"
        )

        if transfer_excess_assets:
            asset_addresses = {ZERO_ADDRESS} | {token[chain] for token in ERC20_TOKENS}
            balances = get_assets_balances(
                ledger_api=ledger_api,
                addresses={wallet.address},
                asset_addresses=asset_addresses,
                raise_on_invalid_address=False,
            )[wallet.address]
            initial_funds = subtract_dicts(balances, DEFAULT_MASTER_EOA_FUNDS[chain])

        logger.info(f"POST /api/wallet/safe Computed {initial_funds=}")

        try:
            create_tx = wallet.create_safe(  # pylint: disable=no-member
                chain=chain,
                backup_owner=backup_owner,
            )

            safe_address = t.cast(str, safes.get(chain))

            transfer_txs = {}
            for asset, amount in initial_funds.items():
                tx_hash = wallet.transfer_asset(
                    to=safe_address,
                    amount=int(amount),
                    chain=chain,
                    asset=asset,
                    from_safe=False,
                )
                transfer_txs[asset] = tx_hash

            return JSONResponse(
                content={
                    "create_tx": create_tx,
                    "transfer_txs": transfer_txs,
                    "safe": safes.get(chain),
                    "message": "Safe created successfully",
                },
                status_code=HTTPStatus.CREATED,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Safe creation failed: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content={"error": "Failed to create safe. Please check the logs."},
            )

    @app.put("/api/wallet/safe")
    @with_retries
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

    @app.get("/api/v2/services")
    @with_retries
    async def _get_services(request: Request) -> JSONResponse:
        """Get all services."""
        return JSONResponse(content=operate.service_manager().json)

    @app.get("/api/v2/services/validate")
    @with_retries
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

    @app.get("/api/v2/service/{service_config_id}")
    @with_retries
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
    @with_retries
    async def _get_service_deployment(request: Request) -> JSONResponse:
        """Get a service deployment."""
        service_config_id = request.path_params["service_config_id"]

        if not operate.service_manager().exists(service_config_id=service_config_id):
            return service_not_found_error(service_config_id=service_config_id)

        service = operate.service_manager().load(service_config_id=service_config_id)
        deployment_json = service.deployment.json
        deployment_json["healthcheck"] = service.get_latest_healthcheck()
        return JSONResponse(content=deployment_json)

    @app.get("/api/v2/service/{service_config_id}/agent_performance")
    @with_retries
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

    @app.get("/api/v2/service/{service_config_id}/refill_requirements")
    @with_retries
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
    @with_retries
    async def _create_services_v2(request: Request) -> JSONResponse:
        """Create a service."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR
        template = await request.json()
        manager = operate.service_manager()
        output = manager.create(service_template=template)

        return JSONResponse(content=output.json)

    @app.post("/api/v2/service/{service_config_id}")
    @with_retries
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
            manager.fund_service(service_config_id=service_config_id)
            manager.deploy_service_locally(service_config_id=service_config_id)

        await run_in_executor(_fn)
        schedule_funding_job(service_config_id=service_config_id)
        schedule_healthcheck_job(service_config_id=service_config_id)

        return JSONResponse(
            content=(
                operate.service_manager().load(service_config_id=service_config_id).json
            )
        )

    @app.put("/api/v2/service/{service_config_id}")
    @app.patch("/api/v2/service/{service_config_id}")
    @with_retries
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
    @with_retries
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
        cancel_funding_job(service_config_id=service_config_id)
        return JSONResponse(content=deployment.json)

    @app.post("/api/v2/service/{service_config_id}/onchain/withdraw")
    @with_retries
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
                    withdrawal_address=withdrawal_address,
                )

                # drain the master safe and master signer for the home chain
                chain = Chain(service.home_chain)
                master_wallet = service_manager.wallet_manager.load(
                    ledger_type=chain.ledger_type
                )

                # drain the master safe
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

    @app.post("/api/bridge/bridge_refill_requirements")
    @with_retries
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
    @with_retries
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
    @with_retries
    async def _bridge_last_executed_bundle_id(request: Request) -> t.List[t.Dict]:
        """Get last executed bundle id."""
        content = {"id": operate.bridge_manager.last_executed_bundle_id()}
        return JSONResponse(content=content, status_code=HTTPStatus.OK)

    @app.get("/api/bridge/status/{id}")
    @with_retries
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

    @app.post("/api/wallet/recovery/initiate")
    @with_retries
    async def _wallet_recovery_initiate(request: Request) -> JSONResponse:
        """Initiate wallet recovery."""
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
            output = operate.wallet_recoverey_manager.initiate_recovery(
                new_password=new_password
            )
            return JSONResponse(
                content=output,
                status_code=HTTPStatus.OK,
            )
        except (ValueError, WalletRecoveryError) as e:
            logger.error(f"_recovery_initiate error: {e}")
            return JSONResponse(
                content={"error": f"Failed to initiate recovery: {e}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"_recovery_initiate error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                content={
                    "error": "Failed to initiate recovery. Please check the logs."
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @app.post("/api/wallet/recovery/complete")
    @with_retries
    async def _wallet_recovery_complete(request: Request) -> JSONResponse:
        """Complete wallet recovery."""
        if operate.user_account is None:
            return ACCOUNT_NOT_FOUND_ERROR

        if operate.password:
            return USER_LOGGED_IN_ERROR

        data = await request.json()
        bundle_id = data.get("id")
        password = data.get("password")
        raise_if_inconsistent_owners = data.get("require_consistent_owners", True)

        try:
            operate.wallet_recoverey_manager.complete_recovery(
                bundle_id=bundle_id,
                password=password,
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

    # try automatically shutdown previous instance
    if TRY_TO_SHUTDOWN_PREVIOUS_INSTANCE:
        url = f"http{'s' if ssl_keyfile and ssl_certfile else ''}://{host}:{port}/shutdown"
        logger.info(f"trying to stop  previous instance with {url}")
        try:
            requests.get(
                f"https://{host}:{port}/shutdown", timeout=3, verify=False  # nosec
            )
        except requests.exceptions.SSLError:
            logger.warning("SSL failed, trying HTTP fallback...")
            try:
                requests.get(f"http://{host}:{port}/shutdown", timeout=3)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failed to stop previous instance")

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
) -> None:
    """Quickstart."""
    os.environ["ATTENDED"] = attended.lower()
    operate = OperateApp()
    operate.setup()
    run_service(
        operate=operate,
        config_path=config,
        build_only=build_only,
        skip_dependency_check=skip_dependency_check,
    )


@_operate.command(name="quickstop")
def qs_stop(
    config: Annotated[str, params.String(help="Quickstart config file path")],
) -> None:
    """Quickstart."""
    operate = OperateApp()
    operate.setup()
    stop_service(operate=operate, config_path=config)


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
