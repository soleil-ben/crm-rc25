"""Every reference a test fixture builds must be one the application could have issued.

DEC-0117. Two fixture modules built a `public_id` as `SX-<route>-<uuid4().hex[:12]>`. The
unambiguous alphabet the real generator draws from is
`ABCDEFGHJKLMNPQRSTUVWXYZ23456789` -- no `0`, no `1`, no `I`, no `O` -- and hexadecimal
contains `0` and `1` freely, so such a reference parses about one time in five.

The consequence is quiet in the worst way. The shipment exists, is listed, is reported on
and is exported, because those paths address it by row. Every path that addresses it by
*reference* refuses it before building a query, and refuses it with the same generic
not-found it gives an unknown reference -- so the fixture's defect arrives dressed as the
product's answer. One test had been passing at roughly one run in five since Phase 11.

These tests assert the property rather than the spelling: whatever a fixture builds, the
public parser must accept it as a shipment reference.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.enums import BookingState, RouteGroup
from app.core.public_reference import parse_public_reference
from app.services.identifier_service import UNAMBIGUOUS_ALPHABET
from tests.approval_fixtures import add_shipment as approval_add_shipment
from tests.approval_fixtures import make_customer as approval_make_customer
from tests.conftest import add_shipment, make_customer

TESTS_ROOT = Path(__file__).resolve().parent

#: Every route group, so a prefix that is valid for one and not another cannot hide.
ROUTE_GROUPS = [route.value for route in RouteGroup]


def test_the_alphabet_excludes_the_characters_hex_would_supply():
    """The premise of DEC-0117, asserted rather than assumed.

    If `0` or `1` were ever added to the alphabet this whole file would still pass while
    testing nothing, so the premise is checked first.
    """
    for confusable in "01IO":
        assert confusable not in UNAMBIGUOUS_ALPHABET


@pytest.mark.parametrize("route_group", ROUTE_GROUPS)
def test_add_shipment_builds_a_reference_the_parser_accepts(db, route_group):
    customer = make_customer(db, full_name="Reference Check", email="ref.check@example.com")
    for _ in range(25):
        shipment = add_shipment(db, customer, route_group=route_group)
        parsed = parse_public_reference(shipment.public_id)
        assert parsed is not None, shipment.public_id
        assert parsed.kind == "shipment"
        assert parsed.value == shipment.public_id


def test_the_approval_fixture_builds_a_reference_the_parser_accepts(db):
    customer = approval_make_customer(
        db, full_name="Approval Check", email="appr.check@example.com"
    )
    for _ in range(25):
        shipment = approval_add_shipment(db, customer)
        parsed = parse_public_reference(shipment.public_id)
        assert parsed is not None, shipment.public_id
        assert parsed.kind == "shipment"


def test_a_draft_still_has_no_reference_at_all(db):
    """The fix must not give a draft an identifier. A draft has none in production."""
    customer = make_customer(db, full_name="Draft Check", email="draft.check@example.com")
    draft = add_shipment(db, customer, booking_state=BookingState.DRAFT)
    assert draft.public_id is None


def test_no_fixture_module_derives_a_reference_from_hex():
    """The spelling, as a second line of defence, across every fixture module.

    The property tests above cover the two builders a test can call. This one reads the
    source, because the next fixture module will be written by copying one of these and
    the copy should fail here rather than one run in five later.
    """
    offenders = []
    pattern = re.compile(r'f"SX-[^"]*uuid', re.I)
    for module in sorted(TESTS_ROOT.glob("*.py")):
        for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                offenders.append(f"{module.name}:{number}: {line.strip()}")
    assert not offenders, (
        "A Solaris reference must be built with identifier_service.random_suffix, not "
        "from hex -- hex supplies 0 and 1, which the unambiguous alphabet excludes "
        "(DEC-0117):\n  " + "\n  ".join(offenders)
    )
