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
import logging
import os
import signal
import traceback
import typing as t
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import FrameType

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

from operate import services
from operate.account.user import UserAccount
from operate.constants import KEY, KEYS, OPERATE_HOME, SERVICES
from operate.ledger.profiles import DEFAULT_NEW_SAFE_FUNDS_AMOUNT
from operate.migration import MigrationManager
from operate.operate_types import Chain, DeploymentStatus, LedgerType
from operate.quickstart.analyse_logs import analyse_logs
from operate.quickstart.claim_staking_rewards import claim_staking_rewards
from operate.quickstart.reset_password import reset_password
from operate.quickstart.reset_staking import reset_staking
from operate.quickstart.run_service import run_service
from operate.quickstart.stop_service import stop_service
from operate.quickstart.terminate_on_chain_service import terminate_service
from operate.services.health_checker import HealthChecker
from operate.wallet.master import MasterWalletManager


DEFAULT_HARDHAT_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
).encode()
DEFAULT_MAX_RETRIES = 3
USER_NOT_LOGGED_IN_ERROR = JSONResponse(
    content={"error": "User not logged in!"}, status_code=401
)


def service_not_found_error(service_config_id: str) -> JSONResponse:
    """Service not found error response"""
    return JSONResponse(
        content={"error": f"Service {service_config_id} not found"}, status_code=404
    )


class OperateApp:
    """Operate app."""

    def __init__(
        self,
        home: t.Optional[Path] = None,
        logger: t.Optional[logging.Logger] = None,
    ) -> None:
        """Initialize object."""
        super().__init__()
        self._path = (home or OPERATE_HOME).resolve()
        self._services = self._path / SERVICES
        self._keys = self._path / KEYS
        self._master_key = self._path / KEY
        self.setup()

        self.logger = logger or setup_logger(name="operate")
        self.keys_manager = services.manage.KeysManager(
            path=self._keys,
            logger=self.logger,
        )
        self.password: t.Optional[str] = os.environ.get("OPERATE_USER_PASSWORD")

        mm = MigrationManager(self._path, self.logger)
        mm.migrate_user_account()

    def create_user_account(self, password: str) -> UserAccount:
        """Create a user account."""
        self.password = password
        return UserAccount.new(
            password=password,
            path=self._path / "user.json",
        )

    def update_password(self, old_password: str, new_password: str) -> None:
        """Updates current password"""

        if not new_password:
            raise ValueError("You must provide a new password.")

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
            raise ValueError("You must provide a new password.")

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
            keys_manager=self.keys_manager,
            wallet_manager=self.wallet_manager,
            logger=self.logger,
            skip_dependency_check=skip_dependency_check,
        )

    @property
    def user_account(self) -> t.Optional[UserAccount]:
        """Load user account."""
        return (
            UserAccount.load(self._path / "user.json")
            if (self._path / "user.json").exists()
            else None
        )

    @property
    def wallet_manager(self) -> MasterWalletManager:
        """Load master wallet."""
        manager = MasterWalletManager(
            path=self._path / "wallets",
            password=self.password,
        )
        manager.setup()
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

    logger = setup_logger(name="operate")
    if HEALTH_CHECKER_OFF:
        logger.warning("Healthchecker is off!!!")
    operate = OperateApp(home=home, logger=logger)

    operate.service_manager().log_directories()
    logger.info("Migrating service configs...")
    operate.service_manager().migrate_service_configs()
    logger.info("Migrating service configs done.")
    operate.service_manager().log_directories()

    logger.info("Migrating wallet configs...")
    operate.wallet_manager.migrate_wallet_configs()
    logger.info("Migrating wallet configs done.")

    funding_jobs: t.Dict[str, asyncio.Task] = {}
    health_checker = HealthChecker(
        operate.service_manager(), number_of_fails=number_of_fails
    )
    # Create shutdown endpoint
    shutdown_endpoint = uuid.uuid4().hex
    (operate._path / "operate.kill").write_text(  # pylint: disable=protected-access
        shutdown_endpoint
    )
    thread_pool_executor = ThreadPoolExecutor()

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
            deployment.stop(force=True)
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

    app = FastAPI()

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
            errors = []
            while retries < DEFAULT_MAX_RETRIES:
                try:
                    return await f(request)
                except (APIError, ProjectError) as e:
                    logger.error(f"Error {e}\n{traceback.format_exc()}")
                    error = {"traceback": traceback.format_exc()}
                    if "has active endpoints" in e.explanation:
                        error["error"] = "Service is already running"
                    else:
                        error["error"] = str(e)
                    errors.append(error)
                    return JSONResponse(content={"errors": errors}, status_code=500)
                except Exception as e:  # pylint: disable=broad-except
                    errors.append(
                        {"error": str(e.args[0]), "traceback": traceback.format_exc()}
                    )
                    logger.error(f"Error {str(e.args[0])}\n{traceback.format_exc()}")
                retries += 1
            return JSONResponse(content={"errors": errors}, status_code=500)

        return _call

    @app.get(f"/{shutdown_endpoint}")
    async def _kill_server(request: Request) -> JSONResponse:
        """Kill backend server from inside."""
        os.kill(os.getpid(), signal.SIGINT)

    @app.get("/shutdown")
    async def _shutdown(request: Request) -> JSONResponse:
        """Kill backend server from inside."""
        logger.info("Stopping services on demand...")
        pause_all_services()
        logger.info("Stopping services on demand done.")
        app._server.should_exit = True  # pylint: disable=protected-access
        await asyncio.sleep(0.3)
        return {"stopped": True}

    @app.post("/api/v2/services/stop")
    @app.get("/stop_all_services")
    async def _stop_all_services(request: Request) -> JSONResponse:
        """Kill backend server from inside."""

        # No authentication required to stop services.

        try:
            logger.info("Stopping services on demand...")
            pause_all_services()
            logger.info("Stopping services on demand done.")
            return JSONResponse(content={"message": "Services stopped."})
        except Exception as e:  # pylint: disable=broad-except
            return JSONResponse(
                content={"error": str(e), "traceback": traceback.format_exc()},
                status_code=500,
            )

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
                content={"error": "Account already exists"},
                status_code=400,
            )

        data = await request.json()
        operate.create_user_account(
            password=data["password"],
        )
        return JSONResponse(content={"error": None})

    @app.put("/api/account")
    @with_retries
    async def _update_password(  # pylint: disable=too-many-return-statements
        request: Request,
    ) -> t.Dict:
        """Update password."""
        if operate.user_account is None:
            return JSONResponse(
                content={"error": "Account does not exist."},
                status_code=400,
            )

        data = await request.json()
        old_password = data.get("old_password")
        new_password = data.get("new_password")
        mnemonic = data.get("mnemonic")

        if not old_password and not mnemonic:
            return JSONResponse(
                content={
                    "error": "You must provide exactly one of 'old_password' or 'mnemonic' (seed phrase).",
                },
                status_code=400,
            )

        if old_password and mnemonic:
            return JSONResponse(
                content={
                    "error": "You must provide exactly one of 'old_password' or 'mnemonic' (seed phrase), but not both.",
                },
                status_code=400,
            )

        try:
            if old_password:
                operate.update_password(old_password, new_password)
                return JSONResponse(
                    content={"error": None, "message": "Password updated."}
                )
            if mnemonic:
                operate.update_password_with_mnemonic(mnemonic, new_password)
                return JSONResponse(
                    content={
                        "error": None,
                        "message": "Password updated using seed phrase.",
                    }
                )

            return JSONResponse(
                content={"error": None, "message": "Password not updated."}
            )
        except ValueError as e:
            return JSONResponse(content={"error": str(e)}, status_code=400)
        except Exception as e:  # pylint: disable=broad-except
            return JSONResponse(
                content={"error": str(e), "traceback": traceback.format_exc()},
                status_code=400,
            )

    @app.post("/api/account/login")
    @with_retries
    async def _validate_password(request: Request) -> t.Dict:
        """Validate password."""
        if operate.user_account is None:
            return JSONResponse(
                content={"error": "Account does not exist"},
                status_code=400,
            )

        data = await request.json()
        if not operate.user_account.is_valid(password=data["password"]):
            return JSONResponse(
                content={"error": "Password is not valid"},
                status_code=401,
            )

        operate.password = data["password"]
        return JSONResponse(
            content={"message": "Login successful"},
            status_code=200,
        )

    @app.get("/api/wallet")
    @with_retries
    async def _get_wallets(request: Request) -> t.List[t.Dict]:
        """Get wallets."""
        wallets = []
        for wallet in operate.wallet_manager:
            wallets.append(wallet.json)
        return JSONResponse(content=wallets)

    @app.get("/api/wallet/{chain}")
    @with_retries
    async def _get_wallet_by_chain(request: Request) -> t.List[t.Dict]:
        """Create wallet safe"""
        ledger_type = Chain.from_string(request.path_params["chain"]).ledger_type
        manager = operate.wallet_manager
        if not manager.exists(ledger_type=ledger_type):
            return JSONResponse(
                content={"error": "Wallet does not exist"},
                status_code=404,
            )
        return JSONResponse(
            content=manager.load(ledger_type=ledger_type).json,
        )

    @app.post("/api/wallet")
    @with_retries
    async def _create_wallet(request: Request) -> t.List[t.Dict]:
        """Create wallet"""
        if operate.user_account is None:
            return JSONResponse(
                content={"error": "Cannot create wallet; User account does not exist!"},
                status_code=400,
            )

        if operate.password is None:
            return JSONResponse(
                content={"error": "You need to login before creating a wallet"},
                status_code=401,
            )

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
        """Create wallet safe"""
        chain = Chain.from_string(request.path_params["chain"])
        ledger_type = chain.ledger_type
        manager = operate.wallet_manager
        if not manager.exists(ledger_type=ledger_type):
            return JSONResponse(
                content={"error": "Wallet does not exist"},
                status_code=404,
            )
        safes = manager.load(ledger_type=ledger_type).safes
        if safes is None or safes.get(chain) is None:
            return JSONResponse(content={"error": "No safes found"})

        return JSONResponse(
            content={
                "safe": safes[chain],
            },
        )

    @app.post("/api/wallet/safe")
    @with_retries
    async def _create_safe(request: Request) -> t.List[t.Dict]:
        """Create wallet safe"""
        if operate.user_account is None:
            return JSONResponse(
                content={"error": "Cannot create safe; User account does not exist!"},
                status_code=400,
            )

        if operate.password is None:
            return JSONResponse(
                content={"error": "You need to login before creating a safe"},
                status_code=401,
            )

        data = await request.json()
        chain = Chain(data["chain"])
        ledger_type = chain.ledger_type
        manager = operate.wallet_manager
        if not manager.exists(ledger_type=ledger_type):
            return JSONResponse(content={"error": "Wallet does not exist"})

        wallet = manager.load(ledger_type=ledger_type)
        if wallet.safes is not None and wallet.safes.get(chain) is not None:
            return JSONResponse(
                content={
                    "safe": wallet.safes.get(chain),
                    "message": f"Safe already exists {chain=}.",
                }
            )

        ledger_api = wallet.ledger_api(chain=chain)
        safes = t.cast(t.Dict[Chain, str], wallet.safes)

        backup_owner = data.get("backup_owner")
        if backup_owner:
            backup_owner = ledger_api.api.to_checksum_address(backup_owner)

        wallet.create_safe(  # pylint: disable=no-member
            chain=chain,
            backup_owner=backup_owner,
        )
        wallet.transfer(
            to=t.cast(str, safes.get(chain)),
            amount=int(data.get("fund_amount", DEFAULT_NEW_SAFE_FUNDS_AMOUNT[chain])),
            chain=chain,
            from_safe=False,
        )
        return JSONResponse(
            content={"safe": safes.get(chain), "message": "Safe created!"}
        )

    @app.post("/api/wallet/safes")
    @with_retries
    async def _create_safes(request: Request) -> t.List[t.Dict]:
        """Create wallet safes"""
        if operate.user_account is None:
            return JSONResponse(
                content={"error": "Cannot create safe; User account does not exist!"},
                status_code=400,
            )

        if operate.password is None:
            return JSONResponse(
                content={"error": "You need to login before creating a safe"},
                status_code=401,
            )

        data = await request.json()
        chains = [Chain(chain_str) for chain_str in data["chains"]]
        # check that all chains are supported
        for chain in chains:
            ledger_type = chain.ledger_type
            manager = operate.wallet_manager
            if not manager.exists(ledger_type=ledger_type):
                return JSONResponse(
                    content={
                        "error": f"A wallet of type {ledger_type} does not exist for chain {chain}."
                    }
                )

        # mint the safes
        for chain in chains:
            ledger_type = chain.ledger_type
            manager = operate.wallet_manager

            wallet = manager.load(ledger_type=ledger_type)
            if wallet.safes is not None and wallet.safes.get(chain) is not None:
                logger.info(f"Safe already exists for chain {chain}")
                continue

            safes = t.cast(t.Dict[Chain, str], wallet.safes)
            wallet.create_safe(  # pylint: disable=no-member
                chain=chain,
                owner=data.get("backup_owner"),
            )
            wallet.transfer(
                to=t.cast(str, safes.get(chain)),
                amount=int(
                    data.get("fund_amount", DEFAULT_NEW_SAFE_FUNDS_AMOUNT[chain])
                ),
                chain=chain,
                from_safe=False,
            )

        return JSONResponse(content={"safes": safes, "message": "Safes created."})

    @app.put("/api/wallet/safe")
    @with_retries
    async def _update_safe(request: Request) -> t.List[t.Dict]:
        """Update wallet safe"""
        # TODO: Extract login check as decorator
        if operate.user_account is None:
            return JSONResponse(
                content={"error": "Cannot update safe; User account does not exist!"},
                status_code=400,
            )

        if operate.password is None:
            return JSONResponse(
                content={"error": "You need to login before updating a safe."},
                status_code=401,
            )

        data = await request.json()

        if "chain" not in data:
            return JSONResponse(
                content={"error": "You need to specify a chain to updae a safe."},
                status_code=401,
            )

        chain = Chain(data["chain"])
        ledger_type = chain.ledger_type
        manager = operate.wallet_manager
        if not manager.exists(ledger_type=ledger_type):
            return JSONResponse(
                content={"error": "Wallet does not exist"},
                status_code=401,
            )

        wallet = manager.load(ledger_type=ledger_type)
        ledger_api = wallet.ledger_api(chain=chain)

        backup_owner = data.get("backup_owner")
        if backup_owner:
            backup_owner = ledger_api.api.to_checksum_address(backup_owner)

        backup_owner_updated = wallet.update_backup_owner(
            chain=chain,
            backup_owner=backup_owner,  # Optional value, it's fine to provide 'None' (set no backup owner/remove backup owner)
        )
        message = (
            "Backup owner updated."
            if backup_owner_updated
            else "No changes on backup owner. The backup owner provided matches the current one."
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

    @app.get("/api/v2/service/{service_config_id}/refill_requirements")
    @with_retries
    async def _get_refill_requirements(request: Request) -> JSONResponse:
        """Get the service balances."""
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

    @app.put("/api/v2/services")
    @with_retries
    async def _update_all_services(request: Request) -> JSONResponse:
        """Update all services of matching the public id referenced in the hash."""
        if operate.password is None:
            return USER_NOT_LOGGED_IN_ERROR

        manager = operate.service_manager()
        template = await request.json()
        updated_services = manager.update_all_matching(service_template=template)

        return JSONResponse(content=updated_services)

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
                content={"error": "withdrawal_address is required"},
                status_code=400,
            )

        try:
            pause_all_services()
            service = service_manager.load(service_config_id=service_config_id)

            # terminate the service on chain
            for chain in service.chain_configs:
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
            )

            # drain the master signer
            logger.info(
                f"Draining the Master Signer {master_wallet.address} on chain {chain.value} (withdrawal address {withdrawal_address})."
            )
            master_wallet.drain(
                withdrawal_address=withdrawal_address,
                chain=chain,
                from_safe=False,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error(traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "traceback": traceback.format_exc()},
            )

        return JSONResponse(content={"error": None})

    return app


@group(name="operate")
def _operate() -> None:
    """Operate - deploy autonomous services."""


@_operate.command(name="daemon")
def _daemon(
    host: Annotated[str, params.String(help="HTTP server host string")] = "localhost",
    port: Annotated[int, params.Integer(help="HTTP server port")] = 8000,
    home: Annotated[
        t.Optional[Path], params.Directory(long_flag="--home", help="Home directory")
    ] = None,
) -> None:
    """Launch operate daemon."""
    app = create_app(home=home)

    server = Server(
        Config(
            app=app,
            host=host,
            port=port,
        )
    )
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
    run(cli=_operate)


if __name__ == "__main__":
    main()
