# Returns — the requirement matrix, and what the documents actually say

Phase 6 recorded that `shipments.is_return` and `shipments.return_of_shipment_id` exist,
that reports and exports read them, and that **nothing in the application ever sets
either one**. The UAT dataset therefore could not contain a return without writing
unsupported state, and it does not.

This file is the trace that was missing: every explicit mention of returns in the
specification and the build, what each one actually requires, and which of them are met.
It exists because "returns are not implemented" is a true sentence that hides a more
useful one — **two different things are called "returns" in this project, and only one of
them is unimplemented.**

---

## 1. The distinction everything else depends on

| | **A — return *status*** | **B — return *shipment record*** |
|---|---|---|
| What it is | A shipment (or package) whose current operational state is `return_in_progress` or `returned` | A separate `shipments` row flagged `is_return = true` and linked by `return_of_shipment_id` to the outbound shipment it returns |
| Where it comes from | A staff-recorded shipment event | Nothing. There is no writer |
| Specified by | `CRM.md` section 10 (the 17 normalized statuses) | `CRM.md` section 4 (a *counting* rule) |
| Implemented? | **Yes, end to end** | **Fields only** |

Phase 6's finding is about **B**. Almost every requirement in the documents is about
**A**, and **A works**. Conflating them is what makes "returns are not implemented" sound
like a missing feature rather than a missing *record type*.

---

## 2. Every explicit mention of returns

Searched: `CRM.md`, `Design.md`, `Claude_Code_Build_Prompt.md`, `PROJECT_STATUS.md`,
`docs/ARCHITECTURE.md`, `docs/DATA_DICTIONARY.md`, `docs/DECISIONS.md`,
`docs/PRODUCT_SPEC.md`, `docs/INTEGRATIONS.md`, `docs/STAFF_GUIDE.md`, the Alembic
migrations, every service, every route, every schema, the frontend, and the tests.

| # | Source | What it says | A or B | Requires a staff workflow? | Met today? |
|---|---|---|---|---|---|
| 1 | `CRM.md` §4 | "Returns remain linked records and do not count as another outbound purchase **by default**." | **B** | **No** — it is an exclusion rule for a counter | **Yes.** `qualifying_shipment_filter` carries `is_return = false` |
| 2 | `CRM.md` §5 | `Primary Shipping Purpose` may be "returns" | Neither — a **customer profile attribute** | No | **Yes.** `ShippingPurpose.RETURNS` |
| 3 | `CRM.md` §10 | Normalized statuses include "Return in progress" and "Returned" | **A** | **Yes — and it exists** | **Yes.** `ShipmentEventType.RETURN_IN_PROGRESS` / `RETURNED` |
| 4 | `CRM.md` §10 | "Handle subsequent returns/corrections with explicit event semantics and audit history" | Neither — this is about **event corrections**, not return shipments | No | **Yes.** Void-and-correct with audit history |
| 5 | `CRM.md` §17 AC-19 | "Tests include … cancellation, **return**, collection-point delivery …" | **A** | No — it is a *test coverage* criterion | **Yes.** `PROJECT_STATUS.md` B3 records AC-19's return half as met in **Phase 3** by "return in progress" |
| 6 | `Design.md` | **Nothing. Zero occurrences of the word.** | — | — | — |
| 7 | `Claude_Code_Build_Prompt.md` | **Nothing. Zero occurrences.** | — | — | — |
| 8 | `docs/ARCHITECTURE.md` §5 | Qualifying shipments are "confirmed, handed-off, non-cancelled, **non-return**" | **B** | No | **Yes** |
| 9 | `docs/DATA_DICTIONARY.md` | `is_return`, `return_of_shipment_id` — "returns stay linked but are not another outbound purchase" | **B** | No | Fields exist |
| 10 | `docs/DATA_DICTIONARY.md` | `return_in_progress`, `returned` event types and operational states | **A** | Yes | **Yes** |
| 11 | `docs/DATA_DICTIONARY.md` | Qualifying shipment excludes `is_return = true`; returns "reported on their own row" | **B** | No | **Yes** |
| 12 | `docs/DATA_DICTIONARY.md` | `shipment_exceptions` counts `return_in_progress` | **A** | No | **Yes** |
| 13 | `docs/DATA_DICTIONARY.md` | Shipment export carries `is_return` | **B** | No | **Yes** — column exists, always `false` |
| 14 | `docs/PRODUCT_SPEC.md` | Restates §4 and the status list | A + B | No | As above |
| 15 | `docs/INTEGRATIONS.md` | The estimate is withdrawn once a shipment "is delivered, **returned**, or cancelled" | **A** | No | **Yes** |
| 16 | `docs/STAFF_GUIDE.md` | "Return in progress" listed among states that do not complete a shipment | **A** | No | **Yes** |
| 17 | `docs/DECISIONS.md` | **Nothing.** No `DEC-` entry discusses returns at all | — | — | — |
| 18 | Migration `b39203a50b1e` (Phase 1 baseline) | Creates `is_return` (non-null) and `return_of_shipment_id` (self-FK, `ON DELETE SET NULL`) | **B** | No | Shipped |
| 19 | `app/services/activity_service.py` | Reads `is_return` to exclude from qualifying | **B** | No | **Yes** |
| 20 | `app/services/report_service.py` | Reads `is_return` for the `returns` row of `shipment_status` | **B** | No | **Yes** (always 0) |
| 21 | `app/services/export_service.py` | Emits `is_return` as a column | **B** | No | **Yes** (always `false`) |
| 22 | Routes / schemas | **No route, no schema field, no service accepts or sets `is_return` or `return_of_shipment_id`** | **B** | — | **No writer exists** |
| 23 | Frontend | Status labels, list filters and tokens for `return_in_progress` / `returned`, in **en** and **vi**, staff and public | **A** | Yes | **Yes** |
| 24 | Frontend | **No return-creation UI of any kind** | **B** | — | — |
| 25 | `backend/tests/report_fixtures.py` | Builds a `return_leg` row with `is_return=True` and `return_of_shipment_id` set, **directly** | **B** | — | Fixture only |
| 26 | `backend/tests/test_reports_metrics.py` | `test_a_return_is_reported_separately_and_never_added_to_volume` | **B** | — | **Yes**, against the fixture |
| 27 | `backend/tests/test_activity.py` | A return is excluded from qualifying counts | **B** | — | **Yes**, against the fixture |
| 28 | `scripts/uat_env.py` | Reports returns as absent, and says why | **B** | — | Honest |

### Reserved model fields, or a required workflow?

| Question | Answer from the documents |
|---|---|
| Is there **any** documented requirement that staff create a return? | **No.** Not in `CRM.md`, not in `Design.md`, not in the build prompt, not in any acceptance criterion |
| Are returns merely reserved model fields? | The fields are **not** decorative — they implement `CRM.md` §4's exclusion rule, which is a real requirement. But they are only ever **read** |
| Are reports and exports expected to contain return data? | **Yes.** `shipment_status` has a dedicated `returns` row and the shipment export has an `is_return` column. Both are shipped, and both can only ever show `0` / `false` |
| Which acceptance criterion remains unmet? | **None.** AC-19's "return" was met in Phase 3 by the *status* path (**A**). No acceptance criterion requires **B** |
| Why were the fields added without a creation path? | Because `CRM.md` §4 required the *counter* to exclude returns. Implementing an exclusion requires a column to exclude on. The column was added to make the rule expressible — and the rule, not the workflow, is what was specified |

---

## 3. Classification

> ### 4 — Specification ambiguity
>
> The documents do not establish which behaviour is intended.

**Not** (1) *Missing required product workflow*: no document requires staff to create or
process a return **record**. The only return processing the documents require is the
status path, and that is implemented.

**Not** (3) *Legacy/import-only*: nothing describes returns arriving from an import or a
migration. Shipment import is itself unanswered — `PROJECT_STATUS.md` §9 still asks
"whether it is needed, and from what source" — so there is no *confirmed* path to call
this.

**Not** (2) *Reserved future capability*, although it is the closest miss, and the
argument for it is real: every explicit requirement is satisfied today, and `Design.md` —
the document whose job it would be to specify a screen — says nothing at all.

It fails on two points:

1. **`CRM.md` §4 presupposes the records exist.** "Returns *remain* linked records" and
   "do not count as another outbound purchase **by default**" are statements about
   records the specification expects to encounter. If nothing can ever create one, the
   sentence is vacuous — and "by default" implies a configurable alternative that is
   likewise unspecified. Two careful readers can disagree about whether §4 presupposes a
   return-creating capability. That disagreement is the ambiguity.
2. **A shipped surface depends on the answer.** A `returns` row in the shipment-status
   report and an `is_return` column in the shipment export are already in front of staff.
   A reserved field is invisible; these are not. Whether they should be there at all
   depends on an answer nobody has given.

Every question a return workflow would need — who may create one, whether it gets a new
Solaris ID, what the route direction is, what happens to the label, what a customer sees,
how it is priced — is answered **nowhere**. Ten unanswered questions and zero documents
that address them is ambiguity, not a deliberate reservation.

**Consequence:** `OD-22 — Return shipment workflow and policy` is raised, no workflow is
implemented, and no return row is manufactured. See `docs/OWNER_DECISIONS.md`.

---

## 4. A defect found by this trace, and corrected at RC-UAT-3

**The `returns` report row linked to a filter that does not exist.**

`report_service.shipment_status` gave the returns row
`"link": "/shipments?returns_only=true"`, and `ReportTable.jsx` renders every row `link`
as a real `<Link>`. But `returns_only` was accepted by **nothing**: not the
`GET /api/v1/shipments` route (which takes `route_group`, `booking_state`,
`operational_state`, `sort`, `direction`, `limit`, `offset`), and not the frontend list
page. FastAPI ignores unknown query parameters, so following that link silently produced
the **unfiltered** shipment list — every shipment, presented as though it were the return
set.

It was never visible because the count is always `0`, but the link was rendered
unconditionally, so a UAT tester could click it.

### What was done, and why it does not answer OD-22

RC-UAT-1 and RC-UAT-2 left it in place on the reasoning that every available repair —
building the filter, removing the row, or removing the link — would answer question 1 by
implementation. Two of those three would have. **Removing the link does not.**

* The row's **value and label are kept**, because both are true: zero return shipments were
  handed over in the period, and that is a fact about the data, not a placeholder.
* The row now carries a neutral note — *"Reported here only. There is no return-shipment
  list to open while the return workflow is undecided."* — which states the absence without
  implying that a return-shipment workflow exists, is planned, or is coming.
* **Nothing was built.** No `returns_only` filter, no return record, no return data, no
  change to the counting rule.
* `return_in_progress` and `returned` remain staff-recordable event statuses, entirely
  unaffected. A return **status** and a linked return **record** are still different
  things, and neither has been conflated with the other.
* The public tracking contract is untouched: still 24 fields.

A known dead control must not be handed to human testers, and "it is recorded as a defect"
is not a substitute for removing it. `backend/tests/test_report_navigation.py` now proves
that no generated staff link names `returns_only`, that the returns row carries no
drill-through of any kind, that its value and label are still true, that no return shipment
was manufactured, and that OD-22 is still open and unanswered.

The same sweep found four more links in the same class, all corrected:

| Link | What it did | Now |
|---|---|---|
| `/shipments?status=active` (dashboard KPI) | `status` is read by nothing; showed the unfiltered list | Built from `ACTIVE_OPERATIONAL_STATES`, so the card and the list cannot disagree |
| `/follow-ups?view=due` (dashboard KPI) | `view` **is** read, and `due` is not one of the two tab ids, so the page rendered no panel at all | `/follow-ups?view=all` |
| `/follow-ups?view=open` and `?view=due` (report rows) | Same empty page | `/follow-ups?view=all`, with `only_overdue=true` where the row means overdue |
| `/follow-ups?status=completed` (report row) | `status` is read by nothing | `/follow-ups?view=all&only_open=false` |

Two inert query parameters were also dropped — `?task=<id>` on the dashboard task link and
`&package=<id>` on the scan-to-open link. Neither was read by its destination. The
navigation they performed was already correct; only the parameters claimed more than the
pages do.

---

## 5. What UAT must be told

| | |
|---|---|
| Returns are **not** in the UAT dataset | Correct. Nothing creates them, and writing the rows would fabricate a feature |
| Return **statuses** *are* testable | `return_in_progress` and `returned` are recordable events, visible on the staff list, the detail page, the exceptions report, and the public tracking page in both languages |
| Return **shipment records** are not testable | No workflow creates one. Do not mark any such case passed or failed — it is **blocked pending OD-22** |
| The `returns` report row | Will read `0`. That is correct, not a defect. It carries **no drill-through link** and says so in a note; that is deliberate, not a missing feature |
| The `is_return` export column | Will read `false` for every row. Correct |

Fixture-level report and export tests are retained exactly as they are: they pin the
counting rule from `CRM.md` §4, which is a real requirement independent of whether a
workflow ever exists. They are the right place for it, because they assert the rule
without asserting that the application can produce the state.
