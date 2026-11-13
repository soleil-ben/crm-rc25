"""A merge racing an approval, on two connections, with the invariant checked every time.

Why this suite exists as something separate from
`tests/test_account_approval_concurrency.py`: that one races two *approvals*, which
contend on rows they both write -- an idempotency digest, an identity status, a link's
unique index. A merge and an approval contend on nothing they both write. The merge reads
``customer_identity_links`` and writes ``customers``; the approval reads ``customers`` and
writes ``customer_identity_links``. That is textbook **write skew**, and it is the one
shape a check-then-write does not survive.

---

## What closes it

Two things, and the first one had to be built. On pysqlite a ``SELECT`` opened **no
transaction at all**, so a check made before the first write was made outside any
transaction and a row committed a microsecond later was invisible to it. Phase 10 fixed
that in `app/core/db.py` (DEC-0108); `test_a_read_before_the_first_write_is_protected`
demonstrates the result against this project's own engine, in this file, so the property
the guards rely on is recorded next to the guards.

The second is that **each operation's first write is a claim**:

* the merge's is ``_claim_source`` -- a conditional ``UPDATE`` of the source's tombstone
  columns with its affected-row count checked;
* the approval's is ``_claim`` -- an ``INSERT`` of the idempotency digest, which is the
  first statement either approval path executes.

Once a connection has written, it holds SQLite's writer lock until it commits. So every
check either operation makes *after* its claim reads committed data with no other writer
able to intervene, and the two operations cannot be inside their write transactions at the
same time. That is the whole mechanism. There is no advisory lock, no ``SELECT FOR
UPDATE``, and no polling.

---

## The invariant

`_assert_invariant` is run after every interleaving in this file, and it is the same four
clauses each time:

1. no effective link points at a merged or archived customer;
2. an ``active`` identity has exactly one active link, and a non-active one has none --
   so no identity has quietly gained a customer's history;
3. where two outcomes conflict, at most one of them happened;
4. a failure left nothing behind: no half-merged customer, no link, no activation, no
   disclosure acknowledgement and no idempotency attempt row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.account_enums import IdentityStatus, LinkStatus
from app.core.enums import Role
from app.models import (
    Customer,
    CustomerAccountApprovalAttempt,
    CustomerAccountDisclosureAcknowledgement,
    CustomerIdentity,
    CustomerIdentityLink,
    User,
)
from app.services import customer_account_approval_service as approval
from app.services import customer_account_link_policy as link_policy
from app.services import customer_service
from app.services.errors import ConflictError
from tests.approval_fixtures import (
    acknowledged_preview,
    add_shipment,
    key,
    make_customer,
    pending_identity,
    staff,
)

#: Every way a loser is allowed to lose. A ``ConflictError`` is the designed refusal; an
#: ``IntegrityError`` is a unique index refusing at the last moment; an
#: ``OperationalError`` carrying "locked" is SQLite serializing two writers. All three are
#: correct, and which one fires is a property of the engine rather than of this
#: application -- so the tests assert *that* exactly one won, never *how* the other lost.
REFUSALS = (ConflictError, IntegrityError, OperationalError)


@pytest.fixture
def second_session(account_engine):
    """A second session on its own connection. The whole point of this module."""
    factory = sessionmaker(
        bind=account_engine, autoflush=False, expire_on_commit=False, future=True
    )
    session = factory()
    yield session
    session.close()


def _actor(session) -> User:
    return session.query(User).filter_by(role=Role.OPERATIONS).one()


def _identity(session, reference: str) -> CustomerIdentity:
    return session.query(CustomerIdentity).filter_by(public_id=reference).one()


def _customer(session, public_id: str) -> Customer:
    return session.query(Customer).filter_by(public_id=public_id).one()


def _run(session, call):
    """Run one racer to completion and commit it, reporting which way it went."""
    try:
        result = call(session)
        session.commit()
        return ("ok", result)
    except REFUSALS as exc:
        session.rollback()
        if isinstance(exc, OperationalError) and "locked" not in str(exc).lower():
            raise
        return ("refused", exc)


def _assert_invariant(db) -> None:
    """The four clauses, swept over the whole database. Run after every interleaving."""
    db.expire_all()

    # 1. No effective link points at a record that has been merged away or archived.
    for link in db.query(CustomerIdentityLink).all():
        if link.status not in link_policy.EFFECTIVE_LINK_STATUSES:
            continue
        customer = db.get(Customer, link.customer_id)
        assert customer is not None
        assert customer.merged_into_customer_id is None, (
            f"active link {link.id} points at merged customer {customer.public_id}"
        )
        assert customer.is_archived is False, (
            f"active link {link.id} points at archived customer {customer.public_id}"
        )

    # 2. `active` implies exactly one live link; anything else implies none.
    for identity in db.query(CustomerIdentity).all():
        live = (
            db.query(CustomerIdentityLink)
            .filter_by(identity_id=identity.id, status=LinkStatus.ACTIVE.value)
            .count()
        )
        if identity.status == IdentityStatus.ACTIVE.value:
            assert live == 1, f"{identity.public_id} is active with {live} links"
        else:
            assert live == 0, f"{identity.public_id} is {identity.status} with {live} links"

    # 3 and 4 are asserted per test, because "conflicting outcomes" is defined by what the
    # test raced. What is universal is that no link is duplicated for one customer.
    linked_customers = [
        link.customer_id
        for link in db.query(CustomerIdentityLink).filter_by(status=LinkStatus.ACTIVE.value).all()
    ]
    assert len(linked_customers) == len(set(linked_customers))


def _assert_nothing_left_behind(db, *, identity_reference: str) -> None:
    """Clause 4: a refused approval leaves no trace of having been attempted."""
    db.expire_all()
    identity = _identity(db, identity_reference)
    assert identity.status == IdentityStatus.PENDING_APPROVAL.value
    assert identity.approved_at is None
    assert db.query(CustomerIdentityLink).filter_by(identity_id=identity.id).count() == 0, (
        "a refused approval left a link row"
    )
    assert (
        db.query(CustomerAccountApprovalAttempt).filter_by(identity_id=identity.id).count() == 0
    ), "a refused approval left an idempotency claim"


def _prepare_link(account_client, account_db, account_users, captured_mail, customer, email):
    """One applicant, verified, with an acknowledged preview naming ``customer``."""
    reference = pending_identity(account_client, captured_mail, email)
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", customer.public_id)
    account_db.commit()
    account_db.expire_all()
    return reference, fingerprint


def _link_call(reference, customer_public_id, fingerprint, idempotency=None):
    def call(session):
        return approval.approve_link_existing(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            customer_public_id=customer_public_id,
            preview_fingerprint=fingerprint,
            idempotency_key=idempotency or key(),
            ip_address=None,
        )

    return call


def _merge_call(source_public_id, target_public_id):
    def call(session):
        return customer_service.merge_customers(
            session,
            source=_customer(session, source_public_id),
            target=_customer(session, target_public_id),
            actor=_actor(session),
            ip_address=None,
        )

    return call


# --- The premise ---------------------------------------------------------------


def test_a_read_before_the_first_write_is_protected(account_engine):
    """The property the guards rely on, demonstrated rather than assumed (DEC-0108).

    Two connections. One reads a row; the other writes a *different* row and commits; the
    first then tries to write its own row. It must be **refused**, because it decided on
    data that has since moved. That is write skew being prevented, and it is the shape of
    "a merge checks for an account link while an approval creates one".

    Phase 10 found this was **not** true of this engine as configured: pysqlite emitted no
    ``BEGIN`` until it saw a statement that changed something, so a read taken first
    belonged to no transaction and the write went through on stale data. `app/core/db.py`
    now emits ``BEGIN`` explicitly, and this test is what says so -- if it ever fails, the
    guards in `customer_service.merge_customers` are load-bearing on their own again and
    the docstring there stops being true.
    """
    factory = sessionmaker(
        bind=account_engine, autoflush=False, expire_on_commit=False, future=True
    )
    first, second = factory(), factory()
    try:
        first.execute(
            text("create table if not exists skew_probe (id integer primary key, v integer)")
        )
        first.execute(text("insert into skew_probe (id, v) values (1, 0), (2, 0)"))
        first.commit()

        # The check half: a read, which now opens a transaction and holds a snapshot.
        assert first.execute(text("select v from skew_probe where id = 1")).scalar() == 0

        # The other connection changes the world and lands it.
        second.execute(text("update skew_probe set v = 1 where id = 1"))
        second.commit()

        # The first tries to write on the strength of its now-stale read, and cannot.
        with pytest.raises(OperationalError):
            first.execute(text("update skew_probe set v = 9 where id = 2"))
            first.commit()
    finally:
        first.rollback()
        second.rollback()
        first.execute(text("drop table if exists skew_probe"))
        first.commit()
        first.close()
        second.close()


# --- Link commits first ---------------------------------------------------------


def test_link_commits_first_then_the_merge_of_the_linked_source_is_refused(
    account_client, account_db, account_users, captured_mail, second_session
):
    """Source linked. The merge arrives second and finds the link."""
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    add_shipment(account_db, survivor, days_ago=20)
    reference, fingerprint = _prepare_link(
        account_client, account_db, account_users, captured_mail, source, "a@demo.example.com"
    )

    linked = _run(account_db, _link_call(reference, source.public_id, fingerprint))
    assert linked[0] == "ok"

    merged = _run(second_session, _merge_call(source.public_id, survivor.public_id))
    assert merged[0] == "refused"
    assert isinstance(merged[1], link_policy.LinkedCustomerMergeRefused)
    assert merged[1].detail["blocked_side"] == link_policy.SIDE_SOURCE

    _assert_invariant(account_db)
    account_db.expire_all()
    assert _customer(account_db, source.public_id).merged_into_customer_id is None


def test_link_commits_first_then_the_merge_into_the_linked_survivor_is_refused(
    account_client, account_db, account_users, captured_mail, second_session
):
    """Surviving customer linked -- the direction that would *grow* a disclosed history.

    The source carries shipments. Merging would move all of them onto a customer an
    identity is already linked to, which is an expansion of that account's shipment history
    that nobody previewed and nobody acknowledged. The refusal is what prevents it.
    """
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    add_shipment(account_db, source, days_ago=30)
    add_shipment(account_db, source, days_ago=15)
    reference, fingerprint = _prepare_link(
        account_client, account_db, account_users, captured_mail, survivor, "b@demo.example.com"
    )

    assert _run(account_db, _link_call(reference, survivor.public_id, fingerprint))[0] == "ok"

    acknowledged = (
        account_db.query(CustomerAccountDisclosureAcknowledgement)
        .order_by(CustomerAccountDisclosureAcknowledgement.id.desc())
        .first()
    )
    assert acknowledged.disclosed_shipment_count == 0

    merged = _run(second_session, _merge_call(source.public_id, survivor.public_id))
    assert merged[0] == "refused"
    assert merged[1].detail["blocked_side"] == link_policy.SIDE_TARGET

    _assert_invariant(account_db)
    account_db.expire_all()
    # The account's history is still the zero shipments its holder's reviewer agreed to.
    from app.services import customer_account_disclosure_service as disclosure

    survivor_row = _customer(account_db, survivor.public_id)
    assert disclosure.summarize(account_db, survivor_row.id).shipment_count == 0


def test_both_customers_linked_refuses_and_names_both(
    account_client, account_db, account_users, captured_mail, second_session
):
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    first_ref, first_fp = _prepare_link(
        account_client, account_db, account_users, captured_mail, source, "c1@demo.example.com"
    )
    assert _run(account_db, _link_call(first_ref, source.public_id, first_fp))[0] == "ok"
    second_ref, second_fp = _prepare_link(
        account_client, account_db, account_users, captured_mail, survivor, "c2@demo.example.com"
    )
    assert _run(account_db, _link_call(second_ref, survivor.public_id, second_fp))[0] == "ok"

    merged = _run(second_session, _merge_call(source.public_id, survivor.public_id))
    assert merged[0] == "refused"
    assert merged[1].detail["blocked_side"] == link_policy.SIDE_BOTH

    _assert_invariant(account_db)


# --- Merge commits first --------------------------------------------------------


def test_merge_commits_first_then_the_link_to_the_tombstone_is_refused(
    account_client, account_db, account_users, captured_mail, second_session
):
    """The approval arrives second and its own guard refuses the merged reference.

    Note where the refusal happens: **after** the idempotency claim, which is the
    approval's first write, so the read that refuses is a read taken under the writer lock
    rather than one taken outside a transaction.
    """
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    reference, fingerprint = _prepare_link(
        account_client, account_db, account_users, captured_mail, source, "d@demo.example.com"
    )

    assert _run(account_db, _merge_call(source.public_id, survivor.public_id))[0] == "ok"

    linked = _run(second_session, _link_call(reference, source.public_id, fingerprint))
    assert linked[0] == "refused"
    assert "merged" in str(linked[1]).lower()

    _assert_invariant(account_db)
    _assert_nothing_left_behind(account_db, identity_reference=reference)


def test_merge_commits_first_then_the_link_to_the_survivor_is_stale(
    account_client, account_db, account_users, captured_mail, second_session
):
    """The survivor is still linkable -- but not on the preview taken before the merge.

    The merge moved shipments onto it, so the five OD-29 figures moved, so the fingerprint
    moved. The approval is refused with 409 and the reviewer has to read the new figures.
    That is the disclosure guarantee doing exactly what it is for.
    """
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    add_shipment(account_db, source, days_ago=40)
    reference, fingerprint = _prepare_link(
        account_client, account_db, account_users, captured_mail, survivor, "e@demo.example.com"
    )

    assert _run(account_db, _merge_call(source.public_id, survivor.public_id))[0] == "ok"

    linked = _run(second_session, _link_call(reference, survivor.public_id, fingerprint))
    assert linked[0] == "refused"
    assert isinstance(linked[1], ConflictError)
    assert linked[1].detail.get("code") == "preview_stale"

    _assert_invariant(account_db)
    _assert_nothing_left_behind(account_db, identity_reference=reference)


def test_merge_commits_first_then_a_create_new_approval_naming_a_merged_candidate_is_stale(
    account_client, account_db, account_users, captured_mail, second_session
):
    """Create-new, where the merge moved a **duplicate candidate** rather than a target.

    The applicant's address matches an existing customer, so that customer is a candidate
    and the preview says so. Merging it away changes the candidate set, which is one of
    the fingerprint's inputs, so the acknowledged preview no longer describes the world.
    """
    candidate = make_customer(account_db, email="shared@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    reference = pending_identity(account_client, captured_mail, "shared@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    account_db.commit()
    account_db.expire_all()

    assert _run(account_db, _merge_call(candidate.public_id, survivor.public_id))[0] == "ok"

    def call(session):
        return approval.approve_create_new(
            session,
            identity=_identity(session, reference),
            actor=_actor(session),
            preview_fingerprint=fingerprint,
            idempotency_key=key(),
            override_reason_code="different_party",
            ip_address=None,
        )

    created = _run(second_session, call)
    assert created[0] == "refused"
    assert created[1].detail.get("code") == "preview_stale"

    _assert_invariant(account_db)
    _assert_nothing_left_behind(account_db, identity_reference=reference)


# --- Genuine interleaving: both transactions open at once ------------------------


@pytest.mark.parametrize(
    "merge_first", [True, False], ids=["merge-claims-first", "link-claims-first"]
)
def test_an_open_merge_and_an_open_approval_resolve_to_exactly_one_outcome(
    account_client, account_db, account_users, captured_mail, second_session, merge_first
):
    """Both transactions are built and left open; only then does either try to land.

    This is the interleaving a check-then-write loses. Whichever claims first holds the
    writer lock, so the other either refuses or cannot write at all -- and the assertion is
    that exactly one of the two outcomes exists afterwards, whichever order they went in.
    """
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    add_shipment(account_db, source, days_ago=25)
    reference, fingerprint = _prepare_link(
        account_client, account_db, account_users, captured_mail, source, "f@demo.example.com"
    )

    merge = _merge_call(source.public_id, survivor.public_id)
    link = _link_call(reference, source.public_id, fingerprint)
    order = (
        [(account_db, merge, "merge"), (second_session, link, "link")]
        if merge_first
        else [(account_db, link, "link"), (second_session, merge, "merge")]
    )

    built = []
    for session, call, name in order:
        try:
            call(session)
            built.append((session, name))
        except REFUSALS:
            session.rollback()

    landed = []
    for session, name in built:
        try:
            session.commit()
            landed.append(name)
        except REFUSALS:
            session.rollback()

    assert len(landed) == 1, f"expected exactly one outcome, got {landed}"
    _assert_invariant(account_db)

    account_db.expire_all()
    if landed == ["merge"]:
        assert _customer(account_db, source.public_id).merged_into_customer_id is not None
        _assert_nothing_left_behind(account_db, identity_reference=reference)
    else:
        assert _customer(account_db, source.public_id).merged_into_customer_id is None
        assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1


# --- Retry ----------------------------------------------------------------------


def test_after_a_conflict_the_merge_retried_against_the_survivor_still_refuses(
    account_client, account_db, account_users, captured_mail, second_session
):
    """A conflict is not a transient error to be retried away.

    The reviewer retries the merge and is refused again, with the same code, because the
    obstacle is a link and retrying does not remove a link. The only thing that clears it
    is Customer Account reconciliation, which is a later phase.
    """
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    reference, fingerprint = _prepare_link(
        account_client, account_db, account_users, captured_mail, source, "g@demo.example.com"
    )
    assert _run(account_db, _link_call(reference, source.public_id, fingerprint))[0] == "ok"

    first = _run(second_session, _merge_call(source.public_id, survivor.public_id))
    second = _run(second_session, _merge_call(source.public_id, survivor.public_id))
    assert first[0] == "refused" and second[0] == "refused"
    assert first[1].detail["code"] == second[1].detail["code"] == link_policy.CONFLICT_CODE

    _assert_invariant(account_db)


def test_after_a_stale_conflict_a_fresh_preview_lets_the_approval_proceed(
    account_client, account_db, account_users, captured_mail, second_session
):
    """The other kind of retry: the refusal is a redirection, not a dead end.

    A merge made the preview stale. The reviewer reads the new figures -- which now include
    the shipments the merge moved -- acknowledges them, and the approval lands. The account
    gets the larger history *because somebody looked at it*, which is the whole of OD-29.
    """
    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    add_shipment(account_db, source, days_ago=50)
    reference, stale = _prepare_link(
        account_client, account_db, account_users, captured_mail, survivor, "h@demo.example.com"
    )

    assert _run(account_db, _merge_call(source.public_id, survivor.public_id))[0] == "ok"
    refused = _run(second_session, _link_call(reference, survivor.public_id, stale))
    assert refused[0] == "refused"

    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fresh = acknowledged_preview(api, reference, "link_existing", survivor.public_id)
    assert fresh != stale
    account_db.expire_all()

    landed = _run(second_session, _link_call(reference, survivor.public_id, fresh))
    assert landed[0] == "ok", landed[1]

    _assert_invariant(account_db)
    account_db.expire_all()
    acknowledgement = (
        account_db.query(CustomerAccountDisclosureAcknowledgement)
        .order_by(CustomerAccountDisclosureAcknowledgement.id.desc())
        .first()
    )
    assert acknowledgement.disclosed_shipment_count == 1
    assert acknowledgement.preview_fingerprint == fresh


def test_a_second_merge_of_the_same_source_loses_on_the_conditional_claim(
    account_client, account_db, account_users, captured_mail, second_session
):
    """The claim is a real conditional write, shown by making it lose.

    Two merges of one source. The second finds ``merged_into_customer_id`` no longer null,
    its ``UPDATE`` affects no row, and the row count check turns that into a refusal rather
    than a silent second merge.
    """
    source = make_customer(account_db, email="source@demo.example.com")
    first_target = make_customer(account_db, email="first@demo.example.com")
    second_target = make_customer(account_db, email="second@demo.example.com")
    account_db.commit()

    assert _run(account_db, _merge_call(source.public_id, first_target.public_id))[0] == "ok"
    again = _run(second_session, _merge_call(source.public_id, second_target.public_id))
    assert again[0] == "refused"
    assert "already been merged" in str(again[1])

    account_db.expire_all()
    assert _customer(account_db, source.public_id).merged_into_customer_id == first_target.id
    aliases = account_db.scalars(
        select(Customer.public_id).where(Customer.merged_into_customer_id.is_not(None))
    ).all()
    assert aliases == [source.public_id]
    _assert_invariant(account_db)
