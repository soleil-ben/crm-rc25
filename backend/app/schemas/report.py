"""Report response schemas (Phase 5A).

The financial report is absent from ``reports`` for a caller without ``financial:read``,
and its ``recorded_cost`` column is absent for a caller without ``financial_cost:read``.
That is why report rows are typed as free-form mappings rather than a fixed model: a
missing key must actually be missing, and a Pydantic model with an optional field would
serialize it as ``null``, which tells the caller the field exists (CRM.md section 11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReportColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    kind: str


class ReportTableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    title: str
    #: ``period`` or ``current``.
    scope: str
    definition: str
    columns: list[ReportColumnOut]
    rows: list[dict[str, Any]]
    notes: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ReportPeriodOut(BaseModel):
    from_date: str
    to_date: str
    timezone: str
    start_utc: datetime
    end_utc: datetime
    granularity: str
    days: int


class ReportSetOut(BaseModel):
    """Every report the caller is entitled to, over one validated period."""

    period: ReportPeriodOut
    route_groups: list[str] | None = None
    reports: list[ReportTableOut]
    #: Notes about what the underlying data can and cannot support.
    coverage_notes: list[str] = Field(default_factory=list)
    #: Context proving shipments are counted once (AC-14).
    counting_guard: dict[str, Any] = Field(default_factory=dict)
    #: Report keys this caller may request. A key absent here does not exist for them.
    available_reports: list[str] = Field(default_factory=list)
