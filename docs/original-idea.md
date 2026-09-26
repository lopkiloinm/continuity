Better project direction: Continuity
Pitch:
An agent handoff protocol for paid, long-running work: when an AI agent, API, or autonomous service stops, fails, loses access, or needs escalation, Continuity transfers the job—with its scoped budget, evidence, and accountability trail—to a verified successor without the user restarting from zero.

This is not “analytics for x402,” nor “put x402 in front of an existing API.”

It solves a different and underexplored friction:

A user delegates an action to an agent, the agent begins paid work, and then something breaks. Who can safely take over—without giving the successor unlimited wallet access, exposing private context, or forcing the user to reconstruct the task?

That failure mode becomes unavoidable as agents make real payments. Most agent-payment demos show the first payment. Very few design for what happens after delegation fails halfway through.

Why this is a stronger “winner-shaped” idea
Glassbox402’s underlying lesson is not “add analytics.” It is:

Find a behavior already happening.

Identify a hidden operational gap.

Add a small protocol surface that makes the ecosystem more usable.

Make adoption incremental rather than requiring a new marketplace or network.

Continuity applies that logic to delegated agent work, not APIs.

Weak hackathon framing	Continuity framing
“AI agents can pay each other”	“An agent can fail without losing the user’s work or money.”
“Here is a wallet with safety features”	“Here is a reversible, scoped delegation contract that survives handoff.”
“Here is agent identity”	“Identity determines which replacement agent may inherit which capability.”
“Human approval is a login”	“Human approval is required only when control genuinely changes hands.”
“We made a marketplace”	“We fixed an incident-response workflow agents will need in production.”
It is technically substantial but has an elegant demo: an agent crashes, another resumes safely, and no one has to recreate the task.

The core interaction
A user gives a travel/research/procurement agent a bounded job:

“Find and reserve a refundable Tokyo–Lisbon flight under 180,000 JPY. Ask me only if an exception is needed.”

The primary agent receives a handoff capsule:

task specification and constraints;

non-sensitive or encrypted working context;

remaining budget;

allowed merchant/service categories;

payment authorization scope;

deadline;

artifacts already produced;

evidence hashes;

current state-machine position;

explicit successor policy.

It gets partway through the workflow, then fails—for demo purposes, its service key is revoked, its session times out, or its worker deliberately crashes.

Continuity then:

Freezes outstanding authority.

Resolves permitted successor agents via ENSv2.

Runs Intercepta preflight checks on the successor’s payout/payment setup.

Determines whether the handoff is within the user’s preapproved policy.

If it is not, invokes World ID for Agents for a one-time human authorization.

Gives the successor only a capability-scoped, time-limited authority.

Lets it complete the task or safely return the funds/unused authorization.

Creates an auditable cryptographic handoff receipt.

The user does not need to begin again. The successor does not inherit an unbounded wallet. The original agent cannot continue spending once the handoff occurs.

Exactly three tracks
1. ENS — Best Use of ENSv2
Use ENSv2 as an agent delegation graph, rather than a profile page.

Example namespace:

continuity.eth — protocol namespace

travel.alice.continuity.eth — the user’s task agent

recovery.alice.continuity.eth — approved replacement agent

audit.alice.continuity.eth — optional evidence reader

ENS records hold:

agent endpoint;

capability-manifest URI/hash;

approved successor set;

public key for handoff capsule encryption;

receipt-verification key;

service capability tags;

active/revoked status;

delegation-policy hash.

ENSv2’s delegated permissions become meaningful:

The primary agent can update its endpoint or rotate a signing key.

It cannot authorize a new successor.

The user’s policy controller can permit successors.

A recovery agent can read only capsules assigned to it.

A treasury role is separate from execution roles.

A handoff is only allowed if the destination subname is authorized by the policy resolver at the moment it happens. This is a genuinely natural use of hierarchical agent namespaces and role-limited permissions, which the ENS track specifically emphasizes.

2. Intercepta — Safe Agent-to-Agent Payments with x402
Do not make Intercepta a decorative “scan the address” widget.

The actual payment decision should be:

handoff allowed
=
policy permits successor
∧
budget remains
∧
Intercepta risk is acceptable
∧
authority is unexpired
handoff allowed=policy permits successor∧budget remains∧Intercepta risk is acceptable∧authority is unexpired
Before a successor agent receives payment authority or pays an external service:

Call Intercepta against the successor settlement address.

Scan a real payment authorization/message.

Verify the payment token.

Display the decision clearly:

green: auto-handoff;

amber: hold for human authorization;

red: block and retain/revoke the capsule.

The most compelling failure scenario is not a random “bad address.” It is:

The trusted primary research agent fails. Its nominated backup has a newly changed settlement address and a risky authorization pattern. Continuity refuses to transfer the remaining 0.08 USDC authority until the owner reviews and authorizes it.

That turns Intercepta into the safety boundary of a real delegation protocol. Intercepta’s track requires a live pre-payment API call that changes the payment outcome, along with a visible passed and blocked/held scenario.

3. World — Best Use of World ID for Agents
Use World only for change-of-control consent, not log-in.

Human verification is triggered when the handoff crosses a policy boundary:

New successor not in the preapproved set.

Successor requests a higher budget.

Payout address has changed.

Work context includes protected data.

The agent wants to extend an expired authorization.

The task becomes irreversible, such as a booking or an on-chain transfer.

World verification produces a narrowly bound authorization:

json
{
  "handoffId": "handoff_73a9",
  "fromAgent": "travel.alice.continuity.eth",
  "toAgent": "backup.vendor.continuity.eth",
  "maxSpend": "0.08 USDC",
  "allowedAction": "complete_refundable_flight_hold",
  "expiresAt": "2026-09-26T10:05:00Z"
}
A cancelled, denied, or expired proof means:

the successor receives no decrypted capsule;

the x402 payment authorization cannot execute;

remaining authority is frozen or returned;

the interface shows the exact state and resolution path.

That matches World’s intended agent use: a meaningful user decision made at the point where an agent needs authority beyond an established limit—not an identity badge on the landing page.

The differentiator: transferable authority, not transferable chat
The project’s novel object is a Handoff Capsule.

Most agent frameworks save state as messages, JSON, traces, or memory. Those are not safe to hand over because they omit authority boundaries. Your capsule combines:

text
Task state
+ constraints
+ bounded payment authority
+ cryptographic artifacts/evidence
+ recipient-specific encrypted context
+ successor eligibility policy
+ expiry/revocation semantics
= safe resumable delegation
This makes it more than an orchestration demo.

The handoff receipt should show:

Field	Why it matters
Original agent ENS identity	Establishes who held authority first
Successor ENS identity	Establishes who received limited authority
Capsule hash	Proves which task state was transferred
Budget before/after	Shows that handoff did not increase authority silently
Risk verdict	Records why the transfer passed, held, or failed
World approval hash, if needed	Shows narrowly scoped human intervention
Revocation event	Proves the original agent lost authority
Completion/artifact hashes	Lets a user audit what the successor actually delivered
The elegant part is that this same structure can later serve support escalation, agent portability, provider migration, key rotation, scheduled automation, and enterprise audit.

Best demo scenario
Avoid travel booking as the actual transaction unless you have reliable test infrastructure. Use a paid research/data-enrichment job so the work can complete deterministically.

User story
A founder delegates:

“Collect 30 recent open-source GitHub repositories related to on-device multimodal inference. Deduplicate them, extract license and activity metrics, and give me a CSV. Spend up to 0.10 USDC.”

What happens
The primary research agent gets a bounded 0.10 USDC x402 work order.

It purchases/starts a retrieval or enrichment task.

It completes 17 of 30 results.

The service intentionally crashes or loses its key.

Continuity freezes its remaining authority.

The system discovers backup.research.continuity.eth through ENSv2.

It verifies delegated successor rights and resolves the successor’s receipt key and endpoint.

Intercepta preflights the successor payment path.

In the clean path, the backup receives an encrypted capsule and finishes the remaining 13 records.

In the risk path, the backup has an altered payout/unsafe authorization, so the system holds the handoff.

A World verification request asks whether to allow this exact successor to use the remaining 0.04 USDC.

Show cancellation first: nothing proceeds.

Then approve: the backup receives only the remaining budget and completes the task.

The final downloadable CSV includes per-row provenance and the handoff receipt proves no duplicated payment or authority escalation occurred.

The user’s “wow” moment is not a blockchain transaction. It is:

“The work continued after the agent failed, but my money and context did not become uncontrolled.”

Architecture that fits a hackathon
Frontend
A single state-machine timeline:

text
Delegated
→ Primary working
→ Failure detected
→ Authority frozen
→ Successor resolved
→ Risk checked
→ Human approval required / not required
→ Capsule transferred
→ Work resumed
→ Receipt finalized
Add a “chaos switch” that causes one of three failure modes:

Worker crash.

Expired authority.

Unexpected successor payout-address change.

That makes the concept instantly demoable.

Backend
Orchestrator: TypeScript, Hono/Next.js routes, or FastAPI.

Agent runtime: lightweight LangGraph/state machine, but avoid making framework usage your story.

Storage: encrypted object blob for capsule payload; put only hash and metadata on-chain or in verifiable receipts.

Cryptography: encrypt the sensitive capsule to the successor’s published encryption key; sign every state transition.

Payments: x402 transaction/authorization only for the bounded work portion.

Policy evaluator: deterministic JSON policy rather than LLM judgment.

Smart-contract scope
Keep contracts minimal:

HandoffRegistry: records capsule hash, state, successor, expiry, and revocation.

Optional ScopedEscrow: locks only the remaining work budget and releases only after completion criteria.

You can avoid a complex escrow contract entirely if that endangers the demo. A verifiable, server-enforced authority token plus x402 preflight still tells the intended story. But a tiny registry contract strengthens auditability.

Why this does not become sponsor bingo
Each sponsor integration is necessary at a different stage:

Step	Primitive	What it prevents
Find eligible successor	ENSv2	Unverifiable identity and uncontrolled authority delegation
Evaluate handoff/payment route	Intercepta	Moving remaining budget to a risky or malicious successor
Cross a human-defined boundary	World	Silent expansion of the agent’s authority
Resume task	x402 + capsule	Restarting work, duplicate payment, or unconstrained wallet access
Remove any one component and the product loses a meaningful property. That is exactly what judges mean by a natural integration.

What not to build
Do not spend time on:

A full universal agent-memory format.

An agent social network or marketplace.

Generic “reputation scores.”

A token, governance system, or points program.

Multi-chain routing.

An autonomous agent that performs an impressive but unreliable open-ended workflow.

A generic dashboard with no forced decision.

Your showcase should be the handoff moment, not the chat interface.

Submission framing
Title options
Continuity — safe handoffs for paid AI agents

Relay — bounded authority when agents fail

Second Shift — resumable delegated work for agents

Failover — x402 work that survives agent failure

I would choose Continuity. It is product-like, immediately understandable, and avoids crypto jargon.

Submission blurb
Continuity lets paid AI-agent work survive failure without transferring uncontrolled wallet access. A failed agent packages its verified progress and remaining, scoped authority into an encrypted handoff capsule; an ENSv2-authorized successor can resume only after Intercepta preflights the payment path, while World ID provides human consent for high-risk changes of control.

The memorable final line
Delegation should survive failure. Authority should not.
