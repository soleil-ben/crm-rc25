# RC-UAT-3 — the release-candidate baseline in force

> ## ⚠ THIS IS NOT A PRODUCTION RELEASE
>
> `RC-UAT-3` is a **pre-release identifier**. It carries no production release number and
> no production-ready label. It means one thing: *this is the exact build handed to human
> UAT.* It is not evidence that the application works for the people who will use it.
>
> Production deployment remains **prohibited** (OD-20: nobody is yet authorised to perform
> one).
>
> **No UAT case has been executed.** All 45 result fields, all 45 defect fields, every
> progress count and every review-sheet identity field are blank.

---

## 1. What is frozen

| | |
|---|---|
| Identifier | `RC-UAT-3` |
| Supersedes | `RC-UAT-2`, frozen 2026-09-15 and preserved unchanged |
| Also preserved | `RC-UAT-1`, frozen 2026-09-14 and preserved unchanged |
| Branch | `phase-6-release-candidate-uat` |
| Measured at commit | `98f1fdece89254ae92905843ee494f599c6ea97e` |
| Register commit | `c3ed3525b361492d5444c07e5f0cecca0176f2c7` |
| Phase 5B closure commit | `8621b9e66b8eb7a69074061d583afc71d0b5e6de` |
| Alembic head | `e5623fcf8018` |
| Frozen | 2026-09-15 |

Machine-readable copy: `docs/RC_UAT_3_BASELINE.json`. That file, not this one, is what the
verification command reads.

### Why RC-UAT-2 was superseded

**Application code changed this time**, which was not true of the last supersession.

| Change | Why it forced a new candidate |
|---|---|
| `report_service.shipment_status` | The **Returns** row no longer carries the dead `/shipments?returns_only=true` drill-through. It keeps its value and label and gains a neutral note |
| `report_service.follow_up_workload` | Three of four rows named parameters nothing reads. `?view=open` and `?view=due` were not tab ids, so the page rendered **no panel at all** |
| `dashboard_service` | `/shipments?status=active` filtered nothing; `/follow-ups?view=due` rendered no panel. The Active-shipments link is now built from the same constant as its count |
| `DashboardPage.jsx`, `GlobalSearch.jsx` | Two inert query parameters dropped — `?task=` and `&package=` — neither read by its destination |
| `docs/OWNER_DECISIONS.*`, `scripts/verify_owner_decisions.py` | The register restored to 22 complete records; the verifier extended to prove it |

A baseline is the tree that was tested. A staff screen behaves differently, so the
identifier moved.

`docs/RC_UAT_1_BASELINE.md` and `docs/RC_UAT_2_BASELINE.md` are **unchanged** and both are
still verifiable:

```bash
backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_1_BASELINE.json
backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_2_BASELINE.json
```

Both reported **all 10 checks match** at this commit.

### Toolchain

| | |
|---|---|
| Python | 3.12.10 |
| Node | 24.11.1 (npm 11.6.2) |
| SQLite | 3.49.1 |

Unchanged from RC-UAT-1 and RC-UAT-2, as are both dependency-lock digests.

### Counts

| | | |
|---|---|---|
| Backend tests | 1256 passed, **0 skipped** | 1244 + 12 navigation guards |
| Frontend unit tests | 223 passed (16 files) | 219 + 4 linkless-row tests |
| Playwright tests | 149 passed, 0 skipped, 0 failed, **retries 0** | run three times consecutively |
| Accessibility screen states | **32** (25 staff, 7 public) | **re-measured — see below** |
| Accessibility audit invocations | **64** | 32 states × 2 viewports |
| Audited viewports | 2 — 1280×800 and 375×812 | unchanged |
| UAT cases | 45, **0 executed** | unchanged |

### Invariants — the things that must not move

| | |
|---|---|
| Public tracking contract | exactly **24** fields |
| Production adapters registered | **0** |
| Integration resource host allowlist | **0** |
| Integration resource path-prefix allowlist | **0** |
| Tracking source modes | `manual`, `external_link` — `connected_api` refused |
| Integration health | `not_configured` |
| Provider webhook routes | **none exist** |
| Public correlation header | **absent** — the staff API carries `X-Correlation-ID`, the public API does not |

---

## 2. Verifying the baseline

```bash
backend/.venv/Scripts/python scripts/verify_rc_baseline.py
```

Exit status 0 means every check matches; 1 means something drifted, and the output names
what. `--json report.json` writes the full report. `--baseline <path>` checks a different
baseline file — that is how RC-UAT-1 and RC-UAT-2 stay verifiable.

It deliberately does not assert test counts, for the reason RC-UAT-1 gave and this
candidate demonstrates again: adding a guard changes them.

---

## 3. Accessibility evidence, re-measured

**Not carried forward.** RC-UAT-2 recorded its accessibility figure as "carried forward
from RC-UAT-1 and not independently re-measured". This candidate measured it from the axe
attachments a complete run actually produced.

**The carried-forward figure was wrong.** RC-UAT-1 and RC-UAT-2 both recorded *34 audit
calls (26 staff, 8 public)*. That came from `grep -c auditAndAssert` against the two specs
— which counts the `import { auditAndAssert, ... }` line in each file. Two of the 34 were
import statements.

| Measured | Value |
|---|---|
| Distinct screens or states audited | **32** — 25 staff, 7 public |
| Audit invocations | **64** |
| Viewport sizes | **1280 × 800** (32 invocations) and **375 × 812** (32 invocations) |
| Critical violations | **0** |
| Serious violations | **0** |
| Moderate violations | 0 |
| Minor violations | 0 |
| Rules suppressed | **0** — `EXPECTED_FINDINGS` is empty; there is no global `disableRules` |
| Tests skipped | **0** — six conditional `test.skip` guards exist, none fired |
| axe `incomplete` (needs human review, not a violation) | `color-contrast` on 34 of 64 audits |

### Screens changed by the return-report correction, and re-audited

| Screen | What changed |
|---|---|
| `staff-reports` | The shipment-status Returns row lost its link and gained a note |
| `staff-reports-filtered` | Same table, filtered |
| `staff-dashboard` | The **Active shipments** and **Follow-ups due** card links changed |

All three were audited at **both** viewports after the change: 0 serious, 0 critical.

### Automated auditing is not human validation

No screen reader has been run against this application. No zoom level above 100% has been
tested. Forced-colors mode has not been exercised. Only Chromium has been used. No disabled
person has used it. **OD-19 is open** and nobody has been assigned to perform the human
review. The distinction is not a caveat on the number above — it is most of what decides
whether the application is usable.

---

## 4. The blank page: still unexplained, still not recurring

| | |
|---|---|
| First seen | RC-UAT-1, `staffKeyboard.spec.js:212`, run 5 of 7 — a blank rendered page |
| Investigated at | RC-UAT-2: 37 consecutive repetitions of the test and its file, plus three complete suites — no reproduction |
| At RC-UAT-3 | **Three consecutive complete suites at this commit. 149 passed each time. No failure, no diagnostic bundle.** |
| Classification | **Unresolved intermittent observation.** Not a fixed defect |

`retries` is 0 throughout, one worker, no sleep added to any test. No cause has been found
and nothing has been changed that would have addressed it. Six clean suites across two
candidates do not prove absence.

What is in place is the failure-only diagnostic capture added at RC-UAT-2
(`frontend/tests/e2e/diagnostics.js`, pinned by `frontend/tests/e2eDiagnostics.test.js`):
if it recurs, the bundle is produced in one shot. **If it recurs during human UAT, preserve
and report the diagnostic bundle before changing anything.**

---

## 5. Provisional dispositions in force for RC-UAT-3

**Temporary UAT dispositions, not owner decisions and not production approval.** The
register is `docs/OWNER_DECISIONS.md`; a disposition is counted there as **open**.

| Item | Disposition for RC-UAT-3 | Decision |
|---|---|---|
| `PUBLIC_CARRIER_LINK_HOSTS` | **9 hosts retained provisionally**, so external-link tracking can be exercised | OD-07 — open for production |
| Integration resource host allowlist | **empty** | OD-21 — provider-only |
| Integration resource path-prefix allowlist | **empty** | OD-21 — provider-only |
| Production adapter registry | **empty**; `connected_api` refused | OD-21 — provider-only |
| `PUBLIC_HELP_URL` | **empty** — UAT **validates the omission** of the optional link | OD-06 — open for production |
| MFA | **not implemented**, not decided | OD-17 — open |
| Retention deletion | disabled | OD-01 — open |
| Shipment import | deferred pending real source data and a mapping contract | OD-15 — open |
| Legacy aggregate history | deferred pending real source data | OD-16 — open |
| Vietnamese text | **unreviewed**, staff catalogue and customer templates alike | OD-08, OD-09 — open |
| Proxy-header trust | disabled | DEC-0087 |
| Production deployment | **prohibited** | OD-20 — open |
| **Return shipment records** | **no workflow creates one; none in any dataset** | **OD-22 — open** |

The nine carrier hosts are **retained for UAT, not reviewed or approved for production**.

---

## 6. Owner decisions at this freeze

| | |
|---|---|
| Recorded | **22** — OD-01 through OD-22, every identifier resolving to a complete record |
| Identifiers with no record | **0** |
| Answered | **0** |
| Open | **22** |
| Of the open, carrying a temporary disposition | **7** |
| Blocking human UAT | **5** — OD-08, OD-09, OD-17, OD-18, OD-19 |
| Blocking production | **15** |
| Provider-only | **1** — OD-21 |

Two blocking flags changed at this freeze, and `docs/OWNER_DECISIONS.md` section 3 says why:
**OD-06** no longer blocks local UAT (the omission is the behaviour under test), and
**OD-22** no longer blocks local UAT (no case in the pack depends on a return record, and
the control that promised one is gone). Both remain **open and unanswered**.

---

## 7. What this baseline does not prove

Everything `RC-UAT-1` section 5 and `RC-UAT-2` section 5 recorded still stands:

* no disabled person has used this application, and no screen reader has been run against it;
* no label has been printed on a thermal printer and no barcode has been read by a scanner;
* the Vietnamese wording is unreviewed in both the staff catalogue and the 17 customer templates;
* the blank-page observation is **not explained**;
* no return shipment record has ever existed in this system;
* **no UAT case has been executed by anyone.**

Added by this candidate: **a report row that had been handed to testers pointing at nothing
is now pointing at nothing visibly, rather than silently.** That is a correction, not
evidence that the reports are right — only a human executing UAT-XX-09 can say that.
