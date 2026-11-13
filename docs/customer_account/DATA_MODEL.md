# Customer Account — proposed relational model and data dictionary

**Status:** proposed. **No migration is written by this phase, and none of these tables
exists.** Column types follow the conventions already in use: SQLite via SQLAlchemy 2.0,
naive UTC `DateTime`, `String(n)` with explicit lengths, integer surrogate keys, and named
constraints so batch migrations work (`render_as_batch`).

---

## 1. Shape at a glance

```
customer_identities ──< customer_identity_links >── customers        (existing)
        │
        ├──< customer_sessions
        ├──< customer_auth_tokens          (verification / reset, hashed)
        ├──< customer_terms_acknowledgements
        ├──< customer_notification_preferences
        └──< customer_data_proposals ──< customer_data_proposal_fields
                      │
                      └── reviewed_by_user_id ──> users              (existing)
```

Existing tables are **read** by this surface and **written only** through existing services
when a staff member approves something: `customers`, `customer_addresses`, `consent_events`,
`contact_suppressions`, `shipments`, `shipment_packages`, `shipment_events`, `audit_events`.

No existing table gains a column that points *at* an identity. The link lives in its own
table, in one direction only, so a customer row never depends on the account feature.

---

## 2. `customer_identities`

The account. One row per registered email address.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | Internal; never serialized |
| `public_id` | String(20) | no, unique | Customer-facing identity reference for support |
| `email_entered` | String(320) | no | As typed |
| `email_normalized` | String(320) | no, **unique** | `app.core.normalization`; the login key and the uniqueness key |
| `password_hash` | String(255) | no | Argon2, same library and rehash-on-login policy as staff (DEC-0003) |
| `status` | String(30) | no | `pending_verification` \| `pending_approval` \| `active` \| `rejected` \| `suspended` \| `deactivated` |
| `email_verified_at` | DateTime | yes | Proof of mailbox control. Not approval |
| `approved_at` | DateTime | yes | |
| `approved_by_user_id` | Integer FK `users.id` | yes | `ON DELETE SET NULL` |
| `rejected_at` / `rejected_by_user_id` | DateTime / Integer FK | yes | |
| `status_reason_code` | String(40) | yes | Reason **code**, never free prose about the person |
| `suspended_at` / `suspended_by_user_id` | DateTime / Integer FK | yes | |
| `deactivated_at` / `deactivated_by_user_id` | DateTime / Integer FK | yes | |
| `failed_sign_in_count` | Integer | no, default 0 | Abuse control |
| `locked_until` | DateTime | yes | Abuse control |
| `last_sign_in_at` | DateTime | yes | |
| `preferred_language` | String(8) | no, default `en` | Release 1 serves English only (OD-39) |
| `created_at` / `updated_at` | DateTime | no | `TimestampMixin` |

**Not in this table, deliberately:** no `role`, no permission column, no `customer_id`, no
copy of the customer's name, address or phone. The account holds credentials and state; the
customer's data lives on the customer.

---

## 3. `customer_identity_links`

The link, in its own table — the decision OD-25 asks for.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | Integer FK `customer_identities.id` | no | `ON DELETE CASCADE` |
| `customer_id` | Integer FK `customers.id` | no | `ON DELETE RESTRICT` — a linked customer is not deleted out from under an account |
| `link_role` | String(20) | no, default `owner` | Release 1 writes only `owner`. `member`, `admin` are where company access lands later (OD-26) |
| `status` | String(20) | no | `active` \| `revoked` |
| `linked_at` | DateTime | no | |
| `linked_by_user_id` | Integer FK `users.id` | yes | The approving staff member |
| `revoked_at` / `revoked_by_user_id` / `revoke_reason_code` | DateTime / Integer / String(40) | yes | |

**Constraints that encode release 1, and only release 1:**

* unique index on `identity_id` where `status = 'active'` — one customer per identity;
* unique index on `customer_id` where `status = 'active'` — one active identity per customer;
* both **partial** (SQLite supports partial indexes), so revoked history accumulates freely.

Company access later is: drop the second index, permit `link_role in ('owner','member')`,
add an invitation table that writes rows here. **No identity ownership is rebuilt**, no
ownership check changes, and `shipments` never learns the account exists.

---

## 4. `customer_sessions`

Deliberately a separate table from `user_sessions`, with the same proven shape.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | Integer FK | no | `ON DELETE CASCADE` |
| `session_token_hash` | String(64) | no, unique | SHA-256 digest. **The token itself is never stored** |
| `csrf_token_hash` | String(64) | no | Digest, bound to this session row (DEC-0005) |
| `created_at` / `last_seen_at` / `expires_at` | DateTime | no | `expires_at` indexed |
| `revoked_at` | DateTime | yes | Server-side revocation, the reason a session table exists at all (DEC-0004) |
| `ip_address` | String(64) | yes | Direct peer only (DEC-0007) |
| `user_agent` | String(255) | yes | Truncated |

**No role, no permission snapshot, and no copy of the linked customer id.** Authorization
re-reads the identity and its active link on every request, so a suspension or a revoked
link takes effect on the **next request**, not the next sign-in — the property Phase 7
established for staff roles, kept here on purpose.

---

## 5. `customer_auth_tokens`

Email verification and password reset. One table, one shape, one set of rules.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | Integer FK | no | `ON DELETE CASCADE` |
| `purpose` | String(30) | no | `email_verification` \| `password_reset` |
| `token_hash` | String(64) | no, unique | SHA-256 of a 32-byte random token. **Plaintext is never stored and never logged** |
| `issued_at` | DateTime | no | |
| `expires_at` | DateTime | no, indexed | Short: hours, not days |
| `consumed_at` | DateTime | yes | Single use. A consumed token is refused, not re-honoured |
| `invalidated_at` | DateTime | yes | Superseded by a newer token, or by a password change |
| `issued_to_email_normalized` | String(320) | no | The address it was sent to, so a later address change cannot be used to redirect an outstanding token |
| `request_ip` | String(64) | yes | Abuse analysis |

Rules: expiry is enforced server-side; consumption is atomic (`UPDATE … WHERE consumed_at
IS NULL` and check the row count) so two simultaneous redemptions cannot both succeed;
issuing a new token of a purpose invalidates the outstanding ones of that purpose; a
successful password reset revokes **every** `customer_sessions` row for that identity.

---

## 6. `customer_data_proposals` and `customer_data_proposal_fields`

What the customer says about themselves, before a person agrees.

**`customer_data_proposals`**

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | Integer FK | no | |
| `customer_id` | Integer FK `customers.id` | yes | Null for a registration proposal — there is no customer yet, and that is the point |
| `kind` | String(30) | no | `registration` \| `profile_update` |
| `status` | String(20) | no | `pending` \| `approved` \| `rejected` \| `superseded` \| `withdrawn` |
| `submitted_at` | DateTime | no | |
| `reviewed_at` / `reviewed_by_user_id` | DateTime / Integer FK | yes | |
| `decision_reason_code` | String(40) | yes | Code, not prose |
| `duplicate_review_outcome` | String(30) | yes | Staff-facing result of the existing duplicate review; **never serialized to a customer** |
| `applied_audit_event_id` | Integer FK `audit_events.id` | yes | Ties the canonical change to its audit row |

**`customer_data_proposal_fields`**

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `proposal_id` | Integer FK | no | `ON DELETE CASCADE` |
| `field_key` | String(60) | no | From the allowlist in [`FIELD_MATRIX.md`](FIELD_MATRIX.md). A key outside it is refused at the API boundary |
| `proposed_value` | Text | yes | As submitted |
| `proposed_value_normalized` | Text | yes | From the existing normalization service |
| `current_value_at_submission` | Text | yes | What the canonical record held when it was submitted — the basis for detecting drift at approval |
| `applied` | Boolean | no, default false | Per field, because an approver may accept some fields and decline others |

Unique index on `(proposal_id, field_key)`.

---

## 7. `customer_terms_acknowledgements` and `customer_notification_preferences`

**`customer_terms_acknowledgements`** — append-only (OD-37).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | Integer FK | no | |
| `document_kind` | String(30) | no | `terms` \| `privacy` |
| `document_version` | String(40) | no | The version identifier presented |
| `presented_language` | String(8) | no | What the person actually read |
| `acknowledged_at` | DateTime | no | |
| `request_ip` | String(64) | yes | |

No update path and no delete path. A new acknowledgement is a new row.

**`customer_notification_preferences`** — operational preferences only.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | Integer FK | no | |
| `channel` | String(20) | no | `email` in release 1 |
| `topic` | String(40) | no | e.g. `shipment_milestones`, `delivery_outcome`, `account_security` |
| `enabled` | Boolean | no | |
| `updated_at` | DateTime | no | |

Marketing consent is **not** here. It is a `consent_events` row, append-only, written
through the existing consent service, and a preference row can neither create nor weaken
one — nor lift a `contact_suppressions` row (OD-27, OD-38).

---

## 8. Staff-side permissions this surface needs

New permission names, added to the existing role → permission map, **Operations and Admin**
(OD-24). Recorded here as a proposal; the register's open question about final Operations
permissions (DEC-0082) is untouched by them.

| Permission | Grants |
|---|---|
| `customer_account:read` | See identities, their states and their proposals |
| `customer_account:approve` | Approve or reject an identity, and make or revoke a link |
| `customer_account:suspend` | Suspend, reinstate or deactivate an identity |
| `customer_data_proposal:review` | Approve or decline proposed canonical changes |
| `customer_account:privacy_request` | Execute an export, correction or deletion request (OD-35) |

No permission on this list is given to Marketing or to the read-only manager in release 1.
The customer surface itself holds **no permission at all** — see
[`IDENTITY_AND_AUTHORIZATION.md`](IDENTITY_AND_AUTHORIZATION.md) §3.

---

## 9. Audit (OD-24, OD-28, OD-35)

Every state change writes an `audit_events` row through the existing audit service, with
`entity_type = 'customer_identity'` or `'customer_data_proposal'`.

**What a payload may contain:** the identity `public_id`, the customer `public_id`, the
field keys affected, reason codes, counts, and the actor.

**What it may never contain:** a password, a password hash, a token, a token hash, a session
identifier, a raw email or phone in a security-event payload, a duplicate score shown to a
customer, or an unbounded copy of the submitted payload.

Actions: `customer_account.register`, `.verify_email`, `.sign_in_failed`, `.approve`,
`.reject`, `.link`, `.unlink`, `.suspend`, `.reinstate`, `.deactivate`,
`.password_reset_requested`, `.password_reset_completed`, `customer_data_proposal.submit`,
`.approve`, `.decline`, `.supersede`, `customer_privacy_request.*`.

---

## 10. Retention (OD-35, OD-36)

| Data | Release 1 | Depends on |
|---|---|---|
| Verification and reset tokens | Expire in hours; consumed or expired rows are purgeable immediately. **This does not wait for OD-01** | nothing |
| Customer sessions | Expire on the existing idle/absolute policy; revoked rows purgeable | nothing |
| Identity rows, proposals, acknowledgements, consent history | **No deletion schedule is implemented.** Aligned with OD-01 when OD-01 is answered | **OD-01, open** |
| Canonical customer and shipment data | Unchanged by this phase | OD-01 |

Proposed retention categories, for the owner and legal review to rule on separately:
*credential material*, *account lifecycle records*, *consent and acknowledgement evidence*,
*security event logs*, *canonical customer data*. No period is asserted here, and **no
compliance claim is made** — legal review determines the applicable response period and
retention exceptions (OD-35).

---

## 11. Migration and `alembic check` (DEC-0089)

Whenever these tables are built:

* one migration per implementation phase, reversible, with a downgrade that is tested rather
  than asserted — the standard this project set in Phase 7;
* **`alembic check` green at the end of every phase**, reached by the models and the schema
  agreeing;
* the autogeneration exclusion stays at exactly one name. No Customer Account table is added
  to it, and `role_merge_provenance` is not dropped, mapped, renamed or repurposed by any
  migration written here;
* the three schema gaps in [`FIELD_MATRIX.md`](FIELD_MATRIX.md) §6 — display name, legal
  name, billing address role — are resolved **in that migration phase**, not assumed now.
