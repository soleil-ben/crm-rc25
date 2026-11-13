# 28 — Build RC-UAT-24: Ben's evening answers (I-1, I-10, I-11, I-12)

**Date:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17` (on RC-UAT-23, `bb9a89b` / app
`3151095`) · **Migration:** `e7a9c1d3f5b6` (data only: no table or column changes) ·
**Decisions:** DEC-0236 to DEC-0239 · **Owner decision:** OD-112 · **Scope:** air only

Ben answered the RC-UAT-23 invoice stand-ins on the evening of 2026-10-24 (about 21:37 ET).
Nothing is pushed or merged; test data only; email is test capture only. On Ben's word, the held
items stay unbuilt for now: returns (OD-22), staff MFA (OD-17), production email (OD-34),
ShipStation / provider sync (OD-21), retention periods (OD-01, OD-36). Refunds, voids and hosting
are untouched.

## 1. What changed

| # | Answer | Result |
|---|---|---|
| 1 | Held items: skip for now | Nothing built; `BUILD_STATUS.md` lists them as held |
| 2 | I-1 confirmed | English-only invoice PDF with names without accents kept as built (DEC-0237) |
| 3 | I-10 build | **Solaris Express Inc.** on Settings (Brand and tracking → Legal entity), the staff portal's login footer (English and Vietnamese) and the demo label sender (`seed.py`, `scripts/render_sample_labels.py`); the `organization_settings` model default; data-only migration `e7a9c1d3f5b6` renames a settings row still holding exactly "Soleil Global Transportation Inc." and leaves any other value alone (DEC-0236). Parent-company references (`README.md`, `CRM.md`, Soleil's warehouse and mailbox) and historical records are unchanged on purpose |
| 4 | I-12 confirmed | The cent nudge on tiny amounts kept (DEC-0238) |
| 5 | I-11 optional polish | The draft editor's sentence is now "Tax included in the price: subtotal before tax …, HST ON @ 13% …, total …" with the invoice's summary labels (DEC-0239); quote wording unchanged |

New tests: `backend/tests/test_rc24_legal_entity.py` (Settings API, model default, both label
senders, the migration renaming only the old default and its downgrade) and
`frontend/tests/rc24LegalEntity.test.jsx` (both languages' login footer, Settings). Eight
frontend fixtures that carried the old name now carry the new one; three earlier assertions of
the editor sentence (two vitest, one Playwright) read the new wording. UAT: `UAT-BLD-25`; the
editor sentence updated in `UAT-OWN-20` and `UAT-OWN-28`; air pack 96 cases.

## 2. Evidence

| Gate | Result |
|---|---|
| ruff | clean (391 files formatted) |
| alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database -- head `e7a9c1d3f5b6`, "No new upgrade operations detected" (data only) |
| verifiers | decision log (DEC-0236 to DEC-0239), owner decisions (OD-112), UAT blank (air pack 96) -- pass |
| eslint, vitest | clean; 844 passed (2 new in `rc24LegalEntity.test.jsx`) |
| build | OK |
| backend pytest | 4,940 passed, 1 skipped, 0 failed (nine foreground chunks covering all 159 test files); 4 new in `test_rc24_legal_entity.py` |
| Playwright | full suite on port 5173, one run: **326 passed** (13.5 min); no second run needed |

## 3. Not done

Returns, staff MFA, production email, ShipStation / provider sync, retention periods (held by
Ben); refunds and voids; hosting.
