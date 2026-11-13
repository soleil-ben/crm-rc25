"""Domain enumerations.

Values are stored as short stable strings. Human labels live in the frontend
translation catalogue so the internal UI stays localization-ready (CRM.md section 14).
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    # Operations absorbed Customer service (DEC-0088). The two were never independent:
    # the Operations set was a strict subset of the Customer service set, so the merged
    # role is the former Customer service permission set under the Operations name, and
    # no permission was invented to create it. Rows written before the merge are migrated
    # by Alembic revision ``a1c7f4d92b30``.
    OPERATIONS = "operations"
    MARKETING = "marketing"
    READ_ONLY_MANAGER = "read_only_manager"


class PreferredLanguage(StrEnum):
    EN = "en"
    VI = "vi"
    FR = "fr"
    OTHER = "other"
    UNKNOWN = "unknown"


class CustomerCategory(StrEnum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class BusinessType(StrEnum):
    ONLINE_SELLER = "online_seller"
    RETAILER = "retailer"
    OTHER = "other"


class ShippingPurpose(StrEnum):
    PERSONAL_ITEMS = "personal_items"
    GIFTS_FAMILY_SUPPORT = "gifts_family_support"
    ONLINE_ORDERS = "online_orders"
    RETURNS = "returns"
    BUSINESS_SAMPLES = "business_samples"
    MOVING = "moving"
    OTHER = "other"
    UNKNOWN = "unknown"


class ShippingFrequency(StrEnum):
    ONE_TIME = "one_time"
    OCCASIONAL = "occasional"
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    FREQUENT = "frequent"
    UNKNOWN = "unknown"


class RouteGroup(StrEnum):
    """The four launch route groups (CRM.md section 6)."""

    VCA = "VCA"  # Vietnam -> Canada
    CAV = "CAV"  # Canada -> Vietnam
    CAD = "CAD"  # Domestic Canada
    XUS = "XUS"  # US Cross Border


ROUTE_GROUP_LABELS: dict[str, str] = {
    RouteGroup.VCA: "Vietnam to Canada",
    RouteGroup.CAV: "Canada to Vietnam",
    RouteGroup.CAD: "Domestic Canada",
    RouteGroup.XUS: "US Cross Border",
}


class ShipmentDirection(StrEnum):
    """Explicit origin-to-destination direction (CRM.md section 6).

    Direction is validated server-side against the route group, so a bypassed frontend
    cannot book an out-of-scope lane. US to US is deliberately absent: it is out of
    scope and must never be silently classified as cross border.
    """

    VN_TO_CA = "vn_to_ca"
    CA_TO_VN = "ca_to_vn"
    CA_TO_CA = "ca_to_ca"
    CA_TO_US = "ca_to_us"
    US_TO_CA = "us_to_ca"


DIRECTION_COUNTRIES: dict[str, tuple[str, str]] = {
    ShipmentDirection.VN_TO_CA: ("VN", "CA"),
    ShipmentDirection.CA_TO_VN: ("CA", "VN"),
    ShipmentDirection.CA_TO_CA: ("CA", "CA"),
    ShipmentDirection.CA_TO_US: ("CA", "US"),
    ShipmentDirection.US_TO_CA: ("US", "CA"),
}

# The only route/direction pairs the business has enabled.
ROUTE_DIRECTIONS: dict[str, tuple[str, ...]] = {
    RouteGroup.VCA: (ShipmentDirection.VN_TO_CA,),
    RouteGroup.CAV: (ShipmentDirection.CA_TO_VN,),
    RouteGroup.CAD: (ShipmentDirection.CA_TO_CA,),
    RouteGroup.XUS: (ShipmentDirection.CA_TO_US, ShipmentDirection.US_TO_CA),
}

DIRECTION_LABELS: dict[str, str] = {
    ShipmentDirection.VN_TO_CA: "Vietnam to Canada",
    ShipmentDirection.CA_TO_VN: "Canada to Vietnam",
    ShipmentDirection.CA_TO_CA: "Canada to Canada",
    ShipmentDirection.CA_TO_US: "Canada to United States",
    ShipmentDirection.US_TO_CA: "United States to Canada",
}


class DimensionUnit(StrEnum):
    CM = "cm"
    IN = "in"


class WeightUnit(StrEnum):
    KG = "kg"
    LB = "lb"


class LegType(StrEnum):
    """Ordered transport legs (CRM.md section 7)."""

    ORIGIN_PICKUP = "origin_pickup"
    CONSOLIDATION_LINEHAUL = "consolidation_linehaul"
    DESTINATION_HANDLING = "destination_handling"
    FINAL_DELIVERY = "final_delivery"


class LegStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TrackingSourceMode(StrEnum):
    """Explicit tracking-source modes (CRM.md section 9).

    Phase 2 implements MANUAL and EXTERNAL_LINK only. CONNECTED_API and DEMO exist in
    the vocabulary so the UI can label a mode honestly, and are rejected by the service
    until Phase 4 connects a verified provider.
    """

    MANUAL = "manual"
    EXTERNAL_LINK = "external_link"
    CONNECTED_API = "connected_api"
    DEMO = "demo"


PHASE_2_TRACKING_SOURCE_MODES = (
    TrackingSourceMode.MANUAL,
    TrackingSourceMode.EXTERNAL_LINK,
)


class ShipmentEventType(StrEnum):
    """Normalized manual operational events.

    The vocabulary maps onto the operational states in CRM.md section 10. Warehouse
    receipt is deliberately its own type: delivery to a Solaris facility is a milestone,
    never final delivery.
    """

    BOOKED = "booked"
    AWAITING_PARCEL = "awaiting_parcel"
    RECEIVED_AT_SOLARIS = "received_at_solaris"
    PROCESSING = "processing"
    DEPARTED_ORIGIN = "departed_origin"
    IN_TRANSIT = "in_transit"
    CUSTOMS_PROCESSING = "customs_processing"
    ARRIVED_DESTINATION = "arrived_destination"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED_TO_RECIPIENT = "delivered_to_recipient"
    DELIVERED_TO_COLLECTION_POINT = "delivered_to_collection_point"
    DELIVERY_ATTEMPTED = "delivery_attempted"
    EXCEPTION = "exception"
    RETURN_IN_PROGRESS = "return_in_progress"
    RETURNED = "returned"


# Every event type maps to exactly one normalized operational state. Only
# DELIVERED_TO_RECIPIENT can complete a package; a collection-point handover and a
# warehouse receipt are separate milestones (CRM.md section 10).
EVENT_TYPE_TO_OPERATIONAL_STATE: dict[str, str] = {
    ShipmentEventType.BOOKED: "booked",
    ShipmentEventType.AWAITING_PARCEL: "awaiting_parcel",
    ShipmentEventType.RECEIVED_AT_SOLARIS: "received_at_solaris",
    ShipmentEventType.PROCESSING: "processing",
    ShipmentEventType.DEPARTED_ORIGIN: "departed_origin",
    ShipmentEventType.IN_TRANSIT: "in_transit",
    ShipmentEventType.CUSTOMS_PROCESSING: "customs_processing",
    ShipmentEventType.ARRIVED_DESTINATION: "arrived_destination",
    ShipmentEventType.OUT_FOR_DELIVERY: "out_for_delivery",
    ShipmentEventType.DELIVERED_TO_RECIPIENT: "delivered",
    ShipmentEventType.DELIVERED_TO_COLLECTION_POINT: "out_for_delivery",
    ShipmentEventType.DELIVERY_ATTEMPTED: "delivery_attempted",
    ShipmentEventType.EXCEPTION: "exception",
    ShipmentEventType.RETURN_IN_PROGRESS: "return_in_progress",
    ShipmentEventType.RETURNED: "returned",
}


class PackageState(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


class LabelJobKind(StrEnum):
    SINGLE = "single"
    SELECTED = "selected"
    ALL_ACTIVE = "all_active"


class LifecycleStatus(StrEnum):
    PROSPECT = "prospect"
    NEW = "new"
    ACTIVE = "active"
    AT_RISK = "at_risk"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class ContactChannel(StrEnum):
    PHONE = "phone"
    EMAIL = "email"
    SMS = "sms"
    MESSAGING_APP = "messaging_app"
    IN_PERSON = "in_person"
    OTHER = "other"


class InteractionDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class InteractionVisibility(StrEnum):
    """All CRM notes are internal by default (CRM.md section 4)."""

    INTERNAL = "internal"
    STAFF_RESTRICTED = "staff_restricted"


class TaskStatus(StrEnum):
    NOT_SCHEDULED = "not_scheduled"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


OPEN_TASK_STATUSES = (
    TaskStatus.NOT_SCHEDULED,
    TaskStatus.SCHEDULED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.WAITING_FOR_CUSTOMER,
)


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskPurpose(StrEnum):
    FIRST_SHIPMENT_FOLLOW_UP = "first_shipment_follow_up"
    AT_RISK_CHECK_IN = "at_risk_check_in"
    DELIVERY_EXCEPTION = "delivery_exception"
    QUOTE_REQUEST = "quote_request"
    DOCUMENT_REQUEST = "document_request"
    SERVICE_RECOVERY = "service_recovery"
    GENERAL = "general"


class ConsentChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"


class ConsentStatus(StrEnum):
    UNKNOWN = "unknown"
    CONSENTED = "consented"
    WITHDRAWN = "withdrawn"
    SUPPRESSED = "suppressed"


class ConsentBasis(StrEnum):
    EXPRESS = "express"
    IMPLIED_BUSINESS_RELATIONSHIP = "implied_business_relationship"
    NOT_RECORDED = "not_recorded"


class AddressRole(StrEnum):
    """What an address-book row is *for*.

    ``BILLING`` was added in Phase 10, resolving the third gap `FIELD_MATRIX.md` section 6
    names. It required no DDL: ``customer_addresses.role`` is a ``String(20)`` with no
    check constraint, so the member is the whole change. It is deliberately a fourth
    *role* rather than an ``is_billing`` boolean, because a billing address is not a
    sender or recipient address with a flag on it -- the booking flow selects on
    ``sender``/``both`` and ``recipient``/``both``, and a billing row must never be
    offered there.
    """

    SENDER = "sender"
    RECIPIENT = "recipient"
    BOTH = "both"
    BILLING = "billing"


class BookingState(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class OperationalState(StrEnum):
    """Normalized operational states (CRM.md section 10)."""

    BOOKED = "booked"
    AWAITING_PARCEL = "awaiting_parcel"
    RECEIVED_AT_SOLARIS = "received_at_solaris"
    PROCESSING = "processing"
    DEPARTED_ORIGIN = "departed_origin"
    IN_TRANSIT = "in_transit"
    CUSTOMS_PROCESSING = "customs_processing"
    ARRIVED_DESTINATION = "arrived_destination"
    OUT_FOR_DELIVERY = "out_for_delivery"
    PARTIALLY_DELIVERED = "partially_delivered"
    DELIVERED = "delivered"
    DELIVERY_ATTEMPTED = "delivery_attempted"
    EXCEPTION = "exception"
    RETURN_IN_PROGRESS = "return_in_progress"
    RETURNED = "returned"
    CANCELLED = "cancelled"
    TRACKING_UNAVAILABLE = "tracking_unavailable"


EXCEPTION_OPERATIONAL_STATES = (
    OperationalState.EXCEPTION,
    OperationalState.DELIVERY_ATTEMPTED,
    OperationalState.RETURN_IN_PROGRESS,
)


class PaymentState(StrEnum):
    UNRECORDED = "unrecorded"
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    REFUNDED = "refunded"


class ServiceType(StrEnum):
    STANDARD_PARCEL = "standard_parcel"
    EXPRESS_PARCEL = "express_parcel"
    EPACKET = "epacket"
    OTHER = "other"


class TransportMode(StrEnum):
    AIR = "air"
    OCEAN = "ocean"
    GROUND = "ground"
    MIXED = "mixed"
    UNSPECIFIED = "unspecified"


class ServiceIssueStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    CLOSED = "closed"


# Readable English labels for values a sentence-case transform would mangle
# ("Cav" instead of "Canada to Vietnam", "Vi" instead of "Vietnamese"). The frontend
# keeps its own translation catalogue; these are the API defaults.
VALUE_LABELS: dict[str, str] = {
    **ROUTE_GROUP_LABELS,
    **DIRECTION_LABELS,
    "en": "English",
    "vi": "Vietnamese",
    "fr": "French",
    "at_risk": "At risk",
    "epacket": "ePacket",
    "sms": "SMS",
    "cm": "cm",
    "in": "in",
    "kg": "kg",
    "lb": "lb",
    "external_link": "External link only",
    "connected_api": "Connected API",
    "delivered_to_recipient": "Delivered to recipient",
    "delivered_to_collection_point": "Delivered to collection point",
    # RC-UAT-25 item 5 (Ben, 2026-10-25): shown as "Received at warehouse"; the stored code
    # ``received_at_solaris`` is unchanged.
    "received_at_solaris": "Received at warehouse",
}


def value_label(value: str) -> str:
    """English default label for an enum value."""
    return VALUE_LABELS.get(value) or value.replace("_", " ").capitalize()


# --- Phase 4A: provider-neutral integration infrastructure -------------------
#
# Every value below is deliberately provider-agnostic. None of it names ShipStation, a
# ShipStation product, an endpoint, an event name, a signature algorithm, or a rate
# limit, because none of those has been verified against the account
# (docs/INTEGRATIONS.md section 3). What exists here is the vocabulary the infrastructure
# needs in order to be correct before a provider is chosen.


class IntegrationConnectionState(StrEnum):
    """How a provider connection stands, stated honestly.

    Until a provider account is actually configured the only truthful value is
    ``NOT_CONFIGURED``, and the production registry is empty, so it is the only value the
    health service can return today. The rest exist so the state machine is complete
    rather than being invented later under pressure.
    """

    #: No provider account exists. The only truthful state today.
    NOT_CONFIGURED = "not_configured"
    #: A connection row exists but an operator has switched it off.
    DISABLED = "disabled"
    #: Configured, but nothing has proved the credentials work yet.
    VERIFICATION_REQUIRED = "verification_required"
    #: A real authenticated operation has succeeded.
    CONNECTED = "connected"
    #: Configured, previously working or not, and currently failing.
    ERROR = "error"


class WebhookVerificationState(StrEnum):
    """Whether an inbound notification can be trusted, and why.

    Authenticity is separate from deduplication and separate from processing: a forged
    payload is still stored and still deduplicated, it simply may not mutate anything
    (CRM.md section 9).
    """

    #: Received; authenticity not yet assessed.
    PENDING = "pending"
    #: The adapter declares signatures, and the payload carried none.
    SIGNATURE_MISSING = "signature_missing"
    #: A signature was present and did not verify. Never applied, never retried.
    SIGNATURE_INVALID = "signature_invalid"
    #: A signature was present and verified.
    SIGNATURE_VALID = "signature_valid"
    #: The provider offers no trustworthy signature. An untrusted notification may
    #: enqueue an authenticated read; it may not mutate business state by itself.
    UNSIGNED_UNTRUSTED = "unsigned_untrusted"
    #: State was confirmed by an authenticated read against the provider.
    VERIFIED_BY_READ = "verified_by_read"


#: Verification states that permit a normalized provider event to be created. An unsigned
#: notification is deliberately absent: it may only enqueue a verification read, because
#: anyone who learns the endpoint could otherwise move a parcel (CRM.md section 9).
APPLICABLE_VERIFICATION_STATES = (
    WebhookVerificationState.SIGNATURE_VALID,
    WebhookVerificationState.VERIFIED_BY_READ,
)


class InboxProcessingState(StrEnum):
    """Where a durably stored notification is in its life."""

    PENDING = "pending"
    RUNNING = "running"
    PROCESSED = "processed"
    #: A later delivery of an event already recorded. Acknowledged, no second effect.
    DUPLICATE = "duplicate"
    #: Refused on arrival: oversized, wrong content type, unparseable, or forged.
    REJECTED = "rejected"
    #: Retryable failure; attempted again once ``next_attempt_at`` passes.
    FAILED = "failed"
    #: Out of attempts, or a failure no retry can fix. Awaits operator review.
    FAILED_TERMINAL = "failed_terminal"


class IntegrationJobType(StrEnum):
    """The work the queue carries. Provider-neutral by construction."""

    #: Turn a durably stored notification into a normalized event, if it may be applied.
    PROCESS_WEBHOOK_INBOX_ITEM = "process_webhook_inbox_item"
    #: An untrusted notification arrived; confirm state through an authenticated read.
    VERIFY_NOTIFICATION = "verify_notification"
    #: Bring a tracking assignment into agreement with the authoritative provider view.
    RECONCILE_TRACKING_ASSIGNMENT = "reconcile_tracking_assignment"
    #: A freshness-driven read for one assignment. At most one active per assignment.
    REFRESH_TRACKING_ASSIGNMENT = "refresh_tracking_assignment"
    #: An operator asked for a failed provider operation to be attempted again.
    RETRY_PROVIDER_OPERATION = "retry_provider_operation"


class IntegrationJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    #: Retryable failure with attempts remaining.
    FAILED = "failed"
    #: No further automatic attempt. Only an audited operator retry moves it.
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED = "cancelled"


#: Statuses that hold an active deduplication claim. A job in any other status has
#: released its claim, so a later legitimate enqueue is not blocked by history.
ACTIVE_JOB_STATUSES = (IntegrationJobStatus.PENDING, IntegrationJobStatus.RUNNING)

#: Statuses no automatic worker will pick up again.
TERMINAL_JOB_STATUSES = (
    IntegrationJobStatus.SUCCEEDED,
    IntegrationJobStatus.FAILED_TERMINAL,
    IntegrationJobStatus.CANCELLED,
)


class ProviderErrorKind(StrEnum):
    """How a provider failure must be treated. The adapter classifies; the worker acts.

    Keeping this an application vocabulary rather than a set of provider status codes is
    the whole point of the adapter boundary: the retry policy must not depend on which
    provider produced the failure, or on an HTTP status this project has not verified
    (CRM.md section 9).
    """

    #: A timeout, a connection reset, a server error. Retry with backoff.
    RETRYABLE = "retryable"
    #: The provider asked for a pause and may have said how long. Honour it.
    RATE_LIMITED = "rate_limited"
    #: Credentials rejected. Bounded retries only: hammering a rejected credential
    #: achieves nothing and can get an account locked.
    AUTHENTICATION = "authentication"
    #: The payload is not what the contract says. No retry will change it.
    MALFORMED_PAYLOAD = "malformed_payload"
    #: The payload parsed, but nothing in it maps onto a Solaris state. Needs a human.
    MAPPING = "mapping"
    #: Anything else that is settled. No retry.
    PERMANENT = "permanent"


#: Failure kinds a worker may attempt again on its own.
RETRYABLE_ERROR_KINDS = (ProviderErrorKind.RETRYABLE, ProviderErrorKind.RATE_LIMITED)


class ProviderEventApplication(StrEnum):
    """What happened when a normalized event met the shipment status rules."""

    PENDING = "pending"
    #: A shipment event was written and the derived status recomputed.
    APPLIED = "applied"
    #: An equivalent event was already applied. Durable, no second effect.
    SKIPPED_DUPLICATE = "skipped_duplicate"
    #: Older than what the shipment already knows. Kept for audit, never applied.
    SKIPPED_SUPERSEDED = "skipped_superseded"
    #: Could not be applied at all: the assignment or package no longer exists.
    REJECTED = "rejected"


class OccurredTimeProvenance(StrEnum):
    """Where a provider event occurred time came from, and how much to trust it.

    CRM.md section 9 requires missing timezone information to be handled explicitly
    rather than assumed. ``LOCAL_NO_TIMEZONE`` is that explicit handling: the value is
    stored, flagged, and never silently treated as UTC.
    """

    #: The provider supplied an unambiguous UTC instant.
    PROVIDER_UTC = "provider_utc"
    #: The provider supplied an explicit offset, which was converted to UTC.
    PROVIDER_OFFSET = "provider_offset"
    #: A wall-clock time with no zone. Interpreted only under a recorded assumption.
    LOCAL_NO_TIMEZONE = "local_no_timezone"
    #: The provider supplied no occurred time. ``received_at`` is not a substitute.
    MISSING = "missing"


class EventSource(StrEnum):
    """Who produced a shipment event.

    ``shipment_events.source`` has been ``manual`` on every row since Phase 2. This names
    the other value, so a provider row is distinguishable by that column alone -- which is
    what keeps a provider event from ever being mistaken for a staff entry.
    """

    MANUAL = "manual"
    PROVIDER = "provider"


# --- Phase 13A: vendor tariffs and exchange rates -------------------------------------


class TariffVersionStatus(StrEnum):
    """Lifecycle of one imported vendor tariff.

    A version is **draft** until an administrator activates it; activation supersedes the
    vendor's previously active version. Nothing prices against a draft, and a superseded
    version is kept forever so a historical quotation can be reproduced (handoff §6, §16).
    """

    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class TariffIntakeStatus(StrEnum):
    """What became of one vendor rate email (Phase 13H, OD-76)."""

    RECEIVED = "received"
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    FAILED = "failed"
    NO_ATTACHMENT = "no_attachment"
    HELD_SENDER = "held_sender"


class TariffIntakeSource(StrEnum):
    UPLOAD = "upload"
    FOLDER = "folder"


class TariffOrigin(StrEnum):
    """Vendor origin depot. The tariff is priced per depot."""

    HCM = "HCM"
    HAN = "HAN"


class TariffProductMode(StrEnum):
    AIR = "air"
    SEA = "sea"


class TariffLastMile(StrEnum):
    """How the vendor delivers in Canada. Decides which zone column and divisor apply."""

    PUROLATOR_GROUND = "purolator_ground"
    PUROLATOR_EXPRESS = "purolator_express"
    TRUCKING = "trucking"


class RateBracketKind(StrEnum):
    """``per_bill`` rows price the whole shipment; ``per_kg`` rows price each kilogram."""

    PER_BILL = "per_bill"
    PER_KG = "per_kg"


class SurchargeSection(StrEnum):
    """The four sections of the vendor's surcharge sheet."""

    HCM_AIR = "hcm_air"
    HAN_AIR = "han_air"
    SEA_CA_AU_UK_EU = "sea_ca_au_uk_eu"
    SEA_USA = "sea_usa"


class SurchargeBasis(StrEnum):
    """What a surcharge's unit price multiplies.

    ``compound`` is a weight tier **plus** a per-unit component (perfume: tiered per
    carton plus a fee per bottle). ``unpriced`` is a rule the vendor prices case by case;
    the engine must never turn it into a number.
    """

    PER_KG = "per_kg"
    PER_PIECE = "per_piece"  # kiện / thùng: a carton
    PER_UNIT = "per_unit"  # cái / máy / con: an item
    PER_PAIR = "per_pair"  # đôi / cặp
    PER_BOX = "per_box"  # hộp: a retail box
    PER_BOTTLE = "per_bottle"  # chai
    PER_SHIPMENT = "per_shipment"  # lô hàng
    COMPOUND = "compound"
    FREE = "free"
    UNPRICED = "unpriced"
    #: The vendor quotes the line case by case and staff enter that amount for the line: no
    #: kilogram basis, no master-wide share (HCM air row 27, owner 2026-10-22, DEC-0225).
    MANUAL_AMOUNT = "manual_amount"


class SurchargeScope(StrEnum):
    """Which weight a per-kg surcharge is taken on.

    The vendor's sheet is explicit that a customs surcharge is charged on the **full**
    carton weight, never on the triggering item's own kilograms (sheet footer; section 3
    and 4 notes). ``item_weight`` therefore exists only for rules whose note says so.
    """

    ITEM_WEIGHT = "item_weight"
    FULL_CARTON = "full_carton"
    FULL_MASTER = "full_master"
    PER_UNIT = "per_unit"
    PER_SHIPMENT = "per_shipment"


class SurchargePricingStatus(StrEnum):
    """Whether the engine may price this rule without a human.

    * ``priced`` -- one unit price, deterministic.
    * ``tiered`` -- deterministic from the tier table.
    * ``free`` -- explicitly exempt in the tariff.
    * ``unpriced_vendor_review`` -- a range, an estimate ("Dự kiến"), or "case by case".
      A quotation carrying one of these cannot be finalised.
    * ``not_applicable_canada`` -- the note restricts the rule to other routes.
    * ``conflict`` -- two places in the workbook disagree (pharmaceuticals: refused on the
      rate sheet, priced on the surcharge sheet). Treated as unpriced until the vendor
      answers.
    """

    PRICED = "priced"
    TIERED = "tiered"
    FREE = "free"
    UNPRICED_VENDOR_REVIEW = "unpriced_vendor_review"
    #: The vendor quotes each case; the price is entered by staff, prefilled with the
    #: file's minimum (OD-56).
    MANUAL_QUOTE = "manual_quote"
    NOT_APPLICABLE_CANADA = "not_applicable_canada"
    CONFLICT = "conflict"


class SemanticsSource(StrEnum):
    """Where a rule's structured meaning came from.

    ``parsed`` -- derived mechanically from the price text by a parser that refuses
    anything ambiguous. ``curated`` -- supplied by the reviewed semantics table in
    ``app/pricing/kango_semantics.py``, with the workbook cell it was read from.
    """

    PARSED = "parsed"
    CURATED = "curated"


class BeyondRateStatus(StrEnum):
    """``no_rate`` is a real state: beyond code 180 has postal codes but no price."""

    PRICED = "priced"
    NO_RATE = "no_rate"


class AccessorialBasis(StrEnum):
    PER_SHIPMENT = "per_shipment"
    PER_PIECE = "per_piece"
    PER_PIECE_PER_WEEK = "per_piece_per_week"
    PER_BILL = "per_bill"


class FxSyncOutcome(StrEnum):
    OK = "ok"
    FAILED = "failed"


class FxFreshness(StrEnum):
    """What the latest exchange-rate snapshot is worth right now.

    ``none`` -- nothing has ever been verified. ``stale`` -- the newest verified snapshot
    is older than the configured bound. Neither state is ever silently replaced by a
    number from another provider (handoff §6, directive v2.0 §12).
    """

    LIVE = "live"
    STALE = "stale"
    NONE = "none"


# --- Phase 13B: consolidations, the service mapping and commodity items -------------


class SolarisService(StrEnum):
    """What Solaris sells (handoff section 2; OD-43).

    A Solaris name, never a vendor product code. The mapping to a vendor product lives in
    ``service_vendor_products`` per tariff version and origin; only the two air services are
    mapped today, Sea is deferred and UPS has no rate sheet on file.
    """

    AIR_STANDARD = "air_standard"
    AIR_EXPRESS = "air_express"
    UPS = "ups"
    SEA = "sea"
    #: Workspace redesign (owner, 2026-11-04; DEC-0272): another vendor's air cargo, priced
    #: by hand like UPS.
    AIR_CARGO = "air_cargo"


#: Customer-facing names (quotes, invoices, offers). Never the vendor's name (DEC-0222).
SOLARIS_SERVICE_LABELS: dict[str, str] = {
    SolarisService.AIR_STANDARD: "Air Standard",
    SolarisService.AIR_EXPRESS: "Air Express",
    SolarisService.UPS: "UPS",
    SolarisService.SEA: "Sea",
    SolarisService.AIR_CARGO: "Air Cargo",
}

#: Staff-only names in the workspace (owner, 2026-11-04): the two Kango services say so, so
#: nobody confuses a rate-sheet service with a manually priced one. Internal screens only.
STAFF_SERVICE_LABELS: dict[str, str] = {
    **SOLARIS_SERVICE_LABELS,
    SolarisService.AIR_STANDARD: "Kango Air Standard",
    SolarisService.AIR_EXPRESS: "Kango Air Express",
}


class ConsolidationState(StrEnum):
    """Lifecycle of a vendor booking.

    ``open`` accepts members. ``booked`` means handed to the vendor: the member list and
    the master weights are final and the chargeable weight is stored. ``completed`` closes
    it after delivery of its members. ``cancelled`` releases every member.
    """

    OPEN = "open"
    BOOKED = "booked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
