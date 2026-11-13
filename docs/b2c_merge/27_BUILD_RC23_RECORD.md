# 27 — Build RC-UAT-23: invoices follow the Solaris Invoicing desk

**Date:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17` (on RC-UAT-22, `ecb19b7` / app
`61f5c22`) · **Migration:** none (no table or column added or altered) · **Decision:** DEC-0235 ·
**Owner decisions:** OD-109 (P-9) closed as confirmed; OD-111 (mimic Solaris Invoicing) ·
**Stand-ins:** I-1 to I-13 (`19_OWNER_QUESTIONS.md` §00000) · **Scope:** air only

Ben confirmed on 2026-10-24 that domestic courier rates **include** GST/HST and that the CRM must
mimic the Solaris Invoicing desk. Nothing is pushed or merged; test data only; email is test
capture only. Refunds and voids are unchanged (the desk does not record payments; Ben decides
any change). Still held: returns (OD-22), staff MFA (OD-17), production email (OD-34),
ShipStation (OD-21); retention off (OD-01, OD-36).

## 1. What was built

| # | Rule | How |
|---|---|---|
| 1 | Air Freight, international: zero-rated | Line amount = rate; Tax column **Zero-rated**; summary **GST @ 0%** |
| 2 | Courier, domestic: GST/HST included, backed out at the destination province's rate | Rate from the route rule and `tax_rates` (ON 13, NS 14, NB/NL/PE 15, others 5). Line amount = the backed-out **net**; tax in the summary; total = the original inclusive total |
| 3 | Back-out arithmetic, per line | `app/services/invoice_tax_math.py`, used by the draft totals, the tax-confirmation echo, both issue paths, the invoice document and the PDF: gross = qty × rate; net = round_half_up(gross ÷ (1 + r), 2); tax = round_half_up(net × r, 2); if net + tax ≠ gross the net moves by the cent; Rate = net ÷ qty to 4 dp. 60 × 2.00 at 5 % → 1.9048, 114.29 + 5.71 = 120.00. Every province rate tested, with cent-nudge cases and a sweep of about 31,000 amounts per rate |
| 4 | Sale of Product: pre-tax + 13 % HST ON | **Not applicable:** the CRM has no product sale, and none was invented (I-8). The manual **Issue invoice** path keeps tax added on top (0 / 5 / 13 %), now per line on the new layout (I-2) |
| 5 | Surcharges: own line, same treatment | Draft lines from a quote keep each surcharge as its own line, taxed like the base line (tested) |
| 6 | Invoice PDF English only | Draft and issued PDFs on the new layout are English for every customer; every printed string loses its Vietnamese accents ("Phạm Thị Thu Trang" → "Pham Thi Thu Trang", I-1) |
| 7 | Labels | Tax column: Zero-rated · GST · HST ON · HST 14% · HST 15%. Summary: GST @ 0% · GST @ 5% · HST ON @ 13% · HST @ 14% · HST @ 15%. No "Prices include" sentence and no "included" in the Tax column on invoices |
| 8 | Footer | "Thank you for your business! We accept payment via E-transfer to info@solarisexpress.ca" |
| 9 | Company block | Solaris Express Inc. · 2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6 · solarisexpressinc@gmail.com · GST/HST BN: 795093756RT0001 · Terms: Due on receipt (`invoice_due_days` 0, the default; "Net N days" when staff set N) · Currency: CAD · Payment: E-transfer to info@solarisexpress.ca · Wire: Bank of Montreal, 2825 Eglinton Avenue West, Mississauga ON L5M 6J3 · SWIFT BOFMCAM2 · Account 1969380. `finance_service.COMPANY` changed, so receipts and the printable quote carry the new name, address and email |
| 10 | Quotes keep the inclusive total; issued invoices show nets + summary | Quote wording unchanged (OD-109, now confirmed). Issued invoices store each line's **net** in `customer_invoice_lines.amount_cad` and the per-line facts plus `tax_layout: "invoicing_v1"` in `document_json`. Invoices issued before keep their stored figures and old presentation (I-4); revenue is still the pre-tax subtotal |
| 11 | OD-109 / P-9 | Closed as confirmed by Ben (2026-10-24); OD-111 and DEC-0235 record the Invoicing alignment |
| — | Staff screens | The draft editor still takes the all-in amounts and shows **As the invoice will show it** (the server's per-line breakdown); the invoice detail and print pages show Qty, Rate, Amount, Tax and the summary rows for new invoices |
| — | UAT smoke | `uat_smoke.py` checks domestic drafts with the per-line rule; still 22 checks |

**QuickBooks and the STCA- rule.** The CRM has no QBO export, so the desk's rule that QBO customer
names start with `STCA-` has nothing to change here (I-7). The CRM keeps its own customer
references (`STCA-000003`) and display names.

## 2. Evidence

| Gate | Result |
|---|---|
| ruff | clean (389 files formatted) |
| alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database -- head `d4f6b8c0e2a5` (unchanged), "No new upgrade operations detected" |
| verifiers | decision log (DEC-0235), owner decisions (OD-109 answered, OD-111), UAT blank (air pack 95), RC baseline -- pass |
| eslint, vitest | clean; 842 passed (7 new in `rc23InvoiceLayout.test.jsx`) |
| build | OK |
| backend pytest | 4,936 passed, 1 skipped, 0 failed (nine foreground chunks); 52 new in `test_rc23_invoice_tax_math.py` and `test_rc23_invoice_layout.py`. About 20 earlier assertions changed for DEC-0235 (old company block, Vietnamese PDF labels, whole-total back-out amounts, the "Prices include" note on invoices); the quote allowlist change is AS-43 |
| Playwright | full suite on port 5173, one run: **326 passed** (14.2 min); no second run needed |

## 3. Known issues and open questions

* I-1: whether a customer name without accents is acceptable on a legal invoice.
* I-10: the staff Settings legal-entity name and the label sender still read "Soleil Global
  Transportation Inc."; only the invoice, receipt and quote company block changed.
* I-12: on very small amounts the cent nudge gives odd-looking splits (0.04 at 14 % → 0.03 +
  0.01); this is the desk's rule applied literally.
* All stand-ins: `19_OWNER_QUESTIONS.md` §00000.

## 4. Not done

Returns, staff MFA, production email, ShipStation / provider sync, enabling retention; any change
to refunds or voids.
