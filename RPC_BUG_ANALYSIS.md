# RPC Configuration Bug Analysis

## Issue

When using custom RPC endpoints for chains (e.g., via `MECHX_CHAIN_RPC` override), balance checks fail because they use default RPCs instead of the configured custom RPCs.

### Error Example
```
Cannot get balance of address='0x098de452F4B87e85bc11fb95AF8Eb88C176Dc406'
asset_address='0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359'
rpc=https://polygon-rpc.com.
```

User configured: `https://polygon-mainnet.g.alchemy.com/v2/...`
Actually used: `https://polygon-rpc.com` (default)

## Root Cause

Services store custom RPC configurations in `chain_configs[chain].ledger_config.rpc`, but several functions ignore these and always use `get_default_ledger_api(chain)`:

### Affected Code Locations

1. **`operate/wallet/master.py:226`** - `MasterWallet.get_balance()`
   ```python
   def get_balance(self, chain: Chain, asset: str = ZERO_ADDRESS, from_safe: bool = True) -> BigInt:
       # ...
       return get_asset_balance(
           ledger_api=get_default_ledger_api(chain),  # BUG: ignores custom RPC
           asset_address=asset,
           address=address,
       )
   ```

2. **`operate/services/funding_manager.py:104`** - `FundingManager.drain_agents_eoas()`
   ```python
   def drain_agents_eoas(self, service: Service, withdrawal_address: str, chain: Chain) -> None:
       ledger_api = get_default_ledger_api(chain)  # BUG: ignores service's custom RPC
   ```

3. **`operate/services/funding_manager.py:130`** - `FundingManager.drain_service_safe()`
   ```python
   def drain_service_safe(self, service: Service, withdrawal_address: str, chain: Chain) -> None:
       chain_config = service.chain_configs[chain.value]
       ledger_api = get_default_ledger_api(chain)  # BUG: has chain_config but doesn't use it!
       ledger_config = chain_config.ledger_config
       # Later correctly uses: sftxb = EthSafeTxBuilder(rpc=ledger_config.rpc, ...)
   ```

4. **`operate/services/funding_manager.py:331`** - Asset requirement computation
5. **`operate/services/funding_manager.py:614, 645`** - Asset balance checks
6. **`operate/services/service.py:1322, 1350`** - `Service.get_balances()`

## How Default RPC Resolution Works

```python
# operate/ledger/__init__.py
POLYGON_RPC = os.environ.get("POLYGON_RPC", "https://polygon-rpc.com")

DEFAULT_RPCS = {
    Chain.POLYGON: POLYGON_RPC,
    # ...
}

def get_default_rpc(chain: Chain) -> str:
    return DEFAULT_RPCS[chain]  # Returns env var or hardcoded default

def get_default_ledger_api(chain: Chain) -> LedgerApi:
    # Always uses default RPC, never checks service's chain_configs
    return make_chain_ledger_api(chain=chain, rpc=get_default_rpc(chain=chain))
```

## The Fix

### Strategy
Add optional `rpc` parameter to balance-checking functions and thread it through the call stack.

### Required Changes

#### 1. `operate/wallet/master.py` - Add `rpc` parameter to `get_balance()`
```python
def get_balance(
    self,
    chain: Chain,
    asset: str = ZERO_ADDRESS,
    from_safe: bool = True,
    rpc: t.Optional[str] = None,  # NEW
) -> BigInt:
    """Get wallet balance on a given chain."""
    if from_safe:
        if chain not in self.safes:
            raise ValueError(f"Wallet does not have a Safe on chain {chain}.")
        address = self.safes[chain]
    else:
        address = self.address

    # Use custom RPC if provided, otherwise fall back to default
    ledger_api = (
        make_chain_ledger_api(chain, rpc) if rpc
        else get_default_ledger_api(chain)
    )

    return get_asset_balance(
        ledger_api=ledger_api,
        asset_address=asset,
        address=address,
    )
```

#### 2. `operate/services/funding_manager.py` - Use service's custom RPC

Multiple locations need to be updated to extract and use the custom RPC from `service.chain_configs[chain.value].ledger_config.rpc`.

**Pattern to follow:**
```python
# BEFORE (wrong)
ledger_api = get_default_ledger_api(chain)

# AFTER (correct)
chain_config = service.chain_configs[chain.value]
ledger_config = chain_config.ledger_config
ledger_api = make_chain_ledger_api(chain, rpc=ledger_config.rpc)
```

Or when calling wallet methods:
```python
# BEFORE (wrong)
balance = wallet.get_balance(chain=chain, asset=asset, from_safe=from_safe)

# AFTER (correct)
chain_config = service.chain_configs[chain.value]
balance = wallet.get_balance(
    chain=chain,
    asset=asset,
    from_safe=from_safe,
    rpc=chain_config.ledger_config.rpc
)
```

#### 3. `operate/services/service.py` - Update `Service.get_balances()`

The `get_balances()` method should use the service's own `chain_configs` RPCs:
```python
def get_balances(self, unify_wrapped_native_tokens: bool = True) -> ChainAmounts:
    """Get balances for all service chains."""
    # ...
    for chain_str, chain_config in self.chain_configs.items():
        chain = Chain(chain_str)
        ledger_config = chain_config.ledger_config
        ledger_api = make_chain_ledger_api(chain, rpc=ledger_config.rpc)  # Use custom RPC
        # ... rest of the logic
```

### Files to Update

1. `operate/wallet/master.py`
   - `get_balance()` - add optional `rpc` parameter
   - `_pre_transfer_checks()` - pass `rpc` through
   - All internal callers of `get_balance()`

2. `operate/services/funding_manager.py`
   - `drain_agents_eoas()` - use service's RPC
   - `drain_service_safe()` - use service's RPC
   - `_compute_asset_requirements()` - use service's RPC
   - Any other methods using `get_default_ledger_api()`

3. `operate/services/service.py`
   - `get_balances()` - use service's chain_configs RPCs

### Testing Strategy

1. Create unit test mocking RPC calls with custom endpoint
2. Verify that custom RPC is used instead of default
3. Integration test with actual custom RPC configuration
4. Test that balance checks use the configured RPC

### Priority

**HIGH** - This bug causes production failures when users configure custom RPCs.

## Related Code Patterns

### ✅ Correct Pattern (already used in some places)
```python
# operate/services/manage.py:298
chain_config = service.chain_configs[chain.value]
ledger_config = chain_config.ledger_config
sftxb = self.get_eth_safe_tx_builder(ledger_config=ledger_config)
# sftxb uses the custom RPC correctly
```

### ❌ Incorrect Pattern (needs fixing)
```python
# Many places in funding_manager.py and service.py
ledger_api = get_default_ledger_api(chain)  # Ignores service's custom RPC
```

## Impact

- Users cannot reliably use custom RPC providers (Alchemy, Infura, etc.)
- Services fail during funding operations
- Error messages are confusing (show default RPC being used, not the configured one)
- Workaround requires setting environment variables globally, which doesn't work for multi-chain or multi-service setups
