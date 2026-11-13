# Method v0.7 (backend only) — record

**Asked:** Louis, 2026-11-03 PM: answers to the 8 follow-up questions (decision log §12, entries
26–34). Backend only; no screens until "go". Decisions DEC-0260 to DEC-0264.

| Area | Change |
|---|---|
| Switch | `v0_7` (migration `e6a8c0e2b4d6`, data only); `v0_5` / `v0_6` accepted as aliases |
| Sea minimum | Quote per customer per type = max(own kg × rate, min); cost once per package per type, split by item kg; margin = quote − cost; no package record → whole master + warning (DEC-0260) |
| Typed carton weight | Used as typed (confirmed, DEC-0261) |
| Origin / service | Origin keeps the rate confirmation; service revokes it (confirmed) |
| Packed as one box | Refused on masters with several packages; cleared when a master gains a second package (DEC-0262) |
| Routes | Non-Canada rows excluded, listed in the diff; HCM-41 Canada rate (DEC-0263) |
| Rate sheet | `POST /tariffs/rate-sheet/import` (draft + diff), approve = confirm, `GET /tariffs/rate-sheet/history`, `POST /tariffs/versions/{id}/rollback`; demo / UAT seed on the 2026-11-03 sheet (DEC-0264) |

v0.6 fixes (Louis's review, DEC-0265 / DEC-0266): Sea / UPS masters book without a Kango
product; booking stores the Kango bill weight so the estimate is identical before and after;
routes for manual Express / UPS pricing, method settings, the packed flag and the sea cost.
Correction to the v0.6 record: HCM-44 and HAN-08 are both refused as not applying to Canada.

Tests: `test_method_v07_golden.py` (S1–S7 against `case_study_results_v0.7.json`, every row,
including surcharge margin); `test_method_v07_service.py` (packed scope, excluded rows, sea
without package record, import → diff → confirm → history → rollback, approver rule, seed).

Open: none from Louis's list. Still noted: the engine module and the estimate key keep the
step-1 name (`method_v05`, `v05`).
