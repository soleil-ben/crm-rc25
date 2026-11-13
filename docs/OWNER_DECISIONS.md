# Owner decisions

Questions only the business can answer. An entry here is **not** an implementation
decision — those are `docs/DECISIONS.md` (`DEC-nnnn`), which records defaults the build
chose and can reverse on its own. An `OD` is something the build cannot decide at all.

> ## Where this register came from
>
> **The register existed in owner-provided conversation material. It had not previously
> been committed to this repository.** Nine identifiers — OD-01, OD-06, OD-07, OD-08,
> OD-09, OD-17, OD-18, OD-19, OD-20 — were being cited across the UAT materials and the RC
> baseline while no committed document defined any of them, so a reviewer handed
> `REVIEW_accessibility.md` and told "Owner decision: OD-19 — open" had nothing to look up.
>
> That absence is a fact about the repository, **not** evidence that the decisions or their
> subjects were never supplied. An earlier reconstruction declared twelve identifiers
> "unrecorded, subject unknown"; that claim was wrong and has been withdrawn. The owner
> supplied all twenty-two subjects, and all twenty-two now have complete records here.
>
> **No owner answer has been invented.** For **OD-01 … OD-22** every `owner_answer` is
> null and every `date_decided` is null. What is written below each decision — current
> behaviour, safest temporary behaviour, options, and the four consequence dimensions — is
> **derived by review** from the repository, and each record's `basis` in the JSON names
> what it was derived from.
>
> ## What changed on 2026-09-21
>
> **OD-41 is answered.** Issued with the Phase 12 instruction, it approves exactly two
> additional authenticated Customer Account shipment-list filters — an exact Solaris
> shipment reference and an exact route group — and no others. It refines, rather than
> reopens, the release-1 filter set fixed by OD-31 and `SHIPMENT_ALLOWLISTS.md` §3.2.
> Its full text is `docs/customer_account/OWNER_DECISIONS_23_39.md` section OD-41.
>
> ## What changed on 2026-09-20
>
> **OD-40 is answered.** It closes the customer-merge/account-link gate Phase 10 left
> open: a customer merge is refused outright while either side holds an active Customer
> Account identity link, rather than moving the link, revoking it, suspending the
> identity, or leaving a live link on a tombstoned record. Its full text is
> `docs/customer_account/OWNER_DECISIONS_23_39.md` section OD-40, and the behaviour it
> requires is `backend/app/services/customer_account_link_policy.py`.
>
> ## What changed on 2026-09-19
>
> **OD-23 … OD-39 are answered**, and their answers are the owner's own words rather than
> this project's proposals. They record the owner's decision to lift the `CRM.md` deferral
> of authenticated customer self-service for a limited **Customer Account** phase — and
> only that deferral. Public booking, provider synchronization and recipient accounts
> remain deferred. The analysis fields on those records — current behaviour, options and
> the four consequence dimensions — are still **derived by review**, exactly as above; only
> `owner_answer` and `date_decided` come from the owner.
>
> Nothing in OD-01 … OD-22 was answered, disposed of, or reworded by that decision.

`docs/OWNER_DECISIONS.json` is the machine-readable register and the authority. The totals
below are **generated** from it by `scripts/verify_owner_decisions.py`. Do not edit them by
hand; edit the JSON and run:

```bash
backend/.venv/Scripts/python scripts/verify_owner_decisions.py --write
```

---

## 1. Totals

<!-- BEGIN GENERATED COUNTS -- edit OWNER_DECISIONS.json, then run scripts/verify_owner_decisions.py --write -->

| Figure | Count |
|---|---|
| **Decisions recorded** | **113** |
| Highest identifier in use | OD-113 |
| Identifiers with no record | 0 |
| Answered | 91 |
| Open | 22 |
| Of the open, carrying a temporary UAT disposition | 7 |
| Blocking human UAT | 5 |
| Blocking production | 17 |
| Provider-only | 1 |
| Known to produce a migration | 26 |
| Migration impact undecided | 11 |

By category:

| Category | Count |
|---|---|
| `configuration_defaults` | 34 |
| `customer_account_surface` | 5 |
| `data_migration` | 2 |
| `hosting_and_recovery` | 4 |
| `language_review` | 8 |
| `permissions_and_authentication` | 12 |
| `physical_and_accessibility_acceptance` | 2 |
| `product_scope` | 24 |
| `provider_integration` | 2 |
| `public_surface` | 8 |
| `release_authority` | 4 |
| `retention_and_privacy` | 8 |
| **Total** | **113** |

A decision may block both UAT and production, so those two rows are independent
tallies and are not expected to sum to the total. A temporary UAT disposition is
not an answer: a disposed decision is counted under **Open**.

<!-- END GENERATED COUNTS -->

---

## 2. What each record must contain

Every record carries all of the following. The verification command fails if any one of
them is missing or empty, so a decision cannot be filed here as a bare title.

| Field | What it holds |
|---|---|
| `decision_required` | The question, stated so the owner can answer it without reading code |
| `affected_feature` | What in the application the answer changes |
| `current_implemented_behavior` | What the code does **today**, not what it should do |
| `safest_temporary_behavior` | The reversible way of proceeding without an answer |
| `options` | The answers actually available, including "no" where "no" is a real answer |
| `consequences.security` | What the answer changes about attack surface and access |
| `consequences.privacy` | What it changes about personal data held, disclosed or retained |
| `consequences.operational` | What it changes about running the business day to day |
| `consequences.user_experience` | What staff or customers will actually see |
| `blocks_local_uat` | Whether any part of human UAT cannot be completed or signed |
| `blocks_uat_case_or_section` | **Which** case ids or review sheets, named |
| `blocks_production` | Whether it must be answered before production use |
| `blocks_provider_integration_only` | Whether it blocks nothing except provider integration |
| `may_require_migration` | `yes` / `no` / `undecided` — never guessed as `yes` |
| `owner_answer` | **Null until the owner answers.** Never a disposition |
| `date_decided` | **Null until the owner answers** |
| `implementation_status` | `not_implemented`, `default_in_force`, `provisional_for_uat`, `deferred`, `disabled` |

---

## 3. The decisions

Blocking flags are **derived by review** from the cited text, not quoted from an owner.

| ID | Decision | Category | Status | Blocks UAT | Blocks production | Provider-only | Temporary UAT disposition |
|---|---|---|---|---|---|---|---|
| **OD-01** | Retention periods by data category | retention_and_privacy | Open | — | Yes | — | Retention deletion disabled |
| **OD-02** | Final Operations permissions | permissions_and_authentication | Open | — | — | — | — |
| **OD-03** | Final Marketing permissions | permissions_and_authentication | Open | — | — | — | — |
| **OD-04** | Lifecycle thresholds | configuration_defaults | Open | — | — | — | — |
| **OD-05** | Tracking domain | configuration_defaults | Open | — | Yes | — | — |
| **OD-06** | Public help URL | public_surface | Open | — | Yes | — | Empty; UAT validates the omission |
| **OD-07** | Carrier-link allowlist | public_surface | Open | — | Yes | — | Nine hosts enabled for UAT only |
| **OD-08** | Vietnamese staff wording | language_review | Open | **Yes** | Yes | — | — |
| **OD-09** | Vietnamese customer wording and the 17 templates | language_review | Open | **Yes** | Yes | — | — |
| **OD-10** | Hosting shortlist | hosting_and_recovery | Open | — | Yes | — | — |
| **OD-11** | Canadian or other data-residency requirement | retention_and_privacy | Open | — | Yes | — | — |
| **OD-12** | Recovery point objective | hosting_and_recovery | Open | — | Yes | — | — |
| **OD-13** | Recovery time objective | hosting_and_recovery | Open | — | Yes | — | — |
| **OD-14** | Import file and row limits | configuration_defaults | Open | — | Yes | — | — |
| **OD-15** | Shipment CSV import | data_migration | Open | — | — | — | Deferred pending real source data |
| **OD-16** | Legacy aggregate-history baseline | data_migration | Open | — | — | — | Deferred pending real source data |
| **OD-17** | MFA requirement and implementation approach | permissions_and_authentication | Open | **Yes** | Yes | — | — |
| **OD-18** | Physical thermal printer and scanner acceptance | physical_and_accessibility_acceptance | Open | **Yes** | Yes | — | — |
| **OD-19** | Screen-reader and zoom testing responsibility | physical_and_accessibility_acceptance | Open | **Yes** | Yes | — | — |
| **OD-20** | Who may authorize production deployment | release_authority | Open | — | Yes | — | Deployment prohibited |
| **OD-21** | ShipStation account facts: the nine integration questions | provider_integration | Open | — | — | **Yes** | Allowlists and adapter registry empty |
| **OD-22** | Return shipment workflow and policy | product_scope | Open | — | — | — | — |
| **OD-23** | Customer Account registration mode | permissions_and_authentication | **Answered 2026-09-19** | — | — | — | — |
| **OD-24** | Customer Account approval authority | permissions_and_authentication | **Answered 2026-09-19** | — | — | — | — |
| **OD-25** | Account-to-customer cardinality | product_scope | **Answered 2026-09-19** | — | — | — | — |
| **OD-26** | Company and multiple-user access | product_scope | **Answered 2026-09-19** | — | — | — | — |
| **OD-27** | Customer-editable field policy | retention_and_privacy | **Answered 2026-09-19** | — | — | — | — |
| **OD-28** | Staff approval rules for customer-submitted changes | permissions_and_authentication | **Answered 2026-09-19** | — | — | — | — |
| **OD-29** | Shipment ownership and history visibility | customer_account_surface | **Answered 2026-09-19** | — | — | — | — |
| **OD-30** | Recipient access | product_scope | **Answered 2026-09-19** | — | — | — | — |
| **OD-31** | Authenticated shipment field allowlist | customer_account_surface | **Answered 2026-09-19** | — | — | — | — |
| **OD-32** | Customer financial visibility | customer_account_surface | **Answered 2026-09-19** | — | — | — | — |
| **OD-33** | Customer-account multi-factor authentication | permissions_and_authentication | **Answered 2026-09-19** | — | — | — | — |
| **OD-34** | Production email delivery | hosting_and_recovery | **Answered 2026-09-19** | — | Yes | — | — |
| **OD-35** | Deletion and privacy requests | retention_and_privacy | **Answered 2026-09-19** | — | — | — | — |
| **OD-36** | Customer-account retention | retention_and_privacy | **Answered 2026-09-19** | — | — | — | — |
| **OD-37** | Terms and privacy acknowledgement | retention_and_privacy | **Answered 2026-09-19** | — | Yes | — | — |
| **OD-38** | Notification preferences and consent separation | retention_and_privacy | **Answered 2026-09-19** | — | — | — | — |
| **OD-39** | Customer Account language launch policy | language_review | **Answered 2026-09-19** | — | — | — | — |
| **OD-40** | Linked-customer merge policy | permissions_and_authentication | **Answered 2026-09-20** | — | — | — | — |
| **OD-41** | Additional authenticated shipment-list filters | customer_account_surface | **Answered 2026-09-21** | — | — | — | — |
| **OD-42** | Customer public ID prefix: STCA | product_scope | **Answered 2026-10-19** | — | — | — | — |
| **OD-43** | Service taxonomy: Solaris services mapped to vendor products; air first | product_scope | **Answered 2026-10-19** | — | — | — | — |
| **OD-44** | Customer surcharge markup policy | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-45** | Who sees vendor cost, and who confirms or overrides the selling rate | permissions_and_authentication | **Answered 2026-10-19** | — | — | — | — |
| **OD-46** | Vendor delivery point: vendor cost is zoned at L5A 3K6 only | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-47** | Pharmaceutical surcharge lines block finalisation (superseded by OD-58) | product_scope | **Answered 2026-10-19** | — | — | — | — |
| **OD-48** | Air Standard $18/kg default and the two-thirds full-master cost rule | configuration_defaults | **Answered 2026-10-20** | — | — | — | — |
| **OD-49** | Air only: sea is out of scope for pricing, rules and tests | product_scope | **Answered 2026-10-19** | — | — | — | — |
| **OD-50** | Weight rounding: 0.5 kg steps for every weight, per shipment | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-51** | The matching weight band's rate applies; no minimum bill | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-52** | Dimensional divisor 6000 for everything | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-53** | Beyond fee: convert lb to kg, round, then the band rate | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-54** | No fixed 19,500 rate: Vietcombank cash buying and selling | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-55** | Vendor data used as provided (zone 1 = zone 3; Express below Ground) | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-56** | Unpriced HCM air surcharges are manual quotes prefilled with the minimum | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-57** | Nail polish and perfume tiers: no overlap, above 30 kg the top tier | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-58** | Pharmaceuticals are carried at 200,000 VND/kg (supersedes OD-47) | product_scope | **Answered 2026-10-19** | — | — | — | — |
| **OD-59** | Battery groups: 3.1-3.5 kg low group, 3.6-8 kg high group, above 8 kg quoted | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-60** | No rounding of VND bill amounts; the vendor bills VND, the customer pays CAD | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-61** | Tariff effective from 12 Oct 2026, no end date | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-62** | Under-12 kg piece fee: 300,000 Ground / 700,000 Express per piece | configuration_defaults | **Answered 2026-10-19** | — | — | — | — |
| **OD-63** | No tracking API: manual staff events stay | provider_integration | **Answered 2026-10-19** | — | — | — | — |
| **OD-64** | Tax on customer invoices, invoice wording and company details (D-11) | release_authority | **Answered 2026-10-20** | — | — | — | — |
| **OD-65** | Payment terms: due date and whether payment gates dispatch (D-10) | configuration_defaults | **Answered 2026-10-20** | — | — | — | — |
| **OD-66** | Customer payments in VND: which rate converts them (superseded by OD-73) | configuration_defaults | **Answered 2026-10-20** | — | — | — | — |
| **OD-67** | Vendor bills in VND: which rate puts them into CAD (superseded by OD-73) | configuration_defaults | **Answered 2026-10-20** | — | — | — | — |
| **OD-68** | No customer credit | product_scope | **Answered 2026-10-20** | — | — | — | — |
| **OD-69** | Who may refund, void and reopen a closed month | permissions_and_authentication | **Answered 2026-10-20** | — | — | — | — |
| **OD-70** | Pharmaceutical surcharge on the item's own kilograms | configuration_defaults | **Answered 2026-10-20** | — | — | — | — |
| **OD-71** | Customer Account in Vietnamese first, English as an option (D-13) | language_review | **Answered 2026-10-20** | — | — | — | — |
| **OD-72** | Milestone notifications: email, per-milestone opt-in, suppressions, test capture | product_scope | **Answered 2026-10-20** | — | — | — | — |
| **OD-73** | FX rule everywhere: VND to CAD at the buy rate, CAD to VND at the sell rate | configuration_defaults | **Answered 2026-10-20** | — | — | — | — |
| **OD-74** | Default 2 % markup on surcharges, as a setting | configuration_defaults | **Answered 2026-10-20** | — | — | — | — |
| **OD-75** | A CAD invoice paid in VND converts at the sell rate (confirms OD-73) | configuration_defaults | **Answered 2026-10-20** | — | — | — | —
| **OD-76** | Vendor rate emails: Ben's Soleil mailbox; Ben approves new tariff versions (D-12) | release_authority | **Answered 2026-10-20** | — | — | — | —
| **OD-77** | Quote acceptance: staff send the quote, the customer accepts it in the Customer Account (D-08) | customer_account_surface | **Answered 2026-10-20** | — | — | — | —
| **OD-78** | No QuickBooks export | product_scope | **Answered 2026-10-20** | — | — | — | —
| **OD-79** | Customer-facing service names: Air Standard and Air Express (D-03) | public_surface | **Answered 2026-10-20** | — | — | — | —
| **OD-80** | D-07, D-09 and V-20 (non-pharma per-kg) answered later; development not blocked | configuration_defaults | **Answered 2026-10-20** | — | — | — | —
| **OD-81** | Express zone 2 price drop at 16 kg is correct (D-07) | configuration_defaults | **Answered 2026-10-21** | — | — | — | —
| **OD-82** | HCM meat/egg/dairy/honey surcharge: 20,000 VND/kg for VN-CA (D-09) | configuration_defaults | **Answered 2026-10-21** | — | — | — | —
| **OD-83** | Per-kg surcharge kg basis follows the vendor notes (V-20) | configuration_defaults | **Answered 2026-10-21** | — | — | — | —
| **OD-84** | No vendor or carrier name on customer-facing quotes, invoices or labels | public_surface | **Answered 2026-10-21** | — | — | — | —
| **OD-85** | Vietnamese wording accepted as is | language_review | **Answered 2026-10-21** | — | — | — | —
| **OD-86** | Air Express has no default rate (confirmed) | configuration_defaults | **Answered 2026-10-21** | — | — | — | —
| **OD-87** | Vendor rate emails go to Ben's mailbox (confirms OD-76) | release_authority | **Answered 2026-10-21** | — | — | — | —
| **OD-88** | A booked master locks its items and fees; Admin can unlock with a reason | permissions_and_authentication | **Answered 2026-10-21** | — | — | — | —
| **OD-89** | Accepting a quote creates a draft invoice; quotes expire on a new tariff only before goods are received | product_scope | **Answered 2026-10-21** | — | — | — | —
| **OD-90** | Draft invoice screen: Save, Send, Download, Edit; unsaved edits block other actions | product_scope | **Answered 2026-10-21** | — | — | — | —
| **OD-91** | Last-mile carrier tracking links stay visible; vendor name hidden around them (Q-P1) | public_surface | **Answered 2026-10-22** | — | — | — | —
| **OD-92** | Customer-facing leg names: Master Tracking and Last Mile Tracking (Q-P2) | public_surface | **Answered 2026-10-22** | — | — | — | —
| **OD-93** | Costume jewellery (HCM air row 27) is a manual quote input (F-1) | configuration_defaults | **Answered 2026-10-22** | — | — | — | —
| **OD-94** | Draft invoices: GST/HST auto-filled, included in the all-in price, confirmed before Save/Send (F-3) | configuration_defaults | **Answered 2026-10-22** | — | — | — | —
| **OD-95** | A quote with an issued invoice does not expire (F-4) | product_scope | **Answered 2026-10-22** | — | — | — | —
| **OD-96** | No customer email on quote expiry (F-5) | product_scope | **Answered 2026-10-22** | — | — | — | —
| **OD-97** | Master relock after an Admin unlock stays as built (F-6) | permissions_and_authentication | **Answered 2026-10-22** | — | — | — | —
| **OD-98** | Quotes on a booked master do not expire (F-7) | product_scope | **Answered 2026-10-22** | — | — | — | —
| **OD-99** | An exception milestone does not count as received (F-8) | product_scope | **Answered 2026-10-22** | — | — | — | —
| **OD-100** | No Back-button warning on unsaved draft edits (F-9) | product_scope | **Answered 2026-10-22** | — | — | — | —
| **OD-101** | Whole-word vendor-name matching (F-10) | public_surface | **Answered 2026-10-22** | — | — | — | —
| **OD-102** | GST/HST by route: international zero-rated, domestic included at the destination province's rate (P-1, P-2) | configuration_defaults | **Answered 2026-10-23** | — | — | — | —
| **OD-103** | Costume jewellery: staff enter both the vendor's VND cost and the customer price (P-3) | configuration_defaults | **Answered 2026-10-23** | — | — | — | —
| **OD-104** | Vietnamese leg names approved (P-4) | language_review | **Answered 2026-10-23** | — | — | — | —
| **OD-105** | Tracking links whose address names the vendor stay hidden (P-5) | public_surface | **Answered 2026-10-23** | — | — | — | —
| **OD-106** | Directly issued invoices are unchanged (P-6) | product_scope | **Answered 2026-10-23** | — | — | — | —
| **OD-107** | Admin delete of retained quote records: later (P-7) | retention_and_privacy | **Answered 2026-10-23** | — | — | — | —
| **OD-108** | Keep the customer quote total and staff note wording | language_review | **Answered 2026-10-23** | — | — | — | —
| **OD-109** | Customer quote tax wording follows the invoice rule (P-9 stand-in, pending Ben) | language_review | Open (stand-in in force) | — | — | — | —
| **OD-110** | Build every remaining feature now; stand-ins recorded as open questions | product_scope | **Answered 2026-10-24** | — | — | — | —

**Nothing in OD-01 … OD-22 is answered.** Several of those carry a temporary disposition
that let the release candidate be assembled — the generated table in section 1 says how
many, and that is the only place the figure should be read from.

**OD-23 … OD-63, except OD-48, are answered** — OD-23 … OD-39 on 2026-09-19, OD-40 on 2026-09-20,
OD-41 on 2026-09-21, OD-42 … OD-47 and OD-49 … OD-63 on 2026-10-19 (OD-48, also of
2026-10-19, is open by the owner's instruction: implemented as flagged defaults pending
confirmation; OD-58 supersedes OD-47) (the B2C merge decisions, recorded in
full in the JSON register and summarised in `docs/b2c_merge/05_OPEN_DECISIONS.md`) —
and none of them carries a disposition: an answered decision has no need of one. Their full text is
`docs/customer_account/OWNER_DECISIONS_23_39.md`. Two of them **block production**:
**OD-34** (no email provider is selected) and **OD-37** (no approved terms or privacy text
exists), so customer registration cannot launch in production until the owner acts on both.
None of the nineteen blocks local UAT: OD-41 names a filter on a surface that is now built
and is exercised by the Customer Account UAT pack, and the rest describe behaviour that is
reachable without it.

### The authorised temporary dispositions, in full

A disposition is a way of proceeding **without** an answer. None survives into production,
and none is ever written into `owner_answer`.

| Decision | Disposition in force for RC-UAT-3 |
|---|---|
| **OD-01** | Retention deletion remains disabled |
| **OD-06** | The public help URL remains empty; UAT **validates the omission** of the optional link rather than blocking on it |
| **OD-07** | The nine public carrier-link hosts remain enabled provisionally for UAT; **not approved for production** |
| **OD-15** | Shipment import remains deferred until real source data and a confirmed mapping contract exist |
| **OD-16** | Legacy history remains deferred until real source data exists |
| **OD-20** | Production deployment remains prohibited |
| **OD-21** | Provider resource host and path allowlists remain empty; the production adapter registry remains empty; `connected_api` remains refused |

Three further conditions are in force and are **not** dispositions, because they are simply
the unanswered state: **MFA remains unanswered** (OD-17), so authentication and security
UAT cannot receive final sign-off; **Vietnamese text remains unreviewed** (OD-08, OD-09);
and **no return shipment record has ever existed** (OD-22).

### Two blocking flags that changed at RC-UAT-3

Both are recorded here rather than left to be noticed.

* **OD-06 no longer blocks local UAT.** Under the owner-authorised disposition the empty
  help URL is the behaviour *under test*: the tester confirms the optional link is cleanly
  absent, rather than recording a case as `Blocked`. It still blocks production.
* **OD-22 no longer blocks local UAT.** `docs/UAT/UAT_CASES.md` states that no case in the
  45-case pack depends on a return **record**, and the one control that promised a
  return-shipment list — the `returns_only` drill-through — was removed at RC-UAT-3. There
  is nothing left for a tester to be blocked on. The decision itself remains open and
  unanswered.

---

## 4. OD-21 — provider-only, and the nine questions

OD-21 is the register's only **provider-only** decision. It blocks neither local UAT nor
production: provider work is deferred by DEC-0075, and the application ships with manual
and external-link tracking as its complete tracking story.

The nine questions are `docs/INTEGRATIONS.md` section 9, carried verbatim in the JSON as
`provider_questions`. **They are recorded, not answered.** The verification command fails
if any of them stops being a question.

| # | Question |
|---|---|
| 1 | Which ShipStation product and API generation is the account entitled to — legacy, V2, or ShipStation API / ShipEngine? |
| 2 | What is the authentication scheme for that specific product? |
| 3 | Can the account track a label it did **not** purchase? |
| 4 | Which webhook event types exist, and what does each actually mean? |
| 5 | Do webhook payloads carry a verifiable signature, and by what algorithm? |
| 6 | Does the provider supply a stable event identifier? |
| 7 | What are the documented rate limits, and does the provider send `Retry-After`? |
| 8 | Exactly which HTTPS hosts and path prefixes would a `resource_url` fetch need? |
| 9 | What is the carrier coverage for VCA, CAV, CAD, and XUS? |

An answer of "no" to 3, 5, or 9 is a **useful** answer, not a blocker.

---

## 5. OD-22 — Return shipment workflow and policy

Raised 2026-09-15 by the pre-UAT gate review. The full trace is
`docs/RETURNS_REQUIREMENT_MATRIX.md`, which establishes the twelve questions carried in
the JSON as `return_questions`.

**The situation.** `shipments.is_return` and `shipments.return_of_shipment_id` exist, are
read by `report_service`, `export_service` and `activity_service`, and are written by
**nothing** — no service, no route, no schema field, no screen. `CRM.md` section 4 says
"Returns remain linked records and do not count as another outbound purchase by default",
which presupposes such records exist, but no document says how one comes to exist. A
`returns` row is already shipped in the shipment-status report and an `is_return` column
in the shipment export; both can only ever read `0` and `false`.

Note that **return *statuses* are fully implemented** and are not in question here:
`return_in_progress` and `returned` are staff-recordable events, shown on the staff list,
the detail page, the exceptions report and the public tracking page in both languages.
This decision is only about return **shipment records**.

### The questions

| # | Question |
|---|---|
| 1 | **Are returns in current scope at all?** If no, the reporting and export surfaces below must be reconsidered rather than left reading zero |
| 2 | **Who may create one?** Which roles — and is it a booking action, a shipment action, or an admin correction? |
| 3 | **Does a return receive a new Solaris ID**, reuse the outbound ID, or carry a derived suffix? |
| 4 | **What relationship to the outbound shipment is required?** Must `return_of_shipment_id` always be set, must the outbound be confirmed, must it be delivered, and may one outbound have several returns? |
| 5 | **Package selection.** All packages, a subset, or new package records? What happens to the outbound's delivered counts? |
| 6 | **Route direction.** Is a return the reverse route group, the same one, or a separately chosen route? |
| 7 | **Label behaviour.** Does a return get a printed label, and if so whose address is the recipient? |
| 8 | **Public tracking.** Is a return publicly trackable, under which reference, and what does the customer see on the original reference once a return exists? |
| 9 | **Financial treatment.** Is a return charged, free, or a refund against the outbound? How does it interact with `payment_state` and `refund_amount`? |
| 10 | **Cancellation and rebooking interaction.** May a return be cancelled? May a cancelled outbound have a return? Does a rebooking inherit its predecessor's returns? |
| 11 | **Reporting treatment.** Confirm the current rule — excluded from qualifying counts, reported on their own row — and decide whether the `returns` report row should link anywhere. **As of RC-UAT-3 it links nowhere**, because every available destination would answer question 1 by implementation |
| 12 | **Must legacy or imported returns be supported?** Shipment import is itself unanswered (OD-15), so a return arriving from a migration has no path either |

### Until this is answered

* No return workflow is implemented, and **no return row is manufactured** to make a
  dataset look complete.
* The UAT dataset contains no returns, and `scripts/uat_env.py --check` reports them as
  absent with the reason.
* The fixture-level report and export tests stay exactly as they are. They pin
  `CRM.md` section 4's counting rule, which is a real requirement whether or not a
  workflow ever exists.
* **The `returns_only` drill-through has been removed** (RC-UAT-3). The report row keeps
  its truthful value and label and carries a neutral note saying drill-through is
  unavailable. Removing a link that went nowhere does not answer question 1; building the
  filter, or removing the row, would have.

---

## 6. Verifying this register

```bash
backend/.venv/Scripts/python scripts/verify_owner_decisions.py
```

It proves, from the records and nothing else, that OD-01 through OD-41 all exist, that the
identifiers are contiguous and unique, that every identifier resolves to a *complete*
record, that the category totals are derived, that no provisional disposition has been
recorded as a final answer, that OD-21 is provider-only and still asks nine questions, that
OD-22 is present, open and still asks twelve, that the totals displayed in section 1 match
the records, and that every `OD-NN` cited anywhere in the repository resolves to a record.

Exit status 0 means every check passed.
