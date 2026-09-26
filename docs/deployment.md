# Vercel deployment

Production: https://continuity-ruddy.vercel.app

World registration redirect URI:

```text
https://continuity-ruddy.vercel.app/auth/world/callback
```

Choose **Client secret (Basic)**. Leave multiple callback domains empty. This device-flow app does not consume authorization-code callbacks; the route explains that and links back to the app.

## Runtime and plan

The existing Python backend deploys as a single Vercel Python 3.12 Function (`api/index.py`). `vercel.json` routes the frontend and API through that function. There is no local server dependency and no TypeScript rewrite. The function runs in Tokyo (`hnd1`) with a 60-second request limit. Each device poll is a separate bounded request; the function never waits for a human inside a running invocation.

The Vercel team was verified as **Hobby**. The user selected and connected the **Free Upstash Redis** plan. No paid Vercel upgrade or paid database was requested. Both services have free-tier quotas; do not enable auto-upgrades or paid plans for this demo.

## Configuration

Vercel project: `lopkiloinms-projects/continuity`.

| Variable | Source |
| --- | --- |
| `WORLD_CLIENT_ID` | World sandbox portal, after registration |
| `WORLD_CLIENT_SECRET` | Portal secret; backend-only |
| `WORLD_AUTH_METHOD` | `client_secret_basic` |
| `KV_REST_API_URL` / `KV_REST_API_TOKEN` | Connected Upstash integration |
| `SESSION_ENCRYPTION_KEY` | Random Fernet key configured on Vercel; backend-only |
| `APP_ORIGIN` | Optional exact HTTPS origin; otherwise Vercel's production and deployment URL environment variables are used |

Add World credentials to **Production** environment settings, then redeploy. Do not prefix secrets with public/frontend variable names. The World flow remains disabled until configured. Registration and live end-user verification remain separate steps from deployment.

Redis credentials created as sensitive Vercel variables cannot be downloaded through `vercel env pull`; that does not mean they are missing at runtime. Check `/api/health` on the deployed app for actual connectivity.

## Persistence and request safety

Cloud sessions live in Redis, expire after an hour of inactivity, and survive Python cold starts. A backend-only Fernet key encrypts the stored job, owner binding, and pending device-flow data. Cookies hold only an opaque session ID and use HttpOnly, Secure, and SameSite=Strict. A strict origin allowlist is derived from deployment configuration; a client cannot supply an arbitrary origin.

Each session request acquires a 90-second Redis lease. Atomic Lua scripts load, commit, and release state. The server confirms mutations only after a successful commit. A request whose lease has expired cannot overwrite a newer request's state. Concurrent requests return a retryable conflict. A lost provider response still requires a fresh verification attempt; this is not a distributed exactly-once payment guarantee.

World verification starts are limited per client address to eight per ten minutes. Failure of shared storage returns an error; production never falls back to process-local memory. Local development still uses in-memory sessions.

Rotating the encryption key invalidates existing sessions. Redis expiry is session retention, not a durable audit archive. Tokens and device codes must not be printed in logs or exposed through debug endpoints.

## Deploy and verify

Use a current Vercel CLI (the previously installed 41.7.0 was rejected by Vercel):

```sh
.venv/bin/python -m unittest discover -s tests -v
npx --yes vercel@latest deploy --prod --yes
```

Live checks:

- `/` serves the interface.
- `/api/health` reports `runtime: python` and `storage: redis` when the backend and database are connected.
- `/api/job` returns the same job ID for repeated requests carrying the same session cookie.
- `/auth/world/callback` is reachable over HTTPS.
- Wrong-origin mutations and unverified approval requests are rejected.

`.vercelignore` excludes `.env*`, the local virtual environment, tests, documentation, and Git metadata from uploaded deployment files. `.vercel/` is ignored by Git. Do not commit downloaded credentials.

References: [Vercel Python functions](https://vercel.com/docs/functions/runtimes/python/api-directory), [Vercel Redis](https://vercel.com/docs/redis), [Upstash REST API](https://upstash.com/docs/redis/features/restapi).

## Verified deployment evidence (2026-09-26)

35 automated tests passed. The public homepage, callback route, JavaScript asset, and Python health endpoint returned HTTP 200. The health response confirmed Redis connectivity and reported World credentials as not configured. Live API checks confirmed that unverified execution is rejected, cross-origin mutations are rejected, and session cookies are Secure. An existing session recovered the same job ID after a second production deployment replaced the Python function.

World credentials were subsequently configured as sensitive Production variables and deployed. `/api/health` now reports `world_configured: true`. A live owner device request was accepted by the official World service and returned its verification URL/user code; the isolated test request was cancelled locally without establishing an owner or granting authority. Completed end-user verification still requires the user's interaction.
