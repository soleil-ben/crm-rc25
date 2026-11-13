"""Demo and UAT identities must not be usable in production.

Two independent refusals, tested separately because each has to hold on its own:

1. `app.main._refuse_demo_accounts_in_production` refuses to *start* when a production
   database holds an active account on a reserved domain;
2. `auth_service.authenticate` refuses to authenticate one even if the process is running.

The second exists because the first can be bypassed by a database that changed after
startup, and the first exists because the second would otherwise leave known-password
accounts sitting in production until somebody tried them.

The threat is not a hostile seed -- `app.seed` already refuses to run in production. It is
the ordinary path: a database seeded in development, then copied, promoted, or restored
into production, arriving with five accounts whose password is printed in the seed output.
"""

from __future__ import annotations

import pytest

from app.core.demo_identity import is_reserved_demo_email
from app.services import auth_service
from app.services.errors import AuthenticationError

#: The password `app.seed` prints and the documentation records. That it is public is the
#: whole reason these refusals exist.
SEED_PASSWORD = "SolarisDemo!2026"

#: A password belonging to a real account, to prove the refusals are scoped to the address
#: and not to the credential.
REAL_PASSWORD = "NotADemoPass!99"


def demo_user(db, email: str, role: str, password: str = SEED_PASSWORD):
    return auth_service.create_user(
        db,
        email=email,
        full_name=f"UAT {role.replace('_', ' ').title()}",
        password=password,
        role=role,
    )


class TestReservedDemoAddresses:
    @pytest.mark.parametrize(
        "email",
        [
            "admin@demo.example.com",  # every address the seed creates
            "cs@demo.example.com",
            "ops@demo.example.com",
            "marketing@demo.example.com",
            "manager@demo.example.com",
            "someone@example.com",
            "someone@example.net",
            "someone@example.org",
            "someone@uat.example.com",
            "someone@deeply.nested.example.com",
            "ADMIN@DEMO.EXAMPLE.COM",  # case is not a way around it
            "  admin@demo.example.com  ",
            "tester@solaris.invalid",
            "tester@solaris.test",
            "tester@anything.example",
            "tester@localhost",
            "tester@box.localhost",
        ],
    )
    def test_reserved_addresses_are_recognised(self, email):
        assert is_reserved_demo_email(email) is True

    @pytest.mark.parametrize(
        "email",
        [
            "tuan@solarisexpress.ca",
            "staff@soleiltransportation.com",
            "someone@example.company.ca",  # a real domain that merely starts with "example"
            "someone@notexample.com",
            "someone@examples.com",
            "someone@example.com.attacker.net",  # the reserved name is not the domain here
            "someone@testing.ca",
            "someone@invalidate.co",
        ],
    )
    def test_real_addresses_are_not_caught(self, email):
        """A rule that refused a real member of staff would be worse than no rule."""
        assert is_reserved_demo_email(email) is False

    @pytest.mark.parametrize("email", ["", None, "no-at-sign", "trailing@", "   "])
    def test_malformed_addresses_are_not_demo_identities(self, email):
        """Malformed is a validation problem, not a silent authentication refusal."""
        assert is_reserved_demo_email(email) is False


class TestLoginRefusal:
    def test_a_demo_account_cannot_sign_in_in_production(self, db, monkeypatch):
        demo_user(db, "admin@demo.example.com", "admin")
        monkeypatch.setattr(auth_service.settings, "environment", "production")

        with pytest.raises(AuthenticationError):
            auth_service.authenticate(
                db,
                email="admin@demo.example.com",
                password="SolarisDemo!2026",
                ip_address="203.0.113.9",
                user_agent="pytest",
            )

    def test_the_refusal_is_indistinguishable_from_a_wrong_password(self, db, monkeypatch):
        """Otherwise production confirms which seeded accounts survived the copy."""
        demo_user(db, "admin@demo.example.com", "admin")
        monkeypatch.setattr(auth_service.settings, "environment", "production")

        with pytest.raises(AuthenticationError) as refused:
            auth_service.authenticate(
                db,
                email="admin@demo.example.com",
                password="SolarisDemo!2026",
                ip_address="203.0.113.9",
                user_agent="pytest",
            )
        with pytest.raises(AuthenticationError) as absent:
            auth_service.authenticate(
                db,
                email="nobody@demo.example.com",
                password="whatever",
                ip_address="203.0.113.10",
                user_agent="pytest",
            )

        assert str(refused.value) == str(absent.value) == auth_service.GENERIC_LOGIN_FAILURE

    def test_the_same_account_signs_in_normally_outside_production(self, db):
        """The refusal is scoped to production; UAT itself has to be able to sign in."""
        demo_user(db, "admin@demo.example.com", "admin")

        user, session_token, csrf_token = auth_service.authenticate(
            db,
            email="admin@demo.example.com",
            password="SolarisDemo!2026",
            ip_address="127.0.0.1",
            user_agent="pytest",
        )
        assert user.email == "admin@demo.example.com"
        assert session_token and csrf_token

    def test_a_real_account_still_signs_in_in_production(self, db, monkeypatch):
        demo_user(db, "tuan@solarisexpress.ca", "admin", password=REAL_PASSWORD)
        monkeypatch.setattr(auth_service.settings, "environment", "production")

        user, _, _ = auth_service.authenticate(
            db,
            email="tuan@solarisexpress.ca",
            password="NotADemoPass!99",
            ip_address="203.0.113.11",
            user_agent="pytest",
        )
        assert user.email == "tuan@solarisexpress.ca"


class TestStartupRefusal:
    def test_startup_refuses_while_a_demo_account_is_active(self, db, monkeypatch):
        from app import main

        demo_user(db, "ops@demo.example.com", "operations")
        monkeypatch.setattr(main.settings, "environment", "production")

        with pytest.raises(RuntimeError) as refused:
            main._refuse_demo_accounts_in_production(db)

        message = str(refused.value)
        assert "Refusing to start" in message
        assert "ops@demo.example.com" in message, "the operator needs the list to act on"

    def test_a_deactivated_demo_account_does_not_block_startup(self, db, monkeypatch):
        """`is_active = false` already refuses the login, and keeping the row is legitimate."""
        from app import main

        user = demo_user(db, "ops@demo.example.com", "operations")
        auth_service.set_user_active(db, user, is_active=False)
        db.flush()
        monkeypatch.setattr(main.settings, "environment", "production")

        main._refuse_demo_accounts_in_production(db)

    def test_startup_is_silent_outside_production(self, db, monkeypatch):
        from app import main

        demo_user(db, "admin@demo.example.com", "admin")
        monkeypatch.setattr(main.settings, "environment", "development")

        main._refuse_demo_accounts_in_production(db)

    def test_a_production_database_of_real_accounts_starts(self, db, monkeypatch):
        from app import main

        demo_user(db, "tuan@solarisexpress.ca", "admin", password=REAL_PASSWORD)
        monkeypatch.setattr(main.settings, "environment", "production")

        main._refuse_demo_accounts_in_production(db)
