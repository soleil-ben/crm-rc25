# Decision register — what the owner must decide, and in what order

**Date:** 2026-10-11
**Audited against:** commit `0b772e0` on `chore/cleanup-xplat-deps-deprecations` (the RC-UAT-4 re-freeze candidate)
**Scope:** analysis only. No feature code, no schema, no behaviour was changed to produce this document.
**Sources:** `docs/OWNER_DECISIONS.json` (the authority for OD-01 … OD-41), `docs/DECISIONS.md`, `docs/customer_account/*`, `docs/INTEGRATIONS.md`, `docs/RETURNS_REQUIREMENT_MATRIX.md`, `docs/OPERATIONS.md` §6, `docs/DEPLOYMENT.md` §8, `PROJECT_STATUS.md`, and the code under `backend/app` and `frontend/src`, read on 2026-10-11.

This register does **not** replace `docs/OWNER_DECISIONS.md`. That file records each decision neutrally and never recommends. This one ranks them, recommends, and says what each one is waiting on, so the owner can answer them in a useful order. Nothing here is written into `owner_answer`; a recommendation is not an answer.

---

## 1. How to read this

Each item carries:

| Field | Meaning |
|---|---|
| **Class** | **UAT blocker** — a human UAT case or review sheet cannot be executed or signed without it. **Production blocker** — the application must not go live without it; the code may even refuse to start. **Post-launch** — can be answered after the first production release without loss. |
| **Priority** | **P1** decide this month; it gates the critical path. **P2** decide before the production go/no-go. **P3** decide when convenient. |
| **Cost to answer** | How much of the owner's time the answer needs: *minutes* (confirm a default), *hours* (choose between options), *days* (external party, legal, vendor, procurement). |
| **Dev effort once answered** | Rough engineering size: *none*, *S* (under a day), *M* (one to three days), *L* (a sprint or more). |

Where this register's classification differs from the flag in `OWNER_DECISIONS.json`, the difference is stated and the reason given. The JSON flags were derived by review; so were these. Neither is an owner statement.

---

## 2. The audit: where the documents and the code disagree

These were found while checking each decision against the code. None changes the software; each is a documentation correction or a small hardening item for the next sprint (§7).

| # | Finding | Where | Why it matters |
|---|---|---|---|
| A1 | `docs/customer_account/IMPLEMENTATION_STATUS.md` still says the staff approval screens and the Customer Account frontend are "deferred to Phase 12". Both exist (`frontend/src/account/AccountApp.jsx`, the two approval screens in the Staff Portal). | IMPLEMENTATION_STATUS.md §2 | A reader checking what is built will be told less exists than does |
| A2 | `docs/UAT/CUSTOMER_ACCOUNT_UAT_PACK.md` says OD-34 blocks production execution of every `CA-REG-*` and `CA-REC-*` case. No `CA-REC-*` case exists in the pack; the recovery cases are numbered differently. | pack, line ~48 | A tester cannot find what the sentence points at |
| A3 | `docs/customer_account/EMAIL_DELIVERY.md` §3 lists an `account.suspended` template. `account_email_service.TEMPLATES` has six keys and no suspended template. | EMAIL_DELIVERY.md §3 vs `account_email_service.py` | The copy review sheet (OD-39) would ask for review of text that is not sent |
| A4 | `docs/OWNER_DECISIONS.md` §3 says "no case in the 45-case pack depends on a return record". The pack has held 49 cases since the role merge. | OWNER_DECISIONS.md, OD-22 note | Stale count; the statement is still true at 49 |
| A5 | Staff sign-in resolves the client address with `api/deps.py::client_ip`, which returns the raw peer and does not apply the "fold any forwarded request into one untrusted bucket" rule that the public and account routers apply. It is safe today only because the unit template runs `--no-proxy-headers`. `trusted_proxy_host_list` is validated at startup but no code compares a peer address against it. | `backend/app/api/deps.py`, `api/public/deps.py`, `api/account/deps.py`, `config.py` | Three routers, two rules. When proxy trust is eventually enabled (DEPLOYMENT.md §3) the staff limiter would be the one that is wrong |
| A6 | `DEPLOYMENT.md` §8 lists "Final Operations/Marketing permissions" as an open gate at deployment. `OWNER_DECISIONS.json` marks OD-02 and OD-03 as blocking neither UAT nor production. | DEPLOYMENT.md §8 vs JSON | Either the gate list or the flags should move. This register treats them as *confirmations* (§4, P3) |
| A7 | `PROJECT_STATUS.md` §29.2 records `react-router-dom` as "6.28.x → 6.30.6". The lockfile at `ffa03ad` already resolved `react-router` 6.30.6; only the `package.json` floor moved from `^6.28.0` to `^6.30.6`. | PROJECT_STATUS.md §29.2 | No runtime change happened; the record should not imply one |
| A8 | Service functions for suspend, reinstate and deactivate of a customer identity exist (`customer_identity_service.py`) with no route reaching them. `OPERATIONS.md` §6 lists them as a production gate. | `customer_identity_service.py` ~L782–853 | Staff will have no way to suspend an account after launch except the database |
| A9 | Customer change-password was deferred at Phase 9, again at Phase 11 "to Phase 12", and Phase 12 did not add it. The account routes are register, verify, resend, sign-in, sign-out, forgot, reset and `me`. | `backend/app/api/account/routes.py`; IMPLEMENTATION_STATUS.md L34 | A signed-in customer who suspects their password is known must use the forgot-password path |

The scripts that verify the registers (`verify_owner_decisions.py`, `verify_decision_log.py`, `verify_uat_blank.py`) all pass at this commit; none of the above is something they check.

---

## 3. The ranking in one table

Ordered by the recommended answering sequence, not by identifier. The reason for the order: UAT cannot be signed without the first group; production cannot start without the second; the third shapes the hosting contract and should be answered together; the rest are confirmations or post-launch.

| Rank | Decision | Class | Priority | Cost to answer | Dev effort once answered | Blocks |
|---:|---|---|---|---|---|---|
| 1 | **OD-17** Staff MFA | UAT + production | **P1** | hours | M (TOTP) to L (external IdP) | Security sign-off, UAT-AD-01/02 |
| 2 | **OD-34 follow-on** Choose the production email provider | Production | **P1** | days | M | Every Customer Account registration and recovery flow in production |
| 3 | **OD-37 follow-on** Approve terms and privacy text | Production | **P1** | days (legal) | S (set two version strings) | Production registration refuses while placeholders stand |
| 4 | **OD-08 / OD-09** Name the Vietnamese reviewer(s) | UAT + production | **P1** | minutes to name; days to review | none | REVIEW_vietnamese_ui, REVIEW_vietnamese_templates, UAT-OP-05, UAT-XX-14 |
| 5 | **OD-19** Name the accessibility reviewer | UAT + production | **P1** | minutes to name; days to review | none | REVIEW_accessibility, UAT-XX-12/13 |
| 6 | **OD-18** Name the printer, stock and scanner | UAT + production | **P1** | minutes if owned; days if purchased | none | REVIEW_physical_label, UAT-OP-04 |
| 7 | **OD-39 follow-on** Review the customer-facing English copy | Production | P2 | hours | S | REVIEW_customer_account_copy |
| 8 | **OD-11** Data residency | Production | P2 | hours (may need legal) | none | OD-10, OD-34 provider region, backup location |
| 9 | **OD-10** Hosting shortlist and choice | Production | P2 | days | L (provisioning, not code) | Every production gate that needs a host |
| 10 | **OD-12 / OD-13** RPO and RTO | Production | P2 | hours | S (schedule the existing backup script) | Backup schedule, hosting tier |
| 11 | **OD-20** Who may authorise production deployment | Production | P2 | minutes | none | The release gate itself |
| 12 | **OD-05** Tracking domain | Production | P2 | hours | S (one setting, TLS) | Labels, every customer-facing link |
| 13 | **OD-07** Carrier-link allowlist | Production | P2 | hours | S | Public tracking external links |
| 14 | **OD-06** Public help URL | Production | P2 | minutes | S | Public page contact link |
| 15 | **OD-01 / OD-36 follow-on** Retention periods | Production | P2 | hours | L (a destructive job with its own audit trail) | Deletion schedule; privacy requests (OD-35) |
| 16 | **Secret store** (existing gate, no OD) | Production | P2 | hours | M | `SECRET_KEY`, email credentials, any provider credential |
| 17 | **DEC-0006** Shared rate limits | Production, *conditional* | P2 | minutes | none at one worker; M for a shared store | Only if more than one worker process is ever run |
| 18 | **OD-14** Import file and row limits | Production | P3 | minutes | none or S | First real customer import |
| 19 | **OD-02 / OD-03** Final Operations and Marketing permissions | Confirmation | P3 | minutes | none (placeholder stands) or S | Nothing, if the placeholder is confirmed |
| 20 | **OD-04** Lifecycle thresholds | Confirmation | P3 | minutes | none (editable in Settings) | Nothing |
| 21 | **OD-22** Returns | Post-launch (scope) | P3 | hours | none (out of scope) to L (workflow) | Nothing in UAT or production today |
| 22 | **OD-15 / OD-16** Shipment import, legacy baseline | Post-launch | P3 | hours | L each | Day-one report completeness only |
| 23 | **OD-21 / Phase 4B** Provider integration | Post-launch (final phase) | P3 | days (vendor account facts) | L | Nothing; manual and external-link tracking is the complete story |
| 24 | **React Router 7** | Post-launch, engineering | P3 | none (engineering call) | M | Nothing; two moderate advisories, neither reachable (§5.6) |
| 25 | **ESLint 10** | Post-launch, engineering | P3 | none (engineering call) | S | Nothing; development tooling only (§5.7) |

Five decisions are **UAT blockers** (ranks 1, 4, 5, 6 — OD-17, OD-08, OD-09, OD-18, OD-19), the same five the JSON flags. Everything in ranks 2–17 is a **production blocker**. Ranks 18–25 are confirmations or post-launch.

---

## 4. Each decision

### 4.1 UAT blockers

#### OD-17 — Staff MFA. *Rank 1, P1, UAT + production.*

**Question.** Is MFA required for staff sign-in before production, for which roles, by what method?

**Today.** Email and password, argon2 hashing, server-side opaque session cookies with CSRF binding, 8-hour idle and 24-hour absolute expiry, sign-in rate-limited at 8 attempts per 5 minutes per address and per email. No lockout on staff accounts (customers have one). No MFA, TOTP or two-factor code exists anywhere in `backend/` or `frontend/src`. `CRM.md` §11 says "prefer MFA-capable authentication". `RUNBOOKS.md` §11 says that after a credential compromise "that gate has become urgent".

**Options** (from the register): no MFA; TOTP for all staff; TOTP for Admin only; email one-time codes; external identity provider.

| Option | Risk | Effort |
|---|---|---|
| No MFA | One reused or phished password is full access at that role. Admin can export every customer. Must be recorded as a deliberate acceptance | none |
| TOTP, all staff | Enrolment, recovery codes and lost-device handling must be built and documented. Re-runs UAT-AD-01/02 | M |
| TOTP, Admin only | Operations and Marketing still single-factor; Marketing has segment export | M (same build, narrower policy) |
| Email codes | Weak second factor: the mailbox is usually protected by the same password habits. Adds a production email dependency to *staff* sign-in, which today has none | M |
| External IdP | Strongest and offloads recovery, but introduces a vendor, a cost and an availability dependency for a four-to-twelve-person staff | L |

**Recommendation.** **TOTP for all staff**, with enrolment enforced at first sign-in after the feature ships, eight single-use recovery codes, and Admin able to reset a colleague's enrolment (audited). The session layer is already server-side, so a step-up state on the session row is a small change; the customer-account design already reserves exactly this shape (`SESSION_COOKIES_AND_CSRF.md` §9). Admin-only is the acceptable fallback if the owner wants a smaller first step; "no MFA" should be chosen only in writing.

**Dependencies.** None to decide. Once decided: the security sign-off and UAT-AD-01/02 re-run; the staff guide gains an enrolment section.

**Why P1.** It is the only open decision that blocks UAT *and* has a material build behind it. Every week it is undecided is a week the build cannot start.

#### OD-08 and OD-09 — Vietnamese staff wording; Vietnamese customer wording and the 17 templates. *Rank 4, P1, UAT + production.*

**Today.** Complete Vietnamese staff catalogue (`frontend/src/i18n/vi.js`), parity with English enforced by test; 17 public update templates in both languages, pinned by tests; English template wording approved 2026-09-13 (DEC-0084). No native speaker has read any of the Vietnamese. The Customer Account is English-only by OD-39, so it is not in this review.

**Options.** A named Vietnamese-speaking staff member; an external translator; withhold Vietnamese until reviewed.

**Risk.** A mistranslated destructive-action confirmation (staff) or a template that overstates delivery certainty (customer) is the concrete harm. Withholding Vietnamese is reversible and costs nothing in code (the language switch exists), but Vietnamese is a stated product requirement.

**Recommendation.** Name one internal reviewer now for both sheets; they are ordinary review sheets and need no tooling. If nobody internal is available within two weeks, commission an external translator for the 17 templates first (customer-facing, smaller) and the staff catalogue second.

**Dependencies.** None. **Dev effort.** None unless the review finds changes; then S.

#### OD-19 — Screen-reader and zoom testing responsibility. *Rank 5, P1, UAT + production.*

**Today.** 124 automated axe audits (62 screen states × 2 viewports), zero serious or critical, zero suppressions. No screen reader, no zoom above 100%, no forced-colors, Chromium only. `REVIEW_accessibility.md` is prepared and blank.

**Options.** A staff member who uses a screen reader daily; an external specialist; a trained staff member with the limitation recorded; defer and record the application as not validated for assistive technology.

**Recommendation.** Option 3 for the first release: one trained staff member runs NVDA on Windows and 200 % zoom through the review sheet, with the limitation recorded in the sheet. Automated coverage is roughly a third of WCAG; focus order and announcements are what it cannot see. An external specialist is the right choice if the Customer Account is ever marketed as accessible.

**Dependencies.** None. **Dev effort.** None until findings exist.

#### OD-18 — Physical thermal printer and scanner acceptance. *Rank 6, P1, UAT + production.*

**Today.** Labels render to PDF with page geometry and barcode content pinned by tests; a scanned package reference opens its shipment. No label has been printed on a thermal printer and no barcode read by a physical scanner.

**Options.** Name the hardware the business already owns; purchase named hardware and test; accept PDF rendering only and defer physical acceptance.

**Recommendation.** Name what is already on the warehouse bench (model, DPI, label stock size) and run `UAT-OP-04` against it. This is the cheapest UAT blocker on the list to clear and the one most likely to find a real defect (barcode density at 203 dpi on 4×6 stock is only knowable with the device).

**Dependencies.** None. **Dev effort.** None, or S if the barcode module size needs adjusting.

### 4.2 Production blockers

#### OD-34 follow-on — Production email provider. *Rank 2, P1.*

**What is decided.** OD-34 (answered 2026-09-19): development-only capture is allowed; **no production provider is selected**; production launch of customer registration is blocked until an owner-approved provider is selected using verified documentation and any data-residency requirement. The open question is *which provider*.

**Today.** Two transports exist, `null` and `capture`; `production` is a name that `build_transport()` refuses with `ProductionTransportNotConfigured`, and `get_settings()` refuses to start with it in every environment. In `ENVIRONMENT=production`, `capture` is also refused, so `account_delivery_blockers()` always reports `email_provider_not_selected` and register, resend and forgot-password return 503. Suppression is honoured before any send. **No bounce or complaint handling exists.** `EMAIL_DELIVERY.md` §5 lists seven launch conditions: provider selected; residency confirmed; SPF, DKIM and DMARC on the sending domain; bounce and complaint handling defined; credentials in a secret store via `credential_ref`; legal text approved (OD-37); copy reviewed (OD-39).

**Options.**

| Option | Risk | Effort |
|---|---|---|
| A transactional email API with a Canadian or US region, bounce and complaint webhooks | Vendor onboarding, domain authentication, a webhook route that creates suppressions. The provider holds recipient addresses, so OD-11 must be answered first | M |
| Plain authenticated SMTP relay from the company's existing mail domain (Microsoft 365) | Simplest to configure; bounces arrive as mail, not as events, so complaint handling is manual; sending limits on a shared tenant | S–M |
| Send through a personal mailbox | Recorded in the register as an option; it is not a serious one for a customer-facing system | — |

**Recommendation.** Choose a transactional provider with bounce and complaint webhooks, in the region OD-11 allows, and have engineering build the transport provider-agnostically (SMTP or HTTP API behind the existing `EmailTransport` protocol, credentials via `credential_ref`). If the owner prefers to defer the vendor decision, the M365 SMTP relay is a legitimate first-release choice provided the manual bounce procedure is written into `OPERATIONS.md`.

**Dependencies.** OD-11 (residency) first; secret store (rank 16) for the credential; OD-37 and OD-39 before the first production send.

#### OD-37 follow-on — Approved terms and privacy text. *Rank 3, P1.*

**Today.** Both version identifiers are `PLACEHOLDER-…-unapproved`; production registration refuses while either is. The acknowledgement mechanism is built and tested. The owner's answer requires legal text; none exists.

**Recommendation.** Commission the two documents now; they are on the critical path for registration and depend on nobody in engineering. Once approved, two settings change and one registration test re-runs. **Dev effort.** S.

#### OD-39 follow-on — Customer-facing English copy review. *Rank 7, P2.*

**Today.** English only, no language control rendered. `REVIEW_customer_account_copy.md` is prepared and blank. Note finding A3: the review sheet should not include the `account.suspended` template that does not exist.

**Recommendation.** Assign the review alongside OD-19; both are a few hours in the UAT environment. **Dev effort.** S for whatever the review changes.

#### OD-11 — Data residency. *Rank 8, P2.*

**Today.** Nothing recorded or enforced; `HOSTING.md` §5 carries an unticked checklist item. Answering after a host is chosen may mean moving the database and every backup.

**Options.** Canadian residency required (by law or by policy); any comparable jurisdiction; no constraint.

**Recommendation.** Answer this **before** OD-10 and OD-34; it is a constraint on both. If the business has no legal advice on PIPEDA or Quebec Law 25 obligations for this data set, "Canadian region preferred, not required" is a defensible interim answer that keeps the hosting shortlist wide. **Dev effort.** None.

#### OD-10 — Hosting shortlist. *Rank 9, P2.*

**Today.** No provider; nothing provisioned; pricing research deferred by the owner until a shortlist exists. The application is a single SQLite-backed FastAPI process plus one worker and a static frontend, so a small managed VM or platform host is sufficient.

**Options.** Managed platform host; VPS the business administers; on-premises; a Canadian-region managed host if OD-11 requires it.

**Recommendation.** A managed VPS in a Canadian region (if OD-11 permits a non-Canadian region the shortlist widens). The deployment artefacts under `deploy/` are systemd templates and assume a Linux host the business controls, which favours a VPS over a platform host. **Dev effort.** L in provisioning time, none in code.

#### OD-12 and OD-13 — RPO and RTO. *Rank 10, P2.*

**Today.** No backup schedule runs; `BACKUP_RESTORE.md` §6 states a *target* of one hour in business hours and twelve overnight and marks it unmeasured. Restore of a 0.89 MiB development database measured under one second; the figure is the database step only.

**Recommendation.** RPO: one hour in business hours (the documented target; the backup script exists and a cron entry delivers it). RTO: a few hours from a stored backup, no warm standby for release 1. Both answers are implementable with what exists. **Dev effort.** S (schedule the script, add an off-site copy).

#### OD-20 — Who may authorise production deployment. *Rank 11, P2.*

**Recommendation.** The owner alone, for release 1, recorded in `DEPLOYMENT.md` with a one-line gate: "all P1 and P2 items in this register answered or explicitly accepted". Two-person authorisation can follow when there are two people. **Dev effort.** None.

#### OD-05 — Tracking domain. *Rank 12, P2.*

**Today.** `tracking_base_url` is `http://localhost:5173/track`; production configuration rejects a local origin. The domain is printed on labels, which cannot be corrected after they ship.

**Recommendation.** A subdomain of the company domain (`DEPLOYMENT.md` §8 already names `track.solarisexpress.ca` as the intended host). Decide together with OD-10 since the certificate is provisioned on the host. **Dev effort.** S.

#### OD-07 — Carrier-link allowlist. *Rank 13, P2.*

**Today.** Nine hosts shipped and enforced; not reviewed against carrier documentation. The list is the only thing between the public page and an arbitrary outbound link.

**Recommendation.** Replace the nine with the hosts of the carriers the business actually hands parcels to (likely three or four), confirmed against each carrier's public tracking URL. Removing a host is a setting change; a wrong host is an open redirect on a public page. **Dev effort.** S.

#### OD-06 — Public help URL. *Rank 14, P2.*

**Today.** Empty; link omitted; startup warns. UAT validates the omission.

**Recommendation.** A link to the existing company contact page. It is one setting and the omission is the status quo, so this can also be answered "no link" without harm. **Dev effort.** S.

#### OD-01 and OD-36 follow-on — Retention periods. *Rank 15, P2.*

**Today.** Nothing is deleted automatically; no retention job exists; OD-36 (answered) defers customer-account retention to the same periods OD-01 will set. OD-35 (privacy requests) is designed but not built; only `deactivate()` exists and it is not a deletion.

**Options.** Per-category periods with automatic deletion; one organisation-wide period; manual deletion on request only; retain everything indefinitely, recorded as deliberate.

**Recommendation.** For release 1: **manual deletion on request only**, recorded as the deliberate choice, with per-category periods set on paper now (customer records 7 years after last shipment for tax purposes; audit log indefinite; imported and exported files 90 days; public tracking events 2 years) and the automatic job built post-launch against those periods. A retention job is destructive code and should not be the thing that ships first. **Dev effort.** None now; L for the job.

#### Secret store (existing gate). *Rank 16, P2.*

**Today.** `SECRET_KEY` and any credential live in `.env`. `credential_ref` is a documented convention; nothing resolves it. The email provider credential (rank 2) is the first thing that will need it.

**Recommendation.** Decide this with OD-10: whatever host is chosen has a secret facility (systemd `LoadCredential`, a platform secret, or a vault). Engineering then implements `credential_ref` resolution against it. **Dev effort.** M.

#### DEC-0006 — Shared rate limits. *Rank 17, P2, conditional.*

**Today.** One in-process sliding-window limiter (`security.py`), per-process counters, reset on restart, 20,000-bucket cap. Eleven limited routes (staff login; public tracking; eight Customer Account buckets; account shipment reads). The unit template runs `uvicorn --workers 1 --no-proxy-headers` and `DEPLOYMENT.md` says "exactly one instance". No Redis, broker or cache anywhere. Proxy-header trust is off; public and account routes fold any forwarded request into one untrusted bucket; staff login does not (finding A5).

**Options.**

| Option | Risk | Effort |
|---|---|---|
| Keep one worker and record it as the release-1 operating constraint | A single process handles the load; for this business's volume that is realistic. Must be enforced, not remembered: the unit template already does | none |
| Shared store (Redis or an SQLite-backed counter table) before launch | Adds an operational dependency for a limit nobody has hit | M |
| Move limits to the reverse proxy | Loses the per-email and per-identity buckets | M |

**Recommendation.** **Not a launch blocker at one worker.** Record "one worker process, limiter in-process" as the release-1 constraint in `DEPLOYMENT.md`, keep the template as it is, and revisit when the first capacity measurement says otherwise. Fix A5 in the next sprint so all three routers apply the same client-address rule. Reclassify the JSON flag from "blocks production" to "blocks multi-worker deployment".

#### OD-14 — Import limits. *Rank 18, P3.*

**Recommendation.** Ask one question: how many rows is the real customer list? Under 5,000, keep the limits. Over, keep them and document splitting; a background importer is not worth building for a one-off. **Dev effort.** None.

### 4.3 Confirmations

#### OD-02 and OD-03 — Final Operations and Marketing permissions. *Rank 19, P3.*

**Today.** Import and bulk export are Admin-only (DEC-0082); Operations and Marketing see no cost or profit; UAT-OP-10, UAT-MK-03 and UAT-MK-04 pin these. Finding A6: `DEPLOYMENT.md` lists this as a deployment gate; the JSON says it blocks nothing.

**Recommendation.** Confirm the restrictive placeholder as the release-1 answer and widen later on evidence. The only real operational cost is that an Admin runs every bulk export. If that is already a daily annoyance, grant Operations shipment export (not import) now. **Dev effort.** None or S.

#### OD-04 — Lifecycle thresholds. *Rank 20, P3.*

**Recommendation.** Confirm 30/60/90. They are visible, editable in Settings, and stated on the report. **Dev effort.** None.

### 4.4 Post-launch

#### OD-22 — Returns. *Rank 21, P3.*

**Today.** `is_return` and `return_of_shipment_id` exist and are read by `is_qualifying`, `activity_service`, `report_service` (the `returns` row, always 0) and `export_service` (always `false`); nothing writes them. Return *statuses* are fully implemented and not in question. The `returns_only` drill-through was removed at RC-UAT-3. The requirement matrix classifies this as specification ambiguity and recommends building nothing until answered.

**Options.** Out of scope (reporting and export surfaces reconsidered); a booking action creating a linked shipment; an administrative correction on the outbound; tracked outside the application.

**Risk.** Leaving it open costs nothing in UAT or production. Leaving the report row reading zero forever is a small credibility cost. Building a workflow is a new write path against confirmed shipments: L, with its own permission, label, pricing and public-tracking answers (the twelve questions).

**Recommendation.** Answer question 1 only, now: **"Returns are out of scope for release 1."** Then relabel the report row and export column rather than remove them (the columns stay; the rule in `CRM.md` §4 stays pinned). Reopen the other eleven questions when a real return has to be handled and the business knows what it wants to record about it.

#### OD-15 and OD-16 — Shipment CSV import; legacy aggregate baseline. *Rank 22, P3.*

**Recommendation.** Answer both with one fact: does any pre-existing shipment data exist in a system the business still has? If no, both close as "nothing to build". If yes, OD-16 (aggregate totals with a cutoff date) is the cheaper way to make day-one reports honest; OD-15 (row-level import) only if the historical records must be opened individually. **Dev effort.** L each; none if closed.

#### OD-21 and Phase 4B — Provider (ShipStation) integration. *Rank 23, P3.*

**What Phase 4B is.** The verified provider adapter: one file implementing `ProviderAdapter`, a registry entry, a webhook endpoint handing its body to `integration_inbox_service.accept_delivery`, the event-to-status map, reconciliation, a staff mapping screen, and switching on `connected_api`. The owner deferred it to the end of the project on 2026-09-10 (DEC-0075, a schedule choice, not a blocker).

**Today.** Phase 4A groundwork is built and tested: five tables (connections, inbox, provider events, jobs, heartbeats), the worker with `--once` and continuous modes, the adapter contract, the SSRF resource policy, four admin routes. Deliberately inert: `PRODUCTION_ADAPTERS = {}` and `register()` raises in production; both allowlists empty so `fetch_guarded` returns `fetch_disabled`; no webhook route; `connected_api` refused by `leg_service` and absent from the public vocabulary; health reads `not_configured`. The only adapter is the test fake. `verify_rc_baseline.py` checks four of these invariants on every run.

**Options.** Answer the nine questions against the real account and build; answer them and find the account cannot support it, closing the item; continue with manual and external-link tracking indefinitely.

**Risk.** Building against a guessed API generation or event vocabulary publishes wrong statuses to customers (legacy `SHIP_NOTIFY` means a label was created, not a delivery). Not building costs staff the manual status entry they do today.

**Recommendation.** Leave deferred until human UAT is signed and the production gates are closed. When the owner is ready, the nine questions take an afternoon with the ShipStation account open; answers of "no" to 3, 5 or 9 are useful and may close the item cheaply. Phase 4B is then one sprint of adapter work on infrastructure that already exists. Keep the four invariants in the baseline verifier until that sprint starts.

**Dependencies.** OD-21 answers; a secret store for `credential_ref`; a host with an inbound HTTPS endpoint for the webhook.

#### React Router 7. *Rank 24, P3, engineering.*

**Today.** `react-router-dom` 6.30.6, the last 6.x. `npm audit` reports two moderate advisories on `react-router`, both fixed only in 7.18.4:

| Advisory | What it needs | Reachable here? |
|---|---|---|
| GHSA-wrjc-x8rr-h8h6, open redirect via backslash in `<Link>` / `useNavigate` (CWE-601, no CVSS score published) | An attacker-controlled string reaching a `to=` or `navigate()` target with a leading `\` or `/\` | **No.** The only dynamic targets are: `SignInPage` and `AccountApp`, where `state.from` is a `location.pathname` this application wrote and is additionally checked for the `/account/` prefix; `destinationForSession()`, which returns one of a fixed set of paths; and report and dashboard rows, whose `link` strings are built server-side in `report_service.py` as literal `/…` paths with enum values in the query string. No URL query parameter is ever passed to a navigation |
| GHSA-337j-9hxr-rhxg, constructor injection via `deserializeErrors()` during SSR hydration (CWE-470, CVSS 6.1) | Server-side rendering with `hydrateRoot` and a data router | **No.** `main.jsx` uses `createRoot`; there is no `StaticRouter`, `createBrowserRouter`, `RouterProvider` or `hydrateRoot` anywhere in `frontend/src` |

The v7 `v7_relativeSplatPath` future flag is already on in `App.jsx` and `tests/utils.jsx`. `v7_startTransition` is off because `ReportsPage` drives controlled checkboxes from `useSearchParams` and the flag breaks the click (caught by Playwright, recorded in PROJECT_STATUS §29.3).

**Options.** Upgrade now, before human UAT begins; upgrade after UAT sign-off; stay on 6.30.6 for release 1 and record the two advisories as accepted.

**Risk of upgrading.** 7.x is mostly a package rename for a `BrowserRouter` app (`react-router-dom` becomes `react-router`); the `startTransition` behaviour becomes the default and the ReportsPage filter inputs must move to local state first. Every change is to the tested tree and forces a re-freeze. **Risk of not upgrading.** None reachable today; the 6.x line will receive no further security fixes.

**Recommendation.** Upgrade in the next sprint **if** human UAT has not started by then (today no case has been executed, so the tree is not yet something a tester has seen), otherwise immediately after UAT sign-off. It is an M-sized change: move the report filters to local state, flip `v7_startTransition` on under 6.30.6, run the suites, then take 7.18.4 and re-run. Re-freeze as RC-UAT-5 either way.

#### ESLint 10. *Rank 25, P3, engineering.*

**Today.** `eslint` 9.39.5, which the registry now marks "no longer supported" (every 9.x is). `eslint-plugin-react-hooks` 7.1.1 supports `^10.0.0`; `eslint-plugin-react` 7.37.5 (the newest release, April 2025) declares `peer eslint ^9.7`, so ESLint 10 leaves an invalid tree and every later `npm install` fails with `ERESOLVE` unless forced. This is development tooling: it is not in the built bundle and not on any production path.

**Options.** Wait for an `eslint-plugin-react` release that accepts 10; replace the plugin with `@eslint-react/eslint-plugin`, which is maintained and ESLint-10-compatible, and re-map the two rules this config turns off; install with `--legacy-peer-deps` and record it; stay on 9.39.5.

**Recommendation.** Stay on 9.39.5 for release 1 and check the plugin's peer range at each sprint boundary; swap to `@eslint-react/eslint-plugin` if it has not moved by the React Router 7 sprint, since that sprint touches the frontend toolchain anyway. Forcing the peer is the one option not to take: it makes every fresh clone fail to install cleanly.

---

## 5. Answered decisions that still gate production

For completeness, because a reader of the JSON sees them as "answered" and may assume nothing is owed:

| Decision | Answered | What is still owed | Covered above |
|---|---|---|---|
| OD-34 Production email | 2026-09-19 | A provider | rank 2 |
| OD-37 Terms and privacy | 2026-09-19 | The two texts | rank 3 |
| OD-39 Language launch policy | 2026-09-19 | The English copy review | rank 7 |
| OD-36 Customer-account retention | 2026-09-19 | The periods, via OD-01 | rank 15 |
| OD-33 Customer MFA | 2026-09-19 | Nothing before launch; optional TOTP is a hardening-phase item | — |
| OD-40 Linked-customer merge | 2026-09-20 | Nothing; merge is refused while a link exists, as decided. `OPERATIONS.md` §6 still lists "merging customers that have an account" as a gate; it is a post-launch scope question, not a gate | — |

---

## 6. Outstanding features, classified

Features the documents name that the code does not implement. Owner-decision dependencies are given where they exist; the rest are engineering scope questions.

| Feature | Exists today | Depends on | Class |
|---|---|---|---|
| Staff MFA | nothing | OD-17 | UAT + production |
| Production email transport, bounce and complaint handling | `null` and `capture` transports; `production` refused | OD-34 follow-on, OD-11, secret store | Production |
| Approved terms and privacy versions | placeholders, refused in production | OD-37 follow-on | Production |
| Secret store and `credential_ref` resolution | convention only | OD-10 | Production |
| Scheduled and off-site backups | manual scripts | OD-12, OD-13, OD-10 | Production |
| Customer identity suspend / reinstate / deactivate **routes** | service functions, no route (A8) | none | **Production** (operational necessity; recommend sprint) |
| Customer change-password | nothing (A9) | none | Production-adjacent (recommend sprint) |
| Retention and deletion job | nothing | OD-01 | Post-launch (manual deletion for release 1) |
| Privacy-request execution | `deactivate()` only | OD-35, OD-01 | Post-launch |
| Admin reinstatement of a rejected account | nothing | scope | Post-launch |
| Unlink an account from a customer | nothing | scope | Post-launch |
| Customer "My information" and "Notification preferences" screens; profile change proposals after approval | excluded from Phase 12 by the owner's instruction; CA-PRF-01…04 out of scope | DEC-0095, OD-27/28/38 (answered) | Post-launch |
| Customer consent self-service | staff-side only | OD-38 (answered) | Post-launch |
| Customer optional TOTP | nothing; columns reserved on paper | OD-33 (answered, hardening) | Post-launch |
| Returns workflow | columns only | OD-22 | Post-launch |
| Shipment CSV import; legacy baseline | nothing | OD-15, OD-16 | Post-launch |
| Provider integration (Phase 4B) | Phase 4A groundwork, inert | OD-21, DEC-0075 | Post-launch (final phase) |
| Worker supervision (systemd unit installed) | template, disabled | Phase 4B | Post-launch |
| "Demo" tracking mode fixtures | nothing | — | Post-launch, low value |
| Vietnamese Customer Account | nothing | OD-39 (English-only answered) | Post-launch |
| Shared-store rate limiting | in-process | DEC-0006 | Only if more than one worker |
| Lead and marketing fields; bulk messaging; loyalty; payments; quotes; public booking; recipient accounts; multi-user companies; US domestic routes | nothing | CRM.md deferrals, OD-26/30/32 | Post-launch, deferred not rejected |

---

## 7. The proposed next sprint

**Name.** Sprint 13 — Launch hardening. **Length.** Two weeks. **Rule.** No new customer-facing surface; every item either closes an audit finding, removes a known gap on the production path, or is gated on a decision the owner makes in the first three days.

### Lane A — decision-independent (starts day 1)

| # | Item | Size | Closes |
|---|---|---|---|
| A-1 | Customer identity suspend / reinstate / deactivate routes and Staff Portal controls, with audit events and tests | M | A8; `OPERATIONS.md` §6 gate |
| A-2 | Customer change-password (current password required; revokes other sessions; rate-limited in the `account:` namespace) | S–M | A9 |
| A-3 | One client-address rule for all three routers: staff login adopts the forwarded-request bucket; `trusted_proxy_host_list` is compared against the peer when trust is enabled; tests for both | S | A5 |
| A-4 | Provider-agnostic production email transport behind the existing `EmailTransport` protocol (SMTP with STARTTLS, credential via `credential_ref`), still refused at startup until a provider is configured; a suppression-creating bounce/complaint intake route, inert until a provider is named | M | Prepares rank 2 so the owner's provider choice becomes configuration, not a build |
| A-5 | Documentation corrections A1, A2, A3, A4, A6, A7; reclassify DEC-0006 in the JSON per rank 17 | S | the audit |
| A-6 | React Router 7: move `ReportsPage` filters to local state, enable `v7_startTransition`, take 7.18.4, full suites, re-freeze as RC-UAT-5 — **only if human UAT has not started by the sprint midpoint**; otherwise deferred to Sprint 14 | M | rank 24 |

### Lane B — gated on an owner answer in the first three days

| # | Item | Needs | Size |
|---|---|---|---|
| B-1 | Staff TOTP: enrolment, verification step on sign-in, recovery codes, Admin reset, staff guide section, UAT-AD-01/02 revised | OD-17 | M (L if an external IdP is chosen; then this becomes a design item) |
| B-2 | Email provider configuration, domain authentication checklist, bounce webhook wired to A-4 | OD-34 provider, OD-11 | S after A-4 |
| B-3 | Terms and privacy versions set; registration test re-run | OD-37 texts | S |

### Lane C — owner and reviewer actions the sprint supports but does not do

Name the Vietnamese, accessibility and physical-label reviewers (OD-08/09/19/18) and start human UAT on the re-frozen RC-UAT-4. Engineering reserves two days in the sprint for defect triage from whatever the testers find.

### What the sprint deliberately leaves out

Returns, shipment import, Phase 4B, the retention job, the Customer Account profile screens, ESLint 10. Each is post-launch by this register and none shortens the path to a first production release.

### Exit criteria

All gates green on the sprint's final commit; `verify_rc_baseline.py` passes against whichever RC is in force; every Lane A item merged; every Lane B item either merged or recorded as waiting on its named decision; the audit findings table in §2 reduced to those the owner chose to leave.

---

## 8. Changes since this register was written

### 8.1 2026-10-14 — RC-UAT-5 frozen; the UAT round 1 fix pack and three owner approvals

**What the owner decided.** After the bot-executed UAT run of 2026-10-14 (106 cases: 67
passed, 11 failed, 28 blocked) the owner approved a thirteen-item fix pack, then three
follow-ups: the password-reset link lives **one hour** (DEC-0121), the tree is
**re-frozen as RC-UAT-5**, and every gate is re-run.

**RC-UAT-5.** `docs/RC_UAT_5_BASELINE.json` and `.md`, measured at `0dfaf23` on
`fix/uat-round-1`. It supersedes RC-UAT-4 because screens, routes, schemas and wording all
changed, which is this repository's rule for a new identifier. RC-UAT-4's files are left
byte-identical and stay verifiable with `--baseline docs/RC_UAT_4_BASELINE.json`. No
migration and no dependency changed, so the Alembic head and both lock digests carry over.
The §4.4 recommendation to re-freeze as RC-UAT-5 after React Router 7 now means **RC-UAT-6**.

**Effect on this register.**

| Item | Was | Now |
|---|---|---|
| Finding A8 (§2): identity suspend/reinstate/deactivate with no route | Open | **Suspend and reinstate routed**, with Staff Portal controls and audit (DEC-0120). Deactivate deliberately not routed |
| Lane A, A-1 (§7) | Proposed | **Done** for suspend and reinstate; deactivate waits on OD-35 |
| OD-35 (deletion and privacy requests) | Answered 2026-09-19; execution not built | Unchanged. `deactivate()` is the only privacy-request primitive and is still unrouted; routing it belongs with building OD-35's execution (§6) |
| Reset-link lifetime | 2 hours | **1 hour** (DEC-0121), a setting |
| Human UAT start (§7, Lane C) | "on the re-frozen RC-UAT-4" | **on RC-UAT-5** |

**New decisions for the owner, from the fix pack** (`PROJECT_STATUS.md` §31.6):

1. **57 or 59.** The Customer Account pack has 59 case headings; the bot run listed 57.
   Reconciling needs the run's own list. *Class: UAT record. Priority: P2.*
2. **Public tracking shows only published milestones** (DEC-0118). Not a decision to
   reopen, but one to brief Operations on before UAT round 2. *Class: UAT readiness.*
3. **Customer identity deactivation** stays unrouted until OD-35's execution is built
   and names who may perform it. *Class: production. Priority: P2.*

### 8.2 2026-10-14 — UAT round 2, fix pack 2

**What the owner approved.** Four fixes from the second UAT run — the Customer Account
profile (CA-PRF-01, -02, -04 had been blocked by its absence), the customer-facing time
display, tags on the customer list with a tag filter and the referral refresh, and the merge
confirmation text — plus one acceptance:

| Item | Register effect |
|---|---|
| CA-SEC-07 Chrome-history residual | **Accepted by the owner** with the one-hour reset link (DEC-0122). Closed |
| Customer profile and post-approval proposals | **Built** (DEC-0123). IMPLEMENTATION_STATUS §2 updated; email change and notification preferences remain unbuilt |
| A customer's marketing grant on a suppressed address | Recorded as the customer's choice; the suppression still decides (DEC-0123) |

**RC identifier.** These change screens, routes, schemas and wording, so by the re-freeze
convention the tree under test is no longer RC-UAT-5's. RC-UAT-6 is required before UAT
round 3 (see `PROJECT_STATUS.md` §33).

### 8.3 2026-10-15 — UAT round 3: owner decisions and fix pack 3

**What the owner decided** (Ben, 2026-10-15), answering the questions `PROJECT_STATUS.md`
§33.4 left open:

| Question | Answer | Record |
|---|---|---|
| Who reviews profile change requests? | **Operations**, with **Louis Tong** as the default owner. Admin keeps the permission as a fallback | DEC-0124 |
| Customer self-service email change | **Deferred.** The profile keeps refusing `email`; a customer asks staff | DEC-0125 |
| Who may deactivate a customer account? | **Admin only** | DEC-0126 |

**Effect on this register.**

| Item | Was | Now |
|---|---|---|
| OD-35 (deletion and privacy requests) | Answered 2026-09-19; who may deactivate left open (§8.1 item 3) | **Closed.** Deactivation is Admin-only (DEC-0126). Routing `deactivate()` behind an Admin-only permission is now unblocked engineering work, not a decision. Privacy-request execution is still designed only (§6) |
| Profile change request queue (RC-UAT-6 risk) | No owner | **Operations, Louis Tong** (DEC-0124) |
| Email change (RC-UAT-6 risk) | Not built, undecided | **Deferred by the owner** (DEC-0125); staff change it on request |

**Fix pack 3.** The owner also approved one failure fix (UAT-XX-05: an import could be
confirmed without anybody deciding a possible duplicate), UAT enablement for three
blocked cases (CA-REG-07, CA-SHP-10, CA-REG-09), and fifteen minor fixes. Two of the fixes
record decisions: a customer who is opted in is told plainly when marketing email cannot
reach their address (DEC-0127, partly superseding DEC-0123), and a linked customer's
preferred language has one source (DEC-0128). Details are in `PROJECT_STATUS.md` §34.

**RC identifier.** Screens, schemas and wording changed, so **RC-UAT-7** supersedes
RC-UAT-6 before UAT round 4.

### 8.4 2026-10-15 — UAT round 4: fix pack 4

**What the owner approved** (Ben, 2026-10-15), from the UAT round 4 findings on RC-UAT-7:
one failure (CA-APR-05), two functional gaps, four small fixes, and the routing of
deactivation that §8.3 left as engineering work.

| Item | Register effect |
|---|---|
| CA-APR-05: an Admin approval did not say it was an override | **Fixed** (DEC-0129). `admin_override` on approve and reject audit rows, shown on Audit access |
| No staff screen to suppress an address | **Built** (DEC-0130). `suppression:add`, Marketing and Admin; evidence and reason required; audited. Unblocks the DEC-0127 note for UAT |
| OD-35 deactivation | **Routed** (DEC-0131). Admin-only route with a reason code and audit, and a control on the review screen. Lane A, A-1 (§7) is now done for all three lifecycle actions |
| All-skip import; password-reset 429 wording | **Fixed** (DEC-0132) |

**New questions for the owner** (`PROJECT_STATUS.md` §35.4): whether Operations keeps the
consent-status path to suppression or gets `suppression:add`; whether a deactivated
account's link should end; whether the resend-verification 429 should get the same generic
treatment as reset and registration.

**RC identifier.** A route, screens, schemas and wording changed, so **RC-UAT-8** supersedes
RC-UAT-7 before UAT round 5.

### 8.5 2026-10-15 — UAT round 5: owner decisions and fix pack 5

**What the owner decided** (Ben, 2026-10-15), answering the four questions of
`PROJECT_STATUS.md` §35.4, and approved the five UAT round 5 findings on RC-UAT-8.

| Item | Register effect |
|---|---|
| Operations and suppression | **Decided** (DEC-0133). Marketing and Admin only; the consent-status path refuses Operations and the form no longer offers it |
| A deactivated account's link | **Decided** (DEC-0134). Kept, and no longer blocks a customer merge; active and suspended links still do (OD-40) |
| Resend-verification 429 | **Decided** (DEC-0135). Generic sentence, same confirmation |
| 57 or 59 | **Closed** (DEC-0136). 59 |
| Marketing opt-in lost on link; audit evidence and account reference | **Fixed** (DEC-0137) |
| Add customer error summary; registration email check; 409 retries | **Fixed** (fix pack, no decision) |

**New questions for the owner** (`PROJECT_STATUS.md` §36.4): whether a linked customer
whose own email differs from the applicant's should also have its state row reflect the
opt-in; whether a customer whose only link belongs to a deactivated account may be linked
to a new account.

**RC identifier.** Screens, schemas and wording changed, so **RC-UAT-9** supersedes
RC-UAT-8 before UAT round 6.

### 8.6 2026-10-15 — UAT round 6: owner decisions and fix pack 6

**What the owner decided** (Ben, 2026-10-15), answering the three questions of
`PROJECT_STATUS.md` §36.4, and approved the UAT round 6 finding on RC-UAT-9.

| Item | Register effect |
|---|---|
| Consent on a link where the emails differ (§36.4 q1) | **Decided** (DEC-0138). One email per customer: approving a link makes the record's email the verified sign-in email, shown in the preview and audited; consent and suppression apply to that address; staff cannot change a linked customer's email |
| Suppressed address gets no verification email (UAT round 6 defect) | **Decided and fixed** (DEC-0139). A suppression blocks marketing email only; verification, reset, the attempt notice and decision notices are sent; the opt-in stays ineffective and is never explained to the customer |
| A customer whose only link is a deactivated account's (§36.4 q2) | **Decided** (DEC-0140). A new registration may take it over by staff approval, which ends the old link, audited |
| Personal details in the evidence reference (§36.4 q3) | **Decided** (DEC-0141). Helper text "Ticket or reference number only, no names"; `@` values stay hidden in the audit |

**New questions for the owner** (`PROJECT_STATUS.md` §37.4).

**RC identifier.** Screens, schemas, a permission-like edit rule and wording changed, so
**RC-UAT-10** supersedes RC-UAT-9 before UAT round 7.

### 8.7 2026-10-16 — UAT round 7: owner decisions

**What the owner decided** (Ben, 2026-10-16), answering the three questions of
`PROJECT_STATUS.md` §37.4.

| Item | Register effect |
|---|---|
| Changing a linked customer's email (§37.4 q1) | **Decided** (DEC-0142). Staff cannot change it while the account is active or suspended; the account must be deactivated first. The edit form shows the rule and the field is read-only |
| Suppression and other mail (§37.4 q2) | **Decided** (DEC-0143). A suppression blocks marketing email only; shipment and operational email keeps sending when built |
| Notice to the former holder on a takeover (§37.4 q3) | **Decided** (DEC-0144). No notice; the takeover is audited only |

**RC identifier.** A screen (the email field and its rule), a response field and wording
changed, so **RC-UAT-11** supersedes RC-UAT-10.

### 8.8 2026-10-17 — UAT round 8: real-phone feedback and staff-side gaps

**What the owner asked for** (Ben, 2026-10-17): three changes from real-phone UAT of
registration, and three gaps found in staff-side verification.

| Item | Register effect |
|---|---|
| Shipping address first, billing second (item 1) | **Done** (DEC-0145) |
| "Billing address is the same as shipping address" (item 2) | **Done** (DEC-0145). Ticked by default once a shipping street is typed; ticked hides billing and the server copies it; unticked shows empty billing fields; the server checks both |
| Confirm password at registration and reset (item 3) | **Done** (DEC-0146). Inline error, nothing sent; the server refuses a missing or different confirmation |
| Approved values flagged as drift (item 4) | **Fixed** (DEC-0147) |
| Approval audit said only "contact" (item 5) | **Fixed** (DEC-0148). Field names with old and new values, shown under Changes in Audit access |
| Customer withdrawal audited as "system" (item 6) | **Fixed** (DEC-0149). Actor `customer_account:CA-…`, in the audit and the consent history |

**RC identifier.** Screens (registration, reset, Audit access, the consent history), request
and response fields, and wording changed, so **RC-UAT-12** supersedes RC-UAT-11.

### 8.9 2026-10-18 — UAT round 9: the registration address, and the sign-in actor

**What the owner decided** (Ben, 2026-10-18): four registration changes, the sign-in and
sign-out audit actor, and answers to the three questions in PROJECT_STATUS §39.4.

| Item | Register effect |
|---|---|
| "Address" instead of "Shipping address" (item 1) | **Done** (DEC-0150). Billing box: "Billing address is the same as the address above" |
| Address country, line 1, city, province or state, postal code required (item 2) | **Done** (DEC-0151). Inline error per part, nothing sent; the server refuses the first missing part by name |
| "Notes for driver (buzz code, contact concierge, security,...)" (item 3) | **Done** (DEC-0150) |
| Billing required when unticked (item 4; §39.4 question 2) | **Done** (DEC-0152). The same five parts, client and server |
| Sign-in and sign-out actor `customer_account:CA-…` (item 5; §39.4 question 3) | **Done** (DEC-0153). A refused sign-in keeps `system` |
| Vietnamese Customer Account copy (item 6; §39.4 question 1) | **Deferred** to its own later pack; OD-39 stands (DEC-0154) |
| Refused sign-ins were rolled back (found while testing item 5) | **Fixed** (DEC-0155), in its own commit, for the owner's review |

**RC identifier.** Screens (registration's headings, labels, required markers and errors),
request validation and wording changed, so **RC-UAT-13** supersedes RC-UAT-12.

### 8.10 2026-10-18 — UAT round 10: the shipment list's keyword search

**What the owner asked for** (Ben, 2026-10-18, real-phone UAT): the Customer Account
shipment list's "Solaris Shipment ID" filter needed the exact full ID.

| Item | Register effect |
|---|---|
| Keyword search box instead of the exact-ID filter, with a hint listing what it searches | **Done** (DEC-0156). "Search shipments"; `q` on the list route |
| Partial, case-insensitive | **Done** (DEC-0156). Accents are ignored too, so "da nang" finds Đà Nẵng |
| Shipment ID, booking reference, origin and destination cities | **Done** (DEC-0156). Nothing else is searched; the booking reference is still not shown |
| Dates, status and route keep working with the keyword | **Done**. An intersection; all in the URL |
| Own shipments only; parameterized; LIKE wildcards escaped; bounded | **Done**. After the ownership clause; bound parameter; `%` `_` `\` literal; 64 characters, refused with this surface's 422 |
| Tests and UAT pack | **Done**. AS-08 registers the superseded free-text-absence assertion; UAT pack CA-SHP-09, CA-SHP-19 and CA-XP-01 extended, still 59 cases (DEC-0136) |

**RC identifier.** A screen, an API parameter and wording changed, so **RC-UAT-14**
supersedes RC-UAT-13.

### 8.11 2026-10-18 — UAT round 11: answers to the RC-UAT-13 and RC-UAT-14 questions

**What the owner decided** (Ben, 2026-10-18): eight answers to the points in PROJECT_STATUS
§40.4 and §41.4.

| Item | Register effect |
|---|---|
| 1. Keep the sign-in lockout fix as is (§40.4 question 1) | **Confirmed** (DEC-0157). DEC-0155 stands; no change |
| 2. Billing box ticked by default (§40.4 question 2) | **Done** (DEC-0158). An empty form shows no billing errors; unticking still requires the billing parts |
| 3. Country default stays Canada (§40.4 question 3) | **Confirmed** (DEC-0157). No change |
| 4. Postal code optional, address and billing, every country (§40.4 question 4) | **Done** (DEC-0159). Required: country, line 1, city, province or state. No format check; the 30-character bound stays. AS-09 |
| 5. Booking reference shown on each list row and card (§41.4 question 1) | **Done** (DEC-0160). The list allowlist is 18 fields; the detail stays at 24. AS-10, AS-12 to AS-15 |
| 6. Keep accent-insensitive search (§41.4 question 2) | **Confirmed** (DEC-0157). No change |
| 7. Package references find their shipment, own shipments only (§41.4 question 3) | **Done** (DEC-0161). An `EXISTS` correlated on the shipment, inside the ownership clause. AS-11 |
| 8. A dedicated UAT case for the keyword search (§41.4 question 4) | **Done** (DEC-0162). CA-SHP-20; the pack is 60 cases, supersedes DEC-0136's 59 |

**RC identifier.** Screens (registration's billing box and postal code, the shipment
list's booking reference and search hint), a response field, request validation, search
behaviour and wording changed, so **RC-UAT-15** supersedes RC-UAT-14.

### 8.12 2026-10-19 — UAT round 12: answers to the RC-UAT-15 questions

**What the owner decided** (Ben, 2026-10-19): four answers to the points in PROJECT_STATUS
§42.4.

| Item | Register effect |
|---|---|
| 1. Show the booking reference on the shipment detail too, phone and desktop (§42.4 question 1) | **Done** (DEC-0163). The detail is 25 fields: the public 24 plus `booking_reference`, first under "Where it is". Public Tracking stays at 24. AS-19 to AS-26 |
| 2. A cancelled package's reference still finds its shipment, own shipments only (§42.4 question 2) | **Confirmed** (DEC-0164). No code change; a test pins the stranger case |
| 3. Postal code stays optional; lenient shape check for Canada and the United States, client and server (§42.4 question 3) | **Done** (DEC-0165). Canada `A1A 1A1` with or without the space, any case; the United States `12345` or `12345-6789`. Blank always allowed, other countries unchecked, inline error in the same words on both sides. The server holds the profile address proposal to the same shapes. AS-17 |
| 4. Billing same as shipping defaults to true in the API too (§42.4 question 4) | **Done** (DEC-0166). A request that omits the flag gets the address copied; one that sends billing parts must send `false`. AS-18 |

**UAT pack.** Still 60 cases (DEC-0162): CA-REG-01, CA-SHP-05, CA-SHP-06, CA-SHP-20 and
CA-XP-01 gain the new steps; no case is added.

**RC identifier.** A screen (the shipment page's booking reference, registration's postal
code errors), a response field, request validation and an API default changed, so
**RC-UAT-16** supersedes RC-UAT-15.
