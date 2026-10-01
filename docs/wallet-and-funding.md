# Wallet and Funding Model

## Purpose

This document explains the durable wallet hierarchy, custody model, funding flows, and recovery concepts used by Olas Operate Middleware.

## Core idea

The middleware separates custody across multiple layers so that service operation, funding, recovery, and on-chain ownership can be coordinated without collapsing everything into a single key or balance pool.

The stable mental model is:

`User-controlled root wallet → managed operational safes → agent EOA → service safe → service operations`

## Wallet hierarchy

### User-controlled root wallet (Master EOA)
The root wallet is the user-controlled source of ownership and authority.

Its stable role is to:
- anchor wallet ownership,
- provide the trust root for controlled assets,
- bootstrap and restore the rest of the custody model,
- serve as the origin of user-authorized operational funding.

### Managed operational safes (Master safes)
The next layer provides managed operational custody.

In the current implementation, the master safe is configured with threshold `1`, so the durable model here is a 1-of-2 safe with a backup-owner-aware ownership arrangement multisig.

Its stable role is to:
- hold funds intended for service operation,
- create separation between user-rooted ownership and day-to-day service funding,
- provide a safer coordination point for moving assets toward service-level custody,
- support backup/recovery-aware ownership arrangements.

### Service-level custody
Each service operates with its own custody boundary.

At a durable level, this service-side custody includes:
- a **service safe** as the service-level custody boundary,
- an **agent EOA** as the service-side operating identity.

Their stable roles are:
- isolate service funds from the global custody layer,
- hold assets required for service runtime and on-chain actions,
- separate per-service operational risk from root-level ownership,
- allow service operation to proceed without collapsing all control back into the root wallet.

## Service-safe ownership transitions

The service safe is not a permanently fixed owner-controlled object.
Its control relationship changes with the service’s on-chain lifecycle.

The durable pattern is:
- the **agent EOA** acts as the service-side operating identity during the phases where the service is actively operating as an OLAS service,
- the **master safe** acts as the root-side recovery and control anchor,
- ownership/control of the **service safe** can be swapped between the agent EOA and the master safe depending on the service’s on-chain state.

This matters architecturally because the wallet model is designed to balance two needs that would otherwise conflict:
- giving the service enough direct control to operate,
- preserving higher-level control and recoverability when the protocol lifecycle requires it.

## Why the hierarchy exists

The hierarchy separates four concerns that should not be conflated:
- ownership,
- operational funding,
- service execution,
- recovery.

That separation allows services to be funded, operated, and recovered without giving every service direct control over the root custody layer, while still allowing service-safe control to shift between service-side and root-side custody as the on-chain lifecycle changes.

## Chain-aware custody

The custody model is chain-aware rather than single-chain.

This means:
- service and operational custody can exist on multiple chains,
- chain-specific safe addresses and balances matter,
- funding and recovery logic must account for the chain on which a service is operating.

## Funding model

### Funding direction
The durable funding direction is:

1. the user-controlled root wallet is funded,
2. managed operational custody holds service-operational funds,
3. service-level custody receives the funds it needs,
4. running services use those funds for ongoing service and on-chain obligations.

### Why funding is coordinated centrally
Funding is not left entirely to each service because the middleware needs one coordinating layer for:
- determining what each service requires,
- moving funds safely across custody boundaries,
- avoiding duplicate or conflicting funding actions,
- handling periodic refill and claim behavior over time.

### Batched execution
When a single operation moves several assets or funds several addresses
from Safe custody (the periodic funding pass, a drain, a withdrawal),
those transfers execute together as one batched on-chain transaction per
chain (a Gnosis Safe MultiSend) rather than as a sequence of individual
transactions. This keeps gas overhead and settlement latency down and
narrows the window in which an operation can be left half-done.

Two durable properties follow from this model:

- Entries that cannot succeed (insufficient balance for the requested
  amount, a transfer that would revert) are filtered out and logged
  before the batch is sent, so one infeasible asset does not block the
  rest of the operation. Flows that promise exact amounts (such as
  partial withdrawals) instead fail loudly when any requested transfer
  cannot be included.
- Only Safe-signed transfers can join a batch. Transfers signed by an
  EOA (the root wallet, or an agent key acting alone) always settle as
  individual transactions, so mixed operations consist of one batched
  Safe transaction plus individual EOA transactions for any remainder.

## Funding run

A funding run lets the user fund Pearl with **one** transfer of a token they
already hold, on a chain they choose, instead of sending the exact token to
the exact address on the exact chain twice (Master EOA and Master Safe).
It lives in `operate/funding_run/` and is exposed under `/api/funding_run`
(see [api.md](api.md#funding-run)).

### Modes
The three modes differ only in how the target is produced and where funds
end up; quoting, monitoring and execution are shared:

- `onboard`: the service's net shortfall on its home chain, from
  `FundingManager.destination_targets`. That shortfall already includes the
  Master EOA reserve (and, before the Safe exists, the larger
  `DEFAULT_EOA_TOPUPS_WITHOUT_SAFE` that pays for creating it), so the quote
  adds only transfer gas. Ends in the Master Safe.
- `deposit`: user-entered **amounts to add** to the Pearl Wallet. Funds it
  already holds are never netted or counted as received. Ends in the Master
  Safe.
- `signer_gas`: the Master EOA native reserve (`DEFAULT_EOA_TOPUPS`). Ends in
  the Master EOA; there is no Safe step.

### Flow
1. **Quote**, walking backwards from the net targets: destination swaps from
   a carrier token (USDC when the source is USDC, otherwise native), then a
   source leg that delivers the carrier plus destination native for every
   later step, so only the source leg ever needs gas abstraction.
2. **Receive**: the user sends the quoted amount to the Master EOA on the
   source chain, in one transfer or several. "Received" is derived from the
   current Master EOA balance, so partial deposits and restarts need no
   bookkeeping. When the source chain is the destination chain, the targets
   were already netted against that same balance, so only its growth above
   the balance at run creation counts. On full receipt the run re-quotes once
   more and freezes.
3. **Source leg**, **swaps** and **Safe create + transfer** (everything above
   the Master EOA reserve moves to the Master Safe), then, for USDC sources,
   **delegation clearing**.

Routing reuses the bridge providers through `BridgeManager.quote_requests`,
which never touches the Transak/bridge flow's cached bundle. One run exists at
a time. The run is persisted in `funding_runs/<id>.json` (with
`funding_runs/active.json` pointing at the live one), and every transition is
stored before its side effect: after a restart a step with a recorded UserOp
hash, tx hash or Relay `requestId` is reconciled, never blindly resent, and a
retry re-quotes only failed requests. A `FAILED` run with nothing in flight
can be cancelled instead, leaving its funds in the Master EOA. While a run moves Master EOA funds it
holds `FundingManager.master_eoa_lock`, so the periodic funding job cannot
spend them mid-run.

### Gas abstraction and custody
A USDC source on a chain with a Circle Paymaster (`CIRCLE_PAYMASTER`:
Ethereum, Base, Optimism, Polygon, Arbitrum) works from a zero native balance.
The source leg is one ERC-4337 UserOperation (`GasAbstractedSender`):

- the Master EOA signs an **EIP-7702 authorization** delegating its own
  address to `Simple7702Account`, bound to the source chain id (never 0,
  which would be valid on every chain);
- an **EIP-2612 permit** lets the Circle Paymaster take at most
  `GAS_ABSTRACTION_USDC_CAP[chain]` of USDC for gas ($10 on Ethereum, $1.00
  elsewhere); unused allowance is not spent;
- the UserOperation is signed over the EntryPoint's hash and submitted to
  Candide's public bundler.

All three signatures come from the Master EOA key inside the wallet class,
with no user prompt. Custody properties:

- Master Safe ownership and backup-wallet recovery are unaffected: Safe
  checks owner signatures with `ecrecover`, independent of code at the owner
  address.
- The recovery phrase path is unaffected: the key is unchanged and can always
  re-delegate or clear the delegation.
- The delegation lasts only for the run. It would persist on-chain until
  replaced, so the run ends with a self-sponsored type-4 transaction
  delegating to `address(0)`, paid with source-chain native the source leg
  reserves for it (`CLEAR_DELEGATION_GAS_RESERVE`). Clearing never fails the
  run; it is retried in the background and at start-up until the Master EOA
  has no code. While live, `Simple7702Account` accepts calls only from itself
  or the EntryPoint, and only with the Master EOA's own signature.

Chains without a Circle Paymaster (Gnosis, Robinhood) accept native sources
only, which pay their own gas.

## Health and funding relationship

Funding is related to service health, but it is not identical to it.

The durable relationship is:
- service runtime produces signals about readiness and need,
- those signals are persisted in local state,
- funding logic uses that information to maintain operability,
- health observation and funding maintenance remain separate but coordinated concerns.

## Recovery model

Recovery is part of the intended wallet architecture, not an afterthought.

The stable recovery concept is:
- custody is designed with restoration in mind,
- backup ownership and wallet restoration protect long-term operability,
- recovery acts on top of the wallet hierarchy rather than bypassing it,
- service operability depends on the recovery path remaining viable.

## Stable invariants

The following are intended architectural invariants:

- The root wallet is the ownership anchor, not the everyday service runtime wallet.
- Service-level custody is isolated from root-level custody.
- Funding decisions are coordinated centrally rather than ad hoc inside each service.
- Recovery is a designed part of the custody model.
- The wallet model is chain-aware and must be understood together with service and on-chain context.

## What is intentionally not in scope here

This document does not try to describe:
- exact transfer helper behavior,
- per-chain operational edge cases,
- RPC and gas-management details,
- API payloads for wallet actions.

Those are more volatile than the wallet and funding model itself.
