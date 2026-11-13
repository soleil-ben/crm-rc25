# Customer Account — threat model

**Status:** requirements only. Each finding below states what an attacker does, what they
gain, what prevents it, how it is detected, what the audit record holds, and the test that
proves the prevention. A finding without a test is not mitigated; it is hoped about.

**Scope.** The new authenticated customer surface. The Staff Portal and Public Tracking are
in scope only where this surface could weaken them.

---

## Summary

| ID | Threat | Severity | Release-1 disposition |
|---|---|---|---|
| T-01 | Cross-surface session confusion | **High** | Prevented by separate realms |
| T-02 | Account and customer enumeration | **High** | Prevented by generic responses |
| T-03 | Horizontal access — another customer's shipments | **High** | Prevented by server-side ownership |
| T-04 | Ownership claimed by possession of a reference | **High** | Prevented; references are not credentials |
| T-05 | Token theft, replay or brute force | **High** | Hashed, single-use, expiring, rate limited |
| T-06 | Approval abused to link the wrong customer | **High** | Human approval with disclosure preview + audit |
| T-07 | Canonical data corrupted through the customer surface | **High** | Proposals only; no direct canonical write |
| T-08 | Suppression or consent weakened by a customer | **High** | Suppression is not customer-reachable |
| T-09 | CSRF against a customer action | Medium | Double-submit bound to the session row |
| T-10 | Credential stuffing / password spraying | Medium | Per-address and per-IP buckets, lockout |
| T-11 | Registration flooding / mail-bombing a third party | Medium | Rate limits + no unsolicited repeat mail |
| T-12 | Privilege escalation to a staff route | **High** | No role, no permission, no shared dependency |
| T-13 | Sensitive data in logs or audit payloads | Medium | Reason codes and safe identifiers only |
| T-14 | Session fixation / insufficient revocation | Medium | Rotate on authentication, server-side revocation |
| T-15 | An external request escaping during tests | Medium | No provider, no network in fixtures |
| T-16 | Timing or error-shape oracles | Medium | Uniform shapes; comparable work |
| T-17 | Disclosure through an error or a stack trace | Medium | Single error shape, no internals |
| T-18 | Insider misuse of approval | Medium | Audit with actor, reason code, and preview figures |

---

## T-01 — Cross-surface session confusion
**Attack.** A staff cookie is presented to a customer route, or a customer cookie to a staff
route, and one of them authenticates.
**Gain.** Total: a customer reaching staff data, or a staff session silently acting as a
customer.
**Prevention.** Separate cookie names, separate session tables, separate resolvers, separate
routers, separate dependency modules. A customer session token is not resolvable by
`app.services.auth_service`, and a staff token is not resolvable by the customer resolver —
they read different tables, not the same table with a flag.
**Detection.** A staff cookie arriving at a customer route is logged as a security event with
no customer identifier attached.
**Audit.** Action, surface, reason code. No cookie value, ever.
**Tests.** Present each cookie to every route of the other surface and assert 401; assert no
Customer Account route depends on `app.api.deps`, by walking the route table.

## T-02 — Account and customer enumeration
**Attack.** Register, request a reset, or resend verification with a guessed address and read
the difference in response, status code, field-level error, or latency.
**Gain.** Confirmation that a person is a Solaris customer — which is itself commercially
and personally sensitive — and a target list for T-10.
**Prevention.** One response body and one status code for every outcome of register, forgot
password and resend. No "email already registered" error, ever. No duplicate score, match
count or candidate detail on any customer-facing response. Comparable work is performed on
the miss path so latency does not separate the cases.
**Detection.** Rate-limit counters per IP and per address; a spike of distinct addresses from
one source is the signal.
**Audit.** `register` and `password_reset_requested` with a hashed address key and the reason
code, **not** the raw address, in the security-event payload.
**Tests.** Assert the response body, status and headers are identical for known and unknown
addresses; assert no response field anywhere contains a match, score or count.

## T-03 — Horizontal access to another customer's shipments
**Attack.** Authenticate as customer A, request customer B's shipment reference directly.
**Gain.** Another customer's shipment history — names, cities, dates.
**Prevention.** Ownership in the query: `shipments.customer_id = <linked customer>`. The
detail route re-checks the loaded row. Same generic not-found body for "absent" and "not
yours".
**Detection.** Repeated not-found results for one identity is a probing signal.
**Audit.** Denied access logged with identity `public_id` and the requested reference; no
customer data from the refused row.
**Tests.** Two customers, each with shipments; every cross request returns the generic body;
list responses contain only the caller's references.

## T-04 — Ownership claimed by possession of a reference
**Attack.** Register, then claim a shipment by entering a tracking reference found on a
label, an email or a parcel.
**Gain.** Access to a shipment the attacker did not send.
**Prevention.** **There is no claim-by-reference flow.** Linking is staff-performed against
the canonical customer. Email, phone, address and reference possession are all explicitly
insufficient (OD-29, OD-30).
**Detection.** Not applicable — the flow does not exist. A code review that finds one has
found a defect.
**Audit.** n/a.
**Tests.** Assert no route accepts a tracking reference as an identity or linking input.

## T-05 — Token theft, replay or brute force
**Attack.** Reuse a verification or reset link, guess a token, or redeem one twice
concurrently.
**Gain.** Account takeover.
**Prevention.** 32 bytes of randomness; stored as SHA-256; single use enforced by a
conditional update so concurrent redemption cannot both succeed; short expiry; invalidated
by a newer token of the same purpose and by any password change; bound to the address it was
issued to; a completed reset revokes every session.
**Detection.** Redemption attempts on consumed or expired tokens, counted per identity and
per IP.
**Audit.** Token **purpose** and outcome. Never the token, never its digest in a customer-
visible response.
**Tests.** Replay a consumed token; redeem an expired one; redeem concurrently and assert
exactly one success; assert the plaintext appears in no log, no audit row and no database
column.

## T-06 — Approval abused to link the wrong customer
**Attack.** A plausible registration matching a well-known customer is approved by a hurried
staff member.
**Gain.** Full history of that customer.
**Prevention.** Approval is explicit, per account, never automatic or bulk; the disclosure
preview (count, oldest, newest, cancelled/rebooked included) must be acknowledged; the
approver sees proposed vs current values and duplicate implications; one active link per
customer refuses a second.
**Detection.** Approval rate per actor; approvals with a large disclosure count.
**Audit.** Actor, identity, customer, preview figures, acknowledgement, reason code.
**Tests.** Approval refused without acknowledgement; refused when the customer already has an
active link; audit row contains the preview figures.

## T-07 — Canonical data corrupted through the customer surface
**Attack.** Craft a profile update that writes the canonical customer directly, or a
registration that overwrites an existing record.
**Gain.** CRM corruption, or a takeover by rewriting a customer's contact details.
**Prevention.** The customer surface has **no canonical write path**. Registration and
updates create proposals. Canonical writes happen only in the staff approval transaction,
through the existing customer service, with the existing audit and duplicate review.
Field keys are validated against the allowlist; drift since submission refuses the field.
**Detection.** Any canonical write whose actor is not a staff user is an alarm.
**Audit.** `customer_data_proposal.*` plus the existing customer audit rows.
**Tests.** Assert no Customer Account service imports a canonical write function; assert a
proposal alone changes nothing; assert drift refuses.

## T-08 — Suppression or consent weakened by a customer
**Attack.** Re-consent, or flip a notification preference, to escape a global suppression.
**Gain.** Marketing mail that operations had blocked. (Since DEC-0139 a suppression
blocks marketing only: account email -- verification, reset, decision notices -- reaches a
suppressed address, so a suppression can never lock a person out of their own account.)
**Prevention.** Suppression is not readable, creatable or releasable from this surface. A
consent grant does not lift a suppression and does not report its existence. Consent is
append-only; withdrawal always works, granting never overrides.
**Detection.** Any send-time check that finds a suppressed address with a consent grant is a
defect signal, not a reason to send.
**Audit.** Consent events as today, append-only.
**Tests.** Grant consent on a suppressed address; assert the suppression stands, that the
address remains non-contactable, and that the response says nothing about it.

## T-09 — CSRF against a customer action
**Attack.** A third-party page posts to a Customer Account route using the customer's cookie.
**Gain.** A profile proposal, a consent change, or a sign-out on the customer's behalf.
**Prevention.** The staff pattern, re-implemented in the customer realm: a readable CSRF
cookie whose digest is stored on the customer session row, echoed in a header on every
non-safe method, compared with `hmac.compare_digest`; `SameSite=Lax` (`Strict` if the
final navigation design allows); `Secure` in production.
**Detection.** CSRF failures per session.
**Audit.** Reason code only.
**Tests.** Every non-safe route without the header returns 403; a staff CSRF token does not
satisfy a customer route.

## T-10 — Credential stuffing and password spraying
**Attack.** Breached credential pairs replayed against sign-in.
**Gain.** Account takeover at scale.
**Prevention.** Per-address and per-IP sliding-window limits in a **separate bucket
namespace** from staff and public limits; per-identity lockout after repeated failures;
Argon2 verification on the miss path too, so failure timing does not separate known from
unknown addresses; a strong minimum password policy.
**Detection.** Failure counts per address, per IP, and distinct-address counts per IP.
**Audit.** `sign_in_failed` with a hashed address key, IP and reason code.
**Tests.** Lockout engages and expires; a customer flood does not consume the staff or public
allowance; refusal text is identical to a wrong password.

## T-11 — Registration flooding, and mail-bombing a third party
**Attack.** Repeated registrations or resends against somebody else's address.
**Gain.** Harassment, or denial of service against the mail path.
**Prevention.** Rate limits per IP and per target address; **one** verification message per
issuance with a cooling-off period on resend; an already-registered address receives at most
a single "somebody tried to register" notice subject to the same cooling-off.
**Detection.** Resend counts per address.
**Audit.** Counts and reason codes; never the message body.
**Tests.** Repeated registrations for one address produce one message within the window and a
generic response every time.

## T-12 — Privilege escalation to a staff route
**Attack.** Manipulate the identity payload — inject a role, a permission, an `is_staff`
flag — to reach a staff route.
**Gain.** Staff access.
**Prevention.** A customer identity has no role column and no permission lookup path. Staff
routes depend on `require(...)`, which resolves permissions from `users.role`; there is no
code path from a customer session to a `User`.
**Detection.** Any customer identifier appearing in a staff authorization decision.
**Audit.** Standard staff audit, unchanged.
**Tests.** Walk every staff route with a customer session and assert 401 — never 403, which
would imply the caller was authenticated.

## T-13 — Sensitive data in logs or audit payloads
**Attack.** Read a log or an audit payload and find credentials, tokens or personal data.
**Gain.** Credentials or a customer list without touching the database.
**Prevention.** Audit payloads carry reason codes, public identifiers, field keys and counts.
Passwords, hashes, tokens, digests and session identifiers are never written. Email and phone
are absent from security-event payloads; a hashed address key is used instead. Access-log
redaction already required in production (`docs/OPERATIONS.md`) extends to the new routes.
**Detection.** A repository scan for token-shaped strings in fixtures and logs.
**Audit.** n/a — this is about the audit.
**Tests.** Register, verify, reset and sign in, then assert that no emitted log line or audit
row contains the password, the token or the raw address.

## T-14 — Session fixation and insufficient revocation
**Attack.** Fix a session before authentication, or keep using one after a password change,
suspension or link revocation.
**Gain.** Persistence after the account was supposed to be closed.
**Prevention.** A new session token on every successful authentication; server-side
revocation; the session row holds **no cached grant**, so state is re-read every request;
password reset revokes all sessions; suspension and link revocation take effect on the next
request.
**Detection.** Requests arriving on revoked session digests.
**Audit.** Revocation events with reason codes.
**Tests.** Suspend mid-session and assert the next request fails; reset a password and assert
every other session is dead.

## T-15 — An external request escaping during tests
**Attack.** A fixture or a development email path reaches the internet.
**Gain.** Real mail sent to a real person from a test, or a provider contacted before the
owner chose one.
**Prevention.** No provider is selected (OD-34); the development transport writes to a
capture, never to a socket; the existing "no external provider request" invariant in
`scripts/verify_rc_baseline.py` extends to the mail path.
**Detection.** The existing baseline invariant, plus a test-level socket guard.
**Audit.** n/a.
**Tests.** Assert the test suite makes no outbound connection on the mail path, and that the
production transport is unreachable unless explicitly configured.

## T-16 — Timing and error-shape oracles
**Attack.** Measure latency, or compare error shapes and headers, to separate a known address
from an unknown one.
**Gain.** Enumeration by another route (see T-02).
**Prevention.** Identical bodies, status codes and headers; comparable work on both paths,
including password verification on the miss path.
**Detection.** n/a in release 1 — this is a design property, not a runtime alarm.
**Audit.** n/a.
**Tests.** Assert shape equality. **Latency equality is not asserted as a numeric threshold**:
a timing assertion on a shared CI machine is a flaky test, not a security control. The
control is the work performed, which is asserted structurally.

## T-17 — Disclosure through an error
**Attack.** Force an exception and read the response.
**Gain.** Internal ids, table names, query fragments, a stack trace.
**Prevention.** One error shape for this surface, like the public surface's single failure
body; no internal identifiers in any customer-facing error; debug output off in production,
already a startup gate.
**Detection.** Error rates per route.
**Audit.** Server-side detail stays server-side.
**Tests.** Malformed input on every route returns the standard shape with no internals.

## T-18 — Insider misuse of approval
**Attack.** A staff member links themselves, or a colleague, to a customer they want to read.
**Gain.** Customer history, without any external compromise.
**Prevention.** Approval requires an account that completed registration and verification;
one active link per customer; every approval is attributable, with the disclosure figures.
**Detection.** Review of approvals per actor; approvals of large-history customers.
**Audit.** Actor, identity, customer, preview figures, acknowledgement, reason code.
**Tests.** Audit completeness for every approval path.

---

## Residual risks, accepted and recorded

| Risk | Why it is accepted in release 1 |
|---|---|
| **No customer MFA.** A stolen password is enough | OD-33 defers TOTP to a hardening phase. The architecture must not prevent making it required later |
| **No production email provider chosen** | OD-34. Registration cannot launch in production until one is selected, which makes this a launch blocker rather than a live risk |
| **In-process rate limiting** | DEC-0006: counters are per process and reset on restart. Multiple workers require a shared store, already a production gate |
| **No captcha or proof of work** | Not selected; rate limits and generic responses carry release 1. Revisit if registration abuse appears |
| **Suppression state is invisible to the customer** | Deliberate. A customer who cannot see a suppression cannot work around it; the cost is a customer who does not know why mail stopped, which is handled by staff |
| **OD-01 retention unanswered** | No canonical deletion schedule exists to implement (OD-36). Token and session expiry do not wait for it |
