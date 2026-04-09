# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Fund recovery manager for recovering on-chain funds using a BIP-39 mnemonic.

Security constraints:
- The mnemonic and derived private key are NEVER persisted to disk, logged, or
  transmitted in any form.
- Both endpoints that use this manager are intentionally unauthenticated.
"""

import concurrent.futures
import json
import logging
import secrets
import string
import tempfile
import time
import typing as t
from pathlib import Path

import requests
from aea.helpers.logging import setup_logger
from autonomy.chain.base import registry_contracts
from autonomy.chain.constants import CHAIN_PROFILES
from web3 import Web3

from operate.constants import (
    CONFIG_JSON,
    NO_STAKING_PROGRAM_ID,
    ZERO_ADDRESS,
)
from operate.data.contracts.staking_token.contract import StakingTokenContract
from operate.keys import KeysManager
from operate.ledger import get_default_ledger_api, get_default_rpc
from operate.ledger.profiles import (
    CONTRACTS,
    DEFAULT_EOA_THRESHOLD,
    DEFAULT_EOA_TOPUPS,
    ERC20_TOKENS_BY_CHAIN_ID,
    STAKING,
)
from operate.operate_types import (
    Chain,
    ChainAmounts,
    ChainConfig,
    FundRecoveryExecuteResponse,
    FundRecoveryScanResponse,
    GasWarningEntry,
    LedgerConfig,
    LedgerType,
    OnChainData,
    OnChainState,
    OnChainUserParams,
    RecoveredServiceInfo,
)
from operate.resource import LocalResource
from operate.serialization import BigInt
from operate.services.service import (
    NON_EXISTENT_MULTISIG,
    SERVICE_CONFIG_PREFIX,
    SERVICE_CONFIG_VERSION,
    Service,
)
from operate.utils.gnosis import (
    drain_eoa,
    fetch_safes_for_owner,
    get_asset_balance,
    transfer,
    transfer_erc20_from_eoa,
    transfer_erc20_from_safe,
)

logger = setup_logger(name="operate.fund_recovery_manager")

# ---------------------------------------------------------------------------
# Chain-specific constants
# ---------------------------------------------------------------------------

#: Chains on which fund recovery is supported
RECOVERY_CHAINS: t.List[Chain] = [
    Chain.POLYGON,
    Chain.GNOSIS,
    Chain.BASE,
    Chain.OPTIMISM,
]

#: Minimum native balance (in wei) to warn the user about insufficient gas.
#: Built from DEFAULT_EOA_TOPUPS * DEFAULT_EOA_THRESHOLD so the threshold
#: stays in sync with the funding-manager formula used across the codebase.
GAS_WARN_THRESHOLDS: t.Dict[int, int] = {
    chain.id: int(amounts[ZERO_ADDRESS] * DEFAULT_EOA_THRESHOLD)
    for chain, amounts in DEFAULT_EOA_TOPUPS.items()
    if hasattr(chain, "id") and ZERO_ADDRESS in amounts
}

#: Subgraph URLs for fast service enumeration
SUBGRAPH_URLS: t.Dict[Chain, str] = {
    Chain.GNOSIS: "https://api.subgraph.autonolas.tech/api/proxy/service-registry-gnosis",
    Chain.OPTIMISM: "https://registry-optimism.subgraph.autonolas.tech/graphql",
    Chain.POLYGON: "https://registry-polygon.subgraph.autonolas.tech/graphql",
    Chain.BASE: "https://registry-base.subgraph.autonolas.tech/graphql",
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _mnemonic_to_address(mnemonic: str) -> str:
    """Derive the Master EOA address from a BIP-39 mnemonic (no private key stored)."""
    w3 = Web3()
    w3.eth.account.enable_unaudited_hdwallet_features()
    account = w3.eth.account.from_mnemonic(mnemonic)
    return account.address


def _mnemonic_to_private_key(mnemonic: str) -> str:
    """Derive the Master EOA private key from a BIP-39 mnemonic.

    SECURITY: The returned value must never be persisted, logged, or transmitted.
    It should only exist in memory for the duration of a single request handler.
    """
    w3 = Web3()
    w3.eth.account.enable_unaudited_hdwallet_features()
    account = w3.eth.account.from_mnemonic(mnemonic)
    return account._private_key.hex()  # pylint: disable=protected-access


def _get_service_registry_contract(
    ledger_api: t.Any,
    service_registry_address: str,
) -> t.Any:
    """Return a contract instance for ServiceRegistryL2 via registry_contracts."""
    return registry_contracts.service_registry.get_instance(
        ledger_api=ledger_api,
        contract_address=service_registry_address,
    )


def _get_safe_deploy_and_last_tx_block(
    w3: "Web3", safe: str, current_block: int
) -> t.Tuple[int, int]:
    """Find the block when the Safe was deployed and the block of its last transaction."""
    safe_checksum = w3.to_checksum_address(safe)

    # 1. Binary search for deployment block
    low = 0
    high = current_block
    deploy_block = current_block

    while low <= high:
        mid = (low + high) // 2
        try:
            code = w3.eth.get_code(safe_checksum, block_identifier=mid)
            if len(code) > 2:
                deploy_block = mid
                high = mid - 1
            else:
                low = mid + 1
        except Exception:  # pylint: disable=broad-except
            low = mid + 1

    # 2. Binary search for last transaction block
    try:
        # Keccak of "nonce()"
        nonce_data = Web3.keccak(text="nonce()")[:4].hex()
        res = w3.eth.call(
            {"to": safe_checksum, "data": nonce_data}, block_identifier=current_block
        )
        current_nonce = int.from_bytes(res, "big") if res else 0
    except Exception:  # pylint: disable=broad-except
        current_nonce = 0

    last_tx_block = current_block
    if current_nonce > 0:
        low = deploy_block
        high = current_block
        last_tx_block = current_block

        while low <= high:
            mid = (low + high) // 2
            try:
                res = w3.eth.call(
                    {"to": safe_checksum, "data": nonce_data}, block_identifier=mid
                )
                mid_nonce = int.from_bytes(res, "big") if res else 0

                if mid_nonce == current_nonce:
                    last_tx_block = mid
                    high = mid - 1
                else:
                    low = mid + 1
            except Exception:  # pylint: disable=broad-except
                low = mid + 1

    return deploy_block, last_tx_block


def _fetch_logs_in_chunks(
    w3: "Web3",
    registry: str,
    start_block: int,
    end_block: int,
    topics: t.List[t.Optional[str]],
) -> t.Set[int]:
    """Fetch logs dynamically adjusting chunk sizes on failure."""
    token_ids: t.Set[int] = set()
    current_start = start_block
    chunk_size = 100_000
    registry_checksum = w3.to_checksum_address(registry)

    while current_start <= end_block:
        chunk_end = min(current_start + chunk_size - 1, end_block)
        try:
            logs = w3.eth.get_logs(
                {
                    "address": registry_checksum,
                    "topics": topics,
                    "fromBlock": hex(current_start),
                    "toBlock": hex(chunk_end),
                }
            )
            for log in logs:
                if len(log["topics"]) >= 4:
                    token_ids.add(int(log["topics"][3].hex(), 16))

            current_start = chunk_end + 1
            # Grow chunk size on success up to max
            chunk_size = min(100_000, chunk_size * 2)

        except Exception as e:  # pylint: disable=broad-except
            if chunk_size <= 1:
                logger.warning(
                    f"Log chunk [{current_start},{chunk_end}] failed at minimum size: {e}"
                )
                current_start = chunk_end + 1
            else:
                chunk_size = max(1, chunk_size // 2)

    return token_ids


def _enumerate_owned_services(  # pylint: disable=too-many-locals
    ledger_api: t.Any,
    service_registry_address: str,
    owner_address: str,
) -> t.List[int]:
    """
    Enumerate service IDs owned by *owner_address* by scanning Transfer events.

    ServiceRegistryL2 does NOT expose ``getServicesOfOwner``.  Instead we scan
    Transfer events where ``to == owner_address`` in bounded chunks, then filter
    via ``ownerOf(tokenId)`` to skip transferred-away NFTs.
    """
    contract = _get_service_registry_contract(ledger_api, service_registry_address)
    try:
        latest_block = ledger_api.api.eth.block_number
        owner_checksum: str = str(Web3.to_checksum_address(owner_address))

        deploy_block, last_tx_block = _get_safe_deploy_and_last_tx_block(
            ledger_api.api, owner_checksum, latest_block
        )

        topics: t.List[t.Optional[str]] = [
            Web3.keccak(text="Transfer(address,address,uint256)").to_0x_hex(),
            None,
            "0x" + "0" * 24 + owner_checksum[2:].lower(),
        ]

        token_ids = _fetch_logs_in_chunks(
            ledger_api.api,
            service_registry_address,
            deploy_block,
            last_tx_block,
            topics,
        )

        owned = []
        for token_id in token_ids:
            try:
                current_owner = contract.functions.ownerOf(token_id).call()
                if current_owner.lower() == owner_address.lower():
                    owned.append(token_id)
            except Exception:  # pylint: disable=broad-except  # nosec B110
                pass  # token may not exist or call failed

        return owned
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(f"Service enumeration failed: {exc}")
        return []


def _get_service_state(
    ledger_api: t.Any,
    service_registry_address: str,
    service_id: int,
) -> OnChainState:
    """Return the on-chain state for a service."""
    contract = _get_service_registry_contract(ledger_api, service_registry_address)
    try:
        info = contract.functions.getService(service_id).call()
        # state is the last field (index 6)
        state_int = info[6]
        return OnChainState(state_int)
    except Exception:  # pylint: disable=broad-except
        return OnChainState.NON_EXISTENT


def _fetch_services_from_subgraph(url: str, eoa_address: str) -> t.List[int]:
    """Fetch service IDs created by the Master EOA from the given subgraph URL."""
    payload = {
        "query": f'{{ services(where: {{creator_: {{id: "{eoa_address.lower()}"}}}}) {{ id }} }}'
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            logger.warning(f"Subgraph returned errors for {url}: {data['errors']}")
            raise ValueError("GraphQL query returned errors")

        result_data = data.get("data")
        if not result_data:
            raise ValueError(f"No 'data' field in subgraph response: {data}")

        services = result_data.get("services", [])
        return [int(s["id"]) for s in services]
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(f"Subgraph query failed for {url}: {exc}")
        raise


def _check_gas_warning(
    chain_id: int,
    eoa_address: str,
    ledger_api: t.Any,
) -> GasWarningEntry:
    """Return a GasWarningEntry indicating whether the EOA has enough gas."""
    threshold = GAS_WARN_THRESHOLDS.get(chain_id, 0)
    try:
        balance = ledger_api.api.eth.get_balance(Web3.to_checksum_address(eoa_address))
        return GasWarningEntry(insufficient=balance < threshold)
    except Exception:  # pylint: disable=broad-except
        # If we can't check, assume warning
        return GasWarningEntry(insufficient=True)


def _unstake_service(
    chain: Chain,
    ledger_api: t.Any,
    crypto: t.Any,
    service_id: int,
) -> None:
    """Unstake *service_id* from any known staking program on *chain*.

    Iterates over all staking programs registered for the chain in ``STAKING``
    and calls ``unstake()`` on the first contract that reports the service as
    staked.  This uses direct EOA-based transactions rather than the Safe
    because the unstake call only requires the operator key (the Master EOA).

    Raises are swallowed per-program with a warning; if no program matches,
    the function is a no-op.
    """
    staking_contracts = STAKING.get(chain, {})
    for staking_program_id, staking_addr in staking_contracts.items():
        if not staking_addr:
            continue
        try:
            staking_state = StakingTokenContract.get_service_staking_state(
                ledger_api=ledger_api,
                contract_address=Web3.to_checksum_address(staking_addr),
                service_id=service_id,
            )["data"]
            if staking_state == 0:  # UNSTAKED
                continue
            # Check minimum staking duration to avoid revert on early unstake
            try:
                min_duration = StakingTokenContract.get_min_staking_duration(
                    ledger_api=ledger_api,
                    contract_address=Web3.to_checksum_address(staking_addr),
                )["data"]
                service_info = StakingTokenContract.get_service_info(
                    ledger_api=ledger_api,
                    contract_address=Web3.to_checksum_address(staking_addr),
                    service_id=service_id,
                )["data"]
                ts_start = service_info[2]  # tsStart field
                elapsed = int(time.time()) - ts_start
                if elapsed < min_duration:
                    raise ValueError(
                        f"Cannot unstake service {service_id} from "
                        f"{staking_program_id}: minimum staking duration "
                        f"not elapsed ({elapsed}s < {min_duration}s)"
                    )
            except ValueError:
                raise
            except Exception:  # pylint: disable=broad-except  # nosec B110
                pass  # proceed to unstake if we can't determine duration

            staking_contract_instance = StakingTokenContract.get_instance(
                ledger_api=ledger_api,
                contract_address=Web3.to_checksum_address(staking_addr),
            )
            tx = staking_contract_instance.functions.unstake(
                service_id
            ).build_transaction(
                {
                    "from": crypto.address,
                    "nonce": ledger_api.api.eth.get_transaction_count(crypto.address),
                }
            )
            signed = ledger_api.api.eth.account.sign_transaction(tx, crypto.private_key)
            tx_hash = ledger_api.api.eth.send_raw_transaction(signed.raw_transaction)
            ledger_api.api.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(
                "Unstaked service %s from %s on chain %s",
                service_id,
                staking_program_id,
                chain.id,
            )
            break  # service can only be staked in one program at a time
        except ValueError:
            raise  # min staking duration not elapsed — propagate to caller
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Unstake check/attempt failed for service %s program=%s: %s",
                service_id,
                staking_program_id,
                exc,
            )


def _build_synthetic_service(
    storage: Path,
    chain: Chain,
    service_id: int,
    rpc: str,
) -> t.Any:
    """Build a minimal Service object for *service_id* on *chain*.

    The Service is written to disk under *storage* so that
    ``ServiceManager.load(service_config_id)`` can reload it.  No IPFS
    download is performed — only the JSON config is written.

    Parameters
    ----------
    storage:
        Directory where service config directories live (``OperateApp._services``).
    chain:
        The chain on which the service was registered.
    service_id:
        The on-chain service token ID.
    rpc:
        RPC endpoint for the chain.

    Returns
    -------
    Service instance (already stored on disk).
    """
    chain_str = chain.value
    service_config_id = f"{SERVICE_CONFIG_PREFIX}{service_id}-{chain_str}"
    svc_path = storage / service_config_id
    svc_path.mkdir(parents=True, exist_ok=True)

    ledger_config = LedgerConfig(rpc=rpc, chain=chain)
    user_params = OnChainUserParams(
        staking_program_id=NO_STAKING_PROGRAM_ID,
        nft="",
        agent_id=1,
        cost_of_bond=BigInt(0),
        fund_requirements={},
    )
    chain_data = OnChainData(
        instances=[],
        token=service_id,
        multisig=NON_EXISTENT_MULTISIG,
        user_params=user_params,
    )
    chain_config = ChainConfig(ledger_config=ledger_config, chain_data=chain_data)

    service = Service(
        version=SERVICE_CONFIG_VERSION,
        service_config_id=service_config_id,
        name="recovery-stub",
        description="",
        hash="",
        hash_history={},
        agent_release={},
        agent_addresses=[],
        home_chain=chain_str,
        chain_configs={chain_str: chain_config},
        path=svc_path,
        package_path=Path("."),  # placeholder — not accessed in recovery code paths
        env_variables={},
    )
    # Use LocalResource.json.fget directly to bypass Service.json which calls
    # service_public_id() and reads package_absolute_path (not available for
    # synthetic recovery stubs). The ServiceManager methods used in recovery
    # (terminate_service_on_chain_from_safe, unbond_service_on_chain,
    # _execute_recovery_module_flow_from_safe, drain) never read service_public_id.
    # We do NOT call service.store() for the same reason: store() calls self.json
    # which resolves to the overridden Service.json via Python's MRO.
    config_file = svc_path / CONFIG_JSON
    base_data = LocalResource.json.fget(service)  # type: ignore[attr-defined]
    config_file.write_text(
        json.dumps(base_data, indent=2),
        encoding="utf-8",
    )
    return service


def _inject_safe_into_wallet(
    wallet: t.Any,
    chain: Chain,
    safe_address: str,
) -> None:
    """Set ``wallet.safes[chain]`` to *safe_address* and persist.

    The wallet is stored on disk so that ``MasterWalletManager.load()``
    returns the updated state on subsequent calls.

    Parameters
    ----------
    wallet:
        An ``EthereumMasterWallet`` instance.
    chain:
        Chain for which to set the safe address.
    safe_address:
        Checksummed safe address.
    """
    wallet.safes[chain] = safe_address
    if chain not in wallet.safe_chains:
        wallet.safe_chains.append(chain)
    wallet.store()


# ---------------------------------------------------------------------------
# FundRecoveryManager
# ---------------------------------------------------------------------------


class FundRecoveryManager:  # pylint: disable=too-few-public-methods
    """
    Manages the fund-recovery flow for a lost ``.operate`` folder.

    Both ``scan()`` and ``execute()`` accept a raw BIP-39 mnemonic that is
    **never** persisted, logged, or transmitted.
    """

    def __init__(self) -> None:
        """Initialize the manager."""
        self._logger = logging.getLogger("operate.fund_recovery_manager")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(  # pylint: disable=too-many-locals,too-many-nested-blocks,too-many-statements
        self,
        mnemonic: str,
    ) -> FundRecoveryScanResponse:
        """
        Discover all on-chain funds controlled by the derived Master EOA.

        Parameters
        ----------
        mnemonic:
            BIP-39 seed phrase (12, 15, 18, 21, or 24 words).  Never logged or
            stored.

        Returns
        -------
        FundRecoveryScanResponse
        """
        eoa_address = _mnemonic_to_address(mnemonic)

        balances: ChainAmounts = ChainAmounts()
        services: t.List[RecoveredServiceInfo] = []
        gas_warning: t.Dict[str, GasWarningEntry] = {}

        def _scan_chain(
            chain: t.Any,
        ) -> t.Tuple[
            str, t.Dict[str, t.Any], t.List[RecoveredServiceInfo], GasWarningEntry
        ]:
            chain_id = chain.id
            chain_id_str = str(chain_id)
            chain_balances: t.Dict[str, t.Any] = {}
            chain_services: t.List[RecoveredServiceInfo] = []
            chain_gas_warning: GasWarningEntry = GasWarningEntry(insufficient=True)

            try:
                ledger_api = get_default_ledger_api(chain)

                # --- EOA native balance ---
                eoa_native = get_asset_balance(
                    ledger_api=ledger_api,
                    asset_address=ZERO_ADDRESS,
                    address=eoa_address,
                    raise_on_invalid_address=False,
                )
                chain_balances[eoa_address] = {ZERO_ADDRESS: BigInt(eoa_native)}

                # --- ERC-20 balances for EOA ---
                tokens = ERC20_TOKENS_BY_CHAIN_ID.get(chain_id, [])
                for token_addr in tokens:
                    bal = get_asset_balance(
                        ledger_api=ledger_api,
                        asset_address=token_addr,
                        address=eoa_address,
                        raise_on_invalid_address=False,
                    )
                    if bal > 0:
                        chain_balances[eoa_address][token_addr] = BigInt(bal)

                # --- Master Safe discovery ---
                safe_addresses = fetch_safes_for_owner(chain_id, eoa_address)
                for safe_addr in safe_addresses:
                    safe_native = get_asset_balance(
                        ledger_api=ledger_api,
                        asset_address=ZERO_ADDRESS,
                        address=safe_addr,
                        raise_on_invalid_address=False,
                    )
                    chain_balances[safe_addr] = {ZERO_ADDRESS: BigInt(safe_native)}

                    for token_addr in tokens:
                        bal = get_asset_balance(
                            ledger_api=ledger_api,
                            asset_address=token_addr,
                            address=safe_addr,
                            raise_on_invalid_address=False,
                        )
                        if bal > 0:
                            chain_balances[safe_addr][token_addr] = BigInt(bal)

                # --- Service enumeration ---
                try:
                    contract_addresses = CONTRACTS.get(chain)
                    if contract_addresses:
                        service_registry_addr = contract_addresses.get(
                            "service_registry", ""
                        )
                        if service_registry_addr:
                            seen_service_ids: t.Set[int] = set()
                            all_service_ids: t.List[int] = []

                            subgraph_url = SUBGRAPH_URLS.get(chain)
                            if subgraph_url:
                                try:
                                    all_service_ids = _fetch_services_from_subgraph(
                                        subgraph_url, eoa_address
                                    )
                                except Exception as e:  # pylint: disable=broad-except
                                    self._logger.warning(
                                        "Failed to fetch services from subgraph on %s: %s. Falling back to RPC.",
                                        chain.value,
                                        e,
                                    )
                                    subgraph_url = None  # trigger fallback

                            if not subgraph_url:
                                # Fallback: Enumerate services owned by each master safe
                                for safe_addr in safe_addresses:
                                    safe_owned_ids = _enumerate_owned_services(
                                        ledger_api=ledger_api,
                                        service_registry_address=service_registry_addr,
                                        owner_address=safe_addr,
                                    )
                                    all_service_ids.extend(safe_owned_ids)

                            for svc_id in all_service_ids:
                                if svc_id in seen_service_ids:
                                    continue
                                seen_service_ids.add(svc_id)
                                state = _get_service_state(
                                    ledger_api=ledger_api,
                                    service_registry_address=service_registry_addr,
                                    service_id=svc_id,
                                )
                                can_unstake = state in (
                                    OnChainState.DEPLOYED,
                                    OnChainState.TERMINATED_BONDED,
                                )
                                chain_services.append(
                                    RecoveredServiceInfo(
                                        chain_id=chain_id,
                                        service_id=svc_id,
                                        state=state,
                                        can_unstake=can_unstake,
                                    )
                                )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        f"Service enumeration failed for chain {chain_id}: {exc}"
                    )

                # --- Gas warning ---
                chain_gas_warning = _check_gas_warning(
                    chain_id=chain_id,
                    eoa_address=eoa_address,
                    ledger_api=ledger_api,
                )

            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(f"Scan failed for chain {chain_id}: {exc}")

            return chain_id_str, chain_balances, chain_services, chain_gas_warning

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(RECOVERY_CHAINS)
        ) as executor:
            futures = [executor.submit(_scan_chain, chain) for chain in RECOVERY_CHAINS]
            for future in concurrent.futures.as_completed(futures):
                chain_id_str, chain_balances, chain_services, chain_gas_warning = (
                    future.result()
                )
                balances[chain_id_str] = chain_balances
                services.extend(chain_services)
                gas_warning[chain_id_str] = chain_gas_warning

        return FundRecoveryScanResponse(
            master_eoa_address=eoa_address,
            balances=balances,
            services=services,
            gas_warning=gas_warning,
        )

    def execute(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks
        self,
        mnemonic: str,
        destination_address: str,
    ) -> FundRecoveryExecuteResponse:
        """
        Execute the full recovery sequence.

        Recovery steps (per chain, idempotent — re-checks state before each step):
        1. Unstake (if staked)
        2. Terminate service
        3. Unbond
        4. Drain Agent Safe → destination (via recoverAccess on RecoveryModule)
        5. Drain Master Safe → destination
        6. Drain Master EOA → destination

        Parameters
        ----------
        mnemonic:
            BIP-39 seed phrase.  Never logged or stored.
        destination_address:
            The EVM address to receive all recovered funds.

        Returns
        -------
        FundRecoveryExecuteResponse
            HTTP 200 always; ``partial_failure=True`` signals that not all steps
            succeeded so the frontend can offer a retry CTA.
        """
        eoa_address = _mnemonic_to_address(mnemonic)
        errors: t.List[str] = []
        total_funds_moved: ChainAmounts = ChainAmounts()

        try:
            destination_checksum = Web3.to_checksum_address(destination_address)

            # Generate a random password for the temporary account.
            # This password is only used within the temporary directory and is
            # discarded when the context manager exits.
            alphabet = string.ascii_letters + string.digits
            tmp_password = "".join(secrets.choice(alphabet) for _ in range(32))

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                temp_app = OperateApp(home=tmp_path)
                temp_app.create_user_account(password=tmp_password)
                wallet, _ = temp_app.wallet_manager.import_from_mnemonic(
                    LedgerType.ETHEREUM, mnemonic
                )
                svc_manager = temp_app.service_manager()

                def _execute_chain(
                    chain: t.Any,
                ) -> t.Tuple[t.List[str], str, t.Dict[str, t.Dict[str, BigInt]]]:
                    chain_id = chain.id
                    chain_id_str = str(chain_id)
                    chain_errors: t.List[str] = []
                    chain_funds_moved: t.Dict[str, t.Dict[str, BigInt]] = {}

                    try:
                        ledger_api = get_default_ledger_api(chain)
                        contract_addresses = CONTRACTS.get(chain, {})
                        service_registry_addr = (
                            contract_addresses.get("service_registry", "")
                            if contract_addresses
                            else ""
                        )

                        safe_addresses = fetch_safes_for_owner(chain_id, eoa_address)

                        # ── Steps 1–4: Service recovery ────────────────────────────────
                        if service_registry_addr:
                            seen_service_ids: t.Set[int] = set()
                            all_service_ids: t.List[int] = []

                            subgraph_url = SUBGRAPH_URLS.get(chain)
                            if subgraph_url:
                                try:
                                    all_service_ids = _fetch_services_from_subgraph(
                                        subgraph_url, eoa_address
                                    )
                                except Exception:  # pylint: disable=broad-except
                                    subgraph_url = None  # trigger fallback

                            if not subgraph_url:
                                for safe_addr in safe_addresses:
                                    safe_owned_ids = _enumerate_owned_services(
                                        ledger_api=ledger_api,
                                        service_registry_address=service_registry_addr,
                                        owner_address=safe_addr,
                                    )
                                    all_service_ids.extend(safe_owned_ids)

                            # Need the Master EOA's crypto for EOA-based unstake calls
                            private_key = _mnemonic_to_private_key(mnemonic)
                            with tempfile.TemporaryDirectory() as _km_dir:
                                _km = KeysManager(
                                    path=Path(_km_dir), logger=self._logger
                                )
                                crypto = _km.private_key_to_crypto(
                                    private_key, password=None
                                )

                            rpc = get_default_rpc(chain)

                            for svc_id in all_service_ids:
                                if svc_id in seen_service_ids:
                                    continue
                                seen_service_ids.add(svc_id)

                                state = _get_service_state(
                                    ledger_api=ledger_api,
                                    service_registry_address=service_registry_addr,
                                    service_id=svc_id,
                                )

                                # For each Master Safe that may own this service, we need the
                                # wallet injected with that safe before calling ServiceManager.
                                safe_for_service = (
                                    safe_addresses[0] if safe_addresses else None
                                )

                                try:
                                    # Step 1: Unstake (direct EOA tx — we don't know the staking
                                    # program ID upfront, so we can't use ServiceManager here)
                                    _unstake_service(
                                        chain=chain,
                                        ledger_api=ledger_api,
                                        crypto=crypto,
                                        service_id=svc_id,
                                    )
                                    # Refresh state after potential unstake
                                    state = _get_service_state(
                                        ledger_api=ledger_api,
                                        service_registry_address=service_registry_addr,
                                        service_id=svc_id,
                                    )

                                    # Build a synthetic service for ServiceManager methods
                                    service = _build_synthetic_service(
                                        storage=temp_app._services,  # pylint: disable=protected-access
                                        chain=chain,
                                        service_id=svc_id,
                                        rpc=rpc,
                                    )
                                    service_config_id = service.service_config_id
                                    chain_str = chain.value

                                    # Inject the Master Safe so EthSafeTxBuilder can find it
                                    if safe_for_service:
                                        _inject_safe_into_wallet(
                                            wallet=wallet,
                                            chain=chain,
                                            safe_address=safe_for_service,
                                        )

                                    # Step 2: Terminate if DEPLOYED
                                    if state in (OnChainState.DEPLOYED,):
                                        try:
                                            svc_manager.terminate_service_on_chain_from_safe(
                                                service_config_id=service_config_id,
                                                chain=chain_str,
                                            )
                                            state = OnChainState.TERMINATED_BONDED
                                        except (
                                            Exception
                                        ) as exc:  # pylint: disable=broad-except
                                            logger.warning(
                                                "chain=%s service=%s terminate failed: %s",
                                                chain_id,
                                                svc_id,
                                                exc,
                                            )
                                            chain_errors.append(
                                                f"chain={chain_id} service={svc_id} terminate failed: {exc}"
                                            )

                                    # Step 3: Unbond if TERMINATED_BONDED
                                    if state in (OnChainState.TERMINATED_BONDED,):
                                        try:
                                            svc_manager.unbond_service_on_chain(
                                                service_config_id=service_config_id,
                                                chain=chain_str,
                                            )
                                        except (
                                            Exception
                                        ) as exc:  # pylint: disable=broad-except
                                            logger.warning(
                                                "chain=%s service=%s unbond failed: %s",
                                                chain_id,
                                                svc_id,
                                                exc,
                                            )
                                            chain_errors.append(
                                                f"chain={chain_id} service={svc_id} unbond failed: {exc}"
                                            )

                                    # Step 4: Recovery module + drain Agent Safe
                                    try:
                                        svc_manager._execute_recovery_module_flow_from_safe(  # pylint: disable=protected-access
                                            service_config_id=service_config_id,
                                            chain=chain_str,
                                        )
                                    except (
                                        Exception
                                    ) as exc:  # pylint: disable=broad-except
                                        logger.warning(
                                            "chain=%s service=%s recovery module failed: %s",
                                            chain_id,
                                            svc_id,
                                            exc,
                                        )
                                        chain_errors.append(
                                            f"chain={chain_id} service={svc_id} recovery module failed: {exc}"
                                        )

                                    # Step 4b: Drain Agent Safe assets
                                    try:
                                        svc_manager.drain(
                                            service_config_id=service_config_id,
                                            chain_str=chain_str,
                                            withdrawal_address=destination_checksum,
                                        )
                                    except (
                                        Exception
                                    ) as exc:  # pylint: disable=broad-except
                                        logger.warning(
                                            "chain=%s service=%s drain failed: %s",
                                            chain_id,
                                            svc_id,
                                            exc,
                                        )

                                except Exception as exc:  # pylint: disable=broad-except
                                    logger.warning(
                                        "chain=%s service=%s recovery failed: %s",
                                        chain_id,
                                        svc_id,
                                        exc,
                                    )
                                    chain_errors.append(
                                        f"chain={chain_id} service={svc_id}: {type(exc).__name__}"
                                    )
                                finally:
                                    # Remove the injected safe so the next iteration/chain starts clean
                                    if safe_for_service and chain in wallet.safes:
                                        wallet.safes.pop(chain, None)
                                        if chain in wallet.safe_chains:
                                            wallet.safe_chains.remove(chain)
                                        wallet.store()

                        # ── Step 5: Drain Master Safe(s) ─────────────────────────────
                        for safe_addr in safe_addresses:
                            try:
                                _inject_safe_into_wallet(
                                    wallet=wallet,
                                    chain=chain,
                                    safe_address=safe_addr,
                                )
                                moved = wallet.drain(
                                    withdrawal_address=destination_checksum,
                                    chain=chain,
                                    from_safe=True,
                                )
                                for token, amount in moved.items():
                                    prev = chain_funds_moved.get(safe_addr, {}).get(
                                        token, BigInt(0)
                                    )
                                    chain_funds_moved.setdefault(safe_addr, {})[
                                        token
                                    ] = BigInt(int(prev) + amount)
                            except Exception as exc:  # pylint: disable=broad-except
                                logger.warning(
                                    "chain=%s drain_safe=%s failed: %s",
                                    chain_id,
                                    safe_addr,
                                    exc,
                                )
                                chain_errors.append(
                                    f"chain={chain_id} drain_safe={safe_addr}: {type(exc).__name__}"
                                )
                            finally:
                                wallet.safes.pop(chain, None)
                                if chain in wallet.safe_chains:
                                    wallet.safe_chains.remove(chain)
                                wallet.store()

                        # ── Step 6: Drain Master EOA ──────────────────────────────────
                        try:
                            moved = wallet.drain(
                                withdrawal_address=destination_checksum,
                                chain=chain,
                                from_safe=False,
                            )
                            for token, amount in moved.items():
                                prev = chain_funds_moved.get(eoa_address, {}).get(
                                    token, BigInt(0)
                                )
                                chain_funds_moved.setdefault(eoa_address, {})[token] = (
                                    BigInt(int(prev) + amount)
                                )
                        except Exception as exc:  # pylint: disable=broad-except
                            logger.warning(
                                "chain=%s drain_eoa failed: %s", chain_id, exc
                            )
                            chain_errors.append(
                                f"chain={chain_id} drain_eoa: {type(exc).__name__}"
                            )

                    except Exception as exc:  # pylint: disable=broad-except
                        chain_errors.append(f"chain={chain_id}: {type(exc).__name__}")

                    return chain_errors, chain_id_str, chain_funds_moved

                # NOTE: Cannot use ThreadPoolExecutor here because all chains share
                # the same wallet object in the temp_app; concurrent writes to
                # wallet.safes would race. Run chains sequentially.
                for chain in RECOVERY_CHAINS:
                    chain_errs, chain_id_str, chain_moved = _execute_chain(chain)
                    errors.extend(chain_errs)
                    if chain_moved:
                        total_funds_moved[chain_id_str] = chain_moved

        except Exception as exc:  # pylint: disable=broad-except
            errors.append(f"fatal: {type(exc).__name__}: {exc}")

        success = len(errors) == 0
        partial_failure = not success and bool(total_funds_moved)

        return FundRecoveryExecuteResponse(
            success=success,
            partial_failure=partial_failure,
            total_funds_moved=total_funds_moved,
            errors=errors,
        )


def __getattr__(name: str) -> t.Any:
    """Lazy module-level attribute loader.

    Resolves ``OperateApp`` on first access to break the circular import with
    ``operate.cli`` (which imports this module at startup).  The name is then
    cached in the module's ``__dict__`` so subsequent accesses are O(1) and the
    loader is not called again.
    """
    if name == "OperateApp":
        from operate.cli import (
            OperateApp as _OperateApp,  # pylint: disable=import-outside-toplevel
        )

        globals()[name] = _OperateApp
        return _OperateApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
