"""The email seam: no provider, no socket, no endpoint, and no silent fallback.

OD-34 selects no provider, so the interesting assertions here are all negative. The three
that matter:

* **No socket is opened on the mail path.** Asserted by replacing `socket.socket` with one
  that raises, then running a full registration and reset cycle. A test that merely checked
  "we did not import requests" would pass while a provider adapter used `http.client`.
* **No HTTP route returns captured mail.** A route that did would be a way to read anybody's
  verification link, which is precisely why the capture is a filesystem artefact.
* **Production refuses rather than falls back.** Selecting the capture transport in
  production fails at startup; selecting the production transport fails at startup because
  none is written; and with neither configured, registration, resend and reset refuse at the
  route while the rest of the application still serves.

The last of those is the shape of OD-34 as a control rather than a note: registration cannot
launch, and nothing about the default configuration quietly makes it look like it has.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

import pytest

from app.core import config as config_module
from app.core.config import (
    TRANSPORT_CAPTURE,
    TRANSPORT_NULL,
    TRANSPORT_PRODUCTION,
    UNAPPROVED_VERSION_PREFIX,
    Settings,
    account_delivery_blockers,
    account_registration_blockers,
    email_transport_problems,
    settings,
)
from app.services import account_email_service as email
from tests.account_fixtures import (
    ACCOUNT_PASSWORD,
    register,
    registered_and_verified,
    registration,
    reset_token,
)

ADDRESS = "hanh@demo.example.com"
REGISTER = "/api/v1/account/register"
RESEND = "/api/v1/account/verification/resend"
FORGOT = "/api/v1/account/password/forgot"
RESET = "/api/v1/account/password/reset"


def _production(**overrides) -> Settings:
    """A settings object that would pass the production gate but for what is overridden."""
    base = {
        "environment": "production",
        "secret_key": "x" * 48,
        "cookie_secure": True,
        "allow_demo_seed": False,
        "debug": False,
        "cors_origins": "https://crm.example.com",
        "tracking_base_url": "https://track.example.com/track",
    }
    base.update(overrides)
    return Settings(**base)


# --- No socket ----------------------------------------------------------------


def test_no_socket_is_opened_on_the_mail_path(
    account_client, account_db, captured_mail, monkeypatch
):
    """T-15, asserted at the level a provider adapter would have to use.

    `socket.socket` is the floor under `requests`, `httpx`, `smtplib` and `http.client`
    alike, so replacing it catches an outbound attempt whatever library made it.
    """
    opened: list[tuple] = []

    class Refusing(socket.socket):
        def __init__(self, *args, **kwargs):
            opened.append(args)
            raise AssertionError("the mail path opened a socket")

    monkeypatch.setattr(socket, "socket", Refusing)

    register(account_client, email=ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    account_client.post(RESEND, json={"email": ADDRESS})

    assert opened == []
    assert captured_mail.messages


def test_the_null_transport_opens_nothing_and_keeps_nothing(monkeypatch):
    transport = email.NullEmailTransport()
    message = email.OutboundEmail(
        to_email=ADDRESS,
        template_key=email.TEMPLATE_VERIFY_EMAIL,
        language="en",
        parameters={"verification_url": "https://x/y?token=abc", "expires_after": "24 hours"},
    )
    result = transport.send(message)

    assert result.delivered is False
    assert transport.requested == [email.TEMPLATE_VERIFY_EMAIL]
    # Template keys only -- a list of rendered bodies here would be a capture by another name.
    assert not hasattr(transport, "messages")


# --- The capture is a file, not an endpoint -----------------------------------


def test_the_capture_writes_to_a_local_directory(tmp_path):
    transport = email.CaptureEmailTransport(tmp_path / "mail")
    transport.send(
        email.OutboundEmail(
            to_email=ADDRESS,
            template_key=email.TEMPLATE_VERIFY_EMAIL,
            language="en",
            parameters={"verification_url": "https://x/y?token=abc", "expires_after": "24 hours"},
        )
    )
    files = list((tmp_path / "mail").glob("*.json"))
    assert len(files) == 1
    written = json.loads(files[0].read_text(encoding="utf-8"))
    assert written["to_email"] == ADDRESS
    assert written["template_key"] == email.TEMPLATE_VERIFY_EMAIL
    assert "token=abc" in written["body"]


def test_a_crafted_address_cannot_escape_the_capture_directory(tmp_path):
    """The filename is derived from the address, so the address is sanitized."""
    transport = email.CaptureEmailTransport(tmp_path / "mail")
    transport.send(
        email.OutboundEmail(
            to_email="../../../etc/passwd@evil.example",
            template_key=email.TEMPLATE_PASSWORD_CHANGED,
            language="en",
            parameters={},
        )
    )
    files = list((tmp_path / "mail").glob("*.json"))
    assert len(files) == 1
    assert files[0].parent == tmp_path / "mail"
    assert ".." not in files[0].name


def test_the_filename_stays_within_the_path_budget(tmp_path):
    """A name long enough to break Windows is a 500 on the registration route.

    The failure does not look like a path problem: `mkdir` succeeds, the directory is
    plainly there, and `open` answers ``FileNotFoundError``. This repository sits 151
    characters deep, an E2E run adds another 24, and with the address slice at its old
    sixty characters a captured ``account.registration_attempt_notice`` came to 268 --
    eight past the limit. Found by the Phase 12 browser suite, twice, as a generic
    "Something went wrong" on a registration form.

    The longest name the transport can produce is asserted against its own declared
    bound, using the longest template key and an address well past the slice.
    """
    transport = email.CaptureEmailTransport(tmp_path / "mail")
    longest_key = max(email.TEMPLATES, key=len)
    transport.send(
        email.OutboundEmail(
            to_email="a-deliberately-very-long-local-part-indeed@a-long-domain.example.com",
            template_key=longest_key,
            language="en",
            parameters=dict.fromkeys(email.TEMPLATES[longest_key].parameters, "x"),
        )
    )
    written = list((tmp_path / "mail").glob("*.json"))
    assert len(written) == 1
    assert len(written[0].name) <= transport.MAX_FILENAME_LENGTH, written[0].name


def test_every_template_key_fits_the_budget():
    """The bound is computed from the longest key, so a longer key must move it."""
    transport = email.CaptureEmailTransport
    stamp = len("260921T144908541973")
    separators = 2
    address = 24
    suffix = len(".json")
    longest_key = max(len(key.removeprefix(transport._KEY_PREFIX)) for key in email.TEMPLATES)
    worst = stamp + separators + longest_key + address + suffix
    assert worst <= transport.MAX_FILENAME_LENGTH, (
        "a template key grew past the filename budget. Either shorten the key or raise "
        "MAX_FILENAME_LENGTH deliberately, having checked it against the deepest "
        "directory this transport writes into."
    )


def test_the_whole_path_fits_the_windows_limit_from_this_repository():
    """The bound is not abstract: it is measured against where the files actually go.

    Both destinations are checked -- the development capture directory and the deepest an
    E2E run reaches -- because the number that matters is the *path*, and a bound that
    fits one and not the other would pass here and fail in a run.
    """
    from app.core import e2e_guard

    transport = email.CaptureEmailTransport
    deepest_e2e = e2e_guard.E2E_DIR / "12345678" / "mail"
    development = e2e_guard.REPO_ROOT / "data" / "account_mail"

    for directory in (deepest_e2e, development):
        longest = len(str(directory)) + 1 + transport.MAX_FILENAME_LENGTH
        assert longest <= 260, (
            f"{directory} plus a longest-case capture filename is {longest} characters, "
            "past the Windows limit. Shorten MAX_FILENAME_LENGTH."
        )


def test_two_addresses_sharing_a_prefix_do_not_collide(tmp_path):
    """The slice is twenty-four characters, so the stamp separates them -- and when two sends
    share a microsecond, which happens under load, a counter suffix does (DEC-0183)."""
    transport = email.CaptureEmailTransport(tmp_path / "mail")
    for local in ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-one", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-two"):
        transport.send(
            email.OutboundEmail(
                to_email=f"{local}@example.com",
                template_key=email.TEMPLATE_PASSWORD_CHANGED,
                language="en",
                parameters={},
            )
        )
    assert len(list((tmp_path / "mail").glob("*.json"))) == 2


def test_two_captures_in_the_same_microsecond_both_survive(tmp_path, monkeypatch):
    """Deterministic version of the collision the full suite met under load: the stamp is
    pinned, so only the counter suffix can keep the second file."""
    transport = email.CaptureEmailTransport(tmp_path / "mail")
    fixed = datetime(2026, 10, 19, 12, 0, 0, 123456)
    monkeypatch.setattr(email, "utcnow", lambda: fixed)
    for _ in range(3):
        transport.send(
            email.OutboundEmail(
                to_email="same@example.com",
                template_key=email.TEMPLATE_PASSWORD_CHANGED,
                language="en",
                parameters={},
            )
        )
    names = sorted(p.name for p in (tmp_path / "mail").glob("*.json"))
    assert len(names) == 3
    assert sum(n.endswith("-2.json") for n in names) == 1
    assert sum(n.endswith("-3.json") for n in names) == 1


def test_the_in_memory_mirror_is_bounded(tmp_path):
    """An unbounded list would keep every verification link ever issued in memory."""
    transport = email.CaptureEmailTransport(tmp_path / "mail")
    for _ in range(transport.MAX_IN_MEMORY + 25):
        transport.send(
            email.OutboundEmail(
                to_email=ADDRESS,
                template_key=email.TEMPLATE_PASSWORD_CHANGED,
                language="en",
                parameters={},
            )
        )
    assert len(transport.messages) == transport.MAX_IN_MEMORY


def test_no_http_route_returns_captured_mail(account_client, account_db, captured_mail):
    """AC-CA-9.4. A route that did would be a way to read anybody's recovery link."""
    from tests.test_account_boundary import _all_routes

    paths = [path for path, _ in _all_routes()]
    assert paths
    # Compared segment by segment rather than as a substring: `/account/verify-email` is a
    # route that *sends* mail, which is fine, while a segment literally named `mail` or
    # `outbox` would be a route that serves it.
    forbidden_segments = {"mail", "mails", "outbox", "inbox", "capture", "captures", "messages"}
    for path in paths:
        segments = {segment.lower() for segment in path.split("/") if segment}
        assert not (segments & forbidden_segments), path

    # And the obvious guesses are simply not there.
    for guess in (
        "/api/v1/account/mail",
        "/api/v1/account/messages",
        "/api/v1/account/outbox",
        "/api/v1/mail",
        "/api/v1/public/mail",
    ):
        assert account_client.get(guess).status_code == 404


def test_the_capture_directory_is_outside_the_source_tree_and_git_ignored():
    """`EMAIL_DELIVERY.md` section 2: under the development data directory, never committed."""
    from app.core.config import BACKEND_ROOT, REPO_ROOT

    path = settings.account_email_capture_path.resolve()
    assert (BACKEND_ROOT / "app").resolve() not in path.parents
    assert path.is_relative_to(REPO_ROOT.resolve())

    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    # `data/` is ignored at any depth, which is what covers the capture directory.
    assert "data/" in ignore


def test_no_captured_message_holds_a_password_or_a_hash(account_client, account_db, captured_mail):
    registered_and_verified(account_client, captured_mail, ADDRESS)
    account_client.post(FORGOT, json={"email": ADDRESS})
    account_client.post(
        RESET,
        json={
            "token": reset_token(captured_mail, ADDRESS),
            "password": "Replacement!2026",
            "password_confirmation": "Replacement!2026",
        },
    )

    from app.models import CustomerIdentity

    account_db.expire_all()
    identity = account_db.query(CustomerIdentity).filter_by(email_normalized=ADDRESS).one()

    assert captured_mail.messages
    for message in captured_mail.messages:
        body = message["body"]
        assert ACCOUNT_PASSWORD not in body
        assert "Replacement!2026" not in body
        assert identity.password_hash not in body
        assert "$argon2" not in body
        # At most one secret: the single-use link the message exists to carry.
        assert body.count("token=") <= 1


def test_a_message_carries_no_customer_data_beyond_what_was_provided(
    account_client, account_db, captured_mail
):
    """`EMAIL_DELIVERY.md` section 3: no shipment list, no linked-customer name, no count."""
    registered_and_verified(account_client, captured_mail, ADDRESS)
    for message in captured_mail.messages:
        body = message["body"]
        assert "STCA-" not in body
        assert "SX-" not in body
        assert "shipment" not in body.lower()


def test_a_caller_cannot_supply_a_rendered_body():
    """The caller names a template key and passes bounded parameters, never a body."""
    with pytest.raises(ValueError, match="does not accept"):
        email.OutboundEmail(
            to_email=ADDRESS,
            template_key=email.TEMPLATE_PASSWORD_CHANGED,
            language="en",
            parameters={"body": "<script>alert(1)</script>"},
        )
    with pytest.raises(ValueError, match="Unknown template key"):
        email.OutboundEmail(
            to_email=ADDRESS, template_key="account.anything", language="en", parameters={}
        )


def test_no_template_contains_a_remote_asset_or_tracking_pixel():
    for key, template in email.TEMPLATES.items():
        body = template.body.lower()
        assert "<img" not in body, key
        assert "http://" not in body.replace("{verification_url}", "").replace("{reset_url}", ""), (
            key
        )


# --- Transport selection ------------------------------------------------------


def test_the_default_transport_is_the_null_one():
    assert settings.account_email_transport == TRANSPORT_NULL
    assert isinstance(email.build_transport(TRANSPORT_NULL), email.NullEmailTransport)


def test_selecting_the_production_transport_raises_because_none_is_written():
    with pytest.raises(email.ProductionTransportNotConfigured):
        email.build_transport(TRANSPORT_PRODUCTION)


def test_an_unknown_transport_name_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="Unknown email transport"):
        email.build_transport("smtp")


def test_there_is_no_provider_adapter_anywhere_in_the_mail_path():
    """OD-34: no provider is named, so no provider can be selected by implementation."""
    source = Path(email.__file__).read_text(encoding="utf-8").lower()
    for provider in ("sendgrid", "mailgun", "postmark", "ses", "smtplib", "graph", "mailchimp"):
        # Named only in the prose that explains why none is integrated.
        assert f"import {provider}" not in source
        assert f"{provider}." not in source.replace("mailgun, ", "")


def test_no_module_in_the_application_imports_an_email_provider_library():
    import app

    root = Path(app.__file__).parent
    banned = ("smtplib", "sendgrid", "mailgun", "postmark", "boto3", "aiosmtplib")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            if f"import {name}" in text:
                offenders.append((path.name, name))
    assert offenders == []


# --- Startup refusals ---------------------------------------------------------


def test_production_refuses_to_start_with_the_capture_transport():
    """AC-CA-9.5: no silent fallback, and no accidental use of the development capture."""
    problems = email_transport_problems(_production(account_email_transport=TRANSPORT_CAPTURE))
    assert problems
    assert any("capture" in problem for problem in problems)


def test_any_environment_refuses_to_start_with_the_production_transport():
    """Because nothing is behind it. A stub would drop every verification link silently."""
    for environment in ("development", "test", "production"):
        overrides = {"account_email_transport": TRANSPORT_PRODUCTION}
        candidate = (
            _production(**overrides)
            if environment == "production"
            else Settings(environment=environment, **overrides)
        )
        problems = email_transport_problems(candidate)
        assert problems, environment
        assert any("not implemented" in problem for problem in problems), environment


def test_an_unrecognized_transport_name_refuses_at_startup():
    problems = email_transport_problems(Settings(account_email_transport="sendgrid"))
    assert problems
    assert any("not one of" in problem for problem in problems)


def test_the_default_configuration_starts_cleanly():
    """The refusals must not be so broad that development cannot run."""
    assert email_transport_problems(Settings()) == []


def test_get_settings_applies_the_transport_gate(monkeypatch):
    """The gate is wired into startup, not merely available as a function."""
    monkeypatch.setenv("ACCOUNT_EMAIL_TRANSPORT", TRANSPORT_PRODUCTION)
    config_module.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="email transport"):
            config_module.get_settings()
    finally:
        monkeypatch.delenv("ACCOUNT_EMAIL_TRANSPORT", raising=False)
        config_module.get_settings.cache_clear()


# --- Route-level refusals (OD-34, OD-37) --------------------------------------


def test_production_without_a_provider_blocks_delivery_but_not_the_application():
    production = _production()
    assert account_delivery_blockers(production) == ["email_provider_not_selected"]
    # The rest of the configuration is fine: the Staff Portal and Public Tracking still run.
    assert config_module.production_configuration_problems(production) == []


def test_development_has_no_delivery_blockers():
    assert account_delivery_blockers(Settings()) == []
    assert account_registration_blockers(Settings()) == []


# --- The CA-REG-09 rehearsal: the production gate, outside production ----------


def test_the_rehearsal_is_off_unless_asked_for():
    assert Settings().account_rehearse_no_email_provider is False


def test_the_rehearsal_reproduces_the_production_delivery_blocker(monkeypatch):
    """The same code production returns, so the same refusal at the same three routes."""
    monkeypatch.setenv("ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER", "true")
    rehearsal = Settings()
    assert rehearsal.is_production is False
    assert account_delivery_blockers(rehearsal) == account_delivery_blockers(_production())
    assert account_registration_blockers(rehearsal) == ["email_provider_not_selected"]
    # It is a startable configuration with any transport: the gate is the point, not a
    # startup failure.
    for transport in (TRANSPORT_NULL, TRANSPORT_CAPTURE):
        assert email_transport_problems(Settings(account_email_transport=transport)) == []


def test_the_rehearsal_can_close_registration_but_never_open_it():
    assert account_delivery_blockers(_production(account_rehearse_no_email_provider=False)) == [
        "email_provider_not_selected"
    ]
    assert account_delivery_blockers(_production(account_rehearse_no_email_provider=True)) == [
        "email_provider_not_selected"
    ]


def test_under_the_rehearsal_registration_shows_the_closed_answer_and_writes_nothing(
    account_client, account_db, captured_mail, monkeypatch
):
    """CA-REG-09 as a tester meets it, without a production configuration."""
    from app.api.account.routes import UNAVAILABLE_MESSAGE
    from app.models import CustomerIdentity

    monkeypatch.setattr(settings, "account_rehearse_no_email_provider", True)

    response = register(account_client, email=ADDRESS)
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "account_unavailable"
    assert body["message"] == UNAVAILABLE_MESSAGE
    # No setting, provider, transport, version or decision identifier reaches a stranger.
    for leak in ("rehearse", "transport", "provider", "capture", "OD-", "DEC-", "version"):
        assert leak.lower() not in body["message"].lower()

    assert account_db.query(CustomerIdentity).count() == 0
    assert captured_mail.messages == []
    for path in (RESEND, FORGOT):
        assert account_client.post(path, json={"email": ADDRESS}).status_code == 503


def test_under_the_rehearsal_an_existing_customer_can_still_sign_in(
    account_client, account_db, captured_mail, monkeypatch
):
    from tests.account_fixtures import sign_in

    registered_and_verified(account_client, captured_mail, ADDRESS)
    monkeypatch.setattr(settings, "account_rehearse_no_email_provider", True)
    assert sign_in(account_client, ADDRESS).status_code == 200


def test_production_registration_is_also_blocked_by_the_terms_placeholder():
    """OD-37: approved legal text and version identifiers are an owner action."""
    with_provider = _production(account_email_transport=TRANSPORT_PRODUCTION)
    blockers = account_registration_blockers(with_provider)
    assert "terms_version_not_approved" in blockers

    fully_ready = _production(
        account_email_transport=TRANSPORT_PRODUCTION,
        account_terms_version="terms-2026-11-01",
        account_privacy_version="privacy-2026-11-01",
    )
    assert account_registration_blockers(fully_ready) == []


def test_the_shipped_terms_versions_are_marked_placeholders():
    """So nobody can mistake the default for approved text."""
    assert settings.account_terms_version.startswith(UNAPPROVED_VERSION_PREFIX)
    assert settings.account_privacy_version.startswith(UNAPPROVED_VERSION_PREFIX)


@pytest.mark.parametrize(
    "path,body",
    [
        (REGISTER, None),
        (RESEND, {"email": ADDRESS}),
        (FORGOT, {"email": ADDRESS}),
    ],
)
def test_the_routes_refuse_while_delivery_is_blocked(
    account_client, account_db, monkeypatch, path, body
):
    """AC-CA-12.3, exercised over HTTP rather than asserted about the helper."""
    from app.api.account import routes as account_routes

    monkeypatch.setattr(
        account_routes, "account_delivery_blockers", lambda _: ["email_provider_not_selected"]
    )
    monkeypatch.setattr(
        account_routes,
        "account_registration_blockers",
        lambda _: ["email_provider_not_selected"],
    )

    response = account_client.post(path, json=body if body is not None else registration())
    assert response.status_code == 503
    assert response.json()["code"] == "account_unavailable"
    # The body says nothing about why: the reason is a deployment internal.
    assert "provider" not in response.json()["message"].lower()
    assert "email" not in response.json()["message"].lower()


def test_the_staff_and_public_surfaces_still_work_while_registration_is_blocked(
    account_client, account_db, account_users, monkeypatch
):
    """Blocking the whole application over a surface that has not launched would be wrong."""
    from app.api.account import routes as account_routes
    from tests.conftest import TEST_PASSWORD

    monkeypatch.setattr(
        account_routes, "account_registration_blockers", lambda _: ["email_provider_not_selected"]
    )

    assert account_client.post(REGISTER, json=registration()).status_code == 503

    staff = account_client.post(
        "/api/v1/auth/login",
        json={"email": account_users["admin"].email, "password": TEST_PASSWORD},
    )
    assert staff.status_code == 200

    public = account_client.get("/api/v1/public/track/SX-CAV-7K9D2M4R8T6W")
    assert public.status_code == 404
    assert public.json()["code"] == "tracking_not_found"


def test_sign_in_still_works_while_delivery_is_blocked(
    account_client, account_db, captured_mail, monkeypatch
):
    """Delivery gates the paths that send mail. An existing customer can still sign in."""
    from app.api.account import routes as account_routes
    from tests.account_fixtures import sign_in

    registered_and_verified(account_client, captured_mail, ADDRESS)
    monkeypatch.setattr(
        account_routes, "account_delivery_blockers", lambda _: ["email_provider_not_selected"]
    )
    assert sign_in(account_client, ADDRESS).status_code == 200
