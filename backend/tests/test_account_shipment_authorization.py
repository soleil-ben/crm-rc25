"""Every state in which a shipment read must be refused, and the refusal itself.

The §24.5 table, one test per row, plus the two cross-surface invariants and the sweep
OD-40 asks for. A guard that has never been exercised against the state it guards is a
comment, so every state here is *produced* -- by a staff route where one exists, by writing
the row where the state is one nothing can reach -- and then read against.
"""

from __future__ import annotations

from datetime import timedelta

from app.core.account_enums import IdentityStatus, LinkStatus
from app.core.enums import Role
from app.core.time_utils import utcnow
from app.models import Customer, CustomerIdentity, CustomerIdentityLink
from app.services import customer_account_link_policy as policy
from tests.account_fixtures import ACCOUNT_PASSWORD, registered_and_verified
from tests.approval_fixtures import staff
from tests.shipment_history_fixtures import (
    LIST_URL,
    detail_url,
    link_account,
    linked_and_signed_in,
    shipment,
    sign_in_account,
)
from tests.shipment_history_fixtures import customer as make

MINE = "hanh@demo.example.com"


def _mine(account_db):
    return make(account_db, full_name="Hanh Nguyen", email="hanh.canonical@demo.example.com")


def _identity(account_db, address=MINE) -> CustomerIdentity:
    return (
        account_db.query(CustomerIdentity)
        .filter(CustomerIdentity.email_normalized == address)
        .one()
    )


def _both_routes(client, reference="SX-CAV-AAAAAAAAAAAA"):
    return client.get(LIST_URL), client.get(detail_url(reference))


# --- Not signed in at all -------------------------------------------------------


def test_an_anonymous_caller_reaches_neither_route(account_client):
    for response in _both_routes(account_client):
        assert response.status_code == 401, response.text
        assert "shipment" not in response.text.lower() or "could not find" not in response.text


def test_a_staff_session_authenticates_nothing_here(account_client, account_db, account_users):
    """T-01. The staff cookie is a different name in a different table read by a different
    resolver, so this is not a check that could be forgotten -- but it is asserted anyway,
    because "there is no code path" is exactly the kind of claim that stops being true."""
    mine = _mine(account_db)
    shipment(account_db, mine, days_ago=3)
    staff(account_client, account_users[Role.ADMIN].email)

    for response in _both_routes(account_client):
        assert response.status_code == 401, response.text


def test_a_customer_session_authenticates_nothing_on_a_staff_shipment_route(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    assert client.get(detail_url(row.public_id)).status_code == 200

    # 401, never 403: a 403 would say the caller was authenticated and merely unprivileged.
    assert client.get("/api/v1/shipments").status_code == 401
    assert client.get(f"/api/v1/customers/{mine.public_id}").status_code == 401


# --- Identity states --------------------------------------------------------------


def test_a_pending_approval_identity_is_refused(
    account_client, account_db, account_users, captured_mail
):
    """Signed in, with a real session, and no shipment data at all (AC-CA-5.1)."""
    mine = _mine(account_db)
    shipment(account_db, mine, days_ago=3)
    registered_and_verified(account_client, captured_mail, MINE)
    client = sign_in_account(account_client, MINE)

    for response in _both_routes(client):
        assert response.status_code == 403, response.text
        assert response.json()["code"]
    assert client.get("/api/v1/account/me").json()["shipment_history_available"] is False


def test_a_suspended_identity_is_refused_on_the_next_request(
    account_client, account_db, account_users, captured_mail
):
    """AC-CA-8.5 and T-14: suspension takes effect on the next request, not the next sign-in."""
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    assert client.get(detail_url(row.public_id)).status_code == 200

    identity = _identity(account_db)
    identity.status = IdentityStatus.SUSPENDED.value
    account_db.commit()

    for response in _both_routes(client, row.public_id):
        assert response.status_code in {401, 403}, response.text
        assert row.public_id not in response.text


def test_a_deactivated_identity_is_refused(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    identity = _identity(account_db)
    identity.status = IdentityStatus.DEACTIVATED.value
    account_db.commit()

    for response in _both_routes(client, row.public_id):
        assert response.status_code in {401, 403}


def test_a_rejected_identity_is_refused(account_client, account_db, account_users, captured_mail):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    identity = _identity(account_db)
    identity.status = IdentityStatus.REJECTED.value
    account_db.commit()

    for response in _both_routes(client, row.public_id):
        assert response.status_code in {401, 403}


def test_a_revoked_session_is_refused(account_client, account_db, account_users, captured_mail):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    assert client.get(detail_url(row.public_id)).status_code == 200

    sign_out = client.post(
        "/api/v1/account/sign-out",
        headers={"X-Account-CSRF-Token": client.cookies.get("solaris_account_csrf") or ""},
    )
    assert sign_out.status_code in {200, 204}, sign_out.text

    for response in _both_routes(client, row.public_id):
        assert response.status_code == 401


# --- Link states --------------------------------------------------------------------


def test_an_active_identity_with_no_link_is_refused(
    account_client, account_db, account_users, captured_mail
):
    """A state nothing produces -- approval always writes a link -- and it must fail closed."""
    mine = _mine(account_db)
    shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    link = account_db.query(CustomerIdentityLink).one()
    link.status = LinkStatus.REVOKED.value
    link.revoked_at = utcnow()
    account_db.commit()

    for response in _both_routes(client):
        assert response.status_code == 403


def test_a_revoked_link_stops_access_on_the_next_request(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    assert client.get(detail_url(row.public_id)).status_code == 200

    account_db.query(CustomerIdentityLink).one().status = LinkStatus.REVOKED.value
    account_db.commit()

    assert client.get(detail_url(row.public_id)).status_code == 403
    assert row.public_id not in client.get(detail_url(row.public_id)).text


def test_two_effective_links_are_refused_rather_than_resolved(
    account_client, account_db, account_users, captured_mail
):
    """The partial unique index makes this unreachable. The guard exists for the day it is not.

    "Pick the first one" would be a plausible implementation, and it would mean an identity
    reading a customer nobody approved it for. So the state is constructed the only way it
    can be: the partial unique index is **dropped** and the second row inserted underneath
    it. That is what "the database stopped enforcing its own constraint" looks like, and it
    is the exact scenario the guard is for -- ``effective_links_for_identity`` reads more
    than one row rather than taking the first, so the application refuses even when the
    index no longer does.
    """
    from sqlalchemy import text

    mine = _mine(account_db)
    second = make(account_db, full_name="Another Record", email="another@demo.example.com")
    shipment(account_db, second, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    existing = account_db.query(CustomerIdentityLink).one()

    account_db.execute(text("DROP INDEX uq_customer_identity_links_active_identity"))
    account_db.execute(
        text(
            "INSERT INTO customer_identity_links "
            "(identity_id, customer_id, link_role, status, linked_at) "
            "VALUES (:identity, :customer, 'owner', 'active', :now)"
        ),
        {"identity": existing.identity_id, "customer": second.id, "now": utcnow()},
    )
    account_db.commit()

    assert len(policy.effective_links_for_identity(account_db, existing.identity_id)) == 2
    for response in _both_routes(client):
        assert response.status_code == 403


def test_an_archived_linked_customer_is_refused(
    account_client, account_db, account_users, captured_mail
):
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    assert client.get(detail_url(row.public_id)).status_code == 200

    mine.is_archived = True
    mine.archived_at = utcnow()
    account_db.commit()

    for response in _both_routes(client, row.public_id):
        assert response.status_code == 403
        assert row.public_id not in response.text


def test_a_merged_or_tombstoned_linked_customer_is_refused_and_not_followed(
    account_client, account_db, account_users, captured_mail
):
    """OD-40 makes this unreachable; it fails closed anyway, and it does **not** retarget.

    The survivor has shipments of its own. If the read followed ``merged_into_customer_id``
    it would serve them, which is precisely the silent scope expansion OD-40 refuses a merge
    to prevent.
    """
    mine = _mine(account_db)
    survivor = make(account_db, full_name="Survivor", email="survivor@demo.example.com")
    theirs = shipment(account_db, survivor, days_ago=2)
    mine_row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )

    mine.merged_into_customer_id = survivor.id
    mine.merged_at = utcnow()
    account_db.commit()

    listed = client.get(LIST_URL)
    assert listed.status_code == 403
    assert theirs.public_id not in listed.text
    assert mine_row.public_id not in listed.text
    assert client.get(detail_url(theirs.public_id)).status_code == 403


def test_a_link_to_a_customer_row_that_vanished_is_refused(account_db):
    """The one case with no route: a link whose customer id resolves to nothing.

    ``ON DELETE RESTRICT`` makes it unreachable through the database, so the policy is
    exercised directly rather than through a request that cannot be constructed.
    """

    class Detached:
        id = 999_999
        status = IdentityStatus.ACTIVE.value

    resolved = policy.resolve_readable_customer(account_db, Detached())
    assert resolved.authorized is False
    assert resolved.reason == policy.REASON_NO_EFFECTIVE_LINK


# --- The refusal itself ---------------------------------------------------------------


def test_every_refusal_reason_produces_one_body(
    account_client, account_db, account_users, captured_mail
):
    """Pending, unlinked, archived and merged all say the same sentence.

    Which of them applies is a fact about the CRM's internal state, and a customer-facing
    403 that narrated it would be telling an account holder that a record was archived or
    merged -- both of which `FIELD_MATRIX.md` §3.4 lists as never-visible.
    """
    mine = _mine(account_db)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    link = account_db.query(CustomerIdentityLink).one()
    bodies = set()

    link.status = LinkStatus.REVOKED.value
    account_db.commit()
    bodies.add(client.get(LIST_URL).text)

    link.status = LinkStatus.ACTIVE.value
    mine.is_archived = True
    account_db.commit()
    bodies.add(client.get(LIST_URL).text)

    mine.is_archived = False
    mine.merged_at = utcnow()
    account_db.commit()
    bodies.add(client.get(LIST_URL).text)

    assert len(bodies) == 1, bodies
    body = next(iter(bodies)).lower()
    for forbidden in ("archiv", "merge", "link", "revoked", "customer record"):
        assert forbidden not in body, forbidden


def test_the_refusal_reason_vocabulary_is_closed():
    """A reason is a bounded code, so a future one is a decision rather than a string."""
    assert policy.REASON_OK not in policy.REFUSAL_REASONS
    assert len(policy.REFUSAL_REASONS) == 6
    assert all(isinstance(reason, str) and reason.islower() for reason in policy.REFUSAL_REASONS)


# --- OD-40's sweep ------------------------------------------------------------------


def test_no_effective_link_points_at_a_merged_or_tombstoned_customer(
    account_client, account_db, account_users, captured_mail
):
    """The whole-database sweep, run after an ordinary approval and an attempted merge.

    OD-40 refuses the merge, so the sweep has nothing to find -- which is the assertion.
    """
    mine = _mine(account_db)
    other = make(account_db, full_name="Other", email="other@demo.example.com")
    link_account(account_client, captured_mail, account_users, email_address=MINE, customer=mine)

    api = staff(account_client, account_users[Role.ADMIN].email)
    refused = api.post(
        "/api/v1/customers/merge",
        json={
            "source_customer_id": mine.public_id,
            "target_customer_id": other.public_id,
            "confirm": True,
        },
    )
    assert refused.status_code in {409, 422}, refused.text

    account_db.rollback()
    for link in account_db.query(CustomerIdentityLink).all():
        if link.status != LinkStatus.ACTIVE.value:
            continue
        customer = account_db.get(Customer, link.customer_id)
        assert customer is not None
        assert customer.merged_into_customer_id is None
        assert customer.merged_at is None


# --- The read writes nothing --------------------------------------------------------


def test_a_read_writes_no_canonical_row_and_no_link(
    account_client, account_db, account_users, captured_mail
):
    """T-07 and §24.5: there is no repair path, and a read never retargets a link."""
    mine = _mine(account_db)
    row = shipment(account_db, mine, days_ago=3)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    # The snapshot is of the record as linked: linking writes the sign-in email to it
    # (one email per customer, UAT round 6), and the reads below must write nothing more.
    account_db.rollback()
    account_db.refresh(mine)

    before_customer = {
        column.name: getattr(mine, column.name) for column in Customer.__table__.columns
    }
    link = account_db.query(CustomerIdentityLink).one()
    before_link = {
        column.name: getattr(link, column.name) for column in CustomerIdentityLink.__table__.columns
    }

    assert client.get(LIST_URL).status_code == 200
    assert client.get(detail_url(row.public_id)).status_code == 200
    client.get(detail_url("SX-CAV-AAAAAAAAAAAA"))

    account_db.rollback()
    account_db.refresh(mine)
    account_db.refresh(link)
    assert {
        column.name: getattr(mine, column.name) for column in Customer.__table__.columns
    } == before_customer
    assert {
        column.name: getattr(link, column.name) for column in CustomerIdentityLink.__table__.columns
    } == before_link
    assert account_db.query(CustomerIdentityLink).count() == 1


def test_no_mutation_route_exists_on_the_shipment_surface(account_client):
    """Phase 11 adds reads. The absence of everything else is asserted, not assumed."""
    from app.main import app

    paths = app.openapi()["paths"]
    shipment_paths = {
        path: set(methods) for path, methods in paths.items() if "/account/shipments" in path
    }
    assert shipment_paths, "the routes are not mounted"
    for path, methods in shipment_paths.items():
        assert methods <= {"get"}, (path, methods)

    for method, url in (
        ("post", LIST_URL),
        ("patch", detail_url("SX-CAV-AAAAAAAAAAAA")),
        ("delete", detail_url("SX-CAV-AAAAAAAAAAAA")),
        ("put", detail_url("SX-CAV-AAAAAAAAAAAA")),
    ):
        assert getattr(account_client, method)(url).status_code == 405, (method, url)


def test_no_account_route_depends_on_a_staff_dependency():
    """AC-CA-1.4, extended to the two new routes by walking the dependency graph."""
    import app.api.deps as staff_deps
    from app.api.account import shipments as module

    staff_callables = {
        value
        for value in vars(staff_deps).values()
        if callable(value) and not isinstance(value, type)
    }
    for route in module.router.routes:
        for dependant in route.dependant.dependencies:
            assert dependant.call not in staff_callables, dependant.call


def test_a_delayed_sign_in_still_re_reads_state(
    account_client, account_db, account_users, captured_mail
):
    """No grant is cached on the session row: a fresh sign-in reads the same live state.

    The account is signed in, suspended, and then signed in again with the correct password.
    The second sign-in is refused because the identity is not authenticatable, which is the
    Phase 9 behaviour -- restated here because the shipment routes are the first thing that
    would notice if a session had been allowed to carry a stale grant across it.
    """
    mine = _mine(account_db)
    linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    _identity(account_db).status = IdentityStatus.SUSPENDED.value
    account_db.commit()
    account_client.cookies.clear()

    again = account_client.post(
        "/api/v1/account/sign-in", json={"email": MINE, "password": ACCOUNT_PASSWORD}
    )
    assert again.status_code in {401, 403, 422}
    assert account_client.get(LIST_URL).status_code == 401


def test_shipment_history_available_tracks_the_same_authorization(
    account_client, account_db, account_users, captured_mail
):
    """`/me` and the shipment routes answer from one helper, so they cannot disagree."""
    mine = _mine(account_db)
    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    assert client.get("/api/v1/account/me").json()["shipment_history_available"] is True
    assert client.get(LIST_URL).status_code == 200

    account_db.query(CustomerIdentityLink).one().status = LinkStatus.REVOKED.value
    account_db.commit()

    me = client.get("/api/v1/account/me").json()
    assert me["shipment_history_available"] is False
    assert me["linked"] is False
    assert client.get(LIST_URL).status_code == 403
    # Still a boolean, and still no count, date or customer reference.
    assert "customer" not in str(me).lower() or me["account_reference"].startswith("CA-")
    assert not any(isinstance(value, int) and value > 1 for value in me.values())


def test_the_date_filter_cannot_be_used_to_widen_ownership(
    account_client, account_db, account_users, captured_mail
):
    """Ownership is the first clause and a filter can only narrow it.

    ``qualifying_conditions`` carries the ``customer_id`` equality itself, so there is no
    way to construct a filter that drops it -- asserted by asking for a range that covers
    everything, including another customer's rows.
    """
    mine, theirs = (
        _mine(account_db),
        make(account_db, full_name="Other", email="other@demo.example.com"),
    )
    shipment(account_db, theirs, days_ago=1)
    shipment(account_db, theirs, days_ago=300)
    ours = shipment(account_db, mine, days_ago=100)

    client = linked_and_signed_in(
        account_client, captured_mail, account_users, email_address=MINE, customer=mine
    )
    today = utcnow().date()
    body = client.get(
        LIST_URL,
        params={
            "booked_from": (today - timedelta(days=399)).isoformat(),
            "booked_to": today.isoformat(),
            "limit": 50,
        },
    ).json()

    assert [item["shipment_reference"] for item in body["items"]] == [ours.public_id]
    assert body["total"] == 1
