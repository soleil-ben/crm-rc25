"""Versioned API router. Every staff route lives under /api/v1."""

from fastapi import APIRouter

from app.api.v1.routes import (
    admin,
    auth,
    bulk_imports,
    consolidations,
    customer_account_review,
    customers,
    data_retention,
    engagement,
    exports,
    finance,
    imports,
    integrations,
    invoice_drafts,
    notifications,
    pricing,
    quote_offers,
    reports,
    segments,
    shipments,
    tariffs,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(customers.router)
# Mounted after `customers` so its concrete `/customer-account/...` paths cannot be
# shadowed by a `/customers/{customer_id}` pattern, and kept a separate router so the
# route table shows Customer Account review as its own surface within the Staff Portal.
api_router.include_router(customer_account_review.router)
api_router.include_router(engagement.router)
api_router.include_router(tasks.router)
api_router.include_router(shipments.router)
# Consolidations and commodity items (Phase 13B): mounted after `shipments` so its own
# `/shipments/{id}/items` paths sit beside the shipment routes in the table.
api_router.include_router(consolidations.router)
# Pricing: settings, surcharge policies, fee lines, estimates and quotes (Phase 13C).
api_router.include_router(pricing.router)
# Quote offers: staff send a finalised quote; the customer answers it (Phase 13G, OD-77).
api_router.include_router(quote_offers.router)
# RC-UAT-21 Phase D: Admin soft delete of old quote versions and Settings > Retention.
api_router.include_router(data_retention.router)
# Finance: invoices, payments, receipts, vendor bills, reports, month close (Phase 13E).
api_router.include_router(finance.router)
# Draft invoices prepared on acceptance, and invoice PDFs (owner decision 9a).
api_router.include_router(invoice_drafts.router)
# Milestone notifications: the outbox and customers' choices (Phase 13F).
api_router.include_router(notifications.router)
api_router.include_router(segments.router)
api_router.include_router(reports.router)
api_router.include_router(exports.router)
api_router.include_router(imports.router)
# RC-UAT-21 Phase A: shipment import, legacy history baseline, staff legacy reads.
api_router.include_router(bulk_imports.router)
api_router.include_router(integrations.router)
# Vendor tariffs and exchange rates (Phase 13A): staff-only vendor cost data.
api_router.include_router(tariffs.router)
api_router.include_router(admin.router)
