"""Re-measure the current release-candidate baseline and fail on drift.

`docs/RC_UAT_25_BASELINE.json` records what the release candidate is now; RC-UAT-1 to
RC-UAT-24 are kept beside it as superseded historical records. A
frozen number that nobody re-measures is a claim, not a control, so this script reads the
baseline file and measures the same things again from the running code.

RC-UAT-1 was superseded because the branch added failure-only diagnostic capture to the
end-to-end harness. RC-UAT-2 was superseded because a staff screen changed: the
shipment-status report's Returns row lost a drill-through that pointed at a filter
nothing implements, and four further generated links naming parameters nothing reads
were corrected. RC-UAT-3 was superseded by Phase 12, which added a third frontend
application: fourteen Customer Account routes, two Staff Portal approval screens, and two
exact-match filters on the authenticated shipment list (OD-41). Every superseded baseline
stays verifiable -- pass its path with ``--baseline`` -- so the evidence behind it can be
rechecked rather than taken on trust.

**The two drifts RC-UAT-3 carried are closed here, by re-freezing rather than by changing
anything.** Its Alembic head was ``e5623fcf8018`` and the repository has been at
``6af30fcdd3a8`` since Phase 10; its UAT case count was 45 and the file has held 49 since
the role merge. Both are recorded at their measured values in RC-UAT-4, so a drift against
the baseline in force now means something moved today.

**RC-UAT-4 was re-frozen on 2026-10-11 at ``0b772e0``**, keeping its identifier. The
cross-platform, dependency and deprecation cleanup (``PROJECT_STATUS.md`` section 29)
changed both dependency locks -- Vitest 2 to 4, Starlette 1.6 to 1.7, ``httpx`` to
``httpx2`` -- and nothing a tester sees. The two lock digests in the baseline file are the
new ones; the previous pair is recorded beside them in ``dependency_lock_note`` and
``refreeze_history``. To re-check the first freeze, run this script from a checkout of
``48abca5``; its copy of the baseline file carries the digests of that tree.

**RC-UAT-4 was superseded by RC-UAT-5 on 2026-10-14, measured at ``0dfaf23``.** The UAT
round 1 fix pack (``PROJECT_STATUS.md`` section 31) changed screens, routes, schemas and
wording, which is the convention's rule for a new identifier. It changed no migration and
no dependency, so RC-UAT-4 still reported 10 of 10 on the new tree: none of these ten
checks hashes application code. That is a property of what is checked, recorded here so a
clean report is never read as "nothing a tester sees moved".

**RC-UAT-5 was superseded by RC-UAT-6 on 2026-10-15, measured at ``92d3331``**: UAT round 2
fix pack 2 (``PROJECT_STATUS.md`` section 33) added the Customer Account profile and its
staff review, and again changed no migration and no dependency.

**RC-UAT-6 was superseded by RC-UAT-7 on 2026-10-15, measured at ``d9f61ee``**: UAT round 3
fix pack 3 (``PROJECT_STATUS.md`` section 34) changed screens, schemas and wording, and
changed no route, migration or dependency.

**RC-UAT-7 was superseded by RC-UAT-8 on 2026-10-15, measured at ``4374407``**: UAT round 4
fix pack 4 (``PROJECT_STATUS.md`` section 35) added two routes and two permissions and
changed screens, schemas and wording, and changed no migration or dependency.

**RC-UAT-8 was superseded by RC-UAT-9 on 2026-10-15, measured at ``e1720f4``**: UAT round 5
fix pack 5 and owner decisions (``PROJECT_STATUS.md`` section 36) changed screens, schemas,
a permission rule and wording, and changed no route, migration or dependency.

**RC-UAT-9 was superseded by RC-UAT-10 on 2026-10-15, measured at ``ba3fce0``**: UAT round
6 fix pack 6 and owner decisions (``PROJECT_STATUS.md`` section 37) changed screens, schemas,
an edit rule and behaviour, and changed no route, migration or dependency.

**RC-UAT-10 was superseded by RC-UAT-11 on 2026-10-16, measured at ``e74b388``**: the UAT
round 7 owner decisions (``PROJECT_STATUS.md`` section 38) changed a screen, a response
field and wording, and changed no route, migration or dependency.

**RC-UAT-11 was superseded by RC-UAT-12 on 2026-10-17, measured at ``3d46044``**: UAT
round 8 (``PROJECT_STATUS.md`` section 39) changed screens, request and response fields,
behaviour and wording, and changed no route, migration or dependency.

**RC-UAT-12 was superseded by RC-UAT-13 on 2026-10-18, measured at ``f872068``**: UAT
round 9 (``PROJECT_STATUS.md`` section 40) changed screens, request validation, audit
behaviour and wording, and changed no route, migration or dependency.

**RC-UAT-13 was superseded by RC-UAT-14 on 2026-10-18, measured at ``04123c1``**: UAT
round 10 (``PROJECT_STATUS.md`` section 41) changed a screen, an API query parameter and
wording (the shipment list's keyword search), and changed no route, migration or dependency.

**RC-UAT-14 was superseded by RC-UAT-15 on 2026-10-18, measured at ``b81ad85``**: UAT
round 11 (``PROJECT_STATUS.md`` section 42) changed screens, a response field, request
validation and search behaviour, and changed no route, migration or dependency.

**RC-UAT-15 was superseded by RC-UAT-16 on 2026-10-19, measured at ``58f2039``**: UAT
round 12 (``PROJECT_STATUS.md`` section 43) changed a screen, a response field, request
validation and an API default, and changed no route, migration or dependency.

**RC-UAT-16 was superseded by RC-UAT-17 on 2026-10-21**, measured on ``1089257`` plus the
Phase 17 dry-run fixes (the app+tests commit, recorded in the baseline file): the B2C
merge, Phases 13A to 16 on ``phase-13-b2c-merge`` (``PROJECT_STATUS.md`` sections 44 to 56),
added screens, routes, schemas, migrations and a backend dependency (``openpyxl``), and Phase
17 (section 57, DEC-0218) froze it for UAT with the seeded air dataset and a third UAT pack.
Against this tree RC-UAT-16 drifts on the Alembic head and the backend lock digest, which
RC-UAT-17 re-measures.

**RC-UAT-17 was superseded by RC-UAT-18 on 2026-10-22, measured at ``03b943d``**: the
owner-answer fix pack OD-81 to OD-90 (``PROJECT_STATUS.md`` section 58, DEC-0219 to DEC-0222,
``docs/b2c_merge/22_FIXPACK_RC18_RECORD.md``) changed screens, routes (228 to 238), a
permission (``master:unlock``), schemas and a migration (``d4f7a2c9e1b8``), and changed no
dependency. Against this tree RC-UAT-17 drifts on the Alembic head only.

**RC-UAT-18 was superseded by RC-UAT-19 on 2026-10-22, measured at ``418cf3f``**: the owner
answers of 2026-10-22, OD-91 to OD-101 (``PROJECT_STATUS.md`` section 59, DEC-0223 to
DEC-0226, ``docs/b2c_merge/23_FIXPACK_RC19_RECORD.md``) changed screens, a route (238 to 239,
``PATCH /shipments/{id}/fee-lines/{line_id}``), the public tracking contract (24 to 25 fields,
``carrier_links``), schemas and a migration (``e6b1c4a8d2f3``), and the UAT launcher (Python
3.11 to 3.14), and changed no dependency. Against this tree RC-UAT-18 drifts on the public
contract field count and the Alembic head.

**RC-UAT-19 was superseded by RC-UAT-20 on 2026-10-24, measured at ``98ca88b``**: Ben's
answers of 2026-10-23, OD-102 to OD-108 (``PROJECT_STATUS.md`` section 60, DEC-0227 to
DEC-0229, ``docs/b2c_merge/24_FIXPACK_RC20_RECORD.md``) changed screens (Settings > GST/HST
rates, the tariff warnings panel, tax by route and costume-jewellery cost and price on drafts),
routes (239 to 242: ``GET /finance/tax-rates``, ``PATCH /finance/tax-rates/{province_code}``,
``GET /tariffs/versions/{version_id}/warnings``), schemas and a migration (``f7c2d9e3a1b5``),
and changed no dependency. Against this tree RC-UAT-19 drifts on the Alembic head only.

**RC-UAT-20 was superseded by RC-UAT-21 on 2026-10-24, measured at ``be7d2df``**: the build
run on Ben's direction of 2026-10-24, OD-110 (``PROJECT_STATUS.md`` section 61, DEC-0230 to
DEC-0233, ``docs/b2c_merge/25_BUILD_RC21_RECORD.md``) changed screens (shipment CSV import and
the legacy history baseline, password and sign-in email change, Admin reinstatement, the quote
GST/HST line, Admin soft delete of old quote versions, data-retention settings left off),
routes (242 to 269: 22 staff -- bulk imports, legacy shipments, quote history, delete and
restore, data retention, staff password change, deactivated accounts and reactivate -- and 5
Customer Account -- account security, password change, email change), permissions (53 to 55:
``quote:delete``, ``retention:manage``), a Customer Account quote field (17 to 18, ``tax``) and
three migrations (``a1c3e5f7b9d2``, ``b2d4f6a8c1e3``, ``c3e5a7b9d2f4``), and changed no
dependency. Against this tree RC-UAT-20 drifts on the Alembic head only.

**RC-UAT-21 was superseded by RC-UAT-22 on 2026-10-24, measured at ``61f5c22``**: the build
of B-13 (``PROJECT_STATUS.md`` section 62, DEC-0234,
``docs/b2c_merge/26_BUILD_RC22_RECORD.md``) changed a screen (Customer accounts > Accounts
needing a customer: Admin re-links an account left without a customer after reinstatement, or
closes it; dialogs taller than the window scroll), routes (269 to 273, all staff
under ``/customer-account``: ``GET identities-orphaned`` and, on
``identities/{account_reference}``, ``GET relink-preview``, ``POST relink`` and
``POST close-orphan``), schemas and a migration
(``d4f6b8c0e2a5``), and the test harness: Playwright now binds Vite and the API to
``127.0.0.1`` and gives the browser that origin (the ``ERR_CONNECTION_REFUSED`` blank page),
and ``test_e2e_safety`` asserts the development database is unchanged instead of failing in
every worktree. It changed no permission (55), no public or Customer Account field and no
dependency. Against this tree RC-UAT-21 drifts on the Alembic head only.

**RC-UAT-22 was superseded by RC-UAT-23 on 2026-10-24, measured at ``3151095``**: invoices
follow the Solaris Invoicing desk (``PROJECT_STATUS.md`` section 63, DEC-0235, OD-111, OD-109
answered, ``docs/b2c_merge/27_BUILD_RC23_RECORD.md``). It changed screens (GST/HST backed out
per line at the destination province's rate, international zero-rated, net lines with a Tax
column and summary rows, English-only invoice PDFs without accents, the Solaris Express Inc.
company block, terms, payment lines and footer; the draft editor's "As the invoice will show
it") and response schemas, with optional fields only: the invoice detail, invoice document,
draft and their lines (``tax_layout``, ``tax_rows``, ``tax_lines``, per-line Rate, tax, all-in
amount and Tax column, payment terms and lines) and ``company_email`` on the invoice, receipt
and quote documents (the quote document allowlist 20 to 21 fields, AS-43). It changed no route
(273), no permission (55), no public tracking or Customer Account field, no migration (head
``d4f6b8c0e2a5``) and no dependency. Against this tree RC-UAT-22 drifts on none of the ten
checks, because none of them hashes application code -- the RC-UAT-4 to RC-UAT-5 case again.

**RC-UAT-23 was superseded by RC-UAT-24 on 2026-10-24, measured at ``f4a04a3``**: Ben's
evening answers of 2026-10-24 (``PROJECT_STATUS.md`` section 64, DEC-0236 to DEC-0239,
OD-112, ``docs/b2c_merge/28_BUILD_RC24_RECORD.md``). It changed screens: the legal-entity
name on Settings, the staff login footer (English and Vietnamese) and the demo label sender
read "Solaris Express Inc." (I-10, DEC-0236), and the draft invoice editor's tax sentence
uses the invoice's summary labels (I-11, DEC-0239); I-1 and I-12 were confirmed as built
(DEC-0237, DEC-0238). It added the data-only migration ``e7a9c1d3f5b6`` (new Alembic head,
no table or column change), which renames an ``organization_settings.legal_entity_name``
still holding exactly the old default "Soleil Global Transportation Inc." and leaves any
other value alone; the model default changed with it. It changed no route (273), no
permission (55), no public tracking, Customer Account or other response field (every
Pydantic model under ``app`` has the same field set at ``3151095`` and ``f4a04a3``) and no
dependency. Against this tree RC-UAT-23 drifts on the Alembic head only
(``d4f6b8c0e2a5`` recorded, ``e7a9c1d3f5b6`` measured).

**RC-UAT-24 was superseded by RC-UAT-25 on 2026-10-25, measured at ``bccbddf``**: the fix
pack for Ben's live UAT of 2026-10-25 (``PROJECT_STATUS.md`` section 65, DEC-0240 to DEC-0247,
OD-113, ``docs/b2c_merge/29_BUILD_RC25_RECORD.md``). It changed screens: a red asterisk instead
of "(required)" on required labels (DEC-0240), the declared value currency a list of CAD and
VND (DEC-0241), saved addresses for the recipient (DEC-0242), "Received at warehouse"
(DEC-0244), the blank Financials tab fixed at its cause with an error boundary around every
shipment tab (DEC-0246) and a Quote and invoice card (DEC-0247). The customer can no longer
change the sign-in email; an Admin does (DEC-0243, withdrawing DEC-0231's self-service change),
and Admin and Operations can correct a recorded or published timeline event (DEC-0245). It
added the migration ``a5c7e9b1d3f6`` (new Alembic head; two new tables,
``customer_account_email_changes`` and ``shipment_event_revisions``; nothing existing altered)
and four staff routes, 273 to 277: ``POST /customer-account/identities/{ref}/sign-in-email``
(the review set 21 to 22), ``POST /shipments/{id}/events/edit``, ``GET
/shipments/{id}/event-revisions`` and ``GET /shipments/{id}/financial-summary``; the customer's
three email-change routes stay mounted and refuse, so the Customer Account counts (26,
mutations 18) are unchanged. Permissions 55, the same set; public tracking 25 and Customer
Account 18 / 26 / 18 unchanged. Pydantic models under ``app`` 330 to 337: ``EmailChangeRequest``
removed, eight added (the sign-in email request, the financial summary and its four parts, the
event edit and its revision), ``IdentityStatusOut`` 13 to 14 (``can_change_sign_in_email``);
``GET /shipments/meta`` gains ``declared_value_currencies``. No dependency changed. Against
this tree RC-UAT-24 drifts on the Alembic head only (``e7a9c1d3f5b6`` recorded,
``a5c7e9b1d3f6`` measured): none of the ten checks counts routes or hashes application code.

What it checks, and why each one is here
----------------------------------------
The four invariants the phase brief names are the ones that must not move while provider
work is deferred (DEC-0075):

* the production adapter registry is empty -- no provider is registered;
* both integration resource allowlists are empty -- no host and no path prefix may be
  fetched, so no external request can be constructed;
* the public tracking contract is exactly the recorded field count (25 since RC-UAT-19
  added ``carrier_links``; 24 before) -- nothing has been added to what a stranger can see,
  and no reserved freshness field has appeared;
* the tracking source vocabulary is exactly `manual` and `external_link` -- `connected_api`
  is still refused.

It also checks the Alembic head and the two dependency-lock digests, because a baseline
that silently migrated or re-resolved its dependencies is not the thing that was tested.

What it deliberately does **not** check
---------------------------------------
Test counts. They change whenever a test is added -- including by adding a guard like this
one -- so asserting them here would make the guard fail for the one reason that is not a
regression. The counts are recorded in the baseline as measured evidence and are re-measured
by running the suites, which is the only honest way to confirm them.

This script makes no network request, starts no server, and writes nothing.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/verify_rc_baseline.py
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --json report.json
    # The superseded baselines, all twenty-four still verifiable:
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_1_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_2_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_3_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_4_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_5_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_6_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_7_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_8_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_9_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_10_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_11_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_12_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_13_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_14_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_15_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_16_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_17_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_18_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_19_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_20_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_21_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_22_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_23_BASELINE.json
    backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline \
        docs/RC_UAT_24_BASELINE.json

Exit status is 0 when every check matches and 1 when anything drifted. A superseded
baseline is *expected* to drift -- that is what superseded means -- and the drift it
reports is the evidence of what changed since it was frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
#: The baseline in force. The earlier ones remain on disk as superseded records and are
#: never edited -- that is what makes them independently checkable.
BASELINE_PATH = REPO_ROOT / "docs" / "RC_UAT_25_BASELINE.json"
SUPERSEDED_BASELINE_PATHS = (
    REPO_ROOT / "docs" / "RC_UAT_1_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_2_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_3_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_4_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_5_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_6_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_7_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_8_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_9_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_10_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_11_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_12_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_13_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_14_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_15_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_16_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_17_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_18_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_19_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_20_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_21_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_22_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_23_BASELINE.json",
    REPO_ROOT / "docs" / "RC_UAT_24_BASELINE.json",
)

sys.path.insert(0, str(BACKEND_ROOT))  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.enums import PHASE_2_TRACKING_SOURCE_MODES, TrackingSourceMode  # noqa: E402
from app.integrations import registry  # noqa: E402
from app.schemas.public_tracking import PublicTrackingResult  # noqa: E402


class Check:
    """One measured value against its frozen counterpart."""

    def __init__(self, name: str, expected: object, actual: object) -> None:
        self.name = name
        self.expected = expected
        self.actual = actual

    @property
    def ok(self) -> bool:
        return self.expected == self.actual

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.name,
            "expected": self.expected,
            "actual": self.actual,
            "ok": self.ok,
        }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alembic_head() -> str:
    """The single head revision, read from the migration files rather than the database.

    Reading the database would report where *a* database happens to be, which is a property
    of that file and not of this commit. The revision graph is the baseline.
    """
    versions = BACKEND_ROOT / "alembic" / "versions"
    revisions: dict[str, str | None] = {}
    for migration in versions.glob("*.py"):
        source = migration.read_text(encoding="utf-8")
        revision = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", source, re.M)
        down = re.search(
            r"^down_revision(?::\s*[^=]+)?\s*=\s*(?:['\"]([^'\"]+)['\"]|None)", source, re.M
        )
        if revision:
            revisions[revision.group(1)] = down.group(1) if down and down.group(1) else None

    parents = {down for down in revisions.values() if down}
    heads = sorted(rev for rev in revisions if rev not in parents)
    if len(heads) != 1:
        return f"<{len(heads)} heads: {', '.join(heads)}>"
    return heads[0]


def uat_case_count() -> int:
    """Count case headings, which are `### UAT-<role>-<number> — title`.

    Counted from the headings rather than every mention, because the ids also appear in
    cross-references and in the summary sheet.
    """
    cases = REPO_ROOT / "docs" / "UAT" / "UAT_CASES.md"
    if not cases.exists():
        return -1
    found = re.findall(r"^#{2,4}\s+(UAT-[A-Z]{2}-\d+)", cases.read_text(encoding="utf-8"), re.M)
    return len(set(found))


def collect(baseline: dict) -> list[Check]:
    invariants = baseline["invariants"]
    locks = baseline["dependency_locks"]

    checks = [
        Check(
            "public tracking contract fields",
            invariants["public_contract_fields"],
            len(PublicTrackingResult.model_fields),
        ),
        Check(
            "production adapters registered",
            invariants["production_adapters"],
            len(registry.PRODUCTION_ADAPTERS),
        ),
        Check(
            "integration resource host allowlist",
            invariants["integration_resource_host_allowlist"],
            len(settings.integration_resource_host_list),
        ),
        Check(
            "integration resource path-prefix allowlist",
            invariants["integration_resource_path_prefix_allowlist"],
            len(settings.integration_resource_path_prefix_list),
        ),
        Check(
            "tracking source modes",
            sorted(invariants["tracking_source_modes"]),
            sorted(mode.value for mode in PHASE_2_TRACKING_SOURCE_MODES),
        ),
        Check(
            "connected_api excluded from the tracking vocabulary",
            True,
            TrackingSourceMode.CONNECTED_API not in PHASE_2_TRACKING_SOURCE_MODES,
        ),
        Check("alembic head", baseline["alembic_head"], alembic_head()),
    ]

    for relative, digest in locks.items():
        path = REPO_ROOT / relative
        checks.append(
            Check(f"lock digest {relative}", digest, sha256(path) if path.exists() else "<missing>")
        )

    checks.append(
        Check("UAT cases", baseline["test_counts"]["uat_cases"], uat_case_count()),
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the release-candidate baseline has not drifted."
    )
    parser.add_argument("--json", type=Path, help="Write the full report to this path.")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help=(
            "Baseline file to verify against. Defaults to the baseline in force "
            f"({BASELINE_PATH.name}); pass "
            f"{' or '.join(path.name for path in SUPERSEDED_BASELINE_PATHS)} "
            "to re-check a superseded one."
        ),
    )
    args = parser.parse_args(argv)

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    checks = collect(baseline)
    drifted = [check for check in checks if not check.ok]

    width = max(len(check.name) for check in checks)
    print(f"RC baseline: {baseline['identifier']}  (pre-release: {baseline['is_prerelease']})")
    print(f"measured at: {baseline['measured_at_commit']}")
    print()
    for check in checks:
        status = "ok  " if check.ok else "DRIFT"
        print(f"  {status}  {check.name:<{width}}  {check.actual!r}")
        if not check.ok:
            print(f"  {'':<5}  {'':<{width}}  expected {check.expected!r}")

    print()
    if drifted:
        print(f"{len(drifted)} of {len(checks)} checks drifted from the frozen baseline.")
    else:
        print(f"All {len(checks)} checks match the frozen baseline.")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "identifier": baseline["identifier"],
                    "measured_at_commit": baseline["measured_at_commit"],
                    "drifted": bool(drifted),
                    "checks": [check.as_dict() for check in checks],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return 1 if drifted else 0


if __name__ == "__main__":
    raise SystemExit(main())
