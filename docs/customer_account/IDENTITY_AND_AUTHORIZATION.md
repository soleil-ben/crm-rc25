# Customer Account — identity and authorization architecture

**Status:** requirements only. No code exists for anything described here.

---

## 1. The one-sentence rule

A **customer identity** is not a user, does not live in `users`, does not hold a role, does
not carry a permission, and cannot reach a staff route — and a staff user cannot reach a
customer route with a staff session. Everything below is an elaboration of that sentence.

---

## 2. Why customer identities are not rows in `users`

`users` is the staff table. A row in it has a `role`, and that role resolves through
`app.core.permissions.permissions_for()` into the permission set that
`app.api.deps.require(...)` enforces on **97 guarded staff routes**. Adding customers to
that table means every one of those routes is one permission-set bug away from serving a
customer, and every future permission added to a role has to be checked against a
population it was never meant to describe.

It also means a single authentication bug is a total one. Today a staff session cookie
resolves in `app.api.deps.current_session`; a customer session must resolve somewhere else,
through code that cannot mint a staff session even if it is wrong.

So:

| | Staff | Customer |
|---|---|---|
| Table | `users` | `customer_identities` (new) |
| Credential | password hash (Argon2) | password hash (Argon2), separate column in a separate table |
| Session table | `user_sessions` | `customer_sessions` (new) |
| Session cookie | `solaris_session` | **different name**, see [`SESSION_COOKIES_AND_CSRF.md`](SESSION_COOKIES_AND_CSRF.md) |
| CSRF cookie | `solaris_csrf` | **different name** |
| Dependency | `app.api.deps.current_user` / `require(...)` | `app.api.account.deps.current_identity` (new) |
| Router | `app/api/v1` | `app/api/account` (new) |
| Prefix | `/api/v1/...` | `/api/v1/account/...` |
| Authorization model | role → permissions | **no roles, no permissions**: ownership only |
| Rate-limit buckets | staff keys | separate key namespace |

There is **no shared base class, no shared dependency, and no shared session resolver**
between the two columns. The public surface already sets this precedent:
`app/api/public/deps.py` exists as its own small file precisely so that a staff dependency
cannot be attached to a public route by reflex. The Customer Account gets the same
treatment, for the same reason.

---

## 3. Authorization is ownership, not permissions

A customer identity has no permission set. Every authenticated customer route answers one
question instead:

> Does the row being requested belong to the canonical customer this identity is linked to?

Concretely, for every customer resource:

```
identity  →  identity.status == active
          →  identity.linked_customer_id is not null
          →  resource.customer_id == identity.linked_customer_id
```

All three, server-side, on **every** request, in the query itself — not as a filter applied
after loading, and never in the frontend. A list endpoint constrains by
`shipments.customer_id = :linked_customer_id` in SQL; a detail endpoint re-checks ownership
on the loaded row and returns the **same generic not-found response** for "does not exist"
and "exists but is not yours" (see [`THREAT_MODEL.md`](THREAT_MODEL.md) T-03).

**No frontend-only ownership filtering.** A screen that hides a row is a courtesy, never a
boundary. This is the same rule `CRM.md` section 11 already applies to the Staff Portal.

---

## 4. Identity states

| State | Can sign in | Sees own profile | Sees shipment history |
|---|---|---|---|
| `pending_verification` | no | — | no |
| `pending_approval` | yes | yes | **no** |
| `active` | yes | yes | yes, its linked customer's only |
| `rejected` | no | — | no |
| `suspended` | no | — | no |
| `deactivated` | no | — | no |

Only `active` **and** linked reaches shipment data. `pending_approval` is a real signed-in
state with a real session, deliberately: the customer needs to be told where their
application stands, and telling them requires authenticating them. It reaches exactly two
things — their own submitted profile, and their account state.

The transitions, their actors and their audit records are in
[`STATE_MACHINES.md`](STATE_MACHINES.md).

---

## 5. Identity ↔ customer cardinality (OD-25, OD-26)

**Release 1 rule.** One identity links to **at most one** canonical customer. One canonical
customer has **at most one approved active identity**. No identity reaches two canonical
customers.

**The model must not make the future expensive.** The link is therefore *not* a nullable
`customer_id` column on the identity row, even though that is the smallest thing that
satisfies release 1. It is a **separate link table**,
`customer_identity_links(identity_id, customer_id, link_role, status, …)`, with a partial
uniqueness constraint that enforces the release-1 limitation:

* at most one `active` link per identity — the release-1 rule;
* at most one `active` link per customer — the release-1 rule;
* both enforced by index, not by application code alone.

Relaxing to company access later means **dropping a uniqueness constraint and adding a
`link_role` value**, not rebuilding identity ownership, not rewriting every ownership check, and
not migrating a foreign key that half the application reads. That is the entire reason for
the extra table, and it is what OD-25 asks for in its last sentence.

The same table is where a later invitation model attaches (`invited_by_identity_id`,
`accepted_at`) without touching the identity itself.

### 5.1 What counts as an **effective** link (OD-40)

Two questions read this table and must not answer differently: "may this identity be linked
to this customer?" (the approval) and "may this customer be merged?" (the customer merge).
One definition, in
`backend/app/services/customer_account_link_policy.py`:

> A customer has an **effective link** when a `customer_identity_links` row names it and
> that row's `status` is `active`.

The **identity's** status is deliberately not part of the test. Every case falls out of the
one rule:

| Identity state | Link row | Effective? | Why |
|---|---|:--:|---|
| `active` | `active` | **yes** | The account reaches this customer's history today. |
| `suspended` | `active` (retained) | **yes** | Suspension revokes sessions and keeps the link; transition 7 of [`STATE_MACHINES.md`](STATE_MACHINES.md) returns the account to `active` **precisely when** an active link is still there. Access is paused, not surrendered. |
| `deactivated` | `active` (kept) | **yes**, but it does **not** block a merge | `customer_identity_service.deactivate` revokes sessions and tokens and keeps the link. The row still counts for the unique indexes; the merge guard (`has_merge_blocking_link`) excludes it, because a deactivated identity can never read through it (DEC-0134). It does not stop a new account being linked: a staff link-existing approval of the new account ends it (DEC-0140). |
| `deactivated` | `revoked` | no | Ended by a takeover approval (`revoke_reason_code = taken_over_by_new_account`, audited `customer_account.unlink`, DEC-0140). Grants nothing and does not block. |
| `rejected` | none | no | Rejection writes no link. |
| `rejected` | `active` | **yes** | A state nothing can produce. It blocks anyway: a guard that permits impossible states fails open. |
| `pending_*` | none | no | An unlinked customer merges exactly as it did before OD-40. |
| any | `revoked`, retained for audit | no | A record that access *used* to exist. Never deleted to permit a merge, never blocks one. |

This is the same predicate as the two partial unique indexes above, so the guard and the
index cannot disagree about which rows are live.

**What an effective link forbids.** A merge involving a customer with one is **refused
whole** — not resolved by moving the link, revoking it, suspending the identity, or leaving
a live link on a tombstoned record (OD-40, DEC-0107). The refusal carries the stable code
`customer_account_link_present` and names which side blocked; it names no account
reference, no address, and no shipment figure. A dedicated merge-with-account
reconciliation workflow — fresh duplicate review, disclosure preview, acknowledgement,
session handling, explicit owner-approved link transition — is a later phase's work and is
**not** part of Phase 10.

---

## 6. Where customer data lives, and what registration may write

Registration writes to **two** new tables and to no existing one:

* `customer_identities` — the account;
* `customer_data_proposals` (+ `customer_data_proposal_fields`) — what the customer says
  about themselves.

It does **not** write `customers`, `customer_addresses`, `consent_events`,
`contact_suppressions`, or anything else canonical. Canonical data changes only when a staff
member approves a proposal, through the existing customer service, inside one transaction,
with the existing audit record (OD-23, OD-28).

This is the single most important structural decision in this document. It means a bug in
the customer-facing code cannot corrupt the CRM: the worst it can do is create a bad
proposal that a person then declines.

**Normalization and duplicate detection are reused, not reimplemented.**
`app.core.normalization` produces the same `email_normalized`, `phone_e164` and
`name_match_key` values for a proposal that the Staff Portal produces for a staff-entered
customer, and `duplicate_service` scores a proposal exactly as it scores an import row.
Reusing them is what makes "the same customer" mean the same thing on both surfaces. What
the customer surface may never do is *report* the result: scores, matches and match counts
are staff-facing only ([`THREAT_MODEL.md`](THREAT_MODEL.md) T-02).

---

## 7. Response schemas

Every Customer Account response model is **standalone**:

* it does not inherit from a staff schema;
* it does not inherit from a Public Tracking schema;
* it does not set `from_attributes`, so an ORM object can never be handed to one;
* every field is assigned explicitly by a service, from an allowlist;
* `extra="forbid"`.

This is the rule Phase 3 already applies to `app/schemas/public_tracking.py`, and the reason
given there applies unchanged: an internal schema gains fields over time, and a model that
inherits one silently starts publishing them.

The allowlists are in [`SHIPMENT_ALLOWLISTS.md`](SHIPMENT_ALLOWLISTS.md) and
[`FIELD_MATRIX.md`](FIELD_MATRIX.md).

---

## 8. Route inventory (proposed, release 1)

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/api/v1/account/register` | none | Generic response always |
| `POST` | `/api/v1/account/verify-email` | token | Single-use, expiring |
| `POST` | `/api/v1/account/verification/resend` | none | Generic response, rate limited |
| `POST` | `/api/v1/account/sign-in` | none | Generic failure text |
| `POST` | `/api/v1/account/sign-out` | identity | Server-side revocation |
| `POST` | `/api/v1/account/password/forgot` | none | Generic response always |
| `POST` | `/api/v1/account/password/reset` | token | Single-use, expiring, revokes sessions |
| `POST` | `/api/v1/account/password/change` | identity | Requires current password |
| `GET` | `/api/v1/account/me` | identity | State + own profile. No shipment data |
| `GET` | `/api/v1/account/profile` | identity, approved | Customer-visible fields only |
| `PATCH` | `/api/v1/account/profile/direct` | identity, approved | Preferred language, operational preferences |
| `POST` | `/api/v1/account/profile/proposals` | identity, approved | Creates a proposal |
| `GET` | `/api/v1/account/profile/proposals` | identity, approved | Own proposals and their state |
| `POST` | `/api/v1/account/consent/marketing` | identity | Append-only; cannot lift suppression |
| `GET` | `/api/v1/account/shipments` | identity, approved | List allowlist |
| `GET` | `/api/v1/account/shipments/{reference}` | identity, approved | Detail allowlist |

Staff-side routes (approval queue, proposal review, suspension, privacy requests) live in
the **Staff Portal** router under new permissions, not here. Their proposed permission names
are in [`DATA_MODEL.md`](DATA_MODEL.md) section 8.

**Every route in this table is a proposal.** None exists.

---

## 9. Cross-surface invariants, to be enforced by test

1. A staff session cookie presented to a Customer Account route authenticates **nothing**.
2. A customer session cookie presented to a staff route authenticates **nothing**, and to a
   Public Tracking route changes nothing.
3. No Customer Account route depends on `app.api.deps` — asserted by walking the route table
   and inspecting the dependency graph, the same technique
   `backend/tests/test_route_permissions.py` already uses for the staff routes.
4. No Customer Account response model is a subclass of a staff or public model — asserted by
   `issubclass` over the module's exported models.
5. The `PublicTrackingResult` field set is still exactly 24 — asserted today by name in
   `backend/tests/test_public_contract_unchanged.py` and by count in
   `backend/tests/test_phase5b_seam_and_contracts.py`. Both must keep passing untouched.
6. A customer identity has no `role` attribute and no permission lookup path.
7. No **effective link** points at a merged or archived customer, under any interleaving
   of a merge and an approval — asserted by a whole-database sweep after every race in
   `backend/tests/test_merge_link_concurrency.py` (OD-40).

These become UAT and automated acceptance criteria in
[`ACCEPTANCE_CRITERIA.md`](ACCEPTANCE_CRITERIA.md).
