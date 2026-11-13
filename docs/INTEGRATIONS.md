# Integrations

**Status: nothing is connected.** No provider account, API key, webhook, or paid service
has been configured, purchased, or activated. No tracking data has ever been received or
fetched by this application.

Provider integration was scheduled as **Phase 4**. As of 2026-09-10 the owner has
**deferred it to the final phase of the project** (DEC-0075, section 10 below). The
provider-neutral infrastructure built in Phase 4A remains in place and unmodified; only
the provider itself is deferred. This file exists so the integration status is recorded
honestly from the start, and so the verification work is written down before anyone starts
building against assumptions.

---

## 1. Current state

| Item | Status |
|---|---|
| ShipStation account | Not provisioned for this application. Product, version, and entitlements unknown. |
| API credentials | None issued. `backend/.env.example` carries commented placeholders only. |
| Webhooks | **None registered**, and no receiving endpoint exists. Phase 4A built the durable inbox, database-enforced deduplication, and the authenticity boundary they will use (section 8). |
| Carrier tracking | No provider is contacted. Phase 2 added a place to *record* a carrier name and tracking number by hand; nothing is fetched, polled, or synchronized. |
| Tracking source modes | Partially implemented: `manual` and `external_link` only. `connected_api` is refused by the service. |
| Integration health panel | Implemented in Phase 4A, and it truthfully reports `not_configured`. Settings → **Integration infrastructure**. No Connect or Verify button, because neither could perform a real operation. |

The Settings page shows no *provider* cards, because there are no providers. It shows an
**Integration infrastructure** panel instead, describing the inbox, the queue, and the
worker that exist — and stating plainly that no provider account is connected. A panel
titled for a connection that does not exist would be worse than its absence (DEC-0071).

### What Phase 2 added, and what it deliberately did not

`leg_tracking_references` stores a carrier name, a tracking number, an optional public
carrier link, and a source mode against a transport leg. That is a **placeholder**, not an
integration:

* `leg_service.add_tracking_reference` **rejects** `connected_api` with a message saying no
  provider account is connected. Only `manual` and `external_link` are accepted.
* A `public_url` is validated for scheme and host and then **stored and displayed. It is
  never fetched.** No server-side request is made to it, with or without credentials.
* Carrier names offered in the UI (`UPS`, `FedEx`, `Purolator`, `Canada Post`, `DHL`,
  `USPS`, `Viettel Post`, `Vietnam Post`, `Solaris Express`, `Other`) are labels. The API
  returns them alongside an explicit note that selecting one implies nothing, and the
  transport-legs panel repeats it on screen.
* Superseded references are **retired**, not overwritten, so a relabel keeps its history.
* Every operational event carries `source = "manual"`. When a provider eventually supplies
  events, they will be distinguishable from staff entries by that column alone.

Assigning, changing, or retiring a carrier reference never alters the Solaris Shipment ID
or a package reference — `backend/tests/test_booking.py` asserts this directly (AC-6).

---

## 2. Tracking source modes

`CRM.md` section 9 requires four explicit modes, and the UI must state which one is in
force for every shipment:

| Mode | Meaning | Status |
|---|---|---|
| **Connected API** | Real updates from a supported, authenticated provider | **Refused** until Phase 4 verifies an account |
| **External link only** | A validated public carrier link. **No** claim of automatic synchronization | Available |
| **Manual milestones** | Staff-entered, audited events | Available, and the default |
| **Demo** | Development fixtures, visibly isolated and never shown in production | Not implemented; no fixtures exist |

Receiving a tracking number or a URL does **not** authorize or enable API tracking.
Selectable carrier names must not imply that automatic integration exists for them.

---

## 3. Verification required before any code is written

`CRM.md` section 9 is explicit that ShipStation legacy, ShipStation V2, and
ShipStation API / ShipEngine endpoints and authentication must **not** be treated as
interchangeable. Before implementation, confirm against current official documentation
**and against the actual account**:

- [ ] Which ShipStation product and API version the account is entitled to
- [ ] The authentication scheme for that specific product
- [ ] Whether the account can track a label it did not purchase — if not, the limitation must be shown in the UI and external-link or manual mode offered instead
- [ ] Which webhook event types are actually available, and what each one means
- [ ] Whether webhook payloads carry a verifiable signature. **If they do not, treat every payload as an untrusted notification and verify state through an authenticated API read before applying it.**
- [ ] Documented rate limits, and the correct backoff and `Retry-After` handling
- [ ] Exact HTTPS hosts and paths for any `resource_url` fetch, so they can be allowlisted
- [ ] Carrier coverage for the four launch route groups

Legacy `SHIP_NOTIFY` indicates that a shipping label was created. It is **not** evidence
of a physical scan or of delivery. Documentation reviewed for the brief indicated that
ShipStation V2 supports label tracking by `label_id` and documents a `TRACK_EVENT_V2`
event; both need re-verification at implementation time rather than being taken on trust.

---

## 4. Design constraints already decided

These are settled, so Phase 4 does not have to relitigate them:

- Provider access sits behind an **adapter**. The rest of the application never depends on
  raw provider status codes; every provider status is mapped to the normalized operational
  states listed in `CRM.md` section 10.
- Webhook payloads are persisted durably and acknowledged promptly, then processed by a
  separate worker. The request process never performs long provider polling inline.
- Events are deduplicated by provider event ID or a stable fingerprint. Duplicates must
  not create duplicate timeline entries, delivered counts, revenue, or follow-up tasks.
- `occurred_at` and `received_at` are recorded separately. Missing timezone information is
  handled explicitly rather than assumed.
- A late "In Transit" event must not regress a shipment out of Delivered. Corrections and
  returns use explicit event semantics plus audit history, not naive status ranking.
- A failed refresh preserves the last known result and shows the last successful
  synchronization time. Provider outages and 429s apply bounded retries with jitter.
- Public page requests read cached results. If a result is stale, at most **one**
  deduplicated refresh is enqueued per assignment, so concurrent visitors cannot trigger
  repeated chargeable provider calls.
- Any `resource_url` fetch is restricted to an allowlist of exact documented HTTPS hosts
  and paths, blocks private and loopback destinations, and refuses unsafe redirects.
  Arbitrary URLs are never fetched with credentials.
- Credentials are server-side only. The API never returns a secret; the settings UI will
  show a masked indicator and a rotation action.

A missing API key must never prevent the CRM, manual milestones, or label printing from
working.

---

## 5. Sources to re-check at implementation time

These informed the brief and must be re-read rather than relied on from memory. Do not
infer an endpoint contract from a marketing page.

- ShipStation V2 tracking guide — <https://docs.shipstation.com/tracking>
- ShipStation webhook event guide — <https://help.shipstation.com/hc/en-us/articles/360025856252-ShipStation-Webhooks>
- ShipStation legacy `SHIP_NOTIFY` — <https://www.shipstation.com/docs/api/webhooks/subscribe/>

For any future marketing campaign work, verify CASL requirements against official CRTC
guidance (<https://crtc.gc.ca/eng/com500/faq500.htm> and
<https://crtc.gc.ca/eng/com500/guide.htm>) rather than encoding legal conclusions into the
CRM from assumptions.

---

## 6. Honesty rule

Do not describe this integration as live until a real event has been received or fetched
successfully from the actual account. Until then this document, the Settings page, and any
status report must say that provider tracking is not connected.

As of the Phase 3 completion this remains true without qualification: **no request has
ever been made to a carrier or to ShipStation by this application.** Every tracking number
in the system was typed by a person, and every operational event was entered by a person.

---

## 7. What Phase 3 changed, and what it deliberately did not

Phase 3 built the public tracking page. **No provider was contacted, and nothing was
connected.** The honesty rule in section 6 stands without qualification: no request has
ever been made to a carrier or to ShipStation by this application.

What Phase 3 added is the surface where a provider's absence becomes visible to customers,
so it had to be explicit about that absence rather than vague.

### Tracking source modes, as customers now see them

`CRM.md` section 9 requires four modes. The public page reports its own vocabulary, which
maps onto them without ever implying a connection that does not exist:

| Mode (`CRM.md` §9) | Public `tracking_state` | Shown to a customer as |
|---|---|---|
| Connected API | **absent from the vocabulary** | — |
| Manual milestones | `manual_updates` | "Updates entered by Solaris staff … This page does not refresh by itself." |
| External link only | `external_link_only` | "Carrier link only … We do not read that page for you." |
| Demo | `demo` | A persistent warning: "This is a synthetic development record." |
| *(none of the above)* | `no_public_milestones` | "No updates published yet." |
| *(none of the above)* | `tracking_unavailable` | "Tracking unavailable." |
| *(none of the above)* | `cancelled` | "Booking cancelled." |

`connected_api` is **absent from the public vocabulary** rather than present and unused, so
it cannot be selected by accident before Phase 4 verifies an account.

### What the public page will not do

These are constraints on the Phase 4 implementation as much as descriptions of today:

- **No `last_carrier_update` and no `last_successful_sync` field exists**, in the response
  or on the page. Those names are reserved for Phase 4 and were not added as nulls,
  because a null field is an invitation to populate it with something approximate.
  `last_public_update_at` is the occurred time of the newest **manual** update and is
  labelled as exactly that.
- **No freshness age.** Nothing says "updated 4 hours ago", because nothing is being
  updated.
- **A stored carrier link is never fetched.** Not to validate it, not to check that it
  resolves, not to render a preview. It is displayed and nothing more (DEC-0041).
- **Nothing polls.** There is no interval, no refetch on focus, no refetch on reconnect.
  The page is honest that it does not refresh itself, which would be false if it quietly
  did.
- **No estimated delivery is manufactured.** `estimated_delivery_at` is shown only when a
  real source supplied one, always labelled "Estimated", and withdrawn once the shipment
  is delivered, returned, or cancelled.

### The carrier link is judged twice

`leg_service._validate_public_url` decides what staff may **store**.
`public_tracking_service.is_safe_public_carrier_url` decides what a stranger may **see**,
and is strictly narrower (DEC-0053): HTTPS, no credentials, no fragment, no port, and a
host on `PUBLIC_CARRIER_LINK_HOSTS`, with private, loopback, link-local, and reserved
addresses refused outright. The source mode must be `external_link`; a `manual` reference
never becomes a public link. Where safety cannot be established the link is dropped whole
rather than rewritten.

The carrier's tracking **number** is not returned as a field. It does appear inside the
link's URL, because that is how every carrier addresses its own public tracking page — the
distinction, and the test that pins it down, is in `docs/DATA_DICTIONARY.md`.

**The nine default allowlist hosts have not been reviewed by anyone.** They are plausible,
not verified. Checking them is a production gate.

### What Phase 4 inherits

The seam is already in place and did not need a schema change:

- `shipment_events.source` is `"manual"` on every row. Provider events will be
  distinguishable by that column alone.
- `internal_detail` and `public_update_text` are separate columns, so a provider's raw
  description can be persisted without any risk of it reaching a customer.
- `public_tracking_service` is the single place that decides what a stranger sees, so
  adding a provider means adding rows, not widening the public surface.
- The public response model is standalone, so a provider field cannot arrive on the public
  page by inheritance.

When a provider is connected, the work on this surface is: add `connected_api` to the
public `TrackingState`, add the two freshness fields with real values behind it, and
translate both in each catalogue. Nothing else about the public page should need to change.

---

## 8. What Phase 4A built, and what it deliberately did not

Phase 4A built the **provider-neutral integration infrastructure**: everything whose
correctness does not depend on which product the account holds. It did not build a
ShipStation adapter, and the honesty rule in section 6 stands without qualification.

> **No provider account is connected. No adapter is registered. No webhook is registered.
> No request has ever been made to a carrier or to ShipStation by this application.**
> Every tracking number in the system was typed by a person, and every operational event
> shown to a customer was entered by a person.

### Why no adapter was written

`CRM.md` section 9 requires the account's actual product, API generation, entitlements,
authentication, webhook capabilities, signature mechanism, rate limits, external-label
tracking support, and resource hosts to be established **before** implementation, and
forbids treating legacy ShipStation, ShipStation V2, and ShipStation API / ShipEngine as
interchangeable. None of those has been established. An adapter written against guessed
fixtures would encode every one of those assumptions in code, and a passing test suite
would then read as evidence that the integration works.

So the work was split. The parts whose correctness is provider-independent — durable
storage, deduplication, leasing, retry policy, the authenticity boundary, the mapping
layer, and the SSRF policy — are built and tested. The parts that need answers are not.

### What exists

| Piece | State |
|---|---|
| Durable webhook inbox | Built. Deduplicated by a database constraint; bounded; authenticity recorded as its own field |
| Durable job queue | Built. Atomic claim, expiring leases, bounded retries, `Retry-After` handling, failed-job review |
| Worker | Built. `--once` and continuous with graceful shutdown. **Never run unattended** |
| Adapter contract | Built. Capabilities, not assumptions |
| Production adapter registry | **Empty**, and registration is refused in production |
| Normalized provider events | Built. Raw provider status preserved for audit, never published |
| Resource-fetch policy | Built and tested. **No network request is made**; production supplies no transport |
| Integration health API | Built. Reports `not_configured`, real counts, and explicit absences |
| Settings panel | Built. Titled "Integration infrastructure". No Connect or Verify button |
| ShipStation adapter | **Not built** |
| Webhook receiving endpoint | **Not built** — there is nothing to authenticate against |
| Provider connection | **Not created** |
| `connected_api` | **Still refused** by `leg_service` |

### The only adapter is a fake, and it is visibly a fake

`backend/tests/fakes/fake_provider_adapter.py`. Provider key `fake`, API version
`fake-v0`, statuses like `FAKE_MOVING` and `FAKE_HANDED_TO_RECIPIENT` chosen precisely
because no real carrier uses them, and an HMAC "signature" invented in that file.

**It is not ShipStation and does not model it.** It exists to exercise deduplication,
leasing, retries, the authenticity gate, mapping, and the resource policy — not to
anticipate a provider nobody has verified.

It cannot reach production for three independent reasons: it lives under `tests/`, which
is not packaged; its key is `fake`; and `AdapterRegistry.register` raises while the
environment is production. Three, because the cost of being wrong is a synthetic provider
answering a real customer.

### The authenticity rules, settled now

These are decisions Phase 4B inherits rather than relitigates:

* A **signature-capable** adapter must reject a missing, malformed, or invalid signature.
  Such a delivery is stored, marked `signature_missing` or `signature_invalid`, and creates
  **no job at all** — no number of attempts turns an invalid signature into a valid one.
* A **forged** event cannot mutate shipment or package state. Ever.
* If the provider has **no trustworthy signature**, the notification is
  `unsigned_untrusted`. It may enqueue **one authenticated read** and nothing else; the
  *answer* is what may move a parcel, and the status claimed in the body is ignored.
* Only `signature_valid` or `verified_by_read` may create a normalized provider event, and
  the worker re-checks that at application time rather than trusting the enqueue.
* **Replay detection is independent of authenticity.** A forged replay of a genuine event
  is still recognized as a replay, or the deduplication table becomes somewhere an
  attacker can write.
* Authentication failures are bounded to two attempts, far below the general allowance.
  Repeating a rejected credential achieves nothing and can lock an account.

**No signature algorithm has been invented for any real provider.**

### The resource-fetch allowlist is empty, and a test keeps it empty

`INTEGRATION_RESOURCE_ALLOWED_HOSTS` and `INTEGRATION_RESOURCE_ALLOWED_PATH_PREFIXES` are
both empty strings. An empty allowlist refuses everything, which is correct for a provider
whose documentation nobody has read.
`test_integration_resource_policy.py::test_the_production_allowlist_is_empty` fails if
somebody adds a plausible guess.

The policy itself is complete and tested: HTTPS only, exact host match (never a suffix),
exact path prefixes, no URL credentials, no fragment, approved ports, DNS checks rejecting
loopback, private, link-local, multicast, reserved and unspecified destinations for IPv4
and IPv6, revalidation after resolution and on every redirect, a strict hop limit,
credential stripping across origins, and response size, timeout, and content-type limits.

**No network request is made anywhere in Phase 4A.** The DNS resolver and the transport are
injected; production supplies no transport, so `fetch_guarded` refuses with
`fetch_disabled`.

---

## 9. What is still blocked, and exactly what is needed

Unchanged from section 3, and now the only thing standing between this infrastructure and
a working integration. **These are questions about the real account, not about
documentation in the abstract.** Answer them against current official documentation *and*
against the account itself.

| # | Question | What it decides in the code |
|---|---|---|
| 1 | Which ShipStation product and API generation is the account entitled to — legacy, V2, or ShipStation API / ShipEngine? | Which adapter is written at all. These are not interchangeable |
| 2 | What is the authentication scheme for that specific product? | `fetch_authoritative_state`, and what `credential_ref` names |
| 3 | Can the account track a label it did **not** purchase? | `ProviderCapabilities.tracks_external_labels`. If no, the interface must show the limitation and offer external-link or manual mode |
| 4 | Which webhook event types exist, and what does each actually mean? | The status map, and `mapping_version`. Legacy `SHIP_NOTIFY` means a label was created — **not** a scan or a delivery |
| 5 | Do webhook payloads carry a verifiable signature, and by what algorithm? | `verifies_signatures` and `verify_webhook`. **If no**, every notification stays `unsigned_untrusted` and only an authenticated read may move a parcel |
| 6 | Does the provider supply a stable event identifier? | `supplies_event_ids`. If no, deduplication falls back to a fingerprint, and the adapter must choose fields the provider does not rewrite between retries |
| 7 | What are the documented rate limits, and does the provider send `Retry-After`? | `documented_requests_per_minute`, and whether the existing `Retry-After` handling is exercised |
| 8 | Exactly which HTTPS hosts and path prefixes would a `resource_url` fetch need? | `ResourceHostPolicy`. Until answered, the allowlist stays empty and nothing is fetched |
| 9 | What is the carrier coverage for VCA, CAV, CAD, and XUS? | Whether the integration is useful for the launch lanes at all |

An answer of "no" to 3, 5, or 9 is a **useful** answer, not a blocker. It settles which
honest mode the interface offers, and the infrastructure already handles each case.

### What must happen before anything is described as live

1. A real event received or fetched successfully from the actual account.
2. `PRODUCTION_ADAPTERS` populated with a verified adapter.
3. A connection row created, with `credential_ref` naming a secret-store entry — never a
   value.
4. The resource allowlist filled from documentation, not from a guess.
5. `connected_api` accepted by `leg_service`, and `connected_api` added to the public
   tracking vocabulary along with the two freshness fields.

Until all five, this document, the Settings panel, and every status report say that
provider tracking is not connected.

---

## 10. Owner decision — provider synchronization is deferred to the final phase (Phase 5A)

Recorded 2026-09-10 as DEC-0075.

**The owner has deferred ShipStation and all live-provider work until the end of the
project.** Section 9 above is no longer a description of work about to start. It is a
description of work deliberately scheduled last. Everything in sections 1 through 8
remains accurate; only the timing changed.

### What this means concretely

| | State during Phase 5A and until the final phase |
|---|---|
| Production adapter registry | **Empty.** `PRODUCTION_ADAPTERS` contains nothing, and `test_the_production_registry_is_empty` fails the build if it ever does |
| Requests to a provider | **None have ever been made.** No transport is supplied in production, and no test in the suite performs a network request |
| Webhook endpoint | **Does not exist.** No HTTP route accepts a provider delivery |
| Resource host allowlist | **Empty**, along with the path-prefix allowlist. Asserted by `test_the_production_allowlist_is_empty` |
| `connected_api` tracking mode | **Refused** by `leg_service`, unchanged since Phase 2 |
| Carrier freshness, last update, last successful sync | **Not reported.** No value is fabricated, and `stale_assignment_count` stays `null` rather than a comforting `0` (DEC-0065) |
| Integration health state | **`not_configured`.** It is the only state the health service can truthfully return |

### What is preserved, and why that matters

Two tracking modes are in real use and are untouched by this deferral:

* **Manual milestones** — staff-entered, audited operational events. This is how a parcel
  moves through the system today.
* **External link only** — a validated public carrier tracking link, judged twice
  (DEC-0053), displayed and never fetched.

The entire provider-neutral seam built in Phase 4A is preserved intact and unmodified:
the durable webhook inbox, the deduplication constraint, the authenticity axis, the job
queue with leases and bounded retries, the worker, the adapter contract, the normalized
event mapping layer, and the SSRF resource policy with its 111 tests. Phase 5A adds
reporting and CSV import/export and touches none of those files.

That is the point of having built them provider-neutral. A deferral of the provider costs
nothing, because nothing in the infrastructure names a provider. When the final phase
arrives, the work is what section A8 of `PROJECT_STATUS.md` always said it was: one file
implementing `ProviderAdapter`, one registry entry, and one endpoint that hands a request
body to `integration_inbox_service.accept_delivery`.

### What Phase 5A specifically did not do with the integration surface

Reporting is the feature most likely to erode an honest integration boundary, because a
report wants a column for every dimension and an empty column looks like a bug rather than
a truth. Two rules were applied:

1. **No report displays a freshness, last-update, or last-successful-sync figure.** There
   is no such value. A plausible-looking one would be a fabrication, and a reader has no
   way to distinguish a fabricated freshness from a real one.
2. **The shipment-exception report groups by tracking source mode and shows only the modes
   that can exist**: `manual`, `external_link`, and `none`. It does not render an empty
   `connected_api` column. A column implies a mode that could have data in it.

`backend/tests/test_phase5a_integration_seam.py` asserts both, plus the empty registry,
the empty allowlist, the refused `connected_api`, the unchanged public tracking contract,
and that no report, export, or import code path imports a provider structure or creates an
integration job.

### The five steps that would end the deferral

Unchanged from section 9, and none of them was made harder by Phase 5A:

1. A real event received or fetched successfully from the actual account.
2. `PRODUCTION_ADAPTERS` populated with a verified adapter.
3. A connection row created, with `credential_ref` naming a secret-store entry.
4. The resource allowlist filled from official documentation.
5. `connected_api` accepted by `leg_service`, and added to the public tracking vocabulary
   along with the two freshness fields.

Until all five, this document, the Settings panel, every report, and every status summary
say that provider tracking is not connected.
