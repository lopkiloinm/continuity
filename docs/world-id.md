# World ID for Agents integration

Continuity uses the official **World sandbox OIDC device grant**, implemented in `continuity/world.py`. It is a direct backend integration; installing World’s coding-agent plugin is not required.

## Register and configure

1. Open https://sandbox.auth.world.org/portal and sign in with Google. This developer login is separate from end-user World verification.
2. Register a confidential OIDC client, named Continuity, with **client_secret_basic** authentication (the portal default). `client_secret_post` is also supported if that is how you register.
3. Supply an exact **HTTPS redirect URL on a hostname you control**, as required by the portal. The device grant never navigates to this URL, but World requires it even for device-only clients and uses the registration’s hostname to establish the identity sector. Do not invent a domain or use an HTTP localhost callback. If you do not have a suitable URL or the portal rejects your account, ask the event team to help with registration.
4. Save the generated secret immediately; the portal displays it only once. Copy `.env.example` to `.env` and set `WORLD_CLIENT_ID`, `WORLD_CLIENT_SECRET`, and `WORLD_AUTH_METHOD`. Keep the secret out of chat, commits, screenshots, and the browser console.
5. Restart the server using the virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env  # only if .env does not already exist
# Edit .env locally with the portal values.
.venv/bin/python -m continuity.server
```

Open http://127.0.0.1:8000. Without credentials, the app shows “Not configured” and blocks job execution. There is no fake verification or approval fallback.

## Demonstrate the protected action

1. Select **Connect owner with World ID**. The backend creates a device request using the registered client. Open the returned World link, check the displayed user code, and complete World’s verification/approval flow.
2. The backend polls at the provider’s interval, validates the RS256 ID token, and privately associates `(issuer, subject)` with this browser session’s job. The browser receives neither token nor subject.
3. Start the primary worker, inject a crash, and choose **Changed payout · checks pass · ask owner**. The risk verdict is still an explicitly labeled fixture.
4. Select **Verify owner with World ID**. This starts a new device grant bound server-side to the immutable handoff intent hash. Verify with the same identity as step 1.
5. After backend validation, review the intent and select **Approve this handoff**. Only this separate consent consumes the one-time verification evidence and grants the backup worker authority. Resume to demonstrate the protected action.
6. Reset and repeat, denying on World’s page or cancelling locally. The successor must not start. A wrong owner, expired attempt, failed provider, or invalid token also prevents authority from being granted.

Job authority lasts ten minutes. Handoff approval lasts two minutes. Verification cannot extend either deadline. Reset creates a new job and requires establishing its owner again. Browser sessions and pending attempts are in memory and expire after an hour of inactivity; restarting the server discards them.

## Backend checks and boundaries

- Discovery is fetched from `https://sandbox.auth.world.org/.well-known/openid-configuration`; issuer and endpoint origin are checked. HTTPS endpoint redirects are refused.
- Device initiation requests exactly `scope=openid`. Secrets authenticate backend requests using the registered basic or POST method. There is no browser callback, PKCE, state, or nonce for this documented device grant.
- Device codes are private. The browser sees only the user code and provider-issued verification URL.
- Polls respect `interval`, `authorization_pending`, and `slow_down`. Other OAuth errors and transport failures terminate the local attempt; a retry requires an explicit new request. Local cancellation drops the device code and rejects late results; it does not claim to revoke the provider’s pending grant.
- PyJWT validates RS256 signatures against the discovered JWKS, exact issuer, audience, token expiry, required claims, and applicable authorized-party claims. The integration additionally checks `acr`, `amr`, and `auth_time` against the attempt start with five seconds of clock tolerance and a five-minute maximum age. Issuance time is not used as a replacement for authentication time.
- Fresh handoff verification must return the original owner’s issuer and subject. The backend binds the result to the job, capsule hash, epoch, successor, payee, amount, action, and deadline through the pending intent hash.
- A JSON `approved: true` request or a client-supplied `evidence` object is insufficient. The server must already possess validated, unexpired evidence, which is consumed once.
- Explicit consent is recorded separately from identity verification. Receipts contain an issuer, assurance class, authentication time, intent binding, evidence expiry, and token hash; no raw token, secret, device code, or subject is exported. These receipts remain unsigned local records, not independent proof of verification.
- Browser sessions use random HttpOnly, SameSite=Strict cookies. State is isolated by session; JSON-only requests and exact loopback Host/Origin checks protect local mutations. This server is loopback-only. Deployment needs HTTPS/Secure cookies, durable sessions and job storage, limits, and a production review.

The job's records, money, risk checks, and successor discovery are still simulated. World’s **sandbox uses test identities**, according to the supplied event brief; calling the real sandbox service does not establish production proof of humanity.

## Sources and observed evidence

Inspected on 2026-09-26:

- Official overview: https://sandbox.auth.world.org/docs
- Live OIDC discovery: https://sandbox.auth.world.org/.well-known/openid-configuration
- Official public MCP: https://sandbox.auth.world.org/mcp — `list_idp_guides`, then `get_idp_guide` for `getting-started`, `oidc`, and `step-up`. These developer guides require no login and specify the device grant and validation contract.
- Official plugin repository: https://github.com/worldcoin/world-id-agent-plugin — portal registration and HTTPS callback requirements.

Live discovery and public guide retrieval succeeded. **No client is registered for this project yet; no end-user live verification has been completed.** Automated tests use an isolated test transport and generated RSA keys, never a runtime mock mode.

## Integration debrief — fill in only after a live run

- Time to first successful end-user verification: not measured; registration pending.
- Friction observed: the docs page provides an overview; detailed endpoint contracts are exposed through public MCP guides. Registration requires an HTTPS redirect even for a localhost device-flow demo that never uses it.
- Missing capability observed in this prototype: credentials and a registered client; no claim that the provider lacks necessary features.
- Suggested improvement: a clearly linked device-only onboarding guide that explains the callback requirement upfront.
- Still to capture: successful verification and protected handoff, denial/cancellation, stale identity handling, and actual timing. Record redacted evidence without identity tokens, user subjects, or secrets.
