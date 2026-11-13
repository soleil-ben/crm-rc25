# Customer Account — phased implementation plan

**Status:** proposed. Nothing in this plan has started, and **Phase 9 must not be started
from this document alone** — the owner starts a phase.

---

## 1. Shape of the plan

Four implementation phases, each one shippable-as-a-branch, each ending green, each with a
completion record. The order is chosen so that **the security boundary exists before there is
anything worth attacking**.

| Phase | Name | Ends with |
|---:|---|---|
| **9** | Customer identity foundation | Identity, sessions, registration, verification, recovery — **no shipment data, no canonical writes** |
| **10** | Staff approval, linking and proposals | Staff queues, approval, linking, proposal review, audit |
| **11** | Authenticated shipment history | List and detail allowlists, ownership enforcement |
| **12** | Customer Account frontend and UAT | Screens, accessibility, human UAT execution |
| *(later)* | Hardening | Optional TOTP (OD-33), and whatever the threat model's residual list has become |

Phases 9–11 are backend-first on purpose: every boundary in
[`THREAT_MODEL.md`](THREAT_MODEL.md) is a server-side property, and a screen built against a
boundary that does not yet hold teaches the wrong habit.

---

## 2. Phase 9 — Customer identity foundation

**Builds:** `customer_identities`, `customer_identity_links` (table and constraints only),
`customer_sessions`, `customer_auth_tokens`, `customer_terms_acknowledgements`,
`customer_notification_preferences`, `customer_data_proposals`,
`customer_data_proposal_fields`; the account router, its own dependencies, its own cookie
realm; register, verify, resend, sign-in, sign-out, forgot/reset/change password, `me`; the
email transport seam with the development capture; the customer rate-limit namespace.

**Does not build:** anything that reads a shipment; any canonical write; any staff screen;
any frontend; any provider; MFA.

**Ends when:** AC-CA-1, AC-CA-2, AC-CA-3, AC-CA-8, AC-CA-9 and the relevant parts of
AC-CA-10 and AC-CA-11 pass, and `alembic check` is green.

**The migration in this phase is the riskiest thing in the whole plan** — eight new tables,
partial unique indexes, and a downgrade that must drop them cleanly. It gets the Phase 7
treatment: a tested downgrade, a populated-database rehearsal on a copy, and no repair
applied to the development database without the owner's word.

## 3. Phase 10 — Staff approval, linking and proposals

**Builds:** the five staff permissions; approval queue and proposal review in the Staff
Portal; approve / reject / link / unlink / suspend / reinstate / deactivate; the history
disclosure preview and its acknowledgement; proposal application through the **existing**
customer service; duplicate review reuse; the audit actions.

**Ends when:** AC-CA-4 and AC-CA-7 pass, the staff UAT cases `CA-APR-*` are executable, and
no automatic merge exists anywhere in the path.

## 4. Phase 11 — Authenticated shipment history

**Builds:** `AccountShipmentListItem`, `AccountShipmentDetail`, the two routes, and the
ownership enforcement in the queries.

**Ends when:** AC-CA-5 and AC-CA-6 pass — including the assertion that
`PublicTrackingResult` is still exactly 24 fields, untouched.

## 5. Phase 12 — Frontend and UAT

**Requires first:** an **accepted** `Design.md` Customer Account section
([`DESIGN_SECTION_PROPOSAL.md`](DESIGN_SECTION_PROPOSAL.md)).

**Builds:** the eleven screens in [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) §7, English only;
mobile-friendly layouts distinct from Public Tracking; the customer-facing copy, reviewed for
wording that does not disclose.

**Ends when:** the 28-case UAT pack has been executed by a human with results recorded, the
accessibility review is done, and AC-CA-12 passes.

---

## 6. What must be true before Phase 9 starts

| | Status |
|---|---|
| OD-23 … OD-39 recorded as owner answers | **Done, this phase** |
| Phase 7 Alembic follow-up complete, `alembic check` green | **Done** |
| Development database at the corrected head | **Done** |
| An accepted `Design.md` section | **Not needed until Phase 12** |
| An email provider | **Not needed until production launch** (OD-34) |
| Approved terms and privacy text | **Not needed until production launch** (OD-37) |

Phase 9 is therefore unblocked, which is exactly why it is first.

---

## 7. Launch blockers, restated as a checklist

None of these is a development task. Each is an owner or reviewer action.

| # | Blocker | Decision |
|---:|---|---|
| 1 | Production email provider selected, with data residency confirmed | OD-34 |
| 2 | Sending domain authenticated (SPF, DKIM, DMARC); bounce and complaint handling defined | OD-34 |
| 3 | Approved terms and privacy text, with version identifiers | OD-37 |
| 4 | Customer-facing English copy reviewed | OD-39 |
| 5 | Customer Account accessibility review performed | OD-19 (no reviewer assigned) |
| 6 | Retention periods, when OD-01 is answered | OD-01, OD-36 |
| 7 | Rate limiting moved to a shared store if more than one worker process runs | DEC-0006 |
| 8 | Secrets in a secret store; `credential_ref` names the entry, never the value | existing gate |

---

## 8. Risks, and what each one would cost

| Risk | Cost if it lands | Reduced by |
|---|---|---|
| The approval queue is slower than customers expect | Support load, and pressure to automate approval — **the one thing OD-24 forbids** | Set the expectation in the UI; measure queue age before, not after, complaints |
| Three schema gaps (display name, legal name, billing address) are decided hastily inside a migration | A column that means two things | Decide them explicitly in Phase 9, in the migration's record |
| The authenticated detail quietly grows past 24 fields | A new disclosure surface nobody reviewed | The field-count test, and this document's table |
| A frontend built before the design section is accepted | Rework, or a design accepted retroactively because it already exists | Phase 12 is gated on acceptance |
| OD-01 stays open indefinitely | Customer data accumulates with no retention answer | Recorded as a launch blocker rather than absorbed |

---

## 9. Appendix — proposed prompt for Phase 9

> **Phase 9 — Customer identity foundation.**
>
> Branch `phase-9-customer-identity-foundation` from the completed Phase 8 HEAD.
>
> Implement the customer identity foundation specified in `docs/customer_account/`, and
> nothing beyond it.
>
> **Build:** the eight tables in `DATA_MODEL.md` §2–§7, with one reversible migration whose
> downgrade is tested rather than asserted; a separate account router at
> `/api/v1/account`, its own dependency module, and its own cookie realm
> (`solaris_account_session`, `solaris_account_csrf`, `X-Account-CSRF-Token`); registration,
> email verification, resend, sign-in, sign-out, forgot/reset/change password, and `me`;
> hashed single-use expiring tokens; the email transport seam with a development capture that
> opens no socket; the customer rate-limit namespace from
> `RATE_LIMITS_AND_ABUSE.md` §2–§3; audit actions per `DATA_MODEL.md` §9.
>
> **Do not build:** any route that reads a shipment; any canonical customer write; any staff
> screen or staff route; any frontend screen; MFA; any email provider; any provider adapter;
> any UniUni or `connected_api` work.
>
> **Hold these invariants:** customer identities are never rows in `users`; no Customer
> Account route depends on `app.api.deps`; no response model inherits from a staff or public
> schema and none sets `from_attributes`; registration writes no canonical table; every
> account-existence response is generic; no audit payload contains a credential, a token or a
> raw address; no test makes an external request; `PublicTrackingResult` stays at exactly 24
> fields.
>
> **Finish with:** `alembic check` green against a database at head; the autogeneration
> exclusion still naming exactly `role_merge_provenance`; ruff clean; the full backend suite
> green; a tested migration round trip; and a Phase 9 completion record in `PROJECT_STATUS.md`
> that states what was measured rather than what was intended.
>
> Do not start Phase 10.

This prompt is a proposal for the owner to issue. **Phase 9 has not been started.**

---

## 10. Appendix — proposed prompt for Phase 12

**Phases 9, 10 and 11 are complete.** The identity foundation, the staff approval and
linking surface, and the authenticated shipment history all exist as backend and staff API
only. There is no Customer Account screen, and no human has executed a Customer Account UAT
case. This prompt is a proposal for the owner to issue.

> **Phase 12 — Customer Account frontend and final UAT preparation.**
>
> Branch `phase-12-customer-account-frontend` from the completed Phase 11 HEAD.
>
> **Before any code:** an **accepted** `Design.md` Customer Account section
> (`DESIGN_SECTION_PROPOSAL.md`). Phase 12 is gated on that acceptance, and a frontend built
> against an unaccepted design is the risk `IMPLEMENTATION_PLAN.md` §8 records.
>
> **Build:** the customer-facing screens in `PRODUCT_SPEC.md` §7 — register, verify, sign in,
> forgot and reset password, account status, my information, my shipments, one shipment —
> plus the **staff** approval queue and registration review screens Phase 10 left without a
> UI; English only (OD-39); mobile-friendly layouts visibly distinct from Public Tracking;
> URL-addressable list state for the two approved filters and paging; the customer-facing
> copy, reviewed for wording that does not disclose.
>
> **Do not build:** public booking; customer-created shipments; customer cancellation; a
> claim-by-reference flow; recipient accounts; company multi-user access; any financial
> display; a linked return-shipment workflow while OD-22 is open; MFA; a production email
> provider; any provider adapter; `connected_api`. Add **no** new backend route without an
> owner instruction: the two shipment routes and the Phase 9 routes are the contract, and a
> screen that needs a field the allowlists do not carry is a documentation change first.
>
> **Hold these invariants:** the list stays 17 fields and the detail 24, both asserted by
> name; `PublicTrackingResult` stays exactly 24 and its tests stay untouched; no Customer
> Account model inherits a staff or public one; no Customer Account route depends on
> `app.api.deps`; ownership stays in the query and **no screen filters for privacy** — a
> screen that hides a row is a courtesy, never a boundary; a refusal still says one sentence
> and never which condition failed; the two surfaces still share no session, no cookie name
> and no CSRF header; every read still re-evaluates authorization, so suspension and link
> revocation still take effect on the next request; no external request from any test.
>
> **Then prepare UAT, and do not execute it.** Re-read the 51-case Customer Account pack
> against the screens that now exist, move each `CA-*` case from `Blocked` to executable or
> record why it is still blocked, add the six existing-pack assertions the impact map has
> been holding since Phase 9, and produce `REVIEW_customer_account_copy.md` as a blank
> review sheet. **Every result, tester, date, evidence, defect and sign-off field stays
> blank.**
>
> **Finish with:** ruff and eslint clean; the full backend suite green with no skips; the
> frontend unit suite and production build green; the complete Playwright suite green
> through the isolated orchestrator, extended to the new screens including an accessibility
> pass; `alembic check` green; the decision and owner registers verified; the RC baseline
> verified with its documented historical drift and no new drift; the development and UAT
> database SHA-256 digests unchanged before and after; `data/e2e/` clean; and a Phase 12
> completion record in `PROJECT_STATUS.md` that states what was measured rather than what
> was intended.
>
> Do not execute human UAT. Do not deploy and do not push.

**What Phase 12 cannot close.** OD-34, OD-37, OD-39 and OD-19 are owner and reviewer
actions, and release 1 is not done until a human has executed the pack with results
recorded — whatever the test suite says.
