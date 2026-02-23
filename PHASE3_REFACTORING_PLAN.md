# Phase 3: Architecture Refactoring - Comprehensive Plan

**Status:** 📋 READY FOR REVIEW
**Updated:** 2026-02-12
**Estimated Effort:** 22-28 days (4.4-5.6 weeks)

## Executive Summary

This Phase 3 plan incorporates both the original refactoring goals and the **actual pain points identified by the engineering team** during code review. It prioritizes the most problematic areas based on production experience and engineering feedback.

### Key Pain Points Identified

From engineering team notes in the codebase:

1. **LocalResource/JSON Storage** - "caused many problems" → Replace with SQLite
2. **Service Manager Complexity** - "most buggy area" with complex protocol interactions
3. **Missing Wallet Abstraction** - No abstraction between Safe and EOA operations
4. **CLI/Quickstart Overlap** - Duplicate code paths, unclear separation
5. **Bridge Manager Complexity** - Multiple providers, gas estimation issues
6. **Configuration Scattered** - Constants and configs spread across files
7. **Inconsistent File System Access** - Mix of LocalResource and direct file operations

### Strategic Approach

**Priority Order (by impact and risk):**
1. **Storage Layer** (LocalResource → SQLite) - Affects all components, high impact
2. **Wallet Abstraction** - Critical for Safe vs EOA operations, reduces bugs
3. **Service Manager Decomposition** - "Most buggy area" per engineers
4. **Configuration Consolidation** - Enables easier testing and deployment
5. **Bridge Manager Simplification** - Improves reliability
6. **CLI Consolidation** - Reduces maintenance burden

---

## Phase 3.1: Storage Layer Refactoring (Priority 1)

**Duration:** 5-6 days
**Risk:** HIGH (affects all components)
**Impact:** HIGH (eliminates JSON corruption issues)

### Problem Statement

From engineer notes: "LocalResource class - stores everything in JSON; caused many problems"

**Current Issues:**
- JSON corruption risk during concurrent writes
- No transactional integrity
- Slow queries (must deserialize entire files)
- No indexing or relational queries
- Backup rotation complex (5 backups per file)
- File locking issues on Windows

**Files Using LocalResource:**
- `operate/account/user.py` - User accounts
- `operate/services/service.py` - Service state
- `operate/wallet/master.py` - Wallet data
- `operate/settings.py` - User settings
- `operate/bridge/bridge_manager.py` - Bridge state
- `operate/keys.py` - Key storage (encrypted)

### Solution: SQLite-Based Storage Layer

**New Files:**
```
operate/storage/
├── __init__.py
├── database.py          # Database connection, migrations
├── models.py            # SQLAlchemy models
├── repositories.py      # Data access layer
└── migrations/          # Schema migrations
    ├── 001_initial.py
    └── 002_add_indexes.py
```

**Architecture:**
```python
# operate/storage/database.py
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class Database:
    """Thread-safe SQLite database with WAL mode."""

    def __init__(self, db_path: Path):
        # SQLite with WAL mode for concurrent reads/writes
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={
                "check_same_thread": False,
                "timeout": 30.0,
            },
        )
        # Enable WAL mode for better concurrency
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_session(self):
        """Get database session with automatic cleanup."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

# operate/storage/models.py
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship

class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    hash = Column(String, nullable=False)
    state = Column(Integer, nullable=False, index=True)
    chain_configs = Column(JSON, nullable=False)
    env_variables = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # Relationships
    deployments = relationship("Deployment", back_populates="service")

class MasterWallet(Base):
    __tablename__ = "master_wallets"

    id = Column(Integer, primary_key=True)
    address = Column(String, nullable=False, unique=True, index=True)
    ledger_type = Column(String, nullable=False)
    encrypted_key = Column(String, nullable=False)
    safe_chains = Column(JSON, nullable=False)  # List of chains with safes
    created_at = Column(DateTime, nullable=False)

    # Relationships
    safes = relationship("Safe", back_populates="master_wallet")

class Safe(Base):
    __tablename__ = "safes"

    id = Column(Integer, primary_key=True)
    chain = Column(String, nullable=False, index=True)
    address = Column(String, nullable=False, unique=True, index=True)
    master_wallet_id = Column(Integer, ForeignKey("master_wallets.id"))
    created_at = Column(DateTime, nullable=False)

    master_wallet = relationship("MasterWallet", back_populates="safes")

# operate/storage/repositories.py
from typing import Optional, List

class ServiceRepository:
    """Data access layer for Service entities."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, service_data: dict) -> Service:
        """Create new service."""
        with self.db.get_session() as session:
            service = Service(**service_data)
            session.add(service)
            return service

    def get_by_id(self, service_id: str) -> Optional[Service]:
        """Get service by ID."""
        with self.db.get_session() as session:
            return session.query(Service).filter_by(id=service_id).first()

    def list_all(self) -> List[Service]:
        """List all services."""
        with self.db.get_session() as session:
            return session.query(Service).all()

    def update(self, service_id: str, updates: dict) -> Service:
        """Update service."""
        with self.db.get_session() as session:
            service = session.query(Service).filter_by(id=service_id).first()
            if not service:
                raise ValueError(f"Service {service_id} not found")
            for key, value in updates.items():
                setattr(service, key, value)
            return service
```

### Migration Strategy

**Phase 3.1.1: Create New Storage Layer (2 days)**
- Implement Database, Models, Repositories
- Add migration system
- Write comprehensive unit tests
- NO changes to existing code yet

**Phase 3.1.2: Dual-Write Pattern (1.5 days)**
- Modify Service, MasterWallet, etc. to write to BOTH systems
- Read from JSON (old), write to both JSON and SQLite
- Enables gradual rollout and easy rollback

```python
class Service(LocalResource):
    """Service with dual-write to SQLite."""

    def store(self) -> None:
        """Store to both JSON and SQLite."""
        # Write to JSON (existing)
        super().store()

        # ALSO write to SQLite (new)
        try:
            repo = ServiceRepository(get_database())
            repo.update(self.id, self.json)
        except Exception as e:
            # Log but don't fail - SQLite is optional during migration
            logger.warning(f"Failed to write to SQLite: {e}")
```

**Phase 3.1.3: Data Migration Tool (1 day)**
- Script to migrate existing JSON files to SQLite
- Validation: verify all data migrated correctly
- Backup original JSON files

```bash
# operate/storage/migrate.py
python -m operate.storage.migrate --validate  # Dry run
python -m operate.storage.migrate --execute   # Actual migration
```

**Phase 3.1.4: Switch to SQLite Reads (1 day)**
- Change to read from SQLite, fallback to JSON if missing
- Gradual rollout per installation
- JSON writes continue for safety

**Phase 3.1.5: Remove JSON Dependencies (0.5 days)**
- Remove LocalResource inheritance
- Remove JSON file operations
- Clean up backup rotation code

### Testing Strategy

**New Tests:**
- `tests/storage/test_database.py` (15 tests) - Connection, WAL mode, transactions
- `tests/storage/test_models.py` (20 tests) - Model validation, relationships
- `tests/storage/test_repositories.py` (30 tests) - CRUD operations, queries
- `tests/storage/test_migration.py` (10 tests) - Migration validation

**Integration Tests:**
- Concurrent access (multiple threads)
- Data integrity (transaction rollback)
- Performance (query benchmarks)

### Benefits

✅ **Eliminates JSON corruption** - ACID transactions
✅ **Better concurrency** - SQLite WAL mode
✅ **Faster queries** - Indexed lookups, no full deserialization
✅ **Relational queries** - Join services with deployments, wallets with safes
✅ **Easier testing** - In-memory SQLite for tests
✅ **Better backups** - Single DB file, point-in-time snapshots

### Risks & Mitigation

**Risk:** Data loss during migration
**Mitigation:** Dual-write period, extensive validation, JSON backups retained

**Risk:** Performance regression
**Mitigation:** Benchmark suite, SQLite is typically faster than JSON for reads

**Risk:** Increased complexity
**Mitigation:** Repository pattern hides complexity, simpler than current backup rotation

---

## Phase 3.2: Wallet Abstraction Layer (Priority 2)

**Duration:** 4-5 days
**Risk:** MEDIUM
**Impact:** HIGH (reduces wallet-related bugs)

### Problem Statement

From engineer notes: "missing abstraction between service manager and wallet; abstraction for safe vs eoa"

**Current Issues:**
- MasterWalletManager handles both EOA and Safe operations directly
- Service manager calls wallet methods with Safe-specific parameters
- No polymorphism - lots of `if is_safe` conditionals
- Transfer logic duplicated (EOA transfer vs Safe transfer)
- Gas estimation differs between Safe and EOA (not abstracted)

### Solution: Wallet Interface Hierarchy

**New Files:**
```
operate/wallet/
├── __init__.py
├── interface.py         # IWallet interface
├── eoa_wallet.py        # EOA implementation
├── safe_wallet.py       # Safe implementation
├── factory.py           # Wallet factory
└── master.py            # MasterWalletManager (simplified)
```

**Architecture:**
```python
# operate/wallet/interface.py
from abc import ABC, abstractmethod
from typing import Optional

class IWallet(ABC):
    """Wallet interface for both EOA and Safe."""

    @property
    @abstractmethod
    def address(self) -> str:
        """Wallet address."""

    @abstractmethod
    def get_balance(
        self,
        chain: Chain,
        asset: Optional[str] = None,
        rpc: Optional[str] = None,
    ) -> BigInt:
        """Get balance (native or ERC20)."""

    @abstractmethod
    def transfer(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: Optional[str] = None,
        rpc: Optional[str] = None,
    ) -> str:
        """Transfer funds. Returns transaction hash."""

    @abstractmethod
    def estimate_gas(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: Optional[str] = None,
    ) -> int:
        """Estimate gas for transfer."""

# operate/wallet/eoa_wallet.py
class EOAWallet(IWallet):
    """Externally Owned Account wallet."""

    def __init__(self, crypto: Crypto, chain: Chain):
        self._crypto = crypto
        self._chain = chain

    @property
    def address(self) -> str:
        return self._crypto.address

    def get_balance(
        self,
        chain: Chain,
        asset: Optional[str] = None,
        rpc: Optional[str] = None,
    ) -> BigInt:
        ledger_api = make_chain_ledger_api(chain, rpc=rpc)
        if asset:
            return get_erc20_balance(ledger_api, self.address, asset)
        return ledger_api.get_balance(self.address)

    def transfer(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: Optional[str] = None,
        rpc: Optional[str] = None,
    ) -> str:
        ledger_api = make_chain_ledger_api(chain, rpc=rpc)
        if asset:
            return self._transfer_erc20(ledger_api, to, amount, asset)
        return self._transfer_native(ledger_api, to, amount)

    def estimate_gas(self, to: str, amount: int, chain: Chain, asset: Optional[str] = None) -> int:
        """Estimate gas for EOA transfer."""
        if asset:
            return 65000  # ERC20 transfer gas
        return 21000  # Native transfer gas

# operate/wallet/safe_wallet.py
class SafeWallet(IWallet):
    """Gnosis Safe wallet."""

    def __init__(self, safe_address: str, owner_crypto: Crypto, chain: Chain):
        self._safe_address = safe_address
        self._owner_crypto = owner_crypto
        self._chain = chain

    @property
    def address(self) -> str:
        return self._safe_address

    def get_balance(
        self,
        chain: Chain,
        asset: Optional[str] = None,
        rpc: Optional[str] = None,
    ) -> BigInt:
        ledger_api = make_chain_ledger_api(chain, rpc=rpc)
        return get_asset_balance(
            ledger_api=ledger_api,
            safe_address=self.address,
            asset=asset,
        )

    def transfer(
        self,
        to: str,
        amount: int,
        chain: Chain,
        asset: Optional[str] = None,
        rpc: Optional[str] = None,
    ) -> str:
        ledger_api = make_chain_ledger_api(chain, rpc=rpc)
        if asset:
            return transfer_erc20_from_safe(
                ledger_api=ledger_api,
                crypto=self._owner_crypto,
                safe_address=self.address,
                to=to,
                amount=amount,
                token_address=asset,
            )
        return transfer_from_safe(
            ledger_api=ledger_api,
            crypto=self._owner_crypto,
            safe_address=self.address,
            to=to,
            amount=amount,
        )

    def estimate_gas(self, to: str, amount: int, chain: Chain, asset: Optional[str] = None) -> int:
        """Estimate gas for Safe transfer."""
        ledger_api = make_chain_ledger_api(chain)
        return estimate_transfer_tx_fee(
            ledger_api=ledger_api,
            safe_address=self.address,
            to=to,
            amount=amount,
            token_address=asset,
        )

# operate/wallet/factory.py
class WalletFactory:
    """Factory for creating wallet instances."""

    @staticmethod
    def create_eoa(crypto: Crypto, chain: Chain) -> EOAWallet:
        """Create EOA wallet."""
        return EOAWallet(crypto, chain)

    @staticmethod
    def create_safe(safe_address: str, owner_crypto: Crypto, chain: Chain) -> SafeWallet:
        """Create Safe wallet."""
        return SafeWallet(safe_address, owner_crypto, chain)

    @staticmethod
    def from_master_wallet(
        master_wallet: MasterWallet,
        chain: Chain,
        use_safe: bool = True,
    ) -> IWallet:
        """Create wallet from MasterWallet configuration."""
        if use_safe and chain in master_wallet.safes:
            return WalletFactory.create_safe(
                safe_address=master_wallet.safes[chain],
                owner_crypto=master_wallet.crypto,
                chain=chain,
            )
        return WalletFactory.create_eoa(master_wallet.crypto, chain)
```

### Refactoring Service Manager

**Before:**
```python
# operate/services/manage.py
class ServiceManager:
    def fund_service(self, service: Service, chain: Chain):
        # Direct wallet access, Safe-specific logic
        if chain in self.master_wallet.safes:
            safe_address = self.master_wallet.safes[chain]
            # Safe-specific transfer
            transfer_from_safe(...)
        else:
            # EOA transfer
            ledger_api.transfer(...)
```

**After:**
```python
# operate/services/manage.py
class ServiceManager:
    def fund_service(self, service: Service, chain: Chain):
        # Use wallet abstraction
        wallet = WalletFactory.from_master_wallet(
            self.master_wallet,
            chain,
            use_safe=True
        )

        # Polymorphic call - works for both EOA and Safe
        tx_hash = wallet.transfer(
            to=service.agent_address,
            amount=funding_amount,
            chain=chain,
        )
```

### Benefits

✅ **Eliminates if/else chains** - Polymorphic behavior
✅ **Easier testing** - Mock IWallet interface
✅ **Reduces bugs** - Single code path for transfers
✅ **Clearer separation** - Service manager doesn't need Safe/EOA knowledge
✅ **Easier to extend** - Add new wallet types (multi-sig, hardware wallets)

### Testing Strategy

**New Tests:**
- `tests/wallet/test_eoa_wallet.py` (15 tests)
- `tests/wallet/test_safe_wallet.py` (20 tests)
- `tests/wallet/test_wallet_factory.py` (10 tests)
- `tests/wallet/test_wallet_interface.py` (10 tests) - Interface contract tests

---

## Phase 3.3: Service Manager Decomposition (Priority 3)

**Duration:** 5-6 days
**Risk:** MEDIUM-HIGH
**Impact:** HIGH (addresses "most buggy area")

### Problem Statement

From engineer notes: "most buggy area: service manager; very complex protocol interactions"

**Current Issues:**
- ServiceManager: 2,881 lines (God class)
- Multiple responsibilities:
  - Service CRUD
  - Deployment orchestration
  - Protocol interactions (on-chain)
  - Funding management
  - State management
  - Balance checking
- 43 TODO/FIXME comments in manage.py alone
- Tight coupling to wallet, protocol, funding_manager

### Solution: Extract Cohesive Services

This follows the original Phase 3.1 plan with enhancements based on engineer feedback.

**New Files:**
```
operate/services/
├── service_registry.py          # Service CRUD
├── deployment_coordinator.py    # Deployment orchestration
├── protocol_manager.py          # Protocol interactions (NEW)
├── state_manager.py             # State transitions
└── manage.py                    # ServiceManager (orchestrator only)
```

**1. ServiceRegistry (2 days)**
```python
# operate/services/service_registry.py
class ServiceRegistry:
    """Service CRUD operations and persistence."""

    def __init__(self, db: Database, services_dir: Path):
        self.repo = ServiceRepository(db)
        self.services_dir = services_dir

    def create(self, service_template: dict) -> Service:
        """Create new service."""

    def get(self, service_id: str) -> Service:
        """Get service by ID."""

    def list_all(self) -> List[Service]:
        """List all services."""

    def update(self, service_id: str, updates: dict) -> Service:
        """Update service configuration."""

    def delete(self, service_id: str) -> None:
        """Delete service and clean up resources."""
```

**2. ProtocolManager (NEW - 2 days)**
```python
# operate/services/protocol_manager.py
class ProtocolManager:
    """Handles all on-chain protocol interactions.

    Extracts complex protocol logic from ServiceManager.
    """

    def __init__(self, wallet: IWallet):
        self.wallet = wallet
        self._protocol_cache = {}

    def register_service(
        self,
        service: Service,
        chain: Chain,
    ) -> str:
        """Register service on-chain. Returns tx hash."""

    def activate_service(
        self,
        service: Service,
        chain: Chain,
    ) -> str:
        """Activate service on-chain."""

    def stake_service(
        self,
        service: Service,
        chain: Chain,
        staking_program_id: str,
    ) -> str:
        """Stake service in program."""

    def get_service_info(
        self,
        service_id: str,
        chain: Chain,
    ) -> dict:
        """Get on-chain service information."""
```

**3. DeploymentCoordinator (2 days)**
```python
# operate/services/deployment_coordinator.py
class DeploymentCoordinator:
    """Orchestrates service deployments (local + on-chain)."""

    def __init__(
        self,
        protocol_manager: ProtocolManager,
        agent_runner: AgentRunner,
        deployment_runner: DeploymentRunner,
    ):
        self.protocol_manager = protocol_manager
        self.agent_runner = agent_runner
        self.deployment_runner = deployment_runner

    async def deploy_local(self, service: Service) -> None:
        """Deploy service locally (Docker containers)."""

    async def deploy_onchain(self, service: Service, chain: Chain) -> None:
        """Deploy service on-chain (registration, activation)."""

    async def stop(self, service: Service) -> None:
        """Stop service gracefully."""
```

**4. Refactored ServiceManager (orchestrator only)**
```python
# operate/services/manage.py
class ServiceManager:
    """Orchestrates service lifecycle operations.

    Delegates to specialized services:
    - ServiceRegistry: CRUD operations
    - DeploymentCoordinator: Deployments
    - ProtocolManager: On-chain interactions
    - FundingManager: Funding operations
    - StateManager: State transitions
    """

    def __init__(self, ...):
        self.registry = ServiceRegistry(db, services_dir)
        self.protocol = ProtocolManager(wallet)
        self.coordinator = DeploymentCoordinator(...)
        self.funding = FundingManager(...)
        self.state = StateManager()

    def create_service(self, template: dict) -> Service:
        """Create service - delegates to registry."""
        return self.registry.create(template)

    def deploy_service(self, service_id: str) -> None:
        """Deploy service - orchestrates multiple services."""
        service = self.registry.get(service_id)

        # Validate state transition
        self.state.validate_transition(service.state, ServiceState.DEPLOYING)

        # Update state
        service.state = ServiceState.DEPLOYING
        self.registry.update(service.id, {"state": service.state})

        # Fund if needed
        if self.funding.needs_funding(service):
            self.funding.fund_service(service)

        # Deploy
        await self.coordinator.deploy_local(service)
        await self.coordinator.deploy_onchain(service, service.home_chain)

        # Update state
        service.state = ServiceState.DEPLOYED
        self.registry.update(service.id, {"state": service.state})
```

### Result

- ServiceManager: 2,881 → ~800 lines (72% reduction)
- ServiceRegistry: ~350 lines
- ProtocolManager: ~400 lines (NEW)
- DeploymentCoordinator: ~450 lines
- Each class has single responsibility
- Easier to test, mock, extend

---

## Phase 3.4: Configuration Consolidation (Priority 4)

**Duration:** 3-4 days
**Risk:** LOW
**Impact:** MEDIUM

### Problem Statement

From engineer notes: "constants should be elsewhere" (from profiles.py)

**Current Issues:**
- Chain configurations in `ledger/profiles.py` mixed with code
- Magic numbers throughout codebase
- Timeout values hardcoded
- RPC endpoints hardcoded
- Contract addresses in multiple places

### Solution: Centralized Configuration

**New Files:**
```
operate/config/
├── __init__.py
├── app_config.py       # Application configuration
├── chains.yaml         # Chain configurations
└── loader.py           # Configuration loader
```

**1. Chain Configuration (chains.yaml)**
```yaml
# operate/config/chains.yaml
chains:
  ethereum:
    chain_id: 1
    name: "Ethereum Mainnet"
    rpc_endpoints:
      primary: "https://eth.llamarpc.com"
      fallback:
        - "https://ethereum.publicnode.com"
        - "https://rpc.ankr.com/eth"
    explorer: "https://etherscan.io"
    contracts:
      service_registry: "0x48b6af7B12C71f09e2fC8aF4855De4Ff54e775cA"
      staking_token: "0x0001A500A6B18995B03f44bb040A5fFc28E45CB0"
    tokens:
      native:
        symbol: "ETH"
        decimals: 18
      usdc:
        address: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        symbol: "USDC"
        decimals: 6
    gas:
      price_oracle: "https://api.etherscan.io/api"
      max_priority_fee: 2000000000  # 2 gwei
      max_fee_per_gas: 100000000000  # 100 gwei

  gnosis:
    # Similar structure...

  base:
    # Similar structure...
```

**2. Application Configuration**
```python
# operate/config/app_config.py
from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class TimeoutConfig:
    """Timeout configuration."""
    on_chain_interact: int = 120  # seconds
    rpc_request: int = 30
    health_check: int = 300
    deployment: int = 600

    @classmethod
    def from_env(cls) -> "TimeoutConfig":
        """Load from environment variables."""
        return cls(
            on_chain_interact=int(os.getenv("TIMEOUT_ON_CHAIN", "120")),
            rpc_request=int(os.getenv("TIMEOUT_RPC", "30")),
            health_check=int(os.getenv("TIMEOUT_HEALTH_CHECK", "300")),
            deployment=int(os.getenv("TIMEOUT_DEPLOYMENT", "600")),
        )

@dataclass
class RetryConfig:
    """Retry configuration."""
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0

    @classmethod
    def from_env(cls) -> "RetryConfig":
        return cls(
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            initial_delay=float(os.getenv("RETRY_INITIAL_DELAY", "1.0")),
        )

@dataclass
class CooldownConfig:
    """Cooldown configuration."""
    funding_request: int = 300  # 5 minutes
    deployment: int = 60
    health_check_restart: int = 120

    @classmethod
    def from_env(cls) -> "CooldownConfig":
        return cls(
            funding_request=int(os.getenv("COOLDOWN_FUNDING", "300")),
            deployment=int(os.getenv("COOLDOWN_DEPLOYMENT", "60")),
        )

@dataclass
class AppConfig:
    """Application configuration."""
    timeouts: TimeoutConfig
    retries: RetryConfig
    cooldowns: CooldownConfig

    @classmethod
    def load(cls) -> "AppConfig":
        """Load configuration from environment."""
        return cls(
            timeouts=TimeoutConfig.from_env(),
            retries=RetryConfig.from_env(),
            cooldowns=CooldownConfig.from_env(),
        )

# Global config instance
config = AppConfig.load()
```

**3. Usage**
```python
# Before
from operate.constants import ON_CHAIN_INTERACT_TIMEOUT
timeout = ON_CHAIN_INTERACT_TIMEOUT

# After
from operate.config import config
timeout = config.timeouts.on_chain_interact
```

### Benefits

✅ **Single source of truth** - All config in one place
✅ **Environment overrides** - Easy to customize per environment
✅ **Type safety** - Dataclasses with validation
✅ **Easier testing** - Override config in tests
✅ **Better documentation** - YAML is self-documenting

---

## Phase 3.5: Bridge Manager Simplification (Priority 5)

**Duration:** 2-3 days
**Risk:** LOW
**Impact:** MEDIUM

### Problem Statement

From engineer notes: "complex manager; multiple swaps are supported; gas estimation issues historically; started with lifi and added relay; relay is better"

**Current Issues:**
- BridgeManager: 473 lines
- Multiple provider implementations (LiFi, Relay)
- Gas estimation issues
- Inconsistent error handling across providers
- No fallback mechanism

### Solution: Provider Pattern with Fallback

**Enhancements:**

**1. Provider Interface (1 day)**
```python
# operate/bridge/providers/provider.py (enhanced)
class IBridgeProvider(ABC):
    """Bridge provider interface with enhanced error handling."""

    @abstractmethod
    async def get_quote(
        self,
        from_chain: Chain,
        to_chain: Chain,
        token: str,
        amount: int,
    ) -> BridgeQuote:
        """Get bridge quote with gas estimation."""

    @abstractmethod
    async def execute_bridge(
        self,
        quote: BridgeQuote,
        from_address: str,
        to_address: str,
    ) -> BridgeTx:
        """Execute bridge transaction."""

    @abstractmethod
    def estimate_gas(
        self,
        from_chain: Chain,
        to_chain: Chain,
        amount: int,
    ) -> int:
        """Estimate total gas cost (source + destination)."""
```

**2. Fallback Chain (1 day)**
```python
# operate/bridge/bridge_manager.py (enhanced)
class BridgeManager:
    """Bridge manager with provider fallback."""

    def __init__(self):
        # Priority order: Relay (better pricing) -> LiFi (fallback)
        self.providers = [
            RelayBridgeProvider(),
            LiFiBridgeProvider(),
        ]

    async def bridge(
        self,
        from_chain: Chain,
        to_chain: Chain,
        token: str,
        amount: int,
    ) -> str:
        """Bridge with automatic provider fallback."""
        last_error = None

        for provider in self.providers:
            try:
                logger.info(f"Attempting bridge with {provider.name}")

                # Get quote with gas estimation
                quote = await provider.get_quote(
                    from_chain, to_chain, token, amount
                )

                # Validate quote
                if not self._validate_quote(quote):
                    logger.warning(f"Invalid quote from {provider.name}")
                    continue

                # Execute
                tx = await provider.execute_bridge(
                    quote, from_address, to_address
                )

                logger.info(f"Bridge successful via {provider.name}: {tx.hash}")
                return tx.hash

            except BridgeProviderError as e:
                logger.warning(f"Provider {provider.name} failed: {e}")
                last_error = e
                continue

        # All providers failed
        raise BridgeError(f"All providers failed. Last error: {last_error}")
```

### Benefits

✅ **Improved reliability** - Automatic fallback
✅ **Better gas estimation** - Standardized across providers
✅ **Clearer error handling** - Specific exceptions per provider
✅ **Easy to add providers** - Implement IBridgeProvider interface

---

## Phase 3.6: CLI Consolidation (Priority 6)

**Duration:** 2-3 days
**Risk:** LOW
**Impact:** MEDIUM

### Problem Statement

From engineer notes: "CLI and quickstart overlap"

**Current Issues:**
- `cli.py`: 2,057 lines
- `quickstart/` scripts duplicate functionality
- Three access paths to same functionality:
  - Pearl frontend → FastAPI → internals
  - Quickstart → scripts → internals
  - Manual CLI → scripts → internals

**Ideal Architecture (from notes):**
- Pearl frontend → FastAPI server → programmatically → Operate
- QS → programmatically → Operate
- MC → programmatically → Operate

### Solution: Unified Programmatic API

**New Structure:**
```
operate/
├── api.py              # Public programmatic API
├── cli.py              # CLI wrapper (thin)
├── operate_http/       # FastAPI server (uses api.py)
└── quickstart/         # QS scripts (use api.py)
```

**1. Public API (2 days)**
```python
# operate/api.py
"""Public programmatic API for Operate.

This is the single entry point for all programmatic access:
- FastAPI server
- Quickstart scripts
- Manual CLI
- External integrations
"""

class OperateAPI:
    """Unified API for all Operate operations."""

    def __init__(self, home_dir: Path, user: User):
        self.home_dir = home_dir
        self.user = user
        self.db = Database(home_dir / "operate.db")

        # Initialize services
        wallet = WalletFactory.from_user(user)
        self.services = ServiceManager(db=self.db, wallet=wallet)
        self.wallets = WalletManager(db=self.db)
        self.bridges = BridgeManager()

    # Service operations
    def create_service(self, template: dict) -> Service:
        """Create new service."""
        return self.services.create_service(template)

    def deploy_service(self, service_id: str) -> None:
        """Deploy service."""
        self.services.deploy_service(service_id)

    def stop_service(self, service_id: str) -> None:
        """Stop service."""
        self.services.stop_service(service_id)

    # Wallet operations
    def create_wallet(self, ledger_type: LedgerType, password: str) -> MasterWallet:
        """Create master wallet."""
        return self.wallets.create(ledger_type, password)

    # Bridge operations
    async def bridge_tokens(
        self,
        from_chain: Chain,
        to_chain: Chain,
        token: str,
        amount: int,
    ) -> str:
        """Bridge tokens."""
        return await self.bridges.bridge(from_chain, to_chain, token, amount)

# Global API factory
def get_operate_api(home_dir: Optional[Path] = None, user: Optional[User] = None) -> OperateAPI:
    """Get OperateAPI instance."""
    if home_dir is None:
        home_dir = get_default_home_dir()
    if user is None:
        user = User.load_default(home_dir)
    return OperateAPI(home_dir, user)
```

**2. Refactor CLI (0.5 days)**
```python
# operate/cli.py (thin wrapper)
@app.command()
def deploy_service(service_id: str):
    """Deploy service."""
    api = get_operate_api()
    api.deploy_service(service_id)
    print(f"Service {service_id} deployed successfully")
```

**3. Refactor FastAPI (0.5 days)**
```python
# operate/operate_http/routes.py
@router.post("/services/{service_id}/deploy")
async def deploy_service(service_id: str):
    """Deploy service."""
    api = get_operate_api(user=current_user)
    api.deploy_service(service_id)
    return {"status": "deployed"}
```

### Benefits

✅ **Single code path** - Eliminates duplication
✅ **Easier testing** - Test API, not CLI/HTTP layers
✅ **Better error handling** - Consistent across all entry points
✅ **Simpler maintenance** - Changes in one place

---

## Phase 3.7: Eliminate DRY Violations (from original plan)

**Duration:** 2-3 days
**Risk:** LOW
**Impact:** MEDIUM

This follows the original Phase 3.4 plan:

**1. Balance Checking Utility**
- `operate/utils/balance.py` - Consolidate duplicated balance checks

**2. Transfer Utility**
- `operate/utils/transfers.py` - Unified native and ERC20 transfers

**3. RPC Management**
- `operate/ledger/rpc_manager.py` - Centralize RPC creation with fallback

---

## Implementation Roadmap

### Week 1: Foundation (Storage + Wallet)
- **Days 1-3:** Phase 3.1.1-3.1.3 - Create storage layer, dual-write, migration tool
- **Days 4-5:** Phase 3.2.1-3.2.2 - Wallet interface, EOA/Safe implementations

### Week 2: Wallet + Service Manager Start
- **Days 1-2:** Phase 3.2.3 - Integrate wallet abstraction into service manager
- **Days 3-5:** Phase 3.3.1 - Extract ServiceRegistry and ProtocolManager

### Week 3: Service Manager Decomposition
- **Days 1-3:** Phase 3.3.2 - Extract DeploymentCoordinator
- **Days 4-5:** Phase 3.3.3 - Refactor ServiceManager (orchestrator)

### Week 4: Configuration + Utilities
- **Days 1-2:** Phase 3.4 - Configuration consolidation
- **Days 3-4:** Phase 3.5 - Bridge manager simplification
- **Day 5:** Phase 3.6 - CLI consolidation

### Week 5: Cleanup + Testing
- **Days 1-2:** Phase 3.7 - Eliminate DRY violations
- **Days 3-5:** Integration testing, documentation, final cleanup

---

## Testing Strategy

### Per-Phase Testing

**Each phase must include:**
- Unit tests for new classes/functions
- Integration tests for end-to-end flows
- Backward compatibility tests
- Performance regression tests

### Test Coverage Goals

- New code: 90%+ coverage
- Refactored code: Maintain existing coverage
- Critical paths: 100% coverage (deployment, funding, transfers)

### Continuous Validation

```bash
# After each phase
tox -e unit-tests          # Fast validation
tox -e integration-tests   # Full validation
tox -e all-linters         # Code quality
```

---

## Success Criteria

### Quantitative Metrics

- [ ] ServiceManager: 2,881 → <1,000 lines (65%+ reduction)
- [ ] Service: 1,417 → <1,000 lines (30%+ reduction)
- [ ] FundingManager: 1,053 → <700 lines (33%+ reduction)
- [ ] God class total: 5,351 → <3,000 lines (44%+ reduction)
- [ ] No file >1,000 lines
- [ ] TODO/FIXME: 119 → <60 (50% reduction)
- [ ] Code duplication: <3%
- [ ] All tests passing (209+ unit tests)
- [ ] Zero regressions

### Qualitative Improvements

- [ ] Clear separation of concerns (Single Responsibility Principle)
- [ ] Polymorphic wallet operations (no if/else chains)
- [ ] Transactional data integrity (SQLite ACID)
- [ ] Centralized configuration (single source of truth)
- [ ] Single programmatic API (no code duplication)
- [ ] Improved error messages (specific exceptions)

---

## Risk Mitigation

### High-Risk Areas

**Storage Layer Migration:**
- Risk: Data loss during JSON → SQLite migration
- Mitigation: Dual-write period, JSON backups retained, extensive validation

**Service Manager Refactoring:**
- Risk: Breaking existing integrations
- Mitigation: Maintain ServiceManager facade, gradual delegation, backward compatibility tests

### Rollback Strategy

Each phase is independently reversible:
- Feature branch per phase
- Merge only after full validation
- Tag before each merge for easy rollback
- 48-hour staging period before production

---

## Estimated Timeline

| Phase | Duration | Dependencies | Risk |
|-------|----------|--------------|------|
| 3.1 Storage Layer | 5-6 days | None | HIGH |
| 3.2 Wallet Abstraction | 4-5 days | 3.1 (optional) | MEDIUM |
| 3.3 Service Manager | 5-6 days | 3.1, 3.2 | MEDIUM-HIGH |
| 3.4 Configuration | 3-4 days | None | LOW |
| 3.5 Bridge Manager | 2-3 days | 3.4 | LOW |
| 3.6 CLI Consolidation | 2-3 days | 3.3 | LOW |
| 3.7 DRY Violations | 2-3 days | 3.2, 3.4 | LOW |
| **Total** | **23-30 days** | | |

**Parallel Opportunities:**
- 3.4 can start before 3.3 completes
- 3.5 and 3.6 can run in parallel
- 3.7 can overlap with 3.6

**Realistic Estimate:** 4-5 weeks with 1-2 engineers

---

## Next Steps

1. **Review this plan** with engineering team
2. **Prioritize phases** based on current pain points
3. **Create feature branches:**
   - `feat/phase3.1-storage-layer`
   - `feat/phase3.2-wallet-abstraction`
   - `feat/phase3.3-service-manager-decomposition`
4. **Start with Phase 3.1** (Storage Layer) - highest impact
5. **Daily standups** to track progress and blockers
6. **Weekly demos** to stakeholders

---

**Plan prepared by:** Claude Code
**Date:** 2026-02-12
**Based on:** Engineering team notes + original Phase 3 plan
**Estimated effort:** 23-30 days (4-5 weeks)
