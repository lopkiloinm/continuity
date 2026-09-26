# Continuity

Resume interrupted agent work under a fixed remaining budget, with World ID verification protecting a change of control.

## Run

Python 3.9+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m continuity.server
```

Open **http://127.0.0.1:8000**. World ID credentials are required before starting a job. Follow [World setup](docs/world-id.md) to register a sandbox OIDC client and configure `.env`. The app fails closed until configured.

Connect the job owner through World, start the primary worker, inject a crash, and evaluate a changed-payout handoff. Fresh verification must match the same owner; explicit approval then unlocks the backup. Cancellation, denial, wrong identity, and expiry leave it unauthorized. Export the completed fixture CSV and local receipt.

```sh
.venv/bin/python -m unittest discover -s tests -v
```

## Integration status

| Part | Status |
| --- | --- |
| World ID for Agents | Official sandbox OIDC device-grant client implemented, with backend signature/claim/freshness checks and owner-bound consent. Registration and first live user verification pending. No runtime mock fallback. |
| ENS / Intercepta / x402 | Not integrated; successor discovery, screening, and money remain fixtures. |
| Research dataset | Synthetic records; no live GitHub research. |
| Local authority | Enforced state transitions, integer budget, authority epochs, fixed batches, and single-use verification evidence. |

World sandbox identities are test identities. No money moves. Capsules are plaintext and receipts are unsigned. Browser sessions and jobs are in memory; restarting loses them. The server is local-only, not a deployed payment service.

## Files

- [idea.md](idea.md): scope, constraints, and milestones.
- [docs/world-id.md](docs/world-id.md): registration, live-demo checklist, sources, and honest integration debrief.
- [continuity/world.py](continuity/world.py): official World OIDC client and verification lifecycle.
- [continuity/engine.py](continuity/engine.py): handoff model and consent requirement.
- [continuity/server.py](continuity/server.py): private browser sessions, World endpoints, job API, exports.
- [tests/](tests/): authority, HTTP, cryptographic validation, and device-flow failure tests. Test providers exist only in tests.
- [docs/original-idea.md](docs/original-idea.md) and [docs/sponsor-brief.txt](docs/sponsor-brief.txt): preserved original materials.
