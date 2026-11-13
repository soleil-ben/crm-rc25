"""Customer Account shipment response models. Standalone, and standalone on purpose.

These are the only schemas the authenticated shipment routes may return. Read the two
field lists below as the specification of that surface: a value a customer sees is a value
somebody wrote a line for here and in ``customer_account_shipment_service``.

**What "standalone" forbids, spelled out**, because every one of these was available and
every one was declined (OD-31, `SHIPMENT_ALLOWLISTS.md` §1):

* no model here inherits ``PublicTrackingResult``, ``PublicPackage``, ``PublicPlace``,
  ``PublicTimelineEntry`` or ``PublicCarrierLink``;
* no model here inherits ``ShipmentDetail``, ``ShipmentListItem``, ``PackageOut``,
  ``EventOut``, ``LegOut`` or any other staff schema;
* the public models are not imported and re-exported under a Customer Account name -- an
  alias is inheritance with the paperwork hidden;
* nothing here sets ``from_attributes``, so a ``Shipment`` ORM object cannot be handed to
  one of these models by accident;
* ``extra="forbid"`` everywhere, so a service that grew a field and passed it along is an
  error rather than a disclosure;
* the two enums are **re-declared** rather than imported, so widening the public tracking
  vocabulary does not silently widen this one.

The cost is duplication, and the duplication is the feature. The authenticated detail
begins at parity with the public 24 because parity was the decision, not because it is the
same object: release 1 adds *authentication and ownership* without also opening a new
disclosure surface, and any later divergence -- in either direction -- arrives as an edit
to one of these two files rather than as a schema that grew while nobody was counting.

``tests/test_account_shipment_contract.py`` asserts the field counts by name, the mutual
non-subclassing, and that ``PublicTrackingResult`` is still exactly 24 fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AccountShipmentModel(BaseModel):
    """Base for every model in this module. Not shared with any other surface."""

    model_config = ConfigDict(from_attributes=False, extra="forbid")


class AccountTrackingState(StrEnum):
    """How this shipment is tracked, in the Customer Account's own words.

    Re-declared rather than imported from ``app.schemas.public_tracking``. The values match
    today because parity was the decision; the *vocabularies* are separate so that adding a
    member to one is not a change to the other. ``connected_api`` is absent here for the
    same reason it is absent there: no provider has ever been contacted, and a value that
    does not exist cannot be selected by accident (CRM.md section 9).
    """

    MANUAL_UPDATES = "manual_updates"
    EXTERNAL_LINK_ONLY = "external_link_only"
    NO_PUBLIC_MILESTONES = "no_public_milestones"
    TRACKING_UNAVAILABLE = "tracking_unavailable"
    DEMO = "demo"
    CANCELLED = "cancelled"


class AccountDataMode(StrEnum):
    """Live or demo. ``DEMO`` is declared and unreachable on this surface.

    The inclusion rule excludes ``is_demo_record`` rows outright, in every environment, so
    an authenticated customer never sees one. The member exists so the field has a closed
    type rather than a free string, and a test asserts the value is always ``live``.
    """

    LIVE = "live"
    DEMO = "demo"


# --- The list ----------------------------------------------------------------


class AccountShipmentListItem(AccountShipmentModel):
    """One row of the authenticated shipment list. **Eighteen fields, and nothing else.**

    The set is `SHIPMENT_ALLOWLISTS.md` §3, reproduced in `PROJECT_STATUS.md` §24.7 with
    the source column, the transformation, the nullability and the privacy rationale for
    each. What is *not* here matters as much: no recipient name, company, phone, email or
    address; no sender name or address; no money field; no ``payment_state``; no
    ``contents_description`` or ``declared_value``; no ``internal_notes``; no
    ``owner_user_id``; no row id; no ``customer_id``; no idempotency key or import
    mechanics. ``booking_reference`` was added in UAT round 11 (DEC-0160): it is the
    customer's or partner's own reference for the booking, and the keyword search already
    read it.

    A field is not added here because a screen would find it convenient. It is added by
    editing `SHIPMENT_ALLOWLISTS.md` first, which is a review, and then this class.
    """

    # --- Identity -----------------------------------------------------
    shipment_reference: str
    #: The customer's or partner's own reference for the booking (`DATA_DICTIONARY.md`),
    #: or None when none was given. The detail carries it too since UAT round 12 (DEC-0163).
    booking_reference: str | None = None

    # --- Dates --------------------------------------------------------
    #: Stored naive UTC, exactly as every timestamp in this system is. The organization's
    #: display timezone travels once, on the page envelope, rather than on every row.
    booked_at: datetime | None = None

    # --- Route, coarse -------------------------------------------------
    route_group: str
    route_label: str
    origin_city: str | None = None
    origin_country_code: str | None = None
    destination_city: str | None = None
    destination_country_code: str | None = None

    # --- Status ---------------------------------------------------------
    status: str
    status_label: str
    package_count_active: int
    package_count_cancelled: int

    # --- Closure ---------------------------------------------------------
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    last_public_update_at: datetime | None = None

    # --- Derived flags (OD-29 safe states) --------------------------------
    #: Derived from ``booking_state``, so a screen can mark the row without parsing a
    #: status string and without a second vocabulary to keep in step.
    is_cancelled: bool
    #: True when this shipment was replaced by a rebooking. **The replacement's reference
    #: is deliberately not disclosed**: the replacement is itself a shipment and appears on
    #: its own row if and only if it belongs to this same customer. Linking the two in the
    #: response would be a second disclosure decision, and it has not been made
    #: (`SHIPMENT_ALLOWLISTS.md` §5).
    is_rebooked: bool


class AccountShipmentListPage(AccountShipmentModel):
    """The list envelope.

    Deliberately **not** ``app.schemas.common.Page``: that model sets
    ``from_attributes=True`` and is the staff envelope, and the whole rule on this surface
    is that no model reachable from a customer response can serialize an ORM object.

    ``timezone`` is envelope metadata rather than an eighteenth item field. The dates in
    every row are naive UTC; this is the organization timezone a client renders them in, so
    a fifty-row page carries it once.
    """

    items: list[AccountShipmentListItem] = []
    total: int
    limit: int
    offset: int
    timezone: str


# --- The detail ---------------------------------------------------------------


class AccountPlace(AccountShipmentModel):
    """A coarse origin or destination: city and country only.

    No address line, no unit, no postal code, no company, no contact name. The same
    granularity Public Tracking publishes to a stranger, which is the ceiling release 1
    chose for an authenticated shipper too.
    """

    city: str | None = None
    country_code: str | None = None
    country_label: str | None = None


class AccountPackage(AccountShipmentModel):
    """One package's safe state. A cancelled package is shown as cancelled, not hidden."""

    package_reference: str
    status: str
    status_label: str
    is_selected: bool = False
    is_cancelled: bool = False
    delivered_at: datetime | None = None


class AccountTimelineEntry(AccountShipmentModel):
    """One approved public milestone.

    Built only from events a staff member explicitly marked publishable *and* gave
    customer-facing wording. ``internal_detail`` is not readable from this shape; neither
    is the recording staff member, the internal event id, the leg, or any carrier payload.
    That is by construction -- there is no field for any of them -- rather than by a filter
    somebody has to remember.
    """

    status: str
    status_label: str
    #: Phase 15: the published event's type (the public event vocabulary, e.g.
    #: ``delivered_to_collection_point``), so the account shows the standard wording for that
    #: step in the customer's language, with the staff's published text beneath it. A
    #: vocabulary value, never an internal note.
    event_type: str
    #: Phase 15 review: ``package`` when the entry concerns some, not all, of a multi-package
    #: shipment's parcels ("One of your parcels has been delivered", AC-7); ``shipment``
    #: otherwise. Derived from the package references already listed; no package internals.
    scope: str = "shipment"
    #: The approved wording. Never ``internal_detail``.
    message: str
    #: Set when staff chose a standard update rather than typing one. An approved catalogue
    #: key carrying no shipment detail of its own, which a client renders in the reader's
    #: language (DEC-0084).
    message_template_key: str | None = None
    occurred_at: datetime
    location: AccountPlace | None = None
    package_references: list[str] = []
    #: "manual_update" today, and nothing here may ever claim a provider reported anything.
    source_label: str = "manual_update"


class AccountCarrierLink(AccountShipmentModel):
    """A public carrier tracking link, when one is safe to show.

    The carrier's tracking **number** is never included, on this surface any more than on
    the public one: a bare number is a lookup key on somebody else's system, and handing
    one to an authenticated customer makes it no less of an unapproved reference.
    """

    #: The leg's generic name in English ("Master Tracking" / "Last Mile Tracking"), never
    #: the stored carrier or vendor name (owner, 2026-10-22; DEC-0224).
    carrier_name: str
    #: ``master_tracking`` | ``last_mile_tracking``: the account renders it in vi or en.
    tracking_name_key: str
    url: str


class AccountShipmentDetail(AccountShipmentModel):
    """The authenticated shipment detail. **Twenty-five top-level fields, and no others.**

    The same field names and semantics the Phase 8 specification approved for the public
    contract, **re-declared here** rather than referenced (OD-31,
    `SHIPMENT_ALLOWLISTS.md` §4), plus ``booking_reference`` since UAT round 12
    (DEC-0163), the first field the authenticated detail carries that Public Tracking does
    not. ``PublicTrackingResult`` is untouched by this file's existence and stays at
    exactly 24 fields, asserted by its own unchanged test.

    Why parity rather than richer: an authenticated shipper could justifiably see more than
    an anonymous reference-holder, but "could justifiably" is a decision and each field is
    a separate one. Starting at parity means release 1 adds authentication and ownership
    without also adding a disclosure surface nobody reviewed. The candidates a later phase
    may propose -- finer recipient granularity, contents description, declared value,
    per-leg progress, attachments -- are named in that document and are not here.
    """

    # --- Identity ------------------------------------------------------
    shipment_reference: str
    #: The customer's or partner's own reference for the booking, trimmed, or None when
    #: none was given: the list row's field 1a, shown on the detail too (DEC-0163). Owner
    #: only, like every field here; Public Tracking never carries it.
    booking_reference: str | None = None
    #: Always ``"shipment"``. This route is addressed by Solaris Shipment ID only; there is
    #: no package-reference lookup on the authenticated surface, because a package
    #: reference is a second identifier space to authorize and release 1 did not open one.
    matched_reference_type: str
    #: Always ``None`` for the same reason. Declared because the approved field list
    #: declares it, and because a field that is present and constant is a smaller surprise
    #: than a field a later phase has to add back.
    selected_package_reference: str | None = None

    # --- Route and coarse geography --------------------------------------
    route_group: str
    route_label: str
    origin: AccountPlace
    destination: AccountPlace

    # --- Status -----------------------------------------------------------
    status: str
    status_label: str
    package_count_active: int
    package_count_cancelled: int
    package_count_delivered: int
    progress_summary: str
    packages: list[AccountPackage] = []

    # --- Dates -------------------------------------------------------------
    estimated_delivery_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None

    # --- Timeline -----------------------------------------------------------
    timeline: list[AccountTimelineEntry] = []
    tracking_state: AccountTrackingState
    last_public_update_at: datetime | None = None
    carrier_link: AccountCarrierLink | None = None
    #: Every safe link, at most one per generic tracking name, in leg order (2026-10-22);
    #: ``carrier_link`` is the first of them.
    carrier_links: list[AccountCarrierLink] = []

    # --- Presentation --------------------------------------------------------
    data_mode: AccountDataMode = AccountDataMode.LIVE
    help_url: str | None = None
    timezone: str
