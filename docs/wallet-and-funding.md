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
