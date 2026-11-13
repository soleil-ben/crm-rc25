"""Customer Account identity, sessions, tokens, acknowledgements and proposals.

Nine tables, and the first thing to say about them is what they are *not*: none of them is
a staff table, none of them holds a role or a permission, and none of them gives a customer
a row in ``users`` (OD-23, DEC-0090). The second thing is that **none of them is canonical
customer data**. A registration writes an identity and a proposal; a person decides
afterwards whether any of it becomes a `customers` row, in Phase 10, through the existing
customer service (OD-23, DEC-0092).

Table-by-table purpose, primary key, uniqueness, foreign keys, indexes, retention class and
audit implication are on each class. The whole-schema view is
`docs/customer_account/DATA_MODEL.md`, and the one place they differ --
`customer_registration_attempts`, which that document does not propose -- is reconciled in
`PROJECT_STATUS.md` section 17.4.

**Three canonical columns are deliberately absent.** `FIELD_MATRIX.md` section 6 names a
display name, a legal name distinct from it, and a billing address role as things the CRM
has no column for. The owner's Phase 9 instruction says not to add them here, and to carry
those values in the pending-proposal representation until their canonical treatment is
decided. So `customers` is untouched by this phase and the three live as allowlisted
proposal field keys (DEC-0096).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.account_enums import (
    IdentityStatus,
    LinkRole,
    NotificationChannel,
    ProposalStatus,
)
from app.models.base import Base, TimestampMixin


class CustomerIdentity(TimestampMixin, Base):
    """The account. One row per registered email address.

    **Purpose.** Hold a customer's credential and the state of their application, and
    nothing else. There is no name, no phone, no address and no `customer_id` here: the
    account is not the customer, and conflating the two is how a bug in customer-facing
    code reaches the CRM.

    **Primary key.** Surrogate ``id``. Never serialized -- ``public_id`` is the reference a
    customer or a staff member quotes.

    **Uniqueness.** ``public_id`` and ``email_normalized``, both unique.
    ``email_normalized`` comes from ``app.core.normalization.normalize_email``, which
    lowercases, so a plain unique constraint *is* the case-insensitive uniqueness strategy
    -- no ``lower()`` index and no collation dependency. ``email_entered`` is kept beside
    it exactly as the staff-facing customer record keeps both (CRM.md section 4).

    **Foreign keys.** Five nullable references to ``users.id``, every one
    ``ON DELETE SET NULL``: who approved, rejected, suspended or deactivated this account
    is history, and deleting a staff row must not delete a customer's account.

    **Indexes.** ``email_normalized`` (the sign-in lookup), ``status`` (the Phase 10
    approval queue), and ``created_at`` from ``TimestampMixin``. Nothing speculative.

    **Retention.** Account-lifecycle record. No deletion schedule exists: OD-01 is open and
    OD-36 aligns this with it (`DATA_MODEL.md` section 10).

    **Audit.** Every state change writes an ``audit_events`` row carrying ``public_id``, a
    reason code and the actor -- never the password hash, never a token, never the address.
    """

    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_customer_identities_public_id"),
        UniqueConstraint("email_normalized", name="uq_customer_identities_email_normalized"),
        Index("ix_customer_identities_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Customer-facing account reference, e.g. ``CA-000001``. Quoted on the phone; safe to
    #: show and safe to log, which is why it and not ``id`` appears in audit payloads.
    public_id: Mapped[str] = mapped_column(String(20), nullable=False)

    email_entered: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    #: Argon2, the same hasher and rehash-on-sign-in policy as staff (DEC-0003). A separate
    #: column in a separate table: the policy is shared, the storage is not.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=IdentityStatus.PENDING_VERIFICATION
    )
    #: Proof of mailbox control. **Not approval**, and deliberately a separate column from
    #: ``status`` so that "verified" can never be inferred from a lifecycle value.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    suspended_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deactivated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: A reason **code**, never prose about the person. Bounded so nobody writes a sentence.
    status_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    failed_sign_in_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Bounded in time and never permanent: a permanent lockout hands an attacker a way to
    #: disable any customer they can name (`RATE_LIMITS_AND_ABUSE.md` section 3.1).
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    #: Vietnamese first, English as an option (OD-71, superseding OD-39's English only).
    #: Registration records the screen language; an identity created without one is ``vi``.
    preferred_language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi")

    sessions: Mapped[list[CustomerSession]] = relationship(
        back_populates="identity", cascade="all, delete-orphan"
    )
    tokens: Mapped[list[CustomerAuthToken]] = relationship(
        back_populates="identity", cascade="all, delete-orphan"
    )


class CustomerIdentityLink(Base):
    """Identity to canonical customer. **No row is written in Phase 9.**

    **Purpose.** Carry the link OD-25 describes in its own table rather than as a nullable
    ``customer_id`` on the identity. A column would satisfy release 1 and fail its second
    sentence: relaxing to company access later would change the shape every ownership check
    reads. With a link table, relaxing it is dropping one index and permitting a second
    ``link_role`` (DEC-0091).

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** Two *partial* unique indexes, both restricted to ``status = 'active'``
    so revoked history accumulates freely: one active link per identity, and one active
    identity per customer. Enforced by index rather than by application code, because an
    application check loses the race that a unique index wins.

    **Foreign keys.** ``identity_id`` ``ON DELETE CASCADE`` -- a link without its account is
    meaningless. ``customer_id`` ``ON DELETE RESTRICT`` -- a linked customer is not deleted
    out from under an account. ``linked_by_user_id`` / ``revoked_by_user_id``
    ``ON DELETE SET NULL``.

    **Indexes.** The two partial unique indexes, plus ``customer_id`` for the Phase 11
    ownership lookup that will read this table on every authenticated request.

    **Retention.** Account-lifecycle record, OD-01 dependent, like the identity.

    **Audit.** ``customer_account.link`` and ``.unlink`` in Phase 10, with actor, identity
    ``public_id``, customer ``public_id`` and the disclosure-preview figures (OD-29).

    The table is created and mapped now, not later, for two reasons: the migration that
    creates the rest of the surface is the right place for it, and a table in the database
    with no model behind it is exactly the shape the autogeneration exclusion exists to
    tolerate for one table only (DEC-0089).
    """

    __tablename__ = "customer_identity_links"
    __table_args__ = (
        # Release 1, encoded twice because it is two different rules.
        Index(
            "uq_customer_identity_links_active_identity",
            "identity_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_customer_identity_links_active_customer",
            "customer_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_customer_identity_links_customer_id", "customer_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    link_role: Mapped[str] = mapped_column(String(20), nullable=False, default=LinkRole.OWNER)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    linked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoke_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)


class CustomerSession(Base):
    """A Customer Account session. A separate table from ``user_sessions``, on purpose.

    **Purpose.** Make a customer's session revocable server-side and carry no grant. The
    browser holds an opaque token; only its digest is here, so a database copy does not
    yield a usable session (DEC-0004).

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** ``session_token_hash``, unique -- also the lookup key.

    **Foreign keys.** ``identity_id`` ``ON DELETE CASCADE``.

    **Indexes.** ``session_token_hash`` (every authenticated request), ``identity_id`` (bulk
    revocation on password reset), ``expires_at`` (sweeping).

    **Retention.** Credential material. Expired and revoked rows are purgeable immediately
    and **do not wait for OD-01** (OD-36).

    **Audit.** Creation and revocation are audited by reason code. The token, its digest and
    the CSRF digest never appear in an audit payload or a log line.

    **No role, no permission snapshot and no cached ``customer_id``.** Authorization re-reads
    the identity on every request, so a suspension takes effect on the next request rather
    than at the next sign-in -- the property Phase 7 established for staff roles, kept here
    deliberately (`SESSION_COOKIES_AND_CSRF.md` section 4).
    """

    __tablename__ = "customer_sessions"
    __table_args__ = (
        UniqueConstraint("session_token_hash", name="uq_customer_sessions_session_token_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Bound to *this* row, so a CSRF token from another session -- or from the staff realm
    #: -- satisfies nothing (DEC-0005).
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: The directly observed peer only. A forwarding header is not believed (DEC-0007).
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    identity: Mapped[CustomerIdentity] = relationship(back_populates="sessions")


class CustomerAuthToken(Base):
    """Email-verification and password-reset tokens. One table, one set of rules.

    **Purpose.** Prove mailbox control, and let somebody who has lost their password get
    back in -- without either capability becoming the other.

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** ``token_digest``, unique. The digest is a **keyed** HMAC-SHA256 whose
    message includes the purpose, so the same random token yields different digests for
    verification and for reset. Purpose binding is therefore a property of the
    construction, not only of a ``WHERE purpose = ...`` somebody could forget (T-05,
    DEC-0097).

    **Foreign keys.** ``identity_id`` ``ON DELETE CASCADE``.

    **Indexes.** ``token_digest`` (the only lookup path -- a redemption never searches by
    identity or by address), ``expires_at``, and ``(identity_id, purpose)`` for the
    supersession sweep that runs when a replacement is issued.

    **Retention.** Credential material. Consumed, invalidated and expired rows are purgeable
    immediately, independent of OD-01 (OD-36).

    **Audit.** Purpose and outcome category only. **The plaintext exists in the outbound
    message and nowhere else** -- not in a column, not in a log, not in an audit payload.

    Consumption is a conditional update (``WHERE consumed_at IS NULL``) whose affected-row
    count is checked, so two simultaneous redemptions cannot both succeed on a database with
    no ``SELECT ... FOR UPDATE``.
    """

    __tablename__ = "customer_auth_tokens"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_customer_auth_tokens_token_digest"),
        Index("ix_customer_auth_tokens_identity_purpose", "identity_id", "purpose"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: Hours, not days, and enforced server-side on every redemption.
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Superseded by a newer token of the same purpose, or by a completed password reset.
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidated_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: The address it was sent to, so a later address change cannot redirect an outstanding
    #: token to a mailbox its holder does not control.
    issued_to_email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    identity: Mapped[CustomerIdentity] = relationship(back_populates="tokens")


class CustomerTermsAcknowledgement(Base):
    """Append-only record that a person was shown a document and accepted it (OD-37).

    **Purpose.** Answer, later and defensibly, "which version of which document did this
    person accept, in which language, and when".

    **Primary key.** Surrogate ``id``. **No update path and no delete path exists**: a new
    acknowledgement is a new row. That is the whole design.

    **Uniqueness.** None. Two acknowledgements of the same version are two facts, not a
    duplicate -- somebody who registers, is rejected and registers again accepted it twice.

    **Foreign keys.** ``identity_id`` ``ON DELETE CASCADE``.

    **Indexes.** ``(identity_id, document_kind)``, which is how a reviewer reads it.

    **Retention.** Consent and acknowledgement evidence. Kept; OD-01 dependent (OD-36).

    **Audit.** The registration audit row records the versions accepted, by version string
    -- a short identifier, not the document.
    """

    __tablename__ = "customer_terms_acknowledgements"
    __table_args__ = (
        Index("ix_customer_terms_acknowledgements_identity_kind", "identity_id", "document_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    #: The version identifier presented. Until OD-37 is satisfied this is a placeholder that
    #: names itself as one, and production registration refuses while it is.
    document_version: Mapped[str] = mapped_column(String(40), nullable=False)
    #: What the person actually read, which is not necessarily what they prefer.
    presented_language: Mapped[str] = mapped_column(String(8), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CustomerNotificationPreference(Base):
    """Operational notification preferences, scoped to the identity.

    **Purpose.** Record whether a customer wants operational messages about their own
    shipments. **Marketing consent is not here**: it is a ``consent_events`` row, written
    through the existing consent service at approval, and a preference row can neither
    create one nor weaken one, nor lift a ``contact_suppressions`` row (OD-27, OD-38).

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** ``(identity_id, channel, topic)`` -- one preference per topic per
    channel, so a repeated submission updates rather than accumulates.

    **Foreign keys.** ``identity_id`` ``ON DELETE CASCADE``.

    **Indexes.** The unique constraint is the lookup path; nothing else is needed.

    **Retention.** Account-lifecycle record, OD-01 dependent.

    **Audit.** Preference changes are audited by topic key and boolean, never by address.

    ``account_security`` is not a settable topic (``CUSTOMER_SETTABLE_TOPICS``): a
    preference that could suppress a verification or reset message would be a preference
    that locks people out of their own account.
    """

    __tablename__ = "customer_notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "identity_id",
            "channel",
            "topic",
            name="uq_customer_notification_preferences_identity_channel_topic",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NotificationChannel.EMAIL
    )
    topic: Mapped[str] = mapped_column(String(40), nullable=False)
    #: **Unchecked by default** (OD-38). A row exists only because somebody chose.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CustomerDataProposal(Base):
    """What the customer says about themselves, before a person agrees.

    **Purpose.** Hold submitted customer data outside the canonical tables. This is the
    structural reason a bug in customer-facing code cannot corrupt the CRM: the worst
    outcome available to it is a bad proposal that somebody declines (DEC-0092).

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** None at the proposal level -- an identity legitimately has a history of
    them. The ``(proposal_id, field_key)`` uniqueness lives on the field rows.

    **Foreign keys.** ``identity_id`` ``ON DELETE CASCADE``; ``customer_id``
    ``ON DELETE SET NULL`` and **null for a registration proposal, which is the point --
    there is no customer yet**; ``reviewed_by_user_id`` and ``applied_audit_event_id``
    ``ON DELETE SET NULL``; ``supersedes_proposal_id`` ``ON DELETE SET NULL``.

    **Indexes.** ``(identity_id, status)`` -- the customer's own history and the Phase 10
    queue read exactly that pair.

    **Retention.** Account-lifecycle record. A withdrawn or rejected proposal is retained as
    history, not deleted (`STATE_MACHINES.md` section 4).

    **Audit.** ``customer_data_proposal.submit`` records the identity and the **field keys**
    -- never the submitted values, which are the customer's personal data and are already
    stored, once, on the field rows.
    """

    __tablename__ = "customer_data_proposals"
    __table_args__ = (Index("ix_customer_data_proposals_identity_status", "identity_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ProposalStatus.PENDING)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Staff-facing result of the existing duplicate review. **Never serialized to a
    #: customer** -- disclosing it would confirm that another record exists (T-02).
    duplicate_review_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    applied_audit_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("audit_events.id", ondelete="SET NULL"), nullable=True
    )
    #: Versioning by immutability: field rows are never rewritten, so a newer submission is
    #: a new proposal that points back at the one it replaced. A reviewer can read the chain.
    supersedes_proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_data_proposals.id", ondelete="SET NULL"), nullable=True
    )

    fields: Mapped[list[CustomerDataProposalField]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )


class CustomerDataProposalField(Base):
    """One allowlisted, typed field of a proposal.

    **Purpose.** Store submitted customer data as *fields*, not as a blob. A JSON column
    would accept anything the client sent, which is the same as having no allowlist: the
    key set is the schema, and it is checked at the API boundary before a row exists.

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** ``(proposal_id, field_key)``.

    **Foreign keys.** ``proposal_id`` ``ON DELETE CASCADE``.

    **Indexes.** The unique constraint; a proposal is always read whole.

    **Retention.** Account-lifecycle record, with the caveat that these rows hold personal
    data and are the reason the proposal tables are named in the retention categories
    `DATA_MODEL.md` section 10 asks legal review to rule on.

    **Audit.** Field **keys** only.

    ``value_type`` records the type the boundary enforced, so a Phase 10 reviewer reads a
    typed value rather than inferring one from the key. ``proposed_value`` is what the
    person typed; ``proposed_value_normalized`` is what
    ``app.core.normalization`` made of it, which is what later duplicate review compares.
    ``current_value_at_submission`` is null for a registration proposal -- there is no
    canonical record to have drifted from yet.
    """

    __tablename__ = "customer_data_proposal_fields"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id",
            "field_key",
            name="uq_customer_data_proposal_fields_proposal_id_field_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("customer_data_proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(String(60), nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    proposed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_value_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_value_at_submission: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Per field, because an approver may accept some and decline others (OD-28).
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    proposal: Mapped[CustomerDataProposal] = relationship(back_populates="fields")


class CustomerRegistrationAttempt(Base):
    """The idempotency and concurrency claim for a public registration.

    **Purpose.** Make registration idempotent and make concurrent equivalent registrations
    resolve to one identity, on a database with no ``SELECT ... FOR UPDATE``. This is the
    shape ``booking_confirmations`` already uses for the same problem (DEC-0031): a unique
    key claims the operation, and a fingerprint catches one key reused for different data.

    Not proposed by `DATA_MODEL.md`; reconciled in `PROJECT_STATUS.md` section 17.4 and
    recorded as DEC-0098.

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** ``idempotency_key_digest``, unique -- the claim. Also
    ``(email_key, window_start)`` is *not* unique: suppression of repeat work per address is
    a rate-limit concern, not a constraint, because making it a constraint would turn a
    second registration attempt for an address into an error that differs from the first
    one, and the two must be indistinguishable.

    **Foreign keys.** ``identity_id`` ``ON DELETE SET NULL`` -- the attempt is a record of a
    request, and it outlives the identity it may have created.

    **Indexes.** ``idempotency_key_digest`` (unique, the claim), ``email_key`` (abuse
    analysis), ``created_at`` (purging).

    **Retention.** Security event log. Purgeable on a short schedule; holds no address, no
    body and no token.

    **Audit.** The attempt row *is* the operational record; the audit row carries the
    outcome category and the hashed address key.

    **No raw address, no payload, no token.** ``email_key`` is a keyed digest of the
    normalized address and ``request_fingerprint`` is a digest of the canonicalized
    submitted fields -- enough to tell "same request again" from "same key, different data",
    and not enough to reconstruct either.
    """

    __tablename__ = "customer_registration_attempts"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key_digest",
            name="uq_customer_registration_attempts_idempotency_key_digest",
        ),
        Index("ix_customer_registration_attempts_email_key", "email_key"),
        Index("ix_customer_registration_attempts_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: A digest of the caller-supplied key, so a key that happened to be a personal string
    #: is not stored verbatim.
    idempotency_key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Keyed digest of ``email_normalized``. Never the address.
    email_key: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Digest of the canonicalized submitted fields. One key reused with different data is a
    #: conflict, not a silent replay of an unrelated registration.
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    #: An ``account_enums.RegistrationOutcome``. Internal; never serialized.
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CustomerAccountDisclosureAcknowledgement(Base):
    """A staff member saw the history-disclosure preview and said so. Phase 10.

    **Purpose.** OD-29 requires that before an account is approved, staff see how many
    historical shipments become visible, their oldest and newest dates, and whether
    cancelled and rebooked shipments are included -- and **explicitly acknowledge** it.
    An acknowledgement that lived only in the request that made it would be no
    acknowledgement at all: the approval is a separate request, and the thing it has to
    check is that this actor saw *these* figures for *this* intended action.

    So the row stores the figures that were shown, not a boolean. If the approval's
    recomputed fingerprint does not match the one recorded here, the acknowledgement is
    not usable and a fresh preview must be taken (`THREAT_MODEL.md` T-06).

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** None. Acknowledging twice is two facts, and a reviewer who reloads the
    preview after a customer edit legitimately acknowledges a second, different set of
    figures.

    **Foreign keys.** ``identity_id`` and ``proposal_id`` ``ON DELETE CASCADE``;
    ``customer_id`` ``ON DELETE SET NULL`` -- null for a create-new acknowledgement,
    because there is no customer yet; ``acknowledged_by_user_id`` ``ON DELETE SET NULL``.

    **Indexes.** ``(identity_id, preview_fingerprint)``, which is the only lookup the
    approval performs.

    **Retention.** Account-lifecycle record, OD-01 dependent. It is the evidence for
    OD-29, so it is kept as long as the approval it justifies.

    **Audit.** ``customer_account.disclosure_acknowledged`` carries the same five figures.
    The row and the audit entry duplicate each other deliberately: the row is what the
    approval *checks*, the audit entry is what a reviewer *reads*.

    **No shipment reference is stored here**, and none is available to store: the
    disclosure calculation returns counts and two dates and never loads a shipment row.
    """

    __tablename__ = "customer_account_disclosure_acknowledgements"
    __table_args__ = (
        Index(
            "ix_cadisclosure_ack_identity_fingerprint",
            "identity_id",
            "preview_fingerprint",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("customer_data_proposals.id", ondelete="CASCADE"), nullable=False
    )
    #: An ``account_enums.ApprovalAction``. An acknowledgement of a create-new preview does
    #: not authorize a link, and the fingerprint would not match even if this were absent.
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The intended link target. Null for ``create_new``.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    #: The five OD-29 figures, stored as they were shown.
    disclosed_shipment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    oldest_booked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    newest_booked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    includes_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    includes_rebooked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Which definition of "qualifying shipment" produced those figures. A later change to
    #: the rule bumps this, and an acknowledgement taken under the old one stops matching.
    disclosure_definition_version: Mapped[str] = mapped_column(String(40), nullable=False)

    #: The server-computed digest of every material fact. Not a credential and not
    #: reversible: it is a comparison value, and the facts it covers are listed in
    #: ``app.services.customer_account_review_service``.
    preview_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class CustomerAccountApprovalAttempt(Base):
    """The idempotency and concurrency claim for a staff approval or rejection. Phase 10.

    **Purpose.** Make approval idempotent on retry and make concurrent approvals resolve to
    one outcome, on a database with no ``SELECT ... FOR UPDATE``. The same shape
    ``booking_confirmations`` and ``customer_registration_attempts`` already use
    (DEC-0031, DEC-0098): a unique key claims the operation, and a fingerprint catches one
    key reused for different data.

    **Primary key.** Surrogate ``id``.

    **Uniqueness.** ``idempotency_key_digest``, unique -- the claim itself. The insert is
    the serialization point: whoever inserts first owns the operation, and a second
    inserter gets an ``IntegrityError`` rather than a second approval.

    **Foreign keys.** ``identity_id`` ``ON DELETE CASCADE``; ``customer_id`` and
    ``actor_user_id`` ``ON DELETE SET NULL``.

    **Indexes.** The unique constraint, plus ``identity_id`` for reading an account's
    decision history and ``created_at`` for purging.

    **Retention.** Security event log. Purgeable on a short schedule; it holds no address,
    no payload and no token.

    **Audit.** The row is the operational record of the attempt; the audit entry carries
    the outcome and the reason code. A replay writes an audit entry saying it was a replay
    and **writes nothing else** -- no second customer, no second link, no second message.

    ``request_fingerprint`` digests the action and the target, so the same key presented
    with a different action or a different customer is a conflict rather than a silent
    replay of an unrelated decision.
    """

    __tablename__ = "customer_account_approval_attempts"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key_digest",
            name="uq_ca_approval_attempts_idempotency_key_digest",
        ),
        Index("ix_ca_approval_attempts_identity_id", "identity_id"),
        Index("ix_ca_approval_attempts_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: A digest of the caller-supplied key, so a key that happened to be a personal string
    #: is not stored verbatim.
    idempotency_key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_identities.id", ondelete="CASCADE"), nullable=False
    )
    #: An ``account_enums.ApprovalAction`` for an approval, or ``"reject"``.
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    #: Digest of the action and target. One key reused with different data is a conflict.
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    #: An ``account_enums.ApprovalOutcome``. Internal; never serialized as such.
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
