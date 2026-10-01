# Olas-Operate API reference

## Authentication

Most endpoints require authentication. Users must first create an account and log in to access protected resources.

## Error Handling

All endpoints return consistent error responses in JSON format:

```json
{
  "error": "Error message description"
}
```

The API uses appropriate HTTP status codes:

- `400 Bad Request`: Invalid request parameters
- `401 Unauthorized`: Authentication required or invalid credentials
- `404 Not Found`: Resource not found
- `409 Conflict`: Resource already exists
- `500 Internal Server Error`: Server-side errors

## General API Information

### `GET /api`

Get basic API information.

**Response (Success - 200):**

```json
{
  "name": "Operate HTTP server",
  "version": "0.1.0.rc0",
  "home": "/path/to/operate/home"
}
```

### `GET /api/settings`

Get current settings.

**Response (Success - 200):**

```json
{
  "version": 1,
  "eoa_topups": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": "750000000000000000"
    }
  },
  "eoa_thresholds": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": 500000000000000000
    }
  }
}
```

## Account Management

### `GET /api/account`

Get account setup status.

**Response (Success - 200):**

```json
{
  "is_setup": true
}
```

### `POST /api/account`

Create a new user account.

**Request Body:**

```json
{
  "password": "your_password"
}
```

**Response (Success - 200):**

```json
{
  "error": null
}
```

**Response (Password too short - 400):**

```json
{
  "error": "Password must be at least 8 characters long."
}
```

**Response (Account exists - 409):**

```json
{
  "error": "Account already exists."
}
```

### `PUT /api/account`

Update account password.

**Request Body (with current password):**

```json
{
  "old_password": "your_old_password",
  "new_password": "your_new_password"
}
```

**Request Body (with mnemonic):**

```json
{
  "mnemonic": ["word1", "word2", "word3", ...],
  "new_password": "your_new_password"
}
```

**Response (Success - 200):**

```json
{
  "error": null,
  "message": "Password updated successfully."
}
```

**Response (Success with mnemonic - 200):**

```json
{
  "error": null,
  "message": "Password updated successfully using seed phrase."
}
```

**Response (Missing parameters - 400):**

```json
{
  "error": "Exactly one of 'old_password' or 'mnemonic' (seed phrase) is required."
}
```

**Response (Both parameters provided - 400):**

```json
{
  "error": "Exactly one of 'old_password' or 'mnemonic' (seed phrase) is required."
}
```

**Response (New password too short - 400):**

```json
{
  "error": "New password must be at least 8 characters long."
}
```

**Response (Invalid old password - 400):**

```json
{
  "error": "Failed to update password: Password is not valid."
}
```

**Response (Invalid mnemonic - 400):**

```json
{
  "error": "Failed to update password: Seed phrase is not valid."
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

**Response (Update failed - 500):**

```json
{
  "error": "Failed to update password. Please check the logs."
}
```

### `POST /api/account/login`

Validate user credentials and establish a session.

A successful login also starts two background jobs: the recurring funding job, and a one-shot service maintenance task. Maintenance failures never affect the login response; they are logged and retried at the next login.

**Request Body:**

```json
{
  "password": "your_password"
}
```

**Response (Success - 200):**

```json
{
  "message": "Login successful."
}
```

**Response (Invalid password - 401):**

```json
{
  "error": "Password is not valid."
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

## Wallet Management

### `GET /api/wallet`

Get all wallets.

**Response (Success - 200):**

```json
[
  {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": ["gnosis"],
    "safes": {
      "gnosis": "0x..."
    }
  }
]
```

### `POST /api/wallet`

Create a new wallet.

**Request Body:**

```json
{
  "ledger_type": "ethereum"
}
```

**Response (Success - 200):**

```json
{
  "wallet": {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": []
  },
  "mnemonic": ["word1", "word2", "word3", ...]
}
```

**Response (Wallet exists - 200):**

```json
{
  "wallet": {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": ["gnosis"],
    "safes": {
      "gnosis": "0x..."
    }
  },
  "mnemonic": null
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

### `POST /api/wallet/withdraw`

Withdraw funds to the target account, using Master Safe first and
falling back to Master EOA if needed. All Master Safe transfers of a
chain are batched into a single MultiSend transaction; only the Master
EOA legs (if any) settle as additional individual transactions. The
per-asset `transfer_txs` lists are preserved for compatibility — assets
withdrawn in the same batch share the same transaction hashes.

**Request Body:**

```json
{
  "password": "your_password",
  "to": "0x...",
  "withdraw_assets": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": "1000000000000000000",
      "0x...": "500000000000000000"
    }
  }
}
```

**Response (Success - 200):**

```json
{
  "message": "Funds withdrawn successfully.",
  "transfer_txs": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": ["0x...", "0x..."],  // Txs of the chain's batched withdrawal (shared across its assets): one batched Master Safe tx and/or Master EOA txs
      "0x...": ["0x...", "0x..."]
    }
  }
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Invalid password - 401):**

```json
{
  "error": "Password is not valid."
}
```

**Response (Insufficient funds - 400):**

```json
{
  "error": "Failed to withdraw funds. Insufficient funds: (...)",
  "transfer_txs": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": ["0x...", "0x..."],  // Txs of the chain's batched withdrawal (shared across its assets): one batched Master Safe tx and/or Master EOA txs
      "0x...": ["0x...", "0x..."]
    }
  }  
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to withdraw funds. Please check the logs.",
  "transfer_txs": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": ["0x...", "0x..."],  // Txs of the chain's batched withdrawal (shared across its assets): one batched Master Safe tx and/or Master EOA txs
      "0x...": ["0x...", "0x..."]
    }
  }  
}
```

### `POST /api/wallet/private_key`

Get Master EOA private key.

**Request Body:**

```json
{
  "password": "your_password",
  "ledger_type": "ethereum"
}
```

**Response (Success - 200):**

```json
{
  "private_key": "0x..."
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Invalid password - 401):**

```json
{
  "error": "Password is not valid."
}
```

### `POST /api/wallet/mnemonic`

Get Master EOA mnemonic.

**Request Body:**

```json
{
  "password": "your_password",
  "ledger_type": "ethereum"
}
```

**Response (Success - 200):**

```json
{
  "mnemonic": ["word1", "word2", "word3", ...]
}
```

**Response (Mnemonic file does not exist - 404):**

```json
{
  "error": "Mnemonic file does not exist."
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Invalid password - 401):**

```json
{
  "error": "Password is not valid."
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to retrieve mnemonic. Please check the logs."
}
```

### `GET /api/wallet/extended`

Get extended wallet information including safes and additional metadata.

**Response (Success - 200):**

```json
[
  {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": ["gnosis"],
    "safes": {
      "gnosis": {
        "0x...": {
          "backup_owners": ["0x..."],
          "balances": {
            "0x0000000000000000000000000000000000000000": "1000000000000000000",
            "0x...": "500000000000000000"
          }
        }
      }
    },
    "balances": {
      "gnosis": {
        "0x...": {
            "0x0000000000000000000000000000000000000000": "1000000000000000000",
            "0x...": "500000000000000000"
        },
        "0x...": {
            "0x0000000000000000000000000000000000000000": "1000000000000000000",
            "0x...": "500000000000000000"
        },        
      }
    },
    "extended_json": true,
    "all_safes_have_backup_owner": true,
    "consistent_safe_address": true,
    "consistent_backup_owner": true,
    "consistent_backup_owner_count": true
  }
]
```

**Response (No safes - 200):**

```json
[
  {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": []
  }
]
```

### `GET /api/wallet/safe`

Get all safes for all wallets.

**Response (Success - 200):**

```json
[
  {
    "ethereum": ["0x..."]
  }
]
```

## Wallet Recovery

### `POST /api/wallet/recovery/prepare`

Prepare wallet recovery. Creates a new recovery bundle or returns the last incomplete bundle if it contains partial backup owner swaps.

**Request Body:**

```json
{
  "new_password": "your_new_password"
}
```

**Response (Success - 200):**

```json
{
  "id": "bundle_123",
  "wallets": [
    {
      "current_wallet": {
        "address": "0x...",
        "safes": {
          "gnosis": {
            "0x...": {
              "owners": ["0x...", "0x..."],
              "backup_owners": ["0x...", "0x..."],
              "owner_to_remove": "0x...",
              "owner_to_add": "0x..."
            }
          },
          "base": {
            "0x...": {
              "owners": ["0x...", "0x..."],
              "backup_owners": ["0x...", "0x..."],
              "owner_to_remove": "0x...",
              "owner_to_add": "0x..."
            }
          }
        },
        "safe_chains": [
          "gnosis",
          "base"
        ],
        "ledger_type": "ethereum",
        "safe_nonce": 1234567890
      },
      "new_wallet": {
        "address": "0x...",
        "safes": {},
        "safe_chains": [],
        "ledger_type": "ethereum",
        "safe_nonce": 1234567890
      },
      "new_mnemonic": ["word1", "word2", "word3", ...]
    },
  ],
  "status": "PREPARED",
  "all_safes_have_backup_owner": true,
  "consistent_safe_address": true,
  "consistent_backup_owner": true,
  "consistent_backup_owner_count": true,
  "prepared": true,
  "has_swaps": false,
  "has_pending_swaps": true,
  "num_safes": 2,
  "num_safes_with_new_wallet": 0,
  "num_safes_with_old_wallet": 2,
  "num_safes_with_both_wallets": 0
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

**Response (Logged in - 403):**

```json
{
  "error": "User must be logged out to perform this operation."
}
```

**Response (Password too short - 400):**

```json
{
  "error": "New password must be at least 8 characters long."
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to prepare recovery. Please check the logs."
}
```

### `GET /api/wallet/recovery/funding_requirements`

Get backup owner funding requirements to complete wallet recovery process.

**Response (Success - 200):**

```json
{
  "balances": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "1000000000000000000"
      }
    }
  },
  "total_requirements": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "2000000000000000000"
      }
    }
  },
  "refill_requirements": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "500000000000000000"
      }
    }
  },
  "is_refill_required": true,
  "pending_backup_owner_swaps": {
    "gnosis": ["0x..."]
  }
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to retrieve recovery funding requirements. Please check the logs."
}
```

### `GET /api/wallet/recovery/status`

Get recovery status.

**Response (Success - 200):**

```json
{
  "id": "bundle_123",
  "wallets": [
    {
      "current_wallet": {
        "address": "0x...",
        "safes": {
          "gnosis": {
            "0x...": {
              "owners": ["0x...", "0x..."],
              "backup_owners": ["0x...", "0x..."],
              "owner_to_remove": null,
              "owner_to_add": null
            }
          },
          "base": {
            "0x...": {
              "owners": ["0x...", "0x..."],
              "backup_owners": ["0x...", "0x..."],
              "owner_to_remove": "0x...",
              "owner_to_add": "0x..."
            }
          }
        },
        "safe_chains": [
          "gnosis",
          "base"
        ],
        "ledger_type": "ethereum",
        "safe_nonce": 1234567890
      },
      "new_wallet": {
        "address": "0x...",
        "safes": {},
        "safe_chains": [],
        "ledger_type": "ethereum",
        "safe_nonce": 1234567890
      },
      "new_mnemonic": null
    },
  ],
  "status": "IN_PROGRESS",
  "all_safes_have_backup_owner": true,
  "consistent_safe_address": true,
  "consistent_backup_owner": true,
  "consistent_backup_owner_count": true,
  "prepared": true,
  "has_swaps": false,
  "has_pending_swaps": true,
  "num_safes": 2,
  "num_safes_with_new_wallet": 1,
  "num_safes_with_old_wallet": 1,
  "num_safes_with_both_wallets": 0
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to retrieve recovery status. Please check the logs."
}
```

### `POST /api/wallet/recovery/complete`

Complete wallet recovery.

**Request Body:**

```json
{
  "require_consistent_owners": true
}
```

New MasterEOA (output from `POST /api/wallet/recovery/prepare`) must be an owner of all Safes where current (old) MasterEOA is an owner. Additionally, the flag `require_consistent_owners` enforces the following checks to proceed:

- Current (old) MasterEOA cannot be a Safe owner.
- All Safes must have two owners (new MasterEOA and a backup owner).
- All backup owners must match in all Safes.

**Response (Success - 200):**

```json
[
  {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": ["gnosis"],
    "safes": {
      "gnosis": "0x...",
      "base": "0x..."
    },
    "safe_chains": [
      "gnosis",
      "base"
    ],
    "ledger_type": "ethereum",
    "safe_nonce": 1234567890
  }
]
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

**Response (Logged in - 403):**

```json
{
  "error": "User must be logged out to perform this operation."
}
```

**Response (Bundle ID not provided - 400):**

```json
{
  "error": "Failed to complete recovery: 'bundle_id' must be a non-empty string."
}
```

**Response (Bundle does not exist - 404):**

```json
{
  "error": "Failed to complete recovery: Recovery bundle bundle_123 does not exist."
}
```

**Response (Bundle already executed - 400):**

```json
{
  "error": "Failed to complete recovery: Recovery bundle bundle_123 has been executed already."
}
```

**Response (Invalid password - 400):**

```json
{
  "error": "Failed to complete recovery: Password is not valid."
}
```

**Response (Missing owner - 400):**

```json
{
  "error": "Failed to complete recovery: Incorrect owners. Wallet 0x... is not an owner of Safe 0x... on <chain>."
}
```

**Response (Inconsistent owners - 400):**

Only if `require_consistent_owners = true`.

```json
{
  "error": "Failed to complete recovery: Inconsistent owners. Current wallet 0x... is still an owner of Safe 0x... on <chain>."
}
```

**Response (Inconsistent owners - 400):**

Only if `require_consistent_owners = true`.

```json
{
  "error": "Failed to complete recovery: Inconsistent owners. Safe 0x... on <chain> has <N> != 2 owners."
}
```

**Response (Inconsistent owners - 400):**

Only if `require_consistent_owners = true`.

```json
{
  "error": "Failed to complete recovery: Inconsistent owners. Backup owners differ across Safes on chains <chain_1>, <chain_2>. Found backup owners: 0x..., 0x... ."
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to complete recovery. Please check the logs."
}
```

## Safe Management

### `GET /api/wallet/safe/{chain}`

Get the safe address for a specific chain.

**Response (Success - 200):**

```json
{
  "safe": "0x..."
}
```

**Response (No wallet - 404):**

```json
{
  "error": "No Master EOA found for this chain."
}
```

**Response (No safe - 404):**

```json
{
  "error": "No Master Safe found for this chain."
}
```

### `POST /api/wallet/safe`

Create or ensure a Gnosis Safe exists for the specified chain and fund it if needed.

The endpoint automatically skips Safe creation if one already exists for the chain. It will only perform transfers if additional funds are required (or if excess assets should be swept when `transfer_excess_assets` is enabled).

**Important note on transactions:**  
The endpoint only returns transaction hashes (`create_tx` and `transfer_txs`) for actions actually executed **during the current request**. If the Safe already exists and is sufficiently funded, no transactions are performed and the fields will be `null` / empty. The client is responsible for tracking transaction hashes across multiple calls if needed (e.g. for confirmation or monitoring).

**Request Body:**

```json
{
  "chain": "gnosis",
  "backup_owner": "0x...",
  "initial_funds": {
    "0x0000000000000000000000000000000000000000": "1000000000000000000"
  }
}
```

**Request Body (with transfer excess assets):**

```json
{
  "chain": "gnosis", 
  "backup_owner": "0x...",
  "transfer_excess_assets": "true"
}
```

**Response (Safe created, funding - 200):**

```json
{
  "safe": "0x...",
  "create_tx": "0x...",
  "transfer_txs": {
    "0x0000000000000000000000000000000000000000": "0x..."
  },
  "transfer_errors": {},
  "message": "Safe created and funded successfully.",
  "status": "SAFE_CREATED_TRANSFER_COMPLETED"
}
```

**Response (Safe created, funding failed - 200):**

```json
{
  "safe": "0x...",
  "create_tx": "0x...",
  "transfer_txs": {
    "0x0000000000000000000000000000000000000000": "0x..."
  },
  "transfer_errors": {
    "0x0000000000000000000000000000000000000000": "0x..."
  },
  "message": "Safe created but some funding transactions failed.",
  "status": "SAFE_CREATED_TRANSFER_FAILED"
}
```

**Response (Safe exists, funding - 200):**

```json
{
  "safe": "0x...",
  "create_tx": null,
  "transfer_txs": {
    "0x0000000000000000000000000000000000000000": "0x..."
  },
  "transfer_errors": {},
  "message": "Safe already exists and funded successfully.",
  "status": "SAFE_EXISTS_TRANSFER_COMPLETED"
}
```

**Response (Safe exists, funding failed - 200):**

```json
{
  "safe": "0x...",
  "create_tx": null,
  "transfer_txs": {
    "0x0000000000000000000000000000000000000000": "0x..."
  },
  "transfer_errors": {
    "0x0000000000000000000000000000000000000000": "0x..."
  },
  "message": "Safe already exists but some funding transactions failed.",
  "status": "SAFE_EXISTS_TRANSFER_FAILED"
}
```

**Response (Safe exists, no funding needed - 200):**

```json
{
  "safe": null,
  "create_tx": null,
  "transfer_txs": {},
  "transfer_errors": {},
  "message": "Safe already exists and is sufficiently funded.",
  "status": "SAFE_EXISTS_ALREADY_FUNDED"
}
```

**Response (Safe creation failed - 200):**

```json
{
  "safe": null,
  "create_tx": null,
  "transfer_txs": {},
  "transfer_errors": {},
  "message": "Failed to create Safe.",
  "status": "SAFE_CREATION_FAILED"
}
```

**Response (Invalid request - 400):**

```json
{
  "error": "Only specify one of 'initial_funds' or 'transfer_excess_assets', but not both."
}
```

**Response (No wallet - 404):**

```json
{
  "error": "No Master EOA found for this chain."
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

### `PUT /api/wallet/safe`

Update safe settings, such as backup owner.

**Request Body:**

```json
{
  "chain": "gnosis",
  "backup_owner": "0x..."
}
```

**Response (Success - 200):**

```json
{
  "wallet": {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": ["gnosis"],
    "safes": {
      "gnosis": "0x..."
    }
  },
  "chain": "gnosis",
  "backup_owner_updated": true,
  "message": "Backup owner updated successfully"
}
```

**Response (No changes - 200):**

```json
{
  "wallet": {
    "address": "0x...",
    "ledger_type": "ethereum",
    "safe_chains": ["gnosis"],
    "safes": {
      "gnosis": "0x..."
    }
  },
  "chain": "gnosis",
  "backup_owner_updated": false,
  "message": "Backup owner is already set to this address"
}
```

**Response (No account - 404):**

```json
{
  "error": "User account not found."
}
```

**Response (No chain specified - 400):**

```json
{
  "error": "'chain' is required."
}
```

**Response (No wallet - 400):**

```json
{
  "error": "No Master EOA found for this chain."
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

#### Bulk path: `chain: "all"`

When `chain` is `"all"` the call sets the **canonical backup owner** across every chain
where the Master Safe exists.  Two sub-cases apply:

| Sub-case | When | Password required? |
|----------|------|--------------------|
| **Add** | `canonical_backup_owner` is `null` (first time) | No |
| **Update** | `canonical_backup_owner` is already set | Yes |

**Request Body (Add — first time, no password):**

```json
{
  "chain": "all",
  "backup_owner": "0xNewBackupAddress"
}
```

**Request Body (Update — canonical already set, password required):**

```json
{
  "chain": "all",
  "backup_owner": "0xNewBackupAddress",
  "password": "..."
}
```

**Response (Success - 200):**

```json
{
  "canonical_backup_owner": "0xNewBackupAddress",
  "all_succeeded": true,
  "results": [
    {
      "chain": "gnosis",
      "safe": "0x...",
      "success": true,
      "error": null
    }
  ]
}
```

**Response (Missing password for Update - 400):**

```json
{
  "error": "'password' is required to update the canonical backup wallet."
}
```

**Response (Wrong password - 401):**

```json
{
  "error": "Invalid password."
}
```

**Response (Already linked - 409):**

```json
{
  "error": "Wallet Already Linked"
}
```

---

### `GET /api/wallet/safe/backup_owner/status`

Returns the **canonical backup owner** and its sync state relative to each chain's
on-chain Safe.

**Response (Success - 200):**

```json
{
  "canonical_backup_owner": "0xAbcDef...",
  "all_chains_synced": true,
  "any_backup_missing": false,
  "existing_backup_on_any_chain": true,
  "chains": [
    {
      "chain": "gnosis",
      "safe": "0xSafeAddress",
      "current_backup_owner": "0xAbcDef...",
      "is_synced": true
    }
  ],
  "chains_without_safe": []
}
```

**Field notes:**

| Field | Type | Description |
|-------|------|-------------|
| `canonical_backup_owner` | `string \| null` | The designated canonical backup address, or `null` if never set |
| `all_chains_synced` | `bool` | `true` when every chain's on-chain backup matches the canonical |
| `any_backup_missing` | `bool` | `true` when at least one chain has no backup owner on-chain |
| `existing_backup_on_any_chain` | `bool` | `true` when at least one chain has any on-chain backup, even if `canonical_backup_owner` is `null`.  Use this to distinguish "never had a backup" from "has an existing on-chain backup but canonical not yet designated". |
| `chains[].is_synced` | `bool` | Whether the chain's current on-chain backup matches the canonical |

---

### `POST /api/wallet/safe/backup_owner/sync`

Applies the canonical backup owner to any chains that are currently out of sync.

**Request Body:**

```json
{
  "password": "..."
}
```

**Response (Success - 200):**

```json
{
  "canonical_backup_owner": "0xAbcDef...",
  "all_succeeded": true,
  "results": [
    {
      "chain": "gnosis",
      "safe": "0x...",
      "success": true,
      "error": null
    }
  ]
}
```

## Service Management

### `GET /api/v2/services`

Get all valid services.

**Response (Success - 200):**

```json
[
  {
    "name": "My Service",
    "version": 9,
    "service_config_id": "service_123",
    "service_public_id": "valory/service_123:0.1.0",
    "package_path": "package",
    "hash": "bafybei...",
    "hash_history": {
      "1756295395": "bafybei..."
    },
    "agent_release": {
      "is_aea": true,
      "repository": {
        "owner": "org",
        "name": "repo",
        "release_tag": "v0.0.100"
      }
    },
    "agent_addresses": [
      "0x8EA6C20bcC4cCBE59463F579c363732D66F804F9"
    ],
    "home_chain": "gnosis",
    "chain_configs": {
      "gnosis": {
        "ledger_config": {
          "rpc": "https://rpc.gnosis.gateway.fm",
          "chain": "gnosis"
        },
        "chain_data": {
          "instances": ["0x..."],
          "token": "123",
          "multisig": "0x...",
          "staked": true,
          "on_chain_state": 3,
          "user_params": {
            "staking_program_id": "pearl_alpha",
            "nft": "bafybei...",
            "threshold": 1,
            "use_staking": true,
            "use_mech_marketplace": false,
            "cost_of_bond": "10000000000000000000",
            "fund_requirements": {
              "0x0000000000000000000000000000000000000000": {
                "agent": "100000000000000000",
                "safe": "500000000000000000"
              }
            }
          }
        }
      }
    },
    "description": "Service description",
    "env_variables": {
      "ENV_VAR_NAME": {
        "name": "Environment Variable Name",
        "description": "Description of the environment variable",
        "value": "Value of the environment variable",
        "provision_type": "fixed/computed/user"
      }
    }
  }
]
```

### `GET /api/v2/services/validate`

Check if all the services are valid and can be deployed.

**Response (Success - 200):**

```json
{
  "service_config_id1": true,
  "service_config_id2": true,
  "service_config_id3": false
}
```

### `GET /api/v2/services/deployment`

Get all services deployment information.

**Response (Success - 200):**

```json
{
  "service_config_id1": {
    "status": 3,  // DEPLOYED
    "nodes": {
      "agent": ["service_abci_0"],
      "tendermint": ["service_tm_0"]
    },
    "healthcheck": {
      "agent_health": {},
      "is_healthy": true,
      "is_tm_healthy": true,    
      "is_transitioning_fast": true,
      "period": 123,
      "reset_pause_duration": 30,
      "rounds": ["round_1", "round_2", "round_3"],
      "rounds_info": {},
      "seconds_since_last_transition": 12.34,
      "age_seconds": 4.1
    },
    "agent_liveness": {
      "is_alive": true,
      "reason": null,
      "last_checked_at": 1788940512.0,
      "last_healthy_at": 1788940512.0,
      "consecutive_failures": 0,
      "restarts_since_last_healthy": 0
    }
  },
  "service_config_id2": {
    "status": 1,  // BUILT
    "nodes": {
      "agent": [],
      "tendermint": []
    },
    "healthcheck": {},
    "agent_liveness": {
      "is_alive": false,
      "reason": "not_monitored",
      "last_checked_at": null,
      "last_healthy_at": null,
      "consecutive_failures": 0,
      "restarts_since_last_healthy": 0
    }
  },
  "service_config_id3": {
    "status": 1,  // BUILT
    "nodes": {
      "agent": [],
      "tendermint": []
    },
    "healthcheck": {},
    "agent_liveness": {
      "is_alive": false,
      "reason": "not_monitored",
      "last_checked_at": null,
      "last_healthy_at": null,
      "consecutive_failures": 0,
      "restarts_since_last_healthy": 0
    }
  }
}
```

`healthcheck.age_seconds` is the age of the on-disk healthcheck snapshot in
seconds. It is absent when no snapshot exists (`healthcheck` is `{}`) or when
the snapshot could not be read (`healthcheck` carries an `error` key).

`agent_liveness` reports whether the agent process is actually alive, as opposed
to `status`, which records the last deployment transition the middleware
performed. `reason` is `null` when `is_alive` is `true`, and otherwise one of:

| `reason` | Meaning |
|---|---|
| `agent_process_exited` | The health probe is failing and `agent.pid` is absent or invalid. |
| `agent_reported_unhealthy` | The agent answered the health probe, promptly and well-formed, and reported itself unhealthy. It is running and serving HTTP; its own view of its progress is what failed. The evidence is on the sibling `healthcheck` key — `is_tm_healthy`, `is_transitioning_fast` and `seconds_since_last_transition` — and in `cli.log`. |
| `agent_unresponsive` | The health probe is failing, the agent did not answer usefully, and the recorded agent process is live. |
| `evicted_cannot_restake` | The service is evicted on-chain, the middleware could not clear the eviction, and stopped the service rather than restarting into the same condition. |
| `not_monitored` | No health-check job is running for this service — it is not the running instance, or `HEALTH_CHECKER_OFF=1`. |
| `stopped_by_failfast` | The middleware restarted the service too many times inside its failfast window and stopped it rather than restarting again. Health checking ends with it, so nothing will move this service off this value until the operator starts it again. |

Clients that do not read `agent_liveness` are unaffected. A client that renders
"agent is not running" must not read `is_alive` on its own. Two values mean
**unknown**, not "not alive", and a client that treats either as "not alive"
reports a running agent as down:

- a **missing** `agent_liveness` — an older middleware that does not send the field;
- `reason: "not_monitored"` — present, and carrying `is_alive: false`, but it only
  says nothing is probing this service. The middleware falls back to the agent PID
  file here, and that probe matches on process names, so a healthy agent can land
  on this value.

The reasons that do positively establish the agent is not healthy are
`agent_process_exited`, `agent_reported_unhealthy`, `agent_unresponsive`,
`evicted_cannot_restake` and `stopped_by_failfast`. Of those,
`agent_reported_unhealthy` is the one where the agent process is demonstrably up
and answering — a client rendering "agent is not running" should treat it as "not
making progress", not as "down".

`stopped_by_failfast` and `evicted_cannot_restake` are the two that describe a
service the middleware has deliberately left stopped. Both are terminal until the
operator acts: nothing restarts a health-check job after either, so neither value
will change on its own.

### `GET /api/v2/service/{service_config_id}`

Get a specific service.

**Response (Success - 200):**

```json
{
  "name": "My Service",
  "version": 9,
  "service_config_id": "service_123",
  "service_public_id": "valory/service_123:0.1.0",
  "package_path": "package",
  "hash": "bafybei...",
  "hash_history": {
    "1756295395": "bafybei..."
  },
  "agent_release": {
    "is_aea": true,
    "repository": {
      "owner": "org",
      "name": "repo",
      "release_tag": "v0.0.100"
    }
  },
  "agent_addresses": [
    "0x8EA6C20bcC4cCBE59463F579c363732D66F804F9"
  ],
  "home_chain": "gnosis",
  "chain_configs": {
    "gnosis": {
      "ledger_config": {
        "rpc": "https://rpc.gnosis.gateway.fm",
        "chain": "gnosis"
      },
      "chain_data": {
        "instances": ["0x..."],
        "token": "123",
        "multisig": "0x...",
        "staked": true,
        "on_chain_state": 3,
        "user_params": {
          "staking_program_id": "pearl_alpha",
          "nft": "bafybei...",
          "threshold": 1,
          "use_staking": true,
          "use_mech_marketplace": false,
          "cost_of_bond": "10000000000000000000",
          "fund_requirements": {
            "0x0000000000000000000000000000000000000000": {
              "agent": "100000000000000000",
              "safe": "500000000000000000"
            }
          }
        }
      }
    }
  },
  "description": "Service description",
  "env_variables": {
    "ENV_VAR_NAME": {
      "name": "Environment Variable Name",
      "description": "Description of the environment variable",
      "value": "Value of the environment variable",
      "provision_type": "fixed/computed/user"
    }
  }
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

### `GET /api/v2/service/{service_config_id}/deployment`

Get service deployment information.

**Response (Success - 200):**

```json
{
  "status": 3,  // DEPLOYED
  "nodes": {
    "agent": ["service_abci_0"],
    "tendermint": ["service_tm_0"]
  },
  "healthcheck": {
    "agent_health": {},
    "is_healthy": true,
    "is_tm_healthy": true,    
    "is_transitioning_fast": true,
    "period": 123,
    "reset_pause_duration": 30,
    "rounds": ["round_1", "round_2", "round_3"],
    "rounds_info": {},
    "seconds_since_last_transition": 12.34,
    "age_seconds": 4.1
  },
  "agent_liveness": {
    "is_alive": true,
    "reason": null,
    "last_checked_at": 1788940512.0,
    "last_healthy_at": 1788940512.0,
    "consecutive_failures": 0,
    "restarts_since_last_healthy": 0
  }
}
```

See `GET /api/v2/services/deployment` above for the `agent_liveness` and
`healthcheck.age_seconds` fields.

**Response (Success with empty healthcheck - 200):**

```json
{
  "status": 1,  // BUILT
  "nodes": {
    "agent": [],
    "tendermint": []
  },
  "healthcheck": {},
  "agent_liveness": {
    "is_alive": false,
    "reason": "not_monitored",
    "last_checked_at": null,
    "last_healthy_at": null,
    "consecutive_failures": 0,
    "restarts_since_last_healthy": 0
  }
}
```

**Response (Success with healthcheck error - 200):**

```json
{
  "status": 3,  // DEPLOYED
  "nodes": {
    "agent": ["service_abci_0"],
    "tendermint": ["service_tm_0"]
  },
  "healthcheck": {
    "error": "Error reading healthcheck.json: [Errno 2] No such file or directory"
  },
  "agent_liveness": {
    "is_alive": false,
    "reason": "agent_process_exited",
    "last_checked_at": 1788940512.0,
    "last_healthy_at": 1788940031.0,
    "consecutive_failures": 47,
    "restarts_since_last_healthy": 5
  }
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

### `GET /api/v2/service/{service_config_id}/agent_performance`

Get agent performance information.

**Response (Success - 200):**

```json
{
  "last_activity": {
    "title": "Last activity title",
    "description": "Last activity description",
  },
  "last_chat_message": "Agent last chat message",
  "metrics": [
    {
      "description": "Metric description",
      "is_primary": true,
      "name": "Metric name",
      "value": "Metric value"
    }
  ],
  "timestamp": 1234567890
}
```

**Response (Success with empty agent performance - 200):**

```json
{
  "last_activity": null,
  "last_chat_message": null,
  "metrics": [],
  "timestamp": null
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

### `GET /api/v2/service/{service_config_id}/funding_requirements`

Get service funding requirements by asking the agent also.

Notes:

- If `agent_funding_in_progress` is `true`, then `agent_funding_requests` might reflect an inaccurate value, as the agent might not have had time to receive funds and reconsider new funding requests.
- If `agent_funding_requests_cooldown` is `true`, it means a recent call to `/api/v2/service/{service_config_id}/fund` has occurred. Agent requests are ignored during the cooldown period, and the `agent_funding_requests` dictionary will be empty. The default cooldown period is 5 minutes. 

**Response (Success - 200):**

```json
{
  "balances": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "1000000000000000000"
      }
    }
  },
  "bonded_assets": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": "500000000000000000"
    }
  },
  "total_requirements": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "2000000000000000000"
      }
    }
  },
  "refill_requirements": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "500000000000000000"
      }
    }
  },
  "protocol_asset_requirements": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": "1000000000000000000"
    }
  },
  "agent_funding_requests": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "500000000000000000"
      }
    }
  },
  "is_refill_required": true,
  "allow_start_agent": true,
  "agent_funding_requests_cooldown": false,
  "agent_funding_in_progress": false,
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

### `GET /api/v2/service/{service_config_id}/refill_requirements`

Get service refill requirements.

**Response (Success - 200):**

```json
{
  "balances": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "1000000000000000000"
      }
    }
  },
  "bonded_assets": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": "500000000000000000"
    }
  },
  "total_requirements": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "2000000000000000000"
      }
    }
  },
  "refill_requirements": {
    "gnosis": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "500000000000000000"
      }
    }
  },
  "protocol_asset_requirements": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": "1000000000000000000"
    }
  },
  "is_refill_required": true,
  "allow_start_agent": true
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

### `POST /api/v2/service`

Create a new service.

**Request Body:**

```json
{
  "name": "My Service",
  "version": 9,
  "service_config_id": "service_123",
  "service_public_id": "valory/service_123:0.1.0",
  "package_path": "package",
  "hash": "bafybei...",
  "hash_history": {
    "1756295395": "bafybei..."
  },
  "agent_release": {
    "is_aea": true,
    "repository": {
      "owner": "org",
      "name": "repo",
      "release_tag": "v0.0.100"
    }
  },
  "agent_addresses": [
    "0x8EA6C20bcC4cCBE59463F579c363732D66F804F9"
  ],
  "home_chain": "gnosis",
  "chain_configs": {
    "gnosis": {
      "ledger_config": {
        "rpc": "https://rpc.gnosis.gateway.fm",
        "chain": "gnosis"
      },
      "chain_data": {
        "instances": ["0x..."],
        "token": "123",
        "multisig": "0x...",
        "staked": true,
        "on_chain_state": 3,
        "user_params": {
          "staking_program_id": "pearl_alpha",
          "nft": "bafybei...",
          "threshold": 1,
          "use_staking": true,
          "use_mech_marketplace": false,
          "cost_of_bond": "10000000000000000000",
          "fund_requirements": {
            "0x0000000000000000000000000000000000000000": {
              "agent": "100000000000000000",
              "safe": "500000000000000000"
            }
          }
        }
      }
    }
  },
  "description": "Service description",
  "env_variables": {
    "ENV_VAR_NAME": {
      "name": "Environment Variable Name",
      "description": "Description of the environment variable",
      "value": "Value of the environment variable",
      "provision_type": "fixed/computed/user"
    }
  }
}
```

**Response (Success - 200):**

```json
{
  "name": "My Service",
  "version": 9,
  "service_config_id": "service_123",
  "service_public_id": "valory/service_123:0.1.0",
  "package_path": "package",
  "hash": "bafybei...",
  "hash_history": {
    "1756295395": "bafybei..."
  },
  "agent_release": {
    "is_aea": true,
    "repository": {
      "owner": "org",
      "name": "repo",
      "release_tag": "v0.0.100"
    }
  },
  "agent_addresses": [
    "0x8EA6C20bcC4cCBE59463F579c363732D66F804F9"
  ],
  "home_chain": "gnosis",
  "chain_configs": {
    "gnosis": {
      "ledger_config": {
        "rpc": "https://rpc.gnosis.gateway.fm",
        "chain": "gnosis"
      },
      "chain_data": {
        "instances": ["0x..."],
        "token": "123",
        "multisig": "0x...",
        "staked": true,
        "on_chain_state": 3,
        "user_params": {
          "staking_program_id": "pearl_alpha",
          "nft": "bafybei...",
          "threshold": 1,
          "use_staking": true,
          "use_mech_marketplace": false,
          "cost_of_bond": "10000000000000000000",
          "fund_requirements": {
            "0x0000000000000000000000000000000000000000": {
              "agent": "100000000000000000",
              "safe": "500000000000000000"
            }
          }
        }
      }
    }
  },
  "description": "Service description",
  "env_variables": {
    "ENV_VAR_NAME": {
      "name": "Environment Variable Name",
      "description": "Description of the environment variable",
      "value": "Value of the environment variable",
      "provision_type": "fixed/computed/user"
    }
  }
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

### `PUT /api/v2/service/{service_config_id}` <br /> `PATCH /api/v2/service/{service_config_id}`

Update a service configuration. Use `PUT` for full updates and `PATCH` for partial updates.

**Request Body:**

```json
{
  "name": "My Service",
  "version": 9,
  "service_config_id": "service_123",
  "package_path": "package",
  "hash": "bafybei...",
  "hash_history": {
    "1756295395": "bafybei..."
  },
  "agent_release": {
    "is_aea": true,
    "repository": {
      "owner": "org",
      "name": "repo",
      "release_tag": "v0.0.100"
    }
  },
  "agent_addresses": [
    "0x8EA6C20bcC4cCBE59463F579c363732D66F804F9"
  ],
  "home_chain": "gnosis",
  "chain_configs": {
    "gnosis": {
      "ledger_config": {
        "rpc": "https://rpc.gnosis.gateway.fm",
        "chain": "gnosis"
      },
      "chain_data": {
        "instances": ["0x..."],
        "token": "123",
        "multisig": "0x...",
        "staked": true,
        "on_chain_state": 3,
        "user_params": {
          "staking_program_id": "pearl_alpha",
          "nft": "bafybei...",
          "threshold": 1,
          "use_staking": true,
          "use_mech_marketplace": false,
          "cost_of_bond": "10000000000000000000",
          "fund_requirements": {
            "0x0000000000000000000000000000000000000000": {
              "agent": "100000000000000000",
              "safe": "500000000000000000"
            }
          }
        }
      }
    }
  },
  "description": "Service description",
  "env_variables": {
    "ENV_VAR_NAME": {
      "name": "Environment Variable Name",
      "description": "Description of the environment variable",
      "value": "Value of the environment variable",
      "provision_type": "fixed/computed/user"
    }
  },
  "allow_different_service_public_id": false
}
```

**Response (Success - 200):**

```json
{
  "name": "My Service",
  "version": 9,
  "service_config_id": "service_123",
  "package_path": "package",
  "hash": "bafybei...",
  "hash_history": {
    "1756295395": "bafybei..."
  },
  "agent_release": {
    "is_aea": true,
    "repository": {
      "owner": "org",
      "name": "repo",
      "release_tag": "v0.0.100"
    }
  },
  "agent_addresses": [
    "0x8EA6C20bcC4cCBE59463F579c363732D66F804F9"
  ],
  "home_chain": "gnosis",
  "chain_configs": {
    "gnosis": {
      "ledger_config": {
        "rpc": "https://rpc.gnosis.gateway.fm",
        "chain": "gnosis"
      },
      "chain_data": {
        "instances": ["0x..."],
        "token": "123",
        "multisig": "0x...",
        "staked": true,
        "on_chain_state": 3,
        "user_params": {
          "staking_program_id": "pearl_alpha",
          "nft": "bafybei...",
          "threshold": 1,
          "use_staking": true,
          "use_mech_marketplace": false,
          "cost_of_bond": "10000000000000000000",
          "fund_requirements": {
            "0x0000000000000000000000000000000000000000": {
              "agent": "100000000000000000",
              "safe": "500000000000000000"
            }
          }
        }
      }
    }
  },
  "description": "Service description",
  "env_variables": {
    "ENV_VAR_NAME": {
      "name": "Environment Variable Name",
      "description": "Description of the environment variable",
      "value": "Value of the environment variable",
      "provision_type": "fixed/computed/user"
    }
  }
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

### `POST /api/v2/service/{service_config_id}`

Deploy and run a service.

**Response (Success - 200):**

```json
{
  "name": "My Service",
  "version": 9,
  "service_config_id": "service_123",
  "service_public_id": "valory/service_123:0.1.0",
  "package_path": "package",
  "hash": "bafybei...",
  "hash_history": {
    "1756295395": "bafybei..."
  },
  "agent_release": {
    "is_aea": true,
    "repository": {
      "owner": "org",
      "name": "repo",
      "release_tag": "v0.0.100"
    }
  },
  "agent_addresses": [
    "0x8EA6C20bcC4cCBE59463F579c363732D66F804F9"
  ],
  "home_chain": "gnosis",
  "chain_configs": {
    "gnosis": {
      "ledger_config": {
        "rpc": "https://rpc.gnosis.gateway.fm",
        "chain": "gnosis"
      },
      "chain_data": {
        "instances": ["0x..."],
        "token": "123",
        "multisig": "0x...",
        "staked": true,
        "on_chain_state": 3,
        "user_params": {
          "staking_program_id": "pearl_alpha",
          "nft": "bafybei...",
          "threshold": 1,
          "use_staking": true,
          "use_mech_marketplace": false,
          "cost_of_bond": "10000000000000000000",
          "fund_requirements": {
            "0x0000000000000000000000000000000000000000": {
              "agent": "100000000000000000",
              "safe": "500000000000000000"
            }
          }
        }
      }
    }
  },
  "description": "Service description",
  "env_variables": {
    "ENV_VAR_NAME": {
      "name": "Environment Variable Name",
      "description": "Description of the environment variable",
      "value": "Value of the environment variable",
      "provision_type": "fixed/computed/user"
    }
  }
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Internal server error - 500):**

```json
{
  "error": "Internal error message."
}
```

### `POST /api/v2/service/{service_config_id}/deployment/stop`

Stop a running service deployment locally.

**Response (Success - 200):**

```json
{
  "status": 5,  // STOPPED
  "nodes": {
    "agent": [],
    "tendermint": []
  },
  "path": "/path/to/service",
  "healthcheck": {}
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Internal server error - 500):**

```json
{
  "error": "Internal error message."
}
```

### `[DEPRECATED] POST /api/v2/service/{service_config_id}/onchain/withdraw`

Withdraw all funds from a service and terminate it on-chain. This includes terminating the service on-chain and draining both the Master Safe and master signer.

**Request Body:**

```json
{
  "withdrawal_address": "0x..."
}
```

**Response (Success - 200):**

```json
{
  "error": null,
  "message": "Withdrawal successful"
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Missing withdrawal address - 400):**

```json
{
  "error": "'withdrawal_address' is required"
}
```

**Response (Withdrawal failed - 500):**

```json
{
  "error": "Failed to withdraw funds. Please check the logs."
}
```

### `POST /api/v2/service/{service_config_id}/terminate_and_withdraw`

Terminates and unbonds a service on-chain, and withdraws all the funds from the agent safe and agent signer to the Master Safe.

**Response (Success - 200):**

```json
{
  "error": null,
  "message": "Terminate and withdraw successful"
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Terminate and withdraw failed - 500):**

```json
{
  "error": "Failed to terminate and withdraw funds. Please check the logs."
}
```

### `GET /api/v2/service/{service_config_id}/safe_withdrawable_balance`

Get per-chain, per-token withdrawable balances for the Agent Safe. Native token balance is fully withdrawable (Safes do not pay their own gas — the signer EOA does). ERC20 balances are returned as-is.

**Response (Success - 200):**

```json
{
  "gnosis": {
    "withdrawable_amounts": {
      "0x0000000000000000000000000000000000000000": "1000000000000000000",
      "0xTokenAddress": "500000000000000000"
    }
  }
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to get withdrawable balance. Please check the logs."
}
```

### `POST /api/v2/service/{service_config_id}/withdraw_safe`

Withdraw user-specified amounts from the Agent Safe to the Master Safe without stopping the agent. ERC20 tokens are transferred before native to avoid depleting gas. Empty or zero-amount requests are treated as a no-op (200). The operation is non-atomic across chains — if a multi-chain withdrawal fails partway, `succeeded_chains` reflects which chains completed.

**Request Body:**

```json
{
  "amounts": {
    "gnosis": {
      "0x0000000000000000000000000000000000000000": "500000000000000000",
      "0xTokenAddress": "250000000000000000"
    }
  }
}
```

**Response (Success - 200):**

```json
{
  "error": null,
  "message": "Funds withdrawn successfully.",
  "succeeded_chains": ["gnosis"]
}
```

**Response (Invalid request - 400):**

```json
{
  "error": "Invalid withdrawal request.",
  "detail": "Requested amount for 0x... on gnosis exceeds withdrawable balance.",
  "succeeded_chains": []
}
```

**Response (Insufficient signer gas - 400):**

```json
{
  "error": "Partial withdrawal failed due to insufficient signer gas.",
  "succeeded_chains": [],
  "error_code": "INSUFFICIENT_SIGNER_GAS",
  "chain": "gnosis",
  "prefill_amount_wei": "750000000000000000"
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to withdraw funds. Please check the logs.",
  "succeeded_chains": []
}
```

### `POST /api/v2/service/{service_config_id}/fund`

Funds the agent or service Safe from Master Safe. Fails (409 - Request conflict) if a funding operation is already in progress.

**Request Body:**

```json
{
  "gnosis": {
    "0x...": {  // Agent EOA or service Safe
      "0x...": "1000000000000000000",  // token1: value
      "0x...": "1000000000000000000"   // token2: value
    }
  }
}
```

**Response (Success - 200):**

```json
{
  "error": null,
  "message": "Funded from Master Safe successfully"
}
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Invalid address - 400):**

```json
{
  "error": "Failed to fund from Master Safe. Address 0x... is not an agent EOA or service Safe for service service_123."
}
```

**Response (Insufficient funds - 400):**

```json
{
  "error": "Failed to fund from Master Safe. Insufficient funds: (...)"
}
```

**Response (Funding already in progress - 409):**

```json
{
  "error": "Funding already in progress for service service_123."
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to fund from Master Safe. Please check the logs."
}
```

## Service achievements

### `GET /api/v2/service/{service_config_id}/achievements`

Get service achievements notifications.

Query parameters:

- `include_acknowledged` (boolean, optional, default: `false`): Include acknowledged achievements.

**Response (Success - 200):**

```json
[
  {
    "achievement_id": "achievement_1",
    "acknowledged": false,
    "acknowledgement_timestamp": 0,
    "..."  # Achievement data
  },
  {
    "achievement_id": "achievement_2",
    "acknowledged": false,
    "acknowledgement_timestamp": 0,
    "..."  # Achievement data
  }
]
```

**Response (Service not found - 404):**

```json
{
  "error": "Service service_123 not found"
}
```

### `POST /api/v2/service/{service_config_id}/achievement/{achievement_id}/acknowledge`

Acknowledge a service achievement.

**Response (Success - 200):**

```json
{
  "error": null,
  "message": "Acknowledged achievement achievement_1 for service service_123 successfully."
}
```

**Response (Achievement already acknowledged - 400):**

```json
{
  "error": "Achievement achievement_1 was already acknowledged for service service_123."
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Achievement not found - 404):**

```json
{
  "error": "Achievement achievement_1 does not exist for service service_123."
}
```

## Bridge Management

### `POST /api/bridge/bridge_refill_requirements`

Get bridge refill requirements for cross-chain transactions.

**Request Body:**

```json
{
  "bridge_requests": [
    {
      "from": {
        "chain": "ethereum",
        "address": "0x<Master EOA or Master Safe>",
        "token": "0x0000000000000000000000000000000000000000"
      },
      "to": {
        "chain": "gnosis",
        "address": "0x...",
        "token": "0x0000000000000000000000000000000000000000",
        "amount": "1000000000000000000"
      }
    }
  ],
  "force_update": false
}
```

`from.address` must be the Master EOA or the Master Safe on `from.chain`.

**Response (Success - 200):**

```json
{
  "balances": {
    "ethereum": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "1000000000000000000"
      }
    }
  },
  "bridge_refill_requirements": {
    "ethereum": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "500000000000000000"
      }
    }
  },
  "bridge_total_requirements": {
    "ethereum": {
      "0x...": {
        "0x0000000000000000000000000000000000000000": "1500000000000000000"
      }
    }
  },
  "expiration_timestamp": 1234567890,
  "is_refill_required": true
}
```

**Response (Invalid parameters - 400):**
```json
{
  "error": "Invalid bridge request parameters."
}
```

**Response (Not logged in - 401):**
```json
{
  "error": "User not logged in."
}
```

### `POST /api/bridge/execute`

Execute bridge transaction.

**Request Body:**

```json
{
  "id": "bundle_123"
}
```

**Response (Success - 200):**

```json
{
  "id": "bundle_123",
  "bridge_request_status": [
    {
      "eta": 1234567890,
      "explorer_link": "https://gnosisscan.com/tx/0x...",
      "message": "Transaction executed successfully",
      "status": "EXECUTION_DONE",
      "tx_hash": "0x...",
    }
  ]
}
```

Individual bridge request status:

- `QUOTE_DONE`: A quote is available.
- `QUOTE_FAILED`: Failed to request a quote.
- `EXECUTION_PENDING`: Execution submitted and pending to be finalized.
- `EXECUTION_DONE`: Execution finalized successfully.<sup>&#8224;</sup>
- `EXECUTION_FAILED`: Execution failed.<sup>&#8224;</sup>
- `EXECUTION_UNKNOWN`: Execution unknown.

<sup>&#8224;</sup>Final status: bridge request status will not change after reaching this status.

**Response (Invalid bundle ID - 400):**

```json
{
  "error": "Invalid bundle ID or transaction failed."
}
```

**Response (Not logged in - 401):**

```json
{
  "error": "User not logged in."
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to execute bridge transaction. Please check the logs."
}
```

### `GET /api/bridge/last_executed_bundle_id`

Get the last executed bundle ID.

**Response (Success - 200):**

```json
{
  "id": "bundle_123"
}
```

### `GET /api/bridge/status/{id}`

Get bridge transaction status.

**Response (Success - 200):**

```json
{
  "id": "bundle_123",
  "bridge_request_status": [
    {
      "eta": 1234567890,
      "explorer_link": "https://gnosisscan.com/tx/0x...",
      "message": "Transaction executed successfully",
      "status": "EXECUTION_DONE",
      "tx_hash": "0x...",
    }
  ]
}
```

Individual bridge request status:

- `QUOTE_DONE`: A quote is available.
- `QUOTE_FAILED`: Failed to request a quote.
- `EXECUTION_PENDING`: Execution submitted and pending to be finalized.
- `EXECUTION_DONE`: Execution finalized successfully.<sup>&#8224;</sup>
- `EXECUTION_FAILED`: Execution failed.<sup>&#8224;</sup>
- `EXECUTION_UNKNOWN`: Execution unknown.

<sup>&#8224;</sup>Final status: bridge request status will not change after reaching this status.

**Response (Invalid bundle ID - 400):**

```json
{
  "error": "Invalid bundle ID."
}
```

**Response (Failed - 500):**

```json
{
  "error": "Failed to get bridge status. Please check the logs."
}
```

## Funding Run

A funding run turns **one** user transfer of a supported token on a supported chain into the tokens Pearl needs on the destination chain. The user sends to the Master EOA on the source chain (`source.deposit_address`); Pearl then bridges, swaps, creates the Master Safe if missing and moves the funds into it. USDC sources on Ethereum, Base, Optimism, Polygon and Arbitrum work from a zero native balance (EIP-7702 + ERC-4337, gas paid in USDC through Circle Paymaster). See [wallet-and-funding.md](wallet-and-funding.md#funding-run).

All routes return `401` (`{"error": "User not logged in."}`) when not logged in. Amounts are integer strings in base units; token `0x0000000000000000000000000000000000000000` is the chain's native token. The middleware returns kinds, tokens and amounts only; all user-facing copy is the app's.

### `GET /api/funding_run/sources`

The v1 source matrix (chain → accepted source tokens).

```json
{
  "sources": {
    "ethereum": ["0x0000000000000000000000000000000000000000", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"],
    "base": ["0x0000000000000000000000000000000000000000", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"],
    "optimism": ["0x0000000000000000000000000000000000000000", "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"],
    "polygon": ["0x0000000000000000000000000000000000000000", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"],
    "arbitrum_one": ["0x0000000000000000000000000000000000000000", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"],
    "gnosis": ["0x0000000000000000000000000000000000000000"],
    "robinhood": ["0x0000000000000000000000000000000000000000"]
  }
}
```

### `POST /api/funding_run`

Create a run, or replace a run that is still `AWAITING_DEPOSIT` / `QUOTE_FAILED` (this is how the app's "Change" works).

**Request Body:**

```json
{
  "mode": "onboard",
  "source": { "chain": "base", "token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913" },
  "destination": { "chain": "polygon" },
  "service_config_id": "sc-...",
  "deposit_amounts": null,
  "backup_owner": "0x..."
}
```

- `mode`:
  - `onboard`: the target is the service's net shortfall on its home chain. Requires `service_config_id`; `destination.chain` must be the service's home chain.
  - `deposit`: requires `deposit_amounts` (`{"<token>": "<amount>"}`), the **amounts to add** to the Pearl Wallet on `destination.chain`; what it already holds is not netted. `service_config_id` is ignored.
  - `signer_gas`: tops up the Master EOA native reserve (`DEFAULT_EOA_TOPUPS`) on `destination.chain`; the same value as `prefill_amount_wei` in `INSUFFICIENT_SIGNER_GAS` errors.
- `backup_owner` is used only if the Master Safe has to be created.

If every net target is already met, the run is created directly as `COMPLETED` with empty `steps` and `to_receive`.

**Response (Success - 200):** the run object, which every run route returns:

```json
{
  "id": "fr-3f2a...",
  "mode": "onboard",
  "status": "AWAITING_DEPOSIT",
  "source": { "chain": "base", "token": "0x8335...", "symbol": "USDC", "decimals": 6, "deposit_address": "0x<MasterEOA>" },
  "destination": { "chain": "polygon", "wallet": "master_safe" },
  "service_config_id": "sc-...",
  "quote": { "required_amount": "15000000", "received_amount": "4000000", "outstanding_amount": "11000000", "eta_seconds": 180, "quoted_at": 1790592071, "next_refresh_at": 1790592251 },
  "quote_message": null,
  "to_receive": [ { "token": "0x0000...", "symbol": "POL", "amount": "6000000000000000000" } ],
  "steps": [
    { "id": "receive", "kind": "RECEIVE", "status": "PENDING", "token": "0x8335...", "amount": "15000000", "tx_hash": null, "explorer_link": null, "started_at": null, "finished_at": null, "is_slow": false, "visible": true },
    { "id": "bridge", "kind": "BRIDGE", "status": "PENDING", "...": "..." },
    { "id": "native", "kind": "NATIVE", "status": "PENDING", "...": "..." },
    { "id": "swap:0xFEF5...", "kind": "SWAP", "status": "PENDING", "...": "..." },
    { "id": "safe", "kind": "SAFE_AND_TRANSFER", "status": "PENDING", "visible": false, "...": "..." },
    { "id": "clear_delegation", "kind": "CLEAR_DELEGATION", "status": "PENDING", "visible": false, "...": "..." }
  ],
  "error": null
}
```

- Run `status` ∈ `AWAITING_DEPOSIT | QUOTE_FAILED | PROCESSING | FAILED | COMPLETED | CANCELLED`; step `status` ∈ `PENDING | PROCESSING | DONE | FAILED`.
- `quote` is `null` until a quote succeeded; `quote_message` is `"Couldn't get a quote"` while `QUOTE_FAILED` (the provider detail is logged, not returned), or `"<SYMBOL> can't be delivered to <Chain> yet"` when a target token has no route at all (`FUNDING_RUN_UNROUTABLE`: OLAS on Gnosis and Mode). Such a run is never quoted. The quote is refreshed every `next_refresh_at`; once `outstanding_amount` reaches 0 the run re-quotes once more and moves to `PROCESSING`, after which the selection can no longer change.
- Step kinds: `RECEIVE` (the deposit arriving at the Master EOA), `BRIDGE` (the carrier moved to the destination chain; for a native source it is the only source-leg step), `NATIVE` (destination native for fees), one `SWAP` per remaining target token, then the hidden `SAFE_AND_TRANSFER` (`onboard`/`deposit` only) and `CLEAR_DELEGATION` (USDC sources only). `is_slow` flags a step running well past its ETA.
- `to_receive` is the **net** delivery: the shortfall after existing balances (`onboard`, `signer_gas`) or the entered amounts (`deposit`); it can be empty. A token outside the known token maps gets its `symbol` from its on-chain ERC-20 `symbol()`, or `null` when that cannot be read.
- `service_config_id` is the service an `onboard` run funds, so the app can tell one agent's run from another's; `null` for `deposit` and `signer_gas`.
- `destination.wallet` is `master_safe` for `onboard`/`deposit` and `master_eoa` for `signer_gas`.
- `error` is `{"step_id", "message"}` when `FAILED`. `message` is user-facing copy, never raw provider or RPC text (that is logged): `"Couldn't bridge to <Chain>"` (`BRIDGE`), `"Couldn't get <SYMBOL>"` (`NATIVE`, `SWAP`), `"Couldn't finish the transfer"` (anything else, or a `SWAP` whose token symbol cannot be read), or `"The transfer was sent but the bridge has not confirmed it yet. Try again in a few minutes."` when the outcome is not known yet. A hidden Safe/transfer failure is reported against the last visible step, with `"Couldn't finish the transfer"`. `CLEAR_DELEGATION` never sets `error` and never blocks `COMPLETED`.

**Errors:** `400` a malformed body, an unsupported source chain/token, a missing `deposit_amounts`/`service_config_id`, a `deposit_amounts` token the Pearl Wallet does not hold on that chain, or an `onboard` destination that is not the service home chain; `409` while another run is `PROCESSING`/`FAILED`. Every refusal carries one fixed `error` message per status (`"Invalid funding run request."`, `"Funding run not found."`, `"Funding run conflicts with the current run state."`); the detail is logged, not returned.

### `GET /api/funding_run/active`

The run object of the single non-terminal run. If there is none, the run that completed in the last 5 minutes (so the app can show the success modal after a restart); otherwise `null`. The app polls this route.

### `POST /api/funding_run/{id}/refresh_quote`

Re-quote now. Valid only in `AWAITING_DEPOSIT` / `QUOTE_FAILED`. No request body.

### `POST /api/funding_run/{id}/retry`

Resume a `FAILED` run at its failed step. A step whose on-chain effect has landed meanwhile (e.g. the Relay fill later succeeded) is reconciled instead of resent; only failed requests are re-quoted. A source-leg UserOperation that may still be included, or may already have been (the bundler still lists it; its EntryPoint nonce is used but neither the bundler nor the EntryPoint `UserOperationEvent` logs show it yet; or the lookup failed), is waited for again rather than replaced. One that stays unresolved for 30 minutes fails the run with the "not confirmed yet" message, so the user can retry.

### `DELETE /api/funding_run/{id}`

Cancel. Valid in `AWAITING_DEPOSIT` / `QUOTE_FAILED`, and in `FAILED` once nothing is still in flight, so a step that keeps failing does not block every later run. A `FAILED` run is `409` while its source-leg UserOperation may still land, a sent request is still pending, or a failed request may still deliver (the cases where `retry` shows the "not confirmed yet" message). Funds stay in the Master EOA, on whichever chain the run left them, and count toward the next quote. Cancelling a `FAILED` USDC-source run queues the background delegation clearing.

**Errors (run routes):** `404` unknown run id; `409` wrong state for the action.

## Store Management

Persistent key-value store backed by `.operate/pearl_store.json`. The store migrates with the `.operate` folder, allowing app state to persist across machine moves. Supports dot-notation keys for nested objects (e.g. `trader.isInitialFunded`).

### `GET /api/store`

Get the full store contents.

**Response (Success - 200):**

```json
{
  "data": {
    "trader": {
      "isInitialFunded": true
    },
    "autoRun": {
      "enabled": false
    }
  }
}
```

Returns `{"data": {}}` on first run when the store is empty.

---

### `POST /api/store`

Set a key in the store. Supports dot-notation for nested keys (e.g. `trader.isInitialFunded`).

**Request Body:**

```json
{
  "key": "trader.isInitialFunded",
  "value": true
}
```

**Response (Success - 200):**

```json
{
  "success": true
}
```

**Response (Missing or invalid key - 400):**

```json
{
  "error": "Missing or invalid 'key' field."
}
```

**Response (Malformed key - 400):**

```json
{
  "error": "Invalid key: segments must be non-empty (no leading, trailing, or consecutive dots)."
}
```

---

### `DELETE /api/store/{key}`

Delete a key from the store. Supports dot-notation for nested keys (e.g. `trader.isInitialFunded`).

**Path Parameters:**

| Parameter | Type   | Description                              |
|-----------|--------|------------------------------------------|
| `key`     | string | Dot-notation key to delete (e.g. `trader.isInitialFunded`) |

**Response (Success - 200):**

```json
{
  "success": true
}
```
