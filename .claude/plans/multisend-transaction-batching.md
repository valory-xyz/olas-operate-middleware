# Plan: Batch middleware transactions via Gnosis Safe MultiSend

## Context

The middleware sends many on-chain transactions sequentially within single logical operations
(funding loop, drain, withdraw, service deployment cycle, stake, terminate). Each Safe
`execTransaction` carries ~40–70k gas overhead, settles independently (latency), and widens the
partial-failure window. The MultiSend batching machinery from open-autonomy is **already present
and proven** in `operate/services/protocol.py` (`GnosisSafeTransaction`, lines 131–236:
`.new_tx().add(...).add(...).settle()` → one Safe tx with `DELEGATE_CALL` into the MultiSend
contract), and the MultiSend address is configured for every EVM chain
(`operate/ledger/profiles.py:58` → `DEFAULT_MULTISEND` from `autonomy.chain.constants`;
`operate/operate_types.py:90`). But:

- The wallet layer (`operate/utils/gnosis.py`, used by `operate/wallet/master.py`) has **no MultiSend
  path at all** — `send_safe_txs()` (lines 229–296) and `transfer()` (lines 401–468) hardcode
  `operation=SafeOperation.CALL` and accept a single payload.
- Even in `manage.py`, where the batching builder (`sftxb`) is in hand, every call site does
  `new_tx().add(single_tx).settle()` — approve and the action that consumes the approval are
  separate Safe txs, and the deployment cycle settles one tx per state transition.

Goal: collapse every multi-transaction Safe-signed flow to the minimum number of Safe txs
(ideally one per chain per operation). EOA-signed flows (Master EOA transfers/drains, agent-EOA
drains, Safe deployments, current bridge execution) **cannot** use MultiSend and stay as-is.

## Decisions (confirmed with user)

1. **Failure mode: pre-filter then batch.** Before batching, simulate each sub-tx via `eth_call`
   (`{from: safe, to, data, value}`); drop failing entries from the batch and log what was skipped.
   Closest to today's tolerate-and-continue semantics.
2. **Full scope:** wallet primitive, funding/drain/withdraw loops, the full
   service-lifecycle mega-batch (incl. terminate side), cross-token service-safe drain.
3. **API compatibility: keep response shapes.** Withdrawal/drain responses keep the per-asset list
   structure, repeating the batch tx hash for each asset it covered. No Pearl coordination needed.

---

## Changes

### A. Wallet-layer MultiSend primitive — `operate/utils/gnosis.py`

- `send_safe_multisend_txs(txs: list[dict], safe: str, multisend_address: str, ledger_api, crypto) -> str`
  - Each entry: `{"to", "data": bytes, "value", "operation": MultiSendOperation.CALL}`.
  - Encode via `registry_contracts.multisend.get_tx_data(ledger_api, contract_address, multi_send_txs)`
    (import path: `autonomy.chain.base.registry_contracts` — already imported at gnosis.py:30).
  - Multisend address is an explicit parameter — gnosis.py stays chain-agnostic like its existing
    helpers. Callers resolve it from `CONTRACTS[chain]["multisend"]` in
    `operate/ledger/profiles.py`; autonomy's `ContractConfigs` is NOT imported into the wallet layer.
  - Execute with `operation=SafeOperation.DELEGATE_CALL` via
    `registry_contracts.gnosis_safe.get_raw_safe_transaction_hash()` / `get_raw_safe_transaction()`
    + `TxSettler` — mirror `GnosisSafeTransaction.build()`/`.settle()` (protocol.py:153–235),
    including the gas-pricing/estimation calls. The bytes-normalization helper is deduped
    (user-approved): canonical `normalize_tx_data_to_bytes` lives in gnosis.py; protocol.py's
    former private copy is removed and imported from gnosis.py instead.
  - `SafeOperation` / `MultiSendOperation` enums already exist in gnosis.py:59–71 — reuse.
- `transfer_batch_from_safe(ledger_api, crypto, safe, transfers: list[tuple[to, asset, amount]]) -> str`
  - Compose sub-txs: native → `{"to": to, "value": amount, "data": b""}`; ERC20 → encode
    `transfer(to, amount)` against the token (reuse the encode pattern of
    `transfer_erc20_from_safe`, gnosis.py:470–498).
  - **Pre-filter:** `eth_call` each sub-tx with `from=safe`; drop + log failures
    (`logger.warning` with asset/to/amount/revert reason). If everything is filtered out, return None.
  - If exactly one sub-tx remains after the pre-filter, skip MultiSend and route through the
    existing single-tx path (`transfer` / `transfer_erc20_from_safe`, plain CALL) — no
    DELEGATECALL for one transfer.
- The pre-filter simulation helper is shared: it also serves revert attribution for lifecycle
  batches (section E).

### B. Batch transfer APIs — `operate/wallet/master.py`

- New `MasterWallet.transfer_batch(chain, transfers, rpc=None) -> t.Optional[str]`
  - Safe-only by contract — delegates to `gnosis.transfer_batch_from_safe`. No `from_safe`
    parameter (EOA entries are not batchable, so the option would be a lie). Raises `ValueError`
    if the chain has no Master Safe.
- New `MasterWallet.transfer_batch_from_safe_then_eoa(chain, transfers, rpc=None) -> list[str]`
  - Batch-aware sibling of `transfer_from_safe_then_eoa` (master.py:624–689). For each
    (to, asset, amount): compute the Safe contribution `min(safe_balance, amount)`; send **all**
    Safe contributions in one MultiSend via `transfer_batch`; then settle each remaining shortfall
    with the existing per-asset EOA transfer path (different signer — cannot join the batch).
    For native, deduct the batch tx's gas (`gas_fees_spent_in_tx`, once) before computing the
    EOA shortfall, replacing today's per-tx deduction. Returns all tx hashes (batch hash first).
- `drain()` (master.py:690–729): for `from_safe=True`, collect all non-zero balances
  (existing `get_balance` loop) into one `transfer_batch` call per chain instead of per-asset
  `self.transfer()`. Keep the `from_safe=False` (EOA) path unchanged. Keep the returned
  `moved: dict[asset, amount]` shape.

### C. Funding loop + service-safe drains — `operate/services/funding_manager.py`

- `fund_chain_amounts()` (lines 1273–1296): replace the inner per-(address, asset)
  `wallet.transfer(from_safe=True)` with one flattened
  `wallet.transfer_batch(chain, [(address, asset, amount), ...])` per chain.
  Preserve the existing non-positive-amount skip + log lines.
  `fund_service()` / cooldown logic unchanged (it wraps `fund_chain_amounts`).
- `drain_service_safe()` / `partial_withdraw_service_safe()` (lines 246–364, 415–577):
  master-owned branch currently settles one Safe tx **per token** (each already internally
  batching its approveHash+exec pair via `get_safe_b_erc20_transfer_messages` /
  `get_safe_b_native_transfer_messages`, protocol.py:1607–1788). Change: accumulate messages
  across all tokens + native into one `sftxb.new_tx()` and settle once.
  **Requirement:** each service-safe `execTransaction` hash embeds a specific Safe-B nonce — the
  message builders must accept an explicit nonce and the caller assigns `nonce, nonce+1, ...` in
  batch order. Add `nonce: t.Optional[int] = None` to the two `get_safe_b_*` builders in
  `operate/services/protocol.py` — `None` keeps today's behavior (read the nonce on-chain); the
  drain caller reads the Safe-B nonce once and passes `nonce + i` per message pair.
  Agent-owned branch uses the section-A primitive with the agent crypto + service safe to batch
  its per-token transfers too (`send_safe_multisend_txs` works for any Safe + signer).

### D. Withdrawal endpoint — `operate/cli.py`

- `_wallet_withdraw` (lines 1341–1422): replace the per-asset `transfer_from_safe_then_eoa` loop
  with one `transfer_batch_from_safe_then_eoa(chain, transfers)` call: all Safe legs collapse into
  one MultiSend; only the per-asset **EOA fallback** legs stay sequential (different signer).
- Response: keep the current list-of-hashes shape, repeating the batch hash per asset (Decision 3).
- Preserve the gas-fee deduction for the native amount (currently line ~1387 uses
  `gas_fees_spent_in_tx` per prior tx — now computed once from the batch tx receipt).

### E. Service lifecycle — `operate/services/manage.py`

**Mega-batch happy path.** On-chain, the whole deployment cycle between mint and ERC-8004 setup
is valid as **one** Master Safe MultiSend: sub-calls execute sequentially with
`msg.sender = Master Safe`, so registry state transitions land mid-tx (`registerAgents` sees
ACTIVE_REGISTRATION set two sub-calls earlier, `deploy` sees FINISHED_REGISTRATION, `stake` sees
DEPLOYED + the NFT approval before it). Target tx counts per chain: fresh service **3 txs**
(mint | mega-batch | ERC-8004), update/redeploy **2 txs**. Today: 7–9.

- Composition — fresh service: tx 1 = mint alone (`get_mint_tx_data`); tx 2 =
  `[erc20 approve (bond), activate, erc20 approve (bond), registerAgents, deploy,
  staking NFT approve, additional-token approves..., stake]`; tx 3 = ERC-8004 setup (unchanged).
  Update path: `update` joins the front of tx 2 (existing `service_id` is known — no event needed).
  ETH bonds ride as sub-call `value`, funded from the Master Safe balance (same as today).
- Hard boundaries (why not 1 tx):
  - **Mint stays separate for fresh services:** `CreateService` event yields `service_id`
    (manage.py:960–968), which is static calldata in every later call. Predicting `totalSupply+1`
    races with concurrent mints on the shared registry; failure is benign (whole batch reverts)
    but do not build on a race.
  - **ERC-8004 setup stays separate:** signed by the agent EOA through the *service* Safe
    (manage.py:1234–1238); the Master Safe is not an owner of that Safe — different signer set.
    Also depends on the service Safe address from the deploy event.
- New happy-path branch in `_deploy_service_onchain_from_safe`: taken iff the on-chain state at
  entry is PRE_REGISTRATION (fresh service right after the mint tx lands, or the update path);
  any other state goes to the stepwise resume path. When no staking program is selected
  (`use_staking=False`), the staking sub-txs are simply omitted from the batch. Build the full
  batch with the existing `get_*_data` builders and settle once. Builders reused unchanged:
  `get_erc20_approval_data` (protocol.py:1454), `get_activate_data` (:1476),
  `get_register_instances_data` (:1492), `get_staking_approval_data` (:1816),
  `get_staking_data` (:1839), `get_claiming_data` (:1888).
- **Keep the existing stepwise state machine as the resume/repair path** — services interrupted
  mid-cycle (or left mid-state by older versions) still enter at their actual on-chain state and
  proceed step by step. Within that stepwise path, merge each approve with the action that
  consumes it (activate ~992–1035, register ~1057–1102, stake ~1787–1831 — single
  `new_tx().add(approve).add(action).settle()` each), moving interleaved allowance-verification
  reads/logs to after the settle.
- Pre-flight checks move up front for the mega-batch: total native bond + OLAS bond + staking
  deposit availability, staking slot availability, compatibility checks — all validated before
  encoding the batch.
- Event parsing from the single receipt: `CreateMultisig` (multisig address), staking events —
  extend the existing receipt-parsing helpers to scan one combined receipt; persist `config.json`
  (token already known, multisig, staked state) after settle, not between steps.
- Revert attribution: on batch revert, run the pre-filter simulation (section A helper) sub-call
  by sub-call to identify the failing step and raise the standardized error for it.
- Terminate side: `unstake → terminate → unbond` in one batch when entering with a staked,
  unstakeable service — after `unstake` the service is DEPLOYED mid-tx, so `terminate` is valid
  in the same batch (today: separate settles at ~1380–1395 plus a separate unstake flow).
  Claim → reward-transfer stays two txs: the reward transfer is signed by the agent EOA through
  the *service* Safe (manage.py:2013–2020) — a different signer set — and its inputs
  (reward token address, post-claim balance) are read from the claim receipt's logs (manage.py:1999–2008).
  Claim remains a single Safe tx; this flow is unchanged.

## Out of scope (documented, intentional)

- Bridge execution: `Provider.execute()` signs every bridge tx with the Master EOA key
  (`wallet.crypto`) via a per-tx `TxSettler` loop — there is no Safe `execTransaction` path in
  `operate/bridge/`. Although `bridge_manager._raise_if_invalid` accepts the Master Safe as a
  `from` address, no working execution path sends a bridge tx from the Safe, so there is nothing
  to batch. Bridges originate from the Master EOA (EOA-signed) and stay as-is.
- EOA-signed flows: Master EOA transfers/drains (`master.py:324–486, 525–580`,
  `gnosis.py:500–550, 606–702`), agent-EOA drains (`funding_manager.drain_agents_eoas`, :124–244),
  Safe deployments. No EIP-4337/7702 work.
- Cross-chain batching (impossible; one tx per chain is the floor) — `sync_backup_owner` stays per-chain.
- Cross-signer merging only: a Safe leg and an EOA leg can never share one tx. The Safe legs
  themselves ARE batched across assets via `transfer_batch_from_safe_then_eoa` (sections B/D).
- `create_safe` + add backup owner (EOA-signed deploy + Safe-signed add; also salt/address determinism risk).

## Files to modify (summary)

| File | Change |
|---|---|
| `operate/utils/gnosis.py` | Add `send_safe_multisend_txs`, `transfer_batch_from_safe` (+ pre-filter simulation helper) |
| `operate/wallet/master.py` | Add `transfer_batch`, `transfer_batch_from_safe_then_eoa`; rewire `drain()` Safe path |
| `operate/services/funding_manager.py` | `fund_chain_amounts` batch per chain; drain/partial-withdraw cross-token accumulation |
| `operate/services/manage.py` | Mega-batch happy path + combined-receipt event parsing; stepwise-path approve+action merges; terminate-side batch |
| `operate/services/protocol.py` | Explicit-nonce parameter on `get_safe_b_*_transfer_messages`; `_normalize_tx_data_to_bytes` removed in favor of `gnosis.normalize_tx_data_to_bytes` |
| `operate/cli.py` | `_wallet_withdraw` Safe-leg batching, response shape preserved |
| `CLAUDE.md` | Fix `services/manager.py` → `manage.py` reference; note batching convention |
| `docs/wallet-and-funding.md`, `docs/api.md` | Reflect batched semantics |

No JSON schema / persistence changes; no migration; no new endpoints or request schemas.

## Verification

1. **Unit tests** (run `uv run tox -e unit-tests`):
   - gnosis.py: mock `registry_contracts.multisend.get_tx_data` + `gnosis_safe.get_raw_safe_transaction*`;
     assert DELEGATE_CALL outer operation, sub-tx ordering, bytes normalization, pre-filter drops
     failing sub-txs and logs them, single-entry fallback path.
   - master.py: `transfer_batch` routing; `drain()` composes one batch from multi-asset balances.
   - funding_manager: `fund_chain_amounts` issues exactly one `transfer_batch` per chain with the
     flattened tuples; skip-non-positive behavior preserved.
   - Update existing tests asserting per-asset `wallet.transfer` call counts (funding/drain/withdraw).
   - Failure-semantics test: batch with one reverting sub-tx surfaces the standardized
     insufficient-funds error codes (cf. commits 52a05fb9, 35821636), not a generic revert.
2. **Integration tests** (Tenderly-backed, per CLAUDE.md requirement for changed tx flows;
   `uv run tox -e integration-tests -- <file>::<test> -v` when `.env` RPC creds available):
   batched funding (multi-asset, multi-address), batched withdrawal, batched master drain,
   multi-token service-safe drain (verifies Safe-B nonce sequencing), mega-batch: fresh deploy
   lands in 3 txs with correct `CreateMultisig` parsing from the combined receipt, update/redeploy
   in 2, an interrupted service still resumes via the stepwise path, and the terminate-side
   `unstake → terminate → unbond` batch. Check existing integration coverage first; only add where
   the batched flow isn't already exercised. If creds unavailable, report back per project policy.
3. **Lint/type suite** before any commit:
   `uv run tox -p -e flake8 -e pylint && uv run tox -p -e black-check -e isort-check -e bandit -e safety -e mypy`.
4. **Manual smoke**: start daemon, trigger funding job against a Tenderly fork, confirm one Safe tx
   per chain in logs and that the withdrawal endpoint returns the per-asset list shape.

## Risks / notes

- Layering: the new primitive lives in `operate/utils/gnosis.py` so the wallet layer never imports
  from `operate/services/` (protocol.py's `GnosisSafeTransaction` execution logic is left
  untouched — no refactor to delegate to the new helper; the only protocol.py changes are the
  normalization-helper dedup and the explicit-nonce parameter).
- Pre-filter simulation costs extra RPC calls (one `eth_call` per sub-tx) — acceptable; balance reads
  already happen per asset today.
- Single delivery: Stacked PRs; suggested implementation order within it
  is A → B → C/D → E (each section's tests written alongside), since A is the dependency of
  everything else.
