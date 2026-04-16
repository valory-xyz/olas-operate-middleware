# Services and Deployment Model

## Purpose

This document explains the OLAS-specific meaning of a service and how Olas Operate Middleware turns that protocol object into a locally running agent system.

## What an OLAS service is

Detailed answer: https://stack.olas.network/open-autonomy/get_started/what_is_an_agent_service/

In OLAS, a service is the protocol-level representation of an autonomous multi-agent system.

A service is more than a code package and more than a running process.
It combines:
- a service definition that describes the agent system,
- one or more agent identities that are allowed to operate it,
- an on-chain service identity,
- registration and bond rules,
- a deployed runtime that can execute the agent system.

The important distinction is:
- an **agent** is an autonomous software worker with a defined behavior,
- a **service** is the coordinated system that groups the agent logic, the allowed operator identities, and the protocol lifecycle needed to run that system in the OLAS stack.

## How agents relate to a service

A service is built around agent types and agent instances.

At the durable OLAS level:
- the service definition specifies which agent composition is expected,
- the service lifecycle allows compatible agent instances to be registered to that service,
- the registered agent instances become the operator set for the deployed service,
- the deployed service then runs the agent system with those participants reflected in its runtime configuration.

So the protocol does not treat a service as a single isolated bot.
It treats a service as an orchestrated agent system whose participants must be explicitly registered before deployment.

## What the middleware persists for each service

The middleware keeps a long-lived local record for each service so that it can reconcile protocol state with local runtime state.

That persisted service state includes, at a durable level:
- the selected OLAS service package reference,
- chain-specific RPC and operational configuration,
- per-chain on-chain identity such as the service NFT/service id and service-linked multisig context,
- user-selected service economics such as staking preference, bond cost, and funding requirements,
- local deployment status,
- runtime health and operability signals.

This local record is the middleware’s persistent view of the service. It is not a replacement for the protocol state, but it must stay aligned with it.

## Service coordination

Above each individual service, the middleware maintains a coordination layer for the set of locally known services.

Its stable role is to:
- create and load services from packaged OLAS service definitions,
- keep service-local state in sync with chain-specific reality,
- coordinate registration, deployment, termination, staking, and claim flows,
- expose service-level information needed by health, funding, and recovery logic.

Conceptually, each service owns its own persisted state, while the coordination layer decides how lifecycle actions are applied across services.

## Packaged service definition

An OLAS service definition exists before local deployment.

The middleware treats that definition as a packaged artifact that must be retrieved and prepared before the service can run locally.

The durable pattern is:
- the service package is fetched from content-addressed storage,
- the service definition is read from that package,
- chain-specific values and runtime parameters are injected,
- the result is turned into locally executable deployment state.

This matters because the running service is derived from the published OLAS service package, not invented ad hoc by the middleware.

## On-chain service lifecycle

Details: https://stack.olas.network/protocol/life_cycle_of_a_service/#terminated-bonded

The middleware models the OLAS protocol lifecycle of a service separately from local runtime state.

The durable on-chain states are:
- **NON_EXISTENT** — the service does not yet exist on-chain.
- **PRE_REGISTRATION** — the service has been created on-chain and has a service identity, but agent instances are not yet actively being registered.
- **ACTIVE_REGISTRATION** — agent instances can be registered to the service.
- **FINISHED_REGISTRATION** — the registration window has ended and the operator set is fixed for this deployment cycle.
- **DEPLOYED** — the service is deployed on-chain and is considered active in the protocol.
- **TERMINATED_BONDED** — the service has been terminated, but bonded assets are still locked.

Once all agent instances are unbonded, the service returns to a pre-registration-style state for a future lifecycle round.

## Local deployment lifecycle

The middleware also tracks a separate local deployment lifecycle for the service runtime.

The concrete local deployment states exposed by `DeploymentStatus` are:
- built,
- deploying,
- deployed,
- stopping,
- stopped.

Conceptually, a service may also be absent before a build exists or removed after local cleanup, but those are not named `DeploymentStatus` enum values.

These states answer a different question from the on-chain lifecycle.
They describe whether the middleware has already prepared and launched the runtime environment for the service on the local machine.

So two truths can exist at once:
- the protocol may consider the service deployed or terminated on-chain,
- the local runtime may still be building, stopped, or deleted.

## Deployment path

Deployment is the bridge between the OLAS service definition, the OLAS protocol lifecycle, and the local runtime.

The stable path is:

`packaged OLAS service definition → local service record → on-chain registration/deployment progress → service staking → local runtime preparation → running agent system`

In practical terms this means:
- the middleware first knows which OLAS service package it is dealing with,
- then it reconciles the service’s per-chain protocol state and stakes its NFT in a staking program if required by the service definition,
- then it prepares the local execution environment using the service definition,
- then it runs the service locally with chain-aware runtime parameters derived from the service’s registered participants and on-chain context.

## Staking and bonding relationship

In this middleware, staking is one part of a service’s on-chain operating context.

At the service-model level, that means:
- a service may operate with or without a staking program,
- the staking choice changes what bond, deposit, and funding obligations the service has,
- staking remains connected to service funding and lifecycle actions.

The deeper staking model and its economic consequences are described in `docs/staking-and-onchain-model.md`.

## Runtime maintenance after deployment

For the middleware, deployment is not the end of service management.

Once a service is running, the middleware continues to maintain it through recurring background work.

Two durable maintenance loops matter most:
- health observation,
- funding and reward-maintenance flows.

That ongoing maintenance includes:
- persisting runtime health signals produced by the running service,
- using those signals to judge whether the service is still operable,
- periodically performing service-aware funding and reward-claim work.

So the middleware treats a service as a long-lived operated system, not as a one-time launch.

## Long-lived OLAS service invariants

The following are intended to remain true even if implementation details change:

- An OLAS service is the protocol-level representation of an autonomous agent system.
- A service is distinct from an individual agent; it organizes agent participation and lifecycle at the system level.
- On-chain service state and local deployment state are different concepts and must be tracked separately.
- Service packages are retrieved from published artifacts and turned into local runtime state.
- Registered agent instances and service-linked multisig context matter to how a deployed service runs.
- Staking, bonding, funding, and reward flows are service-level operational concerns.
- Health and operability maintenance continue after the initial deployment succeeds.

## What is intentionally not in scope here

This document does not describe:
- endpoint-by-endpoint service APIs,
- command-by-command deployment procedures,
- every smart-contract call involved in service lifecycle actions,
- temporary operational workarounds.
