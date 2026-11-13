"""The staff review reads: the queue, one application, its duplicate candidates.

Three properties, in order of how badly each one fails silently.

**Bounded.** An unbounded queue endpoint is a bulk export of everybody who has ever
applied, available to anybody who can read it. The cap is asserted against a request that
asks for more.

**Totally ordered.** A sort with no tie-break lets two rows swap between page one and page
two, which hides an application from a reviewer paging through and looks like nothing at
all. Asserted by paging through a set that shares a sort value.

**Narrow.** The queue carries no contact detail, and the duplicate candidates carry only
what a linking decision needs. Both are asserted by name against a populated record rather
than by reading the schema.
"""

from __future__ import annotations

from app.core.enums import Role
from tests.approval_fixtures import BASE, make_customer, pending_identity, staff


def test_the_queue_lists_a_verified_pending_application(
    account_client, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    response = api.get(BASE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["account_reference"] == reference
    assert row["status"] == "pending_approval"
    assert row["email_verified_at"] is not None
    assert row["field_count"] > 0


def test_an_unverified_application_is_not_in_the_queue(
    account_client, account_users, captured_mail
):
    """Verification is not approval, but it is a precondition for review (OD-23).

    A ``pending_verification`` identity has not proved mailbox control, so there is
    nothing a reviewer could responsibly decide about it.
    """
    from tests.account_fixtures import register

    register(account_client, email="unverified@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    assert api.get(BASE).json()["total"] == 0


def test_the_queue_carries_no_contact_detail_of_any_kind(
    account_client, account_users, captured_mail
):
    """The list is a list of applications, not a contact export.

    The registration fixture submits a name, an email, a phone and two addresses. None of
    them may appear on the page a reviewer sees before choosing a row.
    """
    pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    raw = api.get(BASE).text.lower()

    for planted in (
        "hanh@demo.example.com",
        "0901234567",
        "dixie road",
        "nguy",
        "mississauga",
    ):
        assert planted.lower() not in raw, planted


def test_the_page_size_is_capped_by_the_server(account_client, account_users, captured_mail):
    pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    over = api.get(BASE, params={"limit": 5000})
    assert over.status_code == 422  # the route's own bound refuses it outright

    at_cap = api.get(BASE, params={"limit": 100})
    assert at_cap.status_code == 200
    assert at_cap.json()["limit"] == 100


def test_paging_is_total_so_no_application_can_hide_between_pages(
    account_client, account_users, captured_mail
):
    """Four applications submitted in one test share a submission second.

    Ordering on ``submitted_at`` alone would make the page boundary arbitrary. The
    tie-break is the account reference, so walking the pages returns each row exactly
    once.
    """
    for index in range(4):
        pending_identity(account_client, captured_mail, f"applicant{index}@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    seen: list[str] = []
    for offset in range(0, 4, 2):
        page = api.get(BASE, params={"limit": 2, "offset": offset}).json()
        seen.extend(row["account_reference"] for row in page["items"])

    assert len(seen) == 4
    assert len(set(seen)) == 4
    assert seen == sorted(seen)


def test_the_queue_filters_by_account_reference(account_client, account_users, captured_mail):
    wanted = pending_identity(account_client, captured_mail, "wanted@demo.example.com")
    pending_identity(account_client, captured_mail, "other@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    filtered = api.get(BASE, params={"account_reference": wanted}).json()
    assert [row["account_reference"] for row in filtered["items"]] == [wanted]


def test_the_detail_shows_both_the_typed_and_the_normalized_value(
    account_client, account_users, captured_mail
):
    """OD-28: the approver sees the proposed value and the normalized value.

    The normalized form is what duplicate review compared, so a reviewer wondering why
    something matched needs to be able to see it.
    """
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    detail = api.get(f"{BASE}/{reference}").json()
    assert detail["status"] == "pending_approval"
    assert detail["has_active_link"] is False
    # The login address is published separately, because a registration supplies it once
    # at the top level and it is never a proposal field row.
    assert detail["account_email_entered"] == "hanh@demo.example.com"
    assert detail["account_email_normalized"] == "hanh@demo.example.com"
    assert "email" not in {row["field_key"] for row in detail["fields"]}

    by_key = {row["field_key"]: row for row in detail["fields"]}
    assert by_key["phone"]["proposed_value"] == "0901234567"
    assert by_key["phone"]["proposed_value_normalized"] == "+84901234567"
    # A name normalizes to its accent-folded match key, which is what duplicate review
    # compared -- so it must be visible and must not be the same string.
    assert (
        by_key["legal_name"]["proposed_value_normalized"] != by_key["legal_name"]["proposed_value"]
    )
    assert all(row["applied"] is False for row in detail["fields"])


def test_the_detail_carries_no_duplicate_result(
    account_client, account_db, account_users, captured_mail
):
    """Opening an application and looking at other people's records are two accesses.

    They are separate requests so the audit log can tell them apart, and so a reviewer who
    only wanted to read a submission has not thereby been shown a list of customers. A
    matching customer exists here, so the absence is a real absence rather than an empty
    database.
    """
    make_customer(account_db, full_name="Hanh Nguyen", email="hanh@demo.example.com")
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    response = api.get(f"{BASE}/{reference}")
    detail = response.json()
    assert "candidates" not in detail
    assert "duplicate_classification" not in detail
    assert "STCA-" not in response.text


def test_an_unknown_reference_is_a_plain_not_found(account_client, account_users):
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    assert api.get(f"{BASE}/CA-999999").status_code == 404


def test_duplicate_candidates_come_from_the_existing_service(
    account_client, account_db, account_users, captured_mail
):
    """An exact email match classifies as ``exact`` and names the record.

    The scoring is `duplicate_service`'s, unchanged: this test asserts the classification
    the review path derives from it, not a second rule.
    """
    make_customer(account_db, full_name="Hanh Nguyen", email="hanh@demo.example.com")
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    body = api.get(f"{BASE}/{reference}/duplicate-candidates").json()
    assert body["duplicate_classification"] == "exact"
    assert len(body["candidates"]) == 1
    candidate = body["candidates"][0]
    assert candidate["matched_on"] == ["email"]
    assert candidate["linkable"] is True


def test_a_name_only_match_is_probable_rather_than_exact(
    account_client, account_db, account_users, captured_mail
):
    make_customer(
        account_db,
        full_name="Nguyễn Thị Bích Hạnh",
        email="different@demo.example.com",
        phone="+1 416 555 0123",
    )
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    body = api.get(f"{BASE}/{reference}/duplicate-candidates").json()
    assert body["duplicate_classification"] == "probable"
    assert body["candidates"][0]["matched_on"] == ["name"]


def test_no_candidate_at_all_is_a_classification_not_an_error(
    account_client, account_users, captured_mail
):
    reference = pending_identity(account_client, captured_mail, "nobodylikethis@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)
    body = api.get(f"{BASE}/{reference}/duplicate-candidates").json()
    assert body["duplicate_classification"] == "none"
    assert body["candidates"] == []


def test_a_candidate_shows_only_what_a_linking_decision_needs(
    account_client, account_db, account_users, captured_mail
):
    """Not the candidate's email, phone, notes, owner, tags or lifecycle.

    The reviewer is deciding whether this is the same party. The match reasons already say
    which fields agreed; reprinting the other person's contact details onto the screen
    would be a disclosure the decision does not need.
    """
    make_customer(
        account_db,
        full_name="Hanh Nguyen",
        email="hanh@demo.example.com",
        phone="+1 416 555 0177",
        notes="PLANTED-INTERNAL-NOTE",
    )
    reference = pending_identity(account_client, captured_mail, "hanh@demo.example.com")
    api = staff(account_client, account_users[Role.OPERATIONS].email)

    response = api.get(f"{BASE}/{reference}/duplicate-candidates")
    candidate = response.json()["candidates"][0]
    assert set(candidate) == {
        "customer_public_id",
        "full_name",
        "display_name",
        "city",
        "country_code",
        "matched_on",
        "confidence",
        "is_archived",
        "is_merged",
        "has_active_identity_link",
        "linkable",
    }
    assert "PLANTED-INTERNAL-NOTE" not in response.text
    assert "4165550177" not in response.text.replace(" ", "")
