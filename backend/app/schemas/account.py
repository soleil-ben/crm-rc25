"""Customer Account request and response models. Standalone, allowlisted, forbidding.

Every model here obeys four rules, and they are the rules Phase 3 already applies to
``app/schemas/public_tracking.py`` for the same reason (OD-31, DEC-0093):

* it **inherits from nothing** in ``app.schemas`` -- not a staff schema, not a public one;
* it sets ``from_attributes=False``, so an ORM object can never be handed to it and a
  customer row cannot be serialized by accident;
* it sets ``extra="forbid"``, so a field added to a service and passed along by mistake is
  an error rather than a disclosure;
* every value is assigned explicitly by a route, field by field, from an allowlist.

The reason is worth restating because it looks like ceremony: an internal schema gains
fields over time, and a model that inherits one silently starts publishing them. The whole
point of declaring these separately is that no other surface can move them by accident.

**What is deliberately absent from every response here**: an internal row id, a password or
anything about one, a token or a token digest, a session identifier, a CSRF digest, a
duplicate score or match count, a customer-link candidate, any audit internal, any staff
name or role, any integration state, and anything that says whether an address is
registered. `tests/test_account_privacy.py` asserts all of that recursively over the raw
JSON, with planted sentinels, rather than trusting this docstring.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AccountModel(BaseModel):
    """Base for Customer Account payloads.

    ``from_attributes`` is off and ``extra`` is forbidden. Both are inherited by every model
    below, and `tests/test_account_boundary.py` asserts it over the module's exported models
    rather than over this class, so a model that sets its own ``model_config`` and gets it
    wrong still fails.
    """

    model_config = ConfigDict(from_attributes=False, extra="forbid")


# --- Requests ----------------------------------------------------------------
#
# These are validated by hand inside the route rather than declared as FastAPI body models.
# A body model is validated *before* the endpoint body runs, which would let a malformed
# request skip the rate limiter and answer with a detailed 422 naming the constraint -- the
# same mistake Phase 3 corrected on the public surface (DEC-0059). They are still declared
# here because they are the contract, and because the route parses against them.


class RegistrationRequest(AccountModel):
    """The registration body. ``fields`` is checked against the allowlist, not against this.

    ``customer`` holds the submitted customer data as a flat map of allowlisted keys. It is
    typed as ``dict[str, object]`` here on purpose: the type check that matters is
    ``app.core.account_fields.normalize_field``, which knows what each key *is*, and a
    second partial type declaration here would be a second place to keep in step.
    """

    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    #: The password typed a second time (UAT round 8). Optional in the type so its absence
    #: is refused by the route with a sentence naming the field, not a generic 422.
    password_confirmation: str | None = Field(default=None, max_length=200)
    #: Both must be present and true. Absent is refused (OD-37); there is no default.
    accept_terms: bool
    accept_privacy: bool
    customer: dict[str, object] = Field(default_factory=dict)
    #: "Billing address is the same as the address above" (UAT rounds 8, 9). When true the
    #: route copies the pickup address into ``billing_address.*`` and refuses any billing
    #: key sent alongside it; when false the billing address needs the same four parts
    #: (postal code optional since UAT round 11). The form starts with the box ticked, and
    #: since UAT round 12 so does the API (DEC-0166): a client that omits the flag gets the
    #: address copied, and one that sends a billing address must also send ``false``.
    billing_same_as_shipping: bool = True
    #: Operational topics the customer switched **on**. Absent means off: unchecked by
    #: default, and the absence is the answer (OD-38).
    notification_topics: list[str] = Field(default_factory=list)
    #: Caller-supplied idempotency key. Optional; the route mints one when it is absent, so
    #: a client that does not send one still cannot create two identities by double-click.
    idempotency_key: str | None = Field(default=None, max_length=120)


class SignInRequest(AccountModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class VerifyEmailRequest(AccountModel):
    token: str = Field(max_length=200)


class ResendVerificationRequest(AccountModel):
    email: str = Field(max_length=320)


class PasswordForgotRequest(AccountModel):
    email: str = Field(max_length=320)


class PasswordResetRequest(AccountModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=200)
    #: Refused by the route when absent or different (UAT round 8), as at registration.
    password_confirmation: str | None = Field(default=None, max_length=200)


# --- Responses ---------------------------------------------------------------


class AccountMessageResponse(AccountModel):
    """The generic answer. One shape, one message, whatever happened.

    Registration, resend and forgot-password all return this, and they return the **same
    instance of the same sentence** whether the address is new, already registered, verified,
    approved, suspended, suppressed, or refused by a rate limit. It carries no identifier and
    no state, because any field that varied would be the field that told two cases apart
    (T-02, T-16).
    """

    message: str


class AccountSessionResponse(AccountModel):
    """What a successful sign-in returns.

    ``csrf_token`` is here for a client that cannot read the readable cookie, exactly as the
    staff login response carries one. It is the value the browser already holds, not a
    second secret, and it is **not** the session token -- that only ever exists in the
    HttpOnly cookie.

    ``status`` is the identity's own lifecycle state. A customer is entitled to know where
    their own application stands; that is the whole reason `pending_approval` is a signed-in
    state (`IDENTITY_AND_AUTHORIZATION.md` section 4).
    """

    account_reference: str
    status: str
    email_verified: bool
    csrf_token: str


class AccountMeResponse(AccountModel):
    """The pending-account status page, and nothing more.

    Eight fields, every one about the caller's own account. **No customer data and no
    shipment data**, because in Phase 9 there is no link to read and nothing to read through
    it -- and because a verified identity is still pending, which is exactly the state this
    response exists to describe.

    ``linked`` is always ``False`` in Phase 9: linking is a staff act and staff approval is
    Phase 10 (OD-24). It is present rather than omitted so the shape does not change when
    Phase 10 makes it possible for it to be true.
    """

    account_reference: str
    status: str
    email_verified: bool
    #: Whether an approved link to a canonical customer exists. Always False in Phase 9.
    linked: bool
    #: Whether this account may see shipment history. Always False in Phase 9: no route
    #: serves shipment data at all, and this says so rather than implying a screen exists.
    shipment_history_available: bool
    preferred_language: str
    #: A short code a screen turns into a sentence -- never prose about the person, and
    #: never a reason that describes another record (`STATE_MACHINES.md` section 1).
    status_reason_code: str | None
    #: Whether a pending customer-data proposal is waiting for review. A boolean, not the
    #: proposal: reading a proposal back is profile surface, which Phase 9 does not build.
    has_pending_proposal: bool


class AccountErrorResponse(AccountModel):
    """Every failure on this surface: three keys, and the same three every time.

    Narrower than the staff error body, which also carries ``detail`` -- a missing
    permission, a retry-after count. None of that belongs here: a value in the body that
    differs between two failures is one more thing that tells them apart, which is what
    DEC-0051 established for Public Tracking and what T-17 asks for here.

    ``field`` is kept rather than dropped, because `STATE_MACHINES.md` section 2 requires
    field-level validation errors for **format** and forbids them for **existence**. A
    registration form whose errors named no field would be a form nobody could fill in.
    It is set only by checks that perform no lookup, so it cannot vary by account, and it
    is present and null on every other failure so the shape does not move.
    """

    code: str
    message: str
    field: str | None
