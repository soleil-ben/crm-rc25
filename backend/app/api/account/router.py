"""The Customer Account router.

Mounted at ``/api/v1/account`` as its **own** router rather than as a prefix inside the
staff router, so the separation is visible in the route table and in the OpenAPI document
rather than resting on a reviewer noticing which dependency a path declares. That is the
shape ``app/api/public/router.py`` already uses, and the reason is the same one with higher
stakes: a staff dependency attached here by reflex would produce a working staff session on
a customer route.
"""

from fastapi import APIRouter

from app.api.account import notifications, profile, quotes, routes, security, shipments

account_router = APIRouter()
account_router.include_router(routes.router)
# Phase 11. A separate module rather than more endpoints in `routes.py`: the shipment
# routes are the first on this surface that read customer data, they carry an
# authorization step the others do not have, and keeping them apart makes "which routes
# can reach a shipment?" a question the file listing answers.
account_router.include_router(shipments.router)
# Fix pack 2. The profile and marketing-consent routes: reads and the two direct writes
# FIELD_MATRIX §3.1 and §4 allow, plus proposals that change nothing canonical.
account_router.include_router(profile.router)
# Phase 13F. Milestone notification choices and history (OD-72).
account_router.include_router(notifications.router)
# Phase 13G. Quotes sent by staff, accepted or declined by the customer (OD-77).
account_router.include_router(quotes.router)
# RC-UAT-21 Phase B (DEC-0231). Signed-in password change and self-service email change.
account_router.include_router(security.router)
