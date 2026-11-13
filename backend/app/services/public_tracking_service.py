"""Public tracking lookups.

This module is the only thing that decides what an unauthenticated visitor may see. It
is deliberately separate from ``shipment_service`` so the public path cannot drift into
the internal read path by someone adding a convenient field to a shared presenter.

Four rules shape everything below.

**Exact match only.** A public caller supplies a complete Solaris Shipment ID or a
complete package reference. There is no partial search, no name search, no phone search,
and no booking-reference search. A reference that does not pass strict validation is
never sent to the database (CRM.md section 10).

**One failure.** An invalid reference, a valid-but-unknown reference, a draft, and a
synthetic demo row in production all raise the *same* error with the same status, body,
and message. A lookup therefore cannot be used to confirm that an identifier exists, and
the high-entropy identifier stays the only thing standing between a stranger and a
customer's parcel status.

**Allowlist, not exclusion.** The result is built field by field. Nothing is serialized
from an ORM object, no internal schema is reused, and no ``**model.__dict__`` shortcut
exists anywhere in this file. A field appears on the public page because somebody wrote a
line adding it, which is a much better default than a field appearing because nobody
remembered to remove it.

**Honesty about tracking.** Phase 4 provider synchronization does not exist. Nothing here
fetches a carrier URL, polls a provider, invents a milestone, manufactures an estimated
delivery, or describes a staff-entered event as synchronized (CRM.md section 9).

**Published events only -- for the status as well as the timeline.** The stored
``operational_state`` on a shipment and on each package is derived by ``event_service``
from *every* non-voided event, published or not. Showing that value publicly let an
internal exception a staff member had not published surface on the tracking page as
"Delayed" (UAT-XX-02, fix pack of 2026-10-14). The public status, the per-package status,
the delivered count and the delivered time are therefore all derived here from the rows
``public_events`` returns and from nothing else, by the same rules ``event_service``
applies internally. A milestone a customer has not been told about does not move the
public state.

**A cancelled booking is not publicly retrievable.** It answers with the same 404 as an
unknown reference, so a stranger probing identifiers cannot confirm that a withdrawn
booking ever existed (UAT-XX-02). The authenticated Customer Account still shows its
owner the cancellation.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.enums import (
    ROUTE_GROUP_LABELS,
    BookingState,
    LegType,
    OperationalState,
    TrackingSourceMode,
    value_label,
)
from app.core.public_reference import PublicReference, parse_public_reference, reference_digest
from app.models import (
    LegTrackingReference,
    OrganizationSettings,
    Shipment,
    ShipmentEvent,
    ShipmentLeg,
    ShipmentPackage,
)
from app.schemas.public_tracking import (
    DataMode,
    PublicCarrierLink,
    PublicPackage,
    PublicPlace,
    PublicTimelineEntry,
    PublicTrackingResult,
    TrackingState,
)
from app.services import package_service
from app.services import public_update_templates as templates
from app.services.errors import NotFoundError
from app.services.event_service import ATTENTION_STATES, STATE_PROGRESS

logger = logging.getLogger("solaris.public_tracking")

#: The single customer-facing failure message. Used for every unsuccessful lookup so an
#: invalid format and an unknown identifier are indistinguishable.
GENERIC_NOT_FOUND = (
    "We could not find tracking information for that reference. Check the Solaris "
    "Shipment ID or package reference on your label or receipt and try again."
)

#: English country names for the lanes in scope. The frontend localizes from the code;
#: this is the fallback label, and an unknown code falls back to the code itself rather
#: than to an invented name.
_COUNTRY_NAMES = {
    "CA": "Canada",
    "VN": "Vietnam",
    "US": "United States",
}

#: Outcome categories recorded for abuse monitoring. Never the reference itself.
OUTCOME_FOUND = "found"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_MALFORMED = "malformed"
OUTCOME_RATE_LIMITED = "rate_limited"


@dataclass(frozen=True)
class _Match:
    shipment: Shipment
    selected_package: ShipmentPackage | None
    reference: PublicReference


# --- Lookup ---------------------------------------------------------------


def _not_found() -> NotFoundError:
    return NotFoundError(GENERIC_NOT_FOUND)


def _resolve(db: Session, reference: PublicReference) -> _Match:
    """Exact lookup. Every failure path raises the same generic error."""
    if reference.is_package:
        package = db.scalar(
            select(ShipmentPackage).where(ShipmentPackage.package_reference == reference.value)
        )
        if package is None:
            raise _not_found()
        shipment = db.get(Shipment, package.shipment_id)
        if shipment is None:
            raise _not_found()
        return _Match(shipment=shipment, selected_package=package, reference=reference)

    shipment = db.scalar(select(Shipment).where(Shipment.public_id == reference.value))
    if shipment is None:
        raise _not_found()
    return _Match(shipment=shipment, selected_package=None, reference=reference)


def _visible(shipment: Shipment) -> bool:
    """Whether this record may be shown publicly at all.

    A draft has no customer-facing identifier and must never be publicly retrievable, so
    this is belt and braces on top of ``public_id`` being NULL for drafts. A demo record
    is visible only outside production; in production it produces the same generic
    not-found response as any unknown reference, so a synthetic row can never be mistaken
    for real tracking (CRM.md section 3).

    A **cancelled** booking is not visible either. It used to answer with a safe
    "cancelled" summary, which was one more thing a stranger could learn by guessing: that
    an identifier had been issued at all. UAT-XX-02 requires a cancelled shipment and an
    unknown reference to be indistinguishable, so it now takes the same path a draft does.
    """
    if shipment.booking_state in {BookingState.DRAFT, BookingState.CANCELLED}:
        return False
    if not shipment.public_id:
        return False
    return not (shipment.is_demo_record and app_settings.is_production)


class _MalformedReference(NotFoundError):
    """A reference that never reached the database.

    Carries the *same* message, status, and body as every other failure -- it subclasses
    ``NotFoundError`` and adds no field -- so a customer cannot tell the two apart. The
    distinction exists solely so ``outcome_for`` can record an aggregate metric category
    without the route having to re-derive it, and so the route never has to hold a
    second, differently shaped error type (DEC-0051, DEC-0059).
    """


def track(db: Session, raw_reference: str | None) -> tuple[PublicTrackingResult, str]:
    """Resolve a public reference into its safe result.

    Returns ``(result, outcome_category)``. The caller logs only the category and a keyed
    digest -- never the submitted reference (CRM.md section 10).

    Validation happens before anything reaches the database, and the display timezone is
    read only once a shipment has actually resolved. The route runs the rate limiter
    before calling this at all, so a refused request performs no query (DEC-0059).
    """
    reference = parse_public_reference(raw_reference)
    if reference is None:
        # A malformed reference, an oversized one, an empty one, and an unknown one are
        # the same event to a caller. The distinction is an aggregate metric category and
        # nothing more.
        raise _MalformedReference(GENERIC_NOT_FOUND)

    match = _resolve(db, reference)
    if not _visible(match.shipment):
        raise _not_found()

    return build_result(db, match), OUTCOME_FOUND


def outcome_for(error: Exception) -> str:
    if isinstance(error, _MalformedReference):
        return OUTCOME_MALFORMED
    return OUTCOME_NOT_FOUND if isinstance(error, NotFoundError) else OUTCOME_MALFORMED


def log_lookup(raw_reference: str | None, outcome: str, *, client_key: str | None = None) -> None:
    """Record an abuse metric without recording the reference.

    Logging a tracking identifier would put it in a file, a log shipper, and quite
    possibly a third-party log search index, which is exactly what CRM.md section 10
    forbids. A keyed HMAC digest is enough to notice that one reference is being probed
    repeatedly, and cannot be turned back into an identifier without the application
    secret.

    Emitted as **structured fields** rather than an interpolated sentence since Phase 5B.
    The values are identical; what changed is that `reference_digest` now travels as a
    field the redaction filter recognizes as opaque. As one interpolated string it read
    as a single 29-character secret-shaped token and was replaced wholesale with
    `[redacted]`, which removed the only part of the line with any operational use.
    """
    from app.core.logging import log_event
    from app.core.public_reference import normalize_public_reference

    normalized = normalize_public_reference(raw_reference)
    digest = reference_digest(normalized, secret=app_settings.secret_key) if normalized else "empty"
    log_event(
        logger,
        logging.INFO,
        "public_tracking_lookup",
        outcome=outcome,
        reference_digest=digest,
        client_key=client_key or "unknown",
    )


# --- Result assembly ------------------------------------------------------


def _place(city: str | None, country_code: str | None) -> PublicPlace:
    """A coarse place. City and country only -- never a street, unit, or postal code."""
    code = (country_code or "").upper() or None
    return PublicPlace(
        city=(city or "").strip() or None,
        country_code=code,
        country_label=_COUNTRY_NAMES.get(code or "", code),
    )


def public_events(db: Session, shipment_id: int) -> list[ShipmentEvent]:
    """Events approved for publication, in occurred order.

    **Public since Phase 11**, and deliberately so. This filter is the entire privacy
    boundary for a timeline -- an event appears only when a staff member explicitly ticked
    "publish this update" *and* supplied approved wording, and only when a correction has
    not voided it. The authenticated Customer Account surface shows the same milestones, and
    a second copy of these clauses would be a second chance for one of them to drift into
    publishing ``internal_detail``. So the boundary is written once, here, and the Customer
    Account builds its **own** response objects from the rows it returns (DEC-0113).

    The rows are ORM events. Nothing but this module and
    ``customer_account_shipment_service`` may read them, and neither hands one to a
    response model.

    The filter is the whole privacy boundary for the timeline: an event appears only when
    a staff member explicitly ticked "publish this update" *and* wrote customer-facing
    wording, and only when it has not been voided by a correction. ``internal_detail`` is
    not read here and is not readable from the result shape.

    Ordering is deterministic. Occurred time drives it; recorded time and then the row id
    break ties, so two milestones stamped the same minute do not swap places between
    requests.
    """
    rows = db.scalars(
        select(ShipmentEvent).where(
            ShipmentEvent.shipment_id == shipment_id,
            ShipmentEvent.is_voided.is_(False),
            ShipmentEvent.is_public_update.is_(True),
            # Approved wording, arriving one of two ways: a template key the customer's
            # own language renders, or a sentence staff typed. An event with the flag but
            # neither is not publishable and is filtered out here rather than surfacing as
            # a blank milestone.
            or_(
                and_(
                    ShipmentEvent.public_update_text.is_not(None),
                    ShipmentEvent.public_update_text != "",
                ),
                and_(
                    ShipmentEvent.public_update_template_key.is_not(None),
                    ShipmentEvent.public_update_template_key != "",
                ),
            ),
        )
    ).all()
    return sorted(rows, key=lambda event: (event.occurred_at, event.recorded_at, event.id or 0))


def _timeline(
    db: Session, shipment_id: int, references: dict[int, str]
) -> list[PublicTimelineEntry]:
    """Approved public milestones, newest first, with identical entries grouped.

    Recording one shipment-wide milestone writes a row per active package, because
    per-package state is what package progress derives from (DEC-0045). A customer does
    not need to read the same sentence three times, so rows that agree on every visible
    attribute collapse into one entry listing the references they cover. The grouping is
    display only: no event is hidden, and a genuinely per-package update still stands on
    its own.
    """
    grouped: dict[tuple, PublicTimelineEntry] = {}
    order: list[tuple] = []
    screen = vendor_screen(db, shipment_id)
    for event in public_events(db, shipment_id):
        location = (
            _place(screen(event.location_label), event.location_country_code)
            if (event.location_label or event.location_country_code)
            else None
        )
        key = (
            event.operational_state,
            event.public_update_text,
            event.public_update_template_key,
            event.occurred_at,
            event.location_label,
            event.location_country_code,
        )
        reference = references.get(event.package_id) if event.package_id else None
        if key in grouped:
            if reference and reference not in grouped[key].package_references:
                grouped[key].package_references.append(reference)
            continue
        order.append(key)
        grouped[key] = PublicTimelineEntry(
            status=event.operational_state,
            status_label=value_label(event.operational_state),
            # ``message`` stays the readable fallback for any consumer that cannot
            # localize -- rendered in the catalogue's default language. The tracking page
            # prefers ``message_template_key`` and renders it in the reader's language,
            # which is the entire point of storing a key (DEC-0084).
            message=(
                screen(event.public_update_text)
                or templates.render(event.public_update_template_key or "")
                or ""
            ),
            message_template_key=event.public_update_template_key,
            occurred_at=event.occurred_at,
            location=location,
            package_references=[reference] if reference else [],
            # Every event in the system today was typed by a person. Nothing may be
            # described as a carrier scan or a synchronized update (CRM.md section 9).
            source_label="manual_update",
        )
    entries = [grouped[key] for key in order]
    for entry in entries:
        entry.package_references.sort()
    entries.reverse()  # newest first for display
    return entries


def vendor_screen(db: Session, shipment_id: int) -> Callable[[str | None], str | None]:
    """Screen staff-typed customer-facing text (a milestone message, a location) on output.

    The air vendor is never named to a customer (owner, Louis Tong, 2026-10-21, DEC-0222):
    the words that name a vendor are replaced by a neutral word in the customer's language
    ("đối tác vận chuyển" / "carrier"); the rest of the sentence stays. Shared with the
    Customer Account timeline.
    """
    from app.models import Customer  # noqa: PLC0415
    from app.services import notification_service  # noqa: PLC0415
    from app.services.customer_labels import customer_safe_text, vendor_names  # noqa: PLC0415

    names = vendor_names(db)
    shipment = db.get(Shipment, shipment_id)
    customer = db.get(Customer, shipment.customer_id) if shipment else None
    language = notification_service.language_for(db, customer)

    def screen(text: str | None) -> str | None:
        return customer_safe_text(text, names, language=language)

    return screen


def public_carrier_link(db: Session, shipment_id: int) -> PublicCarrierLink | None:
    """The first of :func:`public_carrier_links` (the response's ``carrier_link``), or None."""
    links = public_carrier_links(db, shipment_id)
    return links[0] if links else None


def public_carrier_links(db: Session, shipment_id: int) -> list[PublicCarrierLink]:
    """The public carrier links, only those that can be shown safely: at most one per generic
    tracking name (Master Tracking, Last Mile Tracking), in leg order (review, 2026-10-22).

    **Public since Phase 11**, for the reason ``public_events`` is: this is the policy that
    decides whether a stored link may be shown at all, and the authenticated surface asks
    the same question. The Customer Account copies the two values into its own model and
    never returns this one (DEC-0113).

    Everything about this is conservative on purpose. The link must be an active,
    external-link-mode reference; it must be HTTPS; it must carry no credentials, no
    fragment, and no port; its host must be on the configured allowlist of recognized
    public carrier sites; and a host that parses as an IP address, a loopback name, or a
    private-network address is refused outright.

    The URL is **never fetched**. Not to validate it, not to check it resolves, not to
    preview it. Phase 4 is where a provider is contacted, behind its own allowlist
    (CRM.md section 9, DEC-0041). If safety cannot be established the link is simply
    omitted -- the page says tracking is by manual update instead, which is true.

    The carrier's tracking *number* is deliberately not returned in any form.

    **Generic names** (owner, Louis Tong, 2026-10-22; DEC-0224). The link is shown under the
    generic name of its leg, never under the stored label: "Master Tracking" for the leg from
    Vietnam to the vendor's warehouse in Canada, "Last Mile Tracking" for the leg from the
    vendor's warehouse to the Solaris warehouse or the final destination
    (:func:`tracking_name_key`). A last-mile carrier link (UPS, Canada Post, the other allowed
    hosts) therefore stays visible even when staff labelled it with the vendor's name -- the
    RC-UAT-18 rule that hid such a link is reverted. A link whose **host** names a vendor stays
    hidden (stand-in): renaming it would still send the customer to the vendor's own site.
    """
    allowed = set(app_settings.public_carrier_link_host_list)
    if not allowed:
        return []

    rows = db.scalars(
        select(LegTrackingReference)
        .join(ShipmentLeg, ShipmentLeg.id == LegTrackingReference.leg_id)
        .where(
            ShipmentLeg.shipment_id == shipment_id,
            LegTrackingReference.is_active.is_(True),
            LegTrackingReference.source_mode == TrackingSourceMode.EXTERNAL_LINK,
            LegTrackingReference.public_url.is_not(None),
        )
        .order_by(ShipmentLeg.sequence.asc(), LegTrackingReference.id.asc())
    ).all()

    from app.services.customer_labels import names_a_vendor, vendor_names  # noqa: PLC0415

    names = vendor_names(db)
    links: list[PublicCarrierLink] = []
    seen: set[str] = set()
    for row in rows:
        if not is_safe_public_carrier_url(row.public_url, allowed_hosts=allowed):
            continue
        # Owner, 2026-10-22 (DEC-0224): the stored label is never shown -- the link reads as
        # its leg's generic name -- so a label naming the vendor no longer hides the link.
        # A host naming a vendor still does (stand-in): it is the vendor's own site.
        host = urlparse(row.public_url.strip()).hostname or ""
        if names_a_vendor(host, names):
            continue
        key = tracking_name_key(row.leg.leg_type if row.leg else None)
        if key in seen:
            continue
        seen.add(key)
        links.append(
            PublicCarrierLink(
                carrier_name=TRACKING_NAMES[key]["en"], tracking_name_key=key, url=row.public_url
            )
        )
    return links


#: The generic, customer-facing names of the two tracking legs (owner, 2026-10-22; DEC-0224).
#: The Vietnamese names are proposed, for review; the screens render them from the key.
MASTER_TRACKING = "master_tracking"
LAST_MILE_TRACKING = "last_mile_tracking"
TRACKING_NAMES = {
    MASTER_TRACKING: {"en": "Master Tracking", "vi": "Theo dõi chặng chính"},
    LAST_MILE_TRACKING: {"en": "Last Mile Tracking", "vi": "Theo dõi chặng cuối"},
}
#: Legs on the Vietnam side up to the vendor's warehouse in Canada (the air master).
_MASTER_LEG_TYPES = frozenset({LegType.ORIGIN_PICKUP, LegType.CONSOLIDATION_LINEHAUL})


def tracking_name_key(leg_type: str | None) -> str:
    """The generic name of a leg as a customer reads it.

    ``origin_pickup`` and ``consolidation_linehaul`` (Vietnam -> the vendor's warehouse in
    Canada) are **Master Tracking**; every other leg (``destination_handling``,
    ``final_delivery``, a staff-typed type such as ``last_mile``) runs from the vendor's
    warehouse to the Solaris warehouse or the final destination and is **Last Mile
    Tracking**. Staff screens keep the stored leg type, provider and carrier names.
    """
    return MASTER_TRACKING if leg_type in _MASTER_LEG_TYPES else LAST_MILE_TRACKING


def is_safe_public_carrier_url(url: str | None, *, allowed_hosts: set[str] | None = None) -> bool:
    """Whether a stored carrier link may be shown to the public.

    Separate from ``leg_service._validate_public_url``, which decides what staff may
    *store*. This decides what a stranger may *see*, and is strictly narrower.
    """
    if not url:
        return False
    hosts = (
        allowed_hosts
        if allowed_hosts is not None
        else set(app_settings.public_carrier_link_host_list)
    )
    if not hosts:
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.fragment:
        return False
    if parsed.port is not None:
        return False

    host = (parsed.hostname or "").lower()
    if not host or host not in hosts:
        return False

    # A hostname that is really an address, a loopback name, or a private range is not a
    # public carrier site even if somebody put it on the allowlist by mistake.
    if host in {"localhost"} or host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def _estimated_delivery(shipment: Shipment, public_state: str) -> datetime | None:
    """An estimate, only when a real source supplied one.

    Nothing here computes a transit time, and nothing infers a date from a route. If
    ``estimated_delivery_at`` is null it stays null and the page says nothing, which is
    better than a confident guess a customer will plan around (CRM.md section 10).

    A delivered or returned shipment does not show a future estimate either; the estimate
    has been overtaken by what actually happened. The state consulted is the **published**
    one, so an unpublished delivery does not silently withdraw the estimate.
    """
    if shipment.estimated_delivery_at is None:
        return None
    if public_state in {
        OperationalState.DELIVERED,
        OperationalState.RETURNED,
        OperationalState.CANCELLED,
    }:
        return None
    return shipment.estimated_delivery_at


# --- Published state ---------------------------------------------------------


@dataclass(frozen=True)
class _PublicPackageView:
    """One package as the public may see it: state and delivery from published events."""

    package: ShipmentPackage
    state: str
    delivered_at: datetime | None


def _public_package_views(db: Session, shipment: Shipment) -> list[_PublicPackageView]:
    """Per-package state from **published** events only.

    The same rule ``event_service._package_state`` applies -- the latest event by occurred
    time wins, and the delivered time is the earliest final-recipient delivery -- but over
    the rows ``public_events`` returns rather than over every event. A cancelled package is
    reported as cancelled whatever its events say, exactly as the internal derivation does.
    A package with no published event is "booked", which is the only honest thing to say
    about a parcel the customer has not been told anything about.
    """
    published = public_events(db, shipment.id)
    views: list[_PublicPackageView] = []
    for package in package_service.all_packages(db, shipment.id):
        if not package.is_active:
            views.append(_PublicPackageView(package, OperationalState.CANCELLED, None))
            continue
        own = [event for event in published if event.package_id == package.id]
        # `public_events` already orders by occurred, recorded, id -- the last row is the
        # latest-wins winner.
        state = own[-1].operational_state if own else OperationalState.BOOKED
        finals = [event.occurred_at for event in own if event.is_final_recipient_delivery]
        views.append(_PublicPackageView(package, state, min(finals) if finals else None))
    return views


def _public_overall_state(views: list[_PublicPackageView]) -> tuple[str, datetime | None]:
    """The shipment-level state, from the public package views.

    Mirrors ``event_service._overall_state`` clause for clause: every active package
    delivered is Delivered, some is Partially delivered (AC-7), an attention state on any
    package wins, and otherwise the shipment is only as far along as its least advanced
    active package. The two derivations share their vocabulary (``ATTENTION_STATES`` and
    ``STATE_PROGRESS``) so they cannot rank states differently.
    """
    active = [view for view in views if view.package.is_active]
    if not active:
        return OperationalState.CANCELLED, None
    delivered = [view for view in active if view.delivered_at is not None]
    if len(delivered) == len(active):
        return OperationalState.DELIVERED, max(view.delivered_at for view in delivered)
    if delivered:
        return OperationalState.PARTIALLY_DELIVERED, None
    states = [view.state for view in active]
    for attention in ATTENTION_STATES:
        if attention in states:
            return attention, None
    least = min(states, key=lambda state: STATE_PROGRESS.get(state, 0))
    return least, None


def _public_progress(views: list[_PublicPackageView]) -> package_service.PackageProgress:
    """ "1 of 3 packages delivered", counting only deliveries the customer was told about."""
    active = [view for view in views if view.package.is_active]
    delivered = [view for view in active if view.delivered_at is not None]
    return package_service.PackageProgress(
        total=len(views),
        active=len(active),
        cancelled=len(views) - len(active),
        delivered=len(delivered),
    )


def _tracking_state(
    shipment: Shipment,
    public_state: str,
    timeline: list[PublicTimelineEntry],
    carrier_link: PublicCarrierLink | None,
) -> TrackingState:
    """Which honest tracking story this shipment can tell.

    There is no "synchronized", no "last carrier update", and no freshness age, because
    no provider has ever been contacted. Those values belong to Phase 4 and are reserved
    rather than approximated (CRM.md section 9).

    **Demo is a fallback, not an override**, and that ordering was settled by looking at
    the rendered page. ``data_mode`` and the persistent banner it drives already say, in
    two places and in the reader's language, that a record is synthetic. Having
    ``tracking_state`` say it a third time pushed the same warning into the "how this
    shipment is tracked" line and displaced the one thing that line exists to say. So a
    demo row with published milestones reports ``manual_updates``, exactly as a real one
    would, and ``DEMO`` is reported only when there is no other honest story to tell --
    which keeps the value meaningful without letting it crowd out better information.

    ``CANCELLED`` stays in the vocabulary for the contract's sake but is no longer
    reachable: a cancelled booking is not publicly retrievable at all (see ``_visible``).
    """
    if timeline:
        return TrackingState.MANUAL_UPDATES
    if carrier_link is not None:
        return TrackingState.EXTERNAL_LINK_ONLY
    if shipment.is_demo_record:
        return TrackingState.DEMO
    if public_state == OperationalState.TRACKING_UNAVAILABLE:
        return TrackingState.TRACKING_UNAVAILABLE
    return TrackingState.NO_PUBLIC_MILESTONES


def _packages(
    views: list[_PublicPackageView], selected: ShipmentPackage | None
) -> list[PublicPackage]:
    """Safe per-package state, from the published view of each package.

    A cancelled package is shown as cancelled rather than hidden, because a customer
    holding a label for it deserves an answer, and its reference still resolves. It is
    counted separately so it cannot distort "1 of 3 delivered".
    """
    out: list[PublicPackage] = []
    for view in views:
        package = view.package
        if not package.package_reference:
            continue
        out.append(
            PublicPackage(
                package_reference=package.package_reference,
                status=view.state,
                status_label=value_label(view.state),
                is_selected=bool(selected and selected.id == package.id),
                is_cancelled=not package.is_active,
                delivered_at=view.delivered_at,
            )
        )
    return out


def display_timezone(db: Session) -> str:
    """The organization's display timezone, read at the last possible moment.

    Only ``office_timezone`` is read; the settings row is never serialized, so an
    organization-settings response contract is not a dependency of the public page. The
    row is read rather than created -- a public GET must not write -- and its absence
    falls back to the configured default.

    This used to be a FastAPI dependency, which meant it ran *before* the rate limiter
    and gave a refused caller a free database read. It is called from ``build_result``
    now, which is reached only after a shipment has resolved (DEC-0059).
    """
    row = db.scalar(select(OrganizationSettings).order_by(OrganizationSettings.id.asc()).limit(1))
    return (row.office_timezone if row else None) or app_settings.default_timezone


def build_result(db: Session, match: _Match) -> PublicTrackingResult:
    """Assemble the public result, one allowlisted field at a time.

    Read this function as the specification of the public surface. If a value is not
    assigned here, it is not published.
    """
    shipment = match.shipment

    views = _public_package_views(db, shipment)
    references = {
        view.package.id: view.package.package_reference
        for view in views
        if view.package.package_reference
    }

    timeline = _timeline(db, shipment.id, references)
    carrier_links = public_carrier_links(db, shipment.id)
    carrier_link = carrier_links[0] if carrier_links else None

    # Status, progress and delivery all come from the published view (module docstring).
    # `shipment.operational_state` and `shipment.delivered_at` are deliberately not read.
    public_state, delivered_at = _public_overall_state(views)
    progress = _public_progress(views)
    packages = _packages(views, match.selected_package)

    help_url = (app_settings.public_help_url or "").strip() or None

    return PublicTrackingResult(
        # Identity: the customer-facing identifiers only. No database id, no customer id,
        # no booking reference, no consolidation or master reference.
        shipment_reference=shipment.public_id,
        matched_reference_type=match.reference.kind,
        selected_package_reference=(
            match.selected_package.package_reference if match.selected_package else None
        ),
        # Route and coarse geography. City and country; never an address line, a postal
        # code, a recipient name, or a phone number.
        route_group=shipment.route_group,
        route_label=ROUTE_GROUP_LABELS.get(shipment.route_group, shipment.route_group),
        origin=_place(shipment.sender_city, shipment.sender_country_code),
        destination=_place(shipment.recipient_city, shipment.recipient_country_code),
        # Normalized status and derived progress, by the same rules the staff portal
        # uses -- a warehouse receipt is a milestone, one of three delivered is Partially
        # delivered, and a cancelled package never distorts the ratio -- but computed
        # over published events only.
        status=public_state,
        status_label=value_label(public_state),
        package_count_active=progress.active,
        package_count_cancelled=progress.cancelled,
        package_count_delivered=progress.delivered,
        progress_summary=progress.summary,
        packages=packages,
        estimated_delivery_at=_estimated_delivery(shipment, public_state),
        delivered_at=delivered_at,
        # Always null: a cancelled booking never reaches this function.
        cancelled_at=None,
        timeline=timeline,
        tracking_state=_tracking_state(shipment, public_state, timeline, carrier_link),
        # The newest approved *manual* update. Deliberately not called a carrier update
        # or a synchronization time, because it is neither.
        last_public_update_at=timeline[0].occurred_at if timeline else None,
        carrier_link=carrier_link,
        carrier_links=carrier_links,
        data_mode=DataMode.DEMO if shipment.is_demo_record else DataMode.LIVE,
        help_url=help_url,
        timezone=display_timezone(db),
    )
