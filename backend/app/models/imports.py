"""Import batch provenance (Phase 5A, DEC-0078).

Two tables, and **neither of them stores a cell value from an imported file.** They hold
counts, outcomes, row numbers, and the source key that makes a retry safe. The raw upload
is parsed in memory and never written anywhere: a staging table full of un-reviewed
personal data would be a second copy of the customer database with none of its access
controls (CRM.md section 11).

A batch row exists only for a **committed** import. A preview writes nothing at all, so an
abandoned preview leaves no trace.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

#: The ``source_system`` recorded for a customer created by a CSV import that did not
#: name its own source system. Paired with ``source_record_id`` it is the idempotency key
#: that stops a re-import creating a second copy of the same person.
CSV_SOURCE_SYSTEM = "csv_import"


class ImportBatch(TimestampMixin, Base):
    """One committed import.

    ``file_name`` is operator-supplied metadata about the upload, not content from it.
    ``content_sha256`` is the digest of the exact bytes that were committed, which is what
    lets the interface refuse a commit of a file the operator did not preview.
    """

    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_import_batches_public_id"),
        Index("ix_import_batches_committed_at", "committed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(20), nullable=False)

    #: What was imported. Only ``customers`` exists in Phase 5A; shipment import is
    #: deferred, and the column exists so adding one later is not a migration of this
    #: table.
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="customers")

    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system: Mapped[str] = mapped_column(
        String(60), nullable=False, default=CSV_SOURCE_SYSTEM
    )

    #: How a row that matched an existing record by source key was treated. Recorded per
    #: batch because it is a deliberate operator choice and the audit trail has to show
    #: which one was made.
    conflict_policy: Mapped[str] = mapped_column(String(30), nullable=False, default="skip")

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    committed_at: Mapped[datetime] = mapped_column(nullable=False)
    committed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    rows: Mapped[list[ImportBatchRow]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportBatchRow(Base):
    """What happened to one row of one committed import.

    Row number, outcome, a reason code, the resulting customer, and the source key. No
    name, no email, no phone, no address — the point of this table is to make a retry safe
    and a summary durable, not to keep a copy of the file.
    """

    __tablename__ = "import_batch_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_import_batch_rows_batch_id_row_number"),
        Index("ix_import_batch_rows_outcome", "batch_id", "outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 1-based, as the operator sees it in the spreadsheet: the header is row 1.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    #: ``created`` | ``matched`` | ``skipped`` | ``rejected``.
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    #: A short machine-readable code such as ``missing_contact`` or
    #: ``duplicate_not_reviewed``. Never a message containing a value from the file.
    reason_code: Mapped[str | None] = mapped_column(String(60), nullable=True)

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: The key this row was reconciled on. Either the file's own ``source_record_id`` or
    #: a digest of the row's normalized identity fields — never the identity itself.
    source_record_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    batch: Mapped[ImportBatch] = relationship(back_populates="rows")
