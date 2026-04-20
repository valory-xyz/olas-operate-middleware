# Staking and On-Chain Model

## Purpose

This document explains the durable OLAS staking concepts that matter to Olas Operate Middleware: how staking changes the operating model of a service, how that choice is carried per chain, and how staking affects funding, rewards, and lifecycle actions.

## Core idea

In OLAS, staking is not just a yield toggle.
It is a service-level operating mode that attaches protocol and economic consequences to a service.

The stable pattern is:
- a service can technically operate with or without a staking program, although most services are staked in practice,
- the chosen staking program is attached to that service on a chain,
- the staking context changes what the service must lock, hold, or fund,
- the staking context also changes what the service can earn, claim, reset, or unstake.

This is why the middleware treats staking as part of service operability, not as cosmetic metadata.

## Staking belongs to the service

In this middleware, staking is modeled as a property of a service rather than as a global application setting.

That means:
- one service may be unstaked while another participates in a staking program,
- the staking choice travels with the service’s chain-specific on-chain context,
- staking decisions must be interpreted together with that service’s current protocol state.

This matches the OLAS model more closely than a wallet-level or application-level staking switch would.

## Local state versus on-chain staking state

A durable distinction must be preserved:
- local state records what staking program the middleware believes the service should use and what operating requirements follow from that,
- on-chain state determines what the service is actually doing in the protocol right now.

These two views are related but not interchangeable.
A local staking preference may exist even when protocol constraints mean the service cannot yet switch, unstake, or re-enter another staking program.

## Per-chain staking context

Staking context is attached per chain, not as one global service flag.

For each relevant chain, a service can carry:
- its on-chain service identity,
- the service-linked multisig or custody context used for protocol actions,
- the selected staking program or the explicit choice not to stake,
- the bond and funding requirements implied by that choice,
- the chain-specific configuration needed to execute those actions.

This per-chain model is one of the most durable features of the middleware’s on-chain design.

## What a staking program means in OLAS terms

A staking program is the protocol context that determines how a service participates in staking and what that participation implies.

At a durable level, the chosen program can change:
- the minimum bond or deposit a service must lock,
- whether additional staking-token approvals or balances are required,
- whether the service can earn staking rewards,
- whether rewards are currently claimable,
- when the service can be unstaked or reset,
- whether the service remains eligible to continue operating under that program.

So a staking program is not merely a label.
It materially changes the service’s economics and lifecycle constraints.

## Bonding, deposits, and service operability

In OLAS staking flows, service operation is tied to assets that may need to be bonded or otherwise locked for protocol participation.

The durable architectural point is:
- a staked service may need native-asset funding for protocol transactions,
- it may also need service bond or security-deposit funding,
- and it may additionally need staking-token balances or approvals depending on the program.

Because of this, the middleware cannot judge operability by runtime health alone.
A service may be healthy as software but still not be fully operable in protocol terms if its staking-related obligations are not satisfied.

## Funding and staking relationship

Staking directly changes what the middleware considers necessary for a service to remain operable.

The durable relationship is:
- staking selection changes the service’s required funding envelope,
- those requirements can include bond, security deposit, token approvals, and chain-specific balances,
- funding logic must therefore remain aware of the service’s staking context.

This is why staking is simultaneously:
- a protocol concern,
- an economic concern,
- and a funding-maintenance concern.

## Reward and claim model

A staked service can become eligible for staking rewards under its active staking context.

At a durable level:
- rewards are associated with the service’s participation in a staking program,
- reward eligibility is not identical to immediate claimability,
- claim flows are service-aware and custody-aware,
- claimed value is folded back into the wider wallet and funding model.

So reward handling is part of service maintenance, not an unrelated wallet action.

## Staking lifecycle constraints

Staking has lifecycle consequences that outlive the initial opt-in decision.

The durable architectural point is:
- a service cannot always move freely between staking programs,
- protocol state may prevent immediate unstaking,
- claim, terminate, unbond, and unstake flows may need to happen in a constrained order,
- reset behavior must reconcile the desired local staking preference with the service’s actual on-chain position.

This is why the middleware includes dedicated claim, terminate, unstake, and reset behaviors instead of treating staking as a simple preference flip.

## Relationship to service lifecycle

Staking should be understood together with the OLAS service lifecycle.

A durable mental model is:
- service lifecycle state says where the service stands in the protocol,
- staking context says what economic and reward rules apply while it is there,
- local deployment state says whether the runtime is actually running on this machine.

All three layers matter.
A service can be locally deployed yet misaligned with its staking obligations, or it can be correctly positioned in the staking lifecycle while not currently running locally.

## Chain and bridge relationship

Bridging is adjacent to the staking model because services may need assets on different chains while still being operated as one coherent local control-plane object.

The durable bridge concept is:
- cross-chain movement is chain-aware,
- bridge behavior must stay consistent with wallet ownership and service context,
- bridge actions may be necessary to satisfy service funding needs that are themselves influenced by staking.

Bridge behavior is therefore not the same as staking, but both belong to the same chain-aware service operation model.

## Stable OLAS staking invariants

The following are expected to remain true even if specific staking programs evolve:

- Staking is a service-level operating mode, not a global middleware switch.
- Staking context is carried per chain together with the service’s on-chain identity and custody context.
- Local staking preference and actual protocol state are different concepts and must be reconciled carefully.
- Staking changes service economics through bond, deposit, token, and reward consequences.
- Reward claimability is service-aware and tied to the current staking context.
- Unstake, terminate, reset, and related actions are constrained by protocol state rather than purely by local user intent.
- Funding requirements depend on staking and must be maintained as part of ongoing service operability.
- Cross-chain asset movement remains service-aware, wallet-aware, and chain-aware.

## What is intentionally not in scope here

This document does not attempt to enumerate:
- every staking campaign or program variant,
- blog-post feature announcements or rollout timelines,
- every contract ABI or method,
- exact transaction sequences for every protocol action,
- endpoint-level bridge or staking APIs.
