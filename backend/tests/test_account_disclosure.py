"""The OD-29 disclosure calculation, against data rather than against its own definition.

The number this module computes is the one a reviewer is asked to agree to before a
stranger gains access to a customer's shipment history. It can be wrong in two directions
and only one of them is visible later: an overcount makes a reviewer hesitate, an
undercount makes them approve a disclosure larger than the one they read. So the
arithmetic is asserted against seeded rows for every clause of the rule, including the
ones that exclude.

The second claim here is **what ownership is**. A shipment belongs to a customer through
``shipments.customer_id`` and through nothing else: not a matching sender email, not a
matching phone, not a recipient, not a tracking reference (OD-29, OD-30, T-04). That is
asserted by building a shipment whose sender fields match the applicant exactly and whose
``customer_id`` is somebody else, and counting zero.
"""

from __future__ import annotations

from app.core.enums import BookingState
from app.services import customer_account_disclosure_service as disclosure
from tests.approval_fixtures import add_shipment, make_customer


def test_an_empty_customer_discloses_nothing_but_still_produces_a_summary(account_db):
    """A zero is a figure, not an absence. OD-29 requires it to be acknowledged too."""
    customer = make_customer(account_db)
    summary = disclosure.summarize(account_db, customer.id)
    assert summary.shipment_count == 0
    assert summary.oldest_booked_at is None
    assert summary.newest_booked_at is None
    assert summary.includes_cancelled is False
    assert summary.includes_rebooked is False
    assert summary.definition_version == disclosure.DISCLOSURE_DEFINITION_VERSION


def test_the_count_and_the_date_bounds_come_from_the_qualifying_rows(account_db):
    customer = make_customer(account_db)
    add_shipment(account_db, customer, days_ago=100)
    add_shipment(account_db, customer, days_ago=50)
    add_shipment(account_db, customer, days_ago=1)

    summary = disclosure.summarize(account_db, customer.id)
    assert summary.shipment_count == 3
    assert summary.oldest_booked_at < summary.newest_booked_at
    assert (summary.newest_booked_at - summary.oldest_booked_at).days == 99


def test_cancelled_shipments_are_counted_and_labelled(account_db):
    """OD-29 keeps them visible with a safe state, so the count must include them.

    A count that dropped cancellations would understate the disclosure -- the one
    direction this number must never be wrong in.
    """
    customer = make_customer(account_db)
    add_shipment(account_db, customer, days_ago=10)
    add_shipment(account_db, customer, days_ago=5, booking_state=BookingState.CANCELLED)

    summary = disclosure.summarize(account_db, customer.id)
    assert summary.shipment_count == 2
    assert summary.includes_cancelled is True


def test_rebooked_shipments_are_counted_and_labelled_from_either_end_of_the_link(account_db):
    customer = make_customer(account_db)
    original = add_shipment(account_db, customer, days_ago=20)
    replacement = add_shipment(account_db, customer, days_ago=19, rebooked_from=original.id)
    original.rebooked_to_shipment_id = replacement.id
    account_db.commit()

    summary = disclosure.summarize(account_db, customer.id)
    assert summary.shipment_count == 2
    assert summary.includes_rebooked is True


def test_drafts_and_demo_records_are_excluded(account_db):
    """Both are excluded by `SHIPMENT_ALLOWLISTS.md` section 5, so neither is disclosed.

    A draft has no customer-facing identifier at all and Public Tracking already refuses
    it; a demo record is not this customer's shipment.
    """
    customer = make_customer(account_db)
    add_shipment(account_db, customer, days_ago=10)
    add_shipment(account_db, customer, days_ago=9, booking_state=BookingState.DRAFT)
    add_shipment(account_db, customer, days_ago=8, is_demo_record=True)

    summary = disclosure.summarize(account_db, customer.id)
    assert summary.shipment_count == 1


def test_only_the_shipper_relationship_counts(account_db):
    """The claim OD-29 is actually making, asserted against a decoy.

    The other customer's shipment carries the applicant's name, email and phone in its
    sender snapshot. It is still not theirs, because ownership is ``customer_id`` and
    nothing else -- not an email match, not a phone match, not a name match, and not
    possession of the reference printed on it.
    """
    applicant_customer = make_customer(
        account_db, full_name="Applicant", email="applicant@demo.example.com"
    )
    other = make_customer(account_db, full_name="Somebody Else", email="other@demo.example.com")
    decoy = add_shipment(account_db, other, days_ago=5)
    decoy.sender_email = "applicant@demo.example.com"
    decoy.sender_name = "Applicant"
    decoy.sender_phone_e164 = "+14165550199"
    decoy.recipient_email = "applicant@demo.example.com"
    account_db.commit()

    summary = disclosure.summarize(account_db, applicant_customer.id)
    assert summary.shipment_count == 0
    assert disclosure.summarize(account_db, other.id).shipment_count == 1


def test_a_shipment_without_a_booking_date_is_counted_but_bounds_nothing(account_db):
    """It is disclosed, and it has no date to state. Both are true at once."""
    customer = make_customer(account_db)
    dated = add_shipment(account_db, customer, days_ago=7)
    undated = add_shipment(account_db, customer, days_ago=3)
    undated.booking_date = None
    account_db.commit()

    summary = disclosure.summarize(account_db, customer.id)
    assert summary.shipment_count == 2
    assert summary.oldest_booked_at == summary.newest_booked_at == dated.booking_date


def test_the_summary_serializes_to_counts_and_dates_and_nothing_else(account_db):
    """The audit shape. No reference, no package, no event, no recipient, no money."""
    customer = make_customer(account_db)
    add_shipment(account_db, customer, days_ago=4)
    detail = disclosure.summarize(account_db, customer.id).as_audit_detail()

    assert set(detail) == {
        "disclosed_shipment_count",
        "oldest_booked_at",
        "newest_booked_at",
        "includes_cancelled",
        "includes_rebooked",
        "disclosure_definition_version",
    }


def test_the_empty_summary_is_what_a_create_new_preview_uses(account_db):
    """A customer that does not exist yet discloses nothing, and says so explicitly."""
    summary = disclosure.empty()
    assert summary.shipment_count == 0
    assert summary.definition_version == disclosure.DISCLOSURE_DEFINITION_VERSION


def test_the_definition_version_is_part_of_the_fingerprint_material(account_db):
    """A change to the rule must invalidate acknowledgements taken under the old one."""
    customer = make_customer(account_db)
    parts = disclosure.summarize(account_db, customer.id).fingerprint_parts()
    assert f"definition={disclosure.DISCLOSURE_DEFINITION_VERSION}" in parts
    assert len(parts) == 6
