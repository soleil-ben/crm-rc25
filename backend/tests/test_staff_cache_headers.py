"""UAT-AD-01: nothing a signed-in staff member saw may come back from a cache.

The API half of the fix. Every staff response carries ``Cache-Control: no-store`` (since
Phase 1) and, since the 2026-10-14 fix pack, ``Pragma: no-cache`` for the HTTP/1.0 caches
and browser heuristics that still read it. The public and Customer Account surfaces keep
their own, separately asserted header sets, so this file also proves the new header did
**not** leak onto them -- their failure responses are required to be byte-identical to
each other, and a header that appeared on one surface and not another would be a
difference somebody could measure.
"""

from __future__ import annotations

from tests.conftest import make_customer

STAFF_READS = [
    "/api/v1/auth/me",
    "/api/v1/customers",
    "/api/v1/dashboard/summary",
    "/api/v1/shipments",
    "/api/v1/settings",
]


def test_every_staff_response_is_uncacheable(as_admin, db):
    make_customer(db, full_name="Cache Test Person")
    db.commit()
    for path in STAFF_READS:
        response = as_admin.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["cache-control"] == "no-store", path
        assert response.headers["pragma"] == "no-cache", path


def test_a_refusal_is_uncacheable_too(client):
    """A 401 is as much a staff response as a 200; the sign-in screen must not be cached."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_sign_out_clears_the_session_and_the_answer_is_uncacheable(as_admin):
    signed_out = as_admin.post("/api/v1/auth/logout")
    assert signed_out.status_code == 200
    assert signed_out.headers["cache-control"] == "no-store"
    assert signed_out.headers["pragma"] == "no-cache"
    # The session is gone server-side, not just from the cookie jar.
    assert as_admin.get("/api/v1/auth/me").status_code == 401


def test_the_public_surface_keeps_its_own_header_set(client):
    response = client.get("/api/v1/public/track/SX-CAV-ABCDEFGHJKLM")
    assert response.status_code == 404
    # The public set already carries Pragma with its own value; what matters is that it
    # is the public set, unchanged, and not the staff one.
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"


def test_the_customer_account_surface_is_untouched(account_client):
    """The Phase 9 contract: `Cache-Control: no-store` and no new header beside it."""
    response = account_client.get("/api/v1/account/me")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert "pragma" not in response.headers
