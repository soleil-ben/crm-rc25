# Customer Account — email-delivery abstraction and development capture

**Status:** proposed. **Authority:** OD-34, OD-37, OD-38, OD-39.

**No provider is selected, no provider is integrated, and nothing in this phase sends
email.** This document describes the seam and the development implementation behind it.

---

## 1. The seam

One interface, three implementations, chosen by configuration. The application never names a
provider.

```python
class EmailTransport(Protocol):
    def send(self, message: OutboundEmail) -> EmailSendResult: ...
```

| Implementation | Where | Behaviour |
|---|---|---|
| `CaptureEmailTransport` | development, UAT | Writes the message to a local capture. **Opens no socket** |
| `NullEmailTransport` | automated tests by default | Records that a send was requested; produces nothing |
| *(a production transport)* | **not written** | Blocked until the owner selects a provider (OD-34) |

`OutboundEmail` carries a recipient, a **template key**, a language, and a bounded parameter
map — never a rendered body assembled by a caller, and never raw HTML from a request. The
same discipline as the existing public update templates: the catalogue is in the repository
and the caller names a key.

This is the same shape Phase 4A used for provider integration, and it exists for the same
reason: a seam with nothing behind it is honest, and a seam that *implies* something behind
it is not. `integration_health` reports `not_configured` for providers; email reports the
same for delivery.

---

## 2. Development capture

| Property | Decision |
|---|---|
| Destination | A local capture — a directory of `.eml`-style files and an in-memory list the test suite can read |
| Location | Under the existing gitignored development data directory. **Never committed** |
| Contents | Recipient, subject, template key, language, rendered body, timestamp |
| Retention | Cleared by the UAT reset script, like the rest of the development environment |
| Access | Local filesystem only. **No HTTP endpoint exposes captured mail** — that would be a way to read anybody's verification link |
| Tokens | Present in the captured body, because the message contains the link. This is precisely why the capture never ships and never gets an endpoint |

**Fixture tests make no external request.** The default transport in tests is the null one;
a test that wants to assert on a message opts into the capture explicitly. The existing "no
external provider request" baseline invariant extends to the mail path
(`scripts/verify_rc_baseline.py`).

---

## 3. Message catalogue (release 1)

English only (OD-39). Every message is a template key in the repository, reviewed as copy.

| Key | Sent when | Contains |
|---|---|---|
| `account.verify_email` | Registration, resend | A single-use link, its expiry, and what to do if it was not you |
| `account.registration_attempt_notice` | Registration for an **already registered** address | That an attempt was made; a reset link; **no account details** |
| `account.password_reset` | Reset requested | A single-use link and its expiry |
| `account.password_changed` | Password changed or reset completed | Notice only. No link, no credentials |
| `account.approved` | Staff approval | That the account is active |
| `account.rejected` | Staff rejection | Neutral wording. No reason that describes another record |
| `account.suspended` | Staff suspension | Neutral wording |

Rules for every message:

* **No credential, no password, no token except the one single-use link the message exists
  to deliver.**
* **No customer data beyond what the recipient already provided** — no shipment list, no
  linked-customer name, no history count.
* Nothing that confirms whether a *different* address exists.
* Plain text and a minimal HTML part; no remote images, no tracking pixel, no third-party
  asset.

Operational shipment notifications are governed by the notification preferences in
[`FIELD_MATRIX.md`](FIELD_MATRIX.md) §4 and are **not** in release 1's message set beyond
the account messages above; adding one is a decision with its own record.

---

## 4. Suppression and consent at send time

Before any send:

1. A `contact_suppressions` row for the address **stops the send**, with no exception, and
   the customer is told nothing about it (OD-27, T-08).
2. Marketing messages additionally require an explicit, unwithdrawn consent — and there are
   **no marketing messages in this set**.
3. Account-security messages (verification, reset, password changed) are operational and
   necessary; a preference cannot switch them off.

Consent and suppression are read through the **existing** services, not re-implemented.

---

## 5. Production launch blockers (OD-34)

Production registration **cannot launch** until all of the following are true. Each is a gate
in `docs/OPERATIONS.md` section 6, not a task in a sprint.

| # | Blocker | Owner action |
|---|---|---|
| 1 | A provider is selected | Owner decision, using **verified** provider documentation |
| 2 | Data-residency requirements confirmed | Where messages and logs are processed and stored |
| 3 | Sending domain authenticated | SPF, DKIM, DMARC on the real sending domain |
| 4 | Bounce and complaint handling defined | What happens to a hard bounce; how a complaint creates a suppression |
| 5 | Credentials in a secret store | `credential_ref` names the entry, never the value — the existing integration rule |
| 6 | Approved legal text and version identifiers | Terms and privacy, with versions to record (OD-37) |
| 7 | Reviewed message copy | English for release 1; Vietnamese only after a qualified reviewer approves all four categories (OD-39) |

**No provider name, pricing, quota or API shape is asserted anywhere in this phase.** Any
such figure would have to come from documentation nobody has verified, and an unverified
figure in a specification becomes a decision by accident.

---

## 6. Test obligations

1. The default test transport opens no socket; a socket guard fails the suite if the mail
   path attempts one.
2. Registration for an existing address produces **at most one** notice per window and the
   same generic HTTP response as any other registration.
3. A suppressed address receives its account email -- verification, the registration-attempt
   notice, reset, and the approval or rejection notice -- and no marketing; the response says
   nothing about the suppression (DEC-0139, superseding "receives nothing"). Shipment and
   other operational email, when built, is not blocked either, and no module that sends
   email reads `contact_suppressions` (DEC-0143).
4. No captured message contains a password or a password hash; the only token present is the
   single-use link the message exists to carry.
5. No HTTP route returns captured mail.
6. Selecting the production transport without configuration **fails at startup**, loudly,
   rather than silently discarding messages.
