"""The email seam, and the two implementations that exist behind it.

**No provider is selected, no provider is integrated, and nothing in this module sends
email** (OD-34, DEC-0094). This is a seam with a development capture behind it, which is the
honest shape: a seam that *implies* something behind it is not. The application never names
a provider, exactly as `integration_health` reports `not_configured` rather than naming a
carrier.

What a caller may hand this service is a **template key** and a bounded parameter map --
never a rendered body, never HTML from a request. The catalogue lives in this repository and
the caller names a key, the same discipline the public update templates already follow. A
caller that could pass a body would be a caller that could be made to send anything.

Three transports, selected by `ACCOUNT_EMAIL_TRANSPORT`, and the set is closed:

``null``
    Records that a send was requested and produces nothing. The default, and the default in
    tests, so a test that wants to read a message opts into the capture explicitly.
``capture``
    Writes the message to a local directory and appends it to an in-process list.
    **Opens no socket.** Development and UAT only; refused at startup in production.
``production``
    **Not implemented.** Selecting it fails at startup rather than falling back to
    something that looks like it worked.

There is deliberately no value meaning "production if configured, capture otherwise". A
silent fallback is how a deployment ends up writing verification links to a directory while
customers wait for mail that was never sent.

**Nothing here is reachable over HTTP.** A route that returned captured mail would be a way
to read any account's verification link, which is why the capture is a filesystem artefact
and why `tests/test_account_email_capture.py` walks the whole route table to prove no
endpoint exposes it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.core.config import (
    TRANSPORT_CAPTURE,
    TRANSPORT_NULL,
    TRANSPORT_PRODUCTION,
    settings,
)
from app.core.time_utils import utcnow

# --- The message catalogue ---------------------------------------------------
#
# `EMAIL_DELIVERY.md` section 3. English here; Vietnamese in `TEMPLATES_VI` below (OD-71,
# superseding OD-39's English-only release 1). Every message obeys the
# same rules: no credential and no password; no token except the single-use link the message
# exists to deliver; no customer data beyond what the recipient already provided -- no
# shipment list, no linked-customer name, no history count; nothing that confirms whether a
# *different* address exists; and no remote image, tracking pixel or third-party asset.

#: Sent on registration and on resend. Carries the one link this message exists to deliver.
TEMPLATE_VERIFY_EMAIL = "account.verify_email"
#: Sent when somebody registers an address that **already has an account**. Says an attempt
#: was made and offers a reset. **No account details**, because the person reading it may
#: not be the person who typed the address.
TEMPLATE_REGISTRATION_ATTEMPT_NOTICE = "account.registration_attempt_notice"
TEMPLATE_PASSWORD_RESET = "account.password_reset"
#: Notice only. No link, no credentials.
TEMPLATE_PASSWORD_CHANGED = "account.password_changed"
#: Sent when staff approve an account (Phase 10). Says the account is usable, and nothing
#: else: no customer id, no linked-customer name, no shipment count, no staff name and no
#: duplicate result. A message is forwarded, and read by people who were not party to the
#: decision.
TEMPLATE_ACCOUNT_APPROVED = "account.approved"
#: Sent when staff decline an application (Phase 10). Neutral, and carrying **no reason** --
#: a reason that said "duplicate of an existing customer" would confirm that an existing
#: customer exists (`STATE_MACHINES.md` section 1, transition 5).
TEMPLATE_ACCOUNT_REJECTED = "account.rejected"


def hours_phrase(hours: int) -> str:
    """ "1 hour", "24 hours". The link lifetime as the message states it.

    A phrase rather than a bare number since the reset link's lifetime became one hour
    (DEC-0121): "expires in 1 hours" is the kind of slip that makes a genuine message read
    like a phishing one.
    """
    return "1 hour" if hours == 1 else f"{hours} hours"


@dataclass(frozen=True)
class _Template:
    subject: str
    #: ``{placeholder}`` names this template accepts. A parameter outside the set is a
    #: programming error and is refused, so a caller cannot smuggle a value into a message
    #: by inventing a key.
    parameters: frozenset[str]
    body: str


#: The whole catalogue, in the repository, reviewed as copy. Plain text; a minimal HTML part
#: is a later frontend-phase concern and is deliberately not invented here.
TEMPLATES: dict[str, _Template] = {
    TEMPLATE_VERIFY_EMAIL: _Template(
        subject="Confirm your Solaris Express account",
        parameters=frozenset({"verification_url", "expires_after"}),
        body=(
            "Someone asked to create a Solaris Express account with this address.\n\n"
            "Confirm it here:\n{verification_url}\n\n"
            "The link works once and expires in {expires_after}.\n\n"
            "If this was not you, you do not need to do anything. The account stays "
            "unconfirmed and nobody can use it.\n"
        ),
    ),
    TEMPLATE_REGISTRATION_ATTEMPT_NOTICE: _Template(
        subject="Someone tried to register with your Solaris Express address",
        parameters=frozenset({"reset_url"}),
        body=(
            "Someone tried to create a Solaris Express account with this address, and an "
            "account already exists for it.\n\n"
            "If that was you and you have forgotten your password, you can set a new one "
            "here:\n{reset_url}\n\n"
            "If it was not you, nothing has changed and no action is needed.\n"
        ),
    ),
    TEMPLATE_PASSWORD_RESET: _Template(
        subject="Set a new Solaris Express password",
        parameters=frozenset({"reset_url", "expires_after"}),
        body=(
            "Someone asked to reset the password for this Solaris Express account.\n\n"
            "Set a new one here:\n{reset_url}\n\n"
            "The link works once and expires in {expires_after}.\n\n"
            "If this was not you, your password has not changed and you can ignore this "
            "message.\n"
        ),
    ),
    TEMPLATE_PASSWORD_CHANGED: _Template(
        subject="Your Solaris Express password was changed",
        parameters=frozenset(),
        body=(
            "The password for this Solaris Express account was changed, and every signed-in "
            "session was ended.\n\n"
            "If you did not do this, contact Solaris Express.\n"
        ),
    ),
    TEMPLATE_ACCOUNT_APPROVED: _Template(
        subject="Your Solaris Express account is ready",
        parameters=frozenset({"sign_in_url"}),
        body=(
            "Your Solaris Express account has been reviewed and is now active.\n\n"
            "Sign in here:\n{sign_in_url}\n\n"
            "If you did not ask for an account, contact Solaris Express.\n"
        ),
    ),
    TEMPLATE_ACCOUNT_REJECTED: _Template(
        subject="About your Solaris Express account request",
        parameters=frozenset(),
        body=(
            "We have reviewed your request for a Solaris Express account and are not able "
            "to set one up.\n\n"
            "You can still track a shipment with its tracking reference, and you are "
            "welcome to contact Solaris Express if you think this is wrong.\n"
        ),
    ),
}


# --- Vietnamese (OD-71) and milestone notifications (OD-72), Phase 13F -------------------
#
# The Customer Account is Vietnamese first. An account message whose language is ``vi`` is
# written from this catalogue; any other language uses the English one above. The wording is
# a working translation awaiting review by Vietnamese-speaking staff, like the staff catalogue.

TEMPLATES_VI: dict[str, _Template] = {
    TEMPLATE_VERIFY_EMAIL: _Template(
        subject="Xác nhận tài khoản Solaris Express của bạn",
        parameters=frozenset({"verification_url", "expires_after"}),
        body=(
            "Có người đã yêu cầu tạo tài khoản Solaris Express bằng địa chỉ email này.\n\n"
            "Xác nhận tại đây:\n{verification_url}\n\n"
            "Đường dẫn chỉ dùng được một lần và hết hạn sau {expires_after}.\n\n"
            "Nếu không phải bạn, bạn không cần làm gì. Tài khoản sẽ không được xác nhận và "
            "không ai dùng được.\n"
        ),
    ),
    TEMPLATE_REGISTRATION_ATTEMPT_NOTICE: _Template(
        subject="Có người thử đăng ký Solaris Express bằng địa chỉ email của bạn",
        parameters=frozenset({"reset_url"}),
        body=(
            "Có người đã thử tạo tài khoản Solaris Express bằng địa chỉ này, nhưng địa chỉ "
            "này đã có tài khoản.\n\n"
            "Nếu đó là bạn và bạn quên mật khẩu, bạn có thể đặt mật khẩu mới tại đây:\n"
            "{reset_url}\n\n"
            "Nếu không phải bạn, không có gì thay đổi và bạn không cần làm gì.\n"
        ),
    ),
    TEMPLATE_PASSWORD_RESET: _Template(
        subject="Đặt mật khẩu Solaris Express mới",
        parameters=frozenset({"reset_url", "expires_after"}),
        body=(
            "Có người đã yêu cầu đặt lại mật khẩu cho tài khoản Solaris Express này.\n\n"
            "Đặt mật khẩu mới tại đây:\n{reset_url}\n\n"
            "Đường dẫn chỉ dùng được một lần và hết hạn sau {expires_after}.\n\n"
            "Nếu không phải bạn, mật khẩu của bạn không thay đổi và bạn có thể bỏ qua thư này.\n"
        ),
    ),
    TEMPLATE_PASSWORD_CHANGED: _Template(
        subject="Mật khẩu Solaris Express của bạn đã được thay đổi",
        parameters=frozenset(),
        body=(
            "Mật khẩu của tài khoản Solaris Express này đã được thay đổi và mọi phiên đăng "
            "nhập đã kết thúc.\n\n"
            "Nếu không phải bạn làm việc này, hãy liên hệ Solaris Express.\n"
        ),
    ),
    TEMPLATE_ACCOUNT_APPROVED: _Template(
        subject="Tài khoản Solaris Express của bạn đã sẵn sàng",
        parameters=frozenset({"sign_in_url"}),
        body=(
            "Tài khoản Solaris Express của bạn đã được xem xét và đang hoạt động.\n\n"
            "Đăng nhập tại đây:\n{sign_in_url}\n\n"
            "Nếu bạn không yêu cầu tài khoản, hãy liên hệ Solaris Express.\n"
        ),
    ),
    TEMPLATE_ACCOUNT_REJECTED: _Template(
        subject="Về yêu cầu tài khoản Solaris Express của bạn",
        parameters=frozenset(),
        body=(
            "Chúng tôi đã xem xét yêu cầu tài khoản Solaris Express của bạn và chưa thể tạo "
            "tài khoản.\n\n"
            "Bạn vẫn có thể theo dõi lô hàng bằng mã theo dõi, và có thể liên hệ Solaris "
            "Express nếu bạn nghĩ có nhầm lẫn.\n"
        ),
    ),
}

#: Milestone notifications (OD-72). Parameters: the shipment reference and its public
#: tracking link -- nothing else about the shipment, its contents, its price or its master.
_MILESTONE_PARAMETERS = frozenset({"shipment_reference", "tracking_url"})
_MILESTONE_COPY = {
    ("received", "en"): (
        "We have received your shipment {shipment_reference}",
        "Solaris Express has received your shipment {shipment_reference} in Vietnam.",
    ),
    ("in_transit", "en"): (
        "Your shipment {shipment_reference} is on its way",
        "Your shipment {shipment_reference} has left Vietnam and is on its way to Canada.",
    ),
    ("out_for_delivery", "en"): (
        "Your shipment {shipment_reference} is out for delivery",
        "Your shipment {shipment_reference} is out for delivery.",
    ),
    ("delivered", "en"): (
        "Your shipment {shipment_reference} has been delivered",
        "Your shipment {shipment_reference} has been delivered.",
    ),
    ("received", "vi"): (
        "Chúng tôi đã nhận lô hàng {shipment_reference} của bạn",
        "Solaris Express đã nhận lô hàng {shipment_reference} của bạn tại Việt Nam.",
    ),
    ("in_transit", "vi"): (
        "Lô hàng {shipment_reference} của bạn đang trên đường",
        "Lô hàng {shipment_reference} của bạn đã rời Việt Nam và đang trên đường đến Canada.",
    ),
    ("out_for_delivery", "vi"): (
        "Lô hàng {shipment_reference} của bạn đang được giao",
        "Lô hàng {shipment_reference} của bạn đang được giao.",
    ),
    ("delivered", "vi"): (
        "Lô hàng {shipment_reference} của bạn đã được giao",
        "Lô hàng {shipment_reference} của bạn đã được giao.",
    ),
}
_MILESTONE_FOOTER = {
    "en": (
        "\n\nTrack it here:\n{tracking_url}\n\n"
        "You receive this because milestone updates are on for your shipments. Reply or "
        "contact Solaris Express to stop them, or turn each one off in your Solaris Express "
        "account if you have one.\n"
    ),
    "vi": (
        "\n\nTheo dõi tại đây:\n{tracking_url}\n\n"
        "Bạn nhận thư này vì thông báo theo mốc đang bật cho lô hàng của bạn. Hãy trả lời hoặc "
        "liên hệ Solaris Express để ngừng nhận, hoặc tắt từng thông báo trong tài khoản Solaris "
        "Express nếu bạn có tài khoản.\n"
    ),
}
for (_milestone, _language), (_subject, _lead) in _MILESTONE_COPY.items():
    TEMPLATES[f"notify.{_milestone}.{_language}"] = _Template(
        subject=_subject,
        parameters=_MILESTONE_PARAMETERS,
        body=_lead + _MILESTONE_FOOTER[_language],
    )


#: Quote sent (Phase 13G, OD-77). Parameters: the shipment reference and the link to the
#: Customer Account's quotes page -- **no amount**, no rate, no line: the figures are read
#: in the account, behind sign-in, where the customer accepts or declines.
_QUOTE_PARAMETERS = frozenset({"shipment_reference", "account_url"})
_QUOTE_COPY = {
    "en": (
        "Your Solaris Express quote for {shipment_reference} is ready",
        "Solaris Express has prepared the quote for your shipment {shipment_reference}.\n\n"
        "Sign in to your Solaris Express account to read it and to accept or decline it:\n"
        "{account_url}\n\n"
        "If you do not have an account or did not expect this message, contact Solaris "
        "Express.\n",
    ),
    "vi": (
        "Báo giá Solaris Express cho lô hàng {shipment_reference} đã sẵn sàng",
        "Solaris Express đã chuẩn bị báo giá cho lô hàng {shipment_reference} của bạn.\n\n"
        "Đăng nhập vào tài khoản Solaris Express để xem báo giá và chấp nhận hoặc từ chối:\n"
        "{account_url}\n\n"
        "Nếu bạn chưa có tài khoản hoặc không mong đợi thư này, hãy liên hệ Solaris Express.\n",
    ),
}
for _language, (_subject, _body) in _QUOTE_COPY.items():
    TEMPLATES[f"quote.sent.{_language}"] = _Template(
        subject=_subject, parameters=_QUOTE_PARAMETERS, body=_body
    )


#: Invoice sent (owner decision 9a, 2026-10-21): staff sent the invoice prepared when the
#: customer accepted the quote. Parameters: the invoice number, the total and the due date
#: only -- no line, no service name, never a vendor name.
_INVOICE_PARAMETERS = frozenset({"invoice_number", "total", "due_date"})
_INVOICE_COPY = {
    "en": (
        "Your Solaris Express invoice {invoice_number}",
        "Solaris Express has issued invoice {invoice_number} for your shipment.\n\n"
        "Total: {total}\nDue date: {due_date}\n\n"
        "If you have a question about this invoice, reply to this message or contact "
        "Solaris Express.\n",
    ),
    "vi": (
        "Hóa đơn Solaris Express {invoice_number} của bạn",
        "Solaris Express đã lập hóa đơn {invoice_number} cho lô hàng của bạn.\n\n"
        "Tổng cộng: {total}\nHạn thanh toán: {due_date}\n\n"
        "Nếu bạn có câu hỏi về hóa đơn này, hãy trả lời thư này hoặc liên hệ Solaris "
        "Express.\n",
    ),
}
for _language, (_subject, _body) in _INVOICE_COPY.items():
    TEMPLATES[f"invoice.sent.{_language}"] = _Template(
        subject=_subject, parameters=_INVOICE_PARAMETERS, body=_body
    )


#: RC-UAT-21 Phase B (DEC-0231): self-service password and email change, and an Admin
#: reinstating a deactivated account. Account-security email: never suppressed, never carries
#: a password; the change-confirmation link is the only token, and the notice to the old
#: address names neither address.
TEMPLATE_PASSWORD_CHANGED_HERE = "account.password_changed_here"
TEMPLATE_EMAIL_CHANGE_CONFIRM = "account.email_change_confirm"
TEMPLATE_EMAIL_CHANGED_NOTICE = "account.email_changed_notice"
#: Sent to the **current** address when a change is requested (review HIGH 1). No token.
TEMPLATE_EMAIL_CHANGE_REQUESTED = "account.email_change_requested"
TEMPLATE_ACCOUNT_REINSTATED = "account.reinstated"
#: RC-UAT-25 item 2 (Ben, 2026-10-25): an Admin changed the sign-in email; sent to the **new**
#: address with the sign-in link. The old address gets ``TEMPLATE_EMAIL_CHANGED_NOTICE``.
TEMPLATE_SIGN_IN_EMAIL_SET_BY_STAFF = "account.sign_in_email_set_by_staff"

TEMPLATES.update(
    {
        TEMPLATE_PASSWORD_CHANGED_HERE: _Template(
            subject="Your Solaris Express password was changed",
            parameters=frozenset(),
            body=(
                "The password for this Solaris Express account was changed from a signed-in "
                "session. Every other signed-in session was ended.\n\n"
                "If you did not do this, reset your password straight away and contact "
                "Solaris Express.\n"
            ),
        ),
        TEMPLATE_EMAIL_CHANGE_CONFIRM: _Template(
            subject="Confirm your new Solaris Express sign-in email",
            parameters=frozenset({"confirm_url", "expires_after"}),
            body=(
                "Someone asked to use this address as the sign-in email of a Solaris Express "
                "account.\n\n"
                "Confirm it here:\n{confirm_url}\n\n"
                "The link works once and expires in {expires_after}. Until it is used, the "
                "account keeps its current email.\n\n"
                "If this was not you, you do not need to do anything.\n"
            ),
        ),
        TEMPLATE_EMAIL_CHANGE_REQUESTED: _Template(
            subject="Someone asked to change your Solaris Express sign-in email",
            parameters=frozenset(),
            body=(
                "Someone signed in to your Solaris Express account asked to change its "
                "sign-in email to a different address. Nothing changes until a link sent to "
                "that address is used.\n\n"
                "If this was not you, change your password straight away: that cancels the "
                "request and signs out every other session. Then contact Solaris Express.\n"
            ),
        ),
        TEMPLATE_EMAIL_CHANGED_NOTICE: _Template(
            subject="Your Solaris Express sign-in email was changed",
            parameters=frozenset(),
            body=(
                "The sign-in email of your Solaris Express account was changed to a new "
                "address, and this address is no longer used for the account.\n\n"
                "If you did not do this, contact Solaris Express straight away.\n"
            ),
        ),
        TEMPLATE_SIGN_IN_EMAIL_SET_BY_STAFF: _Template(
            subject="This is now your Solaris Express sign-in email",
            parameters=frozenset({"sign_in_url"}),
            body=(
                "Solaris Express has made this address the sign-in email of your Solaris "
                "Express account. Your password is unchanged; every signed-in session was "
                "ended.\n\n"
                "Sign in with this address here:\n{sign_in_url}\n\n"
                "If you did not ask for this, contact Solaris Express straight away.\n"
            ),
        ),
        TEMPLATE_ACCOUNT_REINSTATED: _Template(
            subject="Your Solaris Express account is available again",
            parameters=frozenset({"sign_in_url"}),
            body=(
                "Solaris Express has reinstated your account.\n\n"
                "Sign in again here:\n{sign_in_url}\n\n"
                "If you did not expect this, contact Solaris Express.\n"
            ),
        ),
    }
)
TEMPLATES_VI.update(
    {
        TEMPLATE_PASSWORD_CHANGED_HERE: _Template(
            subject="Mật khẩu Solaris Express của bạn đã được thay đổi",
            parameters=frozenset(),
            body=(
                "Mật khẩu của tài khoản Solaris Express này đã được thay đổi từ một phiên đang "
                "đăng nhập. Mọi phiên đăng nhập khác đã kết thúc.\n\n"
                "Nếu không phải bạn làm việc này, hãy đặt lại mật khẩu ngay và liên hệ Solaris "
                "Express.\n"
            ),
        ),
        TEMPLATE_EMAIL_CHANGE_CONFIRM: _Template(
            subject="Xác nhận email đăng nhập mới cho Solaris Express",
            parameters=frozenset({"confirm_url", "expires_after"}),
            body=(
                "Có người đã yêu cầu dùng địa chỉ này làm email đăng nhập của một tài khoản "
                "Solaris Express.\n\n"
                "Xác nhận tại đây:\n{confirm_url}\n\n"
                "Đường dẫn chỉ dùng được một lần và hết hạn sau {expires_after}. Cho đến khi "
                "được xác nhận, tài khoản vẫn dùng email hiện tại.\n\n"
                "Nếu không phải bạn, bạn không cần làm gì.\n"
            ),
        ),
        TEMPLATE_EMAIL_CHANGE_REQUESTED: _Template(
            subject="Có người yêu cầu đổi email đăng nhập Solaris Express của bạn",
            parameters=frozenset(),
            body=(
                "Một người đang đăng nhập vào tài khoản Solaris Express của bạn đã yêu cầu đổi "
                "email đăng nhập sang một địa chỉ khác. Không có gì thay đổi cho đến khi đường "
                "dẫn gửi đến địa chỉ đó được dùng.\n\n"
                "Nếu không phải bạn, hãy đổi mật khẩu ngay: việc này hủy yêu cầu và đăng xuất "
                "mọi phiên khác. Sau đó hãy liên hệ Solaris Express.\n"
            ),
        ),
        TEMPLATE_EMAIL_CHANGED_NOTICE: _Template(
            subject="Email đăng nhập Solaris Express của bạn đã được thay đổi",
            parameters=frozenset(),
            body=(
                "Email đăng nhập của tài khoản Solaris Express của bạn đã được đổi sang một địa "
                "chỉ mới, và địa chỉ này không còn được dùng cho tài khoản.\n\n"
                "Nếu không phải bạn làm việc này, hãy liên hệ Solaris Express ngay.\n"
            ),
        ),
        TEMPLATE_SIGN_IN_EMAIL_SET_BY_STAFF: _Template(
            subject="Đây là email đăng nhập Solaris Express mới của bạn",
            parameters=frozenset({"sign_in_url"}),
            body=(
                "Solaris Express đã đặt địa chỉ này làm email đăng nhập cho tài khoản Solaris "
                "Express của bạn. Mật khẩu của bạn không thay đổi; mọi phiên đăng nhập đã kết "
                "thúc.\n\n"
                "Hãy đăng nhập bằng địa chỉ này tại đây:\n{sign_in_url}\n\n"
                "Nếu bạn không yêu cầu việc này, hãy liên hệ Solaris Express ngay.\n"
            ),
        ),
        TEMPLATE_ACCOUNT_REINSTATED: _Template(
            subject="Tài khoản Solaris Express của bạn đã được mở lại",
            parameters=frozenset({"sign_in_url"}),
            body=(
                "Solaris Express đã mở lại tài khoản của bạn.\n\n"
                "Hãy đăng nhập lại tại đây:\n{sign_in_url}\n\n"
                "Nếu bạn không mong đợi điều này, hãy liên hệ Solaris Express.\n"
            ),
        ),
    }
)


def _template_for(key: str, language: str) -> _Template:
    """The Vietnamese account template for ``vi``, else the catalogue's own."""
    if language == "vi" and key in TEMPLATES_VI:
        return TEMPLATES_VI[key]
    return TEMPLATES[key]


@dataclass(frozen=True)
class OutboundEmail:
    """A message to be sent: a recipient, a template key, a language, bounded parameters.

    Never a rendered body assembled by a caller, and never raw HTML from a request.
    """

    to_email: str
    template_key: str
    language: str
    parameters: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        template = TEMPLATES.get(self.template_key)
        if template is None:
            raise ValueError(f"Unknown template key: {self.template_key!r}")
        unexpected = set(self.parameters) - template.parameters
        if unexpected:
            raise ValueError(
                f"{self.template_key} does not accept {sorted(unexpected)}; "
                f"it accepts {sorted(template.parameters)}"
            )
        missing = template.parameters - set(self.parameters)
        if missing:
            raise ValueError(f"{self.template_key} requires {sorted(missing)}")

    @property
    def subject(self) -> str:
        return _template_for(self.template_key, self.language).subject.format(**self.parameters)

    def render(self) -> str:
        return _template_for(self.template_key, self.language).body.format(**self.parameters)


@dataclass(frozen=True)
class EmailSendResult:
    """What happened, in terms a log may carry. No address, no body, no token."""

    template_key: str
    transport: str
    delivered: bool
    #: A vocabulary token when something stopped the send, else None.
    reason_code: str | None = None


class EmailTransport(Protocol):
    def send(self, message: OutboundEmail) -> EmailSendResult: ...


class NullEmailTransport:
    """Records that a send was requested and produces nothing.

    The default everywhere, including tests. A test that wants to assert on a message opts
    into the capture explicitly, so the ordinary suite cannot accidentally depend on a
    message existing anywhere.
    """

    name = TRANSPORT_NULL

    def __init__(self) -> None:
        #: Template keys only. Deliberately not the messages: a list of rendered bodies
        #: living in the default transport would be a capture by another name.
        self.requested: list[str] = []

    def send(self, message: OutboundEmail) -> EmailSendResult:
        self.requested.append(message.template_key)
        return EmailSendResult(
            template_key=message.template_key, transport=self.name, delivered=False
        )


#: Characters allowed in a capture filename. Everything else in the address is replaced, so
#: a crafted address cannot escape the capture directory or collide with a path device name.
_FILENAME_SAFE = re.compile(r"[^a-z0-9._-]+")

#: Runs of dots, collapsed to one. The separator substitution above already stops a
#: traversal -- the slashes are gone and the name is joined onto the capture directory --
#: but ``..`` surviving in a filename is the kind of thing that stops being harmless the
#: moment somebody passes the name to a different API. Collapsed rather than stripped, so a
#: legitimate ``first.last@example.com`` still reads as itself.
_DOT_RUNS = re.compile(r"\.{2,}")


class CaptureEmailTransport:
    """Writes the message to a local directory. **Opens no socket.**

    The captured body contains the verification or reset link in plaintext, because the
    message is the link. That is precisely why this transport never ships, never runs in
    production, and has no HTTP endpoint: an endpoint returning captured mail would be a way
    to read anybody's account-recovery credential (`EMAIL_DELIVERY.md` section 2).

    Files land under the git-ignored development data directory, are cleared by the UAT
    reset script like the rest of that environment, and are never committed.
    """

    name = TRANSPORT_CAPTURE

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else settings.account_email_capture_path
        #: In-process mirror, so a test can read the last message without touching the
        #: filesystem. Bounded, because an unbounded list in a long-running process is a
        #: slow way to keep every verification link ever issued in memory.
        self.messages: list[dict[str, str]] = []

    #: Ceiling on the in-memory mirror. The files on disk are the durable record.
    MAX_IN_MEMORY = 200

    def send(self, message: OutboundEmail) -> EmailSendResult:
        captured = {
            "captured_at": utcnow().isoformat(),
            "to_email": message.to_email,
            "subject": message.subject,
            "template_key": message.template_key,
            "language": message.language,
            "body": message.render(),
        }
        self.messages.append(captured)
        del self.messages[: max(0, len(self.messages) - self.MAX_IN_MEMORY)]
        self._write(captured)
        return EmailSendResult(
            template_key=message.template_key, transport=self.name, delivered=True
        )

    #: Longest name this transport will produce, in characters.
    #:
    #: Windows refuses a path over 260 characters unless long-path support is enabled, and
    #: ``mkdir`` succeeding says nothing about whether a *file* inside it can be created --
    #: the failure arrives as a bare ``FileNotFoundError`` naming a directory that plainly
    #: exists, which reads like a missing folder and is not one.
    #:
    #: This repository sits 151 characters deep inside a OneDrive business folder, and an
    #: E2E run adds ``data/e2e/<8 hex>/mail/`` for another 24 -- leaving **85**. With the
    #: address slice at its original 60 characters, a captured
    #: ``account.registration_attempt_notice`` came to 268 and the registration route
    #: answered 500 with "Something went wrong". Found by the Phase 12 browser suite
    #: (`PROJECT_STATUS.md` §27).
    #:
    #: Three things were shortened to reach 77, which fits: a two-digit year in the stamp,
    #: the redundant ``account.`` prefix dropped from the template key (every key in this
    #: catalogue has it), and the address slice cut to 24.
    MAX_FILENAME_LENGTH = 77

    #: Every template key starts with this, so repeating it in the filename spends eight
    #: characters saying nothing.
    _KEY_PREFIX = "account."

    def _write(self, captured: dict[str, str]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        # `%y` rather than `%Y`: two characters, and a capture directory is not an archive
        # -- the UAT reset clears it, and a run's directory holds one run.
        stamp = datetime.fromisoformat(captured["captured_at"]).strftime("%y%m%dT%H%M%S%f")
        key = captured["template_key"].removeprefix(self._KEY_PREFIX)
        # Twenty-four characters of address: enough to tell which message is which when
        # reading the directory by hand. A collision would need two addresses sharing
        # their first twenty-four sanitized characters *and* the same microsecond.
        safe = _DOT_RUNS.sub(".", _FILENAME_SAFE.sub("_", captured["to_email"].lower()))[:24]
        path = self.directory / f"{stamp}-{key}-{safe}.json"
        # The microsecond stamp usually separates two messages; under load (two suites on one
        # machine) it has not, and the second file silently replaced the first. A counter
        # suffix keeps both: a capture directory must hold every message that was sent.
        counter = 1
        while path.exists():
            counter += 1
            path = self.directory / f"{stamp}-{key}-{safe}-{counter}.json"
        path.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        """Forget everything captured. Used by test fixtures.

        The UAT reset clears the same directory, but from `scripts/uat_env.py` and in a
        separate process -- it runs when the backend is stopped, so it deletes the files
        rather than calling this.
        """
        self.messages.clear()
        if self.directory.exists():
            for path in self.directory.glob("*.json"):
                path.unlink()


class ProductionTransportNotConfigured(RuntimeError):
    """Raised when the production transport is selected, because none is written.

    Deliberately an exception rather than a stub that discards messages. OD-34 has selected
    no provider, and a stub would mean the first production deployment silently dropped
    every verification link.
    """


def build_transport(name: str | None = None) -> EmailTransport:
    """The transport this configuration selects. No fallback, in either direction."""
    selected = (name or settings.account_email_transport).strip().lower()
    if selected == TRANSPORT_NULL:
        return NullEmailTransport()
    if selected == TRANSPORT_CAPTURE:
        return CaptureEmailTransport()
    if selected == TRANSPORT_PRODUCTION:
        raise ProductionTransportNotConfigured(
            "No production email transport is implemented. OD-34 has selected no provider "
            "and production launch of customer registration is blocked until the owner "
            "selects one using verified documentation, with data residency confirmed, the "
            "sending domain authenticated, and bounce and complaint handling defined."
        )
    raise ValueError(f"Unknown email transport: {selected!r}")


_transport: EmailTransport | None = None


def get_transport() -> EmailTransport:
    """The process-wide transport, built once.

    Built lazily rather than at import so that a test can select a transport by patching the
    settings and calling `reset_transport`, and so that importing this module never creates
    a capture directory in an environment that will not use one.
    """
    global _transport
    if _transport is None:
        _transport = build_transport()
    return _transport


def set_transport(transport: EmailTransport | None) -> None:
    """Install a transport explicitly. For tests and for the UAT environment script."""
    global _transport
    _transport = transport


def reset_transport() -> None:
    set_transport(None)


def send(message: OutboundEmail) -> EmailSendResult:
    """Hand a message to the configured transport.

    The caller is responsible for having checked the delivery blockers first; this function
    does not second-guess it, because a second check in a second place is how two different
    answers to "may we contact this address" come to exist. Every template here is account
    email, which a marketing suppression does not block (owner decision, 2026-10-15). The
    same holds for shipment and other operational email when it is built: a suppression
    blocks marketing email only (owner decision, 2026-10-16), so nothing on this path reads
    ``contact_suppressions``.
    """
    return get_transport().send(message)
