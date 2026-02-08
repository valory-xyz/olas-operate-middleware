# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Olas Operate Middleware is a cross-platform Python package for running autonomous agents powered by the OLAS Network. It provides a daemon service with a FastAPI-based HTTP server that manages agent services, wallets, and blockchain interactions.

## Development Commands

### Environment Setup
```bash
# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Code Quality
```bash
# Format code (run before committing)
tox -p -e black -e isort

# Run all quality checks
tox -p -e isort-check -e black-check -e flake8 -e pylint -e mypy -e bandit -e safety
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_services_service.py -v

# Run specific test function
pytest tests/test_services_service.py::test_function_name -v
```

### Starting the Daemon
```bash
# Start the daemon service
python -m operate.cli daemon

# Or using the installed command
operate daemon
```

## Architecture

### Core Components

**CLI Entry Point (`operate/cli.py`)**
- Main application entry point providing `daemon` and other commands
- Initializes FastAPI server with lifecycle management
- Handles process management and graceful shutdown

**Services Layer (`operate/services/`)**
- `service.py`: Core `Service` class representing an autonomous agent service
- `manager.py`: `ServiceManager` for managing multiple services
- `protocol.py`: Protocol interactions for on-chain service operations
- `agent_runner.py`: Manages agent_runner binary execution
- `deployment_runner.py`: Handles service deployment lifecycle
- `funding_manager.py`: Manages wallet funding operations with cooldown mechanisms
- `health_checker.py`: Monitors service health via healthcheck.json

**Wallet Management (`operate/wallet/`)**
- `master.py`: `MasterWalletManager` handles Master EOA (Externally Owned Account) and Master Safe (Gnosis Safe)
- `wallet_recovery_manager.py`: Implements wallet recovery with backup owner swaps
- Master EOA is the primary key, Master Safe is a 2-of-2 multisig (Master EOA + backup owner)
- Agent services create their own Agent Safe funded from Master Safe

**HTTP API (`operate/operate_http/`)**
- FastAPI-based REST API with endpoints for:
  - Authentication and account management
  - Service CRUD and deployment operations
  - Wallet and Safe management
  - Recovery workflows
  - Bridge operations for cross-chain transfers
- See `docs/api.md` for comprehensive API documentation

**Bridge Management (`operate/bridge/`)**
- `bridge_manager.py`: Orchestrates cross-chain token transfers
- `providers/`: Multiple bridge provider implementations (LiFi, Relay, native bridges)

**Ledger Integration (`operate/ledger/`)**
- `profiles.py`: Chain configurations, RPC endpoints, token addresses
- Supports multiple chains: Ethereum, Gnosis, Base, Optimism, Mode

**Account Management (`operate/account/`)**
- `user.py`: User account with password-based authentication using Argon2

### Key Design Patterns

**Wallet Hierarchy**
- Master EOA (user's main private key)
  - Master Safe (2-of-2: Master EOA + backup owner)
    - Agent Safe(s) (per service, funded from Master Safe)
    - Agent EOA(s) (per agent instance)

**Service Deployment States**
- BUILT (1): Service built but not running
- DEPLOYING (2): Deployment in progress
- DEPLOYED (3): Service running successfully
- STOPPING (4): Graceful shutdown in progress
- STOPPED (5): Service stopped

**Environment Variables**
- Services use `env_variables` with provision types:
  - `fixed`: Hardcoded values
  - `computed`: Generated at runtime
  - `user`: User-provided values

**Funding Flow**
- Master EOA funds Master Safe
- Master Safe funds Agent Safe/EOA
- Funding operations have cooldown periods to prevent race conditions
- Agent can request additional funds via healthcheck.json

## Important Conventions

**Directory Structure**
- `~/.olas/operate/` (or `OPERATE_HOME`): Default data directory
  - `services/`: Service deployments
  - `keys/`: Encrypted key files
  - `wallets/`: Wallet metadata
  - `settings.json`: User settings

**Testing**
- Tests use `pytest` with fixtures in `conftest.py`
- Temporary directories via `tmp_path` fixture
- Mock external services (RPC calls, IPFS, Docker)
- Tests require environment variables for RPC endpoints

**Service Configuration**
- Services use `service.yaml` format from open-autonomy
- Chain-specific configurations in `chain_configs`
- Hash history tracks IPFS hashes over time

**Code Exclusions**
- `operate/data/`: Auto-generated contracts, excluded from linting
- Type checking excludes several files (see `tox.ini` mypy config)

## Working with Smart Contracts

Contract ABIs are in `operate/data/contracts/*/build/*.json`. Key contracts:
- `staking_token`: Token staking for services
- `mech_activity`: Mech marketplace activity tracking
- Bridge contracts: `*_omnibridge`, `*_standard_bridge`

Contract wrappers auto-generated, don't edit `contract.py` files directly.

## Common Issues

**Password Requirements**
- Minimum 8 characters enforced throughout

**Safe Creation**
- Master Safe creation requires funding for gas
- Backup owner must be set during creation
- Safe addresses should be consistent across chains

**Service Updates**
- Services must be stopped before configuration updates
- Hash updates trigger redeployment
- Use `PATCH` for partial updates, `PUT` for full replacement

**Funding Cooldowns**
- 5-minute default cooldown after funding operations
- Prevents race conditions with agent funding requests
- Check `agent_funding_requests_cooldown` in funding requirements

## Version Management

Version stored in `operate/__init__.py` as `__version__`. Release process handled via GitHub Actions (`.github/workflows/release.yml`).
