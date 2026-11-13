"""HTTP smoke check for the portable RC-UAT-25 package (standard library only).

Run by ``SMOKE_UAT.bat`` (or ``uat\\uat.ps1 smoke``) while START_UAT.bat is running. Checks:
the backend's health and readiness; the frontend page; every staff role and both seeded
Customer Accounts can sign in through the frontend's /api proxy; the UAT dataset is there
(masters, a quote waiting for the Vietnamese customer); captured emails exist as files.
Exit status 0 when every check passes.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://localhost:5173"
STAFF = (
    "admin@demo.example.com",
    "ops@demo.example.com",
    "marketing@demo.example.com",
    "manager@demo.example.com",
)
CUSTOMERS = ("trang.air@example.com", "emily.air@example.com")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    return ok


#: Ben's rule (2026-10-23): HST 13 ON, 14 NS, 15 NB/NL/PE; every other province 5 % GST.
PROVINCE_RATES = {"ON": 13, "NS": 14, "NB": 15, "NL": 15, "PE": 15}


def _money(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _per_line(amount: Decimal, rate: int) -> tuple[Decimal, Decimal]:
    """(net, tax) of one all-in line, the Solaris Invoicing rule (DEC-0235): net backed out
    and rounded half up, tax on the net, the net nudged so net + tax is the line exactly."""
    cent = Decimal("0.01")
    net = (amount * 100 / Decimal(100 + rate)).quantize(cent, rounding=ROUND_HALF_UP)
    tax = (net * rate / Decimal(100)).quantize(cent, rounding=ROUND_HALF_UP)
    return amount - tax, tax


def _tax_rule(invoices: object, drafts: object) -> tuple[bool, str]:
    """(ok, detail): one zero-rated international invoice, and every domestic draft whose
    province is known carries its province's rate, included and backed out line by line
    (DEC-0235): the breakdown the API returns matches the rule recomputed per line."""
    rows = (invoices or {}).get("items", []) if isinstance(invoices, dict) else []
    zero_rated = [
        inv.get("public_id")
        for inv in rows
        if inv.get("tax_status") == "gst_hst_0"
        and _money(inv.get("tax_cad") or 0) == 0
        and _money(inv.get("subtotal_cad")) == _money(inv.get("total_cad"))
        and (_money(inv.get("total_cad")) or 0) > 0
    ]
    items = (drafts or {}).get("items", []) if isinstance(drafts, dict) else []
    domestic, wrong = [], []
    for draft in items:
        if draft.get("status") == "discarded":
            continue
        route = draft.get("tax_route") or {}
        province = route.get("destination_province")
        if route.get("route_band") != "domestic" or not province:
            continue
        rate = draft.get("tax_rate_percent")
        total = _money(draft.get("total_cad"))
        tax = _money(draft.get("tax_cad"))
        expected_rate = PROVINCE_RATES.get(province, 5)
        amounts = [_money(line.get("amount_cad")) for line in draft.get("lines") or []]
        shown = draft.get("tax_lines") or []
        if rate is None or total is None or tax is None or None in amounts or not amounts:
            wrong.append(f"{province}: no figures")
            continue
        parts = [_per_line(amount, rate) for amount in amounts]
        lines_ok = len(shown) == len(parts) and all(
            (_money(line.get("net_cad")), _money(line.get("tax_cad"))) == part
            and _money(line.get("net_cad")) + _money(line.get("tax_cad")) == amount
            for line, part, amount in zip(shown, parts, amounts, strict=False)
        )
        if (
            rate != expected_rate
            or draft.get("tax_mode") != "included"
            or not lines_ok
            or tax != sum((part[1] for part in parts), Decimal(0))
            or total != sum(amounts, Decimal(0))
            or _money(draft.get("subtotal_cad")) != total - tax
        ):
            wrong.append(f"{province} {rate} %")
        else:
            domestic.append(f"{province} {rate} %")
    zero_text = ", ".join(zero_rated[:2]) or "none"
    detail = f"zero-rated: {zero_text}; domestic: {', '.join(domestic) or 'none'}"
    if wrong:
        detail += f"; WRONG: {', '.join(wrong)}"
    return bool(zero_rated) and bool(domestic) and not wrong, detail


def passwords(root: Path) -> tuple[str, str]:
    """Read the demo passwords from the seed scripts rather than repeating them here."""
    staff = re.search(
        r'^UAT_PASSWORD = "([^"]+)"', (root / "scripts/uat_env.py").read_text("utf-8"), re.M
    )
    account = re.search(
        r'^ACCOUNT_PASSWORD = "([^"]+)"',
        (root / "scripts/uat_seed_phase13.py").read_text("utf-8"),
        re.M,
    )
    if not staff or not account:
        raise SystemExit("could not read the demo passwords from scripts/")
    return staff.group(1), account.group(1)


def client() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def call(opener, method: str, url: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Origin", FRONTEND)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=20) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw or b"null")
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    root = Path(parser.parse_args().root)
    staff_pw, account_pw = passwords(root)

    plain = client()
    status, body = call(plain, "GET", f"{BACKEND}/health")
    check("backend /health", status == 200, str(body))
    status, body = call(plain, "GET", f"{BACKEND}/health/ready")
    check("backend /health/ready", status == 200, str(body))
    status, body = call(plain, "GET", f"{FRONTEND}/")
    check("frontend page", status == 200 and '<div id="root"' in str(body), f"status {status}")

    for email in STAFF:
        s = client()
        status, _ = call(
            s, "POST", f"{FRONTEND}/api/v1/auth/login", {"email": email, "password": staff_pw}
        )
        ok = check(f"staff sign-in {email}", status == 200, f"status {status}")
        if ok:
            status, me = call(s, "GET", f"{FRONTEND}/api/v1/auth/me")
            check(f"staff session {email}", status == 200, f"status {status}")
        if ok and email.startswith("ops@"):
            status, masters = call(s, "GET", f"{FRONTEND}/api/v1/consolidations")
            count = (masters or {}).get("total", 0) if isinstance(masters, dict) else 0
            check(
                "UAT masters present (Operations)", status == 200 and count >= 5, f"{count} masters"
            )
            # RC-UAT-18+ (OD-88): a booked master locks its items and fees.
            items = (masters or {}).get("items", []) if isinstance(masters, dict) else []
            locked = [m for m in items if ((m or {}).get("edit_lock") or {}).get("locked")]
            check("booked masters are locked for edits", len(locked) >= 1, f"{len(locked)} locked")
            # RC-UAT-18+ (OD-89/90): the draft-invoice screen's list answers.
            # Every status: a draft the tester already sent still shows its tax figures.
            status, drafts = call(
                s, "GET", f"{FRONTEND}/api/v1/invoice-drafts?status=all&limit=200"
            )
            check("draft invoice list (Operations)", status == 200, f"status {status}")
            # RC-UAT-20+ (OD-102, Ben 2026-10-23): GST/HST follows the route. International
            # shipments are zero-rated (an invoice at 0 %: no tax, subtotal = total); domestic
            # drafts carry the tax included at the destination province's rate, backed out of
            # the all-in total (tax = total x r / (100 + r), to the cent).
            status, invoices = call(s, "GET", f"{FRONTEND}/api/v1/invoices")
            check("GST/HST follows the route rule", *_tax_rule(invoices, drafts))

    for email in CUSTOMERS:
        a = client()
        status, _ = call(
            a,
            "POST",
            f"{FRONTEND}/api/v1/account/sign-in",
            {"email": email, "password": account_pw},
        )
        ok = check(f"Customer Account sign-in {email}", status == 200, f"status {status}")
        if ok:
            status, me = call(a, "GET", f"{FRONTEND}/api/v1/account/me")
            check(f"Customer Account session {email}", status == 200, f"status {status}")
        if ok and email.startswith("trang."):
            status, quotes = call(a, "GET", f"{FRONTEND}/api/v1/account/quotes")
            items = quotes if isinstance(quotes, list) else (quotes or {}).get("items", [])
            waiting = [q for q in items if isinstance(q, dict) and q.get("status") == "sent"]
            check(
                "a quote waits for the Vietnamese customer",
                status == 200 and bool(waiting),
                f"{len(waiting)} waiting",
            )
            # RC-UAT-18+ (OD-84): no vendor name in what the customer reads.
            leaked = []
            for q in items if isinstance(items, list) else []:
                if isinstance(q, dict) and q.get("id") is not None:
                    st, detail = call(a, "GET", f"{FRONTEND}/api/v1/account/quotes/{q['id']}")
                    if st == 200 and "kango" in json.dumps(detail, ensure_ascii=False).lower():
                        leaked.append(q["id"])
            check(
                "no vendor name in the customer's quotes", not leaked, f"{len(items)} quotes read"
            )

    mail = root / "data" / "uat" / "account_mail"
    files = [p for p in mail.glob("*") if p.is_file()] if mail.exists() else []
    check("captured emails are local files", len(files) > 0, f"{len(files)} files in {mail}")

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
