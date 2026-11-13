"""``active`` has exactly one writer, and a link has exactly one shape.

Two kinds of assertion, and they are different claims.

**Source scans.** "Only the approval service activates an identity" cannot be established
by exercising the routes, because the failure it guards against is a *future* line of code
somewhere else. So the source is parsed and every assignment to the active status and to a
link's ``customer_id`` is located. This is a real control, not a lint: Phase 9 wrote the
value nowhere on purpose, Phase 10 writes it in one statement, and any third place is a
second door into a customer's shipment history.

**Database sweeps.** The cross-table invariants -- an ``active`` identity has exactly one
active link, a pending or rejected one has none -- are not expressible as SQLite
constraints, because SQLite has no cross-table ``CHECK`` and a trigger would be a fifth
mechanism in a codebase that already states its guards in four. The cost of that is stated
rather than hidden: the guarantee lives in the service's transaction ordering and in the
sweep below, which walks the whole database after a decision and finds no identity in a
state its links contradict.

The two index-backed halves -- one active link per identity, one active identity per
customer -- *are* enforced by the database, and are asserted directly against it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.account_enums import IdentityStatus, LinkStatus
from app.core.enums import Role
from app.core.time_utils import utcnow
from app.models import CustomerIdentity, CustomerIdentityLink
from tests.approval_fixtures import (
    acknowledged_preview,
    approve_create,
    approve_link,
    make_customer,
    pending_identity,
    reject,
    staff,
)

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: The one module allowed to activate an identity or write a link.
APPROVAL_MODULE = "services/customer_account_approval_service.py"


def _python_files():
    return [path for path in APP.rglob("*.py") if "__pycache__" not in path.parts]


def _relative(path: pathlib.Path) -> str:
    return path.relative_to(APP).as_posix()


def test_only_two_functions_write_the_active_identity_status():
    """Every module that *assigns* the active status, located by parsing rather than grep.

    There are two, and the second one is why this test is worth having. The approval
    service performs transition 4 of `STATE_MACHINES.md` -- approve and link -- and it is
    the only path an application takes to `active`.
    ``customer_identity_service.reinstate`` performs transition 7, un-suspending an
    account that was already approved, and the owner's state machine authorizes it.

    Phase 10 found that transition 7 was **unsafe as written**: it tested
    ``approved_at is not None``, which stays true forever, so an account that was approved,
    suspended and then unlinked would have come back `active` with no active link -- an
    identity in the one state that reaches shipment data, with no customer to reach it
    through. It now checks the live link instead, which is what the invariant is actually
    about, and `test_reinstatement_cannot_produce_a_linkless_active_identity` asserts it.

    A **third** writer is a defect. This assertion is the one that would catch it.
    """
    writers = set()
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            assigns_status = (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Attribute) and target.attr == "status"
                    for target in node.targets
                )
            ) or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "values"
                and any(keyword.arg == "status" for keyword in node.keywords)
            )
            if not assigns_status:
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "IdentityStatus.ACTIVE" in segment or '"active"' in segment:
                writers.add(_relative(path))

    assert writers == {APPROVAL_MODULE, "services/customer_identity_service.py"}, writers


def test_there_is_exactly_one_statement_that_activates_an_application():
    """Not just one module -- one statement, in one function.

    A second activation inside the approval service would be a second place for the
    conditional guard to be forgotten. ``DecisionResult(status=...)`` is a *response*, not
    a write, so the scan looks only at ``.values(...)``.
    """
    path = APP / APPROVAL_MODULE
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    activations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "values"
        and any(
            keyword.arg == "status"
            and "IdentityStatus.ACTIVE" in (ast.get_source_segment(source, keyword.value) or "")
            for keyword in node.keywords
        )
    ]
    assert len(activations) == 1

    enclosing = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.lineno <= activations[0].lineno <= (node.end_lineno or node.lineno)
    ]
    assert enclosing == ["_activate"]


def test_the_activation_is_a_conditional_update_with_its_row_count_checked():
    """The guard itself, read out of the source.

    ``WHERE status = 'pending_approval'`` plus a ``rowcount`` check is what makes an
    approve/reject race have one winner. A plain ``UPDATE`` would activate an account
    somebody had already rejected.
    """
    source = (APP / APPROVAL_MODULE).read_text(encoding="utf-8")
    activate = source.split("def _activate(")[1].split("\ndef ")[0]
    assert "IdentityStatus.PENDING_APPROVAL.value" in activate
    assert "rowcount" in activate


def test_reinstatement_cannot_produce_a_linkless_active_identity(account_db):
    """Transition 7, with the invariant enforced rather than assumed.

    An account that was approved and then lost its link comes back to
    ``pending_approval``, which is a state a person has to decide about -- not to
    ``active``, which is a state that reaches data.
    """
    from app.services import customer_identity_service

    identity = CustomerIdentity(
        public_id="CA-TEST20",
        email_entered="reinstate@demo.example.com",
        email_normalized="reinstate@demo.example.com",
        password_hash="unused",
        status=IdentityStatus.SUSPENDED.value,
        approved_at=utcnow(),
    )
    account_db.add(identity)
    account_db.flush()

    customer_identity_service.reinstate(account_db, identity, reason_code="review_complete")
    assert identity.status == IdentityStatus.PENDING_APPROVAL.value

    customer = make_customer(account_db, email="reinstate-target@demo.example.com")
    account_db.add(
        CustomerIdentityLink(
            identity_id=identity.id,
            customer_id=customer.id,
            status=LinkStatus.ACTIVE.value,
            linked_at=utcnow(),
        )
    )
    account_db.flush()
    identity.status = IdentityStatus.SUSPENDED.value
    customer_identity_service.reinstate(account_db, identity, reason_code="review_complete")
    assert identity.status == IdentityStatus.ACTIVE.value
    _sweep(account_db)
    account_db.rollback()


def test_a_link_is_constructed_in_exactly_one_place():
    """A link cannot be repointed by an ordinary update, because nothing updates one.

    Asserted two ways: the model is constructed once in the whole application, and no
    module assigns to a link variable's ``customer_id``.
    """
    constructions: dict[str, int] = {}
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        # `class CustomerIdentityLink(Base)` is the declaration, not a construction.
        count = source.count("CustomerIdentityLink(") - source.count("class CustomerIdentityLink(")
        if count:
            constructions[_relative(path)] = count
    assert constructions == {APPROVAL_MODULE: 1}, constructions

    # And no module issues an UPDATE against the link table. ``customer_service`` does
    # repoint a `link` variable on a merge -- that one is a `customer_tags` row, which is
    # why this check names the model rather than matching a variable called `link`.
    for path in _python_files():
        if _relative(path) in {APPROVAL_MODULE, "models/customer_account.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        assert "update(CustomerIdentityLink)" not in source, path


def test_no_route_module_constructs_a_link_or_activates():
    """A route is a thin caller. Either of these in a route would have bypassed the
    transaction ordering the service owns."""
    for path in (APP / "api").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "CustomerIdentityLink(" not in source, path
        assert "IdentityStatus.ACTIVE" not in source, path


# --- The database halves ------------------------------------------------------


def test_the_index_refuses_a_second_active_link_for_one_identity(account_db):
    """Enforced by ``uq_customer_identity_links_active_identity``, not by the service."""
    customer_a = make_customer(account_db, email="a@demo.example.com")
    customer_b = make_customer(account_db, email="b@demo.example.com")
    identity = CustomerIdentity(
        public_id="CA-TEST01",
        email_entered="x@demo.example.com",
        email_normalized="x@demo.example.com",
        password_hash="unused",
        status=IdentityStatus.PENDING_APPROVAL.value,
    )
    account_db.add(identity)
    account_db.flush()

    for customer in (customer_a, customer_b):
        account_db.add(
            CustomerIdentityLink(
                identity_id=identity.id,
                customer_id=customer.id,
                status=LinkStatus.ACTIVE.value,
                linked_at=utcnow(),
            )
        )
    with pytest.raises(IntegrityError):
        account_db.flush()
    account_db.rollback()


def test_the_index_refuses_a_second_active_identity_for_one_customer(account_db):
    """Enforced by ``uq_customer_identity_links_active_customer``. Release 1, OD-25."""
    customer = make_customer(account_db, email="shared@demo.example.com")
    for index in (1, 2):
        identity = CustomerIdentity(
            public_id=f"CA-TEST0{index}",
            email_entered=f"x{index}@demo.example.com",
            email_normalized=f"x{index}@demo.example.com",
            password_hash="unused",
            status=IdentityStatus.PENDING_APPROVAL.value,
        )
        account_db.add(identity)
        account_db.flush()
        account_db.add(
            CustomerIdentityLink(
                identity_id=identity.id,
                customer_id=customer.id,
                status=LinkStatus.ACTIVE.value,
                linked_at=utcnow(),
            )
        )
    with pytest.raises(IntegrityError):
        account_db.flush()
    account_db.rollback()


def test_a_revoked_link_does_not_block_a_later_one(account_db):
    """Both indexes are partial, so history accumulates freely.

    A plain unique index would additionally forbid a second *revoked* link, turning a
    normal correction into a data-repair job.
    """
    customer = make_customer(account_db, email="relink@demo.example.com")
    identity = CustomerIdentity(
        public_id="CA-TEST09",
        email_entered="r@demo.example.com",
        email_normalized="r@demo.example.com",
        password_hash="unused",
        status=IdentityStatus.PENDING_APPROVAL.value,
    )
    account_db.add(identity)
    account_db.flush()
    account_db.add(
        CustomerIdentityLink(
            identity_id=identity.id,
            customer_id=customer.id,
            status=LinkStatus.REVOKED.value,
            linked_at=utcnow(),
            revoked_at=utcnow(),
        )
    )
    account_db.flush()
    account_db.add(
        CustomerIdentityLink(
            identity_id=identity.id,
            customer_id=customer.id,
            status=LinkStatus.ACTIVE.value,
            linked_at=utcnow(),
        )
    )
    account_db.flush()  # no IntegrityError
    account_db.rollback()


def _sweep(session) -> None:
    """Every identity, checked against its links. The cross-table invariant.

    Not a constraint, and the docstring at the top of this module says why. This is where
    the guarantee actually lives, so it is run after every decision the suite makes.
    """
    for identity in session.query(CustomerIdentity).all():
        active = (
            session.query(CustomerIdentityLink)
            .filter_by(identity_id=identity.id, status=LinkStatus.ACTIVE.value)
            .count()
        )
        if identity.status == IdentityStatus.ACTIVE.value:
            assert active == 1, f"{identity.public_id} is active with {active} links"
        else:
            assert active == 0, f"{identity.public_id} is {identity.status} with a live link"


def test_the_sweep_holds_after_a_create_new_approval(
    account_client, account_db, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "create_new")
    assert approve_create(api, reference, fingerprint).status_code == 200
    account_db.expire_all()
    _sweep(account_db)


def test_the_sweep_holds_after_a_link_and_a_rejection(
    account_client, account_db, account_users, captured_mail
):
    customer = make_customer(account_db, email="target@demo.example.com")
    linked = pending_identity(account_client, captured_mail, "linked@demo.example.com")
    declined = pending_identity(account_client, captured_mail, "declined@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    fingerprint = acknowledged_preview(api, linked, "link_existing", customer.public_id)
    assert approve_link(api, linked, customer.public_id, fingerprint).status_code == 200
    assert reject(api, declined).status_code == 200

    account_db.expire_all()
    _sweep(account_db)
    assert account_db.query(CustomerIdentity).filter_by(status="active").count() == 1
    assert account_db.query(CustomerIdentityLink).filter_by(status="active").count() == 1


def test_the_sweep_holds_when_nothing_has_been_approved(
    account_client, account_db, account_users, captured_mail
):
    """A pending identity has no link, which is the other half of the invariant."""
    pending_identity(account_client, captured_mail, "waiting@demo.example.com")
    account_db.expire_all()
    _sweep(account_db)
    assert account_db.query(CustomerIdentityLink).count() == 0


def test_merging_a_linked_customer_is_refused_outright(
    account_client, account_db, account_users, captured_mail
):
    """**Superseded by OD-40.** This assertion was inverted, and the inversion is the point.

    As written in Phase 10 it recorded a *discovered limitation*: ``merge_customers`` knew
    nothing about ``customer_identity_links``, so merging a linked customer left an active
    link pointing at a tombstone. The test asserted that outcome and argued it was safe to
    leave open -- a merge moves the shipments to the survivor, so the account linked to the
    merged record would see nothing, which denies rather than discloses.

    That argument was about **Phase 11's** ownership rule and it was correct about it. What
    it did not cover is the direction the owner actually ruled on: merging into a customer
    the account *is* linked to grows that account's history by everything the source owned,
    with nothing acknowledged -- which is a disclosure, not a denial. And "the link points
    at a tombstone" is a state the sweep in this very module exists to forbid.

    OD-40 answers the owner question the original docstring correctly declined to settle:
    refuse the merge. So the assertion is now the refusal, and the safety property the
    original was protecting -- an account never reaching data it was not linked to -- is
    protected by a merge that does not happen at all.

    See `docs/customer_account/SUPERSEDED_ASSERTIONS.md`, entry AS-05.
    """
    from app.services import customer_account_link_policy as link_policy
    from app.services import customer_service

    source = make_customer(account_db, email="source@demo.example.com")
    survivor = make_customer(account_db, email="survivor@demo.example.com")
    reference = pending_identity(account_client, captured_mail, "merged@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    fingerprint = acknowledged_preview(api, reference, "link_existing", source.public_id)
    assert approve_link(api, reference, source.public_id, fingerprint).status_code == 200
    account_db.expire_all()

    with pytest.raises(link_policy.LinkedCustomerMergeRefused) as refused:
        customer_service.merge_customers(account_db, source=source, target=survivor)
    assert refused.value.detail["blocked_side"] == link_policy.SIDE_SOURCE
    account_db.rollback()
    account_db.expire_all()

    # Nothing moved. The link is still live, and it still points at a record that is not a
    # tombstone -- which is the invariant the original version of this test recorded a
    # violation of.
    link = account_db.query(CustomerIdentityLink).one()
    assert link.status == LinkStatus.ACTIVE.value
    assert link.customer_id == source.id
    assert account_db.get(type(source), source.id).merged_into_customer_id is None

    _sweep(account_db)
