"""GST/HST per invoice line, as the Solaris Invoicing desk does it (owner Ben, 2026-10-24;
DEC-0235).

One pure module, used by the draft invoice (its totals, the confirmation echo and the
preview), both issue paths, the invoice document and the PDF, so what staff confirm, what is
issued and what is printed always agree. No database, no I/O.

* **included** (domestic courier rates are all-in): for each line, ``gross = qty * rate``
  (a draft line has no quantity: qty 1 and gross = its amount; a manual-path quote line's
  amount is its gross), ``net = round_half_up(gross / (1 + r), 2)``, ``tax =
  round_half_up(net * r, 2)``; when ``net + tax != gross`` the net is nudged by the cent
  difference so ``net + tax == gross`` exactly. The invoice total is the original all-in
  total.
* **added** (the manual Issue invoice path; a draft switched to "added on top"): ``net =
  gross``, ``tax = round_half_up(net * r, 2)`` per line.
* **zero-rated** (international): tax 0 on every line.

The unit rate shown is ``net / qty`` to 4 decimals (ROUND_HALF_UP). Subtotal = sum of the
nets, tax = sum of the line taxes, total = sum of the lines' all-in amounts.

Labels (English only, on documents): the per-line TAX column (``tax_code``) and the summary
row (``summary_label``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
UNIT = Decimal("0.0001")
INCLUDED = "included"
ADDED = "added"
#: ``document_json["tax_layout"]`` of an invoice issued with per-line figures.
LAYOUT = "invoicing_v1"


def round_half_up(value: Decimal, step: Decimal = CENT) -> Decimal:
    return Decimal(value).quantize(step, rounding=ROUND_HALF_UP)


def tax_code(rate: int, label: str | None = None) -> str:
    """The TAX column of a line: "Zero-rated", "GST", "HST ON", "HST 14%", "HST 15%"; any other
    rate "GST" when its table label is GST, else "HST {r}%"."""
    rate = int(rate)
    if rate == 0:
        return "Zero-rated"
    if rate == 5:
        return "GST"
    if rate == 13:
        return "HST ON"
    if rate in (14, 15):
        return f"HST {rate}%"
    return "GST" if label == "GST" else f"HST {rate}%"


def summary_label(rate: int, label: str | None = None) -> str:
    """The summary row: "GST @ 0%", "GST @ 5%", "HST ON @ 13%", "HST @ 14%", "HST @ 15%";
    any other rate "GST @ r%" or "HST @ r%"."""
    rate = int(rate)
    if rate in (0, 5):
        return f"GST @ {rate}%"
    if rate == 13:
        return "HST ON @ 13%"
    if rate in (14, 15):
        return f"HST @ {rate}%"
    return f"{'GST' if label == 'GST' else 'HST'} @ {rate}%"


@dataclass(frozen=True)
class LineTax:
    #: 1 when the line has no quantity (every draft line).
    quantity: Decimal
    #: What the line is charged in all: net + tax.
    gross_cad: Decimal
    #: Before tax: the line's ``amount_cad`` on an invoice issued with this layout.
    net_cad: Decimal
    #: ``net / quantity`` to 4 decimals: the Rate column.
    unit_price_cad: Decimal
    tax_cad: Decimal
    tax_code: str

    def as_dict(self) -> dict[str, str]:
        return {
            "quantity": _plain(self.quantity),
            "unit_price_cad": str(self.unit_price_cad),
            "net_cad": str(self.net_cad),
            "tax_cad": str(self.tax_cad),
            "gross_cad": str(self.gross_cad),
            "tax_code": self.tax_code,
        }


@dataclass(frozen=True)
class Breakdown:
    mode: str
    rate_percent: int
    lines: tuple[LineTax, ...]
    subtotal_cad: Decimal
    tax_cad: Decimal
    total_cad: Decimal
    #: ``(label, tax)`` per distinct tax code (normally one), in line order.
    tax_rows: tuple[tuple[str, Decimal], ...]

    @property
    def totals(self) -> tuple[Decimal, Decimal, Decimal]:
        return self.subtotal_cad, self.tax_cad, self.total_cad

    def rows_as_dicts(self) -> list[dict[str, str]]:
        return [{"label": label, "tax_cad": str(tax)} for label, tax in self.tax_rows]


def _plain(value: Decimal) -> str:
    """A quantity as written: 60, 12.5 (no trailing zeros, no exponent)."""
    return format(Decimal(value).normalize(), "f")


def line_tax(
    amount: Decimal,
    rate: int,
    mode: str,
    *,
    quantity: Decimal | None = None,
    label: str | None = None,
) -> LineTax:
    """One line's figures. ``amount`` is the line amount as entered (``qty * quoted rate``):
    all-in in included mode, before tax in added mode."""
    qty = Decimal(quantity) if quantity is not None and Decimal(quantity) > 0 else Decimal(1)
    amount = round_half_up(Decimal(amount))
    rate = int(rate)
    if rate == 0:
        net, tax = amount, Decimal("0.00")
    elif mode == INCLUDED:
        net = round_half_up(amount * Decimal(100) / Decimal(100 + rate))
        tax = round_half_up(net * Decimal(rate) / Decimal(100))
        # The parts add up to what the customer pays, to the cent.
        net += amount - (net + tax)
    else:
        net = amount
        tax = round_half_up(net * Decimal(rate) / Decimal(100))
    return LineTax(
        quantity=qty,
        gross_cad=net + tax,
        net_cad=net,
        unit_price_cad=round_half_up(net / qty, UNIT),
        tax_cad=tax,
        tax_code=tax_code(rate, label),
    )


def breakdown(
    lines: list[Any],
    rate: int,
    mode: str,
    *,
    label: str | None = None,
) -> Breakdown:
    """The invoice's figures, line by line. Each entry of ``lines`` is an amount, or an
    ``(amount, quantity)`` pair (quantity None -> 1)."""
    out = []
    for entry in lines:
        amount, quantity = entry if isinstance(entry, tuple) else (entry, None)
        out.append(line_tax(amount, rate, mode, quantity=quantity, label=label))
    subtotal = sum((line.net_cad for line in out), Decimal("0.00"))
    tax = sum((line.tax_cad for line in out), Decimal("0.00"))
    rows: dict[str, Decimal] = {}
    for line in out:
        key = summary_label(rate, label)
        rows[key] = rows.get(key, Decimal("0.00")) + line.tax_cad
    if not rows:
        rows[summary_label(rate, label)] = Decimal("0.00")
    return Breakdown(
        mode=mode,
        rate_percent=int(rate),
        lines=tuple(out),
        subtotal_cad=subtotal,
        tax_cad=tax,
        total_cad=subtotal + tax,
        tax_rows=tuple(rows.items()),
    )
