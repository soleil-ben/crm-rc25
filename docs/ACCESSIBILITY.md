# Accessibility

What was audited, what was found and fixed, what was walked through by keyboard, and —
at some length, because it matters — what none of this establishes.

> **An automated audit is not an accessibility certification.** axe-core checks what a
> machine can check. Published estimates put that at roughly a third of WCAG success
> criteria, and the ones it cannot check are not the easy ones: whether a label is
> *meaningful*, whether an error message tells a person what to do, whether reading order
> makes sense, whether a Vietnamese sentence says what it should. **No disabled person has
> used this application.** Until that happens, everything below is evidence of care, not
> evidence of accessibility.

---

## 1. What runs, and when it fails the build

| | |
|---|---|
| Tool | axe-core 4.13.0 via `@axe-core/playwright` |
| Standard | WCAG 2.2 AA (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`) |
| Viewports | **1280 × 800** and **375 × 812**, every screen at both |
| Fails the build | Any **serious** or **critical** violation |
| Reported, does not fail | moderate and minor |
| External requests | **None.** A route guard fails the test if a page reaches any off-origin URL |

```bash
# Both applications must be running against the seeded demo database first --
# docs/OPERATIONS.md section 8 has the exact commands.
npx playwright test --prefix frontend accessibility.spec.js staffAccessibility.spec.js
```

Moderate and minor findings are printed but do not fail. That line is drawn at axe's own
severity scale rather than at zero, because a suite that fails on every minor finding is a
suite somebody eventually disables — and a disabled suite catches nothing at all.

### Nothing is suppressed

There is no `disableRules` anywhere. Exceptions would live in `EXPECTED_FINDINGS` in
`frontend/tests/e2e/axeHelpers.js`, keyed by screen *and* rule, each requiring a written
justification. **It is currently empty**: every finding was fixed rather than excused.

A test fails if an exception is ever added and then stops matching anything, so a
suppression cannot outlive the finding it was written for.

### Screens covered

Public: lookup form, successful result, failed lookup, Vietnamese result, exception
result, cancelled result.

Staff: login, dashboard, customer list, customer detail, customer creation, customer
creation with validation errors, duplicate review, shipment list, shipment detail, booking
workflow, label preview, follow-ups, segments, settings, integration-infrastructure
status, reports, reports filtered, reports range error, report export, CSV export, import
upload, import mapping and validation preview, import duplicate decisions, import
confirmation, import result, rejected import file.

---

## 2. What the audit found

Three serious violations. All three were real. **None was a false positive**, and two were
defects in `Design.md` rather than in the implementation.

### 2.1 White text on the primary button — 3.30:1 (serious)

`Design.md` section 3 specifies `brand.orange.600` as `#E9652A` and annotates it
*"selected to retain white-text contrast"*. Measured, white on `#E9652A` is **3.30:1**.
WCAG AA requires **4.5:1** for normal text. The annotation is simply wrong.

This was not a corner case. It was **every primary button in both applications** — Track,
Sign in, Save, Add customer, Import — on every screen.

Section 15 of the same file requires WCAG 2.2 AA, so `Design.md` contradicts itself. The
accessibility requirement is what the token was reaching for, so the requirement wins and
the value is corrected (DEC-0086).

| | Before | After |
|---|---|---|
| `--brand-orange-600` | `#e9652a` — 3.30:1 | `#c94d15` — **4.61:1** |

### 2.2 Teal route badge — 3.99:1 (serious)

`Design.md` pairs `accent.teal.600` as badge text with `accent.teal.100` as its
background. Measured: **3.99:1**, against the 4.5:1 that 12 px badge text needs.

This is the route badge, repeated on every row of the customer list and the shipment list
— probably the most-repeated element in the staff interface.

| | Before | After |
|---|---|---|
| `.badge--teal` colour | `--accent-teal-600` `#16867d` — 3.99:1 | `--accent-teal-700` `#147b73` — **4.61:1** |

### 2.3 Public footer wordmark — 2.61:1 (serious)

`brand.orange.500` on the light footer. This one is an implementation defect against
`Design.md`, not a defect in it: section 3 says to set "Express" in Solaris Orange
*"where contrast permits"*, and here it did not.

### The replacements are the same colours, deeper

Every corrected value keeps the brand hue (18.5° for orange, unchanged for teal) and the
saturation **exactly**, and moves only lightness. Nothing was re-hued, and the brand still
reads as itself.

| Token | Value | Verified |
|---|---|---|
| `--brand-orange-600` | `#c94d15` | white on it 4.61:1 |
| `--brand-orange-700` | `#bd4814` | as text: 5.12 on white, 4.89 on app background, 4.60 on the orange badge |
| `--brand-orange-500` | `#f47a3a` *(unchanged)* | non-text fills, and text on navy only (5.36:1) |
| `--accent-teal-700` | `#147b73` | as text: 5.11 on white, 4.88 on app background, 4.61 on the teal badge |
| `--accent-teal-600` | `#16867d` *(unchanged)* | non-text accents, where 3:1 applies |

### The wordmark, and why every screen is audited

The wordmark accent is now **contextual**, and the route to that was instructive.

Fixing the light footer with a single darker colour **broke the navy header**, where the
darker ink measures 3.02:1 and the lighter one 5.36:1. The audit caught it on the next
run. Then the same mistake again on the login page, whose background I had assumed was a
light card and which is in fact navy — caught again, reverted, and commented in
`login.css` so the next person checks the surface before darkening the ink.

Auditing every screen rather than one representative screen is what found both
regressions. That is the argument for the breadth of the list in section 1.

---

## 3. Keyboard walkthroughs

Eight workflows, plus two structural checks. **Performed, not asserted** — they run in CI
as `frontend/tests/e2e/staffKeyboard.spec.js`, and they use only `keyboard.press` and
`keyboard.type`. No `click()`, no `fill()`, no `focus()`: a helper that reached for the
mouse to get past an awkward step would prove nothing.

`tabTo` walks the real focus order and fails if a control is never reached, printing the
whole order it saw. Calling `locator.focus()` instead would answer an easier question than
the one being asked.

**Last run: 2026-09-14. 11 of 11 passed.**

| # | Workflow | Result | What it establishes |
|---|---|---|---|
| 1 | Customer creation | **Pass** | Drawer opens, traps focus, first field takes focus, Vietnamese name types correctly, submit reachable, record appears |
| 2 | Tracking assignment | **Pass** | Tablist reachable, Arrow keys move within it, and **no `connected_api` control exists to select** (DEC-0075) |
| 3 | Booking confirmation | **Pass** | Customer field and the continue control are both reachable in order |
| 4 | Package and event updates | **Pass** | Inline event form opens from the keyboard; its fields and submit are reachable |
| 5 | Label printing | **Pass** | Dialog opens, traps focus; Print and Download PDF reachable |
| 6 | Task completion | **Pass** | Task completes, and focus does **not** fall back to `<body>` |
| 7 | Report filtering and export | **Pass** | Dates, apply, and export all reachable; the CSV download actually starts |
| 8 | Complete import flow | **Pass** | Upload → preview → import → focus-trapped confirmation → result → duplicate decision |
| — | Skip link | **Pass** | First tab stop on every staff page; moves focus into `<main>` |
| — | Focus indicator | **Pass** | Every control in the shell shows a visible ring |

### What the walkthroughs confirmed about the design

Three things the implementation already had right, recorded because the first draft of the
tests mistook each of them for a defect:

- **Tab panels use roving tabindex.** Tab reaches the tablist once; Arrow keys move
  between tabs. Searching the tab order for each tab found nothing and looked like a bug.
  It is correct ARIA practice.
- **The focus trap focuses the first *field*, not the close button**, on a short timer, so
  a keyboard user lands where they will actually type. Asserting focus immediately read it
  before it had moved.
- **Recording a milestone is an inline form, not a modal** — a deliberate choice, and the
  better one: the timeline stays on screen while the event is described.

### The one step a keyboard cannot finish unaided

**Choosing a file for import.** Activating the file input opens the operating system's own
file dialog, which is outside the page and outside the browser's control. The input itself
is reachable and labelled, which is the part that is the application's responsibility; the
walkthrough supplies the bytes the way the OS dialog would. This is a property of file
inputs on the web, not a defect here, and no workaround exists at the application level.

---

## 4. Bilingual parity

| Check | Status |
|---|---|
| English and Vietnamese staff catalogues at full key parity | Enforced by `frontend/tests/i18n.test.js` |
| Public catalogue parity | Enforced by `frontend/tests/publicI18n.test.js` |
| Public update templates in both languages | 17 templates × 2, enforced by `test_public_update_templates.py` |
| A Vietnamese result audited at both viewports | `public-result-vietnamese` |
| Vietnamese diacritics preserved through import and export | Existing E2E coverage |
| Long Vietnamese text does not overflow at 375 px | `publicTracking.spec.js` |

**The Vietnamese wording itself is unreviewed** — both the staff catalogue and the 17
customer-facing templates. Key parity means nothing is missing; it says nothing about
whether the sentences are right. That remains an open owner decision
(`PROJECT_STATUS.md` section 9).

---

## 5. Reflow, colour, and charts

| Requirement | How it is met |
|---|---|
| No horizontal scroll at 375 px | Asserted for public tracking; the staff audit runs at 375 × 812 throughout |
| Reflow to one column | Content-driven layout per `Design.md` section 16 |
| No meaning from colour alone | Every status carries a text label as well as a token; the exception report names its tracking modes in words |
| Charts have an equivalent | Every dashboard chart has a **"Show as a table"** control in the tab order; reports are tables first, with the figures as text |
| Focus ring | 2 px ring via `box-shadow`, present on every shell control |
| Reduced motion | `prefers-reduced-motion` respected (`Design.md` section 17) |

---

## 6. What this does not establish

Stated plainly, because the gap between "the audit passes" and "the application is
accessible" is where accessibility work usually goes wrong.

- **No disabled person has used this application.** No screen-reader user, no
  keyboard-only user, no low-vision user, no user with a cognitive disability. This is the
  single largest gap and nothing below substitutes for it.
- **No screen reader has been run against it.** Not NVDA, not JAWS, not VoiceOver, not
  TalkBack. Accessible names exist and are asserted; whether the resulting announcement is
  *useful* is unknown.
- **axe covers roughly a third of WCAG.** It cannot judge meaningfulness, reading order,
  or whether an error message helps.
- **Only Chromium was tested.** No Firefox, Safari, or mobile browser.
- **No zoom or magnification testing** at 200% or 400%.
- **No Windows High Contrast Mode testing.**
- **Vietnamese copy is unreviewed** by a native speaker, as is the customer-facing wording.
- **Moderate and minor findings do not fail the build**, so some may be present. They are
  printed on every run.
- **No testing with voice control or a switch device.**
- **Target size (WCAG 2.2, 2.5.8)** is checked only as far as axe checks it.

### The honest summary

The automated audit passes at both viewports with nothing suppressed, three real defects
were found and fixed, and eight workflows can be completed with a keyboard alone. That is
a reasonable place to be before UAT.

**It is not a WCAG 2.2 AA conformance claim.** Making one would require the manual testing
above, and a conformance statement is a legal assertion that should not rest on a tool's
output.

---

## 7. Before launch

| Gate | Status |
|---|---|
| Automated audit, both viewports, no serious or critical | **Closed** |
| Keyboard walkthroughs for the eight workflows | **Closed** |
| Screen-reader pass (NVDA or VoiceOver) on the core workflows | **Open** |
| Testing with at least one disabled user | **Open** |
| 200% and 400% zoom | **Open** |
| Windows High Contrast Mode | **Open** |
| Firefox and Safari | **Open** |
| Vietnamese copy reviewed by a native speaker | **Open — owner decision** |
| A stated conformance position, once the manual passes are done | **Open** |
