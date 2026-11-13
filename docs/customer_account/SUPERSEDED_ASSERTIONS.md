# Superseded assertions

**Status:** a register, and the input to a check that runs.

An assertion written in one phase can become false in a later one for two very different
reasons, and this document exists because they look identical in a diff:

* the later phase **implemented something the earlier phase deliberately had not**, so the
  old assertion was describing an absence that was always meant to end; or
* somebody **weakened a guard** to make a new test pass.

The first is legitimate and needs a record. The second is the failure this register is
built to make expensive. So an assertion may only change when it has an entry here naming
the decision that authorised it, and `backend/tests/test_superseded_assertions.py` fails
the build if a registered test has gone missing, if an entry is incomplete, or if a test
claims a supersession that this file does not record.

Nothing here restores an assertion that contradicts approved behaviour. An entry is a
record of *why* an assertion stopped being true, never a licence to bring it back.

---

## The register

### AS-01 — `test_head_is_the_phase_9_revision`

* **File:** `backend/tests/test_migrations_phase9.py`
* **Now named:** `test_this_revision_follows_the_role_merge_and_is_reachable`
* **Original assertion.** Upgrade to `head`; assert the resulting `alembic_version` is
  `b1047733d0e9`, the Phase 9 revision.
* **Why it became false.** Phase 10 added `6af30fcdd3a8`, so `head` is no longer Phase 9.
  Read literally, the original was asserting *that no migration after Phase 9 may exist* —
  a claim no phase can make on behalf of the ones that follow it.
* **Replacement assertion.** Upgrade to `PHASE_9_REVISION` explicitly; assert the version
  lands on it, **and** that the revision file declares `down_revision` as the role-merge
  revision. It now checks what this migration is and what it sits on.
* **Guarantee still protected.** That the Phase 9 migration is reachable from the role
  merge in one hop and produces exactly the Phase 9 schema version. The chain is still
  pinned; only the claim about the future was dropped.
* **Authorised by:** DEC-0100.

### AS-02 — `test_pre_existing_tables_keep_their_shape`

* **File:** `backend/tests/test_migrations_phase9.py`
* **Name unchanged.**
* **Original assertion.** Build a Phase 8 database, upgrade to `head`, and assert every
  pre-existing table's schema fingerprint is byte-identical afterwards.
* **Why it became false.** Same defect as AS-01 and the same shape: upgrading to `head`
  made it assert that *no migration after Phase 7 ever alters an established table*.
  Phase 10 alters one on purpose, adding `legal_name` and `display_name` to `customers`.
* **Replacement assertion.** Upgrade to `PHASE_9_REVISION` instead of `head`. The Phase 9
  migration still adds no column to any established table, which is what this test was
  always about.
* **Guarantee still protected.** Phase 9 is additive-only with respect to the tables that
  preceded it. The broader guarantee — that every column ever added to an established
  table is named and accounted for — did not disappear; it lives in
  `backend/tests/test_migrations_phase4a.py::INTENTIONAL_COLUMN_ADDITIONS`, which now
  names the two new `customers` columns, so adding a third silently still fails.
* **Authorised by:** DEC-0101.

### AS-03 — `test_the_three_deferred_canonical_columns_were_not_added`

* **File:** `backend/tests/test_account_no_canonical_write.py`
* **Now named:** `test_the_three_deferred_canonical_columns_landed_in_phase_10`
* **Original assertion.** `customers` has no `display_name` and no `legal_name`, and
  `AddressRole` has exactly three members.
* **Why it became false.** The assertion held the owner's Phase 9 instruction as a schema
  fact, and that instruction's stated reason was that nothing in Phase 9 could *apply* a
  proposal — so a column added then would have been a column with no writer. Phase 10
  applies one. `FIELD_MATRIX.md` section 6 always expected the three gaps to be decided in
  the phase that first did.
* **Replacement assertion.** Both columns exist, both are nullable, neither carries a
  default or a server default, `AddressRole` has a fourth member `billing`, `full_name`
  is still non-nullable, and there is still **no** `is_billing` boolean on
  `customer_addresses`.
* **Guarantee still protected.** That canonical shape changes are deliberate and bounded.
  The test asserts the *shape* of the resolution as strictly as it once asserted the
  deferral — a billing address is a role, not a flag on a sender row.
* **Authorised by:** DEC-0101.

### AS-04 — `test_the_deferred_values_are_carried_as_proposal_fields_instead`

* **File:** `backend/tests/test_account_no_canonical_write.py`
* **Now named:** `test_the_submitted_values_are_still_carried_as_proposal_fields`
* **Original assertion.** Registration writes the deferred values as proposal fields and
  writes no `customers` row.
* **Why it became false.** It did not. This is the entry that records a **rename without a
  weakening**: the body of the assertion is unchanged, because the columns existing does
  not change where registration puts a value. Only the name needed to change, since
  "instead" referred to a deferral that had ended.
* **Replacement assertion.** Identical, under a name that no longer implies the columns are
  absent.
* **Guarantee still protected.** All of it. Registration still reaches no canonical table;
  only an approval does (DEC-0092).
* **Authorised by:** DEC-0101.

### AS-05 — `test_merging_a_linked_customer_leaves_the_link_pointing_at_the_merged_record`

* **File:** `backend/tests/test_account_activation_invariant.py`
* **Now named:** `test_merging_a_linked_customer_is_refused_outright`
* **Original assertion.** Merging a customer that holds an active identity link leaves the
  link active and pointing at the tombstoned record; every shipment has moved to the
  survivor, so the account would see nothing.
* **Why it became false.** The original recorded a discovered limitation and argued it was
  safe to leave open, on the grounds that the unhandled case **denies** rather than
  discloses. That argument was correct about the direction it considered — a link left on
  a merged *source* — and it explicitly declined to settle the question, calling it an
  owner question rather than something to decide inside an approval phase. OD-40 is the
  owner answering it. The argument also did not cover the other direction: merging *into*
  a customer an identity is already linked to grows that account's history by everything
  the source owned, with nothing previewed and nothing acknowledged, which is a disclosure.
  And "an active link points at a tombstone" is a state the sweep in that same module
  exists to forbid.
* **Replacement assertion.** `customer_service.merge_customers` raises
  `LinkedCustomerMergeRefused` with `blocked_side = source`; the link stays active, the
  source is **not** tombstoned, and the whole-database sweep passes.
* **Guarantee still protected.** That an account never reaches shipment data it was not
  explicitly linked to and never gains scope nobody acknowledged. It is now protected by a
  merge that does not happen at all, which is strictly stronger than protection by the
  merge happening to move the data out of reach.
* **Authorised by:** OD-40, DEC-0107.

### AS-06 — `test_there_is_no_reference_search`

* **File:** `backend/tests/test_account_shipment_filters.py`
* **Now named:** `test_the_reference_filter_is_exact_and_unknown_parameters_are_ignored`
  (renamed again by AS-08)
* **Original assertion.** No parameter named `q`, `search`, `reference` or
  `shipment_reference` changes the list: every one of them is ignored, so the list returns
  the caller's whole page whatever is passed.
* **Why it became false.** OD-41, issued with the Phase 12 instruction, approves an
  **exact** Solaris shipment-reference filter on this list. The original assertion was
  describing the absence `SHIPMENT_ALLOWLISTS.md` §3.2 required at the time, and §3.2 has
  been amended (§3.3) before the code changed. The original was right to be written: it is
  why the addition had to be an owner decision rather than a convenience.
* **Replacement assertion.** `reference` filters **exactly** — the whole reference returns
  the row, a prefix returns nothing, an unknown one returns an empty list, and another
  customer's returns the same empty list; `q`, `search` and `shipment_reference` are still
  ignored, so free-text search is still absent.
* **Guarantee still protected.** That this surface answers no question about a shipment the
  caller does not own, and that it cannot be asked a partial-match question. The filter is
  applied after the ownership clause, so a foreign reference narrows the caller's own rows
  to none rather than reaching anybody else's, and the empty result is byte-identical to the
  unknown-reference one.
* **Authorised by:** OD-41, DEC-0114.

### AS-07 — `test_there_is_no_route_filter`

* **File:** `backend/tests/test_account_shipment_filters.py`
* **Now named:** `test_the_route_group_filter_accepts_only_the_vocabulary`
* **Original assertion.** A `route_group` parameter is ignored: passing one returns every
  qualifying shipment regardless of its route.
* **Why it became false.** OD-41 approves an exact route-group filter over the existing
  validated vocabulary. As with AS-06, the requirement document was amended first.
* **Replacement assertion.** A valid `route_group` narrows to that route; an invalid one is
  refused with this surface's own `{code, message, field}` validation body and not FastAPI's;
  the value cannot carry SQL; and the filter is still scoped by the effective linked
  customer, so `total` never crosses a customer boundary.
* **Guarantee still protected.** That no caller-supplied string reaches SQL and that
  filtering cannot widen a result set. The vocabulary is closed, membership is checked
  before the query is built, and the ownership clause is still first.
* **Authorised by:** OD-41, DEC-0114.

### AS-08 — `test_the_reference_filter_is_exact_and_free_text_is_still_absent`

* **File:** `backend/tests/test_account_shipment_filters.py`
* **Now named:** `test_the_reference_filter_is_exact_and_unknown_parameters_are_ignored`
* **Original assertion.** AS-06's replacement: `reference` filters exactly, **and** `q`,
  `search` and `shipment_reference` are ignored, so free-text search is still absent from
  the Customer Account shipment list.
* **Why it became false.** The owner's UAT round 10 instruction (2026-10-18) replaces the
  list's "Solaris Shipment ID" box with a keyword search: partial, case-insensitive, over
  the Solaris Shipment ID, the booking reference and the origin and destination cities.
  It is the `q` parameter. `SHIPMENT_ALLOWLISTS.md` §3.2 was amended (§3.4) in the same
  change.
* **Replacement assertion.** `reference` is still exact (whole reference matches, a prefix
  matches nothing); `search` and `shipment_reference` are still ignored. The keyword search
  is asserted in `backend/tests/test_account_shipment_search.py`: partial and
  case-insensitive on the four columns, nothing else searched (recipient, address, phone,
  email, carrier number, package reference, contents, notes), wildcards literal, bounded at
  64 characters with this surface's own 422 body, never logged, and another customer's
  shipment is never returned and never counted.
* **Guarantee still protected.** That this surface answers no question about a shipment
  the caller does not own. The keyword is applied after the ownership clause, so a match on
  somebody else's shipment ID, booking reference or city narrows the caller's own rows to
  none, byte-identical to a keyword that matches nothing anywhere. No caller-supplied
  string reaches SQL as SQL: the pattern is a bound parameter and the searched columns are
  a fixed tuple.
* **Authorised by:** DEC-0156.

### AS-09 — `test_the_postal_part_is_a_zip_code_for_the_united_states`

* **File:** `backend/tests/test_uat_round_9.py`
* **Now named:** `test_a_united_states_address_without_a_zip_code_is_accepted`
* **Original assertion.** A registration whose United States address has no postal code is
  refused, 422, field `pickup_address.1.postal_code`, "Enter the ZIP code." (the postal
  code was the fifth required address part, DEC-0151).
* **Why it became false.** The owner's UAT round 11 decision (2026-10-18) makes the postal
  code optional for the address and for billing, in every country (DEC-0159).
* **Replacement assertion.** The same registration is accepted and an identity is created.
  `test_uat_round_11.py` asserts the rest: absent or blank, for Canada, Vietnam and the
  United States, on the address and on an unticked billing address, nothing is stored for
  it; a typed one is kept as typed; over 30 characters is still refused by name; the other
  four parts are still required.
* **Guarantee still protected.** That registration refuses an address missing a part the
  owner requires (country, line 1, city, province or state), by name and before anything
  is written, and that no field exceeds its allowlisted bound.
* **Authorised by:** DEC-0159.

### AS-10 — `test_part_of_a_booking_reference_matches_without_publishing_it`

* **File:** `backend/tests/test_account_shipment_search.py`
* **Now named:** `test_part_of_a_booking_reference_matches_and_is_shown_on_the_row`
* **Original assertion.** Part of a booking reference finds its shipment, **and** the
  booking reference is not in the response text.
* **Why it became false.** The owner's UAT round 11 decision (2026-10-18) adds the booking
  reference to the list row (DEC-0160), so a shipment found by it says why.
* **Replacement assertion.** Part of a booking reference finds exactly its shipment, the
  matching row's `booking_reference` is that value as entered, and the other shipment's
  booking reference is not in the response.
* **Guarantee still protected.** That the search, and the field, only ever describe the
  caller's own rows: another customer's booking reference is neither matched nor shown
  (`test_another_customers_shipments_are_never_returned_or_counted`,
  `test_uat_round_11.py::test_another_customers_booking_reference_is_never_listed`).
* **Authorised by:** DEC-0160.

### AS-11 — `test_a_package_reference_does_not_match_its_shipment`

* **File:** `backend/tests/test_account_shipment_search.py`
* **Now named:** `test_a_package_reference_finds_its_shipment`
* **Original assertion.** Searching a whole package reference (`<shipment id>-01`) returns
  an empty list: package references were not searched (DEC-0156 item 2).
* **Why it became false.** The owner's UAT round 11 decision (2026-10-18): a package
  reference finds its shipment, still limited to the customer's own shipments (DEC-0161).
* **Replacement assertion.** Each package reference, in any case and with spaces around it,
  returns exactly its shipment, once; a shipment with two matching packages is one row; a
  package reference that does not exist returns nothing. Further tests beside it: a
  cancelled package counts, wildcards in a package keyword are literal, and another
  customer's package references return the same empty page as no match.
* **Guarantee still protected.** That the search only narrows the caller's own rows. The
  package clause is an `EXISTS` correlated on the shipment's own id, inside the keyword
  clause, after the ownership clause; a stranger's package reference, even one shaped like
  one of the caller's, finds nothing and is counted nowhere.
* **Authorised by:** DEC-0161.

### AS-12 — `test_the_list_item_has_exactly_the_seventeen_approved_fields`

* **File:** `backend/tests/test_account_shipment_contract.py`
* **Now named:** `test_the_list_item_has_exactly_the_eighteen_approved_fields`
* **Original assertion.** `AccountShipmentListItem` has exactly the seventeen fields of the
  frozen `LIST_FIELDS`.
* **Why it became false.** DEC-0160 adds `booking_reference` to the list allowlist
  (`SHIPMENT_ALLOWLISTS.md` §3, amended first).
* **Replacement assertion.** Exactly the eighteen fields of the frozen `LIST_FIELDS`,
  which now names `booking_reference`, and `booking_reference` is not in the detail's
  frozen list.
* **Guarantee still protected.** That the list's fields are a reviewed, frozen list
  asserted by name, so nothing else is added without a diff to this test; the detail stays
  at 24 and Public Tracking at 24, each asserted by its own unchanged test.
* **Authorised by:** DEC-0160.

### AS-13 — `test_no_forbidden_key_appears_anywhere_in_either_response`

* **File:** `backend/tests/test_account_shipment_privacy.py`
* **Original assertion.** No key in `FORBIDDEN_KEYS`, `booking_reference` among them,
  appears at any depth in the list response or the detail response.
* **Why it became false.** DEC-0160 publishes `booking_reference` on the list row.
* **Replacement assertion.** The list response carries no forbidden key except
  `booking_reference` (`LIST_ONLY_KEYS`), and carries that one as a top-level key of each
  row; the detail response carries no forbidden key at all, `booking_reference` included.
* **Guarantee still protected.** Every other excluded key (row ids, idempotency key,
  source system and record, recipient and sender details, money, staff and audit fields)
  is still absent from both responses at every depth, and the exception cannot spread to
  the detail.
* **Authorised by:** DEC-0160.

### AS-14 — `test_no_planted_private_value_reaches_either_response`

* **File:** `backend/tests/test_account_shipment_privacy.py`
* **Original assertion.** No planted sentinel, the booking reference's among them, appears
  in the text of the list or the detail response.
* **Why it became false.** DEC-0160 publishes `booking_reference` on the list row.
* **Replacement assertion.** Every other sentinel is absent from both responses; the
  booking reference's sentinel appears in the list exactly once, as that row's
  `booking_reference`, and not at all in the detail.
* **Guarantee still protected.** That no excluded value reaches either response by any
  route (a summary string, a location, a label), checked against a fully populated record.
* **Authorised by:** DEC-0160.

### AS-15 — `test_every_list_field_carries_the_value_its_source_column_holds`

* **File:** `backend/tests/test_account_shipment_list.py`
* **Original assertion.** One fully populated row: each of the seventeen list fields holds
  its source column's value, and the row's keys are exactly those seventeen.
* **Why it became false.** DEC-0160 adds `booking_reference` to the list row.
* **Replacement assertion.** The same seventeen checks, plus `booking_reference` holding
  the column's value trimmed, and the row's keys are exactly those eighteen.
* **Guarantee still protected.** That every list field comes from the column the allowlist
  names, and that a row carries no key the allowlist does not list.
* **Authorised by:** DEC-0160.

### AS-16 — `test_an_active_account_reaches_its_shipments_and_nothing_planted_comes_with_them`

* **File:** `backend/tests/test_account_review_privacy.py`
* **Original assertion.** After approval, neither the customer's shipment list nor the
  detail contains any value planted on the linked customer and shipment, the planted
  booking reference among them.
* **Why it became false.** DEC-0160 publishes `booking_reference` on the list row.
* **Replacement assertion.** The list row's `booking_reference` is the planted value and
  the list contains no other planted value; the detail and the profile contain none.
* **Guarantee still protected.** That approval exposes nothing else of the linked record:
  customer notes, service restriction, source record, recipient name and email, internal
  notes, contents and money stay out of every customer response.
* **Authorised by:** DEC-0160.

### AS-17 — `test_a_typed_postal_code_is_kept_in_any_format`

* **File:** `backend/tests/test_uat_round_11.py`
* **Now named:** `test_a_typed_postal_code_is_kept_as_typed`
* **Original assertion.** A typed postal code is accepted and kept exactly as typed in any
  format, including "Not a real code" for a Canadian address.
* **Why it became false.** The owner's UAT round 12 decision (2026-10-19) adds a lenient
  shape check for Canada and the United States (DEC-0165).
* **Replacement assertion.** A Canadian code of the right shape in either case, with or
  without the space, a United States ZIP+4, and any Vietnamese code (including "Not a real
  code") are accepted and kept as typed, for the address and the copied billing address.
  `test_uat_round_12.py` asserts the refusals, by name and with the sentence, for the
  address and an unticked billing address.
* **Guarantee still protected.** That a blank postal code is never refused (DEC-0159), that
  what is kept is what was typed, and that the 30-character bound still applies.
* **Authorised by:** DEC-0165.

### AS-18 — `test_the_api_still_defaults_the_billing_box_to_unticked`

* **File:** `backend/tests/test_uat_round_11.py`
* **Now named:** `test_the_api_defaults_the_billing_box_to_ticked`
* **Original assertion.** `RegistrationRequest.billing_same_as_shipping` defaults to false,
  and a body that omits it and sends no billing address is refused, field
  `billing_address.country_code`.
* **Why it became false.** The owner's UAT round 12 decision (2026-10-19) makes the API
  default to true, as the form does (DEC-0166).
* **Replacement assertion.** The default is true, and the same body is accepted with the
  address copied into billing. `test_uat_round_12.py` asserts that omitting the flag while
  sending billing keys is refused with the conflict sentence, and that an explicit false
  still takes a separate billing address.
* **Guarantee still protected.** That the server never silently prefers one of two
  addresses: a billing address sent with a "same" flag, explicit or defaulted, is refused
  by name, and an unticked billing address still needs its four required parts.
* **Authorised by:** DEC-0166.

### AS-19 — `test_the_detail_still_has_no_booking_reference`

* **File:** `backend/tests/test_uat_round_11.py`
* **Now named:** `test_the_detail_carries_the_same_booking_reference_as_the_row`
* **Original assertion.** The detail response has no `booking_reference` key and its text
  does not contain the shipment's booking reference.
* **Why it became false.** The owner's UAT round 12 decision (2026-10-19) shows the booking
  reference on the shipment detail too (DEC-0163).
* **Replacement assertion.** The detail's `booking_reference` is the column's value trimmed,
  and equals the list row's. `test_uat_round_12.py` adds null for absent and blank, a
  cancelled shipment, and another customer's shipment (404, no value).
* **Guarantee still protected.** That the value is only ever read from the caller's own
  shipment, after the ownership check, and that Public Tracking never carries it.
* **Authorised by:** DEC-0163.

### AS-20 — `test_the_list_item_has_exactly_the_eighteen_approved_fields`

* **File:** `backend/tests/test_account_shipment_contract.py`
* **Original assertion.** As AS-12, plus `booking_reference` is **not** in the detail's
  frozen `DETAIL_FIELDS`.
* **Why it became false.** DEC-0163 adds `booking_reference` to the detail.
* **Replacement assertion.** The list's eighteen fields, unchanged; `booking_reference` is
  in `DETAIL_FIELDS` and is not a field of `PublicTrackingResult`.
* **Guarantee still protected.** That the list's fields are a frozen list asserted by name,
  and that the booking reference never reaches the public contract.
* **Authorised by:** DEC-0163.

### AS-21 — `test_the_detail_has_exactly_the_twenty_four_approved_fields`

* **File:** `backend/tests/test_account_shipment_contract.py`
* **Now named:** `test_the_detail_has_exactly_the_twenty_six_approved_fields`
  (renamed again by AS-27)
* **Original assertion.** `AccountShipmentDetail` has exactly the twenty-four fields of the
  frozen `DETAIL_FIELDS`.
* **Why it became false.** DEC-0163 adds `booking_reference` (`SHIPMENT_ALLOWLISTS.md` §4,
  amended first).
* **Replacement assertion.** Exactly the twenty-five fields of the frozen `DETAIL_FIELDS`,
  which now names `booking_reference`.
* **Guarantee still protected.** That the detail's fields are a reviewed, frozen list
  asserted by name; Public Tracking stays at 24, asserted beside it and by its own
  unchanged test.
* **Authorised by:** DEC-0163.

### AS-22 — `test_the_two_detail_schemas_have_the_same_names_today_and_are_not_the_same_class`

* **File:** `backend/tests/test_account_shipment_contract.py`
* **Now named:** `test_the_detail_is_the_public_names_plus_the_booking_reference_and_not_the_same_class`
* **Original assertion.** `AccountShipmentDetail` and `PublicTrackingResult` have exactly the
  same field names, and are different classes.
* **Why it became false.** DEC-0163 adds one field to the authenticated detail only.
* **Replacement assertion.** The detail's names are exactly the public names plus
  `booking_reference`, and the two are different classes.
* **Guarantee still protected.** That the two schemas differ by exactly one reviewed field
  and nothing else, and remain unrelated classes (the non-subclassing tests are unchanged).
* **Authorised by:** DEC-0163.

### AS-23 — `test_every_detail_field_carries_the_value_its_source_holds`

* **File:** `backend/tests/test_account_shipment_detail.py`
* **Original assertion.** One fully populated shipment: each detail field holds its source's
  value, and the body has exactly twenty-four keys.
* **Why it became false.** DEC-0163 adds `booking_reference` to the detail.
* **Replacement assertion.** The same checks, plus `booking_reference` holding the column's
  value trimmed, and the body has exactly twenty-five keys.
* **Guarantee still protected.** That every detail field comes from the source the
  allowlist names, and that the body carries no key the allowlist does not list.
* **Authorised by:** DEC-0163.

### AS-24 — `test_no_forbidden_key_appears_anywhere_in_either_response`

* **File:** `backend/tests/test_account_shipment_privacy.py`
* **Original assertion.** As replaced by AS-13: no forbidden key in the list except
  `booking_reference` as a top-level key of each row, and no forbidden key at all, at any
  depth, in the detail.
* **Why it became false.** DEC-0163 publishes `booking_reference` on the detail.
* **Replacement assertion.** Neither response carries any forbidden key other than
  `booking_reference`, at any depth; that one is a top-level key of each list row and of
  the detail, and appears nowhere deeper in either (not in a package, a timeline entry or
  a place). The scanner self-test beside it uses the same set.
* **Guarantee still protected.** Every other excluded key (row ids, idempotency key, source
  system and record, recipient and sender details, money, staff and audit fields) is still
  absent from both responses at every depth.
* **Authorised by:** DEC-0163.

### AS-25 — `test_no_planted_private_value_reaches_either_response`

* **File:** `backend/tests/test_account_shipment_privacy.py`
* **Original assertion.** As replaced by AS-14: every sentinel but the booking reference's
  absent from both responses; that one in the list exactly once, and not in the detail.
* **Why it became false.** DEC-0163 publishes `booking_reference` on the detail.
* **Replacement assertion.** Every other sentinel is absent from both responses; the booking
  reference's sentinel appears exactly once in the list, as the row's field, and exactly
  once in the detail, as its field.
* **Guarantee still protected.** That no other excluded value reaches either response by
  any route, checked against a fully populated record.
* **Authorised by:** DEC-0163.

### AS-26 — `test_an_active_account_reaches_its_shipments_and_nothing_planted_comes_with_them`

* **File:** `backend/tests/test_account_review_privacy.py`
* **Original assertion.** As replaced by AS-16: the list row carries the planted booking
  reference and no other planted value; the detail and the profile carry none.
* **Why it became false.** DEC-0163 publishes `booking_reference` on the detail.
* **Replacement assertion.** The list row and the detail each carry the planted booking
  reference in their own field and no other planted value; the profile carries none.
* **Guarantee still protected.** That approval exposes nothing else of the linked record:
  customer notes, service restriction, source record, recipient name and email, internal
  notes, contents and money stay out of every customer response.
* **Authorised by:** DEC-0163.

### AS-27 — `test_the_detail_has_exactly_the_twenty_five_approved_fields`

* **File:** `backend/tests/test_account_shipment_contract.py`
* **Now named:** `test_the_detail_has_exactly_the_twenty_six_approved_fields`
* **Original assertion.** As replaced by AS-21: `AccountShipmentDetail` has exactly the
  twenty-five fields of the frozen `DETAIL_FIELDS`.
* **Why it became false.** The owner's answers of 2026-10-22 show both tracking legs to the
  customer under generic names (Master Tracking, Last Mile Tracking), so the detail gains
  `carrier_links`: every safe link, at most one per generic name, in leg order;
  `carrier_link` stays as the first of them (DEC-0224 item 1, "Both legs").
* **Replacement assertion.** Exactly the twenty-six fields of the frozen `DETAIL_FIELDS`,
  which now names `carrier_links`.
* **Guarantee still protected.** That the detail's fields are an exact allow-list asserted by
  name, so nothing else is added without a diff to this test. Each entry of `carrier_links`
  is the same `AccountCarrierLink` as `carrier_link` (generic name, `tracking_name_key`,
  URL; no tracking-number field), and the detail is still exactly the public names plus
  `booking_reference` (AS-22's test, unchanged by this pack).
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-28 — `test_public_tracking_is_still_exactly_twenty_four_fields`

* **File:** `backend/tests/test_account_shipment_contract.py`
* **Now named:** `test_public_tracking_is_exactly_twenty_five_fields`
* **Original assertion.** `PublicTrackingResult` has exactly twenty-four fields: OD-31's
  other half, restated from the Customer Account's side, so the account contract cannot
  widen the public one.
* **Why it became false.** DEC-0224 adds `carrier_links` to the public contract as well
  (both legs shown on public tracking), owner answers of 2026-10-22.
* **Replacement assertion.** `PublicTrackingResult` has exactly twenty-five fields.
* **Guarantee still protected.** That the public contract changes only by a recorded
  decision: the count is still pinned here and the names are pinned by
  `test_public_contract_unchanged.py` (AS-33). `booking_reference` is still not a public
  field (AS-20's test, unchanged).
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-29 — `test_every_detail_field_carries_the_value_its_source_holds`

* **File:** `backend/tests/test_account_shipment_detail.py`
* **Name unchanged.**
* **Original assertion.** As replaced by AS-23: one fully populated shipment, each detail
  field holds its source's value, and the body has exactly twenty-five keys.
* **Why it became false.** DEC-0224 adds `carrier_links` to the detail.
* **Replacement assertion.** The same checks, and the body has exactly twenty-six keys.
* **Guarantee still protected.** That the response body carries no key the allow-list does
  not list. The values of `carrier_links` are asserted in
  `test_owner_answers_2026_10_22.py::test_the_account_shows_both_tracking_links`
  (generic names only, one per leg).
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-30 — `test_the_public_tracking_schemas_are_untouched`

* **File:** `backend/tests/test_account_boundary.py`
* **Name unchanged.**
* **Original assertion.** `PublicTrackingResult` has exactly twenty-four fields and does not
  read from ORM attributes (`from_attributes` is false).
* **Why it became false.** DEC-0224 adds `carrier_links` to the public contract.
* **Replacement assertion.** Exactly twenty-five fields; `from_attributes` still false.
* **Guarantee still protected.** That the Customer Account does not move the public
  contract: the account declares its own classes, and the public model is still built
  field by field, never from a database row.
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-31 — `test_the_public_contract_is_still_exactly_24_fields`

* **File:** `backend/tests/test_account_privacy.py`
* **Name unchanged.** The name keeps the historical count; the docstring records it.
* **Original assertion.** `PublicTrackingResult` has exactly twenty-four fields, repeated in
  the account privacy suite so a Customer Account change trips it too.
* **Why it became false.** DEC-0224 adds `carrier_links` to the public contract.
* **Replacement assertion.** Exactly twenty-five fields.
* **Guarantee still protected.** That a change made for the Customer Account cannot widen
  the public contract unnoticed: the count is still pinned in this suite as well as in the
  public one.
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-32 — `test_the_timeline_names_each_published_step_and_hides_internal_notes`

* **File:** `backend/tests/test_phase15_golden.py`
* **Name unchanged.**
* **Original assertion.** Among its checks, the public body's keys are a subset of
  `PublicTrackingResult`'s fields and that model has exactly twenty-four fields.
* **Why it became false.** DEC-0224 adds `carrier_links` to the public contract.
* **Replacement assertion.** The same subset check, and exactly twenty-five fields; the
  timeline checks (no `event_type`, internal notes hidden) are unchanged.
* **Guarantee still protected.** That the golden public body carries only allow-listed
  keys and the timeline never shows an internal note.
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-33 — `test_the_public_result_model_gained_no_field`

* **File:** `backend/tests/test_public_contract_unchanged.py`
* **Name unchanged.**
* **Original assertion.** `set(PublicTrackingResult.model_fields)` equals the published
  allow-list of twenty-four names, `carrier_link` among them and no `carrier_links`.
* **Why it became false.** DEC-0224 adds `carrier_links` (at most one link per generic
  tracking name, in leg order).
* **Replacement assertion.** The same exact set plus `carrier_links`.
* **Guarantee still protected.** That the public fields are an exact allow-list asserted by
  name: any other addition still fails. Each `carrier_links` entry is a `PublicCarrierLink`,
  the same class as `carrier_link`, with no tracking-number field.
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-34 — `test_the_payload_contains_exactly_the_documented_allowlist`

* **File:** `backend/tests/test_public_privacy.py`
* **Name unchanged.**
* **Original assertion.** The public tracking response's top-level keys are exactly the
  documented twenty-four, with the origin, package and timeline keys each an exact set.
* **Why it became false.** DEC-0224 adds `carrier_links` to the public response.
* **Replacement assertion.** The same exact top-level set plus `carrier_links`; the origin,
  package and timeline key sets are unchanged.
* **Guarantee still protected.** That the live payload, not only the model, is an exact
  allow-list at every level asserted here.
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-35 — `test_the_carrier_tracking_number_appears_only_inside_the_approved_link`

* **File:** `backend/tests/test_public_privacy.py`
* **Name unchanged.**
* **Original assertion.** The public `carrier_link` has exactly the keys `carrier_name` and
  `url`; the carrier tracking number is inside the URL; and it appears nowhere in the body
  outside `carrier_link`.
* **Why it became false.** OD-92 and DEC-0224 replace the carrier's name with the leg's
  generic name and add `tracking_name_key` (`master_tracking` | `last_mile_tracking`) so
  the page can render it in the reader's language; DEC-0224 also adds `carrier_links`,
  whose entries carry the same URLs.
* **Replacement assertion.** The link's keys are exactly `carrier_name`, `tracking_name_key`
  and `url`; the number is inside the URL; and it appears nowhere in the body outside
  `carrier_link` and `carrier_links`.
* **Guarantee still protected.** That the carrier tracking number is never a field of its
  own: it is still only inside the carrier's URL, and the link key set is still exact (the
  added key is a fixed two-value vocabulary, not shipment data). `carrier_links` entries
  are the same `PublicCarrierLink` class. The stored carrier or vendor label never reaches
  the customer (`test_customer_labels.py::test_no_customer_facing_output_names_a_vendor`,
  DEC-0224 item 2), and a link whose host names a vendor stays hidden (item 3).
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-36 — `test_the_public_result_model_still_has_exactly_twenty_four_fields`

* **File:** `backend/tests/test_phase5b_seam_and_contracts.py`
* **Now named:** `test_the_public_result_model_still_has_exactly_twenty_five_fields`
* **Original assertion.** `PublicTrackingResult` has exactly 24 fields.
* **Why it became false.** DEC-0224 adds `carrier_links` (at most one carrier link per generic
  tracking name) so both "Master Tracking" and "Last Mile Tracking" links can reach the
  customer (OD-91, OD-92).
* **Replacement assertion.** Exactly 25 fields, and `carrier_links` is among them.
* **Guarantee still protected.** That the public result's size is pinned, so any further field
  fails this test; the field-by-field allow-list is asserted by AS-27 to AS-35.
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-37 — `test_public_tracking_still_has_no_booking_reference`

* **File:** `backend/tests/test_uat_round_12.py`
* **Name unchanged.**
* **Original assertion.** `booking_reference` is not a public field, and the public result has
  exactly 24 fields.
* **Why it became false.** DEC-0224 adds `carrier_links` (OD-91, OD-92).
* **Replacement assertion.** `booking_reference` is still not a public field; exactly 25
  fields, and `carrier_links` is among them.
* **Guarantee still protected.** That the booking reference never reaches public tracking
  (DEC-0163 widens only the authenticated detail), and that the public size stays pinned.
* **Authorised by:** OD-91, OD-92, DEC-0224.

### AS-38 — `test_the_customer_quote_wording_is_kept`

* **File:** `backend/tests/test_rc20_tax_by_route.py`
* **Now named:** `test_the_customer_quote_wording_follows_the_invoice_rule`
* **Original assertion.** The Customer Account quote keeps "Tổng cộng" and prints the note
  "Thuế, nếu có, sẽ được tính trên hóa đơn." / "Taxes, if any, are added on the invoice." when
  `tax_included` is false; the staff note label stays "Ghi chú từ Solaris Express".
* **Why it became false.** RC-UAT-21 P-9 stand-in (owner direction 2026-10-24, pending Ben;
  drafted as decision 0232 in `docs/b2c_merge/_drafts/rc21_B.md`): the quote's tax wording
  follows the RC-UAT-20 invoice rule -- domestic "Giá đã bao gồm HST 13 %" at the destination
  province's rate, international "Thuế suất 0 (0 %)" -- replacing OD-108's note.
* **Replacement assertion.** "Tổng cộng" and the staff note label are unchanged; the account
  i18n carries `quotes.taxIncluded` ("Giá đã bao gồm {label} {rate} %" / "Prices include
  {label} {rate} %") and `quotes.taxZeroRated` ("Thuế suất 0 (0 %)" / "Zero-rated (0 %)"), and
  the quote page prints `quoteTaxSentence(t, data.tax)`.
* **Guarantee still protected.** The customer-facing total label and staff note label stay
  pinned; the wording is pinned to the invoice's (`finance_service.TAX_INCLUDED_NOTE`,
  `ZERO_RATED_LABEL`) by `tests/test_rc21_quote_tax_wording.py`; amounts are unchanged.
* **Authorised by:** OD-108 (note superseded by the P-9 stand-in, pending Ben), DEC-0227.

### AS-39 — `test_customer_quote_and_staff_note_wording_kept`

* **File:** `backend/tests/test_rc20_golden.py`
* **Now named:** `test_customer_quote_tax_wording_and_staff_note`
* **Original assertion.** The account i18n holds the OD-108 tax note and the quote page shows
  `t('quotes.taxNote')` unless `data.tax_included`.
* **Why it became false.** The same P-9 stand-in as AS-38.
* **Replacement assertion.** "Tổng cộng" and the staff note label are unchanged; the page
  shows `quoteTaxSentence(t, data.tax)` and the i18n holds `quotes.taxIncluded`.
* **Guarantee still protected.** As AS-38.
* **Authorised by:** OD-108 (note superseded by the P-9 stand-in, pending Ben), DEC-0227.

### AS-40 — `test_happy_path_totals_match_the_finalised_quote_and_are_customer_safe`

* **File:** `backend/tests/test_quote_offers_golden.py`
* **Name unchanged.**
* **Original assertion.** The Customer Account quote detail has exactly sixteen fields.
* **Why it became false.** The P-9 stand-in adds `tax` (`band`, `label`, `rate_percent`) so
  the screen can print the invoice rule's GST/HST sentence.
* **Replacement assertion.** Exactly seventeen fields, `tax` among them; every figure and the
  customer-safety checks unchanged.
* **Guarantee still protected.** The detail's field set stays pinned, so any further field
  fails; `tax` carries a band, a tax label and a whole percent -- no cost, margin or vendor.
* **Authorised by:** OD-108 (note superseded by the P-9 stand-in, pending Ben), DEC-0227.

### AS-41 — `test_quote_document_is_revenue_only_with_company_details`

* **File:** `backend/tests/test_phase14_staff_screens.py`
* **Name unchanged.**
* **Original assertion.** The printable quote document has exactly its Phase 14 field set.
* **Why it became false.** The P-9 stand-in adds `tax` to the printed quote, as on the
  account's quote.
* **Replacement assertion.** The same set plus `tax`; revenue-only and no cost word in any key.
* **Guarantee still protected.** The document stays an exact allowlist with no cost, exchange
  rate, markup, margin or vendor field.
* **Authorised by:** OD-108 (note superseded by the P-9 stand-in, pending Ben), DEC-0227.

### AS-42 — `test_the_account_routes_are_the_twenty_one_built_so_far`

* **File:** `backend/tests/test_account_boundary.py`
* **Now named:** `test_the_account_routes_are_the_twenty_six_built_so_far`
* **Original assertion.** The Customer Account mounts exactly twenty-one routes, listed by
  method and path.
* **Why it became false.** RC-UAT-21 Phase B (owner direction 2026-10-24; drafted as decision
  0231 in `docs/b2c_merge/_drafts/rc21_B.md`) adds five: `GET /security`,
  `POST /password/change`, `POST /email/change`, `POST /email/change/cancel` and
  `POST /email/change/confirm`.
* **Replacement assertion.** Exactly twenty-six routes, the five new ones among them, every
  earlier one unchanged.
* **Guarantee still protected.** The route table stays pinned, so any further account route
  fails this test; the new routes read and write only the caller's own identity (the
  confirmation only by its single-use, purpose-bound token), are covered for session, CSRF,
  rate limits and enumeration by `tests/test_rc21_account_security.py`, and none reads a
  shipment.
* **Authorised by:** OD-36 (the verification period the email-change link uses), DEC-0181.

### AS-43 — `test_quote_document_is_revenue_only_with_company_details`

* **File:** `backend/tests/test_phase14_staff_screens.py`
* **Name unchanged.**
* **Original assertion.** The printable quote names the company as on every invoice (OD-64):
  "Soleil Global Transportation Inc.", BN 795093756RT0001, "2446 Cawthra Road B1U8,
  Mississauga ON L5A 3K6"; the document's field set is AS-41's (Phase 14 plus `tax`).
* **Why it became false.** RC-UAT-23 (owner Ben, 2026-10-24; DEC-0235): invoices follow the
  Solaris Invoicing desk, whose company block is
  "Solaris Express Inc.", "2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6",
  solarisexpressinc@gmail.com, BN 795093756RT0001. `finance_service.COMPANY` carries those
  values and a new `company_email`, and the quote document follows.
* **Replacement assertion.** The new name, address and email, the same business number; the
  same field set plus `company_email`.
* **Guarantee still protected.** The document stays an exact allowlist (any further field
  fails) with no cost, exchange rate, markup, margin or vendor field; the business number is
  unchanged; `company_email` is the company's own published address, not a customer's.
* **Authorised by:** OD-64 (the company details on every customer document, revised by the
  owner on 2026-10-24), DEC-0235.

### AS-44 — `test_email_change_confirmed_by_the_new_address_switches_and_tells_the_old`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_the_customer_cannot_ask_to_change_the_sign_in_email`
* **Original assertion.** A customer's request sends a link to the new address only; the old address stays until the link is used; using it switches the identity and the linked customer, keeps the asking browser signed in, tells the old address, and audits without addresses.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** The request is refused with 403 and the one sentence; nothing is sent; no request row, no token, no audit of a request; the security read shows the old email and no pending change; only the old address signs in.
* **Guarantee still protected.** The account's address cannot be moved by whoever holds a session. Switching, the customer following, the notice to the old address and address-free audit are asserted on the Admin path by `tests/test_rc25_email_admin_only.py::test_admin_changes_the_sign_in_email_and_everything_follows`.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-45 — `test_the_link_works_once`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_an_outstanding_link_no_longer_works`
* **Original assertion.** A confirmation link succeeds once; a second use is 422 with the token sentence.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** A link written before the change (built by `legacy_link`) is refused on its first use and on every later one, with the same token sentence; the address is unchanged.
* **Guarantee still protected.** A link is never usable twice, and the refusal sentence is the generic one. The live link is consumed by the refusal (`test_rc25_email_admin_only.py::test_a_link_sent_before_the_change_no_longer_works`).
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-46 — `test_a_new_request_supersedes_the_old_link_and_cancel_kills_it`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_a_pending_request_is_closed_and_cancel_still_answers`
* **Original assertion.** A second request supersedes the first link; cancel returns no pending change and kills the second link; the rows end `superseded` and `cancelled`.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** A customer cannot make a second request any more; a pending (pre-RC-UAT-25) request is closed by cancel, which still answers 200 with no pending change, and its link is then refused; the row ends `cancelled`.
* **Guarantee still protected.** An open request never keeps a working link once it is closed; the security read also closes it (`test_opening_the_security_page_closes_a_pending_request`).
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-47 — `test_an_address_in_use_gets_the_same_answer_as_success_and_no_message`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_every_customer_request_gets_the_same_refusal_and_no_message`
* **Original assertion.** Free, taken-by-an-account and taken-by-a-record addresses get the same 200 body; only the free one is sent a link; the audit outcomes are sent / in use (identity) / in use (customer).
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** All three get the identical 403 body and headers; nothing is sent to any of them; no request is audited.
* **Guarantee still protected.** No enumeration: the customer surface still says nothing about whether an address is known to Solaris Express (T-02), now because it says the same refusal to everyone.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-48 — `test_the_rule_is_checked_again_when_the_link_is_used`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_the_admin_change_refuses_an_address_held_by_another_account`
* **Original assertion.** An address registered by another account between request and confirmation refuses the link (422, token sentence) and the request ends `refused` / `address_in_use_identity`.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** The Admin's change to an address held by another account is refused (409, a staff-facing sentence naming the reason) and the address is unchanged.
* **Guarantee still protected.** The single email rule: no two accounts share a sign-in email. Staff may be told why; the customer surface never is.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-49 — `test_a_customer_record_taking_the_address_meanwhile_also_refuses`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_the_admin_change_refuses_an_address_held_by_another_customer_record`
* **Original assertion.** A customer record taking the address before confirmation refuses the link.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** The Admin's change to an address held by another customer record is refused (409); the address is unchanged.
* **Guarantee still protected.** The single email rule across accounts and customer records (`address_refusal`).
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-50 — `test_the_unique_index_decides_a_true_race`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_the_unique_index_decides_a_true_race_on_an_admin_change`
* **Original assertion.** With the re-check bypassed, the unique index refuses the confirmation and the request ends `refused` / `address_in_use_identity`.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** With the check bypassed, the unique index refuses the Admin's change (409) inside a savepoint and the address is unchanged.
* **Guarantee still protected.** A race between the check and the write cannot give two accounts one address.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-51 — `test_email_change_refusals_about_the_callers_own_input`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_admin_change_refusals_about_the_input`
* **Original assertion.** The customer's request is 422 for a wrong current password, a malformed address and the caller's own address, each on its field.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** The Admin's change is 422 for an unlisted reason, a malformed address and the account's own address, each on its field. (The customer's request has no fields to refuse: it is refused whole.)
* **Guarantee still protected.** Input is normalized and validated by `normalize_email` before anything changes.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-52 — `test_email_change_is_rate_limited_per_account`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_the_customer_route_refuses_every_time_and_sends_nothing`
* **Original assertion.** Three requests an hour per account, then 429.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** Every request is the 403 refusal and nothing is sent; there is nothing left to rate-limit because no request can send a message.
* **Guarantee still protected.** The account cannot be used to send mail to an address the customer typed (the reason the limit existed): it sends none at all.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-53 — `test_the_current_address_is_told_when_a_change_is_asked_for`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_the_old_address_is_told_when_an_admin_changes_it`
* **Original assertion.** Asking for a change sends the current address a notice (customer's language, no token, no new address, no link), also when the single email rule refused the address.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** The Admin's change sends the old address the changed notice (customer's language, no token, no new address, no link); no request notice exists any more.
* **Guarantee still protected.** The owner of the old mailbox always hears that the sign-in email moved (review HIGH 1).
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-54 — `test_confirming_an_email_change_ends_every_other_session`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_an_admin_email_change_ends_every_session`
* **Original assertion.** Confirming in the browser that asked keeps that session and ends every other one.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** The Admin's change ends every session; the new address signs in with the unchanged password.
* **Guarantee still protected.** No session survives a sign-in email change except one that proved itself; with an Admin change none did, so none survives (review LOW 12).
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-55 — `test_a_link_opened_elsewhere_ends_every_session`

* **File:** `backend/tests/test_rc21_account_security.py`
* **Now named:** `test_a_withdrawn_link_ends_no_session`
* **Original assertion.** A link opened in another browser changes the address and ends every session.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** A pre-RC-UAT-25 link changes nothing, so the customer's session is untouched.
* **Guarantee still protected.** A refused link has no effect on the account.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-56 — `test_email_change_round_trip_and_token_rules`

* **File:** `backend/tests/test_rc21_golden.py`
* **Now named:** `test_admin_sign_in_email_change_round_trip`
* **Original assertion.** Black box: the customer asks, the link goes to the new address only, the old address works until confirmation, the new one after, the old address is told, the link is single-use and expires.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** Black box: the customer's request is 403 and sends nothing; Operations is refused; the Admin's change makes the new address the one that signs in, ends the session, tells both addresses, sends no confirmation link, leaves no email-change token, and is audited.
* **Guarantee still protected.** The sign-in email moves only through an authorised, audited path that tells the old address.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

### AS-57 — `test_email_change_to_an_address_in_use_is_generic_and_never_switches`

* **File:** `backend/tests/test_rc21_golden.py`
* **Now named:** `test_admin_change_to_an_address_in_use_is_refused_and_never_switches`
* **Original assertion.** Black box: addresses in use get the same answer as a free one and no link; a race at confirmation never switches.
* **Why it became false.** RC-UAT-25 item 2 (Ben, 2026-10-25): customers can no longer change their sign-in email from the Customer Account; `POST /account/email/change` refuses every request (403, one sentence, body unread) and `POST /account/email/change/confirm` refuses every link. An Admin changes it on the staff account screen (`POST /customer-account/identities/{reference}/sign-in-email`).
* **Replacement assertion.** Black box: the Admin's change to an address held by an account or a record is 409, sends nothing and never switches; the customer's request is one refusal whatever the address.
* **Guarantee still protected.** The single email rule, and no enumeration on the customer surface.
* **Authorised by:** DEC-0231 (the self-service email change it introduced, withdrawn by the owner, Ben, on 2026-10-25: RC-UAT-25 item 2, the sign-in email is changed by an Admin only), DEC-0243.

---

---

## Rules for adding an entry

1. An entry is written **in the same commit** as the assertion change it authorises.
2. It names the decision — an `OD-NN`, a `DEC-NNNN`, or both. "The new behaviour needs it"
   is not a reason; it is a restatement of the change.
3. It states the **original** assertion in enough detail that a reader can tell what was
   lost without checking out the old revision.
4. It states which security or architectural guarantee survives, and where. If the honest
   answer is "none", the change is a weakening and needs an owner decision, not an entry.
5. The registered test must exist under the recorded name. `test_superseded_assertions.py`
   checks this, so a later rename has to come back here.
