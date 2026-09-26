# Continuity — bounded handoffs for interrupted agent work

## Product hypothesis

A user delegates a paid, multi-step job. The worker fails after producing useful results. Continuity checkpoints that progress and lets an eligible successor finish within the original constraints and remaining budget.

The hypothesis to test: users and agent developers need recovery that preserves both work and spending boundaries. Demand, novelty, adoption, and competitive advantage have not been established. This is an application prototype, not yet an interoperable protocol.

**First user:** a developer operating a paid research worker and a separately configured backup worker.

**First task:** produce a 30-row research CSV in two batches. The local implementation uses explicitly synthetic records. It does not claim to discover real GitHub repositories, inspect licenses, or measure current activity.

**Success criterion:** after a deliberate failure at row 17, the backup completes rows 18–30 without charging twice for a batch or increasing the job budget. The old worker cannot commit through the local orchestrator after its authority epoch changes.

## What exists now

Install `requirements.txt` in `.venv`, configure the registered World sandbox client in `.env`, and run `.venv/bin/python -m continuity.server`. Open http://127.0.0.1:8000. See [World setup](docs/world-id.md).

- A deterministic Python state machine and browser interface, with PyJWT/cryptography for World token validation.
- A 100,000-unit simulated budget, displayed as 0.10 USDC. The primary batch consumes 60,000 units; the successor batch consumes 40,000. These are chosen demo prices, not market prices or actual USDC transfers.
- A checkpoint containing 17 completed fixture records, job identity, next record, remaining budget, action scope, expiry, and authority epoch.
- Four explicit screening fixtures: pass, changed payee with passing screening, deny, and unavailable.
- A real World sandbox OIDC device-grant integration with backend validation, original-owner matching, fresh verification, and separate action-bound consent. Registration and live device initiation are complete; first completed user verification remains pending.
- CSV export and a JSON receipt containing a SHA-256 event hash chain.
- Tests for the local authority, budget, duplicate-work, approval, and expiry boundaries.

Local state is in memory; the Vercel deployment stores encrypted sessions in Redis with one-hour idle expiry. Each browser session controls its own job. World device-grant and token validation code is implemented; no successful end-user live verification is claimed yet. There are no independently authenticated workers, real payments, deployed contracts, ENS/Intercepta/x402 integrations, encrypted capsules, or signed receipts. The hash chain is unsigned and can be recomputed by the server; it is not independently verifiable accountability.

## Demo script and acceptance criteria

1. Connect the job owner through World sandbox, then start the primary worker. Observe 17/30 rows, 0.06 simulated USDC spent, 0.04 remaining.
2. Inject a worker crash. The server clears the active worker and increments the authority epoch. The existing checkpoint remains available to the local operator.
3. Select an approved successor. Passing fixture checks grant only the remaining batch. Resume and download the 30-row CSV.
4. Reset and repeat with a changed payout. This fixture passes risk screening but requires fresh World verification of the same job owner followed by explicit consent. Cancel: no backup starts, no further spend occurs. Reset to demonstrate approval separately; cancellation cannot be replayed into approval.
5. Reset and repeat with risk denied or screening unavailable. Both block. Human consent cannot override these outcomes.
6. The job expires ten minutes after the primary worker starts; consent expires after at most two minutes. Neither approval nor retry extends the job deadline.

The tests must also reject stale worker epochs, repeated batch commits, mismatched approval hashes, repeated approvals, and spending above the cap. These are local model guarantees, not claims about distributed execution or external settlement.

## State and data model

`ready → primary_working → frozen → successor_working → completed`

From `frozen`, a decision can instead enter `awaiting_approval`, `blocked`, or `expired`. Pending consent can grant successor authority, cancel, or expire. Cancelled and blocked jobs are terminal in this prototype; New job starts a separate job, retaining the current session’s verified owner while clearing handoff verification evidence.

| Object | Required fields / responsibility |
| --- | --- |
| Job | ID, deadline, budget, spent amount, active worker, authority epoch, state |
| Checkpoint capsule | Version, job ID, completed records, next record, remaining budget, allowed action, expiry, epoch |
| Approval intent | Job ID, successor, payee, capsule hash, epoch, maximum amount, action, expiry |
| Event | Sequence, timestamp, transition reason, state, epoch, spent amount, previous hash, hash |
| Output row | Stable fixture ID, synthetic provenance URI, description, producing worker |

Amounts use integers. The local hash convention is SHA-256 over Python's sorted compact JSON encoding. A cross-language protocol will need a specified canonical encoding, signature format, domain separation, and test vectors before other implementations can rely on it.

The fixture successor is `backup.local`, a local identifier. No ownership or resolution of `continuity.eth` or any subname is claimed.

## Decision policy

For the first live version, all mandatory checks must pass: active job, unexpired authority, positive remaining budget, allowed capability, authenticated eligible successor, and fresh acceptable screening of the exact payment route. Unknown, timed-out, malformed, or denied screening fails closed.

A changed payee that otherwise passes screening may require owner consent. A denied risk verdict must not become acceptable merely because someone verifies their identity. An increased budget, expired job, unknown successor, or broader capability should require a separately authorized policy change, not a generic “approve anyway” button. These policy-change flows are outside the starter.

Before granting authority, re-read the approved policy and bind the successor identity, payee, token, network, amount, capsule hash, nonce, and deadline to the decision. Before signing a payment, check the same values again. The live design must specify how stale screening and changed resolver data invalidate consent.

## Planned integrations and evidence needed

### ENSv2: successor discovery and public configuration

The official [Permissioned Resolver documentation](https://docs.ens.domains/ensv2/permissioned-resolver/) describes address, text, and data records and role-controlled writes. Application-specific record keys for endpoints, keys, and successor policy would be **our proposed schema**, not a pre-existing Continuity or ENS standard.

A material constraint: resolver write permissions are scoped to record arguments such as a text key and apply across names served by that resolver; they are not per-name permissions. Assess separate resolver instances where isolation is required. Do not assume a parent/subname arrangement alone enforces the desired boundary. The documented interfaces are subject to change.

Next experiment: obtain a controlled test namespace and confirm the current event deployment, resolve a backup endpoint and policy hash on Sepolia, demonstrate that the worker cannot alter successor-policy records, then revoke the successor and show the handoff failing. Capture network, deployment addresses, resolver reads, transaction hashes, and permission tests.

ENS public records do not make task data private. The application must separately authenticate the capsule recipient and authorize access. Never store private task context in public records.

### Intercepta: screening that gates a payment

The supplied event brief requires a live API call before signing or accepting payment; fixtures do not qualify. It also specifies screening real mainnet addresses even if the payment occurs on a testnet. See the [Quick Scan Address reference](https://docs.web3antivirus.io/reference/quick-scan-address).

Next experiment: obtain a sandbox key, verify the current request/response schema and supported networks, run one documented pass and one documented risk case, and save redacted evidence. Implement a backend adapter with explicit timeout, error handling, freshness, and verdict mapping. Confirm the additional token/message screening endpoints before claiming they cover a real authorization. Do not invent test addresses or infer “safe” from a successful HTTP status.

No Intercepta API client exists in the starter. The fixture scenarios are not vendor verdicts.

### World ID for Agents: implemented integration, live validation pending

The pasted event brief calls for the official development environment, backend validation, and a denied/expired/cancelled path. It explicitly says event proofs use fake identities and must not be relied on in production.

The official service and public MCP guides were successfully retrieved on 2026-09-26. `continuity/world.py` now implements the documented confidential-client device flow: discovery, device initiation, timed polling, JWKS signature validation, identity and freshness checks. The app first establishes the job owner, then requires a fresh matching identity for a changed-payout handoff. A separate explicit consent action consumes verification evidence bound to the exact intent hash. Device codes, tokens, and subjects stay on the backend.

A client is registered, Production credentials are configured, and live device initiation has succeeded. No completed live end-user verification is claimed. Missing configuration blocks execution; there is no fake approval fallback. See [setup, validation details, sources, and debrief](docs/world-id.md). Next evidence: register the client, complete a successful protected handoff, demonstrate denial/cancellation and wrong-owner rejection with the actual service, and record timings without exposing tokens or identities.

### x402: bounded paid requests

The [official buyer quickstart](https://docs.x402.org/getting-started/quickstart-for-buyers) documents clients that pay for HTTP resources. It does not establish a transferable or universally revocable agent-budget primitive. Continuity must own its budget and signing policy.

Next experiment: operate a test paid endpoint and a server-controlled signer; settle one bounded request and record the receipt. Use an idempotency key tied to job and batch, reconcile ambiguous settlements before retry, and account for chain fees separately. Never give either worker the owner's unrestricted wallet key.

Incrementing a local epoch cannot invalidate an already signed external authorization. Before live handoff, outstanding payment intents must be settled, expired, cancelled where supported, or reserved against the remaining budget. Do not advertise exactly-once payments until reconciliation and crash-recovery tests support that claim.

## Next implementation milestones

| Milestone | Concrete deliverable | Exit evidence |
| --- | --- | --- |
| 0 — local model (implemented) | State machine, fixture UI, exports, tests | Successful recovery and blocked/cancelled paths; automated invariant tests |
| 1 — durable execution (partial) | Encrypted Redis sessions and fenced request leases implemented for Vercel; authenticated workers and durable settlement records remain | Kill/restart at every transition; stale worker and concurrent retry tests |
| 2 — actual paid batch | Test x402 endpoint, bounded signing service, payment-intent ledger and reconciliation | Settlement evidence; ambiguous response/retry does not double-charge |
| 3 — resolution and screening | ENSv2 resolver and live Intercepta adapters | Recorded permission test and live pass/block results gate signing |
| 4 — owner-authorized handoff (code implemented) | World sandbox device flow and explicit intent consent; register client and run live | Automated rejection tests; live success/denial evidence still pending |
| 5 — protected capsules | Authenticated recipient key selection, authenticated encryption, retention policy, signed receipts | Wrong recipient fails decryption; tampering fails verification |

Use established cryptographic libraries for milestone 5; the starter intentionally contains no custom encryption. Exclude old credentials and payment secrets from every capsule. Key rotation does not erase information already disclosed to an earlier worker.

## Submission scope and unresolved questions

The supplied sponsor text is preserved in [docs/sponsor-brief.txt](docs/sponsor-brief.txt). It is user-provided event material, not a separately verified record of current prize rules. The original proposal is preserved in [docs/original-idea.md](docs/original-idea.md).

ENSv2, Intercepta, and World are candidate tracks. This starter does not satisfy their integration requirements, and Continuity-track eligibility has not been established. Confirm eligibility with the organizers before choosing a track. Do not report integration timings, feedback, real users, live calls, or deployed contracts until actually observed.

Open questions: who operates and authenticates the successor; who holds the signer; what happens after settlement succeeds but the response is lost; how checkpoint quality is validated; and whether a developer will integrate this rather than use existing orchestration retries. Interview a developer with a real failed paid workflow and reproduce that failure before expanding scope.

Defer escrow contracts, a marketplace, reputation scores, travel reservations, multichain support, and universal agent memory. The next useful proof is one recoverable paid batch with evidence of bounded authority.
