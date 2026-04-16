# Architecture Overview

## Purpose

This document explains how Olas Operate Middleware fits together at a system level. It captures the stable system model: what the middleware is responsible for, which long-lived domains it coordinates, and how local control-plane state relates to on-chain OLAS service behavior.

## What the middleware is

Olas Operate Middleware is the local control plane for operating OLAS services.

Its durable role is not limited to launching software.
It sits between:
- the user’s local control surfaces,
- the wallet and custody structure used to hold and move funds,
- the local runtime environment where services actually run,
- the chain-aware and protocol-aware actions required to register, deploy, fund, stake, bridge, recover, claim, terminate, and maintain those services over time.

A good mental model is:

`local operator intent → middleware control plane → wallet/service state → protocol and runtime actions`

## User-facing surfaces

There are two durable ways users interact with the system:

- a local command-line interface for direct operation, setup, and recovery tasks,
- a daemon-backed HTTP interface for account, service, wallet, recovery, and bridge actions.

These are two access surfaces over the same underlying control-plane model.
The important point is that both surfaces act on the same persisted local state and the same service/wallet/protocol relationships.

## What the middleware coordinates

At a durable level, the middleware coordinates four kinds of things at once:

- **service state** — what services exist locally, what package and chain context they carry, and where they are in local deployment and on-chain lifecycle terms,
- **custody state** — what wallets and safes exist, who controls them, and how assets move through the custody hierarchy,
- **protocol state** — what each service means on-chain, including registration, deployment, staking, claim, termination, and bridge-related actions,
- **maintenance state** — whether a running service is healthy, funded, and still operable over time.

This is why the middleware is best understood as a coordinator rather than as a single-purpose deployment tool.

## Core system domains

### Service domain
The service domain represents OLAS services as durable local control-plane objects.

Its stable responsibilities are:
- storing per-service configuration and lifecycle state,
- linking each service to chain-specific and on-chain information,
- turning published service definitions into locally executable runtime state,
- exposing the service information needed by health, funding, staking, and protocol actions.

### Wallet and custody domain
The wallet domain defines the long-lived custody structure that makes service operation possible.

Its stable responsibilities are:
- anchoring ownership in a user-controlled root wallet,
- separating operational custody from root ownership through managed safes,
- isolating per-service operational custody,
- preserving recovery paths so services remain controllable even when ownership arrangements change.

### Runtime orchestration domain
The runtime orchestration domain treats service operation as an ongoing responsibility rather than a one-time deployment event.

Its stable responsibilities are:
- observing service health,
- persisting health and operability signals,
- maintaining funding readiness,
- performing recurring background work such as refill and claim-oriented maintenance.

### Chain, staking, and bridge domain
The chain domain gives the middleware its chain-aware and protocol-aware model.

Its stable responsibilities are:
- carrying per-chain service context rather than one global chain state,
- mapping local service intent into on-chain lifecycle actions,
- handling staking-program selection and its economic consequences,
- handling bridge-aware movement of assets when services need funds or assets on different chains.

### Account and access domain
The account domain protects entry to the local control plane.

Its stable responsibility is to ensure that local service, wallet, recovery, and bridge actions occur inside an authenticated, password-protected model.

## Persistent local state

The middleware persists long-lived local state under its operate home directory.

That durable local state includes:
- service records and local deployment state,
- encrypted key material,
- wallet and safe metadata,
- application settings,
- persisted health and operability signals.

This local state is the middleware’s off-chain source of truth.
It does not replace on-chain protocol state, but it is the authoritative record for how the middleware understands and operates the system locally.

## Stable system relationships

A useful black-box view of the system is:

- users act through CLI or daemon-backed interfaces,
- those actions are routed into the middleware’s control-plane domains,
- the middleware reads or updates persistent local state,
- wallet and custody logic determine who can fund or authorize service actions,
- service logic reconciles local service records with chain-aware protocol reality,
- runtime orchestration keeps deployed services healthy and funded after deployment,
- protocol logic turns local intent into chain actions such as register, deploy, stake, claim, terminate, unstake, recover, or bridge.

The key relationship is that no one domain is sufficient on its own.
A service action usually crosses service state, custody state, and protocol state, then continues into maintenance.

## Conceptual system flow

At a high level, most durable flows follow this pattern:

1. a user initiates an action through a local interface,
2. the middleware resolves which service, wallet, and chain context the action belongs to,
3. local control-plane state is read or updated,
4. if required, custody and protocol logic perform chain-aware actions,
5. if the action changes service operation, local runtime state is prepared or updated,
6. background maintenance continues to keep the service healthy, funded, and operable afterward.

This is true not just for initial deployment, but also for staking changes, reward claims, bridge operations, recovery tasks, and shutdown or termination flows.

## How the deeper reference docs fit in

This overview is the top-level system map.
The deeper durable docs explain specific parts of that model in more detail:

- `docs/wallet-and-funding.md` explains the custody hierarchy, funding direction, and recovery model.
- `docs/services-and-deployment.md` explains what an OLAS service is, how services relate to agents, and how protocol lifecycle and local runtime lifecycle fit together.
- `docs/staking-and-onchain-model.md` explains the staking-specific on-chain model, including per-chain staking context and how staking changes funding and lifecycle constraints.

## What stays stable

The following are intended to remain true over time:

- the middleware is a local control plane over service, custody, runtime, and on-chain concerns,
- services are durable local objects connected to chain-specific and protocol-specific state,
- wallet custody, service management, and protocol execution are separate concerns that must be coordinated,
- persistent local state is the source of truth for off-chain middleware behavior,
- deployment is only one phase of the system; health, funding, rewards, and recovery remain ongoing responsibilities afterward.
