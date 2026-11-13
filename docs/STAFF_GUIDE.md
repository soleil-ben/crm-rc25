# Staff guide

How to use the Solaris Express CRM day to day.

**What exists today:** customers, follow-ups, segments, the dashboard, bookings, packages,
transport legs, operational events, internal 4 × 6 labels, and — new in Phase 3 — the
public tracking page customers use to check their own shipments. Carrier integration is a
later phase; the Reports page says so rather than pretending to work.

**Added since (Phases 13 to 15, air only):** the **Workspace** for air masters and quotes,
customer quote acceptance, **Finance**, pricing settings, vendor tariffs and rate emails,
milestone emails, and the Customer Account in Vietnamese. See
[Air masters, quotes and money](#air-masters-quotes-and-money-phases-13-to-15) below.

---

## Signing in

Go to the portal URL and sign in with your own account. Accounts are personal — never
share one, because every change is recorded against the person who made it.

If you see an orange **Demo environment** banner across the top, you are on a practice
system. Everything there is invented sample data. Nothing you do affects real customers.

After too many wrong password attempts the system pauses sign-in for a few minutes. Wait,
then try again, or ask an administrator to check the account.

---

## What your role can do

> **Customer service is no longer a role.** It was merged into **Operations** in
> September 2026, and Operations now carries the whole of what Customer service could
> do (DEC-0088). If you held a Customer service account, it is the same account with
> the same sign-in; only the role name changed, and nothing you could do before was
> taken away. If you held an Operations account, you can now do more than you could:
> customer records, consent, segments, duplicate review, cancel-and-rebook, and
> revenue. Carrier costs are still Admin-only.

| You are | You can | You cannot |
|---|---|---|
| **Admin** | Everything, including staff accounts, settings, merges, imports, every export, costs, and cancelling bookings | — |
| **Operations** | Customers, bookings, packages, labels, transport legs, events, cancel and rebook, follow-ups, consent, tags, referrals, segments, duplicate review, reports, revenue figures | Manage staff or settings, merge customers, import, bulk-export anything, see carrier costs |
| **Marketing** | Customer profiles, consent, tags, segments, duplicate review, follow-ups, reports, marketing-audience exports; shipments read-only | Create or archive customers, edit shipments, see costs, import, operational exports |
| **Read-only manager** | View records, shipments, dashboards, reports, revenue, duplicate review, audit log | Change anything, import, export |

If a button is missing, your role does not include that action. The server enforces this,
so there is no workaround — ask an administrator if you need the access.

**Two Phase 5A notes on this table.**

*Importing and bulk-exporting shipments and reports are Admin-only for now.* Those are the
operations that move the whole database across a boundary in one action, and `CRM.md` does
not say who should hold them. Admin-only is the reversible placeholder while the owner
decides — widening a permission later is a settings change; taking one away after people
have been trained on it is not.

*Operations no longer reaches the duplicate-review screens.* Reviewing duplicates means
being shown two people's contact details side by side in order to decide whether they are
one person, which is customer-data stewardship rather than parcel handling. `CRM.md`
section 11 gives Operations only the customer detail its task needs.

---

## Finding someone

Use the search box at the top of every page. It searches names, customer IDs, email
addresses, phone numbers, and cities at once.

- Accents are optional — typing `nguyen thi` finds `Nguyễn Thị`.
- Pasting or scanning a customer ID such as `STCA-000042` jumps straight to that record.
- An old customer ID from before a merge still finds the surviving record.

For a filtered list, use **Customers** and the filter bar. Active filters appear as chips
you can remove one at a time, and the URL updates so you can bookmark or share the view.

---

## Adding a customer

**Customers → Add customer.**

You must provide a **full name** and **at least one** phone number or email address.
Everything else can be filled in later — leave what you do not know blank rather than
guessing. "Unknown" is a real answer and the system treats it as one.

A few things worth getting right:

- **Full name.** Type it as the customer writes it. Accents are preserved everywhere,
  including in exports.
- **Preferred language.** Ask. Never infer language from someone's name or from the
  country they ship to.
- **Expected shipping frequency** is what the customer *expects*. What they actually ship
  is measured separately and shown as "Shipping activity" on their profile. The two never
  overwrite each other.
- **Do not contact** is a service restriction, not a marketing setting. It is separate
  from consent and stays visible on the profile.

### When the duplicate panel appears

While you type, the system looks for records that share a name, phone number, or email
and shows them in an orange panel.

**Nothing is ever merged automatically.** Families often share a phone number or an email
address, and two people genuinely can be two customers. You decide:

- **Open existing record** — it is the same person; use the record that already exists.
- **Create a separate customer** — tick the box to confirm, then save.

Save stays disabled until you make that choice, on purpose.

---

## Merging two records (admin only)

If you are certain two records are the same person, an administrator can merge them from
the profile. You type the source customer ID to confirm.

The merge moves shipments, tasks, notes, consent history, addresses, referrals, and tags
onto the surviving record, and keeps the old customer ID as an alias so old paperwork
still resolves. The merged record becomes read-only rather than disappearing.

A do-not-contact restriction on **either** record survives the merge. Suppressed email
addresses stay suppressed — a merge cannot quietly re-enable contact.

A record linked to a Customer Account that is active or suspended cannot be merged; the
screen says so. A record whose account has been **deactivated** can be merged: the link is
kept as history, and nobody can sign in through it.

A customer whose account was deactivated can also be linked to a new registration. The
approval preview says "Approving ends a deactivated account's link" and names the old
account; approving ends that link and records it in the audit log. An active or suspended
account's customer cannot be taken over. The former account holder is not told: the
takeover is recorded in the audit log only.

---

## Profile change requests

A customer with an approved account can ask to change their legal name, preferred name,
phone or pickup address. The request waits in **Customer accounts → Profile change
requests** until Operations (or an administrator) approves or declines each part. Nothing on
the customer record changes before that.

The review shows, for each field, what the customer proposed, what was on file when they
asked, and what is on file now. **Changed since** means somebody else changed that field on
the record after the customer asked; approve it and the request is refused, so decline it
and let the customer ask again. After you approve, the fields you approved are on file and
are **not** marked Changed since. If one is marked later, somebody changed it after your
approval.

Every approval is in the audit log as one customer update, with each field's old and new
value: Audit access shows them under **Changes**, for example
`display_name: Hạnh → Chị Hạnh`.

What a customer does from their own account is in the audit log under their account
reference, `customer_account:CA-…`, in the **Actor** column: signing in and out, their
marketing choice, their language, and their change requests. A refused sign-in reads
**system**, because nobody knows who typed the password.

---

## Reading a customer profile

The summary card shows who they are, their status, and how to reach them. Below it:

| Tab | What it holds |
|---|---|
| **Overview** | Their details, shipping activity, next follow-up, and recent notes |
| **Shipments** | Activity figures and, if your role allows, recorded amounts |
| **Follow-ups** | Open and completed tasks |
| **Interactions** | The note timeline |
| **Address book** | Saved sender and recipient contacts |
| **Consent** | Marketing permission per channel, with its full history |
| **Referrals** | Who referred them, and whom they referred |

### What the status badge means

| Status | Meaning |
|---|---|
| **Prospect** | No shipment yet |
| **New** | One shipment, recently |
| **Active** | Shipped recently |
| **At risk** | Has not shipped in a while — a good time to check in |
| **Inactive** | Has not shipped in a long time |
| **Archived** | Someone archived the record; unrelated to shipping |

The exact day counts are set in Settings and shown next to each status, so you can always
see the rule being applied. Hover the ⓘ next to any figure to see how it is calculated.

### Qualifying shipments versus bookings

**Qualifying shipments** count only real shipping: a confirmed booking that Solaris
actually took custody of. Drafts, cancelled bookings, and returns are excluded.

**Bookings** counts everything booked, including cancellations.

They differ on purpose — one shows demand, the other shows what actually shipped.

---

## Notes

**Interactions → Add note**, or **Add note** on the Overview.

Every CRM note is **internal**. Customers never see them. Record what happened, the
channel, and the outcome, so the next person picking up the conversation is not starting
from nothing.

---

## Follow-ups

**Follow-ups** shows your tasks grouped **Overdue**, **Due today**, and **Upcoming**.
Switch to **All tasks** to see the team's workload.

Creating one: give it a subject, a purpose, a priority, and a due date and time. A
scheduled task must have a due date — that is what makes "overdue" meaningful.

Completing one: click **Complete**, record the outcome, and optionally schedule the next
task in the same step. Completing a task records an interaction automatically and
**never closes any other task** — each one is tracked on its own.

A completed task cannot be reopened. If more work is needed, create a follow-on task so
the history stays honest.

The system can create follow-up tasks for you when a customer becomes at risk. Those are
**internal tasks only** — the CRM never sends a customer a message.

---

## Consent

The **Consent** tab shows, per channel, whether the customer may receive marketing, and
the complete history of how that changed.

Recording a change **adds** to the history — nothing is overwritten. To record consent
you must supply a basis and an evidence reference: a ticket or reference number only,
never a name or an email address. Evidence references appear in the audit trail. "Unknown" is the honest default for imported contacts, and unknown
means **not** marketing eligible.

**Suppressed** means the address must not receive marketing. It does not stop account
email: a suppressed customer still gets the email to confirm their address, password
resets, and the message saying their account was approved, and shipment emails will
reach them too when those are sent. Only an administrator can release
a suppression, and the release is recorded with a reason. Recording a new consent event
cannot clear it.

Only Marketing and administrators can suppress an address. Operations records consent and
withdrawals but is not offered "Suppressed". To suppress, use **Suppress address** on the
Consent tab. Choose the channel, enter an **evidence reference** (ticket or reference
number only, no names) and a **reason**; both are required. The suppression,
a "suppressed" entry in the consent history and an audit entry are written together. The
customer is never told why, and cannot lift it. Audit access shows the evidence reference
on the audit entry.

The **By** column of the consent history says who recorded each change: a staff name,
`customer_account:CA-…` when the customer changed it themselves from their Customer
Account, or **System** for an import. The audit log names the customer's account the same
way for everything a customer does to their own record.

When a customer ticks the marketing box while registering for a Customer Account, the
approval records it as consent on the customer record, whether the reviewer creates a new
record or links an existing one. A suppressed address stays suppressed, and the opt-in has
no effect while it is.

A customer has **one email**. When you link a Customer Account to an existing customer
whose email is different, approving replaces the record's email with the account's
sign-in email. The preview says so, with both addresses, before you acknowledge it, and
the change is in the audit log. After that, the email on a customer with an active or
suspended account cannot be edited on the profile: the email field is read-only and says
so. To change it, an administrator deactivates the account first; the email can then be
edited like any other.

Operational messages about someone's shipment are a different thing from marketing
consent. A shipment, a referral, or receiving someone's parcel does not create consent.

---

## Segments

**Segments** holds saved views that update themselves as records change. Build one with
**New segment**: add conditions, choose whether **all** or **any** must match, and nest
groups for more complex rules. The plain-language summary under the name always describes
exactly what the segment does.

Each segment shows two numbers, and they are not the same:

- **Matching customers** — everyone the filter matches.
- **Marketing eligible** — the subset who may actually receive marketing, after consent
  and suppression are applied.

The eligible number is usually smaller. Use it, not the member count, when planning
outreach. Built-in segments cannot be edited; use **Save as copy**.

---

## Dashboard

The dashboard answers "what needs attention today".

- **New customers** covers the selected date range.
- **Active shipments**, **Follow-ups due**, and **Delivery exceptions** are labelled
  *Current state* — they show what is true right now, whatever range you pick.
- Every card and figure is clickable and opens the records behind it.

If a comparison figure is missing, there genuinely is not enough history to compute one.
The dashboard leaves it blank rather than inventing a percentage, and says so in the note
under the cards. Empty charts mean no qualifying shipments in that period — not zero
activity misreported as a flat line.

---

## Exporting

**Customers → Export** (admin) downloads a CSV that opens cleanly in Excel with Vietnamese
characters intact. Every export is recorded in the audit log with who ran it and how many
rows it covered.

A marketing export must exclude anyone who is not eligible. Use the segment's eligible
count, and check consent before sending anything.


---

## Bookings and shipments

**Shipments** lists every booking. Search accepts a Solaris Shipment ID, a package
reference, a recipient name, or a customer name, and you can filter by route, operational
status, booking state, owner, booking date, or exceptions only. The filters live in the
web address, so you can bookmark a view or send it to a colleague.

The **Packages** column reads as a sentence — "1 of 3 packages delivered" — because a
count on its own does not tell you whether the shipment is finished.

### Creating a booking

**Shipments → Create booking** opens a six-step workflow. The footer at the bottom stays
put: **Back**, **Save draft**, and **Continue**.

1. **Customer.** Find them by name, Customer ID, email, or phone. If they are new, create
   them here without losing your place.
2. **Route and service.** Pick the route group. Three of the four only allow one
   direction, so it is filled in for you; US Cross Border asks which way the parcel is
   going, or works it out from the addresses. Describe the contents in plain words. If the
   customer has their own order or PO number, put it in **Booking reference**: a customer
   with a Customer Account sees it on each row of **My shipments** and on the shipment's
   own page (since UAT round 12), and can find the shipment by typing part of it in
   **Search shipments** (since UAT round 11 they can also search by a package ID such as
   `…-01`, including a cancelled package's). Put nothing in it you would not want the
   customer to read.
3. **Sender and recipient.** Pick a saved address or type the details. Either way, **the
   booking stores its own copy**. Editing that saved address next month will not change
   this shipment — the paperwork you printed stays true.
4. **Packages.** One card per package: dimensions, weight, and what is inside. Use
   **Duplicate** for identical cartons. Centimetres or inches, kilograms or pounds — the
   system keeps what you typed *and* the converted value. Leave a measurement blank if it
   was not measured; zero is not accepted, because zero is a claim.
5. **Review.** Check everything. This screen tells you which fields lock afterwards.
6. **Confirmed.** The Solaris Shipment ID appears here, and only here — a draft never has
   one, so there is nothing to accidentally give a customer too early.

**Save draft** at any point. The draft appears in the list as "Draft — no ID yet" and you
can come back to it.

Clicking **Confirm booking** twice cannot create two bookings. The second click returns
the same booking, not a new one.

### What locks after confirmation

The **route group and direction**. That is deliberate: the route is part of the Solaris
ID, so changing it would change what an ID already given to a customer means.

Everything else — service type, transport mode, contents, declared value, owner, notes,
payment state — stays editable.

### If the route was wrong

**Cancel and rebook** (admin and operations). It cancels the original and opens a
replacement draft with the details copied across, so you can correct them. Confirming the
replacement issues a **new** Solaris ID. Both records link to each other, so anyone
looking at either one can see what happened.

The cancelled ID is retired for good. It is never given to another shipment.

---

## Packages

The **Packages** tab shows every package with its permanent reference
(`SX-CAV-…-01`), its measurements in both the unit you entered and the canonical one, and
its own status.

Adding a package after confirmation gives it the next number. **Cancelling** a package
keeps its reference — the reference is not reused, and it still finds this shipment if
someone scans an old label. A cancelled package drops out of the "1 of 3" count rather
than distorting it.

A confirmed shipment must keep at least one active package. If none should ship, cancel
the booking instead.

---

## Recording what happened

**Tracking → Record event.** Choose what happened, when it happened, and which package —
leaving the package blank applies it to every active package.

Two fields, two very different meanings:

- **Internal detail** is for the team. Customers never see it.
- **Publish this update** plus **public wording** is the customer-facing sentence. It
  needs its own words; internal detail is never promoted into it.

**When it happened** and **when you recorded it** are stored separately. Entering
yesterday's scan today is fine and honest — it shows as both.

### What counts as delivered

Only **Delivered to recipient**. Everything else is a milestone:

| You record | The shipment shows |
|---|---|
| Received at warehouse | Received at warehouse — **not delivered**, even for a parcel going on to Vietnam |
| Arrived destination | Arrived destination |
| Delivered to collection point | Out for delivery — a collection point is not confirmed delivery |
| Delivered to recipient | that package is delivered |

One of three delivered shows **Partially delivered** and "1 of 3 packages delivered".
Only when every active package has reached its recipient does the shipment read
**Delivered**.

Recording an older event later will not undo a newer one. The system takes the most recent
thing that happened, not the most recent thing typed.

Made a mistake? **Void** the event and give a reason. The record stays in the history —
corrections are visible, not erased.

---

## Transport legs and carrier numbers

**Transport legs** is the journey: origin pickup, consolidation or linehaul, destination
handling, final delivery. Tick **This leg delivers to the final recipient** only for the
leg that actually reaches the customer — a leg ending at a Solaris warehouse does not.

Carrier tracking numbers hang off a leg, and can be for one package or for the whole leg
(a consolidated master reference). When a carrier relabels a parcel, **retire** the old
reference and add the new one. The old one stays visible; nothing is overwritten.

**Nothing is connected to a carrier.** Numbers and links are recorded by hand and are not
being checked automatically. The panel says so on screen. If you paste a carrier link, it
is stored for someone to click — it is not being watched.

Assigning, changing, or retiring a carrier number never changes the Solaris Shipment ID or
a package reference.

---

## Printing labels

**Print labels** on the shipment header, the Packages tab, or straight after confirming.

Choose all active packages or specific ones. The preview on the right is the exact 4 × 6
shape so you can check you have the right parcel; the PDF is the thing that prints.

**Print at actual size: 4 × 6 in, portrait, 100% scale, browser headers and footers off.**
Do not use "fit to page" — it shrinks the barcode and it may stop scanning.

Each label carries the Solaris ID, the package reference, a scannable barcode of that
reference, a QR code to the tracking page, "Package 1 of 3", the recipient and
destination, the weight, and — in small print at the bottom —
**SOLARIS INTERNAL LABEL — NOT CARRIER POSTAGE.**

That line matters. This is our label, for our warehouse. It goes *alongside* the carrier's
label and must never cover the carrier's barcode.

**Reprinting is safe.** A reprint carries exactly the same identifiers; it does not issue
new ones. Every download is recorded with who did it and when, and shown in the reprint
history.

The system records that the PDF was generated. It has no way of knowing whether your
printer actually produced a label — check the print itself.

### Scanning

Scan a package barcode into the search box at the top of any page and press Enter. It
opens that shipment with the scanned package identified. Scanning the parent Solaris ID
opens the same shipment.

---

## What each role can do with shipments

| You are | Bookings | Cancel / rebook | Events and carriers | Labels | Money |
|---|---|---|---|---|---|
| **Admin** | Yes | Yes | Yes | Yes | Revenue and costs |
| **Operations** | Yes | Yes | Yes | Yes | Revenue only |
| **Marketing** | View only | No | No | No | None |
| **Read-only manager** | View only | No | No | No | Revenue only |

Costs are administrator-only. If your role cannot see them, the figures are not merely
hidden on screen — the server does not send them.

---

## Getting help

Something looks wrong? Note the customer ID and what you expected, and tell an
administrator — the audit log records what changed and who changed it, so most questions
can be answered from the record itself.

---

## What customers can see (Phase 3)

There is now a public tracking page. A customer with a Solaris Shipment ID or a package
reference can look up their own shipment at `/track`, in English or Vietnamese, without an
account. Scanning the QR code on a label opens that package's result directly.

### What they see

The Solaris Shipment ID, the route, the origin and destination **city and country only**,
the status in plain words, how many packages there are and how many have been delivered,
each package's reference and status, and the updates you have published.

### What they never see

Their address, their phone number, their email, the recipient's name, the booking
reference, your internal notes, any internal event detail, any amount of money, the
carrier's tracking number, a consolidation reference, who recorded an update, or anything
at all about another customer. None of it is sent to the page, so none of it can appear on
it — this is not a matter of the page choosing not to display it.

### This is why "Publish this update" has its own wording box

When you record an event there are two text fields, and the difference now has visible
consequences:

- **Internal detail** is for the team. It never leaves the building. A customer cannot see
  it even if they view the page source.
- **Public wording**, with **Publish this update** ticked, is the sentence a customer
  reads on the tracking page.

An event with no public wording still moves the shipment's status — the customer sees the
status change — but nothing about that event appears in the update list. That is usually
what you want: "Received at warehouse" as a status without the note about which shelf it is
on.

**Write the public wording as a sentence to a customer.** "Your parcels have left Canada"
rather than "DEP YYZ consol 014". It appears exactly as you type it.

### Write public updates in the customer's language

The page itself is fully bilingual — statuses, routes, dates, buttons, error messages all
switch between English and Vietnamese. **Your update text does not.** It is shown word for
word, in whatever language you wrote it.

So a Vietnamese-speaking customer reading the page in Vietnamese sees a Vietnamese page
with your English sentence in the middle of it. Check the customer's preferred language on
their profile before writing a public update, and write it in that language.

Nothing translates it automatically, on purpose: a machine translation of "held pending
paperwork" that comes out wrong is a service problem, and the wording you approve should
be the wording that is shown.

### Correcting a published update

**Void** the event and give a reason, then record the corrected one. The customer sees only
the current approved wording; the voided event disappears from their page immediately. The
original and the reason stay in the internal history, which is what makes the correction
auditable rather than invisible.

### Cancelled bookings

A cancelled shipment still resolves — the ID may be on paperwork the customer holds — but
the page shows only that the booking was cancelled. It does not replay the journey, and it
never shows your cancellation reason.

### What to tell a customer who cannot find their shipment

The page gives the same answer for a mistyped reference and for one that does not exist,
deliberately: it must not let a stranger discover which made-up IDs are real. So "we could
not find that shipment" genuinely does not tell you which of the two happened.

Ask them to read the reference back to you and check it against the record. Case and
spaces do not matter, and neither do the dashes if their email program changed them — the
page copes with all of that. A wrong character does not, and that is the usual cause.

If they looked it up several times in quick succession they may see "Too many lookups".
That clears itself in about a minute.

### The page does not refresh itself

It says so, and it is true. Solaris is not connected to any carrier's system yet. Every
update on that page is one a member of staff recorded. If a customer expects it to update
on its own, it will not — and the page tells them that rather than letting them assume.

If you have pasted a carrier's tracking link onto a leg, the page may offer it as a link
to the carrier's own site. Solaris does not read that page, so the two can disagree, and
the page says that too.

---

## The Integration infrastructure panel (Settings)

Administrators and read-only managers see a **Integration infrastructure** tab in Settings.
It is worth knowing what it is, because the name is deliberately not "Provider
integrations".

**It says "No provider account is connected", and that is the whole story.** Solaris is not
connected to ShipStation or to any carrier's system. Nothing is fetched, polled, or
synchronized. Every tracking number in the CRM was typed by someone, and every update a
customer sees was recorded by someone.

### So what is the panel for?

The plumbing a provider connection will eventually run on has been built and tested: a
place to store incoming notifications safely, a queue of work, and a worker to do it. The
panel shows that plumbing sitting idle. It exists so that when a provider *is* connected,
there is somewhere honest to look — and so nobody has to wonder whether something is
quietly broken in the meantime.

Everything on it is a real number or an explicit "we cannot tell". There is **no Connect
button and no Verify button**, because neither could do anything real. If you see one in a
future version, a provider has genuinely been connected and this page will have been
rewritten.

### What the numbers mean

| Line | What it tells you |
|---|---|
| **Connection state** | `Not configured` — the only truthful answer today |
| **Provider and version** | "Unknown until an account is verified". Not a placeholder waiting to be filled with a guess |
| **Last successful operation** | "Never". Nothing has run, because there is nothing to run against |
| **Pending / Running / Failed** | Queue depth. All zero today |
| **Oldest pending job** | The number that would reveal a stopped worker. Counts alone look the same whether work is flowing or frozen |
| **Awaiting verification** | Notifications from a provider that does not sign its messages, waiting to be checked directly rather than believed |
| **Stale tracking assignments** | **"Not measured"**, deliberately — not zero. Measuring staleness needs a provider's own update schedule, and there is no provider. Showing "0" would tell you everything is fresh, which nobody can promise |
| **Worker** | "No worker has reported in". Nothing is scheduled to run |
| **Failed jobs awaiting review** | Empty today |

### If a job ever appears in the review queue

An administrator can press **Retry job**. That is recorded in the audit log, adds exactly
one more attempt, and **keeps the record of what failed** — the attempt count carries on
rather than resetting, so a second failure looks like a second failure rather than a first.

A retry buys one attempt, not a restart. If it fails again, it comes back to the queue.

### What none of this changes for you

- **Manual milestones work exactly as before.** Record what happened, tick "Publish this
  update", write the customer-facing wording.
- **Carrier numbers and links work exactly as before.** Record them by hand; they are not
  being watched.
- **Bookings, labels, and public tracking are unaffected**, and stay unaffected whether the
  worker is running, stopped, or has never run at all.
- **The public tracking page has not changed.** It still says it does not refresh itself,
  because it still does not.

If somebody asks whether Solaris now has automatic tracking: **no**. What exists is the
groundwork for it, and the answer to what is still needed lives in
`docs/INTEGRATIONS.md`.

---

## Reports (Phase 5A)

**Reports → pick a date range.** Everything on the page is worked out from the records in
the CRM at the moment you load it. Nothing is typed in by hand and nothing is a sample.

### The date range means local dates

The range covers whole days in the office timezone. If you pick 1–30 September, a parcel
you handed over at 11:30 on the evening of the 30th is in September, where you would expect
it. The page says which timezone it used.

Ranges are capped at two years. If you need longer, run two reports.

### "Selected period" versus "Current state"

Every report is labelled with one of these, next to its title. It is the easiest thing on
the page to misread, so read it.

* **Selected period** — the figures are about the dates you chose.
* **Current state** — the figures are about *today*, and your date range does not apply to
  them. Customer lifecycle and shipment exceptions are like this: a customer is at risk
  now, not "at risk during August".

### What counts as a shipment

The same rule as everywhere else in the CRM. A qualifying shipment is a confirmed booking
that was actually handed over, not cancelled, and not a return.

* A three-package shipment is **one** shipment. The page shows you the package count
  alongside so you can see the difference rather than wonder about it.
* A shipment with four transport legs is **one** shipment.
* Drafts appear in one place only: the booking-state distribution.
* If you cancelled a booking and rebooked it, that is **one** shipment, not two and not
  none.
* Returns get their own line and are never added to the shipment count.
* A customer you merged into another is counted once — as the surviving record.

### Numbers the reports will not show you

These are missing on purpose. If somebody asks for them, this is the answer:

* **"How does that compare with last month?"** The reports show no comparison, no trend
  arrow, and no percentage change. A change figure only means something against a
  comparable previous period, and a made-up one is worse than none. Run the same report for
  last month and compare the two yourself.
* **"When did the carrier last update?"** There is no carrier integration connected, so
  there is no such time. Nothing on the page will pretend otherwise.
* **"What is the total across all currencies?"** Money is grouped by currency and never
  added together. No exchange rate has been recorded.
* **A blank share.** A share of nothing is blank, not 0%. If nobody shipped, there is
  nothing to divide.

### Getting from a number to the records

Click any row in a report and it opens the customers or shipments behind it, already
filtered. If a figure looks wrong, that is the first thing to do.

### Sharing a report

The date range and filters are in the address bar, so you can copy the link and send it. It
will show the same figures to whoever opens it, subject to what their role is allowed to
see.

### Money on reports

You will only see the financial report if your role includes financial access, and you will
only see cost and gross profit if it includes cost access. This is not the page hiding
things from you — the figures are not sent to your browser at all.

---

## Exporting (Phase 5A)

**Export** appears on the customer list and the shipment list when your role allows it.
Today that is Admin only for shipments and reports; the final permissions are still being
decided.

* **The file matches the screen.** Whatever filters are on the list are applied to the
  export. If you have filtered to Vietnamese-speaking customers, that is what you get — not
  everybody.
* **Open it in Excel.** The file is UTF-8 with a byte-order mark, so Vietnamese names open
  correctly without any import wizard.
* **Some columns are missing on purpose.** Internal notes, street addresses, recipient
  phone numbers and emails are not in any export. Carrier costs appear only for roles with
  cost access.
* **Every export is logged** — who, what type, which filters, how many rows. The contents
  are never logged.
* **A marketing audience is not a segment.** Exporting a segment's audience leaves out
  anybody who is suppressed, has withdrawn consent, has no recorded consent, is marked do
  not contact, or is archived. The audience file is usually smaller than the segment, and
  that is correct.

---

## Importing customers from a spreadsheet (Phase 5A)

**Customers → Import.** The workflow has four steps and only the last one changes anything.

### 1. Start with the template

Click **Download template**. It has the exact headings the import understands and two
example rows you can delete. Fill it in and save as **CSV UTF-8** — that is the only format
that reliably keeps Vietnamese names intact.

You do not have to use the template. Headings are matched regardless of capitals, spaces,
punctuation and accents, so `Full Name`, `full_name` and `Họ và tên` all work. Anything the
import does not recognize is listed for you and ignored.

### 2. Upload and read the preview

**Nothing is imported at this stage.** The page will say so, repeatedly, because it
matters. You can close the tab at any point before the last step and nothing will have
changed.

The preview tells you, for every row:

| Result | What it means |
|---|---|
| **New customer** | Nobody in the CRM looks like this person. It will be created. |
| **Already imported** | This exact row was imported before. It will be left alone. |
| **Possible duplicate** | Somebody in the CRM looks like this person. **You decide.** |
| **Cannot be imported** | Something is wrong with the row. It is left out; the rest still import. |

A row is rejected if it has no name, or no phone number and no email, or an email that is
not a valid address, or a value the CRM does not recognize in one of the fixed-choice
fields. The reason is written next to the row.

### 3. Decide about the duplicates

This is the step that needs a person. Families legitimately share a phone number and an
email address, so a match is not proof that two records are the same person.

For each one you choose:

* **Skip this row** (the default) — nothing happens to it.
* **Create separate customer** — a new record is created alongside the existing one.

**There is no merge option here, and nothing merges by itself.** If two records really are
the same person, import them separately and use the merge tool on the customer profile
afterwards, where you can see both records in full.

### 4. Confirm

The button says how many customers will be created. Clicking it opens a confirmation that
repeats the counts — how many will be created, how many duplicates skipped, how many rows
left out. Only after you confirm does anything get written.

You then get a summary with a batch number, and each created customer is a link. The
summary is kept, so you can look at it again later under **Recent imports**. The file
itself is not kept.

### Importing the same file twice

Safe. Import it again and the rows come back as **Already imported** — you get the same
customers, not two of each. This works whether or not your spreadsheet has an ID column: if
it does not, the CRM works out a stable key from the name, email and phone.

This means a half-finished import is easy to recover from: fix the rows that failed and
import the whole file again.

### If a row already exists

By default the existing record is left completely alone. There is a second option — **fill
fields that are empty, and only those** — which will add a city or a province to a record
that has none. It will never replace something a person typed.

### What an import will never do

* It will never merge two customers.
* It will never overwrite a value somebody entered.
* It will never record consent. Imported email addresses and phone numbers are **not**
  marketing eligible; consent has to be recorded in the CRM with its evidence, as always.
* It will never import a column the CRM does not understand.

### If the file is rejected

The message tells you what to fix. The most common ones:

| Message | Fix |
|---|---|
| "This looks like a ZIP archive or an .xlsx workbook" | Save the sheet as CSV, not as a workbook. |
| "The file is not valid UTF-8 text" | Save as **CSV UTF-8**. |
| "A quotation mark is opened and never closed" | Find the row with a stray `"` in it. |
| "Columns X and Y both map to the same field" | Delete or rename one of them. |
| "The file has more than 5,000 rows" | Split it and import each part. |

---

## Telling the customer (Phase 5A1)

**Shipment → Tracking → Record event.**

### The update is published by default now

"Publish this update to the customer" starts **ticked**, with a standard sentence already
chosen. Record the milestone and the customer is told — you do not have to remember a
second step.

Untick it when the event is genuinely internal: a damaged carton, a correction, a note for
the next shift. Nothing stops you.

### Four event types start unticked

**Exception**, **Delivery attempted**, **Return in progress** and **Awaiting parcel** do
*not* publish automatically. These are the moments where we know something is wrong but
not yet what, and a canned sentence would tell the customer something we cannot stand
behind. Once you know what happened, tick the box and publish.

### Standard updates versus your own wording

The **Standard update** dropdown holds approved sentences for that event type. Pick one
and you will see exactly what the customer reads, in **both English and Vietnamese**,
before you send it.

**This is the part worth understanding.** A standard update is stored as a choice, not as
a sentence. The tracking page then shows it to each customer in whichever language they
picked. Choose the standard "Your shipment is on its way" and a Vietnamese-speaking
customer reads it in Vietnamese — even though you were working in English.

Choose **Write my own wording** and you get a free text box. That text is published
exactly as you typed it, in one language only. A customer reading the page in Vietnamese
will see your English. Use it when no standard update fits — and prefer a standard one
when one does.

### What you cannot do

* You cannot publish both a standard update and your own wording on the same event. Pick
  one.
* You cannot publish a standard update belonging to a different event type.
* You cannot publish an update with no wording at all.
* Internal detail is never shown to a customer, on any event, ever.

### If the wording is wrong

Standard wording is never edited in place — a customer who read it last week would
otherwise see different words today. A new version is added instead. Tell whoever maintains
the catalogue; do not expect an existing sentence to change.

The Vietnamese in these templates has not yet been checked by a native speaker. If
something reads badly, say so — it is a known open item, not a surprise.

---

# Air masters, quotes and money (Phases 13 to 15)

Everything in this part is **air only** (Air Standard and Air Express, from Hồ Chí Minh City
or Hà Nội). Sea is not priced. On the practice system all of it runs on test data, and **no
email reaches anybody**: emails are written to a test folder, or only recorded.

**Who sees what.** The Workspace, Settings → Pricing and Settings → Tariffs need the tariff
permission, which Operations and Admin hold. They show the **vendor's cost**, which is
internal. It never reaches a customer, an invoice or the Customer Account. Some actions are
Admin only: saving pricing settings and invoice terms, importing or approving tariffs, and
CSV exports. Admin and Operations can both refund, void and reopen a month (OD-69).

## The Workspace

**Workspace** in the main navigation. One page per air **master**: the vendor's
consolidated shipment that carries several customers' goods.

### Masters

**Workspace → New master.** Choose the service (Air Standard or Air Express) and the
origin (HCM or HAN). Add the vendor's reference when you know it. The list shows each
master's state (**Open**, **Booked**, **Completed**, **Cancelled**), its customers and its
chargeable weight.

On an open master:

- **Add a customer's shipment.** Search by shipment ID, booking reference or customer name.
  Only confirmed Vietnam → Canada shipments can be added.
- **Edit master** for the weights and dimensions. **Cartons → Edit cartons** records each
  carton. The under-12 kg piece fee needs them on lots of 21 kg and over. Without them a
  multi-carton master is flagged.
- **Remove from master** takes a shipment off an open master. Give a reason.
- **Book with vendor** hands the master to the vendor. It freezes the members and the
  weights. Every member must still be a confirmed booking.

The **Vendor cost** panel shows base freight, the piece fee, the surcharges and the total in
VND, the Vietcombank rates used (a demo rate is labelled), and the cost by customer.
**Must be resolved before finalising** lists what blocks a quote. **Provisional** lists
what is only flagged.

### Items and fees

Each customer has a card. **Add item** records the goods: description, quantity, unit,
optional weight and notes. **Edit item** changes them later.

Under an item, **Add fee** searches the vendor's surcharges for the master's own origin.
Accents are optional, so `nuoc hoa` finds `nước hoa`. The form asks only for what that fee
needs: a quantity, a weight, or the vendor's price. A **manual quote** fee uses the file's
minimum, flagged, until you enter the vendor's price.

### Pricing a quote

In the customer's **Quote** panel:

1. **Price quote** (or **Re-price**) works out the figures: revenue, cost in VND and CAD,
   and the customer's cost share. Internal cost-share lines are marked "cost share only,
   not billed". If costs move afterwards, the panel says the quote is out of date.
2. **Confirm selling rate.** Leave the box empty to confirm the rate shown. A rate other
   than the default needs a reason, and it is audited.
3. **Finalise quote.** The server lists anything that blocks it. If a surcharge bills below
   its cost, finalising needs a reason. A finalised quote keeps its figures, whatever
   changes later.

**Print customer quote vN** opens a printable quote with our company details, the
customer's charges and the total before tax. It never shows cost, exchange rate or
markup.

### Sending the quote and the customer's answer

**Send to customer** sends the latest finalised version. The customer reads it in their
Customer Account (**Báo giá** / Quotes) and accepts or declines it. They also get an
email with a link. The email shows no amount (test capture only). The panel shows the
status: **Sent — waiting for the customer**, **Accepted**, **Declined** (with their reason,
if they gave one) or **Withdrawn**.

- **Withdraw** needs a reason. The customer never sees your reason, only that the quote is
  no longer valid.
- Re-pricing and finalising a newer version withdraws an unanswered quote automatically.
  You cannot send while a newer draft is open: finalise it first.
- **Resend email** appears when the email failed, or when the customer had no address and
  now has one.
- Accepting does **not** book or invoice anything. You see **Customer accepted vN — issue
  the invoice** with a **Go to Issue invoice** button. If a newer version was finalised
  after the acceptance, the panel says to agree the price with the customer first.

### Milestones for the whole master

**Milestones and closing → Record a milestone.** Record a milestone once and it is written
on every shipment on the master. Choose a standard update or write your own wording, not
both, exactly as on a single shipment. The result lists what each shipment got:
**Updated**, **Already had it**, or **Refused**, with the reason.

- **Complete master** is for a booked master whose shipments are delivered. The system
  only checks that the master is booked; waiting for delivery is up to you. It cannot be
  reopened.
- **Cancel master** (open or booked) needs a reason. It releases every shipment. It does
  not withdraw quotes already sent or accepted: the confirmation lists them so you can
  tell those customers.

## Finance

**Finance** in the main navigation has these tabs: **Invoices**, **Receivables**,
**Payables**, **Profitability** and **Month close**. Payables and Profitability show vendor
cost, so only roles with the tariff permission see them.

### Invoices

Issue invoices from the workspace: **Issue invoice** on a finalised quote. Choose
**GST/HST**: **0 %**, **5 %** or **13 %**. GST/HST applies only to domestic moves, and a
Vietnam → Canada shipment is 0 %. The invoice has revenue lines only. It is billed to the
shipment's payer, or else its customer. A shipment has one live invoice at a time. The due
date follows **Invoice terms** (Finance → Month close; Admin saves, 0 to 365 days, 0 means
due on issue).

**Accepted, not invoiced** (Finance → Invoices) lists the quotes customers accepted that
have no invoice yet. Each row links to its master. Nothing is invoiced automatically.

### Payments, refunds and voids

On an invoice, **Record payment**:

- **CAD**, or **VND** converted at Vietcombank's **selling** rate on the invoice date. The
  first VND payment fixes that rate for the invoice. If no recent rate is recorded for
  that date, the payment is refused until one is.
- A payment can never be more than the balance. Nothing is kept as credit (OD-68).
- Every payment gets a receipt (`RCT-`). Use **Print receipt** to print it.

**Refund** returns money against one payment, with a reason. **Void invoice** works only
when no money is held against it, so refund first. The number stays used, and you can
issue a new invoice. Admin and Operations can do both, and both are audited.

### Vendor bills

On a booked master, **Enter bill (start from the estimate)** records the vendor's actual
charge, in VND or CAD, beside the expected cost. A VND bill is converted at Vietcombank's
**buy** rate on the bill date, and that rate is frozen on the bill. If the bill differs
from the expected cost, give a reason. Then **Approve and split the cost** shares it across
the master's shipments. **Mark paid** when it is paid. **Void bill** needs a reason.

### Month close (M+7)

A month locks **seven days after it ends**. After that, late invoices and vendor bills are
booked in the next open month as adjustments. A payment or void dated in a locked month is
refused. **Close month** freezes the month's figures. **Reopen month** needs a reason.
Admin and Operations can reopen a month (OD-69). Profitability is an internal management figure by hand-in month, not an
accounting statement.

## Pricing settings and markups

**Settings → Pricing.** Everyone with the tariff permission can read it. Only Admin saves.

- **Air Standard default rate** (CAD per kg). **Air Express default rate** stays empty
  while there is no default, and Operations enters the rate on each Air Express quote.
  With no default, every Air Express rate counts as an override and needs a typed reason.
- **Share carried by the triggering customer**: for example 2 / 3 of a whole-master
  surcharge. The rest is split among the other customers.
- **Default surcharge markup**: **2 %** unless Admin changes it. It applies to every
  surcharge whose policy says **Default**.
- **Surcharge policies (air)**: per surcharge, choose **Default** (inherit the default
  markup), **Percent**, **Fixed amount** or **Pass through (no markup)**. Set the **Weight
  basis override** only when the vendor's sheet is read wrongly.

Changes apply to future quotes only. A finalised quote keeps its figures. Every change is
in the audit log.

## Tariffs and vendor rate emails

**Settings → Tariffs** is read-only for Operations. It lists every imported tariff version
(**Draft**, **Active**, **Superseded**, **Rejected by approver**). Each version shows its
air products and rate brackets, accessorial charges and beyond-area rates. The tab also
shows the Vietcombank exchange-rate history. Admin can use **Import a workbook by hand**
(.xlsx, at most 4 MB). The workbook becomes a **draft**.

**Settings → Tariff updates** (Admin) is for the vendor's rate emails. No mailbox is
connected. Save the vendor's email as an `.eml` file and **Upload a rate email**. Or the
person who runs the server drops it in the intake folder, and the intake worker picks it up.

- An email from a sender outside **Senders imported without review** is **Held: unknown
  sender** until an approver presses **Release**. By default every sender is held.
- An imported workbook becomes a **draft**. It never activates by itself.
- Only a **designated approver** (listed in **Approvers**; by default Ben) sees **Approve
  and activate** and **Reject**. They also see what changed against the active version.
  Rejecting needs a reason, and a rejected draft can never be activated.
- The approver sees a count on **Settings** and on the tab, for example "Tariff updates
  (2 waiting)".

## Milestone emails

A **published** milestone (Received at warehouse, In transit, Out for delivery, Delivered)
queues one email per shipment and milestone. On the practice system these emails are test
capture only.

- **Customer choices.** Each customer turns each milestone on or off in their account. All
  four are on until they turn one off. On the customer record, **Milestone emails** lets
  staff with the tracking permission change the choices for them.
- **Never behind.** No email goes out for a step behind the furthest one the shipment has
  already reached. Nothing goes out for a returned or cancelled shipment. Delivered is sent
  only when the whole shipment is delivered.
- **Settings → Customer notifications** is the outbox: each email's status and reason
  ("customer turned it off", "address suppressed", "no email address", "withdrawn (event
  voided)", "shipment returned or cancelled"). **Retry** a failed one. A suppressed
  address is never emailed.

## The Customer Account

Customers sign in at `/account`. It opens in **Vietnamese first**, with an English switch at
the top of every screen. A signed-in customer's saved language applies when they sign in.
They see:

- **Lô hàng của tôi** / My shipments, with each shipment's updates. Each update shows the
  standard sentence in their language, with your published wording beneath it.
- **Báo giá** / Quotes: the quotes you sent, which they can accept or decline.
- **Thông báo** / Notifications: their milestone email choices and what was sent.
- **Hồ sơ của tôi** / My profile. Changes to their name, phone or pickup address come to
  you as **Profile change requests** (see above).

The only money a customer sees in their account is **a quote you sent them**: the rate per
kg, the base charge, the surcharges they pay, and the total before tax (OD-77, which
narrows OD-32). They never see an invoice, a payment, a balance, our cost or a markup.

New accounts wait in **Customer accounts**. Operations or Admin read the application,
check the possible duplicates, take a preview and acknowledge the disclosure figures, then
approve or reject. Nothing is approved automatically.

The Vietnamese wording has not yet been checked by a native speaker. If something reads
badly, say so.

---

# Keeping the system safe (Phase 5B)

Four things every member of staff needs, regardless of role. The first two are about your
own account; the last two are what to do when something looks wrong.

## Your session, and keeping it yours

**Your account is yours alone.** Every change is recorded against the person who made it,
so a shared login means the audit trail names the wrong person — and the person it names
is the one who has to explain it.

| | |
|---|---|
| **Signing out** | Use the account menu. Closing the tab is not signing out |
| **Shared or public computers** | Sign out every time. Always |
| **How long a session lasts** | It ends after **8 hours of inactivity**, and after **24 hours** regardless. You will be asked to sign in again — this is normal, not a fault |
| **Too many wrong passwords** | Sign-in pauses for a few minutes. Wait, or ask an administrator |
| **Signing out everywhere** | If you think someone else has your session — a lost laptop, a borrowed computer — ask an administrator to revoke your sessions. This takes effect immediately, on every device |
| **Leaving the company** | Deactivating an account revokes its sessions in the same moment. There is no window where a deactivated account still works |

**Never send a customer's details over a channel that is not the CRM.** No customer lists
by personal email, no addresses in a chat message, no spreadsheets to a home account. The
CRM records who saw what; a chat message does not.

## When you are told you cannot do something

You will sometimes see a permission message, or find that a figure, button, or column is
simply not there. **Both are deliberate.**

| What you see | What it means |
|---|---|
| **"You do not have permission…"** | Your role does not include that action. It is not a fault |
| **A cost or profit figure is absent entirely** | Not blanked, not zero — **absent**. Costs are administrator-only, and for other roles the figure is not sent to your browser at all |
| **A whole report is missing from the page** | Same reason. The financial report is not sent to a role that may not see it |
| **An export button is not shown** | Bulk export is currently administrator-only while the final permissions are being decided |

**An absent figure is not a broken page.** The system is built so that a number you may not
see never reaches your browser, rather than being hidden by the screen. It is a stronger
guarantee, and it is why things sometimes look missing rather than locked.

**If you need an action your role does not have, ask an administrator** — do not ask a
colleague to do it under their login. That breaks the audit trail, which is the thing that
protects you both.

## Reporting a suspected data problem

A figure that looks wrong, a customer who appears twice, a shipment in the wrong state, a
tracking page showing something odd.

**Do this**

1. **Write down what you saw, before it changes.** The Solaris ID or customer name, what
   you expected, what you saw, and roughly when.
2. **Take a screenshot** if you can. If it shows another customer's details, share it
   internally only.
3. **Note what you had just done.** "After I confirmed a rebook" is far more useful than
   "the number was wrong".
4. **Report it** to your supervisor or the system administrator.

**Do not**

- **Do not "fix" it by editing records** until someone has looked. The wrong figure may be
  the only evidence of the cause, and correcting it can hide a bug that will recur.
- **Do not delete anything.**
- Do not assume it is your mistake and say nothing. A number that is wrong once is usually
  wrong in a pattern.

**Things that look like faults but are not**

| Looks wrong | Actually |
|---|---|
| A shipment count lower than expected | Drafts and cancelled bookings are excluded from shipping activity on purpose |
| A cancel-and-rebook showing as one shipment | Correct. One parcel, one shipment |
| A three-package shipment counting as one | Correct. Packages are never counted as shipments |
| A blank figure where you expected zero | Deliberate. Unknown is shown as unknown, never as zero |
| The public page not updating after you record an event | It does not refresh itself. The customer sees the update on their next visit |
| A report showing no comparison to last month | Correct. No trend or percentage change is calculated |

## Reporting a security incident

**Report immediately. Do not investigate first, and do not wait until you are sure.**

**Tell an administrator straight away if**

- You think someone else has used your account
- You received a message asking for your password, or a link that asked you to sign in
- A customer received information about a different customer
- An export, spreadsheet, or screenshot of customer data went to the wrong person
- A laptop or phone with access to the CRM was lost or stolen
- You were asked for customer details by someone you cannot verify
- Anything about the portal looks unfamiliar — an unexpected page, a strange prompt

**What to do first**

1. **Say something.** Speed matters more than certainty. A false alarm costs a
   conversation; a delayed report can cost a great deal more.
2. **If it is your account, ask for your sessions to be revoked** — do not just change the
   password. Revoking ends access on every device immediately.
3. **Do not delete anything**, including a misdirected email. It is evidence.
4. **Write down the time and what happened**, while you remember it.

**Do not**

- Do not try to find out how far it went yourself.
- Do not contact the affected customer before the owner has decided what to say. What is
  said first matters, and it may be a legal question.
- Do not discuss it outside the company.

**What happens next** is in `docs/RUNBOOKS.md` §10 and §11. Whether an incident must be
reported to anyone outside the company is a decision for the owner, taken with proper
advice — it is explicitly **not** a judgement for staff to make, and not one to guess at.
