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
import logging
import secrets
import string
import tempfile
import typing as t
from pathlib import Path

import requests
from aea.helpers.logging import setup_logger
from autonomy.chain.base import registry_contracts
from autonomy.chain.config import ChainType
from autonomy.chain.service import get_service_info
from web3 import Web3

from operate.constants import (
    KEYS_DIR,
    NO_STAKING_PROGRAM_ID,
    SERVICES_DIR,
    WALLETS_DIR,
    ZERO_ADDRESS,
)
from operate.keys import KeysManager
from operate.ledger import get_default_ledger_api, get_default_rpc
from operate.ledger.profiles import (
    CONTRACTS,
    DEFAULT_EOA_THRESHOLD,
    DEFAULT_EOA_TOPUPS,
    ERC20_TOKENS_BY_CHAIN_ID,
    OLAS,
    STAKING,
)
from operate.operate_types import (
    Chain,
    ChainAmounts,
    FundRecoveryExecuteResponse,
    FundRecoveryScanResponse,
    GasWarningEntry,
    LedgerType,
    OnChainState,
    RecoveredServiceInfo,
    ServiceTemplate,
)
from operate.serialization import BigInt
from operate.services.funding_manager import FundingManager
from operate.services.manage import ServiceManager
from operate.services.protocol import StakingManager
from operate.services.service import NON_EXISTENT_MULTISIG
from operate.utils.gnosis import (
    get_asset_balance,
    get_owners,
)
from operate.wallet.master import EthereumMasterWallet, MasterWalletManager

logger = setup_logger(name="operate.fund_recovery_manager")

# ---------------------------------------------------------------------------
# Chain-specific constants
# ---------------------------------------------------------------------------

# Sentinel: lower-cased zero address used to detect un-deployed agent safes.
_ZERO_ADDRESS_LOWER = ZERO_ADDRESS.lower()

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

#: A real IPFS CID used when constructing a synthetic service via
#: ``ServiceManager.create()``.  The downloaded package contents are never
#: accessed during recovery — only ``chain_configs`` and ``agent_addresses``
#: from the resulting Service object are used.
_RECOVERY_SERVICE_HASH = "bafybeifhxeoar5hdwilmnzhy6jf664zqp5lgrzi6lpbkc4qmoqrr24ow4q"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _mnemonic_to_address(mnemonic: str) -> str:
    """Derive the Master EOA address from a BIP-39 mnemonic (no private key stored)."""
    w3 = Web3()
    w3.eth.account.enable_unaudited_hdwallet_features()
    account = w3.eth.account.from_mnemonic(mnemonic)
    return account.address


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


def _get_master_safes_from_contracts(  # pylint: disable=too-many-locals
    chain: Chain,
    ledger_api: t.Any,
    service_registry_address: str,
    eoa_address: str,
    subgraph_url: t.Optional[str],
) -> t.List[str]:
    """Discover MasterSafe addresses for *eoa_address* via on-chain contract lookups.

    Replaces the Safe Transaction Service API dependency in the recovery flow.
    Uses the OLAS subgraph as primary service-ID source, falls back to on-chain
    Transfer-event enumeration, then resolves each service's MasterSafe via
    ``StakingManager.get_current_staking_program`` (handles both staked and
    non-staked cases) and ``StakingManager.service_info`` (staked branch).

    Only safes where *eoa_address* is a confirmed owner are returned.
    """
    safe_addresses: t.Set[str] = set()

    # ── 1. Service ID discovery ──────────────────────────────────────────────
    service_ids: t.List[int] = []
    if subgraph_url:
        try:
            service_ids = _fetch_services_from_subgraph(subgraph_url, eoa_address)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Subgraph query failed in _get_master_safes_from_contracts (%s): %s. "
                "Falling back to on-chain enumeration.",
                subgraph_url,
                exc,
            )
            service_ids = []

    if not service_ids:
        logger.warning(
            "No service IDs found from subgraph for EOA %s; falling back to on-chain enumeration.",
            eoa_address,
        )
        service_ids = _enumerate_owned_services(
            ledger_api=ledger_api,
            service_registry_address=service_registry_address,
            owner_address=eoa_address,
        )

    # ── 2. MasterSafe resolution per service ID ─────────────────────────────
    staking_manager = StakingManager(chain=chain, rpc=get_default_rpc(chain))
    unique_service_ids = list(dict.fromkeys(service_ids))  # deduplicate, preserve order

    for svc_id in unique_service_ids:
        try:
            staking_program_id = staking_manager.get_current_staking_program(svc_id)
            if staking_program_id is None:
                # Not staked: ownerOf(svc_id) is the MasterSafe.
                registry = _get_service_registry_contract(
                    ledger_api, service_registry_address
                )
                master_safe = registry.functions.ownerOf(svc_id).call()
            else:
                # Staked: resolve via service_info wrapper (index 1 = owner = MasterSafe).
                staking_contract = staking_manager.get_staking_contract(
                    staking_program_id
                )
                svc_info = staking_manager.service_info(
                    staking_contract=staking_contract,
                    service_id=svc_id,
                )
                # service_info returns (multisig, owner, nonces, tsStart, reward, inactivity)
                master_safe = svc_info[1]

            if not master_safe or master_safe.lower() == _ZERO_ADDRESS_LOWER:
                logger.warning(
                    "Resolved MasterSafe for service %s is zero address; skipping.",
                    svc_id,
                )
                continue

            master_safe_cs = Web3.to_checksum_address(master_safe)

            # Verify that the recovery EOA is actually an owner of this safe.
            try:
                owners = get_owners(ledger_api=ledger_api, safe=master_safe_cs)
                if eoa_address.lower() not in [o.lower() for o in owners]:
                    logger.warning(
                        "Resolved MasterSafe %s for service %s does not have EOA %s "
                        "as owner; skipping.",
                        master_safe_cs,
                        svc_id,
                        eoa_address,
                    )
                    continue
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to verify ownership of safe %s for service %s: %s; skipping.",
                    master_safe_cs,
                    svc_id,
                    exc,
                )
                continue

            safe_addresses.add(master_safe_cs)

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Failed to resolve MasterSafe for service %s: %s",
                svc_id,
                exc,
            )

    return list(safe_addresses)


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


def _inject_safe_into_wallet(
    wallet: EthereumMasterWallet,
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
                _contract_addrs_for_safe = CONTRACTS.get(chain)
                _service_registry_addr_for_safe = (
                    _contract_addrs_for_safe.get("service_registry", "")
                    if _contract_addrs_for_safe
                    else ""
                )
                if _service_registry_addr_for_safe:
                    safe_addresses = _get_master_safes_from_contracts(
                        chain=chain,
                        ledger_api=ledger_api,
                        service_registry_address=_service_registry_addr_for_safe,
                        eoa_address=eoa_address,
                        subgraph_url=SUBGRAPH_URLS.get(chain),
                    )
                else:
                    self._logger.warning(
                        "Service registry address not found for chain %s", chain.value
                    )
                    safe_addresses = []
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
                            else:
                                self._logger.warning(
                                    "No subgraph URL configured for chain %s; falling back to on-chain enumeration.",
                                    chain.value,
                                )

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
                                    continue  # pragma: no cover  -- unreachable in practice
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

                                # Discover staked OLAS locked in a staking contract.
                                try:
                                    staking_manager = StakingManager(
                                        chain=chain,
                                        rpc=get_default_rpc(chain),
                                    )
                                    staking_program_id = (
                                        staking_manager.get_current_staking_program(
                                            svc_id
                                        )
                                    )
                                    if staking_program_id is not None:
                                        staking_contract = STAKING[chain].get(
                                            staking_program_id
                                        )
                                        if staking_contract:
                                            staking_params = (
                                                staking_manager.get_staking_params(
                                                    staking_contract
                                                )
                                            )
                                            staked_olas = (
                                                staking_params["min_staking_deposit"]
                                                * 2
                                            )
                                            if staked_olas > 0:
                                                olas_address = OLAS.get(chain)
                                                if olas_address:
                                                    staking_contract_cs = (
                                                        Web3.to_checksum_address(
                                                            staking_contract
                                                        )
                                                    )
                                                    if (
                                                        staking_contract_cs
                                                        not in chain_balances
                                                    ):
                                                        chain_balances[
                                                            staking_contract_cs
                                                        ] = {}
                                                    chain_balances[staking_contract_cs][
                                                        olas_address
                                                    ] = BigInt(staked_olas)
                                                else:
                                                    self._logger.warning(
                                                        "OLAS token address not found for chain %s; skipping staked OLAS balance.",
                                                        chain_id,
                                                    )
                                            else:
                                                self._logger.info(
                                                    "Service %s on chain %s is staked but has zero staked OLAS; skipping staking balance check.",
                                                    svc_id,
                                                    chain_id,
                                                )
                                        else:
                                            self._logger.warning(
                                                "Staking contract not found for program ID %s on chain %s; skipping staking balance check.",
                                                staking_program_id,
                                                chain_id,
                                            )
                                    else:
                                        self._logger.info(
                                            "Service %s on chain %s is not staked; skipping staking balance check.",
                                            svc_id,
                                            chain_id,
                                        )
                                except (  # pylint: disable=broad-except
                                    Exception
                                ) as _staking_exc:
                                    self._logger.warning(
                                        "Failed to fetch staked OLAS for service %s on chain %s: %s",
                                        svc_id,
                                        chain_id,
                                        _staking_exc,
                                    )

                                # Fetch agent safe (multisig) balances so the
                                # scan result includes all recoverable funds.
                                try:
                                    _svc_info = get_service_info(
                                        ledger_api=ledger_api,
                                        chain_type=ChainType(chain.value),
                                        token_id=svc_id,
                                    )
                                    _agent_safe = _svc_info[1]
                                except (  # pylint: disable=broad-except
                                    Exception
                                ) as _svc_info_exc:
                                    logger.warning(
                                        "Failed to fetch service info for service %s on chain %s: %s",
                                        svc_id,
                                        chain_id,
                                        _svc_info_exc,
                                    )
                                    _agent_safe = ZERO_ADDRESS
                                if (
                                    _agent_safe
                                    and _agent_safe.lower() != _ZERO_ADDRESS_LOWER
                                    and _agent_safe not in chain_balances
                                ):
                                    _agent_safe_cs = Web3.to_checksum_address(
                                        _agent_safe
                                    )
                                    _agent_native = get_asset_balance(
                                        ledger_api=ledger_api,
                                        asset_address=ZERO_ADDRESS,
                                        address=_agent_safe_cs,
                                        raise_on_invalid_address=False,
                                    )
                                    chain_balances[_agent_safe_cs] = {
                                        ZERO_ADDRESS: BigInt(_agent_native)
                                    }
                                    for token_addr in tokens:
                                        _agent_tok_bal = get_asset_balance(
                                            ledger_api=ledger_api,
                                            asset_address=token_addr,
                                            address=_agent_safe_cs,
                                            raise_on_invalid_address=False,
                                        )
                                        if _agent_tok_bal > 0:
                                            chain_balances[_agent_safe_cs][
                                                token_addr
                                            ] = BigInt(_agent_tok_bal)
                                else:
                                    self._logger.warning(
                                        "AgentSafe %s on chain %s is zero address or already tracked; skipping balance fetch.",
                                        _agent_safe,
                                        chain_id,
                                    )
                        else:
                            self._logger.warning(  # pragma: no cover  -- impossible: else requires truthy zero address
                                "Resolved AgentSafe for service %s is zero address; skipping.",
                                svc_id,
                            )
                    else:
                        self._logger.warning(
                            "No contract addresses configured for chain %s; skipping service enumeration.",
                            chain.value,
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    self._logger.warning(
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
                keys_manager = KeysManager(
                    path=tmp_path / KEYS_DIR,
                    logger=logger,
                    password=tmp_password,
                )
                wallet_manager = MasterWalletManager(
                    path=tmp_path / WALLETS_DIR,
                    password=tmp_password,
                ).setup()
                funding_manager = FundingManager(
                    keys_manager=keys_manager,
                    wallet_manager=wallet_manager,
                    logger=logger,
                )
                svc_manager = ServiceManager(
                    path=tmp_path / SERVICES_DIR,
                    keys_manager=keys_manager,
                    wallet_manager=wallet_manager,
                    funding_manager=funding_manager,
                    logger=logger,
                )
                svc_manager.setup()

                wallet, _ = wallet_manager.import_from_mnemonic(
                    LedgerType.ETHEREUM, mnemonic
                )

                for chain in RECOVERY_CHAINS:
                    chain_id = chain.id
                    chain_id_str = str(chain_id)
                    chain_funds_moved: t.Dict[str, t.Dict[str, BigInt]] = {}

                    try:
                        ledger_api = wallet.ledger_api(chain=chain)
                        contract_addresses = CONTRACTS.get(chain, {})  # type: ignore[assignment]
                        service_registry_addr = (
                            contract_addresses.get("service_registry", "")
                            if contract_addresses
                            else ""
                        )
                        chain_str = chain.value
                        rpc = get_default_rpc(chain)
                        safe_addresses = (
                            _get_master_safes_from_contracts(
                                chain=chain,
                                ledger_api=ledger_api,
                                service_registry_address=service_registry_addr,
                                eoa_address=eoa_address,
                                subgraph_url=SUBGRAPH_URLS.get(chain),
                            )
                            if service_registry_addr
                            else []
                        )

                        # Iterate per-safe: inject the safe into the wallet once, run
                        # all service recovery steps under it, then drain it before
                        # moving to the next safe.  This avoids per-service injection
                        # noise and keeps the manager calls simple.
                        for safe_addr in safe_addresses:
                            # ── Inject safe ──────────────────────────────────────────
                            _inject_safe_into_wallet(
                                wallet=wallet,
                                chain=chain,
                                safe_address=safe_addr,
                            )

                            try:
                                # ── Service recovery (Steps 1–4) ─────────────────────
                                if service_registry_addr:
                                    all_service_ids: t.Set[int] = set()

                                    subgraph_url = SUBGRAPH_URLS.get(chain)
                                    if subgraph_url:
                                        try:
                                            all_service_ids = set(
                                                _fetch_services_from_subgraph(
                                                    subgraph_url, eoa_address
                                                )
                                            )
                                        except (  # pylint: disable=broad-except
                                            Exception
                                        ):
                                            subgraph_url = None  # trigger fallback

                                    if not subgraph_url:
                                        all_service_ids.update(
                                            _enumerate_owned_services(
                                                ledger_api=ledger_api,
                                                service_registry_address=service_registry_addr,
                                                owner_address=safe_addr,
                                            )
                                        )

                                    for svc_id in all_service_ids:
                                        try:
                                            service = svc_manager.create(
                                                service_template=ServiceTemplate(
                                                    name=f"recovery-stub-{svc_id}",
                                                    hash=_RECOVERY_SERVICE_HASH,
                                                    description="",
                                                    home_chain=chain_str,
                                                    configurations={
                                                        chain_str: {
                                                            "staking_program_id": NO_STAKING_PROGRAM_ID,
                                                            "nft": "",
                                                            "rpc": rpc,
                                                            "agent_id": 1,
                                                            "cost_of_bond": 0,
                                                            "fund_requirements": {},
                                                            "fallback_chain_params": None,
                                                        }
                                                    },
                                                    env_variables={},
                                                    agent_release={
                                                        "is_aea": False,
                                                        "repository": {
                                                            "owner": "",
                                                            "name": "",
                                                            "version": "",
                                                        },
                                                    },
                                                ),
                                                agent_addresses=[],
                                            )
                                            # Patch in the real on-chain token ID and
                                            # the current Safe address, then re-persist
                                            # so downstream svc_manager calls that
                                            # reload via self.load() see the correct
                                            # values.
                                            chain_config = service.chain_configs[
                                                chain_str
                                            ]
                                            chain_config.chain_data.token = svc_id
                                            # Fetch the agent safe (multisig) on-chain.
                                            # get_service_info returns ServiceInfo tuple;
                                            # index 1 is the multisig / agent safe address.
                                            try:
                                                _svc_info = get_service_info(
                                                    ledger_api=ledger_api,
                                                    chain_type=ChainType(chain.value),
                                                    token_id=svc_id,
                                                )
                                                _agent_safe = _svc_info[1]
                                            except (  # pylint: disable=broad-except
                                                Exception
                                            ):
                                                _agent_safe = ZERO_ADDRESS
                                            if _agent_safe == ZERO_ADDRESS:
                                                chain_config.chain_data.multisig = (
                                                    NON_EXISTENT_MULTISIG
                                                )
                                            else:
                                                chain_config.chain_data.multisig = (
                                                    Web3.to_checksum_address(
                                                        _agent_safe
                                                    )
                                                )
                                            service.store()
                                            service_config_id = (
                                                service.service_config_id
                                            )

                                            # Step 1-3: terminate (handles unstake +
                                            # terminate + unbond internally)
                                            try:
                                                svc_manager.terminate_service_on_chain_from_safe(
                                                    service_config_id=service_config_id,
                                                    chain=chain_str,
                                                )
                                            except (  # pylint: disable=broad-except
                                                Exception
                                            ) as exc:
                                                logger.warning(
                                                    "chain=%s service=%s terminate failed: %s",
                                                    chain_id,
                                                    svc_id,
                                                    exc,
                                                )
                                                errors.append(
                                                    f"chain={chain_id} service={svc_id} terminate failed: {exc}"
                                                )

                                            # Step 4: Recovery module flow
                                            try:
                                                svc_manager._execute_recovery_module_flow_from_safe(  # pylint: disable=protected-access
                                                    service_config_id=service_config_id,
                                                    chain=chain_str,
                                                )
                                            except (  # pylint: disable=broad-except
                                                Exception
                                            ) as exc:
                                                logger.warning(
                                                    "chain=%s service=%s recovery module failed: %s",
                                                    chain_id,
                                                    svc_id,
                                                    exc,
                                                )
                                                errors.append(
                                                    f"chain={chain_id} service={svc_id} recovery module failed: {exc}"
                                                )

                                            # Step 4b: Drain Agent Safe assets
                                            try:
                                                svc_manager.drain(
                                                    service_config_id=service_config_id,
                                                    chain_str=chain_str,
                                                    withdrawal_address=destination_checksum,
                                                )
                                            except (  # pylint: disable=broad-except
                                                Exception
                                            ) as exc:
                                                logger.warning(
                                                    "chain=%s service=%s drain failed: %s",
                                                    chain_id,
                                                    svc_id,
                                                    exc,
                                                )
                                                errors.append(
                                                    f"chain={chain_id} service={svc_id} drain failed: {exc}"
                                                )

                                        except (  # pylint: disable=broad-except
                                            Exception
                                        ) as exc:
                                            logger.warning(
                                                "chain=%s service=%s recovery failed: %s",
                                                chain_id,
                                                svc_id,
                                                exc,
                                            )
                                            errors.append(
                                                f"chain={chain_id} service={svc_id}: {type(exc).__name__}"
                                            )

                                # ── Step 5: Drain this Master Safe ────────────────────
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
                                    "chain=%s safe=%s drain_safe failed: %s",
                                    chain_id,
                                    safe_addr,
                                    exc,
                                )
                                errors.append(
                                    f"chain={chain_id} safe={safe_addr} drain_safe: {type(exc).__name__}"
                                )
                            finally:
                                # Always remove the injected safe before moving on
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
                            errors.append(
                                f"chain={chain_id} drain_eoa: {type(exc).__name__}"
                            )

                    except Exception as exc:  # pylint: disable=broad-except
                        errors.append(f"chain={chain_id}: {type(exc).__name__}")

                    if chain_funds_moved:
                        total_funds_moved[chain_id_str] = chain_funds_moved

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
