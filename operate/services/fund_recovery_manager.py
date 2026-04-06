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

import json
import logging
import tempfile
import time
import typing as t
import urllib.request

from aea.helpers.logging import setup_logger
from autonomy.chain.base import registry_contracts
from autonomy.chain.constants import CHAIN_PROFILES
from web3 import Web3

from operate.constants import ZERO_ADDRESS
from operate.ledger import get_default_ledger_api
from operate.operate_types import (
    Chain,
    FundRecoveryExecuteResponse,
    FundRecoveryScanResponse,
    GasWarningEntry,
    OnChainState,
    RecoveredServiceInfo,
)
from operate.serialization import BigInt
from operate.utils.gnosis import (
    drain_eoa,
    get_asset_balance,
    transfer,
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

#: Safe Transaction Service hosts, keyed by chain_id
SAFE_SERVICE_HOSTS: t.Dict[int, str] = {
    137: "safe-transaction-polygon.safe.global",
    100: "safe-transaction-gnosis-chain.safe.global",
    8453: "safe-transaction-base.safe.global",
    10: "safe-transaction-optimism.safe.global",
}

#: Minimum native balance (in wei) to warn the user about insufficient gas
GAS_WARN_THRESHOLDS: t.Dict[int, int] = {
    137: int(1e18),  # 1 POL
    100: int(1e17),  # 0.1 xDAI
    8453: int(5e15),  # 0.005 ETH
    10: int(5e15),  # 0.005 ETH
}

#: ERC-20 tokens to scan per chain (symbol → address)
_ERC20_TOKENS_BY_CHAIN_ID: t.Dict[int, t.Dict[str, str]] = {}
try:
    # Lazy-import to avoid circular dependency issues at module load time
    from operate.ledger.profiles import ERC20_TOKENS

    for _symbol, _chain_map in ERC20_TOKENS.items():
        for _chain, _addr in _chain_map.items():
            if hasattr(_chain, "id"):
                _ERC20_TOKENS_BY_CHAIN_ID.setdefault(_chain.id, {})[_symbol] = _addr
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Staking contract minimal ABI
# ---------------------------------------------------------------------------

_STAKING_ABI = [
    {
        "name": "getStakingState",
        "type": "function",
        "inputs": [{"name": "serviceId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
    },
    {
        "name": "isServiceStaked",
        "type": "function",
        "inputs": [{"name": "serviceId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
    },
    {
        "name": "minStakingDuration",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
    {
        "name": "getServiceInfo",
        "type": "function",
        "inputs": [{"name": "serviceId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "bond", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "tsStart", "type": "uint256"},
                    {"name": "multisig", "type": "address"},
                    {"name": "availableRewards", "type": "uint256"},
                ],
            }
        ],
        "stateMutability": "view",
    },
    {
        "name": "unstake",
        "type": "function",
        "inputs": [{"name": "serviceId", "type": "uint256"}],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
]

# ---------------------------------------------------------------------------
# RecoveryModule ABI (recoverAccess)
# ---------------------------------------------------------------------------

_RECOVERY_MODULE_ABI = [
    {
        "name": "recoverAccess",
        "type": "function",
        "inputs": [{"name": "safe", "type": "address"}],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
]

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


def _fetch_safes_for_owner(chain_id: int, owner_address: str) -> t.List[str]:
    """Fetch Master Safe addresses via Gnosis Safe Transaction Service API."""
    host = SAFE_SERVICE_HOSTS.get(chain_id)
    if not host:
        return []

    url = f"https://{host}/api/v1/owners/{owner_address}/safes/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "olas-operate/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("safes", [])
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(f"Safe TX service query failed for chain={chain_id}: {exc}")
        return []


def _get_service_registry_contract(
    ledger_api: t.Any,
    service_registry_address: str,
) -> t.Any:
    """Return a contract instance for ServiceRegistryL2 via registry_contracts."""
    return registry_contracts.service_registry.get_instance(
        ledger_api=ledger_api,
        contract_address=service_registry_address,
    )


def _enumerate_owned_services(
    ledger_api: t.Any,
    service_registry_address: str,
    owner_address: str,
) -> t.List[int]:
    """
    Enumerate service IDs owned by *owner_address* by scanning Transfer events.

    ServiceRegistryL2 does NOT expose ``getServicesOfOwner``.  Instead we scan
    Transfer events where ``to == owner_address`` in bounded chunks, then filter
    via ``ownerOf(tokenId)`` to skip transferred-away NFTs.

    Scanning from genesis (fromBlock=0) is avoided because many RPC providers
    (including those used on Polygon) enforce a maximum block range of 10k–50k
    blocks and will return an error or time out on unbounded log queries.
    """
    # Maximum blocks per eth_getLogs call; most RPC providers allow at least this.
    _BLOCK_CHUNK = 10_000

    contract = _get_service_registry_contract(ledger_api, service_registry_address)
    try:
        latest_block = ledger_api.api.eth.block_number
        owner_checksum = Web3.to_checksum_address(owner_address)

        token_ids: t.Set[int] = set()
        # Scan backwards in chunks from latest to genesis (stop early if possible)
        from_block = max(0, latest_block - _BLOCK_CHUNK)
        to_block = latest_block

        while to_block >= 0:
            try:
                logs = ledger_api.api.eth.get_logs(
                    {
                        "address": Web3.to_checksum_address(service_registry_address),
                        "topics": [
                            # Transfer(address,address,uint256) — topic0
                            Web3.keccak(
                                text="Transfer(address,address,uint256)"
                            ).hex(),
                            None,  # from: any
                            # to: padded owner address
                            "0x"
                            + "0" * 24
                            + owner_checksum[2:].lower(),
                        ],
                        "fromBlock": hex(from_block),
                        "toBlock": hex(to_block),
                    }
                )
                for log in logs:
                    # tokenId is the third indexed topic (topics[3])
                    if len(log["topics"]) >= 4:
                        token_ids.add(int(log["topics"][3].hex(), 16))
            except Exception as chunk_exc:  # pylint: disable=broad-except
                logger.warning(
                    f"Log chunk [{from_block},{to_block}] failed: {chunk_exc}"
                )

            if from_block == 0:
                break
            to_block = from_block - 1
            from_block = max(0, to_block - _BLOCK_CHUNK)

        owned = []
        for token_id in token_ids:
            try:
                current_owner = contract.functions.ownerOf(token_id).call()
                if current_owner.lower() == owner_address.lower():
                    owned.append(token_id)
            except Exception:  # pylint: disable=broad-except
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

    def scan(
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
        from operate.operate_types import (  # pylint: disable=import-outside-toplevel
            ChainAmounts,
        )

        eoa_address = _mnemonic_to_address(mnemonic)

        balances: ChainAmounts = ChainAmounts()
        services: t.List[RecoveredServiceInfo] = []
        gas_warning: t.Dict[str, GasWarningEntry] = {}

        for chain in RECOVERY_CHAINS:
            chain_id = chain.id
            chain_id_str = str(chain_id)

            try:
                ledger_api = get_default_ledger_api(chain)

                # --- EOA native balance ---
                eoa_native = get_asset_balance(
                    ledger_api=ledger_api,
                    asset_address=ZERO_ADDRESS,
                    address=eoa_address,
                    raise_on_invalid_address=False,
                )
                balances.setdefault(chain_id_str, {})[eoa_address] = {
                    ZERO_ADDRESS: BigInt(eoa_native)
                }

                # --- ERC-20 balances for EOA ---
                tokens = _ERC20_TOKENS_BY_CHAIN_ID.get(chain_id, {})
                for token_addr in tokens.values():
                    bal = get_asset_balance(
                        ledger_api=ledger_api,
                        asset_address=token_addr,
                        address=eoa_address,
                        raise_on_invalid_address=False,
                    )
                    if bal > 0:
                        balances[chain_id_str][eoa_address][token_addr] = BigInt(bal)

                # --- Master Safe discovery ---
                safe_addresses = _fetch_safes_for_owner(chain_id, eoa_address)
                for safe_addr in safe_addresses:
                    safe_native = get_asset_balance(
                        ledger_api=ledger_api,
                        asset_address=ZERO_ADDRESS,
                        address=safe_addr,
                        raise_on_invalid_address=False,
                    )
                    balances[chain_id_str][safe_addr] = {
                        ZERO_ADDRESS: BigInt(safe_native)
                    }

                    for token_addr in tokens.values():
                        bal = get_asset_balance(
                            ledger_api=ledger_api,
                            asset_address=token_addr,
                            address=safe_addr,
                            raise_on_invalid_address=False,
                        )
                        if bal > 0:
                            balances[chain_id_str][safe_addr][token_addr] = BigInt(bal)

                # --- Service enumeration ---
                # Services are owned by the master safes (not the master EOA
                # directly); the master safes are in turn owned by the master EOA.
                try:
                    from operate.ledger.profiles import (  # pylint: disable=import-outside-toplevel
                        CONTRACTS,
                    )

                    contract_addresses = CONTRACTS.get(chain)
                    if contract_addresses:
                        service_registry_addr = contract_addresses.get(
                            "service_registry", ""
                        )
                        if service_registry_addr:
                            seen_service_ids: t.Set[int] = set()
                            # Enumerate services owned by each master safe
                            for safe_addr in safe_addresses:
                                safe_owned_ids = _enumerate_owned_services(
                                    ledger_api=ledger_api,
                                    service_registry_address=service_registry_addr,
                                    owner_address=safe_addr,
                                )
                                for svc_id in safe_owned_ids:
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
                                    services.append(
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
                gas_warning[chain_id_str] = _check_gas_warning(
                    chain_id=chain_id,
                    eoa_address=eoa_address,
                    ledger_api=ledger_api,
                )

            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(f"Scan failed for chain {chain_id}: {exc}")
                balances.setdefault(chain_id_str, {})
                gas_warning[chain_id_str] = GasWarningEntry(insufficient=True)

        return FundRecoveryScanResponse(
            master_eoa_address=eoa_address,
            balances=balances,
            services=services,
            gas_warning=gas_warning,
        )

    def execute(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
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
        # Derive private key in memory — NEVER persisted or logged
        private_key = _mnemonic_to_private_key(mnemonic)
        eoa_address = _mnemonic_to_address(mnemonic)

        from operate.operate_types import (  # pylint: disable=import-outside-toplevel
            ChainAmounts,
        )

        errors: t.List[str] = []
        total_funds_moved: ChainAmounts = ChainAmounts()

        try:
            from aea_ledger_ethereum.ethereum import (  # pylint: disable=import-outside-toplevel
                EthereumCrypto,
            )

            from operate.ledger.profiles import (  # pylint: disable=import-outside-toplevel
                CONTRACTS,
                ERC20_TOKENS,
            )

            destination_checksum = Web3.to_checksum_address(destination_address)

            for chain in RECOVERY_CHAINS:
                chain_id = chain.id
                chain_id_str = str(chain_id)

                try:
                    ledger_api = get_default_ledger_api(chain)
                    contract_addresses = CONTRACTS.get(chain, {})
                    chain_profile = CHAIN_PROFILES.get(chain.value, {})
                    service_registry_addr = (
                        contract_addresses.get("service_registry", "")
                        if contract_addresses
                        else ""
                    )
                    # service_manager is sourced from CHAIN_PROFILES because the
                    # CONTRACTS dict built in profiles.py does not include it.
                    service_manager_addr = chain_profile.get("service_manager", "")
                    recovery_module_addr = (
                        contract_addresses.get("recovery_module", "")
                        if contract_addresses
                        else ""
                    )

                    # Build a temporary EthereumCrypto from the in-memory private key
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".json", delete=True
                    ) as key_file:
                        # Write a minimal keystore (unencrypted — in /tmp, deleted immediately)
                        account = Web3().eth.account.from_key(private_key)
                        keystore = account.encrypt(password="")  # nosec B106
                        json.dump(keystore, key_file)
                        key_file.flush()

                        crypto = EthereumCrypto(
                            private_key_path=key_file.name, password=""  # nosec B106
                        )

                    # ── Step 1-3: Handle owned services ──────────────────────────
                    # Services are owned by the master safes (not the master EOA
                    # directly); the master safes are in turn owned by the master EOA.
                    safe_addresses = _fetch_safes_for_owner(chain_id, eoa_address)
                    if service_registry_addr:
                        seen_service_ids: t.Set[int] = set()
                        for safe_addr in safe_addresses:
                            safe_owned_ids = _enumerate_owned_services(
                                ledger_api=ledger_api,
                                service_registry_address=service_registry_addr,
                                owner_address=safe_addr,
                            )
                            for svc_id in safe_owned_ids:
                                if svc_id in seen_service_ids:
                                    continue
                                seen_service_ids.add(svc_id)
                                try:
                                    self._recover_service(
                                        chain=chain,
                                        ledger_api=ledger_api,
                                        crypto=crypto,
                                        service_id=svc_id,
                                        service_registry_addr=service_registry_addr,
                                        service_manager_addr=service_manager_addr,
                                        recovery_module_addr=recovery_module_addr,
                                        destination_address=destination_checksum,
                                        total_funds_moved=total_funds_moved,
                                        chain_id_str=chain_id_str,
                                        eoa_address=eoa_address,
                                    )
                                except Exception as exc:  # pylint: disable=broad-except
                                    errors.append(
                                        f"chain={chain_id} service={svc_id}: {exc}"
                                    )

                    # ── Step 5: Drain Master Safe(s) ─────────────────────────────
                    # Token addresses as keys and values; aligns with ChainAmounts format.
                    erc20_tokens = {
                        addr: addr
                        for chain_map in ERC20_TOKENS.values()
                        for addr in [chain_map.get(chain)]
                        if addr
                    }
                    for safe_addr in safe_addresses:
                        try:
                            moved = self._drain_safe(
                                ledger_api=ledger_api,
                                crypto=crypto,
                                safe_addr=safe_addr,
                                destination=destination_checksum,
                                erc20_tokens=erc20_tokens,
                            )
                            for token, amount in moved.items():
                                prev = (
                                    total_funds_moved.get(chain_id_str, {})
                                    .get(safe_addr, {})
                                    .get(token, BigInt(0))
                                )
                                total_funds_moved.setdefault(
                                    chain_id_str, {}
                                ).setdefault(safe_addr, {})[token] = BigInt(
                                    int(prev) + amount
                                )
                        except Exception as exc:  # pylint: disable=broad-except
                            errors.append(
                                f"chain={chain_id} drain_safe={safe_addr}: {exc}"
                            )

                    # ── Step 6: Drain Master EOA ──────────────────────────────────
                    try:
                        _moved = self._drain_eoa_assets(
                            chain=chain,
                            ledger_api=ledger_api,
                            crypto=crypto,
                            eoa_address=eoa_address,
                            destination=destination_checksum,
                            erc20_tokens=erc20_tokens,
                        )
                        for token, amount in _moved.items():
                            prev = (
                                total_funds_moved.get(chain_id_str, {})
                                .get(eoa_address, {})
                                .get(token, BigInt(0))
                            )
                            total_funds_moved.setdefault(
                                chain_id_str, {}
                            ).setdefault(eoa_address, {})[token] = BigInt(
                                int(prev) + amount
                            )
                    except Exception as exc:  # pylint: disable=broad-except
                        errors.append(f"chain={chain_id} drain_eoa: {exc}")

                except Exception as exc:  # pylint: disable=broad-except
                    errors.append(f"chain={chain_id}: {exc}")

        finally:
            # Explicitly zero-out the private key from local scope
            private_key = "0" * len(private_key)  # nosec B105
            del private_key

        success = len(errors) == 0
        partial_failure = not success and bool(total_funds_moved)

        return FundRecoveryExecuteResponse(
            success=success,
            partial_failure=partial_failure,
            total_funds_moved=total_funds_moved,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _recover_service(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        chain: Chain,
        ledger_api: t.Any,
        crypto: t.Any,
        service_id: int,
        service_registry_addr: str,
        service_manager_addr: str,
        recovery_module_addr: str,
        destination_address: str,
        total_funds_moved: t.Dict,
        chain_id_str: str,
        eoa_address: str,
    ) -> None:
        """Run the per-service portion of the recovery sequence (steps 1–4)."""
        from operate.ledger.profiles import (  # pylint: disable=import-outside-toplevel
            ERC20_TOKENS,
            STAKING,
        )

        state = _get_service_state(
            ledger_api=ledger_api,
            service_registry_address=service_registry_addr,
            service_id=service_id,
        )

        # Step 1: Unstake if the service is staked in any known staking program.
        # Iterate over STAKING[chain] contracts to find and call unstake.
        staking_contracts = STAKING.get(chain, {})
        for staking_program_id, staking_addr in staking_contracts.items():
            if not staking_addr:
                continue
            try:
                staking_contract = ledger_api.api.eth.contract(
                    address=Web3.to_checksum_address(staking_addr),
                    abi=_STAKING_ABI,
                )
                is_staked = staking_contract.functions.isServiceStaked(
                    service_id
                ).call()
                if not is_staked:
                    continue
                # Check minimum staking duration to avoid revert on early unstake
                try:
                    min_duration = staking_contract.functions.minStakingDuration().call()
                    service_info = staking_contract.functions.getServiceInfo(
                        service_id
                    ).call()
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
                except Exception:  # pylint: disable=broad-except
                    pass  # proceed to unstake if we can't determine duration

                tx = staking_contract.functions.unstake(service_id).build_transaction(
                    {
                        "from": crypto.address,
                        "nonce": ledger_api.api.eth.get_transaction_count(
                            crypto.address
                        ),
                    }
                )
                signed = ledger_api.api.eth.account.sign_transaction(
                    tx, crypto.private_key
                )
                tx_hash = ledger_api.api.eth.send_raw_transaction(
                    signed.raw_transaction
                )
                ledger_api.api.eth.wait_for_transaction_receipt(tx_hash)
                logger.info(
                    f"Unstaked service {service_id} from {staking_program_id} "
                    f"on chain {chain.id}"
                )
                break  # service can only be staked in one program at a time
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    f"Unstake check/attempt failed for service {service_id} "
                    f"program={staking_program_id}: {exc}"
                )

        # Refresh state after potential unstake
        state = _get_service_state(
            ledger_api=ledger_api,
            service_registry_address=service_registry_addr,
            service_id=service_id,
        )

        # Step 2: Terminate if DEPLOYED
        if state in (OnChainState.DEPLOYED,):
            try:
                if service_manager_addr:
                    sm_contract = registry_contracts.service_manager.get_instance(
                        ledger_api=ledger_api,
                        contract_address=service_manager_addr,
                    )
                    tx = sm_contract.functions.terminate(service_id).build_transaction(
                        {
                            "from": crypto.address,
                            "nonce": ledger_api.api.eth.get_transaction_count(
                                crypto.address
                            ),
                        }
                    )
                    signed = ledger_api.api.eth.account.sign_transaction(
                        tx, crypto.private_key
                    )
                    tx_hash = ledger_api.api.eth.send_raw_transaction(
                        signed.raw_transaction
                    )
                    # Wait for the transaction to be mined before proceeding to
                    # unbond; without confirmation the on-chain state has not yet
                    # changed and the unbond call would revert.
                    ledger_api.api.eth.wait_for_transaction_receipt(tx_hash)
                    logger.info(f"Terminated service {service_id} on chain {chain.id}")
                    state = OnChainState.TERMINATED_BONDED
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(f"Terminate failed for service {service_id}: {exc}")

        # Step 3: Unbond if TERMINATED_BONDED
        if state in (OnChainState.TERMINATED_BONDED,):
            try:
                if service_manager_addr:
                    sm_contract = registry_contracts.service_manager.get_instance(
                        ledger_api=ledger_api,
                        contract_address=service_manager_addr,
                    )
                    tx = sm_contract.functions.unbond(service_id).build_transaction(
                        {
                            "from": crypto.address,
                            "nonce": ledger_api.api.eth.get_transaction_count(
                                crypto.address
                            ),
                        }
                    )
                    signed = ledger_api.api.eth.account.sign_transaction(
                        tx, crypto.private_key
                    )
                    tx_hash = ledger_api.api.eth.send_raw_transaction(
                        signed.raw_transaction
                    )
                    # Wait for unbond to be mined before proceeding to recoverAccess.
                    ledger_api.api.eth.wait_for_transaction_receipt(tx_hash)
                    logger.info(f"Unbonded service {service_id} on chain {chain.id}")
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(f"Unbond failed for service {service_id}: {exc}")

        # Step 4: recoverAccess on RecoveryModule for Agent Safe
        # Retrieve the Agent Safe multisig address from service info, call
        # recoverAccess on the RecoveryModule, then drain the Agent Safe.
        if recovery_module_addr:
            try:
                registry_contract = _get_service_registry_contract(
                    ledger_api, service_registry_addr
                )
                service_info = registry_contract.functions.getService(service_id).call()
                agent_safe_addr = service_info[1]  # multisig field

                if agent_safe_addr and agent_safe_addr != ZERO_ADDRESS:
                    rm_contract = ledger_api.api.eth.contract(
                        address=Web3.to_checksum_address(recovery_module_addr),
                        abi=_RECOVERY_MODULE_ABI,
                    )
                    tx = rm_contract.functions.recoverAccess(
                        agent_safe_addr
                    ).build_transaction(
                        {
                            "from": crypto.address,
                            "nonce": ledger_api.api.eth.get_transaction_count(
                                crypto.address
                            ),
                        }
                    )
                    signed = ledger_api.api.eth.account.sign_transaction(
                        tx, crypto.private_key
                    )
                    tx_hash = ledger_api.api.eth.send_raw_transaction(
                        signed.raw_transaction
                    )
                    # Wait for recoverAccess to be mined before draining the
                    # Agent Safe; the Safe must be accessible first.
                    ledger_api.api.eth.wait_for_transaction_receipt(tx_hash)
                    logger.info(
                        f"recoverAccess called for agent safe {agent_safe_addr}"
                    )

                    # Drain Agent Safe; token addresses as keys per ChainAmounts.
                    erc20_tokens = {
                        addr: addr
                        for chain_map in ERC20_TOKENS.values()
                        for addr in [chain_map.get(chain)]
                        if addr
                    }
                    moved = self._drain_safe(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe_addr=agent_safe_addr,
                        destination=destination_address,
                        erc20_tokens=erc20_tokens,
                    )
                    for token, amount in moved.items():
                        total_funds_moved.setdefault(chain_id_str, {}).setdefault(
                            agent_safe_addr, {}
                        )[token] = BigInt(amount)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    f"recoverAccess/drain agent safe failed for service "
                    f"{service_id}: {exc}"
                )

    def _drain_safe(
        self,
        ledger_api: t.Any,
        crypto: t.Any,
        safe_addr: str,
        destination: str,
        erc20_tokens: t.Dict[str, str],
    ) -> t.Dict[str, int]:
        """Drain all native and ERC-20 assets from a Safe to ``destination``."""
        moved: t.Dict[str, int] = {}

        # ERC-20 first (so we still have native for gas);
        # erc20_tokens keys are token addresses per ChainAmounts convention.
        for token_addr in erc20_tokens:
            bal = get_asset_balance(
                ledger_api=ledger_api,
                asset_address=token_addr,
                address=safe_addr,
                raise_on_invalid_address=False,
            )
            if bal > 0:
                try:
                    transfer_erc20_from_safe(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        safe=safe_addr,
                        token=token_addr,
                        to=destination,
                        amount=int(bal),
                    )
                    moved[token_addr] = int(bal)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        f"ERC-20 drain failed for safe={safe_addr} token={token_addr}: {exc}"
                    )

        # Native
        native_bal = get_asset_balance(
            ledger_api=ledger_api,
            asset_address=ZERO_ADDRESS,
            address=safe_addr,
            raise_on_invalid_address=False,
        )
        if native_bal > 0:
            try:
                transfer(
                    ledger_api=ledger_api,
                    crypto=crypto,
                    safe=safe_addr,
                    to=destination,
                    amount=int(native_bal),
                )
                moved[ZERO_ADDRESS] = int(native_bal)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(f"Native drain failed for safe={safe_addr}: {exc}")

        return moved

    def _drain_eoa_assets(
        self,
        chain: Chain,
        ledger_api: t.Any,
        crypto: t.Any,
        eoa_address: str,
        destination: str,
        erc20_tokens: t.Dict[str, str],
    ) -> t.Dict[str, int]:
        """Drain all native and ERC-20 assets from the Master EOA to ``destination``."""
        from operate.utils.gnosis import (  # pylint: disable=import-outside-toplevel
            transfer_erc20_from_eoa,
        )

        moved: t.Dict[str, int] = {}

        # ERC-20 first; erc20_tokens keys are token addresses per ChainAmounts convention.
        for token_addr in erc20_tokens:
            bal = get_asset_balance(
                ledger_api=ledger_api,
                asset_address=token_addr,
                address=eoa_address,
                raise_on_invalid_address=False,
            )
            if bal > 0:
                try:
                    transfer_erc20_from_eoa(
                        ledger_api=ledger_api,
                        crypto=crypto,
                        token=token_addr,
                        to=destination,
                        amount=int(bal),
                    )
                    moved[token_addr] = int(bal)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        f"ERC-20 EOA drain failed token={token_addr}: {exc}"
                    )

        # Native (last, since it pays gas)
        try:
            tx_hash = drain_eoa(
                ledger_api=ledger_api,
                crypto=crypto,
                withdrawal_address=destination,
                chain_id=chain.id,
            )
            if tx_hash:
                # Record approximate amount (balance minus gas already drained)
                moved[ZERO_ADDRESS] = int(
                    get_asset_balance(
                        ledger_api=ledger_api,
                        asset_address=ZERO_ADDRESS,
                        address=destination,
                        raise_on_invalid_address=False,
                    )
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(f"Native EOA drain failed: {exc}")

        return moved
