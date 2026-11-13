"""Report routes (CRM.md section 12, Design.md section 12).

Thin, like every other route module: validate the period, authorize, delegate to
``report_service``, return. Every business rule lives in the service so the API, the CSV
export, and the tests all apply the same definition.

Authorization is declared here and enforced by ``require(...)``. ``report:read`` opens the
page; the financial report is gated structurally inside the service, which omits it
entirely rather than returning it masked.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, OrgSettings, Thresholds, require
from app.core.permissions import Permission
from app.models import User
from app.schemas.report import ReportSetOut, ReportTableOut
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])

ReportReader = Annotated[User, Depends(require(Permission.REPORT_READ))]


@router.get("/definitions")
def report_definitions(user: ReportReader) -> dict:
    """What this caller may ask for, and what each figure means.

    Served separately from the data so the interface can render a definition tooltip
    without running eight aggregate queries, and so a role learns which reports exist for
    it without inferring that from an empty payload.
    """
    return {
        "available_reports": list(report_service.available_report_keys(user.role)),
        "max_period_days": report_service.MAX_PERIOD_DAYS,
        "granularity_rule": {
            "day": f"up to {report_service.DAY_MAX_SPAN} days",
            "week": f"up to {report_service.WEEK_MAX_SPAN} days",
            "month": "longer ranges",
        },
        "qualifying_shipment": (
            "A confirmed booking with a recorded first physical handoff, not cancelled and "
            "not a return. Counted once at the shipment level: packages and transport legs "
            "are never counted as additional shipments."
        ),
        "period_rule": (
            "Periods are half-open and cut at local midnight in the organization's "
            "configured timezone, then converted to UTC for the query."
        ),
        "comparison_rule": (
            "No prior-period comparison, trend arrow, or percentage change is computed. "
            "A change figure is only meaningful against a comparable prior period."
        ),
    }


@router.get("", response_model=ReportSetOut)
def read_reports(
    db: DbSession,
    org: OrgSettings,
    thresholds: Thresholds,
    user: ReportReader,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    route_group: list[str] | None = Query(default=None),
    report: list[str] | None = Query(default=None),
) -> ReportSetOut:
    """Every report the caller is entitled to, over one validated period.

    ``report`` narrows the set. Asking for a report this role may not see is a validation
    error naming an unknown report, not a 403: a caller without ``financial:read`` should
    not learn that a financial report exists.
    """
    period = report_service.resolve_period(from_date=from_date, to_date=to_date, org=org)
    keys = report or list(report_service.available_report_keys(user.role))

    tables = [
        report_service.build_report(
            db,
            key,
            period=period,
            thresholds=thresholds,
            route_groups=route_group,
            role=user.role,
        )
        for key in keys
    ]

    return ReportSetOut(
        period=period.to_dict(),
        route_groups=route_group,
        reports=[ReportTableOut(**table.to_dict()) for table in tables],
        coverage_notes=report_service.coverage_notes(db, period, route_group),
        counting_guard=report_service.package_and_leg_guard(db, period, route_group),
        available_reports=list(report_service.available_report_keys(user.role)),
    )
