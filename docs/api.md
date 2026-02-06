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
falling back to Master EOA if needed.

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
      "0x0000000000000000000000000000000000000000": ["0x...", "0x..."],  // List of successful txs from Master Safe and/or Master EOA
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
      "0x0000000000000000000000000000000000000000": ["0x...", "0x..."],  // List of successful txs from Master Safe and/or Master EOA
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
      "0x0000000000000000000000000000000000000000": ["0x...", "0x..."],  // List of successful txs from Master Safe and/or Master EOA
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
    "path": "/path/to/service",
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
    }
  },
  "service_config_id2": {
    "status": 1,  // BUILT
    "nodes": {
      "agent": [],
      "tendermint": []
    },
    "healthcheck": {}
  },
  "service_config_id3": {
    "status": 1,  // BUILT
    "nodes": {
      "agent": [],
      "tendermint": []
    },
    "healthcheck": {}
  }
}
```

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
  "path": "/path/to/service",
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
  }
}
```

**Response (Success with empty healthcheck - 200):**

```json
{
  "status": 1,  // BUILT
  "nodes": {
    "agent": [],
    "tendermint": []
  },
  "path": "/path/to/service",
  "healthcheck": {}
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
  "path": "/path/to/service",
  "healthcheck": {
    "error": "Error reading healthcheck.json: [Errno 2] No such file or directory"
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
      "source_chain": "ethereum",
      "target_chain": "gnosis",
      "amount": "1000000000000000000",
      "asset": "0x0000000000000000000000000000000000000000"
    }
  ],
  "force_update": false
}
```

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
