"""The registration form's field list, checked against the allowlist that is the authority.

`FIELD_MATRIX.md` §2 ends "a registration form field not in this table is a defect", and
`app.core.account_fields.FIELD_SPECS` is that table as code. The Phase 12 form declares
its own list in `frontend/src/account/pages/RegisterPage.jsx`, and a list in a second
language is a list that drifts.

The check lives **here** rather than in the frontend suite because this is the only place
both can be read: the allowlist is Python, and importing it into Vitest would mean
generating a JSON copy — which is a third list, and therefore a third thing to drift.

What this asserts, and what it deliberately does not:

* every key the form sends **is** in the allowlist. A key that is not would be refused at
  the API boundary, and the person filling in the form would see a validation error naming
  a field they cannot correct;
* the form's list has no duplicates and no empty entries;
* the form sends **no** key outside `FIELD_SPECS`, including no invented `pickup_address.4`;
* the form does not send a key the matrix marks **Never**.

It does **not** assert the converse — that the form offers every allowlisted key. It does
not: the form offers one pickup address and the allowlist permits three (OD-27's bounded
plural), and offering the second and third is a design decision rather than a correctness
one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.account_fields import ALLOWED_FIELD_KEYS, MAX_PICKUP_ADDRESSES

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER_PAGE = REPO_ROOT / "frontend" / "src" / "account" / "pages" / "RegisterPage.jsx"

#: The declaration the form exports. Parsed rather than executed, because running a JSX
#: module from pytest would mean a Node dependency in the backend suite.
DECLARATION = re.compile(
    r"export const SUBMITTED_FIELD_KEYS = \[(?P<body>.*?)\];",
    re.DOTALL,
)


def submitted_keys() -> list[str]:
    source = REGISTER_PAGE.read_text(encoding="utf-8")
    match = DECLARATION.search(source)
    assert match is not None, (
        f"{REGISTER_PAGE.name} no longer exports SUBMITTED_FIELD_KEYS as a literal array. "
        "The form's field list is the thing this test exists to check; if it has moved, "
        "point this test at the new declaration rather than deleting the check."
    )
    return re.findall(r"'([^']+)'", match.group("body"))


def test_the_form_declares_a_field_list():
    keys = submitted_keys()
    assert keys, "the registration form declares no fields"
    assert len(keys) > 10


def test_every_key_the_form_sends_is_allowlisted():
    """The check that matters. A key here that is not there is a 422 in front of a customer."""
    unknown = sorted(set(submitted_keys()) - set(ALLOWED_FIELD_KEYS))
    assert unknown == [], (
        f"the registration form submits {unknown}, which `account_fields.FIELD_SPECS` does "
        "not accept. Either add the field to FIELD_MATRIX.md section 2 and to the "
        "allowlist, or remove it from the form."
    )


def test_the_form_list_has_no_duplicates_or_blanks():
    keys = submitted_keys()
    assert len(keys) == len(set(keys)), "the registration form declares a key twice"
    assert all(key.strip() for key in keys)


def test_the_form_does_not_invent_a_fourth_pickup_address():
    """OD-27's plural is bounded at three. A fourth would be refused unparsed."""
    indexes = {
        int(match.group(1))
        for key in submitted_keys()
        if (match := re.match(r"pickup_address\.(\d+)\.", key))
    }
    assert indexes <= set(range(1, MAX_PICKUP_ADDRESSES + 1)), indexes


@pytest.mark.parametrize(
    "never_field",
    [
        "notes",
        "internal_notes",
        "lifecycle_status",
        "owner_user_id",
        "is_archived",
        "do_not_contact",
        "selling_amount",
        "payment_state",
        "primary_shipping_purpose",
        "shipping_frequency",
        "estimated_monthly_shipments",
        "primary_route_group",
        "preferred_contact_channel",
        "source_system",
    ],
)
def test_the_form_never_offers_a_never_field(never_field: str):
    """`FIELD_MATRIX.md` §3.4. None of these is in the allowlist either, which is the real
    protection — this asserts the form does not *try*, so a reviewer reading the form does
    not have to check each control against the matrix by eye."""
    assert never_field not in submitted_keys()
    assert never_field not in ALLOWED_FIELD_KEYS


def test_the_form_sends_the_marketing_answer_explicitly():
    """Unchecked by default means the absence is an answer, and the form states it anyway.

    OD-38 makes marketing consent explicit and separate. The form sends `'false'` rather
    than omitting the key when the box is unchecked, so the proposal records that the
    question was asked — which is a different fact from "the field was not on the form".
    """
    assert "marketing_consent" in submitted_keys()
    assert "marketing_consent" in ALLOWED_FIELD_KEYS


def test_the_form_states_the_language_rather_than_defaulting_to_it():
    """Recorded as a choice rather than left to a column default: the screen language the
    person registered in (Vietnamese first, OD-71, superseding OD-39's fixed English)."""
    assert "preferred_language" in submitted_keys()
    source = REGISTER_PAGE.read_text(encoding="utf-8")
    assert "customer.preferred_language = locale" in source
