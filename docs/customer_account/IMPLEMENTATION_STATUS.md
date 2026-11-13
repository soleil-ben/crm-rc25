# Customer Account — implementation status

**As of Phase 11 (2026-09-21).** This file answers one question: for every capability the
Phase 8 documents describe, what is actually true today?

The distinction that matters most is between **implemented** and **tested with synthetic
fixtures**. Everything below in the first column is real code with real tests, and every test
runs against generated data on a developer's machine. No customer has used any of it, no
message has been delivered to a real mailbox, and no human has executed a UAT case.

| Status | Meaning |
|---|---|
| **Implemented** | Built, and covered by automated tests against synthetic fixtures |
| **Development-only** | Built, and deliberately unusable in production |
| **Blocked for production** | Built, and refused in production until an owner action closes a gate |
| **Designed** | Specified in a Phase 8 document; no code exists |
| **Deferred** | Specified, and explicitly out of scope for the phase that might have built it |

---

## 1. Identity and authentication

| Capability | Status | Where |
|---|---|---|
| Separate identity realm: own table, sessions, cookies, CSRF header, router, dependencies, limiter namespace | **Implemented** | `app/api/account/`, `app/services/customer_auth_service.py` |
| Registration creating a pending identity and a pending proposal | **Implemented**, **blocked for production** | `customer_identity_service.register` |
| Email verification: purpose-bound, expiring, single-use | **Implemented** | `customer_identity_service.verify_email` |
| Verification resend, enumeration-safe | **Implemented**, **blocked for production** | `customer_identity_service.resend_verification` |
| Sign-in, sign-out, session resolution and revocation | **Implemented** | `customer_auth_service` |
| Password-reset request and completion | **Implemented**, **blocked for production** | `customer_identity_service` |
| Per-identity lockout, bounded in time | **Implemented** | `customer_auth_service._record_failure` |
| Administrative suspend / reinstate / deactivate | **Implemented at the service layer only** — still no route in Phase 10; reinstatement now checks for a live link before returning an account to `active` (DEC-0106) | `customer_identity_service` |
| Account status endpoint (`GET /me`) | **Implemented** | `app/api/account/routes.py` |
| Change password (knowing the current one) | **Deferred again, to Phase 12** — not in the Phase 10 scope list either | — |
| Optional TOTP | **Designed** (OD-33), deferred to a hardening phase | — |

## 2. Customer data

| Capability | Status | Where |
|---|---|---|
| Typed, allowlisted registration proposal (43 keys) | **Implemented** | `app/core/account_fields.py` |
| Normalized forms stored for later duplicate review | **Implemented** | reuses `app.core.normalization` |
| Terms and privacy acknowledgement, versioned and append-only | **Implemented**, **blocked for production** (OD-37) | `customer_terms_acknowledgements` |
| Operational notification preferences, unchecked by default | **Implemented** (written at registration only) | `customer_notification_preferences` |
| Marketing consent recorded as a proposal field, never a consent row | **Implemented** at registration. After approval the customer grants or withdraws directly, append-only, audited (DEC-0123) | `customer_data_proposal_fields`; `POST /api/v1/account/consent/marketing` |
| Proposal supersession by immutability | **Implemented** | `supersedes_proposal_id` |
| Canonical columns for display name, legal name, billing address role | **Implemented** (DEC-0101) — `customers.legal_name`, `customers.display_name`, `AddressRole.BILLING` | Phase 10 migration `6af30fcdd3a8` |
| Profile read, direct edit, and proposal submission after approval | **Implemented** in fix pack 2 (DEC-0123): preferred language direct; legal name, preferred name, phone and pickup address by proposal; email **not** proposable (needs a verified email-change flow) | `GET /api/v1/account/profile`, `POST …/profile/direct`, `…/profile/proposals`, `…/profile/proposals/withdraw`; screen `/account/profile` |
| Staff approval, linking and registration review | **Implemented** — backend and staff API only | `app/api/v1/routes/customer_account_review.py` |
| Post-approval profile-change proposal review | **Implemented** in fix pack 2: per-group approve/decline, drift refused, decided once | `/api/v1/customer-account/profile-proposals`, `…/identities/{ref}/profile-proposal[/decide]`; screen `/customer-accounts/{ref}/profile-change` |

## 3. Shipment visibility

| Capability | Status | Where |
|---|---|---|
| Authenticated shipment list, 18 fields (`booking_reference` added in UAT round 11, DEC-0160) | **Implemented** | `GET /api/v1/account/shipments` |
| Authenticated shipment detail, 25 fields (`booking_reference` added in UAT round 12, DEC-0163) | **Implemented** | `GET /api/v1/account/shipments/{reference:path}` |
| Ownership enforcement in the query, on both routes | **Implemented** | `customer_account_shipment_service` |
| The effective-link resolution both routes authorize from | **Implemented** | `customer_account_link_policy.resolve_readable_customer` |
| One OD-29 inclusion rule, shared with the staff disclosure preview | **Implemented** | `customer_account_disclosure_service.qualifying_conditions` |
| Status-group and date-range filters | **Implemented** — the two `SHIPMENT_ALLOWLISTS.md` §3.2 approves |
| Bounded, stably ordered offset paging | **Implemented** — max 50 per page, total order on `(booking_date, public_id)` |
| `account:read:identity:*` rate-limit bucket | **Implemented** — 300 / 5 min, its own namespace |
| Denial audit, success logging, both redacted | **Implemented** | `customer_account.shipment_access_denied` |
| `customer_identity_links` table and its partial unique indexes | **Implemented** — written by the Phase 10 approval service, and by nothing else |
| Free-text search by shipment reference | **Not built** — §3.2 declines it in release 1. Asserted absent |
| Route filter | **Not built** — not in the approved filter set. Asserted absent |
| Package-reference lookup on the authenticated route | **Not built** — a second identifier space to authorize, and none was opened |
| The replacement reference on a rebooked shipment | **Not built** — a second disclosure decision (`SHIPMENT_ALLOWLISTS.md` §5) |
| Linked return-shipment workflow | **Deferred** — OD-22 is open. A return is visible only through its own `customer_id` |
| Customer Account frontend screens | **Deferred to Phase 12** — this phase is backend only |
| Any mutation route on this surface | **Not built**, and asserted absent by walking the route table |

**An active, linked identity now reads its own shipment history, and nothing else.**
`GET /me` reports `shipment_history_available` truthfully, answered by the same helper the
shipment routes use so the two cannot disagree. It is still a boolean: no count, no date and
no customer reference, because a count of matching shipments is itself an enumeration
oracle.

## 4. Email delivery

| Capability | Status |
|---|---|
| `EmailTransport` seam and message catalogue | **Implemented** |
| `null` transport (records a send, produces nothing) | **Implemented** — the default, including in tests |
| `capture` transport (local files, opens no socket) | **Development-only** — refused at startup in production |
| Production transport | **Not written.** Selecting it fails at startup (OD-34) |
| Suppression checked before every send | **Implemented** — reads the existing `contact_suppressions` |
| HTTP access to captured mail | **Deliberately absent**, asserted over the whole route table |

## 5. Security controls

| Control | Status |
|---|---|
| Argon2 hashing, shared policy with staff | **Implemented** |
| Generic responses on register, resend, forgot-password, sign-in, token redemption | **Implemented** |
| Comparable work on the sign-in miss path | **Implemented** |
| Keyed, purpose-bound token digests (DEC-0097) | **Implemented** |
| Session rotation on authentication | **Implemented** |
| Server-side revocation; reset revokes every session | **Implemented** |
| CSRF double-submit bound to the session row | **Implemented** |
| `Origin` / `Referer` check on unauthenticated POSTs | **Implemented** |
| Ten `account:*` rate-limit buckets, separate from staff and public | **Implemented** |
| Rate limits before body parsing; zero statements on a refusal | **Implemented**, measured with an engine listener |
| Audit events with hashed address keys and no credential material | **Implemented** |
| CAPTCHA, proof of work, IP reputation, device fingerprinting | **Not built**, and deliberately so (`RATE_LIMITS_AND_ABUSE.md` §6) |

## 6. Acceptance criteria

| Group | Position after Phase 11 |
|---|---|
| AC-CA-1 surface separation | **Passing** — extended to the two read routes: no staff dependency, no staff or public model, their own limiter bucket |
| AC-CA-2 registration and enumeration resistance | **Passing** |
| AC-CA-3 verification, tokens, recovery | **Passing** |
| AC-CA-4 approval, linking, canonical safety | **Passing** — Phase 10, and 4.9 still holds: the read path writes no canonical row |
| AC-CA-5 ownership of shipment data | **Passing** — 5.1 to 5.7, all automated. The **H** half of 5.1, 5.5 and 5.7 waits for the Phase 12 UAT execution |
| AC-CA-6 field and response discipline | **Passing** — 6.1 (24 by name), 6.2 (17 by name), 6.3 (public still 24, its test untouched), 6.4 and 6.5 by planted-value scan. 6.6 is still Phase 12's, because no proposal route exists |
| AC-CA-7 consent, suppression, preferences | **Partially passing** — suppression and consent-absence hold; the customer-facing consent route is Phase 12 |
| AC-CA-8 sessions and CSRF | **Passing** — 8.5 and 8.6 re-asserted on the new routes: suspension takes effect on the next request, and both routes carry `no-store` on success and on refusal |
| AC-CA-9 email | **Passing** |
| AC-CA-10 audit | **Passing for the Phase 9, 10 and 11 vocabularies** |
| AC-CA-11 schema and migrations | **Passing** — Phase 11 adds no migration, and `alembic check` is green at the same head |
| AC-CA-12 language and launch | **12.1–12.4 passing**; human confirmation of 12.1 needs the frontend |

The **A** (automated) half of every group above is green. The **H** (human UAT) and **R**
(review) halves of AC-CA-5, AC-CA-6 and AC-CA-12 are unexecuted by design: no human has run
a Customer Account UAT case, and Phase 11 was instructed not to.

## 7. What blocks release 1

Unchanged by this phase, and none of it is a development task:

1. **OD-34** — a production email provider, with data residency, an authenticated sending
   domain, and bounce and complaint handling. **Registration cannot launch without it.**
2. **OD-37** — approved terms and privacy text with version identifiers. **Registration
   cannot launch without it.**
3. **OD-39** — customer-facing English copy reviewed by the business.
4. **OD-19** — a Customer Account accessibility review, with no reviewer assigned.
5. **OD-01** — retention periods, which OD-36 aligns the canonical categories with.
6. An accepted `Design.md` Customer Account section, before any frontend work (Phase 12).
7. The 28-case Customer Account UAT pack executed by a human. **All 28 results are blank.**

**Registration is not production-ready**, and nothing in this phase describes it as such.

## 8. Testing status, stated precisely

Every Customer Account test runs against synthetic fixtures on a developer machine:
generated identities, generated customers, generated shipments, and a capture transport that
writes to a temporary directory. That is what the suite is evidence of.

It is **not** evidence that a real mailbox receives a message, that a real provider accepts
one, that a real customer can complete registration, or that the copy reads well to somebody
who did not write it. Those need OD-34, OD-37, OD-39 and a human.

No test makes an external request. `socket.socket` is replaced with one that raises, and the
whole registration and recovery path is driven against it.


---

## Phase 10 — staff approval, linking and rejection

| Capability | Status | Where |
|---|---|---|
| `customer_account:review` and `customer_account:approve`, Admin and Operations only | **Implemented** | `app/core/permissions.py` |
| Bounded, filtered, totally ordered pending-registration queue | **Implemented** | `customer_account_review_service.list_pending` |
| One application in detail, with entered and normalized values | **Implemented** | `GET …/registrations/{ref}` |
| Duplicate candidates through the **existing** `duplicate_service` | **Implemented** | `customer_account_review_service.duplicate_candidates` |
| Server-calculated approval preview with a drift fingerprint | **Implemented** | `customer_account_review_service.build_preview` |
| Historical-shipment disclosure (OD-29), five figures | **Implemented** | `customer_account_disclosure_service` |
| Explicit disclosure acknowledgement, stored with its figures | **Implemented** | `customer_account_disclosure_acknowledgements` |
| Approve by creating a canonical customer | **Implemented** | `customer_account_approval_service.approve_create_new` |
| Approve by linking to an existing customer, writing no canonical value but the email (DEC-0138), and ending a deactivated account's link (DEC-0140) | **Implemented** | `…approve_link_existing` |
| Rejection, with session revocation and token invalidation | **Implemented** | `…reject` |
| Activation, only through the approval service | **Implemented** | `…_activate`, one statement |
| Idempotency and concurrency guards, SQLite-safe | **Implemented** | `customer_account_approval_attempts` + two partial unique indexes |
| Development-only approval and rejection notices | **Development-only**, **blocked for production** (OD-34) | `account_email_service` |
| Staff Portal approval screen | **Deferred to Phase 12** — this phase is backend and staff API only | — |
| Admin reinstatement of a rejected account (transition 9) | **Deferred** — not in the Phase 10 scope list | — |
| Suspend / reinstate / deactivate routes | **Deferred** — services exist, no route | — |
| Unlink | **Deferred** — no route, and no service | — |
| Privacy-request execution (OD-35) | **Designed**; not built | — |

### What an approval grants, as of Phase 11

An account that is `active` and linked reads **its own canonical customer's shipment
history**, through two `GET` routes, under the same OD-29 rule the reviewer acknowledged
before approving. It reaches nothing else: no other customer's rows, no financial value, no
recipient or sender detail beyond a city and a country, no internal note, no audit row, no
staff name, and no mutation of anything.

An account that is anything other than `active` **and** holds exactly one effective link to a
canonical, unarchived, unmerged customer reads nothing at all, and is told so in one sentence
that does not say which of those conditions failed.

### Known limitations recorded rather than fixed

| Limitation | Why it is left, and why it is safe |
|---|---|
| ~~Merging a linked customer leaves the link on the tombstoned record~~ — **closed by OD-40** | The merge is now refused while either side holds an effective link (`customer_account_link_policy`, DEC-0107). What replaces it as a limitation is the next row |
| No merge-with-account reconciliation workflow | OD-40's consequence: a duplicate involving an account holder cannot be merged at all. The refusal names which side blocked, and there is no route to revoke a link either, so there is no workaround inside this phase. The workflow — fresh duplicate review, disclosure preview, acknowledgement, session handling, explicit owner-approved link transition — is deferred |
| The cross-table activation invariant is not a database constraint | SQLite has no cross-table `CHECK`, and a trigger would be a fifth guard mechanism. It lives in the transaction ordering and in a database sweep the tests run after every decision |
| `internal_detail` on a rejection is accepted and discarded | The existing redaction rules keep prose about a person out of the audit trail, and no other reviewed store exists. The field stays in the contract so the shape does not move when one does |
