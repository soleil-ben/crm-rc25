# Existing UAT impact map — Customer Account

**Question this document answers:** what does the Customer Account do to the 49 UAT cases and
4 review sheets that already exist?

**Answer, up front: nothing is invalidated, nothing is renumbered, and no case is rewritten
by this phase.** The Customer Account is a new surface. The existing pack tests the Staff
Portal and Public Tracking, and neither of those changes here. Every result field in the
existing pack is still blank, so nothing executed is being discarded either.

---

## 1. Summary

| | Cases |
|---|---:|
| Existing pack (post role-merge remap) | **49** |
| Invalidated by the Customer Account | **0** |
| Requiring rewriting | **0** |
| Requiring an **added assertion** when the Customer Account is built | **6** |
| New cases, in a **separate** pack | **59** — 28 proposed in Phase 8, 11 added in Phase 10 (section 7), 12 added in Phase 11 (section 8), 8 added in Phase 12 (section 9) |
| Existing review sheets affected | **2** — `REVIEW_vietnamese_ui.md` gains five staff screens; the proposed fifth sheet now exists |

The new cases live in `docs/UAT/CUSTOMER_ACCOUNT_UAT_PACK.md`, not inside `UAT_CASES.md`.
Mixing them would make the existing pack un-executable until the Customer Account exists, and
the existing pack must stay executable on its own.

---

## 2. Cases that gain an assertion once the Customer Account is built

None of these changes today. Each is listed with the sentence to add, and each is an
**addition**, not a replacement.

| Case | Today | Add when built |
|---|---|---|
| **UAT-AD-01** — Sign in, session ends | Staff sign-in and sign-out | Confirm the staff session cookie is `solaris_session` and that no customer cookie is issued by a staff sign-in |
| **UAT-AD-07** — Audit log records a material change | Staff audit | Confirm a customer-account approval appears in the audit log with actor, reason code, and **no** credential material |
| **UAT-OP-12** — Near-duplicate held for review | Staff-entered duplicates | Confirm a **customer-submitted** registration matching an existing customer enters the same review and is never merged automatically |
| **UAT-OP-13** — Consent, then suppress | Staff-recorded consent | Confirm a customer-side marketing opt-in does **not** release a suppression |
| **UAT-XX-15** — Staff data never visible to the public | Public Tracking boundary | Extend to the authenticated customer surface: no internal field, no financial value, no other customer's shipment |
| **UAT-XX-13** — Usable on a phone | Staff Portal and Public Tracking | Add the Customer Account screens, which are mobile-friendly and distinct from Public Tracking |

## 3. Cases explicitly **not** affected

| Group | Why |
|---|---|
| `UAT-OP-01` … `UAT-OP-11`, `UAT-OP-14` … `UAT-OP-20` | Staff booking, packages, labels, milestones, tasks, segments and revenue. The Customer Account creates no booking and edits no shipment |
| `UAT-MK-01` … `UAT-MK-04` | Marketing segments and boundaries. No Marketing permission is granted by this work |
| `UAT-RM-01` … `UAT-RM-03` | Read-only manager. Unchanged |
| `UAT-XX-01`, `UAT-XX-02` | **Public Tracking stays exactly as it is.** The 24-field contract does not move, and the Customer Account does not replace it |
| `UAT-XX-03` … `UAT-XX-11` | Import, export and reports. Untouched |
| `UAT-XX-12`, `UAT-XX-14` | Keyboard access and the Vietnamese staff interface. The Customer Account ships English-only (OD-39) and has its own accessibility work |
| `UAT-AD-02` … `UAT-AD-06` | Staff accounts, merges, financial visibility, integration health |

## 4. Review sheets

| Sheet | Impact |
|---|---|
| `REVIEW_accessibility.md` | Unchanged for the Staff Portal. **A separate Customer Account accessibility review is needed** before launch, and OD-19 — no reviewer assigned — blocks it exactly as it blocks the existing one |
| `REVIEW_vietnamese_ui.md` | **No impact.** The Customer Account is English-only (OD-39); its Vietnamese review is a *future* sheet, not an addition to this one |
| `REVIEW_vietnamese_templates.md` | No impact. The 17 public update templates are unchanged |
| `REVIEW_physical_label.md` | No impact. No label work |
| `REVIEW_customer_account_copy.md` | **Written at Phase 12, and blank.** Customer-facing English copy, including the generic security messages, reviewed for wording that does not disclose |

## 5. Owner decisions that block the new pack

| Decision | Blocks |
|---|---|
| **OD-34** — email provider | Production execution of every registration and recovery case. Development capture allows local execution |
| **OD-37** — terms and privacy text | Production execution of registration; local execution uses placeholder versions **clearly marked as placeholders** |
| **OD-19** — accessibility reviewer | The proposed Customer Account accessibility review |
| **OD-22** — return workflow | Any case about linked return **records**. Return *statuses* are testable, as in the existing pack |
| **OD-01** — retention | Any case about canonical deletion. None is proposed |

## 6. Baseline and counting

`scripts/verify_rc_baseline.py` counts cases in **`docs/UAT/UAT_CASES.md` only** — checked,
not assumed. The new pack is a separate file, so the baseline's UAT figure does not move: it
still reports 49 against the frozen 45, the documented drift the role merge produced, and
this phase adds no new drift to it.

That also means the new pack is **not** covered by the baseline count. Its 51 cases are
tracked here and in the pack itself, and if the two ever disagree, the pack is right and this
line is stale.

**The eight baseline invariants are untouched by this phase**: the 24-field public contract,
zero production adapters, both provider allowlists empty, `manual` and `external_link` only,
`connected_api` excluded, integration health `not_configured`, no provider webhook, no
external provider request.


---

## 7. What Phase 10 changed about this map (2026-09-20)

**Nothing is invalidated and nothing is renumbered**, for the same reason as before: the
Customer Account is a separate surface and the existing pack tests the Staff Portal and
Public Tracking, neither of which Phase 10 changes in a way a case would notice.

**The new-pack figure moves from 28 to 39.** Eleven `CA-APR-*` cases were added for the
behaviours Phase 10 built: the disclosure figures, ownership that ignores a matching sender
address, two kinds of drift, the separate-customer override, merged and archived link
targets, linking that writes nothing, an idempotent retry, the two refused roles, what a
rejection does to a live session, and the fact that an approved account still sees no
shipment history.

**Every one of them is `Blocked` until Phase 12**, and the pack's header now says so
explicitly: each step names a screen, and there is no screen. The behaviour is reachable
over the staff API and is covered by automated tests; that is not the same as the case
having been executed, and recording it as a Pass would be recording something that did not
happen.

### One existing-pack assertion moves from "add when built" to "addable now"

| Case | Status after Phase 10 |
|---|---|
| **UAT-AD-07** — audit log records a material change | The approval audit entry now exists, with actor, reason code, the disclosure figures and no credential material. The sentence can be added to the case as soon as a screen exists to produce it from |
| **UAT-OP-12** — near-duplicate held for review | The customer-submitted path now runs through the same `duplicate_service`, and nothing merges automatically. Same caveat |
| **UAT-OP-13** — consent then suppress | A customer-side marketing opt-in is now written *at approval*, and a suppression refuses it silently. Same caveat |
| The other three | Unchanged; they wait on Phases 11 and 12 |

### Two things a tester should be told before Phase 12

* **There is no approval screen.** Approving an account today means calling the staff API.
* **A rejected applicant has no way back.** Admin reinstatement is specified
  (`STATE_MACHINES.md` transition 9) and not built, so a rejection in a UAT environment is
  effectively final for that address. Use a fresh address rather than trying to recover one.

### The baseline figure still does not move

`scripts/verify_rc_baseline.py` counts `docs/UAT/UAT_CASES.md` only — still 49 against the
frozen 45, still the role-merge drift, and Phase 10 adds none of its own. The eight
substantive baseline invariants are untouched.

---

## 8. What Phase 11 changed about this map (2026-09-21)

**Nothing is invalidated and nothing is renumbered.** The existing pack tests the Staff
Portal and Public Tracking; Phase 11 adds two authenticated Customer Account read routes and
changes neither of those surfaces. Every result field in the existing pack is still blank.

**The new-pack figure moves from 39 to 51.** Twelve `CA-SHP-*` cases were added for the
behaviours Phase 11 built: an empty history, drafts and demo records staying invisible, the
two approved filters, the date boundary in the organization's timezone, dates matching the
Staff Portal, paging that loses and repeats nothing, one failure shape across four ways of
asking wrongly, suspension and customer archive taking effect on the next request, a new
shipment appearing without a sign-out, the planted-private-value check done by eye, and the
absence of any control that changes anything.

**Every one of them is `Blocked` until Phase 12**, for the same reason the `CA-APR-*` cases
are: each names a screen, and there is no screen. The behaviour is reachable over the API and
is covered by automated tests; recording that as a Pass would be recording something that did
not happen. The pack's header table now says `CA-SHP-*` is "backend only" rather than "not
executable", which is the only sentence in it that moved.

### Two existing-pack assertions move from "add when built" to "addable now"

| Case | Status after Phase 11 |
|---|---|
| **UAT-XX-15** — staff data never visible to the public | The authenticated customer surface now exists to extend the case to. The sentence to add: no internal field, no financial value, no recipient detail beyond a city, and no other customer's shipment. Still needs a screen to execute against |
| **UAT-AD-07** — audit log records a material change | A refused shipment read now writes an audit row with the identity, a bounded reason code, a keyed reference digest and no credential material. Addable; same caveat |
| The other four | Unchanged; they wait on Phase 12 |

### One thing a tester should be told before Phase 12

**A refusal never says why.** Pending approval, a revoked link, an archived linked customer
and a merged one all produce one sentence, deliberately. A tester who needs to know which
applies reads the `outcome` field in the application log — `docs/OPERATIONS.md` §14.5 maps
each one to what the customer should actually be told. Filing a defect because "the message
does not explain the problem" would be filing a defect against the design.

### The baseline figure still does not move

`scripts/verify_rc_baseline.py` counts `docs/UAT/UAT_CASES.md` only — still 49 against the
frozen 45, still the role-merge drift, and Phase 11 adds none of its own. The eight
substantive baseline invariants are untouched: the 24-field public contract, zero production
adapters, both provider allowlists empty, `manual` and `external_link` only, `connected_api`
excluded, integration health `not_configured`, no provider webhook, no external provider
request.

---

## 9. What Phase 12 changed about this map (2026-09-21)

**Nothing is invalidated and nothing is renumbered.** The existing pack still tests the
Staff Portal and Public Tracking. Phase 12 adds a customer-facing surface, two Staff
Portal screens, and two list filters; it changes no existing staff screen and no public
one. Every result field in `UAT_CASES.md` is still blank.

**The six "add when built" assertions are now added.** Section 2 has been holding them
since Phase 8. Each is in the pack as an **`Added at Phase 12`** row on its existing case
— `UAT-AD-01`, `UAT-AD-07`, `UAT-OP-12`, `UAT-OP-13`, `UAT-XX-13`, `UAT-XX-15` — and none
of the six cases was rewritten, renumbered or given a result. The file still holds exactly
49 cases.

**The new-pack figure moves from 51 to 59.** Eight cases were added for behaviour that had
no screen to test before:

| Case | What it is for |
|---|---|
| `CA-REG-09` | The production-email gate, as a customer meets it: a plain sentence naming no configuration |
| `CA-SHP-19` | An unknown reference, a foreign one and a malformed one, compared word for word on the detail page **and** through the new reference filter |
| `CA-SEC-05` | Every sign-in refusal reads the same, across four differently-broken accounts |
| `CA-SEC-06` | The declined and unavailable states, held against the reason code staff can see |
| `CA-SEC-07` | What a verification or reset link leaves in the address bar, the history and the page source |
| `CA-XP-01` | The whole surface at 375 × 812 |
| `CA-XP-02` | The whole surface from the keyboard |
| `CA-XP-03` | English only, with no switch to find |

**Every `CA-*` case is now executable, except four.** The pack's header table says which.
`CA-PRF-01` … `CA-PRF-04` are **out of scope**, not blocked by a decision: *My
information* and *Notification preferences* are customer profile editing and customer
consent management, and the owner's Phase 12 instruction excludes both by name. No screen
was built and no route exists. They are recorded as `Blocked` with "screen not in scope at
Phase 12", and they become executable when the owner authorises the screens — which is a
new instruction, not an omission.

### The fifth review sheet exists

`REVIEW_customer_account_copy.md`, proposed in section 4, is written and **blank**. It
covers the 32 screens, the six message templates, the nine sentences that are deliberately
uninformative, and the staff terminology that must not appear. Completing it approves the
**English** copy and closes neither OD-39 nor OD-37.

`REVIEW_vietnamese_ui.md` gains five screens — the staff approval queue and review, at
rows 26 to 30 — because the Staff Portal is bilingual and those screens added roughly
ninety Vietnamese strings. They are unreviewed, like the rest of that catalogue. The
**Customer Account** adds none: it is English-only and renders no language control at all.

### The baseline figure still does not move

`scripts/verify_rc_baseline.py` counts `docs/UAT/UAT_CASES.md` only. RC-UAT-3 froze 45 and
the file holds 49 — the role-merge drift, unchanged. RC-UAT-4 re-freezes at 49, so that
drift closes against the new baseline and no new one is introduced. The eight substantive
invariants are untouched: the 24-field public contract, zero production adapters, both
provider allowlists empty, `manual` and `external_link` only, `connected_api` excluded,
integration health `not_configured`, no provider webhook, no external provider request.

### Three things a tester should be told before starting

* **Mail is a file, not a page.** There is no mailbox screen and there will not be one; a
  verification link is read out of `data/account_mail/`. `docs/OPERATIONS.md` §15 is the
  procedure, and it also explains the two behaviours that look like faults — a resend
  invalidates the previous link, and a second registration for the same address sends no
  second verification.
* **A refusal still never says why.** Pending approval, a revoked link, an archived linked
  customer and a merged one all produce one sentence. Filing a defect because "the message
  does not explain the problem" is filing a defect against the design.
* **A rejected applicant still has no way back.** Admin reinstatement is specified
  (`STATE_MACHINES.md` transition 9) and is still not built. Use a fresh address rather
  than trying to recover one.
