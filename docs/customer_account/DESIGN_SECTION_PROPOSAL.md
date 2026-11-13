# Proposed `Design.md` section — Customer Account

> **ACCEPTED 2026-09-21.** The owner accepted this proposal as the Phase 12 baseline. It
> is now `Design.md` **section 14a**, inserted between the existing sections 14 and 15 with
> no historical section edited and no number moved. Four deviations were carried by the
> acceptance and are listed in `Design.md` §14a.8 — most consequentially, *My information*
> and *Notification preferences* are **not** built, because the Phase 12 instruction
> excludes customer profile editing and customer consent-management screens by name.
>
> **This file is kept unchanged below as the record of what was proposed.** Read
> `Design.md` §14a for what was accepted; where the two differ, §14a is the specification.

---

**This was a proposal for the owner to accept, not an edit.**

`Design.md` is the owner's design specification, version 1.0, dated September 2026. It has
fourteen product sections and **none of them describes an authenticated customer surface**:
section 14 is Public Tracking, which is unauthenticated and reference-based. Under this
project's conventions an owner document is not rewritten in place, so the section is proposed
here in full. **Until it is accepted, no Customer Account screen has an approved visual
specification, and the frontend phase is blocked** — not by anything technical, but because
building screens first and approving them afterwards is how a design specification becomes
decorative.

Numbering: this would sit as a new **section 14a**, immediately after Public Tracking, so
the two customer-facing surfaces read together and the existing numbering does not shift.

---

## Proposed section 14a — Customer Account experience

### 14a.1 What this surface is

The **Customer Account** is the authenticated self-service surface for customers who ship
with Solaris Express. It is **not** the Staff Portal and **not** Public Tracking.

* "Portal", unqualified, means the internal staff CRM. This surface is never called the
  portal.
* Public Tracking stays exactly as section 14 describes it. The Customer Account does not
  replace it, and the 24-field public contract does not change.
* Release 1 is English only.

### 14a.2 Layout direction

A **third layout**, sharing the brand foundation of section 3 and nothing else:

* the Solaris wordmark and the section 3 colour tokens, type scale and spacing;
* **no staff navigation** — no sidebar, no staff search, no internal counts;
* **not the Public Tracking card** either: this surface is signed in, has several screens,
  and needs navigation between them;
* a slim top bar: wordmark, the two or three destinations, and an account menu.

**Mobile-friendly, and distinct from Public Tracking.** `Design.md` section 2 sets
"mobile-first for public tracking"; the Customer Account follows the same instinct — a
customer checking a parcel is usually on a phone — with its own navigation and its own
screens rather than a reuse of the tracking card.

### 14a.3 Screens

| Screen | Composition |
|---|---|
| **Sign in** | Centred card; email, password, sign-in, forgot-password link, register link. One generic failure message |
| **Register** | Single-column form grouped as *about you*, *addresses*, *preferences*. Terms acknowledgement and marketing consent are **separate, unchecked controls** with visible wording |
| **Check your email** | Plain confirmation, identical for every outcome. No hint about whether an account exists |
| **Verify / reset landing** | One outcome message; no account detail |
| **Account pending** | A calm state card: what has happened, what happens next, and no shipment data |
| **My information** | Current values, the two directly editable preferences, and proposed changes with their state clearly marked as *awaiting review* |
| **My shipments** | Card list on mobile, table on wide screens. Reference, date, route, destination city, status, package counts. Cancelled and rebooked rows visibly marked, never hidden |
| **Shipment detail** | Summary card, package cards, vertical timeline — the same *values* Public Tracking shows, presented for a signed-in reader |
| **Notification preferences** | Operational preferences and marketing consent visibly separate, both unchecked by default |

### 14a.4 States that must be designed, not left to chance

* **Pending** — the most common first experience. It must read as "we have your application"
  and not as an error.
* **Empty history** — an approved account with no shipments gets a plain sentence, not an
  error and not an invitation to search for someone else's.
* **Cancelled / rebooked** — visible, clearly marked, never silently removed.
* **Generic refusals** — sign-in failure, unknown token, expired link and rate limiting all
  read as neutral, unalarming sentences that reveal nothing.
* **Rate limited** — say when to retry, as Public Tracking already does.

### 14a.5 Accessibility

Section 15 applies unchanged: WCAG 2.2 AA, visible focus, 4.5:1 text contrast, keyboard
operation throughout, and colour never carrying meaning alone. Status is always accompanied
by text.

A **separate accessibility review sheet** is required for this surface before launch. OD-19
— no reviewer assigned — blocks it exactly as it blocks the existing one.

### 14a.6 What the design must never show

No financial value. No internal tag, note, interaction, lifecycle status, assigned staff
member, duplicate score or audit entry. No other customer's data. No recipient contact
detail. No staff terminology anywhere in the interface — a customer reads "shipment", not
"booking state".

### 14a.7 Language

English only in release 1 (OD-39). No language switch is shown until a qualified reviewer has
approved the Vietnamese customer-facing UI, the verification and password-reset messages, the
privacy and terms wording, and the operational notification wording. **Partially translated
screens do not ship.**

---

## How to accept this

1. Read the section above alongside `docs/customer_account/PRODUCT_SPEC.md`.
2. Accept it as written, or return changes.
3. On acceptance it is added to `Design.md` as section 14a, with the version and date of that
   document updated by the owner — which is the point at which `Design.md` stops being a
   version 1.0 artifact and becomes 1.1.

Until then this file is the only place the Customer Account design exists, and it is a
proposal.
