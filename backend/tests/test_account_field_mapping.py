"""Where an approved registration field lands, and the precedence between the names.

Two claims are worth separating. The first is **coverage**: every key the registration
allowlist accepts has a decided destination, and no destination exists for a key nobody
may submit. That is asserted against the two modules rather than against a list written
here, so adding a key to one without the other fails.

The second is **precedence**, which is the part `FIELD_MATRIX.md` section 6 left open and
Phase 10 had to decide: which of legal name, display name, primary contact name and
company name ends up in ``customers.full_name``, the one column every existing query
reads. Getting that wrong would not raise anything -- it would quietly file a company
under a person's name, or the reverse -- so it is asserted for both customer types and in
both directions.
"""

from __future__ import annotations

import pytest

from app.core import account_field_mapping as mapping
from app.core.account_fields import ALLOWED_FIELD_KEYS
from app.core.enums import AddressRole


def test_every_submittable_key_has_a_decided_destination():
    """The allowlist and the mapping are the same key set, in both directions.

    A key a customer may submit with nowhere to land would be silently dropped at
    approval; a mapping entry for a key nobody may submit is dead code that looks like
    policy.
    """
    assert ALLOWED_FIELD_KEYS == mapping.MAPPED_FIELD_KEYS
    assert len(mapping.FIELD_MAP) == len(mapping.MAPPED_FIELD_KEYS)


def test_the_mapping_table_names_only_three_destination_tables():
    """`customers`, `customer_addresses`, `consent_events`. Nothing else is reachable.

    This is the claim that a registration cannot write a tag, an interaction, a note, an
    owner, a suppression or a shipment. It is asserted over the table the reviewer's
    documentation prints, so the documentation and the code cannot disagree.
    """
    tables = {target.table for target in mapping.FIELD_MAP}
    assert tables == {"customers", "customer_addresses", "consent_events"}


def test_an_individual_files_the_legal_name_as_the_contactable_name():
    mapped = mapping.resolve_customer_payload(
        {
            "customer_type": "individual",
            "legal_name": "Nguyen Thi Bich Hanh",
            "display_name": "Hanh",
            "primary_contact_name": "Nguyen Thi Bich Hanh",
            "email": "hanh@demo.example.com",
        }
    )
    assert mapped.customer["full_name"] == "Nguyen Thi Bich Hanh"
    assert mapped.customer["legal_name"] == "Nguyen Thi Bich Hanh"
    assert mapped.customer["display_name"] == "Hanh"
    assert "business_name" not in mapped.customer


def test_a_business_files_the_contact_as_the_name_and_the_legal_name_as_the_company():
    """The precedence that matters. ``full_name`` is the person to talk to, not the company.

    Filing "Mekong Trading Co" into ``full_name`` would put a company into the column the
    Staff Portal displays as a person's name and the duplicate service builds a person's
    match key from -- so the company would start matching people.
    """
    mapped = mapping.resolve_customer_payload(
        {
            "customer_type": "business",
            "business_type": "retailer",
            "legal_name": "Mekong Trading Co",
            "display_name": "Mekong",
            "primary_contact_name": "Tran Quoc Tuan",
            "email": "orders@demo.example.com",
        }
    )
    assert mapped.customer["full_name"] == "Tran Quoc Tuan"
    assert mapped.customer["business_name"] == "Mekong Trading Co"
    assert mapped.customer["legal_name"] == "Mekong Trading Co"
    assert mapped.customer["display_name"] == "Mekong"
    assert mapped.customer["business_type"] == "retailer"


def test_each_name_falls_back_to_the_other_when_only_one_was_given():
    individual = mapping.resolve_customer_payload(
        {"customer_type": "individual", "primary_contact_name": "Solo Applicant"}
    )
    assert individual.customer["full_name"] == "Solo Applicant"
    assert "legal_name" not in individual.customer

    business = mapping.resolve_customer_payload(
        {"customer_type": "business", "legal_name": "Company Only Ltd"}
    )
    assert business.customer["full_name"] == "Company Only Ltd"
    assert business.customer["business_name"] == "Company Only Ltd"


def test_a_submission_with_no_name_at_all_is_refused_rather_than_invented():
    """``customers.full_name`` is not nullable, and guessing a value is worse than refusing."""
    with pytest.raises(mapping.MappingRefused) as exc:
        mapping.resolve_customer_payload({"customer_type": "individual", "email": "a@b.example"})
    assert exc.value.field_key == "legal_name"


def test_the_billing_address_becomes_a_billing_role_and_never_a_sender():
    """The third gap, resolved as a role rather than as a flag.

    A billing row that was a sender row with a boolean would be offered by the booking
    pickers as a place to collect a parcel from, which is what the role prevents.
    """
    mapped = mapping.resolve_customer_payload(
        {
            "customer_type": "individual",
            "legal_name": "Billing Only",
            "billing_address.address_line1": "125 Nguyen Hue",
            "billing_address.city": "Ho Chi Minh City",
            "billing_address.country_code": "VN",
        }
    )
    assert [address.role for address in mapped.addresses] == [AddressRole.BILLING.value]
    billing = mapped.addresses[0]
    assert billing.is_default_sender is False
    assert billing.values["city"] == "Ho Chi Minh City"


def test_pickup_addresses_are_sender_rows_and_only_the_first_is_the_default():
    mapped = mapping.resolve_customer_payload(
        {
            "customer_type": "individual",
            "legal_name": "Two Pickups",
            "pickup_address.1.address_line1": "4120 Dixie Road",
            "pickup_address.1.city": "Mississauga",
            "pickup_address.1.country_code": "CA",
            "pickup_address.1.contact_name": "Tran Quoc Tuan",
            "pickup_address.2.address_line1": "900 Pike Street",
            "pickup_address.2.city": "Seattle",
            "pickup_address.2.country_code": "US",
        }
    )
    roles = [address.role for address in mapped.addresses]
    assert roles == [AddressRole.SENDER.value, AddressRole.SENDER.value]
    assert [address.is_default_sender for address in mapped.addresses] == [True, False]
    assert mapped.addresses[0].contact_name == "Tran Quoc Tuan"
    # The second pickup carries no contact name, so it falls back to the customer's.
    assert mapped.addresses[1].contact_name == "Two Pickups"


def test_the_customers_location_comes_from_billing_first_then_pickup_then_the_phone():
    """``customers.country_code`` is the region a later phone edit parses against.

    Leaving it null would make an account-created customer behave differently from a
    staff-created one the first time somebody edited the phone number.
    """
    billing_wins = mapping.resolve_customer_payload(
        {
            "customer_type": "individual",
            "legal_name": "Both Addresses",
            "billing_address.city": "Ho Chi Minh City",
            "billing_address.country_code": "VN",
            "pickup_address.1.city": "Mississauga",
            "pickup_address.1.country_code": "CA",
        }
    )
    assert billing_wins.customer["country_code"] == "VN"
    assert billing_wins.customer["city"] == "Ho Chi Minh City"

    pickup_only = mapping.resolve_customer_payload(
        {
            "customer_type": "individual",
            "legal_name": "Pickup Only",
            "pickup_address.1.city": "Mississauga",
            "pickup_address.1.country_code": "CA",
        }
    )
    assert pickup_only.customer["country_code"] == "CA"

    phone_only = mapping.resolve_customer_payload(
        {
            "customer_type": "individual",
            "legal_name": "Phone Only",
            "phone_country_code": "VN",
            "phone": "0901234567",
        }
    )
    assert phone_only.customer["country_code"] == "VN"


def test_marketing_consent_is_off_unless_it_was_explicitly_chosen():
    """OD-38: unchecked by default, and the absence is the answer.

    Three cases, because "absent" and "false" are different submissions and both must
    produce no consent.
    """
    for submitted in ({}, {"marketing_consent": "false"}):
        mapped = mapping.resolve_customer_payload(
            {"customer_type": "individual", "legal_name": "No Marketing", **submitted}
        )
        assert mapped.marketing_consent is False
        assert "marketing_consent" not in mapped.applied_field_keys

    chosen = mapping.resolve_customer_payload(
        {
            "customer_type": "individual",
            "legal_name": "Yes Marketing",
            "email": "yes@demo.example.com",
            "marketing_consent": "true",
        }
    )
    assert chosen.marketing_consent is True
    assert chosen.marketing_address == "yes@demo.example.com"


def test_applied_keys_name_only_what_was_actually_submitted():
    """``applied`` is per field, so it must not claim a field nobody sent."""
    mapped = mapping.resolve_customer_payload(
        {"customer_type": "individual", "legal_name": "Sparse", "email": "s@demo.example.com"}
    )
    assert set(mapped.applied_field_keys) == {"customer_type", "legal_name", "email"}


def test_differences_ignore_casing_and_whitespace_but_not_content():
    proposed = {"full_name": "  Nguyen  Thi Bich Hanh ", "city": "Hanoi"}
    current = {"full_name": "nguyen thi bich hanh", "city": "Ho Chi Minh City"}
    rows = mapping.differences(proposed, current)
    assert [row["field"] for row in rows] == ["city"]


def test_a_field_the_proposal_did_not_supply_is_not_a_difference():
    """Absence is not disagreement. Reporting it would ask a reviewer to adjudicate a
    field the applicant never filled in."""
    rows = mapping.differences({"full_name": None}, {"full_name": "Existing Name"})
    assert rows == []
