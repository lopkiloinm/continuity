# Continuity

A local prototype for resuming interrupted agent work under a fixed remaining budget.

## Run

Python 3.9+; no packages or credentials needed.

```sh
python3 -m continuity.server
```

Open **http://127.0.0.1:8000**. Start the primary worker, inject a crash, evaluate a successor, and resume. Reset to try changed-payout approval/cancellation, a risk denial, or unavailable screening. Download the completed synthetic CSV and local JSON receipt.

```sh
python3 -m unittest discover -s tests -v
```

## What is real here

The server enforces state transitions, a simulated integer budget, authority epochs, fixed batch scope, and action-bound local consent. It creates checkpoints and hashed event records. Tests exercise rejection paths as well as completion.

**All records and spending are synthetic.** ENS, Intercepta, World, and x402 are not connected. Local approval is not identity verification. Capsules are plaintext and receipts are unsigned. No funds move. This single-process, single-job demo stores state in memory; restart/reset loses it. It binds only to loopback and has no user or worker authentication. Do not deploy it as a payment service.

## Files

- [idea.md](idea.md): refined scope, sourced constraints, acceptance criteria, and milestones.
- [continuity/engine.py](continuity/engine.py): local authority and handoff model.
- [continuity/server.py](continuity/server.py): local JSON API, CSV export, and static server.
- [static/](static/): interactive demo.
- [tests/](tests/): state-machine and HTTP tests.
- [docs/original-idea.md](docs/original-idea.md): preserved original proposal.
- [docs/sponsor-brief.txt](docs/sponsor-brief.txt): supplied event material.

The next milestone is durable job/batch storage and authenticated workers, followed by a real bounded test payment and settlement reconciliation. See the idea for the subsequent sponsor integration gates. No prize eligibility or production guarantees are claimed.
