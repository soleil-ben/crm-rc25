"""Import request and response schemas (Phase 5A).

The preview response is the one place imported values are echoed back. They go to the
person who uploaded the file, over an authenticated request, so they can see what the
parse understood before anything is written. They are never stored, never logged, and
never written to an audit payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportFieldOut(BaseModel):
    field: str
    headers: list[str]
    required: bool
    allowed_values: list[str] | None = None


class ImportFieldsOut(BaseModel):
    fields: list[dict[str, Any]]
    template_headers: list[str]
    conflict_policies: list[str]
    limits: dict[str, int]
    notes: list[str]


class RowIssueOut(BaseModel):
    field_name: str
    code: str
    message: str


class DuplicateCandidateOut(BaseModel):
    customer_id: int
    public_id: str
    full_name: str
    city: str | None = None
    country_code: str | None = None
    matched_on: list[str]
    confidence: int


class PreviewRowOut(BaseModel):
    row_number: int
    #: ``new`` | ``exact_match`` | ``duplicate_review`` | ``rejected``.
    classification: str
    values: dict[str, str | None]
    issues: list[RowIssueOut] = Field(default_factory=list)
    matched_customer_id: int | None = None
    matched_customer_public_id: str | None = None
    duplicate_candidates: list[DuplicateCandidateOut] = Field(default_factory=list)
    source_record_id: str | None = None
    #: What a commit would do to this row if no further decision is made.
    default_action: str


class ImportPreviewOut(BaseModel):
    """The result of a preview. **Nothing has been written when this is returned.**"""

    #: Digest of the exact bytes previewed. The commit must be handed the same file.
    content_sha256: str
    file_name: str | None = None
    row_count: int
    headers: list[str]
    raw_headers: list[str]
    unmapped_headers: list[str]
    rows: list[PreviewRowOut]
    counts: dict[str, int]
    notes: list[str]


class ImportCommitRowOut(BaseModel):
    row_number: int
    outcome: str
    reason_code: str | None = None
    customer_id: int | None = None
    customer_public_id: str | None = None


class ImportCommitOut(BaseModel):
    batch_public_id: str
    created: int
    matched: int
    skipped: int
    rejected: int
    row_count: int
    conflict_policy: str
    rows: list[ImportCommitRowOut]


class ImportBatchRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    outcome: str
    reason_code: str | None = None
    customer_id: int | None = None
    source_record_id: str | None = None


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    kind: str
    file_name: str | None = None
    content_sha256: str
    source_system: str
    conflict_policy: str
    row_count: int
    created_count: int
    matched_count: int
    skipped_count: int
    rejected_count: int
    committed_at: datetime
    committed_by_user_id: int | None = None
    rows: list[ImportBatchRowOut] = Field(default_factory=list)
