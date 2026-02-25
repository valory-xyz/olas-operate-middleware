# Input Validation & State Protection Gaps

Analysis of missing validation that could lead to state corruption or unsafe operations.

**Date:** 2026-02-10
**Phase:** 1.5 - Input Validation & State Protection

---

## Critical Gaps

### 1. Service Deletion Without State Validation ⚠️

**File:** `operate/services/service.py:773-778`

**Issue:**
```python
def delete(self) -> None:
    """Delete the deployment."""
    build = self.path / DEPLOYMENT_DIR
    shutil.rmtree(build)  # No validation!
    self.status = DeploymentStatus.DELETED
    self.store()
```

**Problems:**
- ❌ No check if service is currently running (could delete running deployment)
- ❌ No validation that path exists (shutil.rmtree fails on missing path)
- ❌ No validation of path safety (could delete wrong directory if path is corrupted)

**Comparison:**
`stop()` method (line 749) HAS proper validation:
```python
def stop(self, use_docker: bool = False, force: bool = False, is_aea: bool = True) -> None:
    if self.status != DeploymentStatus.DEPLOYED and not force:
        return  # ✅ State validation!
```

**Recommended Fix:**
```python
def delete(self) -> None:
    """Delete the deployment."""
    # Validate state before destructive operation
    if self.status == DeploymentStatus.DEPLOYED:
        raise ValueError(
            f"Cannot delete deployment in {self.status} state. "
            "Stop the service first."
        )

    build = self.path / DEPLOYMENT_DIR

    # Validate path exists and is safe
    if not build.exists():
        self.logger.warning(f"Deployment directory {build} does not exist")
        self.status = DeploymentStatus.DELETED
        self.store()
        return

    # Additional safety: verify path is within service directory
    if not str(build.resolve()).startswith(str(self.path.resolve())):
        raise ValueError(f"Invalid deployment path: {build}")

    shutil.rmtree(build)
    self.status = DeploymentStatus.DELETED
    self.store()
```

**Test Cases Needed:**
```python
def test_delete_deployed_service_raises_error():
    """Cannot delete a deployed (running) service."""
    service.status = DeploymentStatus.DEPLOYED
    with pytest.raises(ValueError, match="Cannot delete.*Stop"):
        service.deployment.delete()

def test_delete_missing_deployment_graceful():
    """Deleting non-existent deployment is graceful."""
    shutil.rmtree(service.deployment.path / DEPLOYMENT_DIR)
    service.deployment.delete()  # Should not raise

def test_delete_invalid_path_raises_error():
    """Cannot delete path outside service directory."""
    service.deployment.path = Path("/etc")  # Dangerous!
    with pytest.raises(ValueError, match="Invalid deployment path"):
        service.deployment.delete()
```

---

### 2. Address Validation Missing in Funding ⚠️

**File:** `operate/services/funding_manager.py:975-1010`

**Issue:**
```python
def fund_service(self, service: Service, amounts: ChainAmounts) -> None:
    for chain_str, addresses in amounts.items():
        for address in addresses:
            # Only checks if address is in agent_addresses or multisig
            # Does NOT validate address format/checksum
            if (address not in service.agent_addresses and
                address != service.chain_configs[chain_str].chain_data.multisig):
                raise ValueError(f"Address {address} is not an agent EOA or service Safe")
```

**Problems:**
- ❌ No Ethereum address format validation (must be 42 chars, start with 0x)
- ❌ No EIP-55 checksum validation (prevents typos)
- ❌ No validation that address is not zero address (0x000...000)

**Recommended Fix:**
```python
from eth_utils import is_address, is_checksum_address, to_checksum_address

def _validate_ethereum_address(address: str, field_name: str = "address") -> str:
    """Validate and normalize Ethereum address.

    :param address: Address to validate
    :param field_name: Field name for error messages
    :return: Checksummed address
    :raises ValueError: If address is invalid
    """
    if not address or not isinstance(address, str):
        raise ValueError(f"{field_name} must be a non-empty string")

    # Check format (42 chars, starts with 0x)
    if not is_address(address):
        raise ValueError(
            f"Invalid {field_name}: {address}. "
            "Must be 42-character hex string starting with 0x"
        )

    # Check not zero address
    if address.lower() == "0x0000000000000000000000000000000000000000":
        raise ValueError(f"{field_name} cannot be zero address")

    # Validate checksum if provided (case-sensitive)
    if not address.islower() and not is_checksum_address(address):
        raise ValueError(
            f"Invalid {field_name} checksum: {address}. "
            f"Expected: {to_checksum_address(address)}"
        )

    return to_checksum_address(address)

def fund_service(self, service: Service, amounts: ChainAmounts) -> None:
    """Fund service-related wallets."""
    service_config_id = service.service_config_id

    # Validate all addresses BEFORE starting funding
    for chain_str, addresses in amounts.items():
        for address in addresses:
            # Validate format and checksum
            validated_address = self._validate_ethereum_address(
                address,
                f"funding address on {chain_str}"
            )

            # Validate address is authorized
            if (validated_address not in service.agent_addresses and
                validated_address != service.chain_configs[chain_str].chain_data.multisig):
                raise ValueError(
                    f"Address {validated_address} is not an agent EOA or service Safe "
                    f"for service {service_config_id}"
                )
```

**Test Cases Needed:**
```python
def test_fund_service_invalid_address_format():
    """Reject malformed addresses."""
    amounts = {"ethereum": {"not_an_address": {ZERO_ADDRESS: 1000}}}
    with pytest.raises(ValueError, match="Invalid.*Must be 42-character"):
        funding_manager.fund_service(service, amounts)

def test_fund_service_invalid_checksum():
    """Reject addresses with invalid checksum."""
    # Valid format but wrong checksum
    amounts = {"ethereum": {"0x1234567890123456789012345678901234567890": {ZERO_ADDRESS: 1000}}}
    with pytest.raises(ValueError, match="Invalid.*checksum"):
        funding_manager.fund_service(service, amounts)

def test_fund_service_zero_address():
    """Reject zero address."""
    amounts = {"ethereum": {ZERO_ADDRESS: {ZERO_ADDRESS: 1000}}}
    with pytest.raises(ValueError, match="cannot be zero address"):
        funding_manager.fund_service(service, amounts)
```

---

### 3. Amount Validation - Silent Skipping vs Rejection ℹ️

**File:** `operate/services/funding_manager.py:961-962`

**Current Behavior:**
```python
for asset, amount in assets.items():
    if amount <= 0:
        continue  # Silently skip invalid amounts
```

**Issue:**
- Non-positive amounts are silently ignored
- Caller doesn't know their request was invalid
- Could hide bugs where amounts are computed incorrectly

**Recommended Fix:**
```python
def _validate_funding_amount(amount: int, chain: str, asset: str, address: str) -> None:
    """Validate funding amount is positive and reasonable.

    :raises ValueError: If amount is invalid
    """
    if not isinstance(amount, int):
        raise TypeError(f"Amount must be integer, got {type(amount)}")

    if amount <= 0:
        raise ValueError(
            f"Funding amount must be positive. "
            f"Got {amount} for {asset} on {chain} to {address}"
        )

    # Optional: Check for suspiciously large amounts (potential bugs)
    MAX_REASONABLE_AMOUNT = 10**30  # 1 trillion tokens with 18 decimals
    if amount > MAX_REASONABLE_AMOUNT:
        raise ValueError(
            f"Funding amount {amount} exceeds maximum reasonable value. "
            f"This might indicate a calculation error."
        )

def fund_chain_amounts(...):
    for address, assets in addresses.items():
        for asset, amount in assets.items():
            # Validate instead of silently skipping
            self._validate_funding_amount(amount, chain.value, asset, address)

            self.logger.info(...)
            wallet.transfer(...)
```

**Alternative (Keep Skip with Warning):**
```python
if amount <= 0:
    self.logger.warning(
        f"[FUNDING MANAGER] Skipping invalid amount {amount} "
        f"for {asset} to {address} on {chain.value}"
    )
    continue
```

---

## Lower Priority Gaps

### 4. Service State Transitions Not Validated

**File:** `operate/services/service.py`

**Issue:**
Status can be set directly without validation:
```python
self.status = DeploymentStatus.DELETED  # No validation of transition
```

**Valid Transitions:**
```
BUILT -> DEPLOYING -> DEPLOYED -> STOPPING -> STOPPED -> BUILT
                                           \-> DELETED
```

**Invalid Transitions (Should Reject):**
- DEPLOYED -> DELETED (must stop first)
- STOPPING -> DEPLOYING (must complete stop)
- Any state -> random state (enforce state machine)

**Recommended Fix:**
```python
class Deployment:
    VALID_TRANSITIONS = {
        DeploymentStatus.BUILT: {DeploymentStatus.DEPLOYING},
        DeploymentStatus.DEPLOYING: {DeploymentStatus.DEPLOYED, DeploymentStatus.BUILT},
        DeploymentStatus.DEPLOYED: {DeploymentStatus.STOPPING},
        DeploymentStatus.STOPPING: {DeploymentStatus.STOPPED, DeploymentStatus.BUILT},
        DeploymentStatus.STOPPED: {DeploymentStatus.BUILT, DeploymentStatus.DELETED},
    }

    def set_status(self, new_status: DeploymentStatus, force: bool = False) -> None:
        """Set status with transition validation."""
        if not force and self.status not in self.VALID_TRANSITIONS:
            raise ValueError(f"No transitions defined for state {self.status}")

        if not force and new_status not in self.VALID_TRANSITIONS[self.status]:
            raise ValueError(
                f"Invalid state transition: {self.status} -> {new_status}. "
                f"Valid transitions: {self.VALID_TRANSITIONS[self.status]}"
            )

        self.status = new_status
```

---

## Summary of Recommended Actions

**High Priority:**
1. ✅ Add state validation to `Deployment.delete()` (Prevents deleting running services)
2. ✅ Add Ethereum address validation to funding operations (Prevents typos/corruption)
3. ✅ Add path safety checks to destructive operations (Prevents accidental deletions)

**Medium Priority:**
4. ⚠️ Validate amounts (reject vs skip) - decide on error handling strategy
5. ⚠️ Add state transition validation - enforce state machine

**Implementation Plan:**
1. Create validation utility functions in `operate/utils/validation.py`
2. Add validation to critical operations (delete, fund)
3. Add comprehensive test coverage
4. Document validation requirements

**Test Coverage Goals:**
- Negative tests for each validation (invalid inputs raise proper errors)
- Edge cases (zero address, negative amounts, invalid states)
- Error messages are clear and actionable

---

**Last Updated:** 2026-02-10
**Status:** Analysis Complete - Ready for Implementation
