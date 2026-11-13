"""Public router.

Mounted at ``/api/v1/public``. Kept as its own router, not a prefix inside the staff
router, so the separation is visible in the route table and in the OpenAPI document: a
path under ``/public`` has no security dependency, and a path outside it has one on every
operation.
"""

from fastapi import APIRouter

from app.api.public import tracking

public_router = APIRouter()
public_router.include_router(tracking.router)
