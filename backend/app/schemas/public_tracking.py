"""Public tracking response models.

These are the **only** schemas the public surface may return, and they are deliberately
standalone. Nothing here inherits from, wraps, or embeds ``ShipmentDetail``,
``PackageOut``, ``EventOut``, ``LegOut``, or any other internal schema, and no model here
sets ``from_attributes``. That is not stylistic: an internal schema gains fields over
time, and a public model that inherits one would silently start publishing them. Every
value on this page is copied across by ``public_tracking_service`` field by field, from
an explicit allowlist (CRM.md section 10, AC-12).

If you are adding a field, the question to answer first is not "is it useful?" but "would
we be comfortable if this appeared in a search engine's cache, in a forwarded screenshot,
or in the hands of somebody who guessed an identifier?" The forbidden list in
``docs/PRODUCT_SPEC.md`` is the answer for everything currently known.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class PublicModel(BaseModel):
    """Base for public payloads.

    ``from_attributes`` is intentionally **off**. An ORM object can never be handed to
    one of these models; every field is assigned explicitly by the service.
    """

    model_config = ConfigDict(from_attributes=False, extra="forbid")


class TrackingState(StrEnum):
    """How this shipment is being tracked, stated honestly.

    Phase 4 provider synchronization does not exist. Until it does, no value here may
    imply that anything is fetched, polled, or synchronized (CRM.md section 9).
    ``CONNECTED_API`` is deliberately absent from this vocabulary rather than present and
    unused, so it cannot be selected by accident.
    """

    #: Staff-entered, audited milestones. The only real source of events today.
    MANUAL_UPDATES = "manual_updates"
    #: A validated public carrier link exists, but Solaris publishes no milestones for it.
    EXTERNAL_LINK_ONLY = "external_link_only"
    #: Confirmed, but nothing has been published yet.
    NO_PUBLIC_MILESTONES = "no_public_milestones"
    #: No tracking information is available for this shipment at all.
    TRACKING_UNAVAILABLE = "tracking_unavailable"
    #: A synthetic development record. Never reachable in production.
    DEMO = "demo"
    #: The booking was cancelled; only the cancellation is shown.
    CANCELLED = "cancelled"


class DataMode(StrEnum):
    LIVE = "live"
    DEMO = "demo"


class PublicPlace(PublicModel):
    """A coarse origin or destination: city and country only.

    No address line, no postal code, no company, no name. A city is coarse enough to be
    useful to the person tracking the parcel and useless to somebody who guessed an ID.
    """

    city: str | None = None
    country_code: str | None = None
    country_label: str | None = None


class PublicPackage(PublicModel):
    """One package's safe public state."""

    package_reference: str
    status: str
    status_label: str
    is_selected: bool = False
    is_cancelled: bool = False
    delivered_at: datetime | None = None


class PublicTimelineEntry(PublicModel):
    """One approved public milestone.

    Built only from events where ``is_public_update`` is true and ``public_update_text``
    is present. ``internal_detail`` is not readable from this shape, and the recording
    staff member, the internal event id, the leg, and the raw carrier data are all absent
    by construction.
    """

    status: str
    status_label: str
    #: The wording staff explicitly approved for customers. Never ``internal_detail``.
    #: When the milestone used a standard template this is that template rendered in the
    #: catalogue's default language, so a consumer that cannot localize still reads a
    #: sentence rather than a key.
    message: str
    #: Set when staff chose a standard update rather than typing one. A client that holds
    #: the template catalogue -- the tracking page does -- renders this in the language the
    #: reader picked, which ``message`` alone could never do (DEC-0084). It is an approved
    #: catalogue key and carries no shipment detail of its own.
    message_template_key: str | None = None
    occurred_at: datetime
    location: PublicPlace | None = None
    #: Which packages this milestone covers, when that is useful to say.
    package_references: list[str] = []
    #: "Manual update" today. Never claims a provider reported anything.
    source_label: str = "manual_update"


class PublicCarrierLink(PublicModel):
    """A public carrier tracking link, when one is safe to show.

    The carrier's tracking *number* is never included: the link is the whole affordance,
    and a bare number is a lookup key on somebody else's system.
    """

    #: The leg's generic name in English ("Master Tracking" / "Last Mile Tracking"), never
    #: the stored carrier or vendor name (owner, 2026-10-22; DEC-0224).
    carrier_name: str
    #: ``master_tracking`` | ``last_mile_tracking``: the page renders the reader's language.
    tracking_name_key: str
    url: str


class PublicTrackingResult(PublicModel):
    """The complete public tracking response. This list is the allowlist."""

    # --- Identity ------------------------------------------------------
    shipment_reference: str
    matched_reference_type: str  # "shipment" | "package"
    selected_package_reference: str | None = None

    # --- Route and geography -------------------------------------------
    route_group: str
    route_label: str
    origin: PublicPlace
    destination: PublicPlace

    # --- Status ---------------------------------------------------------
    status: str
    status_label: str
    package_count_active: int
    package_count_cancelled: int
    package_count_delivered: int
    progress_summary: str
    packages: list[PublicPackage] = []

    # --- Dates -----------------------------------------------------------
    #: Present only when a real source supplied one. Always labelled as an estimate.
    estimated_delivery_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None

    # --- Timeline and honesty -------------------------------------------
    timeline: list[PublicTimelineEntry] = []
    tracking_state: TrackingState
    #: When the newest approved public update happened. Not a carrier scan time.
    last_public_update_at: datetime | None = None
    carrier_link: PublicCarrierLink | None = None
    #: Every safe link, at most one per generic tracking name, in leg order (2026-10-22);
    #: ``carrier_link`` is the first of them.
    carrier_links: list[PublicCarrierLink] = []

    # --- Presentation context -------------------------------------------
    data_mode: DataMode = DataMode.LIVE
    help_url: str | None = None
    timezone: str


class PublicTrackingError(PublicModel):
    """The single failure shape.

    An invalid reference, a correctly formed unknown reference, a draft, and a demo row
    in production all produce **this exact body** with the same status code, so a lookup
    cannot be used to confirm that an identifier exists (CRM.md section 10).
    """

    code: str = "tracking_not_found"
    message: str
