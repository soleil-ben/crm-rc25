# Accessibility review — screen reader, zoom, and forced colors

> ## ⚠ NOT TESTED BY A HUMAN
>
> **No screen reader has ever been run against this application, and no disabled person has
> used it.** Every field below is blank and must be filled in by the person who actually
> operated the assistive technology. Claude cannot run a screen reader and must not fill in
> any field.
>
> **Automated axe results are not human screen-reader validation and must never be
> presented as such.** The automated suite audits **32 screen states** — 64 audit
> invocations, each state at 1280 x 800 and again at 375 x 812 — and passes with **0
> serious and 0 critical violations** and **nothing suppressed**. (RC-UAT-1 and RC-UAT-2
> reported 34 states. That figure came from `grep -c auditAndAssert`, which counted the
> `import` line in each of the two specs. RC-UAT-3 re-measured it from the axe
> attachments the run actually produced.) axe checks roughly a third of WCAG: it cannot tell you whether an announcement
> makes sense, whether focus order is usable, or whether a dialog traps focus correctly —
> which is most of what makes this application usable or not.

**Owner decision:** OD-19 — open. Nobody has been assigned to perform this.

**Already known:** only Chromium has been tested. No Firefox, no Safari, no zoom, no
forced-colors mode.

---

## Field classes on this sheet

Four kinds of field appear below, and they must never be confused with one another.

| Class | What it is | State before review |
|---|---|---|
| **Content under review** | The screen, sentence, template or check being judged. Written in advance as part of this sheet | Prewritten — **not** a reviewer's answer |
| **Reviewer response** | What the reviewer judged, observed or would change | **Blank** |
| **Evidence obtained** | What the reviewer actually captured — recordings, transcripts, screenshots, photographs | **Blank** |
| **Result / sign-off** | The outcome, the signature and the date | **Blank** |

Prewritten content is never evidence that this sheet was reviewed. A sheet is reviewed
only when the **Reviewer response**, **Evidence obtained** and **Result / sign-off**
fields have been filled in by the person who did the work.

---

## 1. Tester and environment

| Field | Reviewer response |
|---|---|
| Tester name | |
| Date | |
| Is the tester a regular screen-reader user? (yes/no) | |
| Operating system and version | |
| Browser and version | |
| **Screen reader and version** (NVDA / JAWS / VoiceOver / Narrator / Orca) | |
| Screen reader speech or braille | |
| Keyboard layout | |
| UAT account used | |

> Record the version. Announcement behaviour differs materially between screen-reader
> versions and between screen-reader/browser pairings, and a result without the pairing
> cannot be reproduced.

---

## 2. Screen reader — per screen

For each screen: navigate by heading, by landmark, and by tab. Record what was **announced**,
not what is on screen.

| # | Screen (content under review) | Headings sensible? | Landmarks present? | Form labels announced? | Errors announced? | Tables navigable? | Defects |
|---|---|---|---|---|---|---|---|
| 1 | Sign in | | | | | | |
| 2 | Dashboard | | | | | | |
| 3 | Customer list | | | | | | |
| 4 | Customer detail | | | | | | |
| 5 | Customer create form | | | | | | |
| 6 | Customer form **showing validation errors** | | | | | | |
| 7 | Duplicate review panel | | | | | | |
| 8 | Shipment list | | | | | | |
| 9 | Shipment detail and tabs | | | | | | |
| 10 | Booking wizard | | | | | | |
| 11 | Label preview | | | | | | |
| 12 | Follow-up tasks | | | | | | |
| 13 | Segments | | | | | | |
| 14 | Reports | | | | | | |
| 15 | Reports with an invalid range (error state) | | | | | | |
| 16 | Export controls | | | | | | |
| 17 | Import — upload | | | | | | |
| 18 | Import — mapping and preview | | | | | | |
| 19 | Import — duplicate decisions | | | | | | |
| 20 | Import — confirmation dialog | | | | | | |
| 21 | Import — result | | | | | | |
| 22 | Import — rejected file (error state) | | | | | | |
| 23 | Settings | | | | | | |
| 24 | Empty state | | | | | | |
| 25 | Permission-denied state | | | | | | |
| 26 | Not-found state | | | | | | |
| 27 | Public tracking — lookup form | | | | | | |
| 28 | Public tracking — result | | | | | | |
| 29 | Public tracking — not found | | | | | | |
| 30 | Public tracking — Vietnamese | | | | | | |

## 3. Screen reader — behaviour

| Check | Expected | Reviewer response | Result |
|---|---|---|---|
| Skip link | First tab stop, moves focus into main | | |
| Tab order | Follows visual order, nothing unreachable | | |
| Focus visible | Every focused control shows a visible indicator | | |
| No keyboard trap | Focus can always leave a component | | |
| **Dialog opens** | Focus moves into the dialog and is announced | | |
| **Dialog traps focus** | Tab cycles inside, does not reach the page behind | | |
| **Dialog closes** | Focus returns to the control that opened it | | |
| Escape closes a dialog | Yes, without losing unsaved-state warnings | | |
| Dynamic content | Result counts and status changes are announced | | |
| Error summary | Announced when validation fails, and links to the field | | |
| Tables | Row and column headers announced when moving between cells | | |
| Language | Vietnamese content announced with Vietnamese pronunciation | | |
| Buttons vs links | Announced as the right role for what they do | | |
| Icon-only controls | Have an accessible name that says what they do | | |

---

## 4. Browser zoom

Test both. Reflow is where narrow-viewport bugs appear.

| Check | 200% | 400% |
|---|---|---|
| Any content lost or clipped? | | |
| Any horizontal scrolling of the page body? | | |
| Do tables scroll in their own container rather than the page? | | |
| Are all controls still reachable and operable? | | |
| Does text overlap anything? | | |
| Do dialogs still fit and remain usable? | | |
| Is the Vietnamese text still un-clipped? | | |

| Field | Reviewer response |
|---|---|
| Browser and zoom method (browser zoom, not OS scaling) | |
| Viewport size before zoom | |
| Defects raised | |

---

## 5. Forced colors / High Contrast

Windows High Contrast Mode, or the equivalent forced-colors mode.

| Check | Expected | Reviewer response | Result |
|---|---|---|---|
| Mode used | Record which theme | | |
| All text readable | Nothing invisible against its background | | |
| Focus indicator visible | Still clearly visible in forced colors | | |
| Buttons distinguishable from text | | | |
| Borders and boundaries visible | Cards, tables, inputs still delineated | | |
| Icons visible | Not lost to a background-image rule | | |
| Status colors | Meaning still conveyed when color is overridden | | |
| Charts | Still interpretable, or a text alternative exists | | |
| Selected / active states | Distinguishable | | |

> Status must not be conveyed by color alone. Where it is, that is a defect regardless of
> whether the automated audit passed.

---

## 6. Result / sign-off

| Field | Reviewer response |
|---|---|
| Screens tested | |
| Screens **not** tested | |
| Critical defects | |
| High defects | |
| Medium / low defects | |
| Evidence obtained (recordings, transcripts, screenshots) | |
| Overall result (pass / fail / **blocked — no tester or no AT available**) | |
| Tester signature | |
| Date | |

**Blank is not a pass, and an automated pass is not this.** Until a person signs the table
above, screen-reader, zoom and forced-colors testing remain explicit launch blockers.
