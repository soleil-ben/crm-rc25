"""RC-UAT-23: GST/HST per invoice line, the Solaris Invoicing desk rules (owner Ben,
2026-10-24; DEC-0235). Pure arithmetic of ``invoice_tax_math``: no database.

1. **Included** (domestic courier rates are all-in): per line, ``net = round_half_up(gross /
   (1 + r))``, ``tax = round_half_up(net * r)``, the net nudged by the cent difference so
   ``net + tax == gross`` exactly; the unit rate is ``net / qty`` to 4 decimals. The owner's
   example: 60 x 2.00 at 5 % -> unit 1.9048, net 114.29, GST 5.71, total 120.00.
2. Every province's rate (ON 13, NS 14, NB/NL/PE 15, the rest 5) backs out exactly, including
   amounts that need the nudge; net + tax == gross for every amount tried.
3. **Added** (the manual path): net = the amount, tax on each line. **Zero-rated**: tax 0.
4. The labels: the TAX column and the summary row.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.services import invoice_tax_math as m
from app.services import tax_rate_service

D = Decimal
CENT = D("0.01")


def _unnudged(gross: Decimal, rate: int) -> tuple[Decimal, Decimal]:
    net = (gross * 100 / D(100 + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
    return net, (net * rate / D(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def _needs_nudge(rate: int, start: int = 1) -> Decimal:
    """The first amount (in cents from ``start``) whose plain back-out is a cent off."""
    for cents in range(start, 1_000_000):
        gross = D(cents) / 100
        net, tax = _unnudged(gross, rate)
        if net + tax != gross:
            return gross
    raise AssertionError(f"no amount needs the nudge at {rate} %")


# === 1. The owner's example ======================================================================


def test_sixty_at_two_dollars_at_five_percent_is_the_owners_example():
    line = m.line_tax(D("120.00"), 5, "included", quantity=D(60))
    assert line.unit_price_cad == D("1.9048")
    assert line.net_cad == D("114.29")
    assert line.tax_cad == D("5.71")
    assert line.gross_cad == D("120.00")
    assert line.tax_code == "GST"
    figures = m.breakdown([(D("120.00"), D(60))], 5, "included")
    assert figures.totals == (D("114.29"), D("5.71"), D("120.00"))
    assert figures.tax_rows == (("GST @ 5%", D("5.71")),)
    assert line.as_dict() == {
        "quantity": "60",
        "unit_price_cad": "1.9048",
        "net_cad": "114.29",
        "tax_cad": "5.71",
        "gross_cad": "120.00",
        "tax_code": "GST",
    }


def test_a_line_with_no_quantity_reads_as_one():
    line = m.line_tax(D("113.00"), 13, "included")
    assert (line.quantity, line.unit_price_cad) == (D(1), D("100.0000"))
    assert (line.net_cad, line.tax_cad) == (D("100.00"), D("13.00"))
    assert m.line_tax(D("10.00"), 5, "included", quantity=D(0)).quantity == D(1)


# === 2. Every province ===========================================================================

PROVINCES = sorted(tax_rate_service.DEFAULT_RATES.items())


@pytest.mark.parametrize(("province", "rate_label"), PROVINCES)
def test_every_province_backs_out_exactly_line_by_line(province, rate_label):
    rate, label = rate_label
    expected = {"ON": 13, "NS": 14, "NB": 15, "NL": 15, "PE": 15}.get(province, 5)
    assert rate == expected
    for cents in (1, 4, 99, 100, 11300, 12345, 99999, 123456):
        gross = D(cents) / 100
        line = m.line_tax(gross, rate, "included", label=label)
        assert line.net_cad + line.tax_cad == gross, (province, gross)
        assert line.net_cad == line.net_cad.quantize(CENT)
        assert line.tax_cad == line.tax_cad.quantize(CENT)
        # Within a cent of the exact back-out, either way.
        exact_net = gross * 100 / D(100 + rate)
        assert abs(line.net_cad - exact_net) <= D("0.011"), (province, gross)


@pytest.mark.parametrize(
    ("rate", "gross", "net", "tax"),
    [
        (13, "113.00", "100.00", "13.00"),
        (13, "100.00", "88.49", "11.51"),  # 88.50 + 11.51 = 100.01: nudged to 88.49
        (14, "114.00", "100.00", "14.00"),
        (15, "115.00", "100.00", "15.00"),
        (15, "100.00", "86.96", "13.04"),
        (5, "105.00", "100.00", "5.00"),
        (5, "10.00", "9.52", "0.48"),
    ],
)
def test_known_back_outs(rate, gross, net, tax):
    line = m.line_tax(D(gross), rate, "included")
    assert (line.net_cad, line.tax_cad) == (D(net), D(tax))


@pytest.mark.parametrize("rate", [13, 14, 15])
def test_an_amount_that_needs_the_cent_nudge_still_adds_up(rate):
    for start in (1, 1000, 10000):
        gross = _needs_nudge(rate, start)
        plain_net, plain_tax = _unnudged(gross, rate)
        assert plain_net + plain_tax != gross
        line = m.line_tax(gross, rate, "included")
        assert line.tax_cad == plain_tax
        assert line.net_cad == gross - plain_tax == plain_net + (gross - plain_net - plain_tax)
        assert abs(line.net_cad - plain_net) == CENT
        assert line.net_cad + line.tax_cad == gross


@pytest.mark.parametrize(
    "rate", sorted({rate for rate, _label in tax_rate_service.DEFAULT_RATES.values()})
)
def test_net_plus_tax_is_the_gross_for_every_amount(rate):
    """Property-style: every amount from 0.01 to 300.00, and a spread of larger ones."""
    amounts = [D(cents) / 100 for cents in range(1, 30001)]
    amounts += [D(cents) / 100 for cents in range(30001, 10_000_000, 7919)]
    for gross in amounts:
        line = m.line_tax(gross, rate, "included")
        assert line.net_cad + line.tax_cad == gross, gross
        assert line.net_cad >= 0 and line.tax_cad >= 0


def test_the_invoice_is_the_sum_of_its_lines_and_the_total_is_unchanged():
    amounts = [D("100.00"), D("45.67"), D("0.04"), D("1234.56")]
    figures = m.breakdown(amounts, 13, "included", label="HST")
    assert figures.total_cad == sum(amounts, D(0))
    assert figures.subtotal_cad == sum((line.net_cad for line in figures.lines), D(0))
    assert figures.tax_cad == sum((line.tax_cad for line in figures.lines), D(0))
    assert figures.subtotal_cad + figures.tax_cad == figures.total_cad
    assert figures.tax_rows == (("HST ON @ 13%", figures.tax_cad),)
    assert [line.tax_cad for line in figures.lines] == [
        D("11.51"),
        D("5.25"),
        D("0.01"),
        D("142.03"),
    ]
    assert figures.tax_cad == D("158.80")
    # Not the whole-total back-out of DEC-0223, which reads a cent less on 1380.27.
    whole = (figures.total_cad * 13 / D(113)).quantize(CENT, rounding=ROUND_HALF_UP)
    assert whole == D("158.79")


# === 3. Added on top and zero-rated ==============================================================


def test_added_on_top_is_charged_per_line():
    figures = m.breakdown([(D("10.01"), D(2)), D("0.10")], 5, "added")
    assert [line.net_cad for line in figures.lines] == [D("10.01"), D("0.10")]
    assert [line.tax_cad for line in figures.lines] == [D("0.50"), D("0.01")]
    assert figures.totals == (D("10.11"), D("0.51"), D("10.62"))
    assert figures.lines[0].unit_price_cad == D("5.0050")
    assert figures.lines[0].gross_cad == D("10.51")


@pytest.mark.parametrize("mode", ["included", "added"])
def test_zero_rated_lines_carry_no_tax(mode):
    figures = m.breakdown([D("250.00"), (D("33.33"), D(3))], 0, mode)
    assert figures.totals == (D("283.33"), D("0.00"), D("283.33"))
    assert {line.tax_code for line in figures.lines} == {"Zero-rated"}
    assert figures.lines[1].unit_price_cad == D("11.1100")
    assert figures.tax_rows == (("GST @ 0%", D("0.00")),)


# === 4. Labels ===================================================================================


@pytest.mark.parametrize(
    ("rate", "label", "code", "row"),
    [
        (0, None, "Zero-rated", "GST @ 0%"),
        (5, "GST", "GST", "GST @ 5%"),
        (5, "HST", "GST", "GST @ 5%"),
        (13, "HST", "HST ON", "HST ON @ 13%"),
        (13, None, "HST ON", "HST ON @ 13%"),
        (14, "HST", "HST 14%", "HST @ 14%"),
        (15, "HST", "HST 15%", "HST @ 15%"),
        (7, "GST", "GST", "GST @ 7%"),
        (12, "HST", "HST 12%", "HST @ 12%"),
        (12, "GST/HST", "HST 12%", "HST @ 12%"),
    ],
)
def test_labels(rate, label, code, row):
    assert m.tax_code(rate, label) == code
    assert m.summary_label(rate, label) == row
    assert "included" not in code.lower()
