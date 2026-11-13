# Customer Account — state machines

**Status:** requirements only. Every transition below names its actor, its guard, its audit
action and its customer-visible message. A transition not listed does not exist.

A rule that holds across all of them: **the customer-visible message never reveals more than
the customer already knows.** Several distinct internal outcomes deliberately share one
message, and where they do it is marked *generic*.

---

## 1. Identity lifecycle

```
                    register
                       │
                       ▼
            ┌──────────────────────┐
            │ pending_verification │──── token expires ──┐
            └──────────┬───────────┘                     │ (stays; a new
                 verify token                            │  token may be
                       │                                 │  requested)
                       ▼                                 │
            ┌──────────────────────┐ ◄───────────────────┘
            │  pending_approval    │
            └───┬──────────────┬───┘
     staff approve          staff reject
                │              │
                ▼              ▼
          ┌──────────┐   ┌──────────┐
          │  active  │   │ rejected │ (terminal unless staff reinstate)
          └────┬─────┘   └──────────┘
               │
   ┌───────────┼────────────┐
   │           │            │
staff       staff        customer or staff
suspend   deactivate     deactivate (staff-executed, OD-35)
   │           │            │
   ▼           ▼            ▼
┌───────────┐ ┌─────────────────────┐
│ suspended │ │    deactivated      │
└─────┬─────┘ └─────────────────────┘
      │ staff reinstate
      └──────────► active
```

| # | From → To | Actor | Guard | Audit action | Customer sees |
|---:|---|---|---|---|---|
| 1 | — → `pending_verification` | customer | Registration accepted, terms acknowledged, rate limit passed | `customer_account.register` | *generic*: "If that address can be registered, we have sent a message to it." |
| 2 | `pending_verification` → `pending_approval` | customer | Token valid, unconsumed, unexpired, matches the issued address | `customer_account.verify_email` | "Email confirmed. Your account is waiting for review." |
| 3 | `pending_verification` → `pending_verification` | customer | Resend requested; previous tokens invalidated; rate limit passed | `customer_account.verification_resent` | *generic*, identical to #1 |
| 4 | `pending_approval` → `active` | Operations or Admin | An explicit link to exactly one canonical customer; disclosure preview acknowledged; no active link exists for that customer | `customer_account.approve` + `.link` | "Your account is active." |
| 5 | `pending_approval` → `rejected` | Operations or Admin | Reason code recorded | `customer_account.reject` | Neutral: the account cannot be used. No reason that describes another record |
| 6 | `active` → `suspended` | Operations or Admin | Reason code | `customer_account.suspend` | Sign-in refused with the **same** generic failure text as a wrong password |
| 7 | `suspended` → `active` | Operations or Admin | Reason code | `customer_account.reinstate` | Sign-in works again |
| 8 | `active`/`suspended`/`pending_*` → `deactivated` | Admin (DEC-0126), on a customer request or a privacy request | Reason code; every session revoked; every token invalidated; the link is kept and no longer blocks a customer merge (DEC-0134). A later link-existing approval of a new account may end it (`revoked`, `taken_over_by_new_account`, DEC-0140) | `customer_account.deactivate` | Sign-in refused, generic |
| 9 | `rejected` → `pending_approval` | Admin | Explicit reinstatement of a rejected application | `customer_account.reinstate` | As #2 |

**Invariants**

* `active` **and** an `active` link are both required before any shipment data is served.
* Suspension and deactivation take effect on the **next request**, because authorization
  re-reads the identity every time and sessions hold no cached grant.
* No transition is automatic. No timer, no rule, no bulk action (OD-24).
* No transition writes canonical customer data. Only proposal approval does.

---

## 2. Registration, in sequence

| Step | What happens | What the caller is told |
|---|---|---|
| 1 | Request arrives | — |
| 2 | Rate limits checked (per IP, per submitted address) | On refusal: generic throttle response with `Retry-After` |
| 3 | Payload validated against the registration allowlist | Field-level validation errors only for **format**, never for existence |
| 4 | Terms and privacy acknowledgement present, version recorded | Refused if absent (OD-37) |
| 5 | Marketing consent recorded as submitted — explicitly, unchecked by default | — |
| 6 | If the address is already registered: **nothing is created**, and a notification may be sent to the existing address instead | *generic*, identical |
| 7 | Otherwise: identity created `pending_verification`, proposal created `pending` | *generic*, identical |
| 8 | Verification token issued, hashed, stored; plaintext sent to the address only | *generic*, identical |

Steps 6 and 7 produce **byte-identical responses** and are engineered to have comparable
latency (see [`THREAT_MODEL.md`](THREAT_MODEL.md) T-02).

A registration proposal is **never** matched, merged or linked automatically, even on an
exact email match (OD-23).

---

## 3. Approval (staff)

```
pending_approval ──► [approver opens the review]
                         │
                         ├─ sees: proposed vs current values, normalized values,
                         │        duplicate implications, affected account, actor
                         ├─ sees: history disclosure preview (count, oldest, newest,
                         │        cancelled included?, rebooked included?)
                         ├─ acknowledges the preview explicitly
                         │
            ┌────────────┴────────────┐
       approve + link            reject
            │                        │
            ▼                        ▼
   one transaction:              rejected
   • identity → active           reason code recorded
   • link row → active
   • proposal fields applied
     through the customer service
   • audit rows written
```

| Property | Requirement |
|---|---|
| **Transactional** | Identity state, link, canonical writes and audit rows commit together or not at all |
| **Idempotent** | Re-submitting the same approval produces one canonical change and one audit record. A second attempt on an already-active identity is a no-op that reports success, not a second write |
| **No automatic merge** | An exact or probable duplicate goes into the **existing** review process. Approval never merges two customer records as a side effect (OD-28) |
| **Drift-safe** | If a canonical value changed since submission, the field is **refused, not overwritten**; the approver sees the drift and decides again |
| **Non-disclosing** | Duplicate scores, candidate customers and match counts are staff-facing only |
| **Cardinality-safe** | Refused if the candidate customer already has an active link (OD-25) |

---

## 4. Proposal lifecycle (profile updates)

```
  submit ──► pending ──┬── approve ──► approved   (fields applied, per field)
                       ├── decline ──► rejected   (reason code; nothing applied)
                       ├── customer withdraws ──► withdrawn
                       └── newer proposal for the same field ──► superseded
```

| Rule | |
|---|---|
| A pending proposal does not change anything a customer or staff member sees as canonical | |
| An approver may apply some fields and decline others; `applied` is per field | |
| Superseding is automatic **within the customer's own submissions only** — a newer value for the same field replaces the older pending one. Nothing about canonical data is automatic | |
| Direct fields (preferred language, operational notification preferences) never create a proposal | |
| A withdrawn or rejected proposal is retained as history, not deleted | |

---

## 5. Email verification and password reset tokens

```
issue ──► outstanding ──┬── redeemed (single use, atomic) ──► consumed
                        ├── expiry reached ──────────────► expired
                        ├── newer token of same purpose ─► invalidated
                        └── password changed ────────────► invalidated
```

| Rule | |
|---|---|
| Stored as a SHA-256 digest. The plaintext exists in the outbound message and nowhere else — not in the database, not in a log, not in an audit payload | |
| Single use, enforced by a conditional update, so two simultaneous redemptions cannot both succeed | |
| Expiry in hours, enforced server-side (OD-36) | |
| A completed password reset revokes **every** session for that identity | |
| An invalid, expired, consumed or unknown token produces **one** generic response | |
| A reset request for an unknown address produces the same response as one for a known address | |

---

## 6. Recovery, suspension and deactivation

| Flow | Actor | Notes |
|---|---|---|
| **Forgot password** | customer | Generic response always. Token rules as §5 |
| **Change password** | customer | Requires the current password; revokes other sessions; does not require staff approval |
| **Change login email** | customer → staff | A **proposal** (it is identity-bearing). The new address must be verified, and the account keeps the old address until both verification and approval have happened |
| **Suspension** | Operations or Admin | Immediate on the next request. Sign-in refused with the standard generic text |
| **Deactivation** | Admin only (DEC-0126) | Routed with a bounded reason code and audit (DEC-0131). Revokes sessions and invalidates tokens; the link row is kept and does not block a merge (DEC-0134); a staff approval of a new account for the same customer ends it (DEC-0140). Not a deletion: no self-service hard delete exists (OD-35) |
| **Privacy request** (export, correction, deletion) | staff-executed | Audited, with a reason code. **No SLA is asserted and no compliance claim is made**; legal review determines the applicable response period and retention exceptions (OD-35) |

---

## 7. Sign-in

| Outcome | Response |
|---|---|
| Correct credentials, identity `active` | Session issued |
| Correct credentials, identity `pending_approval` | Session issued; **no shipment data reachable** |
| Correct credentials, identity `pending_verification` | Refused, *generic* |
| Correct credentials, identity `suspended`, `rejected` or `deactivated` | Refused, *generic* |
| Wrong password | Refused, *generic* |
| Unknown address | Refused, *generic*, after work comparable to a real verification |
| Rate limit exceeded | Throttle response with `Retry-After` |

One failure message covers every refusal above. The distinctions matter to the server and
to the audit log; none of them is a sentence the customer reads.
