# Customer Account — acceptance criteria

**Status:** criteria for the *implementation* phases. Nothing here passes today, because
nothing is built. Each criterion is written so that its failure is observable.

Legend: **A** = automated test, **H** = human UAT, **R** = review of the code or the record.

---

## AC-CA-1 — Surface separation

| # | Criterion | How |
|---|---|---|
| 1.1 | A staff session cookie presented to any Customer Account route authenticates nothing | A |
| 1.2 | A customer session cookie presented to any staff route authenticates nothing, and returns 401 rather than 403 | A |
| 1.3 | Customer cookie names, CSRF header name and session table differ from the staff realm, asserted by literal name | A |
| 1.4 | No Customer Account route resolves any dependency from `app.api.deps` | A |
| 1.5 | No Customer Account response model subclasses a staff or public model, and none sets `from_attributes` | A |
| 1.6 | Customer rate-limit buckets are in their own namespace: a customer-side flood consumes no staff or public allowance | A |
| 1.7 | A customer identity has no role, no permission set and no path to one | A, R |

## AC-CA-2 — Registration and enumeration resistance

| # | Criterion | How |
|---|---|---|
| 2.1 | Registration with an unknown address and with an already-registered address return identical status, body and headers | A |
| 2.2 | Registration never writes `customers`, `customer_addresses` or `consent_events` | A, R |
| 2.3 | Registration creates exactly one pending identity and one pending proposal | A |
| 2.4 | Registration is refused without a terms/privacy acknowledgement, and the acknowledgement records version, language and timestamp | A |
| 2.5 | Marketing consent is unchecked by default and absent unless explicitly chosen | A, H |
| 2.6 | No response on this surface contains a duplicate score, match, or count of matching customers | A |
| 2.7 | Forgot-password returns the same response for known and unknown addresses | A |

## AC-CA-3 — Verification, tokens and recovery

| # | Criterion | How |
|---|---|---|
| 3.1 | Tokens are stored as digests; the plaintext appears in no column, log or audit row | A |
| 3.2 | A consumed token is refused; concurrent redemption yields exactly one success | A |
| 3.3 | An expired token is refused, and expiry is enforced server-side | A |
| 3.4 | Issuing a new token invalidates outstanding tokens of the same purpose | A |
| 3.5 | A completed password reset revokes every session for that identity | A |
| 3.6 | Invalid, expired, consumed and unknown tokens produce one identical response | A |

## AC-CA-4 — Approval, linking and canonical safety

| # | Criterion | How |
|---|---|---|
| 4.1 | An identity reaches `active` only through an explicit staff action | A, H |
| 4.2 | Approval is refused until the history-disclosure preview is acknowledged | A, H |
| 4.3 | The preview figures — count, oldest, newest, cancelled included, rebooked included — are correct against the data, and are stored in the audit record | A |
| 4.4 | Approval is transactional: a failure leaves no partial state | A |
| 4.5 | Approval is idempotent: the same approval twice produces one canonical change and one audit record | A |
| 4.6 | Approval is refused when the candidate customer already has an active link | A |
| 4.7 | No approval path merges two canonical customers; duplicates go to the existing review | A, R |
| 4.8 | A field whose canonical value changed since submission is refused, not overwritten | A |
| 4.9 | Canonical writes occur only through the existing customer service, with the existing audit | R, A |

## AC-CA-5 — Ownership of shipment data

| # | Criterion | How |
|---|---|---|
| 5.1 | A pending or suspended account reaches no shipment data at all | A, H |
| 5.2 | The list contains only shipments whose `customer_id` is the linked customer | A |
| 5.3 | Another customer's reference returns the generic not-found body, identical to an unknown reference | A |
| 5.4 | Ownership is enforced in the query, not by filtering loaded rows, and not in the frontend | R, A |
| 5.5 | Cancelled and rebooked shipments appear with safe states | A, H |
| 5.6 | Drafts and demo records do not appear | A |
| 5.7 | An account with no qualifying shipments sees an empty list and a plain sentence | A, H |
| 5.8 | **(OD-41)** The reference filter matches exactly; a prefix, a fragment, a package reference and a malformed value all return an empty list | A |
| 5.9 | **(OD-41)** An unknown reference and another customer's reference return **identical** empty responses — same status, body and headers | A, H |
| 5.10 | **(OD-41)** The route-group filter accepts only the existing vocabulary; anything else is refused with this surface's validation body, not the framework's | A |
| 5.11 | **(OD-41)** A malformed filter cannot bypass the account read limiter | A |
| 5.12 | **(OD-41)** All four filters compose, conjunctively, with the ownership clause first; no filter widens a result set or crosses a customer boundary | A |

## AC-CA-6 — Field and response discipline

| # | Criterion | How |
|---|---|---|
| 6.1 | `AccountShipmentDetail` has exactly the 24 declared fields, by name | A |
| 6.2 | `AccountShipmentListItem` has exactly the 17 declared fields, by name | A |
| 6.3 | `PublicTrackingResult` still has exactly 24 fields — the existing test, unchanged | A |
| 6.4 | Every **Never** field in `FIELD_MATRIX.md` §3.4 is absent from every response, asserted against a populated record | A |
| 6.5 | No response contains any financial column or `payment_state`, asserted over the serialized body | A |
| 6.6 | A direct-edit naming a proposal field is refused; a proposal naming a never-field is refused | A |

## AC-CA-7 — Consent, suppression and preferences

| # | Criterion | How |
|---|---|---|
| 7.1 | Consent changes append; nothing is updated in place or deleted | A |
| 7.2 | A consent grant on a suppressed address leaves the suppression in force, sends no marketing, and discloses nothing; account email is still sent (DEC-0139) | A |
| 7.3 | A customer cannot read, create or release a suppression | A |
| 7.4 | Withdrawal always takes effect immediately, with no staff approval | A |
| 7.5 | Operational preferences cannot switch marketing on, and cannot switch off account-security messages | A |

## AC-CA-8 — Sessions and CSRF

| # | Criterion | How |
|---|---|---|
| 8.1 | Every non-safe route rejects a request without the customer CSRF header | A |
| 8.2 | A staff CSRF token does not satisfy a customer route | A |
| 8.3 | Authentication rotates the session token | A |
| 8.4 | Sign-out revokes server-side: the captured cookie value stops working | A, H |
| 8.5 | Suspension takes effect on the next request, not the next sign-in | A |
| 8.6 | Authenticated responses carry `Cache-Control: no-store` | A |
| 8.7 | A production configuration without `Secure` cookies fails at startup | A |

## AC-CA-9 — Email

| # | Criterion | How |
|---|---|---|
| 9.1 | No test opens a socket on the mail path | A |
| 9.2 | A registration for an existing address produces at most one notice per window | A |
| 9.3 | No captured message contains a password or hash; the only token is the single-use link | A |
| 9.4 | No HTTP route returns captured mail | A, R |
| 9.5 | Selecting a production transport without configuration fails at startup | A |

## AC-CA-10 — Audit

| # | Criterion | How |
|---|---|---|
| 10.1 | Every state transition in `STATE_MACHINES.md` writes an audit row | A |
| 10.2 | No audit payload contains a password, hash, token, digest or session id | A |
| 10.3 | Security-event payloads carry a hashed address key, not a raw address | A |
| 10.4 | Approval audit rows carry actor, identity, customer, preview figures and reason code | A |

## AC-CA-11 — Schema and migrations

| # | Criterion | How |
|---|---|---|
| 11.1 | `alembic check` is green at the end of every implementation phase | A |
| 11.2 | The autogeneration exclusion still names exactly `role_merge_provenance` | A |
| 11.3 | No Customer Account migration drops, renames, maps or repurposes that table | R, A |
| 11.4 | Each migration's downgrade is tested, not asserted | A |

## AC-CA-12 — Language and launch

| # | Criterion | How |
|---|---|---|
| 12.1 | The Customer Account ships English-only; no Vietnamese string is reachable | A, H |
| 12.2 | Existing Vietnamese Public Tracking is unchanged | A |
| 12.3 | Production registration is unreachable while no email provider is configured | A, R |
| 12.4 | Production registration is unreachable while no approved terms/privacy version exists | A, R |

---

## What "done" means for release 1

All twelve groups pass, **and**:

* the Customer Account UAT pack has been executed by a human with results recorded;
* OD-34 and OD-37 are satisfied by owner action, not by a default;
* `docs/OPERATIONS.md` section 6 carries the new production gates;
* the frontend has an accepted `Design.md` Customer Account section.

Any one of those missing means release 1 is not done, whatever the test suite says.
