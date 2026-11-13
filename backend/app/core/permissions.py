"""Resource/action permission matrix, enforced on the server (CRM.md section 11).

Hidden UI controls are never an authorization boundary. Every route that touches data
declares the permission it needs; ``app.api.deps.require`` raises 403 when the caller's
role does not hold it.

Exports and cost visibility are separate permissions so a role can read a customer
without being able to bulk-export contacts or see carrier costs.
"""

from __future__ import annotations

from app.core.enums import Role


class Permission:
    CUSTOMER_READ = "customer:read"
    CUSTOMER_CREATE = "customer:create"
    CUSTOMER_UPDATE = "customer:update"
    CUSTOMER_ARCHIVE = "customer:archive"
    CUSTOMER_MERGE = "customer:merge"

    ADDRESS_READ = "address:read"
    ADDRESS_WRITE = "address:write"

    INTERACTION_READ = "interaction:read"
    INTERACTION_WRITE = "interaction:write"

    TASK_READ = "task:read"
    TASK_WRITE = "task:write"

    CONSENT_READ = "consent:read"
    CONSENT_WRITE = "consent:write"
    SUPPRESSION_RELEASE = "suppression:release"
    # Suppressing an address from the customer's Consent tab, with an evidence reference
    # and a reason (UAT round 4, DEC-0130). Marketing and Admin. Adding a block is the
    # cautious direction, so it is wider than release, which stays Admin's alone.
    SUPPRESSION_ADD = "suppression:add"

    # Reviewing duplicate candidates is customer-data stewardship, not ordinary record
    # reading: the reviewer is being shown two people's contact details side by side in
    # order to decide whether they are one person (CRM.md section 13). It is gated
    # separately from ``customer:read`` for that reason. Merging remains a further,
    # stricter permission — reviewing a candidate never merges anything (AC-16).
    DUPLICATE_REVIEW = "duplicate:review"

    # Customer Account registration review is its own power, split in two (OD-24).
    #
    # Not ``duplicate:review``. Reviewing a duplicate candidate decides whether two
    # *records* are one person; activating a Customer Account decides whether a **living
    # person holding a password** may read a canonical customer's shipment history from
    # then on. Marketing and the read-only manager both hold ``duplicate:review`` today and
    # must reach neither of these, which is the whole reason they are separate names.
    #
    # Split into read and mutate because the instruction requires read permission and
    # mutation permission to remain explicit: a mutating route asks for both, so a role
    # that may look at the queue has not thereby been given the power to activate anything.
    CUSTOMER_ACCOUNT_REVIEW = "customer_account:review"
    CUSTOMER_ACCOUNT_APPROVE = "customer_account:approve"
    # Deactivation is permanent for the account, so it is its own permission and Admin's
    # alone (DEC-0126): it appears in no role set below, and Admin holds every permission.
    CUSTOMER_ACCOUNT_DEACTIVATE = "customer_account:deactivate"

    TAG_READ = "tag:read"
    TAG_WRITE = "tag:write"

    REFERRAL_READ = "referral:read"
    REFERRAL_WRITE = "referral:write"

    SEGMENT_READ = "segment:read"
    SEGMENT_WRITE = "segment:write"

    SHIPMENT_READ = "shipment:read"
    SHIPMENT_WRITE = "shipment:write"
    # Cancelling or rebooking retires a customer-facing Solaris ID, so it is gated
    # separately from ordinary shipment editing (CRM.md section 6).
    SHIPMENT_CANCEL = "shipment:cancel"
    # Carrier association and manual operational events are the operations desk's work.
    TRACKING_WRITE = "tracking:write"
    LABEL_GENERATE = "label:generate"

    DASHBOARD_READ = "dashboard:read"
    REPORT_READ = "report:read"

    # Financial visibility is split: recorded revenue vs. carrier/direct cost.
    FINANCIAL_READ = "financial:read"
    FINANCIAL_COST_READ = "financial_cost:read"
    FINANCIAL_WRITE = "financial:write"
    # Phase 13E: refunds, voids and reopening a closed month. Admin and Operations (OD-69).
    FINANCIAL_ADJUST = "financial:adjust"

    # Exports are restricted separately from record access. Reading one customer and
    # extracting the whole book are different acts, and one export permission per export
    # type keeps them separable (CRM.md section 13, AC-2).
    EXPORT_CUSTOMERS = "export:customers"
    EXPORT_MARKETING_SEGMENT = "export:marketing_segment"
    EXPORT_SHIPMENTS = "export:shipments"
    EXPORT_REPORTS = "export:reports"

    # CSV customer import is staged, and each stage is its own permission. Downloading a
    # blank template is harmless; previewing puts a file of real people's contact details
    # in front of the caller; committing writes them. A role may hold the earlier stages
    # without the later ones (CRM.md section 13).
    IMPORT_TEMPLATE = "import:template"
    IMPORT_PREVIEW = "import:preview"
    IMPORT_COMMIT = "import:commit"

    STAFF_READ = "staff:read"
    STAFF_MANAGE = "staff:manage"
    SETTINGS_READ = "settings:read"
    SETTINGS_MANAGE = "settings:manage"
    # Reading integration health is separated from managing the integration, because
    # CRM.md section 12 wants integration health and stale-tracking warnings visible to
    # authorized staff while section 11 keeps API credentials away from most roles.
    # Health carries no secret, so it can be read more widely than it can be changed.
    INTEGRATION_READ = "integration:read"
    INTEGRATION_MANAGE = "integration:manage"
    AUDIT_READ = "audit:read"

    # Vendor tariffs and exchange rates (Phase 13A). Reading a tariff reveals the vendor's
    # purchase prices, which the directive keeps strictly internal (v2.1 §1); it is not a
    # customer-facing surface and never reaches the public or account routers. Operations
    # holds read because the Unified Workspace prices against it; only Admin imports or
    # activates a version, because activation changes every quotation from then on.
    TARIFF_READ = "tariff:read"
    TARIFF_MANAGE = "tariff:manage"

    # Owner decision 8 (2026-10-21): a booked master's items and fees are locked. Unlocking
    # one for edits is Admin's alone (stand-in): it is in no role set below, and Admin holds
    # every permission. Locking it again needs only ``shipment:write``.
    MASTER_UNLOCK = "master:unlock"

    # RC-UAT-21 Phase D (DEC-0233): soft-deleting an old quote version (and restoring it, and
    # seeing deleted ones) and reading or changing the retention policies are Admin's alone:
    # neither is in any role set below, and Admin holds every permission.
    QUOTE_DELETE = "quote:delete"
    RETENTION_MANAGE = "retention:manage"


P = Permission

# Operations is the merged customer-facing and operational desk (DEC-0088). This set was
# Customer service's; the former Operations set was a strict subset of it, holding nothing
# this does not, so the merge added no permission that did not already belong to a role
# doing this work. Cost remains out: ``financial_cost:read`` is Admin's alone, which is why
# the merged role still cannot see carrier cost or profit.
_OPERATIONS: set[str] = {
    P.CUSTOMER_READ,
    P.CUSTOMER_CREATE,
    P.CUSTOMER_UPDATE,
    P.CUSTOMER_ARCHIVE,
    P.ADDRESS_READ,
    P.ADDRESS_WRITE,
    P.INTERACTION_READ,
    P.INTERACTION_WRITE,
    P.TASK_READ,
    P.TASK_WRITE,
    P.CONSENT_READ,
    P.CONSENT_WRITE,
    P.DUPLICATE_REVIEW,
    # OD-24: Operations performs explicit account approval; Admin may override. Nobody
    # else holds either of these in release 1.
    P.CUSTOMER_ACCOUNT_REVIEW,
    P.CUSTOMER_ACCOUNT_APPROVE,
    P.TAG_READ,
    P.TAG_WRITE,
    P.REFERRAL_READ,
    P.REFERRAL_WRITE,
    P.SEGMENT_READ,
    P.SEGMENT_WRITE,
    P.SHIPMENT_READ,
    P.SHIPMENT_WRITE,
    P.SHIPMENT_CANCEL,
    P.TRACKING_WRITE,
    P.LABEL_GENERATE,
    P.DASHBOARD_READ,
    P.REPORT_READ,
    P.FINANCIAL_READ,
    P.FINANCIAL_WRITE,
    P.SETTINGS_READ,
    P.TARIFF_READ,
    # OD-69 (owner, 2026-10-20): Operations refunds, voids and reopens a closed month too.
    P.FINANCIAL_ADJUST,
}

# Marketing manages profiles, segments, consent and follow-ups. No credentials,
# no unrestricted operational export, no carrier costs (CRM.md section 11).
_MARKETING: set[str] = {
    P.CUSTOMER_READ,
    P.CUSTOMER_UPDATE,
    P.ADDRESS_READ,
    P.INTERACTION_READ,
    P.INTERACTION_WRITE,
    P.TASK_READ,
    P.TASK_WRITE,
    P.CONSENT_READ,
    P.CONSENT_WRITE,
    P.SUPPRESSION_ADD,
    P.DUPLICATE_REVIEW,
    P.TAG_READ,
    P.TAG_WRITE,
    P.REFERRAL_READ,
    P.SEGMENT_READ,
    P.SEGMENT_WRITE,
    P.SHIPMENT_READ,
    P.DASHBOARD_READ,
    P.REPORT_READ,
    P.EXPORT_MARKETING_SEGMENT,
    P.SETTINGS_READ,
}

_READ_ONLY_MANAGER: set[str] = {
    P.CUSTOMER_READ,
    P.ADDRESS_READ,
    P.INTERACTION_READ,
    P.TASK_READ,
    P.CONSENT_READ,
    P.DUPLICATE_REVIEW,
    P.TAG_READ,
    P.REFERRAL_READ,
    P.SEGMENT_READ,
    P.SHIPMENT_READ,
    P.DASHBOARD_READ,
    P.REPORT_READ,
    P.FINANCIAL_READ,
    P.AUDIT_READ,
    P.SETTINGS_READ,
    # A read-only manager watches dashboards; integration health is a dashboard. It
    # carries counts and states, never a credential (DEC-0064).
    P.INTEGRATION_READ,
}

# Phase 5A note (DEC-0082). ``import:template``, ``import:preview``, ``import:commit``,
# ``export:shipments`` and ``export:reports`` appear in no role set above, so **Admin
# alone** holds them, through ``_ALL_PERMISSIONS``. CRM.md section 11 does not say who may
# bulk-import a customer list or bulk-export shipments, and those are precisely the two
# operations that move the whole database across a boundary in a single action. Widening a
# permission later is a settings change; narrowing one after staff have been trained on it
# is a support incident. The final Operations and Marketing permission set is an open
# business decision, recorded in PROJECT_STATUS.md.
_ALL_PERMISSIONS: set[str] = {
    value
    for key, value in vars(Permission).items()
    if not key.startswith("_") and isinstance(value, str)
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN: set(_ALL_PERMISSIONS),
    Role.OPERATIONS: _OPERATIONS,
    Role.MARKETING: _MARKETING,
    Role.READ_ONLY_MANAGER: _READ_ONLY_MANAGER,
}

ROLE_LABELS: dict[str, str] = {
    Role.ADMIN: "Admin",
    Role.OPERATIONS: "Operations",
    Role.MARKETING: "Marketing",
    Role.READ_ONLY_MANAGER: "Read-only manager",
}


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: str, permission: str) -> bool:
    return permission in permissions_for(role)
