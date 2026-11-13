# Customer Account — cookie, CSRF and session-separation design

**Status:** proposed. **Authority:** OD-23, OD-33, DEC-0004, DEC-0005.

---

## 1. Three realms, and nothing shared between them

| | Staff Portal | Public Tracking | Customer Account |
|---|---|---|---|
| Session cookie | `solaris_session` | none | **`solaris_account_session`** |
| CSRF cookie | `solaris_csrf` | none | **`solaris_account_csrf`** |
| CSRF header | `X-CSRF-Token` | none | **`X-Account-CSRF-Token`** |
| Cookie path | `/` | — | **`/`**, see §3 |
| Session store | `user_sessions` | none | `customer_sessions` |
| Resolver | `auth_service.resolve_session` | none | `customer_auth_service.resolve_session` |
| Dependency module | `app/api/deps.py` | `app/api/public/deps.py` | `app/api/account/deps.py` |

**No cookie name, no header name, no session table, no resolver, no dependency and no
authorization decision is shared across a column.** A cookie from one realm presented to
another authenticates nothing — not because it is rejected by a check, but because the code
that would resolve it reads a different table.

Distinct names matter beyond hygiene: with one name, a browser holding both would send one
value and the server would resolve whichever realm looked first. That is the confusion
T-01 describes, and separate names make it impossible rather than unlikely.

---

## 2. Cookie attributes

| Attribute | Value | Why |
|---|---|---|
| `HttpOnly` | **true** for the session cookie | Script must not read it (DEC-0004) |
| `HttpOnly` | **false** for the CSRF cookie | The page has to echo it in a header (DEC-0005) |
| `Secure` | **true in production**, enforced at startup | Already a startup gate for the staff cookie; extended, not re-invented |
| `SameSite` | `Lax` | Survives the top-level navigation from a verification or reset link. `Strict` is preferred and is adopted if the final navigation design makes it workable |
| `Domain` | unset by default | A host-only cookie does not leak to sibling subdomains |
| `Path` | `/` | Considered and rejected: see §3 |
| `Max-Age` / expiry | session row governs | The cookie is a bearer of a digest; the server decides the lifetime |

---

## 3. Why the cookie path is `/` and not `/api/v1/account`

A narrower path looks like defence in depth and mostly is not: `Path` is not a security
boundary — same-origin script can read cookies for any path — and a narrow path breaks the
verification and reset landing pages, which are not under the API prefix. Separation is
enforced by **distinct names and distinct server-side stores**, which do not depend on the
browser honouring anything.

If the Customer Account is ever served from a **separate hostname**, that becomes the real
boundary and this section should be revisited then.

---

## 4. Session lifetime and revocation

| Property | Value | Note |
|---|---|---|
| Idle expiry | proposed **60 minutes** | Shorter than the staff 480: a customer session is often on a shared or mobile device and is used briefly |
| Absolute expiry | proposed **24 hours** | Matches the staff absolute expiry |
| Rotation | **new token on every successful authentication** | Session fixation (T-14) |
| Revocation | server-side, by row | The reason a session table exists at all (DEC-0004) |
| Cached grants | **none** | No role, no permission, no linked-customer id on the session row |
| "Remember me" | **not in release 1** | A longer-lived credential is a decision, not a convenience |

Because nothing is cached on the session row, a suspension, a link revocation or a
deactivation takes effect on the **next request**. This is the property Phase 7 established
for staff role changes, kept deliberately.

A completed password reset revokes **every** session for that identity. A password change
revokes every session except the one performing it.

---

## 5. CSRF

Double-submit with a server-stored digest, the staff pattern (DEC-0005), re-implemented in
this realm rather than imported from it:

1. On authentication a random CSRF token is issued in a readable cookie, and its SHA-256
   digest is stored on the `customer_sessions` row.
2. Every non-safe method must echo the value in `X-Account-CSRF-Token`.
3. The header is compared to the stored digest with `hmac.compare_digest`.
4. `GET`, `HEAD` and `OPTIONS` are exempt and **must stay side-effect free** — a `GET` that
   mutates is a CSRF hole no token can close.

A **staff** CSRF token does not satisfy a customer route, and vice versa: different cookie,
different header, different session row.

### 5.1 Unauthenticated POSTs

Register, sign-in, forgot-password and token redemption are `POST` routes with no session,
so there is no session row to bind a token to. They are protected by:

* being state-changing only in ways that are **rate limited and generic** — a forged
  registration produces the same response as a real one and no disclosure;
* `Origin` / `Referer` checking against the configured application origin, refused with the
  standard error shape when it mismatches;
* no ambient authority: nothing about them depends on an existing cookie.

Issuing a pre-session CSRF cookie to unauthenticated forms is deliberately **not** done: it
adds a cookie for anonymous visitors and protects nothing that the controls above do not.

---

## 6. CORS and origins

The Customer Account is served from the same origin as the API in release 1, exactly as the
Staff Portal is. Cross-origin credentialed requests are **not** enabled for it. If a
separate hostname is ever chosen, the CORS allowlist and cookie `Domain` become an owner
decision with its own record, not a configuration change made in passing.

---

## 7. Response headers

The security headers the application already sets apply to the new routes. Additionally:

| Header | Value |
|---|---|
| `Cache-Control` | `no-store` on every authenticated Customer Account response |
| `Referrer-Policy` | as configured today |
| `X-Content-Type-Options` | `nosniff` |

`no-store` matters here specifically: a shipment list on a shared phone must not sit in a
back-button cache after sign-out.

---

## 8. Sign-out

Sign-out **revokes the session row server-side** and then clears both cookies. Clearing a
cookie alone is not a sign-out: a copy of the value taken before it was cleared would still
resolve.

---

## 9. MFA readiness (OD-33)

Optional TOTP, **disabled by default**, is deferred to a hardening phase and is not part of
the first implementation phase. Customer MFA is **separate from the staff MFA decision
OD-17**, which remains open and is not answered by anything here.

The architecture must not make required MFA expensive later. Two cheap provisions, taken now
because they cost nothing at design time:

* the identity table can gain `mfa_secret`, `mfa_enabled_at` and `mfa_required` without
  touching the session model;
* the session row can gain an `authentication_level` column, so a partially authenticated
  session is representable without redefining what a session is.

Neither column is created by this phase.

---

## 10. Test obligations

1. Cookie names, header name and session table differ from the staff realm — asserted by
   name, so a copy-paste that reuses `solaris_session` fails.
2. A staff session cookie at a Customer Account route authenticates nothing; a customer
   session cookie at a staff route authenticates nothing.
3. A staff CSRF token does not satisfy a customer non-safe route.
4. Every non-safe Customer Account route rejects a request without the header.
5. Authentication rotates the session token.
6. Sign-out revokes server-side: a captured cookie value stops working.
7. Password reset kills every session for that identity.
8. Authenticated responses carry `no-store`.
9. In a production configuration, `Secure` is set on both cookies and startup refuses
   otherwise.
